"""Tests for W11: NL→SQL + Anomaly detection."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, AsyncMock

from core.search.nl2sql import NL2SQLTranslator, NL2SQLResult
from scenes.anomaly.detector import AnomalyDetector, Anomaly, AnomalyType


class TestNL2SQLTranslator:
    """Test natural language to SQL translation."""

    @pytest.fixture
    def translator(self):
        with patch('core.search.nl2sql.get_llm_client'), \
             patch('core.search.nl2sql.get_fallback'):
            return NL2SQLTranslator()

    @pytest.mark.asyncio
    async def test_template_query_recent(self, translator):
        """Test template match for recent emails query."""
        result = await translator.translate("最近7天的邮件")
        assert isinstance(result, NL2SQLResult)
        assert result.sql is not None

    @pytest.mark.asyncio
    async def test_template_query_sender(self, translator):
        """Test template match for sender query."""
        result = await translator.translate("张三发给我的邮件")
        assert isinstance(result, NL2SQLResult)

    @pytest.mark.asyncio
    async def test_template_query_approval(self, translator):
        """Test template match for approval query."""
        result = await translator.translate("审批邮件")
        assert isinstance(result, NL2SQLResult)
        assert result.sql is not None

    @pytest.mark.asyncio
    async def test_template_query_important(self, translator):
        """Test template match for important emails."""
        result = await translator.translate("重要的邮件")
        assert isinstance(result, NL2SQLResult)

    @pytest.mark.asyncio
    async def test_sql_injection_prevention(self, translator):
        """SQL injection should be prevented."""
        result = await translator.translate("邮件; DROP TABLE pages; --")
        assert "DROP" not in result.sql.upper()
        assert "DELETE" not in result.sql.upper()

    @pytest.mark.asyncio
    async def test_empty_query(self, translator):
        """Empty query should return safe fallback."""
        result = await translator.translate("")
        assert isinstance(result, NL2SQLResult)

    def test_nl2sql_result_model(self):
        """Test NL2SQLResult data model."""
        result = NL2SQLResult(
            original_query="测试",
            sql="SELECT * FROM pages",
            explanation="查询所有页面",
            is_safe=True,
        )
        assert result.original_query == "测试"
        assert result.is_safe is True

    def test_sql_validation(self, translator):
        """Test SQL validation method."""
        is_safe, errors = translator._validate_sql("SELECT id FROM pages WHERE type='email'")
        assert is_safe is True
        assert len(errors) == 0

        is_safe2, errors2 = translator._validate_sql("DROP TABLE pages")
        assert is_safe2 is False
        assert len(errors2) > 0


class TestAnomalyDetector:
    """Test anomaly detection for emails."""

    @pytest.fixture
    def detector(self):
        return AnomalyDetector()

    def test_unreplied_urgent(self, detector):
        old_date = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        emails = [
            {"email_id": "e1", "content": "紧急：系统故障需要立即处理", "date": old_date, "gate_class": "important"},
        ]
        anomalies = detector.detect_unreplied_urgent(emails, hours_threshold=24)
        assert len(anomalies) >= 1
        assert anomalies[0].anomaly_type == AnomalyType.UNREPLIED_URGENT

    def test_deadline_approaching(self, detector):
        soon = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
        emails = [
            {"email_id": "e2", "content": "请在本周五前完成审批", "date": datetime.now(timezone.utc).isoformat(), "deadline": soon},
        ]
        anomalies = detector.detect_deadline_approaching(emails, hours_threshold=24)
        assert len(anomalies) >= 1
        assert anomalies[0].anomaly_type == AnomalyType.DEADLINE_APPROACHING

    def test_promise_unfulfilled(self, detector):
        old_date = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        emails = [
            {"email_id": "e3", "content": "我会在明天完成项目报告", "date": old_date},
        ]
        anomalies = detector.detect_promise_unfulfilled(emails, days_threshold=3)
        assert len(anomalies) >= 1
        assert anomalies[0].anomaly_type == AnomalyType.PROMISE_UNFULFILLED

    def test_no_false_positives(self, detector):
        recent = datetime.now(timezone.utc).isoformat()
        emails = [
            {"email_id": "e4", "content": "普通邮件内容", "date": recent},
        ]
        anomalies = detector.detect_unreplied_urgent(emails, hours_threshold=24)
        assert len(anomalies) == 0

    def test_detect_all(self, detector):
        old_date = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        emails = [
            {"email_id": "e5", "content": "紧急处理+我会在明天完成", "date": old_date, "gate_class": "important"},
        ]
        anomalies = detector.detect_all(emails)
        assert isinstance(anomalies, list)

    def test_anomaly_model(self):
        anomaly = Anomaly(
            anomaly_type=AnomalyType.UNREPLIED_URGENT,
            severity="high",
            title="未回复紧急邮件",
            description="重要邮件30小时未回复",
            email_ids=["e1"],
            confidence=0.85,
        )
        assert anomaly.anomaly_type == AnomalyType.UNREPLIED_URGENT
        assert anomaly.severity == "high"
        assert not anomaly.dismissed

    def test_anomaly_severity_values(self, detector):
        """Anomaly severity should be valid string."""
        old_date = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        emails = [
            {"email_id": "e6", "content": "紧急：服务器宕机", "date": old_date, "gate_class": "important"},
        ]
        anomalies = detector.detect_unreplied_urgent(emails, hours_threshold=24)
        if anomalies:
            assert anomalies[0].severity in ("low", "medium", "high", "critical")
