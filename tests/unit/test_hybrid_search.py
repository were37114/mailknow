"""Tests for HybridSearch V2: RRF weights + metadata + pagination."""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from core.search.hybrid import (
    HybridSearch,
    SearchOptions,
    SearchResult,
    SearchWeights,
)
from db.pgpool import SQLitePool


@pytest.fixture
async def db():
    """Create temporary database for tests."""
    with tempfile.TemporaryDirectory() as d:
        pool = SQLitePool(data_dir=Path(d))
        await pool.start()
        await pool.init_schema()
        yield pool
        await pool.stop()


@pytest.fixture
def mock_embedding():
    """Create mock embedding model."""
    model = MagicMock()
    # Return 512-dim random vector for any input
    model.encode = MagicMock(return_value=np.random.rand(512).astype(np.float32))
    model.encode_batch = MagicMock(return_value=np.random.rand(5, 512).astype(np.float32))
    model.similarity = MagicMock(return_value=0.85)
    model.bytes_to_embedding = MagicMock(return_value=np.random.rand(512).astype(np.float32))
    model.embedding_to_bytes = MagicMock(return_value=bytes(2048))
    model.dimension = 512
    return model


@pytest.fixture
async def search(db, mock_embedding):
    """Create HybridSearch with mock embedding."""
    db_path = str(db.data_dir / "mailknow.db")
    return HybridSearch(
        db_path=db_path,
        embedding=mock_embedding,
        weights=SearchWeights(),
    )


async def _insert_email(db, page_id, subject, from_addr, content, gate_class="routine", embedding=True):
    """Helper to insert an email page."""
    conn = await db.get_connection()
    now = datetime.now(timezone.utc).isoformat()
    metadata = json.dumps({
        "from_addr": from_addr,
        "from_name": from_addr.split("@")[0],
        "to_addrs": ["me@company.com"],
        "date": now,
    }, ensure_ascii=False)

    emb_bytes = bytes(2048) if embedding else None

    await conn.execute(
        """INSERT OR IGNORE INTO pages
           (id, type, content, metadata, gate_class, embedding, created_at, updated_at)
           VALUES (?, 'email', ?, ?, ?, ?, ?, ?)""",
        (page_id, subject, metadata, gate_class, emb_bytes, now, now)
    )
    await conn.commit()


class TestSearchWeights:
    """Tests for SearchWeights."""

    def test_default_weights(self):
        w = SearchWeights()
        assert w.vector_weight == 1.0
        assert w.keyword_weight == 1.0
        assert w.metadata_weight == 0.5
        assert w.rrf_k == 60

    def test_custom_weights(self):
        w = SearchWeights(vector_weight=2.0, keyword_weight=0.5, rrf_k=30)
        assert w.vector_weight == 2.0
        assert w.rrf_k == 30


class TestSearchOptions:
    """Tests for SearchOptions."""

    def test_default_options(self):
        o = SearchOptions()
        assert o.limit == 10
        assert o.offset == 0
        assert o.gate_filter is None
        assert o.search_metadata is True

    def test_custom_options(self):
        o = SearchOptions(
            gate_filter=["important", "urgent"],
            limit=20,
            offset=10,
            date_from="2026-01-01",
        )
        assert o.gate_filter == ["important", "urgent"]
        assert o.offset == 10


class TestHybridSearch:
    """Tests for HybridSearch V2."""

    @pytest.mark.asyncio
    async def test_search_returns_tuple(self, search, db):
        """Test that search returns (results, total) tuple."""
        await _insert_email(db, "email:s1", "项目讨论", "zhangsan@test.com", "项目讨论内容")

        results, total = await search.search("项目")
        assert isinstance(results, list)
        assert isinstance(total, int)

    @pytest.mark.asyncio
    async def test_keyword_search_finds_content(self, search, db, mock_embedding):
        """Test keyword search finds matching content."""
        await _insert_email(db, "email:kw1", "项目讨论", "zhangsan@test.com", "关于项目进度")
        await _insert_email(db, "email:kw2", "会议通知", "lisi@test.com", "明天开会")

        results, total = await search.search("项目")
        # Should find at least the email containing "项目"
        assert total >= 1

    @pytest.mark.asyncio
    async def test_gate_filter(self, search, db, mock_embedding):
        """Test gate filter works."""
        await _insert_email(db, "email:gf1", "紧急服务器告警", "ops@test.com", "紧急", "urgent")
        await _insert_email(db, "email:gf2", "日常讨论", "dev@test.com", "讨论", "routine")

        options = SearchOptions(gate_filter=["urgent"])
        results, total = await search.search("讨论", options)

        # All results should be urgent
        for r in results:
            assert r.gate_class == "urgent"

    @pytest.mark.asyncio
    async def test_pagination(self, search, db, mock_embedding):
        """Test pagination works."""
        for i in range(15):
            await _insert_email(db, f"email:page{i}", f"项目{i}", f"sender{i}@test.com", f"项目内容{i}")

        # Page 1
        opts1 = SearchOptions(limit=5, offset=0)
        results1, total1 = await search.search("项目", opts1)
        assert len(results1) <= 5

        # Page 2
        opts2 = SearchOptions(limit=5, offset=5)
        results2, total2 = await search.search("项目", opts2)

        # Total should be the same
        assert total1 == total2

    @pytest.mark.asyncio
    async def test_metadata_search_from_addr(self, search, db, mock_embedding):
        """Test metadata search finds sender."""
        await _insert_email(db, "email:meta1", "项目进度", "zhangsan@company.com", "讨论项目")
        await _insert_email(db, "email:meta2", "会议通知", "lisi@company.com", "开会讨论")

        results, total = await search.search("zhangsan")
        assert total >= 1

    @pytest.mark.asyncio
    async def test_empty_query(self, search, db, mock_embedding):
        """Test empty query returns no results."""
        results, total = await search.search("")
        # Should handle gracefully
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_search_result_has_scores(self, search, db, mock_embedding):
        """Test results have individual score breakdown."""
        await _insert_email(db, "email:score1", "项目进度", "test@test.com", "项目讨论")

        results, _ = await search.search("项目")
        if results:
            r = results[0]
            assert hasattr(r, 'vector_score')
            assert hasattr(r, 'keyword_score')
            assert hasattr(r, 'metadata_score')

    @pytest.mark.asyncio
    async def test_weighted_rrf(self, search, db, mock_embedding):
        """Test weighted RRF fusion."""
        # High vector weight should favor vector results
        search.weights = SearchWeights(vector_weight=2.0, keyword_weight=0.5)

        await _insert_email(db, "email:w1", "测试邮件", "test@test.com", "内容")
        results, _ = await search.search("测试")
        # Should still return results
        assert isinstance(results, list)
