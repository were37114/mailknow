"""Tests for hybrid search."""

import os
import sqlite3
import tempfile
from unittest.mock import Mock, patch

import numpy as np
import pytest

from core.search.embedding import LocalEmbedding
from core.search.hybrid import HybridSearch, SearchOptions, SearchResult, SearchWeights


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    # Create schema
    conn = sqlite3.connect(path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE pages (
            id TEXT PRIMARY KEY,
            type TEXT DEFAULT 'email',
            content TEXT NOT NULL,
            metadata TEXT DEFAULT '{}',
            gate_class TEXT DEFAULT 'routine',
            gate_score REAL DEFAULT 0.5,
            embedding BLOB,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # Insert test data
    test_pages = [
        ("page1", "这是一封关于项目的邮件", "{}", "important", None),
        ("page2", "请审批这份合同", "{}", "urgent", None),
        ("page3", "项目进度更新通知", "{}", "routine", None),
        ("page4", "垃圾邮件促销信息", "{}", "spam", None),
    ]

    cursor.executemany(
        "INSERT INTO pages (id, content, metadata, gate_class, embedding) VALUES (?, ?, ?, ?, ?)",
        test_pages
    )

    conn.commit()
    conn.close()

    yield path

    # Cleanup
    os.unlink(path)


@pytest.fixture
def mock_embedding():
    """Create mock embedding instance."""
    mock = Mock(spec=LocalEmbedding)
    mock.dimension = 512
    mock.encode = Mock(return_value=np.random.randn(512).astype(np.float32))
    mock.similarity = Mock(return_value=0.8)
    mock.bytes_to_embedding = Mock(return_value=np.random.randn(512).astype(np.float32))
    return mock


@pytest.fixture
def search(temp_db, mock_embedding):
    """Create hybrid search instance."""
    return HybridSearch(temp_db, embedding=mock_embedding)


def test_rrf_fusion(search: HybridSearch):
    """Test RRF fusion algorithm."""
    # Mock results
    vector_results = [
        ("page1", 0.9, 1),
        ("page2", 0.8, 2),
        ("page3", 0.7, 3),
    ]

    keyword_results = [
        ("page2", 0.85, 1),
        ("page4", 0.75, 2),
        ("page1", 0.65, 3),
    ]

    # Combine using RRF
    results = search._rrf_fusion(vector_results, keyword_results)

    # Should have 4 unique results
    assert len(results) == 4

    # page1 and page2 should have higher scores (appear in both lists)
    page1 = next(r for r in results if r.page_id == "page1")
    page2 = next(r for r in results if r.page_id == "page2")
    page3 = next(r for r in results if r.page_id == "page3")
    page4 = next(r for r in results if r.page_id == "page4")

    # page1: rank 1 in vector + rank 3 in keyword
    # RRF_score = 1/(60+1) + 1/(60+3) = 0.0164 + 0.0159 = 0.0323
    expected_page1 = 1/(60+1) + 1/(60+3)
    assert abs(page1.score - expected_page1) < 0.001

    # page2: rank 2 in vector + rank 1 in keyword
    # RRF_score = 1/(60+2) + 1/(60+1) = 0.0161 + 0.0164 = 0.0325
    expected_page2 = 1/(60+2) + 1/(60+1)
    assert abs(page2.score - expected_page2) < 0.001

    # page3: only in vector (rank 3)
    expected_page3 = 1/(60+3)
    assert abs(page3.score - expected_page3) < 0.001

    # page4: only in keyword (rank 2)
    expected_page4 = 1/(60+2)
    assert abs(page4.score - expected_page4) < 0.001


def test_apply_filters(search: HybridSearch):
    """Test applying filters to results."""
    results = [
        SearchResult(page_id="page1", content="content1", score=0.9, metadata={}, gate_class="important"),
        SearchResult(page_id="page2", content="content2", score=0.8, metadata={}, gate_class="urgent"),
        SearchResult(page_id="page3", content="content3", score=0.7, metadata={}, gate_class="routine"),
        SearchResult(page_id="page4", content="content4", score=0.6, metadata={}, gate_class="spam"),
    ]

    # Filter by gate class
    filtered = search._apply_filters(results, SearchOptions(gate_filter=["important", "urgent"]))
    assert len(filtered) == 2
    assert all(r.gate_class in ["important", "urgent"] for r in filtered)

    # Filter by min score
    filtered = search._apply_filters(results, SearchOptions(min_score=0.75))
    assert len(filtered) == 2
    assert all(r.score >= 0.75 for r in filtered)

    # Combined filter
    filtered = search._apply_filters(results, SearchOptions(gate_filter=["important", "urgent"], min_score=0.85))
    assert len(filtered) == 1
    assert filtered[0].page_id == "page1"


@pytest.mark.asyncio
async def test_keyword_search(search: HybridSearch):
    """Test keyword search."""
    results = await search._keyword_search("项目", 10)

    # Should find pages with "项目"
    assert len(results) > 0

    # All results should have rank
    for page_id, score, rank in results:
        assert rank > 0
        assert score > 0


@pytest.mark.asyncio
async def test_vector_search(search: HybridSearch):
    """Test vector search."""
    # Mock embedding returns random vector
    query_embedding = np.random.randn(512).astype(np.float32)

    results = await search._vector_search(query_embedding, 10)

    # Should return results (even without embeddings, it won't crash)
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_full_search(search: HybridSearch):
    """Test full hybrid search."""
    results, total = await search.search("项目", SearchOptions(limit=5))

    # Should return results
    assert isinstance(results, list)
    assert len(results) <= 5

    # All results should be SearchResult instances
    for result in results:
        assert isinstance(result, SearchResult)
        assert result.page_id
        assert result.score >= 0


@pytest.mark.asyncio
async def test_search_with_filters(search: HybridSearch):
    """Test search with gate filter."""
    results, total = await search.search(
        "项目",
        SearchOptions(limit=5, gate_filter=["important", "routine"])
    )

    # All results should match filter
    for result in results:
        assert result.gate_class in ["important", "routine"]


def test_rrf_k_parameter(temp_db, mock_embedding):
    """Test custom RRF k parameter."""
    weights = SearchWeights(rrf_k=100)
    search = HybridSearch(temp_db, embedding=mock_embedding, weights=weights)

    assert search.weights.rrf_k == 100

    # Test that k affects scores
    vector_results = [("page1", 0.9, 1)]
    keyword_results = [("page1", 0.8, 1)]

    results = search._rrf_fusion(vector_results, keyword_results)

    # With k=100: RRF_score = 1/(100+1) + 1/(100+1) = 0.0198
    expected = 2 * (1 / (100 + 1))
    assert abs(results[0].score - expected) < 0.001
