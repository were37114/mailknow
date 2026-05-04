"""IMAP email synchronizer."""

import asyncio
import email
import imaplib
import logging
import ssl
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aioimaplib

from .models import Email, EmailAddress, EmailFlag, IMAPFolder

logger = logging.getLogger(__name__)


# Extend imaplib to support ID command for 163/126/QQ
imaplib.Commands['ID'] = ('AUTH', 'SELECTED')


class IMAPSyncError(Exception):
    """IMAP sync error."""
    pass


class IMAPConnector:
    """IMAP email connector with async support.

    Supports:
    - Gmail, Outlook, Yahoo, 163, QQ, etc.
    - OAuth2 (Gmail, Outlook) - future
    - SSL/TLS
    - Incremental sync via UID
    """

    # Common IMAP servers
    SERVERS = {
        "gmail": ("imap.gmail.com", 993),
        "outlook": ("outlook.office365.com", 993),
        "yahoo": ("imap.mail.yahoo.com", 993),
        "163": ("imap.163.com", 993),
        "qq": ("imap.qq.com", 993),
        "126": ("imap.126.com", 993),
    }

    def __init__(
        self,
        email_address: str,
        password: str,
        server: Optional[str] = None,
        port: int = 993,
    ):
        """Initialize IMAP connector.

        Args:
            email_address: Email address
            password: Password or app-specific password
            server: IMAP server (auto-detected if not provided)
            port: IMAP port (default 993 for SSL)
        """
        self.email_address = email_address
        self.password = password

        # Auto-detect server
        if server is None:
            detected = self._detect_server(email_address)
            if detected:
                server, port = detected
            else:
                raise IMAPSyncError(f"Unknown email provider for {email_address}")

        self.server = server
        self.port = port

        self._client: Optional[aioimaplib.IMAP4_SSL] = None
        self._selected_folder: Optional[str] = None

    def _detect_server(self, email_addr: str) -> Optional[tuple]:
        """Auto-detect IMAP server from email domain."""
        domain = email_addr.split("@")[-1].lower()

        for name, config in self.SERVERS.items():
            if name in domain:
                logger.info(f"Detected IMAP server: {config}")
                return config

        return None

    async def connect(self) -> None:
        """Connect to IMAP server."""
        if self._client is not None:
            return

        logger.info(f"Connecting to {self.server}:{self.port}")

        self._client = aioimaplib.IMAP4_SSL(
            host=self.server,
            port=self.port,
            timeout=30.0
        )

        await self._client.wait_hello_from_server()

        # Login
        result, data = await self._client.login(self.email_address, self.password)

        if result != "OK":
            raise IMAPSyncError(f"Login failed: {data}")

        logger.info(f"Logged in as {self.email_address}")

        # Send ID command for 163/QQ/Yahoo servers that require client identification
        # This is required for 163.com, 126.com, qq.com and some other Chinese email providers
        # Reference: https://help.mail.163.com/faqDetail.do?code=d7a5dc8471cd0c0e8b4b8f4f8e49998b
        await self._send_client_id()

    async def _send_client_id(self) -> None:
        """Send IMAP ID command to identify client.

        Required by 163.com, 126.com, qq.com and some other providers.
        Without this, SELECT command will fail with 'Unsafe Login' error.
        """
        if not self._client:
            return

        # Check if server is one that requires ID
        requires_id = any(
            domain in self.server
            for domain in ['163.com', '126.com', 'qq.com', 'yahoo.com']
        )

        if not requires_id:
            return

        try:
            # aioimaplib's id() method doesn't work correctly for 163
            # We need to send raw IMAP command
            # The protocol object is in _client.protocol
            client_id_str = '("name" "MailKnow" "version" "1.0" "vendor" "MailKnow")'

            # Use the underlying protocol to send command
            # aioimaplib stores the IMAP4_SSL object in _client
            # We need to access the raw socket
            if hasattr(self._client, 'protocol'):
                # aioimaplib > 0.2
                protocol = self._client.protocol
                protocol.write(f'ID {client_id_str}'.encode())
                response = await protocol.read_response()
                if response and response[0] == 'OK':
                    logger.info("IMAP ID sent successfully")
            else:
                # Fallback: use synchronous imaplib for ID command
                # This is a workaround for aioimaplib's ID implementation issues
                await self._send_id_sync()

        except Exception as e:
            # Non-fatal - some servers may not support ID command
            logger.debug(f"ID command not supported or failed: {e}")

    async def _send_id_sync(self) -> None:
        """Send ID command using synchronous imaplib as fallback.

        This is needed because aioimaplib's ID implementation has issues
        with Chinese email providers like 163.com.
        """
        import imaplib

        try:
            # Create a temporary synchronous connection just for ID
            context = ssl.create_default_context()
            sync_client = imaplib.IMAP4_SSL(self.server, self.port, ssl_context=context)
            sync_client.login(self.email_address, self.password)

            # Send ID command
            typ, dat = sync_client._simple_command('ID', '("name" "MailKnow" "version" "1.0")')
            logger.info(f"IMAP ID sent via sync: {typ}")

            # Close sync connection
            sync_client.logout()

        except Exception as e:
            logger.debug(f"Sync ID fallback failed: {e}")

    async def disconnect(self) -> None:
        """Disconnect from IMAP server."""
        if self._client:
            try:
                await self._client.logout()
            except Exception as e:
                logger.warning(f"Logout error: {e}")
            finally:
                self._client = None
                self._selected_folder = None

    async def list_folders(self) -> List[IMAPFolder]:
        """List all folders."""
        if not self._client:
            raise IMAPSyncError("Not connected")

        result, data = await self._client.list("", "*")

        if result != "OK":
            raise IMAPSyncError(f"List folders failed: {data}")

        folders = []
        for item in data:
            if not item:
                continue

            # Parse: (flags) "delimiter" "name"
            try:
                parts = item.decode().split('"')
                if len(parts) >= 3:
                    flags_str = parts[0].strip("()")
                    delimiter = parts[1]
                    name = parts[3] if len(parts) > 3 else parts[-1]

                    folders.append(IMAPFolder(
                        name=name,
                        delimiter=delimiter,
                        flags=flags_str.split() if flags_str else []
                    ))
            except Exception as e:
                logger.warning(f"Failed to parse folder: {item}, error: {e}")

        return folders

    async def select_folder(self, folder: str = "INBOX") -> int:
        """Select a folder and return message count."""
        if not self._client:
            raise IMAPSyncError("Not connected")

        result, data = await self._client.select(folder)

        if result != "OK":
            raise IMAPSyncError(f"Select folder failed: {data}")

        self._selected_folder = folder

        # Parse message count
        count = 0
        for item in data:
            if item and isinstance(item, bytes) and item.isdigit():
                count = int(item)
                break

        logger.info(f"Selected folder {folder} with {count} messages")
        return count

    async def fetch_message_uids(
        self,
        start_uid: int = 1,
        limit: Optional[int] = None
    ) -> List[int]:
        """Fetch message UIDs starting from a UID.

        Args:
            start_uid: Starting UID (inclusive)
            limit: Maximum number of UIDs to return

        Returns:
            List of UIDs in ascending order.
        """
        if not self._client:
            raise IMAPSyncError("Not connected")

        # Search for messages with UID >= start_uid
        result, data = await self._client.uid(
            "SEARCH",
            None,
            f"UID {start_uid}:*"
        )

        if result != "OK":
            raise IMAPSyncError(f"Search failed: {data}")

        uids = []
        if data[0]:
            uids = [int(uid) for uid in data[0].decode().split()]

        if limit and len(uids) > limit:
            uids = uids[:limit]

        return sorted(uids)

    async def fetch_message_headers(self, uid: int) -> Optional[Dict[str, Any]]:
        """Fetch message headers by UID."""
        if not self._client:
            raise IMAPSyncError("Not connected")

        result, data = await self._client.uid(
            "FETCH",
            str(uid),
            "(FLAGS BODY.PEEK[HEADER])"
        )

        if result != "OK" or not data[0]:
            return None

        # Parse headers
        headers = {}
        for item in data:
            if isinstance(item, bytes):
                try:
                    msg = email.message_from_bytes(item)
                    headers = dict(msg.items())
                except Exception:
                    pass

        return headers

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()
