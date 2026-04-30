"""LLM fallback wrapper - withFallback pattern.

Provides automatic degradation when LLM is unavailable:
- Try primary LLM → retry with backoff → fall back to local
- Integrates with TokenBudgetController for budget-aware decisions
- Tracks degradation events for monitoring
"""

import asyncio
import logging
import time
from typing import Optional, Dict, Any, Callable, Awaitable, List
from dataclasses import dataclass, field
from enum import Enum

from .client import LLMClient, LLMResponse, LLMProvider, get_llm_client
from .token_budget_v2 import TokenBudgetController, DegradationLevel
from .desensitize import DesensitizeEngine

logger = logging.getLogger(__name__)


class FallbackStrategy(str, Enum):
    """Fallback strategies when LLM fails."""
    RETRY_THEN_LOCAL = "retry_then_local"   # Retry N times, then local
    LOCAL_IMMEDIATELY = "local_immediately"  # Skip LLM, go straight to local
    FAIL_FAST = "fail_fast"                  # No fallback, raise error


@dataclass
class FallbackConfig:
    """Configuration for fallback behavior."""
    max_retries: int = 2
    retry_delay_base: float = 1.0       # Base delay in seconds
    retry_delay_max: float = 10.0       # Max delay cap
    timeout_per_retry: float = 10.0     # Timeout per LLM call in seconds
    strategy: FallbackStrategy = FallbackStrategy.RETRY_THEN_LOCAL
    desensitize_before_llm: bool = True # Desensitize input before sending to LLM


@dataclass
class FallbackResult:
    """Result of a fallback-wrapped LLM call."""
    content: str
    provider: LLMProvider
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0
    retries: int = 0
    used_fallback: bool = False
    fallback_reason: str = ""
    was_desensitized: bool = False
    
    @property
    def tokens_total(self) -> int:
        return self.tokens_in + self.tokens_out


# Type for local fallback functions
LocalFallbackFn = Callable[[str, Optional[str]], str]


class WithFallback:
    """LLM call wrapper with automatic retry and fallback.
    
    Usage:
        wf = WithFallback(llm_client=client, budget=controller)
        
        # With local fallback function
        result = await wf.call(
            prompt="Classify this email...",
            system="You are an email classifier.",
            local_fallback=lambda prompt, system: '{"is_approval": false}',
            task_type="approval",
        )
        
        # Check if fallback was used
        if result.used_fallback:
            logger.warning(f"LLM failed, used local fallback: {result.fallback_reason}")
    """
    
    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        budget: Optional[TokenBudgetController] = None,
        config: Optional[FallbackConfig] = None,
        desensitize_engine: Optional[DesensitizeEngine] = None,
    ):
        """Initialize with fallback wrapper.
        
        Args:
            llm_client: LLM client (use global if None)
            budget: Token budget controller
            config: Fallback configuration
            desensitize_engine: Engine for desensitizing input before LLM
        """
        self.llm = llm_client or get_llm_client()
        self.budget = budget or TokenBudgetController()
        self.config = config or FallbackConfig()
        self.desensitize = desensitize_engine or DesensitizeEngine()
        
        # Stats
        self._total_calls = 0
        self._fallback_calls = 0
        self._retry_calls = 0
        self._desensitized_calls = 0
    
    async def call(
        self,
        prompt: str,
        system: Optional[str] = None,
        local_fallback: Optional[LocalFallbackFn] = None,
        task_type: str = "general",
        temperature: float = 0.0,
        max_tokens: int = 1024,
        json_mode: bool = False,
        estimated_tokens: int = 500,
    ) -> FallbackResult:
        """Make an LLM call with fallback protection.
        
        Args:
            prompt: User prompt
            system: System prompt
            local_fallback: Function to call if LLM fails
            task_type: Task type for budget tracking
            temperature: Sampling temperature
            max_tokens: Maximum output tokens
            json_mode: Force JSON output
            estimated_tokens: Estimated token count for budget check
            
        Returns:
            FallbackResult with content and metadata
        """
        self._total_calls += 1
        
        # Check if we should skip LLM entirely
        if self.config.strategy == FallbackStrategy.LOCAL_IMMEDIATELY:
            return self._use_local_fallback(prompt, system, local_fallback, "strategy=local_immediately")
        
        # Check token budget
        if not self.budget.check(estimated_tokens, task_type):
            degradation = self.budget.degradation_level
            if degradation == DegradationLevel.PURE_GBRAIN:
                return self._use_local_fallback(prompt, system, local_fallback, "budget_exceeded_pure_gbrain")
            elif degradation == DegradationLevel.DEGRADED and task_type not in ("tier4_extract", "approval"):
                return self._use_local_fallback(prompt, system, local_fallback, f"budget_degraded_task={task_type}")
        
        # Desensitize input if enabled
        actual_prompt = prompt
        was_desensitized = False
        desensitize_replacements = []
        
        if self.config.desensitize_before_llm:
            result = self.desensitize.desensitize(prompt)
            if result.was_modified:
                actual_prompt = result.sanitized
                was_desensitized = True
                desensitize_replacements = result.replacements
                self._desensitized_calls += 1
        
        # Try LLM with retries
        last_error = None
        for attempt in range(self.config.max_retries + 1):
            try:
                start = time.time()
                
                response = await asyncio.wait_for(
                    self.llm.complete(
                        prompt=actual_prompt,
                        system=system,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        json_mode=json_mode,
                    ),
                    timeout=self.config.timeout_per_retry,
                )
                
                latency = (time.time() - start) * 1000
                
                # Record usage
                self.budget.record(
                    tokens_in=response.tokens_in,
                    tokens_out=response.tokens_out,
                    cost=self.budget.estimate_cost(response.tokens_in, response.tokens_out),
                    provider=response.provider.value,
                    task_type=task_type,
                )
                
                # Restore desensitized content in response if needed
                content = response.content
                if was_desensitized and desensitize_replacements:
                    # The LLM response may contain sanitized values; restore them
                    content = self.desensitize.restore(content, desensitize_replacements)
                
                return FallbackResult(
                    content=content,
                    provider=response.provider,
                    model=response.model,
                    tokens_in=response.tokens_in,
                    tokens_out=response.tokens_out,
                    latency_ms=latency,
                    retries=attempt,
                    used_fallback=False,
                    was_desensitized=was_desensitized,
                )
                
            except asyncio.TimeoutError:
                last_error = "timeout"
                logger.warning(f"LLM call timeout (attempt {attempt + 1}/{self.config.max_retries + 1})")
            except Exception as e:
                last_error = str(e)
                logger.warning(f"LLM call failed (attempt {attempt + 1}): {e}")
            
            # Retry with exponential backoff (skip on last attempt)
            if attempt < self.config.max_retries:
                delay = min(
                    self.config.retry_delay_base * (2 ** attempt),
                    self.config.retry_delay_max,
                )
                self._retry_calls += 1
                await asyncio.sleep(delay)
        
        # All retries failed, use fallback
        return self._use_local_fallback(prompt, system, local_fallback, f"llm_failed: {last_error}")
    
    def _use_local_fallback(
        self,
        prompt: str,
        system: Optional[str],
        local_fallback: Optional[LocalFallbackFn],
        reason: str,
    ) -> FallbackResult:
        """Use local fallback function."""
        self._fallback_calls += 1
        
        if local_fallback:
            content = local_fallback(prompt, system)
        else:
            content = self._default_local_fallback(prompt, system)
        
        return FallbackResult(
            content=content,
            provider=LLMProvider.LOCAL,
            model="local-fallback",
            used_fallback=True,
            fallback_reason=reason,
        )
    
    def _default_local_fallback(self, prompt: str, system: Optional[str]) -> str:
        """Default local fallback when no custom function provided."""
        # Pattern matching for common task types
        if "审批" in prompt or "approve" in prompt.lower():
            return '{"is_approval": false, "confidence": 0.3, "approval_type": "none", "reason": "local_fallback_no_llm"}'
        elif "周报" in prompt or "report" in prompt.lower():
            return '{"sections": [], "reason": "local_fallback_no_llm"}'
        elif "实体" in prompt or "entity" in prompt.lower():
            return '{"entities": []}'
        elif "异常" in prompt or "anomaly" in prompt.lower():
            return '{"anomalies": []}'
        else:
            return '{"result": null, "reason": "local_fallback_no_llm"}'
    
    @property
    def stats(self) -> Dict[str, Any]:
        """Get fallback statistics."""
        return {
            "total_calls": self._total_calls,
            "fallback_calls": self._fallback_calls,
            "retry_calls": self._retry_calls,
            "desensitized_calls": self._desensitized_calls,
            "fallback_rate": self._fallback_calls / max(self._total_calls, 1),
        }


# Global instance
_fallback: Optional[WithFallback] = None


def get_fallback() -> WithFallback:
    """Get global fallback instance."""
    global _fallback
    if _fallback is None:
        _fallback = WithFallback()
    return _fallback
