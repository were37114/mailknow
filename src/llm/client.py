"""Unified LLM client for MailKnow.

Supports:
- OpenAI (GPT-4o-mini)
- Anthropic (Claude Haiku)
- Local fallback (rule-based)
"""

import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class LLMProvider(str, Enum):
    """Supported LLM providers."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    LOCAL = "local"  # Fallback: no API call


@dataclass
class LLMResponse:
    """LLM response."""
    content: str
    provider: LLMProvider
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0

    @property
    def tokens_total(self) -> int:
        return self.tokens_in + self.tokens_out


class LLMClient:
    """Unified LLM client with fallback.

    Priority: OpenAI > Anthropic > Local (rule-based)
    """

    def __init__(
        self,
        provider: Optional[LLMProvider] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        """Initialize LLM client.

        Args:
            provider: LLM provider (auto-detect if None)
            api_key: API key (use env var if None)
            model: Model name (use default if None)
            base_url: Custom base URL (for proxies)
        """
        self.provider = provider or self._detect_provider()
        self.api_key = api_key
        self.model = model
        self.base_url = base_url

        # Token budget tracking
        self._total_tokens_in = 0
        self._total_tokens_out = 0

        logger.info(f"LLM client initialized: provider={self.provider.value}")

    def _detect_provider(self) -> LLMProvider:
        """Auto-detect provider from environment."""
        if os.getenv("OPENAI_API_KEY"):
            return LLMProvider.OPENAI
        if os.getenv("ANTHROPIC_API_KEY"):
            return LLMProvider.ANTHROPIC
        return LLMProvider.LOCAL

    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Generate completion.

        Args:
            prompt: User prompt
            system: System prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            json_mode: Force JSON output

        Returns:
            LLM response
        """
        try:
            if self.provider == LLMProvider.OPENAI:
                return await self._openai_complete(
                    prompt, system, temperature, max_tokens, json_mode
                )
            elif self.provider == LLMProvider.ANTHROPIC:
                return await self._anthropic_complete(
                    prompt, system, temperature, max_tokens
                )
            else:
                return self._local_complete(prompt, system)
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            # Fallback to local
            if self.provider != LLMProvider.LOCAL:
                logger.warning("Falling back to local provider")
                return self._local_complete(prompt, system)
            raise

    async def _openai_complete(
        self,
        prompt: str,
        system: Optional[str],
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> LLMResponse:
        """OpenAI completion."""
        import time

        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError("openai package required: pip install openai")

        api_key = self.api_key or os.getenv("OPENAI_API_KEY")
        model = self.model or "gpt-4o-mini"

        client_kwargs = {"api_key": api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        client = AsyncOpenAI(**client_kwargs)

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        start = time.time()

        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = await client.chat.completions.create(**kwargs)

        latency = (time.time() - start) * 1000

        content = response.choices[0].message.content
        tokens_in = response.usage.prompt_tokens if response.usage else 0
        tokens_out = response.usage.completion_tokens if response.usage else 0

        self._total_tokens_in += tokens_in
        self._total_tokens_out += tokens_out

        return LLMResponse(
            content=content,
            provider=LLMProvider.OPENAI,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency,
        )

    async def _anthropic_complete(
        self,
        prompt: str,
        system: Optional[str],
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        """Anthropic completion."""
        import time

        try:
            from anthropic import AsyncAnthropic
        except ImportError:
            raise ImportError("anthropic package required: pip install anthropic")

        api_key = self.api_key or os.getenv("ANTHROPIC_API_KEY")
        model = self.model or "claude-3-haiku-20240307"

        client = AsyncAnthropic(api_key=api_key)

        start = time.time()

        response = await client.messages.create(
            model=model,
            system=system or "",
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )

        latency = (time.time() - start) * 1000

        content = response.content[0].text
        tokens_in = response.usage.input_tokens
        tokens_out = response.usage.output_tokens

        self._total_tokens_in += tokens_in
        self._total_tokens_out += tokens_out

        return LLMResponse(
            content=content,
            provider=LLMProvider.ANTHROPIC,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency,
        )

    def _local_complete(
        self,
        prompt: str,
        system: Optional[str],
    ) -> LLMResponse:
        """Local fallback - rule-based responses.

        Used when no LLM API is available.
        Returns structured responses based on prompt patterns.
        """
        # For approval classification
        if "审批" in prompt or "approve" in prompt.lower():
            content = '{"is_approval": false, "confidence": 0.3, "reason": "local_fallback"}'
        # For report generation
        elif "周报" in prompt or "report" in prompt.lower():
            content = "无法生成周报：LLM服务不可用，请检查API配置"
        # For entity extraction
        elif "实体" in prompt or "entity" in prompt.lower():
            content = '{"entities": []}'
        else:
            content = "本地模式：LLM服务不可用"

        return LLMResponse(
            content=content,
            provider=LLMProvider.LOCAL,
            model="local-fallback",
            tokens_in=0,
            tokens_out=0,
            latency_ms=0.0,
        )

    @property
    def total_tokens(self) -> int:
        """Total tokens used."""
        return self._total_tokens_in + self._total_tokens_out

    def estimate_cost(self) -> float:
        """Estimate total cost in USD.

        GPT-4o-mini: $0.15/1M input, $0.60/1M output
        Claude Haiku: $0.25/1M input, $1.25/1M output
        """
        if self.provider == LLMProvider.OPENAI:
            return (self._total_tokens_in * 0.15 + self._total_tokens_out * 0.60) / 1_000_000
        elif self.provider == LLMProvider.ANTHROPIC:
            return (self._total_tokens_in * 0.25 + self._total_tokens_out * 1.25) / 1_000_000
        return 0.0


# Global instance
_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """Get global LLM client instance."""
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
