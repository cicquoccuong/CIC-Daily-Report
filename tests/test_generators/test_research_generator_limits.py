"""Tests for research article character limits (P1.25).

Verifies that generate_research_article() enforces RESEARCH_MAX_CHARS (18000)
via truncate_to_limit, and that word_count is recalculated after truncation.
NQ05 compliance: DISCLAIMER must ALWAYS be present in final output.
"""

import logging
from unittest.mock import AsyncMock

import pytest

from cic_daily_report.adapters.llm_adapter import LLMResponse
from cic_daily_report.collectors.research_data import ResearchData
from cic_daily_report.generators.article_generator import DISCLAIMER, GenerationContext
from cic_daily_report.generators.research_generator import (
    RESEARCH_MAX_CHARS,
    generate_research_article,
)


@pytest.fixture()
def _propagate_research_logger():
    """Temporarily enable propagation so caplog can capture messages.

    WHY: cic.research_generator logger has propagate=False by default.
    """
    logger = logging.getLogger("cic.research_generator")
    logger.propagate = True
    yield
    logger.propagate = False


def _make_context() -> GenerationContext:
    return GenerationContext(
        market_data="BTC: $70,000",
        onchain_data="BTC_Funding_Rate: 0.0008",
        key_metrics={"BTC Price": "$70,000"},
    )


def _make_research_data() -> ResearchData:
    return ResearchData()


def _mock_llm(text: str) -> AsyncMock:
    mock = AsyncMock()
    mock.generate = AsyncMock(
        return_value=LLMResponse(text=text, tokens_used=5000, model="gemini_flash")
    )
    return mock


# WHY 22000+ chars: comfortably over 18000 to guarantee truncation,
# and >800 words so it passes the quality gate (word_count >= 800)
_LONG_CONTENT = (
    "# CIC Market Insight\n\n"
    "## 1. Tong quan thi truong\n\n"
    "Phan tich chi tiet ve thi truong tai san ma hoa hom nay. " * 400
)


class TestResearchTruncation:
    async def test_truncated_when_over_limit(self):
        """LLM returns >18000 chars -> output must be <= RESEARCH_MAX_CHARS."""
        llm = _mock_llm(_LONG_CONTENT)
        article = await generate_research_article(llm, _make_context(), _make_research_data())
        assert article is not None
        assert len(article.content) <= RESEARCH_MAX_CHARS

    async def test_not_truncated_when_under_limit(self):
        """LLM returns content under limit -> unchanged (plus disclaimer)."""
        # ~5000 chars, well under 18000, and >800 words
        medium_content = "Phan tich thi truong tai san ma hoa hom nay chi tiet va sau. " * 100
        llm = _mock_llm(medium_content)
        article = await generate_research_article(llm, _make_context(), _make_research_data())
        assert article is not None
        # Content should be the original + disclaimer, not truncated
        assert len(article.content) < RESEARCH_MAX_CHARS
        assert medium_content[:50] in article.content

    @pytest.mark.usefixtures("_propagate_research_logger")
    async def test_truncation_logs_warning(self, caplog):
        """Warning logged when research article is truncated."""
        llm = _mock_llm(_LONG_CONTENT)
        with caplog.at_level(logging.WARNING):
            await generate_research_article(llm, _make_context(), _make_research_data())
        assert any("Research article body truncated" in msg for msg in caplog.messages)
        # Verify the warning contains char count info
        warning_msgs = [m for m in caplog.messages if "truncated" in m]
        assert len(warning_msgs) >= 1
        assert "->" in warning_msgs[0]

    async def test_word_count_updated_after_truncation(self):
        """word_count reflects the truncated content, not the original."""
        llm = _mock_llm(_LONG_CONTENT)
        article = await generate_research_article(llm, _make_context(), _make_research_data())
        assert article is not None
        # word_count must match actual content
        expected = len(article.content.split())
        assert article.word_count == expected
        # And it should be less than what the original would have been
        original_word_count = len((_LONG_CONTENT.strip() + DISCLAIMER).split())
        assert article.word_count < original_word_count

    async def test_research_disclaimer_preserved_when_truncated(self):
        """NQ05 compliance: DISCLAIMER must be present even after truncation.

        WHY: Body is truncated first, then DISCLAIMER appended — so the
        mandatory NQ05 disclaimer is never cut off.
        """
        llm = _mock_llm(_LONG_CONTENT)
        article = await generate_research_article(llm, _make_context(), _make_research_data())
        assert article is not None
        assert DISCLAIMER in article.content
        assert len(article.content) <= RESEARCH_MAX_CHARS
