"""Dashboard — health data generator for GitHub Pages (QĐ7)."""

from cic_daily_report.dashboard.data_generator import (
    DashboardData,
    DataFreshness,
    ErrorEntry,
    LastRun,
    LLMStatus,
    TierStatus,
    generate_dashboard_data,
)

__all__ = [
    "DashboardData",
    "DataFreshness",
    "ErrorEntry",
    "LastRun",
    "LLMStatus",
    "TierStatus",
    "generate_dashboard_data",
]
