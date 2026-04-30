"""Auto entity extractor - builds entities automatically from links.

When links are created by Tier1/Tier2 extractors, this module:
1. Identifies person/email/url/project targets that need entity records
2. Creates or updates entity records with accumulated attributes
3. Performs entity alignment (dedup/merge same person with different IDs)
4. Maintains compiled_truth summaries
"""

import logging
from datetime import datetime, timezone
from typing import List, Dict, Set, Optional, Tuple
from dataclasses import dataclass, field

from .models import Link, LinkRelation, LinkTier
from db.pgpool import SQLitePool

logger = logging.getLogger(__name__)


@dataclass
class EntityCandidate:
    """A candidate entity extracted from links."""
    id: str
    type: str  # person, url, project, email
    name: str
    attributes: Dict = field(default_factory=dict)
    source_link_ids: List[str] = field(default_factory=list)


@dataclass
class ExtractionResult:
    """Result of auto extraction pass."""
    entities_created: int = 0
    entities_updated: int = 0
    entities_merged: int = 0
    errors: int = 0


class AutoExtractor:
    """Automatically extract and maintain entities from links.
    
    Core logic:
    1. Scan links for targets that represent entities
    2. Create entity records if they don't exist
    3. Update entity attributes from link metadata
    4. Perform entity alignment for same-person detection
    """
    
    # Map link relations to entity types
    RELATION_ENTITY_MAP = {
        LinkRelation.SENT_BY: "person",
        LinkRelation.SENT_TO: "person",
        LinkRelation.CC_TO: "person",
        LinkRelation.MENTIONS: "person",  # could also be project
        LinkRelation.BELONGS_TO: "project",
        LinkRelation.RELATED_TO: "url",
    }
    
    # ID prefix to entity type mapping
    PREFIX_TYPE_MAP = {
        "person": "person",
        "url": "url",
        "project": "project",
        "email": "email",
    }
    
    def __init__(self, db: SQLitePool):
        """Initialize auto extractor.
        
        Args:
            db: Database pool for reading/writing entities
        """
        self.db = db
    
    async def extract_from_links(
        self,
        links: List[Link],
        page_id: str = "",
    ) -> ExtractionResult:
        """Extract entities from a list of links.
        
        Args:
            links: Links to extract entities from
            page_id: Source page ID for context
            
        Returns:
            ExtractionResult with counts
        """
        result = ExtractionResult()
        
        # Step 1: Collect entity candidates from links
        candidates = self._collect_candidates(links)
        
        if not candidates:
            return result
        
        conn = await self.db.get_connection()
        
        # Step 2: Create or update each entity
        for entity_id, candidate in candidates.items():
            try:
                created = await self._upsert_entity(conn, candidate)
                if created:
                    result.entities_created += 1
                else:
                    result.entities_updated += 1
            except Exception as e:
                logger.warning(f"Failed to upsert entity {entity_id}: {e}")
                result.errors += 1
        
        # Step 3: Entity alignment for person entities
        try:
            merged = await self._align_person_entities(conn, list(candidates.keys()))
            result.entities_merged += merged
        except Exception as e:
            logger.warning(f"Entity alignment failed: {e}")
            result.errors += 1
        
        await conn.commit()
        return result
    
    def _collect_candidates(self, links: List[Link]) -> Dict[str, EntityCandidate]:
        """Collect entity candidates from links.
        
        Returns dict of entity_id → EntityCandidate
        """
        candidates: Dict[str, EntityCandidate] = {}
        
        for link in links:
            target = link.target_id
            if not target:
                continue
            
            # Determine entity type from target ID prefix
            entity_type = self._get_entity_type(target)
            if not entity_type:
                continue
            
            # Extract name from target ID
            name = self._extract_name(target)
            
            # Build attributes from link metadata
            attrs = dict(link.metadata) if link.metadata else {}
            attrs["last_seen_relation"] = link.relation.value
            attrs["last_seen_tier"] = link.tier.value
            
            if target in candidates:
                # Merge attributes
                candidates[target].attributes.update(attrs)
                candidates[target].source_link_ids.append(link.id)
            else:
                candidates[target] = EntityCandidate(
                    id=target,
                    type=entity_type,
                    name=name,
                    attributes=attrs,
                    source_link_ids=[link.id],
                )
        
        return candidates
    
    def _get_entity_type(self, target_id: str) -> Optional[str]:
        """Get entity type from target ID prefix."""
        for prefix, etype in self.PREFIX_TYPE_MAP.items():
            if target_id.startswith(f"{prefix}:"):
                return etype
        return None
    
    def _extract_name(self, target_id: str) -> str:
        """Extract display name from target ID.
        
        Examples:
            person:zhangsan@company.com → zhangsan@company.com
            person:mentioned:张三 → 张三
            url:example.com → example.com
            project:MailKnow → MailKnow
        """
        parts = target_id.split(":", 1)
        if len(parts) < 2:
            return target_id
        
        remainder = parts[1]
        
        # For "person:mentioned:张三", extract "张三"
        if remainder.startswith("mentioned:"):
            return remainder.split(":", 1)[1]
        
        return remainder
    
    async def _upsert_entity(self, conn, candidate: EntityCandidate) -> bool:
        """Create or update an entity.
        
        Returns True if created, False if updated.
        """
        import json
        
        now = datetime.now(timezone.utc).isoformat()
        
        # Check if entity exists
        cursor = await conn.execute(
            "SELECT id, attributes FROM entities WHERE id = ?", (candidate.id,)
        )
        existing = await cursor.fetchone()
        
        if existing:
            # Merge attributes
            existing_attrs = json.loads(existing[1]) if existing[1] else {}
            # New attributes override, but don't delete existing keys
            merged = {**existing_attrs, **candidate.attributes}
            
            await conn.execute(
                """UPDATE entities 
                   SET attributes = ?, updated_at = ?
                   WHERE id = ?""",
                (json.dumps(merged, ensure_ascii=False), now, candidate.id)
            )
            return False
        else:
            await conn.execute(
                """INSERT INTO entities 
                   (id, type, name, attributes, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    candidate.id,
                    candidate.type,
                    candidate.name,
                    json.dumps(candidate.attributes, ensure_ascii=False),
                    now,
                    now,
                )
            )
            return True
    
    async def _align_person_entities(self, conn, entity_ids: List[str]) -> int:
        """Align person entities that refer to the same person.
        
        Detection rules:
        1. Same email address with different name forms → merge
        2. "mentioned:张三" + "zhangsan@company.com" if zhangsan matches → flag for review
        
        For MVP, we only auto-merge exact email matches.
        """
        import json
        
        merged_count = 0
        
        # Only process person entities
        person_ids = [eid for eid in entity_ids if eid.startswith("person:")]
        if len(person_ids) < 2:
            return 0
        
        # Extract email addresses from person IDs
        email_map: Dict[str, List[str]] = {}  # email → [entity_ids]
        for eid in person_ids:
            # person:zhangsan@company.com → extract email
            remainder = eid.split(":", 1)[1]
            # Skip "mentioned:" prefix
            if remainder.startswith("mentioned:"):
                continue
            # This is an email-based person ID
            email = remainder.lower()
            if email not in email_map:
                email_map[email] = []
            email_map[email].append(eid)
        
        # No duplicates found
        for email, ids in email_map.items():
            if len(ids) <= 1:
                continue
            
            # Merge: keep the first as canonical, point others to it
            canonical_id = ids[0]
            for alias_id in ids[1:]:
                try:
                    await conn.execute(
                        """UPDATE entities 
                           SET canonical_id = ?, updated_at = ?
                           WHERE id = ?""",
                        (canonical_id, datetime.now(timezone.utc).isoformat(), alias_id)
                    )
                    merged_count += 1
                    logger.info(f"Entity aligned: {alias_id} → {canonical_id}")
                except Exception as e:
                    logger.warning(f"Failed to align {alias_id}: {e}")
        
        return merged_count
    
    async def get_entity(self, entity_id: str) -> Optional[Dict]:
        """Get entity by ID.
        
        Returns entity dict or None.
        """
        import json
        
        conn = await self.db.get_connection()
        cursor = await conn.execute(
            "SELECT id, type, name, attributes, canonical_id, truth_summary FROM entities WHERE id = ?",
            (entity_id,)
        )
        row = await cursor.fetchone()
        
        if not row:
            return None
        
        return {
            "id": row[0],
            "type": row[1],
            "name": row[2],
            "attributes": json.loads(row[3]) if row[3] else {},
            "canonical_id": row[4],
            "truth_summary": row[5],
        }
    
    async def search_entities(
        self,
        entity_type: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """Search entities by type and/or name query.
        
        Args:
            entity_type: Filter by entity type
            query: Search in name field (LIKE)
            limit: Max results
            
        Returns:
            List of entity dicts
        """
        import json
        
        conn = await self.db.get_connection()
        
        conditions = []
        params = []
        
        if entity_type:
            conditions.append("type = ?")
            params.append(entity_type)
        
        if query:
            conditions.append("name LIKE ?")
            params.append(f"%{query}%")
        
        where = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)
        
        cursor = await conn.execute(
            f"SELECT id, type, name, attributes FROM entities WHERE {where} ORDER BY updated_at DESC LIMIT ?",
            params,
        )
        rows = await cursor.fetchall()
        
        return [
            {
                "id": r[0],
                "type": r[1],
                "name": r[2],
                "attributes": json.loads(r[3]) if r[3] else {},
            }
            for r in rows
        ]
