"""Tests for generators/summary_generator.py — all mocked (v0.24.0)."""

from unittest.mock import AsyncMock

from cic_daily_report.adapters.llm_adapter import LLMResponse
from cic_daily_report.generators.article_generator import DISCLAIMER, GeneratedArticle
from cic_daily_report.generators.summary_generator import (
    GeneratedSummary,
    _build_data_context,
    _build_prompt,
    generate_bic_summary,
)


def _make_articles() -> list[GeneratedArticle]:
    return [
        GeneratedArticle(
            tier="L1",
            title="[L1] Test",
            content="L1 analysis content here",
            word_count=50,
            llm_used="test",
            generation_time_sec=1.0,
        ),
        GeneratedArticle(
            tier="L2",
            title="[L2] Test",
            content="L2 deeper analysis",
            word_count=80,
            llm_used="test",
            generation_time_sec=1.5,
        ),
    ]


def _metrics() -> dict[str, str | float]:
    return {
        "BTC Price": "$105,000",
        "Fear & Greed": 72,
        "BTC Dominance": "58.5%",
        "Total Market Cap": "$3.42T",
        "DXY": 103.5,
        "Gold": "$2,850",
    }


def _cleaned_news() -> list[dict]:
    return [
        {
            "title": "BTC hits $105K milestone",
            "source_name": "CoinDesk",
            "summary": "Bitcoin reached a new high",
            "url": "https://example.com/1",
            "language": "en",
        },
        {
            "title": "VN crypto regulation update",
            "source_name": "Coin68",
            "summary": "Vietnam tightens crypto rules",
            "url": "https://example.com/2",
            "language": "vi",
        },
    ]


class TestGenerateBicSummary:
    async def test_generates_summary_with_new_signature(self):
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                text="⭐ TỔNG QUAN THỊ TRƯỜNG\nSummary content", tokens_used=200, model="m"
            )
        )

        summary = await generate_bic_summary(
            llm=mock_llm,
            articles=_make_articles(),
            key_metrics=_metrics(),
            cleaned_news=_cleaned_news(),
        )

        assert isinstance(summary, GeneratedSummary)
        assert "TỔNG QUAN" in summary.content
        assert summary.word_count > 0

    async def test_backward_compatible_minimal_args(self):
        """Old call signature (just articles + key_metrics) still works."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(text="Summary text", tokens_used=50, model="m")
        )

        summary = await generate_bic_summary(mock_llm, _make_articles(), _metrics())

        assert isinstance(summary, GeneratedSummary)
        assert "Summary text" in summary.content

    async def test_summary_has_disclaimer(self):
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(text="Market overview", tokens_used=30, model="m")
        )

        summary = await generate_bic_summary(mock_llm, _make_articles(), _metrics())

        assert DISCLAIMER in summary.content

    async def test_uses_nq05_system_prompt(self):
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(text="ok", tokens_used=10, model="m")
        )

        await generate_bic_summary(mock_llm, _make_articles(), _metrics())

        call_args = mock_llm.generate.call_args
        sys_prompt = call_args.kwargs.get("system_prompt", "")
        assert "NQ05" in sys_prompt

    async def test_uses_lower_temperature(self):
        """v0.24.0: temperature should be 0.3 (data-driven, less creative)."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(text="ok", tokens_used=10, model="m")
        )

        await generate_bic_summary(mock_llm, _make_articles(), _metrics())

        call_args = mock_llm.generate.call_args
        assert call_args.kwargs.get("temperature") == 0.3

    async def test_uses_higher_max_tokens(self):
        """v0.24.0: max_tokens should be 4096 (longer output for 4 sections)."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(text="ok", tokens_used=10, model="m")
        )

        await generate_bic_summary(mock_llm, _make_articles(), _metrics())

        call_args = mock_llm.generate.call_args
        assert call_args.kwargs.get("max_tokens") == 4096

    async def test_prompt_includes_4_section_format(self):
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(text="ok", tokens_used=10, model="m")
        )

        await generate_bic_summary(
            mock_llm, _make_articles(), _metrics(), cleaned_news=_cleaned_news()
        )

        call_args = mock_llm.generate.call_args
        prompt = call_args.kwargs.get("prompt", "")
        # Check all 4 sections are in the prompt
        assert "PHẦN 1" in prompt
        assert "PHẦN 2" in prompt
        assert "PHẦN 3" in prompt
        assert "PHẦN 4" in prompt
        assert "Đáng chú ý" in prompt
        assert "tin tức nổi bật" in prompt

    async def test_handles_empty_articles(self):
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(text="No data summary", tokens_used=10, model="m")
        )

        summary = await generate_bic_summary(mock_llm, [], _metrics())

        assert isinstance(summary, GeneratedSummary)


class TestBuildDataContext:
    def test_includes_key_metrics(self):
        ctx = _build_data_context(
            key_metrics=_metrics(),
            cleaned_news=[],
            market_data=[],
            onchain_data=[],
            sector_snapshot=None,
            econ_calendar=None,
            metrics_interp=None,
            narratives_text="",
            whale_data=None,
            articles=[],
        )
        assert "BTC Price" in ctx
        assert "$105,000" in ctx

    def test_includes_news_separated_by_language(self):
        ctx = _build_data_context(
            key_metrics={},
            cleaned_news=_cleaned_news(),
            market_data=[],
            onchain_data=[],
            sector_snapshot=None,
            econ_calendar=None,
            metrics_interp=None,
            narratives_text="",
            whale_data=None,
            articles=[],
        )
        assert "Tin Việt Nam" in ctx
        assert "Tin quốc tế" in ctx

    def test_includes_whale_data(self):
        from cic_daily_report.collectors.whale_alert import (
            WhaleAlertSummary,
            WhaleTransaction,
        )

        txs = [
            WhaleTransaction(
                "bitcoin", "btc", 500, 50_000_000, "exchange", "unknown", "Binance", "", 0
            ),
        ]
        whale = WhaleAlertSummary(
            transactions=txs,
            total_count=1,
            btc_outflow_usd=50_000_000,
        )

        ctx = _build_data_context(
            key_metrics={},
            cleaned_news=[],
            market_data=[],
            onchain_data=[],
            sector_snapshot=None,
            econ_calendar=None,
            metrics_interp=None,
            narratives_text="",
            whale_data=whale,
            articles=[],
        )
        assert "WHALE" in ctx
        assert "BTC" in ctx


class TestBuildPrompt:
    def test_contains_4_sections(self):
        prompt = _build_prompt("18/03/2026", "data context here")
        assert "PHẦN 1" in prompt
        assert "PHẦN 2" in prompt
        assert "PHẦN 3" in prompt
        assert "PHẦN 4" in prompt

    def test_contains_date(self):
        prompt = _build_prompt("18/03/2026", "data")
        assert "18/03/2026" in prompt

    def test_contains_terminology_rule(self):
        """v0.30.1: NQ05 removed from prompt — post-filter enforces. Terminology rule kept."""
        prompt = _build_prompt("18/03/2026", "data")
        assert "tài sản mã hóa" in prompt
        assert "bịa" in prompt.lower()

    def test_contains_emoji_guide(self):
        prompt = _build_prompt("18/03/2026", "data")
        assert "🔴" in prompt
        assert "🟢" in prompt
        assert "😱" in prompt
