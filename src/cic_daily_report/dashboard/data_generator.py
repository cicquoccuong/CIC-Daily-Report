"""Dashboard Data Generator (Story 6.1, QĐ7) — JSON output for health dashboard.

Generates dashboard-data.json after every pipeline run with:
- last_run: timestamp + status
- llm_used: provider name + fallback info
- tier_delivery: per-tier status
- data_freshness: last collect time per source
- error_history: last 7 days errors
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from cic_daily_report.core.logger import get_logger

logger = get_logger("dashboard")


@dataclass
class LastRun:
    """Last pipeline run information (FR45)."""

    timestamp: str = ""
    status: str = "unknown"  # success / partial / error / no_events
    pipeline_type: str = "daily"  # daily / breaking
    duration_seconds: float = 0


@dataclass
class LLMStatus:
    """LLM provider usage information (FR46)."""

    provider: str = "none"
    is_fallback: bool = False
    model: str = ""


@dataclass
class TierStatus:
    """Per-tier delivery status (FR47)."""

    tier: str = ""
    status: str = "pending"  # sent / failed / skipped


@dataclass
class ErrorEntry:
    """Single error in error history (FR48)."""

    timestamp: str = ""
    code: str = ""
    message: str = ""
    severity: str = "warning"  # warning / error / critical


@dataclass
class DataFreshness:
    """Per-source data freshness (FR49)."""

    source: str = ""
    last_collected: str = ""
    status: str = "unknown"  # fresh / stale / expired


@dataclass
class DashboardData:
    """Complete dashboard data structure."""

    generated_at: str = ""
    last_run: LastRun = field(default_factory=LastRun)
    llm_used: LLMStatus = field(default_factory=LLMStatus)
    tier_delivery: list[TierStatus] = field(default_factory=list)
    error_history: list[ErrorEntry] = field(default_factory=list)
    data_freshness: list[DataFreshness] = field(default_factory=list)
    breaking_stats: dict = field(default_factory=dict)

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(asdict(self), ensure_ascii=False, indent=indent)

    @staticmethod
    def from_json(json_str: str) -> DashboardData:
        """Deserialize from JSON string."""
        data = json.loads(json_str)
        return _dict_to_dashboard(data)


def generate_dashboard_data(
    last_run: LastRun | None = None,
    llm_used: LLMStatus | None = None,
    tier_delivery: list[TierStatus] | None = None,
    error_history: list[ErrorEntry] | None = None,
    data_freshness: list[DataFreshness] | None = None,
    breaking_stats: dict | None = None,
) -> DashboardData:
    """Generate dashboard data structure.

    Args:
        last_run: Last pipeline run info.
        llm_used: LLM provider status.
        tier_delivery: Per-tier delivery status.
        error_history: Recent error history (last 7 days).
        data_freshness: Per-source freshness.
        breaking_stats: Breaking pipeline stats.

    Returns:
        DashboardData ready for JSON serialization.
    """
    dashboard = DashboardData(
        generated_at=datetime.now(timezone.utc).isoformat(),
        last_run=last_run or LastRun(),
        llm_used=llm_used or LLMStatus(),
        tier_delivery=tier_delivery or [],
        error_history=_trim_error_history(error_history or []),
        data_freshness=data_freshness or [],
        breaking_stats=breaking_stats or {},
    )

    logger.info(
        f"Dashboard data generated: status={dashboard.last_run.status}, "
        f"{len(dashboard.tier_delivery)} tiers, "
        f"{len(dashboard.error_history)} errors"
    )

    return dashboard


def merge_error_history(
    existing: list[ErrorEntry],
    new_errors: list[ErrorEntry],
    max_days: int = 7,
) -> list[ErrorEntry]:
    """Merge new errors into existing history, keeping last N days."""
    combined = existing + new_errors
    return _trim_error_history(combined, max_days)


def _trim_error_history(
    errors: list[ErrorEntry],
    max_days: int = 7,
) -> list[ErrorEntry]:
    """Remove errors older than max_days."""
    if not errors:
        return []

    now = datetime.now(timezone.utc)
    kept: list[ErrorEntry] = []

    for error in errors:
        if not error.timestamp:
            kept.append(error)  # Keep errors without timestamp
            continue
        try:
            ts = datetime.fromisoformat(error.timestamp)
            age_days = (now - ts).total_seconds() / 86400
            if age_days <= max_days:
                kept.append(error)
        except (ValueError, TypeError):
            kept.append(error)  # Keep malformed entries

    return kept


def _dict_to_dashboard(data: dict) -> DashboardData:
    """Convert raw dict to DashboardData."""
    last_run_data = data.get("last_run", {})
    llm_data = data.get("llm_used", {})

    return DashboardData(
        generated_at=data.get("generated_at", ""),
        last_run=LastRun(**last_run_data) if last_run_data else LastRun(),
        llm_used=LLMStatus(**llm_data) if llm_data else LLMStatus(),
        tier_delivery=[
            TierStatus(**t) for t in data.get("tier_delivery", [])
        ],
        error_history=[
            ErrorEntry(**e) for e in data.get("error_history", [])
        ],
        data_freshness=[
            DataFreshness(**d) for d in data.get("data_freshness", [])
        ],
        breaking_stats=data.get("breaking_stats", {}),
    )
