"""Tests for P1.9 — Macro market triggers in market_trigger.py."""

from cic_daily_report.breaking.market_trigger import (
    DXY_SPIKE_THRESHOLD,
    GOLD_SPIKE_THRESHOLD,
    OIL_SPIKE_THRESHOLD,
    SPX_DROP_THRESHOLD,
    VIX_SPIKE_THRESHOLD,
    _spike_to_score,
    detect_market_triggers,
)
from cic_daily_report.collectors.market_data import MarketDataPoint


def _make_dp(symbol="BTC", price=50000.0, change_24h=2.0, **kwargs) -> MarketDataPoint:
    return MarketDataPoint(
        symbol=symbol,
        price=price,
        change_24h=change_24h,
        volume_24h=kwargs.get("volume_24h", 1e9),
        market_cap=kwargs.get("market_cap", 0),
        data_type=kwargs.get("data_type", "macro"),
        source=kwargs.get("source", "yfinance"),
    )


class TestSpikeToScore:
    """Unit tests for the _spike_to_score helper."""

    def test_at_threshold(self):
        # At exactly 1x threshold -> score = 70
        assert _spike_to_score(8.0, 8.0) == 70

    def test_double_threshold(self):
        # At 2x threshold -> score = 85
        assert _spike_to_score(16.0, 8.0) == 85

    def test_triple_threshold(self):
        # At 3x threshold -> score = 100
        assert _spike_to_score(24.0, 8.0) == 100

    def test_below_threshold(self):
        # Below threshold -> score < 70 (not 0; the caller guards with >= threshold)
        # WHY not 0: _spike_to_score is a pure math function; the >= threshold
        # check in _detect_macro_triggers prevents this from being called for
        # sub-threshold values in production.
        score = _spike_to_score(0.5, 8.0)
        assert score < 70

    def test_zero_change(self):
        assert _spike_to_score(0.0, 8.0) == 0

    def test_capped_at_100(self):
        assert _spike_to_score(100.0, 3.0) <= 100


class TestOilTrigger:
    def test_oil_spike_triggers(self):
        data = [_make_dp("Oil", price=95, change_24h=8.5)]
        events = detect_market_triggers(data)
        assert len(events) == 1
        assert "Dầu thô" in events[0].title
        assert "oil crisis" in events[0].matched_keywords
        assert events[0].raw_data["symbol"] == "Oil"
        assert events[0].raw_data["source_type"] == "market_trigger"

    def test_oil_at_threshold(self):
        data = [_make_dp("Oil", price=90, change_24h=OIL_SPIKE_THRESHOLD)]
        events = detect_market_triggers(data)
        assert len(events) == 1

    def test_oil_below_threshold_no_trigger(self):
        data = [_make_dp("Oil", price=80, change_24h=5.0)]
        events = detect_market_triggers(data)
        assert len(events) == 0

    def test_oil_negative_change_no_trigger(self):
        data = [_make_dp("Oil", price=70, change_24h=-3.0)]
        events = detect_market_triggers(data)
        assert len(events) == 0


class TestGoldTrigger:
    def test_gold_spike_triggers(self):
        data = [_make_dp("Gold", price=2100, change_24h=3.5)]
        events = detect_market_triggers(data)
        assert len(events) == 1
        assert "Vàng" in events[0].title
        assert "gold spike" in events[0].matched_keywords
        assert events[0].raw_data["symbol"] == "Gold"

    def test_gold_at_threshold(self):
        data = [_make_dp("Gold", price=2050, change_24h=GOLD_SPIKE_THRESHOLD)]
        events = detect_market_triggers(data)
        assert len(events) == 1

    def test_gold_below_threshold_no_trigger(self):
        data = [_make_dp("Gold", price=2000, change_24h=1.5)]
        events = detect_market_triggers(data)
        assert len(events) == 0


class TestVixTrigger:
    def test_vix_spike_triggers(self):
        """VIX uses absolute value (price >= 30), not change_24h."""
        data = [_make_dp("VIX", price=35, change_24h=5.0, data_type="index")]
        events = detect_market_triggers(data)
        assert len(events) == 1
        assert "VIX" in events[0].title
        assert "VIX spike" in events[0].matched_keywords
        assert events[0].raw_data["symbol"] == "VIX"

    def test_vix_at_threshold(self):
        data = [_make_dp("VIX", price=VIX_SPIKE_THRESHOLD, change_24h=2.0, data_type="index")]
        events = detect_market_triggers(data)
        assert len(events) == 1

    def test_vix_below_threshold_no_trigger(self):
        data = [_make_dp("VIX", price=22, change_24h=8.0, data_type="index")]
        events = detect_market_triggers(data)
        assert len(events) == 0

    def test_vix_panic_score_scaling(self):
        """Higher VIX -> higher panic score."""
        data = [_make_dp("VIX", price=50, change_24h=10.0, data_type="index")]
        events = detect_market_triggers(data)
        assert len(events) == 1
        assert events[0].panic_score == 90  # 70 + (50 - 30) = 90


class TestDxyTrigger:
    def test_dxy_spike_triggers(self):
        data = [_make_dp("DXY", price=106.5, change_24h=2.5)]
        events = detect_market_triggers(data)
        assert len(events) == 1
        assert "Dollar Index" in events[0].title
        assert "DXY spike" in events[0].matched_keywords

    def test_dxy_at_threshold(self):
        data = [_make_dp("DXY", price=105, change_24h=DXY_SPIKE_THRESHOLD)]
        events = detect_market_triggers(data)
        assert len(events) == 1

    def test_dxy_below_threshold_no_trigger(self):
        data = [_make_dp("DXY", price=104, change_24h=1.0)]
        events = detect_market_triggers(data)
        assert len(events) == 0


class TestSpxTrigger:
    def test_spx_drop_triggers(self):
        data = [_make_dp("SPX", price=4800, change_24h=-3.5, data_type="index")]
        events = detect_market_triggers(data)
        assert len(events) == 1
        assert "S&P 500" in events[0].title
        assert "SPX drop" in events[0].matched_keywords

    def test_spx_at_threshold(self):
        data = [_make_dp("SPX", price=4900, change_24h=SPX_DROP_THRESHOLD, data_type="index")]
        events = detect_market_triggers(data)
        assert len(events) == 1

    def test_spx_above_threshold_no_trigger(self):
        data = [_make_dp("SPX", price=5000, change_24h=-1.5, data_type="index")]
        events = detect_market_triggers(data)
        assert len(events) == 0


class TestMultipleMacroTriggers:
    def test_oil_and_gold_spike_together(self):
        data = [
            _make_dp("Oil", price=95, change_24h=10.0),
            _make_dp("Gold", price=2100, change_24h=4.0),
        ]
        events = detect_market_triggers(data)
        assert len(events) == 2
        symbols = {e.raw_data["symbol"] for e in events}
        assert symbols == {"Oil", "Gold"}

    def test_all_macro_triggers_fire(self):
        """All 5 macro triggers + BTC + ETH + F&G = 8 events."""
        data = [
            _make_dp("BTC", price=40000, change_24h=-8.0, data_type="crypto"),
            _make_dp("ETH", price=1800, change_24h=-12.0, data_type="crypto"),
            _make_dp("Fear&Greed", price=5, change_24h=0, data_type="index"),
            _make_dp("Oil", price=100, change_24h=12.0),
            _make_dp("Gold", price=2200, change_24h=5.0),
            _make_dp("VIX", price=40, change_24h=15.0, data_type="index"),
            _make_dp("DXY", price=108, change_24h=3.0),
            _make_dp("SPX", price=4500, change_24h=-4.0, data_type="index"),
        ]
        events = detect_market_triggers(data)
        assert len(events) == 8


class TestExistingTriggersStillWork:
    """Regression: BTC/ETH/F&G triggers unaffected by P1.9 macro additions."""

    def test_btc_crash_still_works(self):
        data = [_make_dp("BTC", price=42000, change_24h=-8.0, data_type="crypto")]
        events = detect_market_triggers(data)
        assert len(events) == 1
        assert "BTC" in events[0].title

    def test_eth_crash_still_works(self):
        data = [_make_dp("ETH", price=1900, change_24h=-11.0, data_type="crypto")]
        events = detect_market_triggers(data)
        assert len(events) == 1
        assert "ETH" in events[0].title

    def test_extreme_fear_still_works(self):
        data = [_make_dp("Fear&Greed", price=8, change_24h=0, data_type="index")]
        events = detect_market_triggers(data)
        assert len(events) == 1
        assert "Fear" in events[0].title


class TestMissingDataGraceful:
    def test_no_oil_data_no_crash(self):
        """Missing data point -> no event, no error."""
        data = [_make_dp("BTC", price=50000, change_24h=1.0)]
        events = detect_market_triggers(data)
        assert len(events) == 0

    def test_empty_market_data(self):
        events = detect_market_triggers([])
        assert events == []


class TestTriggerTitlesVietnamese:
    """Verify Vietnamese title format for all macro triggers."""

    def test_oil_title_format(self):
        data = [_make_dp("Oil", price=95, change_24h=10.0)]
        events = detect_market_triggers(data)
        title = events[0].title
        assert "Dầu thô tăng" in title
        assert "/thùng" in title

    def test_gold_title_format(self):
        data = [_make_dp("Gold", price=2100, change_24h=4.0)]
        events = detect_market_triggers(data)
        title = events[0].title
        assert "Vàng tăng" in title
        assert "/oz" in title

    def test_vix_title_format(self):
        data = [_make_dp("VIX", price=35, change_24h=5.0, data_type="index")]
        events = detect_market_triggers(data)
        title = events[0].title
        assert "VIX" in title
        assert "biến động lớn" in title

    def test_dxy_title_format(self):
        data = [_make_dp("DXY", price=106, change_24h=2.5)]
        events = detect_market_triggers(data)
        title = events[0].title
        assert "Dollar Index" in title
        assert "áp lực" in title

    def test_spx_title_format(self):
        data = [_make_dp("SPX", price=4800, change_24h=-3.5, data_type="index")]
        events = detect_market_triggers(data)
        title = events[0].title
        assert "S&P 500" in title
        assert "bán tháo" in title

    def test_source_is_market_data(self):
        """All macro triggers have source='market_data'."""
        data = [_make_dp("Oil", price=95, change_24h=10.0)]
        events = detect_market_triggers(data)
        assert events[0].source == "market_data"
