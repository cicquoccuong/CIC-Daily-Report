"""CryptoPanic News & Sentiment collector (FR2, FR7)."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from cic_daily_report.core.logger import get_logger
from cic_daily_report.core.quota_manager import QuotaManager

logger = get_logger("cryptopanic")

API_BASE = "https://cryptopanic.com/api/developer/v2"
MAX_URLS_PER_RUN = 50
TRAFILATURA_TIMEOUT = 10  # seconds per URL


@dataclass
class CryptoPanicArticle:
    """News article from CryptoPanic with sentiment."""

    title: str
    url: str
    source_name: str
    published_date: str
    summary: str
    full_text: str
    panic_score: float
    votes_bullish: int
    votes_bearish: int
    currencies: list[str] | None = None  # coin codes from API (e.g. ["BTC","ETH"])
    news_type: str = "crypto"  # "crypto" or "macro" — classified from currencies field
    language: str = "en"
    og_image: str | None = None  # Open Graph image URL

    def to_row(self) -> list[str]:
        """Convert to Sheets row for TIN_TUC_THO tab."""
        collected_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        sentiment = self.panic_score if self.panic_score else ""
        return [
            "",  # ID
            self.title,
            self.url,
            f"CryptoPanic:{self.source_name}",
            collected_at,
            self.language,
            self.summary or self.full_text[:500],
            "",  # event_type
            "",  # coin_symbol
            str(sentiment),  # sentiment_score
            "",  # action_category
        ]


async def collect_cryptopanic(
    api_key: str | None = None,
    extract_fulltext: bool = True,
    quota_manager: QuotaManager | None = None,
) -> list[CryptoPanicArticle]:
    """Collect news + sentiment from CryptoPanic API.

    Respects rate limit: 5 req/min with 1s delay between calls.
    """
    api_key = api_key or os.getenv("CRYPTOPANIC_API_KEY", "")
    if not api_key:
        logger.error("CRYPTOPANIC_API_KEY not set — skipping CryptoPanic collection")
        return []

    qm = quota_manager or QuotaManager()
    if not qm.can_call("cryptopanic"):
        logger.warning("CryptoPanic daily quota reached — skipping collection")
        return []

    logger.info("Collecting from CryptoPanic API")
    await qm.wait_for_rate_limit("cryptopanic")

    try:
        articles = await _fetch_posts(api_key)
        qm.track("cryptopanic")
        logger.info(f"CryptoPanic: {len(articles)} articles fetched")

        if extract_fulltext and articles:
            await _extract_fulltext(articles[:MAX_URLS_PER_RUN])

        return articles

    except Exception as e:
        logger.error(f"CryptoPanic collection failed: {e}")
        return []


async def _fetch_posts(api_key: str) -> list[CryptoPanicArticle]:
    """Fetch posts from CryptoPanic API."""
    url = f"{API_BASE}/posts/"
    params = {
        "auth_token": api_key,
        "filter": "hot",
        "public": "true",
        "kind": "news",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()

    data = response.json()
    articles = []

    for post in data.get("results", [])[:30]:
        votes = post.get("votes", {})
        # Extract currency codes from API response
        coin_codes = [c.get("code", "") for c in post.get("currencies", []) if c.get("code")]
        articles.append(
            CryptoPanicArticle(
                title=post.get("title", ""),
                url=post.get("url", ""),
                source_name=post.get("source", {}).get("title", "unknown"),
                published_date=post.get("published_at", ""),
                summary="",
                full_text="",
                panic_score=_calc_panic_score(votes),
                votes_bullish=votes.get("positive", 0),
                votes_bearish=votes.get("negative", 0),
                currencies=coin_codes or None,
                news_type="crypto" if coin_codes else _classify_news(post.get("title", "")),
            )
        )

    return articles


# Keywords indicating macro/geopolitical news
_MACRO_KEYWORDS = (
    "fed ",
    "federal reserve",
    "interest rate",
    "inflation",
    "gdp",
    "tariff",
    "dxy",
    "gold",
    "oil",
    "crude",
    "treasury",
    "geopolit",
    "war",
    "sanction",
    "election",
    "recession",
    "cpi",
    "ppi",
    "fomc",
    "ecb",
    "boj",
    "pboc",
    "stock market",
    "s&p",
    "nasdaq",
    "dow jones",
    "usd",
    "eur",
    "jpy",
    "yuan",
)


def _classify_news(title: str) -> str:
    """Classify news as 'crypto' or 'macro' based on title keywords."""
    lower = title.lower()
    for kw in _MACRO_KEYWORDS:
        if kw in lower:
            return "macro"
    return "crypto"


def _calc_panic_score(votes: dict[str, Any]) -> float:
    """Calculate sentiment score from vote counts.

    NOTE: Despite the field name 'panic_score', this is a SENTIMENT score:
      0 = extreme bearish, 100 = extreme bullish, 50 = neutral.
    This is DIFFERENT from event_detector's panic score which measures
    negative/toxic votes for breaking news severity classification.
    """
    bullish = votes.get("positive", 0)
    bearish = votes.get("negative", 0)
    total = bullish + bearish
    if total == 0:
        return 50.0  # neutral
    # 0 = extreme bearish, 100 = extreme bullish
    return round(bullish / total * 100, 1)


async def _extract_fulltext(articles: list[CryptoPanicArticle]) -> None:
    """Extract full text from article URLs using trafilatura."""
    try:
        import trafilatura
    except ImportError:
        logger.warning("trafilatura not installed — skipping full-text extraction")
        return

    async def _extract_one(article: CryptoPanicArticle) -> None:
        try:
            async with httpx.AsyncClient(timeout=TRAFILATURA_TIMEOUT) as client:
                resp = await client.get(article.url, follow_redirects=True)
            text = await asyncio.to_thread(trafilatura.extract, resp.text, include_comments=False)
            if text:
                article.full_text = text[:2000]
                if not article.summary:
                    article.summary = text[:500]
            # Extract og:image metadata
            metadata = await asyncio.to_thread(trafilatura.extract_metadata, resp.text)
            if metadata and metadata.image:
                article.og_image = metadata.image
        except Exception as e:
            logger.debug(f"Full-text extraction failed for {article.url}: {e}")

    tasks = [_extract_one(a) for a in articles]
    await asyncio.gather(*tasks, return_exceptions=True)
    extracted = sum(1 for a in articles if a.full_text)
    logger.info(f"Full-text extracted: {extracted}/{len(articles)}")
