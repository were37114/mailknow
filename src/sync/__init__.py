"""MailKnow sync package."""

from .imap_sync import IMAPConnector
from .models import Email, EmailAddress, EmailFlag, IMAPFolder

__all__ = ["Email", "EmailAddress", "EmailFlag", "IMAPFolder", "IMAPConnector"]
