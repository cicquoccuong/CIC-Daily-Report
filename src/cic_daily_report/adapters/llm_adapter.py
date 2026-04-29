"""Multi-LLM Adapter Pattern (QĐ2).

Chain: Gemini 2.5 Flash → Flash-Lite → Groq Qwen3 → Groq Llama 4 → Cerebras (gpt-oss-120b).
Unified interface: all providers return the same response format.
Automatic fallback when primary fails. Provider preference per pipeline.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field

import httpx

from cic_daily_report.core.error_handler import LLMError
from cic_daily_report.core.logger import get_logger
from cic_daily_report.core.quota_manager import QuotaManager

logger = get_logger("llm_adapter")

# PR#1 Emergency Fix: Hard wall-clock timeout per provider call.
# WHY 90s: Master Analysis took 84s in the last successful Gemini Flash-Lite run (#58).
# 90s gives a small headroom over that baseline while staying well below the
# 116-minute hang we observed on 5/8 recent runs (Google Gemini socket stall
# bug — googleapis/python-genai#1893 — httpx timeout=60 does NOT catch it because
# the socket stays open with no data). Per-tier dynamic timeouts will come in PR#3.
_PROVIDER_CALL_TIMEOUT_SEC = 90


class LLMTimeoutError(LLMError):
    """Raised when a provider call exceeds the hard wall-clock timeout.

    WHY separate subclass: downstream logic (generate()) must know this was a
    timeout (not a 4xx/5xx/auth error) so it can FALL BACK to the next provider
    rather than retry the same provider — retrying a hung Gemini socket just
    wastes another 90s per attempt. Subclassing LLMError keeps existing
    `except LLMError` catch-alls working unchanged.
    """

    def __init__(self, provider_name: str, timeout_sec: int) -> None:
        # retry=False: timed-out provider is probably stalled; fallback to next
        # chain entry, do not retry this one. LLMError defaults retry=True which
        # would cause callers checking `e.retry` to hammer the hung provider —
        # exactly the opposite of the fallback semantics this subclass exists for.
        super().__init__(
            f"{provider_name} timed out after {timeout_sec}s (hard wall-clock limit)",
            source="llm_adapter",
            retry=False,
        )
        self.provider_name = provider_name
        self.timeout_sec = timeout_sec


# v2.0 Đợt 2: Gemini API base URL — single source of truth for endpoint construction.
# WHY: Avoid repeating full URL in each provider. When Google changes API version,
# only this constant needs updating.
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

# v0.31.0: Provider-specific token-per-minute limits (output tokens).
# Used by suggest_cooldown() to calculate adaptive wait times.
_PROVIDER_TPM: dict[str, int] = {
    "gemini_flash": 32000,
    "gemini_flash_lite": 32000,
    "groq": 12000,  # Groq 2026: ~12K output TPM
    "groq_llama4": 12000,
    "cerebras": 50000,  # Cerebras: very generous TPM
}

# v0.31.0: Circuit breaker recovery time (seconds).
# Provider marked failed won't be retried until this time elapses.
_CIRCUIT_RECOVERY_SEC = 300  # 5 minutes


def _strip_think_tags(text: str) -> str:
    """Remove <think>...</think> reasoning blocks from LLM output.

    WHY: Qwen3-32B (Groq/Cerebras) emits <think> reasoning tags that
    leak to end users in BIC Chat. Strip them at adapter level so all
    downstream consumers get clean text.
    """
    # BUG-05: Iteratively strip innermost <think> tags until none remain.
    # WHY iterative: non-greedy regex .*? fails on nested <think> tags
    # (e.g., Qwen3 occasionally nests reasoning blocks).
    # [^<]* matches text without any '<', so it targets the INNERMOST tags
    # first. The while loop strips from inside out.
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"<think>[^<]*</think>", "", text, flags=re.DOTALL).strip()
    # Fallback: unclosed <think> tag (LLM ran out of tokens mid-thinking).
    # WHY: If LLM hits token limit inside a <think> block, the closing tag is
    # missing and the regex above won't match — internal reasoning leaks to users.
    if "<think>" in text:
        text = text[: text.index("<think>")].strip()
    return text


def _truncate_to_complete_sentence(text: str) -> str:
    """Truncate text to the last complete sentence boundary.

    WHY: When finish_reason=length, the LLM ran out of tokens mid-sentence.
    Cutting at the last sentence boundary gives readable text for BIC Chat.
    """
    # Find last sentence-ending punctuation followed by whitespace or at end of string.
    # We search for ALL matches and take the last one.
    # WHY negative lookbehind (?<!\d): The old regex [.!?](?:\s|\Z) matched "1." in
    # numbered lists (e.g., "1. Item"), truncating mid-list. (?<!\d) ensures periods
    # after digits (numbered list markers) are NOT treated as sentence boundaries.
    last_pos = -1
    for m in re.finditer(r"(?<!\d)[.!?](?:\s|\Z)", text):
        last_pos = m.start()
    if last_pos >= 0:
        # Include the punctuation character itself
        return text[: last_pos + 1].strip()
    # BUG-08: No sentence boundary — try last whitespace to avoid mid-word cut.
    # WHY: Returning text as-is means a word could be cut mid-way (e.g., "analy"),
    # which looks broken in BIC Chat. Truncating at last space + "..." is cleaner.
    last_space = text.rfind(" ")
    if last_space > 0:
        return text[:last_space].rstrip() + "..."
    return text


@dataclass
class LLMResponse:
    """Normalized response from any LLM provider."""

    text: str
    tokens_used: int
    model: str
    # P1.24: finish reason from provider ("stop", "length", etc.)
    finish_reason: str = field(default="")


@dataclass
class JudgeResult:
    """Wave 0.6 Story 0.6.2: Fact-checker verdict for generated content.

    WHY separate from LLMResponse: judge output is a structured verdict
    (approved/needs_revision/rejected + issues list) — distinct from raw
    text generation. Downstream pipeline branches on `verdict` to decide
    retry/ship/abort.

    Fields:
        verdict: "approved" (0 issues) | "needs_revision" (1-2 minor) |
                 "rejected" (3+ issues OR clear hallucination).
        issues: List of human-readable issue descriptions for logging/retry.
        confidence: Judge's self-reported confidence 0.0-1.0.
        model_used: Name of the provider that produced the verdict (for
                    metrics/debugging).
        raw_text: Original judge response (for debugging when JSON parse fails).
    """

    verdict: str
    issues: list[str] = field(default_factory=list)
    confidence: float = 0.0
    model_used: str = ""
    raw_text: str = ""


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

    # P1.18: Prefer DR-specific key for independent rate limits and billing
    # between CIC-Sentinel (GAS) and CIC-Daily-Report (Python).
    # WHY separate keys: a single shared key means quota exhaustion in one
    # project breaks the other. DR key isolates usage; falls back to shared.
    gemini_key = os.getenv("GEMINI_API_KEY_DR") or os.getenv("GEMINI_API_KEY", "")
    if gemini_key:
        # v0.30.0: Both Gemini models share 15 RPM total on same API key.
        # Use shared rate limiter group "gemini" with 7 RPM each (14 max combined,
        # leaving 1 RPM headroom). QuotaManager tracks "gemini" as shared group.
        # WHY local vars: model name used in both `model=` and endpoint URL.
        # Single variable eliminates risk of mismatch if model is updated.
        # MIGRATION NOTE (Đợt 3): When ready to switch to Gemini 3.x, change:
        #   _gemini_flash = "gemini-3-flash-preview"
        #   _gemini_flash_lite = "gemini-3-flash-preview"  (no lite variant yet)
        # Also check: temperature 0.05-0.1 may cause loops on Gemini 3 (VĐ7)
        # Also check: thinkingBudget → thinking_level if using thinking mode (VĐ8)
        # Also check: GEMINI_API_BASE may need v1beta → v1 if Google changes (VĐ3)
        _gemini_flash = "gemini-2.5-flash"
        providers.append(
            LLMProvider(
                name="gemini_flash",
                api_key=gemini_key,
                model=_gemini_flash,
                # v2.0 Đợt 2: Use GEMINI_API_BASE constant (was full hardcoded URL)
                endpoint=f"{GEMINI_API_BASE}/models/{_gemini_flash}:generateContent",
                rate_limit_per_min=7,
            )
        )
        _gemini_flash_lite = "gemini-2.5-flash-lite"
        providers.append(
            LLMProvider(
                name="gemini_flash_lite",
                api_key=gemini_key,
                model=_gemini_flash_lite,
                # v2.0 Đợt 2: Use GEMINI_API_BASE constant (was full hardcoded URL)
                endpoint=f"{GEMINI_API_BASE}/models/{_gemini_flash_lite}:generateContent",
                rate_limit_per_min=7,
            )
        )

    groq_key = os.getenv("GROQ_API_KEY", "")
    if groq_key:
        providers.append(
            LLMProvider(
                name="groq",
                api_key=groq_key,
                model="qwen/qwen3-32b",
                endpoint="https://api.groq.com/openai/v1/chat/completions",
                rate_limit_per_min=60,
            )
        )

    # Groq Llama 4 Scout — Vietnamese native, fast inference
    if groq_key:
        providers.append(
            LLMProvider(
                name="groq_llama4",
                api_key=groq_key,
                model="meta-llama/llama-4-scout-17b-16e-instruct",
                endpoint="https://api.groq.com/openai/v1/chat/completions",
                rate_limit_per_min=30,
            )
        )

    # Cerebras — final fallback, 1M tokens/day free
    cerebras_key = os.getenv("CEREBRAS_API_KEY", "")
    if cerebras_key:
        providers.append(
            LLMProvider(
                name="cerebras",
                api_key=cerebras_key,
                # v2.0 Đợt 1: qwen-3-32b deprecated → gpt-oss-120b (VĐ11)
                model="gpt-oss-120b",
                endpoint="https://api.cerebras.ai/v1/chat/completions",
                rate_limit_per_min=30,
            )
        )

    return providers


# v0.30.0: Providers sharing the same API key rate limit
_SHARED_RATE_GROUPS: dict[str, list[str]] = {
    "gemini": ["gemini_flash", "gemini_flash_lite"],
    "groq": ["groq", "groq_llama4"],
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
                "No LLM providers available — set GROQ_API_KEY"
                " or GEMINI_API_KEY_DR (or GEMINI_API_KEY)",
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
            # cooldown = (tokens_used / tpm_limit) * 60s + 5s buffer
            cooldown = int(self._last_tokens / tpm * 60) + 5
            return max(10, min(cooldown, 120))  # clamp to 10-120s

        # Default per provider type
        if self._last_provider.startswith("gemini"):
            return 10  # Gemini 2.5 has generous TPM
        if self._last_provider == "cerebras":
            return 10  # Cerebras also generous
        return 30  # Groq models

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

                if provider.name in ("groq", "groq_llama4", "cerebras"):
                    response = await _call_groq(
                        provider, prompt, max_tokens, temperature, system_prompt
                    )
                else:
                    response = await _call_gemini(
                        provider, prompt, max_tokens, temperature, system_prompt
                    )

                # P1.23: Strip <think> tags BEFORE any other processing.
                # WHY: Qwen3 may emit reasoning tags even when disabled;
                # defense-in-depth ensures clean text regardless.
                response.text = _strip_think_tags(response.text)

                # Safety net: validate response is non-empty
                if not response.text.strip():
                    raise LLMError(
                        f"{provider.name} returned empty response",
                        source="llm_adapter",
                    )

                # P1.24: Truncate to complete sentence if LLM ran out of tokens.
                # WHY: Cut-off mid-sentence text is unreadable for BIC Chat users.
                if response.finish_reason == "length":
                    original_len = len(response.text)
                    response.text = _truncate_to_complete_sentence(response.text)
                    logger.warning(
                        f"LLM response truncated (finish_reason=length): "
                        f"{original_len} → {len(response.text)} chars "
                        f"[{provider.name}]"
                    )

                # BUG-04: Handle content_filter (Gemini SAFETY/RECITATION).
                # WHY: Gemini may return partial text when content is filtered.
                # Truncate to last complete sentence like finish_reason=length.
                if response.finish_reason == "content_filter":
                    original_len = len(response.text)
                    response.text = _truncate_to_complete_sentence(response.text)
                    logger.warning(
                        f"LLM response filtered (finish_reason=content_filter): "
                        f"{original_len} → {len(response.text)} chars "
                        f"[{provider.name}]"
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
                # PR#1 Emergency Fix (F2): logger.exception() emits full traceback.
                # WHY: the old logger.warning(f"...: {e}") logged an EMPTY string
                # when `e` was httpx.RemoteProtocolError("") (Gemini socket stall
                # bug), hiding the real failure for 5 days. `{type(e).__name__}`
                # + `{e!r}` (repr) ensures the exception class name is always
                # visible even when str(e) is empty. logger.exception() also
                # writes the traceback so we can pinpoint where the stall happened.
                errors.append(f"{provider.name}: {type(e).__name__}: {e!r}")
                logger.exception(f"LLM {provider.name} failed ({type(e).__name__}): {e!r}")
                continue

        fallback_chain = " → ".join(p.name for p in available)
        raise LLMError(
            f"All LLM providers failed ({fallback_chain}): {'; '.join(errors)}",
            source="llm_adapter",
        )

    # ------------------------------------------------------------------
    # Wave 0.6 Story 0.6.2: Fact-checker (2nd LLM judge pass)
    # ------------------------------------------------------------------

    async def judge_factual_claims(
        self,
        content: str,
        source_text: str,
        historical_context: list[dict] | None = None,
    ) -> JudgeResult:
        """Verify factual claims in generated content using Cerebras Qwen3 235B.

        WHY separate model: judging requires DIFFERENT capabilities than
        generation (long-context comparison, structured JSON output, less
        creative). Cerebras Qwen3 235B is the documented Wave 0.6 choice
        (free 1M tokens/day quota — separate from generation chain).

        WHY graceful degradation: fact-checker MUST NOT block the pipeline
        — Cerebras 5xx/quota/timeout returns "approved" so message still
        ships. The judge is a SAFETY NET, not a gate. Caller decides what
        to do with the verdict.

        Args:
            content: LLM-generated text to verify (the bản tin).
            source_text: Raw article text the generator was given (ground truth).
            historical_context: RAG results [{"timestamp", "title", "btc_price",
                "source", ...}] used by generator. Empty list = no historical
                claims should appear in `content`.

        Returns:
            JudgeResult. On infrastructure failure → verdict="approved",
            confidence=0.0, issues=["judge_unavailable: ..."] so pipeline
            can proceed without surfacing it as a hallucination.
        """
        cerebras_key = os.getenv("CEREBRAS_API_KEY", "")
        if not cerebras_key:
            return JudgeResult(
                verdict="approved",
                issues=["judge_unavailable: CEREBRAS_API_KEY missing"],
                confidence=0.0,
                model_used="",
            )

        # WHY dedicated provider (not chain): the generation chain prefers
        # Gemini for cost; the judge MUST use Qwen3 235B for quality. Build
        # a one-shot provider rather than reordering the global chain.
        # Fallback model: gpt-oss-120b (already battle-tested in chain) if
        # Qwen3 235B 404s on Cerebras quota tier.
        judge_model = os.getenv("WAVE_0_6_JUDGE_MODEL", "qwen-3-235b-a22b-instruct-2507")
        judge_provider = LLMProvider(
            name="cerebras_judge",
            api_key=cerebras_key,
            model=judge_model,
            endpoint="https://api.cerebras.ai/v1/chat/completions",
            rate_limit_per_min=30,
        )

        rag_json = json.dumps(historical_context or [], ensure_ascii=False)

        # WHY strict JSON instruction: parser-friendly output. Qwen3 235B
        # follows JSON schema reliably when explicitly instructed.
        prompt = (
            "Bạn là fact-checker đọc bản tin crypto vừa được sinh ra. "
            "Verify mọi claim numerical/historical/quote.\n\n"
            "INPUT:\n"
            "<source_article>\n"
            f"{source_text}\n"
            "</source_article>\n\n"
            "<historical_context>\n"
            f"{rag_json}\n"
            "</historical_context>\n\n"
            "<generated_content>\n"
            f"{content}\n"
            "</generated_content>\n\n"
            "Soi GENERATED_CONTENT, list TẤT CẢ:\n"
            "1. Numerical claims (% change, $ amount, count, date) — "
            "verify có trong source/historical?\n"
            '2. Historical analogies ("Lần cuối X...") — match '
            "historical_context không?\n"
            "3. Quote attribution — có trong source không?\n\n"
            "Trả về JSON THUẦN (không markdown, không text khác):\n"
            '{"verdict": "approved" | "needs_revision" | "rejected", '
            '"issues": ["mô tả ngắn issue 1", ...], '
            '"confidence": 0.0-1.0}\n\n'
            "verdict rules:\n"
            "- approved: 0 issues\n"
            "- needs_revision: 1-2 issues minor\n"
            "- rejected: 3+ issues HOẶC có hallucination "
            "historical/numerical rõ ràng"
        )

        try:
            response = await _call_groq(
                judge_provider,
                prompt,
                max_tokens=1024,
                # WHY temperature=0.0: judge must be deterministic — same
                # input → same verdict. No creative interpretation.
                temperature=0.0,
                system_prompt="",
            )
        except Exception as e:
            # WHY approved on failure: judge is non-blocking safety net.
            # Pipeline should not be held hostage by Cerebras outage.
            logger.warning(f"Judge call failed ({type(e).__name__}: {e!r}) — defaulting approved")
            return JudgeResult(
                verdict="approved",
                issues=[f"judge_unavailable: {type(e).__name__}"],
                confidence=0.0,
                model_used=judge_provider.name,
            )

        raw = (response.text or "").strip()
        # Strip optional markdown json fences (some models add them despite
        # instructions)
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE).strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            # WHY approved on parse failure: same logic — non-blocking.
            # But surface the issue for ops dashboards.
            logger.warning(f"Judge returned non-JSON: {raw[:200]!r}")
            return JudgeResult(
                verdict="approved",
                issues=["judge_unavailable: malformed JSON response"],
                confidence=0.0,
                model_used=judge_provider.name,
                raw_text=raw,
            )

        # Wave 0.6.6 B3: judge sometimes returns valid JSON but non-object
        # (list `[]`, string, or null). Calling `.get()` on those → AttributeError
        # → uncaught → generate_breaking_content fails → critical event dropped.
        # Defend by treating any non-dict as "judge unavailable" → approved.
        if not isinstance(data, dict):
            logger.warning(f"Judge returned non-object JSON ({type(data).__name__}): {raw[:200]!r}")
            return JudgeResult(
                verdict="approved",
                issues=[f"judge_unavailable: non-object JSON ({type(data).__name__})"],
                confidence=0.0,
                model_used=judge_provider.name,
                raw_text=raw,
            )

        verdict = data.get("verdict", "approved")
        if verdict not in ("approved", "needs_revision", "rejected"):
            # WHY normalize to approved: unknown verdict = unsafe to block
            logger.warning(f"Judge returned unknown verdict: {verdict!r}")
            verdict = "approved"

        issues_raw = data.get("issues", [])
        # WHY str-coerce: defensive — model may return non-string entries
        if isinstance(issues_raw, list):
            issues = [str(x) for x in issues_raw if x is not None]
        else:
            issues = []

        confidence_raw = data.get("confidence", 0.0)
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = 0.0
        # Clamp 0-1
        confidence = max(0.0, min(1.0, confidence))

        return JudgeResult(
            verdict=verdict,
            issues=issues,
            confidence=confidence,
            model_used=judge_provider.name,
            raw_text=raw,
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

    payload: dict = {
        "model": provider.model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    # P1.23: Disable Qwen3 thinking mode via provider-specific API param.
    # WHY: Qwen3-32B defaults to thinking=enabled, which emits <think> tags.
    # Groq API expects `reasoning_effort: "none"` (NOT `thinking: {type: disabled}`).
    if "qwen" in provider.model.lower() and "groq" in provider.name.lower():
        payload["reasoning_effort"] = "none"

    # v2.0 Đợt 1 (VĐ14): Cerebras gpt-oss-120b is a reasoning model.
    # WHY: Unlike Qwen3, gpt-oss-120b does NOT use <think> tags — its reasoning
    # text is mixed directly into content. _strip_think_tags() cannot catch it.
    # Must disable reasoning at API level. Use disable_reasoning (explicit off)
    # + reasoning_format="hidden" (belt-and-suspenders safety).
    # See: https://inference-docs.cerebras.ai/capabilities/reasoning
    if provider.name == "cerebras" and "gpt-oss" in provider.model.lower():
        payload["disable_reasoning"] = True
        payload["reasoning_format"] = "hidden"

    # PR#1 Emergency Fix (F1): wrap the full HTTP call in asyncio.wait_for.
    # WHY asyncio.wait_for on top of httpx timeout=60: httpx's timeout only fires
    # when the socket is IDLE waiting for bytes; the Gemini stall bug keeps the
    # socket technically "active" (TLS keepalive) but never returns data. Only a
    # wall-clock asyncio.wait_for can forcibly cancel that task. Even though
    # _call_groq doesn't hit Gemini, we apply the same guard uniformly so ANY
    # provider that hangs is bounded. See googleapis/python-genai#1893.
    async def _do_request() -> httpx.Response:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                provider.endpoint,
                json=payload,
                headers={
                    "Authorization": f"Bearer {provider.api_key}",
                    "Content-Type": "application/json",
                },
            )
            r.raise_for_status()
            return r

    try:
        resp = await asyncio.wait_for(_do_request(), timeout=_PROVIDER_CALL_TIMEOUT_SEC)
    except asyncio.TimeoutError as exc:
        # Convert to LLMTimeoutError so generate()'s except block and downstream
        # callers can distinguish timeout-vs-other-error and skip to next provider.
        raise LLMTimeoutError(provider.name, _PROVIDER_CALL_TIMEOUT_SEC) from exc

    data = resp.json()
    choice = data.get("choices", [{}])[0]
    text = choice.get("message", {}).get("content", "")
    if not text.strip():
        raise LLMError("Groq returned empty text", source="llm_adapter")
    usage = data.get("usage", {})
    tokens = usage.get("total_tokens", 0)
    # P1.24: Parse finish_reason — "stop" (complete) or "length" (truncated)
    finish_reason = choice.get("finish_reason", "")

    return LLMResponse(
        text=text, tokens_used=tokens, model=provider.model, finish_reason=finish_reason
    )


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

    # PR#1 Emergency Fix (F1): wrap the full HTTP call in asyncio.wait_for.
    # WHY: this is the exact call that stalls per googleapis/python-genai#1893
    # (Gemini 2.5 Flash socket stall — httpx timeout=60 does not fire because
    # the socket stays open with no data). The wall-clock asyncio.wait_for
    # is the only layer guaranteed to cancel the hung task.
    async def _do_request() -> httpx.Response:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                provider.endpoint,
                json=payload,
                params={"key": provider.api_key},
                headers={"Content-Type": "application/json"},
            )
            r.raise_for_status()
            return r

    try:
        resp = await asyncio.wait_for(_do_request(), timeout=_PROVIDER_CALL_TIMEOUT_SEC)
    except asyncio.TimeoutError as exc:
        # Convert to LLMTimeoutError so outer fallback chain skips to next provider.
        raise LLMTimeoutError(provider.name, _PROVIDER_CALL_TIMEOUT_SEC) from exc

    data = resp.json()
    candidates = data.get("candidates", [])
    if not candidates:
        block_reason = data.get("promptFeedback", {}).get("blockReason", "unknown")
        raise LLMError(
            f"Gemini returned no candidates (blockReason={block_reason})",
            source="llm_adapter",
        )
    parts = candidates[0].get("content", {}).get("parts", [])
    # v2.0 Đợt 1 (VĐ2): Filter thinking parts (defense-in-depth for Gemini 3.x upgrade).
    # WHY: Gemini 3.x may return parts with "thought": true when thinking is enabled.
    # We pick the first non-thought part; fallback to last part if all are thoughts.
    answer_part = next((p for p in parts if not p.get("thought")), parts[-1] if parts else {})
    text = answer_part.get("text", "")
    if not text.strip():
        raise LLMError("Gemini returned empty text", source="llm_adapter")

    usage = data.get("usageMetadata", {})
    tokens = usage.get("totalTokenCount", 0)

    # P1.24: Map Gemini finish reason to normalized values.
    # WHY: Gemini uses "MAX_TOKENS"/"STOP" vs Groq's "length"/"stop".
    # Normalize so generate() can handle both uniformly.
    # WHY SAFETY/RECITATION → content_filter: Gemini returns these when output
    # is blocked for policy violations. Must handle like "length" (truncated).
    _gemini_reason_map = {
        "MAX_TOKENS": "length",
        "STOP": "stop",
        "SAFETY": "content_filter",
        "RECITATION": "content_filter",
    }
    raw_reason = candidates[0].get("finishReason", "")
    finish_reason = _gemini_reason_map.get(raw_reason, raw_reason.lower())

    return LLMResponse(
        text=text, tokens_used=tokens, model=provider.model, finish_reason=finish_reason
    )
