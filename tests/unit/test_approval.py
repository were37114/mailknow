"""Tests for approval detection."""

import pytest
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch

from scenes.approval import ApprovalDetector, ApprovalDetection, ApprovalType, ConfidenceLevel
from core.wiring import Tier4Extractor, ApprovalResult
from core.gate import GateClassifier, GateClass
from sync.models import Email, EmailAddress


@pytest.fixture
def detector():
    """Create approval detector."""
    return ApprovalDetector()


@pytest.fixture
def tier4():
    """Create Tier4 extractor."""
    return Tier4Extractor()


def test_local_approval_classify_direct(tier4: Tier4Extractor):
    """Test local classification of direct approval email."""
    email = Email(
        message_id="<approve1@example.com>",
        subject="请审批合同",
        from_addr=EmailAddress("colleague@company.com", "同事"),
        to_addrs=[EmailAddress("user@company.com", "用户")],
        text_body="请审批附件中的合同，谢谢",
        date=datetime(2024, 1, 1)
    )
    
    result = tier4._local_approval_classify(email)
    
    assert result.is_approval is True
    assert result.approval_type == "direct"
    assert result.confidence > 0.7


def test_local_approval_classify_cc(tier4: Tier4Extractor):
    """Test local classification of CC approval email."""
    email = Email(
        message_id="<cc1@example.com>",
        subject="审批请求 - 合同",
        from_addr=EmailAddress("colleague@company.com", "同事"),
        to_addrs=[],
        cc_addrs=[EmailAddress("user@company.com", "用户")],
        text_body="请审批合同",
        date=datetime(2024, 1, 1)
    )
    
    result = tier4._local_approval_classify(email)
    
    assert result.is_approval is True
    assert result.approval_type == "cc"
    assert result.confidence < 0.8  # Lower confidence for CC


def test_local_approval_classify_notification(tier4: Tier4Extractor):
    """Test local classification of approval notification."""
    email = Email(
        message_id="<notify1@example.com>",
        subject="审批通过通知",
        from_addr=EmailAddress("system@company.com", "系统"),
        to_addrs=[EmailAddress("user@company.com", "用户")],
        text_body="您的审批已通过",
        date=datetime(2024, 1, 1)
    )
    
    result = tier4._local_approval_classify(email)
    
    assert result.is_approval is False
    assert result.approval_type == "notification"


def test_local_approval_classify_routine(tier4: Tier4Extractor):
    """Test local classification of routine email."""
    email = Email(
        message_id="<routine1@example.com>",
        subject="项目进度更新",
        from_addr=EmailAddress("colleague@company.com", "同事"),
        to_addrs=[EmailAddress("user@company.com", "用户")],
        text_body="本周项目进展顺利",
        date=datetime(2024, 1, 1)
    )
    
    result = tier4._local_approval_classify(email)
    
    assert result.is_approval is False
    assert result.approval_type == "none"


def test_parse_approval_response(tier4: Tier4Extractor):
    """Test parsing LLM approval response."""
    # Valid JSON
    response = '{"is_approval": true, "confidence": 0.9, "approval_type": "direct", "reason": "包含审批关键词"}'
    result = tier4._parse_approval_response(response)
    
    assert result.is_approval is True
    assert result.confidence == 0.9
    assert result.approval_type == "direct"
    
    # Invalid JSON
    result = tier4._parse_approval_response("not json")
    assert result.is_approval is False
    assert result.approval_type == "none"
    
    # JSON in code block
    response = '```json\n{"is_approval": false, "confidence": 0.8, "approval_type": "none", "reason": "test"}\n```'
    result = tier4._parse_approval_response(response)
    assert result.is_approval is False


def test_truncate_content(tier4: Tier4Extractor):
    """Test content truncation."""
    short = "short content"
    assert tier4._truncate_content(short, max_chars=100) == short
    
    long_content = "a" * 2000
    result = tier4._truncate_content(long_content, max_chars=1000)
    assert len(result) <= 1003  # 1000 + "..."
    assert result.endswith("...")


def test_approval_result_needs_action():
    """Test ApprovalDetection.needs_action property."""
    # Direct high-confidence approval needs action
    direct = ApprovalDetection(
        is_approval=True,
        approval_type=ApprovalType.DIRECT,
        confidence=0.9,
        confidence_level=ConfidenceLevel.HIGH,
        gate_class=GateClass.IMPORTANT,
    )
    assert direct.needs_action is True
    
    # CC approval doesn't need action (regardless of confidence)
    cc = ApprovalDetection(
        is_approval=True,
        approval_type=ApprovalType.CC,
        confidence=0.5,
        confidence_level=ConfidenceLevel.LOW,
        gate_class=GateClass.ROUTINE,
    )
    assert cc.needs_action is False
    
    # Notification doesn't need action
    notification = ApprovalDetection(
        is_approval=False,
        approval_type=ApprovalType.NOTIFICATION,
        confidence=0.8,
        confidence_level=ConfidenceLevel.MEDIUM,
        gate_class=GateClass.NOTIFICATION,
    )
    assert notification.needs_action is False
    
    # Direct low-confidence doesn't need action
    low = ApprovalDetection(
        is_approval=True,
        approval_type=ApprovalType.DIRECT,
        confidence=0.4,
        confidence_level=ConfidenceLevel.LOW,
        gate_class=GateClass.ROUTINE,
    )
    assert low.needs_action is False


@pytest.mark.asyncio
async def test_detector_spam_rejection(detector: ApprovalDetector):
    """Test that spam emails are rejected by detector."""
    email = Email(
        message_id="<spam@example.com>",
        subject="免费领取优惠券",
        from_addr=EmailAddress("promo@spam.com", "促销"),
        to_addrs=[EmailAddress("user@company.com", "用户")],
        text_body="恭喜您中奖了！点击领取",
        date=datetime(2024, 1, 1)
    )
    
    result = await detector.detect(email)
    
    assert result.is_approval is False
    assert result.gate_class == GateClass.SPAM


@pytest.mark.asyncio
async def test_detector_direct_approval(detector: ApprovalDetector):
    """Test detection of direct approval email."""
    email = Email(
        message_id="<direct@example.com>",
        subject="请审批项目预算",
        from_addr=EmailAddress("pm@company.com", "项目经理"),
        to_addrs=[EmailAddress("user@company.com", "用户")],
        text_body="请审批附件中的项目预算方案",
        date=datetime(2024, 1, 1)
    )
    
    result = await detector.detect(email)
    
    assert result.is_approval is True


@pytest.mark.asyncio
async def test_detector_routine_email(detector: ApprovalDetector):
    """Test detection of routine (non-approval) email."""
    email = Email(
        message_id="<routine@example.com>",
        subject="关于项目进度的讨论",
        from_addr=EmailAddress("colleague@company.com", "同事"),
        to_addrs=[EmailAddress("user@company.com", "用户")],
        text_body="我们讨论一下项目的下一步计划",
        date=datetime(2024, 1, 1)
    )
    
    result = await detector.detect(email)
    
    assert result.is_approval is False
