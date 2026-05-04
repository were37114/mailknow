"""Email data models."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class EmailFlag(str, Enum):
    """IMAP email flags."""
    SEEN = "\\Seen"
    ANSWERED = "\\Answered"
    FLAGGED = "\\Flagged"
    DELETED = "\\Deleted"
    DRAFT = "\\Draft"
    RECENT = "\\Recent"


@dataclass
class EmailAddress:
    """Email address with optional name."""
    address: str
    name: Optional[str] = None

    def __str__(self) -> str:
        if self.name:
            return f"{self.name} <{self.address}>"
        return self.address


@dataclass
class Email:
    """Email message model."""
    message_id: str
    subject: str
    from_addr: EmailAddress
    to_addrs: List[EmailAddress] = field(default_factory=list)
    cc_addrs: List[EmailAddress] = field(default_factory=list)

    # Content
    text_body: Optional[str] = None
    html_body: Optional[str] = None

    # Metadata
    date: Optional[datetime] = None
    flags: List[EmailFlag] = field(default_factory=list)

    # References
    in_reply_to: Optional[str] = None
    references: List[str] = field(default_factory=list)

    # Attachments (placeholder for D4)
    attachments: List[dict] = field(default_factory=list)

    # Raw data
    raw_bytes: Optional[bytes] = None

    @property
    def is_read(self) -> bool:
        return EmailFlag.SEEN in self.flags

    @property
    def is_replied(self) -> bool:
        return EmailFlag.ANSWERED in self.flags


@dataclass
class IMAPFolder:
    """IMAP folder info."""
    name: str
    delimiter: str
    flags: List[str] = field(default_factory=list)

    # Stats
    total_messages: int = 0
    unread_messages: int = 0
