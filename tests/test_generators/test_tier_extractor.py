"""Tests for generators/tier_extractor.py — all LLM calls mocked."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from cic_daily_report.adapters.llm_adapter import LLMResponse
from cic_daily_report.generators.article_generator import DISCLAIMER, GeneratedArticle
from cic_daily_report.generators.master_analysis import MasterAnalysis
from cic_daily_report.generators.tier_extractor import (
    EXTRACTION_CONFIGS,
    extract_all,
    extract_tier,
)


def _make_master(content: str = "Master content " * 500) -> MasterAnalysis:
    """Build a fake MasterAnalysis for testing."""
    return MasterAnalysis(
        content=content,
        word_count=len(content.split()),
        llm_used="gemini-2.5-flash",
        generation_time_sec=15.0,
        finish_reason="stop",
        sections_found=8,
        has_conclusion=True,
    )


_MOCK_EXTRACTION = (
    "Phan tich thi truong tai san ma hoa hom nay co nhieu bien dong. "
    "BTC dang giao dich quanh muc ho tro quan trong voi khoi luong giao dich tang. "
    "Ethereum cung co xu huong tuong tu voi nhieu nha dau tu quan tam. "
    "Thi truong dang trong giai doan tich luy, cho tin hieu ro rang hon. " * 20
)


# ---------------------------------------------------------------------------
# EXTRACTION_CONFIGS tests
# ---------------------------------------------------------------------------


class TestExtractionConfigs:
    def test_all_six_configs_defined(self):
        """Should have configs for L1-L5 + Summary (6 total)."""
        expected = {"L1", "L2", "L3", "L4", "L5", "Summary"}
        assert set(EXTRACTION_CONFIGS.keys()) == expected

    def test_each_config_has_required_fields(self):
        """Every config should have non-empty tier, audience, focus, sections_focus."""
        for tier, config in EXTRACTION_CONFIGS.items():
            assert config.tier == tier
            assert config.audience, f"{tier} missing audience"
            assert config.focus, f"{tier} missing focus"
            assert config.sections_focus, f"{tier} missing sections_focus"
            assert config.max_tokens > 0, f"{tier} max_tokens must be positive"
            assert config.target_words[0] < config.target_words[1], (
                f"{tier} target_words range invalid"
            )

    def test_summary_has_format_instructions(self):
        """Summary config must have non-empty format_instructions for story-based format."""
        summary_config = EXTRACTION_CONFIGS["Summary"]
        assert summary_config.format_instructions, "Summary missing format_instructions"
        assert "HOOK" in summary_config.format_instructions
        assert "Telegram" in summary_config.format_instructions

    def test_tier_configs_no_format_instructions(self):
        """L1-L5 tier configs should NOT have format_instructions (empty string)."""
        for tier in ["L1", "L2", "L3", "L4", "L5"]:
            assert EXTRACTION_CONFIGS[tier].format_instructions == ""

    def test_word_count_increases_with_tier(self):
        """Higher tiers should have larger word count targets."""
        tiers_ordered = ["L1", "L2", "L3", "L4", "L5"]
        prev_max = 0
        for tier in tiers_ordered:
            config = EXTRACTION_CONFIGS[tier]
            assert config.target_words[1] > prev_max, (
                f"{tier} target_words max should exceed previous tier"
            )
            prev_max = config.target_words[1]

    def test_temperature_increases_with_tier(self):
        """Higher tiers should have equal or higher temperature."""
        tiers_ordered = ["L1", "L2", "L3", "L4", "L5"]
        prev_temp = 0.0
        for tier in tiers_ordered:
            config = EXTRACTION_CONFIGS[tier]
            assert config.temperature >= prev_temp, f"{tier} temperature should be >= previous tier"
            prev_temp = config.temperature


# ---------------------------------------------------------------------------
# extract_tier tests
# ---------------------------------------------------------------------------


class TestExtractTier:
    async def test_returns_generated_article(self):
        """extract_tier should return a GeneratedArticle with correct tier."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                text=_MOCK_EXTRACTION,
                tokens_used=2000,
                model="gemini-2.5-flash",
                finish_reason="stop",
            )
        )

        master = _make_master()
        config = EXTRACTION_CONFIGS["L1"]
        article = await extract_tier(mock_llm, master, config, "Additional L1 context")

        assert isinstance(article, GeneratedArticle)
        assert article.tier == "L1"
        assert article.word_count > 0
        assert article.llm_used == "gemini-2.5-flash"

    async def test_tier_articles_get_disclaimer(self):
        """L1-L5 tier articles should have DISCLAIMER appended."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                text=_MOCK_EXTRACTION, tokens_used=2000, model="mock", finish_reason="stop"
            )
        )

        master = _make_master()
        for tier in ["L1", "L2", "L3", "L4", "L5"]:
            config = EXTRACTION_CONFIGS[tier]
            article = await extract_tier(mock_llm, master, config)
            assert DISCLAIMER in article.content, f"{tier} missing DISCLAIMER"

    async def test_summary_no_disclaimer(self):
        """Summary extraction should NOT have DISCLAIMER (pipeline handles it)."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                text=_MOCK_EXTRACTION, tokens_used=2000, model="mock", finish_reason="stop"
            )
        )

        master = _make_master()
        config = EXTRACTION_CONFIGS["Summary"]
        article = await extract_tier(mock_llm, master, config)
        assert DISCLAIMER not in article.content

    async def test_extraction_prompt_contains_master_content(self):
        """The prompt sent to LLM should contain the Master Analysis content."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                text=_MOCK_EXTRACTION, tokens_used=2000, model="mock", finish_reason="stop"
            )
        )

        master_content = "UNIQUE_MARKER_BTC_70810_ANALYSIS"
        master = _make_master(content=master_content + " " + " ".join(["word"] * 500))
        config = EXTRACTION_CONFIGS["L3"]
        await extract_tier(mock_llm, master, config)

        call_kwargs = mock_llm.generate.call_args.kwargs
        assert "UNIQUE_MARKER_BTC_70810_ANALYSIS" in call_kwargs["prompt"]

    async def test_tier_context_included_in_prompt(self):
        """tier_context_str should appear in the extraction prompt."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                text=_MOCK_EXTRACTION, tokens_used=2000, model="mock", finish_reason="stop"
            )
        )

        master = _make_master()
        config = EXTRACTION_CONFIGS["L2"]
        await extract_tier(mock_llm, master, config, "SPECIAL_L2_CONTEXT_HERE")

        call_kwargs = mock_llm.generate.call_args.kwargs
        assert "SPECIAL_L2_CONTEXT_HERE" in call_kwargs["prompt"]

    async def test_format_instructions_included_for_summary(self):
        """Summary's format_instructions should appear in the extraction prompt."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                text=_MOCK_EXTRACTION, tokens_used=2000, model="mock", finish_reason="stop"
            )
        )

        master = _make_master()
        config = EXTRACTION_CONFIGS["Summary"]
        await extract_tier(mock_llm, master, config)

        call_kwargs = mock_llm.generate.call_args.kwargs
        assert "HOOK" in call_kwargs["prompt"]


# ---------------------------------------------------------------------------
# extract_all tests
# ---------------------------------------------------------------------------


class TestExtractAll:
    async def test_sequential_order(self):
        """extract_all should produce articles in config order: L1,L2,L3,L4,L5,Summary."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                text=_MOCK_EXTRACTION, tokens_used=2000, model="mock", finish_reason="stop"
            )
        )
        mock_llm.suggest_cooldown = lambda: 0  # no cooldown in tests

        master = _make_master()
        articles = await extract_all(mock_llm, master, {})

        assert len(articles) == 6
        expected_order = ["L1", "L2", "L3", "L4", "L5", "Summary"]
        actual_order = [a.tier for a in articles]
        assert actual_order == expected_order

    async def test_skips_failed_tier(self):
        """If a tier extraction fails (non-429), it should be skipped, not crash."""
        call_count = 0

        async def _side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            # Fail on 3rd call (L3)
            if call_count == 3:
                raise ValueError("LLM error on L3")
            return LLMResponse(
                text=_MOCK_EXTRACTION, tokens_used=2000, model="mock", finish_reason="stop"
            )

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(side_effect=_side_effect)
        mock_llm.suggest_cooldown = lambda: 0

        master = _make_master()
        articles = await extract_all(mock_llm, master, {})

        # 6 configs - 1 failed = 5 articles
        assert len(articles) == 5
        tiers = [a.tier for a in articles]
        assert "L3" not in tiers

    @patch("cic_daily_report.generators.tier_extractor.asyncio.sleep", new_callable=AsyncMock)
    async def test_429_retry_then_succeed(self, mock_sleep):
        """On 429 error, should wait and retry once."""
        call_count = 0

        async def _side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            # First call for L1 fails with 429, retry succeeds
            if call_count == 1:
                raise Exception("429 Too Many Requests")
            return LLMResponse(
                text=_MOCK_EXTRACTION, tokens_used=2000, model="mock", finish_reason="stop"
            )

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(side_effect=_side_effect)
        mock_llm.suggest_cooldown = lambda: 0

        master = _make_master()
        articles = await extract_all(mock_llm, master, {})

        # All 6 should succeed (L1 retried)
        assert len(articles) == 6
        # Should have called sleep with 120s for the 429 retry
        mock_sleep.assert_any_call(120)

    async def test_tier_contexts_passed_through(self):
        """tier_contexts dict should be passed to each extraction."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                text=_MOCK_EXTRACTION, tokens_used=2000, model="mock", finish_reason="stop"
            )
        )
        mock_llm.suggest_cooldown = lambda: 0

        tier_contexts = {
            "L1": "L1 specific context",
            "L5": "L5 advanced context",
        }

        master = _make_master()
        await extract_all(mock_llm, master, tier_contexts)

        # Verify L1 call included its context
        calls = mock_llm.generate.call_args_list
        l1_prompt = calls[0].kwargs["prompt"]
        assert "L1 specific context" in l1_prompt

    async def test_empty_master_still_works(self):
        """Even with minimal master content, extraction should not crash."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                text=_MOCK_EXTRACTION, tokens_used=2000, model="mock", finish_reason="stop"
            )
        )
        mock_llm.suggest_cooldown = lambda: 0

        master = _make_master(content="Minimal content here.")
        articles = await extract_all(mock_llm, master, {})
        assert len(articles) == 6
