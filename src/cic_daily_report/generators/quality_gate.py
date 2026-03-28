"""Quality Gate — Factual Consistency + Insight Density Check (P1.22).

Phase 1a: LOG-ONLY — measures quality metrics and logs warnings.
Does NOT block or retry article generation.

Spec: v2.0-architecture-redesign.md Section 2.6
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from cic_daily_report.core.logger import get_logger

logger = get_logger("quality_gate")

# WHY 0.30: Spec says "< 30% -> retry". Articles below this threshold
# are mostly filler text without data-backed claims.
INSIGHT_DENSITY_THRESHOLD = 0.30

# --- Vietnamese "no event" claim patterns ---
# WHY: LLM sometimes claims "no macro events" when the economic calendar
# has real events. These patterns detect such false claims.
_NO_EVENT_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"không có sự kiện",
        r"thị trường yên ắt",
        r"tuần yên tĩnh",
        r"không có dữ liệu",
        r"không có tin tức",
        r"không có biến động",
    ]
]

# --- "Quiet market" patterns ---
# WHY: LLM may claim market is calm when BTC moved >5%.
_QUIET_MARKET_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"thị trường yên ắt",
        r"tuần yên tĩnh",
        r"không có biến động",
        r"biến động\s+(?:không\s+)?đáng\s+kể",
    ]
]

# --- Data-backed sentence detection patterns ---
# WHY: A sentence with at least one of these patterns is considered
# "data-backed" — it references a concrete number, metric, or figure.
_DATA_PATTERNS = [
    re.compile(p)
    for p in [
        r"\d+[.,]\d+%",  # percentages like 5.2%
        r"\$[\d,]+",  # dollar amounts like $87,500
        r"(?:BTC|ETH|Bitcoin|Ethereum)\s*[\$\d]",  # crypto + number
        r"\d+[.,]\d+\s*(?:tỷ|triệu|nghìn)",  # Vietnamese number words
        # metrics with values (e.g. "RSI = 52", "F&G Index = 45", "Fear & Greed = 72")
        r"(?:RSI|MVRV|NUPL|SOPR|Puell|F&G|Fear\s*&?\s*Greed)"
        r"\s*(?:\w+\s*)*[:\=]?\s*\d",
        r"\d+[.,]?\d*[KMB]\b",  # abbreviated numbers like 1.5B, 200K
    ]
]

# --- Percentage extraction for factual cross-check ---
# Matches patterns like "tăng 5.2%", "giảm 12%", "+3.5%", "-8.1%"
_PERCENTAGE_CLAIM_RE = re.compile(
    r"(?:tăng|giảm|tang|giam|\+|-)\s*(\d+[.,]?\d*)\s*%",
    re.IGNORECASE,
)

# Matches percentage values in market data text like "BTC: $87,500 (+5.2%)"
_MARKET_PERCENTAGE_RE = re.compile(
    r"\(([+-]?\d+[.,]?\d*)\s*%\)",
)


@dataclass
class QualityGateResult:
    """Result of quality gate checks on a generated article."""

    passed: bool
    factual_issues: list[str] = field(default_factory=list)
    insight_density: float = 0.0  # 0.0-1.0
    total_sentences: int = 0
    data_backed_sentences: int = 0
    retry_recommended: bool = False
    details: str = ""


def check_factual_consistency(content: str, input_data: dict) -> list[str]:
    """Check generated content against input data for factual contradictions.

    Args:
        content: Generated article text.
        input_data: Dict with keys "economic_events", "market_data", "key_metrics".

    Returns:
        List of issue descriptions (empty = no issues found).
    """
    issues: list[str] = []

    economic_events = input_data.get("economic_events", "") or ""
    market_data = input_data.get("market_data", "") or ""

    # Check 1: Content claims "no events" but economic calendar has data
    # WHY: This is the most common LLM hallucination — saying "nothing happened"
    # when the calendar has real macro events.
    if economic_events.strip():
        for pattern in _NO_EVENT_PATTERNS:
            if pattern.search(content):
                issues.append(
                    f"Content claims '{pattern.pattern}' but economic_events has data "
                    f"({len(economic_events)} chars)"
                )

    # Check 2: Percentage mismatch — content claims X% but data says Y%
    # WHY: LLM sometimes rounds or fabricates percentage changes.
    # Tolerance: 5 percentage points (absolute).
    content_pcts = _PERCENTAGE_CLAIM_RE.findall(content)
    market_pcts = _MARKET_PERCENTAGE_RE.findall(market_data)

    if content_pcts and market_pcts:
        # Convert to float sets for comparison
        content_values = set()
        for p in content_pcts:
            try:
                content_values.add(abs(float(p.replace(",", "."))))
            except ValueError:
                continue

        market_values = set()
        for p in market_pcts:
            try:
                market_values.add(abs(float(p.replace(",", "."))))
            except ValueError:
                continue

        # Flag content percentages that are far from any market data percentage
        for cv in content_values:
            if market_values and all(abs(cv - mv) > 5.0 for mv in market_values):
                issues.append(
                    f"Content mentions {cv}% but no market data value within 5pp tolerance "
                    f"(market values: {sorted(market_values)[:5]})"
                )

    # Check 3: Content claims "quiet market" but data shows >5% moves
    # WHY: A >5% daily move in BTC is significant — calling the market "quiet"
    # is factually wrong.
    has_large_move = bool(re.search(r"\([+-]?\d*[5-9]\d*[.,]\d*%\)", market_data))
    # Also check for double-digit moves
    if not has_large_move:
        has_large_move = bool(re.search(r"\([+-]?\d{2,}[.,]\d*%\)", market_data))

    if has_large_move:
        for pattern in _QUIET_MARKET_PATTERNS:
            if pattern.search(content):
                issues.append(f"Content claims '{pattern.pattern}' but market data shows >5% moves")

    return issues


def check_insight_density(content: str) -> tuple[float, int, int]:
    """Measure the ratio of data-backed sentences in the content.

    A "data-backed" sentence contains at least one concrete data point
    (number, percentage, dollar amount, metric name with value).

    Args:
        content: Generated article text.

    Returns:
        Tuple of (density_ratio, total_sentences, data_backed_count).
        density_ratio is 0.0 if there are no sentences.
    """
    if not content or not content.strip():
        return 0.0, 0, 0

    # Split into sentences — Vietnamese text uses ". " and newlines as boundaries.
    # Also split on "! " and "? " for completeness.
    # WHY: Vietnamese articles often use newlines between bullet points,
    # so newline splitting is important alongside period splitting.
    raw_sentences = re.split(r"(?<=[.!?])\s+|\n+", content)

    # Filter out empty strings, headers (## lines), disclaimers, and very short fragments
    sentences = [
        s.strip()
        for s in raw_sentences
        if s.strip()
        and len(s.strip()) > 10  # skip fragments too short to be real sentences
        and not s.strip().startswith("##")  # skip markdown headers
        and not s.strip().startswith("---")  # skip horizontal rules
        and not s.strip().startswith("*Tuyên bố")  # skip disclaimer
    ]

    total = len(sentences)
    if total == 0:
        return 0.0, 0, 0

    data_backed = 0
    for sentence in sentences:
        for pattern in _DATA_PATTERNS:
            if pattern.search(sentence):
                data_backed += 1
                break  # one match is enough per sentence

    density = data_backed / total
    return density, total, data_backed


def run_quality_gate(content: str, tier: str, input_data: dict) -> QualityGateResult:
    """Run all quality gate checks on a generated article.

    Phase 1a: LOG-ONLY — populates result but does NOT block pipeline.

    Args:
        content: Generated article text.
        tier: Article tier (L1-L5, Summary, Research).
        input_data: Dict with keys "economic_events", "market_data", "key_metrics".

    Returns:
        QualityGateResult with all check results.
    """
    factual_issues = check_factual_consistency(content, input_data)
    density, total_sentences, data_backed = check_insight_density(content)

    passed = len(factual_issues) == 0 and density >= INSIGHT_DENSITY_THRESHOLD
    retry_recommended = not passed

    details_parts = [f"tier={tier}"]
    if factual_issues:
        details_parts.append(f"factual_issues={len(factual_issues)}")
    details_parts.append(f"density={density:.0%} ({data_backed}/{total_sentences} sentences)")
    if density < INSIGHT_DENSITY_THRESHOLD:
        details_parts.append(f"below_threshold={INSIGHT_DENSITY_THRESHOLD:.0%}")
    details = " | ".join(details_parts)

    result = QualityGateResult(
        passed=passed,
        factual_issues=factual_issues,
        insight_density=density,
        total_sentences=total_sentences,
        data_backed_sentences=data_backed,
        retry_recommended=retry_recommended,
        details=details,
    )

    # Phase 1a: Log results — do NOT block pipeline
    if not result.passed:
        logger.warning(f"Quality gate WARN [{tier}]: {details}")
        for issue in factual_issues:
            logger.warning(f"  Factual: {issue}")
    else:
        logger.info(f"Quality gate PASS [{tier}]: {details}")

    return result
