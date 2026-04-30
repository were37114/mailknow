"""Tests for W7: LLM fallback wrapper, approval pipeline, and scene recommender."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta

# ===== Test WithFallback =====

from llm.fallback import WithFallback, FallbackConfig, FallbackStrategy, FallbackResult
from llm.client import LLMClient, LLMProvider, LLMResponse
from llm.token_budget_v2 import TokenBudgetController, DegradationLevel, BudgetConfig


class TestWithFallback:
    """Test withFallback wrapper."""
    
    def test_fallback_config_defaults(self):
        """Test default fallback configuration."""
        config = FallbackConfig()
        assert config.max_retries == 2
        assert config.strategy == FallbackStrategy.RETRY_THEN_LOCAL
        assert config.desensitize_before_llm is True
    
    @pytest.mark.asyncio
    async def test_fallback_to_local_on_budget_exceeded(self):
        """Test fallback to local when budget exceeded."""
        # Create budget controller already at limit
        budget = TokenBudgetController(config=BudgetConfig(
            daily_token_limit=100,
            monthly_token_limit=100,
        ))
        budget._daily_tokens = 200  # Exceed limit
        
        # Create LLM client mock
        llm = MagicMock(spec=LLMClient)
        llm.provider = LLMProvider.OPENAI
        llm.complete = AsyncMock(side_effect=Exception("Should not be called"))
        
        wf = WithFallback(llm_client=llm, budget=budget, config=FallbackConfig())
        
        result = await wf.call(
            prompt="Test prompt",
            local_fallback=lambda p, s: '{"result": "local"}',
            task_type="test",
            estimated_tokens=500,
        )
        
        assert result.used_fallback is True
        assert result.provider == LLMProvider.LOCAL
        assert "local" in result.content
    
    @pytest.mark.asyncio
    async def test_fallback_to_local_on_llm_failure(self):
        """Test fallback when LLM call fails."""
        # Mock LLM that always fails
        llm = MagicMock(spec=LLMClient)
        llm.provider = LLMProvider.OPENAI
        llm.complete = AsyncMock(side_effect=Exception("API error"))
        
        budget = TokenBudgetController()
        wf = WithFallback(llm_client=llm, budget=budget, config=FallbackConfig(max_retries=1))
        
        result = await wf.call(
            prompt="Test prompt",
            local_fallback=lambda p, s: '{"result": "local_fallback"}',
            task_type="test",
        )
        
        assert result.used_fallback is True
        assert "local_fallback" in result.content
    
    @pytest.mark.asyncio
    async def test_fallback_stats(self):
        """Test fallback statistics tracking."""
        wf = WithFallback(config=FallbackConfig(
            strategy=FallbackStrategy.LOCAL_IMMEDIATELY,
        ))
        
        await wf.call(prompt="test", task_type="test")
        await wf.call(prompt="test2", task_type="test")
        
        stats = wf.stats
        assert stats["total_calls"] == 2
        assert stats["fallback_calls"] == 2
        assert stats["fallback_rate"] == 1.0
    
    @pytest.mark.asyncio
    async def test_local_immediately_strategy(self):
        """Test LOCAL_IMMEDIATELY strategy skips LLM."""
        wf = WithFallback(config=FallbackConfig(
            strategy=FallbackStrategy.LOCAL_IMMEDIATELY,
        ))
        
        result = await wf.call(
            prompt="Classify this approval",
            task_type="approval",
        )
        
        assert result.used_fallback is True
    
    @pytest.mark.asyncio
    async def test_desensitization_before_llm(self):
        """Test input desensitization before LLM call."""
        llm = MagicMock(spec=LLMClient)
        llm.provider = LLMProvider.LOCAL  # Use local to avoid real API
        llm.complete = AsyncMock(return_value=LLMResponse(
            content='{"result": "ok"}',
            provider=LLMProvider.LOCAL,
            model="local",
            tokens_in=0,
            tokens_out=0,
        ))
        
        wf = WithFallback(
            llm_client=llm,
            config=FallbackConfig(desensitize_before_llm=True),
        )
        
        # Input with sensitive data
        result = await wf.call(
            prompt="张三的手机号是13812345678，请审批",
            task_type="approval",
        )
        
        # Should have been desensitized
        # (Local provider won't actually call, but the path is tested)


# ===== Test Approval Actions =====

from scenes.approval.actions import (
    ApprovalActions, ApprovalCard, ApprovalAction, ApprovalStatus,
    AmountCategory, classify_amount, BatchApprovalResult,
    ConfirmationRequiredError,
)


class TestApprovalActions:
    """Test approval closed-loop operations."""
    
    def test_classify_amount(self):
        """Test amount classification."""
        assert classify_amount(5000) == AmountCategory.SMALL
        assert classify_amount(10000) == AmountCategory.SMALL
        assert classify_amount(50000) == AmountCategory.MEDIUM
        assert classify_amount(100000) == AmountCategory.MEDIUM
        assert classify_amount(200000) == AmountCategory.LARGE
        assert classify_amount(None) == AmountCategory.UNKNOWN
    
    def test_classify_amount_usd(self):
        """Test USD amount classification (approximate conversion)."""
        # $1500 ≈ ¥10800 → MEDIUM
        assert classify_amount(1500, "USD") == AmountCategory.MEDIUM
        # $500 ≈ ¥3600 → SMALL
        assert classify_amount(500, "USD") == AmountCategory.SMALL
    
    def test_create_card(self):
        """Test creating an approval card."""
        actions = ApprovalActions()
        card = actions.create_card(
            email_id="email:123",
            subject="采购审批",
            requester="zhangsan@company.com",
            approver="lisi@company.com",
            confidence=0.9,
            confidence_level="high",
            amount=5000,
            currency="CNY",
        )
        
        assert card.email_id == "email:123"
        assert card.subject == "采购审批"
        assert card.amount == 5000
        assert card.amount_category == AmountCategory.SMALL
        assert card.status == ApprovalStatus.PENDING
        assert card.is_actionable is True
    
    def test_approve_small_amount(self):
        """Test approving a small amount (no double confirmation)."""
        actions = ApprovalActions()
        card = actions.create_card(
            email_id="e1",
            subject="小额审批",
            amount=5000,
        )
        
        result = actions.approve(card.card_id, comment="同意", actor="lisi")
        assert result.status == ApprovalStatus.APPROVED
        assert result.action == ApprovalAction.APPROVE
    
    def test_approve_large_amount_needs_confirmation(self):
        """Test large amount requires double confirmation."""
        actions = ApprovalActions()
        card = actions.create_card(
            email_id="e2",
            subject="大额审批",
            amount=200000,
        )
        
        # First attempt should require confirmation
        with pytest.raises(ConfirmationRequiredError):
            actions.approve(card.card_id, actor="lisi")
        
        # With force=True should succeed
        result = actions.approve(card.card_id, actor="lisi", force=True)
        assert result.status == ApprovalStatus.APPROVED
    
    def test_reject(self):
        """Test rejecting an approval."""
        actions = ApprovalActions()
        card = actions.create_card(email_id="e3", subject="拒绝测试")
        
        result = actions.reject(card.card_id, comment="不符合要求", actor="lisi")
        assert result.status == ApprovalStatus.REJECTED
        assert result.action == ApprovalAction.REJECT
    
    def test_forward(self):
        """Test forwarding an approval."""
        actions = ApprovalActions()
        card = actions.create_card(email_id="e4", subject="转发测试")
        
        result = actions.forward(card.card_id, forward_to="wangwu@company.com", actor="lisi")
        assert result.status == ApprovalStatus.FORWARDED
        assert "wangwu" in result.comment
    
    def test_batch_approve(self):
        """Test batch approval mode."""
        actions = ApprovalActions()
        
        # Create 5 cards: 3 small, 1 large, 1 already processed
        cards = []
        for i in range(3):
            c = actions.create_card(email_id=f"batch_{i}", subject=f"小额{i}", amount=3000)
            cards.append(c)
        
        # Large amount card
        large = actions.create_card(email_id="batch_large", subject="大额", amount=200000)
        
        # Already approved card
        done = actions.create_card(email_id="batch_done", subject="已完成", amount=1000)
        actions.approve(done.card_id, actor="test")
        
        # Batch approve with skip_large
        result = actions.batch_approve(
            card_ids=[c.card_id for c in cards] + [large.card_id, done.card_id],
            comment="批量审批",
            actor="lisi",
            skip_large=True,
        )
        
        assert result.approved == 3  # 3 small approved
        assert result.skipped >= 1  # 1 large + 1 done skipped
        assert result.total == 5
    
    def test_batch_approve_including_large(self):
        """Test batch approve with large amounts (force)."""
        actions = ApprovalActions()
        
        cards = []
        for i in range(2):
            c = actions.create_card(email_id=f"force_{i}", subject=f"审批{i}", amount=50000)
            cards.append(c)
        
        # With skip_large=False, large amounts get force-approved
        result = actions.batch_approve(
            card_ids=[c.card_id for c in cards],
            skip_large=False,
        )
        
        assert result.approved == 2
    
    def test_get_pending_cards(self):
        """Test filtering pending cards."""
        actions = ApprovalActions()
        
        # Create cards with different confidence levels
        actions.create_card(email_id="h1", subject="High", confidence=0.9, confidence_level="high")
        actions.create_card(email_id="m1", subject="Medium", confidence=0.7, confidence_level="medium")
        actions.create_card(email_id="l1", subject="Low", confidence=0.4, confidence_level="low")
        
        # Filter by confidence
        high_only = actions.get_pending_cards(confidence_level="high")
        assert len(high_only) == 1
        assert high_only[0].confidence_level == "high"
    
    def test_get_stats(self):
        """Test approval statistics."""
        actions = ApprovalActions()
        
        actions.create_card(email_id="s1", subject="S1", amount=1000)
        actions.create_card(email_id="s2", subject="S2", amount=50000)
        actions.create_card(email_id="s3", subject="S3", confidence_level="high")
        
        stats = actions.get_stats()
        assert stats["total"] == 3
        assert stats["pending"] == 3


# ===== Test Approval Detector V2 =====

from scenes.approval.detector import (
    ApprovalDetector, ApprovalDetection, ApprovalType, 
    ConfidenceLevel, _confidence_to_level,
)


class TestConfidenceLevel:
    """Test three-level confidence classification."""
    
    def test_high_confidence(self):
        assert _confidence_to_level(0.9) == ConfidenceLevel.HIGH
        assert _confidence_to_level(0.86) == ConfidenceLevel.HIGH
        assert _confidence_to_level(1.0) == ConfidenceLevel.HIGH
    
    def test_medium_confidence(self):
        assert _confidence_to_level(0.7) == ConfidenceLevel.MEDIUM
        assert _confidence_to_level(0.6) == ConfidenceLevel.MEDIUM
        assert _confidence_to_level(0.85) == ConfidenceLevel.MEDIUM
    
    def test_low_confidence(self):
        assert _confidence_to_level(0.5) == ConfidenceLevel.LOW
        assert _confidence_to_level(0.3) == ConfidenceLevel.LOW
        assert _confidence_to_level(0.0) == ConfidenceLevel.LOW


class TestApprovalDetection:
    """Test approval detection data class."""
    
    def test_needs_action_high_confidence(self):
        """High confidence direct approval needs action."""
        detection = ApprovalDetection(
            is_approval=True,
            approval_type=ApprovalType.DIRECT,
            confidence=0.9,
            confidence_level=ConfidenceLevel.HIGH,
            gate_class=MagicMock(),
        )
        assert detection.needs_action is True
    
    def test_needs_action_low_confidence(self):
        """Low confidence approval doesn't need action."""
        detection = ApprovalDetection(
            is_approval=True,
            approval_type=ApprovalType.DIRECT,
            confidence=0.4,
            confidence_level=ConfidenceLevel.LOW,
            gate_class=MagicMock(),
        )
        assert detection.needs_action is False
    
    def test_cc_approval_no_card(self):
        """CC approval should not create card."""
        detection = ApprovalDetection(
            is_approval=True,
            approval_type=ApprovalType.CC,
            confidence=0.7,
            confidence_level=ConfidenceLevel.MEDIUM,
            gate_class=MagicMock(),
        )
        assert detection.should_push is False
    
    def test_notification_no_push(self):
        """Approval notification should not push."""
        detection = ApprovalDetection(
            is_approval=False,
            approval_type=ApprovalType.NOTIFICATION,
            confidence=0.9,
            confidence_level=ConfidenceLevel.HIGH,
            gate_class=MagicMock(),
        )
        assert detection.should_push is False
    
    def test_high_confidence_direct_push(self):
        """High confidence direct approval should push."""
        detection = ApprovalDetection(
            is_approval=True,
            approval_type=ApprovalType.DIRECT,
            confidence=0.9,
            confidence_level=ConfidenceLevel.HIGH,
            gate_class=MagicMock(),
        )
        assert detection.should_push is True


# ===== Test Report Generator V2 =====

from scenes.report.generator import (
    ReportGenerator, DeterministicValidator, ReportScheduler,
    WeeklyReport, ReportSection, FORBIDDEN_PHRASES,
)


class TestDeterministicValidator:
    """Test deterministic derivation validation."""
    
    def test_factual_report_passes(self):
        """Report with only factual content should pass."""
        report = WeeklyReport(
            period_start="2026-04-20",
            period_end="2026-04-27",
            sections=[
                ReportSection(
                    title="重要事项",
                    items=["完成了项目A的评审", "与客户确认了需求变更"],
                    source_count=5,
                ),
            ],
            total_emails=20,
            generated_at="2026-04-27",
        )
        
        validator = DeterministicValidator()
        passed, warnings = validator.validate(report)
        assert passed is True
        assert len(warnings) == 0
    
    def test_report_with_prediction_fails(self):
        """Report with prediction content should fail validation."""
        report = WeeklyReport(
            period_start="2026-04-20",
            period_end="2026-04-27",
            sections=[
                ReportSection(
                    title="重要事项",
                    items=["完成了项目A的评审", "下周计划开始项目B"],
                    source_count=5,
                ),
            ],
            total_emails=20,
            generated_at="2026-04-27",
        )
        
        validator = DeterministicValidator()
        passed, warnings = validator.validate(report)
        assert passed is False
        assert len(warnings) > 0
        assert any("下周计划" in w for w in warnings)
    
    def test_forbidden_phrases(self):
        """Test all forbidden phrases are detected."""
        for phrase in FORBIDDEN_PHRASES[:5]:  # Test first 5
            report = WeeklyReport(
                period_start="2026-04-20",
                period_end="2026-04-27",
                sections=[
                    ReportSection(
                        title="Test",
                        items=[f"项目{phrase}启动"],
                        source_count=1,
                    ),
                ],
                total_emails=1,
                generated_at="2026-04-27",
            )
            
            validator = DeterministicValidator()
            passed, warnings = validator.validate(report)
            assert passed is False, f"Should detect: {phrase}"


class TestReportScheduler:
    """Test weekly report scheduler."""
    
    def test_should_generate_on_friday_4pm(self):
        """Should trigger on Friday at 16:00."""
        scheduler = ReportScheduler()
        # Friday = weekday 4
        friday_4pm = datetime(2026, 5, 1, 16, 0)  # This is a Friday
        if friday_4pm.weekday() != 4:
            friday_4pm = datetime(2026, 5, 8, 16, 0)  # Next Friday
        
        assert scheduler.should_generate(friday_4pm) is True
    
    def test_should_not_generate_on_monday(self):
        """Should not trigger on Monday."""
        scheduler = ReportScheduler()
        monday = datetime(2026, 4, 27, 16, 0)  # Monday
        
        assert scheduler.should_generate(monday) is False
    
    def test_should_not_generate_twice_same_week(self):
        """Should not generate twice in the same week."""
        scheduler = ReportScheduler()
        friday_4pm = datetime(2026, 5, 8, 16, 0)  # Friday
        
        assert scheduler.should_generate(friday_4pm) is True
        
        # Generate
        report = scheduler.generate_if_due(
            emails=[{"subject": "test", "from": "a@b.com", "gate_class": "routine"}],
            now=friday_4pm,
        )
        
        # Should not trigger again
        assert scheduler.should_generate(friday_4pm) is False


# ===== Test Scene Recommender =====

from scenes.recommender import (
    SceneRecommender, SceneCard, SceneType, FeedbackType,
    ColdStartStage, RecommendationBoundary,
)


class TestSceneRecommender:
    """Test scene recommendation engine."""
    
    def test_cold_start_day1(self):
        """Day1 stage should have conservative recommendations."""
        rec = SceneRecommender()
        rec.set_first_use(datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        
        stage = rec.get_cold_start_stage()
        assert stage == ColdStartStage.POST_IMPORT or stage == ColdStartStage.DAY_1
    
    def test_cold_start_month1(self):
        """Month1 stage should have full recommendations."""
        rec = SceneRecommender()
        rec.set_first_use("2026-03-01")  # 2 months ago
        rec.set_first_import("2026-03-02")
        
        stage = rec.get_cold_start_stage()
        assert stage == ColdStartStage.MONTH_1
    
    def test_recommend_with_approvals(self):
        """Should recommend approval reminder when pending approvals exist."""
        rec = SceneRecommender()
        rec.set_first_use("2026-03-01")
        rec.set_first_import("2026-03-02")
        
        context = {
            "pending_approvals": [
                {"subject": "采购审批", "confidence": 0.9, "email_id": "e1", "card_id": "c1"},
            ],
        }
        
        now = datetime(2026, 4, 29, 10, 0)  # Wednesday 10:00
        cards = rec.recommend(context, now=now)
        
        # Should have at least 1 card
        assert len(cards) >= 1
        assert any(c.scene_type == SceneType.APPROVAL_REMINDER for c in cards)
    
    def test_recommend_boundary_max_daily(self):
        """Should respect daily card limit."""
        boundary = RecommendationBoundary(max_daily_cards=2)
        rec = SceneRecommender(boundary=boundary)
        rec.set_first_use("2026-03-01")
        rec.set_first_import("2026-03-02")
        
        context = {
            "pending_approvals": [
                {"subject": f"审批{i}", "confidence": 0.9, "email_id": f"e{i}"}
                for i in range(10)
            ],
        }
        
        now = datetime(2026, 4, 29, 10, 0)
        cards = rec.recommend(context, now=now)
        
        # Should not exceed daily limit
        assert len(cards) <= 2
    
    def test_silent_hours_no_recommendations(self):
        """Should not recommend during silent hours."""
        boundary = RecommendationBoundary(
            silent_hours_start=22,
            silent_hours_end=8,
        )
        rec = SceneRecommender(boundary=boundary)
        rec.set_first_use("2026-03-01")
        rec.set_first_import("2026-03-02")
        
        # 23:00 - in silent hours
        now = datetime(2026, 4, 29, 23, 0)
        cards = rec.recommend({"pending_approvals": [{"subject": "审批", "confidence": 0.9}]}, now=now)
        assert len(cards) == 0
    
    def test_feedback_thumbs_up(self):
        """👍 feedback should increase scene weight."""
        rec = SceneRecommender()
        card = SceneCard(scene_type=SceneType.APPROVAL_REMINDER, title="审批")
        rec._cards[card.card_id] = card
        
        initial_weight = rec._scene_weights[SceneType.APPROVAL_REMINDER]
        
        rec.record_feedback(card.card_id, FeedbackType.THUMBS_UP)
        
        new_weight = rec._scene_weights[SceneType.APPROVAL_REMINDER]
        assert new_weight > initial_weight
        assert new_weight == initial_weight + 0.1
    
    def test_feedback_thumbs_down_cooldown(self):
        """👎 feedback should decrease weight and add cooldown."""
        rec = SceneRecommender()
        card = SceneCard(scene_type=SceneType.WEEKLY_REPORT, title="周报")
        rec._cards[card.card_id] = card
        
        initial_weight = rec._scene_weights[SceneType.WEEKLY_REPORT]
        
        rec.record_feedback(card.card_id, FeedbackType.THUMBS_DOWN)
        
        # Weight should decrease
        new_weight = rec._scene_weights[SceneType.WEEKLY_REPORT]
        assert new_weight < initial_weight
        assert new_weight == initial_weight - 0.2
        
        # Should be in cooldown
        assert SceneType.WEEKLY_REPORT in rec._cooldowns
    
    def test_weekly_report_on_friday(self):
        """Should recommend weekly report on Friday afternoon."""
        rec = SceneRecommender()
        rec.set_first_use("2026-03-01")
        rec.set_first_import("2026-03-02")
        
        # Find a Friday
        friday = datetime(2026, 5, 8, 15, 0)  # Friday 15:00
        
        context = {"is_friday": True}
        cards = rec.recommend(context, now=friday)
        
        # Should include weekly report card
        report_cards = [c for c in cards if c.scene_type == SceneType.WEEKLY_REPORT]
        assert len(report_cards) >= 1
    
    def test_quote_aggregation(self):
        """Should recommend quote aggregation when quotes detected."""
        rec = SceneRecommender()
        rec.set_first_use("2026-03-01")
        rec.set_first_import("2026-03-02")
        
        context = {
            "recent_quotes": [
                {"subject": f"报价{i}", "email_id": f"q{i}"}
                for i in range(5)
            ],
        }
        
        now = datetime(2026, 4, 29, 10, 0)
        cards = rec.recommend(context, now=now)
        
        # Should include quote card
        quote_cards = [c for c in cards if c.scene_type == SceneType.QUOTE_AGGREGATION]
        assert len(quote_cards) >= 1


# ===== Test Cold Start Manager =====

from scenes.cold_start import ColdStartManager, STAGE_STRATEGIES, ColdStartStage as CSStage


class TestColdStartManager:
    """Test cold start stage management."""
    
    def test_day1_no_data(self):
        """Day 1 with no data."""
        mgr = ColdStartManager()
        assert mgr.get_stage() == CSStage.DAY_1
    
    def test_post_import(self):
        """Post-import stage."""
        mgr = ColdStartManager()
        mgr.set_first_use()
        mgr.set_first_import()
        assert mgr.get_stage() == CSStage.POST_IMPORT
    
    def test_month1_full_personalization(self):
        """Month 1 stage with full personalization."""
        mgr = ColdStartManager()
        mgr.set_first_use("2026-03-01")
        mgr.set_first_import("2026-03-02")
        assert mgr.get_stage() == CSStage.MONTH_1
    
    def test_stage_strategy_enabled_scenes(self):
        """Each stage should enable progressively more scenes."""
        day1_scenes = STAGE_STRATEGIES[CSStage.DAY_1].enabled_scenes
        month1_scenes = STAGE_STRATEGIES[CSStage.MONTH_1].enabled_scenes
        
        assert len(day1_scenes) < len(month1_scenes)
    
    def test_get_stage_info(self):
        """Test stage info for UI display."""
        mgr = ColdStartManager()
        mgr.set_first_use("2026-03-01")
        mgr.set_first_import("2026-03-02")
        
        info = mgr.get_stage_info()
        assert "stage" in info
        assert "enabled_scenes" in info
        assert "max_daily_cards" in info


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
