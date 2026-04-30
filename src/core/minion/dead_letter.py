"""Dead letter queue for failed Minion tasks.

V5.2 spec:
- Failed tasks automatically enter dead_letter queue
- Alert on new dead_letter entries
- Manual retry support
- Max retry limit (3)
"""

import json
import logging
import uuid
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger(__name__)


class DeadLetterReason(str, Enum):
    """Reasons for task failure."""
    LLM_ERROR = "llm_error"                 # LLM call failed
    LLM_TIMEOUT = "llm_timeout"             # LLM call timed out
    BUDGET_EXCEEDED = "budget_exceeded"      # Token budget exceeded
    DB_ERROR = "db_error"                    # Database error
    PARSE_ERROR = "parse_error"              # Response parse error
    VALIDATION_ERROR = "validation_error"    # Output validation failed
    RETRY_EXHAUSTED = "retry_exhausted"      # All retries failed
    UNKNOWN = "unknown"                      # Unknown error


@dataclass
class DeadLetterEntry:
    """A dead letter entry for a failed task."""
    entry_id: str = field(default_factory=lambda: str(uuid.uuid4())[:16])
    task_type: str = ""
    task_id: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    
    # Failure info
    reason: DeadLetterReason = DeadLetterReason.UNKNOWN
    error_message: str = ""
    original_error: str = ""
    
    # Retry tracking
    retry_count: int = 0
    max_retries: int = 3
    last_retry_at: Optional[str] = None
    
    # Timestamps
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved: bool = False
    resolved_at: Optional[str] = None
    resolved_by: str = ""  # "retry" or "discard"
    
    @property
    def can_retry(self) -> bool:
        """Whether this entry can be retried."""
        return self.retry_count < self.max_retries and not self.resolved


class DeadLetterQueue:
    """Dead letter queue for failed tasks.
    
    Features:
    - Automatic entry on task failure
    - Retry with backoff
    - Max retry limit
    - Manual retry/discard
    - Statistics
    """
    
    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries
        self._entries: Dict[str, DeadLetterEntry] = {}
        self._alert_callbacks: List = []
    
    def add(
        self,
        task_type: str,
        task_id: str,
        payload: Dict[str, Any],
        reason: DeadLetterReason = DeadLetterReason.UNKNOWN,
        error_message: str = "",
        original_error: str = "",
    ) -> DeadLetterEntry:
        """Add a failed task to the dead letter queue."""
        entry = DeadLetterEntry(
            task_type=task_type,
            task_id=task_id,
            payload=payload,
            reason=reason,
            error_message=error_message,
            original_error=original_error,
            max_retries=self.max_retries,
        )
        
        self._entries[entry.entry_id] = entry
        
        # Alert
        logger.warning(
            f"Dead letter: {task_type}/{task_id} failed ({reason.value}): {error_message}"
        )
        self._fire_alert(entry)
        
        return entry
    
    def retry(self, entry_id: str) -> Optional[DeadLetterEntry]:
        """Mark entry for retry."""
        entry = self._entries.get(entry_id)
        if not entry:
            return None
        
        if not entry.can_retry:
            logger.warning(f"Entry {entry_id} cannot be retried (retries={entry.retry_count}/{entry.max_retries})")
            return None
        
        entry.retry_count += 1
        entry.last_retry_at = datetime.now(timezone.utc).isoformat()
        
        logger.info(f"Retrying dead letter {entry_id} (attempt {entry.retry_count}/{entry.max_retries})")
        return entry
    
    def resolve(self, entry_id: str, resolved_by: str = "retry") -> bool:
        """Mark entry as resolved."""
        entry = self._entries.get(entry_id)
        if not entry:
            return False
        
        entry.resolved = True
        entry.resolved_at = datetime.now(timezone.utc).isoformat()
        entry.resolved_by = resolved_by
        
        logger.info(f"Dead letter {entry_id} resolved by {resolved_by}")
        return True
    
    def discard(self, entry_id: str) -> bool:
        """Discard a dead letter entry (mark as resolved by discard)."""
        return self.resolve(entry_id, resolved_by="discard")
    
    def discard_all_resolved(self) -> int:
        """Remove all resolved entries."""
        resolved_ids = [
            eid for eid, entry in self._entries.items()
            if entry.resolved
        ]
        for eid in resolved_ids:
            del self._entries[eid]
        return len(resolved_ids)
    
    def get_pending(self) -> List[DeadLetterEntry]:
        """Get all unresolved entries."""
        return [e for e in self._entries.values() if not e.resolved]
    
    def get_retryable(self) -> List[DeadLetterEntry]:
        """Get entries that can be retried."""
        return [e for e in self._entries.values() if e.can_retry]
    
    def get_entry(self, entry_id: str) -> Optional[DeadLetterEntry]:
        """Get a specific entry."""
        return self._entries.get(entry_id)
    
    def on_alert(self, callback):
        """Register alert callback."""
        self._alert_callbacks.append(callback)
    
    def _fire_alert(self, entry: DeadLetterEntry):
        """Fire alert callbacks."""
        for cb in self._alert_callbacks:
            try:
                cb(entry)
            except Exception as e:
                logger.error(f"Alert callback error: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get dead letter queue statistics."""
        entries = list(self._entries.values())
        pending = [e for e in entries if not e.resolved]
        retryable = [e for e in entries if e.can_retry]
        
        by_reason: Dict[str, int] = {}
        for e in entries:
            by_reason[e.reason.value] = by_reason.get(e.reason.value, 0) + 1
        
        by_type: Dict[str, int] = {}
        for e in entries:
            by_type[e.task_type] = by_type.get(e.task_type, 0) + 1
        
        return {
            "total": len(entries),
            "pending": len(pending),
            "retryable": len(retryable),
            "resolved": len(entries) - len(pending),
            "by_reason": by_reason,
            "by_type": by_type,
        }


# Global instance
_queue: Optional[DeadLetterQueue] = None


def get_dead_letter_queue() -> DeadLetterQueue:
    """Get global dead letter queue instance."""
    global _queue
    if _queue is None:
        _queue = DeadLetterQueue()
    return _queue
