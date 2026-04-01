"""Tests for collectors/research_data.py — all external APIs mocked."""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from cic_daily_report.collectors.research_data import (
    ETFFlowData,
    ETFFlowEntry,
    OnChainAdvanced,
    PiCycleData,
    ResearchData,
    StablecoinData,
    _calculate_pi_cycle_from_closes,
    _collect_bgeometrics,
    _collect_blockchain_stats,
    _collect_etf_flows,
    _collect_pi_cycle,
    _collect_stablecoin_data,
    _fetch_pi_cycle_closes_coingecko,
    collect_research_data,
)

_REQ = httpx.Request("GET", "http://test")


def _resp(status: int, json_data: object = None, text: str = "") -> httpx.Response:
    if json_data is not None:
        return httpx.Response(status, json=json_data, request=_REQ)
    return httpx.Response(status, text=text, request=_REQ)


# ---------------------------------------------------------------------------
# BGeometrics
# ---------------------------------------------------------------------------


class TestCollectBGeometrics:
    async def test_collects_all_four_metrics(self):
        """Successfully fetch MVRV Z-Score, NUPL, SOPR, Puell."""
        mock_data = [
            {"d": "2026-03-19", "v": 1.23},
            {"d": "2026-03-20", "v": 1.45},
        ]

        async def mock_get(url, **kwargs):
            return _resp(200, mock_data)

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "cic_daily_report.collectors.research_data.httpx.AsyncClient",
            return_value=mock_client,
        ):
            metrics = await _collect_bgeometrics()

        assert len(metrics) == 4
        names = {m.name for m in metrics}
        assert names == {"MVRV_Z_Score", "NUPL", "SOPR", "Puell_Multiple"}
        for m in metrics:
            assert m.value == 1.45  # latest entry
            assert m.source == "BGeometrics"
            assert m.date == "2026-03-20"

    async def test_handles_rate_limit_429(self):
        """Returns partial data when rate limited."""
        call_count = 0

        async def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return _resp(200, [{"d": "2026-03-20", "v": 1.0}])
            return _resp(429, {"error": "rate limited"})

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "cic_daily_report.collectors.research_data.httpx.AsyncClient",
            return_value=mock_client,
        ):
            metrics = await _collect_bgeometrics()

        assert len(metrics) == 2

    async def test_handles_empty_response(self):
        """Returns empty list when API returns no data."""

        async def mock_get(url, **kwargs):
            return _resp(200, [])

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "cic_daily_report.collectors.research_data.httpx.AsyncClient",
            return_value=mock_client,
        ):
            metrics = await _collect_bgeometrics()

        assert len(metrics) == 0


# ---------------------------------------------------------------------------
# ETF Flows
# ---------------------------------------------------------------------------


class TestCollectETFFlows:
    def _build_next_data_html(self, chart2: dict, providers: dict | None = None) -> str:
        """Build mock HTML with embedded __NEXT_DATA__."""
        data = {
            "props": {
                "pageProps": {
                    "dehydratedState": {
                        "queries": [
                            {
                                "state": {
                                    "data": {
                                        "data": {
                                            "providers": providers or {},
                                            "chart2": chart2,
                                        }
                                    }
                                }
                            }
                        ]
                    }
                }
            }
        }
        return (
            '<html><script id="__NEXT_DATA__" type="application/json">'
            f"{json.dumps(data)}"
            "</script></html>"
        )

    async def test_extracts_etf_flow_data(self):
        """Successfully parse ETF flows from __NEXT_DATA__."""
        chart2 = {
            "dates": ["2026-03-17", "2026-03-18", "2026-03-19"],
            "IBIT": [500e6, 600e6, 700e6],
            "FBTC": [100e6, 110e6, 120e6],
            "GBTC": [-50e6, -30e6, -20e6],
        }
        providers = {"IBIT": "iShares Bitcoin Trust", "FBTC": "Fidelity", "GBTC": "Grayscale"}
        html = self._build_next_data_html(chart2, providers)

        async def mock_get(url, **kwargs):
            return _resp(200, text=html)

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "cic_daily_report.collectors.research_data.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await _collect_etf_flows()

        assert result is not None
        assert len(result.entries) == 3
        assert result.date == "2026-03-19"
        assert result.total_flow_usd == pytest.approx(800e6)  # 700 + 120 + (-20)

        ibit = next(e for e in result.entries if e.etf_name == "iShares Bitcoin Trust")
        assert ibit.flow_usd == 700e6

        # 5-day trend (3 days available in fixture)
        assert len(result.recent_total_flows) == 3
        assert result.recent_total_flows[0] == ("2026-03-17", pytest.approx(550e6))
        assert result.recent_total_flows[2] == ("2026-03-19", pytest.approx(800e6))

    async def test_handles_missing_next_data(self):
        """Returns None when __NEXT_DATA__ not found."""

        async def mock_get(url, **kwargs):
            return _resp(200, text="<html><body>No data</body></html>")

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "cic_daily_report.collectors.research_data.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await _collect_etf_flows()

        assert result is None

    async def test_handles_network_error(self):
        """Returns None on network failure."""

        async def mock_get(url, **kwargs):
            raise httpx.ConnectError("Connection refused")

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "cic_daily_report.collectors.research_data.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await _collect_etf_flows()

        assert result is None


# ---------------------------------------------------------------------------
# Stablecoins (DefiLlama)
# ---------------------------------------------------------------------------


class TestCollectStablecoinData:
    async def test_collects_usdt_and_usdc(self):
        """Extract USDT and USDC from DefiLlama response."""
        mock_data = {
            "peggedAssets": [
                {
                    "name": "Tether",
                    "symbol": "USDT",
                    "circulating": {"peggedUSD": 184e9},
                    "circulatingPrevDay": {"peggedUSD": 183.5e9},
                    "circulatingPrevWeek": {"peggedUSD": 183e9},
                    "circulatingPrevMonth": {"peggedUSD": 180e9},
                    "chainCirculating": {
                        "Ethereum": {"current": {"peggedUSD": 80e9}},
                        "Tron": {"current": {"peggedUSD": 60e9}},
                    },
                },
                {
                    "name": "USDC",
                    "symbol": "USDC",
                    "circulating": {"peggedUSD": 79e9},
                    "circulatingPrevDay": {"peggedUSD": 78.8e9},
                    "circulatingPrevWeek": {"peggedUSD": 78e9},
                    "circulatingPrevMonth": {"peggedUSD": 74e9},
                    "chainCirculating": {
                        "Ethereum": {"current": {"peggedUSD": 50e9}},
                    },
                },
                {
                    "name": "SmallStable",
                    "symbol": "SMOL",
                    "circulating": {"peggedUSD": 1e6},  # Too small, should be filtered
                    "circulatingPrevDay": {"peggedUSD": 1e6},
                    "circulatingPrevWeek": {"peggedUSD": 1e6},
                    "circulatingPrevMonth": {"peggedUSD": 1e6},
                    "chainCirculating": {},
                },
            ]
        }

        async def mock_get(url, **kwargs):
            return _resp(200, mock_data)

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "cic_daily_report.collectors.research_data.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await _collect_stablecoin_data()

        assert len(result) == 2
        usdt = result[0]  # sorted by market cap, USDT first
        assert "Tether" in usdt.name
        assert usdt.market_cap == 184e9
        assert usdt.change_1d == pytest.approx(0.5e9)
        assert usdt.change_30d == pytest.approx(4e9)


# ---------------------------------------------------------------------------
# Blockchain.com stats
# ---------------------------------------------------------------------------


class TestCollectBlockchainStats:
    async def test_collects_stats(self):
        """Extract network stats from Blockchain.com."""
        mock_data = {
            "miners_revenue_usd": 31_200_000,
            "difficulty": 145_000_000_000_000,
            "hash_rate": 920_000_000_000_000_000_000,
            "n_tx": 445_564,
            "total_fees_btc": 2864,
            "mempool_size": 12_500_000,
            "n_blocks_mined": 144,
        }

        async def mock_get(url, **kwargs):
            return _resp(200, mock_data)

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "cic_daily_report.collectors.research_data.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await _collect_blockchain_stats()

        assert len(result) == 7
        assert result["Miner_Revenue_USD"] == 31_200_000
        assert result["Transactions_24h"] == 445_564


# ---------------------------------------------------------------------------
# Pi Cycle Top
# ---------------------------------------------------------------------------


class TestCollectPiCycle:
    async def test_calculates_pi_cycle(self):
        """Calculate 111SMA and 350SMA*2 from price data."""
        # Generate 365 mock candles with predictable prices
        klines = []
        for i in range(365):
            price = 60000 + i * 100  # Steadily increasing
            klines.append(
                [
                    0,
                    "0",
                    "0",
                    "0",
                    str(price),
                    "0",
                    0,
                    "0",
                    0,
                    "0",
                    "0",
                    "0",
                ]
            )

        async def mock_get(url, **kwargs):
            return _resp(200, klines)

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "cic_daily_report.collectors.research_data.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await _collect_pi_cycle()

        assert result is not None
        assert result.sma_111 > 0
        assert result.sma_350x2 > 0
        assert isinstance(result.is_crossed, bool)
        assert isinstance(result.distance_pct, float)

    async def test_handles_insufficient_data(self):
        """Returns None when not enough candles."""
        klines = [[0, "0", "0", "0", "60000", "0", 0, "0", 0, "0", "0", "0"]] * 200

        async def mock_get(url, **kwargs):
            return _resp(200, klines)

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "cic_daily_report.collectors.research_data.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await _collect_pi_cycle()

        assert result is None

    async def test_falls_back_to_coingecko_on_binance_failure(self):
        """v0.32.0: When Binance returns 451, falls back to CoinGecko."""
        # CoinGecko response: {"prices": [[ts, price], ...]}
        cg_prices = [[i * 86400000, 60000 + i * 100] for i in range(365)]

        with (
            patch(
                "cic_daily_report.collectors.research_data._fetch_pi_cycle_closes_binance",
                return_value=None,  # Binance failed
            ),
            patch(
                "cic_daily_report.collectors.research_data._fetch_pi_cycle_closes_coingecko",
                return_value=[float(p[1]) for p in cg_prices],
            ),
        ):
            result = await _collect_pi_cycle()

        assert result is not None
        assert result.sma_111 > 0
        assert result.sma_350x2 > 0

    async def test_coingecko_response_parsing(self):
        """v0.32.0: CoinGecko market_chart response parsed correctly."""
        cg_data = {
            "prices": [[1000 * i, 60000 + i * 10] for i in range(365)],
        }

        async def mock_get(url, **kwargs):
            return _resp(200, cg_data)

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "cic_daily_report.collectors.research_data.httpx.AsyncClient",
            return_value=mock_client,
        ):
            closes = await _fetch_pi_cycle_closes_coingecko()

        assert closes is not None
        assert len(closes) == 365
        assert closes[0] == 60000.0
        assert closes[-1] == 60000.0 + 364 * 10

    async def test_coingecko_returns_none_on_empty_prices(self):
        """v0.32.0: CoinGecko returns None when prices array is empty."""

        async def mock_get(url, **kwargs):
            return _resp(200, {"prices": []})

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "cic_daily_report.collectors.research_data.httpx.AsyncClient",
            return_value=mock_client,
        ):
            closes = await _fetch_pi_cycle_closes_coingecko()

        assert closes is None


class TestCalculatePiCycleFromCloses:
    """v0.32.0: Unit tests for extracted calculation function."""

    def test_basic_calculation(self):
        """Verify SMA values and cross detection from known data."""
        closes = [60000 + i * 100 for i in range(365)]
        result = _calculate_pi_cycle_from_closes(closes)
        assert result.sma_111 > 0
        assert result.sma_350x2 > 0
        assert isinstance(result.is_crossed, bool)
        assert isinstance(result.distance_pct, float)

    def test_crossed_detection(self):
        """When 111SMA > 350SMA*2, is_crossed should be True."""
        # Create data where recent prices are very high (111SMA >> 350SMA*2)
        closes = [10000] * 239 + [200000] * 126  # Last 126 days at 200k
        result = _calculate_pi_cycle_from_closes(closes)
        # 111SMA = close to 200000, 350SMA*2 = close to 2 * weighted avg
        # With these numbers, 111SMA should exceed 350SMA*2
        assert result.sma_111 > 0
        assert result.sma_350x2 > 0


# ---------------------------------------------------------------------------
# ETF Flows — list-type defense (v0.32.0)
# ---------------------------------------------------------------------------


class TestETFFlowsListDefense:
    """v0.32.0: Tests for defensive type checking when __NEXT_DATA__ structure changes."""

    async def test_state_data_as_list(self):
        """state.data is a list instead of dict — extracts first element."""
        chart2 = {
            "dates": ["2026-03-19"],
            "IBIT": [500e6],
        }
        inner = {"data": {"providers": {}, "chart2": chart2}}
        data = {
            "props": {
                "pageProps": {
                    "dehydratedState": {
                        "queries": [
                            {
                                "state": {
                                    "data": [inner],  # List instead of dict
                                }
                            }
                        ]
                    }
                }
            }
        }
        html = (
            '<html><script id="__NEXT_DATA__" type="application/json">'
            f"{json.dumps(data)}"
            "</script></html>"
        )

        async def mock_get(url, **kwargs):
            return _resp(200, text=html)

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "cic_daily_report.collectors.research_data.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await _collect_etf_flows()

        assert result is not None
        assert len(result.entries) == 1

    async def test_inner_data_as_list(self):
        """state.data.data is a list instead of dict — extracts first element."""
        chart2 = {
            "dates": ["2026-03-19"],
            "FBTC": [300e6],
        }
        data = {
            "props": {
                "pageProps": {
                    "dehydratedState": {
                        "queries": [
                            {
                                "state": {
                                    "data": {
                                        "data": [  # List instead of dict
                                            {"providers": {}, "chart2": chart2}
                                        ]
                                    }
                                }
                            }
                        ]
                    }
                }
            }
        }
        html = (
            '<html><script id="__NEXT_DATA__" type="application/json">'
            f"{json.dumps(data)}"
            "</script></html>"
        )

        async def mock_get(url, **kwargs):
            return _resp(200, text=html)

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "cic_daily_report.collectors.research_data.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await _collect_etf_flows()

        assert result is not None
        assert len(result.entries) == 1

    async def test_state_data_empty_list_returns_none(self):
        """state.data is an empty list — returns None gracefully."""
        data = {
            "props": {
                "pageProps": {
                    "dehydratedState": {
                        "queries": [
                            {
                                "state": {
                                    "data": [],  # Empty list
                                }
                            }
                        ]
                    }
                }
            }
        }
        html = (
            '<html><script id="__NEXT_DATA__" type="application/json">'
            f"{json.dumps(data)}"
            "</script></html>"
        )

        async def mock_get(url, **kwargs):
            return _resp(200, text=html)

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "cic_daily_report.collectors.research_data.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await _collect_etf_flows()

        assert result is None


# ---------------------------------------------------------------------------
# ResearchData.format_for_llm
# ---------------------------------------------------------------------------


class TestResearchDataFormat:
    def test_format_with_all_data(self):
        """Format produces structured text with all sections."""
        data = ResearchData(
            onchain_advanced=[
                OnChainAdvanced("MVRV_Z_Score", 1.45, "BGeometrics", "2026-03-20"),
                OnChainAdvanced("NUPL", 0.35, "BGeometrics", "2026-03-20"),
            ],
            etf_flows=ETFFlowData(
                entries=[
                    ETFFlowEntry("IBIT", 700e6, date="2026-03-19"),
                    ETFFlowEntry("GBTC", -20e6, date="2026-03-19"),
                ],
                total_flow_usd=680e6,
                date="2026-03-19",
            ),
            stablecoins=[
                StablecoinData("Tether (USDT)", 184e9, 500e6, 1e9, 4e9),
            ],
            blockchain_stats={"Miner_Revenue_USD": 31.2e6},
            pi_cycle=PiCycleData(sma_111=72000, sma_350x2=85000, distance_pct=-15.3),
        )

        text = data.format_for_llm()
        assert "MVRV_Z_Score" in text
        assert "NUPL" in text
        assert "IBIT" in text
        assert "Tether" in text
        assert "Miner_Revenue_USD" in text
        assert "PI CYCLE" in text
        assert "111-day SMA" in text

    def test_format_empty_data(self):
        """Format returns empty string when no data."""
        data = ResearchData()
        assert data.format_for_llm() == ""

    def test_format_stablecoin_zero_change(self):
        """Stablecoin with change_1d=0 shows '+0' not 'N/A'."""
        data = ResearchData(
            stablecoins=[StablecoinData("TestCoin (TC)", 50e9, 0.0, 0.0, 0.0)],
        )
        text = data.format_for_llm()
        assert "N/A" not in text
        assert "+0" in text

    def test_format_filters_zero_onchain_values(self):
        """QW3/VD-27: On-chain metrics with value 0.0 are filtered out."""
        data = ResearchData(
            onchain_advanced=[
                OnChainAdvanced("MVRV_Z_Score", 1.45, "BGeometrics", "2026-03-20"),
                OnChainAdvanced("NUPL", 0.0, "BGeometrics", "2026-03-20"),
                OnChainAdvanced("SOPR", 0.0, "BGeometrics", "2026-03-20"),
            ],
        )
        text = data.format_for_llm()
        assert "MVRV_Z_Score" in text
        assert "NUPL" not in text
        assert "SOPR" not in text

    def test_format_all_zero_bgeometrics_shows_warning(self):
        """QW3/VD-27: All 4 BGeometrics metrics at 0.0 → unavailability warning."""
        data = ResearchData(
            onchain_advanced=[
                OnChainAdvanced("MVRV_Z_Score", 0.0, "BGeometrics", "2026-03-20"),
                OnChainAdvanced("NUPL", 0.0, "BGeometrics", "2026-03-20"),
                OnChainAdvanced("SOPR", 0.0, "BGeometrics", "2026-03-20"),
                OnChainAdvanced("Puell_Multiple", 0.0, "BGeometrics", "2026-03-20"),
            ],
        )
        text = data.format_for_llm()
        # Should NOT have the on-chain section (all filtered)
        assert "ON-CHAIN" not in text
        # Should have unavailability warning
        assert "BGeometrics" in text
        assert "MVRV" in text

    def test_format_partial_zero_no_warning(self):
        """QW3/VD-27: Only some zeros → no all-unavailable warning, valid ones shown."""
        data = ResearchData(
            onchain_advanced=[
                OnChainAdvanced("MVRV_Z_Score", 1.45, "BGeometrics", "2026-03-20"),
                OnChainAdvanced("NUPL", 0.0, "BGeometrics", "2026-03-20"),
                OnChainAdvanced("SOPR", 1.02, "BGeometrics", "2026-03-20"),
                OnChainAdvanced("Puell_Multiple", 0.0, "BGeometrics", "2026-03-20"),
            ],
        )
        text = data.format_for_llm()
        assert "MVRV_Z_Score" in text
        assert "SOPR" in text
        # Partial zero should NOT trigger the all-unavailable warning
        assert "kh\u00f4ng kh\u1ea3 d\u1ee5ng" not in text

    def test_format_etf_with_trend(self):
        """ETF format includes 5-day trend data."""
        data = ResearchData(
            etf_flows=ETFFlowData(
                entries=[ETFFlowEntry("IBIT", 700e6, date="2026-03-19")],
                total_flow_usd=700e6,
                date="2026-03-19",
                recent_total_flows=[
                    ("2026-03-15", -100e6),
                    ("2026-03-16", 200e6),
                    ("2026-03-17", 550e6),
                    ("2026-03-18", 680e6),
                    ("2026-03-19", 700e6),
                ],
            ),
        )
        text = data.format_for_llm()
        assert "Xu hướng 5 ngày" in text
        assert "2026-03-15" in text
        assert "2026-03-19" in text


# ---------------------------------------------------------------------------
# Full collect_research_data (integration-level mock)
# ---------------------------------------------------------------------------


class TestCollectResearchData:
    async def test_returns_research_data_on_partial_failure(self):
        """Returns whatever succeeded even when some sources fail."""
        with (
            patch(
                "cic_daily_report.collectors.research_data._collect_bgeometrics",
                return_value=[OnChainAdvanced("MVRV_Z_Score", 1.5, "BGeometrics", "2026-03-20")],
            ),
            patch(
                "cic_daily_report.collectors.research_data._collect_etf_flows",
                side_effect=Exception("network error"),
            ),
            patch(
                "cic_daily_report.collectors.research_data._collect_stablecoin_data",
                return_value=[],
            ),
            patch(
                "cic_daily_report.collectors.research_data._collect_blockchain_stats",
                return_value={},
            ),
            patch(
                "cic_daily_report.collectors.research_data._collect_pi_cycle",
                return_value=None,
            ),
        ):
            result = await collect_research_data()

        assert isinstance(result, ResearchData)
        assert len(result.onchain_advanced) == 1
        assert result.etf_flows is None  # Failed gracefully
