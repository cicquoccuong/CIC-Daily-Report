"""Deribit Options Data Collector (QO.43).

Fetches BTC and ETH options data from Deribit public API.
No API key needed — all endpoints used are public.

Collects:
  - Implied Volatility (IV) for near-term expiry
  - Max Pain price
  - Put/Call ratio

Source: https://www.deribit.com/api/v2/public/
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from cic_daily_report.core.logger import get_logger

logger = get_logger("deribit_collector")

# WHY public API: Deribit v2 public endpoints require no authentication.
# The book_summary_by_currency endpoint gives us IV, volume, and OI per
# instrument, which we aggregate into put/call ratio and max pain.
DERIBIT_API_BASE = "https://www.deribit.com/api/v2/public"
REQUEST_TIMEOUT = 20  # seconds — Deribit can be slow during high-volume periods
CURRENCIES = ("BTC", "ETH")


@dataclass
class OptionsData:
    """Aggregated options data for a single asset (BTC or ETH).

    WHY dataclass: structured data that flows into daily_pipeline
    alongside other collector outputs. Consistent with MarketDataPoint pattern.
    """

    currency: str  # "BTC" or "ETH"
    iv_avg: float = 0.0  # Average implied volatility across near-term options
    max_pain: float = 0.0  # Max pain price (strike where most options expire worthless)
    put_call_ratio: float = 0.0  # Put volume / Call volume
    total_volume: float = 0.0  # Total options volume (contracts)
    collected_at: str = ""
    source: str = "deribit"

    def to_dict(self) -> dict:
        """Convert to dict for pipeline consumption."""
        return {
            "currency": self.currency,
            "iv_avg": round(self.iv_avg, 2),
            "max_pain": round(self.max_pain, 2),
            "put_call_ratio": round(self.put_call_ratio, 4),
            "total_volume": round(self.total_volume, 2),
            "collected_at": self.collected_at,
            "source": self.source,
        }


@dataclass
class DeribitOptionsData:
    """Container for all options data collected from Deribit."""

    options: list[OptionsData] = field(default_factory=list)

    def get(self, currency: str) -> OptionsData | None:
        """Get options data for a specific currency."""
        for opt in self.options:
            if opt.currency == currency:
                return opt
        return None

    def format_for_llm(self) -> str:
        """Format options data for LLM context injection.

        WHY separate method: keeps formatting logic close to the data structure.
        """
        if not self.options:
            return ""

        parts = ["=== DU LIEU QUYEN CHON (DERIBIT) ==="]
        for opt in self.options:
            if opt.iv_avg > 0 or opt.max_pain > 0:
                line = f"{opt.currency}: IV={opt.iv_avg:.1f}%"
                if opt.max_pain > 0:
                    line += f" | Max Pain=${opt.max_pain:,.0f}"
                if opt.put_call_ratio > 0:
                    line += f" | Put/Call={opt.put_call_ratio:.2f}"
                if opt.total_volume > 0:
                    line += f" | Vol={opt.total_volume:,.0f}"
                parts.append(line)
        return "\n".join(parts) if len(parts) > 1 else ""


def _calculate_max_pain(instruments: list[dict]) -> float:
    """Calculate max pain price from option instruments.

    Max Pain = the strike price at which the total value of options
    that expire worthless is maximized (i.e., where option sellers
    keep the most premium).

    Algorithm: For each unique strike, sum the total OI * loss for
    puts below and calls above. The strike with minimum total loss
    to option holders = max pain.

    WHY simplified: We use open interest weighting rather than full
    P&L calculation. This gives a good approximation for daily context.
    """
    # WHY filter: only include instruments with meaningful open interest
    strikes: dict[float, dict[str, float]] = {}
    for inst in instruments:
        strike = inst.get("strike", 0)
        if strike <= 0:
            continue
        oi = inst.get("open_interest", 0) or 0
        if oi <= 0:
            continue

        inst_name = inst.get("instrument_name", "")
        if strike not in strikes:
            strikes[strike] = {"call_oi": 0, "put_oi": 0}

        if inst_name.endswith("-C"):
            strikes[strike]["call_oi"] += oi
        elif inst_name.endswith("-P"):
            strikes[strike]["put_oi"] += oi

    if not strikes:
        return 0.0

    all_strikes = sorted(strikes.keys())

    # WHY: For each candidate strike, calculate total "pain" = how much
    # option holders lose if price settles at that strike.
    min_pain = float("inf")
    max_pain_strike = 0.0

    for candidate in all_strikes:
        total_pain = 0.0
        for strike, oi_data in strikes.items():
            # Calls: lose money when price < strike (call expires worthless)
            # Pain to call holders = call_oi * max(0, strike - candidate)
            if candidate < strike:
                total_pain += oi_data["call_oi"] * (strike - candidate)
            # Puts: lose money when price > strike (put expires worthless)
            # Pain to put holders = put_oi * max(0, candidate - strike)
            if candidate > strike:
                total_pain += oi_data["put_oi"] * (candidate - strike)

        if total_pain < min_pain:
            min_pain = total_pain
            max_pain_strike = candidate

    return max_pain_strike


def _calculate_put_call_ratio(instruments: list[dict]) -> float:
    """Calculate put/call ratio from option instruments.

    Ratio = total put volume / total call volume.
    >1.0 = bearish sentiment (more puts being bought).
    <1.0 = bullish sentiment (more calls being bought).

    WHY volume not OI: volume reflects current-day activity (sentiment now),
    while OI reflects accumulated positions (may be old hedges).
    """
    put_volume = 0.0
    call_volume = 0.0

    for inst in instruments:
        volume = inst.get("volume", 0) or 0
        inst_name = inst.get("instrument_name", "")
        if inst_name.endswith("-C"):
            call_volume += volume
        elif inst_name.endswith("-P"):
            put_volume += volume

    if call_volume == 0:
        return 0.0
    return put_volume / call_volume


def _calculate_avg_iv(instruments: list[dict]) -> float:
    """Calculate volume-weighted average IV from option instruments.

    WHY volume-weighted: heavily traded options have more reliable IV.
    Illiquid options can have extreme IV values that distort the average.
    """
    total_iv_weighted = 0.0
    total_volume = 0.0

    for inst in instruments:
        iv = inst.get("mark_iv", 0) or 0
        volume = inst.get("volume", 0) or 0
        if iv > 0 and volume > 0:
            total_iv_weighted += iv * volume
            total_volume += volume

    if total_volume == 0:
        return 0.0
    return total_iv_weighted / total_volume


async def _fetch_book_summary(currency: str) -> list[dict]:
    """Fetch option book summaries from Deribit for a currency.

    Uses get_book_summary_by_currency endpoint which returns
    summary data for all active option instruments.

    Returns list of instrument dicts or empty list on failure.
    """
    url = f"{DERIBIT_API_BASE}/get_book_summary_by_currency"
    params = {"currency": currency, "kind": "option"}

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        result = data.get("result", [])
        if not result:
            logger.info(f"Deribit {currency}: no option instruments returned")
            return []

        logger.debug(f"Deribit {currency}: {len(result)} option instruments fetched")
        return result
    except httpx.TimeoutException:
        logger.warning(f"Deribit {currency} request timed out after {REQUEST_TIMEOUT}s")
        return []
    except httpx.HTTPStatusError as e:
        logger.warning(f"Deribit {currency} HTTP error: {e.response.status_code}")
        return []
    except Exception as e:
        logger.warning(f"Deribit {currency} fetch failed: {e}")
        return []


async def collect_deribit_options() -> DeribitOptionsData:
    """Collect options data from Deribit for BTC and ETH.

    Returns DeribitOptionsData with OptionsData per currency.
    Returns empty container if Deribit API fails — caller should
    check options.options list before using.

    WHY async: runs in parallel with other collectors in daily_pipeline.
    """
    result = DeribitOptionsData()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    for currency in CURRENCIES:
        try:
            instruments = await _fetch_book_summary(currency)
            if not instruments:
                continue

            iv_avg = _calculate_avg_iv(instruments)
            max_pain = _calculate_max_pain(instruments)
            put_call_ratio = _calculate_put_call_ratio(instruments)
            total_volume = sum((inst.get("volume", 0) or 0) for inst in instruments)

            opt = OptionsData(
                currency=currency,
                iv_avg=iv_avg,
                max_pain=max_pain,
                put_call_ratio=put_call_ratio,
                total_volume=total_volume,
                collected_at=now,
            )
            result.options.append(opt)
            logger.info(
                f"Deribit {currency}: IV={iv_avg:.1f}%, MaxPain=${max_pain:,.0f}, "
                f"P/C={put_call_ratio:.2f}, Vol={total_volume:,.0f}"
            )
        except Exception as e:
            # WHY catch-all: one currency failing must not block the other.
            logger.warning(f"Deribit {currency} collection failed: {e}")

    if result.options:
        logger.info(f"Deribit options collected: {len(result.options)} currencies")
    else:
        logger.warning("Deribit options: no data collected (API may be down)")

    return result
