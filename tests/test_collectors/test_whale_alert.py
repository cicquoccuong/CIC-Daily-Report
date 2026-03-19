"""Tests for collectors/whale_alert.py — all mocked."""

from unittest.mock import AsyncMock, patch

import httpx

from cic_daily_report.collectors.whale_alert import (
    WhaleAlertSummary,
    WhaleTransaction,
    _aggregate_transactions,
    collect_whale_alerts,
)

_REQ = httpx.Request("GET", "http://test")


def _resp(status: int, json: object = None) -> httpx.Response:
    return httpx.Response(status, json=json, request=_REQ)


class TestWhaleTransaction:
    def test_exchange_inflow(self):
        tx = WhaleTransaction(
            blockchain="bitcoin",
            symbol="btc",
            amount=100,
            amount_usd=10_000_000,
            from_owner="unknown",
            to_owner="exchange",
            from_name="",
            to_name="Binance",
            timestamp=1710000000,
        )
        assert tx.flow_type == "exchange_inflow"

    def test_exchange_outflow(self):
        tx = WhaleTransaction(
            blockchain="bitcoin",
            symbol="btc",
            amount=100,
            amount_usd=10_000_000,
            from_owner="exchange",
            to_owner="unknown",
            from_name="Coinbase",
            to_name="",
            timestamp=1710000000,
        )
        assert tx.flow_type == "exchange_outflow"

    def test_exchange_to_exchange(self):
        tx = WhaleTransaction(
            blockchain="bitcoin",
            symbol="btc",
            amount=100,
            amount_usd=10_000_000,
            from_owner="exchange",
            to_owner="exchange",
            from_name="Binance",
            to_name="Coinbase",
            timestamp=1710000000,
        )
        assert tx.flow_type == "exchange_to_exchange"

    def test_unknown_transfer(self):
        tx = WhaleTransaction(
            blockchain="bitcoin",
            symbol="btc",
            amount=100,
            amount_usd=10_000_000,
            from_owner="unknown",
            to_owner="unknown",
            from_name="",
            to_name="",
            timestamp=1710000000,
        )
        assert tx.flow_type == "unknown_transfer"


class TestAggregateTransactions:
    def test_aggregates_btc_flows(self):
        txs = [
            WhaleTransaction(
                "bitcoin",
                "btc",
                100,
                10_000_000,
                "unknown",
                "exchange",
                "",
                "Binance",
                0,
            ),
            WhaleTransaction(
                "bitcoin",
                "btc",
                200,
                20_000_000,
                "exchange",
                "unknown",
                "Coinbase",
                "",
                0,
            ),
        ]
        summary = _aggregate_transactions(txs)
        assert summary.total_count == 2
        assert summary.btc_inflow_usd == 10_000_000
        assert summary.btc_outflow_usd == 20_000_000
        assert summary.btc_net_flow == -10_000_000  # net outflow

    def test_aggregates_stablecoin_flows(self):
        txs = [
            WhaleTransaction(
                "ethereum",
                "usdt",
                5_000_000,
                5_000_000,
                "unknown",
                "exchange",
                "",
                "Binance",
                0,
            ),
            WhaleTransaction(
                "ethereum",
                "usdc",
                3_000_000,
                3_000_000,
                "unknown",
                "exchange",
                "",
                "Coinbase",
                0,
            ),
        ]
        summary = _aggregate_transactions(txs)
        assert summary.stablecoin_inflow_usd == 8_000_000
        assert summary.stablecoin_net_flow == 8_000_000

    def test_empty_transactions(self):
        summary = _aggregate_transactions([])
        assert summary.total_count == 0
        assert summary.btc_net_flow == 0.0


class TestWhaleAlertSummaryFormat:
    def test_format_for_llm_empty(self):
        summary = WhaleAlertSummary()
        text = summary.format_for_llm()
        assert "Không có dữ liệu" in text

    def test_format_for_llm_with_data(self):
        txs = [
            WhaleTransaction(
                "bitcoin",
                "btc",
                500,
                50_000_000,
                "exchange",
                "unknown",
                "Binance",
                "",
                0,
            ),
        ]
        summary = _aggregate_transactions(txs)
        text = summary.format_for_llm()
        assert "WHALE ACTIVITY" in text
        assert "BTC" in text
        assert "$50.0M" in text

    def test_format_includes_signal_interpretation(self):
        txs = [
            WhaleTransaction(
                "bitcoin",
                "btc",
                500,
                50_000_000,
                "exchange",
                "unknown",
                "Binance",
                "",
                0,
            ),
        ]
        summary = _aggregate_transactions(txs)
        text = summary.format_for_llm()
        assert "tích lũy" in text  # BTC outflow → accumulation signal


class TestAggregateEdgeCases:
    def test_exchange_to_exchange_excluded_from_flows(self):
        """exchange_to_exchange counted in total but not inflow/outflow."""
        txs = [
            WhaleTransaction(
                "bitcoin",
                "btc",
                100,
                10_000_000,
                "exchange",
                "exchange",
                "Binance",
                "Coinbase",
                0,
            ),
        ]
        summary = _aggregate_transactions(txs)
        assert summary.total_count == 1
        assert summary.btc_inflow_usd == 0.0
        assert summary.btc_outflow_usd == 0.0

    def test_unknown_transfer_excluded_from_flows(self):
        """unknown_transfer counted in total but not inflow/outflow."""
        txs = [
            WhaleTransaction(
                "bitcoin",
                "btc",
                100,
                10_000_000,
                "unknown",
                "unknown",
                "",
                "",
                0,
            ),
        ]
        summary = _aggregate_transactions(txs)
        assert summary.total_count == 1
        assert summary.btc_inflow_usd == 0.0


class TestCollectWhaleAlerts:
    async def test_returns_empty_without_api_key(self):
        with patch.dict("os.environ", {}, clear=True):
            summary = await collect_whale_alerts()
        assert isinstance(summary, WhaleAlertSummary)
        assert summary.total_count == 0

    async def test_collects_and_aggregates(self):
        api_response = {
            "result": "success",
            "transactions": [
                {
                    "blockchain": "bitcoin",
                    "symbol": "btc",
                    "amount": 100,
                    "amount_usd": 10_000_000,
                    "timestamp": 1710000000,
                    "from": {"owner_type": "unknown", "owner": ""},
                    "to": {"owner_type": "exchange", "owner": "Binance"},
                },
                {
                    "blockchain": "ethereum",
                    "symbol": "eth",
                    "amount": 5000,
                    "amount_usd": 15_000_000,
                    "timestamp": 1710000001,
                    "from": {"owner_type": "exchange", "owner": "Coinbase"},
                    "to": {"owner_type": "unknown", "owner": ""},
                },
            ],
        }

        async def mock_get(url, **kwargs):
            return _resp(200, api_response)

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch.dict("os.environ", {"WHALE_ALERT_API_KEY": "test-key"}),
            patch(
                "cic_daily_report.collectors.whale_alert.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            summary = await collect_whale_alerts()

        assert summary.total_count == 2
        assert summary.btc_inflow_usd == 10_000_000
        assert summary.eth_outflow_usd == 15_000_000

    async def test_graceful_on_api_error(self):
        async def mock_get(url, **kwargs):
            raise httpx.TimeoutException("timeout")

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch.dict("os.environ", {"WHALE_ALERT_API_KEY": "test-key"}),
            patch(
                "cic_daily_report.collectors.whale_alert.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            summary = await collect_whale_alerts()

        assert isinstance(summary, WhaleAlertSummary)
        assert summary.total_count == 0

    async def test_returns_empty_on_api_result_error(self):
        """API returns result=error → empty list."""
        api_response = {"result": "error", "message": "invalid api_key"}

        async def mock_get(url, **kwargs):
            return _resp(200, api_response)

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch.dict("os.environ", {"WHALE_ALERT_API_KEY": "bad-key"}),
            patch(
                "cic_daily_report.collectors.whale_alert.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            summary = await collect_whale_alerts()

        assert summary.total_count == 0

    async def test_filters_below_minimum_value(self):
        api_response = {
            "result": "success",
            "transactions": [
                {
                    "blockchain": "bitcoin",
                    "symbol": "btc",
                    "amount": 1,
                    "amount_usd": 500_000,  # below $1M threshold
                    "timestamp": 1710000000,
                    "from": {"owner_type": "unknown", "owner": ""},
                    "to": {"owner_type": "exchange", "owner": "Binance"},
                },
            ],
        }

        async def mock_get(url, **kwargs):
            return _resp(200, api_response)

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch.dict("os.environ", {"WHALE_ALERT_API_KEY": "test-key"}),
            patch(
                "cic_daily_report.collectors.whale_alert.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            summary = await collect_whale_alerts()

        assert summary.total_count == 0
