"""Severity Classification & Night Mode (Story 5.3).

3 severity levels: 🔴 Critical / 🟠 Important / 🟡 Notable.
Night Mode (23:00-07:00 VN UTC+7): only 🔴 sent immediately.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from cic_daily_report.breaking.event_detector import (
    VN_REGULATORY_KEYWORDS,
    BreakingEvent,
    is_vn_regulatory,
)
from cic_daily_report.core.logger import get_logger

logger = get_logger("severity_classifier")

VN_UTC_OFFSET = timedelta(hours=7)
VN_TZ = timezone(VN_UTC_OFFSET)
NIGHT_START = 23  # 23:00 VN
NIGHT_END = 7  # 07:00 VN

# Severity levels
CRITICAL = "critical"
IMPORTANT = "important"
NOTABLE = "notable"

SEVERITY_EMOJI = {
    CRITICAL: "\U0001f534",  # 🔴
    IMPORTANT: "\U0001f7e0",  # 🟠
    NOTABLE: "\U0001f7e1",  # 🟡
}

# QO.11 (VD-37): Severity legend appended to the FIRST breaking message of the day.
# WHY: Each message has a severity emoji but no explanation — new members may not
# know what 🔴/🟠/🟡 mean. Sending once per day avoids repetition.
SEVERITY_LEGEND = (
    "\n\n📋 *Mức độ tin:* \U0001f534 Nghiêm trọng • \U0001f7e0 Quan trọng • \U0001f7e1 Đáng chú ý"
)

# QO.11 fix: Legend tracking uses BOTH module-level state (within a process)
# AND dedup_manager persistence (across processes). GitHub Actions runs the
# breaking pipeline as a fresh process ~4x/day, so module-level state alone
# would reset each run, causing legend to fire 4x/day instead of 1x.
# The dedup_manager writes a synthetic "SEVERITY_LEGEND" entry to BREAKING_LOG
# sheet, which persists across process restarts.
_legend_last_sent_date: datetime | None = None


def should_send_legend(
    now: datetime | None = None,
    dedup_mgr: object | None = None,
) -> bool:
    """Check if severity legend should be appended to this message.

    Returns True for the first breaking message of each calendar day (UTC).
    Uses two layers:
    1. Module-level date tracker (fast, within single process)
    2. DedupManager persistence via BREAKING_LOG (across process restarts)

    When dedup_mgr is provided, checks for a synthetic "SEVERITY_LEGEND" entry
    with today's date. If found, legend was already sent by a previous pipeline run.

    Args:
        now: Current time. Defaults to now.
        dedup_mgr: Optional DedupManager instance for cross-process persistence.
    """
    global _legend_last_sent_date
    current = now or datetime.now(timezone.utc)
    current_date = current.date()

    # Layer 1: Module-level fast check (within same process)
    if _legend_last_sent_date is not None and _legend_last_sent_date.date() == current_date:
        return False

    # Layer 2: Cross-process persistence via dedup_manager
    if dedup_mgr is not None:
        if _is_legend_in_dedup(dedup_mgr, current_date):
            # Already sent by a previous pipeline run today — update module state
            _legend_last_sent_date = current
            return False

    # First legend of the day — mark it
    _legend_last_sent_date = current
    return True


def mark_legend_sent(dedup_mgr: object, now: datetime | None = None) -> None:
    """Record that legend was sent today in dedup_manager for cross-process persistence.

    Writes a synthetic DedupEntry with hash="SEVERITY_LEGEND" so that subsequent
    pipeline runs (fresh processes) can detect the legend was already sent today.

    Args:
        dedup_mgr: DedupManager instance to record into.
        now: Current time. Defaults to now.
    """
    from cic_daily_report.breaking.dedup_manager import DedupEntry

    current = now or datetime.now(timezone.utc)
    entry = DedupEntry(
        hash=f"SEVERITY_LEGEND_{current.date().isoformat()}",
        title="SEVERITY_LEGEND",
        source="system",
        severity="",
        detected_at=current.isoformat(),
        status="sent",
    )
    # WHY direct append: DedupManager.check_and_filter() is for real events;
    # legend is a synthetic marker. Direct append + hash_map update is simpler.
    dedup_mgr._entries.append(entry)
    dedup_mgr._hash_map[entry.hash] = entry


def _is_legend_in_dedup(dedup_mgr: object, target_date) -> bool:
    """Check if a SEVERITY_LEGEND entry exists for the given date in dedup_mgr.

    Looks for an entry with hash matching "SEVERITY_LEGEND_{date}" pattern.
    """
    target_hash = f"SEVERITY_LEGEND_{target_date.isoformat()}"
    return target_hash in dedup_mgr._hash_map


def reset_legend_tracker() -> None:
    """Reset legend tracker — for testing only."""
    global _legend_last_sent_date
    _legend_last_sent_date = None


# Default classification keywords (configurable via CAU_HINH)
# WHY "ban" removed from CRITICAL (VD-21): Too broad — matches "Binance ban",
# "gambling ban", etc. Only CRITICAL when combined with crypto-specific context.
# Moved to IMPORTANT keywords instead.
DEFAULT_CRITICAL_KEYWORDS = [
    "hack",
    "exploit",
    "collapse",
    "bankrupt",
    "emergency",
    "rug pull",
]

# v0.30.1: Analysis/opinion indicators — when title contains a critical keyword
# AND one of these, downgrade severity from CRITICAL → IMPORTANT.
# Rationale: "Hậu quả hack Bybit" is analysis, not a live hack alert.
ANALYSIS_DOWNGRADE_KEYWORDS = [
    # Vietnamese
    "hậu quả",
    "bài học",
    "phân tích",
    "nhìn lại",
    "đánh giá",
    "tổng hợp",
    "bình luận",
    "ảnh hưởng sau",
    # English
    "aftermath",
    "lesson",
    "analysis",
    "review",
    "history",
    "postmortem",
    "opinion",
    "impact of",
    "what we learned",
]

DEFAULT_IMPORTANT_KEYWORDS = [
    "ban",  # VD-21: moved from CRITICAL — too broad for top severity
    "crash",  # Synced from event_detector DEFAULT_KEYWORD_TRIGGERS
    "partnership",
    "liquidation",
    "liquidated",
    "regulatory",
    "SEC",
    "lawsuit",
    "acquisition",
    "drops",
    "falls",
    "plunges",
    "surges",
    "soars",
    "selloff",
    "sell-off",
    "rally",
    "war",
    "attack",
    "missile",
    "sanctions",
    "Iran",
    "escalation",
    "invasion",
]

# v0.28.0: Crypto relevance keywords — at least one must appear in title
# for non-geopolitical events to be classified as breaking news.
# Geopolitical keywords (war, sanctions, etc.) bypass this check.
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
    # Assets — project names (v0.28.0: sync with data_cleaner + coin_mapping)
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
    # Security events (common in crypto)
    "hack",
    "exploit",
    "breach",
    "vulnerability",
    "rug pull",
    "stolen",
    # Sentiment indicators
    # WHY: "Fear & Greed Index" is a core crypto sentiment metric. Without these,
    # F&G extreme events get skipped as "non-crypto" (observed in production logs).
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
_GEOPOLITICAL_KEYWORDS = {
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
}


def _is_crypto_relevant(title: str) -> bool:
    """Check if event title is relevant to crypto market.

    Returns True if title contains any crypto keyword, geopolitical keyword,
    or VN regulatory keyword (QO.17).
    Non-crypto, non-geopolitical events (e.g., sports betting platforms)
    should not trigger breaking alerts for a crypto community.
    """
    title_lower = title.lower()
    if any(kw in title_lower for kw in _CRYPTO_RELEVANCE_KEYWORDS):
        return True
    if any(kw in title_lower for kw in _GEOPOLITICAL_KEYWORDS):
        return True
    # QO.17: VN regulatory keywords are always crypto-relevant
    if any(kw in title_lower for kw in VN_REGULATORY_KEYWORDS):
        return True
    return False


@dataclass
class ClassificationConfig:
    """Configuration for severity classification."""

    critical_keywords: list[str] = field(default_factory=lambda: list(DEFAULT_CRITICAL_KEYWORDS))
    important_keywords: list[str] = field(default_factory=lambda: list(DEFAULT_IMPORTANT_KEYWORDS))
    critical_panic_threshold: int = 85
    important_panic_threshold: int = 60


@dataclass
class ClassifiedEvent:
    """An event with severity classification and delivery decision."""

    event: BreakingEvent
    severity: str  # "critical", "important", "notable"
    emoji: str
    delivery_action: str  # "send_now", "deferred_to_morning", "deferred_to_daily"

    @property
    def is_deferred(self) -> bool:
        return self.delivery_action != "send_now"

    @property
    def header(self) -> str:
        """Formatted header for delivery."""
        return f"{self.emoji} [{self.severity.upper()}] {self.event.title}"


def classify_event(
    event: BreakingEvent,
    config: ClassificationConfig | None = None,
    now: datetime | None = None,
) -> ClassifiedEvent:
    """Classify event severity and determine delivery action.

    Args:
        event: Breaking event to classify.
        config: Classification thresholds and keywords.
        now: Current time (for Night Mode check). Defaults to now.

    Returns:
        ClassifiedEvent with severity and delivery action.
    """
    cfg = config or ClassificationConfig()
    current_time = now or datetime.now(timezone.utc)

    # v0.28.0: Skip non-crypto-relevant events (e.g., sports betting)
    if not _is_crypto_relevant(event.title):
        logger.info(f"Skipping non-crypto event: '{event.title}'")
        return ClassifiedEvent(
            event=event,
            severity=NOTABLE,
            emoji=SEVERITY_EMOJI[NOTABLE],
            delivery_action="skipped",
        )

    severity = _determine_severity(event, cfg)
    is_night = _is_night_mode(current_time)
    action = _determine_action(severity, is_night)

    logger.info(
        f"Classified '{event.title}': {severity} ({'night' if is_night else 'day'}) → {action}"
    )

    return ClassifiedEvent(
        event=event,
        severity=severity,
        emoji=SEVERITY_EMOJI[severity],
        delivery_action=action,
    )


def classify_batch(
    events: list[BreakingEvent],
    config: ClassificationConfig | None = None,
    now: datetime | None = None,
) -> list[ClassifiedEvent]:
    """Classify multiple events."""
    return [classify_event(e, config, now) for e in events]


def _determine_severity(event: BreakingEvent, config: ClassificationConfig) -> str:
    """Determine severity based on panic_score, keywords, and price movement."""
    title_lower = event.title.lower()

    # QO.17: VN regulatory events → auto CRITICAL (before any other checks).
    # WHY first: VN regulation directly impacts CIC community, must never be
    # downgraded by analysis-downgrade or other heuristics.
    if is_vn_regulatory(event.title):
        logger.info(f"QO.17: VN regulatory event auto-CRITICAL: '{event.title[:60]}'")
        return CRITICAL

    # Check critical keywords (word-boundary matching to avoid false positives)
    has_critical_keyword = False
    for kw in config.critical_keywords:
        if re.search(r"\b" + re.escape(kw.lower()) + r"\b", title_lower):
            has_critical_keyword = True
            break

    if has_critical_keyword:
        # v0.30.1: Downgrade analysis/opinion articles that mention critical keywords
        # e.g. "Hậu quả hack Bybit" → IMPORTANT (not a live incident)
        for akw in ANALYSIS_DOWNGRADE_KEYWORDS:
            if akw.lower() in title_lower:
                logger.info(
                    f"Downgraded '{event.title}': "
                    f"critical keyword + analysis indicator '{akw}' → IMPORTANT"
                )
                return IMPORTANT
        return CRITICAL

    # Check panic score for critical
    if event.panic_score >= config.critical_panic_threshold:
        return CRITICAL

    # Check price-movement percentage in title (e.g. "drops 3.5%", "surges 10%")
    # Only apply for PRICE movements — volume/OI/TVL percentages are not severity signals
    pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", event.title)
    if pct_match:
        pct_value = float(pct_match.group(1))

        _VOLUME_KEYWORDS = {"volume", "trading volume", "open interest", "oi", "tvl"}
        _PRICE_KEYWORDS = {
            "drop",
            "crash",
            "fall",
            "plunge",
            "surge",
            "soar",
            "gain",
            "rise",
            "jump",
        }

        is_volume = any(kw in title_lower for kw in _VOLUME_KEYWORDS)
        is_price = any(kw in title_lower for kw in _PRICE_KEYWORDS)

        if is_price and not is_volume:
            if pct_value >= 10:
                return CRITICAL
            if pct_value >= 3:
                return IMPORTANT
        # Volume % or ambiguous → do NOT use percentage for severity

    # Check important keywords (word-boundary matching)
    for kw in config.important_keywords:
        if re.search(r"\b" + re.escape(kw.lower()) + r"\b", title_lower):
            return IMPORTANT

    # Check panic score for important
    if event.panic_score >= config.important_panic_threshold:
        return IMPORTANT

    return NOTABLE


def _is_night_mode(now: datetime) -> bool:
    """Check if current time is within Night Mode window (23:00-07:00 VN).

    Args:
        now: Current time in any timezone (will be converted to VN).
    """
    vn_time = now.astimezone(VN_TZ)
    hour = vn_time.hour
    return hour >= NIGHT_START or hour < NIGHT_END


def _determine_action(severity: str, is_night: bool) -> str:
    """Determine delivery action based on severity and night mode.

    - 🔴 Critical: always send_now
    - 🟠 Important: deferred_to_morning during night
    - 🟡 Notable during night: skipped (C2 — deferred_to_daily was never consumed)
    """
    if severity == CRITICAL:
        return "send_now"

    if not is_night:
        return "send_now"

    if severity == IMPORTANT:
        return "deferred_to_morning"

    return "skipped"
