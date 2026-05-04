"""Tests for W7: Approval detection + Actions + API."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.gate.models import GateClass
from scenes.approval import ApprovalDetection, ApprovalDetector, ApprovalType, ConfidenceLevel
from scenes.approval.actions import (
    AmountCategory,
    ApprovalAction,
    ApprovalActions,
    ApprovalCard,
    ApprovalStatus,
    ConfirmationRequiredError,
    classify_amount,
)
from sync.models import Email, EmailAddress


class TestApprovalDetector:
    """Test dual-layer approval detection."""

    @pytest.fixture
    def detector(self):
        with patch('scenes.approval.detector.get_llm_client'), \
             patch('scenes.approval.detector.get_fallback'), \
             patch('scenes.approval.detector.TokenBudget'):
            return ApprovalDetector()

    @pytest.mark.asyncio
    async def test_detect_spam_rejected(self, detector):
        email = Email(
            message_id="<spam@test.com>",
            subject="免费领取优惠券！！！",
            from_addr=EmailAddress("promo@spam.com", "促销"),
            to_addrs=[EmailAddress("user@company.com", "用户")],
            text_body="恭喜中奖！点击领取",
            date=datetime(2024, 1, 1),
        )
        result = await detector.detect(email)
        assert result.is_approval is False
        assert result.gate_class == GateClass.SPAM

    @pytest.mark.asyncio
    async def test_detect_direct_approval(self, detector):
        email = Email(
            message_id="<approve@test.com>",
            subject="请审批项目预算",
            from_addr=EmailAddress("pm@company.com", "PM"),
            to_addrs=[EmailAddress("user@company.com", "用户")],
            text_body="请审批附件中的项目预算方案",
            date=datetime(2024, 1, 1),
        )
        result = await detector.detect(email)
        assert result.is_approval is True
        assert result.approval_type == ApprovalType.DIRECT

    @pytest.mark.asyncio
    async def test_detect_routine(self, detector):
        email = Email(
            message_id="<routine@test.com>",
            subject="项目进度更新",
            from_addr=EmailAddress("colleague@company.com", "同事"),
            to_addrs=[EmailAddress("user@company.com", "用户")],
            text_body="本周项目进展顺利",
            date=datetime(2024, 1, 1),
        )
        result = await detector.detect(email)
        assert result.is_approval is False

    def test_confidence_level_mapping(self):
        from scenes.approval.detector import _confidence_to_level
        assert _confidence_to_level(0.95) == ConfidenceLevel.HIGH
        assert _confidence_to_level(0.70) == ConfidenceLevel.MEDIUM
        assert _confidence_to_level(0.40) == ConfidenceLevel.LOW

    def test_needs_action_logic(self):
        high = ApprovalDetection(
            is_approval=True, approval_type=ApprovalType.DIRECT,
            confidence=0.9, confidence_level=ConfidenceLevel.HIGH,
            gate_class=GateClass.IMPORTANT,
        )
        assert high.needs_action is True

        low = ApprovalDetection(
            is_approval=True, approval_type=ApprovalType.DIRECT,
            confidence=0.4, confidence_level=ConfidenceLevel.LOW,
            gate_class=GateClass.ROUTINE,
        )
        assert low.needs_action is False

    def test_should_push_logic(self):
        high = ApprovalDetection(
            is_approval=True, approval_type=ApprovalType.DIRECT,
            confidence=0.9, confidence_level=ConfidenceLevel.HIGH,
            gate_class=GateClass.IMPORTANT,
        )
        assert high.should_push is True

        cc = ApprovalDetection(
            is_approval=True, approval_type=ApprovalType.CC,
            confidence=0.9, confidence_level=ConfidenceLevel.HIGH,
            gate_class=GateClass.ROUTINE,
        )
        assert cc.should_push is False

    def test_amount_extraction(self, detector):
        email = Email(
            message_id="<amt@test.com>",
            subject="请审批采购订单",
            from_addr=EmailAddress("pm@company.com", "PM"),
            to_addrs=[EmailAddress("user@company.com", "用户")],
            text_body="采购金额：¥50,000，请审批",
            date=datetime(2024, 1, 1),
        )
        approver, requester, amount, deadline = detector._extract_details(email, MagicMock())
        assert amount == 50000.0


class TestApprovalActions:
    """Test approval closed-loop operations."""

    @pytest.fixture
    def actions(self):
        return ApprovalActions()

    def test_create_card(self, actions):
        card = actions.create_card(
            email_id="e1",
            subject="请审批预算",
            confidence=0.9,
            confidence_level="high",
            amount=5000,
        )
        assert card.email_id == "e1"
        assert card.amount_category == AmountCategory.SMALL
        assert card.is_actionable is True

    def test_approve_card(self, actions):
        card = actions.create_card(email_id="e1", subject="审批1", confidence=0.9)
        result = actions.approve(card.card_id, actor="user1")
        assert result.status == ApprovalStatus.APPROVED
        assert result.action == ApprovalAction.APPROVE

    def test_reject_card(self, actions):
        card = actions.create_card(email_id="e2", subject="审批2", confidence=0.8)
        result = actions.reject(card.card_id, comment="预算超支", actor="user1")
        assert result.status == ApprovalStatus.REJECTED

    def test_forward_card(self, actions):
        card = actions.create_card(email_id="e3", subject="审批3", confidence=0.7)
        result = actions.forward(card.card_id, forward_to="boss@company.com", actor="user1")
        assert result.status == ApprovalStatus.FORWARDED

    def test_large_amount_requires_confirmation(self, actions):
        card = actions.create_card(
            email_id="e4", subject="大额审批", confidence=0.9, amount=200000,
        )
        assert card.is_large_amount is True
        with pytest.raises(ConfirmationRequiredError):
            actions.approve(card.card_id)
        # Force confirm
        result = actions.approve(card.card_id, force=True, actor="user1")
        assert result.status == ApprovalStatus.APPROVED

    def test_batch_approve(self, actions):
        cards = []
        for i in range(5):
            c = actions.create_card(
                email_id=f"e{i}", subject=f"审批{i}", confidence=0.8,
                amount=1000,  # Small amounts
            )
            cards.append(c)
        result = actions.batch_approve(
            card_ids=[c.card_id for c in cards],
            actor="user1",
        )
        assert result.approved == 5
        assert result.total == 5

    def test_classify_amount(self):
        assert classify_amount(5000) == AmountCategory.SMALL
        assert classify_amount(50000) == AmountCategory.MEDIUM
        assert classify_amount(200000) == AmountCategory.LARGE
        assert classify_amount(None) == AmountCategory.UNKNOWN

    def test_get_pending_cards(self, actions):
        actions.create_card(email_id="e1", subject="A", confidence=0.9, confidence_level="high")
        actions.create_card(email_id="e2", subject="B", confidence=0.5, confidence_level="low")
        pending = actions.get_pending_cards()
        assert len(pending) == 2
        # High confidence first
        assert pending[0].confidence_level == "high"

    def test_get_stats(self, actions):
        actions.create_card(email_id="e1", subject="A", confidence=0.9)
        stats = actions.get_stats()
        assert stats["total"] == 1
        assert stats["pending"] == 1
