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
    # WHY: "gemini" is the shared rate_key used by generate() for all Gemini models.
    # Must match gemini_flash/gemini_flash_lite limits (250 RPD free tier).
    "gemini": {"daily_limit": 250, "rate_limit_per_min": 10},
    "groq": {"daily_limit": 1000, "rate_limit_per_min": 60},
    "groq_llama4": {"daily_limit": 1000, "rate_limit_per_min": 30},
    "cerebras": {"daily_limit": 1000, "rate_limit_per_min": 30},
    "gemini_flash": {
        "daily_limit": 250,
        "rate_limit_per_min": 10,
    },  # Free tier 250 RPD, 10 RPM (VĐ15)
    "gemini_flash_lite": {
        "daily_limit": 250,
        "rate_limit_per_min": 10,
    },  # Free tier 250 RPD, 10 RPM (VĐ15)
    "cryptopanic": {"daily_limit": 15, "rate_limit_per_min": 5},
    "google_sheets": {"daily_limit": 60000, "rate_limit_per_min": 60},
    "telegram": {"daily_limit": 100000, "rate_limit_per_min": 30},
}


class QuotaManager:
    """Track and enforce API quotas across all services."""

    def __init__(self) -> None:
        self._quotas: dict[str, ServiceQuota] = {}
        # WHY: per-service asyncio.Lock prevents race in wait_for_rate_limit() when
        # asyncio.gather() launches >=2 coroutines on same service — each would otherwise
        # read stale last_call_time before any caller's track() bumps it, all bypassing
        # the rate limit and triggering 429s. Per-service (not global) avoids head-of-line
        # blocking across independent providers (e.g. gemini vs groq).
        self._locks: dict[str, asyncio.Lock] = {}
        for name, config in DEFAULT_QUOTAS.items():
            self._quotas[name] = ServiceQuota(name=name, **config)

    def _get_lock(self, service: str) -> asyncio.Lock:
        """Lazy-create per-service lock. Safe: single-threaded asyncio event loop."""
        lock = self._locks.get(service)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[service] = lock
        return lock

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

    def track_failure(self, service: str) -> None:
        """Record a failed API call — updates timing but not daily counter.

        v0.29.0: Ensures wait_for_rate_limit() respects interval after 429 errors,
        preventing rapid-fire retries against rate-limited providers.
        """
        quota = self._quotas.get(service)
        if quota is None:
            return
        quota.last_call_time = time.monotonic()

    async def wait_for_rate_limit(self, service: str) -> None:
        """Wait until rate limit allows the next call.

        Race-safe: serializes per-service via asyncio.Lock and reserves the slot
        by bumping last_call_time BEFORE returning. Subsequent gather()-ed callers
        on the same service see the reservation and sleep correctly. The real
        track() call later overwrites with a fresher timestamp (monotonic, OK).
        """
        quota = self._quotas.get(service)
        if quota is None or quota.rate_limit_per_min <= 0:
            return

        async with self._get_lock(service):
            min_interval = 60.0 / quota.rate_limit_per_min
            elapsed = time.monotonic() - quota.last_call_time
            if elapsed < min_interval:
                wait_time = min_interval - elapsed
                logger.debug(f"Rate limit: waiting {wait_time:.1f}s for {service}")
                await asyncio.sleep(wait_time)
            # WHY: reserve slot under lock so concurrent waiters compute their wait
            # against THIS reservation, not the stale pre-sleep value.
            quota.last_call_time = time.monotonic()

    def remaining(self, service: str) -> int:
        """Return remaining daily quota for a service.

        v0.28.0: Used by pipeline to check if enough budget exists
        before attempting optional tasks (research, summary).
        """
        quota = self._quotas.get(service)
        if quota is None:
            return 999999  # unknown service = unlimited
        return max(0, quota.daily_limit - quota.calls_made)

    def has_budget(self, service: str, needed: int) -> bool:
        """Check if enough daily quota remains for a task.

        Args:
            service: Service name (e.g., "gemini_flash").
            needed: Number of calls the task will make.
        """
        return self.remaining(service) >= needed

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
