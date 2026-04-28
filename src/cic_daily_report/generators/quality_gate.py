"""Quality Gate — Factual Consistency + Insight Density Check (P1.22, QO.20).

QO.20: BLOCK mode — actively retries generation when quality issues detected.
Modes (configurable via QUALITY_GATE_MODE in CAU_HINH Google Sheet):
  - "BLOCK" (default): retry once on factual_issues > 0 or density < threshold
  - "LOG": measure and log only (original Phase 1a behavior)
  - "OFF": skip all checks

Spec: SPEC-quality-overhaul-v2.md Section 4 (Wave 2, QO.20)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from cic_daily_report.core.logger import get_logger

logger = get_logger("quality_gate")

# QO.32: Kept as DEFAULT FALLBACK — runtime value read from config_loader.
# WHY 0.30: Spec says "< 30% -> retry". Articles below this threshold
# are mostly filler text without data-backed claims.
INSIGHT_DENSITY_THRESHOLD = 0.30

# Wave 0.5.2 (alpha.19) Fix 2: per-tier density thresholds (Winston).
# WHY: applying 0.30 uniformly fails L3-L5 narrative/macro articles by design
# (they reason about scenarios, not raw metrics). Audit 28/04 found 100% of
# Daily Report L3-L5 articles failed → quality warning attached to every
# message → user trust eroded. Tiered thresholds reflect content shape.
INSIGHT_DENSITY_THRESHOLDS = {
    "L1": 0.30,  # quick takes, must be data-dense
    "L2": 0.30,
    "L3": 0.15,  # narrative analysis, looser
    "L4": 0.15,
    "L5": 0.10,  # macro/strategy, mostly reasoning
    "summary": 0.20,
    "Summary": 0.20,
    "research": 0.20,
    "Research": 0.20,
    "breaking": 0.25,
    "Breaking": 0.25,
}

# QO.20: Valid quality gate modes — BLOCK is the new default.
# WHY BLOCK default: spec says "Active retry on quality issues, not LOG-ONLY anymore"
VALID_MODES = {"BLOCK", "LOG", "OFF"}
DEFAULT_MODE = "BLOCK"

# QO.20 / Wave 0.5.2 Fix 7: Quality warning is now INTERNAL (log-only).
# WHY changed: Devil audit found the user-facing warning eroded trust without
# giving users actionable information. The warning was meant for dev/admin
# triage, not end users. Constant kept (empty) for backwards compat with
# existing tests that import QUALITY_WARNING; new code logs to logger.warning().
QUALITY_WARNING = ""

# Internal-only quality warning text (logged, never appended to user content).
_QUALITY_WARNING_LOG_TEXT = (
    "Quality gate: article shipped despite low density / factual issues — "
    "monitor in CHANGELOG audit and tighten Wave 0.6 RAG."
)

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
        r"\$[\d,.]+\d",  # dollar amounts: $87,500 (US) or $87.500 (VN format)
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
    # QO.20: Track whether the result came from a retry attempt
    was_retried: bool = False
    quality_warning_appended: bool = False


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
    # BUG-06 fix: Match actual numeric value >= 5%, not digits containing 5-9.
    # Old regex `[5-9]` caught 3.5% because '5' after decimal matched.
    # New approach: extract all percentages and check numerically.
    has_large_move = False
    for m in re.finditer(r"\([+-]?(\d+[.,]?\d*)%\)", market_data):
        try:
            val = float(m.group(1).replace(",", "."))
            if val >= 5.0:
                has_large_move = True
                break
        except ValueError:
            pass
    # NOTE: Double-digit check now redundant — numeric >= 5.0 covers it.

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


def get_quality_gate_mode(config_loader: object | None = None) -> str:
    """Read QUALITY_GATE_MODE from CAU_HINH config, falling back to BLOCK.

    QO.20: Mode is configurable via Google Sheet for easy rollback.
    Operator can set "LOG" to revert to Phase 1a behavior without deploy.

    Args:
        config_loader: Optional ConfigLoader instance. If None, returns DEFAULT_MODE.

    Returns:
        One of "BLOCK", "LOG", "OFF".
    """
    if config_loader is None:
        return DEFAULT_MODE

    try:
        raw = config_loader.get_setting("QUALITY_GATE_MODE", DEFAULT_MODE)
        mode = str(raw).strip().upper()
        if mode not in VALID_MODES:
            logger.warning(f"Invalid QUALITY_GATE_MODE '{mode}' in CAU_HINH, using {DEFAULT_MODE}")
            return DEFAULT_MODE
        return mode
    except Exception:
        return DEFAULT_MODE


def _get_insight_density_threshold(
    config_loader: object | None = None,
    tier: str = "",
) -> float:
    """QO.32: Read INSIGHT_DENSITY_THRESHOLD from CAU_HINH config at runtime.

    Wave 0.5.2 Fix 2: tier-aware lookup. Resolution order:
        1. CAU_HINH override per-tier key INSIGHT_DENSITY_THRESHOLD_<TIER>
        2. CAU_HINH global key INSIGHT_DENSITY_THRESHOLD
        3. Per-tier default in INSIGHT_DENSITY_THRESHOLDS
        4. Module fallback INSIGHT_DENSITY_THRESHOLD (0.30)

    WHY: L3-L5 narrative articles legitimately have lower data density than
    L1-L2 quick-takes. A uniform 0.30 caused 100% false positives there.
    """
    # Per-tier default from the dict
    tier_default = INSIGHT_DENSITY_THRESHOLDS.get(tier, INSIGHT_DENSITY_THRESHOLD)

    if config_loader is None:
        return tier_default
    try:
        # Per-tier config override takes precedence when set
        if tier:
            tier_key = f"INSIGHT_DENSITY_THRESHOLD_{tier.upper()}"
            tier_override = config_loader.get_setting_float(tier_key, -1.0)
            if tier_override >= 0:
                return tier_override
        # Global config override applies if set; otherwise tier default.
        global_override = config_loader.get_setting_float("INSIGHT_DENSITY_THRESHOLD", -1.0)
        if global_override >= 0:
            return global_override
        return tier_default
    except Exception:
        return tier_default


def run_quality_gate(
    content: str,
    tier: str,
    input_data: dict,
    mode: str = "BLOCK",
    config_loader: object | None = None,
) -> QualityGateResult:
    """Run all quality gate checks on a generated article.

    QO.20: Supports 3 modes:
      - BLOCK (default): checks + retry_recommended=True on failure
      - LOG: checks + log only (original Phase 1a behavior)
      - OFF: skip all checks, return passed=True

    QO.32: INSIGHT_DENSITY_THRESHOLD read from CAU_HINH via config_loader.

    Args:
        content: Generated article text.
        tier: Article tier (L1-L5, Summary, Research).
        input_data: Dict with keys "economic_events", "market_data", "key_metrics".
        mode: Quality gate mode — "BLOCK", "LOG", or "OFF".
        config_loader: Optional ConfigLoader for reading thresholds from CAU_HINH.

    Returns:
        QualityGateResult with all check results.
    """
    # QO.20: OFF mode — skip all checks
    if mode == "OFF":
        return QualityGateResult(
            passed=True,
            insight_density=1.0,
            details=f"tier={tier} | mode=OFF (skipped)",
        )

    # QO.32 + Wave 0.5.2 Fix 2: Read density threshold per-tier at runtime
    density_threshold = _get_insight_density_threshold(config_loader, tier=tier)

    factual_issues = check_factual_consistency(content, input_data)
    density, total_sentences, data_backed = check_insight_density(content)

    passed = len(factual_issues) == 0 and density >= density_threshold
    # QO.20: In BLOCK mode, retry_recommended drives actual retry logic.
    # In LOG mode, it's informational only.
    retry_recommended = not passed

    details_parts = [f"tier={tier}", f"mode={mode}"]
    if factual_issues:
        details_parts.append(f"factual_issues={len(factual_issues)}")
    details_parts.append(f"density={density:.0%} ({data_backed}/{total_sentences} sentences)")
    if density < density_threshold:
        details_parts.append(f"below_threshold={density_threshold:.0%}")
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

    if not result.passed:
        logger.warning(
            f"Quality gate [{tier}] ({mode}): RETRY RECOMMENDED — "
            f"density={density:.0%}, issues={len(factual_issues)}"
        )
        for issue in factual_issues:
            logger.warning(f"  Factual: {issue}")
    else:
        logger.info(f"Quality gate PASS [{tier}]: {details}")

    return result


async def run_quality_gate_with_retry(
    content: str,
    tier: str,
    input_data: dict,
    regenerate_fn: Callable[[], object] | None = None,
    mode: str = "BLOCK",
    config_loader: object | None = None,
) -> tuple[str, QualityGateResult]:
    """QO.20: Run quality gate with optional retry in BLOCK mode.

    When mode=BLOCK and the first check fails:
    1. Call regenerate_fn() to get new content
    2. Re-check the new content
    3. If still fails → log warning, append quality warning, send anyway

    QO.32: config_loader passed through to run_quality_gate for
    INSIGHT_DENSITY_THRESHOLD reading.

    Args:
        content: Generated article text.
        tier: Article tier.
        input_data: Dict with market/economic data for factual checks.
        regenerate_fn: Async callable that returns new content string.
            If None, retry is skipped.
        mode: Quality gate mode.
        config_loader: Optional ConfigLoader for reading thresholds from CAU_HINH.

    Returns:
        Tuple of (final_content, QualityGateResult).
    """
    first_result = run_quality_gate(
        content, tier, input_data, mode=mode, config_loader=config_loader
    )

    # If passed, or mode is not BLOCK, return as-is
    if first_result.passed or mode != "BLOCK":
        return content, first_result

    # BLOCK mode: attempt retry if regenerate_fn provided
    if regenerate_fn is None:
        logger.warning(f"Quality gate [{tier}] BLOCK: no regenerate_fn — sending as-is")
        return content, first_result

    logger.info(f"Quality gate [{tier}] BLOCK: retrying generation...")
    try:
        new_content_obj = await regenerate_fn()
        # WHY: regenerate_fn returns either a string or an object with .content attr
        new_content = (
            new_content_obj.content if hasattr(new_content_obj, "content") else str(new_content_obj)
        )

        retry_result = run_quality_gate(
            new_content, tier, input_data, mode=mode, config_loader=config_loader
        )
        retry_result.was_retried = True

        if retry_result.passed:
            logger.info(f"Quality gate [{tier}] BLOCK: retry PASSED")
            return new_content, retry_result

        # Retry also failed — Wave 0.5.2 Fix 7: log internally, ship clean content
        # (no user-facing warning suffix).
        logger.warning(
            f"Quality gate [{tier}] BLOCK: retry also failed "
            f"(density={retry_result.insight_density:.0%}, "
            f"issues={len(retry_result.factual_issues)}). "
            f"{_QUALITY_WARNING_LOG_TEXT}"
        )
        retry_result.quality_warning_appended = True  # flag kept for ops dashboards
        return new_content + QUALITY_WARNING, retry_result

    except Exception as e:
        logger.error(f"Quality gate [{tier}] BLOCK: retry failed with error: {e}")
        # On retry error, ship original — Fix 7: no user-facing warning appended.
        logger.warning(
            f"Quality gate [{tier}] BLOCK: shipping original. {_QUALITY_WARNING_LOG_TEXT}"
        )
        first_result.was_retried = True
        first_result.quality_warning_appended = True
        return content + QUALITY_WARNING, first_result


# ---------------------------------------------------------------------------
# QO.48: Headline price validation
# ---------------------------------------------------------------------------

# WHY 0.05: 5% deviation threshold. Larger deviations between LLM-generated
# price mentions and actual PriceSnapshot data likely indicate hallucination
# or stale data in the prompt.
PRICE_DEVIATION_THRESHOLD = 0.05

# Matches dollar-denominated prices like "$87,500", "$3,200.50", "$0.45"
_PRICE_MENTION_RE = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)")

# Matches patterns like "BTC ... $87,500" or "Bitcoin ... $87,500" within proximity
_ASSET_PRICE_RE = re.compile(
    r"(BTC|ETH|Bitcoin|Ethereum|SOL|Solana|BNB|XRP|ADA|DOGE|AVAX|DOT|MATIC|LINK)"
    r"[^$]{0,80}"
    r"\$\s*([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)

# WHY: Map display names to symbols for PriceSnapshot lookup
_NAME_TO_SYMBOL = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "solana": "SOL",
    "bnb": "BNB",
    "xrp": "XRP",
    "cardano": "ADA",
    "dogecoin": "DOGE",
    "avalanche": "AVAX",
    "polkadot": "DOT",
    "polygon": "MATIC",
    "chainlink": "LINK",
}


@dataclass
class PriceValidationResult:
    """QO.48: Result of headline price validation against PriceSnapshot."""

    passed: bool
    warnings: list[str] = field(default_factory=list)
    checked_count: int = 0
    deviation_count: int = 0


def validate_headline_prices(
    content: str,
    price_snapshot: object | None = None,
) -> PriceValidationResult:
    """QO.48: Validate that prices mentioned in generated text match PriceSnapshot.

    Extracts dollar-amount patterns from text and compares with PriceSnapshot.
    If deviation > 5%, logs a warning. Does NOT block — advisory only.

    WHY advisory: LLM may format prices differently (rounded, abbreviated),
    and blocking on price mismatch would be too aggressive. Warnings let
    operators spot hallucinated prices in logs.

    Args:
        content: Generated article text.
        price_snapshot: PriceSnapshot object with get_price(symbol) method.

    Returns:
        PriceValidationResult with warnings for any significant deviations.
    """
    if not content or price_snapshot is None:
        return PriceValidationResult(passed=True)

    warnings_list: list[str] = []
    checked = 0
    deviated = 0

    # Find asset-price pairs in text
    for match in _ASSET_PRICE_RE.finditer(content):
        asset_raw = match.group(1).upper()
        price_str = match.group(2).replace(",", "")

        try:
            mentioned_price = float(price_str)
        except ValueError:
            continue

        # Normalize asset name to symbol
        symbol = _NAME_TO_SYMBOL.get(asset_raw.lower(), asset_raw.upper())

        # Look up actual price from snapshot
        actual_price = price_snapshot.get_price(symbol)
        if actual_price is None or actual_price <= 0:
            continue

        checked += 1

        # Calculate deviation
        deviation = abs(mentioned_price - actual_price) / actual_price

        if deviation > PRICE_DEVIATION_THRESHOLD:
            deviated += 1
            warnings_list.append(
                f"QO.48: {symbol} price mismatch — "
                f"text says ${mentioned_price:,.2f}, "
                f"snapshot has ${actual_price:,.2f} "
                f"(deviation: {deviation:.1%})"
            )
            logger.warning(warnings_list[-1])

    passed = deviated == 0

    if checked > 0:
        log_fn = logger.info if passed else logger.warning
        log_fn(
            f"QO.48: Price validation — {checked} prices checked, "
            f"{deviated} deviations > {PRICE_DEVIATION_THRESHOLD:.0%}"
        )

    return PriceValidationResult(
        passed=passed,
        warnings=warnings_list,
        checked_count=checked,
        deviation_count=deviated,
    )


# ---------------------------------------------------------------------------
# QO.21: Cross-tier overlap check
# ---------------------------------------------------------------------------

# WHY 0.40: Spec says "overlap > 40% for any pair → retry".
# Adjacent tier pairs should share <40% sentence-level content to ensure
# each tier adds unique value for members who read all tiers.
OVERLAP_THRESHOLD = 0.40

# QO.38: Default for CROSS_TIER_CHECK_ENABLED config key.
# WHY True: Cross-tier overlap check should be active by default (spec says
# "actively enforced"). Operator can disable via CAU_HINH if needed.
DEFAULT_CROSS_TIER_CHECK_ENABLED = True

# Adjacent tier pairs to check (spec: L1↔L2, L2↔L3, L3↔L4, L4↔L5)
_ADJACENT_PAIRS = [("L1", "L2"), ("L2", "L3"), ("L3", "L4"), ("L4", "L5")]


def _normalize_sentence(sentence: str) -> str:
    """Normalize a sentence for comparison: lowercase, strip whitespace/punctuation.

    WHY: Vietnamese text may have diacritics, extra spaces, or punctuation
    differences between tiers. Normalization ensures fair comparison.
    """
    s = sentence.lower().strip()
    # Remove common punctuation and extra whitespace
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def _split_sentences(content: str) -> list[str]:
    """Split content into normalized sentences for overlap comparison.

    QO.21: Uses same splitting logic as check_insight_density but returns
    normalized sentences for comparison.
    """
    if not content or not content.strip():
        return []

    raw = re.split(r"(?<=[.!?])\s+|\n+", content)
    sentences = []
    for s in raw:
        s = s.strip()
        if (
            s
            and len(s) > 10
            and not s.startswith("##")
            and not s.startswith("---")
            and not s.startswith("*Tuyên bố")
            and not s.startswith("⚠️")
        ):
            normalized = _normalize_sentence(s)
            if normalized:
                sentences.append(normalized)
    return sentences


def _calculate_pair_overlap(sentences_a: list[str], sentences_b: list[str]) -> float:
    """Calculate sentence-level overlap between two sets of sentences.

    QO.21: Overlap = |intersection| / min(|A|, |B|)
    WHY min: Using min avoids penalizing longer articles and makes the metric
    sensitive to the shorter article being fully repeated in the longer one.

    Returns:
        Overlap ratio 0.0-1.0. Returns 0.0 if either set is empty.
    """
    if not sentences_a or not sentences_b:
        return 0.0

    set_a = set(sentences_a)
    set_b = set(sentences_b)
    intersection = set_a & set_b

    denominator = min(len(set_a), len(set_b))
    if denominator == 0:
        return 0.0

    return len(intersection) / denominator


def is_cross_tier_check_enabled(config_loader: object | None = None) -> bool:
    """QO.38: Read CROSS_TIER_CHECK_ENABLED from CAU_HINH config.

    WHY configurable: Operator may want to disable the check temporarily
    (e.g., during testing or when intentionally publishing similar content).

    Args:
        config_loader: Optional ConfigLoader instance. If None, returns default (True).

    Returns:
        True if cross-tier overlap check should be active, False to skip.
    """
    if config_loader is None:
        return DEFAULT_CROSS_TIER_CHECK_ENABLED
    try:
        return config_loader.get_setting_bool(
            "CROSS_TIER_CHECK_ENABLED", DEFAULT_CROSS_TIER_CHECK_ENABLED
        )
    except Exception:
        return DEFAULT_CROSS_TIER_CHECK_ENABLED


def check_cross_tier_overlap(tier_contents: dict[str, str]) -> dict:
    """QO.21: Check sentence-level overlap between adjacent tier pairs.

    Args:
        tier_contents: Dict mapping tier name to article content.
            E.g. {"L1": "...", "L2": "...", "L3": "...", "L4": "...", "L5": "..."}

    Returns:
        Dict with keys:
            - "passed": bool — True if all pairs < OVERLAP_THRESHOLD
            - "pairs": dict — per-pair overlap percentages
            - "exceeded": list — pairs that exceeded threshold
            - "threshold": float — the threshold used
    """
    # Pre-compute sentences per tier
    tier_sentences: dict[str, list[str]] = {}
    for tier, content in tier_contents.items():
        tier_sentences[tier] = _split_sentences(content)

    pairs: dict[str, float] = {}
    exceeded: list[str] = []

    for tier_a, tier_b in _ADJACENT_PAIRS:
        if tier_a not in tier_sentences or tier_b not in tier_sentences:
            continue

        overlap = _calculate_pair_overlap(tier_sentences[tier_a], tier_sentences[tier_b])
        pair_key = f"{tier_a}↔{tier_b}"
        pairs[pair_key] = round(overlap, 3)

        if overlap > OVERLAP_THRESHOLD:
            exceeded.append(pair_key)
            logger.warning(
                f"Cross-tier overlap [{pair_key}]: {overlap:.0%} "
                f"exceeds {OVERLAP_THRESHOLD:.0%} threshold"
            )
        else:
            logger.info(f"Cross-tier overlap [{pair_key}]: {overlap:.0%} — OK")

    passed = len(exceeded) == 0

    return {
        "passed": passed,
        "pairs": pairs,
        "exceeded": exceeded,
        "threshold": OVERLAP_THRESHOLD,
    }
