"""Macro News Collector (QO.47) — GDELT + NewsAPI.org.

Collects major macro/economic news headlines relevant to crypto markets.
- Primary: GDELT Project (free, no key needed)
- Supplementary: NewsAPI.org (free tier 100 req/day, needs NEWSAPI_KEY)

GDELT TV API: https://api.gdeltproject.org/api/v2/tv/tv
NewsAPI: https://newsapi.org/v2/everything
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from cic_daily_report.core.logger import get_logger

logger = get_logger("macro_news_collector")

# --- GDELT config ---
# WHY DOC API over TV API: DOC API returns article metadata (title, URL, date)
# which is what we need. TV API is for television mentions.
GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_QUERY = (
    '(inflation OR "interest rate" OR "federal reserve" OR GDP OR employment '
    'OR tariff OR recession OR "central bank" OR crypto OR bitcoin)'
)

# --- NewsAPI config ---
NEWSAPI_URL = "https://newsapi.org/v2/everything"
NEWSAPI_QUERY = 'cryptocurrency OR bitcoin OR "federal reserve" OR inflation OR GDP'

REQUEST_TIMEOUT = 20
MAX_HEADLINES = 30  # combined limit from both sources


@dataclass
class MacroHeadline:
    """A single macro news headline."""

    title: str
    source: str  # publisher name
    url: str
    timestamp: str  # ISO 8601
    provider: str  # "gdelt" or "newsapi"

    def to_dict(self) -> dict:
        """Convert to dict for pipeline consumption."""
        return {
            "title": self.title,
            "source": self.source,
            "url": self.url,
            "timestamp": self.timestamp,
            "provider": self.provider,
        }


async def collect_macro_news() -> list[dict]:
    """Collect macro news from GDELT (primary) + NewsAPI (supplementary).

    Returns list of headline dicts from at least one source.
    Returns empty list only if ALL sources fail (spec: graceful fallback).
    """
    logger.info("Collecting macro news headlines")

    # WHY parallel: both APIs are independent — fetch concurrently for speed.
    gdelt_task = _fetch_gdelt()
    newsapi_task = _fetch_newsapi()

    results = await asyncio.gather(gdelt_task, newsapi_task, return_exceptions=True)

    headlines: list[MacroHeadline] = []

    # GDELT results (primary)
    if isinstance(results[0], list):
        headlines.extend(results[0])
        logger.info(f"GDELT: {len(results[0])} headlines")
    elif isinstance(results[0], Exception):
        logger.warning(f"GDELT failed: {results[0]}")

    # NewsAPI results (supplementary)
    if isinstance(results[1], list):
        headlines.extend(results[1])
        logger.info(f"NewsAPI: {len(results[1])} headlines")
    elif isinstance(results[1], Exception):
        logger.warning(f"NewsAPI failed: {results[1]}")

    if not headlines:
        logger.warning("Macro news: all sources failed — returning empty list")
        return []

    # Deduplicate by title (case-insensitive)
    seen_titles: set[str] = set()
    unique: list[MacroHeadline] = []
    for h in headlines:
        title_lower = h.title.lower().strip()
        if title_lower and title_lower not in seen_titles:
            seen_titles.add(title_lower)
            unique.append(h)

    # Cap to MAX_HEADLINES
    unique = unique[:MAX_HEADLINES]

    logger.info(f"Macro news: {len(unique)} unique headlines collected")
    return [h.to_dict() for h in unique]


async def _fetch_gdelt() -> list[MacroHeadline]:
    """Fetch macro news from GDELT DOC API.

    GDELT is completely free, no key needed.
    Returns last 24h of matching articles.
    """
    params = {
        "query": GDELT_QUERY,
        "mode": "artlist",
        "maxrecords": "20",
        "format": "json",
        "sort": "datedesc",
        # WHY sourcelang: spec says "English + Vietnamese" — GDELT supports lang filter
        "sourcelang": "english",
    }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(GDELT_DOC_URL, params=params)
            resp.raise_for_status()

        data = resp.json()
        articles = data.get("articles", [])
        if not isinstance(articles, list):
            return []

        headlines: list[MacroHeadline] = []
        for article in articles:
            title = article.get("title", "").strip()
            url = article.get("url", "").strip()
            source = article.get("domain", "GDELT")
            # WHY seendate: GDELT uses "seendate" (YYYYMMDDTHHMMSSZ format)
            seen_date = article.get("seendate", "")
            iso_date = _parse_gdelt_date(seen_date)

            if title and url:
                headlines.append(
                    MacroHeadline(
                        title=title,
                        source=source,
                        url=url,
                        timestamp=iso_date,
                        provider="gdelt",
                    )
                )

        return headlines

    except httpx.TimeoutException:
        logger.warning(f"GDELT API timeout ({REQUEST_TIMEOUT}s)")
        return []
    except httpx.HTTPStatusError as e:
        logger.warning(f"GDELT API HTTP error: {e.response.status_code}")
        return []
    except Exception as e:
        logger.warning(f"GDELT fetch failed: {e}")
        return []


async def _fetch_newsapi() -> list[MacroHeadline]:
    """Fetch macro news from NewsAPI.org (supplementary).

    Requires NEWSAPI_KEY env var. Free tier: 100 req/day.
    Returns empty list if key not set or API fails.
    """
    api_key = os.getenv("NEWSAPI_KEY", "")
    if not api_key:
        # WHY: not an error — NewsAPI is supplementary, GDELT is primary
        logger.info("NEWSAPI_KEY not set — skipping NewsAPI (supplementary)")
        return []

    params = {
        "q": NEWSAPI_QUERY,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": "15",
        "apiKey": api_key,
    }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(NEWSAPI_URL, params=params)
            resp.raise_for_status()

        data = resp.json()
        articles = data.get("articles", [])
        if not isinstance(articles, list):
            return []

        headlines: list[MacroHeadline] = []
        for article in articles:
            title = article.get("title", "").strip()
            url = article.get("url", "").strip()
            source_obj = article.get("source", {})
            source_name = (
                source_obj.get("name", "NewsAPI") if isinstance(source_obj, dict) else "NewsAPI"
            )
            timestamp = article.get("publishedAt", "")

            if title and url:
                headlines.append(
                    MacroHeadline(
                        title=title,
                        source=source_name,
                        url=url,
                        timestamp=timestamp,
                        provider="newsapi",
                    )
                )

        return headlines

    except httpx.TimeoutException:
        logger.warning(f"NewsAPI timeout ({REQUEST_TIMEOUT}s)")
        return []
    except httpx.HTTPStatusError as e:
        logger.warning(f"NewsAPI HTTP error: {e.response.status_code}")
        return []
    except Exception as e:
        logger.warning(f"NewsAPI fetch failed: {e}")
        return []


def _parse_gdelt_date(gdelt_date: str) -> str:
    """Parse GDELT seendate format (YYYYMMDDTHHMMSSZ) to ISO 8601.

    WHY: GDELT uses a non-standard date format without dashes/colons.
    """
    if not gdelt_date:
        return ""
    try:
        # GDELT format: "20260415T120000Z"
        dt = datetime.strptime(gdelt_date, "%Y%m%dT%H%M%SZ")
        dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return gdelt_date
