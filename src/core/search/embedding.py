"""Local embedding using bge-small-zh.

Provides zero-cost embedding generation using local model.
"""

import logging
from typing import List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Lazy import to avoid loading model at import time
_model = None


def get_embedding_model():
    """Get or load the embedding model (lazy loading)."""
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            logger.info("Loading bge-small-zh model...")
            _model = SentenceTransformer('BAAI/bge-small-zh-v1.5')
            logger.info("Model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            raise
    return _model


class LocalEmbedding:
    """Local embedding generator using bge-small-zh.

    Features:
    - Zero API cost
    - 512 dimensions
    - Chinese + English support
    - Offline capable
    """

    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5"):
        """Initialize embedding generator.

        Args:
            model_name: Model name (default: bge-small-zh-v1.5)
        """
        self.model_name = model_name
        self._model = None

    @property
    def model(self):
        """Lazy load model on first use."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading embedding model: {self.model_name}")
            self._model = SentenceTransformer(self.model_name)
        return self._model

    @property
    def dimension(self) -> int:
        """Get embedding dimension (512 for bge-small-zh)."""
        return 512

    def encode(self, text: str) -> np.ndarray:
        """Generate embedding for a single text.

        Args:
            text: Input text

        Returns:
            Embedding vector (512 dimensions)
        """
        if not text or not text.strip():
            # Return zero vector for empty text
            return np.zeros(self.dimension, dtype=np.float32)

        try:
            embedding = self.model.encode(
                text,
                normalize_embeddings=True,
                show_progress_bar=False
            )
            return embedding.astype(np.float32)
        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            return np.zeros(self.dimension, dtype=np.float32)

    def encode_batch(self, texts: List[str], batch_size: int = 32) -> np.ndarray:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of input texts
            batch_size: Batch size for processing

        Returns:
            Array of embeddings (N x 512)
        """
        if not texts:
            return np.array([], dtype=np.float32).reshape(0, self.dimension)

        # Filter empty texts
        valid_texts = [t if t and t.strip() else " " for t in texts]

        try:
            embeddings = self.model.encode(
                valid_texts,
                batch_size=batch_size,
                normalize_embeddings=True,
                show_progress_bar=False
            )
            return embeddings.astype(np.float32)
        except Exception as e:
            logger.error(f"Failed to generate batch embeddings: {e}")
            return np.zeros((len(texts), self.dimension), dtype=np.float32)

    def similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """Calculate cosine similarity between two vectors.

        Args:
            vec1: First vector
            vec2: Second vector

        Returns:
            Similarity score (0-1)
        """
        # Vectors are already normalized
        return float(np.dot(vec1, vec2))

    def embedding_to_bytes(self, embedding: np.ndarray) -> bytes:
        """Convert embedding to bytes for database storage.

        Args:
            embedding: Embedding vector

        Returns:
            Bytes representation
        """
        return embedding.tobytes()

    def bytes_to_embedding(self, data: bytes) -> np.ndarray:
        """Convert bytes back to embedding.

        Args:
            data: Bytes from database

        Returns:
            Embedding vector
        """
        return np.frombuffer(data, dtype=np.float32)


# Global instance for convenience
_embedding_instance: Optional[LocalEmbedding] = None


def get_embedding() -> LocalEmbedding:
    """Get global embedding instance."""
    global _embedding_instance
    if _embedding_instance is None:
        _embedding_instance = LocalEmbedding()
    return _embedding_instance
