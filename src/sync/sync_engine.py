"""Multi-account email sync engine."""

import asyncio
import logging
import hashlib
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Callable, Awaitable
from dataclasses import dataclass, field

from .config import AccountManager, AccountConfig, AccountStatus
from .imap_sync import IMAPConnector, IMAPSyncError
from .parser import EmailParser
from .models import Email
from db.pgpool import SQLitePool, get_db

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """Result of a sync operation."""
    account_id: str
    total_fetched: int = 0
    new_emails: int = 0
    duplicates: int = 0
    errors: int = 0
    duration_ms: float = 0.0
    error_message: Optional[str] = None


@dataclass
class SyncProgress:
    """Sync progress tracker."""
    account_id: str
    folder: str
    total: int = 0
    fetched: int = 0
    status: str = "idle"  # idle, syncing, done, error


class SyncEngine:
    """Multi-account email sync engine.
    
    Features:
    - Concurrent sync for multiple accounts
    - Incremental sync via UID
    - Content-hash deduplication
    - Error recovery and retry
    - Progress callbacks
    """

    def __init__(
        self,
        account_manager: AccountManager,
        db: Optional[SQLitePool] = None,
        max_concurrent: int = 3,
        batch_size: int = 100,
    ):
        """Initialize sync engine.
        
        Args:
            account_manager: Account configuration manager
            db: Database pool (lazy init if not provided)
            max_concurrent: Max concurrent account syncs
            batch_size: Emails per batch
        """
        self.account_manager = account_manager
        self._db = db
        self.max_concurrent = max_concurrent
        self.batch_size = batch_size
        self.parser = EmailParser()
        
        self._connectors: Dict[str, IMAPConnector] = {}
        self._running = False
        self._sync_tasks: Dict[str, asyncio.Task] = {}
        self._progress_callbacks: List[Callable[[SyncProgress], Awaitable[None]]] = []
        self._result_callbacks: List[Callable[[SyncResult], Awaitable[None]]] = []

    async def _get_db(self) -> SQLitePool:
        """Get database pool."""
        if self._db is None:
            self._db = await get_db()
        return self._db

    def on_progress(self, callback: Callable[[SyncProgress], Awaitable[None]]) -> None:
        """Register progress callback."""
        self._progress_callbacks.append(callback)

    def on_result(self, callback: Callable[[SyncResult], Awaitable[None]]) -> None:
        """Register result callback."""
        self._result_callbacks.append(callback)

    async def _notify_progress(self, progress: SyncProgress) -> None:
        """Notify progress callbacks."""
        for cb in self._progress_callbacks:
            try:
                await cb(progress)
            except Exception as e:
                logger.warning(f"Progress callback error: {e}")

    async def _notify_result(self, result: SyncResult) -> None:
        """Notify result callbacks."""
        for cb in self._result_callbacks:
            try:
                await cb(result)
            except Exception as e:
                logger.warning(f"Result callback error: {e}")

    async def sync_account(self, account: AccountConfig) -> SyncResult:
        """Sync a single account.
        
        Args:
            account: Account configuration
            
        Returns:
            Sync result
        """
        start_time = datetime.now(timezone.utc)
        result = SyncResult(account_id=account.account_id)
        
        connector = self._connectors.get(account.account_id)
        
        try:
            # Connect if needed
            if connector is None:
                connector = IMAPConnector(
                    email_address=account.email_address,
                    password=account.password_encrypted,  # MVP: stored as-is
                    server=account.server or None,
                    port=account.port,
                )
                self._connectors[account.account_id] = connector
            
            # Mark as syncing
            self.account_manager.update_sync_state(
                account.account_id, account.last_uid,
                status=AccountStatus.SYNCING.value
            )
            
            # Connect
            await connector.connect()
            
            total_new = 0
            total_dup = 0
            total_err = 0
            max_uid = account.last_uid
            
            for folder in account.folders:
                # Select folder
                msg_count = await connector.select_folder(folder)
                
                if msg_count == 0:
                    continue
                
                # Fetch UIDs since last sync
                uids = await connector.fetch_message_uids(
                    start_uid=account.last_uid + 1
                )
                
                if not uids:
                    continue
                
                progress = SyncProgress(
                    account_id=account.account_id,
                    folder=folder,
                    total=len(uids),
                )
                
                # Process in batches
                for i in range(0, len(uids), self.batch_size):
                    batch = uids[i:i + self.batch_size]
                    
                    for uid in batch:
                        try:
                            # Fetch headers first
                            headers = await connector.fetch_message_headers(uid)
                            if not headers:
                                continue
                            
                            # For MVP, we only have header fetch
                            # Full message fetch would be: connector.fetch_message(uid)
                            
                            # Calculate content hash for dedup
                            message_id = headers.get("Message-ID", "")
                            content_hash = hashlib.sha256(
                                f"{account.email_address}:{uid}:{message_id}".encode()
                            ).hexdigest()[:32]
                            
                            # Check for duplicates
                            db = await self._get_db()
                            conn = await db.get_connection()
                            
                            cursor = await conn.execute(
                                "SELECT id FROM pages WHERE id = ?",
                                (f"email:{content_hash}",)
                            )
                            existing = await cursor.fetchone()
                            
                            if existing:
                                total_dup += 1
                                continue
                            
                            # Store email (header only for MVP)
                            subject = headers.get("Subject", "(No Subject)")
                            from_addr = headers.get("From", "")
                            to_addrs = headers.get("To", "")
                            date_str = headers.get("Date", "")
                            
                            metadata = {
                                "account_id": account.account_id,
                                "uid": uid,
                                "folder": folder,
                                "message_id": message_id,
                                "from": from_addr,
                                "to": to_addrs,
                                "date": date_str,
                                "content_hash": content_hash,
                            }
                            
                            await conn.execute(
                                """INSERT OR IGNORE INTO pages 
                                   (id, type, content, metadata, gate_class, created_at, updated_at)
                                   VALUES (?, 'email', ?, ?, 'routine', ?, ?)""",
                                (
                                    f"email:{content_hash}",
                                    subject,
                                    json_dumps(metadata),
                                    now_iso(),
                                    now_iso(),
                                )
                            )
                            await conn.commit()
                            
                            total_new += 1
                            max_uid = max(max_uid, uid)
                            
                        except Exception as e:
                            logger.warning(f"Error processing UID {uid}: {e}")
                            total_err += 1
                    
                    # Update progress
                    progress.fetched = min(i + self.batch_size, len(uids))
                    progress.status = "syncing"
                    await self._notify_progress(progress)
                
                progress.status = "done"
                await self._notify_progress(progress)
            
            # Update sync state
            self.account_manager.update_sync_state(
                account.account_id, max_uid,
                status=AccountStatus.IDLE.value
            )
            
            result.total_fetched = total_new + total_dup
            result.new_emails = total_new
            result.duplicates = total_dup
            result.errors = total_err
            
        except IMAPSyncError as e:
            result.error_message = str(e)
            result.errors = 1
            self.account_manager.update_sync_state(
                account.account_id, account.last_uid,
                status=AccountStatus.ERROR.value,
                error=str(e)
            )
            
        except Exception as e:
            result.error_message = f"Unexpected error: {e}"
            result.errors = 1
            self.account_manager.update_sync_state(
                account.account_id, account.last_uid,
                status=AccountStatus.ERROR.value,
                error=str(e)
            )
            
        finally:
            # Don't disconnect - keep connection for next sync
            end_time = datetime.now(timezone.utc)
            duration = (end_time - start_time).total_seconds() * 1000
            result.duration_ms = duration
            
            await self._notify_result(result)
        
        return result

    async def sync_all(self) -> List[SyncResult]:
        """Sync all active accounts concurrently.
        
        Returns:
            List of sync results
        """
        accounts = self.account_manager.get_active_accounts()
        
        if not accounts:
            logger.info("No active accounts to sync")
            return []
        
        logger.info(f"Starting sync for {len(accounts)} accounts")
        
        # Limit concurrency
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        async def _sync_with_semaphore(account: AccountConfig) -> SyncResult:
            async with semaphore:
                return await self.sync_account(account)
        
        # Run all syncs concurrently
        tasks = [_sync_with_semaphore(acc) for acc in accounts]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle exceptions
        final_results = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                final_results.append(SyncResult(
                    account_id=accounts[i].account_id,
                    errors=1,
                    error_message=str(r)
                ))
            else:
                final_results.append(r)
        
        logger.info(f"Sync complete: {len(final_results)} accounts")
        return final_results

    async def shutdown(self) -> None:
        """Shutdown sync engine and close all connections."""
        self._running = False
        
        # Cancel running tasks
        for task in self._sync_tasks.values():
            task.cancel()
        
        # Close all IMAP connections
        for connector in self._connectors.values():
            try:
                await connector.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting: {e}")
        
        self._connectors.clear()
        logger.info("Sync engine shutdown complete")


def json_dumps(obj: Any) -> str:
    """JSON serialize helper."""
    import json
    return json.dumps(obj, ensure_ascii=False, default=str)


def now_iso() -> str:
    """Current time in ISO format."""
    return datetime.now(timezone.utc).isoformat()
