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
