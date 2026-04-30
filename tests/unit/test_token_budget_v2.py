"""Tests for TokenBudgetController V2: monthly budget + degradation + persistence."""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timezone

from llm.token_budget_v2 import (
    TokenBudgetController,
    BudgetConfig,
    UsageSummary,
    DegradationLevel,
)


@pytest.fixture
def config():
    """Test budget config with small limits."""
    return BudgetConfig(
        daily_token_limit=1000,
        daily_cost_limit=0.10,
        monthly_token_limit=10000,
        monthly_cost_limit=5.00,
        per_request_token_limit=500,
        warning_threshold=0.8,
        degradation_threshold=0.95,
    )


@pytest.fixture
def db_path():
    """Create temp database path."""
    with tempfile.TemporaryDirectory() as d:
        yield str(Path(d) / "test_budget.db")


@pytest.fixture
def controller(config, db_path):
    """Create controller with test config and persistence."""
    return TokenBudgetController(config=config, db_path=db_path)


@pytest.fixture
def memory_controller(config):
    """Create controller without persistence."""
    return TokenBudgetController(config=config)


class TestBudgetConfig:
    """Tests for BudgetConfig."""

    def test_default_config(self):
        c = BudgetConfig()
        assert c.daily_token_limit == 500_000
        assert c.monthly_cost_limit == 9.00

    def test_custom_config(self):
        c = BudgetConfig(daily_token_limit=100, monthly_token_limit=5000)
        assert c.daily_token_limit == 100


class TestDegradationLevel:
    """Tests for DegradationLevel."""

    def test_levels(self):
        assert DegradationLevel.NORMAL.value == "normal"
        assert DegradationLevel.WARNING.value == "warning"
        assert DegradationLevel.DEGRADED.value == "degraded"
        assert DegradationLevel.PURE_GBRAIN.value == "pure_gbrain"


class TestUsageSummary:
    """Tests for UsageSummary."""

    def test_empty_summary(self):
        s = UsageSummary()
        assert s.daily_usage_ratio == 0.0
        assert s.monthly_usage_ratio == 0.0

    def test_usage_ratios(self):
        s = UsageSummary(
            daily_tokens=800, daily_limit=1000,
            monthly_tokens=5000, monthly_limit=10000,
        )
        assert s.daily_usage_ratio == 0.8
        assert s.monthly_usage_ratio == 0.5

    def test_remaining(self):
        s = UsageSummary(daily_tokens=600, daily_limit=1000, monthly_tokens=7000, monthly_limit=10000)
        assert s.daily_remaining == 400
        assert s.monthly_remaining == 3000


class TestTokenBudgetController:
    """Tests for TokenBudgetController V2."""

    def test_check_within_budget(self, memory_controller):
        """Test check passes when within budget."""
        assert memory_controller.check(500) is True

    def test_check_exceeds_per_request(self, memory_controller):
        """Test check fails when exceeding per-request limit."""
        assert memory_controller.check(600) is False

    def test_check_exceeds_daily(self, memory_controller):
        """Test check fails when exceeding daily limit."""
        memory_controller.record(400, 400, 0.0, "openai", "test")
        # 800 used, 500 requested = 1300 > 1000 limit
        assert memory_controller.check(500) is False

    def test_record_usage(self, memory_controller):
        """Test recording usage updates counters."""
        memory_controller.record(100, 50, 0.001, "openai", "tier4_extract")
        
        summary = memory_controller.get_summary()
        assert summary.daily_tokens == 150
        assert summary.daily_cost == 0.001
        assert summary.by_task.get("tier4_extract") == 150

    def test_degradation_normal(self, memory_controller):
        """Test normal degradation level."""
        assert memory_controller.degradation_level == DegradationLevel.NORMAL

    def test_degradation_warning(self, memory_controller):
        """Test warning degradation at 80%."""
        # 80% of 1000 = 800
        memory_controller.record(400, 400, 0.0, "openai", "test")
        assert memory_controller.degradation_level == DegradationLevel.WARNING

    def test_degradation_degraded(self, memory_controller):
        """Test degraded at 95%."""
        # 95% of 1000 = 950
        memory_controller.record(475, 475, 0.0, "openai", "test")
        assert memory_controller.degradation_level == DegradationLevel.DEGRADED

    def test_degradation_pure_gbrain(self, memory_controller):
        """Test pure GBrain mode at 100%."""
        # 100% of 1000
        memory_controller.record(500, 500, 0.0, "openai", "test")
        assert memory_controller.degradation_level == DegradationLevel.PURE_GBRAIN
        
        # LLM calls should be blocked
        assert memory_controller.check(100) is False

    def test_degraded_blocks_non_critical(self, memory_controller):
        """Test degraded mode blocks non-critical tasks."""
        # Reach degraded level
        memory_controller.record(475, 475, 0.0, "openai", "test")
        assert memory_controller.degradation_level == DegradationLevel.DEGRADED
        
        # Critical tasks allowed
        assert memory_controller.check(50, task_type="tier4_extract") is True
        assert memory_controller.check(50, task_type="approval") is True
        
        # Non-critical blocked
        assert memory_controller.check(50, task_type="report") is False
        assert memory_controller.check(50, task_type="general") is False

    def test_estimate_cost(self, memory_controller):
        """Test cost estimation."""
        cost = memory_controller.estimate_cost(1000, 500)
        # (1000 * 0.15 + 500 * 0.60) / 1M = (150 + 300) / 1M = 0.00045
        assert cost > 0
        assert cost < 0.01

    def test_persistence(self, config, db_path):
        """Test usage persistence across instances."""
        # First instance
        c1 = TokenBudgetController(config=config, db_path=db_path)
        c1.record(100, 50, 0.001, "openai", "test_task")
        
        # Second instance should load state
        c2 = TokenBudgetController(config=config, db_path=db_path)
        summary = c2.get_summary()
        assert summary.daily_tokens == 150
        assert summary.by_task.get("test_task") == 150

    def test_get_summary(self, memory_controller):
        """Test summary contains all fields."""
        memory_controller.record(100, 50, 0.001, "openai", "test")
        
        summary = memory_controller.get_summary()
        assert summary.daily_tokens == 150
        assert summary.daily_cost == 0.001
        assert summary.daily_limit == 1000
        assert summary.monthly_tokens == 150
        assert summary.monthly_limit == 10000
        assert summary.degradation == DegradationLevel.NORMAL

    def test_multiple_task_types(self, memory_controller):
        """Test tracking multiple task types."""
        memory_controller.record(100, 50, 0.0, "openai", "tier4_extract")
        memory_controller.record(200, 100, 0.0, "openai", "report")
        memory_controller.record(50, 25, 0.0, "openai", "approval")
        
        summary = memory_controller.get_summary()
        assert summary.by_task["tier4_extract"] == 150
        assert summary.by_task["report"] == 300
        assert summary.by_task["approval"] == 75
        assert summary.daily_tokens == 525

    def test_monthly_budget_check(self, memory_controller):
        """Test monthly budget is checked."""
        # Exhaust monthly budget (10000)
        for _ in range(20):
            memory_controller.record(250, 250, 0.0, "openai", "test")
        
        # Should be at/past monthly limit
        assert memory_controller.check(100) is False
