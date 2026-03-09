"""Breaking Event Detector (Story 5.1) — CryptoPanic event detection.

Queries CryptoPanic API for recent crypto news, evaluates each item
against panic_score thresholds and keyword triggers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from cic_daily_report.core.error_handler import CollectorError, ConfigError
from cic_daily_report.core.logger import get_logger

logger = get_logger("event_detector")

CRYPTOPANIC_API_URL = "https://cryptopanic.com/api/v1/posts/"

# Default keyword triggers — operator can add more via CAU_HINH
DEFAULT_KEYWORD_TRIGGERS = [
    "hack",
    "exploit",
    "SEC",
    "ban",
    "crash",
    "collapse",
    "bankrupt",
    "rug pull",
    "delisting",
    "emergency",
]

DEFAULT_PANIC_THRESHOLD = 70


@dataclass
class BreakingEvent:
    """A detected breaking event from CryptoPanic."""

    title: str
    source: str
    url: str
    panic_score: int
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    matched_keywords: list[str] = field(default_factory=list)
    raw_data: dict = field(default_factory=dict)

    @property
    def trigger_reason(self) -> str:
        """Why this event was flagged."""
        reasons = []
        if self.panic_score >= DEFAULT_PANIC_THRESHOLD:
            reasons.append(f"panic_score={self.panic_score}")
        if self.matched_keywords:
            reasons.append(f"keywords={','.join(self.matched_keywords)}")
        return " + ".join(reasons) or "manual"


@dataclass
class DetectionConfig:
    """Configuration for event detection, loaded from CAU_HINH."""

    panic_threshold: int = DEFAULT_PANIC_THRESHOLD
    keyword_triggers: list[str] = field(default_factory=lambda: list(DEFAULT_KEYWORD_TRIGGERS))
    max_results: int = 50


async def detect_breaking_events(
    config: DetectionConfig | None = None,
    api_key: str | None = None,
) -> list[BreakingEvent]:
    """Detect breaking events from CryptoPanic API.

    Args:
        config: Detection config (thresholds, keywords). Defaults to sensible defaults.
        api_key: CryptoPanic API key. Falls back to env var.

    Returns:
        List of detected breaking events.

    Raises:
        ConfigError: If API key is missing.
        CollectorError: If API call fails.
    """
    key = api_key or os.getenv("CRYPTOPANIC_API_KEY", "")
    if not key:
        raise ConfigError(
            "CRYPTOPANIC_API_KEY missing — breaking detection disabled",
            source="event_detector",
        )

    cfg = config or DetectionConfig()

    try:
        raw_items = await _fetch_cryptopanic(key, cfg.max_results)
    except Exception as e:
        raise CollectorError(
            f"CryptoPanic API error: {e}",
            source="event_detector",
        ) from e

    events = _evaluate_items(raw_items, cfg)
    logger.info(f"Detected {len(events)} breaking events from {len(raw_items)} items")
    return events


async def _fetch_cryptopanic(api_key: str, max_results: int) -> list[dict]:
    """Fetch recent posts from CryptoPanic API."""
    params = {
        "auth_token": api_key,
        "kind": "news",
        "filter": "hot",
        "public": "true",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(CRYPTOPANIC_API_URL, params=params)
        resp.raise_for_status()

    data = resp.json()
    results = data.get("results", [])
    return results[:max_results]


def _evaluate_items(
    items: list[dict],
    config: DetectionConfig,
) -> list[BreakingEvent]:
    """Evaluate each item against thresholds and keyword triggers."""
    events: list[BreakingEvent] = []

    for item in items:
        title = item.get("title", "")
        source = item.get("source", {})
        source_name = source.get("title", "unknown") if isinstance(source, dict) else str(source)
        url = item.get("url", "")
        votes = item.get("votes", {})
        panic_score = _calculate_panic_score(votes)

        # Check panic_score threshold
        score_triggered = panic_score >= config.panic_threshold

        # Check keyword triggers
        matched = _match_keywords(title, config.keyword_triggers)

        if score_triggered or matched:
            events.append(
                BreakingEvent(
                    title=title,
                    source=source_name,
                    url=url,
                    panic_score=panic_score,
                    matched_keywords=matched,
                    raw_data=item,
                )
            )

    return events


def _calculate_panic_score(votes: dict) -> int:
    """Calculate panic score from CryptoPanic votes.

    Score = negative + toxic + disliked, normalized to 0-100.
    Higher = more panic-worthy.
    """
    if not votes:
        return 0

    negative = votes.get("negative", 0)
    toxic = votes.get("toxic", 0)
    disliked = votes.get("disliked", 0)
    positive = votes.get("positive", 0)
    liked = votes.get("liked", 0)
    important = votes.get("important", 0)

    panic_raw = negative + toxic * 2 + disliked
    calm_raw = positive + liked + important

    total = panic_raw + calm_raw
    if total == 0:
        return 0

    return min(100, int((panic_raw / total) * 100))


def _match_keywords(title: str, keywords: list[str]) -> list[str]:
    """Check if title contains any keyword triggers (case-insensitive)."""
    title_lower = title.lower()
    return [kw for kw in keywords if kw.lower() in title_lower]
