"""Tests for Wave 0.6 Story 0.6.2 — RAG inject + Cerebras Qwen3 fact-checker.

Covers:
- RAG inject path (flag on/off, hit/miss, fallback safe behavior)
- Judge pass (approved / needs_revision / rejected)
- Retry logic (rejected once → retry → ship; rejected twice → raise)
- Severity gating (judge only critical/important)
- Cerebras failures (missing key, network exception, malformed JSON, unknown verdict)
- Confidence clamp + JSON parsing (markdown fence)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cic_daily_report.adapters.llm_adapter import (
    JudgeResult,
    LLMAdapter,
    LLMProvider,
    LLMResponse,
)
from cic_daily_report.breaking.content_generator import (
    _get_historical_context,
    generate_breaking_content,
)
from cic_daily_report.breaking.event_detector import BreakingEvent
from cic_daily_report.core.error_handler import LLMError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _event(title: str = "Major exchange hack", summary: str = "") -> BreakingEvent:
    return BreakingEvent(
        title=title,
        source="CoinDesk",
        url="https://coindesk.com/x",
        panic_score=85,
        raw_data={"summary": summary} if summary else {},
    )


def _mock_llm(text: str = "Tin nóng: tài sản mã hóa bị hack 100 triệu USD."):
    """Mock LLMAdapter — generate() + judge_factual_claims()."""
    mock = AsyncMock()
    mock.generate = AsyncMock(
        return_value=LLMResponse(text=text, tokens_used=100, model="test-model")
    )
    mock.judge_factual_claims = AsyncMock(
        return_value=JudgeResult(verdict="approved", confidence=0.9)
    )
    mock.last_provider = "groq"
    return mock


@pytest.fixture
def wave06_on(monkeypatch):
    """Enable Wave 0.6 feature flag for the test."""
    monkeypatch.setenv("WAVE_0_6_ENABLED", "1")
    yield


@pytest.fixture
def wave06_off(monkeypatch):
    """Disable Wave 0.6 feature flag (default)."""
    monkeypatch.delenv("WAVE_0_6_ENABLED", raising=False)
    yield


# ---------------------------------------------------------------------------
# 1. RAG inject behaviour
# ---------------------------------------------------------------------------


class TestRagInject:
    async def test_rag_inject_with_results(self, wave06_on):
        """Flag ON + RAG returns 3 events → prompt contains <historical_events>."""
        fake_results = [
            {
                "timestamp": "2025-11-01T10:00:00+00:00",
                "title": "FTX collapse aftermath",
                "btc_price": 32000.0,
                "score": 1.5,
                "source": "Reuters",
            },
            {
                "timestamp": "2025-12-15T08:00:00+00:00",
                "title": "Binance regulatory action",
                "btc_price": 41000.0,
                "score": 1.2,
                "source": "Bloomberg",
            },
        ]
        mock_idx = MagicMock()
        mock_idx.query.return_value = fake_results

        with patch(
            "cic_daily_report.breaking.rag_index.get_or_build_index",
            return_value=mock_idx,
        ):
            llm = _mock_llm()
            await generate_breaking_content(_event(), llm, severity="critical")
        prompt = llm.generate.call_args.kwargs["prompt"]
        assert "<historical_events>" in prompt
        assert "FTX collapse aftermath" in prompt
        assert "$32,000" in prompt or "32000" in prompt
        # Constraint instruction must appear
        assert "KHÔNG TỰ BỊA" in prompt

    async def test_rag_inject_no_results(self, wave06_on):
        """Flag ON + RAG empty → instruct LLM 'KHÔNG viết tham chiếu lịch sử'."""
        mock_idx = MagicMock()
        mock_idx.query.return_value = []
        with patch(
            "cic_daily_report.breaking.rag_index.get_or_build_index",
            return_value=mock_idx,
        ):
            llm = _mock_llm()
            await generate_breaking_content(_event(), llm)
        prompt = llm.generate.call_args.kwargs["prompt"]
        assert "<historical_events>" not in prompt
        assert "KHÔNG viết tham chiếu lịch sử" in prompt

    async def test_rag_inject_disabled_flag(self, wave06_off):
        """Flag OFF → never query RAG, instruct no-history."""
        with patch("cic_daily_report.breaking.rag_index.get_or_build_index") as mock_get:
            llm = _mock_llm()
            await generate_breaking_content(_event(), llm)
        # RAG NEVER called
        mock_get.assert_not_called()
        prompt = llm.generate.call_args.kwargs["prompt"]
        assert "KHÔNG viết tham chiếu lịch sử" in prompt

    async def test_rag_query_failure_graceful(self, wave06_on):
        """RAG raises (sheets down/sqlite corrupt) → fallback empty, no crash."""
        with patch(
            "cic_daily_report.breaking.rag_index.get_or_build_index",
            side_effect=RuntimeError("sheets down"),
        ):
            llm = _mock_llm()
            result = await generate_breaking_content(_event(), llm)
        assert result.ai_generated
        prompt = llm.generate.call_args.kwargs["prompt"]
        # Falls back to no-history instruction
        assert "KHÔNG viết tham chiếu lịch sử" in prompt

    async def test_rag_self_reference_filter_param(self, wave06_on):
        """RAG.query MUST exclude recent (24h) AND exclude current URL.

        Wave 0.8.4 F4: bumped from 1.0 → 24.0 hours after Bug 4 (01/05)
        where Wasabi tin self-cited the same batch event as 'lịch sử'.
        Plus exclude_url passes the current event URL for belt-and-suspenders.
        """
        mock_idx = MagicMock()
        mock_idx.query.return_value = []
        with patch(
            "cic_daily_report.breaking.rag_index.get_or_build_index",
            return_value=mock_idx,
        ):
            llm = _mock_llm()
            await generate_breaking_content(_event(), llm)
        kwargs = mock_idx.query.call_args.kwargs
        assert kwargs.get("exclude_recent_hours") == 24.0
        # exclude_url must be passed (not None) for the test event URL
        assert kwargs.get("exclude_url") == _event().url


# ---------------------------------------------------------------------------
# 2. Judge pass — verdict handling
# ---------------------------------------------------------------------------


class TestJudgePass:
    async def test_judge_approved_ships_content(self, wave06_on):
        """Judge approved → content ships untouched."""
        with patch("cic_daily_report.breaking.rag_index.get_or_build_index") as mock_get:
            mock_get.return_value.query.return_value = []
            llm = _mock_llm()
            llm.judge_factual_claims = AsyncMock(
                return_value=JudgeResult(verdict="approved", confidence=0.95)
            )
            result = await generate_breaking_content(_event(), llm, severity="critical")
        assert result.ai_generated
        # Only ONE generate call (no retry)
        assert llm.generate.call_count == 1
        assert llm.judge_factual_claims.call_count == 1

    async def test_judge_needs_revision_ships_with_warning(self, wave06_on, caplog):
        """Judge needs_revision → ship + log warning, no retry."""
        with patch("cic_daily_report.breaking.rag_index.get_or_build_index") as mock_get:
            mock_get.return_value.query.return_value = []
            llm = _mock_llm()
            llm.judge_factual_claims = AsyncMock(
                return_value=JudgeResult(
                    verdict="needs_revision",
                    issues=["claim X chưa rõ"],
                    confidence=0.6,
                )
            )
            result = await generate_breaking_content(_event(), llm, severity="important")
        assert result.ai_generated
        assert llm.generate.call_count == 1  # no retry

    async def test_judge_rejected_then_approved_on_retry(self, wave06_on):
        """1st rejected → retry → 2nd approved → ship retry content.

        Wave 0.8.4 F1: retry must produce >= 80 words; otherwise hard gate
        triggers. Bumped fixture text to 100+ words to clear the gate.
        """
        # 110-word mock text — clears Wave 0.8.4 F1 gate (>= 80)
        long_text = (
            "Tin nóng: tài sản mã hóa bị hack 100 triệu USD trên sàn lớn. "
            "Hacker đã khai thác lỗ hổng oracle để rút tiền từ pool thanh khoản. "
            "Sự kiện diễn ra trong vòng 30 phút và ảnh hưởng đến hàng nghìn người dùng. "
            "Đội ngũ bảo mật đang điều tra nguyên nhân và truy vết hacker qua on-chain. "
            "Với cộng đồng CIC, đây là lời nhắc về rủi ro DeFi và tầm quan trọng của bảo mật. "
            "Người dùng nên kiểm tra lại các vị thế và chuyển tài sản sang ví lạnh nếu cần. "
            "Sàn cam kết bồi thường thiệt hại theo chính sách bảo hiểm hiện hành."
        )
        with patch("cic_daily_report.breaking.rag_index.get_or_build_index") as mock_get:
            mock_get.return_value.query.return_value = []
            llm = _mock_llm(text=long_text)
            llm.judge_factual_claims = AsyncMock(
                side_effect=[
                    JudgeResult(verdict="rejected", issues=["bịa $6B Poly"]),
                    JudgeResult(verdict="approved", confidence=0.9),
                ]
            )
            result = await generate_breaking_content(_event(), llm, severity="critical")
        assert result.ai_generated
        assert llm.generate.call_count == 2  # original + retry
        assert llm.judge_factual_claims.call_count == 2
        # Retry prompt MUST contain the rejection reason
        retry_prompt = llm.generate.call_args_list[1].kwargs["prompt"]
        assert "LẦN TRƯỚC bị reject" in retry_prompt
        assert "bịa $6B Poly" in retry_prompt

    async def test_judge_rejected_twice_raises_llmerror(self, wave06_on):
        """Both passes rejected → raise LLMError so pipeline marks failed."""
        with patch("cic_daily_report.breaking.rag_index.get_or_build_index") as mock_get:
            mock_get.return_value.query.return_value = []
            llm = _mock_llm()
            llm.judge_factual_claims = AsyncMock(
                return_value=JudgeResult(
                    verdict="rejected",
                    issues=["bịa số 1", "bịa số 2", "bịa quote"],
                )
            )
            with pytest.raises(LLMError) as exc_info:
                await generate_breaking_content(_event(), llm, severity="critical")
        assert "Fact-check rejected" in str(exc_info.value)
        assert llm.generate.call_count == 2  # original + 1 retry only

    async def test_judge_skips_notable_severity(self, wave06_on):
        """Severity=notable → judge SKIPPED (only critical/important fact-checked)."""
        with patch("cic_daily_report.breaking.rag_index.get_or_build_index") as mock_get:
            mock_get.return_value.query.return_value = []
            llm = _mock_llm()
            await generate_breaking_content(_event(), llm, severity="notable")
        # Judge NEVER called for notable
        assert llm.judge_factual_claims.call_count == 0

    async def test_judge_skipped_when_flag_off(self, wave06_off):
        """Flag OFF → judge never called even for critical."""
        llm = _mock_llm()
        await generate_breaking_content(_event(), llm, severity="critical")
        assert llm.judge_factual_claims.call_count == 0

    async def test_judge_called_for_important_severity(self, wave06_on):
        """Severity=important → judge IS called."""
        with patch("cic_daily_report.breaking.rag_index.get_or_build_index") as mock_get:
            mock_get.return_value.query.return_value = []
            llm = _mock_llm()
            await generate_breaking_content(_event(), llm, severity="important")
        assert llm.judge_factual_claims.call_count == 1


# ---------------------------------------------------------------------------
# 3. JudgeResult dataclass + judge_factual_claims behaviour
# ---------------------------------------------------------------------------


class TestJudgeResultDataclass:
    def test_default_fields(self):
        r = JudgeResult(verdict="approved")
        assert r.verdict == "approved"
        assert r.issues == []
        assert r.confidence == 0.0
        assert r.model_used == ""
        assert r.raw_text == ""

    def test_full_construction(self):
        r = JudgeResult(
            verdict="rejected",
            issues=["bịa số"],
            confidence=0.85,
            model_used="cerebras_judge",
            raw_text='{"verdict":"rejected"}',
        )
        assert r.verdict == "rejected"
        assert r.issues == ["bịa số"]
        assert r.confidence == 0.85


class TestJudgeFactualClaims:
    async def test_no_cerebras_key_returns_approved(self, monkeypatch):
        """Missing CEREBRAS_API_KEY → graceful approved (non-blocking)."""
        monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
        # Build adapter with a single dummy provider (won't be called)
        adapter = LLMAdapter(
            providers=[
                LLMProvider(
                    name="dummy",
                    api_key="x",
                    model="m",
                    endpoint="http://local",
                    rate_limit_per_min=1,
                )
            ]
        )
        result = await adapter.judge_factual_claims("content", "source", [])
        assert result.verdict == "approved"
        assert any("judge_unavailable" in i for i in result.issues)
        assert result.confidence == 0.0

    async def test_judge_parses_clean_json(self, monkeypatch):
        """Clean JSON response → parsed correctly."""
        monkeypatch.setenv("CEREBRAS_API_KEY", "fake")
        adapter = LLMAdapter(
            providers=[
                LLMProvider(
                    name="dummy",
                    api_key="x",
                    model="m",
                    endpoint="http://local",
                    rate_limit_per_min=1,
                )
            ]
        )
        fake_response = LLMResponse(
            text=json.dumps(
                {
                    "verdict": "needs_revision",
                    "issues": ["thiếu nguồn quote"],
                    "confidence": 0.7,
                }
            ),
            tokens_used=50,
            model="qwen",
        )
        with patch(
            "cic_daily_report.adapters.llm_adapter._call_groq",
            return_value=fake_response,
        ):
            result = await adapter.judge_factual_claims("content", "source", [])
        assert result.verdict == "needs_revision"
        assert result.issues == ["thiếu nguồn quote"]
        assert result.confidence == 0.7

    async def test_judge_strips_markdown_fence(self, monkeypatch):
        """Response wrapped in ```json fences → still parsed."""
        monkeypatch.setenv("CEREBRAS_API_KEY", "fake")
        adapter = LLMAdapter(
            providers=[
                LLMProvider(
                    name="dummy",
                    api_key="x",
                    model="m",
                    endpoint="http://local",
                    rate_limit_per_min=1,
                )
            ]
        )
        fake_response = LLMResponse(
            text='```json\n{"verdict":"approved","issues":[],"confidence":1.0}\n```',
            tokens_used=20,
            model="qwen",
        )
        with patch(
            "cic_daily_report.adapters.llm_adapter._call_groq",
            return_value=fake_response,
        ):
            result = await adapter.judge_factual_claims("c", "s", [])
        assert result.verdict == "approved"
        assert result.confidence == 1.0

    async def test_judge_malformed_json_returns_approved(self, monkeypatch):
        """Garbage response → approved + 'judge_unavailable' issue."""
        monkeypatch.setenv("CEREBRAS_API_KEY", "fake")
        adapter = LLMAdapter(
            providers=[
                LLMProvider(
                    name="dummy",
                    api_key="x",
                    model="m",
                    endpoint="http://local",
                    rate_limit_per_min=1,
                )
            ]
        )
        with patch(
            "cic_daily_report.adapters.llm_adapter._call_groq",
            return_value=LLMResponse(text="not json at all", tokens_used=5, model="qwen"),
        ):
            result = await adapter.judge_factual_claims("c", "s", [])
        assert result.verdict == "approved"
        assert any("malformed" in i for i in result.issues)

    async def test_judge_network_failure_returns_approved(self, monkeypatch):
        """_call_groq raises → graceful approved (judge non-blocking)."""
        monkeypatch.setenv("CEREBRAS_API_KEY", "fake")
        adapter = LLMAdapter(
            providers=[
                LLMProvider(
                    name="dummy",
                    api_key="x",
                    model="m",
                    endpoint="http://local",
                    rate_limit_per_min=1,
                )
            ]
        )
        with patch(
            "cic_daily_report.adapters.llm_adapter._call_groq",
            side_effect=RuntimeError("429 quota"),
        ):
            result = await adapter.judge_factual_claims("c", "s", [])
        assert result.verdict == "approved"
        assert any("RuntimeError" in i for i in result.issues)
        assert result.confidence == 0.0

    async def test_judge_unknown_verdict_normalized_to_approved(self, monkeypatch):
        """Verdict outside enum → defaults to approved (safe fallback)."""
        monkeypatch.setenv("CEREBRAS_API_KEY", "fake")
        adapter = LLMAdapter(
            providers=[
                LLMProvider(
                    name="dummy",
                    api_key="x",
                    model="m",
                    endpoint="http://local",
                    rate_limit_per_min=1,
                )
            ]
        )
        fake_response = LLMResponse(
            text='{"verdict":"WTF_HALT","issues":[],"confidence":0.5}',
            tokens_used=10,
            model="qwen",
        )
        with patch(
            "cic_daily_report.adapters.llm_adapter._call_groq",
            return_value=fake_response,
        ):
            result = await adapter.judge_factual_claims("c", "s", [])
        assert result.verdict == "approved"

    async def test_judge_confidence_clamped(self, monkeypatch):
        """Out-of-range confidence (5.0) clamped to [0,1]."""
        monkeypatch.setenv("CEREBRAS_API_KEY", "fake")
        adapter = LLMAdapter(
            providers=[
                LLMProvider(
                    name="dummy",
                    api_key="x",
                    model="m",
                    endpoint="http://local",
                    rate_limit_per_min=1,
                )
            ]
        )
        fake_response = LLMResponse(
            text='{"verdict":"approved","issues":[],"confidence":5.0}',
            tokens_used=10,
            model="qwen",
        )
        with patch(
            "cic_daily_report.adapters.llm_adapter._call_groq",
            return_value=fake_response,
        ):
            result = await adapter.judge_factual_claims("c", "s", [])
        assert result.confidence == 1.0

    async def test_judge_passes_historical_to_prompt(self, monkeypatch):
        """historical_context should be JSON-encoded and visible in judge prompt."""
        monkeypatch.setenv("CEREBRAS_API_KEY", "fake")
        adapter = LLMAdapter(
            providers=[
                LLMProvider(
                    name="dummy",
                    api_key="x",
                    model="m",
                    endpoint="http://local",
                    rate_limit_per_min=1,
                )
            ]
        )
        captured = {}

        async def _fake(provider, prompt, *args, **kwargs):
            captured["prompt"] = prompt
            return LLMResponse(
                text='{"verdict":"approved","issues":[],"confidence":1.0}',
                tokens_used=5,
                model="x",
            )

        with patch(
            "cic_daily_report.adapters.llm_adapter._call_groq",
            side_effect=_fake,
        ):
            await adapter.judge_factual_claims(
                "generated text",
                "raw article body",
                [{"title": "Past event A", "btc_price": 30000}],
            )
        prompt = captured["prompt"]
        assert "raw article body" in prompt
        assert "generated text" in prompt
        assert "Past event A" in prompt


# ---------------------------------------------------------------------------
# 4. _get_historical_context helper unit tests
# ---------------------------------------------------------------------------


class TestGetHistoricalContext:
    def test_flag_off_returns_empty(self, wave06_off):
        ctx, results = _get_historical_context(_event())
        assert ctx == ""
        assert results == []

    def test_flag_on_no_results(self, wave06_on):
        mock_idx = MagicMock()
        mock_idx.query.return_value = []
        with patch(
            "cic_daily_report.breaking.rag_index.get_or_build_index",
            return_value=mock_idx,
        ):
            ctx, results = _get_historical_context(_event())
        assert ctx == ""
        assert results == []

    def test_flag_on_with_results(self, wave06_on):
        mock_idx = MagicMock()
        mock_idx.query.return_value = [
            {
                "timestamp": "2025-10-01T00:00:00+00:00",
                "title": "Old event",
                "btc_price": 50000.0,
                "score": 0.9,
                "source": "Reuters",
            }
        ]
        with patch(
            "cic_daily_report.breaking.rag_index.get_or_build_index",
            return_value=mock_idx,
        ):
            ctx, results = _get_historical_context(_event())
        assert "<historical_events>" in ctx
        assert "Old event" in ctx
        assert "$50,000" in ctx
        assert len(results) == 1
