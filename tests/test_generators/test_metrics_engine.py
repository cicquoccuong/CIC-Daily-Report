"""Tests for generators/metrics_engine.py — Metrics Engine, Regime, Narratives."""

from cic_daily_report.collectors.market_data import MarketDataPoint
from cic_daily_report.collectors.onchain_data import OnChainMetric
from cic_daily_report.generators.metrics_engine import (
    REGIME_BEAR,
    REGIME_BULL,
    REGIME_DISTRIBUTION,
    REGIME_NEUTRAL,
    REGIME_RECOVERY,
    classify_market_regime,
    detect_narratives,
    format_narratives_for_llm,
    interpret_metrics,
)


def _btc(price: float = 65000, change_24h: float = 0.0, volume: float = 30e9) -> MarketDataPoint:
    return MarketDataPoint(
        symbol="BTC",
        price=price,
        change_24h=change_24h,
        volume_24h=volume,
        market_cap=1.2e12,
        data_type="crypto",
        source="test",
    )


def _fg(value: int) -> dict:
    return {"Fear & Greed": value}


def _funding(rate: float) -> OnChainMetric:
    return OnChainMetric(metric_name="BTC_Funding_Rate", value=rate, source="test")


def _oi(value: float) -> OnChainMetric:
    return OnChainMetric(metric_name="BTC_Open_Interest", value=value, source="test")


def _ls_ratio(value: float) -> OnChainMetric:
    return OnChainMetric(metric_name="BTC_Long_Short_Ratio", value=value, source="test")


# ---------------------------------------------------------------------------
# Market Regime classification
# ---------------------------------------------------------------------------


class TestMarketRegime:
    def test_strong_bull(self):
        """BTC +6%, F&G=80 → Bull high confidence."""
        regime = classify_market_regime(
            [_btc(change_24h=6.0)],
            [_funding(0.001)],
            {"Fear & Greed": 80},
        )
        assert regime.regime == REGIME_BULL
        assert regime.confidence == "high"

    def test_strong_bear(self):
        """BTC -6%, F&G=15 → Bear high confidence."""
        regime = classify_market_regime(
            [_btc(change_24h=-6.0)],
            [_funding(-0.001)],
            {"Fear & Greed": 15},
        )
        assert regime.regime == REGIME_BEAR
        assert regime.confidence == "high"

    def test_neutral_sideways(self):
        """BTC flat, F&G=50 → Neutral."""
        regime = classify_market_regime(
            [_btc(change_24h=0.5)],
            [],
            {"Fear & Greed": 50},
        )
        assert regime.regime == REGIME_NEUTRAL

    def test_recovery_from_fear(self):
        """Mild positive with Fear sentiment + weak USD → Recovery."""
        regime = classify_market_regime(
            [_btc(change_24h=3.0)],
            [],
            {"Fear & Greed": 30, "DXY": 98.0},
        )
        # score: BTC+3%=+1, F&G=30=-1, DXY<100=+1 → net=+1, F&G<=40 → Recovery
        assert regime.regime == REGIME_RECOVERY

    def test_distribution_from_greed(self):
        """Mild negative with Greed sentiment + strong USD → Distribution."""
        regime = classify_market_regime(
            [_btc(change_24h=-3.0)],
            [],
            {"Fear & Greed": 70, "DXY": 106.0},
        )
        # score: BTC-3%=-1, F&G=70=+1, DXY>105=-1 → net=-1, F&G>=60 → Distribution
        assert regime.regime == REGIME_DISTRIBUTION

    def test_dxy_strong_bearish_signal(self):
        """DXY >= 105 adds bearish signal."""
        regime = classify_market_regime(
            [_btc(change_24h=-1.0)],
            [],
            {"Fear & Greed": 45, "DXY": 106.5},
        )
        # DXY strong = -1, BTC flat = 0, F&G neutral = 0 → score = -1
        assert regime.regime in (REGIME_BEAR, REGIME_NEUTRAL)

    def test_signals_populated(self):
        """Regime signals should contain descriptive text."""
        regime = classify_market_regime(
            [_btc(change_24h=2.5)],
            [_funding(0.0008)],
            {"Fear & Greed": 65, "DXY": 99.0},
        )
        assert len(regime.signals) >= 2
        assert any("BTC" in s for s in regime.signals)

    def test_format_vi(self):
        """Vietnamese format should include regime name."""
        regime = classify_market_regime([_btc(change_24h=5.0)], [], {"Fear & Greed": 70})
        formatted = regime.format_vi()
        assert "TRẠNG THÁI THỊ TRƯỜNG" in formatted

    def test_empty_data(self):
        """No data → Neutral."""
        regime = classify_market_regime([], [], {})
        assert regime.regime == REGIME_NEUTRAL


# ---------------------------------------------------------------------------
# Metrics Interpreter
# ---------------------------------------------------------------------------


class TestInterpretMetrics:
    def test_returns_all_fields(self):
        result = interpret_metrics(
            [_btc(change_24h=2.0)],
            [_funding(0.0005), _oi(15e9), _ls_ratio(1.2)],
            {"Fear & Greed": 55, "DXY": 103.0},
        )
        assert result.regime is not None
        assert result.derivatives_analysis
        assert result.macro_analysis
        assert result.sentiment_analysis
        assert result.cross_signal_summary

    def test_tier_specific_formatting(self):
        result = interpret_metrics(
            [_btc(change_24h=2.0)],
            [_funding(0.0005)],
            {"Fear & Greed": 55},
        )
        l1_text = result.format_for_tier("L1")
        l5_text = result.format_for_tier("L5")
        # L5 should have more content than L1
        assert len(l5_text) > len(l1_text)
        # L1 should have sentiment but not derivatives
        assert "SENTIMENT" in l1_text
        # L5 should have everything
        assert "DERIVATIVES" in l5_text
        assert "TỔNG HỢP TÍN HIỆU" in l5_text

    def test_l3_includes_derivatives_and_macro(self):
        result = interpret_metrics(
            [_btc()],
            [_funding(0.0005)],
            {"Fear & Greed": 50, "DXY": 104.0},
        )
        l3_text = result.format_for_tier("L3")
        assert "DERIVATIVES" in l3_text
        assert "MACRO" in l3_text

    def test_l4_includes_cross_signals(self):
        result = interpret_metrics(
            [_btc(change_24h=3.0)],
            [_funding(-0.0002)],
            {"Fear & Greed": 30},
        )
        l4_text = result.format_for_tier("L4")
        assert "TÍN HIỆU" in l4_text

    def test_derivatives_extreme_funding_rate(self):
        result = interpret_metrics(
            [_btc()],
            [_funding(0.001)],  # 0.1% = extreme
            {},
        )
        assert "CẢNH BÁO" in result.derivatives_analysis

    def test_derivatives_negative_funding_rate(self):
        result = interpret_metrics(
            [_btc()],
            [_funding(-0.0003)],  # -0.03% = negative
            {},
        )
        assert "Âm" in result.derivatives_analysis

    def test_derivatives_no_data(self):
        result = interpret_metrics([_btc()], [], {})
        assert "Không có dữ liệu" in result.derivatives_analysis

    def test_long_short_ratio_extreme_long(self):
        result = interpret_metrics(
            [_btc()],
            [_ls_ratio(1.8)],
            {},
        )
        assert "Rất thiên long" in result.derivatives_analysis

    def test_long_short_ratio_short_bias(self):
        result = interpret_metrics(
            [_btc()],
            [_ls_ratio(0.6)],
            {},
        )
        assert "Thiên short mạnh" in result.derivatives_analysis

    def test_cross_signals_conflict(self):
        """Bullish price + bearish sentiment → conflict."""
        result = interpret_metrics(
            [_btc(change_24h=3.0)],
            [],
            {"Fear & Greed": 25, "DXY": 106.0},
        )
        assert "MÂU THUẪN" in result.cross_signal_summary

    def test_cross_signals_agreement_bull(self):
        """All bullish signals → agreement."""
        result = interpret_metrics(
            [_btc(change_24h=4.0)],
            [_funding(0.0003)],
            {"Fear & Greed": 70, "DXY": 98.0},
        )
        assert "ĐỒNG THUẬN TĂNG" in result.cross_signal_summary


# ---------------------------------------------------------------------------
# Narrative Detection
# ---------------------------------------------------------------------------


class TestNarrativeDetection:
    def test_detects_etf_narrative(self):
        news = [
            {"title": "Bitcoin ETF sees record inflows"},
            {"title": "SEC approves spot Ethereum ETF"},
            {"title": "ETF approval boosts crypto market"},
            {"title": "BlackRock Bitcoin ETF hits $10B AUM"},
        ]
        narratives = detect_narratives(news, min_mentions=3)
        names = [n.name for n in narratives]
        assert "ETF" in names

    def test_min_mentions_filter(self):
        news = [
            {"title": "Bitcoin ETF news"},
            {"title": "ETF update"},
        ]
        # Only 2 mentions, min=3
        narratives = detect_narratives(news, min_mentions=3)
        assert len(narratives) == 0

    def test_multiple_narratives(self):
        news = [
            {"title": "Bitcoin ETF approval"},
            {"title": "SEC reviews ETF application"},
            {"title": "New ETF launches today"},
            {"title": "Major exchange hack reported"},
            {"title": "Exchange security breach"},
            {"title": "Hack leads to $100M loss"},
        ]
        narratives = detect_narratives(news, min_mentions=3)
        names = [n.name for n in narratives]
        assert len(names) >= 2

    def test_sorted_by_count(self):
        news = [{"title": f"ETF news {i}"} for i in range(5)]
        news += [{"title": f"DeFi update {i}"} for i in range(3)]
        narratives = detect_narratives(news, min_mentions=2)
        if len(narratives) >= 2:
            assert narratives[0].mention_count >= narratives[1].mention_count

    def test_sample_titles_limited(self):
        news = [{"title": f"ETF headline {i}"} for i in range(10)]
        narratives = detect_narratives(news, min_mentions=2)
        for n in narratives:
            assert len(n.sample_titles) <= 3

    def test_empty_news(self):
        narratives = detect_narratives([], min_mentions=1)
        assert narratives == []

    def test_format_narratives_for_llm(self):
        news = [{"title": f"Bitcoin ETF news {i}"} for i in range(5)]
        narratives = detect_narratives(news, min_mentions=2)
        text = format_narratives_for_llm(narratives)
        assert "CHỦ ĐỀ NÓNG" in text

    def test_format_empty_narratives(self):
        text = format_narratives_for_llm([])
        assert text == ""

    def test_case_insensitive(self):
        news = [
            {"title": "BITCOIN ETF approved"},
            {"title": "bitcoin etf flows"},
            {"title": "Bitcoin ETF Record"},
        ]
        narratives = detect_narratives(news, min_mentions=3)
        names = [n.name for n in narratives]
        assert "ETF" in names
