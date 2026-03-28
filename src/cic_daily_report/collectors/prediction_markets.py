"""Polymarket Prediction Markets Collector (P1.4 — Expert Consensus Engine).

Fetches BTC/ETH prediction market data from Polymarket's public Gamma API.
No authentication needed. Used as "skin in the game" signal for consensus engine.

NOTE: This module is standalone for now. It will be wired into the daily pipeline
in P1.6 (Consensus Engine) — see docs/epics.md for integration plan.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from cic_daily_report.core.logger import get_logger

logger = get_logger("prediction_markets")

# --- Constants ---

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
POLYMARKET_EVENT_URL = "https://polymarket.com/event"
REQUEST_TIMEOUT = 15  # seconds per request
MIN_VOLUME_USD = 10_000  # filter out tiny markets
MAX_MARKETS_PER_ASSET = 10

# WHY: Two separate keyword groups to catch both full names and ticker symbols.
# "eth" alone could match "method" etc., but Polymarket questions are crypto-focused
# so false positives are rare and filtered by the crypto tag anyway.
BTC_KEYWORDS = ("bitcoin", "btc")
ETH_KEYWORDS = ("ethereum", "eth")


# --- Dataclasses ---


@dataclass
class PredictionMarket:
    """Single prediction market from Polymarket."""

    question: str
    outcome_yes: float  # 0.0-1.0 probability for YES
    outcome_no: float  # 0.0-1.0 probability for NO
    volume: float  # Total volume in USD
    liquidity: float  # Available liquidity
    end_date: str  # Market end date (ISO)
    url: str  # Polymarket URL
    asset: str  # "BTC", "ETH", or "CRYPTO"
    source: str = "polymarket"


@dataclass
class PredictionMarketsData:
    """Aggregated prediction markets data."""

    markets: list[PredictionMarket] = field(default_factory=list)
    fetch_timestamp: str = ""
    source: str = "polymarket"

    def format_for_llm(self) -> str:
        """Format markets data for LLM context injection.

        Groups by asset, formats each market as a compact readable line.
        """
        if not self.markets:
            return ""

        # Group by asset
        grouped: dict[str, list[PredictionMarket]] = {}
        for m in self.markets:
            grouped.setdefault(m.asset, []).append(m)

        lines: list[str] = ["=== Polymarket Prediction Markets ==="]
        for asset in ("BTC", "ETH", "CRYPTO"):
            markets = grouped.get(asset, [])
            if not markets:
                continue
            lines.append(f"\n[{asset}]")
            for m in markets:
                yes_pct = round(m.outcome_yes * 100)
                vol_str = _format_volume(m.volume)
                lines.append(f"  {m.question}: YES {yes_pct}% (Vol: {vol_str})")

        return "\n".join(lines)

    def format_for_consensus(self) -> dict:
        """Extract consensus-relevant data for the consensus engine.

        Returns average bullish probability per asset + top markets list.
        """
        if not self.markets:
            return {
                "btc_bullish_pct": 0.0,
                "eth_bullish_pct": 0.0,
                "key_markets": [],
            }

        btc_probs: list[float] = []
        eth_probs: list[float] = []
        key_markets: list[dict] = []

        for m in self.markets:
            if m.asset == "BTC":
                btc_probs.append(m.outcome_yes)
            elif m.asset == "ETH":
                eth_probs.append(m.outcome_yes)

            key_markets.append(
                {
                    "question": m.question,
                    "yes_pct": round(m.outcome_yes * 100, 1),
                    "volume": m.volume,
                    "asset": m.asset,
                }
            )

        return {
            "btc_bullish_pct": round(sum(btc_probs) / len(btc_probs) * 100, 1)
            if btc_probs
            else 0.0,
            "eth_bullish_pct": round(sum(eth_probs) / len(eth_probs) * 100, 1)
            if eth_probs
            else 0.0,
            "key_markets": key_markets,
        }


# --- Public API ---


async def collect_prediction_markets() -> PredictionMarketsData:
    """Collect BTC/ETH prediction market data from Polymarket.

    Strategy:
    1. Search for BTC-related markets (keywords: "bitcoin", "btc")
    2. Search for ETH-related markets (keywords: "ethereum", "eth")
    3. Filter: only active markets with volume > $10K
    4. Sort by volume (highest first)
    5. Return top 10 markets per asset

    Free API, no auth needed. Rate limit: be respectful (1 req/sec).
    Graceful degrade: return empty PredictionMarketsData on failure.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        # WHY: parallel fetch for both keyword groups to minimize latency
        btc_raw, eth_raw = await asyncio.gather(
            _fetch_markets("bitcoin"),
            _fetch_markets("ethereum"),
        )

        all_markets = _parse_and_filter(btc_raw + eth_raw)

        # Deduplicate by question text (same market may appear in both searches)
        seen_questions: set[str] = set()
        unique_markets: list[PredictionMarket] = []
        for m in all_markets:
            q_lower = m.question.lower()
            if q_lower not in seen_questions:
                seen_questions.add(q_lower)
                unique_markets.append(m)

        # Sort by volume descending, then cap per asset
        unique_markets.sort(key=lambda m: m.volume, reverse=True)
        final = _cap_per_asset(unique_markets)

        logger.info(f"Prediction markets collected: {len(final)} markets")
        return PredictionMarketsData(markets=final, fetch_timestamp=timestamp)

    except Exception as exc:
        logger.warning(f"Prediction markets collection failed: {exc}")
        return PredictionMarketsData(markets=[], fetch_timestamp=timestamp)


# --- Internal helpers ---


async def _fetch_markets(keyword: str) -> list[dict]:
    """Fetch markets from Gamma API for a given keyword.

    Returns raw market dicts, or empty list on failure.
    """
    url = f"{GAMMA_API_BASE}/markets"
    params = {"tag": "crypto", "closed": "false", "limit": "50"}
    # WHY: Gamma API uses 'slug_contains' for keyword search
    if keyword:
        params["slug_contains"] = keyword

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            # API returns a JSON array directly
            if isinstance(data, list):
                return data
            return []
    except httpx.TimeoutException:
        logger.warning(f"Polymarket API timeout for keyword '{keyword}'")
        return []
    except Exception as exc:
        logger.warning(f"Polymarket API error for keyword '{keyword}': {exc}")
        return []


def _parse_and_filter(raw_markets: list[dict]) -> list[PredictionMarket]:
    """Parse raw API responses into PredictionMarket objects.

    Filters out: inactive, closed, low volume, unparseable outcomes.
    """
    results: list[PredictionMarket] = []

    for raw in raw_markets:
        try:
            # Skip inactive or closed markets
            if not raw.get("active", False) or raw.get("closed", False):
                continue

            # Parse volume, skip low-volume markets
            volume = float(raw.get("volume", "0") or "0")
            if volume < MIN_VOLUME_USD:
                continue

            # Parse outcomePrices — JSON string like "[0.72, 0.28]"
            outcome_prices = _parse_outcome_prices(raw.get("outcomePrices", ""))
            if outcome_prices is None:
                continue

            question = raw.get("question", "")
            slug = raw.get("slug", "")
            liquidity = float(raw.get("liquidity", "0") or "0")
            end_date = raw.get("endDate", "")

            results.append(
                PredictionMarket(
                    question=question,
                    outcome_yes=outcome_prices[0],
                    outcome_no=outcome_prices[1],
                    volume=volume,
                    liquidity=liquidity,
                    end_date=end_date,
                    url=f"{POLYMARKET_EVENT_URL}/{slug}",
                    asset=_detect_asset(question),
                )
            )
        except (ValueError, KeyError, TypeError) as exc:
            logger.debug(f"Skipping unparseable market: {exc}")
            continue

    return results


def _parse_outcome_prices(raw: str) -> tuple[float, float] | None:
    """Parse outcomePrices JSON string into (yes_prob, no_prob).

    Returns None if parsing fails.
    """
    if not raw:
        return None
    try:
        prices = json.loads(raw)
        if isinstance(prices, list) and len(prices) >= 2:
            yes_prob = float(prices[0])
            no_prob = float(prices[1])
            # WHY: basic sanity check — probabilities should be in [0, 1]
            if 0.0 <= yes_prob <= 1.0 and 0.0 <= no_prob <= 1.0:
                return (yes_prob, no_prob)
        return None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def _detect_asset(question: str) -> str:
    """Detect asset type from market question text.

    WHY: Simple keyword match is sufficient — Polymarket questions are explicit
    about which crypto asset they reference.
    """
    q_lower = question.lower()
    for kw in BTC_KEYWORDS:
        if kw in q_lower:
            return "BTC"
    for kw in ETH_KEYWORDS:
        if kw in q_lower:
            return "ETH"
    return "CRYPTO"


def _cap_per_asset(
    markets: list[PredictionMarket],
) -> list[PredictionMarket]:
    """Cap to MAX_MARKETS_PER_ASSET per asset type.

    WHY: Prevent one asset from dominating the list. Markets are already
    sorted by volume, so we keep the highest-volume ones.
    """
    counts: dict[str, int] = {}
    result: list[PredictionMarket] = []
    for m in markets:
        count = counts.get(m.asset, 0)
        if count < MAX_MARKETS_PER_ASSET:
            result.append(m)
            counts[m.asset] = count + 1
    return result


def _format_volume(volume: float) -> str:
    """Format volume to human-readable string (e.g., $5.2M, $120K)."""
    if volume >= 1_000_000:
        return f"${volume / 1_000_000:.1f}M"
    if volume >= 1_000:
        return f"${volume / 1_000:.0f}K"
    return f"${volume:.0f}"
