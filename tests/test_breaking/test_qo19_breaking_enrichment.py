"""Tests for QO.19 — Breaking enrichment: consensus snapshot + historical parallel.

The breaking prompt includes consensus data when available, and asks LLM
to reference historical parallels for critical/important events.
"""

from unittest.mock import AsyncMock, patch

from cic_daily_report.adapters.llm_adapter import LLMResponse
from cic_daily_report.breaking.content_generator import (
    BREAKING_PROMPT_TEMPLATE,
    generate_breaking_content,
)
from cic_daily_report.breaking.event_detector import BreakingEvent


def _event():
    return BreakingEvent(
        title="Fed raises rates by 75 bps",
        source="Reuters",
        url="https://reuters.com/fed",
        panic_score=85,
    )


def _mock_llm(text="Tin nóng: sự kiện tài sản mã hóa quan trọng."):
    mock = AsyncMock()
    mock.generate = AsyncMock(
        return_value=LLMResponse(text=text, tokens_used=100, model="test-model")
    )
    mock.last_provider = "groq"
    return mock


# ============================================================================
# BREAKING_PROMPT_TEMPLATE — structure
# ============================================================================


class TestBreakingPromptTemplate:
    """QO.19: Template includes consensus and historical placeholders."""

    def test_template_has_consensus_section(self):
        """Template must have {consensus_section} placeholder."""
        assert "{consensus_section}" in BREAKING_PROMPT_TEMPLATE

    def test_template_has_historical_instruction(self):
        """Template must have {historical_instruction} placeholder."""
        assert "{historical_instruction}" in BREAKING_PROMPT_TEMPLATE

    def test_template_still_has_market_context(self):
        """Existing {market_context} placeholder preserved."""
        assert "{market_context}" in BREAKING_PROMPT_TEMPLATE

    def test_template_still_has_recent_events(self):
        """Existing {recent_events} placeholder preserved."""
        assert "{recent_events}" in BREAKING_PROMPT_TEMPLATE


# ============================================================================
# generate_breaking_content — consensus_snapshot parameter
# ============================================================================


class TestConsensusInPrompt:
    """QO.19: Consensus snapshot injected into breaking prompt."""

    async def test_consensus_included_when_provided(self):
        """consensus_snapshot → appears in the LLM prompt."""
        llm = _mock_llm()
        consensus = "BTC: BULLISH (score +0.45, 3 nguồn, bullish 70%)"
        await generate_breaking_content(
            _event(), llm, severity="critical", consensus_snapshot=consensus
        )
        call_kwargs = llm.generate.call_args
        prompt = call_kwargs.kwargs.get("prompt", "") or call_kwargs.args[0]
        assert "Đồng thuận thị trường hiện tại" in prompt
        assert "BTC: BULLISH" in prompt
        assert "+0.45" in prompt

    async def test_consensus_omitted_when_empty(self):
        """Empty consensus_snapshot → no consensus section in prompt."""
        llm = _mock_llm()
        await generate_breaking_content(_event(), llm, consensus_snapshot="")
        call_kwargs = llm.generate.call_args
        prompt = call_kwargs.kwargs.get("prompt", "") or call_kwargs.args[0]
        assert "Đồng thuận thị trường hiện tại" not in prompt

    async def test_consensus_omitted_when_whitespace(self):
        """Whitespace-only consensus_snapshot → no consensus section."""
        llm = _mock_llm()
        await generate_breaking_content(_event(), llm, consensus_snapshot="   ")
        call_kwargs = llm.generate.call_args
        prompt = call_kwargs.kwargs.get("prompt", "") or call_kwargs.args[0]
        assert "Đồng thuận thị trường hiện tại" not in prompt

    async def test_consensus_default_is_empty(self):
        """Default consensus_snapshot is empty string."""
        llm = _mock_llm()
        await generate_breaking_content(_event(), llm)
        call_kwargs = llm.generate.call_args
        prompt = call_kwargs.kwargs.get("prompt", "") or call_kwargs.args[0]
        assert "Đồng thuận thị trường hiện tại" not in prompt

    async def test_does_not_fail_without_consensus(self):
        """No consensus data → should still generate content successfully."""
        llm = _mock_llm()
        result = await generate_breaking_content(_event(), llm, consensus_snapshot="")
        assert result.ai_generated is True
        assert result.word_count > 0


# ============================================================================
# Historical parallel instruction
# ============================================================================


class TestHistoricalParallel:
    """Wave 0.5 (alpha.18): historical parallel instruction REMOVED — see content_generator.py.

    Audit 27-28/04/2026 found 87.5% of LLM-generated historical claims were
    fabricated. Tests below now assert the absence of the instruction across
    all severities. Re-enable in Wave 0.6+ once a RAG/historical DB is wired.
    """

    async def test_critical_no_historical_instruction(self):
        """Wave 0.5: Critical events → NO historical instruction (LLM hallucinates without RAG)."""
        llm = _mock_llm()
        await generate_breaking_content(_event(), llm, severity="critical")
        call_kwargs = llm.generate.call_args
        prompt = call_kwargs.kwargs.get("prompt", "") or call_kwargs.args[0]
        assert "THAM CHIẾU LỊCH SỬ" not in prompt

    async def test_important_no_historical_instruction(self):
        """Wave 0.5: Important events → NO historical instruction (LLM hallucinates without RAG)."""
        llm = _mock_llm()
        await generate_breaking_content(_event(), llm, severity="important")
        call_kwargs = llm.generate.call_args
        prompt = call_kwargs.kwargs.get("prompt", "") or call_kwargs.args[0]
        assert "THAM CHIẾU LỊCH SỬ" not in prompt

    async def test_notable_no_historical_instruction(self):
        """Notable events → NO historical parallel (consistent with all severities now)."""
        llm = _mock_llm()
        await generate_breaking_content(_event(), llm, severity="notable")
        call_kwargs = llm.generate.call_args
        prompt = call_kwargs.kwargs.get("prompt", "") or call_kwargs.args[0]
        assert "THAM CHIẾU LỊCH SỬ" not in prompt

    async def test_no_hardcoded_fed_example_in_prompt(self):
        """Wave 0.5 SMOKING GUN: prompt MUST NOT contain the historical INSTRUCTION
        example. Note: source title may legit contain '75 bps' if the news is
        about the Fed — what we assert is that the *prompt instruction* no longer
        teaches the LLM to clone the template "(date) → BTC -X% in Yh"."""
        llm = _mock_llm()
        await generate_breaking_content(_event(), llm, severity="critical")
        call_kwargs = llm.generate.call_args
        prompt = call_kwargs.kwargs.get("prompt", "") or call_kwargs.args[0]
        # These exact phrases were the instruction template — must be gone.
        assert "06/2022" not in prompt
        assert "BTC giảm 15% trong 48h" not in prompt
        assert "Lần cuối Fed tăng lãi suất" not in prompt


# ============================================================================
# Combined: consensus + historical
# ============================================================================


class TestCombinedEnrichment:
    """QO.19: Both consensus and historical parallel can coexist."""

    async def test_both_consensus_and_historical(self):
        """Wave 0.5: Critical event + consensus → consensus appears, historical REMOVED."""
        llm = _mock_llm()
        consensus = "BTC: NEUTRAL (score +0.05, 4 nguồn)"
        await generate_breaking_content(
            _event(), llm, severity="critical", consensus_snapshot=consensus
        )
        call_kwargs = llm.generate.call_args
        prompt = call_kwargs.kwargs.get("prompt", "") or call_kwargs.args[0]
        assert "Đồng thuận thị trường hiện tại" in prompt
        assert "THAM CHIẾU LỊCH SỬ" not in prompt  # Wave 0.5: removed
        assert "BTC: NEUTRAL" in prompt

    async def test_consensus_without_historical_for_notable(self):
        """Notable event + consensus → consensus yes, historical no."""
        llm = _mock_llm()
        consensus = "ETH: BEARISH (score -0.30, 2 nguồn)"
        await generate_breaking_content(
            _event(), llm, severity="notable", consensus_snapshot=consensus
        )
        call_kwargs = llm.generate.call_args
        prompt = call_kwargs.kwargs.get("prompt", "") or call_kwargs.args[0]
        assert "Đồng thuận thị trường hiện tại" in prompt
        assert "THAM CHIẾU LỊCH SỬ" not in prompt


# ============================================================================
# _collect_consensus_snapshot (pipeline helper)
# ============================================================================


class TestCollectConsensusSnapshot:
    """QO.19: _collect_consensus_snapshot in breaking_pipeline."""

    async def test_returns_empty_on_failure(self):
        """Consensus collection failure → empty string (non-fatal)."""
        from cic_daily_report.breaking_pipeline import _collect_consensus_snapshot

        with patch(
            "cic_daily_report.generators.consensus_engine.build_consensus",
            side_effect=Exception("Consensus engine error"),
        ):
            result = await _collect_consensus_snapshot(None)
        assert result == ""

    async def test_returns_empty_when_no_results(self):
        """Consensus returns empty list → empty string."""
        from cic_daily_report.breaking_pipeline import _collect_consensus_snapshot

        with patch(
            "cic_daily_report.generators.consensus_engine.build_consensus",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await _collect_consensus_snapshot(None)
        assert result == ""

    async def test_formats_btc_consensus(self):
        """BTC consensus → formatted text."""
        from cic_daily_report.breaking_pipeline import _collect_consensus_snapshot
        from cic_daily_report.generators.consensus_engine import MarketConsensus

        mock_consensus = [
            MarketConsensus(
                asset="BTC",
                score=0.45,
                label="BULLISH",
                source_count=3,
                bullish_pct=70.0,
            ),
        ]

        with patch(
            "cic_daily_report.generators.consensus_engine.build_consensus",
            new_callable=AsyncMock,
            return_value=mock_consensus,
        ):
            result = await _collect_consensus_snapshot(None)

        assert "BTC" in result
        assert "BULLISH" in result
        assert "+0.45" in result
        assert "3 nguồn" in result
        assert "70%" in result

    async def test_formats_btc_and_eth(self):
        """Both BTC and ETH → pipe-separated."""
        from cic_daily_report.breaking_pipeline import _collect_consensus_snapshot
        from cic_daily_report.generators.consensus_engine import MarketConsensus

        mock_consensus = [
            MarketConsensus(
                asset="BTC", score=0.30, label="BULLISH", source_count=3, bullish_pct=65.0
            ),
            MarketConsensus(
                asset="ETH", score=-0.10, label="NEUTRAL", source_count=2, bullish_pct=40.0
            ),
        ]

        with patch(
            "cic_daily_report.generators.consensus_engine.build_consensus",
            new_callable=AsyncMock,
            return_value=mock_consensus,
        ):
            result = await _collect_consensus_snapshot(None)

        assert "BTC" in result
        assert "ETH" in result
        assert "|" in result

    async def test_skips_non_btc_eth_assets(self):
        """market_overall and other assets are excluded."""
        from cic_daily_report.breaking_pipeline import _collect_consensus_snapshot
        from cic_daily_report.generators.consensus_engine import MarketConsensus

        mock_consensus = [
            MarketConsensus(asset="market_overall", score=0.10, label="NEUTRAL", source_count=4),
        ]

        with patch(
            "cic_daily_report.generators.consensus_engine.build_consensus",
            new_callable=AsyncMock,
            return_value=mock_consensus,
        ):
            result = await _collect_consensus_snapshot(None)

        assert result == ""


# ============================================================================
# Regression: existing behavior preserved
# ============================================================================


class TestRegressionBreakingContent:
    """Ensure QO.19 changes don't break existing content generation."""

    async def test_still_generates_without_consensus(self):
        """Backward compat: generate_breaking_content works without consensus."""
        llm = _mock_llm()
        result = await generate_breaking_content(_event(), llm, severity="critical")
        assert result.ai_generated
        assert result.word_count > 0

    async def test_still_uses_nq05_system_prompt(self):
        """NQ05 system prompt still present."""
        llm = _mock_llm()
        await generate_breaking_content(_event(), llm)
        call_kwargs = llm.generate.call_args
        assert "NQ05" in call_kwargs.kwargs.get("system_prompt", "")

    async def test_market_context_still_works(self):
        """market_context still injected into prompt."""
        llm = _mock_llm()
        await generate_breaking_content(_event(), llm, market_context="BTC: $70,000 (+2.1%)")
        call_kwargs = llm.generate.call_args
        prompt = call_kwargs.kwargs.get("prompt", "") or call_kwargs.args[0]
        assert "BTC: $70,000" in prompt

    async def test_recent_events_still_works(self):
        """recent_events still injected into prompt."""
        llm = _mock_llm()
        await generate_breaking_content(_event(), llm, recent_events="- Event 1 (CoinDesk)")
        call_kwargs = llm.generate.call_args
        prompt = call_kwargs.kwargs.get("prompt", "") or call_kwargs.args[0]
        assert "Event 1" in prompt
