"""Tests for core/quota_manager.py."""

import time

import pytest

from cic_daily_report.core.quota_manager import QuotaManager


class TestQuotaManager:
    @pytest.fixture
    def qm(self):
        return QuotaManager()

    def test_default_services_registered(self, qm):
        assert qm.can_call("groq") is True
        assert qm.can_call("gemini_flash") is True
        assert qm.can_call("cryptopanic") is True

    def test_unknown_service_always_allowed(self, qm):
        assert qm.can_call("unknown_service") is True

    def test_track_increments_counter(self, qm):
        qm.track("groq", 5)
        summary = qm.get_summary()
        assert summary["groq"] == "5/14400"

    def test_daily_limit_blocks(self, qm):
        qm.register_service("test_svc", daily_limit=2, rate_limit_per_min=0)
        qm.track("test_svc", 2)
        assert qm.can_call("test_svc") is False

    def test_rate_limit_blocks_rapid_calls(self, qm):
        qm.register_service("rate_test", daily_limit=1000, rate_limit_per_min=60)
        qm.track("rate_test", 1)
        # Immediately after tracking, rate limit should block
        assert qm.can_call("rate_test") is False

    def test_reset_clears_counters(self, qm):
        qm.track("groq", 100)
        qm.reset()
        summary = qm.get_summary()
        assert "groq" not in summary  # 0 calls = not in summary

    def test_track_unknown_service_auto_registers(self, qm):
        qm.track("new_service", 3)
        summary = qm.get_summary()
        assert "new_service" in summary

    def test_get_summary_only_active(self, qm):
        qm.track("groq", 1)
        summary = qm.get_summary()
        assert "groq" in summary
        assert "telegram" not in summary  # 0 calls

    def test_register_service(self, qm):
        qm.register_service("custom", daily_limit=50, rate_limit_per_min=10)
        assert qm.can_call("custom") is True
        qm.track("custom", 50)
        assert qm.can_call("custom") is False


class TestQuotaManagerAsync:
    @pytest.fixture
    def qm(self):
        return QuotaManager()

    async def test_wait_for_rate_limit_no_delay(self, qm):
        """Should return immediately for service with no prior calls."""
        qm.register_service("fast", daily_limit=1000, rate_limit_per_min=60)
        start = time.monotonic()
        await qm.wait_for_rate_limit("fast")
        elapsed = time.monotonic() - start
        assert elapsed < 0.1

    async def test_wait_for_unknown_service(self, qm):
        """Should return immediately for unknown service."""
        await qm.wait_for_rate_limit("nonexistent")


class TestQuotaBudget:
    """v0.28.0: Tests for remaining() and has_budget()."""

    @pytest.fixture
    def qm(self):
        return QuotaManager()

    def test_remaining_fresh_service_returns_daily_limit(self, qm):
        """remaining() on a fresh (zero calls) service returns the full daily_limit."""
        quota = qm._quotas["gemini_flash"]
        assert qm.remaining("gemini_flash") == quota.daily_limit

    def test_remaining_after_tracking_returns_reduced_amount(self, qm):
        """remaining() decreases by exactly the number of tracked calls."""
        quota = qm._quotas["gemini_flash"]
        initial_limit = quota.daily_limit
        qm.track("gemini_flash", 10)
        assert qm.remaining("gemini_flash") == initial_limit - 10

    def test_remaining_unknown_service_returns_sentinel(self, qm):
        """remaining() on an unregistered service returns 999999 (unlimited sentinel)."""
        assert qm.remaining("nonexistent_service") == 999999

    def test_has_budget_when_budget_available_returns_true(self, qm):
        """has_budget() returns True when remaining quota covers the needed calls."""
        # gemini_flash daily_limit=1500, zero calls made → plenty of budget
        assert qm.has_budget("gemini_flash", 5) is True

    def test_has_budget_when_budget_exhausted_returns_false(self, qm):
        """has_budget() returns False when daily limit has been reached."""
        qm.register_service("tight_svc", daily_limit=3, rate_limit_per_min=0)
        qm.track("tight_svc", 3)
        assert qm.has_budget("tight_svc", 1) is False


class TestTrackFailure:
    """v0.29.0 (A2): track_failure() updates timing but not daily counter."""

    @pytest.fixture
    def qm(self):
        return QuotaManager()

    def test_track_failure_does_not_increment_calls(self, qm):
        """Failed calls should not count against daily quota."""
        qm.register_service("test_svc", daily_limit=10, rate_limit_per_min=60)
        qm.track_failure("test_svc")
        assert qm.remaining("test_svc") == 10  # Unchanged

    def test_track_failure_updates_last_call_time(self, qm):
        """Failed calls update timing to prevent rapid-fire retries."""
        qm.register_service("test_svc", daily_limit=10, rate_limit_per_min=60)
        qm.track_failure("test_svc")
        # Rate limit should now block immediate retry
        assert qm.can_call("test_svc") is False

    def test_track_failure_unknown_service_no_crash(self, qm):
        """track_failure() on unknown service is a no-op."""
        qm.track_failure("nonexistent")  # Should not raise
