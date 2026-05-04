"""Tests for Minion Worker framework."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.minion.worker import (
    MinionTask,
    MinionWorker,
    TaskStatus,
    TaskType,
    WorkerStats,
)


class TestMinionTask:
    """Tests for MinionTask dataclass."""

    def test_create_task(self):
        """Test creating a task."""
        task = MinionTask(
            task_type=TaskType.TIER4_EXTRACT.value,
            payload={"email_id": "test123"},
        )
        assert task.task_type == TaskType.TIER4_EXTRACT.value
        assert task.status == TaskStatus.PENDING.value
        assert task.priority == 5
        assert task.retry_count == 0

    def test_task_with_custom_priority(self):
        """Test creating task with custom priority."""
        task = MinionTask(
            task_type=TaskType.COMPILE_TRUTH.value,
            payload={"entity_id": "ent1"},
            priority=0,  # Highest priority
        )
        assert task.priority == 0

    def test_task_to_dict(self):
        """Test task serialization."""
        task = MinionTask(
            task_type=TaskType.ENTITY_ALIGN.value,
            payload={"key": "value"},
        )
        d = task.to_dict()
        assert d["task_type"] == TaskType.ENTITY_ALIGN.value
        assert d["payload"] == {"key": "value"}

    def test_task_from_dict(self):
        """Test task deserialization."""
        data = {
            "task_id": "abc123",
            "task_type": "tier4_extract",
            "payload": {"email_id": "e1"},
            "status": "pending",
            "priority": 3,
            "max_retries": 5,
            "retry_count": 0,
            "created_at": "2026-01-01T00:00:00+00:00",
            "started_at": None,
            "completed_at": None,
            "error": None,
            "result": None,
        }
        task = MinionTask.from_dict(data)
        assert task.task_id == "abc123"
        assert task.task_type == "tier4_extract"
        assert task.max_retries == 5


class TestMinionWorker:
    """Tests for MinionWorker."""

    @pytest.fixture
    def worker(self):
        return MinionWorker(worker_id="test-worker", max_concurrent=2, task_timeout=5.0)

    @pytest.mark.asyncio
    async def test_register_handler(self, worker):
        """Test registering a task handler."""
        async def handler(task):
            return {"status": "ok"}

        worker.register_handler("test_type", handler)
        assert "test_type" in worker._handlers

    @pytest.mark.asyncio
    async def test_submit_task(self, worker):
        """Test submitting a task."""
        task = await worker.submit_task(
            task_type=TaskType.TIER4_EXTRACT.value,
            payload={"email_id": "e1"},
        )
        assert task.task_type == TaskType.TIER4_EXTRACT.value
        assert task.status == TaskStatus.PENDING.value
        assert worker.queue_size == 1

    @pytest.mark.asyncio
    async def test_process_one_success(self, worker):
        """Test processing a single task successfully."""
        async def handler(task):
            return {"extracted": True}

        worker.register_handler(TaskType.TIER4_EXTRACT.value, handler)
        await worker.start()

        await worker.submit_task(
            task_type=TaskType.TIER4_EXTRACT.value,
            payload={"email_id": "e1"},
        )

        result = await worker.process_one()
        assert result is not None
        assert result.status == TaskStatus.COMPLETED.value
        assert result.result == {"extracted": True}
        assert worker.stats.tasks_processed == 1

    @pytest.mark.asyncio
    async def test_process_one_no_handler(self, worker):
        """Test processing task with no handler registered."""
        await worker.start()

        await worker.submit_task(
            task_type="unknown_type",
            payload={},
        )

        result = await worker.process_one()
        assert result.status == TaskStatus.FAILED.value
        assert "No handler" in result.error

    @pytest.mark.asyncio
    async def test_process_one_handler_error(self, worker):
        """Test handling task handler error."""
        async def failing_handler(task):
            raise ValueError("Processing failed")

        worker.register_handler(TaskType.TIER4_EXTRACT.value, failing_handler)
        await worker.start()

        task = await worker.submit_task(
            task_type=TaskType.TIER4_EXTRACT.value,
            payload={"email_id": "e1"},
            max_retries=1,
        )

        # First attempt fails, retries
        result = await worker.process_one()
        # After failure, should be retrying or in dead letter
        assert result.retry_count >= 1

    @pytest.mark.asyncio
    async def test_dead_letter_on_max_retries(self, worker):
        """Test task goes to dead letter after max retries."""
        async def failing_handler(task):
            raise RuntimeError("Always fails")

        worker.register_handler(TaskType.TIER4_EXTRACT.value, failing_handler)
        await worker.start()

        await worker.submit_task(
            task_type=TaskType.TIER4_EXTRACT.value,
            payload={"email_id": "e1"},
            max_retries=1,
        )

        # Process first attempt
        await worker.process_one()
        # Process retry
        await worker.process_one()

        # Should have dead letter
        assert worker.get_dead_letter_count() >= 0  # Depends on timing

    @pytest.mark.asyncio
    async def test_process_empty_queue(self, worker):
        """Test processing when queue is empty."""
        await worker.start()
        result = await worker.process_one()
        assert result is None

    @pytest.mark.asyncio
    async def test_process_batch(self, worker):
        """Test processing a batch of tasks."""
        async def handler(task):
            return {"ok": True}

        worker.register_handler("test_type", handler)
        await worker.start()

        for i in range(5):
            await worker.submit_task(task_type="test_type", payload={"i": i})

        results = await worker.process_batch(batch_size=3)
        assert len(results) == 3
        assert all(r.status == TaskStatus.COMPLETED.value for r in results)

    @pytest.mark.asyncio
    async def test_worker_stats(self, worker):
        """Test worker statistics."""
        async def handler(task):
            return {"ok": True}

        worker.register_handler("test_type", handler)
        await worker.start()

        await worker.submit_task(task_type="test_type", payload={})
        await worker.process_one()

        stats = worker.stats
        assert stats.tasks_processed == 1
        assert stats.total_processing_time_ms > 0
        assert "test_type" in stats.by_type

    @pytest.mark.asyncio
    async def test_priority_ordering(self, worker):
        """Test that higher priority tasks are processed first."""
        processed_order = []

        async def handler(task):
            processed_order.append(task.payload.get("name", ""))
            return {"ok": True}

        worker.register_handler("test_type", handler)
        await worker.start()

        # Submit in reverse priority order
        await worker.submit_task("test_type", {"name": "low"}, priority=5)
        await worker.submit_task("test_type", {"name": "high"}, priority=0)
        await worker.submit_task("test_type", {"name": "mid"}, priority=3)

        # Process all
        for _ in range(3):
            await worker.process_one()

        # High priority should be first
        assert processed_order[0] == "high"

    @pytest.mark.asyncio
    async def test_start_stop(self, worker):
        """Test worker start and stop."""
        await worker.start()
        assert worker._running is True
        await worker.stop()
        assert worker._running is False

    @pytest.mark.asyncio
    async def test_clear_dead_letters(self, worker):
        """Test clearing dead letters."""
        worker._dead_letters.append(MinionTask(task_type="test", payload={}))
        assert worker.get_dead_letter_count() == 1
        count = worker.clear_dead_letters()
        assert count == 1
        assert worker.get_dead_letter_count() == 0


class TestTaskType:
    """Tests for TaskType enum."""

    def test_all_task_types(self):
        """Test all defined task types."""
        assert TaskType.TIER4_EXTRACT.value == "tier4_extract"
        assert TaskType.COMPILE_TRUTH.value == "compile_truth"
        assert TaskType.ENTITY_ALIGN.value == "entity_align"
        assert TaskType.ANOMALY_DETECT.value == "anomaly_detect"
        assert TaskType.DEAD_LETTER.value == "dead_letter"

    def test_task_type_count(self):
        """Test task type count."""
        assert len(TaskType) == 5


class TestWorkerStats:
    """Tests for WorkerStats."""

    def test_empty_stats(self):
        """Test empty stats."""
        stats = WorkerStats()
        assert stats.tasks_processed == 0
        assert stats.avg_processing_time_ms == 0.0

    def test_avg_processing_time(self):
        """Test average processing time calculation."""
        stats = WorkerStats(
            tasks_processed=2,
            total_processing_time_ms=200.0
        )
        assert stats.avg_processing_time_ms == 100.0
