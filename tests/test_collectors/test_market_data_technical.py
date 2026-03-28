"""Tests for technical indicators in collectors/market_data.py (P1.11).

All yfinance calls are mocked — no real API calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from cic_daily_report.collectors.market_data import (
    TechnicalIndicators,
    _calculate_rsi,
    collect_technical_indicators,
    format_technical_for_llm,
)

# ---------------------------------------------------------------------------
# _calculate_rsi tests
# ---------------------------------------------------------------------------


class TestCalculateRSI:
    """Verify Wilder's smoothing RSI matches expected values."""

    def test_known_price_series(self):
        """Test RSI with a known price series.

        WHY this test: Wilder's RSI on this series should produce a specific value.
        Hand-verified against the Wilder formula:
        - 14 deltas from 15 prices
        - Seed avg_gain, avg_loss from first 14 deltas
        - Then Wilder-smooth through remaining deltas
        """
        # 16 prices → 15 deltas, enough for period=14 + 1 smoothing step
        closes = [
            44.0,
            44.34,
            44.09,
            43.61,
            44.33,
            44.83,
            45.10,
            45.42,
            45.84,
            46.08,
            45.89,
            46.03,
            45.61,
            46.28,
            46.28,
            46.00,
        ]
        rsi = _calculate_rsi(closes, 14)
        # With Wilder's smoothing on this series, RSI should be around 51-58
        assert 40.0 < rsi < 70.0, f"RSI {rsi} outside expected range for balanced series"

    def test_all_gains(self):
        """If price only goes up, RSI should be 100."""
        closes = [float(i) for i in range(1, 20)]  # 1, 2, 3, ..., 19
        rsi = _calculate_rsi(closes, 14)
        assert rsi == 100.0

    def test_all_losses(self):
        """If price only goes down, RSI should be ~0."""
        closes = [float(20 - i) for i in range(20)]  # 20, 19, 18, ..., 1
        rsi = _calculate_rsi(closes, 14)
        assert rsi < 5.0  # Should be very close to 0

    def test_insufficient_data_returns_neutral(self):
        """Fewer than period+1 values → return 50.0 (neutral)."""
        rsi = _calculate_rsi([100.0, 101.0, 99.0], 14)
        assert rsi == 50.0

    def test_exact_minimum_data(self):
        """Exactly period+1 values → should compute (seed only, no smoothing steps)."""
        # 15 values = 14 deltas = exactly enough for seed, no additional smoothing
        closes = [100.0 + i * 0.5 for i in range(15)]
        rsi = _calculate_rsi(closes, 14)
        # All gains, no losses → RSI = 100
        assert rsi == 100.0

    def test_flat_prices(self):
        """Flat prices (no change) → RSI = 50 (neutral).

        WHY: avg_gain=0, avg_loss=0 means no price movement at all.
        This is genuinely neutral — not bullish (100) or bearish (0).
        Explicit check for both-zero before the avg_loss==0 shortcut.
        """
        closes = [100.0] * 20
        rsi = _calculate_rsi(closes, 14)
        # avg_gain=0, avg_loss=0 → neutral, not all-gains
        assert rsi == 50.0

    def test_period_custom(self):
        """Test with non-default period (7)."""
        closes = [float(i) for i in range(1, 12)]  # 11 values, enough for period=7
        rsi = _calculate_rsi(closes, 7)
        assert rsi == 100.0  # all gains


# ---------------------------------------------------------------------------
# collect_technical_indicators tests
# ---------------------------------------------------------------------------


class TestCollectTechnicalIndicators:
    """Test collect_technical_indicators with mocked yfinance."""

    def _make_mock_hist(self, closes: list[float]) -> MagicMock:
        """Create a mock yfinance history DataFrame-like object."""
        mock_hist = MagicMock()
        mock_hist.empty = len(closes) == 0
        mock_hist.__len__ = MagicMock(return_value=len(closes))

        # Mock the Close column as a Series-like with .tolist()
        mock_close = MagicMock()
        mock_close.tolist.return_value = closes
        mock_close.iloc.__getitem__ = lambda self, idx: closes[idx]
        mock_hist.__getitem__ = lambda self, key: mock_close if key == "Close" else MagicMock()

        return mock_hist

    async def test_success_both_assets(self):
        """Both BTC and ETH return valid indicators."""
        # Generate 210 prices for a realistic scenario
        btc_closes = [60000.0 + i * 50 for i in range(210)]
        eth_closes = [3000.0 + i * 5 for i in range(210)]

        def mock_yf_get(ticker: str):
            if "BTC" in ticker:
                return {"closes": btc_closes, "current_price": btc_closes[-1]}
            return {"closes": eth_closes, "current_price": eth_closes[-1]}

        with patch(
            "cic_daily_report.collectors.market_data._yf_get_technical",
            side_effect=mock_yf_get,
        ):
            result = await collect_technical_indicators()

        assert len(result) == 2
        btc = next(r for r in result if r.symbol == "BTC")
        eth = next(r for r in result if r.symbol == "ETH")

        # All gains → RSI should be 100 or near 100
        assert btc.rsi_14d > 90.0
        assert eth.rsi_14d > 90.0

        # MA50 and MA200 should be positive
        assert btc.ma_50 > 0
        assert btc.ma_200 > 0
        assert eth.ma_50 > 0
        assert eth.ma_200 > 0

        # Current > all MAs (monotonically increasing) → above
        assert btc.price_vs_ma50 == "above"
        assert btc.price_vs_ma200 == "above"

        # Golden cross: MA50 > MA200 for monotonically increasing series
        assert btc.golden_cross is True

        assert btc.source == "yfinance"

    async def test_yfinance_not_installed(self):
        """If yfinance not importable, return empty list gracefully.

        WHY patch sys.modules: The function uses `import yfinance as _yf` which checks
        sys.modules first. Setting it to None triggers ImportError on access.
        """
        import sys

        original = sys.modules.get("yfinance", "NOT_SET")
        sys.modules["yfinance"] = None  # type: ignore[assignment]
        try:
            result = await collect_technical_indicators()
        finally:
            if original == "NOT_SET":
                sys.modules.pop("yfinance", None)
            else:
                sys.modules["yfinance"] = original

        assert result == []

    async def test_yfinance_returns_none(self):
        """yfinance returns no data → empty list (no crash)."""
        with patch(
            "cic_daily_report.collectors.market_data._yf_get_technical",
            return_value=None,
        ):
            result = await collect_technical_indicators()

        assert result == []

    async def test_partial_failure(self):
        """One asset fails, other succeeds → return partial results."""
        btc_closes = [60000.0 + i * 50 for i in range(210)]

        def mock_yf_get(ticker: str):
            if "BTC" in ticker:
                return {"closes": btc_closes, "current_price": btc_closes[-1]}
            # ETH fails
            return None

        with patch(
            "cic_daily_report.collectors.market_data._yf_get_technical",
            side_effect=mock_yf_get,
        ):
            result = await collect_technical_indicators()

        assert len(result) == 1
        assert result[0].symbol == "BTC"

    async def test_exception_in_yf_get(self):
        """Exception during fetch → return empty, no crash."""
        with patch(
            "cic_daily_report.collectors.market_data._yf_get_technical",
            side_effect=Exception("Network timeout"),
        ):
            result = await collect_technical_indicators()

        assert result == []

    async def test_fewer_than_200_candles(self):
        """Only 100 candles → MA50 computed, MA200 = 0 (insufficient)."""
        closes = [50000.0 + i * 30 for i in range(100)]

        with patch(
            "cic_daily_report.collectors.market_data._yf_get_technical",
            return_value={"closes": closes, "current_price": closes[-1]},
        ):
            result = await collect_technical_indicators()

        assert len(result) == 2  # Both BTC and ETH get same mock data
        for ind in result:
            assert ind.ma_50 > 0
            assert ind.ma_200 == 0.0  # Not enough data for MA200
            assert ind.golden_cross is False  # Can't determine with MA200=0

    async def test_rsi_signal_overbought(self):
        """Monotonically increasing prices → RSI > 70 → overbought signal."""
        closes = [1000.0 + i * 100 for i in range(210)]  # strong uptrend

        with patch(
            "cic_daily_report.collectors.market_data._yf_get_technical",
            return_value={"closes": closes, "current_price": closes[-1]},
        ):
            result = await collect_technical_indicators()

        for ind in result:
            assert ind.rsi_signal == "overbought"

    async def test_rsi_signal_oversold(self):
        """Monotonically decreasing prices → RSI < 30 → oversold signal."""
        closes = [100000.0 - i * 100 for i in range(210)]  # strong downtrend

        with patch(
            "cic_daily_report.collectors.market_data._yf_get_technical",
            return_value={"closes": closes, "current_price": closes[-1]},
        ):
            result = await collect_technical_indicators()

        for ind in result:
            assert ind.rsi_signal == "oversold"

    async def test_death_cross(self):
        """When recent prices crash hard, MA50 < MA200 → death cross (golden_cross=False).

        WHY steep decline: MA200 includes old high prices, so MA50 must be
        significantly below to flip. We use a sharp crash in last 50 candles.
        """
        # First 160: stable at 70k. Last 50: crash from 70k to 30k.
        # MA200 ≈ (160*70000 + 50*~50000) / 200 ≈ 65000
        # MA50 = avg of 30k-70k crash ≈ 50000 → MA50 < MA200
        stable = [70000.0] * 160
        crash = [70000.0 - i * 800 for i in range(1, 51)]  # 69200 → 30000
        closes = stable + crash

        with patch(
            "cic_daily_report.collectors.market_data._yf_get_technical",
            return_value={"closes": closes, "current_price": closes[-1]},
        ):
            result = await collect_technical_indicators()

        for ind in result:
            assert ind.golden_cross is False  # MA50 < MA200 due to crash


# ---------------------------------------------------------------------------
# format_technical_for_llm tests
# ---------------------------------------------------------------------------


class TestFormatTechnicalForLLM:
    """Test LLM text formatting of technical indicators."""

    def test_format_both_assets(self):
        """Two indicators → header + 2 lines."""
        indicators = [
            TechnicalIndicators(
                symbol="BTC",
                rsi_14d=45.2,
                ma_50=68500.0,
                ma_200=62300.0,
                price_vs_ma50="above",
                price_vs_ma200="above",
                golden_cross=True,
                rsi_signal="neutral",
            ),
            TechnicalIndicators(
                symbol="ETH",
                rsi_14d=38.7,
                ma_50=3200.0,
                ma_200=2800.0,
                price_vs_ma50="above",
                price_vs_ma200="above",
                golden_cross=True,
                rsi_signal="neutral",
            ),
        ]
        text = format_technical_for_llm(indicators)

        assert "CHI BAO KY THUAT" in text
        assert "yfinance" in text
        assert "BTC: RSI(14) = 45.2" in text
        assert "Trung tinh" in text
        assert "MA50 = $68,500" in text
        assert "MA200 = $62,300" in text
        assert "Golden Cross" in text
        assert "ETH: RSI(14) = 38.7" in text
        assert "MA50 = $3,200" in text

    def test_format_overbought(self):
        """Overbought RSI → 'Qua mua' label."""
        indicators = [
            TechnicalIndicators(
                symbol="BTC",
                rsi_14d=78.5,
                ma_50=70000.0,
                ma_200=65000.0,
                price_vs_ma50="above",
                price_vs_ma200="above",
                golden_cross=True,
                rsi_signal="overbought",
            ),
        ]
        text = format_technical_for_llm(indicators)
        assert "Qua mua" in text

    def test_format_oversold(self):
        """Oversold RSI → 'Qua ban' label."""
        indicators = [
            TechnicalIndicators(
                symbol="BTC",
                rsi_14d=22.3,
                ma_50=60000.0,
                ma_200=65000.0,
                price_vs_ma50="below",
                price_vs_ma200="below",
                golden_cross=False,
                rsi_signal="oversold",
            ),
        ]
        text = format_technical_for_llm(indicators)
        assert "Qua ban" in text
        assert "Death Cross" in text

    def test_format_no_ma200(self):
        """MA200 = 0 → not shown in output."""
        indicators = [
            TechnicalIndicators(
                symbol="BTC",
                rsi_14d=55.0,
                ma_50=68000.0,
                ma_200=0.0,
                price_vs_ma50="above",
                price_vs_ma200="below",
                golden_cross=False,
                rsi_signal="neutral",
            ),
        ]
        text = format_technical_for_llm(indicators)
        assert "MA200" not in text
        # No golden/death cross line either (MA200=0)
        assert "Cross" not in text

    def test_format_empty_list(self):
        """Empty indicators → empty string."""
        assert format_technical_for_llm([]) == ""


# ---------------------------------------------------------------------------
# _yf_get_technical tests
# ---------------------------------------------------------------------------


class TestYfGetTechnical:
    """Test the sync yfinance helper function.

    WHY patch 'yfinance.Ticker': _yf_get_technical imports yfinance locally
    (`import yfinance as yf`), so we patch the actual yfinance module.
    """

    def test_success(self):
        """Mock yfinance Ticker → returns closes dict."""
        from cic_daily_report.collectors.market_data import _yf_get_technical

        mock_hist = MagicMock()
        mock_hist.empty = False
        mock_hist.__len__ = MagicMock(return_value=210)
        closes = [60000.0 + i * 10 for i in range(210)]
        mock_close_series = MagicMock()
        mock_close_series.tolist.return_value = closes
        mock_hist.__getitem__ = lambda self, key: mock_close_series

        mock_ticker = MagicMock()
        mock_ticker.history.return_value = mock_hist

        with patch("yfinance.Ticker", return_value=mock_ticker):
            result = _yf_get_technical("BTC-USD")

        assert result is not None
        assert len(result["closes"]) == 210
        assert result["current_price"] == closes[-1]

    def test_empty_history(self):
        """Empty history → returns None."""
        from cic_daily_report.collectors.market_data import _yf_get_technical

        mock_hist = MagicMock()
        mock_hist.empty = True
        mock_hist.__len__ = MagicMock(return_value=0)

        mock_ticker = MagicMock()
        mock_ticker.history.return_value = mock_hist

        with patch("yfinance.Ticker", return_value=mock_ticker):
            result = _yf_get_technical("BTC-USD")

        assert result is None

    def test_too_few_candles(self):
        """Fewer than 50 candles → returns None."""
        from cic_daily_report.collectors.market_data import _yf_get_technical

        mock_hist = MagicMock()
        mock_hist.empty = False
        mock_hist.__len__ = MagicMock(return_value=30)

        mock_ticker = MagicMock()
        mock_ticker.history.return_value = mock_hist

        with patch("yfinance.Ticker", return_value=mock_ticker):
            result = _yf_get_technical("BTC-USD")

        assert result is None
