"""Tests for generators/consensus_engine.py — Expert Consensus Engine v1 (P1.6).

Tests covering:
  - Dataclass creation (2)
  - Score calculation (8)
  - Label mapping (5)
  - Source extraction (10)
  - ETF neutral band (4)
  - ETH proxy transparency (5)
  - market_overall composite (6)
  - Integration / build_consensus (8)
  - Format for LLM (3)
"""

from __future__ import annotations

import pytest

from cic_daily_report.collectors.market_data import MarketDataPoint
from cic_daily_report.collectors.onchain_data import OnChainMetric
from cic_daily_report.collectors.prediction_markets import (
    PredictionMarket,
    PredictionMarketsData,
)
from cic_daily_report.collectors.research_data import (
    ETFFlowData,
    ETFFlowEntry,
    ResearchData,
)
from cic_daily_report.collectors.whale_alert import (
    WhaleAlertSummary,
    WhaleTransaction,
)
from cic_daily_report.generators.consensus_engine import (
    ETF_NEUTRAL_BAND,
    ETH_PROXY_CONFIDENCE_PENALTY,
    MARKET_OVERALL_WEIGHTS,
    WEIGHTS,
    ConsensusSource,
    MarketConsensus,
    _build_market_overall_consensus,
    _calculate_weighted_score,
    _detect_contrarians,
    _detect_divergence_alerts,
    _extract_from_etf_flows,
    _extract_from_fear_greed,
    _extract_from_funding_rate,
    _extract_from_polymarket,
    _extract_from_whale_flows,
    _maybe_proxy,
    _score_to_label,
    build_consensus,
    format_consensus_for_llm,
)

# ---------------------------------------------------------------------------
# Helpers — reusable test data builders
# ---------------------------------------------------------------------------


def _make_polymarket(
    asset: str = "BTC", yes: float = 0.72, volume: float = 5e6
) -> PredictionMarketsData:
    """Build a PredictionMarketsData with one market for the given asset."""
    return PredictionMarketsData(
        markets=[
            PredictionMarket(
                question=f"Will {asset} reach $100K?",
                outcome_yes=yes,
                outcome_no=round(1.0 - yes, 2),
                volume=volume,
                liquidity=1e6,
                end_date="2026-04-30",
                url="https://polymarket.com/event/test",
                asset=asset,
            )
        ],
        fetch_timestamp="2026-03-28T08:00:00Z",
    )


def _make_fg(value: float = 50.0) -> list[MarketDataPoint]:
    """Build market data list containing a Fear&Greed data point."""
    return [
        MarketDataPoint(
            symbol="Fear&Greed",
            price=value,
            change_24h=0,
            volume_24h=0,
            market_cap=0,
            data_type="index",
            source="alternative.me",
        )
    ]


def _make_funding_rate(rate: float = 0.0005) -> list[OnChainMetric]:
    """Build onchain metrics list containing a BTC_Funding_Rate."""
    return [OnChainMetric("BTC_Funding_Rate", rate, "Binance", "8h rate")]


def _make_whale_summary(inflow: float = 0.0, outflow: float = 0.0) -> WhaleAlertSummary:
    """Build whale alert summary with BTC inflow/outflow."""
    txs = []
    if inflow > 0:
        txs.append(
            WhaleTransaction(
                blockchain="bitcoin",
                symbol="btc",
                amount=inflow / 100_000,
                amount_usd=inflow,
                from_owner="unknown",
                to_owner="exchange",
                from_name="",
                to_name="Binance",
                timestamp=1711612800,
            )
        )
    if outflow > 0:
        txs.append(
            WhaleTransaction(
                blockchain="bitcoin",
                symbol="btc",
                amount=outflow / 100_000,
                amount_usd=outflow,
                from_owner="exchange",
                to_owner="unknown",
                from_name="Coinbase",
                to_name="",
                timestamp=1711612800,
            )
        )
    return WhaleAlertSummary(
        transactions=txs,
        total_count=len(txs),
        btc_inflow_usd=inflow,
        btc_outflow_usd=outflow,
    )


def _make_etf_research(total_flow: float = 200_000_000) -> ResearchData:
    """Build ResearchData with ETF flow data."""
    return ResearchData(
        etf_flows=ETFFlowData(
            entries=[
                ETFFlowEntry(etf_name="IBIT", flow_usd=total_flow * 0.6),
                ETFFlowEntry(etf_name="FBTC", flow_usd=total_flow * 0.4),
            ],
            total_flow_usd=total_flow,
            date="2026-03-28",
            recent_total_flows=[
                ("2026-03-24", 100_000_000),
                ("2026-03-25", -50_000_000),
                ("2026-03-26", 300_000_000),
                ("2026-03-27", 150_000_000),
                ("2026-03-28", total_flow),
            ],
        )
    )


# ===========================================================================
# ConsensusSource & MarketConsensus dataclass tests
# ===========================================================================


class TestConsensusSourceCreation:
    def test_consensus_source_creation(self):
        src = ConsensusSource(
            name="Polymarket",
            sentiment="BULLISH",
            confidence=0.8,
            key_levels={"support": 65000},
            thesis="72% YES",
            timestamp="2026-03-28T08:00:00Z",
            weight=3.0,
        )
        assert src.name == "Polymarket"
        assert src.sentiment == "BULLISH"
        assert src.confidence == 0.8
        assert src.key_levels == {"support": 65000}
        assert src.thesis == "72% YES"
        assert src.weight == 3.0

    def test_consensus_source_defaults(self):
        src = ConsensusSource(name="Test", sentiment="NEUTRAL", confidence=0.5)
        assert src.key_levels == {}
        assert src.thesis == ""
        assert src.timestamp == ""
        assert src.weight == 1.0


class TestMarketConsensusCreation:
    def test_market_consensus_creation(self):
        mc = MarketConsensus(
            asset="BTC",
            score=0.45,
            label="BULLISH",
            source_count=5,
            bullish_pct=60.0,
        )
        assert mc.asset == "BTC"
        assert mc.score == 0.45
        assert mc.label == "BULLISH"
        assert mc.source_count == 5
        assert mc.bullish_pct == 60.0
        assert mc.sources == []
        assert mc.contrarians == []
        assert mc.divergence_alerts == []
        assert mc.polymarket == {}
        assert mc.key_levels == {}


# ===========================================================================
# Score calculation tests
# ===========================================================================


class TestScoreCalculation:
    def test_score_all_bullish(self):
        """All sources BULLISH -> score near +1.0."""
        sources = [
            ConsensusSource("A", "BULLISH", 1.0, weight=2.0),
            ConsensusSource("B", "BULLISH", 1.0, weight=3.0),
            ConsensusSource("C", "BULLISH", 0.8, weight=1.0),
        ]
        score = _calculate_weighted_score(sources)
        assert score == pytest.approx(1.0)

    def test_score_all_bearish(self):
        """All sources BEARISH -> score near -1.0."""
        sources = [
            ConsensusSource("A", "BEARISH", 1.0, weight=2.0),
            ConsensusSource("B", "BEARISH", 0.9, weight=3.0),
        ]
        score = _calculate_weighted_score(sources)
        assert score == pytest.approx(-1.0)

    def test_score_mixed(self):
        """Mixed sentiment -> intermediate score."""
        sources = [
            ConsensusSource("A", "BULLISH", 1.0, weight=1.0),
            ConsensusSource("B", "BEARISH", 1.0, weight=1.0),
        ]
        score = _calculate_weighted_score(sources)
        # Equal weight and confidence -> 0.0
        assert score == pytest.approx(0.0)

    def test_score_weighted(self):
        """Higher weight sources dominate the result."""
        sources = [
            ConsensusSource("heavy", "BULLISH", 1.0, weight=10.0),
            ConsensusSource("light", "BEARISH", 1.0, weight=1.0),
        ]
        score = _calculate_weighted_score(sources)
        # (10*1 + 1*(-1)) / (10+1) = 9/11 ≈ 0.818
        assert score == pytest.approx(9.0 / 11.0, abs=0.001)

    def test_score_with_confidence(self):
        """Low confidence sources have less impact."""
        sources = [
            ConsensusSource("high_conf", "BULLISH", 1.0, weight=1.0),
            ConsensusSource("low_conf", "BEARISH", 0.1, weight=1.0),
        ]
        score = _calculate_weighted_score(sources)
        # (1*1*1 + (-1)*1*0.1) / (1*1 + 1*0.1) = 0.9/1.1 ≈ 0.818
        assert score == pytest.approx(0.9 / 1.1, abs=0.001)

    def test_score_clamped(self):
        """Score never exceeds [-1.0, +1.0]."""
        sources = [
            ConsensusSource("A", "BULLISH", 1.0, weight=999.0),
        ]
        score = _calculate_weighted_score(sources)
        assert -1.0 <= score <= 1.0

    def test_score_empty_sources(self):
        """No sources -> score 0.0."""
        assert _calculate_weighted_score([]) == 0.0

    def test_score_zero_confidence(self):
        """All zero confidence -> score 0.0 (no division by zero)."""
        sources = [
            ConsensusSource("A", "BULLISH", 0.0, weight=3.0),
        ]
        assert _calculate_weighted_score(sources) == 0.0


# ===========================================================================
# Label mapping tests
# ===========================================================================


class TestLabelMapping:
    def test_label_strong_bullish(self):
        assert _score_to_label(0.6) == "STRONG_BULLISH"
        assert _score_to_label(0.9) == "STRONG_BULLISH"
        assert _score_to_label(1.0) == "STRONG_BULLISH"

    def test_label_bullish(self):
        assert _score_to_label(0.2) == "BULLISH"
        assert _score_to_label(0.5) == "BULLISH"
        assert _score_to_label(0.59) == "BULLISH"

    def test_label_neutral(self):
        assert _score_to_label(0.0) == "NEUTRAL"
        assert _score_to_label(0.19) == "NEUTRAL"
        assert _score_to_label(-0.19) == "NEUTRAL"

    def test_label_bearish(self):
        assert _score_to_label(-0.2) == "BEARISH"
        assert _score_to_label(-0.5) == "BEARISH"
        assert _score_to_label(-0.59) == "BEARISH"

    def test_label_strong_bearish(self):
        assert _score_to_label(-0.6) == "STRONG_BEARISH"
        assert _score_to_label(-0.9) == "STRONG_BEARISH"
        assert _score_to_label(-1.0) == "STRONG_BEARISH"


# ===========================================================================
# Source extraction tests
# ===========================================================================


class TestExtractPolymarket:
    def test_extract_polymarket_bullish(self):
        """High YES probability -> BULLISH."""
        data = _make_polymarket(asset="BTC", yes=0.72)
        results = _extract_from_polymarket(data, "BTC")
        assert len(results) == 1
        src = results[0]
        assert src.sentiment == "BULLISH"
        assert src.weight == WEIGHTS["prediction_markets"]
        assert src.confidence > 0.0
        assert "72%" in src.thesis

    def test_extract_polymarket_bearish(self):
        """Low YES probability -> BEARISH."""
        data = _make_polymarket(asset="BTC", yes=0.30)
        results = _extract_from_polymarket(data, "BTC")
        assert len(results) == 1
        assert results[0].sentiment == "BEARISH"

    def test_extract_polymarket_neutral(self):
        """Middle YES probability -> NEUTRAL."""
        data = _make_polymarket(asset="BTC", yes=0.50)
        results = _extract_from_polymarket(data, "BTC")
        assert len(results) == 1
        assert results[0].sentiment == "NEUTRAL"

    def test_extract_polymarket_empty(self):
        """No markets -> empty list."""
        data = PredictionMarketsData(markets=[], fetch_timestamp="")
        assert _extract_from_polymarket(data, "BTC") == []

    def test_extract_polymarket_none(self):
        """None data -> empty list."""
        assert _extract_from_polymarket(None, "BTC") == []

    def test_extract_polymarket_wrong_asset(self):
        """No matching asset -> empty list."""
        data = _make_polymarket(asset="ETH", yes=0.72)
        assert _extract_from_polymarket(data, "BTC") == []


class TestExtractFearGreed:
    def test_extract_fear_greed_extreme_fear(self):
        """F&G=10 -> BEARISH."""
        src = _extract_from_fear_greed(_make_fg(10))
        assert src is not None
        assert src.sentiment == "BEARISH"
        assert src.weight == WEIGHTS["social_sentiment"]
        assert src.confidence == pytest.approx(0.8, abs=0.01)

    def test_extract_fear_greed_extreme_greed(self):
        """F&G=85 -> BULLISH."""
        src = _extract_from_fear_greed(_make_fg(85))
        assert src is not None
        assert src.sentiment == "BULLISH"
        assert src.confidence == pytest.approx(0.7, abs=0.01)

    def test_extract_fear_greed_neutral(self):
        """F&G=50 -> NEUTRAL."""
        src = _extract_from_fear_greed(_make_fg(50))
        assert src is not None
        assert src.sentiment == "NEUTRAL"
        assert src.confidence == pytest.approx(0.0, abs=0.01)

    def test_extract_fear_greed_empty(self):
        """Empty market_data -> None."""
        assert _extract_from_fear_greed([]) is None

    def test_extract_fear_greed_no_fg_point(self):
        """Market data without F&G -> None."""
        data = [MarketDataPoint("BTC", 100000, 2.0, 50e9, 2e12, "crypto", "CoinLore")]
        assert _extract_from_fear_greed(data) is None


class TestExtractFundingRate:
    def test_extract_funding_rate_positive(self):
        """FR > 0.01% -> BULLISH."""
        src = _extract_from_funding_rate(_make_funding_rate(0.0005))
        assert src is not None
        assert src.sentiment == "BULLISH"
        assert src.weight == WEIGHTS["smart_money"]

    def test_extract_funding_rate_negative(self):
        """FR < -0.01% -> BEARISH."""
        src = _extract_from_funding_rate(_make_funding_rate(-0.0005))
        assert src is not None
        assert src.sentiment == "BEARISH"

    def test_extract_funding_rate_neutral(self):
        """FR near zero -> NEUTRAL."""
        src = _extract_from_funding_rate(_make_funding_rate(0.00005))
        assert src is not None
        assert src.sentiment == "NEUTRAL"

    def test_extract_funding_rate_none(self):
        """None data -> None."""
        assert _extract_from_funding_rate(None) is None

    def test_extract_funding_rate_no_metric(self):
        """Onchain data without FR metric -> None."""
        data = [OnChainMetric("BTC_Open_Interest", 18e9, "okx")]
        assert _extract_from_funding_rate(data) is None


class TestExtractWhaleFlows:
    def test_extract_whale_outflow(self):
        """Net outflow > $10M -> BULLISH (accumulation)."""
        summary = _make_whale_summary(inflow=5_000_000, outflow=50_000_000)
        src = _extract_from_whale_flows(summary)
        assert src is not None
        assert src.sentiment == "BULLISH"
        assert src.weight == WEIGHTS["smart_money"]

    def test_extract_whale_inflow(self):
        """Net inflow > $10M -> BEARISH (distribution)."""
        summary = _make_whale_summary(inflow=50_000_000, outflow=5_000_000)
        src = _extract_from_whale_flows(summary)
        assert src is not None
        assert src.sentiment == "BEARISH"

    def test_extract_whale_neutral(self):
        """Small net flow -> NEUTRAL."""
        summary = _make_whale_summary(inflow=5_000_000, outflow=4_000_000)
        src = _extract_from_whale_flows(summary)
        assert src is not None
        assert src.sentiment == "NEUTRAL"

    def test_extract_whale_none(self):
        """None data -> None."""
        assert _extract_from_whale_flows(None) is None

    def test_extract_whale_empty(self):
        """Empty summary -> None."""
        assert _extract_from_whale_flows(WhaleAlertSummary()) is None


class TestExtractEtfFlows:
    def test_extract_etf_positive_flow(self):
        """Positive ETF flow -> BULLISH."""
        src = _extract_from_etf_flows(_make_etf_research(200_000_000))
        assert src is not None
        assert src.sentiment == "BULLISH"
        assert src.weight == WEIGHTS["smart_money"]

    def test_extract_etf_negative_flow(self):
        """Negative ETF flow -> BEARISH."""
        src = _extract_from_etf_flows(_make_etf_research(-200_000_000))
        assert src is not None
        assert src.sentiment == "BEARISH"

    def test_extract_etf_zero_flow(self):
        """Zero ETF flow -> NEUTRAL with low confidence (inside neutral band)."""
        src = _extract_from_etf_flows(_make_etf_research(0))
        assert src is not None
        assert src.sentiment == "NEUTRAL"
        # WHY 0.3: inside ETF_NEUTRAL_BAND -> fixed low confidence
        assert src.confidence == pytest.approx(0.3, abs=0.01)

    def test_extract_etf_none(self):
        """None data -> None."""
        assert _extract_from_etf_flows(None) is None

    def test_extract_etf_no_entries(self):
        """ResearchData with empty ETF entries -> None."""
        rd = ResearchData(etf_flows=ETFFlowData(entries=[]))
        assert _extract_from_etf_flows(rd) is None

    def test_extract_etf_confidence_scales(self):
        """Confidence scales with flow magnitude (relative to $500M)."""
        # $500M flow -> confidence = 1.0
        src_large = _extract_from_etf_flows(_make_etf_research(500_000_000))
        assert src_large is not None
        assert src_large.confidence == pytest.approx(1.0, abs=0.01)

        # $100M flow (above neutral band) -> confidence = 100/500 = 0.2
        src_medium = _extract_from_etf_flows(_make_etf_research(100_000_000))
        assert src_medium is not None
        assert src_medium.confidence == pytest.approx(0.2, abs=0.01)
        assert src_medium.sentiment == "BULLISH"


# ===========================================================================
# Issue 3 — ETF neutral band tests
# ===========================================================================


class TestEtfNeutralBand:
    """Verify ETF_NEUTRAL_BAND ($50M) filters noise flows."""

    def test_etf_inside_neutral_band_positive(self):
        """$10M positive flow -> NEUTRAL (inside $50M band)."""
        src = _extract_from_etf_flows(_make_etf_research(10_000_000))
        assert src is not None
        assert src.sentiment == "NEUTRAL"
        assert src.confidence == pytest.approx(0.3, abs=0.01)

    def test_etf_inside_neutral_band_negative(self):
        """$-30M flow -> NEUTRAL (inside $50M band)."""
        src = _extract_from_etf_flows(_make_etf_research(-30_000_000))
        assert src is not None
        assert src.sentiment == "NEUTRAL"
        assert src.confidence == pytest.approx(0.3, abs=0.01)

    def test_etf_above_neutral_band_bullish(self):
        """$60M positive flow -> BULLISH (above $50M band)."""
        src = _extract_from_etf_flows(_make_etf_research(60_000_000))
        assert src is not None
        assert src.sentiment == "BULLISH"
        assert src.confidence == pytest.approx(60 / 500, abs=0.01)

    def test_etf_below_neutral_band_bearish(self):
        """$-80M flow -> BEARISH (below -$50M band)."""
        src = _extract_from_etf_flows(_make_etf_research(-80_000_000))
        assert src is not None
        assert src.sentiment == "BEARISH"
        assert src.confidence == pytest.approx(80 / 500, abs=0.01)

    def test_etf_neutral_band_constant(self):
        """ETF_NEUTRAL_BAND is $50M."""
        assert ETF_NEUTRAL_BAND == 50_000_000


# ===========================================================================
# Issue 2 — ETH proxy transparency tests
# ===========================================================================


class TestEthProxyTransparency:
    """Verify BTC-specific signals are tagged and penalized for ETH."""

    def test_maybe_proxy_tags_btc_signal_for_eth(self):
        """Fear&Greed source gets '(BTC proxy)' suffix for ETH."""
        src = ConsensusSource("Fear&Greed", "BEARISH", 0.8, weight=1.0)
        proxied = _maybe_proxy(src, "ETH")
        assert proxied.name == "Fear&Greed (BTC proxy)"
        assert proxied.confidence == pytest.approx(0.7, abs=0.001)

    def test_maybe_proxy_no_change_for_btc(self):
        """BTC asset -> source returned unchanged."""
        src = ConsensusSource("Fear&Greed", "BEARISH", 0.8, weight=1.0)
        result = _maybe_proxy(src, "BTC")
        assert result is src  # same object, no copy

    def test_maybe_proxy_all_btc_signals(self):
        """All 3 BTC-specific signals are proxied for ETH."""
        for name in ("Fear&Greed", "Funding_Rate", "Whale_Flows"):
            src = ConsensusSource(name, "BULLISH", 0.5, weight=2.0)
            proxied = _maybe_proxy(src, "ETH")
            assert "(BTC proxy)" in proxied.name
            assert proxied.confidence == pytest.approx(0.4, abs=0.001)

    def test_maybe_proxy_confidence_floor_at_zero(self):
        """Confidence never goes negative after penalty."""
        src = ConsensusSource("Funding_Rate", "NEUTRAL", 0.05, weight=2.5)
        proxied = _maybe_proxy(src, "ETH")
        assert proxied.confidence == 0.0

    def test_proxy_penalty_constant(self):
        """ETH_PROXY_CONFIDENCE_PENALTY is 0.1."""
        assert ETH_PROXY_CONFIDENCE_PENALTY == 0.1


# ===========================================================================
# Issue 1 — market_overall composite tests
# ===========================================================================


class TestMarketOverallConsensus:
    """Verify market_overall is derived from BTC + ETH + F&G."""

    def test_market_overall_weighted_score(self):
        """Score = BTC*0.6 + ETH*0.3 + F&G*0.1 (F&G=80 -> normalized +0.6)."""
        btc = MarketConsensus(asset="BTC", score=0.5, label="BULLISH", source_count=3)
        eth = MarketConsensus(asset="ETH", score=0.3, label="BULLISH", source_count=2)
        fg_data = _make_fg(80)  # (80-50)/50 = +0.6

        result = _build_market_overall_consensus([btc, eth], fg_data)
        assert result is not None
        assert result.asset == "market_overall"
        expected = 0.5 * 0.6 + 0.3 * 0.3 + 0.6 * 0.1  # 0.30 + 0.09 + 0.06 = 0.45
        assert result.score == pytest.approx(expected, abs=0.001)

    def test_market_overall_no_fg(self):
        """Without F&G data, F&G component is 0."""
        btc = MarketConsensus(asset="BTC", score=0.8, label="STRONG_BULLISH", source_count=5)
        eth = MarketConsensus(asset="ETH", score=0.4, label="BULLISH", source_count=3)

        result = _build_market_overall_consensus([btc, eth], None)
        assert result is not None
        expected = 0.8 * 0.6 + 0.4 * 0.3 + 0.0 * 0.1  # 0.48 + 0.12 = 0.60
        assert result.score == pytest.approx(expected, abs=0.001)

    def test_market_overall_returns_none_when_no_assets(self):
        """No BTC or ETH results -> None."""
        result = _build_market_overall_consensus([], _make_fg(50))
        assert result is None

    def test_market_overall_source_count(self):
        """Source count aggregates BTC + ETH counts."""
        btc = MarketConsensus(asset="BTC", score=0.3, label="BULLISH", source_count=4)
        eth = MarketConsensus(asset="ETH", score=-0.1, label="NEUTRAL", source_count=2)

        result = _build_market_overall_consensus([btc, eth], None)
        assert result is not None
        assert result.source_count == 6  # 4 + 2

    def test_market_overall_sources_list(self):
        """Sources list contains BTC_Consensus, ETH_Consensus, and optionally F&G."""
        btc = MarketConsensus(asset="BTC", score=0.5, label="BULLISH", source_count=3)
        eth = MarketConsensus(asset="ETH", score=-0.3, label="BEARISH", source_count=2)

        result = _build_market_overall_consensus([btc, eth], _make_fg(20))
        assert result is not None
        names = [s.name for s in result.sources]
        assert "BTC_Consensus" in names
        assert "ETH_Consensus" in names
        assert "Fear&Greed_Overall" in names

    def test_market_overall_weights_constant(self):
        """MARKET_OVERALL_WEIGHTS sums to 1.0."""
        total = sum(MARKET_OVERALL_WEIGHTS.values())
        assert total == pytest.approx(1.0, abs=0.001)


# ===========================================================================
# Contrarian & divergence tests
# ===========================================================================


class TestContrarianDetection:
    def test_contrarian_detection(self):
        """Sources opposing BULLISH consensus are flagged."""
        sources = [
            ConsensusSource("A", "BULLISH", 0.9, weight=3.0),
            ConsensusSource("B", "BULLISH", 0.8, weight=2.0),
            ConsensusSource("C", "BEARISH", 0.7, weight=1.0),
        ]
        contrarians = _detect_contrarians(sources, "BULLISH")
        assert len(contrarians) == 1
        assert contrarians[0].name == "C"

    def test_contrarian_neutral_consensus(self):
        """NEUTRAL consensus produces no contrarians."""
        sources = [
            ConsensusSource("A", "BULLISH", 0.9, weight=1.0),
            ConsensusSource("B", "BEARISH", 0.8, weight=1.0),
        ]
        assert _detect_contrarians(sources, "NEUTRAL") == []

    def test_contrarian_bearish_consensus(self):
        """BULLISH source in a BEARISH consensus is contrarian."""
        sources = [
            ConsensusSource("A", "BEARISH", 0.9, weight=3.0),
            ConsensusSource("B", "BULLISH", 0.7, weight=1.0),
        ]
        contrarians = _detect_contrarians(sources, "BEARISH")
        assert len(contrarians) == 1
        assert contrarians[0].name == "B"


class TestDivergenceAlerts:
    def test_divergence_alert_smart_bullish_social_bearish(self):
        """Smart money BULLISH vs retail BEARISH triggers alert."""
        sources = [
            ConsensusSource("Funding_Rate", "BULLISH", 0.8, weight=2.5),
            ConsensusSource("Whale_Flows", "BULLISH", 0.6, weight=2.5),
            ConsensusSource("Fear&Greed", "BEARISH", 0.7, weight=1.0),
        ]
        alerts = _detect_divergence_alerts(sources)
        assert len(alerts) == 1
        assert "Smart money BULLISH" in alerts[0]
        assert "retail BEARISH" in alerts[0]

    def test_divergence_alert_smart_bearish_social_bullish(self):
        """Smart money BEARISH vs retail BULLISH triggers alert."""
        sources = [
            ConsensusSource("ETF_Flows", "BEARISH", 0.8, weight=2.5),
            ConsensusSource("Fear&Greed", "BULLISH", 0.7, weight=1.0),
        ]
        alerts = _detect_divergence_alerts(sources)
        assert len(alerts) == 1
        assert "Smart money BEARISH" in alerts[0]

    def test_no_divergence_when_aligned(self):
        """No alert when smart money and social agree."""
        sources = [
            ConsensusSource("Funding_Rate", "BULLISH", 0.8, weight=2.5),
            ConsensusSource("Fear&Greed", "BULLISH", 0.7, weight=1.0),
        ]
        assert _detect_divergence_alerts(sources) == []

    def test_no_divergence_without_social(self):
        """No alert when no social sentiment sources present."""
        sources = [
            ConsensusSource("Funding_Rate", "BULLISH", 0.8, weight=2.5),
            ConsensusSource("Whale_Flows", "BEARISH", 0.6, weight=2.5),
        ]
        assert _detect_divergence_alerts(sources) == []


# ===========================================================================
# Integration — build_consensus
# ===========================================================================


class TestBuildConsensus:
    @pytest.mark.asyncio
    async def test_build_consensus_full_data(self):
        """All 5 sources available -> valid consensus for BTC, ETH, market_overall."""
        results = await build_consensus(
            prediction_data=_make_polymarket("BTC", 0.72),
            market_data=_make_fg(30),
            onchain_data=_make_funding_rate(0.0005),
            whale_data=_make_whale_summary(inflow=5e6, outflow=50e6),
            research_data=_make_etf_research(200_000_000),
        )
        assert len(results) == 3  # BTC, ETH, market_overall

        btc = results[0]
        assert btc.asset == "BTC"
        assert -1.0 <= btc.score <= 1.0
        assert btc.label in {
            "STRONG_BULLISH",
            "BULLISH",
            "NEUTRAL",
            "BEARISH",
            "STRONG_BEARISH",
        }
        # BTC has: Polymarket(BULLISH) + F&G(NEUTRAL/BEARISH) + FR(BULLISH) +
        # Whale(BULLISH) + ETF(BULLISH) = 5 sources
        assert btc.source_count == 5

        eth = results[1]
        assert eth.asset == "ETH"
        # ETH gets: F&G(proxy) + FR(proxy) + Whale(proxy) = 3 sources
        assert eth.source_count >= 3

        # market_overall is derived from BTC + ETH + F&G
        overall = results[2]
        assert overall.asset == "market_overall"
        assert -1.0 <= overall.score <= 1.0

    @pytest.mark.asyncio
    async def test_build_consensus_partial_data(self):
        """Only some sources available -> consensus from what's available."""
        results = await build_consensus(
            prediction_data=None,
            market_data=_make_fg(80),
            onchain_data=_make_funding_rate(0.0008),
        )
        assert len(results) == 3  # BTC, ETH, market_overall

        btc = results[0]
        # F&G(BULLISH) + FR(BULLISH) = 2 sources, both bullish
        assert btc.source_count == 2
        assert btc.score > 0
        assert btc.label in {"BULLISH", "STRONG_BULLISH"}

    @pytest.mark.asyncio
    async def test_build_consensus_minimum_viable(self):
        """Exactly 2 sources -> valid consensus (minimum viable)."""
        results = await build_consensus(
            market_data=_make_fg(20),
            onchain_data=_make_funding_rate(0.0005),
        )
        btc = results[0]
        assert btc.source_count == 2
        assert btc.label != "NEUTRAL" or btc.score != 0.0  # has real data

    @pytest.mark.asyncio
    async def test_build_consensus_insufficient(self):
        """<2 sources -> NEUTRAL with alert, but market_overall still built."""
        results = await build_consensus(
            market_data=_make_fg(30),
        )
        assert len(results) == 3  # BTC, ETH (both insufficient), market_overall
        btc = results[0]
        assert btc.score == 0.0
        assert btc.label == "NEUTRAL"
        assert "Insufficient data for consensus" in btc.divergence_alerts

    @pytest.mark.asyncio
    async def test_build_consensus_no_data(self):
        """All None -> BTC/ETH NEUTRAL with alerts, market_overall derived."""
        results = await build_consensus()
        assert len(results) == 3  # BTC, ETH, market_overall
        for r in results[:2]:  # BTC and ETH
            assert r.score == 0.0
            assert r.label == "NEUTRAL"
            assert "Insufficient data for consensus" in r.divergence_alerts
        # market_overall still produced (derived from 0.0 + 0.0 + no F&G)
        assert results[2].asset == "market_overall"
        assert results[2].score == 0.0

    @pytest.mark.asyncio
    async def test_build_consensus_etf_only_for_btc(self):
        """ETF flows contribute to BTC only, not ETH."""
        results = await build_consensus(
            market_data=_make_fg(80),
            onchain_data=_make_funding_rate(0.0005),
            research_data=_make_etf_research(500_000_000),
        )
        btc = results[0]
        eth = results[1]
        # BTC: F&G + FR + ETF = 3 sources
        assert btc.source_count == 3
        # ETH: F&G(proxy) + FR(proxy) = 2 sources (no ETF)
        assert eth.source_count == 2
        # market_overall is 3rd result
        assert results[2].asset == "market_overall"

    @pytest.mark.asyncio
    async def test_contrarian_in_build(self):
        """Contrarian sources appear in consensus result."""
        results = await build_consensus(
            prediction_data=_make_polymarket("BTC", 0.75),  # BULLISH
            market_data=_make_fg(10),  # BEARISH (extreme fear)
            onchain_data=_make_funding_rate(0.001),  # BULLISH
        )
        btc = results[0]
        # Consensus should be BULLISH (Polymarket w=3.0 + FR w=2.5 dominate)
        assert btc.label in {"BULLISH", "STRONG_BULLISH"}
        # F&G should be contrarian (BEARISH in a BULLISH consensus)
        contrarian_names = [c.name for c in btc.contrarians]
        assert "Fear&Greed" in contrarian_names

    @pytest.mark.asyncio
    async def test_divergence_in_build(self):
        """Divergence alerts appear when smart money disagrees with retail."""
        results = await build_consensus(
            market_data=_make_fg(10),  # BEARISH retail
            onchain_data=_make_funding_rate(0.001),  # BULLISH smart money
            whale_data=_make_whale_summary(inflow=5e6, outflow=80e6),  # BULLISH
        )
        btc = results[0]
        # Expect divergence: smart money BULLISH, retail BEARISH
        assert any("Smart money BULLISH" in a for a in btc.divergence_alerts)

    @pytest.mark.asyncio
    async def test_eth_proxy_tagging_in_build(self):
        """ETH sources have '(BTC proxy)' suffix and reduced confidence."""
        results = await build_consensus(
            market_data=_make_fg(10),  # BEARISH, confidence=0.8
            onchain_data=_make_funding_rate(0.001),  # BULLISH
            whale_data=_make_whale_summary(inflow=5e6, outflow=80e6),
        )
        eth = results[1]
        assert eth.asset == "ETH"
        # All 3 ETH sources should be proxied
        for src in eth.sources:
            assert "(BTC proxy)" in src.name

        # BTC sources should NOT have proxy tag
        btc = results[0]
        for src in btc.sources:
            assert "(BTC proxy)" not in src.name

    @pytest.mark.asyncio
    async def test_market_overall_in_build(self):
        """market_overall appears as 3rd result in full build."""
        results = await build_consensus(
            market_data=_make_fg(80),
            onchain_data=_make_funding_rate(0.0005),
        )
        overall = [r for r in results if r.asset == "market_overall"]
        assert len(overall) == 1
        assert overall[0].score != 0.0  # non-trivial since F&G=80


# ===========================================================================
# Format for LLM tests
# ===========================================================================


class TestFormatConsensusForLlm:
    def test_format_consensus_for_llm(self):
        """Formatted text contains key information."""
        consensuses = [
            MarketConsensus(
                asset="BTC",
                score=0.45,
                label="BULLISH",
                source_count=4,
                bullish_pct=75.0,
                sources=[
                    ConsensusSource("Polymarket", "BULLISH", 0.8, weight=3.0, thesis="72% YES"),
                    ConsensusSource("Fear&Greed", "BEARISH", 0.6, weight=1.0, thesis="F&G=25"),
                ],
                contrarians=[
                    ConsensusSource("Fear&Greed", "BEARISH", 0.6, weight=1.0),
                ],
                divergence_alerts=["Smart money BULLISH nhưng retail BEARISH"],
            ),
        ]
        text = format_consensus_for_llm(consensuses)
        assert "EXPERT CONSENSUS" in text
        assert "BTC" in text
        assert "BULLISH" in text
        assert "+0.45" in text
        assert "4 sources" in text
        assert "75% bullish" in text
        assert "Polymarket" in text
        assert "72% YES" in text
        assert "Contrarian" in text
        assert "Smart money BULLISH" in text

    def test_format_empty_consensus(self):
        """Empty list -> empty string."""
        assert format_consensus_for_llm([]) == ""

    def test_format_multiple_assets(self):
        """BTC, ETH, and market_overall all appear in output."""
        consensuses = [
            MarketConsensus(asset="BTC", score=0.3, label="BULLISH", source_count=3),
            MarketConsensus(asset="ETH", score=-0.1, label="NEUTRAL", source_count=2),
            MarketConsensus(asset="market_overall", score=0.15, label="NEUTRAL", source_count=5),
        ]
        text = format_consensus_for_llm(consensuses)
        assert "BTC" in text
        assert "ETH" in text
        assert "market_overall" in text
        assert "BULLISH" in text
        assert "NEUTRAL" in text
