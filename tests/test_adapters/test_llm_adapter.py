"""Tests for adapters/llm_adapter.py — all mocked."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cic_daily_report.adapters.llm_adapter import (
    _CIRCUIT_RECOVERY_SEC,
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
        model="qwen-qwq-32b",
        endpoint="https://api.groq.com/openai/v1/chat/completions",
        rate_limit_per_min=30,
    )


def _groq_llama4_provider() -> LLMProvider:
    return LLMProvider(
        name="groq_llama4",
        api_key="test-key",
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        endpoint="https://api.groq.com/openai/v1/chat/completions",
        rate_limit_per_min=30,
    )


def _cerebras_provider() -> LLMProvider:
    return LLMProvider(
        name="cerebras",
        api_key="test-key",
        model="qwen-3-32b",
        endpoint="https://api.cerebras.ai/v1/chat/completions",
        rate_limit_per_min=30,
    )


def _gemini_lite_provider() -> LLMProvider:
    return LLMProvider(
        name="gemini_flash_lite",
        api_key="test-key",
        model="gemini-2.5-flash-lite",
        endpoint="https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent",
        rate_limit_per_min=15,
    )


def _gemini_provider() -> LLMProvider:
    return LLMProvider(
        name="gemini_flash",
        api_key="test-key",
        model="gemini-2.5-flash",
        endpoint="https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
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
        assert len(providers) == 2
        assert providers[0].name == "groq"
        assert providers[1].name == "groq_llama4"

    def test_gemini_adds_two(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": "k2"}, clear=True):
            providers = _build_providers()
        assert len(providers) == 2
        assert providers[0].name == "gemini_flash"
        assert providers[1].name == "gemini_flash_lite"

    def test_groq_adds_two_providers(self):
        """Groq key creates both groq (Qwen3) and groq_llama4 (Llama 4 Scout)."""
        with patch.dict("os.environ", {"GROQ_API_KEY": "k1"}, clear=True):
            providers = _build_providers()
        assert len(providers) == 2
        assert providers[0].name == "groq"
        assert providers[1].name == "groq_llama4"

    def test_all_keys_five_providers(self):
        env = {"GROQ_API_KEY": "k1", "GEMINI_API_KEY": "k2", "CEREBRAS_API_KEY": "k3"}
        with patch.dict("os.environ", env, clear=True):
            providers = _build_providers()
        assert len(providers) == 5
        names = [p.name for p in providers]
        assert names == ["gemini_flash", "gemini_flash_lite", "groq", "groq_llama4", "cerebras"]

    def test_cerebras_only(self):
        with patch.dict("os.environ", {"CEREBRAS_API_KEY": "k3"}, clear=True):
            providers = _build_providers()
        assert len(providers) == 1
        assert providers[0].name == "cerebras"
        assert providers[0].model == "qwen-3-32b"


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

    async def test_circuit_breaker_opens_after_all_fail(self):
        """v0.29.0 (A7): After all providers fail, circuit breaker opens."""
        provider = _groq_provider()
        adapter = LLMAdapter(providers=[provider])

        with patch(
            "cic_daily_report.adapters.llm_adapter._call_groq",
            new_callable=AsyncMock,
            side_effect=Exception("dead"),
        ):
            with pytest.raises(LLMError):
                await adapter.generate("test")

        assert adapter.circuit_open is True

    async def test_failed_provider_skipped_in_chain(self):
        """v0.30.0: Per-provider circuit breaker skips failed provider."""
        groq = _groq_provider()
        gemini = _gemini_provider()
        adapter = LLMAdapter(providers=[groq, gemini])
        # Mark groq as recently failed — gemini should be tried directly
        adapter._provider_failed["groq"] = time.monotonic()

        gemini_resp = LLMResponse(text="gemini ok", tokens_used=5, model="flash")
        with (
            patch(
                "cic_daily_report.adapters.llm_adapter._call_groq",
                new_callable=AsyncMock,
                side_effect=Exception("should not be called"),
            ) as mock_groq,
            patch(
                "cic_daily_report.adapters.llm_adapter._call_gemini",
                new_callable=AsyncMock,
                return_value=gemini_resp,
            ),
        ):
            resp = await adapter.generate("test")

        assert resp.text == "gemini ok"
        assert adapter.last_provider == "gemini_flash"
        mock_groq.assert_not_called()

    async def test_all_failed_retries_oldest(self):
        """v0.31.0: When all providers failed, try the one that failed longest ago."""
        provider = _groq_provider()
        adapter = LLMAdapter(providers=[provider])
        # Mark as failed long ago (past recovery window)
        adapter._provider_failed["groq"] = time.monotonic() - _CIRCUIT_RECOVERY_SEC - 1

        groq_resp = LLMResponse(text="recovered", tokens_used=5, model="llama")
        with patch(
            "cic_daily_report.adapters.llm_adapter._call_groq",
            new_callable=AsyncMock,
            return_value=groq_resp,
        ):
            resp = await adapter.generate("test")

        assert resp.text == "recovered"
        assert adapter.circuit_open is False

    async def test_circuit_breaker_resets_on_success(self):
        """v0.29.0 (A7): Successful response resets circuit breaker."""
        provider = _groq_provider()
        adapter = LLMAdapter(providers=[provider])

        groq_resp = LLMResponse(text="ok", tokens_used=5, model="llama")
        with patch(
            "cic_daily_report.adapters.llm_adapter._call_groq",
            new_callable=AsyncMock,
            return_value=groq_resp,
        ):
            await adapter.generate("test")

        assert adapter.circuit_open is False

    async def test_track_failure_called_on_provider_error(self):
        """v0.29.0 (A2): Failed providers update QuotaManager timing."""
        groq = _groq_provider()
        gemini = _gemini_provider()
        adapter = LLMAdapter(providers=[groq, gemini])

        gemini_resp = LLMResponse(text="fallback", tokens_used=5, model="flash")
        with (
            patch(
                "cic_daily_report.adapters.llm_adapter._call_groq",
                new_callable=AsyncMock,
                side_effect=Exception("groq 429"),
            ),
            patch(
                "cic_daily_report.adapters.llm_adapter._call_gemini",
                new_callable=AsyncMock,
                return_value=gemini_resp,
            ),
        ):
            await adapter.generate("test")

        # Groq failed, its last_call_time should be updated
        groq_quota = adapter._quota._quotas.get("groq")
        assert groq_quota is not None
        assert groq_quota.last_call_time > 0


class TestProviderPreference:
    """v0.31.0: Provider preference reorders chain."""

    def test_prefer_reorders_providers(self):
        groq = _groq_provider()
        gemini = _gemini_provider()
        adapter = LLMAdapter(providers=[gemini, groq], prefer="groq")
        assert adapter._providers[0].name == "groq"
        assert adapter._providers[1].name == "gemini_flash"

    def test_prefer_unknown_keeps_original_order(self):
        groq = _groq_provider()
        gemini = _gemini_provider()
        adapter = LLMAdapter(providers=[gemini, groq], prefer="nonexistent")
        assert adapter._providers[0].name == "gemini_flash"

    def test_suggest_cooldown_gemini(self):
        adapter = LLMAdapter(providers=[_gemini_provider()])
        adapter._last_provider = "gemini_flash"
        adapter._last_tokens = 5000
        cooldown = adapter.suggest_cooldown()
        # Gemini: int(5000/32000 * 60) + 5 = 9 + 5 = 14 → clamped min 14
        assert 10 <= cooldown <= 30

    def test_suggest_cooldown_groq_large_response(self):
        adapter = LLMAdapter(providers=[_groq_provider()])
        adapter._last_provider = "groq"
        adapter._last_tokens = 11000
        cooldown = adapter.suggest_cooldown()
        # Groq: int(11000/12000 * 60) + 5 = 55 + 5 = 60
        assert cooldown == 60

    def test_suggest_cooldown_no_previous(self):
        adapter = LLMAdapter(providers=[_groq_provider()])
        assert adapter.suggest_cooldown() == 60

    def test_suggest_cooldown_zero_tokens_gemini(self):
        adapter = LLMAdapter(providers=[_gemini_provider()])
        adapter._last_provider = "gemini_flash"
        adapter._last_tokens = 0
        # Zero tokens + gemini prefix → default 10
        assert adapter.suggest_cooldown() == 10

    def test_suggest_cooldown_zero_tokens_groq(self):
        adapter = LLMAdapter(providers=[_groq_provider()])
        adapter._last_provider = "groq"
        adapter._last_tokens = 0
        # Zero tokens + groq → default 30
        assert adapter.suggest_cooldown() == 30

    def test_suggest_cooldown_zero_tokens_cerebras(self):
        adapter = LLMAdapter(providers=[_cerebras_provider()])
        adapter._last_provider = "cerebras"
        adapter._last_tokens = 0
        # Zero tokens + cerebras → default 10
        assert adapter.suggest_cooldown() == 10

    def test_suggest_cooldown_unknown_provider(self):
        adapter = LLMAdapter(providers=[_groq_provider()])
        adapter._last_provider = "unknown_model"
        adapter._last_tokens = 5000
        # Unknown provider uses fallback TPM 6000: int(5000/6000*60)+5 = 50+5 = 55
        cooldown = adapter.suggest_cooldown()
        assert cooldown == 55

    def test_suggest_cooldown_boundary_min(self):
        adapter = LLMAdapter(providers=[_gemini_provider()])
        adapter._last_provider = "gemini_flash"
        adapter._last_tokens = 1
        # int(1/32000*60)+5 = 0+5 = 5 → clamped min 10
        assert adapter.suggest_cooldown() == 10

    def test_suggest_cooldown_boundary_max(self):
        adapter = LLMAdapter(providers=[_groq_provider()])
        adapter._last_provider = "groq"
        adapter._last_tokens = 100000
        # int(100000/12000*60)+5 = 500+5 = 505 → clamped max 120
        assert adapter.suggest_cooldown() == 120

    def test_suggest_cooldown_gemini_lite(self):
        adapter = LLMAdapter(providers=[_gemini_lite_provider()])
        adapter._last_provider = "gemini_flash_lite"
        adapter._last_tokens = 5000
        # Same TPM 32000 as gemini_flash: int(5000/32000*60)+5 = 9+5 = 14
        cooldown = adapter.suggest_cooldown()
        assert cooldown == 14

    def test_prefer_none_keeps_order(self):
        gemini = _gemini_provider()
        groq = _groq_provider()
        adapter = LLMAdapter(providers=[gemini, groq], prefer=None)
        assert adapter._providers[0].name == "gemini_flash"
        assert adapter._providers[1].name == "groq"


class TestNewProviderRouting:
    """New providers (groq_llama4, cerebras) route through _call_groq (OpenAI-compatible)."""

    async def test_groq_llama4_uses_call_groq(self):
        provider = _groq_llama4_provider()
        adapter = LLMAdapter(providers=[provider])

        groq_resp = LLMResponse(text="llama4 ok", tokens_used=15, model="llama-4")
        with patch(
            "cic_daily_report.adapters.llm_adapter._call_groq",
            new_callable=AsyncMock,
            return_value=groq_resp,
        ) as mock_groq:
            resp = await adapter.generate("test prompt")

        assert resp.text == "llama4 ok"
        assert adapter.last_provider == "groq_llama4"
        mock_groq.assert_called_once()

    async def test_cerebras_uses_call_groq(self):
        provider = _cerebras_provider()
        adapter = LLMAdapter(providers=[provider])

        groq_resp = LLMResponse(text="cerebras ok", tokens_used=25, model="qwen-3")
        with patch(
            "cic_daily_report.adapters.llm_adapter._call_groq",
            new_callable=AsyncMock,
            return_value=groq_resp,
        ) as mock_groq:
            resp = await adapter.generate("test prompt")

        assert resp.text == "cerebras ok"
        assert adapter.last_provider == "cerebras"
        mock_groq.assert_called_once()

    async def test_shared_rate_group_groq(self):
        """groq and groq_llama4 share the 'groq' rate group."""
        groq = _groq_provider()
        llama4 = _groq_llama4_provider()
        adapter = LLMAdapter(providers=[groq, llama4])

        groq_resp = LLMResponse(text="ok", tokens_used=5, model="qwen")
        with patch(
            "cic_daily_report.adapters.llm_adapter._call_groq",
            new_callable=AsyncMock,
            return_value=groq_resp,
        ):
            await adapter.generate("test")

        # Both groq providers use shared "groq" rate key — check quota tracked under "groq"
        groq_quota = adapter._quota._quotas.get("groq")
        assert groq_quota is not None
        assert groq_quota.calls_made >= 1


class TestTimedCircuitBreaker:
    """v0.31.0: Time-based circuit breaker recovery."""

    def test_recent_failure_skipped(self):
        groq = _groq_provider()
        gemini = _gemini_provider()
        adapter = LLMAdapter(providers=[groq, gemini])
        # Groq failed just now
        adapter._provider_failed["groq"] = time.monotonic()
        available = adapter._get_available_providers()
        names = [p.name for p in available]
        assert "groq" not in names
        assert "gemini_flash" in names

    def test_old_failure_recovered(self):
        groq = _groq_provider()
        adapter = LLMAdapter(providers=[groq])
        # Groq failed long ago
        adapter._provider_failed["groq"] = time.monotonic() - _CIRCUIT_RECOVERY_SEC - 1
        available = adapter._get_available_providers()
        assert len(available) == 1
        assert available[0].name == "groq"

    def test_mixed_failure_states(self):
        """Some providers failed recently, others still available."""
        groq = _groq_provider()
        gemini = _gemini_provider()
        gemini_lite = _gemini_lite_provider()
        adapter = LLMAdapter(providers=[groq, gemini, gemini_lite])
        # Only groq failed recently
        adapter._provider_failed["groq"] = time.monotonic()
        available = adapter._get_available_providers()
        names = [p.name for p in available]
        assert "groq" not in names
        assert "gemini_flash" in names
        assert "gemini_flash_lite" in names

    def test_all_providers_failed_same_time(self):
        """All providers failed at same monotonic time — returns first by min()."""
        groq = _groq_provider()
        gemini = _gemini_provider()
        adapter = LLMAdapter(providers=[groq, gemini])
        now = time.monotonic()
        adapter._provider_failed["groq"] = now
        adapter._provider_failed["gemini_flash"] = now
        available = adapter._get_available_providers()
        # All failed within recovery window → returns oldest (min).
        # Both have same time, min() picks first in providers list = groq
        assert len(available) == 1
        assert available[0].name == "groq"


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


# ===========================================================================
# BUG-02: Groq Qwen reasoning_effort test (v2.0 Wave 0+1)
# ===========================================================================


class TestBug02GroqQwenReasoningEffort:
    """BUG-02: Groq Qwen must get reasoning_effort='none', NOT thinking param."""

    async def test_groq_qwen_reasoning_effort(self):
        """Groq Qwen3 payload has reasoning_effort='none' and no 'thinking' key."""
        # WHY: Groq API rejects `thinking: {type: disabled}` — it expects
        # `reasoning_effort: "none"` for Qwen3 models.
        provider = LLMProvider(
            name="groq",
            api_key="test-key",
            model="qwen/qwen3-32b",
            endpoint="https://api.groq.com/openai/v1/chat/completions",
            rate_limit_per_min=30,
        )

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "test response"}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 10},
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
            await _call_groq(provider, "test prompt", 1024, 0.7, "system")

        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        # Must have reasoning_effort="none"
        assert payload.get("reasoning_effort") == "none"
        # Must NOT have the old thinking param
        assert "thinking" not in payload

    async def test_cerebras_qwen_no_reasoning_effort(self):
        """Cerebras Qwen3 does NOT get reasoning_effort (handled by strip_think_tags)."""
        provider = LLMProvider(
            name="cerebras",
            api_key="test-key",
            model="qwen-3-32b",
            endpoint="https://api.cerebras.ai/v1/chat/completions",
            rate_limit_per_min=30,
        )

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "test"}, "finish_reason": "stop"}],
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
            await _call_groq(provider, "test", 1024, 0.7, "")

        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        # Cerebras should NOT have reasoning_effort
        assert "reasoning_effort" not in payload
        assert "thinking" not in payload
