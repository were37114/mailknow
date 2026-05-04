"""Tests for weekly report generator."""

from datetime import datetime

import pytest

from scenes.report import ReportGenerator, ReportSection, WeeklyReport


@pytest.fixture
def generator():
    """Create report generator."""
    return ReportGenerator()


@pytest.fixture
def sample_emails():
    """Create sample email data for testing."""
    return [
        {
            "subject": "请审批Q2预算",
            "from": "cfo@company.com",
            "to": "user@company.com",
            "content": "请审批Q2预算方案",
            "gate_class": "important",
            "date": "2024-01-02",
            "is_approval": True,
            "approval_type": "direct",
        },
        {
            "subject": "项目进度更新",
            "from": "pm@company.com",
            "to": "user@company.com",
            "content": "项目进展顺利",
            "gate_class": "routine",
            "date": "2024-01-03",
        },
        {
            "subject": "【紧急】服务器宕机",
            "from": "ops@company.com",
            "to": "user@company.com",
            "content": "生产服务器宕机，请立即处理",
            "gate_class": "urgent",
            "date": "2024-01-04",
        },
        {
            "subject": "订单已发货",
            "from": "noreply@shop.com",
            "to": "user@company.com",
            "content": "您的订单已发货",
            "gate_class": "notification",
            "date": "2024-01-04",
        },
        {
            "subject": "免费领取优惠券",
            "from": "promo@spam.com",
            "to": "user@company.com",
            "content": "点击领取大奖",
            "gate_class": "spam",
            "date": "2024-01-05",
        },
        {
            "subject": "技术方案讨论",
            "from": "dev@company.com",
            "to": "user@company.com",
            "content": "讨论技术选型",
            "gate_class": "routine",
            "date": "2024-01-05",
        },
        {
            "subject": "会议纪要",
            "from": "pm@company.com",
            "to": "user@company.com",
            "content": "本周会议纪要",
            "gate_class": "routine",
            "date": "2024-01-06",
        },
    ]


def test_generate_report(generator: ReportGenerator, sample_emails):
    """Test basic report generation."""
    report = generator.generate(sample_emails)

    assert isinstance(report, WeeklyReport)
    assert report.total_emails == 7
    assert len(report.sections) > 0


def test_report_has_important_section(generator: ReportGenerator, sample_emails):
    """Test report has important items section."""
    report = generator.generate(sample_emails)

    # Find important section
    important_sections = [s for s in report.sections if "重要" in s.title]
    assert len(important_sections) > 0

    # Should include urgent and important emails
    section = important_sections[0]
    assert section.source_count >= 2  # 1 urgent + 1 important


def test_report_has_approval_section(generator: ReportGenerator, sample_emails):
    """Test report has approval section."""
    report = generator.generate(sample_emails)

    approval_sections = [s for s in report.sections if "审批" in s.title]
    assert len(approval_sections) > 0

    section = approval_sections[0]
    assert section.source_count == 1


def test_report_has_routine_section(generator: ReportGenerator, sample_emails):
    """Test report has routine work section."""
    report = generator.generate(sample_emails)

    routine_sections = [s for s in report.sections if "常规" in s.title]
    assert len(routine_sections) > 0


def test_report_has_notification_section(generator: ReportGenerator, sample_emails):
    """Test report has notification section."""
    report = generator.generate(sample_emails)

    notification_sections = [s for s in report.sections if "通知" in s.title]
    assert len(notification_sections) > 0


def test_report_has_spam_section(generator: ReportGenerator, sample_emails):
    """Test report has spam section."""
    report = generator.generate(sample_emails)

    spam_sections = [s for s in report.sections if "垃圾" in s.title]
    assert len(spam_sections) > 0


def test_report_to_markdown(generator: ReportGenerator, sample_emails):
    """Test markdown output."""
    report = generator.generate(sample_emails)
    md = report.to_markdown()

    assert "# 周报" in md
    assert "基于 7 封邮件" in md
    assert "⭐ 重要事项" in md
    assert "生成时间" in md


def test_report_period(generator: ReportGenerator, sample_emails):
    """Test custom period."""
    report = generator.generate(
        sample_emails,
        period_start="2024-01-01",
        period_end="2024-01-07"
    )

    assert report.period_start == "2024-01-01"
    assert report.period_end == "2024-01-07"

    md = report.to_markdown()
    assert "2024-01-01" in md
    assert "2024-01-07" in md


def test_empty_email_list(generator: ReportGenerator):
    """Test report with no emails."""
    report = generator.generate([])

    assert report.total_emails == 0
    assert len(report.sections) == 0


def test_only_spam_emails(generator: ReportGenerator):
    """Test report with only spam."""
    emails = [
        {"subject": "促销", "from": "spam@x.com", "gate_class": "spam"},
        {"subject": "优惠", "from": "spam@y.com", "gate_class": "spam"},
    ]

    report = generator.generate(emails)

    spam_sections = [s for s in report.sections if "垃圾" in s.title]
    assert len(spam_sections) > 0


def test_group_by_sender(generator: ReportGenerator, sample_emails):
    """Test grouping emails by sender."""
    routine = [e for e in sample_emails if e.get("gate_class") == "routine"]
    groups = generator._group_by_sender(routine)

    assert "pm" in groups  # pm@company.com
    assert "dev" in groups  # dev@company.com
    assert len(groups["pm"]) == 2


def test_no_next_week_plan(generator: ReportGenerator, sample_emails):
    """Test that report does not contain next week plan (V5.2 spec)."""
    report = generator.generate(sample_emails)
    md = report.to_markdown()

    assert "下周计划" not in md
    assert "下周" not in md


def test_deterministic_no_llm(generator: ReportGenerator, sample_emails):
    """Test deterministic report without LLM."""
    report = generator.generate(sample_emails, use_llm=False)

    assert report.llm_used is False
    assert len(report.sections) > 0
