"""Tests for breaking/content_generator.py — all mocked."""

from unittest.mock import AsyncMock, patch

from cic_daily_report.adapters.llm_adapter import LLMResponse
from cic_daily_report.breaking.content_generator import (
    _DISCLAIMER_RE,
    BreakingContent,
    _fetch_article_text,
    _raw_data_fallback,
    generate_breaking_content,
)
from cic_daily_report.breaking.event_detector import BreakingEvent
from cic_daily_report.generators.article_generator import DISCLAIMER


def _event(image_url: str | None = None) -> BreakingEvent:
    return BreakingEvent(
        title="Major exchange hack",
        source="CoinDesk",
        url="https://coindesk.com/hack",
        panic_score=85,
        image_url=image_url,
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
        assert "200-250" in prompt

    async def test_notable_uses_shorter_target(self):
        llm = _mock_llm()
        await generate_breaking_content(_event(), llm, severity="notable")
        call_kwargs = llm.generate.call_args
        prompt = call_kwargs.kwargs.get("prompt", "") or call_kwargs.args[0]
        assert "100-150" in prompt

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


class TestPhase2ArticleEnrichment:
    """Phase 2: Article text extraction and enrichment for breaking news."""

    async def test_fetch_article_text_success(self):
        """Mock httpx + trafilatura → return extracted text."""
        mock_resp = AsyncMock()
        mock_resp.text = "<html><body>Article body text here with details</body></html>"
        mock_resp.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        extracted = "Extracted article body text " * 50  # ~1400 chars

        with (
            patch(
                "cic_daily_report.breaking.content_generator.httpx.AsyncClient",
                return_value=mock_client,
            ),
            patch("cic_daily_report.breaking.content_generator.trafilatura") as mock_traf,
        ):
            mock_traf.extract.return_value = extracted
            result = await _fetch_article_text("https://example.com/article")

        assert len(result) > 0
        assert len(result) <= 1500

    @patch("cic_daily_report.breaking.content_generator.httpx.AsyncClient")
    async def test_fetch_article_text_timeout(self, mock_client_cls):
        """Timeout → return empty string (graceful)."""
        import httpx

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await _fetch_article_text("https://example.com/slow")
        assert result == ""

    async def test_breaking_with_article_body(self):
        """Event enriched with article body → prompt contains 'Nội dung bài gốc'."""
        llm = _mock_llm()
        event = _event()

        with patch(
            "cic_daily_report.breaking.content_generator._fetch_article_text",
            return_value="Chi tiết bài viết gốc về sự kiện hack sàn giao dịch lớn",
        ):
            await generate_breaking_content(event, llm)

        call_kwargs = llm.generate.call_args
        prompt = call_kwargs.kwargs.get("prompt", "") or call_kwargs.args[0]
        assert "Nội dung bài gốc" in prompt

    async def test_breaking_with_market_context(self):
        """market_context passed → prompt contains market data."""
        llm = _mock_llm()
        await generate_breaking_content(
            _event(), llm, market_context="Bối cảnh thị trường hiện tại: BTC: $74,589 (+0.0%)"
        )
        call_kwargs = llm.generate.call_args
        prompt = call_kwargs.kwargs.get("prompt", "") or call_kwargs.args[0]
        assert "BTC: $74,589" in prompt

    async def test_breaking_with_recent_events(self):
        """recent_events passed → prompt contains recent breaking news."""
        recent = (
            "Tin Breaking gần đây (để liên kết nếu liên quan):\n"
            "- Event 1 (CoinDesk, critical)\n"
            "- Event 2 (TheBlock, important)\n"
            "- Event 3 (CoinTelegraph, notable)"
        )
        llm = _mock_llm()
        await generate_breaking_content(_event(), llm, recent_events=recent)
        call_kwargs = llm.generate.call_args
        prompt = call_kwargs.kwargs.get("prompt", "") or call_kwargs.args[0]
        assert "Tin Breaking gần đây" in prompt
        assert "Event 1" in prompt

    async def test_breaking_without_enrichment(self):
        """All enrichment fails → fallback to title-only (backward compatible)."""
        llm = _mock_llm()
        event = _event()
        event.raw_data = {}  # No summary

        with patch(
            "cic_daily_report.breaking.content_generator._fetch_article_text",
            return_value="",  # trafilatura fails
        ):
            result = await generate_breaking_content(event, llm)

        assert result.ai_generated
        call_kwargs = llm.generate.call_args
        prompt = call_kwargs.kwargs.get("prompt", "") or call_kwargs.args[0]
        assert "Nội dung bài gốc" not in prompt


class TestPhase1Temperature:
    """Phase 1 E2: Breaking content generator must use temperature=0.3."""

    async def test_temperature_breaking_is_0_3(self):
        llm = _mock_llm()
        await generate_breaking_content(_event(), llm)
        call_kwargs = llm.generate.call_args
        temperature = call_kwargs.kwargs.get("temperature")
        assert temperature == 0.3, f"Expected temperature=0.3, got {temperature}"


class TestRawDataFallback:
    def test_includes_title(self):
        result = _raw_data_fallback(_event())
        assert "Major exchange hack" in result.content

    def test_includes_source_hyperlink(self):
        result = _raw_data_fallback(_event())
        assert '<a href="https://coindesk.com/hack">Nguồn: CoinDesk ↗</a>' in result.content

    def test_not_ai_generated(self):
        result = _raw_data_fallback(_event())
        assert not result.ai_generated


class TestFR25ImageUrl:
    """FR25: image_url propagation from event to content."""

    async def test_image_url_passed_to_content(self):
        llm = _mock_llm()
        event = _event(image_url="https://example.com/img.jpg")
        result = await generate_breaking_content(event, llm)
        assert result.image_url == "https://example.com/img.jpg"

    async def test_no_image_url_is_none(self):
        llm = _mock_llm()
        result = await generate_breaking_content(_event(), llm)
        assert result.image_url is None

    def test_raw_fallback_preserves_image_url(self):
        event = _event(image_url="https://example.com/fallback.jpg")
        result = _raw_data_fallback(event)
        assert result.image_url == "https://example.com/fallback.jpg"


class TestSourceUrlInContent:
    """AI-generated content must include clickable source URL."""

    async def test_ai_content_includes_source_hyperlink(self):
        llm = _mock_llm()
        result = await generate_breaking_content(_event(), llm)
        assert '<a href="https://coindesk.com/hack">Nguồn: CoinDesk ↗</a>' in result.content

    async def test_ai_content_has_source_link_emoji(self):
        llm = _mock_llm()
        result = await generate_breaking_content(_event(), llm)
        assert "🔗 <a href=" in result.content


class TestDisclaimerDedup:
    """LLM-generated disclaimer must be stripped; only standard disclaimer remains."""

    def test_disclaimer_regex_strips_trailing_disclaimer(self):
        text = (
            "Tin nóng về tài sản mã hóa.\n\n"
            "---\n"
            "⚠️ Tuyên bố miễn trừ trách nhiệm: Đây không phải lời khuyên đầu tư."
        )
        clean = _DISCLAIMER_RE.sub("", text).rstrip()
        assert "Tin nóng" in clean
        assert "⚠️" not in clean

    def test_disclaimer_regex_preserves_content_without_disclaimer(self):
        text = "Tin nóng về tài sản mã hóa quan trọng."
        clean = _DISCLAIMER_RE.sub("", text).rstrip()
        assert clean == text

    async def test_no_double_disclaimer_when_llm_includes_one(self):
        llm_text = (
            "Tin nóng: sự kiện quan trọng.\n\n"
            "---\n"
            "⚠️ Tuyên bố miễn trừ trách nhiệm: Không phải lời khuyên đầu tư."
        )
        llm = _mock_llm(llm_text)
        result = await generate_breaking_content(_event(), llm)
        count = result.content.count("⚠️")
        assert count == 1, f"Expected 1 disclaimer, found {count}"
