"""Entity alignment - identity recognition + merging.

V5.2 spec:
- Nightly entity alignment job
- Identity recognition: same person with different email addresses
- Merge entities and create merge_log
- Support undo via merge_log
"""

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class MergeReason(str, Enum):
    """Reasons for entity merge."""
    SAME_EMAIL_PREFIX = "same_email_prefix"       # zhangsan@a.com + zhangsan@b.com
    SAME_DISPLAY_NAME = "same_display_name"         # 张三 <a@x.com> + 张三 <b@x.com>
    EMAIL_ALIAS = "email_alias"                     # zhangsan + zhang.san
    MANUAL = "manual"                               # User-initiated merge
    EXPLICIT_MAPPING = "explicit_mapping"           # User-provided mapping


@dataclass
class MergeRecord:
    """Record of an entity merge operation."""
    merge_id: str
    kept_entity_id: str
    merged_entity_id: str
    merged_from: List[str] = field(default_factory=list)  # All previously merged IDs
    reason: MergeReason = MergeReason.MANUAL
    confidence: float = 0.0
    merged_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Snapshot of merged entity before merge
    merged_name: str = ""
    merged_type: str = ""
    merged_attributes: Dict[str, Any] = field(default_factory=dict)

    # Undo support
    undone: bool = False
    undone_at: Optional[str] = None


@dataclass
class AlignmentResult:
    """Result of entity alignment pass."""
    total_entities: int = 0
    merge_candidates: int = 0
    merges_performed: int = 0
    merge_details: List[MergeRecord] = field(default_factory=list)
    errors: int = 0


class EntityAligner:
    """Entity alignment engine.

    Features:
    - Identity recognition via email prefix matching
    - Display name matching
    - Email alias detection
    - Merge with merge_log for undo
    - Nightly batch alignment
    """

    # Email alias patterns: zhangsan, zhang.san, zhang_san, zhangsan123
    ALIAS_PATTERN = re.compile(r'[._]')

    def __init__(self):
        self._merge_log: List[MergeRecord] = []
        self._entity_map: Dict[str, Dict[str, Any]] = {}  # entity_id → entity data
        self._merged_from: Dict[str, List[str]] = {}       # kept_id → [merged_ids]

    def load_entities(self, entities: List[Dict[str, Any]]) -> None:
        """Load entities for alignment.

        Args:
            entities: List of entity dicts with id, name, type, attributes
        """
        self._entity_map = {}
        for entity in entities:
            self._entity_map[entity["id"]] = entity
        logger.info(f"Loaded {len(entities)} entities for alignment")

    def find_merge_candidates(self) -> List[Tuple[str, str, MergeReason, float]]:
        """Find potential merge candidates.

        Returns:
            List of (entity_id_1, entity_id_2, reason, confidence) tuples
        """
        candidates = []
        entities = list(self._entity_map.values())

        # Group by type (only merge same-type entities)
        by_type: Dict[str, List[Dict[str, Any]]] = {}
        for e in entities:
            etype = e.get("type", "unknown")
            by_type.setdefault(etype, []).append(e)

        # Only align person entities for now
        for etype, type_entities in by_type.items():
            if etype != "person":
                continue

            for i, e1 in enumerate(type_entities):
                for e2 in type_entities[i + 1:]:
                    reason, confidence = self._check_merge_candidate(e1, e2)
                    if reason and confidence > 0.5:
                        candidates.append((e1["id"], e2["id"], reason, confidence))

        # Sort by confidence (highest first)
        candidates.sort(key=lambda x: -x[3])
        return candidates

    def align(self, auto_merge: bool = True, min_confidence: float = 0.8) -> AlignmentResult:
        """Run entity alignment.

        Args:
            auto_merge: Automatically merge high-confidence candidates
            min_confidence: Minimum confidence for auto-merge

        Returns:
            Alignment result
        """
        result = AlignmentResult(total_entities=len(self._entity_map))

        candidates = self.find_merge_candidates()
        result.merge_candidates = len(candidates)

        for id1, id2, reason, confidence in candidates:
            if not auto_merge or confidence < min_confidence:
                continue

            try:
                merge_record = self.merge(id1, id2, reason=reason, confidence=confidence)
                result.merges_performed += 1
                result.merge_details.append(merge_record)
            except Exception as e:
                logger.error(f"Merge failed for {id1} + {id2}: {e}")
                result.errors += 1

        logger.info(f"Alignment: {result.merge_candidates} candidates, {result.merges_performed} merged, {result.errors} errors")
        return result

    def merge(
        self,
        kept_id: str,
        merged_id: str,
        reason: MergeReason = MergeReason.MANUAL,
        confidence: float = 0.0,
    ) -> MergeRecord:
        """Merge two entities.

        Args:
            kept_id: Entity to keep
            merged_id: Entity to merge into kept
            reason: Merge reason
            confidence: Merge confidence

        Returns:
            Merge record for undo
        """
        kept = self._entity_map.get(kept_id)
        merged = self._entity_map.get(merged_id)

        if not kept:
            raise ValueError(f"Kept entity not found: {kept_id}")
        if not merged:
            raise ValueError(f"Merged entity not found: {merged_id}")

        # Create merge record
        merge_id = hashlib.sha256(
            f"{kept_id}:{merged_id}:{datetime.now(timezone.utc).isoformat()}".encode()
        ).hexdigest()[:16]

        merge_record = MergeRecord(
            merge_id=merge_id,
            kept_entity_id=kept_id,
            merged_entity_id=merged_id,
            merged_from=self._merged_from.get(merged_id, []) + [merged_id],
            reason=reason,
            confidence=confidence,
            merged_name=merged.get("name", ""),
            merged_type=merged.get("type", ""),
            merged_attributes=merged.get("attributes", {}),
        )

        # Update kept entity attributes
        kept_attrs = kept.get("attributes", {})
        merged_attrs = merged.get("attributes", {})

        # Merge email lists
        kept_emails = set(kept_attrs.get("emails", []))
        merged_emails = set(merged_attrs.get("emails", []))
        kept_attrs["emails"] = list(kept_emails | merged_emails)

        # Add alias names
        kept_names = set(kept_attrs.get("aliases", []))
        kept_names.add(merged.get("name", ""))
        kept_attrs["aliases"] = list(kept_names)

        # Update entity
        kept["attributes"] = kept_attrs

        # Track merge
        self._merged_from.setdefault(kept_id, []).append(merged_id)
        self._merge_log.append(merge_record)

        # Remove merged entity from map
        del self._entity_map[merged_id]

        logger.info(f"Merged {merged_id} → {kept_id} (reason={reason.value}, confidence={confidence:.2f})")
        return merge_record

    def undo(self, merge_id: str) -> bool:
        """Undo a merge operation.

        Args:
            merge_id: Merge record ID to undo

        Returns:
            True if undo successful
        """
        for record in reversed(self._merge_log):
            if record.merge_id == merge_id and not record.undone:
                # Restore merged entity
                restored = {
                    "id": record.merged_entity_id,
                    "name": record.merged_name,
                    "type": record.merged_type,
                    "attributes": record.merged_attributes,
                }
                self._entity_map[record.merged_entity_id] = restored

                # Remove from kept's merged_from
                if record.kept_entity_id in self._merged_from:
                    self._merged_from[record.kept_entity_id] = [
                        mid for mid in self._merged_from[record.kept_entity_id]
                        if mid != record.merged_entity_id
                    ]

                # Mark as undone
                record.undone = True
                record.undone_at = datetime.now(timezone.utc).isoformat()

                logger.info(f"Undone merge {merge_id}: restored {record.merged_entity_id}")
                return True

        logger.warning(f"Merge {merge_id} not found or already undone")
        return False

    def get_merge_log(self) -> List[MergeRecord]:
        """Get all merge records."""
        return list(self._merge_log)

    def get_entities(self) -> List[Dict[str, Any]]:
        """Get current entity map."""
        return list(self._entity_map.values())

    def _check_merge_candidate(
        self,
        e1: Dict[str, Any],
        e2: Dict[str, Any],
    ) -> Tuple[Optional[MergeReason], float]:
        """Check if two entities should be merged.

        Returns:
            (reason, confidence) or (None, 0.0)
        """
        name1 = e1.get("name", "")
        name2 = e2.get("name", "")
        attrs1 = e1.get("attributes", {})
        attrs2 = e2.get("attributes", {})

        emails1 = set(attrs1.get("emails", []))
        emails2 = set(attrs2.get("emails", []))

        # If already merged, skip
        if e2["id"] in self._merged_from.get(e1["id"], []):
            return None, 0.0
        if e1["id"] in self._merged_from.get(e2["id"], []):
            return None, 0.0

        # Check 1: Same email prefix
        prefixes1 = {self._email_prefix(e) for e in emails1}
        prefixes2 = {self._email_prefix(e) for e in emails2}
        common_prefixes = prefixes1 & prefixes2
        if common_prefixes:
            # Same prefix but different domain → likely same person
            return MergeReason.SAME_EMAIL_PREFIX, 0.85

        # Check 2: Email alias (zhangsan vs zhang.san)
        for p1 in prefixes1:
            base1 = self.ALIAS_PATTERN.sub("", p1)
            for p2 in prefixes2:
                base2 = self.ALIAS_PATTERN.sub("", p2)
                if base1 and base2 and base1 == base2 and len(base1) >= 3:
                    return MergeReason.EMAIL_ALIAS, 0.75

        # Check 3: Same display name (Chinese names need 2+ chars)
        if name1 and name2 and name1 == name2 and len(name1) >= 2:
            # Same name is weaker signal (many people share names)
            return MergeReason.SAME_DISPLAY_NAME, 0.6

        return None, 0.0

    def _email_prefix(self, email: str) -> str:
        """Extract email local part (before @)."""
        if "@" in email:
            return email.split("@")[0].lower()
        return email.lower()

    def get_stats(self) -> Dict[str, Any]:
        """Get alignment statistics."""
        return {
            "total_entities": len(self._entity_map),
            "total_merges": len(self._merge_log),
            "undone_merges": len([r for r in self._merge_log if r.undone]),
            "merged_from_map": len(self._merged_from),
        }
