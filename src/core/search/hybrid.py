"""Hybrid search using RRF (Reciprocal Rank Fusion).

Combines vector search and keyword search for better results.
V2: Added metadata search, configurable weights, pagination, relevance scoring.
"""

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from .embedding import LocalEmbedding, get_embedding

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Search result item."""
    page_id: str
    content: str
    score: float
    metadata: Dict
    gate_class: str

    # Individual scores
    vector_score: float = 0.0
    keyword_score: float = 0.0
    metadata_score: float = 0.0
    vector_rank: int = 0
    keyword_rank: int = 0


@dataclass
class SearchWeights:
    """Configurable search weights for RRF fusion."""
    vector_weight: float = 1.0     # Vector search weight
    keyword_weight: float = 1.0    # Keyword search weight
    metadata_weight: float = 0.5   # Metadata search weight (from/to/subject)
    rrf_k: int = 60               # RRF constant

    # Relevance boost factors
    subject_match_boost: float = 2.0    # Subject matches are more important
    from_match_boost: float = 1.5       # Sender matches
    recent_boost: float = 0.1           # Small recency boost


@dataclass
class SearchOptions:
    """Search options for fine-grained control."""
    gate_filter: Optional[List[str]] = None
    min_score: float = 0.0
    offset: int = 0
    limit: int = 10
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    search_metadata: bool = True     # Include from/to/subject in search


class HybridSearch:
    """Hybrid search combining vector and keyword search.

    V2 Features:
    - Configurable RRF weights
    - Metadata search (from, to, subject)
    - Relevance boosting (subject > from > body)
    - Pagination support
    - Date range filtering
    """

    def __init__(
        self,
        db_path: str,
        embedding: Optional[LocalEmbedding] = None,
        weights: Optional[SearchWeights] = None,
    ):
        """Initialize hybrid search.

        Args:
            db_path: Path to SQLite database
            embedding: Embedding instance (default: global instance)
            weights: Search weights configuration
        """
        self.db_path = db_path
        self.embedding = embedding or get_embedding()
        self.weights = weights or SearchWeights()

    async def search(
        self,
        query: str,
        options: Optional[SearchOptions] = None,
    ) -> Tuple[List[SearchResult], int]:
        """Perform hybrid search.

        Args:
            query: Search query
            options: Search options

        Returns:
            Tuple of (results, total_count)
        """
        if options is None:
            options = SearchOptions()

        # Generate query embedding
        query_embedding = self.embedding.encode(query)

        # Get search results from each source
        vector_results = await self._vector_search(query_embedding, options.limit * 3)
        keyword_results = await self._keyword_search(query, options.limit * 3)

        # Get metadata results if enabled
        metadata_results = []
        if options.search_metadata:
            metadata_results = await self._metadata_search(query, options.limit * 3)

        # Combine using weighted RRF
        combined = self._rrf_fusion(vector_results, keyword_results, metadata_results)

        # Fill in content/metadata from database
        combined = await self._enrich_results(combined)

        # Apply filters
        filtered = self._apply_filters(combined, options)

        # Sort by score
        sorted_results = sorted(filtered, key=lambda x: x.score, reverse=True)

        total = len(sorted_results)

        # Apply pagination
        paginated = sorted_results[options.offset:options.offset + options.limit]

        return paginated, total

    async def _vector_search(
        self,
        query_embedding: np.ndarray,
        limit: int
    ) -> List[Tuple[str, float, int]]:
        """Perform vector similarity search."""
        results = []

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT id, embedding
                FROM pages
                WHERE embedding IS NOT NULL
            """)

            rows = cursor.fetchall()

            similarities = []
            for row in rows:
                page_id, embedding_bytes = row

                if embedding_bytes:
                    page_embedding = self.embedding.bytes_to_embedding(embedding_bytes)
                    similarity = self.embedding.similarity(query_embedding, page_embedding)
                    similarities.append((page_id, similarity))

            # Sort by similarity
            similarities.sort(key=lambda x: x[1], reverse=True)

            for rank, (page_id, score) in enumerate(similarities[:limit], 1):
                results.append((page_id, score, rank))

            conn.close()

        except Exception as e:
            logger.error(f"Vector search failed: {e}")

        return results

    async def _keyword_search(
        self,
        query: str,
        limit: int
    ) -> List[Tuple[str, float, int]]:
        """Perform keyword search with TF scoring."""
        results = []

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            keywords = query.split()
            if not keywords:
                return []

            # Build LIKE conditions for content field
            like_conditions = " OR ".join(["content LIKE ?" for _ in keywords])
            like_params = [f"%{kw}%" for kw in keywords]

            cursor.execute(f"""
                SELECT id, content
                FROM pages
                WHERE {like_conditions}
                ORDER BY created_at DESC
                LIMIT ?
            """, like_params + [limit])

            rows = cursor.fetchall()

            for rank, (page_id, content) in enumerate(rows, 1):
                # Calculate TF score with boost for multiple keyword matches
                matches = sum(1 for kw in keywords if kw.lower() in content.lower())
                score = matches / len(keywords)

                # Boost for exact phrase match
                if query.lower() in content.lower():
                    score *= 1.5

                results.append((page_id, score, rank))

            conn.close()

        except Exception as e:
            logger.error(f"Keyword search failed: {e}")

        return results

    async def _metadata_search(
        self,
        query: str,
        limit: int
    ) -> List[Tuple[str, float, int]]:
        """Search in metadata fields (from, to, subject).

        Returns results with boosted scores for metadata matches.
        """
        results = []

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Search in metadata JSON
            keywords = query.split()

            cursor.execute("""
                SELECT id, metadata, content
                FROM pages
                WHERE metadata IS NOT NULL
                ORDER BY created_at DESC
            """)

            rows = cursor.fetchall()
            scored = []

            for page_id, metadata_str, content in rows:
                if not metadata_str:
                    continue

                try:
                    metadata = json.loads(metadata_str)
                except (json.JSONDecodeError, TypeError):
                    continue

                score = 0.0

                # Check subject match (highest boost)
                subject = metadata.get("from_name", "") or content
                from_addr = metadata.get("from_addr", "")
                from_name = metadata.get("from_name", "")

                for kw in keywords:
                    kw_lower = kw.lower()

                    # Subject match (stored in content field for emails)
                    if kw_lower in content.lower():
                        score += self.weights.subject_match_boost

                    # From address/name match
                    if kw_lower in from_addr.lower() or kw_lower in from_name.lower():
                        score += self.weights.from_match_boost

                    # To addresses match
                    to_addrs = metadata.get("to_addrs", [])
                    if isinstance(to_addrs, list):
                        for addr in to_addrs:
                            if kw_lower in str(addr).lower():
                                score += self.weights.from_match_boost
                                break

                if score > 0:
                    scored.append((page_id, score))

            # Sort by score
            scored.sort(key=lambda x: x[1], reverse=True)

            for rank, (page_id, score) in enumerate(scored[:limit], 1):
                results.append((page_id, score, rank))

            conn.close()

        except Exception as e:
            logger.error(f"Metadata search failed: {e}")

        return results

    def _rrf_fusion(
        self,
        vector_results: List[Tuple[str, float, int]],
        keyword_results: List[Tuple[str, float, int]],
        metadata_results: List[Tuple[str, float, int]] = None,
    ) -> List[SearchResult]:
        """Combine results using weighted RRF.

        RRF_score = sum(weight_i * 1 / (k + rank_i))
        """
        result_map: Dict[str, SearchResult] = {}

        # Process vector results
        for page_id, score, rank in vector_results:
            rrf_score = self.weights.vector_weight / (self.weights.rrf_k + rank)

            if page_id not in result_map:
                result_map[page_id] = SearchResult(
                    page_id=page_id, content="", score=rrf_score,
                    metadata={}, gate_class="routine",
                    vector_score=score, vector_rank=rank,
                )
            else:
                result_map[page_id].score += rrf_score
                result_map[page_id].vector_score = score
                result_map[page_id].vector_rank = rank

        # Process keyword results
        for page_id, score, rank in keyword_results:
            rrf_score = self.weights.keyword_weight / (self.weights.rrf_k + rank)

            if page_id not in result_map:
                result_map[page_id] = SearchResult(
                    page_id=page_id, content="", score=rrf_score,
                    metadata={}, gate_class="routine",
                    keyword_score=score, keyword_rank=rank,
                )
            else:
                result_map[page_id].score += rrf_score
                result_map[page_id].keyword_score = score
                result_map[page_id].keyword_rank = rank

        # Process metadata results
        if metadata_results:
            for page_id, score, rank in metadata_results:
                rrf_score = self.weights.metadata_weight / (self.weights.rrf_k + rank)

                if page_id not in result_map:
                    result_map[page_id] = SearchResult(
                        page_id=page_id, content="", score=rrf_score,
                        metadata={}, gate_class="routine",
                        metadata_score=score,
                    )
                else:
                    result_map[page_id].score += rrf_score
                    result_map[page_id].metadata_score = score

        return list(result_map.values())

    async def _enrich_results(self, results: List[SearchResult]) -> List[SearchResult]:
        """Fill in content and metadata from database."""
        if not results:
            return results

        page_ids = [r.page_id for r in results]

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            placeholders = ",".join(["?" for _ in page_ids])
            cursor.execute(
                f"""SELECT id, content, metadata, gate_class
                    FROM pages WHERE id IN ({placeholders})""",
                page_ids
            )

            rows = cursor.fetchall()
            page_data = {}
            for row in rows:
                page_data[row[0]] = {
                    "content": row[1],
                    "metadata": row[2],
                    "gate_class": row[3],
                }

            conn.close()

            for result in results:
                if result.page_id in page_data:
                    data = page_data[result.page_id]
                    result.content = data["content"]
                    result.gate_class = data["gate_class"] or "routine"
                    try:
                        result.metadata = json.loads(data["metadata"]) if data["metadata"] else {}
                    except (json.JSONDecodeError, TypeError):
                        result.metadata = {}

        except Exception as e:
            logger.error(f"Failed to enrich results: {e}")

        return results

    def _apply_filters(
        self,
        results: List[SearchResult],
        options: SearchOptions,
    ) -> List[SearchResult]:
        """Apply filters to results."""
        filtered = results

        if options.gate_filter:
            filtered = [r for r in filtered if r.gate_class in options.gate_filter]

        if options.min_score > 0:
            filtered = [r for r in filtered if r.score >= options.min_score]

        if options.date_from:
            filtered = [r for r in filtered if r.metadata.get("date", "") >= options.date_from]

        if options.date_to:
            filtered = [r for r in filtered if r.metadata.get("date", "") <= options.date_to]

        return filtered
