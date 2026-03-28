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

    # 11. Summary truncated to 200 chars
    def test_summary_truncation(self, tmp_path: Path) -> None:
        p_dir, p_file, fb_dir, fb_file = _patch_paths(tmp_path)
        with p_dir, p_file:
            long_summary = "A" * 300
            save_breaking_summary([_make_event(summary=long_summary)])

            result = read_breaking_summary()
            # The summary line in output should be at most 200 chars of content
            # (plus the "  " indent prefix)
            for line in result.split("\n"):
                if line.startswith("  "):
                    assert len(line.strip()) <= 200

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
