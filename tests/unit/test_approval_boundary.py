"""Boundary tests for approval detection.

Tests edge cases from approval_samples.json:
- CC approval (low confidence)
- Completed notification (Gate1 but not approval request)
- System forwarded approval
- Confirmation email (not approval)
- English approval email
- Mass CC approval notification
- Urgent approval
- Rejection notification
- Discussion with implicit approval
- Pure discussion (no approval)
"""

import json
import pytest
from datetime import datetime
from pathlib import Path

from scenes.approval import ApprovalDetector, ApprovalType
from core.wiring import Tier4Extractor
from sync.models import Email, EmailAddress


@pytest.fixture
def detector():
    """Create approval detector."""
    return ApprovalDetector()


@pytest.fixture
def tier4():
    """Create Tier4 extractor."""
    return Tier4Extractor()


@pytest.fixture
def samples():
    """Load approval boundary samples."""
    samples_path = Path(__file__).parent.parent / "datasets" / "approval_samples.json"
    if samples_path.exists():
        with open(samples_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _sample_to_email(sample: dict) -> Email:
    """Convert sample dict to Email."""
    email_data = sample["email"]
    return Email(
        message_id=f"<{sample['id']}@test.com>",
        subject=email_data["subject"],
        from_addr=EmailAddress(email_data["from_addr"]),
        to_addrs=[EmailAddress(a) for a in email_data.get("to_addrs", [])],
        cc_addrs=[EmailAddress(a) for a in email_data.get("cc_addrs", [])],
        text_body=email_data.get("content", ""),
        date=datetime(2024, 1, 1),
    )


# --- Direct boundary tests (no samples file dependency) ---

def test_cc_approval_low_confidence(tier4: Tier4Extractor):
    """Test CC approval has lower confidence."""
    email = Email(
        message_id="<cc@test.com>",
        subject="FYI: 合同审批请求",
        from_addr=EmailAddress("pm@company.com"),
        to_addrs=[],
        cc_addrs=[EmailAddress("user@company.com")],
        text_body="请审批合同，抄送知会",
        date=datetime(2024, 1, 1)
    )
    
    result = tier4._local_approval_classify(email)
    
    assert result.is_approval is True
    assert result.approval_type == "cc"
    assert result.confidence < 0.8  # CC should have lower confidence


def test_completed_notification_not_approval(tier4: Tier4Extractor):
    """Test completed approval notification is not classified as approval."""
    email = Email(
        message_id="<done@test.com>",
        subject="合同审批已通过",
        from_addr=EmailAddress("system@company.com"),
        to_addrs=[EmailAddress("user@company.com")],
        text_body="您提交的合同审批已通过",
        date=datetime(2024, 1, 1)
    )
    
    result = tier4._local_approval_classify(email)
    
    assert result.is_approval is False
    assert result.approval_type == "notification"


def test_system_forwarded_approval(tier4: Tier4Extractor):
    """Test system forwarded approval is classified correctly."""
    email = Email(
        message_id="<forward@test.com>",
        subject="【系统转发】采购审批单 #12345",
        from_addr=EmailAddress("oa@company.com"),
        to_addrs=[EmailAddress("user@company.com")],
        text_body="请审批采购申请单#12345",
        date=datetime(2024, 1, 1)
    )
    
    result = tier4._local_approval_classify(email)
    
    assert result.is_approval is True
    assert result.approval_type == "direct"


def test_confirmation_not_approval(tier4: Tier4Extractor):
    """Test confirmation email is not classified as approval."""
    email = Email(
        message_id="<confirm@test.com>",
        subject="确认明天会议时间",
        from_addr=EmailAddress("colleague@company.com"),
        to_addrs=[EmailAddress("user@company.com")],
        text_body="确认明天的会议时间改为下午3点",
        date=datetime(2024, 1, 1)
    )
    
    result = tier4._local_approval_classify(email)
    
    assert result.is_approval is False
    assert result.approval_type == "none"


def test_english_approval(tier4: Tier4Extractor):
    """Test English approval email."""
    email = Email(
        message_id="<eng@test.com>",
        subject="Please approve the budget request",
        from_addr=EmailAddress("manager@company.com"),
        to_addrs=[EmailAddress("user@company.com")],
        text_body="Hi, please review and approve the Q2 budget request attached.",
        date=datetime(2024, 1, 1)
    )
    
    result = tier4._local_approval_classify(email)
    
    assert result.is_approval is True
    assert result.approval_type == "direct"


def test_urgent_approval(tier4: Tier4Extractor):
    """Test urgent approval email."""
    email = Email(
        message_id="<urgent@test.com>",
        subject="【紧急】请立即审批服务器采购",
        from_addr=EmailAddress("cto@company.com"),
        to_addrs=[EmailAddress("user@company.com")],
        text_body="服务器即将到期，请紧急审批采购申请",
        date=datetime(2024, 1, 1)
    )
    
    result = tier4._local_approval_classify(email)
    
    assert result.is_approval is True
    assert result.approval_type == "direct"


def test_rejection_notification(tier4: Tier4Extractor):
    """Test approval rejection notification."""
    email = Email(
        message_id="<reject@test.com>",
        subject="审批未通过：差旅申请",
        from_addr=EmailAddress("system@company.com"),
        to_addrs=[EmailAddress("user@company.com")],
        text_body="您的差旅申请审批未通过，原因：超出预算",
        date=datetime(2024, 1, 1)
    )
    
    result = tier4._local_approval_classify(email)
    
    assert result.is_approval is False
    assert result.approval_type == "notification"


def test_implicit_approval_in_discussion(tier4: Tier4Extractor):
    """Test discussion with implicit approval request."""
    email = Email(
        message_id="<implicit@test.com>",
        subject="关于新项目方案的讨论",
        from_addr=EmailAddress("pm@company.com"),
        to_addrs=[EmailAddress("user@company.com")],
        text_body="新项目方案已整理完成，请审核确认",
        date=datetime(2024, 1, 1)
    )
    
    result = tier4._local_approval_classify(email)
    
    assert result.is_approval is True
    assert result.approval_type == "direct"


def test_pure_discussion(tier4: Tier4Extractor):
    """Test pure discussion email without approval."""
    email = Email(
        message_id="<discuss@test.com>",
        subject="关于技术方案的讨论",
        from_addr=EmailAddress("dev@company.com"),
        to_addrs=[EmailAddress("user@company.com")],
        text_body="我觉得方案A更好，大家觉得呢？",
        date=datetime(2024, 1, 1)
    )
    
    result = tier4._local_approval_classify(email)
    
    assert result.is_approval is False
    assert result.approval_type == "none"


# --- Sample-driven tests ---

@pytest.mark.asyncio
async def test_boundary_samples(detector: ApprovalDetector, samples: list):
    """Test all boundary samples from JSON."""
    if not samples:
        pytest.skip("No sample file found")
    
    passed = 0
    failed = 0
    
    for sample in samples:
        email = _sample_to_email(sample)
        expected = sample["expected"]
        
        result = await detector.detect(email)
        
        # Check is_approval
        if result.is_approval != expected["is_approval"]:
            failed += 1
            print(f"FAIL {sample['id']}: expected is_approval={expected['is_approval']}, got {result.is_approval}")
        else:
            passed += 1
    
    # At least 70% should pass for MVP
    if samples:
        pass_rate = passed / len(samples)
        assert pass_rate >= 0.7, f"Pass rate {pass_rate:.0%} < 70% ({passed}/{len(samples)})"
