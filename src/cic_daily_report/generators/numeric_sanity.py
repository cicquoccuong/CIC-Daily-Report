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
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

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
