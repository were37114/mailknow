"""Tests for token budget controller."""

from datetime import datetime

import pytest

from llm.token_budget import TokenBudget


@pytest.fixture
def budget():
    """Create token budget."""
    return TokenBudget(daily_limit=1000, per_request_limit=200, warning_threshold=0.8)


def test_check_within_budget(budget: TokenBudget):
    """Test checking request within budget."""
    assert budget.check(100) is True
    assert budget.check(200) is True


def test_check_exceeds_per_request(budget: TokenBudget):
    """Test checking request exceeding per-request limit."""
    assert budget.check(300) is False


def test_check_exceeds_daily(budget: TokenBudget):
    """Test checking request exceeding daily limit."""
    budget.record(900)
    assert budget.check(200) is False  # 900 + 200 > 1000


def test_record_usage(budget: TokenBudget):
    """Test recording token usage."""
    budget.record(100, cost=0.001)

    assert budget._used_today == 100
    assert budget._cost_today == 0.001


def test_remaining(budget: TokenBudget):
    """Test remaining tokens."""
    assert budget.remaining == 1000

    budget.record(300)
    assert budget.remaining == 700


def test_usage_ratio(budget: TokenBudget):
    """Test usage ratio."""
    assert budget.usage_ratio == 0.0

    budget.record(500)
    assert budget.usage_ratio == 0.5

    budget.record(300)
    assert budget.usage_ratio == 0.8


def test_daily_reset(budget: TokenBudget):
    """Test daily reset."""
    budget.record(500)
    assert budget._used_today == 500

    # Simulate new day
    budget._reset_date = "2000-01-01"
    assert budget.remaining == 1000  # Should reset


def test_default_budget():
    """Test default budget values."""
    budget = TokenBudget()

    assert budget.daily_limit == 500_000
    assert budget.per_request_limit == 10_000
    assert budget.daily_cost_limit == 0.50
