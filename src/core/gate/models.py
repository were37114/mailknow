"""Gate classification models."""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


class GateClass(str, Enum):
    """Gate classification levels.

    Priority order: G0 > G4 > G3 > G2 > G1
    """
    URGENT = "urgent"           # G0: 紧急邮件
    IMPORTANT = "important"     # G1: 重要邮件
    ROUTINE = "routine"         # G2: 常规邮件
    NOTIFICATION = "notification"  # G3: 通知邮件
    SPAM = "spam"               # G4: 垃圾邮件

    @property
    def priority(self) -> int:
        """Higher priority = more important."""
        priorities = {
            GateClass.URGENT: 5,
            GateClass.SPAM: 4,
            GateClass.NOTIFICATION: 3,
            GateClass.ROUTINE: 2,
            GateClass.IMPORTANT: 1,
        }
        return priorities[self]

    @property
    def ui_label(self) -> str:
        """UI display label (4档呈现)."""
        # G2+G3 合并为"一般"
        labels = {
            GateClass.URGENT: "⭐ 重要",
            GateClass.IMPORTANT: "⭐ 重要",
            GateClass.ROUTINE: "📬 一般",
            GateClass.NOTIFICATION: "📬 一般",
            GateClass.SPAM: "🗑️ 垃圾",
        }
        return labels[self]


@dataclass
class GateResult:
    """Gate classification result."""
    gate_class: GateClass
    confidence: float
    matched_rules: List[str]
    score: float = 0.0

    @property
    def is_urgent(self) -> bool:
        return self.gate_class == GateClass.URGENT

    @property
    def is_spam(self) -> bool:
        return self.gate_class == GateClass.SPAM

    @property
    def ui_label(self) -> str:
        return self.gate_class.ui_label
