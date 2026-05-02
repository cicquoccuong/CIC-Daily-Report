"""Tests for breaking/content_generator.py — all mocked."""

from unittest.mock import AsyncMock, patch

import pytest

from cic_daily_report.adapters.llm_adapter import LLMResponse
from cic_daily_report.breaking.content_generator import (
    _DISCLAIMER_RE,
    BreakingContent,
    _fetch_article_text,
    _raw_data_fallback,
    generate_breaking_content,
)
from cic_daily_report.breaking.event_detector import BreakingEvent


def _event(image_url: str | None = None) -> BreakingEvent:
    return BreakingEvent(
        title="Major exchange hack",
        source="CoinDesk",
        url="https://coindesk.com/hack",
        panic_score=85,
        image_url=image_url,
    )


def _mock_llm(text: str | None = None) -> AsyncMock:
    """Wave 0.8.6.1 (alpha.34) Bonus — bump default text to ≥80 words so universal
    word-count gate (Wave 0.8.7 Bug 9) doesn't fire spuriously when WAVE_0_6_ENABLED
    leaks into the env. Tests that explicitly need short text still pass `text=`.
    """
    if text is None:
        text = "Tin nóng tài sản mã hóa: " + " ".join(["nội dung mở rộng"] * 30)
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
        """QO.07: Breaking now uses short disclaimer (DYOR) instead of full."""
        llm = _mock_llm()
        result = await generate_breaking_content(_event(), llm)
        assert "Tuyên bố miễn trừ" in result.content
        assert "DYOR" in result.content

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
        assert "300-400" in prompt

    async def test_notable_uses_shorter_target(self):
        llm = _mock_llm()
        await generate_breaking_content(_event(), llm, severity="notable")
        call_kwargs = llm.generate.call_args
        prompt = call_kwargs.kwargs.get("prompt", "") or call_kwargs.args[0]
        assert "200-300" in prompt

    async def test_llm_failure_propagates_exception(self):
        """v0.29.0 (A4): LLM errors propagate to caller for proper handling."""
        import pytest

        llm = AsyncMock()
        llm.generate = AsyncMock(side_effect=Exception("All LLMs failed"))
        with pytest.raises(Exception, match="All LLMs failed"):
            await generate_breaking_content(_event(), llm)

    async def test_raw_data_fallback_still_works_directly(self):
        """_raw_data_fallback() still available for explicit use by pipeline.
        QO.07: Now uses DISCLAIMER_SHORT instead of full DISCLAIMER.
        """
        from cic_daily_report.generators.article_generator import DISCLAIMER_SHORT

        result = _raw_data_fallback(_event())
        assert not result.ai_generated
        assert result.model_used == "raw_data"
        assert DISCLAIMER_SHORT in result.content
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


class TestSkipEnrichment:
    """v0.29.0 (B4): skip_enrichment skips article fetch."""

    async def test_skip_enrichment_skips_article_fetch(self):
        """When skip_enrichment=True, _fetch_article_text is NOT called."""
        llm = _mock_llm()
        event = _event()
        event.raw_data = {}  # No summary

        with patch(
            "cic_daily_report.breaking.content_generator._fetch_article_text",
        ) as mock_fetch:
            await generate_breaking_content(event, llm, skip_enrichment=True)

        mock_fetch.assert_not_called()

    async def test_no_skip_enrichment_fetches_article(self):
        """When skip_enrichment=False (default), article fetch is attempted."""
        llm = _mock_llm()
        event = _event()
        event.raw_data = {}  # No summary

        with patch(
            "cic_daily_report.breaking.content_generator._fetch_article_text",
            return_value="Article text",
        ) as mock_fetch:
            await generate_breaking_content(event, llm, skip_enrichment=False)

        mock_fetch.assert_called_once()


class TestDigestContent:
    """v0.29.0 (B5): Digest mode for multiple events."""

    async def test_generate_digest_content(self):
        from cic_daily_report.breaking.content_generator import generate_digest_content

        events = [
            BreakingEvent(
                title=f"Event {i}",
                source=f"Source{i}",
                url=f"https://example.com/{i}",
                panic_score=80,
            )
            for i in range(3)
        ]
        llm = _mock_llm()
        result = await generate_digest_content(events, llm)
        assert result.ai_generated
        assert result.word_count > 0

    async def test_digest_includes_all_source_links(self):
        from cic_daily_report.breaking.content_generator import generate_digest_content

        events = [
            BreakingEvent(title="A", source="CoinDesk", url="https://a.com", panic_score=80),
            BreakingEvent(title="B", source="Reuters", url="https://b.com", panic_score=70),
        ]
        llm = _mock_llm()
        result = await generate_digest_content(events, llm)
        assert "CoinDesk" in result.content
        assert "Reuters" in result.content

    async def test_digest_llm_failure_propagates(self):
        import pytest

        from cic_daily_report.breaking.content_generator import generate_digest_content

        events = [
            BreakingEvent(title="A", source="S", url="https://a.com", panic_score=80),
        ]
        llm = AsyncMock()
        llm.generate = AsyncMock(side_effect=Exception("LLM down"))
        with pytest.raises(Exception, match="LLM down"):
            await generate_digest_content(events, llm)


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


# ---------------------------------------------------------------------------
# Wave 0.8.7 (alpha.33) Bug 9 — universal word-count gate when Wave 0.6 ON
# ---------------------------------------------------------------------------


class TestBug9UniversalGate:
    """Tin Coinbase 1-đoạn (01/05) lọt qua because judge approved 1st-pass +
    word_count=72. Now: when Wave 0.6 ON (judge available / fail-open / skip),
    enforce >=80 words for any final output regardless of retry path.
    """

    async def test_short_judge_skipped_raises_when_wave06_on(self, monkeypatch):
        from cic_daily_report.adapters.llm_adapter import JudgeResult, LLMResponse
        from cic_daily_report.core.error_handler import LLMError

        monkeypatch.setenv("WAVE_0_6_ENABLED", "1")
        # 50 word-ish text - under 80 threshold. severity=notable → judge_skipped=True
        # since judge runs only for critical/important.
        short = "Tin nóng tài sản mã hóa: " + " ".join(["từ"] * 50)
        llm = AsyncMock()
        llm.generate = AsyncMock(return_value=LLMResponse(text=short, tokens_used=100, model="m"))
        # Judge would not be called for severity=notable, but stub for safety.
        llm.judge_factual_claims = AsyncMock(
            return_value=JudgeResult(verdict="approved", confidence=0.9)
        )
        llm.last_provider = "groq"
        with patch("cic_daily_report.breaking.rag_index.get_or_build_index") as mock_get:
            mock_get.return_value.query.return_value = []
            with pytest.raises(LLMError) as exc_info:
                await generate_breaking_content(_event(), llm, severity="notable")
        assert exc_info.value.source == "breaking_content_word_gate_universal"

    async def test_long_judge_skipped_passes(self, monkeypatch):
        from cic_daily_report.adapters.llm_adapter import LLMResponse

        monkeypatch.setenv("WAVE_0_6_ENABLED", "1")
        long_text = "Tin nóng tài sản mã hóa: " + " ".join(["từ"] * 120)
        llm = AsyncMock()
        llm.generate = AsyncMock(
            return_value=LLMResponse(text=long_text, tokens_used=200, model="m")
        )
        llm.last_provider = "groq"
        with patch("cic_daily_report.breaking.rag_index.get_or_build_index") as mock_get:
            mock_get.return_value.query.return_value = []
            result = await generate_breaking_content(_event(), llm, severity="notable")
        assert result.word_count >= 80
