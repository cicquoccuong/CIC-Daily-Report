"""Tests for collectors/crypto_calendar.py — all mocked (QO.39)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from cic_daily_report.collectors.crypto_calendar import (
    CryptoEvent,
    _extract_category_from_entry,
    _extract_coin_from_title,
    _is_within_horizon,
    _sanitize_text,
    collect_crypto_calendar,
)

MODULE = "cic_daily_report.collectors.crypto_calendar"


def _future_date(days_ahead: int = 3) -> str:
    """Return an ISO date N days from now."""
    dt = datetime.now(timezone.utc) + timedelta(days=days_ahead)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _past_date(days_ago: int = 3) -> str:
    """Return an ISO date N days ago."""
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_rss(items: list[dict]) -> str:
    """Build a minimal RSS XML string from item dicts."""
    entries = ""
    for item in items:
        title = item.get("title", "")
        link = item.get("link", "")
        pub = item.get("pubDate", "")
        desc = item.get("description", "")
        tags_xml = ""
        for tag in item.get("tags", []):
            tags_xml += f"<category>{tag}</category>"
        entries += f"""
        <item>
          <title>{title}</title>
          <link>{link}</link>
          <pubDate>{pub}</pubDate>
          <description>{desc}</description>
          {tags_xml}
        </item>"""
    return f"""<?xml version="1.0"?>
    <rss version="2.0"><channel><title>Test</title>{entries}</channel></rss>"""


def _mock_httpx_success(text: str):
    """Create mock httpx client returning the given text."""
    mock_resp = MagicMock()
    mock_resp.text = text
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


# --- Unit tests ---


class TestSanitizeText:
    def test_strips_html(self):
        assert _sanitize_text("<p>Hello</p>") == "Hello"

    def test_empty(self):
        assert _sanitize_text("") == ""


class TestExtractCoinFromTitle:
    def test_ticker_in_parens(self):
        assert _extract_coin_from_title("Bitcoin (BTC) Halving") == "BTC"

    def test_no_ticker(self):
        assert _extract_coin_from_title("Ethereum Mainnet Upgrade") == "Ethereum"

    def test_empty(self):
        assert _extract_coin_from_title("") == "Unknown"


class TestExtractCategoryFromEntry:
    def test_from_tags(self):
        entry = {"title": "Event", "tags": [{"term": "mainnet_launch"}]}
        assert _extract_category_from_entry(entry) == "mainnet_launch"

    def test_from_title_keywords(self):
        entry = {"title": "Major Partnership Announcement", "tags": []}
        assert _extract_category_from_entry(entry) == "partnership"

    def test_fallback_other(self):
        entry = {"title": "Something random", "tags": []}
        assert _extract_category_from_entry(entry) == "other"


class TestIsWithinHorizon:
    def test_future_within(self):
        future = _future_date(3)
        assert _is_within_horizon(future, 7) is True

    def test_future_beyond(self):
        future = _future_date(10)
        assert _is_within_horizon(future, 7) is False

    def test_past_date(self):
        past = _past_date(2)
        assert _is_within_horizon(past, 7) is False

    def test_empty_date_returns_true(self):
        """Empty date = include (conservative approach)."""
        assert _is_within_horizon("", 7) is True

    def test_unparseable_date_returns_true(self):
        """Unparseable date = include (conservative approach)."""
        assert _is_within_horizon("not-a-date", 7) is True


class TestCryptoEvent:
    def test_to_dict(self):
        ev = CryptoEvent(
            title="Bitcoin Halving",
            coin="BTC",
            date="2026-04-20T00:00:00Z",
            category="hard_fork",
            source_url="https://coinmarketcal.com/event/123",
        )
        d = ev.to_dict()
        assert d["title"] == "Bitcoin Halving"
        assert d["coin"] == "BTC"
        assert d["source"] == "CoinMarketCal"


# --- Integration tests (mocked HTTP) ---


class TestCollectCryptoCalendar:
    async def test_successful_fetch(self):
        """RSS with 2 valid items returns 2 events."""
        rss = _make_rss(
            [
                {
                    "title": "Bitcoin (BTC) Halving",
                    "link": "https://coinmarketcal.com/event/1",
                    "description": "The next halving event",
                },
                {
                    "title": "Ethereum (ETH) Mainnet Upgrade",
                    "link": "https://coinmarketcal.com/event/2",
                    "description": "Dencun upgrade",
                },
            ]
        )
        mock_client = _mock_httpx_success(rss)

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            # WHY patch _is_within_horizon: RSS items have no dates → default True
            result = await collect_crypto_calendar()

        assert len(result) == 2
        assert result[0]["coin"] == "BTC"
        assert result[0]["source"] == "CoinMarketCal"
        assert result[1]["coin"] == "ETH"

    async def test_filters_items_without_title(self):
        """Items with empty title are skipped."""
        rss = _make_rss(
            [
                {"title": "", "link": "https://coinmarketcal.com/event/1"},
                {"title": "Valid Event", "link": "https://coinmarketcal.com/event/2"},
            ]
        )
        mock_client = _mock_httpx_success(rss)

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_crypto_calendar()

        assert len(result) == 1
        assert result[0]["title"] == "Valid Event"

    async def test_timeout_returns_empty(self):
        """Timeout returns empty list."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_crypto_calendar()

        assert result == []

    async def test_http_error_returns_empty(self):
        """HTTP error returns empty list."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=MagicMock(status_code=404)
        )
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_crypto_calendar()

        assert result == []

    async def test_generic_exception_returns_empty(self):
        """Any unexpected exception returns empty list."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Unexpected"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_crypto_calendar()

        assert result == []

    async def test_empty_feed_returns_empty(self):
        """Empty RSS returns empty list."""
        rss = _make_rss([])
        mock_client = _mock_httpx_success(rss)

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_crypto_calendar()

        assert result == []

    async def test_category_extraction(self):
        """Category inferred from title keywords when no tags."""
        rss = _make_rss(
            [
                {
                    "title": "Token Burn Event for XRP",
                    "link": "https://coinmarketcal.com/event/1",
                },
            ]
        )
        mock_client = _mock_httpx_success(rss)

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_crypto_calendar()

        assert result[0]["category"] == "token_burn"
