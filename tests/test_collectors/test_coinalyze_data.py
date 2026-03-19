"""Tests for collectors/coinalyze_data.py — all mocked."""

from unittest.mock import AsyncMock, patch

import httpx

from cic_daily_report.collectors.coinalyze_data import (
    SYMBOLS,
    _symbol_to_coin,
    collect_coinalyze_derivatives,
)
from cic_daily_report.collectors.onchain_data import OnChainMetric

_REQ = httpx.Request("GET", "http://test")


def _resp(status: int, json: object = None) -> httpx.Response:
    return httpx.Response(status, json=json, request=_REQ)


class TestSymbolToCoin:
    def test_btc_symbol(self):
        assert _symbol_to_coin(SYMBOLS["BTC"]) == "BTC"

    def test_eth_symbol(self):
        assert _symbol_to_coin(SYMBOLS["ETH"]) == "ETH"

    def test_unknown_symbol(self):
        assert _symbol_to_coin("SOLUSDT_PERP.A") == "SOL"


class TestCollectCoinalyzeDerivatives:
    async def test_returns_empty_without_api_key(self):
        with patch.dict("os.environ", {}, clear=True):
            metrics = await collect_coinalyze_derivatives()
        assert metrics == []

    async def test_collects_all_metric_types(self):
        """Mock all 4 endpoints returning valid data."""
        funding_data = [
            {"symbol": "BTCUSDT_PERP.A", "value": 0.0001},
            {"symbol": "ETHUSDT_PERP.A", "value": 0.0002},
        ]
        oi_data = [
            {"symbol": "BTCUSDT_PERP.A", "value": 15000000000},
            {"symbol": "ETHUSDT_PERP.A", "value": 8000000000},
        ]
        liq_data = [
            {
                "symbol": "BTCUSDT_PERP.A",
                "history": [{"t": 1710000000, "l": 5000000, "s": 3000000}],
            },
        ]
        ls_data = [
            {
                "symbol": "BTCUSDT_PERP.A",
                "history": [{"t": 1710000000, "r": 1.05, "l": 51.2, "s": 48.8}],
            },
            {
                "symbol": "ETHUSDT_PERP.A",
                "history": [{"t": 1710000000, "r": 0.98, "l": 49.5, "s": 50.5}],
            },
        ]

        async def mock_get(url, **kwargs):
            if "funding-rate" in url:
                return _resp(200, funding_data)
            if "open-interest" in url:
                return _resp(200, oi_data)
            if "liquidation" in url:
                return _resp(200, liq_data)
            if "long-short" in url:
                return _resp(200, ls_data)
            return _resp(404)

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch.dict("os.environ", {"COINALYZE_API_KEY": "test-key"}),
            patch(
                "cic_daily_report.collectors.coinalyze_data.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            metrics = await collect_coinalyze_derivatives()

        # Should have: 2 funding + 2 OI + 1 liquidation + 2 L/S = 7
        assert len(metrics) >= 5
        names = [m.metric_name for m in metrics]
        assert "BTC_Funding_Rate" in names
        assert "ETH_Funding_Rate" in names
        assert "BTC_Open_Interest" in names
        assert all(isinstance(m, OnChainMetric) for m in metrics)
        assert all(m.source == "Coinalyze" for m in metrics)

    async def test_graceful_on_http_error(self):
        """All endpoints fail → returns empty list."""

        async def mock_get(url, **kwargs):
            raise httpx.HTTPStatusError("500", request=_REQ, response=_resp(500))

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch.dict("os.environ", {"COINALYZE_API_KEY": "test-key"}),
            patch(
                "cic_daily_report.collectors.coinalyze_data.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            metrics = await collect_coinalyze_derivatives()

        assert metrics == []

    async def test_handles_error_dict_response(self):
        """API returns error dict instead of array → graceful empty."""

        async def mock_get(url, **kwargs):
            return _resp(200, {"error": "invalid api_key", "message": "Unauthorized"})

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch.dict("os.environ", {"COINALYZE_API_KEY": "bad-key"}),
            patch(
                "cic_daily_report.collectors.coinalyze_data.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            metrics = await collect_coinalyze_derivatives()

        assert metrics == []

    async def test_partial_endpoint_failure(self):
        """Some endpoints fail, others succeed."""

        async def mock_get(url, **kwargs):
            if "funding-rate" in url:
                return _resp(
                    200,
                    [{"symbol": "BTCUSDT_PERP.A", "value": 0.0001}],
                )
            raise httpx.TimeoutException("timeout")

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch.dict("os.environ", {"COINALYZE_API_KEY": "test-key"}),
            patch(
                "cic_daily_report.collectors.coinalyze_data.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            metrics = await collect_coinalyze_derivatives()

        assert len(metrics) >= 1
        assert metrics[0].metric_name == "BTC_Funding_Rate"
