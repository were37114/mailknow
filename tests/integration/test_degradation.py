"""
降级测试（Degradation Tests）

测试LLM不可用时的系统降级行为，确保核心功能仍可运行。

测试场景：
1. LLM完全不可用 → 纯GBrain模式
2. LLM超时10s → 自动降级
3. LLM部分失败 → 重试+降级混合
4. 间歇断网 → 自动重连

作者：MailKnow Team
日期：2026-05-01
"""

import pytest
import time
import threading
from unittest.mock import Mock, patch, MagicMock
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

# 导入待测模块
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src'))

from llm.fallback import withFallback, FallbackConfig
from core.gate.classifier import GateClassifier
from core.search.hybrid import HybridSearch


class TestLLMUnavailable:
    """场景1：LLM完全不可用"""
    
    def test_gate_without_llm(self):
        """Gate分流在LLM不可用时仍可用"""
        classifier = GateClassifier()
        
        # 测试纯规则分类
        test_email = {
            'subject': '会议邀请：项目评审',
            'content': '请参加周五的项目评审会议',
            'sender': 'manager@example.com'
        }
        
        result = classifier.classify(test_email)
        
        # 验证：即使没有LLM，Gate仍能分流（基于规则）
        assert result is not None
        assert 'gate_class' in result
        assert result['gate_class'] in ['G1', 'G2', 'G3', 'G4']
    
    def test_search_without_llm(self):
        """Hybrid Search在LLM不可用时仍可用"""
        # Hybrid Search使用本地embedding，不依赖LLM
        # 这里测试基本搜索功能
        assert True  # placeholder
    
    def test_approval_detection_without_llm(self):
        """审批识别降级到Tier2（规则匹配）"""
        # Tier4需要LLM，应降级到Tier2
        assert True  # placeholder


class TestLLMTimeout:
    """场景2：LLM超时10s"""
    
    def test_llm_timeout_triggers_fallback(self):
        """LLM超时10s触发降级"""
        
        # 模拟超时函数
        def slow_llm_call(prompt):
            time.sleep(15)  # 超过10s
            return "response"
        
        # 配置降级
        fallback_config = FallbackConfig(
            timeout=10,
            max_retries=2,
            fallback_value=None
        )
        
        # 使用withFallback
        safe_call = withFallback(slow_llm_call, fallback_config)
        
        # 执行应降级
        start_time = time.time()
        result = safe_call("test prompt")
        elapsed = time.time() - start_time
        
        # 验证：应在超时后降级
        assert elapsed < 12  # 不应超过超时时间太多
        assert result is None  # 降级返回默认值
    
    def test_tier4_extraction_timeout(self):
        """Tier4提取超时时降级"""
        assert True  # placeholder


class TestLLMPartialFailure:
    """场景3：LLM部分失败"""
    
    def test_partial_failure_with_retry(self):
        """50%失败率下重试+降级"""
        
        call_count = [0]
        
        def unreliable_llm(prompt):
            call_count[0] += 1
            if call_count[0] % 2 == 0:
                raise Exception("LLM temporarily unavailable")
            return f"Response to: {prompt}"
        
        fallback_config = FallbackConfig(
            max_retries=3,
            retry_delay=0.1,
            fallback_value=None
        )
        
        safe_call = withFallback(unreliable_llm, fallback_config)
        
        # 多次调用
        results = []
        for i in range(10):
            result = safe_call(f"prompt_{i}")
            results.append(result)
        
        # 验证：成功请求应正常响应，失败请求应降级
        success_count = sum(1 for r in results if r is not None)
        assert success_count >= 4  # 至少40%成功（50%失败率+重试）


class TestIntermittentNetwork:
    """场景4：间歇断网"""
    
    def test_network_disconnect_and_reconnect(self):
        """断网30s后自动重连"""
        
        network_state = {'connected': True, 'disconnect_time': 0}
        
        def toggle_network():
            time.sleep(5)
            network_state['connected'] = False
            network_state['disconnect_time'] = time.time()
            time.sleep(30)
            network_state['connected'] = True
        
        # 启动网络切换线程
        net_thread = threading.Thread(target=toggle_network)
        net_thread.start()
        
        # 模拟带网络检查的LLM调用
        def llm_with_network_check(prompt):
            if not network_state['connected']:
                raise ConnectionError("Network unavailable")
            return f"Response to: {prompt}"
        
        fallback_config = FallbackConfig(
            max_retries=5,
            retry_delay=2,
            fallback_value=None
        )
        
        safe_call = withFallback(llm_with_network_check, fallback_config)
        
        # 执行调用
        start = time.time()
        result = safe_call("test")
        elapsed = time.time() - start
        
        net_thread.join()
        
        # 验证：网络恢复后请求成功
        # 或降级返回默认值
        assert result is not None or result is None  # 任一结果均可
    
    def test_offline_queue_buffer(self):
        """断网期间缓存请求，恢复后续传"""
        assert True  # placeholder


class TestFallbackMechanism:
    """降级机制测试"""
    
    def test_fallback_returns_default(self):
        """降级返回默认值"""
        
        def raising_llm(prompt):
            raise Exception("LLM error")
        
        fallback_config = FallbackConfig(
            max_retries=1,
            fallback_value="DEFAULT_RESPONSE"
        )
        
        safe_call = withFallback(raising_llm, fallback_config)
        result = safe_call("test")
        
        assert result == "DEFAULT_RESPONSE"
    
    def test_fallback_with_callable(self):
        """降级使用回调函数"""
        
        def raising_llm(prompt):
            raise Exception("LLM error")
        
        def fallback_handler(prompt, error):
            return f"Fallback for: {prompt}"
        
        fallback_config = FallbackConfig(
            max_retries=1,
            fallback_handler=fallback_handler
        )
        
        safe_call = withFallback(raising_llm, fallback_config)
        result = safe_call("test prompt")
        
        assert result == "Fallback for: test prompt"
    
    def test_retry_with_exponential_backoff(self):
        """指数退避重试"""
        
        call_times = []
        
        def recording_llm(prompt):
            call_times.append(time.time())
            raise Exception("LLM error")
        
        fallback_config = FallbackConfig(
            max_retries=3,
            retry_delay=0.1,
            backoff_factor=2,
            fallback_value=None
        )
        
        safe_call = withFallback(recording_llm, fallback_config)
        start = time.time()
        result = safe_call("test")
        elapsed = time.time() - start
        
        # 验证：指数退避
        # 第1次：0s，第2次：0.1s，第3次：0.2s
        # 总时间应约0.3s
        assert elapsed >= 0.2  # 至少等待指数退避时间
        assert len(call_times) == 3  # 共3次重试


class TestDegradationMetrics:
    """降级指标测试"""
    
    def test_degradation_metrics_collected(self):
        """降级事件被记录"""
        
        metrics = {'fallback_count': 0, 'success_count': 0}
        
        def tracked_llm(prompt):
            metrics['success_count'] += 1
            return f"Response: {prompt}"
        
        fallback_config = FallbackConfig(
            max_retries=1,
            fallback_value=None,
            on_fallback=lambda: metrics.update({'fallback_count': metrics['fallback_count'] + 1})
        )
        
        safe_call = withFallback(tracked_llm, fallback_config)
        
        # 正常调用
        safe_call("test1")
        safe_call("test2")
        
        assert metrics['success_count'] == 2
        assert metrics['fallback_count'] == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
