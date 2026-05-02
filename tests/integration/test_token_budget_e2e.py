#!/usr/bin/env python3
"""
MailKnow V5.2 Token预算测试

基于 TokenBudgetController 实际API重写：
- BudgetConfig: monthly_cost_limit, daily_cost_limit, monthly_token_limit, daily_token_limit
- TokenBudgetController: check(), record(), degradation_level, get_summary(), estimate_cost()
- DegradationLevel: NORMAL, WARNING, DEGRADED, PURE_GBRAIN

注意：degradation_level 基于 max(daily_ratio, monthly_ratio)，
      daily_token_limit 不应小于 monthly_token_limit / 30，否则 daily 会先触发。

作者：MailKnow Team
日期：2026-05-02（V2 重写）
"""

import sys
import os
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

import pytest
from datetime import datetime, timezone
from unittest.mock import patch

from llm.token_budget_v2 import TokenBudgetController, BudgetConfig, DegradationLevel, UsageSummary


# ── Fixtures ──

@pytest.fixture
def budget():
    """创建标准预算控制器"""
    config = BudgetConfig(
        monthly_cost_limit=9.0,
        daily_cost_limit=0.50,
        monthly_token_limit=10_000_000,
        daily_token_limit=500_000,
    )
    return TokenBudgetController(config=config)


@pytest.fixture
def degradation_budget():
    """创建用于测试降级级别的控制器（daily 限制足够大，避免 daily 先触发）"""
    config = BudgetConfig(
        monthly_cost_limit=9.0,
        daily_cost_limit=10.0,          # daily 足够大
        monthly_token_limit=10_000_000,
        daily_token_limit=10_000_000,   # daily = monthly，使降级仅由 monthly 驱动
        warning_threshold=0.8,
        degradation_threshold=0.95,
    )
    return TokenBudgetController(config=config)


@pytest.fixture
def budget_with_db():
    """创建带SQLite持久化的预算控制器"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    config = BudgetConfig(
        monthly_cost_limit=9.0,
        daily_cost_limit=0.50,
        monthly_token_limit=10_000_000,
        daily_token_limit=500_000,
    )
    controller = TokenBudgetController(config=config, db_path=db_path)
    yield controller, db_path

    # 清理
    try:
        os.unlink(db_path)
    except:
        pass


# ── 测试1：正常使用 ──

def test_normal_usage(budget):
    """日均50封邮件的Token消耗 → degradation_level == NORMAL"""
    # 模拟日常使用：50封邮件，每封约 500 tokens
    for i in range(50):
        budget.record(
            tokens_in=400,
            tokens_out=100,
            cost=budget.estimate_cost(400, 100),
            provider="openai",
            task_type="general",
        )

    assert budget.degradation_level == DegradationLevel.NORMAL

    # check 应允许
    assert budget.check(estimated_tokens=5000, task_type="general") is True


def test_check_allows_within_budget(budget):
    """预算内请求被允许"""
    assert budget.check(estimated_tokens=5000, task_type="general") is True
    # 注意：500000 tokens 超过 per_request_token_limit(10000)，会被拒绝
    assert budget.check(estimated_tokens=9999, task_type="general") is True


def test_check_blocks_per_request_limit(budget):
    """单次请求超过限制被拒绝"""
    assert budget.check(estimated_tokens=50000, task_type="general") is False


# ── 测试2：超限预警 ──

def test_warning_threshold(degradation_budget):
    """消耗达到80%月预算 → degradation_level == WARNING"""
    # 消耗到 80% 月 token 限制（daily 限制足够大不会先触发）
    target_tokens = int(degradation_budget.config.monthly_token_limit * 0.81)
    degradation_budget.record(
        tokens_in=target_tokens // 2,
        tokens_out=target_tokens // 2,
        cost=0.001,
        provider="openai",
        task_type="general",
    )

    assert degradation_budget.degradation_level == DegradationLevel.WARNING

    # WARNING 级别仍允许请求
    assert degradation_budget.check(estimated_tokens=100, task_type="general") is True


# ── 测试3：降级触发 ──

def test_degraded_threshold(degradation_budget):
    """消耗达到95%月预算 → degradation_level == DEGRADED"""
    # 消耗到 96% 月 token 限制
    target_tokens = int(degradation_budget.config.monthly_token_limit * 0.96)
    degradation_budget.record(
        tokens_in=target_tokens // 2,
        tokens_out=target_tokens // 2,
        cost=0.005,
        provider="openai",
        task_type="general",
    )

    assert degradation_budget.degradation_level == DegradationLevel.DEGRADED

    # DEGRADED 级别：仅关键任务被允许
    assert degradation_budget.check(estimated_tokens=50, task_type="tier4_extract") is True
    assert degradation_budget.check(estimated_tokens=50, task_type="approval") is True
    assert degradation_budget.check(estimated_tokens=50, task_type="general") is False


# ── 测试4：完全降级 ──

def test_pure_gbrain(degradation_budget):
    """月预算用尽 → degradation_level == PURE_GBRAIN"""
    # 消耗超过月 token 限制
    degradation_budget.record(
        tokens_in=degradation_budget.config.monthly_token_limit + 100,
        tokens_out=0,
        cost=0.01,
        provider="openai",
        task_type="general",
    )

    assert degradation_budget.degradation_level == DegradationLevel.PURE_GBRAIN

    # PURE_GBRAIN 模式拒绝所有请求
    assert degradation_budget.check(estimated_tokens=50, task_type="general") is False
    assert degradation_budget.check(estimated_tokens=50, task_type="approval") is False


# ── 测试5：成本估算 ──

def test_estimate_cost(budget):
    """成本估算与实际偏差<10%"""
    tokens_in = 500
    tokens_out = 200

    estimated = budget.estimate_cost(tokens_in, tokens_out)

    # 验证：GPT-4o-mini pricing: $0.15/1M input, $0.60/1M output
    expected = (500 * 0.15 + 200 * 0.60) / 1_000_000
    assert abs(estimated - expected) < 1e-10
    assert estimated > 0


def test_estimate_cost_zero(budget):
    """零token成本为零"""
    assert budget.estimate_cost(0, 0) == 0.0


# ── 测试6：使用摘要 ──

def test_get_summary(budget):
    """获取 UsageSummary 包含正确的 daily/monthly 数据"""
    budget.record(tokens_in=500, tokens_out=200, cost=0.0002, provider="openai", task_type="general")

    summary = budget.get_summary()

    assert isinstance(summary, UsageSummary)
    assert summary.daily_tokens == 700  # 500 + 200
    assert summary.daily_cost == 0.0002
    assert summary.monthly_tokens == 700
    assert summary.monthly_cost == 0.0002
    assert summary.daily_limit == budget.config.daily_token_limit
    assert summary.monthly_limit == budget.config.monthly_token_limit
    assert summary.degradation == DegradationLevel.NORMAL
    assert "general" in summary.by_task
    assert summary.by_task["general"] == 700


def test_summary_ratios(budget):
    """UsageSummary 的 ratio 属性正确"""
    # 消耗一部分
    budget.record(tokens_in=250000, tokens_out=250000, cost=0.01, provider="openai", task_type="general")

    summary = budget.get_summary()

    # daily_ratio = 500000 / 500000 = 1.0
    assert summary.daily_usage_ratio == 1.0
    # monthly_ratio = 500000 / 10000000 = 0.05
    assert abs(summary.monthly_usage_ratio - 0.05) < 0.001


# ── 测试7：持久化 ──

def test_persistence(budget_with_db):
    """写入SQLite后新建实例 → 数据恢复正确"""
    controller, db_path = budget_with_db

    # 写入数据
    controller.record(tokens_in=500, tokens_out=200, cost=0.0002, provider="openai", task_type="general")
    original_summary = controller.get_summary()

    # 新建实例从数据库加载
    controller2 = TokenBudgetController(config=controller.config, db_path=db_path)
    restored_summary = controller2.get_summary()

    assert restored_summary.daily_tokens == original_summary.daily_tokens
    assert restored_summary.monthly_tokens == original_summary.monthly_tokens


# ── 测试8：多任务类型 ──

def test_multi_task_tracking(budget):
    """多任务类型的消耗追踪"""
    budget.record(tokens_in=100, tokens_out=50, cost=0.001, provider="openai", task_type="tier4_extract")
    budget.record(tokens_in=200, tokens_out=100, cost=0.002, provider="openai", task_type="approval")
    budget.record(tokens_in=300, tokens_out=150, cost=0.003, provider="openai", task_type="report")

    summary = budget.get_summary()

    assert summary.by_task.get("tier4_extract") == 150
    assert summary.by_task.get("approval") == 300
    assert summary.by_task.get("report") == 450


# ── 测试9：降级级别序列 ──

def test_degradation_level_progression(degradation_budget):
    """降级级别按序递进：NORMAL → WARNING → DEGRADED → PURE_GBRAIN"""
    levels = []

    # 以5%步进记录，确保能捕获每个降级级别
    for step in range(1, 22):
        tokens = int(degradation_budget.config.monthly_token_limit * 0.05)
        degradation_budget.record(
            tokens_in=tokens // 2,
            tokens_out=tokens // 2,
            cost=0.001,
            provider="test",
            task_type="general",
        )
        levels.append(degradation_budget.degradation_level)

    # 应包含 NORMAL, WARNING, DEGRADED, PURE_GBRAIN
    unique_levels = set(levels)
    assert DegradationLevel.NORMAL in unique_levels
    assert DegradationLevel.WARNING in unique_levels
    assert DegradationLevel.DEGRADED in unique_levels
    assert DegradationLevel.PURE_GBRAIN in unique_levels


# ── Main（兼容手动执行） ──

def main():
    """手动执行入口"""
    import subprocess
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', __file__, '-v'],
        cwd=os.path.join(os.path.dirname(__file__), '..', '..'),
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
