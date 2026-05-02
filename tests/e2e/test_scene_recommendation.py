"""
E2E场景推荐测试

端到端验证：冷启动 → 首日导入 → 首周 → 首月

验证点：
1. 各阶段推荐策略正确切换（Day1/PostImport/Week1/Month1）
2. 推荐边界控制（每日≤5张卡片）
3. 反馈飞轮生效（👍+0.1 / 👎-0.2+冷却 / 🔄降优先级）
4. 静默时段不推荐（22:00-08:00）
5. CC审批不生成卡片

作者：MailKnow Team
日期：2026-05-02
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src'))

from scenes.recommender import (
    SceneRecommender, SceneCard, SceneType, FeedbackType,
    ColdStartStage, RecommendationBoundary,
)
from scenes.cold_start import ColdStartManager, STAGE_STRATEGIES


# ── Fixtures ──

@pytest.fixture
def recommender():
    """创建场景推荐引擎"""
    return SceneRecommender()


@pytest.fixture
def boundary():
    """创建推荐边界配置"""
    return RecommendationBoundary(
        max_daily_cards=5,
        thumbs_down_cooldown_days=7,
        silent_hours_start=22,
        silent_hours_end=8,
        approval_push_min_confidence=0.85,
    )


@pytest.fixture
def recommender_with_boundary(boundary):
    """创建带自定义边界的推荐引擎"""
    return SceneRecommender(boundary=boundary)


@pytest.fixture
def approval_context():
    """审批场景上下文"""
    return {
        "pending_approvals": [
            {"card_id": "ap-001", "email_id": "e-001", "subject": "采购审批",
             "requester": "pm@company.com", "confidence": 0.92},
            {"card_id": "ap-002", "email_id": "e-002", "subject": "差旅审批",
             "requester": "team@company.com", "confidence": 0.75},
        ],
        "is_friday": False,
        "recent_quotes": [],
        "anomalies": [],
    }


@pytest.fixture
def friday_context():
    """周五周报场景上下文"""
    return {
        "pending_approvals": [],
        "is_friday": True,
        "recent_quotes": [],
        "anomalies": [],
    }


# ── 测试：冷启动阶段 ──

class TestColdStartStages:
    """冷启动4阶段策略"""

    def test_day1_no_data(self):
        """Day1：无数据"""
        manager = ColdStartManager()
        assert manager.get_stage() == ColdStartStage.DAY_1

    def test_post_import(self):
        """PostImport：导入数据后"""
        manager = ColdStartManager()
        manager.set_first_use("2026-05-01")
        manager.set_first_import("2026-05-01", email_count=100)

        # 同一天 → POST_IMPORT
        with patch('scenes.cold_start.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 1, tzinfo=timezone.utc)
            mock_dt.fromisoformat = datetime.fromisoformat
            stage = manager.get_stage()

        assert stage == ColdStartStage.POST_IMPORT

    def test_week1(self):
        """Week1：使用1周后"""
        manager = ColdStartManager()
        # 设置8天前首次使用
        first_use = (datetime.now(timezone.utc) - timedelta(days=8)).strftime("%Y-%m-%d")
        manager.set_first_use(first_use)
        manager.set_first_import(first_use, email_count=500)

        stage = manager.get_stage()
        assert stage == ColdStartStage.WEEK_1

    def test_month1(self):
        """Month1：使用1月后"""
        manager = ColdStartManager()
        first_use = (datetime.now(timezone.utc) - timedelta(days=35)).strftime("%Y-%m-%d")
        manager.set_first_use(first_use)
        manager.set_first_import(first_use, email_count=2000)

        stage = manager.get_stage()
        assert stage == ColdStartStage.MONTH_1

    def test_stage_strategies_progression(self):
        """各阶段策略逐步放宽"""
        day1 = STAGE_STRATEGIES[ColdStartStage.DAY_1]
        post_import = STAGE_STRATEGIES[ColdStartStage.POST_IMPORT]
        week1 = STAGE_STRATEGIES[ColdStartStage.WEEK_1]
        month1 = STAGE_STRATEGIES[ColdStartStage.MONTH_1]

        # Daily cards 逐步增加
        assert day1.max_daily_cards <= post_import.max_daily_cards
        assert post_import.max_daily_cards <= week1.max_daily_cards
        assert week1.max_daily_cards <= month1.max_daily_cards

        # Confidence threshold 逐步降低
        assert day1.confidence_threshold >= post_import.confidence_threshold
        assert post_import.confidence_threshold >= week1.confidence_threshold
        assert week1.confidence_threshold >= month1.confidence_threshold


# ── 测试：推荐边界控制 ──

class TestRecommendationBoundary:
    """推荐边界控制"""

    def test_daily_card_limit(self, recommender_with_boundary, approval_context):
        """每日推荐卡片≤5张"""
        # 消耗4张配额
        now = datetime(2026, 5, 2, 14, 0, tzinfo=timezone.utc)
        recommender_with_boundary._daily_cards["2026-05-02"] = 4

        cards = recommender_with_boundary.recommend(approval_context, now=now)
        # 最多1张（5-4=1）
        assert len(cards) <= 1

    def test_daily_card_limit_reached(self, recommender_with_boundary, approval_context):
        """每日配额用完后不推荐"""
        now = datetime(2026, 5, 2, 14, 0, tzinfo=timezone.utc)
        recommender_with_boundary._daily_cards["2026-05-02"] = 5

        cards = recommender_with_boundary.recommend(approval_context, now=now)
        assert len(cards) == 0

    def test_silent_hours_no_recommendation(self, recommender_with_boundary, approval_context):
        """静默时段（22:00-08:00）不推荐"""
        # 23:00
        night = datetime(2026, 5, 2, 23, 0, tzinfo=timezone.utc)
        cards = recommender_with_boundary.recommend(approval_context, now=night)
        assert len(cards) == 0

        # 03:00
        dawn = datetime(2026, 5, 2, 3, 0, tzinfo=timezone.utc)
        cards = recommender_with_boundary.recommend(approval_context, now=dawn)
        assert len(cards) == 0

    def test_active_hours_recommendation(self, recommender_with_boundary, approval_context):
        """活跃时段正常推荐"""
        now = datetime(2026, 5, 2, 14, 0, tzinfo=timezone.utc)
        cards = recommender_with_boundary.recommend(approval_context, now=now)
        assert len(cards) > 0

    def test_approval_push_min_confidence(self, boundary):
        """审批推送仅高置信度"""
        assert boundary.approval_push_min_confidence == 0.85


# ── 测试：反馈飞轮 ──

class TestFeedbackFlywheel:
    """反馈飞轮：👍+0.1 / 👎-0.2+7天冷却 / 🔄降优先级"""

    def test_thumbs_up_increases_weight(self, recommender):
        """👍 +0.1 增加场景权重"""
        # 创建一张卡片
        card = SceneCard(
            scene_type=SceneType.APPROVAL_REMINDER,
            title="测试卡片",
            confidence=0.9,
        )
        recommender._cards[card.card_id] = card

        original_weight = recommender._scene_weights[SceneType.APPROVAL_REMINDER]
        recommender.record_feedback(card.card_id, FeedbackType.THUMBS_UP)

        assert recommender._scene_weights[SceneType.APPROVAL_REMINDER] == original_weight + 0.1

    def test_thumbs_down_decreases_weight(self, recommender):
        """👎 -0.2 降低场景权重 + 7天冷却"""
        card = SceneCard(
            scene_type=SceneType.WEEKLY_REPORT,
            title="周报卡片",
            confidence=0.8,
        )
        recommender._cards[card.card_id] = card

        original_weight = recommender._scene_weights[SceneType.WEEKLY_REPORT]
        result = recommender.record_feedback(card.card_id, FeedbackType.THUMBS_DOWN)

        assert recommender._scene_weights[SceneType.WEEKLY_REPORT] == original_weight - 0.2
        # 应有冷却
        assert SceneType.WEEKLY_REPORT in recommender._cooldowns

    def test_thumbs_down_cooldown(self, recommender):
        """👎 冷却期间不推荐该场景"""
        card = SceneCard(
            scene_type=SceneType.WEEKLY_REPORT,
            title="周报卡片",
            confidence=0.8,
        )
        recommender._cards[card.card_id] = card
        recommender.record_feedback(card.card_id, FeedbackType.THUMBS_DOWN)

        # 冷却期间该场景得分应为0
        score = recommender._score_card(card, ColdStartStage.MONTH_1)
        assert score == 0.0

    def test_refresh_demotes_priority(self, recommender):
        """🔄 降低优先级"""
        card = SceneCard(
            scene_type=SceneType.QUOTE_AGGREGATION,
            title="报价卡片",
            confidence=0.7,
            priority=3,
        )
        recommender._cards[card.card_id] = card

        recommender.record_feedback(card.card_id, FeedbackType.REFRESH)

        assert card.priority == 4  # 3 + 1

    def test_multiple_thumbs_up_capped(self, recommender):
        """👍 多次增加，上限为2.0"""
        card = SceneCard(
            scene_type=SceneType.APPROVAL_REMINDER,
            title="审批卡片",
            confidence=0.9,
        )
        recommender._cards[card.card_id] = card

        # 连续👍
        for _ in range(20):
            recommender.record_feedback(card.card_id, FeedbackType.THUMBS_UP)

        assert recommender._scene_weights[SceneType.APPROVAL_REMINDER] <= 2.0

    def test_multiple_thumbs_down_floored(self, recommender):
        """👎 多次降低，下限为0.1"""
        card = SceneCard(
            scene_type=SceneType.APPROVAL_REMINDER,
            title="审批卡片",
            confidence=0.9,
        )
        recommender._cards[card.card_id] = card

        for _ in range(20):
            recommender.record_feedback(card.card_id, FeedbackType.THUMBS_DOWN)

        assert recommender._scene_weights[SceneType.APPROVAL_REMINDER] >= 0.1


# ── 测试：推荐场景 ──

class TestRecommendationScenes:
    """推荐场景测试"""

    def test_approval_reminder_card(self, recommender, approval_context):
        """审批提醒卡片"""
        now = datetime(2026, 5, 2, 14, 0, tzinfo=timezone.utc)
        recommender.set_first_use("2026-04-01")
        recommender.set_first_import("2026-04-01")

        cards = recommender.recommend(approval_context, now=now)

        approval_cards = [c for c in cards if c.scene_type == SceneType.APPROVAL_REMINDER]
        assert len(approval_cards) > 0
        assert "审批" in approval_cards[0].title

    def test_friday_weekly_report_card(self, recommender, friday_context):
        """周五周报推荐卡片"""
        # 周五下午
        friday_afternoon = datetime(2026, 5, 1, 15, 0, tzinfo=timezone.utc)
        recommender.set_first_use("2026-04-01")
        recommender.set_first_import("2026-04-01")

        cards = recommender.recommend(friday_context, now=friday_afternoon)

        report_cards = [c for c in cards if c.scene_type == SceneType.WEEKLY_REPORT]
        assert len(report_cards) > 0

    def test_quote_aggregation_card(self, recommender):
        """报价汇总卡片"""
        context = {
            "pending_approvals": [],
            "is_friday": False,
            "recent_quotes": [
                {"email_id": "q-001", "subject": "供应商A报价"},
                {"email_id": "q-002", "subject": "供应商B报价"},
            ],
            "anomalies": [],
        }
        now = datetime(2026, 5, 2, 14, 0, tzinfo=timezone.utc)
        recommender.set_first_use("2026-04-01")
        recommender.set_first_import("2026-04-01")

        cards = recommender.recommend(context, now=now)

        quote_cards = [c for c in cards if c.scene_type == SceneType.QUOTE_AGGREGATION]
        assert len(quote_cards) > 0


class TestRecommenderStats:
    """推荐统计测试"""

    def test_get_stats(self, recommender):
        """获取推荐统计"""
        recommender.set_first_use("2026-04-01")
        recommender.set_first_import("2026-04-01")

        stats = recommender.get_stats()

        assert "cold_start_stage" in stats
        assert "scene_weights" in stats
        assert "feedback_count" in stats
        assert "active_cards" in stats
        assert "daily_cards" in stats


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
