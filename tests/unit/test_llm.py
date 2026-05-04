"""Tests for LLM client."""

import os
from unittest.mock import AsyncMock, Mock, patch

import pytest

from llm.client import LLMClient, LLMProvider, LLMResponse


@pytest.fixture
def local_client():
    """Create local LLM client."""
    return LLMClient(provider=LLMProvider.LOCAL)


@pytest.fixture
def mock_openai():
    """Create mock OpenAI client."""
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        client = LLMClient(provider=LLMProvider.OPENAI)
        yield client


def test_local_provider_detection():
    """Test auto-detection of local provider."""
    with patch.dict(os.environ, {}, clear=True):
        # Remove all API keys
        for key in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"]:
            os.environ.pop(key, None)

        client = LLMClient()
        assert client.provider == LLMProvider.LOCAL


def test_openai_provider_detection():
    """Test auto-detection of OpenAI provider."""
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        client = LLMClient()
        assert client.provider == LLMProvider.OPENAI


def test_anthropic_provider_detection():
    """Test auto-detection of Anthropic provider."""
    env = {"ANTHROPIC_API_KEY": "test-key"}
    with patch.dict(os.environ, env, clear=True):
        os.environ.pop("OPENAI_API_KEY", None)
        client = LLMClient()
        assert client.provider == LLMProvider.ANTHROPIC


def test_local_complete(local_client: LLMClient):
    """Test local fallback completion."""
    response = local_client._local_complete("审批请求", "系统提示")

    assert response.provider == LLMProvider.LOCAL
    assert response.model == "local-fallback"
    assert response.tokens_in == 0
    assert response.tokens_out == 0


def test_local_approval_response(local_client: LLMClient):
    """Test local approval response."""
    response = local_client._local_complete("这封邮件需要审批", None)

    assert "is_approval" in response.content
    assert response.provider == LLMProvider.LOCAL


def test_local_report_response(local_client: LLMClient):
    """Test local report response."""
    response = local_client._local_complete("生成周报", None)

    assert "周报" in response.content or "不可用" in response.content


def test_llm_response_properties():
    """Test LLMResponse properties."""
    response = LLMResponse(
        content="test",
        provider=LLMProvider.OPENAI,
        model="gpt-4o-mini",
        tokens_in=100,
        tokens_out=50,
    )

    assert response.tokens_total == 150


def test_cost_estimation(local_client: LLMClient):
    """Test cost estimation."""
    # Local provider should have zero cost
    assert local_client.estimate_cost() == 0.0

    # Simulate token usage for OpenAI
    client = LLMClient(provider=LLMProvider.OPENAI)
    client._total_tokens_in = 1_000_000
    client._total_tokens_out = 100_000

    # GPT-4o-mini: $0.15/1M input + $0.60/1M output
    expected = (1_000_000 * 0.15 + 100_000 * 0.60) / 1_000_000
    assert abs(client.estimate_cost() - expected) < 0.001
