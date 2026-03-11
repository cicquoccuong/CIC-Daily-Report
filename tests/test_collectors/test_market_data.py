"""Tests for collectors/market_data.py — all mocked."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from cic_daily_report.collectors.market_data import (
    MarketDataPoint,
    _collect_coinlore,
    _collect_coinlore_global,
    _collect_fear_greed,
    _collect_mexc,
    _collect_usdt_vnd,
    _cross_verify_prices,
    collect_market_data,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestMarketDataPoint:
    def test_to_row(self):
        point = MarketDataPoint(
            symbol="BTC",
            price=105234.56,
            change_24h=2.34,
            volume_24h=45e9,
            market_cap=2.05e12,
            data_type="crypto",
            source="CoinLore",
        )
        row = point.to_row()
        assert len(row) == 9  # matches DU_LIEU_THI_TRUONG columns
        assert row[2] == "BTC"
        assert row[8] == "CoinLore"


class TestCollectCoinlore:
    async def test_parse_coinlore_response(self):
        fixture = json.loads((FIXTURES / "coinlore_tickers.json").read_text())

        with patch("cic_daily_report.collectors.market_data.httpx.AsyncClient") as mock_http:
            mock_response = MagicMock()
            mock_response.json.return_value = fixture
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_http.return_value = mock_client

            points = await _collect_coinlore()

        assert len(points) == 2
        assert points[0].symbol == "BTC"
        assert points[0].price == 105234.56
        assert points[1].symbol == "ETH"


class TestCollectFearGreed:
    async def test_parse_fear_greed(self):
        with patch("cic_daily_report.collectors.market_data.httpx.AsyncClient") as mock_http:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "data": [{"value": "72", "value_classification": "Greed"}]
            }
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_http.return_value = mock_client

            points = await _collect_fear_greed()

        assert len(points) == 1
        assert points[0].symbol == "Fear&Greed"
        assert points[0].price == 72.0


class TestCollectMexc:
    async def test_parse_mexc_response(self):
        fixture = json.loads((FIXTURES / "mexc_tickers.json").read_text())

        with patch("cic_daily_report.collectors.market_data.httpx.AsyncClient") as mock_http:
            mock_response = MagicMock()
            mock_response.json.return_value = fixture
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_http.return_value = mock_client

            points = await _collect_mexc()

        # Should parse BTC, ETH, DOGE (in target_symbols) but NOT RANDOM
        assert len(points) == 3
        btc = next(p for p in points if p.symbol == "BTC")
        assert btc.price == 105500.0
        assert btc.source == "MEXC"
        assert btc.change_24h == 2.3  # 0.023 * 100

    async def test_mexc_failure_returns_empty(self):
        with patch("cic_daily_report.collectors.market_data.httpx.AsyncClient") as mock_http:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("Network error"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_http.return_value = mock_client

            points = await _collect_mexc()

        assert points == []


class TestCollectCoinloreGlobal:
    async def test_parse_global_response(self):
        fixture = json.loads((FIXTURES / "coinlore_global.json").read_text())

        with patch("cic_daily_report.collectors.market_data.httpx.AsyncClient") as mock_http:
            mock_response = MagicMock()
            mock_response.json.return_value = fixture
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_http.return_value = mock_client

            points = await _collect_coinlore_global()

        assert len(points) == 4
        btc_d = next(p for p in points if p.symbol == "BTC_Dominance")
        assert btc_d.price == 52.15
        total = next(p for p in points if p.symbol == "Total_MCap")
        assert total.price == 2450000000000
        eth_d = next(p for p in points if p.symbol == "ETH_Dominance")
        assert eth_d.price == 16.80
        total3 = next(p for p in points if p.symbol == "TOTAL3")
        # TOTAL3 = total_mcap - btc_mcap(from dominance) - eth_mcap(from dominance)
        expected_total3 = 2450000000000 * (1 - 0.5215 - 0.168)
        assert abs(total3.price - expected_total3) < 1e6


class TestCollectUsdtVnd:
    async def test_parse_coingecko_response(self):
        fixture = json.loads((FIXTURES / "coingecko_usdt_vnd.json").read_text())

        with patch("cic_daily_report.collectors.market_data.httpx.AsyncClient") as mock_http:
            mock_response = MagicMock()
            mock_response.json.return_value = fixture
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_http.return_value = mock_client

            points = await _collect_usdt_vnd()

        assert len(points) == 1
        assert points[0].symbol == "USDT/VND"
        assert points[0].price == 26287
        assert points[0].change_24h == 0.264
        assert points[0].source == "CoinGecko"


class TestCrossVerify:
    def test_no_deviation(self):
        data = [
            MarketDataPoint("BTC", 105000, 2.0, 1e9, 2e12, "crypto", "CoinLore"),
            MarketDataPoint("BTC", 105100, 2.1, 1e9, 0, "crypto", "MEXC"),
        ]
        result = _cross_verify_prices(data)
        # MEXC duplicate removed, only CoinLore BTC kept
        assert len(result) == 1
        assert result[0].source == "CoinLore"

    def test_high_deviation_logs_warning(self):
        data = [
            MarketDataPoint("BTC", 100000, 0, 0, 2e12, "crypto", "CoinLore"),
            MarketDataPoint("BTC", 110000, 0, 0, 0, "crypto", "MEXC"),
        ]
        # Should log a warning and remove MEXC duplicate
        result = _cross_verify_prices(data)
        assert len(result) == 1
        assert result[0].source == "CoinLore"

    def test_no_mexc_data_passes_through(self):
        data = [
            MarketDataPoint("BTC", 105000, 2.0, 1e9, 2e12, "crypto", "CoinLore"),
        ]
        result = _cross_verify_prices(data)
        assert len(result) == 1


class TestCollectMarketData:
    async def test_partial_failure_continues(self):
        """NFR9: partial source failure doesn't crash pipeline."""
        with (
            patch(
                "cic_daily_report.collectors.market_data._collect_coinlore",
                side_effect=Exception("API down"),
            ),
            patch(
                "cic_daily_report.collectors.market_data._collect_mexc",
                return_value=[],
            ),
            patch(
                "cic_daily_report.collectors.market_data._collect_coinlore_global",
                return_value=[],
            ),
            patch(
                "cic_daily_report.collectors.market_data._collect_usdt_vnd",
                return_value=[],
            ),
            patch(
                "cic_daily_report.collectors.market_data._collect_macro_indices",
                return_value=[],
            ),
            patch(
                "cic_daily_report.collectors.market_data._collect_fear_greed",
                return_value=[MarketDataPoint("FnG", 65, 0, 0, 0, "index", "alt.me")],
            ),
        ):
            data = await collect_market_data()

        # Should have Fear&Greed even though CoinLore failed
        assert len(data) == 1
        assert data[0].symbol == "FnG"
