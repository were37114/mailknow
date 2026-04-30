"""Search module for MailKnow."""

from .embedding import LocalEmbedding, get_embedding
from .hybrid import HybridSearch, SearchResult

__all__ = [
    "LocalEmbedding",
    "get_embedding",
    "HybridSearch",
    "SearchResult",
]
