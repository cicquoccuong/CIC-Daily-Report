"""Economic Calendar Collector (FR60).

Fetches upcoming macro-economic events (Fed, CPI, PPI, FOMC, etc.)
from FairEconomy/Forex Factory feed. Filters for high-impact USD events
most relevant to crypto markets.

Source: https://nfs.faireconomy.media/ff_calendar_thisweek.json
Free, no API key required. ~100+ events/week.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx

from cic_daily_report.core.logger import get_logger

logger = get_logger("economic_calendar")

FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
TIMEOUT = 15

# Event titles most relevant to crypto markets
CRYPTO_RELEVANT_EVENTS = {
    "Federal Funds Rate",
    "Fed Interest Rate Decision",
    "FOMC Statement",
    "FOMC Meeting Minutes",
    "FOMC Press Conference",
    "FOMC Member",  # prefix match
    "CPI m/m",
    "CPI y/y",
    "Core CPI m/m",
    "Core CPI y/y",
    "PPI m/m",
    "PPI y/y",
    "Core PPI m/m",
    "Non-Farm Employment Change",
    "Unemployment Rate",
    "Unemployment Claims",
    "GDP q/q",
    "Advance GDP q/q",
    "Prelim GDP q/q",
    "Retail Sales m/m",
    "Core Retail Sales m/m",
    "ISM Manufacturing PMI",
    "ISM Services PMI",
    "Consumer Confidence",
    "CB Consumer Confidence",
    "PCE Price Index m/m",
    "Core PCE Price Index m/m",
    "Durable Goods Orders m/m",
    "Trade Balance",
    "Treasury Currency Report",
    "10-y Bond Auction",
    "30-y Bond Auction",
}


@dataclass
class EconomicEvent:
    """A single economic calendar event."""

    title: str
    country: str
    date: str  # ISO 8601
    impact: str  # "High", "Medium", "Low", "Holiday"
    forecast: str
    previous: str


@dataclass
class CalendarResult:
    """Result of economic calendar collection."""

    events: list[EconomicEvent] = field(default_factory=list)
    today_events: list[EconomicEvent] = field(default_factory=list)
    upcoming_events: list[EconomicEvent] = field(default_factory=list)

    def format_for_llm(self) -> str:
        """Format events as text context for LLM prompt."""
        if not self.events:
            return ""

        lines: list[str] = []

        if self.today_events:
            lines.append("📅 SỰ KIỆN KINH TẾ HÔM NAY:")
            for ev in self.today_events:
                line = f"  • {ev.title} ({ev.impact})"
                if ev.forecast:
                    line += f" — Dự báo: {ev.forecast}"
                if ev.previous:
                    line += f", Trước đó: {ev.previous}"
                lines.append(line)

        if self.upcoming_events:
            lines.append("\n📅 SỰ KIỆN SẮP TỚI TRONG TUẦN:")
            for ev in self.upcoming_events:
                # Parse date for display
                date_str = _format_event_date(ev.date)
                line = f"  • [{date_str}] {ev.title} ({ev.impact})"
                if ev.forecast:
                    line += f" — Dự báo: {ev.forecast}"
                if ev.previous:
                    line += f", Trước đó: {ev.previous}"
                lines.append(line)

        return "\n".join(lines)


def _format_event_date(iso_date: str) -> str:
    """Format ISO date to 'DD/MM HH:MM' for display."""
    try:
        dt = datetime.fromisoformat(iso_date)
        # Convert to UTC+7 (Vietnam timezone) for display
        vn_dt = dt.astimezone(timezone(timedelta(hours=7)))
        return vn_dt.strftime("%d/%m %H:%M VN")
    except (ValueError, TypeError):
        return iso_date[:16] if iso_date else "N/A"


def _is_crypto_relevant(title: str) -> bool:
    """Check if event title is relevant to crypto markets."""
    for keyword in CRYPTO_RELEVANT_EVENTS:
        if title.startswith(keyword) or title == keyword:
            return True
    return False


async def collect_economic_calendar() -> CalendarResult:
    """Fetch and filter economic calendar events.

    Returns high-impact USD events relevant to crypto markets,
    split into today vs upcoming.

    Returns empty CalendarResult on any error (graceful fallback).
    """
    logger.info("Collecting economic calendar events")

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(FEED_URL)
            resp.raise_for_status()

        raw_events = resp.json()
        if not isinstance(raw_events, list):
            logger.warning("Unexpected feed format: not a list")
            return CalendarResult()

        # Filter: High impact + USD country + crypto-relevant
        filtered: list[EconomicEvent] = []
        for item in raw_events:
            impact = item.get("impact", "")
            country = item.get("country", "")
            title = item.get("title", "")

            # Keep High impact USD events that are crypto-relevant
            if impact == "High" and country == "USD" and _is_crypto_relevant(title):
                filtered.append(
                    EconomicEvent(
                        title=title,
                        country=country,
                        date=item.get("date", ""),
                        impact=impact,
                        forecast=item.get("forecast", ""),
                        previous=item.get("previous", ""),
                    )
                )

        # Split into today vs upcoming
        now_utc = datetime.now(timezone.utc)
        today_events: list[EconomicEvent] = []
        upcoming_events: list[EconomicEvent] = []

        for ev in filtered:
            try:
                ev_dt = datetime.fromisoformat(ev.date)
                ev_utc = ev_dt.astimezone(timezone.utc)
                if ev_utc.date() == now_utc.date():
                    today_events.append(ev)
                elif ev_utc > now_utc:
                    upcoming_events.append(ev)
            except (ValueError, TypeError):
                upcoming_events.append(ev)

        result = CalendarResult(
            events=filtered,
            today_events=today_events,
            upcoming_events=upcoming_events,
        )

        logger.info(
            f"Economic calendar: {len(filtered)} events "
            f"(today={len(today_events)}, upcoming={len(upcoming_events)})"
        )
        return result

    except httpx.HTTPStatusError as e:
        logger.warning(f"Economic calendar HTTP error: {e.response.status_code}")
        return CalendarResult()
    except httpx.RequestError as e:
        logger.warning(f"Economic calendar request failed: {e}")
        return CalendarResult()
    except Exception as e:
        logger.warning(f"Economic calendar unexpected error: {e}")
        return CalendarResult()
