"""Multi-LLM Adapter Pattern (QĐ2) — Groq → Gemini Flash → Gemini Flash Lite.

Unified interface: all providers return the same response format.
Automatic fallback when primary fails.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from cic_daily_report.core.error_handler import LLMError
from cic_daily_report.core.logger import get_logger
from cic_daily_report.core.quota_manager import QuotaManager

logger = get_logger("llm_adapter")


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
    """Build provider list from env vars. Skip providers with missing keys."""
    providers: list[LLMProvider] = []

    groq_key = os.getenv("GROQ_API_KEY", "")
    if groq_key:
        providers.append(
            LLMProvider(
                name="groq",
                api_key=groq_key,
                model="llama-3.3-70b-versatile",
                endpoint="https://api.groq.com/openai/v1/chat/completions",
                rate_limit_per_min=30,
            )
        )

    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if gemini_key:
        providers.append(
            LLMProvider(
                name="gemini_flash",
                api_key=gemini_key,
                model="gemini-2.0-flash",
                endpoint="https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
                rate_limit_per_min=15,
            )
        )
        providers.append(
            LLMProvider(
                name="gemini_flash_lite",
                api_key=gemini_key,
                model="gemini-2.0-flash-lite",
                endpoint="https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-lite:generateContent",
                rate_limit_per_min=15,
            )
        )

    return providers


class LLMAdapter:
    """Multi-provider LLM adapter with automatic fallback chain."""

    def __init__(
        self,
        providers: list[LLMProvider] | None = None,
        quota_manager: QuotaManager | None = None,
    ) -> None:
        self._providers = providers if providers is not None else _build_providers()
        self._quota = quota_manager or QuotaManager()
        self._last_provider: str = ""

        if not self._providers:
            raise LLMError(
                "No LLM providers available — set GROQ_API_KEY or GEMINI_API_KEY",
                source="llm_adapter",
            )

    @property
    def last_provider(self) -> str:
        """Name of the last provider that successfully responded."""
        return self._last_provider

    async def generate(
        self,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        system_prompt: str = "",
    ) -> LLMResponse:
        """Generate text using the fallback chain.

        Tries each provider in order. Returns on first success.
        """
        errors: list[str] = []

        for provider in self._providers:
            try:
                await self._quota.wait_for_rate_limit(provider.name)

                if provider.name == "groq":
                    response = await _call_groq(
                        provider, prompt, max_tokens, temperature, system_prompt
                    )
                else:
                    response = await _call_gemini(
                        provider, prompt, max_tokens, temperature, system_prompt
                    )

                self._quota.track(provider.name)
                self._last_provider = provider.name
                logger.info(f"LLM response from {provider.name} ({response.tokens_used} tokens)")
                return response

            except Exception as e:
                errors.append(f"{provider.name}: {e}")
                logger.warning(f"LLM {provider.name} failed: {e}")
                continue

        fallback_chain = " → ".join(p.name for p in self._providers)
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
    """Call Google Gemini API."""
    full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt

    payload = {
        "contents": [{"parts": [{"text": full_prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": temperature,
        },
    }

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
