"""Tests for dashboard/data_generator.py."""

import json
from datetime import datetime, timedelta, timezone

from cic_daily_report.dashboard.data_generator import (
    DashboardData,
    DataFreshness,
    ErrorEntry,
    LastRun,
    LLMStatus,
    TierStatus,
    generate_dashboard_data,
    merge_error_history,
)


class TestLastRun:
    def test_defaults(self):
        lr = LastRun()
        assert lr.status == "unknown"
        assert lr.pipeline_type == "daily"

    def test_custom(self):
        lr = LastRun(timestamp="2026-03-09", status="success", duration_seconds=120)
        assert lr.status == "success"
        assert lr.duration_seconds == 120


class TestDashboardData:
    def test_to_json_valid(self):
        data = generate_dashboard_data(
            last_run=LastRun(timestamp="2026-03-09", status="success"),
            llm_used=LLMStatus(provider="groq", model="llama-3.3"),
            tier_delivery=[
                TierStatus(tier="L1", status="sent"),
                TierStatus(tier="L2", status="sent"),
            ],
        )
        json_str = data.to_json()
        parsed = json.loads(json_str)
        assert parsed["last_run"]["status"] == "success"
        assert len(parsed["tier_delivery"]) == 2

    def test_from_json_roundtrip(self):
        original = generate_dashboard_data(
            last_run=LastRun(timestamp="2026-03-09", status="partial"),
            llm_used=LLMStatus(provider="gemini_flash", is_fallback=True),
        )
        json_str = original.to_json()
        restored = DashboardData.from_json(json_str)
        assert restored.last_run.status == "partial"
        assert restored.llm_used.provider == "gemini_flash"
        assert restored.llm_used.is_fallback

    def test_generated_at_present(self):
        data = generate_dashboard_data()
        assert data.generated_at != ""

    def test_all_required_fields_in_json(self):
        data = generate_dashboard_data()
        json_str = data.to_json()
        parsed = json.loads(json_str)
        required = [
            "generated_at",
            "last_run",
            "llm_used",
            "tier_delivery",
            "error_history",
            "data_freshness",
            "breaking_stats",
        ]
        for field_name in required:
            assert field_name in parsed, f"Missing field: {field_name}"

    def test_json_has_last_run_fields(self):
        data = generate_dashboard_data(
            last_run=LastRun(
                timestamp="2026-03-09T01:00:00+00:00",
                status="success",
                pipeline_type="daily",
                duration_seconds=180.5,
            )
        )
        parsed = json.loads(data.to_json())
        lr = parsed["last_run"]
        assert lr["timestamp"] == "2026-03-09T01:00:00+00:00"
        assert lr["status"] == "success"
        assert lr["pipeline_type"] == "daily"
        assert lr["duration_seconds"] == 180.5


class TestTierDelivery:
    def test_all_tiers_tracked(self):
        tiers = [TierStatus(tier=f"L{i}", status="sent") for i in range(1, 6)]
        tiers.append(TierStatus(tier="Summary", status="sent"))
        data = generate_dashboard_data(tier_delivery=tiers)
        assert len(data.tier_delivery) == 6

    def test_mixed_status(self):
        tiers = [
            TierStatus(tier="L1", status="sent"),
            TierStatus(tier="L2", status="failed"),
            TierStatus(tier="L3", status="skipped"),
        ]
        data = generate_dashboard_data(tier_delivery=tiers)
        statuses = {t.tier: t.status for t in data.tier_delivery}
        assert statuses["L1"] == "sent"
        assert statuses["L2"] == "failed"
        assert statuses["L3"] == "skipped"


class TestErrorHistory:
    def test_trims_old_errors(self):
        old = ErrorEntry(
            timestamp=(datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
            code="ERR1",
            message="Old error",
        )
        recent = ErrorEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            code="ERR2",
            message="Recent error",
        )
        data = generate_dashboard_data(error_history=[old, recent])
        assert len(data.error_history) == 1
        assert data.error_history[0].code == "ERR2"

    def test_keeps_7_day_errors(self):
        errors = [
            ErrorEntry(
                timestamp=(datetime.now(timezone.utc) - timedelta(days=i)).isoformat(),
                code=f"ERR{i}",
                message=f"Error {i}",
            )
            for i in range(7)
        ]
        data = generate_dashboard_data(error_history=errors)
        assert len(data.error_history) == 7

    def test_empty_errors(self):
        data = generate_dashboard_data(error_history=[])
        assert data.error_history == []

    def test_empty_timestamp_gets_default(self):
        """Errors with empty timestamp should get a default (current time)."""
        error = ErrorEntry(
            timestamp="",
            code="ERR_NO_TS",
            message="Error without timestamp",
        )
        data = generate_dashboard_data(error_history=[error])
        # _trim_error_history assigns a default timestamp to empty ones
        assert len(data.error_history) == 1
        assert data.error_history[0].timestamp != ""
        # Verify it's a valid ISO timestamp
        parsed = datetime.fromisoformat(data.error_history[0].timestamp)
        assert parsed.year >= 2026


class TestMergeErrorHistory:
    def test_merges_new_errors(self):
        existing = [
            ErrorEntry(
                timestamp=datetime.now(timezone.utc).isoformat(),
                code="OLD",
                message="old",
            )
        ]
        new = [
            ErrorEntry(
                timestamp=datetime.now(timezone.utc).isoformat(),
                code="NEW",
                message="new",
            )
        ]
        result = merge_error_history(existing, new)
        assert len(result) == 2

    def test_drops_old_after_merge(self):
        old = [
            ErrorEntry(
                timestamp=(datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
                code="OLD",
                message="old",
            )
        ]
        new = [
            ErrorEntry(
                timestamp=datetime.now(timezone.utc).isoformat(),
                code="NEW",
                message="new",
            )
        ]
        result = merge_error_history(old, new)
        assert len(result) == 1
        assert result[0].code == "NEW"


class TestDataFreshness:
    def test_freshness_tracked(self):
        sources = [
            DataFreshness(source="rss", last_collected="2026-03-09T01:00:00", status="fresh"),
            DataFreshness(
                source="cryptopanic", last_collected="2026-03-09T00:30:00", status="stale"
            ),
        ]
        data = generate_dashboard_data(data_freshness=sources)
        assert len(data.data_freshness) == 2
        assert data.data_freshness[0].status == "fresh"

    def test_from_json_preserves_freshness(self):
        sources = [DataFreshness(source="rss", last_collected="2026-03-09", status="fresh")]
        data = generate_dashboard_data(data_freshness=sources)
        restored = DashboardData.from_json(data.to_json())
        assert restored.data_freshness[0].source == "rss"


class TestBreakingStats:
    def test_breaking_stats_included(self):
        stats = {"events_detected": 5, "events_sent": 3, "events_deferred": 2}
        data = generate_dashboard_data(breaking_stats=stats)
        assert data.breaking_stats["events_detected"] == 5

    def test_empty_breaking_stats(self):
        data = generate_dashboard_data()
        assert data.breaking_stats == {}
