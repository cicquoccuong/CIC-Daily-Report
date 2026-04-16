"""Augmento Social Sentiment Collector (QO.35).

Fetches crypto social sentiment scores (bullish/bearish/neutral) from
Augmento's free public API. No API key required.

Source: https://api.augmento.ai/v0.1/topic/summary
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from cic_daily_report.core.logger import get_logger

logger = get_logger("augmento_collector")

# WHY https: prefer encrypted connection; Augmento API supports HTTPS.
API_URL = "https://api.augmento.ai/v0.1/topic/summary"
REQUEST_TIMEOUT = 20

# WHY BTC and ETH only: spec requires sentiment for top-2 assets.
# Augmento aggregates social media posts and classifies them.
TARGET_ASSETS = ["bitcoin", "ethereum"]

# WHY mapping: Augmento uses full names, we map to standard tickers.
ASSET_TICKER_MAP = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
}


@dataclass
class AssetSentiment:
    """Sentiment data for a single asset."""

    asset: str  # ticker: "BTC" or "ETH"
    bullish: float  # percentage 0-100
    bearish: float  # percentage 0-100
    neutral: float  # percentage 0-100
    source_count: int  # number of social posts analyzed


@dataclass
class SentimentResult:
    """Aggregated social sentiment data."""

    sentiments: dict[str, AssetSentiment] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to spec-required format: {asset: {bullish, bearish, neutral, source_count}}."""
        return {
            ticker: {
                "bullish": s.bullish,
                "bearish": s.bearish,
                "neutral": s.neutral,
                "source_count": s.source_count,
            }
            for ticker, s in self.sentiments.items()
        }

    def format_for_llm(self) -> str:
        """Format sentiment data for LLM context injection."""
        if not self.sentiments:
            return ""

        lines: list[str] = ["=== SOCIAL SENTIMENT (Augmento) ==="]
        for ticker, s in self.sentiments.items():
            lines.append(
                f"  {ticker}: Bullish {s.bullish:.1f}% | Bearish {s.bearish:.1f}% "
                f"| Neutral {s.neutral:.1f}% (n={s.source_count})"
            )
        return "\n".join(lines)


async def collect_augmento_sentiment() -> dict:
    """Collect crypto social sentiment from Augmento API.

    Returns dict in format: {asset: {bullish: %, bearish: %, neutral: %, source_count: N}}.
    Returns empty dict if API is down (spec: graceful fallback).
    """
    logger.info("Collecting social sentiment from Augmento")

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(API_URL)
            resp.raise_for_status()

        data = resp.json()
        if not isinstance(data, dict):
            logger.warning("Augmento: unexpected response format (not a dict)")
            return {}

        result = SentimentResult()

        for asset_name in TARGET_ASSETS:
            ticker = ASSET_TICKER_MAP[asset_name]
            asset_data = data.get(asset_name)
            if not asset_data or not isinstance(asset_data, dict):
                continue

            # WHY: Augmento returns counts — we compute percentages for normalization.
            bullish_count = float(asset_data.get("bullish", 0))
            bearish_count = float(asset_data.get("bearish", 0))
            neutral_count = float(asset_data.get("neutral", 0))
            total = bullish_count + bearish_count + neutral_count

            if total > 0:
                result.sentiments[ticker] = AssetSentiment(
                    asset=ticker,
                    bullish=round(bullish_count / total * 100, 1),
                    bearish=round(bearish_count / total * 100, 1),
                    neutral=round(neutral_count / total * 100, 1),
                    source_count=int(total),
                )

        logger.info(f"Augmento: sentiment collected for {list(result.sentiments.keys())}")
        return result.to_dict()

    except httpx.TimeoutException:
        logger.warning(f"Augmento API timeout ({REQUEST_TIMEOUT}s)")
        return {}
    except httpx.HTTPStatusError as e:
        logger.warning(f"Augmento API HTTP error: {e.response.status_code}")
        return {}
    except Exception as e:
        logger.warning(f"Augmento collector failed: {e}")
        return {}
