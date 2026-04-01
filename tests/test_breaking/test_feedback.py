"""Tests for P1.10: Breaking news feedback loop (save + read).

Covers: file creation, append, day reset, format, round-trip, error handling.
Uses tmp_path fixture -- never writes to real data/ directory.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from cic_daily_report.breaking.feedback import (
    MAX_EVENTS_PER_DAY,
    MAX_FEEDBACK_FILE_SIZE,
    read_breaking_summary,
    save_breaking_summary,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _make_event(
    title: str = "BTC hits $100K",
    source: str = "CoinDesk",
    severity: str = "important",
    summary: str = "Bitcoin reached a new all-time high",
) -> dict:
    return {
        "title": title,
        "source": source,
        "severity": severity,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
    }


def _patch_paths(tmp_path: Path):
    """Return a context manager that redirects feedback file to tmp_path."""
    fb_dir = tmp_path / "data"
    fb_file = fb_dir / "breaking_today.json"
    return (
        patch("cic_daily_report.breaking.feedback._FEEDBACK_DIR", fb_dir),
        patch("cic_daily_report.breaking.feedback._FEEDBACK_FILE", fb_file),
        fb_dir,
        fb_file,
    )


# ---------------------------------------------------------------------------
# 1. save_breaking_summary creates file with correct structure
# ---------------------------------------------------------------------------
class TestSaveBreakingSummary:
    def test_creates_file(self, tmp_path: Path) -> None:
        p_dir, p_file, fb_dir, fb_file = _patch_paths(tmp_path)
        with p_dir, p_file:
            events = [_make_event()]
            save_breaking_summary(events)

            assert fb_file.exists()
            data = json.loads(fb_file.read_text(encoding="utf-8"))
            assert data["date"] == _TODAY
            assert len(data["events"]) == 1
            assert data["events"][0]["title"] == "BTC hits $100K"
            assert "last_updated" in data

    # 2. Second call appends, doesn't overwrite
    def test_appends_on_same_day(self, tmp_path: Path) -> None:
        p_dir, p_file, fb_dir, fb_file = _patch_paths(tmp_path)
        with p_dir, p_file:
            save_breaking_summary([_make_event(title="Event A")])
            save_breaking_summary([_make_event(title="Event B")])

            data = json.loads(fb_file.read_text(encoding="utf-8"))
            assert len(data["events"]) == 2
            assert data["events"][0]["title"] == "Event A"
            assert data["events"][1]["title"] == "Event B"

    # 3. Different date resets file
    def test_resets_on_new_day(self, tmp_path: Path) -> None:
        p_dir, p_file, fb_dir, fb_file = _patch_paths(tmp_path)
        with p_dir, p_file:
            # Write stale data with yesterday's date
            fb_dir.mkdir(parents=True, exist_ok=True)
            stale = {
                "date": "2020-01-01",
                "events": [_make_event(title="Yesterday")],
                "last_updated": "2020-01-01T00:00:00+00:00",
            }
            fb_file.write_text(json.dumps(stale), encoding="utf-8")

            # Save new event -- should reset
            save_breaking_summary([_make_event(title="Today")])

            data = json.loads(fb_file.read_text(encoding="utf-8"))
            assert data["date"] == _TODAY
            assert len(data["events"]) == 1
            assert data["events"][0]["title"] == "Today"

    # 8. data/ directory created if not exists
    def test_creates_data_dir(self, tmp_path: Path) -> None:
        fb_dir = tmp_path / "nonexistent" / "data"
        fb_file = fb_dir / "breaking_today.json"
        with (
            patch("cic_daily_report.breaking.feedback._FEEDBACK_DIR", fb_dir),
            patch("cic_daily_report.breaking.feedback._FEEDBACK_FILE", fb_file),
        ):
            save_breaking_summary([_make_event()])
            assert fb_dir.exists()
            assert fb_file.exists()

    def test_handles_invalid_json_in_existing_file(self, tmp_path: Path) -> None:
        """If existing file has corrupt JSON, save still works (resets)."""
        p_dir, p_file, fb_dir, fb_file = _patch_paths(tmp_path)
        with p_dir, p_file:
            fb_dir.mkdir(parents=True, exist_ok=True)
            fb_file.write_text("NOT VALID JSON {{{", encoding="utf-8")

            save_breaking_summary([_make_event(title="Fresh")])

            data = json.loads(fb_file.read_text(encoding="utf-8"))
            assert len(data["events"]) == 1
            assert data["events"][0]["title"] == "Fresh"


# ---------------------------------------------------------------------------
# read_breaking_summary tests
# ---------------------------------------------------------------------------
class TestReadBreakingSummary:
    # 4. Reads and formats events
    def test_returns_formatted_text(self, tmp_path: Path) -> None:
        p_dir, p_file, fb_dir, fb_file = _patch_paths(tmp_path)
        with p_dir, p_file:
            save_breaking_summary([_make_event(severity="critical")])

            result = read_breaking_summary()
            assert "BREAKING NEWS HOM NAY (1 tin)" in result
            assert "[CRITICAL]" in result
            assert "BTC hits $100K" in result

    # 5. No file returns ""
    def test_empty_when_no_file(self, tmp_path: Path) -> None:
        p_dir, p_file, fb_dir, fb_file = _patch_paths(tmp_path)
        with p_dir, p_file:
            assert read_breaking_summary() == ""

    # 6. Yesterday's data returns ""
    def test_stale_data_returns_empty(self, tmp_path: Path) -> None:
        p_dir, p_file, fb_dir, fb_file = _patch_paths(tmp_path)
        with p_dir, p_file:
            fb_dir.mkdir(parents=True, exist_ok=True)
            stale = {
                "date": "2020-01-01",
                "events": [_make_event()],
                "last_updated": "2020-01-01T00:00:00+00:00",
            }
            fb_file.write_text(json.dumps(stale), encoding="utf-8")

            assert read_breaking_summary() == ""

    # 7. Malformed file returns ""
    def test_invalid_json_returns_empty(self, tmp_path: Path) -> None:
        p_dir, p_file, fb_dir, fb_file = _patch_paths(tmp_path)
        with p_dir, p_file:
            fb_dir.mkdir(parents=True, exist_ok=True)
            fb_file.write_text("{{{NOT JSON", encoding="utf-8")

            assert read_breaking_summary() == ""

    def test_empty_events_list_returns_empty(self, tmp_path: Path) -> None:
        """File exists with today's date but no events."""
        p_dir, p_file, fb_dir, fb_file = _patch_paths(tmp_path)
        with p_dir, p_file:
            fb_dir.mkdir(parents=True, exist_ok=True)
            payload = {"date": _TODAY, "events": [], "last_updated": ""}
            fb_file.write_text(json.dumps(payload), encoding="utf-8")

            assert read_breaking_summary() == ""


# ---------------------------------------------------------------------------
# Format tests
# ---------------------------------------------------------------------------
class TestFormatting:
    # 10. Severity shown in brackets
    def test_severity_in_brackets(self, tmp_path: Path) -> None:
        p_dir, p_file, fb_dir, fb_file = _patch_paths(tmp_path)
        with p_dir, p_file:
            save_breaking_summary(
                [
                    _make_event(severity="critical"),
                    _make_event(title="ETH crash", severity="notable"),
                ]
            )
            result = read_breaking_summary()
            assert "[CRITICAL]" in result
            assert "[NOTABLE]" in result

    # 11. Summary truncated to 1000 chars (VD-20: increased from 200 for richer LLM context)
    def test_summary_truncation(self, tmp_path: Path) -> None:
        p_dir, p_file, fb_dir, fb_file = _patch_paths(tmp_path)
        with p_dir, p_file:
            long_summary = "A" * 1500
            save_breaking_summary([_make_event(summary=long_summary)])

            result = read_breaking_summary()
            # The summary line in output should be at most 1000 chars of content
            # (plus the "  " indent prefix)
            for line in result.split("\n"):
                if line.startswith("  "):
                    assert len(line.strip()) <= 1000

    # 12. Multiple events each on own line
    def test_multiple_events_formatted(self, tmp_path: Path) -> None:
        p_dir, p_file, fb_dir, fb_file = _patch_paths(tmp_path)
        with p_dir, p_file:
            save_breaking_summary(
                [
                    _make_event(title="Event 1"),
                    _make_event(title="Event 2"),
                    _make_event(title="Event 3"),
                ]
            )
            result = read_breaking_summary()
            assert "Event 1" in result
            assert "Event 2" in result
            assert "Event 3" in result
            assert "(3 tin)" in result

            # Each event starts with "- [" on its own line
            event_lines = [line for line in result.split("\n") if line.startswith("- [")]
            assert len(event_lines) == 3


# ---------------------------------------------------------------------------
# 9. Round-trip test
# ---------------------------------------------------------------------------
class TestRoundTrip:
    def test_save_then_read(self, tmp_path: Path) -> None:
        p_dir, p_file, fb_dir, fb_file = _patch_paths(tmp_path)
        with p_dir, p_file:
            events = [
                _make_event(title="Alpha event", severity="critical"),
                _make_event(title="Beta event", severity="important"),
            ]
            save_breaking_summary(events)

            result = read_breaking_summary()
            assert "Alpha event" in result
            assert "Beta event" in result
            assert "[CRITICAL]" in result
            assert "[IMPORTANT]" in result
            assert "(2 tin)" in result

    def test_multiple_saves_then_read(self, tmp_path: Path) -> None:
        """Multiple breaking runs in one day, then daily pipeline reads all."""
        p_dir, p_file, fb_dir, fb_file = _patch_paths(tmp_path)
        with p_dir, p_file:
            save_breaking_summary([_make_event(title="Morning event")])
            save_breaking_summary([_make_event(title="Afternoon event")])
            save_breaking_summary([_make_event(title="Evening event")])

            result = read_breaking_summary()
            assert "(3 tin)" in result
            assert "Morning event" in result
            assert "Evening event" in result


# ---------------------------------------------------------------------------
# BUG-10: Atomic write tests
# ---------------------------------------------------------------------------
class TestAtomicWrite:
    def test_no_tmp_files_left(self, tmp_path: Path) -> None:
        """BUG-10: After save, no .tmp files should remain in data dir."""
        p_dir, p_file, fb_dir, fb_file = _patch_paths(tmp_path)
        with p_dir, p_file:
            save_breaking_summary([_make_event()])
            assert fb_file.exists()
            # No leftover .tmp files
            tmp_files = list(fb_dir.glob("*.tmp"))
            assert tmp_files == []

    def test_file_valid_json_after_save(self, tmp_path: Path) -> None:
        """BUG-10: File is always valid JSON (atomic write prevents corruption)."""
        p_dir, p_file, fb_dir, fb_file = _patch_paths(tmp_path)
        with p_dir, p_file:
            save_breaking_summary([_make_event(title="First")])
            save_breaking_summary([_make_event(title="Second")])
            data = json.loads(fb_file.read_text(encoding="utf-8"))
            assert len(data["events"]) == 2


# ---------------------------------------------------------------------------
# SEC-02: File size limit tests
# ---------------------------------------------------------------------------
class TestFileSizeLimit:
    def test_oversized_file_returns_empty(self, tmp_path: Path) -> None:
        """SEC-02: File larger than MAX_FEEDBACK_FILE_SIZE returns empty."""
        p_dir, p_file, fb_dir, fb_file = _patch_paths(tmp_path)
        with p_dir, p_file:
            fb_dir.mkdir(parents=True, exist_ok=True)
            # Write a file larger than limit
            fb_file.write_text("x" * (MAX_FEEDBACK_FILE_SIZE + 1), encoding="utf-8")
            assert read_breaking_summary() == ""

    def test_normal_size_file_reads(self, tmp_path: Path) -> None:
        """SEC-02: File within size limit reads normally."""
        p_dir, p_file, fb_dir, fb_file = _patch_paths(tmp_path)
        with p_dir, p_file:
            save_breaking_summary([_make_event()])
            assert fb_file.stat().st_size < MAX_FEEDBACK_FILE_SIZE
            result = read_breaking_summary()
            assert "BTC hits $100K" in result


# ---------------------------------------------------------------------------
# SEC-06: Event cap tests
# ---------------------------------------------------------------------------
class TestEventCap:
    def test_events_capped_at_max(self, tmp_path: Path) -> None:
        """SEC-06: Events list capped at MAX_EVENTS_PER_DAY."""
        p_dir, p_file, fb_dir, fb_file = _patch_paths(tmp_path)
        with p_dir, p_file:
            # Save more than MAX_EVENTS_PER_DAY events
            events = [_make_event(title=f"Event {i}") for i in range(MAX_EVENTS_PER_DAY + 20)]
            save_breaking_summary(events)

            data = json.loads(fb_file.read_text(encoding="utf-8"))
            assert len(data["events"]) == MAX_EVENTS_PER_DAY

    def test_cap_keeps_latest_events(self, tmp_path: Path) -> None:
        """SEC-06: Cap keeps the latest (most recent) events, not the oldest."""
        p_dir, p_file, fb_dir, fb_file = _patch_paths(tmp_path)
        with p_dir, p_file:
            events = [_make_event(title=f"Event {i}") for i in range(MAX_EVENTS_PER_DAY + 5)]
            save_breaking_summary(events)

            data = json.loads(fb_file.read_text(encoding="utf-8"))
            # Last event should be in the list (latest kept)
            titles = [e["title"] for e in data["events"]]
            assert f"Event {MAX_EVENTS_PER_DAY + 4}" in titles
            # First event should be dropped (oldest removed)
            assert "Event 0" not in titles


# ---------------------------------------------------------------------------
# R5-06: Yesterday events for late UTC breaking news
# ---------------------------------------------------------------------------
class TestYesterdayEvents:
    def test_yesterday_events_included(self, tmp_path: Path) -> None:
        """R5-06: Yesterday's events are included (catches late UTC breaking)."""
        from datetime import timedelta

        p_dir, p_file, fb_dir, fb_file = _patch_paths(tmp_path)
        with p_dir, p_file:
            fb_dir.mkdir(parents=True, exist_ok=True)
            yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
            payload = {
                "date": yesterday,
                "events": [_make_event(title="Late night event")],
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
            fb_file.write_text(json.dumps(payload), encoding="utf-8")

            result = read_breaking_summary()
            assert "Late night event" in result

    def test_two_days_ago_excluded(self, tmp_path: Path) -> None:
        """R5-06: Events from 2+ days ago are still excluded."""
        from datetime import timedelta

        p_dir, p_file, fb_dir, fb_file = _patch_paths(tmp_path)
        with p_dir, p_file:
            fb_dir.mkdir(parents=True, exist_ok=True)
            two_days_ago = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")
            payload = {
                "date": two_days_ago,
                "events": [_make_event(title="Old event")],
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
            fb_file.write_text(json.dumps(payload), encoding="utf-8")

            result = read_breaking_summary()
            assert result == ""
