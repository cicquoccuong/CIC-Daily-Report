"""Tests for adapters/llm_adapter.py — all mocked."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cic_daily_report.adapters.llm_adapter import (
    LLMAdapter,
    LLMProvider,
    LLMResponse,
    _build_providers,
    _call_gemini,
    _call_groq,
)
from cic_daily_report.core.error_handler import LLMError


def _groq_provider() -> LLMProvider:
    return LLMProvider(
        name="groq",
        api_key="test-key",
        model="llama-3.3-70b-versatile",
        endpoint="https://api.groq.com/openai/v1/chat/completions",
        rate_limit_per_min=30,
    )


def _gemini_provider() -> LLMProvider:
    return LLMProvider(
        name="gemini_flash",
        api_key="test-key",
        model="gemini-2.0-flash",
        endpoint="https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
        rate_limit_per_min=15,
    )


class TestLLMResponse:
    def test_fields(self):
        resp = LLMResponse(text="hello", tokens_used=42, model="test")
        assert resp.text == "hello"
        assert resp.tokens_used == 42
        assert resp.model == "test"


class TestBuildProviders:
    def test_no_keys_returns_empty(self):
        with patch.dict("os.environ", {}, clear=True):
            providers = _build_providers()
        assert providers == []

    def test_groq_only(self):
        with patch.dict("os.environ", {"GROQ_API_KEY": "k1"}, clear=True):
            providers = _build_providers()
        assert len(providers) == 1
        assert providers[0].name == "groq"

    def test_gemini_adds_two(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "k2"}, clear=True):
            providers = _build_providers()
        assert len(providers) == 2
        assert providers[0].name == "gemini_flash"
        assert providers[1].name == "gemini_flash_lite"

    def test_all_keys_three_providers(self):
        env = {"GROQ_API_KEY": "k1", "GEMINI_API_KEY": "k2"}
        with patch.dict("os.environ", env, clear=True):
            providers = _build_providers()
        assert len(providers) == 3


class TestLLMAdapter:
    def test_no_providers_raises(self):
        with pytest.raises(LLMError, match="No LLM providers"):
            LLMAdapter(providers=[])

    async def test_generate_groq_success(self):
        provider = _groq_provider()
        adapter = LLMAdapter(providers=[provider])

        groq_resp = LLMResponse(text="result", tokens_used=10, model="llama")
        with patch(
            "cic_daily_report.adapters.llm_adapter._call_groq",
            new_callable=AsyncMock,
            return_value=groq_resp,
        ):
            resp = await adapter.generate("test prompt")

        assert resp.text == "result"
        assert adapter.last_provider == "groq"

    async def test_generate_gemini_success(self):
        provider = _gemini_provider()
        adapter = LLMAdapter(providers=[provider])

        gemini_resp = LLMResponse(text="gemini ok", tokens_used=20, model="flash")
        with patch(
            "cic_daily_report.adapters.llm_adapter._call_gemini",
            new_callable=AsyncMock,
            return_value=gemini_resp,
        ):
            resp = await adapter.generate("test prompt")

        assert resp.text == "gemini ok"
        assert adapter.last_provider == "gemini_flash"

    async def test_fallback_on_first_failure(self):
        groq = _groq_provider()
        gemini = _gemini_provider()
        adapter = LLMAdapter(providers=[groq, gemini])

        gemini_resp = LLMResponse(text="fallback", tokens_used=5, model="flash")
        with (
            patch(
                "cic_daily_report.adapters.llm_adapter._call_groq",
                new_callable=AsyncMock,
                side_effect=Exception("groq down"),
            ),
            patch(
                "cic_daily_report.adapters.llm_adapter._call_gemini",
                new_callable=AsyncMock,
                return_value=gemini_resp,
            ),
        ):
            resp = await adapter.generate("test prompt")

        assert resp.text == "fallback"
        assert adapter.last_provider == "gemini_flash"

    async def test_all_fail_raises_llm_error(self):
        provider = _groq_provider()
        adapter = LLMAdapter(providers=[provider])

        with patch(
            "cic_daily_report.adapters.llm_adapter._call_groq",
            new_callable=AsyncMock,
            side_effect=Exception("dead"),
        ):
            with pytest.raises(LLMError, match="All LLM providers failed"):
                await adapter.generate("test")


class TestCallGroq:
    async def test_parses_response(self):
        provider = _groq_provider()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "hello world"}}],
            "usage": {"total_tokens": 42},
        }
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "cic_daily_report.adapters.llm_adapter.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await _call_groq(provider, "prompt", 1024, 0.7, "system")

        assert result.text == "hello world"
        assert result.tokens_used == 42

    async def test_includes_system_prompt(self):
        provider = _groq_provider()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"total_tokens": 5},
        }
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "cic_daily_report.adapters.llm_adapter.httpx.AsyncClient",
            return_value=mock_client,
        ):
            await _call_groq(provider, "prompt", 1024, 0.7, "be helpful")

        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        messages = payload["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "be helpful"


class TestCallGemini:
    async def test_parses_response(self):
        provider = _gemini_provider()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "gemini says hi"}]}}],
            "usageMetadata": {"totalTokenCount": 30},
        }
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "cic_daily_report.adapters.llm_adapter.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await _call_gemini(provider, "prompt", 1024, 0.7, "")

        assert result.text == "gemini says hi"
        assert result.tokens_used == 30

    async def test_empty_candidates(self):
        provider = _gemini_provider()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"candidates": [], "usageMetadata": {}}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "cic_daily_report.adapters.llm_adapter.httpx.AsyncClient",
            return_value=mock_client,
        ):
            with pytest.raises(LLMError, match="Gemini returned no candidates"):
                await _call_gemini(provider, "prompt", 1024, 0.7, "")
