"""Tests for breaking/dedup_manager.py."""

from datetime import datetime, timedelta, timezone

from cic_daily_report.breaking.dedup_manager import (
    DedupEntry,
    DedupManager,
    compute_hash,
)
from cic_daily_report.breaking.event_detector import BreakingEvent


def _event(title="BTC hack", source="CoinDesk") -> BreakingEvent:
    return BreakingEvent(title=title, source=source, url="https://x.com", panic_score=80)


class TestComputeHash:
    def test_deterministic(self):
        h1 = compute_hash("BTC hack", "CoinDesk")
        h2 = compute_hash("BTC hack", "CoinDesk")
        assert h1 == h2

    def test_case_insensitive(self):
        h1 = compute_hash("BTC HACK", "COINDESK")
        h2 = compute_hash("btc hack", "coindesk")
        assert h1 == h2

    def test_different_inputs(self):
        h1 = compute_hash("BTC hack", "CoinDesk")
        h2 = compute_hash("ETH crash", "Reuters")
        assert h1 != h2

    def test_trims_whitespace(self):
        h1 = compute_hash("  BTC hack  ", "  CoinDesk  ")
        h2 = compute_hash("BTC hack", "CoinDesk")
        assert h1 == h2


class TestDedupEntry:
    def test_to_row(self):
        e = DedupEntry(
            hash="abc123",
            title="Test",
            source="Src",
            severity="critical",
            detected_at="2026-01-01T00:00:00+00:00",
            status="sent",
            delivered_at="2026-01-01T00:05:00+00:00",
        )
        row = e.to_row()
        # Schema: ID, Thời gian, Tiêu đề, Hash, Nguồn, Mức độ, Trạng thái gửi, URL, Thời gian gửi
        assert len(row) == 9
        assert row[0] == ""  # ID (auto)
        assert row[1] == "2026-01-01T00:00:00+00:00"  # detected_at
        assert row[2] == "Test"  # title
        assert row[3] == "abc123"  # hash
        assert row[6] == "sent"  # status
        assert row[8] == "2026-01-01T00:05:00+00:00"  # delivered_at

    def test_from_row(self):
        # Schema: ID, Thời gian, Tiêu đề, Hash, Nguồn, Mức độ, Trạng thái gửi, URL, Thời gian gửi
        row = [
            "1",
            "2026-01-01",
            "Title",
            "abc",
            "Src",
            "critical",
            "sent",
            "https://x.com",
            "2026-01-01T00:05:00",
        ]
        e = DedupEntry.from_row(row)
        assert e.hash == "abc"
        assert e.title == "Title"
        assert e.status == "sent"
        assert e.url == "https://x.com"
        assert e.delivered_at == "2026-01-01T00:05:00"

    def test_from_row_short(self):
        e = DedupEntry.from_row(["1", "2026-01-01", "Title", "abc"])
        assert e.hash == "abc"
        assert e.title == "Title"


class TestDedupManager:
    def test_new_event_passes(self):
        mgr = DedupManager()
        result = mgr.check_and_filter([_event()])
        assert len(result.new_events) == 1
        assert result.duplicates_skipped == 0

    def test_duplicate_skipped(self):
        mgr = DedupManager()
        mgr.check_and_filter([_event()])
        result = mgr.check_and_filter([_event()])
        assert len(result.new_events) == 0
        assert result.duplicates_skipped == 1

    def test_different_events_both_pass(self):
        mgr = DedupManager()
        events = [_event("BTC hack", "CoinDesk"), _event("ETH crash", "Reuters")]
        result = mgr.check_and_filter(events)
        assert len(result.new_events) == 2

    def test_cooldown_expired_passes(self):
        old_time = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        existing = DedupEntry(
            hash=compute_hash("BTC hack", "CoinDesk"),
            title="BTC hack",
            source="CoinDesk",
            detected_at=old_time,
        )
        mgr = DedupManager(existing_entries=[existing])
        result = mgr.check_and_filter([_event()])
        assert len(result.new_events) == 1

    def test_cooldown_active_blocks(self):
        recent_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        existing = DedupEntry(
            hash=compute_hash("BTC hack", "CoinDesk"),
            title="BTC hack",
            source="CoinDesk",
            detected_at=recent_time,
        )
        mgr = DedupManager(existing_entries=[existing])
        result = mgr.check_and_filter([_event()])
        assert len(result.new_events) == 0
        assert result.duplicates_skipped == 1

    def test_entries_written_recorded(self):
        mgr = DedupManager()
        result = mgr.check_and_filter([_event()])
        assert len(result.entries_written) == 1
        assert result.entries_written[0].status == "pending"

    def test_url_stored_in_entry(self):
        mgr = DedupManager()
        result = mgr.check_and_filter([_event()])
        assert result.entries_written[0].url == "https://x.com"


class TestDedupManagerCleanup:
    def test_removes_old_entries(self):
        old_time = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        entries = [DedupEntry(hash="old", title="Old", source="S", detected_at=old_time)]
        mgr = DedupManager(existing_entries=entries)
        removed = mgr.cleanup_old_entries()
        assert removed == 1
        assert len(mgr.entries) == 0

    def test_keeps_recent_entries(self):
        recent_time = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        entries = [DedupEntry(hash="new", title="New", source="S", detected_at=recent_time)]
        mgr = DedupManager(existing_entries=entries)
        removed = mgr.cleanup_old_entries()
        assert removed == 0
        assert len(mgr.entries) == 1

    def test_removes_entries_without_timestamp(self):
        entries = [DedupEntry(hash="bad", title="Bad", source="S", detected_at="")]
        mgr = DedupManager(existing_entries=entries)
        removed = mgr.cleanup_old_entries()
        assert removed == 1


class TestDedupManagerStatus:
    def test_update_status(self):
        mgr = DedupManager()
        mgr.check_and_filter([_event()])
        h = compute_hash("BTC hack", "CoinDesk")
        assert mgr.update_entry_status(h, "sent", "2026-01-01T00:00:00+00:00")
        entry = mgr._hash_map[h]
        assert entry.status == "sent"

    def test_update_nonexistent_returns_false(self):
        mgr = DedupManager()
        assert not mgr.update_entry_status("nonexistent", "sent")

    def test_get_deferred_events(self):
        entries = [
            DedupEntry(hash="a", title="A", source="S", status="deferred_to_morning"),
            DedupEntry(hash="b", title="B", source="S", status="sent"),
            DedupEntry(hash="c", title="C", source="S", status="deferred_to_morning"),
        ]
        mgr = DedupManager(existing_entries=entries)
        deferred = mgr.get_deferred_events("deferred_to_morning")
        assert len(deferred) == 2

    def test_all_rows(self):
        mgr = DedupManager()
        mgr.check_and_filter([_event()])
        rows = mgr.all_rows()
        assert len(rows) == 1
        assert len(rows[0]) == 9
