"""TradingView Ideas Collector (QO.34).

Fetches recent crypto trading ideas from TradingView's public RSS feed.
No API key required — uses the publicly available ideas feed.

Source: https://www.tradingview.com/feed/?sort=recent&stream=crypto
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime, timezone

import feedparser
import httpx

from cic_daily_report.core.logger import get_logger

logger = get_logger("tradingview_collector")

# WHY public RSS: TradingView has no official free API.
# The RSS feed is publicly available and returns recent crypto ideas.
FEED_URL = "https://www.tradingview.com/feed/?sort=recent&stream=crypto"
REQUEST_TIMEOUT = 30
MAX_IDEAS = 20  # spec: 20 most recent ideas


@dataclass
class TradingIdea:
    """A single trading idea from TradingView."""

    title: str
    author: str
    summary: str
    url: str
    published_date: str

    def to_dict(self) -> dict:
        """Convert to dict compatible with existing collector output format."""
        return {
            "title": self.title,
            "author": self.author,
            "summary": self.summary,
            "url": self.url,
            "published_date": self.published_date,
            "source": "TradingView",
            "collected_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        }


def _sanitize_text(text: str) -> str:
    """Remove HTML tags, decode entities, normalize whitespace."""
    # WHY: RSS summaries often contain HTML — strip before storage.
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


async def collect_tradingview_ideas() -> list[dict]:
    """Collect recent crypto trading ideas from TradingView RSS.

    Returns list of idea dicts. Returns empty list on any error
    (never breaks pipeline — spec requirement).
    """
    logger.info("Collecting TradingView crypto ideas from RSS feed")

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(FEED_URL, follow_redirects=True)
            response.raise_for_status()

        # WHY asyncio.to_thread not used: feedparser.parse() on a string is
        # CPU-light and fast enough to run inline for a single feed.
        parsed = feedparser.parse(response.text)

        ideas: list[TradingIdea] = []
        for entry in parsed.entries[:MAX_IDEAS]:
            title = _sanitize_text(entry.get("title", ""))
            url = entry.get("link", "").strip()
            author = entry.get("author", "").strip()
            summary = _sanitize_text(entry.get("summary", ""))[:500]
            published = entry.get("published", "")

            if title and url:
                ideas.append(
                    TradingIdea(
                        title=title,
                        author=author,
                        summary=summary,
                        url=url,
                        published_date=published,
                    )
                )

        logger.info(f"TradingView: {len(ideas)} ideas collected")
        return [idea.to_dict() for idea in ideas]

    except httpx.TimeoutException:
        logger.warning(f"TradingView RSS feed timeout ({REQUEST_TIMEOUT}s)")
        return []
    except httpx.HTTPStatusError as e:
        logger.warning(f"TradingView RSS HTTP error: {e.response.status_code}")
        return []
    except Exception as e:
        logger.warning(f"TradingView collector failed: {e}")
        return []
