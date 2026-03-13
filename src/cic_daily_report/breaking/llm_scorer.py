"""RSS-based breaking event scoring via LLM (CryptoPanic fallback).

When CryptoPanic API is unavailable (quota exhausted, API error, or no key),
this module scores RSS articles using LLM to identify breaking-worthy news.
Single batch LLM call for efficiency.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from cic_daily_report.breaking.event_detector import (
    DEFAULT_KEYWORD_TRIGGERS,
    DEFAULT_PANIC_THRESHOLD,
    BreakingEvent,
    _match_keywords,
)
from cic_daily_report.collectors.rss_collector import NewsArticle
from cic_daily_report.core.logger import get_logger

logger = get_logger("llm_scorer")

MAX_BATCH_SIZE = 20
MAX_AGE_HOURS = 6

SCORING_SYSTEM_PROMPT = (
    "You are a breaking news detection system for a crypto asset community."
    " Reply ONLY with a JSON array, NO other text."
)

SCORING_PROMPT_TEMPLATE = """\
Score the URGENCY (0-100) of each news item below:
- 80-100: Extremely urgent (hack, exploit, exchange collapse, regulatory ban, crash >10%)
- 60-79: Urgent (SEC action, delisting, major security breach, sharp volatility)
- 40-59: Notable (policy change, major partnership)
- 0-39: Normal (no alert needed)

NEWS:
{articles_text}

Reply with ONLY a JSON array (no markdown, no explanation):
[{{"index": 0, "score": 85}}, {{"index": 1, "score": 30}}]"""


async def score_rss_articles(
    articles: list[NewsArticle],
    llm,
    threshold: int = DEFAULT_PANIC_THRESHOLD,
    keyword_triggers: list[str] | None = None,
) -> list[BreakingEvent]:
    """Score RSS articles using LLM to identify breaking-worthy news.

    Args:
        articles: RSS articles to evaluate.
        llm: LLMAdapter instance for scoring.
        threshold: Minimum score to consider as breaking (default 70).
        keyword_triggers: Keywords that auto-trigger breaking status.

    Returns:
        List of BreakingEvent for articles above threshold or matching keywords.
    """
    keywords = keyword_triggers or list(DEFAULT_KEYWORD_TRIGGERS)

    recent = _filter_recent_articles(articles)
    if not recent:
        logger.info("No recent RSS articles to score")
        return []

    # Pre-filter: keyword match (no LLM needed)
    keyword_events: list[BreakingEvent] = []
    remaining: list[NewsArticle] = []
    for article in recent:
        matched = _match_keywords(article.title, keywords)
        if matched:
            keyword_events.append(_article_to_event(article, score=75, matched_keywords=matched))
        else:
            remaining.append(article)

    # Batch LLM scoring for remaining articles
    llm_events: list[BreakingEvent] = []
    if remaining:
        batch = remaining[:MAX_BATCH_SIZE]
        scores = await _batch_score(batch, llm)
        for article, score in zip(batch, scores):
            if score >= threshold:
                llm_events.append(_article_to_event(article, score=score))

    events = keyword_events + llm_events
    logger.info(
        f"RSS scoring: {len(recent)} articles -> "
        f"{len(keyword_events)} keyword + {len(llm_events)} LLM = "
        f"{len(events)} breaking events"
    )
    return events


def _filter_recent_articles(
    articles: list[NewsArticle],
) -> list[NewsArticle]:
    """Filter articles published within MAX_AGE_HOURS."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)
    recent: list[NewsArticle] = []
    for article in articles:
        pub_dt = _parse_date(article.published_date)
        if pub_dt is None or pub_dt >= cutoff:
            recent.append(article)
    return recent


def _parse_date(date_str: str) -> datetime | None:
    """Parse RSS date string to datetime. Returns None if unparseable."""
    if not date_str:
        return None
    try:
        from email.utils import parsedate_to_datetime

        return parsedate_to_datetime(date_str)
    except Exception:
        pass
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except Exception:
        return None


async def _batch_score(
    articles: list[NewsArticle],
    llm,
) -> list[int]:
    """Send batch of articles to LLM for importance scoring.

    Returns list of scores (0-100), one per article.
    Falls back to 0 for all articles if LLM fails.
    """
    articles_text = "\n".join(
        f"[{i}] {a.title} ({a.source_name}): {a.summary[:200]}" for i, a in enumerate(articles)
    )

    prompt = SCORING_PROMPT_TEMPLATE.format(articles_text=articles_text)

    try:
        response = await llm.generate(
            prompt=prompt,
            system_prompt=SCORING_SYSTEM_PROMPT,
            max_tokens=512,
            temperature=0.2,
        )
        return _parse_scores(response.text, len(articles))
    except Exception as e:
        logger.warning(f"LLM scoring failed: {e}")
        return [0] * len(articles)


def _parse_scores(llm_output: str, expected_count: int) -> list[int]:
    """Parse LLM JSON output into list of scores.

    Handles: raw JSON, markdown code blocks, extra text around JSON.
    Returns list of 0s if parsing fails.
    """
    json_match = re.search(r"\[.*?\]", llm_output, re.DOTALL)
    if not json_match:
        logger.warning("Could not find JSON array in LLM scoring output")
        return [0] * expected_count

    try:
        data = json.loads(json_match.group())
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM scoring JSON")
        return [0] * expected_count

    scores = [0] * expected_count
    for item in data:
        if not isinstance(item, dict):
            continue
        idx = item.get("index", -1)
        score = item.get("score", 0)
        if 0 <= idx < expected_count:
            scores[idx] = max(0, min(100, int(score)))

    return scores


def _article_to_event(
    article: NewsArticle,
    score: int,
    matched_keywords: list[str] | None = None,
) -> BreakingEvent:
    """Convert a NewsArticle to a BreakingEvent."""
    return BreakingEvent(
        title=article.title,
        source=article.source_name,
        url=article.url,
        panic_score=score,
        matched_keywords=matched_keywords or [],
        raw_data={
            "source_type": "rss_fallback",
            "summary": article.summary[:500],
            "language": article.language,
        },
    )
