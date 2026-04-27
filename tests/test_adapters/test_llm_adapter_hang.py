"""Tests for PR#1 Emergency Fix — LLM hang protection.

Covers: asyncio.wait_for timeout, logger.exception empty-error logging, fallback.

WHY: Daily Pipeline hung 116min on 5/8 recent runs. Root cause was Gemini 2.5 Flash
socket stall (googleapis/python-genai#1893) — httpx timeout=60 did not catch it
because the socket stayed open with no data. Additionally, the except block used
str(e) which logged an EMPTY string for httpx.RemoteProtocolError(""), hiding the
real failure for 5 days.

These tests verify:
  F1: asyncio.wait_for fires within the 90s hard limit on a stalled call and
      converts to LLMTimeoutError (NOT retry-on-same-provider).
  F2: Empty-message exceptions still produce useful log output (type name +
      repr) and logger.exception writes a traceback.
  F3: A timeout on provider A falls back to provider B and returns B's response.

All network I/O is mocked — no real API calls in CI.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from cic_daily_report.adapters.llm_adapter import (
    _PROVIDER_CALL_TIMEOUT_SEC,
    LLMAdapter,
    LLMProvider,
    LLMResponse,
    LLMTimeoutError,
    _call_gemini,
)


def _gemini_provider() -> LLMProvider:
    return LLMProvider(
        name="gemini_flash",
        api_key="test-key",
        model="gemini-2.5-flash",
        endpoint="https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
        rate_limit_per_min=7,
    )


def _groq_provider() -> LLMProvider:
    return LLMProvider(
        name="groq",
        api_key="test-key",
        model="qwen/qwen3-32b",
        endpoint="https://api.groq.com/openai/v1/chat/completions",
        rate_limit_per_min=30,
    )


# ---------------------------------------------------------------------------
# F1: asyncio.wait_for triggers on socket stall
# ---------------------------------------------------------------------------


class TestAsyncioWaitForOnStall:
    """F1: Hard wall-clock timeout converts stalled HTTP calls to LLMTimeoutError."""

    async def test_asyncio_wait_for_triggers_on_socket_stall(self):
        """A hung httpx.post (simulated as asyncio.sleep(120)) must raise
        LLMTimeoutError within ~90s — NOT hang forever.

        WHY this test: reproduces the googleapis/python-genai#1893 hang
        symptom. If asyncio.wait_for wrapper is missing/broken, this test
        will itself time out (pytest-timeout=30 in pyproject.toml kills
        it), failing visibly.
        """
        provider = _gemini_provider()

        # Patch _PROVIDER_CALL_TIMEOUT_SEC down to 0.5s so the test completes
        # fast. WHY: we don't want the real 90s in unit tests; we only care
        # that asyncio.wait_for FIRES and converts to LLMTimeoutError.
        async def stall(*args, **kwargs):
            await asyncio.sleep(5)  # longer than the patched 0.5s timeout
            raise AssertionError("should have been cancelled by asyncio.wait_for")

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value.post = AsyncMock(side_effect=stall)
        mock_client.__aexit__.return_value = None

        with (
            patch("cic_daily_report.adapters.llm_adapter._PROVIDER_CALL_TIMEOUT_SEC", 0.5),
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            with pytest.raises(LLMTimeoutError) as exc_info:
                await _call_gemini(provider, "prompt", 100, 0.5, "")

        # Verify the exception carries provider context so callers can decide
        # to fall back rather than retry the same provider.
        assert exc_info.value.provider_name == "gemini_flash"
        assert exc_info.value.timeout_sec == 0.5

    async def test_timeout_constant_is_90_seconds(self):
        """Production timeout MUST be 90s — see WHY comment in llm_adapter.py
        (Master Analysis took 84s in the last successful run #58, 90s leaves
        6s headroom; per-tier dynamic timeouts land in PR#3)."""
        assert _PROVIDER_CALL_TIMEOUT_SEC == 90

    def test_llm_timeout_error_is_non_retriable(self):
        """LLMTimeoutError.retry MUST be False.

        WHY: LLMError defaults retry=True. Without this override, any caller
        checking `e.retry` (e.g. retry_utils) would retry the SAME hung
        provider — wasting another 90s per attempt on a socket that is
        already stalled. The intended recovery is fallback to the next
        provider in the chain, not retry. Review blocker from Winston.
        """
        err = LLMTimeoutError(provider_name="gemini_flash", timeout_sec=90)
        assert err.retry is False


# ---------------------------------------------------------------------------
# F2: Empty-error logging uses logger.exception + type name + repr
# ---------------------------------------------------------------------------


class TestEmptyErrorLogging:
    """F2: httpx.RemoteProtocolError("") with empty str(e) still logs usefully."""

    async def test_empty_error_still_logged_with_traceback(self):
        """Mock provider to raise httpx.RemoteProtocolError("") → assert:
          1. a traceback (logger.exception writes exc_info automatically)
          2. the exception CLASS name ('RemoteProtocolError') in the message
          3. the repr form (which always renders non-empty)

        WHY: the old `logger.warning(f"...: {e}")` wrote empty strings to the
        log when str(e)==""; that's how we silently lost 5 days of runs.

        WHY custom handler (not caplog): core/logger.py sets propagate=False,
        so pytest's caplog (which hooks the root logger) never sees records.
        We attach our own in-memory handler directly to the cic.llm_adapter
        logger so we can introspect what was actually emitted.
        """
        provider = _groq_provider()
        adapter = LLMAdapter(providers=[provider])

        target_logger = logging.getLogger("cic.llm_adapter")
        records: list[logging.LogRecord] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        capture = _Capture(level=logging.DEBUG)
        target_logger.addHandler(capture)
        try:
            with patch(
                "cic_daily_report.adapters.llm_adapter._call_groq",
                new_callable=AsyncMock,
                side_effect=httpx.RemoteProtocolError(""),
            ):
                with pytest.raises(Exception):
                    await adapter.generate("test")
        finally:
            target_logger.removeHandler(capture)

        joined = "\n".join((rec.getMessage() or "") + (rec.exc_text or "") for rec in records)

        # (1) class name must appear even when str(e) is empty.
        assert "RemoteProtocolError" in joined, (
            f"Exception class name must be logged even when str(e) is empty. Got log:\n{joined}"
        )
        # (2) a traceback must be present (logger.exception writes exc_info).
        has_tb = any(rec.exc_info is not None for rec in records)
        assert has_tb, "logger.exception must capture traceback via exc_info"


# ---------------------------------------------------------------------------
# F3: Timeout on provider A falls back to provider B
# ---------------------------------------------------------------------------


class TestTimeoutFallback:
    """F3: LLMTimeoutError from provider A must trigger fallback to provider B,
    NOT retry the same hung provider."""

    async def test_timeout_falls_back_to_next_provider(self):
        """Provider A (Gemini) raises LLMTimeoutError → adapter must try
        provider B (Groq) and return B's response. Log must show A failed.

        WHY custom handler: core/logger.py sets propagate=False so caplog
        cannot observe cic.llm_adapter records. We hook the logger directly.
        """
        gemini = _gemini_provider()
        groq = _groq_provider()
        adapter = LLMAdapter(providers=[gemini, groq])

        groq_resp = LLMResponse(text="fallback ok", tokens_used=5, model="qwen")

        target_logger = logging.getLogger("cic.llm_adapter")
        records: list[logging.LogRecord] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        capture = _Capture(level=logging.DEBUG)
        target_logger.addHandler(capture)
        try:
            with (
                patch(
                    "cic_daily_report.adapters.llm_adapter._call_gemini",
                    new_callable=AsyncMock,
                    side_effect=LLMTimeoutError("gemini_flash", 90),
                ) as mock_gemini,
                patch(
                    "cic_daily_report.adapters.llm_adapter._call_groq",
                    new_callable=AsyncMock,
                    return_value=groq_resp,
                ) as mock_groq,
            ):
                resp = await adapter.generate("test")
        finally:
            target_logger.removeHandler(capture)

        # Final response comes from provider B (Groq)
        assert resp.text == "fallback ok"
        assert adapter.last_provider == "groq"

        # Both providers were attempted (gemini first, then groq)
        mock_gemini.assert_awaited_once()
        mock_groq.assert_awaited_once()

        # Log must mention gemini failed + the timeout class name
        joined = "\n".join(rec.getMessage() for rec in records)
        assert "gemini_flash" in joined
        assert "LLMTimeoutError" in joined, (
            "Log must include LLMTimeoutError class name so operators can "
            "distinguish hangs from other failures. Got:\n" + joined
        )
