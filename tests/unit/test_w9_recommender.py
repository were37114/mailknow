"""Tests for W9: Scene recommender + cold start + feedback."""

from datetime import datetime, timedelta, timezone

import pytest

from scenes.cold_start import STAGE_STRATEGIES, ColdStartManager
from scenes.recommender import (
    ColdStartStage,
    FeedbackType,
    RecommendationBoundary,
    SceneCard,
    SceneRecommender,
    SceneType,
)


class TestSceneRecommender:
    """Test scene recommendation engine."""

    @pytest.fixture
    def recommender(self):
        return SceneRecommender()

    @pytest.fixture
    def experienced_recommender(self):
        """Recommender with 30+ days of data."""
        old_date = (datetime.now(timezone.utc) - timedelta(days=35)).isoformat()
        r = SceneRecommender()
        r.set_first_use(old_date)
        r.set_first_import(old_date)
        return r

    def test_cold_start_day1(self, recommender):
        assert recommender.get_cold_start_stage() == ColdStartStage.DAY_1

    def test_cold_start_post_import(self):
        recent = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        r = SceneRecommender()
        r.set_first_use(recent)
        r.set_first_import(recent)
        assert r.get_cold_start_stage() == ColdStartStage.POST_IMPORT

    def test_cold_start_week1(self):
        recent = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
        r = SceneRecommender()
        r.set_first_use(recent)
        r.set_first_import(recent)
        assert r.get_cold_start_stage() == ColdStartStage.WEEK_1

    def test_cold_start_month1(self, experienced_recommender):
        assert experienced_recommender.get_cold_start_stage() == ColdStartStage.MONTH_1

    def test_recommend_daily_limit(self, experienced_recommender):
        recs = experienced_recommender.recommend(
            context={"pending_approvals": [{"confidence": 0.9}]},
        )
        assert len(recs) <= 5

    def test_recommend_no_duplicates(self, experienced_recommender):
        recs = experienced_recommender.recommend(
            context={"pending_approvals": [{"confidence": 0.9}], "is_friday": True, "recent_quotes": [{"price": 100}]},
        )
        types = [r.scene_type for r in recs]
        assert len(types) == len(set(types))

    def test_silent_hours(self, experienced_recommender):
        late_night = datetime(2024, 1, 1, 3, 0, tzinfo=timezone(timedelta(hours=8)))
        recs = experienced_recommender.recommend(
            context={"pending_approvals": [{"confidence": 0.9}]},
            now=late_night,
        )
        assert isinstance(recs, list)

    def test_record_feedback_on_card(self, recommender):
        """record_feedback takes card_id, must create card first."""
        cards = recommender.recommend(
            context={"pending_approvals": [{"confidence": 0.9, "subject": "审批"}]},
        )
        if cards:
            recommender.record_feedback(cards[0].card_id, FeedbackType.THUMBS_UP)
            assert cards[0].feedback == FeedbackType.THUMBS_UP

    def test_record_feedback_thumbs_down_cooldown(self, recommender):
        """Thumbs down should put scene type in cooldown."""
        cards = recommender.recommend(
            context={"pending_approvals": [{"confidence": 0.9, "subject": "审批"}]},
        )
        if cards:
            recommender.record_feedback(cards[0].card_id, FeedbackType.THUMBS_DOWN)
            assert cards[0].scene_type in recommender._cooldowns

    def test_scene_card_creation(self):
        card = SceneCard(
            scene_type=SceneType.APPROVAL_REMINDER,
            title="审批提醒",
            description="您有3封待审批邮件",
            confidence=0.85,
            priority=1,
        )
        assert card.scene_type == SceneType.APPROVAL_REMINDER
        assert card.confidence == 0.85
        assert card.priority == 1

    def test_scene_card_interaction(self):
        card = SceneCard(
            scene_type=SceneType.WEEKLY_REPORT,
            title="周报",
            description="生成周报",
            confidence=0.9,
        )
        assert not card.is_interacted
        card.feedback = FeedbackType.THUMBS_UP
        assert card.is_interacted

    def test_dismiss_card(self, recommender):
        cards = recommender.recommend(
            context={"pending_approvals": [{"confidence": 0.9, "subject": "审批"}]},
        )
        if cards:
            result = recommender.dismiss_card(cards[0].card_id)
            assert isinstance(result, bool)

    def test_get_stats(self, recommender):
        stats = recommender.get_stats()
        assert isinstance(stats, dict)


class TestColdStartManager:
    """Test cold start onboarding flow."""

    @pytest.fixture
    def manager(self):
        return ColdStartManager()

    def test_initial_stage(self, manager):
        assert manager.get_stage() == ColdStartStage.DAY_1

    def test_set_first_use(self, manager):
        manager.set_first_use()
        assert manager._first_use is not None

    def test_set_first_import(self, manager):
        manager.set_first_use()
        manager.set_first_import(email_count=100)
        assert manager._first_import is not None
        assert manager._email_count == 100

    def test_stage_progression(self, manager):
        old_date = (datetime.now(timezone.utc) - timedelta(days=35)).strftime("%Y-%m-%d")
        manager.set_first_use(old_date)
        manager.set_first_import(old_date, email_count=500)
        assert manager.get_stage() == ColdStartStage.MONTH_1

    def test_get_strategy(self, manager):
        strategy = manager.get_strategy()
        assert strategy.stage == ColdStartStage.DAY_1
        assert len(strategy.enabled_scenes) > 0

    def test_is_scene_enabled(self, manager):
        assert manager.is_scene_enabled(SceneType.WEEKLY_REPORT)
        assert not manager.is_scene_enabled(SceneType.APPROVAL_REMINDER)

    def test_get_max_daily_cards(self, manager):
        assert manager.get_max_daily_cards() == 2

    def test_get_confidence_threshold(self, manager):
        assert manager.get_confidence_threshold() == 0.9

    def test_get_stage_info(self, manager):
        info = manager.get_stage_info()
        assert "stage" in info
        assert "enabled_scenes" in info

    def test_stage_strategies_defined(self):
        for stage in ColdStartStage:
            assert stage in STAGE_STRATEGIES


class TestRecommendationBoundary:
    """Test recommendation boundary constraints."""

    def test_default_boundary(self):
        boundary = RecommendationBoundary()
        assert boundary.max_daily_cards == 5
        assert boundary.approval_push_min_confidence == 0.85

    def test_thumbs_down_cooldown(self):
        boundary = RecommendationBoundary()
        assert boundary.thumbs_down_cooldown_days == 7

    def test_silent_hours(self):
        boundary = RecommendationBoundary()
        assert boundary.silent_hours_start == 22
        assert boundary.silent_hours_end == 8
