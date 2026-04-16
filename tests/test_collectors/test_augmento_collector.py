"""Tests for collectors/augmento_collector.py — all mocked (QO.35)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from cic_daily_report.collectors.augmento_collector import (
    AssetSentiment,
    SentimentResult,
    collect_augmento_sentiment,
)

MODULE = "cic_daily_report.collectors.augmento_collector"


def _mock_httpx_client(response_data: dict):
    """Create a mock httpx.AsyncClient that returns response_data as JSON."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = response_data
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


# --- Unit tests: SentimentResult ---


class TestSentimentResult:
    def test_to_dict_empty(self):
        result = SentimentResult()
        assert result.to_dict() == {}

    def test_to_dict_with_data(self):
        result = SentimentResult(
            sentiments={
                "BTC": AssetSentiment(
                    asset="BTC", bullish=60.0, bearish=25.0, neutral=15.0, source_count=1000
                ),
            }
        )
        d = result.to_dict()
        assert "BTC" in d
        assert d["BTC"]["bullish"] == 60.0
        assert d["BTC"]["bearish"] == 25.0
        assert d["BTC"]["neutral"] == 15.0
        assert d["BTC"]["source_count"] == 1000

    def test_format_for_llm_empty(self):
        result = SentimentResult()
        assert result.format_for_llm() == ""

    def test_format_for_llm_with_data(self):
        result = SentimentResult(
            sentiments={
                "BTC": AssetSentiment("BTC", 55.0, 30.0, 15.0, 500),
                "ETH": AssetSentiment("ETH", 40.0, 35.0, 25.0, 300),
            }
        )
        text = result.format_for_llm()
        assert "SOCIAL SENTIMENT" in text
        assert "BTC" in text
        assert "ETH" in text
        assert "55.0%" in text
        assert "n=500" in text


class TestAssetSentiment:
    def test_dataclass_fields(self):
        s = AssetSentiment(asset="BTC", bullish=60.0, bearish=25.0, neutral=15.0, source_count=100)
        assert s.asset == "BTC"
        assert s.bullish == 60.0


# --- Integration tests (mocked HTTP) ---


class TestCollectAugmentoSentiment:
    async def test_successful_fetch(self):
        """API returns valid sentiment data for BTC and ETH."""
        api_response = {
            "bitcoin": {"bullish": 600, "bearish": 250, "neutral": 150},
            "ethereum": {"bullish": 400, "bearish": 350, "neutral": 250},
        }
        mock_client = _mock_httpx_client(api_response)

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_augmento_sentiment()

        assert "BTC" in result
        assert "ETH" in result
        # BTC: 600/1000 = 60%
        assert result["BTC"]["bullish"] == 60.0
        assert result["BTC"]["bearish"] == 25.0
        assert result["BTC"]["neutral"] == 15.0
        assert result["BTC"]["source_count"] == 1000
        # ETH: 400/1000 = 40%
        assert result["ETH"]["bullish"] == 40.0
        assert result["ETH"]["source_count"] == 1000

    async def test_partial_data_only_btc(self):
        """API returns data only for bitcoin, not ethereum."""
        api_response = {
            "bitcoin": {"bullish": 100, "bearish": 50, "neutral": 50},
        }
        mock_client = _mock_httpx_client(api_response)

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_augmento_sentiment()

        assert "BTC" in result
        assert "ETH" not in result
        assert result["BTC"]["bullish"] == 50.0  # 100/200

    async def test_zero_counts_skipped(self):
        """If all counts are 0, asset is skipped (avoid division by zero)."""
        api_response = {
            "bitcoin": {"bullish": 0, "bearish": 0, "neutral": 0},
            "ethereum": {"bullish": 100, "bearish": 50, "neutral": 50},
        }
        mock_client = _mock_httpx_client(api_response)

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_augmento_sentiment()

        assert "BTC" not in result
        assert "ETH" in result

    async def test_unexpected_format_returns_empty(self):
        """Non-dict response returns empty dict."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = "not a dict"
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_augmento_sentiment()

        assert result == {}

    async def test_timeout_returns_empty(self):
        """Timeout returns empty dict."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_augmento_sentiment()

        assert result == {}

    async def test_http_error_returns_empty(self):
        """HTTP error returns empty dict."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock(status_code=500)
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_augmento_sentiment()

        assert result == {}

    async def test_generic_exception_returns_empty(self):
        """Any unexpected exception returns empty dict."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Unexpected"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_augmento_sentiment()

        assert result == {}

    async def test_asset_data_not_dict_skipped(self):
        """If asset data is not a dict, it is skipped."""
        api_response = {
            "bitcoin": "invalid",
            "ethereum": {"bullish": 100, "bearish": 50, "neutral": 50},
        }
        mock_client = _mock_httpx_client(api_response)

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_augmento_sentiment()

        assert "BTC" not in result
        assert "ETH" in result
