"""Token Unlock Calendar Collector (QO.46).

Fetches upcoming token unlock events from public sources.
Primary: token.unlocks.app RSS/API if available.
Fallback: DeFiLlama unlocks endpoint.

Filters: next 7 days, significant unlocks (> $1M value or > 1% supply).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from cic_daily_report.core.logger import get_logger

logger = get_logger("token_unlock_collector")

# WHY DeFiLlama: token.unlocks.app has no stable free API.
# DeFiLlama /unlocks endpoint provides unlock schedules for free.
DEFILLAMA_UNLOCKS_URL = "https://api.llama.fi/unlocks"
REQUEST_TIMEOUT = 20

# Spec filters
UNLOCK_HORIZON_DAYS = 7
MIN_VALUE_USD = 1_000_000  # $1M minimum
MIN_SUPPLY_PCT = 1.0  # 1% of circulating supply


@dataclass
class TokenUnlock:
    """A single token unlock event."""

    token_name: str
    unlock_date: str  # ISO 8601
    amount: float  # number of tokens
    percentage_of_supply: float  # % of circulating supply
    value_usd: float  # estimated USD value
    source: str = "DeFiLlama"

    def to_dict(self) -> dict:
        """Convert to dict for pipeline consumption."""
        return {
            "token_name": self.token_name,
            "unlock_date": self.unlock_date,
            "amount": self.amount,
            "percentage_of_supply": self.percentage_of_supply,
            "value_usd": self.value_usd,
            "source": self.source,
        }


def _is_significant(value_usd: float, pct_supply: float) -> bool:
    """Check if unlock is significant per spec: > $1M value OR > 1% supply.

    WHY: Small unlocks are noise — only large ones affect price action.
    """
    return value_usd > MIN_VALUE_USD or pct_supply > MIN_SUPPLY_PCT


def _is_within_horizon(date_str: str, horizon_days: int) -> bool:
    """Check if unlock date is within the next N days."""
    if not date_str:
        return False

    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=horizon_days)

    try:
        # Handle Unix timestamp (DeFiLlama format)
        if isinstance(date_str, (int, float)):
            event_dt = datetime.fromtimestamp(date_str, tz=timezone.utc)
        else:
            event_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return now <= event_dt <= cutoff
    except (ValueError, TypeError, OSError):
        return False


def _timestamp_to_iso(ts: int | float | str) -> str:
    """Convert Unix timestamp or date string to ISO 8601."""
    try:
        if isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        return str(ts)
    except (ValueError, TypeError, OSError):
        return str(ts)


async def collect_token_unlocks() -> list[dict]:
    """Collect upcoming token unlock events.

    Returns list of unlock dicts. Returns empty list on any error
    (never breaks pipeline — spec requirement).
    """
    logger.info("Collecting token unlock events")

    try:
        unlocks = await _fetch_defillama_unlocks()
        logger.info(f"Token unlocks: {len(unlocks)} significant events in next 7 days")
        return [u.to_dict() for u in unlocks]

    except Exception as e:
        logger.warning(f"Token unlock collector failed: {e}")
        return []


async def _fetch_defillama_unlocks() -> list[TokenUnlock]:
    """Fetch unlock data from DeFiLlama.

    DeFiLlama /unlocks returns a list of protocols with their unlock schedules.
    We extract upcoming unlock events and filter for significance.
    """
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(DEFILLAMA_UNLOCKS_URL)
            resp.raise_for_status()

        data = resp.json()
        if not isinstance(data, list):
            logger.warning("DeFiLlama unlocks: unexpected format (not a list)")
            return []

        unlocks: list[TokenUnlock] = []

        for protocol in data:
            name = protocol.get("name", "Unknown")
            # WHY: DeFiLlama returns events[] with timestamps and token amounts
            events = protocol.get("events", [])
            if not isinstance(events, list):
                continue

            max_supply = float(protocol.get("maxSupply", 0) or 0)

            for event in events:
                ts = event.get("timestamp")
                if ts is None:
                    continue

                # Check if within 7-day horizon
                iso_date = _timestamp_to_iso(ts)
                if not _is_within_horizon(ts, UNLOCK_HORIZON_DAYS):
                    continue

                # Extract unlock amount and value
                no_of_tokens = float(
                    event.get("noOfTokens", [0])[0]
                    if isinstance(event.get("noOfTokens"), list)
                    else event.get("noOfTokens", 0) or 0
                )
                # WHY: DeFiLlama sometimes provides USD value directly,
                # otherwise we rely on the protocol-level price.
                token_price = float(protocol.get("price", 0) or 0)
                value_usd = no_of_tokens * token_price

                pct_supply = 0.0
                if max_supply > 0:
                    pct_supply = (no_of_tokens / max_supply) * 100

                # Filter: only significant unlocks
                if not _is_significant(value_usd, pct_supply):
                    continue

                unlocks.append(
                    TokenUnlock(
                        token_name=name,
                        unlock_date=iso_date,
                        amount=no_of_tokens,
                        percentage_of_supply=round(pct_supply, 2),
                        value_usd=round(value_usd, 2),
                    )
                )

        # Sort by value descending — most impactful first
        unlocks.sort(key=lambda u: u.value_usd, reverse=True)
        return unlocks

    except httpx.TimeoutException:
        logger.warning(f"DeFiLlama unlocks timeout ({REQUEST_TIMEOUT}s)")
        return []
    except httpx.HTTPStatusError as e:
        logger.warning(f"DeFiLlama unlocks HTTP error: {e.response.status_code}")
        return []
    except Exception as e:
        logger.warning(f"DeFiLlama unlocks failed: {e}")
        return []
