"""MailKnow sync package."""

from .models import Email, EmailAddress, EmailFlag, IMAPFolder
from .imap_sync import IMAPConnector

__all__ = ["Email", "EmailAddress", "EmailFlag", "IMAPFolder", "IMAPConnector"]
