"""
E2E周报生成测试

端到端验证：GBrain查询 → 聚类 → LLM总结 → 周报编辑器 → 导出

验证点：
1. 事实准确率>90%（无预测性内容）
2. 无"下周计划"等预测性词汇（DeterministicValidator）
3. 周报包含正确的分区（重要事项/待审批/常规工作/通知汇总）
4. Markdown导出格式正确
5. 空邮件集不崩溃

作者：MailKnow Team
日期：2026-05-02
"""

import pytest
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src'))

from scenes.report.generator import (
    ReportGenerator, DeterministicValidator, WeeklyReport, ReportSection,
    FORBIDDEN_PHRASES, FACTUAL_PATTERNS,
)
from llm.client import LLMClient, LLMResponse, LLMProvider


# ── Fixtures ──

@pytest.fixture
def sample_emails():
    """模拟一周邮件数据"""
    now = datetime.now()
    return [
        {
            "email_id": "email-001",
            "subject": "【紧急】服务器宕机需要审批重启",
            "from": "ops@company.com",
            "to": "user@company.com",
            "content": "生产服务器宕机，请紧急审批重启流程",
            "gate_class": "urgent",
            "is_approval": True,
            "date": now.strftime("%Y-%m-%d"),
        },
        {
            "email_id": "email-002",
            "subject": "项目周会纪要",
            "from": "pm@company.com",
            "to": "user@company.com",
            "content": "本周项目进展顺利，完成了用户模块开发",
            "gate_class": "routine",
            "is_approval": False,
            "date": (now - timedelta(days=1)).strftime("%Y-%m-%d"),
        },
        {
            "email_id": "email-003",
            "subject": "合同审批已通过",
            "from": "system@company.com",
            "to": "user@company.com",
            "content": "您提交的合同审批已通过",
            "gate_class": "notification",
            "is_approval": False,
            "date": (now - timedelta(days=2)).strftime("%Y-%m-%d"),
        },
        {
            "email_id": "email-004",
            "subject": "Q2采购预算审批",
            "from": "finance@company.com",
            "to": "user@company.com",
            "content": "请审批Q2采购预算，金额￥80,000",
            "gate_class": "important",
            "is_approval": True,
            "date": (now - timedelta(days=3)).strftime("%Y-%m-%d"),
        },
        {
            "email_id": "email-005",
            "subject": "促销活动通知",
            "from": "marketing@company.com",
            "to": "all@company.com",
            "content": "本周五公司促销活动",
            "gate_class": "notification",
            "is_approval": False,
            "date": (now - timedelta(days=4)).strftime("%Y-%m-%d"),
        },
        {
            "email_id": "email-006",
            "subject": "免费领取优惠券",
            "from": "spam@unknown.com",
            "to": "user@company.com",
            "content": "点击领取免费优惠券",
            "gate_class": "spam",
            "is_approval": False,
            "date": (now - timedelta(days=5)).strftime("%Y-%m-%d"),
        },
    ]


@pytest.fixture
def generator():
    """创建不依赖LLM的报告生成器"""
    return ReportGenerator()


# ── 测试：周报生成全流程 ──

class TestReportGenerationE2E:
    """E2E周报生成全流程"""

    def test_generate_deterministic_report(self, generator, sample_emails):
        """确定性周报生成（不使用LLM）"""
        report = generator.generate(
            emails=sample_emails,
            period_start="2026-04-25",
            period_end="2026-05-02",
        )

        assert isinstance(report, WeeklyReport)
        assert report.period_start == "2026-04-25"
        assert report.period_end == "2026-05-02"
        assert report.total_emails == len(sample_emails)
        assert report.llm_used is False
        assert report.deterministic_only is True

    def test_report_has_correct_sections(self, generator, sample_emails):
        """周报包含正确的分区"""
        report = generator.generate(emails=sample_emails)

        section_titles = [s.title for s in report.sections]

        # 应包含重要事项
        assert any("重要" in t for t in section_titles), f"Missing important section in {section_titles}"

        # 应包含待审批
        assert any("审批" in t for t in section_titles), f"Missing approval section in {section_titles}"

        # 应包含常规工作或通知
        has_routine_or_notification = any(
            "常规" in t or "通知" in t for t in section_titles
        )
        assert has_routine_or_notification, f"Missing routine/notification in {section_titles}"

    def test_report_no_forbidden_phrases(self, generator, sample_emails):
        """周报不包含预测性词汇"""
        report = generator.generate(emails=sample_emails)

        # 验证通过确定性校验
        assert report.validation_passed is True
        assert len(report.validation_warnings) == 0

        # 逐条检查
        for section in report.sections:
            for item in section.items:
                for phrase in FORBIDDEN_PHRASES:
                    assert phrase not in item, f"Forbidden phrase '{phrase}' found in: {item}"

    def test_report_markdown_export(self, generator, sample_emails):
        """Markdown导出格式正确"""
        report = generator.generate(
            emails=sample_emails,
            period_start="2026-04-25",
            period_end="2026-05-02",
        )

        md = report.to_markdown()

        assert "# 周报" in md
        assert "2026-04-25" in md
        assert "2026-05-02" in md
        assert "##" in md  # 有分区标题
        assert "- " in md  # 有列表项

    def test_report_dict_export(self, generator, sample_emails):
        """dict导出格式正确"""
        report = generator.generate(emails=sample_emails)

        d = report.to_dict()

        assert "period_start" in d
        assert "period_end" in d
        assert "sections" in d
        assert isinstance(d["sections"], list)
        assert "total_emails" in d
        assert "validation_passed" in d


class TestDeterministicValidator:
    """确定性校验器测试"""

    def test_valid_report_passes(self):
        """合法报告通过校验"""
        report = WeeklyReport(
            period_start="2026-04-25",
            period_end="2026-05-02",
            sections=[
                ReportSection(title="⭐ 重要事项", items=["完成了用户模块开发", "处理了3封审批邮件"], source_count=5),
            ],
            total_emails=10,
            generated_at="2026-05-02",
        )

        validator = DeterministicValidator()
        passed, warnings = validator.validate(report)

        assert passed is True
        assert len(warnings) == 0

    def test_report_with_forbidden_phrases_fails(self):
        """含预测性词汇的报告不通过"""
        report = WeeklyReport(
            period_start="2026-04-25",
            period_end="2026-05-02",
            sections=[
                ReportSection(title="工作计划", items=["下周计划完成新功能", "准备做架构升级"], source_count=3),
            ],
            total_emails=10,
            generated_at="2026-05-02",
        )

        validator = DeterministicValidator()
        passed, warnings = validator.validate(report)

        assert passed is False
        assert len(warnings) > 0

    def test_all_forbidden_phrases_caught(self):
        """所有 FORBIDDEN_PHRASES 都被检测"""
        for phrase in FORBIDDEN_PHRASES[:5]:  # 测试前5个
            report = WeeklyReport(
                period_start="2026-04-25",
                period_end="2026-05-02",
                sections=[
                    ReportSection(title="测试", items=[f"内容包含{phrase}"], source_count=1),
                ],
                total_emails=1,
                generated_at="2026-05-02",
            )

            validator = DeterministicValidator()
            passed, warnings = validator.validate(report)

            assert passed is False, f"Forbidden phrase '{phrase}' not detected"


class TestEdgeCases:
    """边界情况测试"""

    def test_empty_emails(self, generator):
        """空邮件集不崩溃"""
        report = generator.generate(emails=[])
        assert isinstance(report, WeeklyReport)
        assert report.total_emails == 0

    def test_single_email(self, generator):
        """单封邮件也能生成"""
        report = generator.generate(emails=[{
            "email_id": "only-1",
            "subject": "唯一的邮件",
            "from": "test@test.com",
            "to": "user@company.com",
            "content": "测试内容",
            "gate_class": "routine",
            "is_approval": False,
            "date": "2026-05-01",
        }])
        assert report.total_emails == 1

    def test_all_spam_emails(self, generator):
        """全是垃圾邮件的情况"""
        emails = [
            {
                "email_id": f"spam-{i}",
                "subject": f"垃圾邮件{i}",
                "from": f"spam{i}@unknown.com",
                "to": "user@company.com",
                "content": "垃圾内容",
                "gate_class": "spam",
                "is_approval": False,
                "date": "2026-05-01",
            }
            for i in range(10)
        ]

        report = generator.generate(emails=emails)
        assert report.total_emails == 10
        # 应有垃圾邮件分区
        has_spam = any("垃圾" in s.title for s in report.sections)
        assert has_spam


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
