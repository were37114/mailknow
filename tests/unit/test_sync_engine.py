"""Tests for sync config and multi-account support."""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sync.config import AccountConfig, AccountManager, AccountStatus


class TestAccountConfig:
    """Tests for AccountConfig dataclass."""

    def test_create_account_config(self):
        """Test creating an account config."""
        config = AccountConfig(
            account_id="test123",
            email_address="user@gmail.com",
            provider="gmail",
            server="imap.gmail.com",
            port=993,
            password_encrypted="test_password"
        )
        assert config.email_address == "user@gmail.com"
        assert config.provider == "gmail"
        assert config.status == AccountStatus.IDLE.value

    def test_auto_generate_id(self):
        """Test auto-generating account ID from email."""
        config = AccountConfig(
            account_id="",
            email_address="user@gmail.com",
        )
        # Should generate ID from email
        assert len(config.account_id) == 16

    def test_auto_display_name(self):
        """Test auto-setting display name from email."""
        config = AccountConfig(
            account_id="test123",
            email_address="user@gmail.com",
        )
        assert config.display_name == "user@gmail.com"

    def test_custom_display_name(self):
        """Test custom display name."""
        config = AccountConfig(
            account_id="test123",
            email_address="user@gmail.com",
            display_name="My Gmail"
        )
        assert config.display_name == "My Gmail"

    def test_default_folders(self):
        """Test default folders list."""
        config = AccountConfig(
            account_id="test123",
            email_address="user@gmail.com",
        )
        assert config.folders == ["INBOX"]

    def test_custom_folders(self):
        """Test custom folders list."""
        config = AccountConfig(
            account_id="test123",
            email_address="user@gmail.com",
            folders=["INBOX", "Sent", "Archive"]
        )
        assert len(config.folders) == 3


class TestAccountManager:
    """Tests for AccountManager."""

    @pytest.fixture
    def temp_dir(self):
        """Create temp directory for tests."""
        with tempfile.TemporaryDirectory() as d:
            yield Path(d)

    @pytest.fixture
    def manager(self, temp_dir):
        """Create account manager with temp directory."""
        return AccountManager(config_dir=temp_dir)

    def test_empty_manager(self, manager):
        """Test empty manager has no accounts."""
        assert len(manager.get_all_accounts()) == 0

    def test_add_account(self, manager):
        """Test adding an account."""
        config = AccountConfig(
            account_id="acc1",
            email_address="user@gmail.com",
            provider="gmail",
            server="imap.gmail.com",
            password_encrypted="pass1"
        )
        result = manager.add_account(config)
        assert result.account_id == "acc1"
        assert len(manager.get_all_accounts()) == 1

    def test_add_duplicate_account(self, manager):
        """Test adding duplicate account raises error."""
        config = AccountConfig(
            account_id="acc1",
            email_address="user@gmail.com",
            provider="gmail",
            server="imap.gmail.com",
            password_encrypted="pass1"
        )
        manager.add_account(config)
        with pytest.raises(ValueError, match="already exists"):
            manager.add_account(config)

    def test_remove_account(self, manager):
        """Test removing an account."""
        config = AccountConfig(
            account_id="acc1",
            email_address="user@gmail.com",
            provider="gmail",
            server="imap.gmail.com",
            password_encrypted="pass1"
        )
        manager.add_account(config)
        assert manager.remove_account("acc1") is True
        assert len(manager.get_all_accounts()) == 0

    def test_remove_nonexistent_account(self, manager):
        """Test removing non-existent account."""
        assert manager.remove_account("nonexistent") is False

    def test_get_account(self, manager):
        """Test getting an account by ID."""
        config = AccountConfig(
            account_id="acc1",
            email_address="user@gmail.com",
            provider="gmail",
            server="imap.gmail.com",
            password_encrypted="pass1"
        )
        manager.add_account(config)
        result = manager.get_account("acc1")
        assert result is not None
        assert result.email_address == "user@gmail.com"

    def test_get_nonexistent_account(self, manager):
        """Test getting non-existent account."""
        assert manager.get_account("nonexistent") is None

    def test_update_account(self, manager):
        """Test updating account fields."""
        config = AccountConfig(
            account_id="acc1",
            email_address="user@gmail.com",
            provider="gmail",
            server="imap.gmail.com",
            password_encrypted="pass1"
        )
        manager.add_account(config)
        updated = manager.update_account("acc1", display_name="My Gmail")
        assert updated is not None
        assert updated.display_name == "My Gmail"

    def test_update_sync_state(self, manager):
        """Test updating sync state."""
        config = AccountConfig(
            account_id="acc1",
            email_address="user@gmail.com",
            provider="gmail",
            server="imap.gmail.com",
            password_encrypted="pass1"
        )
        manager.add_account(config)
        manager.update_sync_state(
            "acc1",
            last_uid=12345,
            status=AccountStatus.SYNCING.value
        )
        account = manager.get_account("acc1")
        assert account.last_uid == 12345
        assert account.status == AccountStatus.SYNCING.value

    def test_update_sync_error(self, manager):
        """Test updating sync error state."""
        config = AccountConfig(
            account_id="acc1",
            email_address="user@gmail.com",
            provider="gmail",
            server="imap.gmail.com",
            password_encrypted="pass1"
        )
        manager.add_account(config)
        manager.update_sync_state(
            "acc1",
            last_uid=100,
            status=AccountStatus.ERROR.value,
            error="Connection timeout"
        )
        account = manager.get_account("acc1")
        assert account.status == AccountStatus.ERROR.value
        assert account.error_count == 1
        assert account.last_error == "Connection timeout"

    def test_persistence(self, temp_dir):
        """Test that accounts persist across manager instances."""
        manager1 = AccountManager(config_dir=temp_dir)
        config = AccountConfig(
            account_id="acc1",
            email_address="user@gmail.com",
            provider="gmail",
            server="imap.gmail.com",
            password_encrypted="pass1"
        )
        manager1.add_account(config)

        # Create new manager instance
        manager2 = AccountManager(config_dir=temp_dir)
        assert len(manager2.get_all_accounts()) == 1
        assert manager2.get_account("acc1").email_address == "user@gmail.com"

    def test_get_active_accounts(self, manager):
        """Test getting active accounts (excluding disabled)."""
        config1 = AccountConfig(
            account_id="acc1",
            email_address="user1@gmail.com",
            provider="gmail",
            server="imap.gmail.com",
            password_encrypted="pass1"
        )
        config2 = AccountConfig(
            account_id="acc2",
            email_address="user2@outlook.com",
            provider="outlook",
            server="outlook.office365.com",
            password_encrypted="pass2",
            status=AccountStatus.DISABLED.value
        )
        manager.add_account(config1)
        manager.add_account(config2)

        active = manager.get_active_accounts()
        assert len(active) == 1
        assert active[0].account_id == "acc1"

    def test_multiple_accounts(self, manager):
        """Test managing multiple accounts."""
        for i in range(3):
            config = AccountConfig(
                account_id=f"acc{i}",
                email_address=f"user{i}@gmail.com",
                provider="gmail",
                server="imap.gmail.com",
                password_encrypted=f"pass{i}"
            )
            manager.add_account(config)

        assert len(manager.get_all_accounts()) == 3


class TestSyncEngine:
    """Tests for SyncEngine."""

    @pytest.fixture
    def temp_dir(self):
        """Create temp directory for tests."""
        with tempfile.TemporaryDirectory() as d:
            yield Path(d)

    @pytest.fixture
    def account_manager(self, temp_dir):
        """Create account manager."""
        return AccountManager(config_dir=temp_dir)

    def test_create_sync_engine(self, account_manager):
        """Test creating sync engine."""
        from sync.sync_engine import SyncEngine
        engine = SyncEngine(account_manager=account_manager)
        assert engine.max_concurrent == 3
        assert engine.batch_size == 100

    def test_custom_concurrency(self, account_manager):
        """Test custom max concurrent syncs."""
        from sync.sync_engine import SyncEngine
        engine = SyncEngine(
            account_manager=account_manager,
            max_concurrent=5,
            batch_size=50
        )
        assert engine.max_concurrent == 5
        assert engine.batch_size == 50

    @pytest.mark.asyncio
    async def test_sync_all_empty(self, account_manager):
        """Test sync with no accounts."""
        from sync.sync_engine import SyncEngine
        engine = SyncEngine(account_manager=account_manager)
        results = await engine.sync_all()
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_sync_progress_callback(self, account_manager):
        """Test progress callback registration."""
        from sync.sync_engine import SyncEngine, SyncProgress
        engine = SyncEngine(account_manager=account_manager)

        received = []

        async def on_progress(p: SyncProgress):
            received.append(p)

        engine.on_progress(on_progress)
        assert len(engine._progress_callbacks) == 1

    @pytest.mark.asyncio
    async def test_sync_result_callback(self, account_manager):
        """Test result callback registration."""
        from sync.sync_engine import SyncEngine, SyncResult
        engine = SyncEngine(account_manager=account_manager)

        received = []

        async def on_result(r: SyncResult):
            received.append(r)

        engine.on_result(on_result)
        assert len(engine._result_callbacks) == 1

    @pytest.mark.asyncio
    async def test_sync_account_connection_error(self, account_manager):
        """Test sync with connection error."""
        from sync.sync_engine import SyncEngine
        engine = SyncEngine(account_manager=account_manager)

        config = AccountConfig(
            account_id="acc1",
            email_address="test@invalid.com",
            server="invalid.imap.server",
            port=993,
            password_encrypted="pass"
        )
        account_manager.add_account(config)

        result = await engine.sync_account(config)
        assert result.error_message is not None
        assert result.errors > 0
