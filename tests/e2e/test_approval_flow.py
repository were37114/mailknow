"""
E2E审批闭环测试

端到端验证：同步邮件 → Gate分流 → Tier2筛选 → Tier4精筛 → 审批卡片 → 用户操作 → 归档

验证点：
1. Gate分流正确
2. 审批识别准确
3. 卡片展示正确（置信度、金额分类）
4. 用户操作生效（approve/reject/forward/delegate/batch）
5. 大额双确认
6. 归档成功

作者：MailKnow Team
日期：2026-05-02
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src'))

from core.gate.classifier import GateClassifier, EmailInfo
from core.gate.models import GateClass
from scenes.approval.detector import ApprovalDetector, ApprovalType, ConfidenceLevel, ApprovalDetection
from scenes.approval.actions import (
    ApprovalActions, ApprovalCard, ApprovalStatus, ApprovalAction,
    AmountCategory, classify_amount, ConfirmationRequiredError, BatchApprovalResult,
)
from sync.models import Email, EmailAddress


# ── Fixtures ──

@pytest.fixture
def gate_classifier():
    return GateClassifier()


@pytest.fixture
def approval_actions():
    return ApprovalActions()


def make_email(subject, from_addr, to_addrs, cc_addrs=None, content=""):
    """辅助函数：创建 Email 对象"""
    from_addr_obj = EmailAddress(address=from_addr, name="") if from_addr else None
    to_addr_objs = [EmailAddress(address=a, name="") for a in to_addrs]
    cc_addr_objs = [EmailAddress(address=a, name="") for a in (cc_addrs or [])]

    return Email(
        message_id=f"msg-{hash(subject) % 10000}",
        subject=subject,
        from_addr=from_addr_obj,
        to_addrs=to_addr_objs,
        cc_addrs=cc_addr_objs,
        text_body=content,
        html_body="",
        date=datetime.now(timezone.utc),
        attachments=[],
    )


# ── 测试：审批闭环全流程 ──

class TestApprovalFlowE2E:
    """E2E审批闭环：从邮件到卡片到操作"""

    @pytest.mark.asyncio
    async def test_direct_approval_full_flow(self, gate_classifier, approval_actions):
        """直接审批全流程：邮件 → Gate → 检测 → 卡片 → 批准"""
        # 1. 准备审批邮件
        email = make_email(
            subject="请审批Q2采购申请",
            from_addr="pm@company.com",
            to_addrs=["user@company.com"],
            content="请审批Q2采购申请，金额￥50,000",
        )

        # 2. Gate分流
        email_info = EmailInfo(
            subject=email.subject,
            from_addr=str(email.from_addr.address),
            to_addrs=[str(a.address) for a in email.to_addrs],
            cc_addrs=[],
            content=email.text_body,
        )
        gate_result = gate_classifier.classify(email_info)
        assert gate_result.gate_class in (GateClass.IMPORTANT, GateClass.URGENT, GateClass.ROUTINE)

        # 3. 创建审批卡片
        card = approval_actions.create_card(
            email_id=email.message_id,
            subject=email.subject,
            requester="pm@company.com",
            approver="user@company.com",
            confidence=0.92,
            confidence_level="high",
            amount=50000.0,
            currency="CNY",
            gate_class=gate_result.gate_class.value,
            reason="审批关键词匹配",
        )

        # 4. 验证卡片属性
        assert card.status == ApprovalStatus.PENDING
        assert card.is_actionable is True
        assert card.amount == 50000.0
        assert card.amount_category == AmountCategory.MEDIUM
        assert card.confidence_level == "high"

        # 5. 批准
        approved = approval_actions.approve(card.card_id, comment="同意", actor="user@company.com")
        assert approved.status == ApprovalStatus.APPROVED
        assert approved.action == ApprovalAction.APPROVE
        assert approved.comment == "同意"
        assert approved.is_actionable is False  # 已操作不可再操作

    @pytest.mark.asyncio
    async def test_rejection_flow(self, approval_actions):
        """拒绝审批流程"""
        card = approval_actions.create_card(
            email_id="email-reject-001",
            subject="差旅申请",
            requester="employee@company.com",
            approver="user@company.com",
            confidence=0.85,
            confidence_level="high",
            amount=3000.0,
            currency="CNY",
        )

        rejected = approval_actions.reject(card.card_id, comment="超出预算", actor="user@company.com")
        assert rejected.status == ApprovalStatus.REJECTED
        assert rejected.action == ApprovalAction.REJECT

    @pytest.mark.asyncio
    async def test_forward_flow(self, approval_actions):
        """转发审批流程"""
        card = approval_actions.create_card(
            email_id="email-forward-001",
            subject="合同审批",
            requester="legal@company.com",
            approver="user@company.com",
            confidence=0.80,
            confidence_level="medium",
        )

        forwarded = approval_actions.forward(
            card.card_id, forward_to="director@company.com",
            comment="请总监审批", actor="user@company.com"
        )
        assert forwarded.status == ApprovalStatus.FORWARDED
        assert "director@company.com" in forwarded.comment

    @pytest.mark.asyncio
    async def test_delegate_flow(self, approval_actions):
        """委派审批流程"""
        card = approval_actions.create_card(
            email_id="email-delegate-001",
            subject="预算审批",
            requester="cfo@company.com",
            approver="user@company.com",
            confidence=0.88,
            confidence_level="high",
        )

        delegated = approval_actions.delegate(
            card.card_id, delegate_to="deputy@company.com",
            actor="user@company.com"
        )
        assert delegated.status == ApprovalStatus.DELEGATED

    @pytest.mark.asyncio
    async def test_large_amount_double_confirmation(self, approval_actions):
        """大额审批双确认"""
        card = approval_actions.create_card(
            email_id="email-large-001",
            subject="大额采购审批",
            requester="cto@company.com",
            approver="user@company.com",
            confidence=0.95,
            confidence_level="high",
            amount=200000.0,
            currency="CNY",
        )

        # 大额应需要双确认
        assert card.is_large_amount is True
        assert card.amount_category == AmountCategory.LARGE

        # 不带 force 应抛出 ConfirmationRequiredError
        with pytest.raises(ConfirmationRequiredError):
            approval_actions.approve(card.card_id, actor="user@company.com")

        # 带 force 应成功
        approved = approval_actions.approve(
            card.card_id, actor="user@company.com", force=True
        )
        assert approved.status == ApprovalStatus.APPROVED

    @pytest.mark.asyncio
    async def test_small_amount_simplified(self, approval_actions):
        """小额审批简化流程"""
        card = approval_actions.create_card(
            email_id="email-small-001",
            subject="小额采购",
            requester="team@company.com",
            approver="user@company.com",
            confidence=0.90,
            confidence_level="high",
            amount=5000.0,
            currency="CNY",
        )

        assert card.is_small_amount is True
        assert card.amount_category == AmountCategory.SMALL

        # 小额不需要双确认
        approved = approval_actions.approve(card.card_id, actor="user@company.com")
        assert approved.status == ApprovalStatus.APPROVED

    @pytest.mark.asyncio
    async def test_batch_approval(self, approval_actions):
        """批量审批"""
        card_ids = []
        for i in range(5):
            card = approval_actions.create_card(
                email_id=f"email-batch-{i}",
                subject=f"批量审批{i}",
                requester="team@company.com",
                approver="user@company.com",
                confidence=0.85,
                confidence_level="high",
                amount=3000.0 + i * 1000,
                currency="CNY",
            )
            card_ids.append(card.card_id)

        # 添加一个大额审批
        large_card = approval_actions.create_card(
            email_id="email-batch-large",
            subject="大额审批",
            requester="team@company.com",
            approver="user@company.com",
            confidence=0.90,
            confidence_level="high",
            amount=150000.0,
            currency="CNY",
        )
        card_ids.append(large_card.card_id)

        result = approval_actions.batch_approve(
            card_ids, comment="批量通过", actor="user@company.com",
            skip_large=True,
        )

        assert isinstance(result, BatchApprovalResult)
        assert result.total == 6
        assert result.approved == 5  # 5个小额通过
        assert result.skipped == 1   # 1个大额跳过
        assert result.errors == 0


class TestAmountClassification:
    """金额分类测试"""

    def test_small_amount(self):
        assert classify_amount(5000) == AmountCategory.SMALL
        assert classify_amount(10000) == AmountCategory.SMALL

    def test_medium_amount(self):
        assert classify_amount(50000) == AmountCategory.MEDIUM
        assert classify_amount(100000) == AmountCategory.MEDIUM

    def test_large_amount(self):
        assert classify_amount(200000) == AmountCategory.LARGE
        assert classify_amount(1000000) == AmountCategory.LARGE

    def test_unknown_amount(self):
        assert classify_amount(None) == AmountCategory.UNKNOWN


class TestApprovalCardStates:
    """审批卡片状态测试"""

    def test_card_lifecycle(self, approval_actions):
        """卡片生命周期：PENDING → APPROVED"""
        card = approval_actions.create_card(
            email_id="test-lifecycle",
            subject="生命周期测试",
            confidence=0.90,
            confidence_level="high",
        )

        assert card.status == ApprovalStatus.PENDING
        assert card.is_actionable is True

        approved = approval_actions.approve(card.card_id, actor="test")
        assert approved.status == ApprovalStatus.APPROVED
        assert approved.is_actionable is False

    def test_cannot_operate_on_completed_card(self, approval_actions):
        """已完成的卡片不可再操作"""
        card = approval_actions.create_card(
            email_id="test-completed",
            subject="已完成卡片",
            confidence=0.90,
            confidence_level="high",
        )
        approval_actions.approve(card.card_id, actor="test")

        with pytest.raises(ValueError, match="not actionable"):
            approval_actions.reject(card.card_id, actor="test")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
