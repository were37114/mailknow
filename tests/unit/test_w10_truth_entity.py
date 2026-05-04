"""Tests for W10-W14: compiled_truth, entity alignment, anomaly, NL2SQL, integrity."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ===== Test Compiled Truth =====
from core.truth.compiler import CompiledTruth, TruthCompiler
from core.entity.aligner import EntityAligner, MergeReason

from scenes.anomaly.detector import AnomalyDetector, AnomalyType

from core.search.nl2sql import NL2SQLTranslator

from core.minion.dead_letter import DeadLetterQueue, DeadLetterReason

from core.telemetry import TelemetryCollector, TelemetryEvent



class TestTruthCompiler:
    """Test compiled truth generation."""

    def test_template_truth_person(self):
        """Template truth for a person entity."""
        compiler = TruthCompiler()

        truth = compiler._compile_with_template(
            entity_id="person:zhangsan",
            entity_name="张三",
            entity_type="person",
            related_emails=[
                {"subject": "项目讨论", "from": "lisi@company.com", "gate_class": "important", "is_approval": False, "date": "2026-04-28", "email_id": "e1"},
                {"subject": "审批请求", "from": "zhangsan@company.com", "gate_class": "routine", "is_approval": True, "date": "2026-04-27", "email_id": "e2"},
            ],
        )

        assert truth.entity_id == "person:zhangsan"
        assert truth.entity_name == "张三"
        assert "2封" in truth.summary
        assert "1封审批" in truth.summary
        assert truth.llm_used is False
        assert truth.source_count == 2

    def test_template_truth_org(self):
        """Template truth for an org entity."""
        compiler = TruthCompiler()

        truth = compiler._compile_with_template(
            entity_id="org:company-a",
            entity_name="A公司",
            entity_type="org",
            related_emails=[
                {"subject": "合同签署", "gate_class": "important", "is_approval": True, "date": "2026-04-28", "email_id": "e3"},
            ],
        )

        assert "A公司" in truth.summary
        assert truth.source_count == 1

    def test_empty_truth(self):
        """Empty truth for entity with no emails."""
        compiler = TruthCompiler()

        truth = compiler._empty_truth("person:unknown", "未知", "person")
        assert "暂无" in truth.summary
        assert truth.source_count == 0

    def test_cache_expiry(self):
        """Cached truth should expire after TTL."""
        compiler = TruthCompiler(cache_ttl=0)  # 0 second TTL

        truth = CompiledTruth(
            entity_id="test",
            entity_name="test",
            entity_type="person",
            summary="test",
            cache_expires_at=datetime.now(timezone.utc).isoformat(),
        )

        # Should be expired immediately with 0 TTL
        assert truth.is_expired()


# ===== Test Entity Alignment =====

# EntityAligner imported at top


class TestEntityAlignment:
    """Test entity alignment and merging."""

    def test_find_candidates_same_prefix(self):
        """Find merge candidates with same email prefix."""
        aligner = EntityAligner()
        aligner.load_entities([
            {"id": "person:zhangsan-a", "name": "张三", "type": "person", "attributes": {"emails": ["zhangsan@company-a.com"]}},
            {"id": "person:zhangsan-b", "name": "张三", "type": "person", "attributes": {"emails": ["zhangsan@company-b.com"]}},
        ])

        candidates = aligner.find_merge_candidates()
        assert len(candidates) >= 1

        # Should detect same prefix
        id1, id2, reason, confidence = candidates[0]
        assert reason == MergeReason.SAME_EMAIL_PREFIX
        assert confidence > 0.8

    def test_find_candidates_alias(self):
        """Find merge candidates with email aliases."""
        aligner = EntityAligner()
        aligner.load_entities([
            {"id": "person:zhang-san", "name": "张三", "type": "person", "attributes": {"emails": ["zhang.san@company.com"]}},
            {"id": "person:zhangsan2", "name": "张三", "type": "person", "attributes": {"emails": ["zhangsan@company.com"]}},
        ])

        candidates = aligner.find_merge_candidates()
        # Should find alias match
        assert len(candidates) >= 1

    def test_merge_entities(self):
        """Merge two entities."""
        aligner = EntityAligner()
        aligner.load_entities([
            {"id": "person:a", "name": "张三", "type": "person", "attributes": {"emails": ["zhangsan@a.com"]}},
            {"id": "person:b", "name": "张三", "type": "person", "attributes": {"emails": ["zhangsan@b.com"]}},
        ])

        record = aligner.merge("person:a", "person:b", reason=MergeReason.SAME_EMAIL_PREFIX, confidence=0.85)

        assert record.kept_entity_id == "person:a"
        assert record.merged_entity_id == "person:b"
        assert record.reason == MergeReason.SAME_EMAIL_PREFIX

        # Merged entity should be removed
        assert "person:b" not in aligner._entity_map

        # Kept entity should have merged emails
        kept = aligner._entity_map["person:a"]
        emails = kept["attributes"]["emails"]
        assert len(emails) == 2

    def test_merge_undo(self):
        """Undo a merge operation."""
        aligner = EntityAligner()
        aligner.load_entities([
            {"id": "person:a", "name": "张三", "type": "person", "attributes": {"emails": ["a@x.com"]}},
            {"id": "person:b", "name": "张三B", "type": "person", "attributes": {"emails": ["b@x.com"]}},
        ])

        record = aligner.merge("person:a", "person:b")

        # Undo
        result = aligner.undo(record.merge_id)
        assert result is True

        # Merged entity should be restored
        assert "person:b" in aligner._entity_map
        restored = aligner._entity_map["person:b"]
        assert restored["name"] == "张三B"

    def test_auto_align(self):
        """Run automatic alignment."""
        aligner = EntityAligner()
        aligner.load_entities([
            {"id": "person:a", "name": "张三", "type": "person", "attributes": {"emails": ["zhangsan@a.com"]}},
            {"id": "person:b", "name": "张三", "type": "person", "attributes": {"emails": ["zhangsan@b.com"]}},
            {"id": "person:c", "name": "李四", "type": "person", "attributes": {"emails": ["lisi@a.com"]}},
        ])

        result = aligner.align(auto_merge=True, min_confidence=0.8)
        assert result.total_entities == 3
        assert result.merges_performed >= 1


# ===== Test Anomaly Detection =====

# AnomalyDetector imported at top


class TestAnomalyDetection:
    """Test anomaly detection."""

    def test_unreplied_urgent(self):
        """Detect unreplied urgent emails."""
        detector = AnomalyDetector()

        now = datetime.now(timezone.utc)
        old_date = (now - timedelta(hours=48)).isoformat()

        emails = [
            {"email_id": "e1", "subject": "紧急审批", "gate_class": "urgent", "date": old_date, "content": "请尽快审批", "is_approval": True},
            {"email_id": "e2", "subject": "普通邮件", "gate_class": "routine", "date": old_date, "content": "hello"},
        ]

        anomalies = detector.detect_unreplied_urgent(emails, hours_threshold=24)
        assert len(anomalies) >= 1

        urgent = [a for a in anomalies if a.anomaly_type == AnomalyType.UNREPLIED_URGENT]
        assert len(urgent) >= 1
        assert urgent[0].severity == "high"

    def test_deadline_approaching(self):
        """Detect approaching approval deadlines."""
        detector = AnomalyDetector()

        now = datetime.now(timezone.utc)
        deadline = (now + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%S")

        cards = [
            {"card_id": "c1", "email_id": "e1", "subject": "采购审批", "deadline": deadline},
        ]

        anomalies = detector.detect_deadline_approaching(cards, hours_threshold=24)
        assert len(anomalies) >= 1
        assert anomalies[0].anomaly_type == AnomalyType.DEADLINE_APPROACHING

    def test_promise_unfulfilled(self):
        """Detect unfulfilled promises."""
        detector = AnomalyDetector()

        old_date = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()

        emails = [
            {"email_id": "e1", "content": "我会在明天完成项目报告", "date": old_date},
        ]

        # Check that the regex pattern matches
        import re
        pattern = r'我会\s*(?:在|于)?\s*(?:明天|下周|本周|尽快|\d+[天号日]内?)?\s*(?:前|之前)?\s*(完成|回复|提交|处理|确认)'
        match = re.search(pattern, "我会在明天完成项目报告")
        assert match is not None, "Promise pattern should match"

        anomalies = detector.detect_promise_unfulfilled(emails, days_threshold=3)
        assert len(anomalies) >= 1
        assert anomalies[0].anomaly_type == AnomalyType.PROMISE_UNFULFILLED


# ===== Test NL2SQL =====

# NL2SQLTranslator imported at top


class TestNL2SQL:
    """Test natural language to SQL translation."""

    def test_template_recent_emails(self):
        """Template match: recent N days emails."""
        translator = NL2SQLTranslator()

        result = translator._try_template("最近7天的邮件")
        assert result is not None
        assert "SELECT" in result.sql
        assert "7" in result.sql

    def test_template_approval_emails(self):
        """Template match: approval emails."""
        translator = NL2SQLTranslator()

        result = translator._try_template("审批邮件")
        assert result is not None
        assert "SELECT" in result.sql

    def test_validate_sql_safe(self):
        """Validate safe SQL."""
        translator = NL2SQLTranslator()

        is_safe, errors = translator._validate_sql(
            "SELECT id, content FROM pages WHERE gate_class = 'important'"
        )
        assert is_safe is True
        assert len(errors) == 0

    def test_validate_sql_dangerous(self):
        """Validate dangerous SQL (should be rejected)."""
        translator = NL2SQLTranslator()

        is_safe, errors = translator._validate_sql(
            "DELETE FROM pages WHERE id = 'test'"
        )
        assert is_safe is False
        assert len(errors) > 0

    def test_validate_sql_injection(self):
        """Validate SQL with injection attempt."""
        translator = NL2SQLTranslator()

        is_safe, errors = translator._validate_sql(
            "SELECT * FROM pages; DROP TABLE pages;"
        )
        assert is_safe is False


# ===== Test Dead Letter Queue =====

# DeadLetterQueue imported at top


class TestDeadLetterQueue:
    """Test dead letter queue."""

    def test_add_entry(self):
        """Add a failed task to dead letter queue."""
        queue = DeadLetterQueue()
        entry = queue.add(
            task_type="tier4_extract",
            task_id="task-123",
            payload={"email_id": "e1"},
            reason=DeadLetterReason.LLM_TIMEOUT,
            error_message="LLM call timed out after 10s",
        )

        assert entry.entry_id
        assert entry.task_type == "tier4_extract"
        assert entry.reason == DeadLetterReason.LLM_TIMEOUT
        assert not entry.resolved

    def test_retry_entry(self):
        """Retry a dead letter entry."""
        queue = DeadLetterQueue(max_retries=3)
        entry = queue.add(task_type="test", task_id="t1", payload={}, reason=DeadLetterReason.LLM_ERROR)

        # Retry
        retried = queue.retry(entry.entry_id)
        assert retried is not None
        assert retried.retry_count == 1
        assert retried.can_retry

    def test_max_retries(self):
        """Entry should not be retryable after max retries."""
        queue = DeadLetterQueue(max_retries=2)
        entry = queue.add(task_type="test", task_id="t1", payload={}, reason=DeadLetterReason.LLM_ERROR)

        queue.retry(entry.entry_id)
        queue.retry(entry.entry_id)

        assert not entry.can_retry

    def test_resolve_entry(self):
        """Resolve a dead letter entry."""
        queue = DeadLetterQueue()
        entry = queue.add(task_type="test", task_id="t1", payload={}, reason=DeadLetterReason.LLM_ERROR)

        result = queue.resolve(entry.entry_id, resolved_by="retry")
        assert result is True
        assert entry.resolved

    def test_get_stats(self):
        """Get dead letter queue statistics."""
        queue = DeadLetterQueue()
        queue.add(task_type="tier4", task_id="t1", payload={}, reason=DeadLetterReason.LLM_ERROR)
        queue.add(task_type="compile_truth", task_id="t2", payload={}, reason=DeadLetterReason.BUDGET_EXCEEDED)

        stats = queue.get_stats()
        assert stats["total"] == 2
        assert stats["pending"] == 2


# ===== Test Integrity Checker =====

# Note: IntegrityChecker requires a DB connection, tested in integration tests


# ===== Test Telemetry =====

# TelemetryCollector imported at top


class TestTelemetry:
    """Test telemetry collection."""

    def test_record_event(self):
        """Record a telemetry event."""
        collector = TelemetryCollector()
        collector.record(TelemetryEvent.SEARCH_QUERY, {"query_length": 15})

        stats = collector.get_stats(hours=1)
        assert stats["total_events"] == 1
        assert "search_query" in stats["by_event"]

    def test_sanitize_pii(self):
        """Sanitize PII from telemetry properties."""
        collector = TelemetryCollector()
        sanitized = collector._sanitize({
            "subject": "My secret email",
            "query": "test",
        })

        assert sanitized["subject"] == "[REDACTED]"
        assert sanitized["query"] == "test"

    def test_recent_events(self):
        """Get recent telemetry records."""
        collector = TelemetryCollector()
        collector.record(TelemetryEvent.APPROVAL_ACTION, properties={"action": "approve"})
        collector.record(TelemetryEvent.SEARCH_QUERY, properties={"query": "test"})

        recent = collector.get_recent(limit=10)
        assert len(recent) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
