"""Wave 0.5.2 (alpha.19) Fix 4 — Numeric sanity guard for generated content.

Audit Round 2 (28/04/2026) found LLM-generated articles with absurd numerics:
  * "Heat Score độ tin cậy 1700%" — multiplier double-applied
  * "MKR +40.4%" — confused year-to-date with 24h change
  * "BTC.D 58.1%" vs actual 60.66% — drifted from data
  * "AltSeason 50" vs actual 27-37 — fabricated

Root cause for MKR/BTC.D is LLM hallucination from training data (collectors
verified to populate change_24h correctly from `percent_change_24h`). Smoking
gun: same numbers appear in pre-2024 articles in the LLM training corpus.

This module provides POST-GENERATION sanity checks that don't try to fix the
root cause (LLM hallucination — defer to Wave 0.6 RAG factcheck pass) but
DO catch the most embarrassing failures before they ship to Telegram.

Non-blocking — returns warnings + sanitized text. Caller decides whether to
ship sanitized version or refuse (currently we ship sanitized + log).

Wave 0.6 Story 0.6.3 (alpha.21) — Extended numeric guards:
  * BTC price sanity ($10k-$200k plausible window for 2026)
  * ETH price sanity ($1k-$10k plausible window for 2026)
  * Year sanity (flag year > current_year + 1 — likely fabricated future)
  * Wrapper `apply_all_numeric_guards()` runs full guard suite in sequence.

WHY ranges, not exact matches: BTC/ETH spot moves daily, so we cannot pin to
a snapshot value. Instead we flag "obviously wrong" outliers (BTC < $10k or
> $200k cannot occur in 2026 reality). Tight ranges configurable via env
override later if false positives appear.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from cic_daily_report.core.logger import get_logger

logger = get_logger("numeric_sanity")

# WHY 100% cap: real-world 24h price moves above 100% are exceedingly rare and
# are almost always LLM math errors (multiplier double-applied, percent point
# vs percent confusion, year-vs-day mix-up). When detected, cap at 100% to
# avoid shipping nonsense like "+1700%" while keeping the directionality.
PCT_CAP = 100.0

# Match percentage occurrences with optional sign, e.g. "5%", "-12.5%", "+1700%".
# Capture group 1 = sign, group 2 = numeric value, group 3 = decimal part.
# WHY this regex: handles VN locale (5,2%) and ASCII locale (5.2%) both.
_PCT_RE = re.compile(r"(?<![A-Za-z\d])([+\-]?)(\d{1,5})(?:[.,](\d+))?\s*%")


@dataclass
class SanityResult:
    """Outcome of numeric sanity scan."""

    sanitized_content: str
    warnings: list[str] = field(default_factory=list)
    capped_count: int = 0
    checked_count: int = 0

    @property
    def passed(self) -> bool:
        """True iff no values were capped."""
        return self.capped_count == 0


def check_and_cap_percentages(content: str, cap: float = PCT_CAP) -> SanityResult:
    """Detect % values exceeding ``cap`` and replace with ``{cap}%`` in content.

    WHY post-process: shipping "1700%" to Telegram is worse than capping it.
    Operations team gets the warning in logs and can investigate. End user
    sees a still-wrong but at least bounded number.

    Args:
        content: Generated article text (Vietnamese, may contain HTML).
        cap: Hard cap; values strictly greater are replaced.

    Returns:
        SanityResult with sanitized text + warnings list.
    """
    if not content:
        return SanityResult(sanitized_content=content)

    warnings: list[str] = []
    capped = 0
    checked = 0

    def _replace(match: re.Match[str]) -> str:
        nonlocal capped, checked
        sign = match.group(1) or ""
        intp = match.group(2)
        decp = match.group(3) or ""
        try:
            raw_str = f"{intp}.{decp}" if decp else intp
            val = float(raw_str)
        except ValueError:
            return match.group(0)

        checked += 1
        if val > cap:
            capped += 1
            replacement = f"{sign}{int(cap)}%"
            warnings.append(
                f"Numeric sanity: replaced '{match.group(0).strip()}' with '{replacement}' "
                f"(value {val} > cap {cap})"
            )
            logger.warning(warnings[-1])
            return replacement
        return match.group(0)

    sanitized = _PCT_RE.sub(_replace, content)

    return SanityResult(
        sanitized_content=sanitized,
        warnings=warnings,
        capped_count=capped,
        checked_count=checked,
    )


# WHY also expose extract-only for tests / quality_gate hooks: callers may
# want to log without rewriting. Used by tests in test_numeric_sanity.py.
def extract_percentages(content: str) -> list[float]:
    """Return all percentage numeric values found in content (signed)."""
    out: list[float] = []
    for m in _PCT_RE.finditer(content):
        try:
            sign = -1.0 if m.group(1) == "-" else 1.0
            decp = m.group(3) or ""
            raw = f"{m.group(2)}.{decp}" if decp else m.group(2)
            out.append(sign * float(raw))
        except ValueError:
            continue
    return out


# ---------------------------------------------------------------------------
# Wave 0.6 Story 0.6.3 (alpha.21) — Extended numeric guards
# ---------------------------------------------------------------------------

# WHY 2026 ranges: as of 2026-04, BTC trades $70k-$110k zone, ETH $2k-$5k.
# Floor/ceiling chosen to be 5x wider than realistic to avoid flagging real
# news ("BTC chạm $30k năm 2024" historical → still inside floor). Anything
# outside these is almost certainly LLM bullshit (BTC $5k means LLM dreamed
# up 2018 bear, BTC $300k means hallucinated bull projection).
BTC_PRICE_MIN = 10_000.0
BTC_PRICE_MAX = 200_000.0
ETH_PRICE_MIN = 1_000.0
ETH_PRICE_MAX = 10_000.0

# Match dollar amounts with optional decimals + optional k/M suffix.
# Group 1 = numeric, group 2 = decimals, group 3 = suffix.
# WHY this regex: catches $30k, $76,000, $76.5k, $200,000, $5M etc.
# We do NOT match generic numbers without $ to avoid false positives on
# percentages, scores, or unrelated stats.
_BTC_PRICE_RE = re.compile(
    r"\$\s*(\d{1,3}(?:[,.\s]\d{3})*|\d+)(?:[.,](\d+))?\s*([kKmM]?)\b",
)

# Vietnamese + English BTC/ETH context windows. We require the ticker to
# appear within ±60 chars of the dollar amount to avoid stripping unrelated
# prices (e.g., "Coinbase IPO at $381" should not be flagged as BTC price).
_BTC_CONTEXT_TOKENS = ("BTC", "Bitcoin", "bitcoin")
_ETH_CONTEXT_TOKENS = ("ETH", "Ethereum", "ethereum", "Ether")

# Year regex — capture 4-digit years 20XX. We deliberately bound to 20xx so
# we don't flag 1990s historical references (legit) or page numbers.
_YEAR_RE = re.compile(r"\b(20\d{2})\b")


def _parse_dollar_value(int_part: str, dec_part: str | None, suffix: str) -> float | None:
    """Convert regex-captured dollar fragments into a float USD value.

    WHY tolerate spaces/dots/commas as thousands separators: VN articles use
    mixed conventions (76.500 = 76,500 = 76 500 = $76.5k). We normalize all
    these into 76500.0 for sanity comparison.
    """
    try:
        # Strip thousands separators (, . space) — but only if length > 3
        # after the separator (i.e., "76,000" → 76000, but "76.5" stays 76.5).
        cleaned = int_part.replace(",", "").replace(" ", "").replace(".", "")
        # If int_part contained no separator, cleaned == int_part
        if not cleaned.isdigit():
            return None
        val = float(cleaned)
        if dec_part:
            val += float(f"0.{dec_part}")
        suffix_lc = suffix.lower()
        if suffix_lc == "k":
            val *= 1_000.0
        elif suffix_lc == "m":
            val *= 1_000_000.0
        return val
    except (ValueError, TypeError):
        return None


def _has_context(content: str, start: int, end: int, tokens: tuple[str, ...]) -> bool:
    """Return True if any of `tokens` appears within ±60 chars of [start:end]."""
    window_start = max(0, start - 60)
    window_end = min(len(content), end + 60)
    window = content[window_start:window_end]
    return any(tok in window for tok in tokens)


def check_btc_price_sanity(
    content: str,
    min_price: float = BTC_PRICE_MIN,
    max_price: float = BTC_PRICE_MAX,
) -> tuple[str, list[str]]:
    """Flag BTC price claims outside plausible 2026 range.

    Returns (cleaned_content, issues_list). Currently DOES NOT strip — only
    flags. WHY: stripping a sentence mid-paragraph could break narrative
    flow more than the wrong number itself. Caller (content_generator)
    decides whether to log + ship or block.

    WHY context check (BTC|Bitcoin within ±60 chars): a generic "$5,000
    grant fund" should NOT be flagged. Only $X near a BTC mention.
    """
    if not content:
        return content, []
    issues: list[str] = []
    for m in _BTC_PRICE_RE.finditer(content):
        if not _has_context(content, m.start(), m.end(), _BTC_CONTEXT_TOKENS):
            continue
        val = _parse_dollar_value(m.group(1), m.group(2), m.group(3) or "")
        if val is None:
            continue
        # WHY ignore tiny values (< 100): "$5 fee" near "BTC" is not a BTC
        # price claim, just unrelated cost. Real BTC price is always >$1000
        # in any plausible reality (even 2018 lows were $3.2k).
        if val < 100:
            continue
        if val < min_price or val > max_price:
            issues.append(
                f"BTC price out of range: '{m.group(0).strip()}' = ${val:,.0f} "
                f"(range ${min_price:,.0f}-${max_price:,.0f})"
            )
            logger.warning(issues[-1])
    return content, issues


def check_eth_price_sanity(
    content: str,
    min_price: float = ETH_PRICE_MIN,
    max_price: float = ETH_PRICE_MAX,
) -> tuple[str, list[str]]:
    """Flag ETH price claims outside plausible 2026 range. See `check_btc_price_sanity`."""
    if not content:
        return content, []
    issues: list[str] = []
    for m in _BTC_PRICE_RE.finditer(content):
        if not _has_context(content, m.start(), m.end(), _ETH_CONTEXT_TOKENS):
            continue
        val = _parse_dollar_value(m.group(1), m.group(2), m.group(3) or "")
        if val is None:
            continue
        if val < 50:
            # Same low-bound bypass as BTC — small $ near ETH is not price.
            continue
        if val < min_price or val > max_price:
            issues.append(
                f"ETH price out of range: '{m.group(0).strip()}' = ${val:,.0f} "
                f"(range ${min_price:,.0f}-${max_price:,.0f})"
            )
            logger.warning(issues[-1])
    return content, issues


def check_year_sanity(
    content: str,
    current_year: int | None = None,
    future_buffer: int = 1,
) -> tuple[str, list[str]]:
    """Flag year mentions > current_year + future_buffer.

    WHY future_buffer=1: events like "ETF approval expected 2027" are legit
    in 2026 (1 year out). But "Bitcoin halving 2032" in a 2026 article is
    almost certainly LLM hallucination — we don't write speculative 6-year
    forecasts in breaking news.

    Past years pass through without flag — historical references to 2014
    Mt.Gox or 2022 Terra collapse are valid context.
    """
    if not content:
        return content, []
    if current_year is None:
        current_year = datetime.now(timezone.utc).year
    threshold = current_year + future_buffer
    issues: list[str] = []
    for m in _YEAR_RE.finditer(content):
        try:
            year = int(m.group(1))
        except ValueError:
            continue
        if year > threshold:
            issues.append(f"Year suspicious: {year} > current+{future_buffer} ({threshold})")
            logger.warning(issues[-1])
    return content, issues


def apply_all_numeric_guards(
    content: str,
    btc_snapshot: float | None = None,
    eth_snapshot: float | None = None,
) -> tuple[str, list[str]]:
    """Run full guard suite (% cap + BTC/ETH price + year sanity) in sequence.

    Args:
        content: Generated article text.
        btc_snapshot: Optional current BTC price for tighter range (Story 0.6.4
            will wire PriceSnapshot here). When None, use global BTC_PRICE_MIN/MAX.
        eth_snapshot: Same for ETH. When None, use global ETH_PRICE_MIN/MAX.

    Returns:
        (sanitized_content, issues_list). Issues list combines warnings from
        all guards. Sanitized content has %% capped (from Wave 0.5.2) but
        BTC/ETH/year violations are NOT stripped — only logged.

    WHY no stripping for price/year: low confidence in detection regex (false
    positive risk). Story 0.6.4 will pass real PriceSnapshot for tight ranges
    and may add stripping then. For now, fail-soft: flag + ship.
    """
    if not content:
        return content, []

    issues: list[str] = []

    # Step 1: % cap (existing Wave 0.5.2 behavior).
    pct_result = check_and_cap_percentages(content)
    sanitized = pct_result.sanitized_content
    issues.extend(pct_result.warnings)

    # Step 2: BTC price sanity. Use snapshot ±50% if provided, else default range.
    # WHY ±50%: snapshot is a single-point reference; real intraday moves of
    # 5-10% are normal but 50% is hard cap to avoid false positives on legit
    # historical mentions (e.g., "BTC từng đạt $69k năm 2021" if snapshot=$76k).
    if btc_snapshot and btc_snapshot > 0:
        btc_min = max(BTC_PRICE_MIN, btc_snapshot * 0.5)
        btc_max = min(BTC_PRICE_MAX, btc_snapshot * 1.5)
    else:
        btc_min, btc_max = BTC_PRICE_MIN, BTC_PRICE_MAX
    _, btc_issues = check_btc_price_sanity(sanitized, btc_min, btc_max)
    issues.extend(btc_issues)

    if eth_snapshot and eth_snapshot > 0:
        eth_min = max(ETH_PRICE_MIN, eth_snapshot * 0.5)
        eth_max = min(ETH_PRICE_MAX, eth_snapshot * 1.5)
    else:
        eth_min, eth_max = ETH_PRICE_MIN, ETH_PRICE_MAX
    _, eth_issues = check_eth_price_sanity(sanitized, eth_min, eth_max)
    issues.extend(eth_issues)

    # Step 3: year sanity.
    _, year_issues = check_year_sanity(sanitized)
    issues.extend(year_issues)

    return sanitized, issues
