"""Crypto Events Calendar Collector (QO.39).

Fetches upcoming crypto events (token launches, mainnet upgrades, burns,
forks, partnership announcements) from CoinMarketCal RSS.

Source: https://coinmarketcal.com/en/api (free tier — RSS fallback)
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import feedparser
import httpx

from cic_daily_report.core.logger import get_logger

logger = get_logger("crypto_calendar")

# WHY RSS: CoinMarketCal API requires registration; RSS is freely accessible
# and provides sufficient event data for our needs.
RSS_URL = "https://coinmarketcal.com/en/rss"
REQUEST_TIMEOUT = 20

# WHY 7 days: spec says "only events in next 7 days"
EVENT_HORIZON_DAYS = 7

# Categories relevant to crypto markets
RELEVANT_CATEGORIES = {
    "exchange_listing",
    "mainnet_launch",
    "token_burn",
    "hard_fork",
    "soft_fork",
    "partnership",
    "release",
    "update",
    "airdrop",
    "conference",
    "brand_collaboration",
    "staking",
    "unlock",
    "testnet",
}


def _sanitize_text(text: str) -> str:
    """Remove HTML tags, decode entities, normalize whitespace."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


@dataclass
class CryptoEvent:
    """A single upcoming crypto event."""

    title: str
    coin: str  # coin name or ticker
    date: str  # ISO 8601 or human-readable date
    category: str  # event category
    source_url: str

    def to_dict(self) -> dict:
        """Convert to dict for pipeline consumption."""
        return {
            "title": self.title,
            "coin": self.coin,
            "date": self.date,
            "category": self.category,
            "source_url": self.source_url,
            "source": "CoinMarketCal",
        }


def _extract_coin_from_title(title: str) -> str:
    """Extract coin name/ticker from event title.

    WHY: CoinMarketCal RSS titles often follow patterns like
    "Bitcoin (BTC) — Halving" or "Ethereum Mainnet Upgrade".
    We extract the first parenthesized ticker if present.
    """
    # Try pattern: "Name (TICKER)"
    match = re.search(r"\(([A-Z]{2,10})\)", title)
    if match:
        return match.group(1)
    # Fallback: return first word (often the coin name)
    parts = title.split()
    return parts[0] if parts else "Unknown"


def _extract_category_from_entry(entry: dict) -> str:
    """Extract event category from RSS entry tags or content.

    WHY: CoinMarketCal tags entries with categories. We normalize
    these to our standard category set.
    """
    # Check feedparser tags
    tags = entry.get("tags", [])
    for tag in tags:
        term = tag.get("term", "").lower().replace(" ", "_")
        if term in RELEVANT_CATEGORIES:
            return term

    # Fallback: infer from title keywords
    title_lower = entry.get("title", "").lower()
    keyword_map = {
        "listing": "exchange_listing",
        "mainnet": "mainnet_launch",
        "burn": "token_burn",
        "fork": "hard_fork",
        "partnership": "partnership",
        "release": "release",
        "update": "update",
        "airdrop": "airdrop",
        "staking": "staking",
        "unlock": "unlock",
        "testnet": "testnet",
    }
    for keyword, category in keyword_map.items():
        if keyword in title_lower:
            return category

    return "other"


def _parse_event_date(entry: dict) -> str:
    """Parse event date from RSS entry.

    WHY: RSS dates may be in various formats; we normalize to ISO 8601.
    """
    published = entry.get("published", "")
    if published:
        try:
            # feedparser often provides time_struct
            ts = entry.get("published_parsed")
            if ts:
                dt = datetime(*ts[:6], tzinfo=timezone.utc)
                return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except (TypeError, ValueError):
            pass
        return published
    return ""


def _is_within_horizon(date_str: str, horizon_days: int) -> bool:
    """Check if event date is within the next N days.

    WHY: spec says "only events in next 7 days".
    Returns True if date cannot be parsed (conservative — include rather than exclude).
    """
    if not date_str:
        return True  # WHY: include events with unknown dates rather than silently dropping

    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=horizon_days)

    try:
        # Try ISO format first
        event_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return now <= event_dt <= cutoff
    except (ValueError, TypeError):
        pass

    # If can't parse, include it (conservative approach)
    return True


async def collect_crypto_calendar() -> list[dict]:
    """Collect upcoming crypto events from CoinMarketCal RSS.

    Returns list of event dicts. Returns empty list on any error
    (never breaks pipeline — spec requirement).
    """
    logger.info("Collecting crypto events calendar from CoinMarketCal")

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(RSS_URL, follow_redirects=True)
            response.raise_for_status()

        parsed = feedparser.parse(response.text)

        events: list[CryptoEvent] = []
        for entry in parsed.entries:
            title = _sanitize_text(entry.get("title", ""))
            url = entry.get("link", "").strip()

            if not title or not url:
                continue

            event_date = _parse_event_date(entry)

            # Filter: only events within 7-day horizon
            if not _is_within_horizon(event_date, EVENT_HORIZON_DAYS):
                continue

            coin = _extract_coin_from_title(title)
            category = _extract_category_from_entry(entry)

            events.append(
                CryptoEvent(
                    title=title,
                    coin=coin,
                    date=event_date,
                    category=category,
                    source_url=url,
                )
            )

        logger.info(f"Crypto calendar: {len(events)} upcoming events collected")
        return [event.to_dict() for event in events]

    except httpx.TimeoutException:
        logger.warning(f"CoinMarketCal RSS timeout ({REQUEST_TIMEOUT}s)")
        return []
    except httpx.HTTPStatusError as e:
        logger.warning(f"CoinMarketCal RSS HTTP error: {e.response.status_code}")
        return []
    except Exception as e:
        logger.warning(f"Crypto calendar collector failed: {e}")
        return []
