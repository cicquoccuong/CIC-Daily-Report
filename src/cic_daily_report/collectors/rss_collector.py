"""RSS News Collector — parallel fetch from 15+ feeds (FR1, QĐ5).

Enhanced with research feeds layer (Messari, Glassnode, CoinMetrics, Galaxy Digital)
and og:image extraction for research articles.
"""

from __future__ import annotations

import asyncio
import html
import re
from dataclasses import dataclass
from datetime import datetime, timezone

import feedparser
import httpx

from cic_daily_report.core.error_handler import CollectorError
from cic_daily_report.core.logger import get_logger

logger = get_logger("rss_collector")

FEED_TIMEOUT = 30  # seconds per feed
_CONCURRENCY_LIMIT = asyncio.Semaphore(25)  # max concurrent HTTP requests


def _sanitize_text(text: str) -> str:
    """Remove non-printable chars, decode HTML entities, normalize whitespace."""
    text = html.unescape(text)
    # Remove control chars and non-standard Unicode but keep basic Latin + common scripts
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


@dataclass
class FeedConfig:
    """RSS feed configuration."""

    url: str
    source_name: str
    language: str  # "vi" or "en"
    enabled: bool = True
    source_type: str = "news"  # "news" or "research"


# Default feed list — can be extended via config
DEFAULT_FEEDS: list[FeedConfig] = [
    # Vietnamese
    FeedConfig("https://vneconomy.vn/tai-chinh.rss", "VnEconomy", "vi"),
    FeedConfig("https://cafef.vn/thi-truong.rss", "CafeF", "vi"),
    FeedConfig("https://coin68.com/feed/", "Coin68", "vi"),
    FeedConfig("https://tapchibitcoin.io/feed", "TapChiBitcoin", "vi"),
    FeedConfig("https://vn.beincrypto.com/feed/", "BeInCrypto_VN", "vi"),
    # English
    FeedConfig("https://cointelegraph.com/rss", "CoinTelegraph", "en"),
    FeedConfig("https://coindesk.com/arc/outboundfeeds/rss/", "CoinDesk", "en"),
    FeedConfig("https://decrypt.co/feed", "Decrypt", "en"),
    FeedConfig("https://theblock.co/rss.xml", "TheBlock", "en"),
    FeedConfig("https://cryptoslate.com/feed/", "CryptoSlate", "en"),
    FeedConfig("https://u.today/rss", "UToday", "en"),
    FeedConfig("https://ambcrypto.com/feed/", "AMBCrypto", "en"),
    FeedConfig("https://newsbtc.com/feed/", "NewsBTC", "en"),
    FeedConfig("https://www.ccn.com/feed/", "CCN", "en"),
    FeedConfig("https://blockworks.co/feed/", "Blockworks", "en"),
    FeedConfig("https://dlnews.com/feed/", "DLNews", "en"),
    FeedConfig("https://feeds.reuters.com/reuters/businessNews", "Reuters", "en"),
    FeedConfig("https://banklesshq.substack.com/feed/", "Bankless", "en"),
    # Research feeds — deep analysis, typically weekly (source_type="research")
    FeedConfig(
        "https://messari.io/rss", "Messari", "en", source_type="research",
    ),
    FeedConfig(
        "https://insights.glassnode.com/rss/", "Glassnode_Insights", "en",
        source_type="research",
    ),
    FeedConfig(
        "https://coinmetrics.substack.com/feed", "CoinMetrics", "en",
        source_type="research",
    ),
    FeedConfig(
        "https://www.galaxy.com/insights/research/feed.xml", "Galaxy_Digital", "en",
        source_type="research",
    ),
]


@dataclass
class NewsArticle:
    """Parsed news article from RSS."""

    title: str
    url: str
    source_name: str
    published_date: str
    summary: str
    language: str
    source_type: str = "news"  # "news" or "research"
    og_image: str | None = None  # Open Graph image URL (research feeds)
    full_text: str = ""  # Full article text (research feeds only, via trafilatura)

    def to_row(self) -> list[str]:
        """Convert to Sheets row for TIN_TUC_THO tab."""
        collected_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        return [
            "",  # ID (auto)
            self.title,
            self.url,
            self.source_name,
            collected_at,
            self.language,
            self.summary,
            self.source_type,  # event_type column — stores source_type
            "",  # coin_symbol
            "",  # sentiment_score
            "",  # action_category
        ]


async def collect_rss(
    feeds: list[FeedConfig] | None = None,
) -> list[NewsArticle]:
    """Collect news from RSS feeds in parallel.

    Each feed has independent timeout. One feed failing does not block others (NFR16).
    Uses Semaphore to limit concurrent HTTP requests.
    Research feeds get additional trafilatura enrichment (full text + og:image).
    """
    feeds = feeds or [f for f in DEFAULT_FEEDS if f.enabled]
    research_count = sum(1 for f in feeds if f.source_type == "research")
    logger.info(
        f"Collecting from {len(feeds)} RSS feeds ({research_count} research)"
    )

    tasks = [_fetch_feed(feed) for feed in feeds]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    articles: list[NewsArticle] = []
    succeeded = 0
    failed = 0

    for feed, result in zip(feeds, results):
        if isinstance(result, Exception):
            logger.warning(f"Feed '{feed.source_name}' failed: {result}")
            failed += 1
        else:
            articles.extend(result)
            succeeded += 1

    # Enrich research articles with full text + og:image via trafilatura
    research_articles = [a for a in articles if a.source_type == "research"]
    if research_articles:
        await _enrich_research_articles(research_articles)

    logger.info(
        f"RSS collection done: {succeeded} feeds OK, {failed} failed, "
        f"{len(articles)} articles total"
    )
    return articles


async def _fetch_feed(feed: FeedConfig) -> list[NewsArticle]:
    """Fetch and parse a single RSS feed."""
    try:
        async with _CONCURRENCY_LIMIT:
            async with httpx.AsyncClient(timeout=FEED_TIMEOUT) as client:
                response = await client.get(feed.url, follow_redirects=True)
                response.raise_for_status()

        parsed = await asyncio.to_thread(feedparser.parse, response.text)
        articles = []

        for entry in parsed.entries[:20]:  # max 20 per feed
            title = _sanitize_text(entry.get("title", ""))
            url = entry.get("link", "").strip()
            summary = _sanitize_text(entry.get("summary", ""))[:500]
            published = entry.get("published", "")

            # Extract RSS media image as fallback for og:image
            media_image = _extract_rss_image(entry)

            if title and url:
                articles.append(
                    NewsArticle(
                        title=title,
                        url=url,
                        source_name=feed.source_name,
                        published_date=published,
                        summary=summary,
                        language=feed.language,
                        source_type=feed.source_type,
                        og_image=media_image,  # RSS media fallback; trafilatura overwrites later
                    )
                )

        return articles

    except httpx.TimeoutException:
        raise CollectorError(
            f"Timeout fetching {feed.source_name} ({FEED_TIMEOUT}s)",
            source="rss_collector",
        )
    except Exception as e:
        raise CollectorError(
            f"Error fetching {feed.source_name}: {e}",
            source="rss_collector",
        ) from e


def _extract_rss_image(entry: dict) -> str | None:
    """Extract image URL from RSS media tags (fallback for og:image)."""
    # Try media:content
    media = entry.get("media_content", [])
    if media and isinstance(media, list):
        url = media[0].get("url", "")
        if url:
            return url
    # Try enclosure
    for link in entry.get("links", []):
        if link.get("type", "").startswith("image/"):
            return link.get("href", "") or None
    return None


async def _enrich_research_articles(articles: list[NewsArticle]) -> None:
    """Enrich research articles with full text + og:image via trafilatura."""
    try:
        import trafilatura
    except ImportError:
        logger.warning("trafilatura not installed — skipping research enrichment")
        return

    async def _enrich_one(article: NewsArticle) -> None:
        try:
            async with _CONCURRENCY_LIMIT:
                async with httpx.AsyncClient(timeout=FEED_TIMEOUT) as client:
                    resp = await client.get(article.url, follow_redirects=True)

            # Extract full text
            text = await asyncio.to_thread(
                trafilatura.extract, resp.text, include_comments=False
            )
            if text:
                article.full_text = text[:2000]
                if not article.summary or len(article.summary) < 50:
                    article.summary = text[:500]

            # Extract og:image metadata (overwrites RSS media fallback)
            metadata = await asyncio.to_thread(trafilatura.extract_metadata, resp.text)
            if metadata and metadata.image:
                article.og_image = metadata.image

        except Exception as e:
            logger.debug(f"Research enrichment failed for {article.url}: {e}")

    tasks = [_enrich_one(a) for a in articles]
    await asyncio.gather(*tasks, return_exceptions=True)
    enriched = sum(1 for a in articles if a.full_text)
    images = sum(1 for a in articles if a.og_image)
    logger.info(
        f"Research enrichment: {enriched}/{len(articles)} text, "
        f"{images}/{len(articles)} images"
    )
