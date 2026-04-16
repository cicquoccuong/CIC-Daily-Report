"""Market Data Breaking Triggers — price crash & extreme fear detection.

Always-on module (not a fallback). Creates BreakingEvent when market data
indicates extreme conditions: BTC/ETH crash or extreme Fear & Greed.

QO.29/QO.33 (Wave 3): Thresholds read from CAU_HINH via config_loader at
runtime. Module-level constants kept as DEFAULT FALLBACK only.
"""

from __future__ import annotations

from cic_daily_report.breaking.event_detector import BreakingEvent
from cic_daily_report.collectors.market_data import MarketDataPoint
from cic_daily_report.core.logger import get_logger

logger = get_logger("market_trigger")

# QO.29: Constants kept as DEFAULT FALLBACK — actual values read from
# CAU_HINH at runtime via _get_thresholds(). DO NOT call config_loader
# at module level (sheets_client not ready yet).
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

# QO.33: Season multipliers — adjust thresholds based on market cycle.
# MUA_DONG (Winter/Bear): thresholds x 0.7 = more sensitive (smaller moves trigger)
# MUA_HE (Summer/Bull): thresholds x 1.3 = less sensitive (need bigger moves)
# WHY: In bear markets, smaller drops are more significant and should trigger alerts
# earlier. In bull markets, larger swings are normal and should not spam.
SEASON_MULTIPLIERS: dict[str, float] = {
    "MUA_DONG": 0.7,
    "MUA_XUAN": 1.0,  # neutral — use defaults as-is
    "MUA_HE": 1.3,
    "MUA_THU": 1.0,  # neutral — use defaults as-is
}


def _get_thresholds(config_loader: object | None = None) -> dict[str, float]:
    """Read all market trigger thresholds from CAU_HINH config.

    QO.29: Called inside functions at runtime, NOT at module load.
    WHY: config_loader needs sheets_client which is not ready at import time.
    Returns dict of threshold_name -> value, using defaults on failure.
    """
    defaults = {
        "BTC_DROP_THRESHOLD": BTC_DROP_THRESHOLD,
        "ETH_DROP_THRESHOLD": ETH_DROP_THRESHOLD,
        "FEAR_GREED_THRESHOLD": float(FEAR_GREED_THRESHOLD),
        "OIL_SPIKE_THRESHOLD": OIL_SPIKE_THRESHOLD,
        "GOLD_SPIKE_THRESHOLD": GOLD_SPIKE_THRESHOLD,
        "VIX_SPIKE_THRESHOLD": float(VIX_SPIKE_THRESHOLD),
        "DXY_SPIKE_THRESHOLD": DXY_SPIKE_THRESHOLD,
        "SPX_DROP_THRESHOLD": SPX_DROP_THRESHOLD,
    }
    if config_loader is None:
        return defaults

    try:
        result = {}
        for key, default in defaults.items():
            result[key] = config_loader.get_setting_float(key, default)
        return result
    except Exception as e:
        # WHY: Never break pipeline if config read fails — use defaults silently
        logger.warning(f"Config read failed for market thresholds, using defaults: {e}")
        return defaults


def _get_season_multiplier(config_loader: object | None = None) -> float:
    """QO.33: Get season-based threshold multiplier from Sentinel data.

    Tries to read season phase from SentinelReader. If unavailable,
    returns 1.0 (no adjustment).

    WHY: Season data comes from CIC-Sentinel spreadsheet — a separate
    system that may not always be accessible. Graceful fallback to 1.0.
    """
    if config_loader is None:
        return 1.0

    try:
        # WHY: Read season from SentinelReader (not config_loader).
        # Import here to avoid circular import and because sentinel_reader
        # is optional — pipeline works fine without it.
        from cic_daily_report.storage.sentinel_reader import SentinelReader

        reader = SentinelReader()
        season = reader.read_season()
        if season and season.phase:
            phase = season.phase.upper()
            multiplier = SEASON_MULTIPLIERS.get(phase, 1.0)
            logger.info(f"QO.33: Season={phase}, threshold multiplier={multiplier}")
            return multiplier
    except Exception as e:
        # WHY: Sentinel may be unreachable (no credentials, network error).
        # This is expected in dev/CI — silently fall back to 1.0.
        logger.debug(f"QO.33: Season data unavailable, using default multiplier: {e}")

    return 1.0


def _apply_season_multiplier(thresholds: dict[str, float], multiplier: float) -> dict[str, float]:
    """QO.33: Apply season multiplier to all market trigger thresholds.

    For negative thresholds (drops): multiply the absolute value, then re-negate.
    Example: BTC_DROP_THRESHOLD=-7.0, multiplier=0.7 → -4.9 (more sensitive).

    For positive thresholds (spikes/VIX): multiply directly.
    Example: OIL_SPIKE_THRESHOLD=8.0, multiplier=0.7 → 5.6 (more sensitive).
    """
    if multiplier == 1.0:
        return thresholds

    adjusted = {}
    for key, value in thresholds.items():
        if value < 0:
            # WHY: For drop thresholds (negative), smaller absolute value = more sensitive.
            # multiply abs → re-negate: -7.0 * 0.7 = -4.9 (triggers on smaller drops)
            adjusted[key] = -(abs(value) * multiplier)
        else:
            # WHY: For spike thresholds (positive), smaller value = more sensitive.
            # 8.0 * 0.7 = 5.6 (triggers on smaller spikes)
            adjusted[key] = value * multiplier
    return adjusted


def detect_market_triggers(
    market_data: list[MarketDataPoint],
    btc_threshold: float = BTC_DROP_THRESHOLD,
    eth_threshold: float = ETH_DROP_THRESHOLD,
    fear_greed_threshold: int = FEAR_GREED_THRESHOLD,
    config_loader: object | None = None,
) -> list[BreakingEvent]:
    """Check market data for breaking-level conditions.

    QO.29: Thresholds read from CAU_HINH config at runtime. Explicit
    threshold params override config values (backward compat for tests).
    QO.33: Season multiplier applied when config_loader is provided.

    Args:
        market_data: Collected market data points.
        btc_threshold: BTC 24h change threshold (negative = drop). Default -7%.
        eth_threshold: ETH 24h change threshold. Default -10%.
        fear_greed_threshold: Fear & Greed index threshold. Default 10.
        config_loader: Optional ConfigLoader for reading thresholds from CAU_HINH.

    Returns:
        List of BreakingEvent for triggered conditions.
    """
    events: list[BreakingEvent] = []

    # QO.29: Read thresholds from config if available, apply season multiplier (QO.33)
    if config_loader is not None:
        cfg_thresholds = _get_thresholds(config_loader)
        season_mult = _get_season_multiplier(config_loader)
        cfg_thresholds = _apply_season_multiplier(cfg_thresholds, season_mult)
        # WHY: Explicit params override config — backward compat for existing callers/tests
        # that pass custom thresholds directly. Only use config when defaults are passed.
        if btc_threshold == BTC_DROP_THRESHOLD:
            btc_threshold = cfg_thresholds["BTC_DROP_THRESHOLD"]
        if eth_threshold == ETH_DROP_THRESHOLD:
            eth_threshold = cfg_thresholds["ETH_DROP_THRESHOLD"]
        if fear_greed_threshold == FEAR_GREED_THRESHOLD:
            fear_greed_threshold = int(cfg_thresholds["FEAR_GREED_THRESHOLD"])

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
    # WHY pass cfg_thresholds: avoid double-reading config + re-computing season
    # multiplier inside _detect_macro_triggers (QO.31 review Fix 2).
    _detect_macro_triggers(
        market_data,
        events,
        cfg_thresholds=cfg_thresholds if config_loader is not None else None,
    )

    if events:
        logger.info(f"Market triggers: {len(events)} events detected")
    else:
        logger.debug("Market triggers: no extreme conditions detected")

    return events


def _detect_macro_triggers(
    market_data: list[MarketDataPoint],
    events: list[BreakingEvent],
    cfg_thresholds: dict[str, float] | None = None,
) -> None:
    """P1.9: Check Oil, Gold, VIX, DXY, SPX for breaking-level moves.

    QO.29/QO.31 Fix 2: Receives pre-computed thresholds from caller
    (already season-adjusted). Avoids double-reading config + re-creating
    SentinelReader on every call.
    Appends to the given events list in-place.
    """
    # WHY use caller's thresholds: detect_market_triggers already read config
    # and applied season multiplier — no need to repeat that work here.
    if cfg_thresholds is not None:
        oil_threshold = cfg_thresholds["OIL_SPIKE_THRESHOLD"]
        gold_threshold = cfg_thresholds["GOLD_SPIKE_THRESHOLD"]
        vix_threshold = cfg_thresholds["VIX_SPIKE_THRESHOLD"]
        dxy_threshold = cfg_thresholds["DXY_SPIKE_THRESHOLD"]
        spx_threshold = cfg_thresholds["SPX_DROP_THRESHOLD"]
    else:
        oil_threshold = OIL_SPIKE_THRESHOLD
        gold_threshold = GOLD_SPIKE_THRESHOLD
        vix_threshold = float(VIX_SPIKE_THRESHOLD)
        dxy_threshold = DXY_SPIKE_THRESHOLD
        spx_threshold = SPX_DROP_THRESHOLD

    oil = _find_data_point(market_data, "Oil")
    if oil and oil.change_24h >= oil_threshold:
        events.append(
            BreakingEvent(
                title=f"Dầu thô tăng {oil.change_24h:.1f}% — giá ${oil.price:,.0f}/thùng",
                source="market_data",
                url="",
                panic_score=_spike_to_score(oil.change_24h, oil_threshold),
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
    if gold and gold.change_24h >= gold_threshold:
        events.append(
            BreakingEvent(
                title=f"Vàng tăng {gold.change_24h:.1f}% — giá ${gold.price:,.0f}/oz",
                source="market_data",
                url="",
                panic_score=_spike_to_score(gold.change_24h, gold_threshold),
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
    # a value >= threshold is "elevated fear" regardless of daily change direction.
    vix = _find_data_point(market_data, "VIX")
    if vix and vix.price >= vix_threshold:
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
    if dxy and dxy.change_24h >= dxy_threshold:
        events.append(
            BreakingEvent(
                title=(f"Dollar Index tăng {dxy.change_24h:.1f}% — áp lực lên tài sản rủi ro"),
                source="market_data",
                url="",
                panic_score=_spike_to_score(dxy.change_24h, dxy_threshold),
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
    if spx and spx.change_24h <= spx_threshold:
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
