"""Tests for Deribit Options Data Collector (QO.43).

Covers: collect_deribit_options, _calculate_max_pain, _calculate_put_call_ratio,
_calculate_avg_iv, _fetch_book_summary, OptionsData, DeribitOptionsData.

All external API calls are mocked — no real Deribit requests in tests.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from cic_daily_report.collectors.deribit_collector import (
    CURRENCIES,
    DERIBIT_API_BASE,
    DeribitOptionsData,
    OptionsData,
    _calculate_avg_iv,
    _calculate_max_pain,
    _calculate_put_call_ratio,
    _fetch_book_summary,
    collect_deribit_options,
)

# --- Fixtures ---


def _make_instrument(
    name: str,
    strike: float = 70000,
    open_interest: float = 100,
    volume: float = 50,
    mark_iv: float = 60.0,
) -> dict:
    """Create a fake Deribit instrument dict."""
    return {
        "instrument_name": name,
        "strike": strike,
        "open_interest": open_interest,
        "volume": volume,
        "mark_iv": mark_iv,
    }


SAMPLE_BTC_INSTRUMENTS = [
    _make_instrument(
        "BTC-30APR26-65000-C",
        strike=65000,
        open_interest=200,
        volume=100,
        mark_iv=55,
    ),
    _make_instrument(
        "BTC-30APR26-65000-P",
        strike=65000,
        open_interest=100,
        volume=80,
        mark_iv=58,
    ),
    _make_instrument(
        "BTC-30APR26-70000-C",
        strike=70000,
        open_interest=300,
        volume=150,
        mark_iv=50,
    ),
    _make_instrument(
        "BTC-30APR26-70000-P",
        strike=70000,
        open_interest=150,
        volume=120,
        mark_iv=52,
    ),
    _make_instrument(
        "BTC-30APR26-75000-C",
        strike=75000,
        open_interest=250,
        volume=130,
        mark_iv=48,
    ),
    _make_instrument(
        "BTC-30APR26-75000-P",
        strike=75000,
        open_interest=80,
        volume=60,
        mark_iv=55,
    ),
]

SAMPLE_ETH_INSTRUMENTS = [
    _make_instrument("ETH-30APR26-3000-C", strike=3000, open_interest=500, volume=200, mark_iv=65),
    _make_instrument("ETH-30APR26-3000-P", strike=3000, open_interest=300, volume=250, mark_iv=68),
    _make_instrument("ETH-30APR26-3500-C", strike=3500, open_interest=400, volume=180, mark_iv=62),
    _make_instrument("ETH-30APR26-3500-P", strike=3500, open_interest=200, volume=140, mark_iv=64),
]


# === OptionsData Tests ===


class TestOptionsData:
    """Tests for OptionsData dataclass."""

    def test_to_dict_basic(self):
        opt = OptionsData(
            currency="BTC",
            iv_avg=55.123,
            max_pain=70000.0,
            put_call_ratio=0.8567,
            total_volume=1234.5,
            collected_at="2026-04-15 10:00:00",
        )
        d = opt.to_dict()
        assert d["currency"] == "BTC"
        assert d["iv_avg"] == 55.12
        assert d["max_pain"] == 70000.0
        assert d["put_call_ratio"] == 0.8567
        assert d["total_volume"] == 1234.5
        assert d["source"] == "deribit"

    def test_to_dict_rounding(self):
        opt = OptionsData(
            currency="ETH",
            iv_avg=65.999,
            max_pain=3000.999,
            put_call_ratio=1.23456789,
            total_volume=999.999,
        )
        d = opt.to_dict()
        assert d["iv_avg"] == 66.0
        assert d["max_pain"] == 3001.0
        assert d["put_call_ratio"] == 1.2346
        assert d["total_volume"] == 1000.0

    def test_default_values(self):
        opt = OptionsData(currency="BTC")
        assert opt.iv_avg == 0.0
        assert opt.max_pain == 0.0
        assert opt.put_call_ratio == 0.0
        assert opt.total_volume == 0.0
        assert opt.source == "deribit"


# === DeribitOptionsData Tests ===


class TestDeribitOptionsData:
    """Tests for DeribitOptionsData container."""

    def test_get_existing_currency(self):
        data = DeribitOptionsData(
            options=[
                OptionsData(currency="BTC", iv_avg=55),
                OptionsData(currency="ETH", iv_avg=65),
            ]
        )
        btc = data.get("BTC")
        assert btc is not None
        assert btc.iv_avg == 55

    def test_get_nonexistent_currency(self):
        data = DeribitOptionsData(options=[OptionsData(currency="BTC")])
        assert data.get("SOL") is None

    def test_get_empty_container(self):
        data = DeribitOptionsData()
        assert data.get("BTC") is None

    def test_format_for_llm_with_data(self):
        data = DeribitOptionsData(
            options=[
                OptionsData(
                    currency="BTC",
                    iv_avg=55.5,
                    max_pain=70000,
                    put_call_ratio=0.85,
                    total_volume=5000,
                ),
                OptionsData(
                    currency="ETH",
                    iv_avg=65.2,
                    max_pain=3500,
                    put_call_ratio=1.1,
                    total_volume=3000,
                ),
            ]
        )
        text = data.format_for_llm()
        assert "DU LIEU QUYEN CHON" in text
        assert "BTC" in text
        assert "ETH" in text
        assert "IV=55.5%" in text
        assert "Max Pain=$70,000" in text
        assert "Put/Call=0.85" in text

    def test_format_for_llm_empty(self):
        data = DeribitOptionsData()
        assert data.format_for_llm() == ""

    def test_format_for_llm_zero_values(self):
        """Zero IV and max_pain should result in empty output."""
        data = DeribitOptionsData(
            options=[
                OptionsData(currency="BTC", iv_avg=0, max_pain=0),
            ]
        )
        assert data.format_for_llm() == ""


# === _calculate_max_pain Tests ===


class TestCalculateMaxPain:
    """Tests for max pain calculation."""

    def test_basic_max_pain(self):
        """Max pain should be at strike with minimum total loss to holders."""
        instruments = SAMPLE_BTC_INSTRUMENTS
        max_pain = _calculate_max_pain(instruments)
        # WHY: with these OI distributions, max pain should be one of the strikes
        assert max_pain in (65000, 70000, 75000)
        assert max_pain > 0

    def test_empty_instruments(self):
        assert _calculate_max_pain([]) == 0.0

    def test_no_open_interest(self):
        """All instruments with zero OI."""
        instruments = [
            _make_instrument("BTC-C", strike=70000, open_interest=0),
            _make_instrument("BTC-P", strike=70000, open_interest=0),
        ]
        assert _calculate_max_pain(instruments) == 0.0

    def test_negative_strike_ignored(self):
        instruments = [
            _make_instrument("BTC-C", strike=-1000, open_interest=100),
            _make_instrument("BTC-C", strike=70000, open_interest=100),
            _make_instrument("BTC-P", strike=70000, open_interest=50),
        ]
        result = _calculate_max_pain(instruments)
        assert result == 70000

    def test_single_strike(self):
        """Only one strike — max pain is that strike."""
        instruments = [
            _make_instrument("BTC-30APR26-70000-C", strike=70000, open_interest=100),
            _make_instrument("BTC-30APR26-70000-P", strike=70000, open_interest=50),
        ]
        assert _calculate_max_pain(instruments) == 70000

    def test_only_calls(self):
        """Only call options — max pain at highest strike (all calls expire worthless)."""
        instruments = [
            _make_instrument("BTC-C", strike=65000, open_interest=100),
            _make_instrument("BTC-C", strike=70000, open_interest=200),
            _make_instrument("BTC-C", strike=75000, open_interest=150),
        ]
        result = _calculate_max_pain(instruments)
        # WHY: when price >= all strikes, no call holder has additional loss (intrinsic=0)
        assert result == 75000

    def test_only_puts(self):
        """Only put options — max pain at lowest strike (all puts expire worthless)."""
        instruments = [
            _make_instrument("BTC-P", strike=65000, open_interest=100),
            _make_instrument("BTC-P", strike=70000, open_interest=200),
            _make_instrument("BTC-P", strike=75000, open_interest=150),
        ]
        result = _calculate_max_pain(instruments)
        # WHY: when price <= all strikes, no put holder has additional loss (intrinsic=0)
        assert result == 65000


# === _calculate_put_call_ratio Tests ===


class TestCalculatePutCallRatio:
    """Tests for put/call ratio calculation."""

    def test_balanced_ratio(self):
        instruments = [
            _make_instrument("BTC-C", volume=100),
            _make_instrument("BTC-P", volume=100),
        ]
        assert _calculate_put_call_ratio(instruments) == 1.0

    def test_bullish_ratio(self):
        """More calls than puts — ratio < 1."""
        instruments = [
            _make_instrument("BTC-C", volume=200),
            _make_instrument("BTC-P", volume=100),
        ]
        assert _calculate_put_call_ratio(instruments) == 0.5

    def test_bearish_ratio(self):
        """More puts than calls — ratio > 1."""
        instruments = [
            _make_instrument("BTC-C", volume=100),
            _make_instrument("BTC-P", volume=200),
        ]
        assert _calculate_put_call_ratio(instruments) == 2.0

    def test_zero_call_volume(self):
        """Zero call volume — returns 0 to avoid division by zero."""
        instruments = [
            _make_instrument("BTC-C", volume=0),
            _make_instrument("BTC-P", volume=100),
        ]
        assert _calculate_put_call_ratio(instruments) == 0.0

    def test_empty_instruments(self):
        assert _calculate_put_call_ratio([]) == 0.0

    def test_none_volume_treated_as_zero(self):
        """None volumes should be treated as 0."""
        instruments = [
            {"instrument_name": "BTC-C", "volume": None},
            {"instrument_name": "BTC-P", "volume": 100},
        ]
        assert _calculate_put_call_ratio(instruments) == 0.0

    def test_multi_strike_aggregation(self):
        """Volumes aggregated across multiple strikes."""
        instruments = [
            _make_instrument("BTC-65000-C", volume=100),
            _make_instrument("BTC-70000-C", volume=150),
            _make_instrument("BTC-65000-P", volume=80),
            _make_instrument("BTC-70000-P", volume=70),
        ]
        ratio = _calculate_put_call_ratio(instruments)
        # Put total = 150, Call total = 250
        assert abs(ratio - 0.6) < 0.01


# === _calculate_avg_iv Tests ===


class TestCalculateAvgIV:
    """Tests for volume-weighted average IV calculation."""

    def test_basic_weighted_average(self):
        instruments = [
            _make_instrument("BTC-C", mark_iv=50, volume=100),
            _make_instrument("BTC-P", mark_iv=60, volume=100),
        ]
        # (50*100 + 60*100) / 200 = 55.0
        assert _calculate_avg_iv(instruments) == 55.0

    def test_volume_weighting(self):
        """Higher volume should weight IV more heavily."""
        instruments = [
            _make_instrument("BTC-C", mark_iv=50, volume=900),
            _make_instrument("BTC-P", mark_iv=100, volume=100),
        ]
        # (50*900 + 100*100) / 1000 = 55.0
        assert _calculate_avg_iv(instruments) == 55.0

    def test_zero_volume_excluded(self):
        instruments = [
            _make_instrument("BTC-C", mark_iv=50, volume=0),
            _make_instrument("BTC-P", mark_iv=60, volume=100),
        ]
        assert _calculate_avg_iv(instruments) == 60.0

    def test_zero_iv_excluded(self):
        instruments = [
            _make_instrument("BTC-C", mark_iv=0, volume=100),
            _make_instrument("BTC-P", mark_iv=60, volume=100),
        ]
        assert _calculate_avg_iv(instruments) == 60.0

    def test_empty_instruments(self):
        assert _calculate_avg_iv([]) == 0.0

    def test_all_zero_volume(self):
        instruments = [
            _make_instrument("BTC-C", mark_iv=50, volume=0),
            _make_instrument("BTC-P", mark_iv=60, volume=0),
        ]
        assert _calculate_avg_iv(instruments) == 0.0

    def test_none_values(self):
        instruments = [
            {"instrument_name": "BTC-C", "mark_iv": None, "volume": 100},
            {"instrument_name": "BTC-P", "mark_iv": 60, "volume": None},
        ]
        assert _calculate_avg_iv(instruments) == 0.0


# === _fetch_book_summary Tests ===


class TestFetchBookSummary:
    """Tests for _fetch_book_summary — HTTP API call."""

    @pytest.mark.asyncio
    async def test_successful_fetch(self):
        """Successful API response returns instrument list."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": SAMPLE_BTC_INSTRUMENTS}
        mock_response.raise_for_status = MagicMock()  # sync call in source

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        _patch_target = "cic_daily_report.collectors.deribit_collector.httpx.AsyncClient"
        with patch(_patch_target, return_value=mock_client):
            result = await _fetch_book_summary("BTC")

        assert len(result) == len(SAMPLE_BTC_INSTRUMENTS)

    @pytest.mark.asyncio
    async def test_empty_result(self):
        """API returns empty result — returns empty list."""
        mock_response = AsyncMock()
        mock_response.json.return_value = {"result": []}
        mock_response.raise_for_status = AsyncMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        _patch_target = "cic_daily_report.collectors.deribit_collector.httpx.AsyncClient"
        with patch(_patch_target, return_value=mock_client):
            result = await _fetch_book_summary("BTC")

        assert result == []

    @pytest.mark.asyncio
    async def test_timeout_returns_empty(self):
        """Timeout returns empty list (graceful degradation)."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.TimeoutException("timeout")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        _patch_target = "cic_daily_report.collectors.deribit_collector.httpx.AsyncClient"
        with patch(_patch_target, return_value=mock_client):
            result = await _fetch_book_summary("BTC")

        assert result == []

    @pytest.mark.asyncio
    async def test_http_error_returns_empty(self):
        """HTTP error returns empty list."""
        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=AsyncMock(), response=mock_response
        )

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        _patch_target = "cic_daily_report.collectors.deribit_collector.httpx.AsyncClient"
        with patch(_patch_target, return_value=mock_client):
            result = await _fetch_book_summary("BTC")

        assert result == []

    @pytest.mark.asyncio
    async def test_network_error_returns_empty(self):
        """Generic network error returns empty list."""
        mock_client = AsyncMock()
        mock_client.get.side_effect = ConnectionError("network down")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        _patch_target = "cic_daily_report.collectors.deribit_collector.httpx.AsyncClient"
        with patch(_patch_target, return_value=mock_client):
            result = await _fetch_book_summary("ETH")

        assert result == []


# === collect_deribit_options Tests ===


class TestCollectDeribitOptions:
    """Tests for collect_deribit_options — top-level collection function."""

    @pytest.mark.asyncio
    async def test_successful_collection(self):
        """Successful collection for both BTC and ETH."""
        with patch(
            "cic_daily_report.collectors.deribit_collector._fetch_book_summary"
        ) as mock_fetch:
            mock_fetch.side_effect = [SAMPLE_BTC_INSTRUMENTS, SAMPLE_ETH_INSTRUMENTS]
            result = await collect_deribit_options()

        assert isinstance(result, DeribitOptionsData)
        assert len(result.options) == 2
        btc = result.get("BTC")
        assert btc is not None
        assert btc.iv_avg > 0
        assert btc.max_pain > 0
        eth = result.get("ETH")
        assert eth is not None

    @pytest.mark.asyncio
    async def test_one_currency_fails(self):
        """One currency fails — other still collected."""
        with patch(
            "cic_daily_report.collectors.deribit_collector._fetch_book_summary"
        ) as mock_fetch:
            mock_fetch.side_effect = [SAMPLE_BTC_INSTRUMENTS, []]
            result = await collect_deribit_options()

        assert len(result.options) == 1
        assert result.get("BTC") is not None
        assert result.get("ETH") is None

    @pytest.mark.asyncio
    async def test_both_currencies_fail(self):
        """Both currencies fail — returns empty container."""
        with patch(
            "cic_daily_report.collectors.deribit_collector._fetch_book_summary"
        ) as mock_fetch:
            mock_fetch.return_value = []
            result = await collect_deribit_options()

        assert isinstance(result, DeribitOptionsData)
        assert len(result.options) == 0

    @pytest.mark.asyncio
    async def test_exception_in_calculation(self):
        """Exception during calculation for one currency doesn't block other."""
        with patch(
            "cic_daily_report.collectors.deribit_collector._fetch_book_summary"
        ) as mock_fetch:
            # First call returns data that will cause no issues
            mock_fetch.side_effect = [SAMPLE_BTC_INSTRUMENTS, SAMPLE_ETH_INSTRUMENTS]
            with patch(
                "cic_daily_report.collectors.deribit_collector._calculate_avg_iv"
            ) as mock_iv:
                # First call succeeds, second raises
                mock_iv.side_effect = [55.0, ValueError("calc error")]
                result = await collect_deribit_options()

        # WHY: BTC should succeed, ETH should be caught and skipped
        assert len(result.options) == 1
        assert result.get("BTC") is not None

    @pytest.mark.asyncio
    async def test_collected_at_timestamp(self):
        """Collected_at timestamp is set."""
        with patch(
            "cic_daily_report.collectors.deribit_collector._fetch_book_summary"
        ) as mock_fetch:
            mock_fetch.side_effect = [SAMPLE_BTC_INSTRUMENTS, []]
            result = await collect_deribit_options()

        btc = result.get("BTC")
        assert btc is not None
        assert btc.collected_at != ""


# === Constants Tests ===


class TestConstants:
    """Verify module constants."""

    def test_currencies(self):
        assert CURRENCIES == ("BTC", "ETH")

    def test_api_base(self):
        assert "deribit.com" in DERIBIT_API_BASE
        assert DERIBIT_API_BASE.startswith("https://")
