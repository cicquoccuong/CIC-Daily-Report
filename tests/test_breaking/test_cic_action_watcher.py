"""Tests for CIC Action Watcher (QO.42).

Covers: detect_action_changes, load_previous_snapshot, _parse_action_title,
ActionChange, ActionSnapshot.
"""

from __future__ import annotations

from dataclasses import dataclass

from cic_daily_report.breaking.cic_action_watcher import (
    EVENT_SOURCE,
    KNOWN_ACTIONS,
    ActionChange,
    ActionSnapshot,
    _parse_action_title,
    detect_action_changes,
    load_previous_snapshot,
)
from cic_daily_report.breaking.event_detector import BreakingEvent

# --- Helpers ---


@dataclass
class FakeCoin:
    """Minimal coin object mimicking Sentinel registry entries."""

    symbol: str
    cic_action: str


@dataclass
class FakeDedupEntry:
    """Minimal dedup entry for load_previous_snapshot tests."""

    title: str
    source: str
    status: str = "sent"
    detected_at: str = "2026-04-15T00:00:00"


# === ActionChange Tests ===


class TestActionChange:
    """Tests for ActionChange dataclass."""

    def test_to_event_title_basic(self):
        change = ActionChange(symbol="BTC", old_action="theo-doi", new_action="mua")
        title = change.to_event_title()
        assert "BTC" in title
        assert "theo-doi" in title
        assert "mua" in title
        # WHY: title must follow the exact format for _parse_action_title to work
        assert title == "CIC cap nhat: BTC chuyen tu 'theo-doi' sang 'mua'"

    def test_to_event_title_different_actions(self):
        change = ActionChange(symbol="ETH", old_action="mua", new_action="ban")
        title = change.to_event_title()
        assert "ETH" in title
        assert "mua" in title
        assert "ban" in title

    def test_action_change_timestamp(self):
        change = ActionChange(symbol="BTC", old_action="a", new_action="b", timestamp="2026-04-15")
        assert change.timestamp == "2026-04-15"


# === ActionSnapshot Tests ===


class TestActionSnapshot:
    """Tests for ActionSnapshot dataclass."""

    def test_empty_snapshot(self):
        snap = ActionSnapshot()
        assert snap.actions == {}
        assert snap.timestamp == ""

    def test_snapshot_with_data(self):
        snap = ActionSnapshot(actions={"BTC": "mua", "ETH": "theo-doi"}, timestamp="2026-04-15")
        assert snap.actions["BTC"] == "mua"
        assert snap.actions["ETH"] == "theo-doi"


# === detect_action_changes Tests ===


class TestDetectActionChanges:
    """Tests for detect_action_changes — core detection logic."""

    def test_first_run_no_previous_snapshot(self):
        """First run creates snapshot, no events generated."""
        registry = [
            FakeCoin("BTC", "mua"),
            FakeCoin("ETH", "theo-doi"),
        ]
        events, snapshot = detect_action_changes(registry, previous_snapshot=None)
        assert events == []
        assert snapshot.actions["BTC"] == "mua"
        assert snapshot.actions["ETH"] == "theo-doi"
        assert snapshot.timestamp != ""

    def test_no_changes_detected(self):
        """Same actions in both snapshots — no events."""
        registry = [
            FakeCoin("BTC", "mua"),
            FakeCoin("ETH", "theo-doi"),
        ]
        previous = ActionSnapshot(actions={"BTC": "mua", "ETH": "theo-doi"})
        events, snapshot = detect_action_changes(registry, previous)
        assert events == []
        # Snapshot should be updated
        assert snapshot.actions["BTC"] == "mua"

    def test_one_change_detected(self):
        """BTC changes from theo-doi to mua — one event."""
        registry = [
            FakeCoin("BTC", "mua"),
            FakeCoin("ETH", "theo-doi"),
        ]
        previous = ActionSnapshot(actions={"BTC": "theo-doi", "ETH": "theo-doi"})
        events, snapshot = detect_action_changes(registry, previous)
        assert len(events) == 1
        assert isinstance(events[0], BreakingEvent)
        assert "BTC" in events[0].title
        assert events[0].source == EVENT_SOURCE
        assert events[0].panic_score == 75
        assert events[0].raw_data["symbol"] == "BTC"
        assert events[0].raw_data["old_action"] == "theo-doi"
        assert events[0].raw_data["new_action"] == "mua"

    def test_multiple_changes_detected(self):
        """Both BTC and ETH change — two events."""
        registry = [
            FakeCoin("BTC", "ban"),
            FakeCoin("ETH", "giam"),
        ]
        previous = ActionSnapshot(actions={"BTC": "mua", "ETH": "theo-doi"})
        events, snapshot = detect_action_changes(registry, previous)
        assert len(events) == 2
        symbols = {e.raw_data["symbol"] for e in events}
        assert symbols == {"BTC", "ETH"}

    def test_new_coin_not_in_previous(self):
        """New coin appears in registry — no event (only changes trigger)."""
        registry = [
            FakeCoin("BTC", "mua"),
            FakeCoin("SOL", "theo-doi"),
        ]
        previous = ActionSnapshot(actions={"BTC": "mua"})
        events, snapshot = detect_action_changes(registry, previous)
        assert events == []
        # WHY: SOL is new, not a "change" from previous
        assert snapshot.actions["SOL"] == "theo-doi"

    def test_coin_removed_from_registry(self):
        """Coin disappears from registry — no event (only changes trigger)."""
        registry = [FakeCoin("BTC", "mua")]
        previous = ActionSnapshot(actions={"BTC": "mua", "ETH": "theo-doi"})
        events, snapshot = detect_action_changes(registry, previous)
        assert events == []
        assert "ETH" not in snapshot.actions

    def test_empty_registry(self):
        """Empty registry — no events, empty snapshot."""
        events, snapshot = detect_action_changes([], previous_snapshot=None)
        assert events == []
        assert snapshot.actions == {}

    def test_action_case_normalization(self):
        """Actions are lowercased and stripped before comparison."""
        registry = [FakeCoin("BTC", "  MUA  ")]
        previous = ActionSnapshot(actions={"BTC": "theo-doi"})
        events, snapshot = detect_action_changes(registry, previous)
        assert len(events) == 1
        # WHY: verify normalization happened
        assert snapshot.actions["BTC"] == "mua"

    def test_coin_without_action_skipped(self):
        """Coins with empty action are skipped."""
        registry = [FakeCoin("BTC", ""), FakeCoin("ETH", "mua")]
        previous = ActionSnapshot(actions={"ETH": "theo-doi"})
        events, snapshot = detect_action_changes(registry, previous)
        assert len(events) == 1
        assert "BTC" not in snapshot.actions

    def test_coin_without_symbol_skipped(self):
        """Coins with empty symbol are skipped."""
        registry = [FakeCoin("", "mua"), FakeCoin("ETH", "theo-doi")]
        events, snapshot = detect_action_changes(registry, previous_snapshot=None)
        assert "" not in snapshot.actions
        assert "ETH" in snapshot.actions

    def test_event_has_correct_url(self):
        """Events from action changes have empty URL (internal signal)."""
        registry = [FakeCoin("BTC", "ban")]
        previous = ActionSnapshot(actions={"BTC": "mua"})
        events, _ = detect_action_changes(registry, previous)
        assert events[0].url == ""


# === _parse_action_title Tests ===


class TestParseActionTitle:
    """Tests for _parse_action_title — title parsing helper."""

    def test_valid_title(self):
        title = "CIC cap nhat: BTC chuyen tu 'theo-doi' sang 'mua'"
        result = _parse_action_title(title)
        assert result is not None
        symbol, new_action = result
        assert symbol == "BTC"
        assert new_action == "mua"

    def test_different_actions(self):
        title = "CIC cap nhat: ETH chuyen tu 'mua' sang 'ban'"
        result = _parse_action_title(title)
        assert result == ("ETH", "ban")

    def test_invalid_prefix(self):
        title = "Something else: BTC chuyen tu 'a' sang 'b'"
        assert _parse_action_title(title) is None

    def test_missing_chuyen_tu(self):
        title = "CIC cap nhat: BTC changed from 'a' to 'b'"
        assert _parse_action_title(title) is None

    def test_missing_sang(self):
        title = "CIC cap nhat: BTC chuyen tu 'a' to 'b'"
        assert _parse_action_title(title) is None

    def test_empty_string(self):
        assert _parse_action_title("") is None

    def test_malformed_title(self):
        assert _parse_action_title("random text") is None


# === load_previous_snapshot Tests ===


class TestLoadPreviousSnapshot:
    """Tests for load_previous_snapshot — reconstruct from dedup entries."""

    def test_no_entries(self):
        """Empty dedup entries — returns None."""
        assert load_previous_snapshot([]) is None

    def test_no_matching_source(self):
        """Entries from other sources — returns None."""
        entries = [
            FakeDedupEntry(
                title="Some other event",
                source="cryptopanic",
            )
        ]
        assert load_previous_snapshot(entries) is None

    def test_single_action_entry(self):
        """One cic_action entry — snapshot with one coin."""
        entries = [
            FakeDedupEntry(
                title="CIC cap nhat: BTC chuyen tu 'theo-doi' sang 'mua'",
                source=EVENT_SOURCE,
            )
        ]
        snapshot = load_previous_snapshot(entries)
        assert snapshot is not None
        assert snapshot.actions["BTC"] == "mua"

    def test_multiple_action_entries(self):
        """Multiple entries for different coins."""
        entries = [
            FakeDedupEntry(
                title="CIC cap nhat: BTC chuyen tu 'theo-doi' sang 'mua'",
                source=EVENT_SOURCE,
            ),
            FakeDedupEntry(
                title="CIC cap nhat: ETH chuyen tu 'giam' sang 'theo-doi'",
                source=EVENT_SOURCE,
            ),
        ]
        snapshot = load_previous_snapshot(entries)
        assert snapshot is not None
        assert snapshot.actions["BTC"] == "mua"
        assert snapshot.actions["ETH"] == "theo-doi"

    def test_mixed_sources_filtered(self):
        """Only cic_sentinel_action entries are used."""
        entries = [
            FakeDedupEntry(
                title="CIC cap nhat: BTC chuyen tu 'theo-doi' sang 'mua'",
                source=EVENT_SOURCE,
            ),
            FakeDedupEntry(
                title="Some crypto news",
                source="cryptopanic",
            ),
        ]
        snapshot = load_previous_snapshot(entries)
        assert snapshot is not None
        assert len(snapshot.actions) == 1

    def test_unparseable_title_skipped(self):
        """Entries with unparseable titles are skipped gracefully."""
        entries = [
            FakeDedupEntry(
                title="malformed title without expected format",
                source=EVENT_SOURCE,
            ),
        ]
        snapshot = load_previous_snapshot(entries)
        assert snapshot is not None
        assert len(snapshot.actions) == 0

    def test_latest_action_wins(self):
        """If same coin appears multiple times, last entry wins."""
        entries = [
            FakeDedupEntry(
                title="CIC cap nhat: BTC chuyen tu 'theo-doi' sang 'mua'",
                source=EVENT_SOURCE,
            ),
            FakeDedupEntry(
                title="CIC cap nhat: BTC chuyen tu 'mua' sang 'ban'",
                source=EVENT_SOURCE,
            ),
        ]
        snapshot = load_previous_snapshot(entries)
        assert snapshot is not None
        # WHY: last entry overwrites — "ban" is the latest known action
        assert snapshot.actions["BTC"] == "ban"


# === Constants Tests ===


class TestConstants:
    """Verify module constants are correct."""

    def test_known_actions_set(self):
        assert "mua" in KNOWN_ACTIONS
        assert "theo-doi" in KNOWN_ACTIONS
        assert "giam" in KNOWN_ACTIONS
        assert "ban" in KNOWN_ACTIONS
        assert "ngung" in KNOWN_ACTIONS
        assert len(KNOWN_ACTIONS) == 5

    def test_event_source(self):
        assert EVENT_SOURCE == "cic_sentinel_action"
