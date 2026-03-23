"""Multi-LLM Adapter Pattern (QĐ2) — Gemini Flash → Gemini Flash Lite → Groq.

Unified interface: all providers return the same response format.
Automatic fallback when primary fails. Provider preference per pipeline.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import httpx

from cic_daily_report.core.error_handler import LLMError
from cic_daily_report.core.logger import get_logger
from cic_daily_report.core.quota_manager import QuotaManager

logger = get_logger("llm_adapter")

# v0.31.0: Provider-specific token-per-minute limits (output tokens).
# Used by suggest_cooldown() to calculate adaptive wait times.
_PROVIDER_TPM: dict[str, int] = {
    "gemini_flash": 32000,  # Generous TPM, RPM is the real limit
    "gemini_flash_lite": 32000,
    "groq": 6000,  # Groq free tier: ~6K output tokens/min
}

# v0.31.0: Circuit breaker recovery time (seconds).
# Provider marked failed won't be retried until this time elapses.
_CIRCUIT_RECOVERY_SEC = 300  # 5 minutes


@dataclass
class LLMResponse:
    """Normalized response from any LLM provider."""

    text: str
    tokens_used: int
    model: str


@dataclass
class LLMProvider:
    """Configuration for a single LLM provider."""

    name: str
    api_key: str
    model: str
    endpoint: str
    rate_limit_per_min: int


def _build_providers() -> list[LLMProvider]:
    """Build provider list from env vars. Skip providers with missing keys.

    Priority: Gemini Flash (best analysis) → Gemini Flash Lite → Groq (fallback).
    Gemini produces better Vietnamese crypto analysis than Groq Llama.
    """
    providers: list[LLMProvider] = []

    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if gemini_key:
        # v0.30.0: Both Gemini models share 15 RPM total on same API key.
        # Use shared rate limiter group "gemini" with 7 RPM each (14 max combined,
        # leaving 1 RPM headroom). QuotaManager tracks "gemini" as shared group.
        providers.append(
            LLMProvider(
                name="gemini_flash",
                api_key=gemini_key,
                model="gemini-2.0-flash",
                endpoint="https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
                rate_limit_per_min=7,
            )
        )
        providers.append(
            LLMProvider(
                name="gemini_flash_lite",
                api_key=gemini_key,
                model="gemini-2.0-flash-lite",
                endpoint="https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-lite:generateContent",
                rate_limit_per_min=7,
            )
        )

    groq_key = os.getenv("GROQ_API_KEY", "")
    if groq_key:
        providers.append(
            LLMProvider(
                name="groq",
                api_key=groq_key,
                model="llama-3.3-70b-versatile",
                endpoint="https://api.groq.com/openai/v1/chat/completions",
                rate_limit_per_min=6,
            )
        )

    return providers


# v0.30.0: Providers sharing the same API key rate limit
_SHARED_RATE_GROUPS: dict[str, list[str]] = {
    "gemini": ["gemini_flash", "gemini_flash_lite"],
}


class LLMAdapter:
    """Multi-provider LLM adapter with automatic fallback chain.

    v0.30.0: Per-provider circuit breaker — each provider tracks its own
    failure state independently. Gemini Flash failing does NOT block Groq.
    v0.31.0: Provider preference per pipeline + time-based circuit breaker.
    """

    def __init__(
        self,
        providers: list[LLMProvider] | None = None,
        quota_manager: QuotaManager | None = None,
        prefer: str | None = None,
    ) -> None:
        self._providers = providers if providers is not None else _build_providers()
        self._quota = quota_manager or QuotaManager()
        self._last_provider: str = ""
        self._last_tokens: int = 0
        # v0.31.0: Time-based circuit breaker (timestamp of failure)
        self._provider_failed: dict[str, float] = {}

        # v0.31.0: Reorder providers to put preferred one first
        if prefer:
            preferred = [p for p in self._providers if p.name == prefer]
            others = [p for p in self._providers if p.name != prefer]
            self._providers = preferred + others
            if preferred:
                logger.info(f"Provider preference: {prefer} (first in chain)")

        if not self._providers:
            raise LLMError(
                "No LLM providers available — set GROQ_API_KEY or GEMINI_API_KEY",
                source="llm_adapter",
            )

    @property
    def last_provider(self) -> str:
        """Name of the last provider that successfully responded."""
        return self._last_provider

    @property
    def last_tokens_used(self) -> int:
        """Token count from last successful LLM call."""
        return self._last_tokens

    @property
    def circuit_open(self) -> bool:
        """True if ALL providers are marked as failed (within recovery window)."""
        now = time.monotonic()
        return all(
            (now - self._provider_failed.get(p.name, 0)) < _CIRCUIT_RECOVERY_SEC
            for p in self._providers
            if p.name in self._provider_failed
        ) and len(self._provider_failed) >= len(self._providers)

    def _get_available_providers(self) -> list[LLMProvider]:
        """Get providers whose circuit breaker has recovered.

        v0.31.0: Time-based recovery — provider is available again after
        _CIRCUIT_RECOVERY_SEC since last failure. Prevents wasting API calls
        on providers that JUST failed (e.g., Gemini 429 at 03:44, don't
        retry at 03:47 — wait until 03:49).
        """
        now = time.monotonic()
        available = []
        for p in self._providers:
            fail_time = self._provider_failed.get(p.name)
            if fail_time is None or (now - fail_time) >= _CIRCUIT_RECOVERY_SEC:
                available.append(p)

        if not available:
            # All providers failed within recovery window — try the one
            # that failed LONGEST ago (most likely to have recovered)
            oldest = min(
                self._providers,
                key=lambda p: self._provider_failed.get(p.name, 0),
            )
            logger.info(f"All providers in recovery — trying oldest failure: {oldest.name}")
            return [oldest]
        return available

    def suggest_cooldown(self) -> int:
        """Suggest cooldown seconds based on last provider and tokens used.

        v0.31.0: Adaptive cooldown — scales with actual token consumption
        and provider-specific TPM limits. Replaces fixed 60s cooldown.
        """
        if not self._last_provider:
            return 60

        tpm = _PROVIDER_TPM.get(self._last_provider, 6000)
        if self._last_tokens > 0:
            # cooldown = (tokens_used / tpm_limit) * 60s + 15s buffer
            cooldown = int(self._last_tokens / tpm * 60) + 15
            return max(15, min(cooldown, 180))  # clamp to 15-180s

        # Default per provider type
        if self._last_provider.startswith("gemini"):
            return 15  # Gemini has generous TPM
        return 60  # Groq needs more breathing room

    async def generate(
        self,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        system_prompt: str = "",
    ) -> LLMResponse:
        """Generate text using the fallback chain.

        v0.30.0: Per-provider circuit breaker — only skips providers that
        have individually failed. Other providers still get attempted.
        """
        available = self._get_available_providers()
        errors: list[str] = []

        for provider in available:
            # v0.30.0: Shared rate limit — wait for group, not just individual
            rate_key = provider.name
            for group, members in _SHARED_RATE_GROUPS.items():
                if provider.name in members:
                    rate_key = group
                    break
            try:
                await self._quota.wait_for_rate_limit(rate_key)

                if provider.name == "groq":
                    response = await _call_groq(
                        provider, prompt, max_tokens, temperature, system_prompt
                    )
                else:
                    response = await _call_gemini(
                        provider, prompt, max_tokens, temperature, system_prompt
                    )

                # Safety net: validate response is non-empty
                if not response.text.strip():
                    raise LLMError(
                        f"{provider.name} returned empty response",
                        source="llm_adapter",
                    )

                # Success — reset this provider's circuit breaker
                self._provider_failed.pop(provider.name, None)
                self._quota.track(rate_key)
                self._last_provider = provider.name
                self._last_tokens = response.tokens_used
                logger.info(f"LLM response from {provider.name} ({response.tokens_used} tokens)")
                return response

            except Exception as e:
                self._provider_failed[provider.name] = time.monotonic()
                self._quota.track_failure(rate_key)
                errors.append(f"{provider.name}: {e}")
                logger.warning(f"LLM {provider.name} failed: {e}")
                continue

        fallback_chain = " → ".join(p.name for p in available)
        raise LLMError(
            f"All LLM providers failed ({fallback_chain}): {'; '.join(errors)}",
            source="llm_adapter",
        )


async def _call_groq(
    provider: LLMProvider,
    prompt: str,
    max_tokens: int,
    temperature: float,
    system_prompt: str,
) -> LLMResponse:
    """Call Groq API (OpenAI-compatible format)."""
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": provider.model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            provider.endpoint,
            json=payload,
            headers={
                "Authorization": f"Bearer {provider.api_key}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()

    data = resp.json()
    choice = data.get("choices", [{}])[0]
    text = choice.get("message", {}).get("content", "")
    if not text.strip():
        raise LLMError("Groq returned empty text", source="llm_adapter")
    usage = data.get("usage", {})
    tokens = usage.get("total_tokens", 0)

    return LLMResponse(text=text, tokens_used=tokens, model=provider.model)


async def _call_gemini(
    provider: LLMProvider,
    prompt: str,
    max_tokens: int,
    temperature: float,
    system_prompt: str,
) -> LLMResponse:
    """Call Google Gemini API with proper system_instruction separation."""
    payload: dict = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": temperature,
        },
    }
    # Use dedicated system_instruction field — Gemini processes this BEFORE
    # user content, giving higher priority to NQ05 rules & behavioral constraints.
    if system_prompt:
        payload["system_instruction"] = {"parts": [{"text": system_prompt}]}

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            provider.endpoint,
            json=payload,
            params={"key": provider.api_key},
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()

    data = resp.json()
    candidates = data.get("candidates", [])
    if not candidates:
        block_reason = data.get("promptFeedback", {}).get("blockReason", "unknown")
        raise LLMError(
            f"Gemini returned no candidates (blockReason={block_reason})",
            source="llm_adapter",
        )
    parts = candidates[0].get("content", {}).get("parts", [])
    text = parts[0].get("text", "") if parts else ""
    if not text.strip():
        raise LLMError("Gemini returned empty text", source="llm_adapter")

    usage = data.get("usageMetadata", {})
    tokens = usage.get("totalTokenCount", 0)

    return LLMResponse(text=text, tokens_used=tokens, model=provider.model)
