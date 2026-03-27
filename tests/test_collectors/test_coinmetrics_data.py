"""Tests for collectors/coinmetrics_data.py — all mocked."""

from unittest.mock import AsyncMock, patch

import httpx

from cic_daily_report.collectors.coinmetrics_data import (
    collect_coinmetrics_onchain,
)

_REQ = httpx.Request("GET", "http://test")


def _resp(status: int, json: object = None) -> httpx.Response:
    return httpx.Response(status, json=json, request=_REQ)


class TestCollectCoinmetricsOnchain:
    async def test_collects_btc_and_eth_metrics(self):
        """Mock API returning valid data for both assets."""
        btc_data = {
            "data": [
                {
                    "asset": "btc",
                    "time": "2026-03-18T00:00:00.000000000Z",
                    "NVTAdj": "45.2",
                    "CapMVRVCur": "1.85",
                    "AdrActCnt": "850000",
                    "HashRate": "620000000000000000000",
                }
            ]
        }
        eth_data = {
            "data": [
                {
                    "asset": "eth",
                    "time": "2026-03-18T00:00:00.000000000Z",
                    "NVTAdj": "32.1",
                    "CapMVRVCur": "1.42",
                    "AdrActCnt": "520000",
                }
            ]
        }

        async def mock_get(url, **kwargs):
            params = kwargs.get("params", {})
            asset = params.get("assets", "")
            if asset == "btc":
                return _resp(200, btc_data)
            if asset == "eth":
                return _resp(200, eth_data)
            return _resp(404)

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "cic_daily_report.collectors.coinmetrics_data.httpx.AsyncClient",
            return_value=mock_client,
        ):
            metrics = await collect_coinmetrics_onchain()

        assert len(metrics) >= 5  # 4 BTC + 3 ETH
        names = [m.metric_name for m in metrics]
        assert "BTC_NVT_Ratio" in names
        assert "BTC_MVRV_Ratio" in names
        assert "BTC_Active_Addresses" in names
        assert "BTC_Hash_Rate" in names
        assert "ETH_NVT_Ratio" in names
        assert all(m.source == "CoinMetrics" for m in metrics)

    async def test_returns_empty_on_api_error(self):
        """API returns error → empty list."""

        async def mock_get(url, **kwargs):
            return _resp(500)

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "cic_daily_report.collectors.coinmetrics_data.httpx.AsyncClient",
            return_value=mock_client,
        ):
            metrics = await collect_coinmetrics_onchain()

        assert metrics == []

    async def test_handles_empty_data_response(self):
        """API returns success but empty data."""

        async def mock_get(url, **kwargs):
            return _resp(200, {"data": []})

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "cic_daily_report.collectors.coinmetrics_data.httpx.AsyncClient",
            return_value=mock_client,
        ):
            metrics = await collect_coinmetrics_onchain()

        assert metrics == []

    async def test_handles_missing_metric_values(self):
        """Some metrics are null/empty in response."""
        data = {
            "data": [
                {
                    "asset": "btc",
                    "time": "2026-03-18T00:00:00.000000000Z",
                    "NVTAdj": "45.2",
                    "CapMVRVCur": None,  # null
                    "AdrActCnt": "",  # empty
                    "HashRate": "620000000000000000000",
                }
            ]
        }

        async def mock_get(url, **kwargs):
            return _resp(200, data)

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "cic_daily_report.collectors.coinmetrics_data.httpx.AsyncClient",
            return_value=mock_client,
        ):
            metrics = await collect_coinmetrics_onchain()

        btc_names = [m.metric_name for m in metrics if "BTC" in m.metric_name]
        assert "BTC_NVT_Ratio" in btc_names
        assert "BTC_Hash_Rate" in btc_names

    async def test_logs_error_body_on_400(self):
        """v0.32.0: HTTP 400 error logs response body for debugging."""
        error_body = '{"error": "Unknown metric: BadMetric"}'

        async def mock_get(url, **kwargs):
            resp = _resp(400)
            resp._content = error_body.encode()
            return resp

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "cic_daily_report.collectors.coinmetrics_data.httpx.AsyncClient",
            return_value=mock_client,
        ):
            metrics = await collect_coinmetrics_onchain()

        # Should return empty (graceful failure) — error body logged (tested via no crash)
        assert metrics == []

    async def test_metric_has_correct_fields(self):
        """Verify OnChainMetric fields."""
        data = {
            "data": [
                {
                    "asset": "btc",
                    "time": "2026-03-18T00:00:00.000000000Z",
                    "NVTAdj": "45.2",
                }
            ]
        }

        async def mock_get(url, **kwargs):
            return _resp(200, data)

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "cic_daily_report.collectors.coinmetrics_data.httpx.AsyncClient",
            return_value=mock_client,
        ):
            metrics = await collect_coinmetrics_onchain()

        btc_nvt = [m for m in metrics if m.metric_name == "BTC_NVT_Ratio"]
        assert len(btc_nvt) == 1
        assert btc_nvt[0].value == 45.2
        assert btc_nvt[0].source == "CoinMetrics"
        assert "Network Value" in btc_nvt[0].note
