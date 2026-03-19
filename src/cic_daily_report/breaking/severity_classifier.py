"""Severity Classification & Night Mode (Story 5.3).

3 severity levels: 🔴 Critical / 🟠 Important / 🟡 Notable.
Night Mode (23:00-07:00 VN UTC+7): only 🔴 sent immediately.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from cic_daily_report.breaking.event_detector import BreakingEvent
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

# Default classification keywords (configurable via CAU_HINH)
DEFAULT_CRITICAL_KEYWORDS = [
    "hack",
    "exploit",
    "collapse",
    "bankrupt",
    "ban",
    "emergency",
    "rug pull",
]

DEFAULT_IMPORTANT_KEYWORDS = [
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

    # Check critical keywords (word-boundary matching to avoid false positives)
    for kw in config.critical_keywords:
        if re.search(r"\b" + re.escape(kw.lower()) + r"\b", title_lower):
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
    - 🟡 Notable: deferred_to_daily during night
    """
    if severity == CRITICAL:
        return "send_now"

    if not is_night:
        return "send_now"

    if severity == IMPORTANT:
        return "deferred_to_morning"

    return "deferred_to_daily"
