"""Tests for local embedding."""

from unittest.mock import Mock, patch

import numpy as np
import pytest

from core.search.embedding import LocalEmbedding


@pytest.fixture
def embedding():
    """Create embedding instance."""
    return LocalEmbedding()


@pytest.fixture
def mock_model():
    """Create mock sentence transformer model."""
    mock = Mock()
    mock.encode = Mock(return_value=np.random.randn(512).astype(np.float32))
    return mock


def test_embedding_dimension(embedding: LocalEmbedding):
    """Test embedding dimension is 512."""
    assert embedding.dimension == 512


def test_encode_empty_text(embedding: LocalEmbedding, mock_model):
    """Test encoding empty text returns zero vector."""
    embedding._model = mock_model

    result = embedding.encode("")

    # Should return zero vector
    assert result.shape == (512,)
    assert np.allclose(result, np.zeros(512))


def test_encode_single_text(embedding: LocalEmbedding, mock_model):
    """Test encoding single text."""
    embedding._model = mock_model

    result = embedding.encode("测试文本")

    # Should call model.encode
    mock_model.encode.assert_called_once()
    assert result.shape == (512,)
    assert result.dtype == np.float32


def test_encode_batch(embedding: LocalEmbedding, mock_model):
    """Test encoding batch of texts."""
    embedding._model = mock_model
    mock_model.encode = Mock(
        return_value=np.random.randn(3, 512).astype(np.float32)
    )

    texts = ["文本1", "文本2", "文本3"]
    result = embedding.encode_batch(texts)

    # Should return 3 x 512 array
    assert result.shape == (3, 512)
    assert result.dtype == np.float32


def test_encode_empty_batch(embedding: LocalEmbedding):
    """Test encoding empty batch."""
    result = embedding.encode_batch([])

    # Should return empty array with correct shape
    assert result.shape == (0, 512)


def test_similarity(embedding: LocalEmbedding):
    """Test cosine similarity calculation."""
    vec1 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    vec2 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    vec3 = np.array([0.0, 1.0, 0.0], dtype=np.float32)

    # Same vectors
    sim1 = embedding.similarity(vec1, vec2)
    assert abs(sim1 - 1.0) < 0.01

    # Orthogonal vectors
    sim2 = embedding.similarity(vec1, vec3)
    assert abs(sim2) < 0.01


def test_embedding_bytes_conversion(embedding: LocalEmbedding):
    """Test converting embedding to/from bytes."""
    original = np.random.randn(512).astype(np.float32)

    # Convert to bytes
    bytes_data = embedding.embedding_to_bytes(original)
    assert isinstance(bytes_data, bytes)
    assert len(bytes_data) == 512 * 4  # 512 floats * 4 bytes

    # Convert back
    restored = embedding.bytes_to_embedding(bytes_data)
    assert np.allclose(original, restored)


def test_model_lazy_loading(embedding: LocalEmbedding):
    """Test that model is loaded lazily."""
    # Model should not be loaded initially
    assert embedding._model is None

    # Access model property (will load in real test)
    # In mock test, we just verify the pattern
    with patch('sentence_transformers.SentenceTransformer') as mock_st:
        mock_st.return_value = Mock()
        _ = embedding.model

        # Should have called SentenceTransformer
        mock_st.assert_called_once()


@pytest.mark.integration
def test_real_embedding():
    """Integration test with real model (slow)."""
    pytest.skip("Integration test - requires model download")

    embedding = LocalEmbedding()

    # Test Chinese text
    text = "这是一封测试邮件"
    result = embedding.encode(text)

    assert result.shape == (512,)
    assert not np.allclose(result, np.zeros(512))

    # Test similarity
    text2 = "这是另一封测试邮件"
    result2 = embedding.encode(text2)

    sim = embedding.similarity(result, result2)
    assert 0 < sim < 1  # Should have some similarity
