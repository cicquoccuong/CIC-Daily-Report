"""Tests for generators/master_analysis.py — all LLM calls mocked."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from cic_daily_report.adapters.llm_adapter import LLMResponse
from cic_daily_report.generators.article_generator import GenerationContext
from cic_daily_report.generators.master_analysis import (
    MASTER_MIN_WORDS,
    MASTER_SECTIONS_EXPECTED,
    MASTER_SYSTEM_PROMPT,
    MasterAnalysis,
    MasterAnalysisError,
    build_master_context,
    generate_master_analysis,
    validate_master,
)


def _make_context(**overrides) -> GenerationContext:
    """Build a GenerationContext with sensible defaults for testing."""
    defaults = {
        "market_data": "BTC: $70,810 (+1.2%) | ETH: $1,850 (-0.5%)",
        "news_summary": "SEC approves new crypto ETF\nBTC breaks 70K resistance",
        "onchain_data": "BTC_Funding_Rate: 0.0008\nBTC_Open_Interest: 87500",
        "key_metrics": {"BTC Price": "$70,810", "Fear & Greed": 28},
        "whale_data": "BTC transfer: 5,000 BTC ($355M) to Coinbase",
        "research_data_text": "MVRV_Z_Score: 1.45 (BGeometrics)",
        "historical_context": "7d: BTC -2.3%, ETH +1.1%",
        "consensus_text": "=== EXPERT CONSENSUS ===\nBullish: 60%",
        "sector_data": "=== SECTOR ===\nDeFi TVL: $120B",
        "economic_events": "Fed decision 2026-03-26",
        "recent_breaking": "[important] SEC approves new Bitcoin ETF",
        "narratives_text": "=== NARRATIVES ===\nAI narrative rising",
        "data_quality_notes": "Warning: whale data delayed 2h",
        "coin_lists": {"L1": ["BTC", "ETH"], "L2": ["BTC", "ETH", "SOL"]},
    }
    defaults.update(overrides)
    return GenerationContext(**defaults)


def _make_master_content(sections: int = 8, word_count: int = 3000) -> str:
    """Build fake Master Analysis content with the specified number of sections."""
    parts = []
    for i in range(1, sections + 1):
        section_names = {
            1: "TONG QUAN THI TRUONG",
            2: "PHAN TICH BLUECHIP VA SECTOR",
            3: "CHUOI NHAN-QUA MACRO",
            4: "DERIVATIVES VA ON-CHAIN",
            5: "RUI RO VA MAU THUAN",
            6: "KICH BAN VA TRIEN VONG",
            7: "DONG TIEN VA XU HUONG",
            8: "KET LUAN",
        }
        name = section_names.get(i, f"SECTION {i}")
        parts.append(f"## {i}. {name}")
        # Fill with enough words to reach target
        filler = " ".join(["word"] * (word_count // sections))
        parts.append(filler)
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# build_master_context tests
# ---------------------------------------------------------------------------


class TestBuildMasterContext:
    def test_includes_all_fields(self):
        """All non-empty fields in GenerationContext should appear in output."""
        ctx = _make_context()
        result = build_master_context(ctx)

        assert "BTC: $70,810" in result  # market_data
        assert "SEC approves" in result  # news
        assert "BTC_Funding_Rate" in result  # onchain
        assert "5,000 BTC" in result  # whale
        assert "MVRV_Z_Score" in result  # research
        assert "7d: BTC -2.3%" in result  # historical
        assert "EXPERT CONSENSUS" in result  # consensus
        assert "DeFi TVL" in result  # sector
        assert "Fed decision" in result  # economic events
        assert "SEC approves new Bitcoin ETF" in result  # breaking
        assert "NARRATIVES" in result  # narratives
        assert "whale data delayed" in result  # data quality
        assert "BTC" in result  # coin lists
        assert "SOL" in result  # coin lists (from L2)

    def test_skips_empty_fields(self):
        """Empty string fields should not produce sections in output."""
        ctx = _make_context(
            market_data="",
            news_summary="",
            onchain_data="",
            whale_data="",
            research_data_text="",
            historical_context="",
            consensus_text="",
            sector_data="",
            economic_events="",
            recent_breaking="",
            narratives_text="",
            data_quality_notes="",
            coin_lists={},
        )
        result = build_master_context(ctx)
        # Only key_metrics should remain (if non-empty)
        assert "DU LIEU THI TRUONG" not in result
        assert "TIN TUC" not in result
        assert "ON-CHAIN" not in result
        assert "WHALE ALERT" not in result

    def test_skips_whale_with_khong_co(self):
        """Whale data containing 'Khong co' should be excluded."""
        ctx = _make_context(whale_data="Khong co du lieu whale")
        result = build_master_context(ctx)
        assert "WHALE ALERT" not in result

    def test_merges_coin_lists_across_tiers(self):
        """Coin lists from all tiers should be merged into a single set."""
        ctx = _make_context(
            coin_lists={
                "L1": ["BTC", "ETH"],
                "L2": ["BTC", "ETH", "SOL"],
                "L5": ["BTC", "ETH", "SOL", "DOGE"],
            }
        )
        result = build_master_context(ctx)
        assert "BTC" in result
        assert "DOGE" in result
        assert "SOL" in result

    def test_metrics_interpretation_format_for_tier(self):
        """When metrics_interpretation has format_for_tier, it should be included."""

        class MockInterp:
            def format_for_tier(self, tier: str) -> str:
                return f"Interpreted for {tier}"

        ctx = _make_context()
        ctx.metrics_interpretation = MockInterp()
        result = build_master_context(ctx)
        assert "Interpreted for L5" in result

    def test_metrics_interpretation_exception_ignored(self):
        """If format_for_tier raises, it should be silently skipped."""

        class BrokenInterp:
            def format_for_tier(self, tier: str) -> str:
                raise ValueError("broken")

        ctx = _make_context()
        ctx.metrics_interpretation = BrokenInterp()
        # Should not raise
        result = build_master_context(ctx)
        assert "PHAN TICH TU DONG" not in result


# ---------------------------------------------------------------------------
# validate_master tests
# ---------------------------------------------------------------------------


class TestValidateMaster:
    def test_complete_master_passes(self):
        """A Master with all 8 sections + conclusion should pass."""
        master = MasterAnalysis(
            content=_make_master_content(8),
            word_count=3000,
            llm_used="gemini-2.5-flash",
            generation_time_sec=15.0,
            finish_reason="stop",
            sections_found=8,
            has_conclusion=True,
        )
        assert validate_master(master) is True

    def test_no_conclusion_fails(self):
        """Missing conclusion (## 8) should fail validation."""
        master = MasterAnalysis(
            content="short",
            word_count=3000,
            llm_used="mock",
            generation_time_sec=10.0,
            finish_reason="stop",
            sections_found=7,
            has_conclusion=False,
        )
        assert validate_master(master) is False

    def test_too_few_sections_fails(self):
        """Fewer than 6 sections should fail validation."""
        master = MasterAnalysis(
            content="short",
            word_count=3000,
            llm_used="mock",
            generation_time_sec=10.0,
            finish_reason="stop",
            sections_found=5,
            has_conclusion=True,
        )
        assert validate_master(master) is False

    def test_six_sections_with_conclusion_passes(self):
        """Exactly 6 sections with conclusion should pass (threshold is 6)."""
        master = MasterAnalysis(
            content="content",
            word_count=3000,
            llm_used="mock",
            generation_time_sec=10.0,
            finish_reason="stop",
            sections_found=6,
            has_conclusion=True,
        )
        assert validate_master(master) is True

    def test_truncated_without_conclusion_fails(self):
        """finish_reason=length without conclusion should fail."""
        master = MasterAnalysis(
            content="truncated",
            word_count=3000,
            llm_used="mock",
            generation_time_sec=10.0,
            finish_reason="length",
            sections_found=7,
            has_conclusion=False,
        )
        assert validate_master(master) is False

    def test_truncated_always_fails(self):
        """finish_reason=length ALWAYS fails — even if conclusion keyword present.

        WHY: LLM may have been cut mid-section; conclusion keyword could match
        earlier text rather than a complete conclusion section.
        """
        master = MasterAnalysis(
            content="content",
            word_count=3000,
            llm_used="mock",
            generation_time_sec=10.0,
            finish_reason="length",
            sections_found=8,
            has_conclusion=True,
        )
        assert validate_master(master) is False


# ---------------------------------------------------------------------------
# generate_master_analysis tests
# ---------------------------------------------------------------------------


class TestGenerateMasterAnalysis:
    async def test_raises_on_short_response(self):
        """Response with fewer than MASTER_MIN_WORDS should raise MasterAnalysisError."""
        mock_llm = AsyncMock()
        # 500 words = way below 2000 minimum
        short_content = " ".join(["word"] * 500)
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                text=short_content, tokens_used=1000, model="mock", finish_reason="stop"
            )
        )

        ctx = _make_context()
        with pytest.raises(MasterAnalysisError, match="too short"):
            await generate_master_analysis(mock_llm, ctx)

    async def test_successful_generation(self):
        """A sufficiently long response with sections should return MasterAnalysis."""
        mock_llm = AsyncMock()
        content = _make_master_content(8, word_count=3000)
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                text=content, tokens_used=8000, model="gemini-2.5-flash", finish_reason="stop"
            )
        )

        ctx = _make_context()
        result = await generate_master_analysis(mock_llm, ctx)

        assert isinstance(result, MasterAnalysis)
        assert result.word_count >= MASTER_MIN_WORDS
        assert result.llm_used == "gemini-2.5-flash"
        assert result.sections_found >= 6
        assert result.has_conclusion is True

    async def test_calls_llm_with_correct_params(self):
        """LLM should be called with MASTER_SYSTEM_PROMPT and correct max_tokens."""
        mock_llm = AsyncMock()
        content = _make_master_content(8, word_count=3000)
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                text=content, tokens_used=8000, model="mock", finish_reason="stop"
            )
        )

        ctx = _make_context()
        await generate_master_analysis(mock_llm, ctx)

        call_kwargs = mock_llm.generate.call_args
        assert call_kwargs.kwargs["system_prompt"] == MASTER_SYSTEM_PROMPT
        assert call_kwargs.kwargs["max_tokens"] == 16384
        assert call_kwargs.kwargs["temperature"] == 0.4


# ---------------------------------------------------------------------------
# Section parsing tests
# ---------------------------------------------------------------------------


class TestSectionParsing:
    async def test_fuzzy_match_section_dot(self):
        """'## 1.' format should be detected."""
        content = "## 1. TONG QUAN\nSome text " + " ".join(["word"] * 2100)
        content += "\n## 8. KET LUAN\nSome conclusion"

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                text=content, tokens_used=5000, model="mock", finish_reason="stop"
            )
        )

        ctx = _make_context()
        result = await generate_master_analysis(mock_llm, ctx)
        assert result.sections_found >= 1
        assert result.has_conclusion is True

    async def test_fuzzy_match_section_space(self):
        """'## 1 ' (space, no dot) format should also be detected."""
        content = "## 1 TONG QUAN\nSome text " + " ".join(["word"] * 2100)
        content += "\n## 8 KET LUAN\nSome conclusion"

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                text=content, tokens_used=5000, model="mock", finish_reason="stop"
            )
        )

        ctx = _make_context()
        result = await generate_master_analysis(mock_llm, ctx)
        assert result.sections_found >= 1
        assert result.has_conclusion is True

    async def test_ket_luan_keyword_detected(self):
        """'KET LUAN' keyword in content should set has_conclusion=True."""
        content = "## 1. Overview\nSome text " + " ".join(["word"] * 2100)
        content += "\n## 7. Some section\nText\nKET LUAN: summary here"

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                text=content, tokens_used=5000, model="mock", finish_reason="stop"
            )
        )

        ctx = _make_context()
        result = await generate_master_analysis(mock_llm, ctx)
        assert result.has_conclusion is True


# ---------------------------------------------------------------------------
# MASTER_SYSTEM_PROMPT integrity
# ---------------------------------------------------------------------------


class TestMasterSystemPrompt:
    def test_contains_all_8_sections(self):
        """System prompt should define all 8 section headings."""
        for i in range(1, MASTER_SECTIONS_EXPECTED + 1):
            assert f"## {i}." in MASTER_SYSTEM_PROMPT, f"Missing section ## {i}."

    def test_contains_nq05_rule(self):
        """NQ05 compliance rule must be present."""
        assert "NQ05" in MASTER_SYSTEM_PROMPT

    def test_word_count_target(self):
        """Should specify 4000-6000 word target."""
        assert "4000-6000" in MASTER_SYSTEM_PROMPT
