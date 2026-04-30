"""Batch embedding queue with progress tracking.

Processes email embeddings asynchronously:
1. New emails are queued for embedding after Pipeline processing
2. Worker processes queue in batches (skip spam/notification)
3. Progress tracked in database for UI display
4. Failed embeddings tracked for retry
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field
from enum import Enum

from db.pgpool import SQLitePool

logger = logging.getLogger(__name__)


class EmbeddingStatus(str, Enum):
    """Embedding task status."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"  # spam/notification


@dataclass
class EmbeddingProgress:
    """Progress tracking for embedding queue."""
    total: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    pending: int = 0
    processing: int = 0
    
    @property
    def percent(self) -> float:
        """Completion percentage."""
        if self.total == 0:
            return 100.0
        return (self.completed + self.skipped) / self.total * 100


@dataclass
class EmbeddingTask:
    """A single embedding task."""
    page_id: str
    content: str
    gate_class: str
    status: EmbeddingStatus = EmbeddingStatus.PENDING
    attempts: int = 0
    error: Optional[str] = None
    created_at: str = ""


class BatchEmbeddingQueue:
    """Async batch embedding queue with progress tracking.
    
    Usage:
        queue = BatchEmbeddingQueue(db, embedding_model)
        await queue.start()
        
        # Enqueue pages for embedding
        await queue.enqueue("email:abc123", "邮件内容", "routine")
        
        # Get progress
        progress = await queue.get_progress()
        
        await queue.stop()
    """
    
    # Skip embedding for these gate classes
    SKIP_GATE_CLASSES = {"spam", "notification"}
    
    # Batch size for processing
    BATCH_SIZE = 32
    
    # Max retries for failed embeddings
    MAX_RETRIES = 3
    
    # Progress table name
    PROGRESS_TABLE = "embedding_queue"
    
    def __init__(
        self,
        db: SQLitePool,
        embedding_model=None,
        batch_size: int = 32,
        max_retries: int = 3,
    ):
        """Initialize batch embedding queue.
        
        Args:
            db: Database pool
            embedding_model: LocalEmbedding instance (lazy loaded if None)
            batch_size: Batch size for embedding
            max_retries: Max retry attempts
        """
        self.db = db
        self.embedding_model = embedding_model
        self.batch_size = batch_size
        self.max_retries = max_retries
        
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._progress_callbacks: List[Callable] = []
        self._semaphore = asyncio.Semaphore(1)  # Single worker
    
    async def start(self):
        """Start the embedding worker."""
        await self._ensure_table()
        self._running = True
        self._task = asyncio.create_task(self._worker_loop())
        logger.info("Batch embedding queue started")
    
    async def stop(self):
        """Stop the embedding worker."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Batch embedding queue stopped")
    
    @property
    def is_running(self) -> bool:
        """Check if worker is running."""
        return self._running
    
    async def enqueue(
        self,
        page_id: str,
        content: str,
        gate_class: str,
    ) -> bool:
        """Enqueue a page for embedding.
        
        Args:
            page_id: Page ID
            content: Text content to embed
            gate_class: Gate class (spam/notification will be skipped)
            
        Returns:
            True if enqueued (or skipped appropriately)
        """
        # Skip spam/notification
        if gate_class in self.SKIP_GATE_CLASSES:
            await self._update_status(page_id, EmbeddingStatus.SKIPPED)
            return True
        
        # Check if already has embedding
        conn = await self.db.get_connection()
        cursor = await conn.execute(
            "SELECT embedding FROM pages WHERE id = ?", (page_id,)
        )
        row = await cursor.fetchone()
        if row and row[0] is not None:
            return True  # Already embedded
        
        # Add to queue
        try:
            await conn.execute(
                """INSERT OR IGNORE INTO embedding_queue 
                   (page_id, content, gate_class, status, attempts, created_at)
                   VALUES (?, ?, ?, ?, 0, ?)""",
                (
                    page_id,
                    content[:2000],  # Truncate long content
                    gate_class,
                    EmbeddingStatus.PENDING.value,
                    datetime.now(timezone.utc).isoformat(),
                )
            )
            await conn.commit()
            return True
        except Exception as e:
            logger.warning(f"Failed to enqueue {page_id}: {e}")
            return False
    
    async def enqueue_batch(self, items: List[Dict[str, str]]) -> int:
        """Enqueue multiple pages for embedding.
        
        Args:
            items: List of {page_id, content, gate_class}
            
        Returns:
            Number of items enqueued
        """
        count = 0
        for item in items:
            if await self.enqueue(
                page_id=item["page_id"],
                content=item["content"],
                gate_class=item.get("gate_class", "routine"),
            ):
                count += 1
        return count
    
    async def get_progress(self) -> EmbeddingProgress:
        """Get current embedding progress."""
        conn = await self.db.get_connection()
        
        cursor = await conn.execute(
            """SELECT status, COUNT(*) FROM embedding_queue GROUP BY status"""
        )
        rows = await cursor.fetchall()
        
        counts = {row[0]: row[1] for row in rows}
        
        return EmbeddingProgress(
            total=sum(counts.values()),
            completed=counts.get(EmbeddingStatus.COMPLETED.value, 0),
            failed=counts.get(EmbeddingStatus.FAILED.value, 0),
            skipped=counts.get(EmbeddingStatus.SKIPPED.value, 0),
            pending=counts.get(EmbeddingStatus.PENDING.value, 0),
            processing=counts.get(EmbeddingStatus.PROCESSING.value, 0),
        )
    
    async def process_now(self) -> int:
        """Process pending embeddings immediately (blocking).
        
        Returns:
            Number of embeddings processed
        """
        return await self._process_batch()
    
    async def retry_failed(self) -> int:
        """Retry all failed embeddings.
        
        Returns:
            Number of items queued for retry
        """
        conn = await self.db.get_connection()
        await conn.execute(
            """UPDATE embedding_queue 
               SET status = ?, attempts = 0, error = NULL
               WHERE status = ? AND attempts < ?""",
            (EmbeddingStatus.PENDING.value, EmbeddingStatus.FAILED.value, self.max_retries)
        )
        await conn.commit()
        
        cursor = await conn.execute(
            "SELECT changes()"
        )
        changes = (await cursor.fetchone())[0]
        return changes
    
    def on_progress(self, callback: Callable[[EmbeddingProgress], None]):
        """Register progress callback."""
        self._progress_callbacks.append(callback)
    
    # ---- Internal ----
    
    async def _ensure_table(self):
        """Create embedding queue table if not exists."""
        conn = await self.db.get_connection()
        await conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.PROGRESS_TABLE} (
                page_id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                gate_class TEXT DEFAULT 'routine',
                status TEXT DEFAULT 'pending',
                attempts INTEGER DEFAULT 0,
                error TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_eq_status ON {self.PROGRESS_TABLE}(status)
        """)
        await conn.commit()
    
    async def _worker_loop(self):
        """Background worker loop."""
        while self._running:
            try:
                processed = await self._process_batch()
                
                if processed == 0:
                    # No work to do, wait longer
                    await asyncio.sleep(5.0)
                else:
                    # Short sleep between batches
                    await asyncio.sleep(0.5)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Embedding worker error: {e}")
                await asyncio.sleep(10.0)
    
    async def _process_batch(self) -> int:
        """Process a batch of pending embeddings.
        
        Returns:
            Number of embeddings processed in this batch
        """
        async with self._semaphore:
            conn = await self.db.get_connection()
            
            # Get pending items
            cursor = await conn.execute(
                f"""SELECT page_id, content, gate_class, attempts 
                    FROM {self.PROGRESS_TABLE}
                    WHERE status = ?
                    ORDER BY created_at ASC
                    LIMIT ?""",
                (EmbeddingStatus.PENDING.value, self.batch_size)
            )
            rows = await cursor.fetchall()
            
            if not rows:
                return 0
            
            # Mark as processing
            page_ids = [row[0] for row in rows]
            for pid in page_ids:
                await conn.execute(
                    f"UPDATE {self.PROGRESS_TABLE} SET status = ?, updated_at = ? WHERE page_id = ?",
                    (EmbeddingStatus.PROCESSING.value, datetime.now(timezone.utc).isoformat(), pid)
                )
            await conn.commit()
            
            # Generate embeddings
            contents = [row[1] for row in rows]
            
            try:
                embeddings = self._generate_embeddings(contents)
                
                # Store embeddings
                for i, (page_id, _, _, attempts) in enumerate(rows):
                    try:
                        if embeddings is not None and i < len(embeddings):
                            emb_bytes = self._embedding_to_bytes(embeddings[i])
                            await conn.execute(
                                "UPDATE pages SET embedding = ?, updated_at = ? WHERE id = ?",
                                (emb_bytes, datetime.now(timezone.utc).isoformat(), page_id)
                            )
                        
                        await conn.execute(
                            f"UPDATE {self.PROGRESS_TABLE} SET status = ?, attempts = ?, updated_at = ? WHERE page_id = ?",
                            (EmbeddingStatus.COMPLETED.value, attempts + 1, datetime.now(timezone.utc).isoformat(), page_id)
                        )
                    except Exception as e:
                        logger.warning(f"Failed to store embedding for {page_id}: {e}")
                        await conn.execute(
                            f"UPDATE {self.PROGRESS_TABLE} SET status = ?, error = ?, attempts = ?, updated_at = ? WHERE page_id = ?",
                            (EmbeddingStatus.FAILED.value, str(e)[:200], attempts + 1, datetime.now(timezone.utc).isoformat(), page_id)
                        )
                
                await conn.commit()
                
            except Exception as e:
                logger.error(f"Batch embedding failed: {e}")
                # Mark all as failed
                for page_id, _, _, attempts in rows:
                    await conn.execute(
                        f"UPDATE {self.PROGRESS_TABLE} SET status = ?, error = ?, attempts = ?, updated_at = ? WHERE page_id = ?",
                        (EmbeddingStatus.FAILED.value, str(e)[:200], attempts + 1, datetime.now(timezone.utc).isoformat(), page_id)
                    )
                await conn.commit()
            
            # Notify progress
            progress = await self.get_progress()
            for callback in self._progress_callbacks:
                try:
                    callback(progress)
                except Exception:
                    pass
            
            return len(rows)
    
    def _generate_embeddings(self, contents: List[str]):
        """Generate embeddings for a batch of contents."""
        if self.embedding_model is None:
            # Return None to indicate model not available
            logger.warning("No embedding model configured")
            return None
        
        try:
            embeddings = self.embedding_model.encode_batch(contents, batch_size=self.batch_size)
            return embeddings
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            raise
    
    def _embedding_to_bytes(self, embedding) -> bytes:
        """Convert embedding to bytes for storage."""
        if self.embedding_model:
            return self.embedding_model.embedding_to_bytes(embedding)
        import numpy as np
        return np.array(embedding, dtype=np.float32).tobytes()
    
    async def _update_status(self, page_id: str, status: EmbeddingStatus):
        """Update embedding status."""
        conn = await self.db.get_connection()
        await conn.execute(
            f"""INSERT OR REPLACE INTO {self.PROGRESS_TABLE} 
               (page_id, content, gate_class, status, attempts, updated_at)
               VALUES (?, '', '', ?, 0, ?)""",
            (page_id, status.value, datetime.now(timezone.utc).isoformat())
        )
        await conn.commit()
