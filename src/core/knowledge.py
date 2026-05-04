"""Knowledge base V1 - entity + hybrid search integration.

V5.2 spec:
- "和A公司的往来邮件" can be queried
- Entity-based search + semantic search
- compiled_truth integration
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.search.hybrid import HybridSearch
from core.truth.compiler import TruthCompiler, get_truth_compiler

logger = logging.getLogger(__name__)


@dataclass
class KnowledgeResult:
    """A knowledge base query result."""
    query: str
    entity_id: Optional[str] = None
    entity_name: Optional[str] = None
    entity_summary: Optional[str] = None

    # Related emails
    emails: List[Dict[str, Any]] = field(default_factory=list)
    email_count: int = 0

    # Related entities
    related_entities: List[Dict[str, Any]] = field(default_factory=list)

    # Metadata
    search_time_ms: float = 0.0
    source: str = ""  # "entity" | "search" | "hybrid"


class KnowledgeBase:
    """Knowledge base for email queries.

    Features:
    - Entity-based query resolution
    - Hybrid search fallback
    - compiled_truth summaries
    - Multi-hop entity relationships
    """

    def __init__(
        self,
        search: Optional[HybridSearch] = None,
        truth_compiler: Optional[TruthCompiler] = None,
    ):
        self.search = search or HybridSearch()
        self.truth_compiler = truth_compiler or get_truth_compiler()

    async def query(
        self,
        query: str,
        max_emails: int = 20,
    ) -> KnowledgeResult:
        """Query the knowledge base.

        Supports queries like:
        - "和A公司的往来邮件" → entity-based search
        - "关于采购的邮件" → semantic search
        - "最近3天的重要邮件" → structured search

        Args:
            query: Natural language query
            max_emails: Maximum emails to return

        Returns:
            Knowledge result
        """
        start = datetime.now(timezone.utc)

        # Step 1: Try entity-based resolution
        entity_id = self._resolve_entity(query)

        if entity_id:
            result = await self._entity_query(entity_id, query, max_emails)
        else:
            result = await self._search_query(query, max_emails)

        result.query = query
        result.search_time_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000

        return result

    async def _entity_query(
        self,
        entity_id: str,
        query: str,
        max_emails: int,
    ) -> KnowledgeResult:
        """Query by entity."""
        result = KnowledgeResult(
            entity_id=entity_id,
            source="entity",
        )

        # Get compiled truth
        truth = self.truth_compiler.get_cached(entity_id)
        if truth:
            result.entity_name = truth.entity_name
            result.entity_summary = truth.summary

        # Search for emails related to this entity
        entity_name = truth.entity_name if truth else entity_id.split(":")[-1] if ":" in entity_id else entity_id

        # Use hybrid search with entity name
        search_results = await self.search.search(
            query=entity_name,
            limit=max_emails,
        )

        result.emails = search_results if isinstance(search_results, list) else []
        result.email_count = len(result.emails)

        return result

    async def _search_query(
        self,
        query: str,
        max_emails: int,
    ) -> KnowledgeResult:
        """Query by semantic search."""
        result = KnowledgeResult(source="search")

        search_results = await self.search.search(
            query=query,
            limit=max_emails,
        )

        result.emails = search_results if isinstance(search_results, list) else []
        result.email_count = len(result.emails)

        return result

    def _resolve_entity(self, query: str) -> Optional[str]:
        """Try to resolve a query to an entity ID.

        Patterns:
        - "和XXX的往来" → entity:XXX
        - "XXX公司的" → org:XXX
        - "与XXX相关" → person:XXX or org:XXX
        """
        import re

        # Pattern: "和XXX的往来" / "与XXX的往来"
        match = re.search(r'[和与](.+?)[的的]往来', query)
        if match:
            name = match.group(1).strip()
            if "公司" in name or "集团" in name:
                return f"org:{name}"
            return f"person:{name}"

        # Pattern: "XXX公司" / "XXX集团"
        match = re.search(r'(.+?)(公司|集团|组织)', query)
        if match:
            return f"org:{match.group(0)}"

        return None

    def get_stats(self) -> Dict[str, Any]:
        """Get knowledge base statistics."""
        return {
            "truth_compiler": self.truth_compiler.get_stats(),
        }


# Global instance
_kb: Optional[KnowledgeBase] = None


def get_knowledge_base() -> KnowledgeBase:
    """Get global knowledge base instance."""
    global _kb
    if _kb is None:
        _kb = KnowledgeBase()
    return _kb
