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

# P1.9: Macro market triggers (Section 2.3).
# WHY these thresholds: Each represents a historically significant move
# that correlates with crypto market volatility (risk-off cascades).
OIL_SPIKE_THRESHOLD = 8.0  # Oil >= +8% — supply shock / geopolitical risk
GOLD_SPIKE_THRESHOLD = 3.0  # Gold >= +3% — flight to safety
VIX_SPIKE_THRESHOLD = 30  # VIX >= 30 absolute — elevated fear (not % change)
DXY_SPIKE_THRESHOLD = 2.0  # DXY >= +2% — dollar strength pressures risk assets
SPX_DROP_THRESHOLD = -3.0  # S&P 500 <= -3% — broad risk-off selloff


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
                    f"BTC giảm {btc.change_24h:.1f}% trong 24h — giá hiện tại ${btc.price:,.0f}"
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
        logger.warning(f"BTC crash trigger: {btc.change_24h:.1f}% (threshold: {btc_threshold}%)")

    if eth and eth.change_24h <= eth_threshold:
        events.append(
            BreakingEvent(
                title=(
                    f"ETH giảm {eth.change_24h:.1f}% trong 24h — giá hiện tại ${eth.price:,.0f}"
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
        logger.warning(f"ETH crash trigger: {eth.change_24h:.1f}% (threshold: {eth_threshold}%)")

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
            f"Extreme fear trigger: F&G={fgi.price:.0f} (threshold: {fear_greed_threshold})"
        )

    # P1.9: Macro market triggers — Oil, Gold, VIX, DXY, SPX.
    # WHY separate from BTC/ETH: These are traditional-finance indicators that
    # signal macro risk-off cascades affecting crypto indirectly.
    # Graceful degrade: if data point not collected, _find_data_point returns None.
    _detect_macro_triggers(market_data, events)

    if events:
        logger.info(f"Market triggers: {len(events)} events detected")
    else:
        logger.debug("Market triggers: no extreme conditions detected")

    return events


def _detect_macro_triggers(
    market_data: list[MarketDataPoint],
    events: list[BreakingEvent],
) -> None:
    """P1.9: Check Oil, Gold, VIX, DXY, SPX for breaking-level moves.

    Appends to the given events list in-place.
    """
    oil = _find_data_point(market_data, "Oil")
    if oil and oil.change_24h >= OIL_SPIKE_THRESHOLD:
        events.append(
            BreakingEvent(
                title=f"Dầu thô tăng {oil.change_24h:.1f}% — giá ${oil.price:,.0f}/thùng",
                source="market_data",
                url="",
                panic_score=_spike_to_score(oil.change_24h, OIL_SPIKE_THRESHOLD),
                matched_keywords=["oil crisis"],
                raw_data={
                    "source_type": "market_trigger",
                    "symbol": "Oil",
                    "price": oil.price,
                    "change_24h": oil.change_24h,
                },
            )
        )
        logger.warning(f"Oil spike trigger: +{oil.change_24h:.1f}%")

    gold = _find_data_point(market_data, "Gold")
    if gold and gold.change_24h >= GOLD_SPIKE_THRESHOLD:
        events.append(
            BreakingEvent(
                title=f"Vàng tăng {gold.change_24h:.1f}% — giá ${gold.price:,.0f}/oz",
                source="market_data",
                url="",
                panic_score=_spike_to_score(gold.change_24h, GOLD_SPIKE_THRESHOLD),
                matched_keywords=["gold spike"],
                raw_data={
                    "source_type": "market_trigger",
                    "symbol": "Gold",
                    "price": gold.price,
                    "change_24h": gold.change_24h,
                },
            )
        )
        logger.warning(f"Gold spike trigger: +{gold.change_24h:.1f}%")

    # WHY absolute price, not change_24h: VIX is a volatility index —
    # a value >= 30 is "elevated fear" regardless of daily change direction.
    vix = _find_data_point(market_data, "VIX")
    if vix and vix.price >= VIX_SPIKE_THRESHOLD:
        events.append(
            BreakingEvent(
                title=(f"VIX vọt lên {vix.price:.0f} — thị trường lo ngại biến động lớn"),
                source="market_data",
                url="",
                panic_score=min(100, int(70 + (vix.price - 30))),
                matched_keywords=["VIX spike"],
                raw_data={
                    "source_type": "market_trigger",
                    "symbol": "VIX",
                    "price": vix.price,
                    "change_24h": vix.change_24h,
                },
            )
        )
        logger.warning(f"VIX spike trigger: {vix.price:.0f}")

    dxy = _find_data_point(market_data, "DXY")
    if dxy and dxy.change_24h >= DXY_SPIKE_THRESHOLD:
        events.append(
            BreakingEvent(
                title=(f"Dollar Index tăng {dxy.change_24h:.1f}% — áp lực lên tài sản rủi ro"),
                source="market_data",
                url="",
                panic_score=_spike_to_score(dxy.change_24h, DXY_SPIKE_THRESHOLD),
                matched_keywords=["DXY spike"],
                raw_data={
                    "source_type": "market_trigger",
                    "symbol": "DXY",
                    "price": dxy.price,
                    "change_24h": dxy.change_24h,
                },
            )
        )
        logger.warning(f"DXY spike trigger: +{dxy.change_24h:.1f}%")

    spx = _find_data_point(market_data, "SPX")
    if spx and spx.change_24h <= SPX_DROP_THRESHOLD:
        events.append(
            BreakingEvent(
                title=(f"S&P 500 giảm {spx.change_24h:.1f}% — phiên bán tháo mạnh"),
                source="market_data",
                url="",
                panic_score=_drop_to_score(spx.change_24h),
                matched_keywords=["SPX drop"],
                raw_data={
                    "source_type": "market_trigger",
                    "symbol": "SPX",
                    "price": spx.price,
                    "change_24h": spx.change_24h,
                },
            )
        )
        logger.warning(f"SPX drop trigger: {spx.change_24h:.1f}%")


def _spike_to_score(change_pct: float, threshold: float) -> int:
    """Convert a positive % spike to a panic score (0-100).

    Maps threshold -> 70, 2x threshold -> 85, 3x threshold -> 100.
    WHY 70 base: consistent with _drop_to_score for BTC/ETH.
    """
    if change_pct <= 0 or threshold <= 0:
        return 0
    ratio = change_pct / threshold  # 1.0 at threshold, 2.0 at double
    score = int(70 + (ratio - 1) * 15)
    return max(0, min(100, score))


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
