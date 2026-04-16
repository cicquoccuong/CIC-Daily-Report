"""Tests for breaking/event_detector.py — all mocked."""

from unittest.mock import AsyncMock, patch

import pytest

from cic_daily_report.breaking.event_detector import (
    CRYPTOPANIC_API_URL,
    BreakingEvent,
    DetectionConfig,
    _calculate_panic_score,
    _evaluate_items,
    _match_keywords,
    detect_breaking_events,
)
from cic_daily_report.core.error_handler import CollectorError, ConfigError


class TestCryptoPanicAPIURL:
    """v0.32.0: Verify API URL is v2 (consistent with cryptopanic_client.py)."""

    def test_uses_v2_api(self):
        assert "/developer/v2/" in CRYPTOPANIC_API_URL
        assert "/v1/" not in CRYPTOPANIC_API_URL


def _make_item(title="BTC news", panic_votes=None, source_title="CoinDesk", image_url=None):
    """Helper to create a CryptoPanic-style item."""
    votes = panic_votes or {}
    item = {
        "title": title,
        "source": {"title": source_title},
        "url": f"https://example.com/{title.replace(' ', '-')}",
        "votes": votes,
    }
    if image_url:
        item["metadata"] = {"image": image_url}
    return item


class TestBreakingEvent:
    def test_trigger_reason_score(self):
        e = BreakingEvent(title="Test", source="src", url="", panic_score=80)
        assert "panic_score=80" in e.trigger_reason

    def test_trigger_reason_keywords(self):
        e = BreakingEvent(
            title="Test", source="src", url="", panic_score=0, matched_keywords=["hack"]
        )
        assert "keywords=hack" in e.trigger_reason

    def test_trigger_reason_both(self):
        e = BreakingEvent(
            title="Test", source="src", url="", panic_score=80, matched_keywords=["crash"]
        )
        assert "panic_score" in e.trigger_reason
        assert "keywords" in e.trigger_reason


class TestCalculatePanicScore:
    def test_empty_votes(self):
        assert _calculate_panic_score({}) == 0

    def test_all_negative(self):
        score = _calculate_panic_score({"negative": 10, "toxic": 5, "disliked": 5})
        assert score > 0

    def test_all_positive(self):
        score = _calculate_panic_score({"positive": 10, "liked": 5, "important": 5})
        assert score == 0

    def test_mixed(self):
        score = _calculate_panic_score(
            {"negative": 5, "toxic": 0, "disliked": 0, "positive": 5, "liked": 0, "important": 0}
        )
        assert score == 50

    def test_capped_at_100(self):
        score = _calculate_panic_score({"negative": 100, "toxic": 100, "disliked": 100})
        assert score <= 100


class TestMatchKeywords:
    def test_no_match(self):
        assert _match_keywords("Bitcoin goes up", ["hack", "crash"]) == []

    def test_single_match(self):
        assert _match_keywords("Exchange hack discovered", ["hack", "crash"]) == ["hack"]

    def test_multiple_matches_with_crypto_context(self):
        """v0.29.0 (C2): CONTEXT_REQUIRED keywords match when crypto context present."""
        result = _match_keywords("SEC ban causes crypto crash", ["SEC", "ban", "crash"])
        assert "SEC" in result
        assert "ban" in result
        assert "crash" in result

    def test_context_required_without_crypto_context(self):
        """v0.29.0 (C2): CONTEXT_REQUIRED keywords don't match without crypto context."""
        result = _match_keywords("SEC ban causes crash", ["SEC", "ban", "crash"])
        assert result == []  # No crypto context words in title

    def test_always_trigger_without_crypto_context(self):
        """v0.29.0 (C2): ALWAYS_TRIGGER keywords match regardless of context."""
        result = _match_keywords("Major exploit discovered in system", ["exploit", "crash"])
        assert "exploit" in result
        assert "crash" not in result  # CONTEXT_REQUIRED, no crypto context

    def test_case_insensitive(self):
        assert _match_keywords("MAJOR HACK ALERT", ["hack"]) == ["hack"]


class TestEvaluateItems:
    def test_score_triggered(self):
        # WHY "Bitcoin event": QO.15 early filter requires crypto-relevant title
        items = [_make_item("Bitcoin event", {"negative": 80, "toxic": 20})]
        cfg = DetectionConfig(panic_threshold=50)
        events = _evaluate_items(items, cfg)
        assert len(events) == 1

    def test_keyword_triggered(self):
        items = [_make_item("Exchange hack found")]
        cfg = DetectionConfig(panic_threshold=99)
        events = _evaluate_items(items, cfg)
        assert len(events) == 1
        assert "hack" in events[0].matched_keywords

    def test_no_trigger(self):
        items = [_make_item("Normal market update", {"positive": 10})]
        cfg = DetectionConfig(panic_threshold=70)
        events = _evaluate_items(items, cfg)
        assert len(events) == 0

    def test_empty_items(self):
        events = _evaluate_items([], DetectionConfig())
        assert events == []

    def test_source_extraction(self):
        items = [_make_item("Hack alert", source_title="Reuters")]
        cfg = DetectionConfig()
        events = _evaluate_items(items, cfg)
        assert events[0].source == "Reuters"

    def test_image_url_extracted_from_metadata(self):
        """FR25: image_url extracted from CryptoPanic metadata."""
        items = [
            _make_item(
                "Exchange hack",
                image_url="https://example.com/image.jpg",
            )
        ]
        cfg = DetectionConfig()
        events = _evaluate_items(items, cfg)
        assert len(events) == 1
        assert events[0].image_url == "https://example.com/image.jpg"

    def test_image_url_none_when_no_metadata(self):
        """FR25: image_url is None when no metadata present."""
        items = [_make_item("Exchange hack")]
        cfg = DetectionConfig()
        events = _evaluate_items(items, cfg)
        assert len(events) == 1
        assert events[0].image_url is None


class TestDetectBreakingEvents:
    """Tests that call detect_breaking_events() must bypass file cache."""

    _cache_patch = patch("cic_daily_report.breaking.event_detector.get_cached", return_value=None)

    async def test_missing_api_key(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ConfigError, match="CRYPTOPANIC_API_KEY"):
                await detect_breaking_events(api_key="")

    async def test_api_error_raises_collector_error(self):
        with (
            self._cache_patch,
            patch(
                "cic_daily_report.breaking.event_detector._fetch_cryptopanic",
                new_callable=AsyncMock,
                side_effect=Exception("timeout"),
            ),
        ):
            with pytest.raises(CollectorError, match="CryptoPanic API error"):
                await detect_breaking_events(api_key="test-key")

    async def test_detects_events(self):
        mock_items = [
            _make_item("Major hack on exchange", {"negative": 50, "toxic": 30}),
            _make_item("Normal update", {"positive": 10}),
        ]
        with (
            self._cache_patch,
            patch(
                "cic_daily_report.breaking.event_detector._fetch_cryptopanic",
                new_callable=AsyncMock,
                return_value=mock_items,
            ),
        ):
            events = await detect_breaking_events(api_key="test-key")
            assert len(events) >= 1
            assert events[0].title == "Major hack on exchange"

    async def test_empty_results(self):
        with (
            self._cache_patch,
            patch(
                "cic_daily_report.breaking.event_detector._fetch_cryptopanic",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            events = await detect_breaking_events(api_key="test-key")
            assert events == []

    async def test_custom_config(self):
        # WHY "Bitcoin alert": QO.15 early filter requires crypto-relevant title
        mock_items = [_make_item("Bitcoin alert", {"negative": 5, "positive": 5})]
        cfg = DetectionConfig(panic_threshold=10, keyword_triggers=["alert"])
        with (
            self._cache_patch,
            patch(
                "cic_daily_report.breaking.event_detector._fetch_cryptopanic",
                new_callable=AsyncMock,
                return_value=mock_items,
            ),
        ):
            events = await detect_breaking_events(config=cfg, api_key="test-key")
            assert len(events) == 1
