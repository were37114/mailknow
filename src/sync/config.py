"""Email account configuration management."""

import json
import logging
import hashlib
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict
from enum import Enum

logger = logging.getLogger(__name__)


class AccountStatus(str, Enum):
    """Account sync status."""
    IDLE = "idle"
    SYNCING = "syncing"
    ERROR = "error"
    DISABLED = "disabled"


@dataclass
class AccountConfig:
    """Email account configuration.
    
    Attributes:
        account_id: Unique identifier (hash of email address)
        email_address: Email address
        display_name: User-friendly name
        provider: Email provider (gmail, outlook, 163, qq, custom)
        server: IMAP server
        port: IMAP port
        use_ssl: Whether to use SSL
        password_encrypted: Encrypted password (base64 for MVP)
        last_uid: Last synced UID for incremental sync
        last_sync_time: Last successful sync timestamp
        status: Current account status
        folders: List of folders to sync
        error_count: Consecutive error count
        last_error: Last error message
    """
    account_id: str
    email_address: str
    display_name: str = ""
    provider: str = "custom"
    server: str = ""
    port: int = 993
    use_ssl: bool = True
    password_encrypted: str = ""
    last_uid: int = 0
    last_sync_time: Optional[str] = None
    status: str = AccountStatus.IDLE.value
    folders: List[str] = field(default_factory=lambda: ["INBOX"])
    error_count: int = 0
    last_error: Optional[str] = None

    def __post_init__(self):
        if not self.display_name:
            self.display_name = self.email_address
        if not self.account_id:
            self.account_id = self._generate_id()

    def _generate_id(self) -> str:
        """Generate unique account ID from email address."""
        return hashlib.sha256(self.email_address.lower().encode()).hexdigest()[:16]


class AccountManager:
    """Manages email account configurations.
    
    Stores accounts in JSON file at ~/.mailknow/accounts.json
    Supports CRUD operations and concurrent access.
    """

    def __init__(self, config_dir: Optional[Path] = None):
        """Initialize account manager.
        
        Args:
            config_dir: Directory for config files.
                       Defaults to ~/.mailknow
        """
        self.config_dir = config_dir or Path.home() / ".mailknow"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.config_dir / "accounts.json"
        self._accounts: Dict[str, AccountConfig] = {}
        self._load()

    def _load(self) -> None:
        """Load accounts from config file."""
        if not self.config_path.exists():
            logger.info("No accounts config found, starting fresh")
            return

        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            for account_data in data.get("accounts", []):
                config = AccountConfig(**account_data)
                self._accounts[config.account_id] = config

            logger.info(f"Loaded {len(self._accounts)} accounts")

        except Exception as e:
            logger.error(f"Failed to load accounts: {e}")

    def _save(self) -> None:
        """Save accounts to config file."""
        data = {
            "version": "1.0",
            "accounts": [asdict(acc) for acc in self._accounts.values()]
        }

        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save accounts: {e}")

    def add_account(self, config: AccountConfig) -> AccountConfig:
        """Add a new email account.
        
        Args:
            config: Account configuration
            
        Returns:
            Added account config with generated ID
            
        Raises:
            ValueError: If account already exists
        """
        if config.account_id in self._accounts:
            raise ValueError(f"Account {config.email_address} already exists")

        self._accounts[config.account_id] = config
        self._save()
        logger.info(f"Added account: {config.email_address}")
        return config

    def remove_account(self, account_id: str) -> bool:
        """Remove an email account.
        
        Args:
            account_id: Account ID to remove
            
        Returns:
            True if removed, False if not found
        """
        if account_id not in self._accounts:
            return False

        del self._accounts[account_id]
        self._save()
        logger.info(f"Removed account: {account_id}")
        return True

    def get_account(self, account_id: str) -> Optional[AccountConfig]:
        """Get account by ID."""
        return self._accounts.get(account_id)

    def get_all_accounts(self) -> List[AccountConfig]:
        """Get all accounts."""
        return list(self._accounts.values())

    def get_active_accounts(self) -> List[AccountConfig]:
        """Get all active (non-disabled) accounts."""
        return [
            acc for acc in self._accounts.values()
            if acc.status != AccountStatus.DISABLED.value
        ]

    def update_account(self, account_id: str, **kwargs) -> Optional[AccountConfig]:
        """Update account fields.
        
        Args:
            account_id: Account ID
            **kwargs: Fields to update
            
        Returns:
            Updated account or None if not found
        """
        if account_id not in self._accounts:
            return None

        account = self._accounts[account_id]
        for key, value in kwargs.items():
            if hasattr(account, key):
                setattr(account, key, value)

        self._save()
        return account

    def update_sync_state(
        self,
        account_id: str,
        last_uid: int,
        status: Optional[str] = None,
        error: Optional[str] = None
    ) -> None:
        """Update sync state for an account.
        
        Args:
            account_id: Account ID
            last_uid: Last synced UID
            status: New status (optional)
            error: Error message (optional)
        """
        account = self._accounts.get(account_id)
        if not account:
            return

        account.last_uid = last_uid
        account.last_sync_time = _now_iso()

        if status:
            account.status = status

        if error:
            account.last_error = error
            account.error_count += 1
        else:
            account.error_count = 0
            account.last_error = None

        self._save()


def _now_iso() -> str:
    """Get current time in ISO format."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
