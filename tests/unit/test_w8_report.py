"""Tests for W8: Report generator + DeterministicValidator."""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from scenes.report.generator import (
    ReportGenerator,
    WeeklyReport,
    ReportSection,
    DeterministicValidator,
)


class TestReportGenerator:
    """Test weekly report generation."""

    @pytest.fixture
    def generator(self):
        with patch('scenes.report.generator.get_llm_client'), \
             patch('scenes.report.generator.get_fallback'), \
             patch('scenes.report.generator.TokenBudgetController'):
            return ReportGenerator()

    def test_generate_basic_report(self, generator):
        now = datetime.now(timezone.utc)
        emails = [
            {
                "email_id": "e1",
                "subject": "项目A进展",
                "from": "alice@company.com",
                "to": "user@company.com",
                "content": "项目A本周进展顺利",
                "gate_class": "routine",
                "date": now.isoformat(),
                "is_approval": False,
            },
            {
                "email_id": "e2",
                "subject": "请审批预算",
                "from": "bob@company.com",
                "to": "user@company.com",
                "content": "请审批项目B预算",
                "gate_class": "important",
                "date": now.isoformat(),
                "is_approval": True,
            },
        ]
        report = generator.generate(emails)
        assert isinstance(report, WeeklyReport)
        assert report.total_emails == 2
        assert report.deterministic_only is True

    def test_generate_with_period(self, generator):
        emails = [
            {
                "email_id": "e1",
                "subject": "测试邮件",
                "from": "test@company.com",
                "to": "user@company.com",
                "content": "内容",
                "gate_class": "routine",
                "date": "2024-01-15T10:00:00+00:00",
                "is_approval": False,
            },
        ]
        report = generator.generate(
            emails,
            period_start="2024-01-08",
            period_end="2024-01-14",
        )
        assert report.period_start == "2024-01-08"
        assert report.period_end == "2024-01-14"

    def test_empty_emails_report(self, generator):
        report = generator.generate([])
        assert report.total_emails == 0

    def test_report_has_sections(self, generator):
        emails = [
            {
                "email_id": f"e{i}",
                "subject": f"邮件{i}",
                "from": f"sender{i}@company.com",
                "to": "user@company.com",
                "content": f"内容{i}",
                "gate_class": "routine",
                "date": datetime.now(timezone.utc).isoformat(),
                "is_approval": False,
            }
            for i in range(10)
        ]
        report = generator.generate(emails)
        assert isinstance(report.sections, list)


class TestDeterministicValidator:
    """Test report deterministic compliance validator."""

    @pytest.fixture
    def validator(self):
        return DeterministicValidator()

    def test_valid_report(self, validator):
        report = WeeklyReport(
            period_start="2024-01-08",
            period_end="2024-01-14",
            sections=[ReportSection(title="摘要", items=["项目A进展顺利"], source_count=5)],
            total_emails=10,
            generated_at="2024-01-15 10:00",
            llm_used=False,
            deterministic_only=True,
        )
        passed, warnings = validator.validate(report)
        assert passed is True

    def test_contradictory_flags_warning(self, validator):
        """Items with forbidden predictive phrases should trigger warnings."""
        report = WeeklyReport(
            period_start="2024-01-08",
            period_end="2024-01-14",
            sections=[ReportSection(title="摘要", items=["下周计划完成项目报告"], source_count=1)],
            total_emails=10,
            generated_at="2024-01-15 10:00",
            llm_used=False,
            deterministic_only=True,
        )
        passed, warnings = validator.validate(report)
        assert len(warnings) > 0


class TestReportSection:
    """Test ReportSection data model."""

    def test_creation(self):
        section = ReportSection(
            title="审批邮件",
            items=["请审批预算", "请审批合同"],
            source_count=2,
            source_ids=["e1", "e2"],
        )
        assert section.title == "审批邮件"
        assert len(section.items) == 2
        assert section.source_count == 2
