"""Tests for breaking/content_generator.py — all mocked."""

from unittest.mock import AsyncMock

from cic_daily_report.adapters.llm_adapter import LLMResponse
from cic_daily_report.breaking.content_generator import (
    BreakingContent,
    _raw_data_fallback,
    generate_breaking_content,
)
from cic_daily_report.breaking.event_detector import BreakingEvent
from cic_daily_report.generators.article_generator import DISCLAIMER


def _event() -> BreakingEvent:
    return BreakingEvent(
        title="Major exchange hack",
        source="CoinDesk",
        url="https://coindesk.com/hack",
        panic_score=85,
    )


def _mock_llm(text: str = "Tin nóng: sự kiện tài sản mã hóa quan trọng.") -> AsyncMock:
    mock = AsyncMock()
    mock.generate = AsyncMock(
        return_value=LLMResponse(text=text, tokens_used=100, model="test-model")
    )
    mock.last_provider = "groq"
    return mock


class TestBreakingContent:
    def test_formatted_returns_content(self):
        bc = BreakingContent(
            event=_event(),
            content="Test content",
            word_count=2,
            ai_generated=True,
        )
        assert bc.formatted == "Test content"


class TestGenerateBreakingContent:
    async def test_generates_with_llm(self):
        llm = _mock_llm()
        result = await generate_breaking_content(_event(), llm)
        assert result.ai_generated
        assert result.word_count > 0
        assert result.model_used == "groq"

    async def test_content_has_disclaimer(self):
        llm = _mock_llm()
        result = await generate_breaking_content(_event(), llm)
        assert "Tuyên bố miễn trừ trách nhiệm" in result.content

    async def test_uses_nq05_system_prompt(self):
        llm = _mock_llm()
        await generate_breaking_content(_event(), llm)
        call_kwargs = llm.generate.call_args
        assert "NQ05" in call_kwargs.kwargs.get("system_prompt", "")

    async def test_critical_uses_longer_target(self):
        llm = _mock_llm()
        await generate_breaking_content(_event(), llm, severity="critical")
        call_kwargs = llm.generate.call_args
        prompt = call_kwargs.kwargs.get("prompt", "") or call_kwargs.args[0]
        assert "400-500" in prompt

    async def test_notable_uses_shorter_target(self):
        llm = _mock_llm()
        await generate_breaking_content(_event(), llm, severity="notable")
        call_kwargs = llm.generate.call_args
        prompt = call_kwargs.kwargs.get("prompt", "") or call_kwargs.args[0]
        assert "300-400" in prompt

    async def test_llm_failure_returns_raw_fallback(self):
        llm = AsyncMock()
        llm.generate = AsyncMock(side_effect=Exception("All LLMs failed"))
        result = await generate_breaking_content(_event(), llm)
        assert not result.ai_generated
        assert result.model_used == "raw_data"
        assert "AI không khả dụng" in result.content

    async def test_raw_fallback_has_disclaimer(self):
        llm = AsyncMock()
        llm.generate = AsyncMock(side_effect=Exception("fail"))
        result = await generate_breaking_content(_event(), llm)
        assert DISCLAIMER in result.content

    async def test_raw_fallback_has_source(self):
        llm = AsyncMock()
        llm.generate = AsyncMock(side_effect=Exception("fail"))
        result = await generate_breaking_content(_event(), llm)
        assert "CoinDesk" in result.content


class TestRawDataFallback:
    def test_includes_title(self):
        result = _raw_data_fallback(_event())
        assert "Major exchange hack" in result.content

    def test_includes_url(self):
        result = _raw_data_fallback(_event())
        assert "https://coindesk.com/hack" in result.content

    def test_not_ai_generated(self):
        result = _raw_data_fallback(_event())
        assert not result.ai_generated
