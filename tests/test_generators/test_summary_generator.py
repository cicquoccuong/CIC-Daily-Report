"""Tests for generators/summary_generator.py — all mocked."""

from unittest.mock import AsyncMock

from cic_daily_report.adapters.llm_adapter import LLMResponse
from cic_daily_report.generators.article_generator import DISCLAIMER, GeneratedArticle
from cic_daily_report.generators.summary_generator import (
    GeneratedSummary,
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
    return {"BTC Price": "$105,000", "Fear & Greed": "72"}


class TestGeneratedSummary:
    def test_to_row(self):
        summary = GeneratedSummary(
            title="[Summary] Test",
            content="Summary content",
            word_count=30,
            llm_used="test-model",
            generation_time_sec=2.0,
            nq05_status="pass",
        )
        row = summary.to_row()
        assert len(row) == 8
        assert row[1] == "SUMMARY"
        assert row[7] == "pass"


class TestGenerateBicSummary:
    async def test_generates_summary(self):
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(text="Summary text here", tokens_used=50, model="m")
        )

        summary = await generate_bic_summary(mock_llm, _make_articles(), _metrics())

        assert isinstance(summary, GeneratedSummary)
        assert "Summary text here" in summary.content
        assert summary.word_count > 0

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

    async def test_includes_metrics_in_prompt(self):
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(text="ok", tokens_used=10, model="m")
        )

        await generate_bic_summary(mock_llm, _make_articles(), _metrics())

        call_args = mock_llm.generate.call_args
        prompt = call_args.kwargs.get("prompt", "")
        assert "BTC Price" in prompt

    async def test_handles_empty_articles(self):
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(text="No data summary", tokens_used=10, model="m")
        )

        summary = await generate_bic_summary(mock_llm, [], _metrics())

        assert isinstance(summary, GeneratedSummary)
        call_args = mock_llm.generate.call_args
        prompt = call_args.kwargs.get("prompt", "")
        assert "Không có dữ liệu" in prompt
