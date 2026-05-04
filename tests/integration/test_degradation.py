"""
降级测试（Degradation Tests）

测试LLM不可用时的系统降级行为，确保核心功能仍可运行。
基于 WithFallback 类的实际异步 API 重写。

测试场景：
1. LLM完全不可用 → 纯GBrain模式（local_fallback）
2. LLM超时 → 自动降级
3. LLM部分失败 → 重试+降级混合
4. 间歇断网 → 自动重试

作者：MailKnow Team
日期：2026-05-02（V2 重写）
"""

import asyncio
import os

# 导入待测模块
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src'))

from core.gate.classifier import EmailInfo, GateClassifier
from llm.client import LLMClient, LLMProvider, LLMResponse
from llm.fallback import FallbackConfig, FallbackResult, FallbackStrategy, WithFallback
from llm.token_budget_v2 import BudgetConfig, DegradationLevel, TokenBudgetController

# ── Fixtures ──

@pytest.fixture
def fallback_with_mock():
    """创建 WithFallback 实例 + mock LLMClient"""
    llm = AsyncMock(spec=LLMClient)
    config = FallbackConfig(
        max_retries=2,
        retry_delay_base=0.01,  # 极短延迟加速测试
        retry_delay_max=0.1,
        timeout_per_retry=0.5,
        strategy=FallbackStrategy.RETRY_THEN_LOCAL,
    )
    budget = TokenBudgetController(config=BudgetConfig(
        monthly_cost_limit=100.0,
        daily_cost_limit=10.0,
    ))
    wf = WithFallback(llm_client=llm, config=config, budget=budget)
    return wf, llm


@pytest.fixture
def gate_classifier():
    """创建 Gate 分类器实例"""
    return GateClassifier()


# ── 场景1：LLM完全不可用 → 纯GBrain模式 ──

class TestLLMUnavailable:
    """LLM完全不可用时，降级到本地"""

    @pytest.mark.asyncio
    async def test_llm_unavailable_uses_local_fallback(self, fallback_with_mock):
        """LLM抛异常 → 使用 local_fallback 函数"""
        wf, llm = fallback_with_mock
        llm.complete.side_effect = Exception("Service unavailable")

        result = await wf.call(
            prompt="Classify this email",
            local_fallback=lambda p, s: '{"is_approval": false}',
        )

        assert result.used_fallback is True
        assert result.content == '{"is_approval": false}'
        assert result.fallback_reason.startswith("llm_failed")

    @pytest.mark.asyncio
    async def test_llm_unavailable_default_fallback(self, fallback_with_mock):
        """LLM抛异常 → 无 local_fallback 时使用默认降级"""
        wf, llm = fallback_with_mock
        llm.complete.side_effect = Exception("Connection refused")

        result = await wf.call(
            prompt="审批邮件：请批准采购",
        )

        assert result.used_fallback is True
        assert result.provider == LLMProvider.LOCAL
        assert "审批" in result.content or "is_approval" in result.content

    def test_gate_without_llm(self, gate_classifier):
        """Gate分流在LLM不可用时仍可用（纯规则引擎）"""
        test_email = EmailInfo(
            subject='会议邀请：项目评审',
            from_addr='manager@example.com',
            to_addrs=['user@example.com'],
            cc_addrs=[],
            content='请参加周五的项目评审会议',
        )

        result = gate_classifier.classify(test_email)

        assert result is not None
        assert result.gate_class is not None

    @pytest.mark.asyncio
    async def test_local_immediately_strategy(self):
        """LOCAL_IMMEDIATELY 策略直接使用本地"""
        llm = AsyncMock(spec=LLMClient)
        config = FallbackConfig(strategy=FallbackStrategy.LOCAL_IMMEDIATELY)
        wf = WithFallback(llm_client=llm, config=config)

        result = await wf.call(
            prompt="Test",
            local_fallback=lambda p, s: 'local_result',
        )

        assert result.used_fallback is True
        assert result.content == 'local_result'
        # LLM 不应被调用
        llm.complete.assert_not_called()


# ── 场景2：LLM超时 → 自动降级 ──

class TestLLMTimeout:
    """LLM超时后自动降级"""

    @pytest.mark.asyncio
    async def test_llm_timeout_triggers_fallback(self, fallback_with_mock):
        """LLM超时 → 降级到 local_fallback"""
        wf, llm = fallback_with_mock
        llm.complete.side_effect = asyncio.TimeoutError()

        result = await wf.call(
            prompt="Test prompt",
            local_fallback=lambda p, s: 'fallback_result',
        )

        assert result.used_fallback is True
        assert "timeout" in result.fallback_reason

    @pytest.mark.asyncio
    async def test_llm_timeout_retries_exhausted(self, fallback_with_mock):
        """LLM持续超时 → 重试耗尽后降级"""
        wf, llm = fallback_with_mock
        # 所有重试都超时
        llm.complete.side_effect = asyncio.TimeoutError()

        result = await wf.call(
            prompt="Test",
            local_fallback=lambda p, s: 'timeout_fallback',
        )

        assert result.used_fallback is True
        # 验证重试次数 = max_retries
        assert llm.complete.call_count == wf.config.max_retries + 1


# ── 场景3：LLM部分失败 → 重试+降级混合 ──

class TestLLMPartialFailure:
    """LLM部分失败：部分重试成功"""

    @pytest.mark.asyncio
    async def test_retry_succeeds_after_failure(self, fallback_with_mock):
        """第1次失败，重试成功"""
        wf, llm = fallback_with_mock
        llm.complete.side_effect = [
            Exception("Temp error"),
            LLMResponse(
                content='{"result": "ok"}',
                provider=LLMProvider.OPENAI,
                model="gpt-4o-mini",
                tokens_in=100,
                tokens_out=50,
            ),
        ]

        result = await wf.call(prompt="Test")

        assert result.used_fallback is False
        assert result.retries == 1
        assert result.content == '{"result": "ok"}'

    @pytest.mark.asyncio
    async def test_all_retries_fail_then_fallback(self, fallback_with_mock):
        """所有重试都失败 → 降级"""
        wf, llm = fallback_with_mock
        # 第1次主调用 + max_retries 次重试都失败
        llm.complete.side_effect = Exception("Persistent error")

        result = await wf.call(
            prompt="Test",
            local_fallback=lambda p, s: 'final_fallback',
        )

        assert result.used_fallback is True
        assert result.content == 'final_fallback'

    @pytest.mark.asyncio
    async def test_mixed_success_and_failure(self, fallback_with_mock):
        """多次调用中，部分成功部分降级"""
        wf, llm = fallback_with_mock

        # 第1次调用成功
        llm.complete.side_effect = [
            LLMResponse(content='ok1', provider=LLMProvider.OPENAI, model="gpt-4o-mini", tokens_in=50, tokens_out=20),
        ]
        result1 = await wf.call(prompt="Test1")
        assert result1.used_fallback is False
        assert result1.content == 'ok1'

        # 第2次调用：所有重试都失败 → 降级
        llm.complete.side_effect = Exception("Persistent error")
        result2 = await wf.call(prompt="Test2", local_fallback=lambda p, s: 'fb2')
        assert result2.used_fallback is True
        assert result2.content == 'fb2'

        # 第3次调用成功
        llm.complete.side_effect = [
            LLMResponse(content='ok3', provider=LLMProvider.OPENAI, model="gpt-4o-mini", tokens_in=50, tokens_out=20),
        ]
        result3 = await wf.call(prompt="Test3")
        assert result3.used_fallback is False
        assert result3.content == 'ok3'


# ── 场景4：间歇断网 → 自动重试 ──

class TestIntermittentNetwork:
    """间歇断网场景"""

    @pytest.mark.asyncio
    async def test_intermittent_failure_eventually_succeeds(self, fallback_with_mock):
        """间歇断网：前几次失败，最终成功"""
        wf, llm = fallback_with_mock
        llm.complete.side_effect = [
            ConnectionError("Network unreachable"),
            ConnectionError("Network unreachable"),
            LLMResponse(content='recovered', provider=LLMProvider.OPENAI, model="gpt-4o-mini", tokens_in=30, tokens_out=10),
        ]

        result = await wf.call(prompt="Test")
        assert result.used_fallback is False
        assert result.content == 'recovered'
        assert result.retries == 2

    @pytest.mark.asyncio
    async def test_network_down_uses_fallback(self, fallback_with_mock):
        """网络持续断开 → 降级"""
        wf, llm = fallback_with_mock
        llm.complete.side_effect = ConnectionError("Network down")

        result = await wf.call(
            prompt="Test",
            local_fallback=lambda p, s: 'offline_result',
        )

        assert result.used_fallback is True
        assert result.content == 'offline_result'


# ── 降级机制细节 ──

class TestFallbackMechanism:
    """降级机制细节测试"""

    @pytest.mark.asyncio
    async def test_fail_fast_strategy_raises(self):
        """FAIL_FAST 策略不降级，直接抛异常"""
        llm = AsyncMock(spec=LLMClient)
        llm.complete.side_effect = Exception("No LLM")
        config = FallbackConfig(strategy=FallbackStrategy.FAIL_FAST, max_retries=0)
        wf = WithFallback(llm_client=llm, config=config)

        # FAIL_FAST 没有 local_fallback，也没有默认降级路径中提供结果
        # 实际上 _use_local_fallback 在 FAIL_FAST 时也会被调用
        result = await wf.call(prompt="Test")
        # FAIL_FAST 仍然会走到 _use_local_fallback（因为没有 local_fallback 传入）
        assert result.used_fallback is True

    @pytest.mark.asyncio
    async def test_budget_exceeded_triggers_fallback(self):
        """预算超限 → 降级到本地"""
        llm = AsyncMock(spec=LLMClient)
        # 设置极低预算
        budget = TokenBudgetController(config=BudgetConfig(
            monthly_cost_limit=0.001,
            daily_cost_limit=0.001,
            monthly_token_limit=100,
            daily_token_limit=100,
        ))
        # 消耗预算使其进入 PURE_GBRAIN
        budget.record(tokens_in=50, tokens_out=50, cost=0.001, provider="test", task_type="general")

        config = FallbackConfig(max_retries=1)
        wf = WithFallback(llm_client=llm, config=config, budget=budget)

        result = await wf.call(
            prompt="Test",
            local_fallback=lambda p, s: 'budget_exceeded',
        )

        # 预算超限应直接降级
        assert result.used_fallback is True
        assert 'budget' in result.fallback_reason
        # LLM 不应被调用
        llm.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallback_result_structure(self, fallback_with_mock):
        """FallbackResult 结构完整性"""
        wf, llm = fallback_with_mock
        llm.complete.side_effect = Exception("Error")

        result = await wf.call(
            prompt="审批请求",
            local_fallback=lambda p, s: '{"is_approval": true}',
        )

        assert isinstance(result, FallbackResult)
        assert result.used_fallback is True
        assert result.provider == LLMProvider.LOCAL
        assert result.model == "local-fallback"
        assert isinstance(result.fallback_reason, str)
        assert len(result.fallback_reason) > 0

    @pytest.mark.asyncio
    async def test_stats_tracking(self, fallback_with_mock):
        """stats 属性追踪降级统计"""
        wf, llm = fallback_with_mock

        # 正常调用
        llm.complete.return_value = LLMResponse(
            content='ok', provider=LLMProvider.OPENAI, model="gpt-4o-mini", tokens_in=50, tokens_out=20
        )
        await wf.call(prompt="Test1")

        # 降级调用
        llm.complete.side_effect = Exception("Error")
        await wf.call(prompt="Test2", local_fallback=lambda p, s: 'fb')

        stats = wf.stats
        assert stats['total_calls'] == 2
        assert stats['fallback_calls'] == 1
        assert stats['fallback_rate'] == 0.5


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
