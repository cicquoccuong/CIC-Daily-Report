"""Tests for collectors/macro_news_collector.py — all mocked (QO.47)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from cic_daily_report.collectors.macro_news_collector import (
    MacroHeadline,
    _parse_gdelt_date,
    collect_macro_news,
)

MODULE = "cic_daily_report.collectors.macro_news_collector"


def _mock_httpx_client(response_data: dict):
    """Create a mock httpx.AsyncClient returning JSON response."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = response_data
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


# --- Unit tests ---


class TestParseGdeltDate:
    def test_valid_date(self):
        assert _parse_gdelt_date("20260415T120000Z") == "2026-04-15T12:00:00Z"

    def test_empty_string(self):
        assert _parse_gdelt_date("") == ""

    def test_invalid_format(self):
        assert _parse_gdelt_date("not-a-date") == "not-a-date"


class TestMacroHeadline:
    def test_to_dict(self):
        h = MacroHeadline(
            title="Fed raises rates",
            source="reuters.com",
            url="https://reuters.com/1",
            timestamp="2026-04-15T12:00:00Z",
            provider="gdelt",
        )
        d = h.to_dict()
        assert d["title"] == "Fed raises rates"
        assert d["source"] == "reuters.com"
        assert d["provider"] == "gdelt"


# --- Integration tests (mocked HTTP) ---


class TestCollectMacroNews:
    async def test_gdelt_only_no_newsapi_key(self):
        """GDELT returns articles, NewsAPI skipped (no key)."""
        gdelt_response = {
            "articles": [
                {
                    "title": "Fed holds rates steady",
                    "url": "https://reuters.com/fed",
                    "domain": "reuters.com",
                    "seendate": "20260415T080000Z",
                },
                {
                    "title": "Bitcoin surges past 100K",
                    "url": "https://coindesk.com/btc",
                    "domain": "coindesk.com",
                    "seendate": "20260415T090000Z",
                },
            ]
        }
        gdelt_client = _mock_httpx_client(gdelt_response)

        # WHY: patch both AsyncClient calls — GDELT succeeds, NewsAPI skipped
        with (
            patch.dict("os.environ", {}, clear=True),
            patch(f"{MODULE}.httpx.AsyncClient", return_value=gdelt_client),
        ):
            result = await collect_macro_news()

        assert len(result) == 2
        assert result[0]["title"] == "Fed holds rates steady"
        assert result[0]["provider"] == "gdelt"

    async def test_both_sources_combined(self):
        """GDELT + NewsAPI results are combined and deduplicated."""
        gdelt_response = {
            "articles": [
                {
                    "title": "Fed holds rates",
                    "url": "https://reuters.com/1",
                    "domain": "reuters.com",
                    "seendate": "20260415T080000Z",
                },
            ]
        }
        newsapi_response = {
            "articles": [
                {
                    "title": "Inflation data released",
                    "url": "https://cnbc.com/1",
                    "source": {"name": "CNBC"},
                    "publishedAt": "2026-04-15T10:00:00Z",
                },
                {
                    "title": "Fed holds rates",  # duplicate of GDELT
                    "url": "https://reuters.com/2",
                    "source": {"name": "Reuters"},
                    "publishedAt": "2026-04-15T08:00:00Z",
                },
            ]
        }

        # Create two separate mock clients for GDELT and NewsAPI
        gdelt_resp = MagicMock()
        gdelt_resp.json.return_value = gdelt_response
        gdelt_resp.raise_for_status = MagicMock()

        newsapi_resp = MagicMock()
        newsapi_resp.json.return_value = newsapi_response
        newsapi_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[gdelt_resp, newsapi_resp])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.dict("os.environ", {"NEWSAPI_KEY": "test_key"}),
            patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await collect_macro_news()

        # 3 total - 1 duplicate = 2 unique
        assert len(result) == 2
        titles = {r["title"] for r in result}
        assert "Fed holds rates" in titles
        assert "Inflation data released" in titles

    async def test_gdelt_failure_newsapi_succeeds(self):
        """When GDELT fails, NewsAPI results still returned."""
        newsapi_response = {
            "articles": [
                {
                    "title": "GDP report",
                    "url": "https://cnbc.com/gdp",
                    "source": {"name": "CNBC"},
                    "publishedAt": "2026-04-15T10:00:00Z",
                },
            ]
        }

        # GDELT client fails
        gdelt_client = AsyncMock()
        gdelt_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        gdelt_client.__aenter__ = AsyncMock(return_value=gdelt_client)
        gdelt_client.__aexit__ = AsyncMock(return_value=False)

        # NewsAPI client succeeds
        newsapi_client = _mock_httpx_client(newsapi_response)

        # WHY: AsyncClient is called twice (GDELT then NewsAPI).
        # First call fails, second succeeds.
        with (
            patch.dict("os.environ", {"NEWSAPI_KEY": "test_key"}),
            patch(f"{MODULE}.httpx.AsyncClient", side_effect=[gdelt_client, newsapi_client]),
        ):
            result = await collect_macro_news()

        assert len(result) == 1
        assert result[0]["title"] == "GDP report"
        assert result[0]["provider"] == "newsapi"

    async def test_both_fail_returns_empty(self):
        """When both GDELT and NewsAPI fail, returns empty list."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("All down"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.dict("os.environ", {"NEWSAPI_KEY": "test_key"}),
            patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await collect_macro_news()

        assert result == []

    async def test_gdelt_empty_articles(self):
        """GDELT returns no articles — not an error."""
        gdelt_response = {"articles": []}
        mock_client = _mock_httpx_client(gdelt_response)

        with (
            patch.dict("os.environ", {}, clear=True),
            patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await collect_macro_news()

        assert result == []

    async def test_newsapi_missing_source_name(self):
        """NewsAPI article without source name uses default."""
        newsapi_response = {
            "articles": [
                {
                    "title": "Test headline",
                    "url": "https://example.com/1",
                    "source": {},
                    "publishedAt": "2026-04-15T10:00:00Z",
                },
            ]
        }

        gdelt_resp = MagicMock()
        gdelt_resp.json.return_value = {"articles": []}
        gdelt_resp.raise_for_status = MagicMock()

        newsapi_resp = MagicMock()
        newsapi_resp.json.return_value = newsapi_response
        newsapi_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[gdelt_resp, newsapi_resp])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.dict("os.environ", {"NEWSAPI_KEY": "test_key"}),
            patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await collect_macro_news()

        assert len(result) == 1
        assert result[0]["source"] == "NewsAPI"  # default fallback

    async def test_gdelt_http_error(self):
        """GDELT HTTP error handled gracefully."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock(status_code=500)
        )
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.dict("os.environ", {}, clear=True),
            patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await collect_macro_news()

        assert result == []

    async def test_newsapi_http_error(self):
        """NewsAPI HTTP error handled gracefully, GDELT still works."""
        gdelt_response = {
            "articles": [
                {
                    "title": "Fed news",
                    "url": "https://reuters.com/1",
                    "domain": "reuters.com",
                    "seendate": "20260415T080000Z",
                },
            ]
        }

        gdelt_resp = MagicMock()
        gdelt_resp.json.return_value = gdelt_response
        gdelt_resp.raise_for_status = MagicMock()

        newsapi_resp = MagicMock()
        newsapi_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "429", request=MagicMock(), response=MagicMock(status_code=429)
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[gdelt_resp, newsapi_resp])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.dict("os.environ", {"NEWSAPI_KEY": "test_key"}),
            patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await collect_macro_news()

        assert len(result) == 1
        assert result[0]["provider"] == "gdelt"

    async def test_filters_empty_titles(self):
        """Headlines with empty titles are skipped."""
        gdelt_response = {
            "articles": [
                {
                    "title": "",
                    "url": "https://example.com/1",
                    "domain": "example.com",
                    "seendate": "20260415T080000Z",
                },
                {
                    "title": "Valid headline",
                    "url": "https://example.com/2",
                    "domain": "example.com",
                    "seendate": "20260415T090000Z",
                },
            ]
        }
        mock_client = _mock_httpx_client(gdelt_response)

        with (
            patch.dict("os.environ", {}, clear=True),
            patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await collect_macro_news()

        assert len(result) == 1
        assert result[0]["title"] == "Valid headline"
