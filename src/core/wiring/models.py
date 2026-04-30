"""Wiring models for link extraction."""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum


class LinkRelation(str, Enum):
    """Link relation types."""
    # Email thread relations
    REPLY_TO = "reply_to"          # A回复B
    REFERENCES = "references"       # A引用B
    
    # Communication relations
    SENT_BY = "sent_by"            # 邮件由某人发送
    SENT_TO = "sent_to"            # 邮件发送给某人
    CC_TO = "cc_to"                # 邮件抄送给某人
    
    # Content relations
    MENTIONS = "mentions"          # 邮件提及某人/项目
    ATTACHES = "attaches"          # 邮件包含附件
    
    # Entity relations
    BELONGS_TO = "belongs_to"      # 属于某个组织/项目
    RELATED_TO = "related_to"      # 相关关系


class LinkTier(int, Enum):
    """Link extraction tier."""
    TIER_1 = 1  # 邮件头（Message-ID, In-Reply-To, References, From/To/Cc）
    TIER_2 = 2  # 正文匹配（@提及、项目名、URL）
    TIER_4 = 4  # LLM语义提取（隐含关系）


@dataclass
class Link:
    """Link between entities/pages."""
    source_id: str
    target_id: Optional[str]
    relation: LinkRelation
    tier: LinkTier = LinkTier.TIER_1
    
    weight: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def id(self) -> str:
        """Generate unique ID for link."""
        target = self.target_id or "null"
        return f"{self.source_id}:{self.relation.value}:{target}"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation": self.relation.value,
            "weight": self.weight,
            "metadata": self.metadata,
            "tier": self.tier.value
        }
