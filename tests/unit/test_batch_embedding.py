"""Tests for BatchEmbeddingQueue: async embedding with progress tracking."""

import pytest
import asyncio
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch

from core.search.batch_embedding import (
    BatchEmbeddingQueue,
    EmbeddingProgress,
    EmbeddingStatus,
    EmbeddingTask,
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
    import numpy as np
    model.encode_batch = MagicMock(return_value=np.random.rand(5, 512).astype(np.float32))
    model.embedding_to_bytes = MagicMock(side_effect=lambda x: x.tobytes() if hasattr(x, 'tobytes') else bytes(2048))
    model.dimension = 512
    return model


@pytest.fixture
async def queue(db, mock_embedding):
    """Create batch embedding queue."""
    q = BatchEmbeddingQueue(db=db, embedding_model=mock_embedding, batch_size=10)
    await q._ensure_table()
    return q


async def _insert_page(db, page_id, content="Test content", gate_class="routine"):
    """Helper to insert a page."""
    conn = await db.get_connection()
    now = datetime.now(timezone.utc).isoformat()
    await conn.execute(
        "INSERT OR IGNORE INTO pages (id, type, content, gate_class, created_at, updated_at) VALUES (?, 'email', ?, ?, ?, ?)",
        (page_id, content, gate_class, now, now)
    )
    await conn.commit()


class TestEmbeddingProgress:
    """Tests for EmbeddingProgress."""

    def test_empty_progress(self):
        p = EmbeddingProgress()
        assert p.percent == 100.0
        assert p.total == 0

    def test_partial_progress(self):
        p = EmbeddingProgress(total=100, completed=60, skipped=10, failed=5, pending=25)
        assert p.percent == 70.0  # (60+10)/100

    def test_full_progress(self):
        p = EmbeddingProgress(total=50, completed=40, skipped=10)
        assert p.percent == 100.0


class TestEmbeddingStatus:
    """Tests for EmbeddingStatus enum."""

    def test_status_values(self):
        assert EmbeddingStatus.PENDING.value == "pending"
        assert EmbeddingStatus.COMPLETED.value == "completed"
        assert EmbeddingStatus.FAILED.value == "failed"
        assert EmbeddingStatus.SKIPPED.value == "skipped"


class TestEmbeddingTask:
    """Tests for EmbeddingTask."""

    def test_create_task(self):
        t = EmbeddingTask(
            page_id="email:test",
            content="Test content",
            gate_class="routine",
        )
        assert t.status == EmbeddingStatus.PENDING
        assert t.attempts == 0


class TestBatchEmbeddingQueue:
    """Tests for BatchEmbeddingQueue."""

    @pytest.mark.asyncio
    async def test_enqueue_routine_email(self, queue, db):
        """Test enqueueing a routine email."""
        await _insert_page(db, "email:test1", "邮件内容", "routine")
        result = await queue.enqueue("email:test1", "邮件内容", "routine")
        assert result is True
        
        progress = await queue.get_progress()
        assert progress.pending == 1

    @pytest.mark.asyncio
    async def test_enqueue_spam_skipped(self, queue, db):
        """Test spam emails are automatically skipped."""
        await _insert_page(db, "email:spam1", "垃圾邮件", "spam")
        result = await queue.enqueue("email:spam1", "垃圾邮件", "spam")
        assert result is True
        
        progress = await queue.get_progress()
        assert progress.skipped == 1
        assert progress.pending == 0

    @pytest.mark.asyncio
    async def test_enqueue_notification_skipped(self, queue, db):
        """Test notification emails are automatically skipped."""
        await _insert_page(db, "email:notif1", "通知邮件", "notification")
        result = await queue.enqueue("email:notif1", "通知邮件", "notification")
        assert result is True
        
        progress = await queue.get_progress()
        assert progress.skipped == 1

    @pytest.mark.asyncio
    async def test_enqueue_batch(self, queue, db):
        """Test batch enqueue."""
        items = [
            {"page_id": "email:b1", "content": "Content 1", "gate_class": "routine"},
            {"page_id": "email:b2", "content": "Content 2", "gate_class": "important"},
            {"page_id": "email:b3", "content": "Content 3", "gate_class": "spam"},
        ]
        for item in items:
            await _insert_page(db, item["page_id"], item["content"], item["gate_class"])
        
        count = await queue.enqueue_batch(items)
        assert count == 3
        
        progress = await queue.get_progress()
        assert progress.pending == 2  # routine + important
        assert progress.skipped == 1  # spam

    @pytest.mark.asyncio
    async def test_process_batch(self, queue, db, mock_embedding):
        """Test processing a batch of embeddings."""
        items = [
            {"page_id": "email:p1", "content": "邮件1", "gate_class": "routine"},
            {"page_id": "email:p2", "content": "邮件2", "gate_class": "important"},
            {"page_id": "email:p3", "content": "邮件3", "gate_class": "routine"},
        ]
        for item in items:
            await _insert_page(db, item["page_id"], item["content"], item["gate_class"])
        
        await queue.enqueue_batch(items)
        
        processed = await queue.process_now()
        assert processed == 3
        
        progress = await queue.get_progress()
        assert progress.completed == 3
        assert progress.pending == 0

    @pytest.mark.asyncio
    async def test_progress_callback(self, queue, db, mock_embedding):
        """Test progress callback is called after processing."""
        callbacks = []
        queue.on_progress(lambda p: callbacks.append(p))
        
        await _insert_page(db, "email:cb1", "内容", "routine")
        await queue.enqueue("email:cb1", "内容", "routine")
        await queue.process_now()
        
        assert len(callbacks) >= 1

    @pytest.mark.asyncio
    async def test_retry_failed(self, queue, db):
        """Test retrying failed embeddings."""
        conn = await db.get_connection()
        await conn.execute(
            """INSERT INTO embedding_queue (page_id, content, gate_class, status, attempts, error)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("email:fail1", "内容", "routine", "failed", 1, "test error")
        )
        await conn.commit()
        
        retried = await queue.retry_failed()
        assert retried == 1
        
        progress = await queue.get_progress()
        assert progress.pending == 1
        assert progress.failed == 0

    @pytest.mark.asyncio
    async def test_already_embedded_skip(self, queue, db, mock_embedding):
        """Test that already-embedded pages are not re-queued."""
        conn = await db.get_connection()
        import numpy as np
        emb_bytes = np.zeros(512, dtype=np.float32).tobytes()
        now = datetime.now(timezone.utc).isoformat()
        await conn.execute(
            "INSERT INTO pages (id, type, content, embedding, created_at, updated_at) VALUES (?, 'email', ?, ?, ?, ?)",
            ("email:emb1", "已有向量", emb_bytes, now, now)
        )
        await conn.commit()
        
        result = await queue.enqueue("email:emb1", "已有向量", "routine")
        assert result is True
        
        # Should not add to queue
        progress = await queue.get_progress()
        assert progress.total == 0

    @pytest.mark.asyncio
    async def test_start_stop(self, queue):
        """Test starting and stopping the queue."""
        await queue.start()
        assert queue.is_running is True
        
        await asyncio.sleep(0.1)
        
        await queue.stop()
        assert queue.is_running is False

    @pytest.mark.asyncio
    async def test_content_truncation(self, queue, db):
        """Test that long content is truncated."""
        long_content = "A" * 5000
        await _insert_page(db, "email:long1", long_content, "routine")
        
        await queue.enqueue("email:long1", long_content, "routine")
        
        conn = await db.get_connection()
        cursor = await conn.execute(
            "SELECT content FROM embedding_queue WHERE page_id = ?",
            ("email:long1",)
        )
        row = await cursor.fetchone()
        assert len(row[0]) <= 2000
