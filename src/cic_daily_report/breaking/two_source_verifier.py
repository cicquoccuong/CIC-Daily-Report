"""Wave 0.6 Story 0.6.4 (alpha.22) — Two-source verification.

Audit Round 2 finding: CoinDesk + CoinTelegraph reported "Canada Bill C-25"
within minutes. Both passed dedup (different sources, slightly different
wording) and got sent — same event, 2 messages. Conversely, single-source
critical claims have higher hallucination risk (Wave 0.5 audit: 87.5% of
LLM "historical references" fabricated when only 1 source).

This module determines if a candidate event has been reported by a SECOND
independent source within the recent window. Decision logic in
``breaking_pipeline.py``:

- ``verified``: ship the event (corroborated by independent source).
- ``single_source`` + critical → DEFER (wait for corroboration).
- ``single_source`` + non-critical → SHIP + log warning (notable claim).
- ``conflict`` → DEFER + log error (sources disagree on numbers).

Reuses the same SequenceMatcher + entity extraction from dedup_manager so
the matching threshold is consistent with how dedup recognizes "same event".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Literal

from cic_daily_report.breaking.dedup_manager import DedupEntry, _extract_entities
from cic_daily_report.breaking.event_detector import BreakingEvent
from cic_daily_report.core.logger import get_logger

logger = get_logger("two_source_verifier")

# Match threshold: how similar two titles must be to count as "same event".
# WHY 0.4: lower than dedup SIMILARITY_THRESHOLD (0.55) because 2-source
# corroboration is more permissive — we WANT to recognize the same event
# across sources even with significant rewording. Entity overlap >= 1
# provides the required structural signal.
DEFAULT_SIMILARITY_THRESHOLD = 0.4
# Conflict threshold: above this similarity AND numeric disagreement → conflict.
# WHY higher than match threshold: only flag conflict when titles are CLEARLY
# about the same event but quote different numbers (e.g., "$1B hack" vs
# "$10B hack").
CONFLICT_SIMILARITY_THRESHOLD = 0.7
# Recent window: 24h is industry standard for "same news cycle".
DEFAULT_RECENT_HOURS = 24

# Wave 0.6.6 B6: regex captures the magnitude SUFFIX too (K/M/B/T) so we can
# scale the value before comparing. Original `(?:...)` non-capture group
# treated "$1M" and "$1B" both as 1.0 → false-no-conflict on orders-of-mag
# disagreements.
_NUMERIC_PATTERN = re.compile(r"\$?(\d+(?:[.,]\d+)?)\s*([KkMmBbTt%])?")
# Multipliers for magnitude suffixes. "%" stays 1.0 (it's a percent, not size).
_MAG_MULTIPLIERS: dict[str, float] = {
    "K": 1e3,
    "M": 1e6,
    "B": 1e9,
    "T": 1e12,
}


@dataclass
class TwoSourceResult:
    """Result of 2-source verification check.

    Attributes:
        verdict: "verified" | "single_source" | "conflict".
        second_source: source name of the matched 2nd entry, or "" if none.
        similarity_score: SequenceMatcher ratio against best match (0.0-1.0).
        matched_title: title of the matched 2nd entry, for logging.
    """

    verdict: Literal["verified", "single_source", "conflict"]
    second_source: str = ""
    similarity_score: float = 0.0
    matched_title: str = ""


def _extract_magnitudes(title: str) -> set[float]:
    """Extract numeric magnitudes from a title for conflict detection.

    Wave 0.6.6 B6: scale value by suffix (K/M/B/T) so $1M and $1B compare
    correctly as 1e6 vs 1e9 (not both as 1.0). Percent suffix ("%") leaves
    value unchanged — percents are independent of dollar magnitudes.

    WHY set: order doesn't matter; we want overlap check.
    """
    out: set[float] = set()
    for m in _NUMERIC_PATTERN.finditer(title):
        try:
            val_str = m.group(1).replace(",", "")
            val = float(val_str)
            suffix = (m.group(2) or "").upper()
            mult = _MAG_MULTIPLIERS.get(suffix, 1.0)
            out.add(val * mult)
        except (ValueError, IndexError):
            continue
    return out


def _has_numeric_conflict(title_a: str, title_b: str) -> bool:
    """Return True when two titles cite differing numerics.

    Conservative: only flags conflict when BOTH titles contain numbers AND
    the numeric sets differ by more than tolerance. Pure-text titles
    (no numbers) → never conflict here.

    Wave 0.6.6 B6: tolerance now 5% — $1.0M vs $1.05M should NOT be flagged
    (rounding/reporting variance) but $1M vs $1B (1000x) MUST be flagged.
    """
    nums_a = _extract_magnitudes(title_a)
    nums_b = _extract_magnitudes(title_b)
    if not nums_a or not nums_b:
        return False
    # If any number in A is "close enough" (5%) to a number in B → same fact.
    # WHY relative not absolute: $1B has different absolute tolerance than $50.
    for a in nums_a:
        for b in nums_b:
            if a == 0 or b == 0:
                if a == b:
                    return False
                continue
            ratio = a / b if a > b else b / a
            if ratio <= 1.05:
                return False
    # All numbers materially differ → conflict signal.
    return True


def verify_two_sources(
    event: BreakingEvent,
    recent_events: list[DedupEntry],
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    recent_hours: int = DEFAULT_RECENT_HOURS,
) -> TwoSourceResult:
    """Check if event has been reported by a 2nd independent source.

    Algorithm:
    1. Filter recent_events to last ``recent_hours`` window.
    2. Skip entries from the SAME source as event (we want INDEPENDENT
       corroboration, not the same outlet republishing).
    3. For each candidate entry, compute title similarity (SequenceMatcher)
       + entity overlap (reusing dedup_manager._extract_entities).
    4. similarity >= ``similarity_threshold`` AND entity_overlap >= 1
       → match found → ``verified``.
    5. similarity >= CONFLICT_SIMILARITY_THRESHOLD AND numeric values
       differ → ``conflict`` (sources disagree on key numbers).
    6. No match → ``single_source``.

    Args:
        event: Candidate event to verify.
        recent_events: List of DedupEntry from breaking history.
        similarity_threshold: Minimum SequenceMatcher ratio to count as
            "same event". Default 0.4 (more permissive than dedup's 0.55).
        recent_hours: Window for "recent" history. Default 24h.

    Returns:
        TwoSourceResult.
    """
    if not recent_events:
        return TwoSourceResult(verdict="single_source")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=recent_hours)

    event_title_lower = event.title.strip().lower()
    event_entities = _extract_entities(event.title)
    event_source_lower = (event.source or "").strip().lower()

    best_match: DedupEntry | None = None
    best_similarity = 0.0
    conflict_match: DedupEntry | None = None
    conflict_similarity = 0.0

    for entry in recent_events:
        # WHY skip same source: independent corroboration requires DIFFERENT
        # outlet. CoinDesk reposting itself doesn't count.
        entry_source_lower = (entry.source or "").strip().lower()
        if entry_source_lower == event_source_lower:
            continue

        # Time filter — skip entries outside recent window.
        if not entry.detected_at:
            continue
        try:
            entry_time = datetime.fromisoformat(entry.detected_at)
            if entry_time.tzinfo is None:
                entry_time = entry_time.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
        if entry_time < cutoff:
            continue

        # Compute similarity + entity overlap.
        entry_title_lower = entry.title.strip().lower()
        ratio = SequenceMatcher(None, event_title_lower, entry_title_lower).ratio()
        entry_entities = _extract_entities(entry.title)
        overlap = event_entities & entry_entities

        # Conflict check FIRST — high similarity + numeric disagreement.
        if ratio >= CONFLICT_SIMILARITY_THRESHOLD and _has_numeric_conflict(
            event.title, entry.title
        ):
            if ratio > conflict_similarity:
                conflict_similarity = ratio
                conflict_match = entry
            continue

        # Match check — similarity AND entity overlap.
        if ratio >= similarity_threshold and len(overlap) >= 1:
            if ratio > best_similarity:
                best_similarity = ratio
                best_match = entry

    # Conflict wins over verified (safety: surface conflict to operator).
    if conflict_match is not None:
        logger.error(
            f"Story 0.6.4: Source conflict — '{event.title[:60]}' (source={event.source}) "
            f"vs '{conflict_match.title[:60]}' (source={conflict_match.source}, "
            f"sim={conflict_similarity:.2f})"
        )
        return TwoSourceResult(
            verdict="conflict",
            second_source=conflict_match.source,
            similarity_score=conflict_similarity,
            matched_title=conflict_match.title,
        )

    if best_match is not None:
        logger.info(
            f"Story 0.6.4: 2-source verified — '{event.title[:60]}' "
            f"matches '{best_match.title[:60]}' (source={best_match.source}, "
            f"sim={best_similarity:.2f})"
        )
        return TwoSourceResult(
            verdict="verified",
            second_source=best_match.source,
            similarity_score=best_similarity,
            matched_title=best_match.title,
        )

    return TwoSourceResult(verdict="single_source")
