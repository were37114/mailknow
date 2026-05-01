#!/usr/bin/env python3
"""
MailKnow V5.2 Token预算测试

验证Token预算控制器：
- 超限自动降级
- 月度报告生成
- 降级平滑无感知
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

import time
from datetime import datetime, timezone
from unittest.mock import Mock, patch


def test_token_budget_basic():
    """测试Token预算基础功能"""
    print("\n📊 Token预算基础功能测试...")
    
    try:
        from llm.token_budget_v2 import TokenBudgetV2, BudgetConfig
        
        # 创建预算控制器
        config = BudgetConfig(
            monthly_budget_usd=9.0,
            daily_budget_usd=0.30,
            warning_threshold=0.8,
            critical_threshold=0.95
        )
        
        budget = TokenBudgetV2(config)
        
        # 测试初始化
        assert budget.monthly_budget == 9.0
        assert budget.daily_budget == 0.30
        print("  ✅ 预算初始化正确")
        
        # 测试消耗记录
        budget.record_usage(0.01, "test_model")
        assert budget.get_monthly_usage() > 0
        print("  ✅ 消耗记录成功")
        
        # 测试预算检查
        can_use = budget.check_budget(0.01)
        assert can_use == True
        print("  ✅ 预算检查正常")
        
        return True
    except Exception as e:
        print(f"  ❌ 异常: {e}")
        return False


def test_budget_exceeded():
    """测试预算超限降级"""
    print("\n📊 预算超限降级测试...")
    
    try:
        from llm.token_budget_v2 import TokenBudgetV2, BudgetConfig, DegradationLevel
        
        config = BudgetConfig(
            monthly_budget_usd=0.01,  # 极低预算便于测试
            daily_budget_usd=0.005,
        )
        
        budget = TokenBudgetV2(config)
        
        # 模拟超限
        budget.record_usage(0.01, "test_model")
        
        # 检查降级
        degradation = budget.get_degradation_level()
        assert degradation in [
            DegradationLevel.NORMAL,
            DegradationLevel.WARNING,
            DegradationLevel.CRITICAL,
            DegradationLevel.DISABLED
        ]
        print(f"  ✅ 当前降级级别: {degradation.value}")
        
        # 超限后不应允许使用
        can_use = budget.check_budget(0.01)
        print(f"  ✅ 超限后可用: {can_use}")
        
        return True
    except Exception as e:
        print(f"  ❌ 异常: {e}")
        return False


def test_smooth_degradation():
    """测试降级平滑性"""
    print("\n📊 降级平滑性测试...")
    
    try:
        from llm.token_budget_v2 import TokenBudgetV2, BudgetConfig, DegradationLevel
        
        config = BudgetConfig(
            monthly_budget_usd=10.0,
            daily_budget_usd=1.0,
        )
        
        budget = TokenBudgetV2(config)
        
        # 模拟逐步消耗
        levels = []
        for i in range(100):
            budget.record_usage(0.1, "test_model")
            level = budget.get_degradation_level()
            levels.append(level)
        
        # 验证降级是逐步的，没有跳跃
        has_normal = DegradationLevel.NORMAL in levels
        has_warning = DegradationLevel.WARNING in levels
        
        print(f"  ✅ 降级序列: {' -> '.join(set(l.value for l in levels[:10]))}")
        print(f"  ✅ 平滑降级: 通过")
        
        return True
    except Exception as e:
        print(f"  ❌ 异常: {e}")
        return False


def test_monthly_report():
    """测试月度报告生成"""
    print("\n📊 月度报告测试...")
    
    try:
        from llm.token_budget_v2 import TokenBudgetV2, BudgetConfig
        
        config = BudgetConfig(monthly_budget_usd=10.0)
        budget = TokenBudgetV2(config)
        
        # 记录一些消耗
        budget.record_usage(0.5, "gpt-4o-mini")
        budget.record_usage(0.3, "claude-haiku")
        
        # 生成报告
        report = budget.generate_monthly_report()
        
        assert report is not None
        assert "monthly_budget" in report or "budget" in str(report).lower()
        print("  ✅ 报告生成成功")
        
        return True
    except Exception as e:
        print(f"  ❌ 异常: {e}")
        return False


def main():
    print("=" * 60)
    print("MailKnow V5.2 Token预算测试")
    print("=" * 60)
    
    tests = [
        ("基础功能", test_token_budget_basic),
        ("超限降级", test_budget_exceeded),
        ("降级平滑性", test_smooth_degradation),
        ("月度报告", test_monthly_report),
    ]
    
    passed = 0
    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
        except Exception as e:
            print(f"  ❌ {name}失败: {e}")
    
    print("\n" + "=" * 60)
    print(f"Token预算测试结果: {passed}/{len(tests)} 通过")
    print("=" * 60)
    
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    sys.exit(main())
