"""Minion Worker framework for background task processing.

Task types:
- tier4_extract: LLM semantic extraction
- compile_truth: Generate entity summaries
- entity_align: Merge duplicate entities
- anomaly_detect: Detect anomalous patterns
- dead_letter: Failed task analysis
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Callable, Awaitable
from pathlib import Path

logger = logging.getLogger(__name__)


class TaskType(str, Enum):
    """Minion task types."""
    TIER4_EXTRACT = "tier4_extract"
    COMPILE_TRUTH = "compile_truth"
    ENTITY_ALIGN = "entity_align"
    ANOMALY_DETECT = "anomaly_detect"
    DEAD_LETTER = "dead_letter"


class TaskStatus(str, Enum):
    """Task execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
    RETRYING = "retrying"


@dataclass
class MinionTask:
    """A Minion background task.
    
    Attributes:
        task_id: Unique task identifier
        task_type: Type of task
        payload: Task-specific data (JSON-serializable)
        status: Current status
        priority: Priority (0=highest, default=5)
        max_retries: Maximum retry attempts
        retry_count: Current retry count
        created_at: Creation timestamp
        started_at: Execution start timestamp
        completed_at: Completion timestamp
        error: Last error message
        result: Task result data
    """
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    task_type: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    status: str = TaskStatus.PENDING.value
    priority: int = 5
    max_retries: int = 3
    retry_count: int = 0
    created_at: str = field(default_factory=lambda: now_iso())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize task to dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MinionTask":
        """Deserialize task from dict."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# Type for task handlers
TaskHandler = Callable[[MinionTask], Awaitable[Dict[str, Any]]]


@dataclass
class WorkerStats:
    """Worker statistics."""
    tasks_processed: int = 0
    tasks_failed: int = 0
    tasks_dead_lettered: int = 0
    total_processing_time_ms: float = 0.0
    by_type: Dict[str, int] = field(default_factory=dict)

    @property
    def avg_processing_time_ms(self) -> float:
        """Average processing time per task."""
        if self.tasks_processed == 0:
            return 0.0
        return self.total_processing_time_ms / self.tasks_processed


class MinionWorker:
    """Background task worker with queue and retry logic.
    
    Features:
    - Priority-based task queue
    - Concurrent task execution
    - Automatic retry with exponential backoff
    - Dead letter queue for permanently failed tasks
    - Task persistence to SQLite
    - Statistics tracking
    """

    def __init__(
        self,
        worker_id: str = "minion-0",
        max_concurrent: int = 3,
        task_timeout: float = 300.0,  # 5 minutes
        persist_dir: Optional[Path] = None,
    ):
        """Initialize Minion worker.
        
        Args:
            worker_id: Worker identifier
            max_concurrent: Max concurrent tasks
            task_timeout: Task timeout in seconds
            persist_dir: Directory for task persistence
        """
        self.worker_id = worker_id
        self.max_concurrent = max_concurrent
        self.task_timeout = task_timeout
        self.persist_dir = persist_dir
        
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._handlers: Dict[str, TaskHandler] = {}
        self._dead_letters: List[MinionTask] = []
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._stats = WorkerStats()
        self._running = False
        self._semaphore: Optional[asyncio.Semaphore] = None

    def register_handler(self, task_type: str, handler: TaskHandler) -> None:
        """Register a task handler.
        
        Args:
            task_type: Task type to handle
            handler: Async callable that processes the task
        """
        self._handlers[task_type] = handler
        logger.info(f"Registered handler for {task_type}")

    async def submit_task(
        self,
        task_type: str,
        payload: Dict[str, Any],
        priority: int = 5,
        max_retries: int = 3,
    ) -> MinionTask:
        """Submit a new task to the queue.
        
        Args:
            task_type: Type of task
            payload: Task data
            priority: Priority (0=highest)
            max_retries: Max retry attempts
            
        Returns:
            Created MinionTask
        """
        task = MinionTask(
            task_type=task_type,
            payload=payload,
            priority=priority,
            max_retries=max_retries,
        )
        
        # Priority queue uses (priority, creation_time, task)
        await self._queue.put((priority, time.time(), task))
        logger.debug(f"Submitted task {task.task_id} ({task_type}), priority={priority}")
        
        return task

    async def start(self) -> None:
        """Start the worker loop."""
        if self._running:
            return
        
        self._running = True
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        logger.info(f"Minion worker {self.worker_id} started (max_concurrent={self.max_concurrent})")

    async def stop(self) -> None:
        """Stop the worker loop."""
        self._running = False
        
        # Cancel running tasks
        for task_id, task in self._running_tasks.items():
            task.cancel()
        
        # Wait for tasks to finish
        if self._running_tasks:
            await asyncio.gather(*self._running_tasks.values(), return_exceptions=True)
        
        logger.info(f"Minion worker {self.worker_id} stopped")

    async def process_one(self) -> Optional[MinionTask]:
        """Process one task from the queue.
        
        Returns:
            Processed task or None if queue empty
        """
        try:
            # Get task with timeout
            priority, _, task = await asyncio.wait_for(
                self._queue.get(), timeout=1.0
            )
        except asyncio.TimeoutError:
            return None
        
        # Process with semaphore
        async with self._semaphore:
            return await self._execute_task(task)

    async def _execute_task(self, task: MinionTask) -> MinionTask:
        """Execute a single task with timeout and error handling.
        
        Args:
            task: Task to execute
            
        Returns:
            Updated task
        """
        handler = self._handlers.get(task.task_type)
        
        if handler is None:
            task.status = TaskStatus.FAILED.value
            task.error = f"No handler for task type: {task.task_type}"
            task.completed_at = now_iso()
            self._stats.tasks_failed += 1
            logger.error(f"No handler for task {task.task_id} ({task.task_type})")
            return task
        
        task.status = TaskStatus.RUNNING.value
        task.started_at = now_iso()
        start_time = time.time()
        
        try:
            # Execute with timeout
            result = await asyncio.wait_for(
                handler(task),
                timeout=self.task_timeout
            )
            
            # Success
            task.status = TaskStatus.COMPLETED.value
            task.result = result
            task.completed_at = now_iso()
            
            # Update stats
            duration_ms = (time.time() - start_time) * 1000
            self._stats.tasks_processed += 1
            self._stats.total_processing_time_ms += duration_ms
            self._stats.by_type[task.task_type] = self._stats.by_type.get(task.task_type, 0) + 1
            
            logger.debug(f"Task {task.task_id} completed in {duration_ms:.0f}ms")
            
        except asyncio.TimeoutError:
            task.error = f"Task timed out after {self.task_timeout}s"
            await self._handle_task_failure(task)
            
        except Exception as e:
            task.error = str(e)
            await self._handle_task_failure(task)
        
        return task

    async def _handle_task_failure(self, task: MinionTask) -> None:
        """Handle task failure with retry or dead letter.
        
        Args:
            task: Failed task
        """
        task.retry_count += 1
        
        if task.retry_count < task.max_retries:
            # Retry with exponential backoff
            delay = min(2 ** task.retry_count, 60)  # Cap at 60s
            task.status = TaskStatus.RETRYING.value
            logger.warning(
                f"Task {task.task_id} failed (retry {task.retry_count}/{task.max_retries}), "
                f"retrying in {delay}s: {task.error}"
            )
            
            await asyncio.sleep(delay)
            
            # Re-queue with higher priority
            await self._queue.put((task.priority - 1, time.time(), task))
            
        else:
            # Move to dead letter
            task.status = TaskStatus.DEAD_LETTER.value
            task.completed_at = now_iso()
            self._dead_letters.append(task)
            self._stats.tasks_dead_lettered += 1
            logger.error(
                f"Task {task.task_id} moved to dead letter after {task.max_retries} retries: {task.error}"
            )

    async def process_batch(self, batch_size: int = 10) -> List[MinionTask]:
        """Process a batch of tasks.
        
        Args:
            batch_size: Maximum tasks to process
            
        Returns:
            List of processed tasks
        """
        results = []
        for _ in range(batch_size):
            task = await self.process_one()
            if task is None:
                break
            results.append(task)
        return results

    @property
    def stats(self) -> WorkerStats:
        """Get worker statistics."""
        return self._stats

    @property
    def queue_size(self) -> int:
        """Get current queue size."""
        return self._queue.qsize()

    @property
    def dead_letters(self) -> List[MinionTask]:
        """Get dead letter tasks."""
        return self._dead_letters

    def get_dead_letter_count(self) -> int:
        """Get number of dead letter tasks."""
        return len(self._dead_letters)

    def clear_dead_letters(self) -> int:
        """Clear dead letter queue.
        
        Returns:
            Number of cleared tasks
        """
        count = len(self._dead_letters)
        self._dead_letters.clear()
        return count


def now_iso() -> str:
    """Current time in ISO format."""
    return datetime.now(timezone.utc).isoformat()
