"""IMAP connector for 163/126/QQ mailboxes.

These Chinese email providers require special handling:
1. Must send IMAP ID command after LOGIN
2. Without ID, SELECT returns "Unsafe Login" error

This module provides a wrapper that handles the ID requirement.
"""

import imaplib
import ssl
import logging
from typing import Optional, List, Tuple
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Add ID command to imaplib
imaplib.Commands['ID'] = ('AUTH', 'SELECTED')


class IMAP163Connector:
    """IMAP connector for 163.com, 126.com, QQ.com mailboxes.

    These providers require ID command to be sent after login.
    """

    PROVIDERS = {
        '163.com': ('imap.163.com', 993),
        '126.com': ('imap.126.com', 993),
        'qq.com': ('imap.qq.com', 993),
    }

    def __init__(
        self,
        email_address: str,
        password: str,
        server: Optional[str] = None,
        port: int = 993,
    ):
        self.email_address = email_address
        self.password = password

        # Auto-detect server
        if server is None:
            domain = email_address.split('@')[-1].lower()
            for provider, config in self.PROVIDERS.items():
                if provider in domain:
                    server, port = config
                    break
            if server is None:
                raise ValueError(f"Unknown email provider for {email_address}")

        self.server = server
        self.port = port
        self._client: Optional[imaplib.IMAP4_SSL] = None

    def connect(self) -> None:
        """Connect and login to IMAP server."""
        context = ssl.create_default_context()
        self._client = imaplib.IMAP4_SSL(
            self.server,
            self.port,
            ssl_context=context
        )

        # Login
        result = self._client.login(self.email_address, self.password)
        if result[0] != 'OK':
            raise ConnectionError(f"Login failed: {result}")

        logger.info(f"Logged in as {self.email_address}")

        # Send ID command for 163/126/QQ
        self._send_id()

    def disconnect(self) -> None:
        """Disconnect from server."""
        if self._client:
            try:
                self._client.logout()
            except:
                pass
            finally:
                self._client = None

    def _send_id(self) -> None:
        """Send IMAP ID command."""
        if not self._client:
            return

        # Check if this server requires ID
        requires_id = any(
            domain in self.server
            for domain in ['163.com', '126.com', 'qq.com']
        )

        if not requires_id:
            return

        # Send ID command
        # Format: ID ("key" "value" "key" "value" ...)
        try:
            typ, dat = self._client._simple_command(
                'ID',
                '("name" "MailKnow" "version" "1.0" "vendor" "MailKnow")'
            )
            if typ == 'OK':
                logger.info("IMAP ID sent successfully")
            else:
                logger.warning(f"ID command returned: {typ}")
        except Exception as e:
            logger.warning(f"ID command failed: {e}")

    def list_folders(self) -> List[Tuple[str, str]]:
        """List all folders.

        Returns:
            List of (flags, name) tuples
        """
        if not self._client:
            raise ConnectionError("Not connected")

        result, folders = self._client.list()
        if result != 'OK':
            raise ConnectionError(f"List failed: {folders}")

        parsed = []
        for f in folders:
            if f:
                # Parse: (flags) "/" "name"
                parts = f.decode().split('"')
                if len(parts) >= 3:
                    name = parts[-2]
                    parsed.append((parts[0].strip(), name))

        return parsed

    def select_folder(self, folder: str = 'INBOX') -> int:
        """Select a folder.

        Returns:
            Number of messages in folder
        """
        if not self._client:
            raise ConnectionError("Not connected")

        result, data = self._client.select(folder)
        if result != 'OK':
            raise ConnectionError(f"Select failed: {data}")

        count = int(data[0]) if data[0].isdigit() else 0
        logger.info(f"Selected {folder}: {count} messages")
        return count

    def search(self, criteria: str = 'ALL') -> List[int]:
        """Search for messages.

        Returns:
            List of message numbers
        """
        if not self._client:
            raise ConnectionError("Not connected")

        result, data = self._client.search(None, criteria)
        if result != 'OK':
            raise ConnectionError(f"Search failed: {data}")

        nums = []
        if data[0]:
            nums = [int(x) for x in data[0].decode().split()]

        return nums

    def fetch_headers(self, msg_num: int) -> dict:
        """Fetch message headers."""
        if not self._client:
            raise ConnectionError("Not connected")

        result, data = self._client.fetch(str(msg_num), '(BODY.PEEK[HEADER])')
        if result != 'OK':
            return {}

        # Parse headers - data can be list of tuples or bytes
        headers = {}
        raw_headers = None

        for item in data:
            if isinstance(item, tuple) and len(item) == 2:
                # (response_id, header_bytes)
                raw_headers = item[1]
                break
            elif isinstance(item, bytes):
                raw_headers = item
                break

        if raw_headers:
            try:
                import email
                msg = email.message_from_bytes(raw_headers)
                headers = dict(msg.items())
            except Exception as e:
                logger.warning(f"Failed to parse headers: {e}")

        return headers

    @contextmanager
    def connection(self):
        """Context manager for connection."""
        self.connect()
        try:
            yield self
        finally:
            self.disconnect()
