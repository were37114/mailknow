"""Anomaly detection - detect unusual email patterns.

V5.2 spec:
- Unreplied urgent emails
- Promise tracking (commitments without follow-up)
- Unusual sender patterns
- Deadline approaching without action
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AnomalyType(str, Enum):
    """Types of detected anomalies."""
    UNREPLIED_URGENT = "unreplied_urgent"         # Important email not replied
    PROMISE_UNFULFILLED = "promise_unfulfilled"   # Commitment without follow-up
    DEADLINE_APPROACHING = "deadline_approaching" # Approval deadline approaching
    UNUSUAL_SENDER = "unusual_sender"             # First-time sender with important content
    HIGH_VOLUME_SENDER = "high_volume_sender"     # Unusually high email volume from one sender
    PATTERN_CHANGE = "pattern_change"             # Change in email patterns


@dataclass
class Anomaly:
    """A detected anomaly."""
    anomaly_id: str = ""
    anomaly_type: AnomalyType = AnomalyType.UNREPLIED_URGENT
    severity: str = "medium"  # low/medium/high/critical
    title: str = ""
    description: str = ""

    # Source data
    email_ids: List[str] = field(default_factory=list)
    entity_ids: List[str] = field(default_factory=list)

    # Detection info
    confidence: float = 0.0
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    dismissed: bool = False

    # Action suggestion
    suggested_action: str = ""
    action_data: Dict[str, Any] = field(default_factory=dict)


class AnomalyDetector:
    """Detect email anomalies.

    Features:
    - Unreplied urgent email detection
    - Promise/commitment tracking
    - Deadline approaching alerts
    - Unusual sender detection
    - High volume detection
    """

    # Promise patterns in email content
    PROMISE_PATTERNS = [
        r'我会\s*(?:在|于)?\s*(?:明天|下周|本周|尽快|\d+[天号日]内?)?\s*(?:前|之前)?\s*(完成|回复|提交|处理|确认)',
        r'我(?:将|会|准备)(?:在|于)?\s*\d+[月号日]?\s*(前|之前|完成|提交)',
        r'(?:预计|计划)\s*\d+[月号日]?\s*(完成|交付|上线)',
        r'I will (?:follow up|get back|complete|submit|send) (?:by|on|before)',
    ]

    # Urgency indicators
    URGENCY_PATTERNS = [
        r'[紧急加急]',
        r'URGENT',
        r'ASAP',
        r'请(?:尽快|立即|马上|务必)',
        r'今天[之内]?[必须需]',
    ]

    def __init__(self):
        self._detected: List[Anomaly] = []

    def detect_unreplied_urgent(
        self,
        emails: List[Dict[str, Any]],
        reply_map: Optional[Dict[str, List[str]]] = None,
        hours_threshold: int = 24,
    ) -> List[Anomaly]:
        """Detect important/urgent emails that haven't been replied.

        Args:
            emails: List of email dicts
            reply_map: Map of email_id → [reply_email_ids]
            hours_threshold: Hours before flagging as unreplied

        Returns:
            List of detected anomalies
        """
        anomalies = []
        reply_map = reply_map or {}
        now = datetime.now(timezone.utc)

        for email in emails:
            gate = email.get("gate_class", "")
            if gate not in ("important", "urgent"):
                continue

            email_id = email.get("email_id", "")
            has_reply = bool(reply_map.get(email_id))

            if has_reply:
                continue

            # Check if email is old enough
            date_str = email.get("date", "")
            if not date_str:
                continue

            try:
                email_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                if email_date.tzinfo is None:
                    email_date = email_date.replace(tzinfo=timezone.utc)
                hours_old = (now - email_date).total_seconds() / 3600
            except ValueError:
                continue

            if hours_old < hours_threshold:
                continue

            # Check urgency patterns
            content = email.get("content", "") or ""
            subject = email.get("subject", "") or ""
            is_urgent = any(
                re.search(p, content + subject, re.IGNORECASE)
                for p in self.URGENCY_PATTERNS
            )

            severity = "high" if is_urgent or gate == "urgent" else "medium"

            anomaly = Anomaly(
                anomaly_id=f"unreplied:{email_id}",
                anomaly_type=AnomalyType.UNREPLIED_URGENT,
                severity=severity,
                title=f"未回复的{('紧急' if is_urgent else '重要')}邮件",
                description=f"{email.get('subject', '无主题')} - 已{int(hours_old)}小时未回复",
                email_ids=[email_id],
                confidence=0.85 if is_urgent else 0.7,
                suggested_action="回复",
                action_data={"email_id": email_id, "action": "reply"},
            )

            anomalies.append(anomaly)
            self._detected.append(anomaly)

        return anomalies

    def detect_promise_unfulfilled(
        self,
        emails: List[Dict[str, Any]],
        days_threshold: int = 3,
    ) -> List[Anomaly]:
        """Detect unfulfilled promises/commitments.

        Args:
            emails: List of sent emails (from user)
            days_threshold: Days after promise before flagging
        """
        anomalies = []
        now = datetime.now(timezone.utc)

        for email in emails:
            content = email.get("content", "") or ""
            email_id = email.get("email_id", "")

            # Check for promise patterns
            promises = []
            for pattern in self.PROMISE_PATTERNS:
                matches = re.finditer(pattern, content, re.IGNORECASE)
                for match in matches:
                    promises.append(match.group(0))

            if not promises:
                continue

            # Check if old enough
            date_str = email.get("date", "")
            if not date_str:
                continue

            try:
                email_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                if email_date.tzinfo is None:
                    email_date = email_date.replace(tzinfo=timezone.utc)
                days_old = (now - email_date).days
            except ValueError:
                continue

            if days_old < days_threshold:
                continue

            anomaly = Anomaly(
                anomaly_id=f"promise:{email_id}",
                anomaly_type=AnomalyType.PROMISE_UNFULFILLED,
                severity="medium",
                title="待跟进承诺",
                description=f"\"{promises[0]}\" - 已过{days_old}天",
                email_ids=[email_id],
                confidence=0.7,
                suggested_action="跟进",
                action_data={"email_id": email_id, "promises": promises},
            )

            anomalies.append(anomaly)
            self._detected.append(anomaly)

        return anomalies

    def detect_deadline_approaching(
        self,
        approval_cards: List[Dict[str, Any]],
        hours_threshold: int = 24,
    ) -> List[Anomaly]:
        """Detect approval deadlines approaching."""
        anomalies = []
        now = datetime.now(timezone.utc)

        for card in approval_cards:
            deadline = card.get("deadline")
            if not deadline:
                continue

            try:
                deadline_dt = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
                # Handle offset-naive datetimes
                if deadline_dt.tzinfo is None:
                    deadline_dt = deadline_dt.replace(tzinfo=timezone.utc)
                hours_left = (deadline_dt - now).total_seconds() / 3600
            except ValueError:
                continue

            if hours_left > hours_threshold or hours_left < 0:
                continue

            severity = "critical" if hours_left < 4 else "high" if hours_left < 8 else "medium"

            anomaly = Anomaly(
                anomaly_id=f"deadline:{card.get('card_id', '')}",
                anomaly_type=AnomalyType.DEADLINE_APPROACHING,
                severity=severity,
                title="审批即将到期",
                description=f"{card.get('subject', '无主题')} - 截止时间：{deadline}（剩余{int(hours_left)}小时）",
                email_ids=[card.get("email_id", "")],
                confidence=0.95,
                suggested_action="去审批",
                action_data={"card_id": card.get("card_id", ""), "action": "approve"},
            )

            anomalies.append(anomaly)
            self._detected.append(anomaly)

        return anomalies

    def detect_all(
        self,
        emails: List[Dict[str, Any]],
        approval_cards: List[Dict[str, Any]] = None,
        reply_map: Optional[Dict[str, List[str]]] = None,
    ) -> List[Anomaly]:
        """Run all anomaly detections.

        Returns:
            List of all detected anomalies, sorted by severity
        """
        all_anomalies = []

        all_anomalies.extend(self.detect_unreplied_urgent(emails, reply_map))
        all_anomalies.extend(self.detect_promise_unfulfilled(emails))

        if approval_cards:
            all_anomalies.extend(self.detect_deadline_approaching(approval_cards))

        # Sort by severity
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        all_anomalies.sort(key=lambda a: severity_order.get(a.severity, 4))

        return all_anomalies

    def get_detected(self) -> List[Anomaly]:
        """Get all detected anomalies."""
        return [a for a in self._detected if not a.dismissed]

    def dismiss(self, anomaly_id: str) -> bool:
        """Dismiss an anomaly."""
        for a in self._detected:
            if a.anomaly_id == anomaly_id:
                a.dismissed = True
                return True
        return False

    def get_stats(self) -> Dict[str, Any]:
        """Get anomaly detection statistics."""
        active = [a for a in self._detected if not a.dismissed]
        by_type: Dict[str, int] = {}
        by_severity: Dict[str, int] = {}
        for a in active:
            by_type[a.anomaly_type.value] = by_type.get(a.anomaly_type.value, 0) + 1
            by_severity[a.severity] = by_severity.get(a.severity, 0) + 1

        return {
            "total_detected": len(self._detected),
            "active": len(active),
            "dismissed": len(self._detected) - len(active),
            "by_type": by_type,
            "by_severity": by_severity,
        }
