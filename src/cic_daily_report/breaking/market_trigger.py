"""Market Data Breaking Triggers — price crash & extreme fear detection.

Always-on module (not a fallback). Creates BreakingEvent when market data
indicates extreme conditions: BTC/ETH crash or extreme Fear & Greed.
"""

from __future__ import annotations

from cic_daily_report.breaking.event_detector import BreakingEvent
from cic_daily_report.collectors.market_data import MarketDataPoint
from cic_daily_report.core.logger import get_logger

logger = get_logger("market_trigger")

BTC_DROP_THRESHOLD = -7.0
ETH_DROP_THRESHOLD = -10.0
FEAR_GREED_THRESHOLD = 10


def detect_market_triggers(
    market_data: list[MarketDataPoint],
    btc_threshold: float = BTC_DROP_THRESHOLD,
    eth_threshold: float = ETH_DROP_THRESHOLD,
    fear_greed_threshold: int = FEAR_GREED_THRESHOLD,
) -> list[BreakingEvent]:
    """Check market data for breaking-level conditions.

    Args:
        market_data: Collected market data points.
        btc_threshold: BTC 24h change threshold (negative = drop). Default -7%.
        eth_threshold: ETH 24h change threshold. Default -10%.
        fear_greed_threshold: Fear & Greed index threshold. Default 10.

    Returns:
        List of BreakingEvent for triggered conditions.
    """
    events: list[BreakingEvent] = []

    btc = _find_data_point(market_data, "BTC")
    eth = _find_data_point(market_data, "ETH")
    fgi = _find_data_point(market_data, "Fear&Greed")

    if btc and btc.change_24h <= btc_threshold:
        events.append(
            BreakingEvent(
                title=(
                    f"BTC giảm {btc.change_24h:.1f}% trong 24h"
                    f" — giá hiện tại ${btc.price:,.0f}"
                ),
                source="market_data",
                url="",
                panic_score=_drop_to_score(btc.change_24h),
                matched_keywords=["crash"],
                raw_data={
                    "source_type": "market_trigger",
                    "symbol": "BTC",
                    "price": btc.price,
                    "change_24h": btc.change_24h,
                },
            )
        )
        logger.warning(
            f"BTC crash trigger: {btc.change_24h:.1f}% "
            f"(threshold: {btc_threshold}%)"
        )

    if eth and eth.change_24h <= eth_threshold:
        events.append(
            BreakingEvent(
                title=(
                    f"ETH giảm {eth.change_24h:.1f}% trong 24h"
                    f" — giá hiện tại ${eth.price:,.0f}"
                ),
                source="market_data",
                url="",
                panic_score=_drop_to_score(eth.change_24h),
                matched_keywords=["crash"],
                raw_data={
                    "source_type": "market_trigger",
                    "symbol": "ETH",
                    "price": eth.price,
                    "change_24h": eth.change_24h,
                },
            )
        )
        logger.warning(
            f"ETH crash trigger: {eth.change_24h:.1f}% "
            f"(threshold: {eth_threshold}%)"
        )

    if fgi and fgi.price <= fear_greed_threshold:
        events.append(
            BreakingEvent(
                title=f"Fear & Greed Index xuống {fgi.price:.0f} — Extreme Fear",
                source="market_data",
                url="",
                panic_score=max(70, 100 - int(fgi.price)),
                matched_keywords=[],
                raw_data={
                    "source_type": "market_trigger",
                    "metric": "fear_greed",
                    "value": fgi.price,
                },
            )
        )
        logger.warning(
            f"Extreme fear trigger: F&G={fgi.price:.0f} "
            f"(threshold: {fear_greed_threshold})"
        )

    if events:
        logger.info(f"Market triggers: {len(events)} events detected")
    else:
        logger.debug("Market triggers: no extreme conditions detected")

    return events


def _find_data_point(
    data: list[MarketDataPoint],
    symbol: str,
) -> MarketDataPoint | None:
    """Find a data point by symbol (case-insensitive)."""
    symbol_lower = symbol.lower()
    for dp in data:
        if dp.symbol.lower() == symbol_lower:
            return dp
    return None


def _drop_to_score(change_pct: float) -> int:
    """Convert a negative % change to a panic score (0-100).

    -7% -> 70, -10% -> 80, -15% -> 90, -20%+ -> 100.
    """
    if change_pct >= 0:
        return 0
    score = int(70 + (abs(change_pct) - 7) * (30 / 13))
    return max(0, min(100, score))
