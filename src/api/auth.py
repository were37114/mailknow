"""IPC authentication - random token + Unix Domain Socket.

V5.2 spec:
- Startup generates random auth token
- All IPC requests require valid token
- Unix Domain Socket for local-only communication
"""

import logging
import os
import secrets
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class AuthConfig:
    """IPC authentication configuration."""
    token: str = ""
    socket_path: str = ""
    enabled: bool = True
    created_at: str = ""


class IPCAuth:
    """IPC authentication manager.

    Features:
    - Random token generation on startup
    - Token validation for all requests
    - Unix Domain Socket for local-only communication
    - Token rotation support
    """

    def __init__(
        self,
        socket_path: Optional[str] = None,
        enabled: bool = True,
    ):
        self.enabled = enabled
        self._token = secrets.token_hex(32)  # 64-char hex token
        self._socket_path = socket_path or f"/tmp/mailknow-{os.getpid()}.sock"
        self._created_at = datetime.now(timezone.utc).isoformat()
        self._request_count = 0
        self._failed_auth_count = 0

    def validate_token(self, token: str) -> bool:
        """Validate an IPC request token.

        Args:
            token: Token from request

        Returns:
            True if valid
        """
        if not self.enabled:
            return True

        self._request_count += 1

        if not token:
            self._failed_auth_count += 1
            return False

        if not secrets.compare_digest(token, self._token):
            self._failed_auth_count += 1
            logger.warning(f"Invalid IPC auth token (attempt #{self._failed_auth_count})")
            return False

        return True

    def rotate_token(self) -> str:
        """Rotate the auth token.

        Returns:
            New token
        """
        old_token = self._token
        self._token = secrets.token_hex(32)
        self._created_at = datetime.now(timezone.utc).isoformat()

        logger.info("IPC auth token rotated")
        return self._token

    @property
    def token(self) -> str:
        """Get current auth token."""
        return self._token

    @property
    def socket_path(self) -> str:
        """Get Unix Domain Socket path."""
        return self._socket_path

    def get_config(self) -> AuthConfig:
        """Get auth configuration (excludes token for security)."""
        return AuthConfig(
            socket_path=self._socket_path,
            enabled=self.enabled,
            created_at=self._created_at,
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get authentication statistics."""
        return {
            "enabled": self.enabled,
            "total_requests": self._request_count,
            "failed_auth": self._failed_auth_count,
            "token_created_at": self._created_at,
            "socket_path": self._socket_path,
        }


# Global instance
_auth: Optional[IPCAuth] = None


def get_ipc_auth() -> IPCAuth:
    """Get global IPC auth instance."""
    global _auth
    if _auth is None:
        _auth = IPCAuth()
    return _auth
