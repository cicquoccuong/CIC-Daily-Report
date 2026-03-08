"""Tests for collectors/market_data.py — all mocked."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from cic_daily_report.collectors.market_data import (
    MarketDataPoint,
    _collect_coinlore,
    _collect_fear_greed,
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


class TestCollectMarketData:
    async def test_partial_failure_continues(self):
        """NFR9: partial source failure doesn't crash pipeline."""
        with (
            patch(
                "cic_daily_report.collectors.market_data._collect_coinlore",
                side_effect=Exception("API down"),
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
