"""Expert Consensus Engine v1 (P1.6) — Aggregate multi-source sentiment.

Collects signals from available data sources and produces a single consensus
score per asset (BTC, ETH, market_overall). The score ranges from -1.0
(STRONG_BEARISH) to +1.0 (STRONG_BULLISH).

Phase 1 sources (available now):
  - Polymarket prediction markets  (weight 3.0 — "skin in the game")
  - Fear & Greed Index              (weight 1.0 — social_sentiment proxy)
  - Funding Rate                    (weight 2.5 — smart_money: leveraged traders)
  - Whale exchange flows            (weight 2.5 — smart_money: whale behavior)
  - ETF flows                       (weight 2.5 — smart_money: institutional)

Phase 2 will add: TG experts, TradingView, Augmento, YouTube.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from cic_daily_report.collectors.market_data import MarketDataPoint
from cic_daily_report.collectors.onchain_data import OnChainMetric
from cic_daily_report.collectors.prediction_markets import PredictionMarketsData
from cic_daily_report.collectors.research_data import ResearchData
from cic_daily_report.collectors.whale_alert import WhaleAlertSummary
from cic_daily_report.core.logger import get_logger

logger = get_logger("consensus_engine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# WHY these weights: prediction markets have "skin in the game" (real money),
# smart_money signals (funding, whales, ETFs) reflect institutional conviction,
# social sentiment (F&G) is a lagging retail indicator so gets lowest weight.
WEIGHTS = {
    "prediction_markets": 3.0,
    "smart_money": 2.5,
    "expert_channels": 2.0,  # Phase 2
    "research_reports": 2.0,  # Phase 3
    "tradingview": 1.5,  # Phase 2
    "social_sentiment": 1.0,
}

# WHY 2: with fewer than 2 independent sources we cannot establish
# meaningful consensus — a single source is just a data point, not consensus.
MIN_SOURCES_FOR_CONSENSUS = 2

# WHY $50M: daily ETF flows below this are noise — individual fund
# rebalancing, creation/redemption basket rounding, etc.  Only flows
# exceeding $50M signal genuine institutional sentiment.
ETF_NEUTRAL_BAND = 50_000_000

# WHY 0.1 penalty: BTC-specific signals (F&G, funding rate, whale flows)
# used as ETH proxies are less reliable for ETH.  A small confidence
# reduction makes this transparent to the LLM scoring.
ETH_PROXY_CONFIDENCE_PENALTY = 0.1

# Signals that are BTC-specific but get inherited by ETH as proxies.
_BTC_SPECIFIC_SIGNALS = {"Fear&Greed", "Funding_Rate", "Whale_Flows"}

# market_overall composite weights (from spec Section 2.2)
MARKET_OVERALL_WEIGHTS = {
    "btc": 0.6,
    "eth": 0.3,
    "fear_greed": 0.1,
}

# Label thresholds (from spec Section 2.2)
_LABEL_THRESHOLDS = [
    (0.6, "STRONG_BULLISH"),
    (0.2, "BULLISH"),
    (-0.2, "NEUTRAL"),
    (-0.6, "BEARISH"),
]
_STRONG_BEARISH_LABEL = "STRONG_BEARISH"

# Category labels used for divergence detection
_SMART_MONEY_SOURCES = {"Funding_Rate", "Whale_Flows", "ETF_Flows"}
_SOCIAL_SENTIMENT_SOURCES = {"Fear&Greed", "CryptoPanic"}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ConsensusSource:
    """A single data source contributing to consensus."""

    name: str  # e.g., "Polymarket", "Fear&Greed", "Funding_Rate"
    sentiment: str  # "BULLISH" / "NEUTRAL" / "BEARISH"
    confidence: float  # 0.0-1.0
    key_levels: dict = field(default_factory=dict)
    thesis: str = ""
    timestamp: str = ""
    weight: float = 1.0


@dataclass
class MarketConsensus:
    """Aggregated consensus for one asset."""

    asset: str  # "BTC", "ETH"
    score: float  # -1.0 to +1.0
    label: str  # STRONG_BULLISH / BULLISH / NEUTRAL / BEARISH / STRONG_BEARISH
    source_count: int = 0
    bullish_pct: float = 0.0
    sources: list[ConsensusSource] = field(default_factory=list)
    key_levels: dict = field(default_factory=dict)
    contrarians: list[ConsensusSource] = field(default_factory=list)
    divergence_alerts: list[str] = field(default_factory=list)
    polymarket: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Score / label helpers
# ---------------------------------------------------------------------------


def _sentiment_to_numeric(sentiment: str) -> float:
    """Convert sentiment string to numeric value for scoring."""
    mapping = {"BULLISH": 1.0, "NEUTRAL": 0.0, "BEARISH": -1.0}
    return mapping.get(sentiment, 0.0)


def _score_to_label(score: float) -> str:
    """Map a -1..+1 score to a human-readable label.

    Boundaries (from spec Section 2.2):
      score >= 0.6  -> STRONG_BULLISH
      score >= 0.2  -> BULLISH
      score > -0.2  -> NEUTRAL    (strict >)
      score > -0.6  -> BEARISH    (strict >)
      score <= -0.6 -> STRONG_BEARISH

    WHY asymmetric: spec uses >= for bullish side and > for bearish side,
    meaning exact boundary values (-0.2, -0.6) fall into the more bearish bin.
    """
    if score >= 0.6:
        return "STRONG_BULLISH"
    if score >= 0.2:
        return "BULLISH"
    if score > -0.2:
        return "NEUTRAL"
    if score > -0.6:
        return "BEARISH"
    return _STRONG_BEARISH_LABEL


def _calculate_weighted_score(sources: list[ConsensusSource]) -> float:
    """Weighted average: sum(sentiment * weight * confidence) / sum(weight * confidence).

    Returns 0.0 when denominator is zero (no valid sources).
    Clamped to [-1.0, +1.0].
    """
    numerator = 0.0
    denominator = 0.0
    for src in sources:
        w = src.weight * src.confidence
        numerator += _sentiment_to_numeric(src.sentiment) * w
        denominator += w

    if denominator == 0.0:
        return 0.0

    raw = numerator / denominator
    # WHY clamp: floating-point edge cases could produce values outside range
    return max(-1.0, min(1.0, raw))


# ---------------------------------------------------------------------------
# Source extraction functions (pure — no side effects, no API calls)
# ---------------------------------------------------------------------------


def _extract_from_polymarket(data: PredictionMarketsData, asset: str) -> list[ConsensusSource]:
    """Extract consensus sources from Polymarket probabilities.

    Logic: If average YES probability for asset > 0.6 -> BULLISH
           If < 0.4 -> BEARISH
           Else -> NEUTRAL
    Confidence = abs(avg_probability - 0.5) * 2  (how far from 50/50)
    """
    if not data or not data.markets:
        return []

    asset_markets = [m for m in data.markets if m.asset == asset]
    if not asset_markets:
        return []

    avg_yes = sum(m.outcome_yes for m in asset_markets) / len(asset_markets)

    if avg_yes > 0.6:
        sentiment = "BULLISH"
    elif avg_yes < 0.4:
        sentiment = "BEARISH"
    else:
        sentiment = "NEUTRAL"

    # WHY this confidence formula: at 0.5 (coin-flip) confidence=0,
    # at 0.0 or 1.0 (certainty) confidence=1.0
    confidence = min(abs(avg_yes - 0.5) * 2, 1.0)

    # Collect key market questions for polymarket dict
    key_markets = {}
    for m in asset_markets[:5]:
        # Shorten question to a usable key
        short_q = m.question[:60] if len(m.question) > 60 else m.question
        key_markets[short_q] = round(m.outcome_yes, 3)

    timestamp = data.fetch_timestamp or datetime.now(timezone.utc).isoformat()

    return [
        ConsensusSource(
            name="Polymarket",
            sentiment=sentiment,
            confidence=round(confidence, 3),
            key_levels={},
            thesis=f"Avg YES {avg_yes:.0%} across {len(asset_markets)} markets",
            timestamp=timestamp,
            weight=WEIGHTS["prediction_markets"],
        )
    ]


def _extract_from_fear_greed(
    market_data: list[MarketDataPoint],
) -> ConsensusSource | None:
    """Extract consensus from Fear & Greed Index.

    F&G <= 25 -> BEARISH (extreme fear)
    F&G >= 75 -> BULLISH (extreme greed)
    Else -> NEUTRAL
    Confidence scales with distance from neutral (50).
    """
    if not market_data:
        return None

    fg_point = None
    for dp in market_data:
        if dp.symbol == "Fear&Greed":
            fg_point = dp
            break

    if fg_point is None:
        return None

    value = fg_point.price  # F&G is stored as price (0-100)

    if value <= 25:
        sentiment = "BEARISH"
    elif value >= 75:
        sentiment = "BULLISH"
    else:
        sentiment = "NEUTRAL"

    # WHY: confidence is how far the reading is from 50 (neutral),
    # normalized to 0..1. At F&G=0 or 100, confidence=1.0.
    confidence = min(abs(value - 50) / 50, 1.0)

    return ConsensusSource(
        name="Fear&Greed",
        sentiment=sentiment,
        confidence=round(confidence, 3),
        key_levels={},
        thesis=f"F&G Index = {value:.0f}",
        timestamp="",
        weight=WEIGHTS["social_sentiment"],
    )


def _extract_from_funding_rate(
    onchain_data: list[OnChainMetric] | None,
) -> ConsensusSource | None:
    """Extract consensus from BTC funding rate.

    FR > 0.01% -> BULLISH (longs paying premium)
    FR < -0.01% -> BEARISH (shorts paying premium)
    Else -> NEUTRAL
    Confidence = min(abs(FR) * 100, 1.0)

    WHY 0.01% threshold: this is the standard neutral band used by most
    derivatives exchanges (Binance, OKX, Bybit default = 0.01%).
    """
    if not onchain_data:
        return None

    fr_metric = None
    for m in onchain_data:
        if m.metric_name == "BTC_Funding_Rate":
            fr_metric = m
            break

    if fr_metric is None:
        return None

    fr = fr_metric.value  # already a decimal fraction (e.g., 0.0001 = 0.01%)

    if fr > 0.0001:
        sentiment = "BULLISH"
    elif fr < -0.0001:
        sentiment = "BEARISH"
    else:
        sentiment = "NEUTRAL"

    # WHY *100: funding rate is typically tiny (0.0001-0.001),
    # scaling by 100 maps reasonable ranges to 0..1 confidence
    confidence = min(abs(fr) * 100, 1.0)

    return ConsensusSource(
        name="Funding_Rate",
        sentiment=sentiment,
        confidence=round(confidence, 3),
        key_levels={},
        thesis=f"FR = {fr:.4%} ({fr_metric.source})",
        timestamp="",
        weight=WEIGHTS["smart_money"],
    )


def _extract_from_whale_flows(
    whale_data: WhaleAlertSummary | None,
) -> ConsensusSource | None:
    """Extract consensus from whale exchange flows.

    Net outflow (more leaving exchanges) -> BULLISH (accumulation)
    Net inflow (more entering exchanges) -> BEARISH (distribution)
    Confidence based on volume magnitude relative to $10M baseline.

    WHY net flow direction: historically, large BTC outflows from exchanges
    correlate with accumulation phases; inflows with distribution/selling.
    """
    if whale_data is None or not whale_data.transactions:
        return None

    # WHY btc_net_flow: BTC is the primary asset for whale flow analysis.
    # Positive net_flow = net inflow to exchanges = BEARISH (selling pressure).
    net_flow = whale_data.btc_net_flow

    # WHY $10M threshold: small flows are noise; $10M is a meaningful
    # signal given typical daily whale volumes of $100M-$1B.
    if net_flow < -10_000_000:
        sentiment = "BULLISH"  # net outflow = accumulation
    elif net_flow > 10_000_000:
        sentiment = "BEARISH"  # net inflow = distribution
    else:
        sentiment = "NEUTRAL"

    # Confidence: magnitude relative to $100M (large meaningful flow)
    confidence = min(abs(net_flow) / 100_000_000, 1.0)

    return ConsensusSource(
        name="Whale_Flows",
        sentiment=sentiment,
        confidence=round(confidence, 3),
        key_levels={},
        thesis=(f"BTC net {'inflow' if net_flow > 0 else 'outflow'} ${abs(net_flow) / 1e6:,.1f}M"),
        timestamp="",
        weight=WEIGHTS["smart_money"],
    )


def _extract_from_etf_flows(
    research_data: ResearchData | None,
) -> ConsensusSource | None:
    """Extract consensus from ETF flows.

    Positive net flow -> BULLISH (institutional buying)
    Negative net flow -> BEARISH (institutional selling)
    Confidence based on flow magnitude relative to recent average.

    WHY ETF flows matter: they represent regulated institutional demand.
    Large positive inflows signal sustained institutional conviction.
    """
    if research_data is None or research_data.etf_flows is None:
        return None

    etf = research_data.etf_flows
    if not etf.entries:
        return None

    total_flow = etf.total_flow_usd

    # WHY neutral band: small ETF flows ($1M-$49M) are noise from fund
    # rebalancing and basket mechanics. Only flows >= $50M indicate
    # genuine institutional sentiment.
    if abs(total_flow) < ETF_NEUTRAL_BAND:
        sentiment = "NEUTRAL"
        confidence = 0.3  # WHY 0.3: low but non-zero — data exists, just not decisive
    elif total_flow >= ETF_NEUTRAL_BAND:
        sentiment = "BULLISH"
        # WHY $500M baseline: typical large ETF flow day is ~$500M;
        # this normalizes confidence so a $500M+ day = very high confidence.
        confidence = min(abs(total_flow) / 500_000_000, 1.0)
    else:  # total_flow <= -ETF_NEUTRAL_BAND
        sentiment = "BEARISH"
        confidence = min(abs(total_flow) / 500_000_000, 1.0)

    # Build 5-day trend for thesis
    trend_str = ""
    if etf.recent_total_flows:
        signs = ["+" if f >= 0 else "-" for _, f in etf.recent_total_flows]
        trend_str = f" | 5d trend: {''.join(signs)}"

    return ConsensusSource(
        name="ETF_Flows",
        sentiment=sentiment,
        confidence=round(confidence, 3),
        key_levels={},
        thesis=f"ETF net flow ${total_flow:+,.0f}{trend_str}",
        timestamp=etf.date,
        weight=WEIGHTS["smart_money"],
    )


# ---------------------------------------------------------------------------
# Contrarian & divergence detection
# ---------------------------------------------------------------------------


def _detect_contrarians(
    sources: list[ConsensusSource], consensus_label: str
) -> list[ConsensusSource]:
    """Find sources whose sentiment disagrees with the consensus label.

    A source is contrarian if its sentiment direction opposes the consensus:
    - Consensus BULLISH/STRONG_BULLISH but source BEARISH
    - Consensus BEARISH/STRONG_BEARISH but source BULLISH
    NEUTRAL consensus or NEUTRAL sources are not considered contrarian.
    """
    contrarians: list[ConsensusSource] = []

    if consensus_label in ("STRONG_BULLISH", "BULLISH"):
        for src in sources:
            if src.sentiment == "BEARISH":
                contrarians.append(src)
    elif consensus_label in ("STRONG_BEARISH", "BEARISH"):
        for src in sources:
            if src.sentiment == "BULLISH":
                contrarians.append(src)

    return contrarians


def _detect_divergence_alerts(
    sources: list[ConsensusSource],
) -> list[str]:
    """Detect divergence when smart money disagrees with social sentiment.

    WHY: smart money (funding, whales, ETFs) acting contrary to retail
    sentiment (F&G, CryptoPanic) is a historically significant signal.
    """
    alerts: list[str] = []

    smart_money_sentiments: list[str] = []
    social_sentiments: list[str] = []

    for src in sources:
        if src.name in _SMART_MONEY_SOURCES:
            smart_money_sentiments.append(src.sentiment)
        elif src.name in _SOCIAL_SENTIMENT_SOURCES:
            social_sentiments.append(src.sentiment)

    if not smart_money_sentiments or not social_sentiments:
        return alerts

    # Check if dominant sentiment differs between groups
    smart_bullish = sum(1 for s in smart_money_sentiments if s == "BULLISH")
    smart_bearish = sum(1 for s in smart_money_sentiments if s == "BEARISH")
    social_bullish = sum(1 for s in social_sentiments if s == "BULLISH")
    social_bearish = sum(1 for s in social_sentiments if s == "BEARISH")

    if smart_bullish > smart_bearish and social_bearish > social_bullish:
        alerts.append("Smart money BULLISH nhưng retail BEARISH")
    elif smart_bearish > smart_bullish and social_bullish > social_bearish:
        alerts.append("Smart money BEARISH nhưng retail BULLISH")

    return alerts


# ---------------------------------------------------------------------------
# ETH proxy helper
# ---------------------------------------------------------------------------


def _maybe_proxy(source: ConsensusSource, asset: str) -> ConsensusSource:
    """Return a proxy-tagged copy of *source* when it is BTC-specific data
    being applied to a non-BTC asset (i.e., ETH).

    WHY: F&G, funding rate, and whale flows are measured for BTC but
    inherited by ETH.  Tagging them "(BTC proxy)" and reducing confidence
    by ETH_PROXY_CONFIDENCE_PENALTY makes this transparent to the LLM.
    """
    if asset == "BTC" or source.name not in _BTC_SPECIFIC_SIGNALS:
        return source

    return ConsensusSource(
        name=f"{source.name} (BTC proxy)",
        sentiment=source.sentiment,
        confidence=round(max(source.confidence - ETH_PROXY_CONFIDENCE_PENALTY, 0.0), 3),
        key_levels=source.key_levels,
        thesis=source.thesis,
        timestamp=source.timestamp,
        weight=source.weight,
    )


# ---------------------------------------------------------------------------
# market_overall composite
# ---------------------------------------------------------------------------


def _build_market_overall_consensus(
    asset_results: list[MarketConsensus],
    market_data: list[MarketDataPoint] | None,
) -> MarketConsensus | None:
    """Derive a market_overall consensus from BTC + ETH + Fear&Greed.

    Weighted average:
      BTC score * 0.6 + ETH score * 0.3 + F&G normalized score * 0.1

    WHY derived (not built from raw sources): market_overall is a composite
    view — BTC dominates crypto market cap (~55-60%), ETH is second (~15-18%),
    and Fear&Greed captures broad retail sentiment.  Building it from the
    already-computed BTC/ETH consensus avoids double-counting raw sources.

    Returns None if both BTC and ETH results are missing.
    """
    btc_result: MarketConsensus | None = None
    eth_result: MarketConsensus | None = None
    for r in asset_results:
        if r.asset == "BTC":
            btc_result = r
        elif r.asset == "ETH":
            eth_result = r

    if btc_result is None and eth_result is None:
        return None

    btc_score = btc_result.score if btc_result else 0.0
    eth_score = eth_result.score if eth_result else 0.0

    # Fear & Greed component (normalize 0-100 to -1..+1)
    fg_score = 0.0
    if market_data:
        for dp in market_data:
            if dp.symbol == "Fear&Greed":
                # WHY (value - 50) / 50: maps F&G 0→-1.0, 50→0.0, 100→+1.0
                fg_score = (dp.price - 50) / 50
                break

    w = MARKET_OVERALL_WEIGHTS
    raw_score = btc_score * w["btc"] + eth_score * w["eth"] + fg_score * w["fear_greed"]
    score = round(max(-1.0, min(1.0, raw_score)), 4)
    label = _score_to_label(score)

    # Aggregate source count from constituents
    source_count = 0
    if btc_result:
        source_count += btc_result.source_count
    if eth_result:
        source_count += eth_result.source_count

    # Build descriptive sources list for LLM transparency
    sources: list[ConsensusSource] = []
    if btc_result:
        sources.append(
            ConsensusSource(
                name="BTC_Consensus",
                sentiment=btc_result.label,
                confidence=min(abs(btc_result.score), 1.0),
                thesis=f"BTC {btc_result.label} ({btc_result.score:+.2f})",
                weight=w["btc"],
            )
        )
    if eth_result:
        sources.append(
            ConsensusSource(
                name="ETH_Consensus",
                sentiment=eth_result.label,
                confidence=min(abs(eth_result.score), 1.0),
                thesis=f"ETH {eth_result.label} ({eth_result.score:+.2f})",
                weight=w["eth"],
            )
        )
    if fg_score != 0.0:
        fg_sentiment = "BULLISH" if fg_score > 0 else "BEARISH" if fg_score < 0 else "NEUTRAL"
        sources.append(
            ConsensusSource(
                name="Fear&Greed_Overall",
                sentiment=fg_sentiment,
                confidence=round(min(abs(fg_score), 1.0), 3),
                thesis=f"F&G normalized = {fg_score:+.2f}",
                weight=w["fear_greed"],
            )
        )

    bullish_count = sum(1 for s in sources if s.sentiment in ("BULLISH", "STRONG_BULLISH"))
    bullish_pct = round(bullish_count / len(sources) * 100, 1) if sources else 0.0

    return MarketConsensus(
        asset="market_overall",
        score=score,
        label=label,
        source_count=source_count,
        bullish_pct=bullish_pct,
        sources=sources,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def build_consensus(
    prediction_data: PredictionMarketsData | None = None,
    market_data: list[MarketDataPoint] | None = None,
    onchain_data: list[OnChainMetric] | None = None,
    whale_data: WhaleAlertSummary | None = None,
    research_data: ResearchData | None = None,
) -> list[MarketConsensus]:
    """Build consensus from available data sources.

    Phase 1 sources (available now):
    1. Polymarket (prediction_markets) -> weight 3.0
    2. Fear & Greed Index (market_data) -> weight 1.0 (social_sentiment proxy)
    3. Funding Rate (onchain_data) -> weight 2.5 (smart_money: leveraged)
    4. Whale flows (whale_data) -> weight 2.5 (smart_money: whale behavior)
    5. ETF flows (research_data) -> weight 2.5 (smart_money: institutional)

    Phase 2 will add: TG experts, TradingView, Augmento, YouTube.

    Returns: list of MarketConsensus (one per asset: BTC, ETH).
    """
    results: list[MarketConsensus] = []

    for asset in ("BTC", "ETH"):
        sources: list[ConsensusSource] = []

        # 1. Polymarket — weight 3.0
        poly_sources = _extract_from_polymarket(prediction_data, asset)
        sources.extend(poly_sources)

        # 2. Fear & Greed — weight 1.0 (applies to overall crypto market)
        fg_source = _extract_from_fear_greed(market_data)
        if fg_source is not None:
            sources.append(_maybe_proxy(fg_source, asset) if asset == "ETH" else fg_source)

        # 3. Funding Rate — weight 2.5 (BTC only; ETH inherits BTC signal)
        fr_source = _extract_from_funding_rate(onchain_data)
        if fr_source is not None:
            sources.append(_maybe_proxy(fr_source, asset) if asset == "ETH" else fr_source)

        # 4. Whale flows — weight 2.5 (BTC only; ETH inherits signal)
        whale_source = _extract_from_whale_flows(whale_data)
        if whale_source is not None:
            sources.append(_maybe_proxy(whale_source, asset) if asset == "ETH" else whale_source)

        # 5. ETF flows — weight 2.5 (BTC ETFs; signal applies to BTC)
        # WHY only BTC: Spot ETH ETFs exist but etf_flows data is BTC-only
        if asset == "BTC":
            etf_source = _extract_from_etf_flows(research_data)
            if etf_source is not None:
                sources.append(etf_source)

        # Check minimum viable consensus
        if len(sources) < MIN_SOURCES_FOR_CONSENSUS:
            results.append(
                MarketConsensus(
                    asset=asset,
                    score=0.0,
                    label="NEUTRAL",
                    source_count=len(sources),
                    bullish_pct=0.0,
                    sources=sources,
                    divergence_alerts=["Insufficient data for consensus"],
                )
            )
            continue

        # Calculate weighted score
        score = _calculate_weighted_score(sources)
        label = _score_to_label(score)

        # Statistics
        bullish_count = sum(1 for s in sources if s.sentiment == "BULLISH")
        bullish_pct = round(bullish_count / len(sources) * 100, 1)

        # Collect key levels from all sources
        all_support: list[float] = []
        all_resistance: list[float] = []
        for src in sources:
            if "support" in src.key_levels:
                all_support.append(src.key_levels["support"])
            if "resistance" in src.key_levels:
                all_resistance.append(src.key_levels["resistance"])
        key_levels = {}
        if all_support:
            key_levels["support"] = sorted(all_support)
        if all_resistance:
            key_levels["resistance"] = sorted(all_resistance)

        # Contrarian and divergence detection
        contrarians = _detect_contrarians(sources, label)
        divergence_alerts = _detect_divergence_alerts(sources)

        # Polymarket summary
        polymarket_dict: dict = {}
        for src in poly_sources:
            # thesis contains the avg probability info
            polymarket_dict["thesis"] = src.thesis

        results.append(
            MarketConsensus(
                asset=asset,
                score=round(score, 4),
                label=label,
                source_count=len(sources),
                bullish_pct=bullish_pct,
                sources=sources,
                key_levels=key_levels,
                contrarians=contrarians,
                divergence_alerts=divergence_alerts,
                polymarket=polymarket_dict,
            )
        )

    # Build market_overall as a composite of BTC + ETH + Fear&Greed
    market_overall = _build_market_overall_consensus(results, market_data)
    if market_overall is not None:
        results.append(market_overall)

    source_summary = ", ".join(f"{c.asset}={c.label}({c.score:+.2f})" for c in results)
    logger.info(f"Consensus built: {source_summary}")
    return results


# ---------------------------------------------------------------------------
# LLM format
# ---------------------------------------------------------------------------


def format_consensus_for_llm(consensuses: list[MarketConsensus]) -> str:
    """Format consensus data for LLM context injection.

    Example output:
    === EXPERT CONSENSUS ===
    BTC: BULLISH (+0.45) — 5 sources, 60% bullish
      Polymarket: YES 72% cho BTC>100K (weight: 3.0)
      F&G: 35 — Fear (weight: 1.0)
      Funding Rate: +0.012% — Longs dominate (weight: 2.5)
      ⚠ Divergence: Smart money BULLISH but retail BEARISH
    """
    if not consensuses:
        return ""

    lines: list[str] = ["=== EXPERT CONSENSUS ==="]

    for c in consensuses:
        header = (
            f"{c.asset}: {c.label} ({c.score:+.2f})"
            f" — {c.source_count} sources, {c.bullish_pct:.0f}% bullish"
        )
        lines.append(header)

        for src in c.sources:
            lines.append(
                f"  {src.name}: {src.sentiment} "
                f"(conf: {src.confidence:.0%}, weight: {src.weight})"
                + (f" — {src.thesis}" if src.thesis else "")
            )

        if c.contrarians:
            names = ", ".join(s.name for s in c.contrarians)
            lines.append(f"  Contrarian: {names}")

        for alert in c.divergence_alerts:
            lines.append(f"  ⚠ {alert}")

        lines.append("")  # blank line between assets

    return "\n".join(lines).rstrip()
