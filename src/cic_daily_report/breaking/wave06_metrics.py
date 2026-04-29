"""Wave 0.6 Story 0.6.5 (alpha.23) — Pipeline metrics for Wave 0.6 features.

WHY this module exists separately from BreakingRunLog:
BreakingRunLog tracks pipeline-level outcomes (sent/deferred/errors).
Wave06Metrics tracks Wave 0.6 feature internals — fact-check verdicts, RAG
hit rates, date/numeric guard activity, 2-source verification outcomes.
This isolation lets operator monitor each Wave 0.6 sub-feature
independently and decide which flags are safe to keep ON during rollout.

WHY dataclass with int counters (not metrics framework like prometheus):
Pipeline runs every 3h via GitHub Actions — separate processes. There's no
long-lived metrics server to scrape. We log the per-run summary line into
NHAT_KY_PIPELINE for human review and grep-friendly aggregation.

WHY no histograms / no observability infra:
Karpathy "Simplicity First" — metrics are read by Anh Cuong (no-code user)
manually from logs during 3-day Wave 0.6 monitoring window. Adding
prometheus / OTLP would be premature.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Wave06Metrics:
    """Per-run counters for Wave 0.6 features.

    Each pipeline run starts fresh — no cross-run aggregation here.
    Aggregation happens in NHAT_KY_PIPELINE / log analysis downstream.
    """

    # Cerebras Qwen3 fact-checker verdicts (Story 0.6.1)
    fact_check_passed: int = 0
    fact_check_rejected: int = 0
    fact_check_needs_revision: int = 0

    # RAG historical context inject (Story 0.6.2)
    historical_inject_count: int = 0  # events that received RAG context
    historical_no_match: int = 0  # events with no RAG history match

    # Date HARD BLOCK strip activity (Story 0.6.3)
    date_block_strip_count: int = 0  # sentences stripped due to stale date

    # Numeric guard strip activity (Story 0.6.3)
    numeric_guard_strip_count: int = 0  # claims removed by numeric_sanity

    # 2-source verification outcomes (Story 0.6.4)
    two_source_verified: int = 0
    two_source_single: int = 0
    two_source_conflict: int = 0

    # Free-form telemetry (extensible without dataclass churn)
    extra: dict[str, Any] = field(default_factory=dict)

    def increment(self, field_name: str, delta: int = 1) -> None:
        """Bump a named counter by delta (default 1).

        WHY method (not direct attr access): pipeline call sites can use a
        single increment() pattern for both known fields and extras (when
        future stories add new metrics without dataclass change).
        """
        if hasattr(self, field_name) and isinstance(getattr(self, field_name), int):
            setattr(self, field_name, getattr(self, field_name) + delta)
        else:
            # Stash in extras so we don't lose the signal silently
            self.extra[field_name] = self.extra.get(field_name, 0) + delta

    def to_log_line(self) -> str:
        """Compact one-line summary for NHAT_KY_PIPELINE / log grep.

        Format: ``wave06 | factcheck=P/R/V | rag=I/N | dateblock=N | numguard=N | 2src=V/S/C``
        Where:
          - factcheck: passed / rejected / needs_revision
          - rag: inject_count / no_match
          - dateblock: strip count
          - numguard: strip count
          - 2src: verified / single / conflict

        WHY single line: easy to grep + diff between runs in NHAT_KY_PIPELINE.
        WHY use slashes: visual cluster keeps related counters together.
        """
        return (
            f"wave06 | "
            f"factcheck={self.fact_check_passed}/{self.fact_check_rejected}"
            f"/{self.fact_check_needs_revision} | "
            f"rag={self.historical_inject_count}/{self.historical_no_match} | "
            f"dateblock={self.date_block_strip_count} | "
            f"numguard={self.numeric_guard_strip_count} | "
            f"2src={self.two_source_verified}/{self.two_source_single}"
            f"/{self.two_source_conflict}"
        )

    def is_empty(self) -> bool:
        """True if no Wave 0.6 feature counter was incremented this run.

        WHY useful: pipeline can skip the wave06 log line entirely when
        flags are OFF and nothing tracked — avoids noise in NHAT_KY_PIPELINE.
        """
        return (
            self.fact_check_passed == 0
            and self.fact_check_rejected == 0
            and self.fact_check_needs_revision == 0
            and self.historical_inject_count == 0
            and self.historical_no_match == 0
            and self.date_block_strip_count == 0
            and self.numeric_guard_strip_count == 0
            and self.two_source_verified == 0
            and self.two_source_single == 0
            and self.two_source_conflict == 0
            and not self.extra
        )
