"""Tests for breaking content character limits (P1.25).

Verifies that generate_breaking_content() and generate_digest_content()
enforce BREAKING_MAX_CHARS (4000) via truncate_to_limit.
"""

import logging
from unittest.mock import AsyncMock

import pytest

from cic_daily_report.adapters.llm_adapter import LLMResponse
from cic_daily_report.breaking.content_generator import (
    BREAKING_MAX_CHARS,
    generate_breaking_content,
    generate_digest_content,
)
from cic_daily_report.breaking.event_detector import BreakingEvent
from cic_daily_report.generators.article_generator import DISCLAIMER


@pytest.fixture()
def _propagate_breaking_logger():
    """Temporarily enable propagation so caplog can capture messages.

    WHY: cic.breaking_content logger has propagate=False by default (custom handler).
    caplog only captures messages that propagate to the root logger.
    """
    logger = logging.getLogger("cic.breaking_content")
    logger.propagate = True
    yield
    logger.propagate = False


def _event() -> BreakingEvent:
    return BreakingEvent(
        title="Major exchange hack",
        source="CoinDesk",
        url="https://coindesk.com/hack",
        panic_score=85,
    )


def _mock_llm(text: str = "Short content.") -> AsyncMock:
    mock = AsyncMock()
    mock.generate = AsyncMock(
        return_value=LLMResponse(text=text, tokens_used=100, model="test-model")
    )
    mock.last_provider = "groq"
    return mock


class TestBreakingContentTruncation:
    async def test_truncated_when_over_limit(self):
        """LLM returns >4000 chars -> output must be <= BREAKING_MAX_CHARS."""
        # WHY 5000: comfortably over 4000 to guarantee truncation fires
        long_text = "Tin quan trong. " * 400  # ~6400 chars
        llm = _mock_llm(long_text)
        result = await generate_breaking_content(_event(), llm)
        assert len(result.content) <= BREAKING_MAX_CHARS

    async def test_not_truncated_when_under_limit(self):
        """LLM returns short content -> output unchanged (except disclaimer/link)."""
        short_text = "Tin ngan."
        llm = _mock_llm(short_text)
        result = await generate_breaking_content(_event(), llm)
        # Content should contain the original text (plus link + disclaimer)
        assert "Tin ngan." in result.content
        # Should not be truncated — total with disclaimer is well under 4000
        assert len(result.content) < BREAKING_MAX_CHARS

    @pytest.mark.usefixtures("_propagate_breaking_logger")
    async def test_truncation_logs_warning(self, caplog):
        """Warning logged when truncation occurs, with original and new lengths."""
        long_text = "Phan tich chi tiet. " * 400
        llm = _mock_llm(long_text)
        with caplog.at_level(logging.WARNING):
            await generate_breaking_content(_event(), llm)
        assert any("Breaking content body truncated" in msg for msg in caplog.messages)
        # Verify the warning contains body_limit info
        warning_msgs = [m for m in caplog.messages if "truncated" in m]
        assert len(warning_msgs) >= 1
        assert "body_limit=" in warning_msgs[0]

    async def test_word_count_reflects_truncated_content(self):
        """word_count in returned BreakingContent matches truncated content."""
        long_text = "Mot hai ba bon nam. " * 400
        llm = _mock_llm(long_text)
        result = await generate_breaking_content(_event(), llm)
        expected_word_count = len(result.content.split())
        assert result.word_count == expected_word_count


class TestDigestContentTruncation:
    async def test_truncated_when_over_limit(self):
        """Digest with >4000 chars -> output must be <= BREAKING_MAX_CHARS."""
        long_text = "Tong hop tin tuc. " * 400
        llm = _mock_llm(long_text)
        events = [
            BreakingEvent(
                title=f"Event {i}",
                source=f"Source{i}",
                url=f"https://example.com/{i}",
                panic_score=80,
            )
            for i in range(3)
        ]
        result = await generate_digest_content(events, llm)
        assert len(result.content) <= BREAKING_MAX_CHARS

    @pytest.mark.usefixtures("_propagate_breaking_logger")
    async def test_digest_truncation_logs_warning(self, caplog):
        """Warning logged when digest truncation occurs."""
        long_text = "Phan tich su kien. " * 400
        llm = _mock_llm(long_text)
        events = [
            BreakingEvent(
                title="Event A",
                source="CoinDesk",
                url="https://example.com/a",
                panic_score=80,
            ),
        ]
        with caplog.at_level(logging.WARNING):
            await generate_digest_content(events, llm)
        assert any("Digest content body truncated" in msg for msg in caplog.messages)


class TestBreakingDisclaimerPreserved:
    """NQ05 compliance: DISCLAIMER must NEVER be truncated, even when content
    exceeds BREAKING_MAX_CHARS. Body is truncated first, then suffix appended."""

    async def test_breaking_disclaimer_preserved_when_truncated(self):
        """Disclaimer present in output even when body exceeds limit."""
        # WHY 5000 chars: forces truncation, but disclaimer must survive
        long_text = "Tin quan trong. " * 400  # ~6400 chars
        llm = _mock_llm(long_text)
        result = await generate_breaking_content(_event(), llm)
        assert DISCLAIMER in result.content
        assert len(result.content) <= BREAKING_MAX_CHARS

    async def test_breaking_content_still_within_limit(self):
        """After disclaimer-safe truncation, total output <= BREAKING_MAX_CHARS."""
        long_text = "Phan tich chi tiet. " * 400
        llm = _mock_llm(long_text)
        result = await generate_breaking_content(_event(), llm)
        assert len(result.content) <= BREAKING_MAX_CHARS

    async def test_digest_disclaimer_preserved_when_truncated(self):
        """Digest: disclaimer present even when content exceeds limit."""
        long_text = "Tong hop tin tuc. " * 400
        llm = _mock_llm(long_text)
        events = [
            BreakingEvent(
                title=f"Event {i}",
                source=f"Source{i}",
                url=f"https://example.com/{i}",
                panic_score=80,
            )
            for i in range(3)
        ]
        result = await generate_digest_content(events, llm)
        assert DISCLAIMER in result.content
        assert len(result.content) <= BREAKING_MAX_CHARS
