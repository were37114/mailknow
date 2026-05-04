"""Approval actions - closed-loop operations.

Supports:
- Approve / Reject / Forward / Delegate
- Batch approval mode for high-volume users
- Small amount (≤¥10K) simplified 3-step flow
- Large amount (>¥100K) double confirmation
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ApprovalAction(str, Enum):
    """Approval action types."""
    APPROVE = "approve"
    REJECT = "reject"
    FORWARD = "forward"
    DELEGATE = "delegate"
    COMMENT = "comment"       # Add comment without deciding
    DEFER = "defer"           # Defer to later


class ApprovalStatus(str, Enum):
    """Approval status."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    FORWARDED = "forwarded"
    DELEGATED = "delegated"
    DEFERRED = "deferred"
    EXPIRED = "expired"


class AmountCategory(str, Enum):
    """Amount categories for UX optimization."""
    SMALL = "small"      # ≤¥10K: 3-step simplified flow
    MEDIUM = "medium"    # ¥10K-¥100K: standard flow
    LARGE = "large"      # >¥100K: double confirmation
    UNKNOWN = "unknown"  # No amount mentioned


@dataclass
class ApprovalCard:
    """An approval card for UI display."""
    card_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    email_id: str = ""
    subject: str = ""
    requester: str = ""
    approver: str = ""
    confidence: float = 0.0
    confidence_level: str = "medium"  # high/medium/low

    # Amount info
    amount: Optional[float] = None
    amount_category: AmountCategory = AmountCategory.UNKNOWN
    currency: str = "CNY"

    # Deadline
    deadline: Optional[str] = None

    # Status
    status: ApprovalStatus = ApprovalStatus.PENDING
    action: Optional[ApprovalAction] = None
    action_at: Optional[str] = None
    action_by: Optional[str] = None
    comment: str = ""

    # Metadata
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    gate_class: str = ""
    reason: str = ""

    @property
    def is_small_amount(self) -> bool:
        """Whether this is a small amount approval (simplified flow)."""
        return self.amount_category == AmountCategory.SMALL

    @property
    def is_large_amount(self) -> bool:
        """Whether this needs double confirmation."""
        return self.amount_category == AmountCategory.LARGE

    @property
    def is_actionable(self) -> bool:
        """Whether user can take action on this card."""
        return self.status == ApprovalStatus.PENDING


def classify_amount(amount: Optional[float], currency: str = "CNY") -> AmountCategory:
    """Classify amount into category for UX optimization.

    V5.2 spec:
    - Small: ≤¥10K → 3-step simplified flow
    - Medium: ¥10K-¥100K → standard flow
    - Large: >¥100K → double confirmation
    """
    if amount is None:
        return AmountCategory.UNKNOWN

    # Normalize to CNY for classification
    # (For MVP, assume CNY; future: add exchange rates)
    if currency != "CNY" and currency != "RMB":
        # For USD etc., approximate conversion
        if currency in ("USD", "US"):
            amount_cny = amount * 7.2  # Approximate
        else:
            amount_cny = amount
    else:
        amount_cny = amount

    if amount_cny <= 10000:
        return AmountCategory.SMALL
    elif amount_cny <= 100000:
        return AmountCategory.MEDIUM
    else:
        return AmountCategory.LARGE


@dataclass
class BatchApprovalResult:
    """Result of batch approval operation."""
    total: int = 0
    approved: int = 0
    rejected: int = 0
    skipped: int = 0
    errors: int = 0
    details: List[Dict[str, Any]] = field(default_factory=list)


class ApprovalActions:
    """Approval closed-loop operations.

    Features:
    - Single approve/reject/forward/delegate
    - Batch approval (select all → approve → archive)
    - Small amount simplified 3-step flow
    - Large amount double confirmation
    - Action logging
    """

    def __init__(self):
        """Initialize approval actions."""
        self._cards: Dict[str, ApprovalCard] = {}
        self._action_log: List[Dict[str, Any]] = []

    def create_card(
        self,
        email_id: str,
        subject: str,
        requester: str = "",
        approver: str = "",
        confidence: float = 0.0,
        confidence_level: str = "medium",
        amount: Optional[float] = None,
        currency: str = "CNY",
        deadline: Optional[str] = None,
        gate_class: str = "",
        reason: str = "",
    ) -> ApprovalCard:
        """Create an approval card from detection result.

        Args:
            email_id: Email identifier
            subject: Email subject
            requester: Who requested approval
            approver: Who needs to approve
            confidence: Detection confidence
            confidence_level: high/medium/low
            amount: Amount mentioned
            currency: Currency code
            deadline: Approval deadline
            gate_class: Gate classification
            reason: Detection reason

        Returns:
            Created approval card
        """
        amount_category = classify_amount(amount, currency)

        card = ApprovalCard(
            email_id=email_id,
            subject=subject,
            requester=requester,
            approver=approver,
            confidence=confidence,
            confidence_level=confidence_level,
            amount=amount,
            amount_category=amount_category,
            currency=currency,
            deadline=deadline,
            gate_class=gate_class,
            reason=reason,
        )

        self._cards[card.card_id] = card
        logger.info(f"Created approval card {card.card_id}: {subject} (confidence={confidence:.2f}, amount={amount})")

        return card

    def approve(
        self,
        card_id: str,
        comment: str = "",
        actor: str = "",
        force: bool = False,
    ) -> ApprovalCard:
        """Approve an approval request.

        Args:
            card_id: Card identifier
            comment: Approval comment
            actor: Who performed the action
            force: Skip double confirmation for large amounts

        Returns:
            Updated card

        Raises:
            ValueError: If card not found or not actionable
            ConfirmationRequiredError: If large amount needs confirmation
        """
        card = self._get_card(card_id)

        if not card.is_actionable:
            raise ValueError(f"Card {card_id} is not actionable (status={card.status})")

        # Large amount double confirmation
        if card.is_large_amount and not force:
            raise ConfirmationRequiredError(
                f"Large amount (¥{card.amount:,.0f}) requires double confirmation. "
                f"Use force=True to confirm."
            )

        card.status = ApprovalStatus.APPROVED
        card.action = ApprovalAction.APPROVE
        card.action_at = datetime.now(timezone.utc).isoformat()
        card.action_by = actor
        card.comment = comment

        self._log_action(card, "approve", actor, comment)
        logger.info(f"Approved {card_id}: {card.subject}")

        return card

    def reject(
        self,
        card_id: str,
        comment: str = "",
        actor: str = "",
    ) -> ApprovalCard:
        """Reject an approval request."""
        card = self._get_card(card_id)

        if not card.is_actionable:
            raise ValueError(f"Card {card_id} is not actionable")

        card.status = ApprovalStatus.REJECTED
        card.action = ApprovalAction.REJECT
        card.action_at = datetime.now(timezone.utc).isoformat()
        card.action_by = actor
        card.comment = comment

        self._log_action(card, "reject", actor, comment)
        logger.info(f"Rejected {card_id}: {card.subject}")

        return card

    def forward(
        self,
        card_id: str,
        forward_to: str,
        comment: str = "",
        actor: str = "",
    ) -> ApprovalCard:
        """Forward approval to another person."""
        card = self._get_card(card_id)

        if not card.is_actionable:
            raise ValueError(f"Card {card_id} is not actionable")

        card.status = ApprovalStatus.FORWARDED
        card.action = ApprovalAction.FORWARD
        card.action_at = datetime.now(timezone.utc).isoformat()
        card.action_by = actor
        card.comment = f"Forwarded to {forward_to}. {comment}".strip()

        self._log_action(card, "forward", actor, f"→{forward_to} {comment}")
        logger.info(f"Forwarded {card_id} to {forward_to}")

        return card

    def delegate(
        self,
        card_id: str,
        delegate_to: str,
        comment: str = "",
        actor: str = "",
    ) -> ApprovalCard:
        """Delegate approval to another person."""
        card = self._get_card(card_id)

        if not card.is_actionable:
            raise ValueError(f"Card {card_id} is not actionable")

        card.status = ApprovalStatus.DELEGATED
        card.action = ApprovalAction.DELEGATE
        card.action_at = datetime.now(timezone.utc).isoformat()
        card.action_by = actor
        card.comment = f"Delegated to {delegate_to}. {comment}".strip()

        self._log_action(card, "delegate", actor, f"→{delegate_to} {comment}")
        return card

    def batch_approve(
        self,
        card_ids: List[str],
        comment: str = "",
        actor: str = "",
        skip_large: bool = True,
    ) -> BatchApprovalResult:
        """Batch approve multiple approval cards.

        V5.2 spec: select all → approve → archive
        For daily 20+ approval users.

        Args:
            card_ids: List of card IDs to approve
            comment: Shared comment
            actor: Who performed the batch action
            skip_large: Skip large amount items (need individual confirmation)

        Returns:
            Batch result summary
        """
        result = BatchApprovalResult(total=len(card_ids))

        for card_id in card_ids:
            try:
                card = self._cards.get(card_id)
                if not card:
                    result.errors += 1
                    result.details.append({"card_id": card_id, "status": "error", "reason": "not_found"})
                    continue

                if not card.is_actionable:
                    result.skipped += 1
                    result.details.append({"card_id": card_id, "status": "skipped", "reason": "not_actionable"})
                    continue

                # Skip large amounts in batch mode
                if skip_large and card.is_large_amount:
                    result.skipped += 1
                    result.details.append({
                        "card_id": card_id,
                        "status": "skipped",
                        "reason": "large_amount_needs_confirmation",
                        "amount": card.amount,
                    })
                    continue

                self.approve(card_id, comment=comment, actor=actor, force=not skip_large)
                result.approved += 1
                result.details.append({"card_id": card_id, "status": "approved"})

            except ConfirmationRequiredError:
                result.skipped += 1
                result.details.append({
                    "card_id": card_id,
                    "status": "skipped",
                    "reason": "needs_confirmation",
                })
            except Exception as e:
                result.errors += 1
                result.details.append({"card_id": card_id, "status": "error", "reason": str(e)})

        logger.info(f"Batch approve: {result.approved}/{result.total} approved, {result.skipped} skipped, {result.errors} errors")
        return result

    def batch_reject(
        self,
        card_ids: List[str],
        comment: str = "",
        actor: str = "",
    ) -> BatchApprovalResult:
        """Batch reject multiple approval cards."""
        result = BatchApprovalResult(total=len(card_ids))

        for card_id in card_ids:
            try:
                self.reject(card_id, comment=comment, actor=actor)
                result.rejected += 1
                result.details.append({"card_id": card_id, "status": "rejected"})
            except Exception as e:
                result.errors += 1
                result.details.append({"card_id": card_id, "status": "error", "reason": str(e)})

        return result

    def get_pending_cards(
        self,
        confidence_level: Optional[str] = None,
        amount_category: Optional[AmountCategory] = None,
    ) -> List[ApprovalCard]:
        """Get pending approval cards with optional filters.

        Args:
            confidence_level: Filter by confidence (high/medium/low)
            amount_category: Filter by amount category

        Returns:
            List of pending cards
        """
        cards = [c for c in self._cards.values() if c.status == ApprovalStatus.PENDING]

        if confidence_level:
            cards = [c for c in cards if c.confidence_level == confidence_level]

        if amount_category:
            cards = [c for c in cards if c.amount_category == amount_category]

        # Sort by confidence (high first), then by creation time
        cards.sort(key=lambda c: (-c.confidence, c.created_at))
        return cards

    def get_card(self, card_id: str) -> Optional[ApprovalCard]:
        """Get a specific approval card."""
        return self._cards.get(card_id)

    def get_stats(self) -> Dict[str, Any]:
        """Get approval statistics."""
        all_cards = list(self._cards.values())
        pending = [c for c in all_cards if c.status == ApprovalStatus.PENDING]
        approved = [c for c in all_cards if c.status == ApprovalStatus.APPROVED]
        rejected = [c for c in all_cards if c.status == ApprovalStatus.REJECTED]

        return {
            "total": len(all_cards),
            "pending": len(pending),
            "approved": len(approved),
            "rejected": len(rejected),
            "by_confidence": {
                "high": len([c for c in pending if c.confidence_level == "high"]),
                "medium": len([c for c in pending if c.confidence_level == "medium"]),
                "low": len([c for c in pending if c.confidence_level == "low"]),
            },
            "by_amount": {
                "small": len([c for c in pending if c.amount_category == AmountCategory.SMALL]),
                "medium": len([c for c in pending if c.amount_category == AmountCategory.MEDIUM]),
                "large": len([c for c in pending if c.amount_category == AmountCategory.LARGE]),
                "unknown": len([c for c in pending if c.amount_category == AmountCategory.UNKNOWN]),
            },
        }

    def _get_card(self, card_id: str) -> ApprovalCard:
        """Get card or raise error."""
        card = self._cards.get(card_id)
        if not card:
            raise ValueError(f"Card not found: {card_id}")
        return card

    def _log_action(self, card: ApprovalCard, action: str, actor: str, detail: str = ""):
        """Log an approval action."""
        self._action_log.append({
            "card_id": card.card_id,
            "email_id": card.email_id,
            "action": action,
            "actor": actor,
            "detail": detail,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })


class ConfirmationRequiredError(Exception):
    """Raised when large amount approval needs double confirmation."""
    pass
