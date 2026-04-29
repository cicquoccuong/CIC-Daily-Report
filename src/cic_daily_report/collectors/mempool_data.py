"""Mempool.space BTC Network Data Collector (P1.20).

Collects BTC network fundamentals from Mempool.space public API:
- Hashrate (EH/s) and 7-day change
- Recommended transaction fees (sat/vB)
- Difficulty adjustment progress

No API key needed — free public endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from cic_daily_report.core.logger import get_logger

logger = get_logger("mempool_data")

MEMPOOL_BASE_URL = "https://mempool.space/api/v1"
REQUEST_TIMEOUT = 15


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class MempoolData:
    """BTC network data from Mempool.space."""

    hashrate_eh: float  # exahash/s
    hashrate_change_7d: float  # percent
    fee_fast: int  # sat/vB (fastest confirmation)
    fee_medium: int  # sat/vB (~30 min)
    fee_slow: int  # sat/vB (~1 hour)
    difficulty_change: float  # percent
    difficulty_remaining_blocks: int
    difficulty_remaining_time: int  # seconds


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


async def collect_mempool_data() -> MempoolData | None:
    """Fetch BTC network data from Mempool.space.

    Returns None if any critical endpoint fails.
    WHY graceful: Mempool data is supplementary on-chain context.
    Pipeline must not fail if this source is unavailable.
    """
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            # WHY: 3 separate endpoints for different data domains
            hashrate_data = await _fetch_hashrate(client)
            fee_data = await _fetch_fees(client)
            difficulty_data = await _fetch_difficulty(client)

        if hashrate_data is None or fee_data is None or difficulty_data is None:
            logger.warning("Mempool: one or more endpoints returned no data")
            return None

        result = MempoolData(
            hashrate_eh=hashrate_data["hashrate_eh"],
            hashrate_change_7d=hashrate_data["change_7d"],
            fee_fast=fee_data["fastestFee"],
            fee_medium=fee_data["halfHourFee"],
            fee_slow=fee_data["hourFee"],
            difficulty_change=difficulty_data["difficultyChange"],
            difficulty_remaining_blocks=difficulty_data["remainingBlocks"],
            difficulty_remaining_time=difficulty_data["remainingTime"],
        )
        logger.info(
            f"Mempool: hashrate={result.hashrate_eh:.0f} EH/s, "
            f"fees={result.fee_fast}/{result.fee_medium}/{result.fee_slow} sat/vB"
        )
        return result

    except Exception as e:
        logger.warning(f"Mempool collector failed: {e}")
        return None


async def _fetch_hashrate(client: httpx.AsyncClient) -> dict | None:
    """Fetch hashrate from /mining/hashrate/3d endpoint (Wave 0.7.1).

    Returns dict with hashrate_eh (exahash/s) and change_7d (percent).
    The API returns hashrate in H/s — we convert to EH/s.

    WHY 3d (was 1w): Mary's fact-check 29/04 showed cached value 927 EH/s while
    actual was ~994 EH/s. The /1w endpoint averages too much old data; /3d gives
    a fresher 3-day window so currentHashrate reflects today, not week-ago.
    Fallback to /1w if /3d returns no data (some Mempool instances may not expose it).
    """
    endpoint_path = "/mining/hashrate/3d"
    try:
        resp = await client.get(f"{MEMPOOL_BASE_URL}{endpoint_path}")
        if resp.status_code == 404:
            # Fallback for Mempool instances that only expose /1w
            logger.info("Mempool /3d hashrate not available, falling back to /1w")
            endpoint_path = "/mining/hashrate/1w"
            resp = await client.get(f"{MEMPOOL_BASE_URL}{endpoint_path}")
        resp.raise_for_status()
        data = resp.json()

        # WHY: API returns hashrates[], currentHashrate (H/s), currentDifficulty
        current = data.get("currentHashrate", 0)
        hashrates = data.get("hashrates", [])

        hashrate_eh = current / 1e18  # H/s → EH/s

        # Calculate change from first and last entries (label as 7d for back-compat)
        change_7d = 0.0
        if len(hashrates) >= 2:
            first_val = hashrates[0].get("avgHashrate", 0)
            last_val = hashrates[-1].get("avgHashrate", 0)
            if first_val > 0:
                change_7d = ((last_val - first_val) / first_val) * 100

        return {"hashrate_eh": hashrate_eh, "change_7d": change_7d}

    except Exception as e:
        logger.warning(f"Mempool hashrate fetch failed ({endpoint_path}): {e}")
        return None


async def _fetch_fees(client: httpx.AsyncClient) -> dict | None:
    """Fetch recommended fees from /fees/recommended endpoint.

    Returns dict with fastestFee, halfHourFee, hourFee (sat/vB).
    """
    try:
        resp = await client.get(f"{MEMPOOL_BASE_URL}/fees/recommended")
        resp.raise_for_status()
        data = resp.json()

        # Validate expected keys exist
        if "fastestFee" not in data:
            return None

        return data

    except Exception as e:
        logger.warning(f"Mempool fees fetch failed: {e}")
        return None


async def _fetch_difficulty(client: httpx.AsyncClient) -> dict | None:
    """Fetch difficulty adjustment from /difficulty-adjustment endpoint.

    Returns dict with difficultyChange (%), remainingBlocks, remainingTime (seconds).
    """
    try:
        resp = await client.get(f"{MEMPOOL_BASE_URL}/difficulty-adjustment")
        resp.raise_for_status()
        data = resp.json()

        if "difficultyChange" not in data:
            return None

        return data

    except Exception as e:
        logger.warning(f"Mempool difficulty fetch failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_mempool_for_llm(data: MempoolData | None) -> str:
    """Format Mempool data for LLM context injection.

    Output:
    === BTC NETWORK (Mempool.space) ===
    - Hashrate: 650 EH/s (+2.3% 7d)
    - Fees: Fast 25 sat/vB | Medium 15 | Slow 8
    - Difficulty: +3.1% adjustment, ~1200 blocks remaining
    """
    if data is None:
        return ""

    remaining_hours = data.difficulty_remaining_time / 3600 if data.difficulty_remaining_time else 0

    lines: list[str] = [
        "=== BTC NETWORK (Mempool.space) ===",
        f"- Hashrate: {data.hashrate_eh:,.0f} EH/s ({data.hashrate_change_7d:+.1f}% 7d)",
        f"- Fees: Fast {data.fee_fast} sat/vB | Medium {data.fee_medium} | Slow {data.fee_slow}",
        f"- Difficulty: {data.difficulty_change:+.1f}% adjustment, "
        f"~{data.difficulty_remaining_blocks} blocks remaining (~{remaining_hours:.0f}h)",
    ]

    return "\n".join(lines)
