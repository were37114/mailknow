"""Approval scene - dual-layer detection + confidence classification + actions.

V5.2 spec:
- Layer 1: Gate rule-based pre-filter (0 token)
- Layer 2: Tier4 LLM precision filter (~400 token)
- Three-level confidence: High(>85) / Medium(60-85) / Low(<60)
- CC approvals don't enter approval cards
- Approval result notifications go to Gate1 (routine)
- Batch approval mode for high-volume users
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from core.gate.classifier import EmailInfo, GateClassifier
from core.gate.models import GateClass
from core.wiring.tier4_extractor import ApprovalResult, Tier4Extractor
from llm.client import LLMClient, get_llm_client
from llm.fallback import WithFallback, get_fallback
from llm.token_budget import TokenBudget
from sync.models import Email

logger = logging.getLogger(__name__)


class ApprovalType(str, Enum):
    """Approval email types."""
    DIRECT = "direct"          # 主送审批请求
    CC = "cc"                  # 抄送审批通知
    NOTIFICATION = "notification"  # 已完成审批通知
    SYSTEM_FORWARD = "system_forward"  # 系统转发审批


class ConfidenceLevel(str, Enum):
    """Three-level confidence for approval detection."""
    HIGH = "high"        # >85: Direct push, auto-create approval card
    MEDIUM = "medium"    # 60-85: Pending confirmation
    LOW = "low"          # <60: Don't proactively push


@dataclass
class ApprovalDetection:
    """Approval detection result with confidence level."""
    is_approval: bool
    approval_type: ApprovalType
    confidence: float
    confidence_level: ConfidenceLevel
    gate_class: GateClass
    llm_used: bool = False
    reason: str = ""

    # Approval details
    approver: str = ""           # Who needs to approve
    requester: str = ""          # Who requested approval
    amount: Optional[float] = None  # Amount if mentioned
    subject: str = ""
    deadline: Optional[str] = None  # Deadline if mentioned

    @property
    def needs_action(self) -> bool:
        """Whether user needs to take action."""
        return (self.is_approval and
                self.approval_type == ApprovalType.DIRECT and
                self.confidence_level in (ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM))

    @property
    def should_push(self) -> bool:
        """Whether to proactively push notification to user.

        Per V5.2 spec:
        - High confidence: push immediately
        - Medium confidence: show in pending list
        - Low confidence: don't push
        - CC approvals: don't create card
        """
        if not self.is_approval:
            return False
        if self.approval_type == ApprovalType.CC:
            return False  # CC审批不进入卡片
        if self.approval_type == ApprovalType.NOTIFICATION:
            return False  # 已完成通知走Gate1
        return self.confidence_level == ConfidenceLevel.HIGH


def _confidence_to_level(confidence: float) -> ConfidenceLevel:
    """Convert numeric confidence to three-level classification."""
    if confidence > 0.85:
        return ConfidenceLevel.HIGH
    elif confidence >= 0.60:
        return ConfidenceLevel.MEDIUM
    else:
        return ConfidenceLevel.LOW


class ApprovalDetector:
    """Dual-layer approval detection with confidence classification.

    Layer 1: Gate rule-based filter (0 token)
    - Quickly eliminate spam/notification/routine emails
    - Only pass potential approval emails to Layer 2

    Layer 2: LLM precision filter (~400 token)
    - Accurate classification of borderline cases
    - Distinguish direct/cc/notification/system

    V5.2 additions:
    - Three-level confidence (high/medium/low)
    - withFallback integration for automatic degradation
    - Desensitization before LLM call
    - Approval detail extraction (approver, amount, deadline)
    """

    def __init__(
        self,
        gate_classifier: Optional[GateClassifier] = None,
        tier4_extractor: Optional[Tier4Extractor] = None,
        llm_client: Optional[LLMClient] = None,
        token_budget: Optional[TokenBudget] = None,
        fallback: Optional[WithFallback] = None,
    ):
        self.gate = gate_classifier or GateClassifier()
        self.tier4 = tier4_extractor or Tier4Extractor(
            llm_client=llm_client or get_llm_client(),
            token_budget=token_budget or TokenBudget(),
        )
        self.fallback = fallback or get_fallback()

    async def detect(self, email: Email, user_email: str = "") -> ApprovalDetection:
        """Detect if email is an approval request with confidence level.

        Args:
            email: Email to analyze

        Returns:
            Approval detection result
        """
        # Layer 1: Gate rule-based filter
        email_info = self._email_to_info(email)
        gate_result = self.gate.classify(email_info)

        # Quick reject: spam emails are not approvals
        if gate_result.gate_class == GateClass.SPAM:
            return ApprovalDetection(
                is_approval=False,
                approval_type=ApprovalType.NOTIFICATION,
                confidence=0.95,
                confidence_level=ConfidenceLevel.HIGH,
                gate_class=gate_result.gate_class,
                reason="垃圾邮件，无需审批"
            )

        # Auto-reply notifications
        if getattr(email, 'is_auto_reply', False):
            return ApprovalDetection(
                is_approval=False,
                approval_type=ApprovalType.NOTIFICATION,
                confidence=0.9,
                confidence_level=ConfidenceLevel.HIGH,
                gate_class=gate_result.gate_class,
                reason="自动回复通知"
            )

        # Layer 2: LLM or rule-based precision filter
        approval_keywords = ["审批", "批准", "确认", "签字", "审核", "approve", "签核"]
        subject_lower = (email.subject or "").lower()
        content_lower = (email.text_body or "").lower()

        needs_llm = any(kw in subject_lower or kw in content_lower for kw in approval_keywords)

        if needs_llm:
            # Use Tier4 LLM for precise classification
            approval_result = await self.tier4.classify_approval(email, user_email=user_email)

            approval_type = self._map_approval_type(approval_result)
            confidence_level = _confidence_to_level(approval_result.confidence)

            # Extract approval details
            approver, requester, amount, deadline = self._extract_details(email, approval_result)

            return ApprovalDetection(
                is_approval=approval_result.is_approval,
                approval_type=approval_type,
                confidence=approval_result.confidence,
                confidence_level=confidence_level,
                gate_class=gate_result.gate_class,
                llm_used=True,
                reason=approval_result.reason,
                approver=approver,
                requester=requester,
                amount=amount,
                subject=email.subject or "",
                deadline=deadline,
            )
        else:
            # Local rule-based classification (no LLM needed)
            approval_result = self.tier4._local_approval_classify(email, user_email=user_email)

            approval_type = self._map_approval_type(approval_result)
            confidence_level = _confidence_to_level(approval_result.confidence)

            return ApprovalDetection(
                is_approval=approval_result.is_approval,
                approval_type=approval_type,
                confidence=approval_result.confidence,
                confidence_level=confidence_level,
                gate_class=gate_result.gate_class,
                llm_used=False,
                reason=approval_result.reason,
                subject=email.subject or "",
            )

    async def detect_batch(self, emails: List[Email]) -> List[ApprovalDetection]:
        """Batch detect approval emails.

        Args:
            emails: List of emails to analyze

        Returns:
            List of detection results
        """
        results = []
        for email in emails:
            result = await self.detect(email)
            results.append(result)
        return results

    def _map_approval_type(self, approval_result: ApprovalResult) -> ApprovalType:
        """Map Tier4 ApprovalResult.approval_type to our enum."""
        type_map = {
            "direct": ApprovalType.DIRECT,
            "cc": ApprovalType.CC,
            "notification": ApprovalType.NOTIFICATION,
            "system_forward": ApprovalType.SYSTEM_FORWARD,
            "none": ApprovalType.NOTIFICATION,
        }
        return type_map.get(approval_result.approval_type, ApprovalType.NOTIFICATION)

    def _extract_details(
        self,
        email: Email,
        approval_result: ApprovalResult
    ) -> tuple:
        """Extract approval details from email.

        Returns:
            (approver, requester, amount, deadline)
        """
        import re

        approver = ""
        requester = ""
        amount = None
        deadline = None

        content = email.text_body or ""
        subject = email.subject or ""

        # Requester is typically the sender
        if email.from_addr:
            requester = str(email.from_addr)

        # Approver is typically in "to" addresses
        if email.to_addrs:
            approver = str(email.to_addrs[0]) if email.to_addrs else ""

        # Extract amount
        amount_patterns = [
            r'[¥￥$]\s*([\d,]+\.?\d*)',  # ¥50,000
            r'([\d,]+\.?\d*)\s*(元|万|块)',  # 5万元
            r'金额[：:]\s*([\d,]+\.?\d*)',  # 金额：5000
        ]
        for pattern in amount_patterns:
            match = re.search(pattern, content + subject)
            if match:
                try:
                    amount_str = match.group(1).replace(',', '')
                    amount = float(amount_str)
                    if '万' in (content + subject):
                        amount = amount * 10000
                    break
                except ValueError:
                    pass

        # Extract deadline
        deadline_patterns = [
            r'截止[日期]*[：:]\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?)',
            r'(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?)\s*前',
            r'before\s+(\d{4}[-/]\d{1,2}[-/]\d{1,2})',
        ]
        for pattern in deadline_patterns:
            match = re.search(pattern, content + subject)
            if match:
                deadline = match.group(1)
                break

        return approver, requester, amount, deadline

    def _email_to_info(self, email: Email) -> EmailInfo:
        """Convert Email to EmailInfo for Gate classifier."""
        return EmailInfo(
            subject=email.subject or "",
            from_addr=str(email.from_addr.address) if email.from_addr else "",
            to_addrs=[str(a.address) for a in email.to_addrs],
            cc_addrs=[str(a.address) for a in email.cc_addrs],
            content=email.text_body or "",
            has_attachments=len(email.attachments) > 0,
            is_auto_reply=getattr(email, 'is_auto_reply', False),
        )
