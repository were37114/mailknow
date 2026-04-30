"""Tests for Gate classifier."""

import pytest
from core.gate import GateClassifier, GateClass, GateResult
from core.gate.classifier import EmailInfo


@pytest.fixture
def classifier():
    """Create a Gate classifier."""
    return GateClassifier()


def test_gate_class_priority():
    """Test Gate class priority order."""
    assert GateClass.URGENT.priority > GateClass.SPAM.priority
    assert GateClass.SPAM.priority > GateClass.NOTIFICATION.priority
    assert GateClass.NOTIFICATION.priority > GateClass.ROUTINE.priority
    assert GateClass.ROUTINE.priority > GateClass.IMPORTANT.priority


def test_gate_class_ui_labels():
    """Test UI labels (4档呈现)."""
    assert GateClass.URGENT.ui_label == "⭐ 重要"
    assert GateClass.IMPORTANT.ui_label == "⭐ 重要"
    assert GateClass.ROUTINE.ui_label == "📬 一般"
    assert GateClass.NOTIFICATION.ui_label == "📬 一般"
    assert GateClass.SPAM.ui_label == "🗑️ 垃圾"


def test_classify_urgent_email(classifier: GateClassifier):
    """Test classifying urgent email."""
    email = EmailInfo(
        subject="【紧急】请立即处理",
        from_addr="boss@company.com",
        to_addrs=["user@company.com"],
        content="这是一封紧急邮件"
    )
    
    result = classifier.classify(email)
    
    assert result.gate_class == GateClass.URGENT
    assert result.confidence > 0
    assert "subject_keywords" in result.matched_rules or "subject_pattern" in result.matched_rules


def test_classify_spam_email(classifier: GateClassifier):
    """Test classifying spam email."""
    email = EmailInfo(
        subject="恭喜您中奖了！免费领取优惠券",
        from_addr="promo@spam.com",
        to_addrs=["user@example.com"],
        content="点击链接领取大奖"
    )
    
    result = classifier.classify(email)
    
    assert result.gate_class == GateClass.SPAM


def test_classify_notification_email(classifier: GateClassifier):
    """Test classifying notification email."""
    email = EmailInfo(
        subject="【通知】您的订单已发货",
        from_addr="noreply@shop.com",
        to_addrs=["user@example.com"],
        content="您的订单已发货，请注意查收"
    )
    
    result = classifier.classify(email)
    
    assert result.gate_class == GateClass.NOTIFICATION


def test_classify_important_email(classifier: GateClassifier):
    """Test classifying important email."""
    email = EmailInfo(
        subject="【重要】合同审批请求",
        from_addr="colleague@company.com",
        to_addrs=["user@company.com"],
        content="请审批附件中的合同",
        has_attachments=True
    )
    
    result = classifier.classify(email)
    
    # Important has lowest priority, so may be overridden
    assert result.gate_class in [GateClass.IMPORTANT, GateClass.ROUTINE]


def test_classify_routine_email(classifier: GateClassifier):
    """Test classifying routine email."""
    email = EmailInfo(
        subject="关于项目进度的讨论",
        from_addr="colleague@company.com",
        to_addrs=["user@company.com"],
        content="我们讨论一下项目的下一步计划"
    )
    
    result = classifier.classify(email)
    
    assert result.gate_class == GateClass.ROUTINE


def test_conflict_resolution_urgent_over_spam(classifier: GateClassifier):
    """Test that urgent has higher priority than spam."""
    # Email with both urgent and spam keywords
    email = EmailInfo(
        subject="【紧急】免费领取优惠券",
        from_addr="boss@company.com",
        to_addrs=["user@company.com"],
        content="请立即处理"
    )
    
    result = classifier.classify(email)
    
    # Urgent should win over spam
    assert result.gate_class == GateClass.URGENT


def test_conflict_resolution_spam_over_notification(classifier: GateClassifier):
    """Test that spam has higher priority than notification."""
    email = EmailInfo(
        subject="【通知】恭喜中奖",
        from_addr="noreply@spam.com",
        to_addrs=["user@example.com"],
        content="您已中奖，点击领取"
    )
    
    result = classifier.classify(email)
    
    # Spam should win over notification
    assert result.gate_class == GateClass.SPAM


def test_classify_with_flags(classifier: GateClassifier):
    """Test classification with email flags."""
    email = EmailInfo(
        subject="项目进度更新",
        from_addr="pm@company.com",
        to_addrs=["user@company.com"],
        content="请查看项目进度",
        flags=["\\Flagged"]
    )
    
    result = classifier.classify(email)
    
    # Flagged emails should be urgent
    assert result.gate_class == GateClass.URGENT


def test_classify_auto_reply(classifier: GateClassifier):
    """Test classification of auto-reply emails."""
    email = EmailInfo(
        subject="自动回复：不在办公室",
        from_addr="colleague@company.com",
        to_addrs=["user@company.com"],
        content="我已收到您的邮件",
        is_auto_reply=True
    )
    
    result = classifier.classify(email)
    
    assert result.gate_class == GateClass.NOTIFICATION


def test_gate_result_properties():
    """Test GateResult properties."""
    result = GateResult(
        gate_class=GateClass.URGENT,
        confidence=0.9,
        matched_rules=["subject_keywords"],
        score=0.95
    )
    
    assert result.is_urgent
    assert not result.is_spam
    assert result.ui_label == "⭐ 重要"


def test_reload_rules(classifier: GateClassifier):
    """Test hot reload of rules."""
    # Should succeed
    success = classifier.reload_rules()
    assert success


def test_classify_chinese_keywords(classifier: GateClassifier):
    """Test classification with Chinese keywords."""
    email = EmailInfo(
        subject="紧急：明天会议取消",
        from_addr="admin@company.com",
        to_addrs=["user@company.com"],
        content="明天的会议因故取消"
    )
    
    result = classifier.classify(email)
    
    assert result.gate_class == GateClass.URGENT


def test_classify_english_keywords(classifier: GateClassifier):
    """Test classification with English keywords."""
    email = EmailInfo(
        subject="URGENT: Server Down",
        from_addr="ops@company.com",
        to_addrs=["user@company.com"],
        content="The server is down, please check immediately"
    )
    
    result = classifier.classify(email)
    
    assert result.gate_class == GateClass.URGENT


def test_classify_verification_code(classifier: GateClassifier):
    """Test classification of verification code emails."""
    email = EmailInfo(
        subject="您的验证码",
        from_addr="noreply@service.com",
        to_addrs=["user@example.com"],
        content="您的验证码是：123456"
    )
    
    result = classifier.classify(email)
    
    assert result.gate_class == GateClass.NOTIFICATION


def test_classify_marketing_email(classifier: GateClassifier):
    """Test classification of marketing emails."""
    email = EmailInfo(
        subject="双十一大促，全场5折起",
        from_addr="marketing@shop.com",
        to_addrs=["user@example.com"],
        content="限时优惠，错过等一年\n退订请回复TD"
    )
    
    result = classifier.classify(email)
    
    assert result.gate_class == GateClass.SPAM
