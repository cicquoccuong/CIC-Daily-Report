"""Centralized quota manager — tracks API usage, enforces rate limits."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from cic_daily_report.core.logger import get_logger

logger = get_logger("quota_manager")


@dataclass
class ServiceQuota:
    """Quota config for a single API service."""

    name: str
    daily_limit: int
    rate_limit_per_min: int
    calls_made: int = 0
    last_call_time: float = 0.0


# Pre-configured service quotas (free tiers)
DEFAULT_QUOTAS: dict[str, dict[str, int]] = {
    "groq": {"daily_limit": 14400, "rate_limit_per_min": 6},  # ~10s between calls to avoid TPM 429
    "gemini_flash": {"daily_limit": 1500, "rate_limit_per_min": 15},
    "gemini_flash_lite": {"daily_limit": 1500, "rate_limit_per_min": 15},
    "cryptopanic": {"daily_limit": 5000, "rate_limit_per_min": 5},
    "google_sheets": {"daily_limit": 60000, "rate_limit_per_min": 60},
    "telegram": {"daily_limit": 100000, "rate_limit_per_min": 30},
}


class QuotaManager:
    """Track and enforce API quotas across all services."""

    def __init__(self) -> None:
        self._quotas: dict[str, ServiceQuota] = {}
        for name, config in DEFAULT_QUOTAS.items():
            self._quotas[name] = ServiceQuota(name=name, **config)

    def register_service(self, name: str, daily_limit: int, rate_limit_per_min: int) -> None:
        """Register or update a service quota."""
        self._quotas[name] = ServiceQuota(
            name=name,
            daily_limit=daily_limit,
            rate_limit_per_min=rate_limit_per_min,
        )

    def can_call(self, service: str) -> bool:
        """Check if a service call is allowed (within quota and rate limit)."""
        quota = self._quotas.get(service)
        if quota is None:
            return True  # unknown service = no limit

        if quota.calls_made >= quota.daily_limit:
            return False

        # Check rate limit (min delay between calls)
        if quota.rate_limit_per_min > 0:
            min_interval = 60.0 / quota.rate_limit_per_min
            elapsed = time.monotonic() - quota.last_call_time
            if elapsed < min_interval:
                return False

        return True

    def track(self, service: str, count: int = 1) -> None:
        """Record API call(s) for a service."""
        quota = self._quotas.get(service)
        if quota is None:
            self._quotas[service] = ServiceQuota(
                name=service, daily_limit=999999, rate_limit_per_min=0, calls_made=count
            )
            return

        quota.calls_made += count
        quota.last_call_time = time.monotonic()

        usage_pct = (quota.calls_made / quota.daily_limit * 100) if quota.daily_limit > 0 else 0
        if usage_pct >= 80:
            logger.warning(f"{service}: {quota.calls_made}/{quota.daily_limit} ({usage_pct:.0f}%)")

    async def wait_for_rate_limit(self, service: str) -> None:
        """Wait until rate limit allows the next call."""
        quota = self._quotas.get(service)
        if quota is None or quota.rate_limit_per_min <= 0:
            return

        min_interval = 60.0 / quota.rate_limit_per_min
        elapsed = time.monotonic() - quota.last_call_time
        if elapsed < min_interval:
            wait_time = min_interval - elapsed
            logger.debug(f"Rate limit: waiting {wait_time:.1f}s for {service}")
            await asyncio.sleep(wait_time)

    def get_summary(self) -> dict[str, str]:
        """Get quota usage summary for all services."""
        summary = {}
        for name, q in sorted(self._quotas.items()):
            if q.calls_made > 0:
                summary[name] = f"{q.calls_made}/{q.daily_limit}"
        return summary

    def reset(self) -> None:
        """Reset all counters (call at start of each pipeline run)."""
        for quota in self._quotas.values():
            quota.calls_made = 0
            quota.last_call_time = 0.0
