"""RSS-based breaking event scoring + SambaNova LLM Impact Scoring.

Module responsibilities:
1. RSS scoring: When CryptoPanic API is unavailable, scores RSS articles
   using the main LLM chain to identify breaking-worthy news.
2. SambaNova Impact Scoring (QO.18): Separate LLM scoring via SambaNova
   (Meta-Llama-3.3-70B-Instruct) to rate event importance 1-10 for
   Vietnamese crypto investors. Runs BETWEEN detection and delivery.

SambaNova is isolated from the main LLM chain (Gemini/Groq/Cerebras)
to avoid quota competition.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone

import httpx

from cic_daily_report.breaking.event_detector import (
    DEFAULT_KEYWORD_TRIGGERS,
    DEFAULT_PANIC_THRESHOLD,
    BreakingEvent,
    _match_keywords,
)
from cic_daily_report.collectors.rss_collector import NewsArticle
from cic_daily_report.core.logger import get_logger

logger = get_logger("llm_scorer")

# ---------------------------------------------------------------------------
# QO.18: SambaNova Impact Scoring constants
# ---------------------------------------------------------------------------

# WHY SambaNova: Free tier (20 RPD), OpenAI-compatible API, separate from
# main LLM chain so scoring doesn't consume generation quota.
SAMBANOVA_API_BASE = "https://api.sambanova.ai/v1"
SAMBANOVA_MODEL = "Meta-Llama-3.3-70B-Instruct"
SAMBANOVA_TIMEOUT = 15  # seconds — fast timeout for scoring (not generation)
SAMBANOVA_MAX_RPD = 20  # Free tier rate limit: 20 requests per day

# QO.18: Impact score thresholds
# WHY these cutoffs: <4 = noise (sports, irrelevant), 4-6 = worth grouping
# but not urgent enough alone, >=7 = high-impact for VN crypto investors.
IMPACT_SKIP_THRESHOLD = 4  # Score < 4 → skip entirely
IMPACT_DIGEST_THRESHOLD = 7  # Score 4-6 → digest, Score >= 7 → send individually

IMPACT_SCORING_PROMPT = (
    "Tin này quan trọng cỡ nào cho nhà đầu tư crypto Việt Nam? "
    "Chấm điểm 1-10.\n\n"
    "Tiêu đề: {title}\n"
    "Tóm tắt: {summary}\n\n"
    "Trả lời CHỈ một số nguyên từ 1 đến 10, KHÔNG giải thích."
)

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


# ---------------------------------------------------------------------------
# QO.18: SambaNova Impact Scoring
# ---------------------------------------------------------------------------

# WHY file-based persistence: Module-level counter resets each process.
# With 4 pipeline runs/day (daily + 3h breaking), that allows 80 attempts
# against a 20 RPD quota. A JSON sidecar file persists the count across runs.
_sambanova_calls_today = 0

# WHY: GITHUB_WORKSPACE gives the repo root in CI; tempdir for local dev.
_USAGE_FILE_NAME = "sambanova_usage.json"


def _get_usage_file_path() -> str:
    """Return path to SambaNova daily usage JSON file.

    WHY GITHUB_WORKSPACE first: In GitHub Actions, this is the repo root
    and survives across job steps. Falls back to system temp dir for local dev.
    """
    import tempfile

    base = os.getenv("GITHUB_WORKSPACE", tempfile.gettempdir())
    return os.path.join(base, _USAGE_FILE_NAME)


def _load_daily_count() -> int:
    """Load today's SambaNova call count from the usage file.

    Returns 0 if file doesn't exist, is unreadable, or date is stale.
    WHY: Ensures count persists across process restarts within the same day.
    """
    path = _get_usage_file_path()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("date") == today:
            return int(data.get("calls", 0))
    except (FileNotFoundError, json.JSONDecodeError, ValueError, OSError):
        pass
    return 0


def _save_daily_count(count: int) -> None:
    """Persist current day's SambaNova call count to the usage file.

    WHY: Write after each successful API call so the count survives
    process restarts (GitHub Actions breaking pipeline runs every 3h).
    """
    path = _get_usage_file_path()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"date": today, "calls": count}, f)
    except OSError as e:
        logger.warning(f"Failed to persist SambaNova usage: {e}")


async def score_event_impact(
    event: BreakingEvent,
) -> int:
    """Score a single event's importance for VN crypto investors (1-10).

    Uses SambaNova API (Meta-Llama-3.3-70B-Instruct) with OpenAI-compatible
    endpoint. Completely separate from the main LLM chain.

    Returns:
        Integer score 1-10. Returns 10 on failure (graceful fallback —
        let event pass through if scoring is unavailable).
    """
    global _sambanova_calls_today  # noqa: PLW0603 — WHY: simple counter, not shared state

    # WHY: Load persisted count on first call so we track across process restarts
    if _sambanova_calls_today == 0:
        _sambanova_calls_today = _load_daily_count()

    api_key = os.getenv("SAMBANOVA_API_KEY", "")
    if not api_key:
        logger.debug("SAMBANOVA_API_KEY not set — skipping impact scoring (pass-through)")
        return 10  # WHY 10: no key = let all events through (graceful degradation)

    if _sambanova_calls_today >= SAMBANOVA_MAX_RPD:
        logger.warning(
            f"SambaNova daily limit reached ({_sambanova_calls_today}/{SAMBANOVA_MAX_RPD}) "
            "— skipping impact scoring (pass-through)"
        )
        return 10

    summary = ""
    if event.raw_data:
        summary = event.raw_data.get("summary", "")[:300]

    prompt = IMPACT_SCORING_PROMPT.format(title=event.title, summary=summary or "N/A")

    try:
        score = await _call_sambanova(api_key, prompt)
        _sambanova_calls_today += 1
        # WHY: Persist after each call so count survives process restart
        _save_daily_count(_sambanova_calls_today)
        logger.info(
            f"QO.18: Impact score={score} for '{event.title[:60]}' "
            f"(calls: {_sambanova_calls_today}/{SAMBANOVA_MAX_RPD})"
        )
        return score
    except Exception as e:
        logger.warning(f"SambaNova scoring failed for '{event.title[:50]}': {e}")
        return 10  # WHY 10: scoring failure = let event pass through


async def _call_sambanova(api_key: str, prompt: str) -> int:
    """Call SambaNova OpenAI-compatible API and extract integer score.

    Returns integer 1-10. Raises on HTTP/network errors.
    """
    url = f"{SAMBANOVA_API_BASE}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": SAMBANOVA_MODEL,
        "messages": [
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 10,
        "temperature": 0.1,
    }

    async with httpx.AsyncClient(timeout=SAMBANOVA_TIMEOUT) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()

    data = resp.json()
    text = data["choices"][0]["message"]["content"].strip()
    return _parse_impact_score(text)


def _parse_impact_score(text: str) -> int:
    """Extract integer score 1-10 from LLM response text.

    Handles various response formats: "7", "Score: 7", "7/10", etc.
    Returns 10 if parsing fails (graceful fallback — let event through).
    """
    # Try to find a standalone integer 1-10
    match = re.search(r"\b(\d{1,2})\b", text)
    if match:
        score = int(match.group(1))
        return max(1, min(10, score))  # Clamp to 1-10
    logger.warning(f"Could not parse impact score from: '{text}' — defaulting to 10")
    return 10


def classify_by_impact(score: int) -> str:
    """Classify event action based on impact score (QO.18).

    Returns:
        "skip" — Score < 4, not important enough
        "digest" — Score 4-6, group with others
        "send" — Score >= 7, send individually
    """
    if score < IMPACT_SKIP_THRESHOLD:
        return "skip"
    if score < IMPACT_DIGEST_THRESHOLD:
        return "digest"
    return "send"


def reset_sambanova_counter() -> None:
    """Reset the daily SambaNova call counter (both in-memory and on disk).

    Called at the start of each pipeline day or for testing.
    """
    global _sambanova_calls_today  # noqa: PLW0603
    _sambanova_calls_today = 0
    _save_daily_count(0)


def get_sambanova_calls_today() -> int:
    """Get current SambaNova call count (for logging/testing)."""
    return _sambanova_calls_today
