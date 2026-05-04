"""Tests for W14: Telemetry + Feedback flywheel."""

from datetime import datetime, timezone

import pytest

from core.telemetry import TelemetryCollector, TelemetryEvent, TelemetryRecord
from scenes.recommender import FeedbackType, SceneRecommender, SceneType


class TestTelemetryCollector:
    """Telemetry and analytics event collection."""

    @pytest.fixture
    def collector(self):
        return TelemetryCollector(max_records=100)

    def test_record_event(self, collector):
        collector.record(
            event=TelemetryEvent.SCENE_EXECUTED,
            properties={"scene": "approval_reminder"},
        )
        stats = collector.get_stats()
        assert stats["total_events"] == 1

    def test_record_multiple_events(self, collector):
        for _ in range(5):
            collector.record(event=TelemetryEvent.APPROVAL_DETECTED)
        stats = collector.get_stats()
        assert stats["total_events"] == 5

    def test_event_has_timestamp(self, collector):
        collector.record(event=TelemetryEvent.LLM_CALL, properties={"model": "gpt-4o-mini"})
        recent = collector.get_recent(limit=1)
        assert len(recent) == 1
        assert "timestamp" in recent[0]

    def test_filter_by_time(self, collector):
        collector.record(event=TelemetryEvent.SEARCH_QUERY)
        stats_24h = collector.get_stats(hours=24)
        assert stats_24h["total_events"] >= 1
        stats_0h = collector.get_stats(hours=0)
        assert stats_0h["total_events"] == 0

    def test_sanitize_pii(self, collector):
        collector.record(
            event=TelemetryEvent.SEARCH_QUERY,
            properties={"email": "user@company.com", "subject": "秘密", "safe_key": "ok"},
        )
        recent = collector.get_recent(limit=1)
        assert recent[0]["properties"]["email"] == "[REDACTED]"
        assert recent[0]["properties"]["subject"] == "[REDACTED]"
        assert recent[0]["properties"]["safe_key"] == "ok"

    def test_max_records_limit(self):
        c = TelemetryCollector(max_records=5)
        for i in range(10):
            c.record(event=TelemetryEvent.LLM_CALL, properties={"i": i})
        recent = c.get_recent(limit=100)
        assert len(recent) <= 5

    def test_durations_tracking(self, collector):
        collector.record(event=TelemetryEvent.LLM_CALL, duration_ms=100.0)
        collector.record(event=TelemetryEvent.LLM_CALL, duration_ms=200.0)
        stats = collector.get_stats()
        assert "llm_call" in stats["avg_durations_ms"]
        assert stats["avg_durations_ms"]["llm_call"] == 150.0

    def test_event_types_comprehensive(self):
        expected = [
            "SCENE_EXECUTED", "SCENE_DISMISSED", "SCENE_FEEDBACK",
            "SEARCH_QUERY", "SEARCH_RESULT_CLICKED",
            "APPROVAL_DETECTED", "APPROVAL_ACTION", "APPROVAL_BATCH",
            "REPORT_GENERATED", "REPORT_EXPORTED", "REPORT_EDITED",
            "SYNC_COMPLETED", "SYNC_ERROR",
            "LLM_CALL", "LLM_FALLBACK", "BUDGET_DEGRADED",
            "KNOWLEDGE_QUERY", "ENTITY_ALIGNED",
        ]
        for name in expected:
            assert hasattr(TelemetryEvent, name), f"Missing TelemetryEvent: {name}"


class TestFeedbackFlywheel:
    """Test feedback collection and recommendation improvement."""

    def test_thumbs_up_feedback(self):
        recommender = SceneRecommender()
        cards = recommender.recommend(
            context={"pending_approvals": [{"confidence": 0.9, "subject": "审批"}]},
        )
        if cards:
            recommender.record_feedback(cards[0].card_id, FeedbackType.THUMBS_UP)
            assert cards[0].feedback == FeedbackType.THUMBS_UP

    def test_thumbs_down_feedback_cooldown(self):
        recommender = SceneRecommender()
        cards = recommender.recommend(
            context={"pending_approvals": [{"confidence": 0.9, "subject": "审批"}]},
        )
        if cards:
            recommender.record_feedback(cards[0].card_id, FeedbackType.THUMBS_DOWN)
            assert cards[0].scene_type in recommender._cooldowns

    def test_refresh_feedback(self):
        recommender = SceneRecommender()
        cards = recommender.recommend(
            context={"pending_approvals": [{"confidence": 0.9, "subject": "审批"}]},
        )
        if cards:
            recommender.record_feedback(cards[0].card_id, FeedbackType.REFRESH)
            assert cards[0].feedback == FeedbackType.REFRESH

    def test_feedback_recorded_in_history(self):
        recommender = SceneRecommender()
        cards = recommender.recommend(
            context={"pending_approvals": [{"confidence": 0.9, "subject": "审批"}]},
        )
        if cards:
            recommender.record_feedback(cards[0].card_id, FeedbackType.THUMBS_UP)
            assert len(recommender._feedback_history) >= 1
