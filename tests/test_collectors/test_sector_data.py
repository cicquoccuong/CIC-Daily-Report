"""Tests for collectors/sector_data.py — CoinGecko categories + DefiLlama TVL."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from cic_daily_report.collectors.sector_data import (
    DefiProtocol,
    SectorData,
    SectorSnapshot,
    _collect_coingecko_categories,
    _collect_defillama,
    collect_sector_data,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mock_coingecko_response() -> list[dict]:
    return [
        {
            "id": "decentralized-finance-defi",
            "name": "Decentralized Finance (DeFi)",
            "market_cap": 90e9,
            "market_cap_change_24h": 2.5,
            "volume_24h": 5e9,
            "top_3_coins_id": ["uniswap", "aave", "maker"],
        },
        {
            "id": "layer-2",
            "name": "Layer 2",
            "market_cap": 30e9,
            "market_cap_change_24h": -1.2,
            "volume_24h": 2e9,
            "top_3_coins_id": ["arbitrum", "optimism", "polygon"],
        },
        {
            "id": "artificial-intelligence",
            "name": "AI & Big Data",
            "market_cap": 15e9,
            "market_cap_change_24h": 5.0,
            "volume_24h": 1e9,
            "top_3_coins_id": ["fetch-ai", "render-token", "ocean-protocol"],
        },
        {
            "id": "not-tracked",
            "name": "Random Category",
            "market_cap": 1e9,
        },
    ]


def _mock_defillama_tvl_response() -> list[dict]:
    return [
        {"date": 1710547200, "tvl": 95e9},
        {"date": 1710633600, "tvl": 96.5e9},
    ]


def _mock_defillama_protocols_response() -> list[dict]:
    return [
        {
            "name": "Lido",
            "tvl": 30e9,
            "chains": ["Ethereum"],
            "change_1d": 0.5,
            "category": "Liquid Staking",
        },
        {
            "name": "Aave",
            "tvl": 12e9,
            "chains": ["Ethereum", "Polygon"],
            "change_1d": -1.2,
            "category": "Lending",
        },
        {
            "name": "MakerDAO",
            "tvl": 8e9,
            "chains": ["Ethereum"],
            "change_1d": 0.3,
            "category": "CDP",
        },
    ]


def _make_mock_response(json_data):
    """Create a MagicMock httpx Response with sync .json() method."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# SectorSnapshot formatting
# ---------------------------------------------------------------------------


class TestSectorSnapshot:
    def test_format_for_llm_with_data(self):
        snapshot = SectorSnapshot(
            sectors=[
                SectorData("DeFi", 90e9, 2.5, 5e9, ["Uniswap", "Aave"]),
                SectorData("Layer 2", 30e9, -1.2, 2e9, ["Arbitrum"]),
            ],
            defi_total_tvl=96.5e9,
            defi_protocols=[
                DefiProtocol("Lido", 30e9, "Ethereum", 0.5, "Liquid Staking"),
                DefiProtocol("Aave", 12e9, "Ethereum", -1.2, "Lending"),
            ],
        )
        text = snapshot.format_for_llm()
        assert "PHÂN TÍCH THEO SECTOR" in text
        assert "DeFi" in text
        assert "Layer 2" in text
        assert "TỔNG TVL" in text
        assert "Lido" in text
        assert "Aave" in text

    def test_format_for_llm_empty(self):
        snapshot = SectorSnapshot(sectors=[], defi_total_tvl=0, defi_protocols=[])
        text = snapshot.format_for_llm()
        assert text == ""

    def test_format_for_llm_sectors_only(self):
        snapshot = SectorSnapshot(
            sectors=[SectorData("DeFi", 90e9, 2.5, 5e9, ["Uniswap"])],
            defi_total_tvl=0,
            defi_protocols=[],
        )
        text = snapshot.format_for_llm()
        assert "PHÂN TÍCH THEO SECTOR" in text


# ---------------------------------------------------------------------------
# CoinGecko categories
# ---------------------------------------------------------------------------


class TestCoinGeckoCategories:
    @pytest.mark.asyncio
    async def test_parses_categories(self):
        mock_resp = _make_mock_response(_mock_coingecko_response())

        with patch("cic_daily_report.collectors.sector_data.httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            instance.get = AsyncMock(return_value=mock_resp)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = instance

            sectors = await _collect_coingecko_categories()

        names = [s.name for s in sectors]
        assert "DeFi" in names
        assert "Layer 2" in names
        assert "AI & Big Data" in names
        assert len(sectors) == 3  # 3 matched out of 4

    @pytest.mark.asyncio
    async def test_handles_http_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "429", request=httpx.Request("GET", "test"), response=httpx.Response(429)
        )

        with patch("cic_daily_report.collectors.sector_data.httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            instance.get = AsyncMock(return_value=mock_resp)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = instance

            sectors = await _collect_coingecko_categories()

        assert sectors == []

    @pytest.mark.asyncio
    async def test_handles_network_error(self):
        with patch("cic_daily_report.collectors.sector_data.httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            instance.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = instance

            sectors = await _collect_coingecko_categories()

        assert sectors == []

    @pytest.mark.asyncio
    async def test_sorted_by_market_cap(self):
        mock_resp = _make_mock_response(_mock_coingecko_response())

        with patch("cic_daily_report.collectors.sector_data.httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            instance.get = AsyncMock(return_value=mock_resp)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = instance

            sectors = await _collect_coingecko_categories()

        for i in range(len(sectors) - 1):
            assert sectors[i].market_cap >= sectors[i + 1].market_cap


# ---------------------------------------------------------------------------
# DefiLlama
# ---------------------------------------------------------------------------


class TestDefiLlama:
    @pytest.mark.asyncio
    async def test_collects_tvl_and_protocols(self):
        tvl_resp = _make_mock_response(_mock_defillama_tvl_response())
        proto_resp = _make_mock_response(_mock_defillama_protocols_response())

        with patch("cic_daily_report.collectors.sector_data.httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            instance.get = AsyncMock(side_effect=[tvl_resp, proto_resp])
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = instance

            tvl, protocols = await _collect_defillama()

        assert tvl == 96.5e9
        assert len(protocols) == 3
        assert protocols[0].name == "Lido"

    @pytest.mark.asyncio
    async def test_handles_tvl_failure(self):
        with patch("cic_daily_report.collectors.sector_data.httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            instance.get = AsyncMock(side_effect=Exception("Network error"))
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = instance

            tvl, protocols = await _collect_defillama()

        assert tvl == 0.0
        assert protocols == []


# ---------------------------------------------------------------------------
# collect_sector_data (integration)
# ---------------------------------------------------------------------------


class TestCollectSectorData:
    @pytest.mark.asyncio
    async def test_returns_snapshot(self):
        with (
            patch(
                "cic_daily_report.collectors.sector_data._collect_coingecko_categories"
            ) as mock_cg,
            patch("cic_daily_report.collectors.sector_data._collect_defillama") as mock_dl,
        ):
            mock_cg.return_value = [SectorData("DeFi", 90e9, 2.5, 5e9, ["Uniswap"])]
            mock_dl.return_value = (96.5e9, [DefiProtocol("Lido", 30e9, "ETH", 0.5, "Staking")])

            snapshot = await collect_sector_data()

        assert len(snapshot.sectors) == 1
        assert snapshot.defi_total_tvl == 96.5e9
        assert len(snapshot.defi_protocols) == 1

    @pytest.mark.asyncio
    async def test_handles_partial_failure(self):
        with (
            patch(
                "cic_daily_report.collectors.sector_data._collect_coingecko_categories"
            ) as mock_cg,
            patch("cic_daily_report.collectors.sector_data._collect_defillama") as mock_dl,
        ):
            mock_cg.side_effect = Exception("CoinGecko down")
            mock_dl.return_value = (50e9, [])

            snapshot = await collect_sector_data()

        assert snapshot.sectors == []
        assert snapshot.defi_total_tvl == 50e9
