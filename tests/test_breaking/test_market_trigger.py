"""Tests for breaking/market_trigger.py — market-based breaking detection."""

from cic_daily_report.breaking.market_trigger import (
    _drop_to_score,
    _find_data_point,
    detect_market_triggers,
)
from cic_daily_report.collectors.market_data import MarketDataPoint


def _make_dp(
    symbol="BTC", price=50000.0, change_24h=2.0, **kwargs
) -> MarketDataPoint:
    return MarketDataPoint(
        symbol=symbol,
        price=price,
        change_24h=change_24h,
        volume_24h=kwargs.get("volume_24h", 1e9),
        market_cap=kwargs.get("market_cap", 1e12),
        data_type=kwargs.get("data_type", "crypto"),
        source=kwargs.get("source", "CoinLore"),
    )


class TestDropToScore:
    def test_positive_change(self):
        assert _drop_to_score(5.0) == 0

    def test_zero_change(self):
        assert _drop_to_score(0.0) == 0

    def test_threshold_exact(self):
        assert _drop_to_score(-7.0) == 70

    def test_moderate_drop(self):
        score = _drop_to_score(-10.0)
        assert 75 <= score <= 85

    def test_severe_drop(self):
        score = _drop_to_score(-20.0)
        assert score == 100

    def test_extreme_drop_capped(self):
        assert _drop_to_score(-50.0) == 100


class TestFindDataPoint:
    def test_found(self):
        data = [_make_dp("BTC"), _make_dp("ETH")]
        result = _find_data_point(data, "BTC")
        assert result is not None
        assert result.symbol == "BTC"

    def test_case_insensitive(self):
        data = [_make_dp("BTC")]
        assert _find_data_point(data, "btc") is not None

    def test_not_found(self):
        data = [_make_dp("BTC")]
        assert _find_data_point(data, "SOL") is None

    def test_empty_list(self):
        assert _find_data_point([], "BTC") is None


class TestDetectMarketTriggers:
    def test_btc_crash(self):
        data = [_make_dp("BTC", price=45000, change_24h=-8.5)]
        events = detect_market_triggers(data)
        assert len(events) == 1
        assert "BTC" in events[0].title
        assert "crash" in events[0].matched_keywords
        assert events[0].raw_data["source_type"] == "market_trigger"

    def test_btc_normal_drop(self):
        data = [_make_dp("BTC", price=50000, change_24h=-3.0)]
        events = detect_market_triggers(data)
        assert len(events) == 0

    def test_btc_at_threshold(self):
        data = [_make_dp("BTC", price=46500, change_24h=-7.0)]
        events = detect_market_triggers(data)
        assert len(events) == 1

    def test_eth_crash(self):
        data = [_make_dp("ETH", price=2000, change_24h=-12.0)]
        events = detect_market_triggers(data)
        assert len(events) == 1
        assert "ETH" in events[0].title

    def test_eth_normal_drop(self):
        data = [_make_dp("ETH", price=2500, change_24h=-5.0)]
        events = detect_market_triggers(data)
        assert len(events) == 0

    def test_extreme_fear(self):
        data = [_make_dp("Fear&Greed", price=8, change_24h=0, data_type="index")]
        events = detect_market_triggers(data)
        assert len(events) == 1
        assert "Fear" in events[0].title

    def test_normal_fear(self):
        data = [_make_dp("Fear&Greed", price=35, change_24h=0, data_type="index")]
        events = detect_market_triggers(data)
        assert len(events) == 0

    def test_multiple_triggers(self):
        data = [
            _make_dp("BTC", price=40000, change_24h=-10.0),
            _make_dp("ETH", price=1800, change_24h=-15.0),
            _make_dp("Fear&Greed", price=5, change_24h=0, data_type="index"),
        ]
        events = detect_market_triggers(data)
        assert len(events) == 3

    def test_no_data(self):
        assert detect_market_triggers([]) == []

    def test_custom_thresholds(self):
        data = [_make_dp("BTC", price=45000, change_24h=-5.0)]
        events = detect_market_triggers(data, btc_threshold=-3.0)
        assert len(events) == 1

    def test_source_is_market_data(self):
        data = [_make_dp("BTC", price=40000, change_24h=-10.0)]
        events = detect_market_triggers(data)
        assert events[0].source == "market_data"
