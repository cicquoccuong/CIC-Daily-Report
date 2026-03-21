"""Breaking Event Detector (Story 5.1) — CryptoPanic event detection.

Queries CryptoPanic API for recent crypto news, evaluates each item
against panic_score thresholds and keyword triggers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from cic_daily_report.core.cache import get_cached, set_cached
from cic_daily_report.core.error_handler import CollectorError, ConfigError
from cic_daily_report.core.logger import get_logger
from cic_daily_report.core.quota_manager import QuotaManager

logger = get_logger("event_detector")

CRYPTOPANIC_API_URL = "https://cryptopanic.com/api/v1/posts/"
CACHE_KEY = "cryptopanic_breaking"
CACHE_MAX_AGE = 7200  # 2 hours — breaking runs every 3h, so cache protects overlaps/retries

# v0.29.0: Keywords split into two tiers for context-aware triggering.
# ALWAYS_TRIGGER: Crypto-specific terms — trigger regardless of context.
# CONTEXT_REQUIRED: Generic terms — only trigger when title also contains a crypto keyword.
ALWAYS_TRIGGER_KEYWORDS = [
    "hack",
    "exploit",
    "rug pull",
    "delisting",
    "bankrupt",
]

CONTEXT_REQUIRED_KEYWORDS = [
    "crash",
    "collapse",
    "SEC",
    "ban",
    "emergency",
]

# Combined list for backward compat (DetectionConfig default)
DEFAULT_KEYWORD_TRIGGERS = ALWAYS_TRIGGER_KEYWORDS + CONTEXT_REQUIRED_KEYWORDS

DEFAULT_PANIC_THRESHOLD = 70

# Crypto context words — if title contains at least one, CONTEXT_REQUIRED keywords fire.
# Reuses severity_classifier._CRYPTO_RELEVANCE_KEYWORDS concept but minimal set here.
_CRYPTO_CONTEXT_WORDS = {
    "bitcoin",
    "btc",
    "ethereum",
    "eth",
    "crypto",
    "blockchain",
    "solana",
    "sol",
    "bnb",
    "xrp",
    "cardano",
    "ada",
    "doge",
    "altcoin",
    "memecoin",
    "token",
    "coin",
    "nft",
    "web3",
    "stablecoin",
    "usdt",
    "usdc",
    "defi",
    "binance",
    "coinbase",
    "kraken",
    "okx",
    "bybit",
    "exchange",
    "mining",
    "miner",
    "wallet",
    "etf",
    "ripple",
    "dogecoin",
    "avalanche",
    "polkadot",
    "chainlink",
    "litecoin",
    "uniswap",
    "toncoin",
    "stellar",
    "aptos",
    "arbitrum",
    "optimism",
    "sui",
    "near",
    "tron",
    "hedera",
    "filecoin",
}


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
    image_url: str | None = None  # FR25: og:image from source article

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
    quota_manager: QuotaManager | None = None,
) -> list[BreakingEvent]:
    """Detect breaking events from CryptoPanic API.

    Args:
        config: Detection config (thresholds, keywords). Defaults to sensible defaults.
        api_key: CryptoPanic API key. Falls back to env var.
        quota_manager: Shared quota tracker for rate limiting.

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
    qm = quota_manager or QuotaManager()

    if not qm.can_call("cryptopanic"):
        logger.warning("CryptoPanic daily quota reached — skipping breaking detection")
        return []

    # Try cache first — avoid redundant API calls between runs
    cached = get_cached(CACHE_KEY, max_age_seconds=CACHE_MAX_AGE)
    if cached is not None:
        raw_items = cached[: cfg.max_results]
    else:
        await qm.wait_for_rate_limit("cryptopanic")
        try:
            raw_items = await _fetch_cryptopanic(key, cfg.max_results)
            qm.track("cryptopanic")
            set_cached(CACHE_KEY, raw_items)
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
            # FR25: extract image URL from CryptoPanic metadata
            metadata = item.get("metadata", {}) or {}
            image_url = metadata.get("image") or None

            events.append(
                BreakingEvent(
                    title=title,
                    source=source_name,
                    url=url,
                    panic_score=panic_score,
                    matched_keywords=matched,
                    raw_data=item,
                    image_url=image_url,
                )
            )

    return events


def _calculate_panic_score(votes: dict) -> int:
    """Calculate BREAKING panic score from CryptoPanic votes.

    This is a PANIC score (higher = more panic-worthy):
      negative + toxic*2 + disliked, normalized 0-100.

    NOTE: This is DIFFERENT from cryptopanic_client._calc_panic_score()
    which calculates a SENTIMENT score (0=bearish, 100=bullish).
    The two scores measure opposite things and should NOT be compared.
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
    """Check if title contains any keyword triggers (case-insensitive).

    v0.29.0: Context-aware — CONTEXT_REQUIRED keywords only match when
    the title also contains a crypto-related word (prevents "plane crash"
    triggering breaking alerts for a crypto community).
    """
    title_lower = title.lower()
    has_crypto_context = any(w in title_lower for w in _CRYPTO_CONTEXT_WORDS)

    matched: list[str] = []
    for kw in keywords:
        kw_lower = kw.lower()
        if kw_lower not in title_lower:
            continue
        # Always-trigger keywords fire regardless of context
        if kw_lower in {k.lower() for k in ALWAYS_TRIGGER_KEYWORDS}:
            matched.append(kw)
        # Context-required keywords need a crypto word in the same title
        elif has_crypto_context:
            matched.append(kw)
        # else: skip — generic keyword without crypto context
    return matched
