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

# v0.32.0: Migrated from v1 to v2 — consistent with cryptopanic_client.py
CRYPTOPANIC_API_URL = "https://cryptopanic.com/api/developer/v2/posts/"
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

# P1.9: Geopolitical keywords — always trigger (high-impact events).
# WHY always-trigger: Geopolitical events (war, sanctions, energy crises)
# ALWAYS affect crypto markets via risk-off sentiment, regardless of whether
# the title mentions crypto explicitly.
GEOPOLITICAL_KEYWORDS = [
    "war",
    "invasion",
    "blockade",
    "sanctions",
    "airstrike",
    "missile",
    "nuclear",
    "ceasefire",
    "oil crisis",
    "energy crisis",
    "embargo",
    "hormuz",  # Strait of Hormuz — critical oil chokepoint (Spec 2.7)
]

CONTEXT_REQUIRED_KEYWORDS = [
    "crash",
    "collapse",
    "SEC",
    "ban",
    "emergency",
]

# Combined list for backward compat (DetectionConfig default).
# WHY order: always-trigger first (crypto + geo + VN regulatory), then context-required.
# QO.17: VN regulatory keywords included so they also trigger event detection.
DEFAULT_KEYWORD_TRIGGERS = (
    ALWAYS_TRIGGER_KEYWORDS + GEOPOLITICAL_KEYWORDS + CONTEXT_REQUIRED_KEYWORDS
)
# NOTE: VN_REGULATORY_KEYWORDS defined below (after _CRYPTO_CONTEXT_WORDS) are checked
# separately in _match_keywords to avoid polluting the basic keyword list ordering.

DEFAULT_PANIC_THRESHOLD = 70

# BUG-16: Nuclear energy false-positive exclusion.
# WHY: "nuclear" in GEOPOLITICAL_KEYWORDS triggers on "nuclear energy startup"
# or "nuclear power plant" — these are energy topics, not geopolitical threats.
_NUCLEAR_ENERGY_WORDS = {
    "energy",
    "power",
    "reactor",
    "plant",
    "fusion",
    "fission",
    "startup",
}

# SEC-04: Crypto-context neutralizers for geopolitical keywords.
# WHY: CryptoPanic articles like "nuclear energy deal boosts mining stocks"
# contain geopolitical keywords in a crypto/business context, not a threat context.
# If the title has BOTH a geopolitical keyword AND a crypto-context word,
# we skip the geopolitical trigger (the article is about crypto, not geopolitics).
_CRYPTO_CONTEXT_NEUTRALIZERS = {
    "mining",
    "crypto",
    "blockchain",
    "defi",
    "token",
    "coin",
    "nft",
    "protocol",
    "exchange",
    "wallet",
    "etf",
    "staking",
    "yield",
    "airdrop",
}

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

# QO.17: VN regulatory keywords — events matching these get auto CRITICAL severity.
# WHY separate list: VN crypto regulation directly impacts the CIC community (VN-based).
# These keywords bypass normal severity scoring because any VN regulatory action
# on crypto is high-impact for our audience regardless of panic_score.
VN_REGULATORY_KEYWORDS = [
    # Vietnamese legal document types
    "thông tư",
    "nghị định",
    "quy định crypto",
    "cấm giao dịch",
    # Vietnamese regulatory bodies
    "bộ tài chính",
    "ngân hàng nhà nước",
    # English abbreviations for VN regulatory entities
    "sbv",  # State Bank of Vietnam
    "onus",  # VN crypto exchange
    "vasp",  # Virtual Asset Service Provider (VN regulatory term)
    # VN-specific regulatory phrases (English)
    "vietnam crypto ban",
    "vietnam regulation",
    "vietnam blockchain",
    "vietnam digital asset",
    # Common VN regulatory terms in English news
    "vietnamese regulation",
    "vietnam ministry of finance",
    "state bank of vietnam",
]

# QO.15: Crypto relevance keywords — reuses severity_classifier._CRYPTO_RELEVANCE_KEYWORDS
# concept but placed HERE so filtering happens BEFORE severity classification.
# WHY duplicate: event_detector should be self-contained for early filtering.
# The severity_classifier keeps its own copy for backward compat.
_CRYPTO_RELEVANCE_KEYWORDS = {
    # Assets — tickers
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
    # Assets — project names
    "ripple",
    "dogecoin",
    "avalanche",
    "avax",
    "polkadot",
    "dot",
    "polygon",
    "matic",
    "chainlink",
    "link",
    "litecoin",
    "ltc",
    "uniswap",
    "cosmos",
    "toncoin",
    "ton",
    "stellar",
    "xlm",
    "aptos",
    "arbitrum",
    "optimism",
    "sui",
    "near",
    "shib",
    "tron",
    "hedera",
    "filecoin",
    # Exchanges & infra
    "binance",
    "coinbase",
    "kraken",
    "okx",
    "bybit",
    "exchange",
    "mining",
    "miner",
    "halving",
    "wallet",
    "ledger",
    "trezor",
    "smart contract",
    "layer 2",
    "rollup",
    "airdrop",
    # Regulatory
    "etf",
    "sec",
    "cftc",
    "regulation",
    "ban",
    # Security
    "hack",
    "exploit",
    "breach",
    "vulnerability",
    "rug pull",
    "stolen",
    # Sentiment
    "fear & greed",
    "fear and greed",
    "f&g",
    "extreme fear",
    "extreme greed",
    # Market events
    "market",
    "crash",
    "liquidation",
    "liquidated",
    "rally",
    "pump",
    "dump",
    "bull",
    "bear",
    "price",
    "surge",
    "plunge",
    "partnership",
    "acquisition",
    "lawsuit",
}

# QO.15: Geopolitical keywords that bypass crypto relevance check.
# WHY synced with severity_classifier._GEOPOLITICAL_KEYWORDS + event_detector.GEOPOLITICAL_KEYWORDS:
# Must cover all geo terms that existing code treats as always-trigger.
_GEOPOLITICAL_RELEVANCE_KEYWORDS = {
    "war",
    "attack",
    "missile",
    "sanctions",
    "iran",
    "escalation",
    "invasion",
    "fed",
    "interest rate",
    "inflation",
    "tariff",
    # From GEOPOLITICAL_KEYWORDS list (event_detector top-level)
    "blockade",
    "airstrike",
    "nuclear",
    "ceasefire",
    "oil crisis",
    "energy crisis",
    "embargo",
    "hormuz",
}


def is_crypto_relevant(title: str) -> bool:
    """Check if event title is relevant to crypto market (QO.15).

    Runs at event_detector level BEFORE severity classification to filter
    out non-crypto events early (saving LLM scoring quota, etc.).

    Returns True if title contains any crypto keyword, geopolitical keyword,
    or VN regulatory keyword. Non-crypto, non-geopolitical events (e.g.,
    sports betting platforms) should not enter the pipeline at all.
    """
    title_lower = title.lower()
    if any(kw in title_lower for kw in _CRYPTO_RELEVANCE_KEYWORDS):
        return True
    if any(kw in title_lower for kw in _GEOPOLITICAL_RELEVANCE_KEYWORDS):
        return True
    # QO.17: VN regulatory keywords are always relevant
    if any(kw in title_lower for kw in VN_REGULATORY_KEYWORDS):
        return True
    return False


def is_vn_regulatory(title: str) -> bool:
    """Check if event matches VN regulatory keywords (QO.17).

    Used by severity_classifier to auto-assign CRITICAL severity.
    """
    title_lower = title.lower()
    return any(kw in title_lower for kw in VN_REGULATORY_KEYWORDS)


def is_geo_event(title: str) -> bool:
    """Check if event is geopolitical/macro — not crypto-specific (QO.14).

    Returns True if title matches geopolitical keywords but does NOT contain
    crypto-specific terms. Used by breaking_pipeline to route geo events
    to digest instead of individual messages.

    WHY separate from is_crypto_relevant: geo events ARE relevant (they
    affect crypto markets), but they should be GROUPED into digests
    rather than sent individually to reduce noise.
    """
    title_lower = title.lower()
    # Must match at least one geopolitical keyword
    has_geo = any(kw in title_lower for kw in _GEOPOLITICAL_RELEVANCE_KEYWORDS)
    if not has_geo:
        return False
    # If it ALSO has crypto-specific keywords, it's a crypto event with geo context
    # — treat as crypto, not geo. E.g., "Fed rate cut boosts Bitcoin" → crypto event.
    has_crypto = any(kw in title_lower for kw in _CRYPTO_RELEVANCE_KEYWORDS)
    return not has_crypto


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

        # QO.15: Early crypto relevance filter — skip non-crypto events BEFORE
        # any scoring/keyword matching. Saves processing for irrelevant items.
        if not is_crypto_relevant(title):
            logger.debug(f"Skipping non-crypto event at detector level: '{title[:60]}'")
            continue

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

    QO.17: Also checks VN_REGULATORY_KEYWORDS (always-trigger).
    """
    title_lower = title.lower()
    title_words = set(title_lower.split())
    has_crypto_context = any(w in title_lower for w in _CRYPTO_CONTEXT_WORDS)

    # P1.9: Pre-compute always-trigger sets (crypto + geopolitical)
    _always_crypto = {k.lower() for k in ALWAYS_TRIGGER_KEYWORDS}
    _always_geo = {k.lower() for k in GEOPOLITICAL_KEYWORDS}

    matched: list[str] = []
    for kw in keywords:
        kw_lower = kw.lower()
        if kw_lower not in title_lower:
            continue

        # Crypto-specific always-trigger (hack, exploit, etc.) — fire regardless
        if kw_lower in _always_crypto:
            matched.append(kw)
        # Geopolitical always-trigger — with BUG-16 + SEC-04 guards
        elif kw_lower in _always_geo:
            # BUG-16: "nuclear" false positive — skip if energy-related context
            if kw_lower == "nuclear" and title_words & _NUCLEAR_ENERGY_WORDS:
                continue
            # SEC-04: If title has crypto-context neutralizers alongside geo keyword,
            # the article is about crypto/business, not a geopolitical threat — skip.
            if title_words & _CRYPTO_CONTEXT_NEUTRALIZERS:
                continue
            matched.append(kw)
        # Context-required keywords need a crypto word in the same title
        elif has_crypto_context:
            matched.append(kw)
        # else: skip — generic keyword without crypto context

    # QO.17: VN regulatory keywords — always trigger, checked separately
    # to avoid requiring them in the caller's keyword list.
    for kw in VN_REGULATORY_KEYWORDS:
        kw_lower = kw.lower()
        if kw_lower in title_lower and kw not in matched:
            matched.append(kw)

    return matched
