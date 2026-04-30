"""Tests for sync robustness: dedup, reconnection, error handling."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from sync.robust import (
    ContentDeduplicator,
    DedupResult,
    ReconnectionManager,
    RetryConfig,
    SyncErrorHandler,
)
from sync.imap_sync import IMAPConnector


class TestContentDeduplicator:
    """Tests for ContentDeduplicator."""

    @pytest.fixture
    def dedup(self):
        return ContentDeduplicator(max_cache_size=100)

    def test_compute_hash_deterministic(self, dedup):
        """Test hash is deterministic."""
        h1 = dedup.compute_hash("acc1", 123, "<msg@test.com>")
        h2 = dedup.compute_hash("acc1", 123, "<msg@test.com>")
        assert h1 == h2
        assert len(h1) == 32

    def test_compute_hash_different_inputs(self, dedup):
        """Test different inputs produce different hashes."""
        h1 = dedup.compute_hash("acc1", 123, "<msg1@test.com>")
        h2 = dedup.compute_hash("acc1", 124, "<msg2@test.com>")
        assert h1 != h2

    def test_check_duplicate_new(self, dedup):
        """Test checking new (non-duplicate) content."""
        result = dedup.check_duplicate("hash_new_123")
        assert not result.is_duplicate
        assert result.content_hash == "hash_new_123"
        assert result.existing_id is None

    def test_check_duplicate_cached(self, dedup):
        """Test checking cached duplicate."""
        dedup.check_duplicate("hash_dup_123")
        result = dedup.check_duplicate("hash_dup_123")
        assert result.is_duplicate

    def test_check_duplicate_with_existing_id(self, dedup):
        """Test checking duplicate with existing DB ID."""
        result = dedup.check_duplicate("hash_x", existing_id="email:hash_x")
        assert result.is_duplicate
        assert result.existing_id == "email:hash_x"

    def test_lru_eviction(self):
        """Test LRU cache eviction."""
        dedup = ContentDeduplicator(max_cache_size=3)
        
        dedup.check_duplicate("h1")
        dedup.check_duplicate("h2")
        dedup.check_duplicate("h3")
        assert dedup.cache_size == 3
        
        # Adding h4 should evict h1
        dedup.check_duplicate("h4")
        assert dedup.cache_size == 3
        
        # h1 should no longer be in cache
        result = dedup.check_duplicate("h1")
        # It's not in cache, but since existing_id is None, it's not a dup
        assert not result.is_duplicate

    def test_clear_cache(self, dedup):
        """Test clearing cache."""
        dedup.check_duplicate("h1")
        dedup.check_duplicate("h2")
        assert dedup.cache_size == 2
        
        dedup.clear_cache()
        assert dedup.cache_size == 0


class TestRetryConfig:
    """Tests for RetryConfig."""

    def test_default_config(self):
        """Test default retry config."""
        config = RetryConfig()
        assert config.max_retries == 3
        assert config.initial_delay == 1.0
        assert config.max_delay == 60.0
        assert config.backoff_factor == 2.0

    def test_custom_config(self):
        """Test custom retry config."""
        config = RetryConfig(max_retries=5, initial_delay=0.5)
        assert config.max_retries == 5
        assert config.initial_delay == 0.5


class TestReconnectionManager:
    """Tests for ReconnectionManager."""

    @pytest.fixture
    def mock_connector(self):
        connector = MagicMock(spec=IMAPConnector)
        connector._client = MagicMock()
        connector.connect = AsyncMock()
        connector.disconnect = AsyncMock()
        return connector

    @pytest.fixture
    def manager(self, mock_connector):
        return ReconnectionManager(
            connector=mock_connector,
            retry_config=RetryConfig(
                max_retries=2,
                initial_delay=0.01,  # Fast for tests
                max_delay=0.1,
            )
        )

    def test_initial_state(self, manager):
        """Test initial manager state."""
        assert manager.is_healthy is True
        assert manager.retry_count == 0

    @pytest.mark.asyncio
    async def test_successful_operation(self, manager):
        """Test successful operation."""
        async def op():
            return "success"
        
        result = await manager.execute_with_retry(op, "test_op")
        assert result == "success"
        assert manager.retry_count == 0
        assert manager.is_healthy is True

    @pytest.mark.asyncio
    async def test_retry_on_retryable_error(self, manager):
        """Test retry on retryable error (timeout)."""
        call_count = 0
        
        async def op():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("Connection timeout")
            return "success"
        
        result = await manager.execute_with_retry(op, "test_op")
        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_non_retryable_error(self, manager):
        """Test non-retryable error raises immediately."""
        async def op():
            raise ValueError("Invalid credentials")
        
        with pytest.raises(ValueError):
            await manager.execute_with_retry(op, "test_op")

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self, manager):
        """Test max retries exceeded."""
        async def op():
            raise ConnectionError("Connection timeout")
        
        with pytest.raises(ConnectionError):
            await manager.execute_with_retry(op, "test_op")
        
        assert manager.is_healthy is False

    @pytest.mark.asyncio
    async def test_reconnect_on_failure(self, manager, mock_connector):
        """Test reconnection attempt on failure."""
        call_count = 0
        
        async def op():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("Network timeout")
            return "ok"
        
        result = await manager.execute_with_retry(op, "test_op")
        assert result == "ok"
        # Should have attempted reconnect
        assert mock_connector.disconnect.called or mock_connector.connect.called

    def test_reset(self, manager):
        """Test reset retry counter."""
        manager._retry_count = 5
        manager.reset()
        assert manager.retry_count == 0

    @pytest.mark.asyncio
    async def test_health_check_connected(self, manager, mock_connector):
        """Test health check with connected client."""
        mock_connector._client.noop = AsyncMock(return_value=("OK", []))
        result = await manager.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_disconnected(self, manager, mock_connector):
        """Test health check with disconnected client."""
        mock_connector._client = None
        result = await manager.health_check()
        assert result is False


class TestSyncErrorHandler:
    """Tests for SyncErrorHandler."""

    @pytest.fixture
    def handler(self):
        return SyncErrorHandler(max_errors=100)

    def test_record_error(self, handler):
        """Test recording an error."""
        record = handler.record_error(
            account_id="acc1",
            folder="INBOX",
            uid=123,
            error=ConnectionError("Timeout")
        )
        assert record.account_id == "acc1"
        assert record.error_type == "ConnectionError"
        assert record.retryable is True

    def test_record_non_retryable_error(self, handler):
        """Test recording a non-retryable error."""
        record = handler.record_error(
            account_id="acc1",
            folder="INBOX",
            uid=456,
            error=ValueError("Invalid credentials")
        )
        assert record.retryable is False

    def test_get_all_errors(self, handler):
        """Test getting all errors."""
        handler.record_error("acc1", "INBOX", 1, ConnectionError("err1"))
        handler.record_error("acc2", "INBOX", 2, ValueError("err2"))
        
        errors = handler.get_errors()
        assert len(errors) == 2

    def test_get_errors_by_account(self, handler):
        """Test filtering errors by account."""
        handler.record_error("acc1", "INBOX", 1, ConnectionError("err1"))
        handler.record_error("acc2", "INBOX", 2, ValueError("err2"))
        
        errors = handler.get_errors(account_id="acc1")
        assert len(errors) == 1
        assert errors[0].account_id == "acc1"

    def test_get_retryable_errors(self, handler):
        """Test filtering retryable errors."""
        handler.record_error("acc1", "INBOX", 1, ConnectionError("timeout"))
        handler.record_error("acc1", "INBOX", 2, ValueError("invalid"))
        
        errors = handler.get_errors(retryable_only=True)
        assert len(errors) == 1
        assert errors[0].retryable is True

    def test_error_summary(self, handler):
        """Test error summary."""
        handler.record_error("acc1", "INBOX", 1, ConnectionError("timeout"))
        handler.record_error("acc1", "INBOX", 2, ConnectionError("timeout"))
        handler.record_error("acc2", "INBOX", 3, ValueError("bad"))
        
        summary = handler.get_error_summary()
        assert summary["total"] == 3
        assert summary["retryable"] == 2
        assert summary["by_type"]["ConnectionError"] == 2
        assert summary["by_account"]["acc1"] == 2

    def test_clear_all_errors(self, handler):
        """Test clearing all errors."""
        handler.record_error("acc1", "INBOX", 1, ConnectionError("err"))
        count = handler.clear_errors()
        assert count == 1
        assert len(handler.get_errors()) == 0

    def test_clear_errors_by_account(self, handler):
        """Test clearing errors for specific account."""
        handler.record_error("acc1", "INBOX", 1, ConnectionError("err"))
        handler.record_error("acc2", "INBOX", 2, ConnectionError("err"))
        
        count = handler.clear_errors(account_id="acc1")
        assert count == 1
        assert len(handler.get_errors()) == 1

    def test_max_errors_limit(self):
        """Test max errors limit."""
        handler = SyncErrorHandler(max_errors=5)
        
        for i in range(10):
            handler.record_error("acc1", "INBOX", i, ConnectionError(f"err{i}"))
        
        assert len(handler.get_errors()) <= 5

    def test_empty_summary(self, handler):
        """Test summary with no errors."""
        summary = handler.get_error_summary()
        assert summary["total"] == 0
