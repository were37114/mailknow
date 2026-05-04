"""Email processing pipeline: new email → Gate → classify → store.

End-to-end pipeline that orchestrates:
1. Email ingestion (from IMAP sync)
2. Gate classification (5-level routing)
3. Self-wiring link extraction (Tier1 + Tier2)
4. Storage to GBrain (pages + links + entities)
"""

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core.gate.classifier import EmailInfo, GateClassifier, GateResult
from core.gate.models import GateClass
from core.wiring.models import Link, LinkRelation, LinkTier
from core.wiring.tier1_extractor import Tier1Extractor
from core.wiring.tier2_extractor import Tier2Extractor
from db.pgpool import SQLitePool
from sync.config import AccountConfig
from sync.models import Email

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Result of processing a single email through the pipeline."""
    email_id: str
    gate_class: str
    gate_confidence: float
    links_extracted: int
    entities_created: int
    processing_time_ms: float
    error: Optional[str] = None


@dataclass
class PipelineStats:
    """Pipeline execution statistics."""
    total_processed: int = 0
    by_gate: Dict[str, int] = field(default_factory=dict)
    total_links: int = 0
    total_entities: int = 0
    errors: int = 0
    total_time_ms: float = 0.0

    @property
    def avg_time_ms(self) -> float:
        if self.total_processed == 0:
            return 0.0
        return self.total_time_ms / self.total_processed


class EmailPipeline:
    """Email processing pipeline.

    Flow:
    1. Receive email from sync
    2. Gate classify → 5-level routing
    3. Extract links (Tier1 headers + Tier2 content)
    4. Store to GBrain (pages + links + entities)

    Performance target: end-to-end < 100ms per email
    """

    def __init__(
        self,
        db: SQLitePool,
        gate_classifier: Optional[GateClassifier] = None,
        tier1_extractor: Optional[Tier1Extractor] = None,
        tier2_extractor: Optional[Tier2Extractor] = None,
    ):
        """Initialize pipeline.

        Args:
            db: Database pool
            gate_classifier: Gate classifier (created if not provided)
            tier1_extractor: Tier1 link extractor
            tier2_extractor: Tier2 link extractor
        """
        self.db = db
        self.gate_classifier = gate_classifier or GateClassifier()
        self.tier1_extractor = tier1_extractor or Tier1Extractor()
        self.tier2_extractor = tier2_extractor or Tier2Extractor()
        self._stats = PipelineStats()

    @property
    def stats(self) -> PipelineStats:
        """Get pipeline statistics."""
        return self._stats

    async def process_email(
        self,
        email: Email,
        account_id: str = "",
        folder: str = "INBOX",
        uid: int = 0,
    ) -> PipelineResult:
        """Process a single email through the pipeline.

        Args:
            email: Email to process
            account_id: Source account ID
            folder: Source IMAP folder
            uid: IMAP UID

        Returns:
            PipelineResult with processing details
        """
        start_time = _now_ms()

        try:
            # Step 1: Compute page ID (must match Tier1/Tier2 extractor format)
            # Also compute a content_hash for dedup tracking
            content_hash = hashlib.sha256(
                f"{account_id}:{uid}:{email.message_id}".encode()
            ).hexdigest()[:32]

            if email.message_id:
                page_id = f"email:{email.message_id.strip('<>')}"
            else:
                page_id = f"email:generated:{content_hash[:16]}"

            # Step 2: Gate classification
            email_info = EmailInfo(
                subject=email.subject or "",
                from_addr=email.from_addr.address if email.from_addr else "",
                to_addrs=[a.address for a in email.to_addrs],
                cc_addrs=[a.address for a in email.cc_addrs],
                content=email.text_body or "",
                has_attachments=len(email.attachments) > 0,
            )
            gate_result = self.gate_classifier.classify(email_info)

            # Step 3: Store page to GBrain
            conn = await self.db.get_connection()

            metadata = {
                "account_id": account_id,
                "uid": uid,
                "folder": folder,
                "message_id": email.message_id,
                "from_name": email.from_addr.name if email.from_addr else None,
                "from_addr": email.from_addr.address if email.from_addr else None,
                "to_addrs": [str(a) for a in email.to_addrs],
                "cc_addrs": [str(a) for a in email.cc_addrs],
                "date": email.date.isoformat() if email.date else None,
                "in_reply_to": email.in_reply_to,
                "references": email.references,
                "has_attachments": len(email.attachments) > 0,
                "content_hash": content_hash,
                "gate_matched_rules": gate_result.matched_rules,
            }

            # Check if already exists
            cursor = await conn.execute(
                "SELECT id FROM pages WHERE id = ?", (page_id,)
            )
            existing = await cursor.fetchone()

            if existing:
                # Update gate class only
                await conn.execute(
                    "UPDATE pages SET gate_class = ?, gate_score = ?, updated_at = ? WHERE id = ?",
                    (gate_result.gate_class.value, gate_result.confidence, _now_iso(), page_id)
                )
            else:
                # Insert new page
                await conn.execute(
                    """INSERT INTO pages
                       (id, type, content, metadata, gate_class, gate_score, created_at, updated_at)
                       VALUES (?, 'email', ?, ?, ?, ?, ?, ?)""",
                    (
                        page_id,
                        email.subject or "",
                        json.dumps(metadata, ensure_ascii=False, default=str),
                        gate_result.gate_class.value,
                        gate_result.confidence,
                        _now_iso(),
                        _now_iso(),
                    )
                )

            await conn.commit()

            # Step 4: Extract links
            all_links: List[Link] = []

            # Tier1: Header-based links
            try:
                tier1_links = self.tier1_extractor.extract(email)
                all_links.extend(tier1_links)
            except Exception as e:
                logger.warning(f"Tier1 extraction failed for {page_id}: {e}")

            # Tier2: Content-based links (skip spam/notifications)
            if gate_result.gate_class not in (GateClass.SPAM,):
                try:
                    tier2_links = self.tier2_extractor.extract(email)
                    all_links.extend(tier2_links)
                except Exception as e:
                    logger.warning(f"Tier2 extraction failed for {page_id}: {e}")

            # Step 5: Collect ALL unique targets and create stub pages for FK
            # links table has FK: source_id→pages, target_id→pages
            # So every target that doesn't exist yet needs a stub page
            stub_targets = set()
            entities_to_create = set()
            for link in all_links:
                # source_id is always the current page (already exists), skip
                target = link.target_id
                if not target:
                    continue
                # Person targets → also create entities
                if target.startswith("person:"):
                    entities_to_create.add(target)
                    stub_targets.add(target)
                # Email targets (reply-to, references) → stub pages
                elif target.startswith("email:"):
                    stub_targets.add(target)
                # URL/project targets → stub pages
                elif target.startswith(("url:", "project:")):
                    stub_targets.add(target)

            # Create stub pages for all targets (FK constraint requires them)
            for target_id in stub_targets:
                try:
                    name = target_id.split(":", 1)[1] if ":" in target_id else target_id
                    page_type = target_id.split(":", 1)[0] if ":" in target_id else "unknown"
                    await conn.execute(
                        """INSERT OR IGNORE INTO pages
                           (id, type, content, metadata, created_at, updated_at)
                           VALUES (?, ?, ?, '{}', ?, ?)""",
                        (target_id, page_type, name, _now_iso(), _now_iso())
                    )
                except Exception as e:
                    logger.warning(f"Failed to create stub page for {target_id}: {e}")

            # Step 6: Store links to GBrain
            link_count = 0
            for link in all_links:
                try:
                    # Generate link ID from source+target+relation
                    link_id = hashlib.sha256(
                        f"{link.source_id}:{link.target_id}:{link.relation.value if hasattr(link.relation, 'value') else link.relation}".encode()
                    ).hexdigest()[:24]

                    # tier is INTEGER in schema
                    tier_val = link.tier.value if hasattr(link.tier, 'value') else link.tier
                    if isinstance(tier_val, str):
                        tier_map = {"tier1": 1, "tier2": 2, "tier4": 4}
                        tier_val = tier_map.get(tier_val, int(tier_val) if tier_val.isdigit() else 1)

                    # target_id: must reference pages or be NULL
                    target_id = link.target_id if link.target_id else None

                    await conn.execute(
                        """INSERT OR IGNORE INTO links
                           (id, source_id, target_id, relation, tier, weight, metadata, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            link_id,
                            link.source_id,
                            target_id,
                            link.relation.value if hasattr(link.relation, 'value') else link.relation,
                            tier_val,
                            link.weight,
                            json.dumps({}, ensure_ascii=False),
                            _now_iso(),
                        )
                    )
                    link_count += 1
                except Exception as e:
                    logger.warning(f"Failed to store link: {e}")

            # Step 7: Create entities from links (uses attributes, not metadata)
            entities_created = 0
            for entity_id in entities_to_create:
                try:
                    name = entity_id.split(":", 1)[1] if ":" in entity_id else entity_id
                    await conn.execute(
                        """INSERT OR IGNORE INTO entities
                           (id, type, name, attributes, created_at, updated_at)
                           VALUES (?, 'person', ?, ?, ?, ?)""",
                        (
                            entity_id,
                            name,
                            json.dumps({"source": "wiring"}, ensure_ascii=False),
                            _now_iso(),
                            _now_iso(),
                        )
                    )
                    entities_created += 1
                except Exception as e:
                    logger.warning(f"Failed to create entity {entity_id}: {e}")

            await conn.commit()

            # Update stats
            processing_time = _now_ms() - start_time
            self._stats.total_processed += 1
            self._stats.by_gate[gate_result.gate_class.value] = \
                self._stats.by_gate.get(gate_result.gate_class.value, 0) + 1
            self._stats.total_links += len(all_links)
            self._stats.total_entities += entities_created
            self._stats.total_time_ms += processing_time

            return PipelineResult(
                email_id=page_id,
                gate_class=gate_result.gate_class.value,
                gate_confidence=gate_result.confidence,
                links_extracted=len(all_links),
                entities_created=entities_created,
                processing_time_ms=processing_time,
            )

        except Exception as e:
            self._stats.errors += 1
            logger.error(f"Pipeline error for email: {e}")
            return PipelineResult(
                email_id="",
                gate_class="routine",
                gate_confidence=0.0,
                links_extracted=0,
                entities_created=0,
                processing_time_ms=_now_ms() - start_time,
                error=str(e),
            )

    async def process_batch(
        self,
        emails: List[Email],
        account_id: str = "",
        folder: str = "INBOX",
        start_uid: int = 0,
    ) -> List[PipelineResult]:
        """Process a batch of emails.

        Args:
            emails: List of emails to process
            account_id: Source account ID
            folder: Source IMAP folder
            start_uid: Starting UID

        Returns:
            List of PipelineResults
        """
        results = []
        for i, email in enumerate(emails):
            result = await self.process_email(
                email=email,
                account_id=account_id,
                folder=folder,
                uid=start_uid + i,
            )
            results.append(result)

        return results

    def reset_stats(self) -> None:
        """Reset pipeline statistics."""
        self._stats = PipelineStats()


def _now_ms() -> float:
    """Current time in milliseconds."""
    return datetime.now(timezone.utc).timestamp() * 1000


def _now_iso() -> str:
    """Current time in ISO format."""
    return datetime.now(timezone.utc).isoformat()
