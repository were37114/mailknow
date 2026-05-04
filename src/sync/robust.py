"""Sync engine robustness: reconnection, dedup, error handling."""

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .config import AccountConfig, AccountStatus
from .imap_sync import IMAPConnector, IMAPSyncError

logger = logging.getLogger(__name__)


@dataclass
class DedupResult:
    """Result of deduplication check."""
    is_duplicate: bool
    content_hash: str
    existing_id: Optional[str] = None


class ContentDeduplicator:
    """Content-hash based email deduplication.

    Uses SHA-256 hash of (account_id + uid + message_id) for dedup.
    This prevents re-importing the same email on re-sync.
    """

    def __init__(self, max_cache_size: int = 10000):
        """Initialize deduplicator.

        Args:
            max_cache_size: Max cached hashes (LRU)
        """
        self._cache: Dict[str, str] = {}
        self._max_cache_size = max_cache_size

    def compute_hash(
        self,
        account_id: str,
        uid: int,
        message_id: str,
        extra: str = ""
    ) -> str:
        """Compute content hash for an email.

        Args:
            account_id: Account identifier
            uid: IMAP UID
            message_id: Email Message-ID header
            extra: Additional data for hash

        Returns:
            SHA-256 hex digest (first 32 chars)
        """
        raw = f"{account_id}:{uid}:{message_id}:{extra}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def check_duplicate(
        self,
        content_hash: str,
        existing_id: Optional[str] = None
    ) -> DedupResult:
        """Check if content hash is a duplicate.

        Args:
            content_hash: Content hash to check
            existing_id: Existing page ID if found in DB

        Returns:
            DedupResult indicating if duplicate
        """
        is_dup = content_hash in self._cache or existing_id is not None

        if not is_dup:
            self._add_to_cache(content_hash)

        return DedupResult(
            is_duplicate=is_dup,
            content_hash=content_hash,
            existing_id=existing_id
        )

    def _add_to_cache(self, content_hash: str) -> None:
        """Add hash to LRU cache."""
        if len(self._cache) >= self._max_cache_size:
            # Remove oldest entry (first key)
            oldest = next(iter(self._cache))
            del self._cache[oldest]

        self._cache[content_hash] = now_iso()

    def clear_cache(self) -> None:
        """Clear the dedup cache."""
        self._cache.clear()

    @property
    def cache_size(self) -> int:
        """Current cache size."""
        return len(self._cache)


@dataclass
class RetryConfig:
    """Retry configuration for IMAP operations."""
    max_retries: int = 3
    initial_delay: float = 1.0  # seconds
    max_delay: float = 60.0  # seconds
    backoff_factor: float = 2.0
    retryable_errors: List[str] = field(default_factory=lambda: [
        "timeout",
        "connection",
        "network",
        "temporarily",
        "too many",
        "rate limit",
    ])


class ReconnectionManager:
    """Manages IMAP connection reconnection with exponential backoff.

    Features:
    - Auto-reconnect on disconnect
    - Exponential backoff with jitter
    - Max retry limit
    - Connection health checks
    """

    def __init__(
        self,
        connector: IMAPConnector,
        retry_config: Optional[RetryConfig] = None,
    ):
        """Initialize reconnection manager.

        Args:
            connector: IMAP connector to manage
            retry_config: Retry configuration
        """
        self.connector = connector
        self.retry_config = retry_config or RetryConfig()
        self._retry_count = 0
        self._last_retry_time = 0.0
        self._is_healthy = True

    @property
    def is_healthy(self) -> bool:
        """Check if connection is healthy."""
        return self._is_healthy

    @property
    def retry_count(self) -> int:
        """Current retry count."""
        return self._retry_count

    def _is_retryable_error(self, error: Exception) -> bool:
        """Check if error is retryable."""
        error_str = str(error).lower()
        return any(kw in error_str for kw in self.retry_config.retryable_errors)

    def _calculate_delay(self) -> float:
        """Calculate delay with exponential backoff + jitter."""
        delay = min(
            self.retry_config.initial_delay * (self.retry_config.backoff_factor ** self._retry_count),
            self.retry_config.max_delay
        )
        # Add jitter (±20%)
        import random
        jitter = delay * 0.2 * (random.random() * 2 - 1)
        return max(0.1, delay + jitter)

    async def execute_with_retry(
        self,
        operation: Callable[[], Awaitable[Any]],
        operation_name: str = "operation"
    ) -> Any:
        """Execute an async operation with retry logic.

        Args:
            operation: Async callable to execute
            operation_name: Name for logging

        Returns:
            Operation result

        Raises:
            Exception: If all retries fail
        """
        last_error = None

        for attempt in range(self.retry_config.max_retries + 1):
            try:
                result = await operation()

                # Success - reset retry count
                if self._retry_count > 0:
                    logger.info(f"{operation_name} recovered after {self._retry_count} retries")
                self._retry_count = 0
                self._is_healthy = True
                return result

            except Exception as e:
                last_error = e

                if not self._is_retryable_error(e):
                    logger.error(f"{operation_name} non-retryable error: {e}")
                    self._is_healthy = False
                    raise

                self._retry_count += 1
                self._is_healthy = False

                if attempt < self.retry_config.max_retries:
                    delay = self._calculate_delay()
                    logger.warning(
                        f"{operation_name} failed (attempt {attempt + 1}/{self.retry_config.max_retries + 1}), "
                        f"retrying in {delay:.1f}s: {e}"
                    )
                    await asyncio.sleep(delay)

                    # Try to reconnect
                    try:
                        await self.connector.disconnect()
                        await self.connector.connect()
                        logger.info("Reconnected successfully")
                    except Exception as reconnect_error:
                        logger.warning(f"Reconnect failed: {reconnect_error}")
                else:
                    logger.error(
                        f"{operation_name} failed after {self.retry_config.max_retries + 1} attempts: {e}"
                    )

        raise last_error

    async def health_check(self) -> bool:
        """Perform connection health check.

        Returns:
            True if connection is healthy
        """
        try:
            if self.connector._client is None:
                self._is_healthy = False
                return False

            # Try a NOOP command to check connection
            result, _ = await self.connector._client.noop()
            self._is_healthy = (result == "OK")
            return self._is_healthy

        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            self._is_healthy = False
            return False

    def reset(self) -> None:
        """Reset retry counter."""
        self._retry_count = 0


class SyncErrorHandler:
    """Handles sync errors with categorization and reporting."""

    @dataclass
    class ErrorRecord:
        """Record of a sync error."""
        account_id: str
        folder: str
        uid: Optional[int]
        error_type: str
        error_message: str
        timestamp: str
        retryable: bool

    def __init__(self, max_errors: int = 1000):
        """Initialize error handler.

        Args:
            max_errors: Max errors to keep in memory
        """
        self._errors: list = []  # List[ErrorRecord]
        self._max_errors = max_errors

    def record_error(
        self,
        account_id: str,
        folder: str,
        uid: Optional[int],
        error: Exception
    ) -> ErrorRecord:
        """Record a sync error.

        Args:
            account_id: Account ID
            folder: IMAP folder
            uid: Message UID
            error: Exception

        Returns:
            ErrorRecord
        """
        error_type = type(error).__name__
        error_message = str(error)

        # Determine if retryable
        retryable = any(
            kw in error_message.lower()
            for kw in ["timeout", "connection", "network", "temporarily"]
        )

        record = self.ErrorRecord(
            account_id=account_id,
            folder=folder,
            uid=uid,
            error_type=error_type,
            error_message=error_message,
            timestamp=now_iso(),
            retryable=retryable
        )

        self._errors.append(record)

        # Trim if too many
        if len(self._errors) > self._max_errors:
            self._errors = self._errors[-self._max_errors:]

        logger.warning(f"Sync error [{error_type}]: {error_message} (account={account_id}, uid={uid})")

        return record

    def get_errors(
        self,
        account_id: Optional[str] = None,
        retryable_only: bool = False
    ) -> List[ErrorRecord]:
        """Get recorded errors.

        Args:
            account_id: Filter by account (optional)
            retryable_only: Only return retryable errors

        Returns:
            List of error records
        """
        errors = self._errors

        if account_id:
            errors = [e for e in errors if e.account_id == account_id]

        if retryable_only:
            errors = [e for e in errors if e.retryable]

        return errors

    def get_error_summary(self) -> Dict[str, Any]:
        """Get error summary statistics."""
        if not self._errors:
            return {"total": 0}

        by_type: Dict[str, int] = {}
        by_account: Dict[str, int] = {}
        retryable_count = 0

        for err in self._errors:
            by_type[err.error_type] = by_type.get(err.error_type, 0) + 1
            by_account[err.account_id] = by_account.get(err.account_id, 0) + 1
            if err.retryable:
                retryable_count += 1

        return {
            "total": len(self._errors),
            "retryable": retryable_count,
            "by_type": by_type,
            "by_account": by_account,
        }

    def clear_errors(self, account_id: Optional[str] = None) -> int:
        """Clear error records.

        Args:
            account_id: Clear for specific account (optional)

        Returns:
            Number of cleared errors
        """
        if account_id is None:
            count = len(self._errors)
            self._errors.clear()
            return count

        original = len(self._errors)
        self._errors = [e for e in self._errors if e.account_id != account_id]
        return original - len(self._errors)


def now_iso() -> str:
    """Current time in ISO format."""
    return datetime.now(timezone.utc).isoformat()
