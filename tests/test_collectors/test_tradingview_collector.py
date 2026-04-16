"""Tests for collectors/tradingview_collector.py — all mocked (QO.34)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from cic_daily_report.collectors.tradingview_collector import (
    MAX_IDEAS,
    TradingIdea,
    _sanitize_text,
    collect_tradingview_ideas,
)

MODULE = "cic_daily_report.collectors.tradingview_collector"

# --- Sample RSS XML for testing ---

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>TradingView Ideas — Crypto</title>
  <item>
    <title>BTC breakout above 100K resistance</title>
    <link>https://www.tradingview.com/chart/BTCUSD/idea1/</link>
    <author>trader_joe</author>
    <description>Bitcoin showing strong momentum &amp; breaking key resistance</description>
    <pubDate>Tue, 15 Apr 2026 08:00:00 GMT</pubDate>
  </item>
  <item>
    <title>ETH &lt;b&gt;bullish&lt;/b&gt; pattern forming</title>
    <link>https://www.tradingview.com/chart/ETHUSD/idea2/</link>
    <author>crypto_analyst</author>
    <description>Ethereum forming a cup &amp; handle pattern on the daily</description>
    <pubDate>Tue, 15 Apr 2026 07:30:00 GMT</pubDate>
  </item>
  <item>
    <title></title>
    <link>https://www.tradingview.com/chart/invalid/</link>
    <author>no_title</author>
    <description>This has no title</description>
  </item>
</channel>
</rss>"""


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
        assert _sanitize_text("<b>bold</b> text") == "bold text"

    def test_decodes_entities(self):
        assert _sanitize_text("A &amp; B") == "A & B"

    def test_normalizes_whitespace(self):
        assert _sanitize_text("  too   many   spaces  ") == "too many spaces"

    def test_removes_control_chars(self):
        assert _sanitize_text("hello\x00world") == "helloworld"

    def test_empty_string(self):
        assert _sanitize_text("") == ""


class TestTradingIdea:
    def test_to_dict(self):
        idea = TradingIdea(
            title="BTC breakout",
            author="trader_joe",
            summary="Test summary",
            url="https://tradingview.com/idea/1",
            published_date="2026-04-15T08:00:00Z",
        )
        d = idea.to_dict()
        assert d["title"] == "BTC breakout"
        assert d["author"] == "trader_joe"
        assert d["source"] == "TradingView"
        assert "collected_at" in d

    def test_to_dict_empty_fields(self):
        idea = TradingIdea(
            title="Test",
            author="",
            summary="",
            url="https://x.com",
            published_date="",
        )
        d = idea.to_dict()
        assert d["author"] == ""
        assert d["summary"] == ""


# --- Integration tests (mocked HTTP) ---


class TestCollectTradingviewIdeas:
    async def test_successful_fetch(self):
        """RSS feed returns valid ideas — 2 valid items (3rd has no title)."""
        mock_client = _mock_httpx_success(SAMPLE_RSS)

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_tradingview_ideas()

        # 3 items in RSS, but 1 has empty title → should get 2
        assert len(result) == 2
        assert result[0]["title"] == "BTC breakout above 100K resistance"
        assert result[0]["author"] == "trader_joe"
        assert result[0]["source"] == "TradingView"
        assert result[0]["url"] == "https://www.tradingview.com/chart/BTCUSD/idea1/"

        # HTML in title should be sanitized
        assert result[1]["title"] == "ETH bullish pattern forming"

    async def test_html_in_summary_sanitized(self):
        """HTML entities in summary are decoded."""
        mock_client = _mock_httpx_success(SAMPLE_RSS)

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_tradingview_ideas()

        # "Bitcoin showing strong momentum &amp; breaking key resistance"
        assert "&amp;" not in result[0]["summary"]
        assert "&" in result[0]["summary"]

    async def test_timeout_returns_empty(self):
        """Timeout returns empty list (never breaks pipeline)."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_tradingview_ideas()

        assert result == []

    async def test_http_error_returns_empty(self):
        """HTTP error returns empty list."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "403", request=MagicMock(), response=MagicMock(status_code=403)
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_tradingview_ideas()

        assert result == []

    async def test_generic_exception_returns_empty(self):
        """Any unexpected exception returns empty list."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Unexpected"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_tradingview_ideas()

        assert result == []

    async def test_empty_feed_returns_empty(self):
        """Empty RSS feed returns empty list."""
        empty_rss = """<?xml version="1.0"?>
        <rss version="2.0"><channel><title>Empty</title></channel></rss>"""
        mock_client = _mock_httpx_success(empty_rss)

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_tradingview_ideas()

        assert result == []

    async def test_max_ideas_limit(self):
        """At most MAX_IDEAS ideas are returned."""
        items = ""
        for i in range(30):
            items += f"""
            <item>
              <title>Idea {i}</title>
              <link>https://tradingview.com/idea/{i}</link>
              <author>author_{i}</author>
              <description>Summary {i}</description>
            </item>"""

        rss = f"""<?xml version="1.0"?>
        <rss version="2.0"><channel><title>Test</title>{items}</channel></rss>"""
        mock_client = _mock_httpx_success(rss)

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_tradingview_ideas()

        assert len(result) == MAX_IDEAS
