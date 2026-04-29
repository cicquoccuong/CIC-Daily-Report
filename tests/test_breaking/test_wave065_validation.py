"""Wave 0.6 Story 0.6.5 (alpha.23) — Tests for validation infrastructure.

Covers:
- replay_breaking.py: mock mode, date filter, regex detection, reduction math
- core/config.py kill switch: overrides 3 sub-flags, default OFF, log warning
- breaking/wave06_metrics.py: dataclass defaults, increment, log line, edges
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Add scripts/ to import path so test can import replay_breaking module
SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


# ---------------------------------------------------------------------------
# Replay script tests
# ---------------------------------------------------------------------------


class TestReplayScript:
    """Tests for scripts/replay_breaking.py."""

    def test_replay_script_mock_mode(self, tmp_path):
        """--mock mode runs end-to-end without API calls + writes report file."""
        import replay_breaking

        out = tmp_path / "report.md"
        report = asyncio.run(
            replay_breaking.run_replay(
                date_from="2026-04-27",
                date_to="2026-04-28",
                output_path=out,
                mock=True,
            )
        )
        assert out.exists()
        text = out.read_text(encoding="utf-8")
        assert "# Replay Report" in text
        assert "Mock mode: True" in text
        assert report.total_events == 2  # mock dataset has 2 events
        # Mock helper strips first historical pattern → new < old.
        assert report.new_hallucination_total < report.old_hallucination_total

    def test_replay_filter_date_range(self):
        """filter_events_by_date keeps only rows within [from, to] inclusive."""
        import replay_breaking

        rows = [
            {"Thời gian": "2026-04-26T10:00:00+00:00", "title": "before"},
            {"Thời gian": "2026-04-27T10:00:00+00:00", "title": "in1"},
            {"Thời gian": "2026-04-28T23:59:00+00:00", "title": "in2"},
            {"Thời gian": "2026-04-29T01:00:00+00:00", "title": "after"},
            {"Thời gian": "", "title": "empty"},  # malformed → skip
        ]
        out = replay_breaking.filter_events_by_date(rows, "2026-04-27", "2026-04-28")
        titles = [r["title"] for r in out]
        assert titles == ["in1", "in2"]

    def test_replay_detect_historical_claim(self):
        """count_historical_claims matches Vietnamese hallucination patterns."""
        import replay_breaking

        # "Lần cuối" + "năm 2021" → 2 distinct pattern types matched
        text = "BTC giảm 5%. Lần cuối Bitcoin giảm thế này vào năm 2021."
        assert replay_breaking.count_historical_claims(text) >= 2
        # Plain text with no historical claim → 0
        assert replay_breaking.count_historical_claims("BTC giảm 5%.") == 0
        # Empty input → 0 (no crash)
        assert replay_breaking.count_historical_claims("") == 0

    def test_replay_compute_reduction_percentage(self):
        """compute_reduction_percentage handles zero/full/partial cases."""
        import replay_breaking

        # 10 → 5 = 50% reduction
        assert replay_breaking.compute_reduction_percentage(10, 5) == 50.0
        # 10 → 0 = 100% reduction (full elimination)
        assert replay_breaking.compute_reduction_percentage(10, 0) == 100.0
        # 0 baseline → 0% (cannot reduce from nothing)
        assert replay_breaking.compute_reduction_percentage(0, 0) == 0.0
        assert replay_breaking.compute_reduction_percentage(0, 5) == 0.0
        # New > old → negative (regression)
        assert replay_breaking.compute_reduction_percentage(5, 10) == -100.0


# ---------------------------------------------------------------------------
# Kill switch tests
# ---------------------------------------------------------------------------


class TestKillSwitch:
    """Tests for WAVE_0_6_KILL_SWITCH master flag."""

    def _clear_env(self):
        """Helper: clear all Wave 0.6 env vars to known baseline."""
        for k in (
            "WAVE_0_6_KILL_SWITCH",
            "WAVE_0_6_ENABLED",
            "WAVE_0_6_DATE_BLOCK",
            "WAVE_0_6_2SOURCE_REQUIRED",
        ):
            os.environ.pop(k, None)

    def test_killswitch_overrides_all_flags(self):
        """When kill switch ON, all 3 sub-flags forced OFF regardless of env."""
        from cic_daily_report.core import config as cfg

        self._clear_env()
        try:
            os.environ["WAVE_0_6_ENABLED"] = "1"
            os.environ["WAVE_0_6_DATE_BLOCK"] = "1"
            os.environ["WAVE_0_6_2SOURCE_REQUIRED"] = "1"
            os.environ["WAVE_0_6_KILL_SWITCH"] = "1"
            assert cfg._wave_0_6_kill_switch_active() is True
            assert cfg._wave_0_6_enabled() is False
            assert cfg._wave_0_6_date_block_enabled() is False
            assert cfg._wave_0_6_2source_required() is False
        finally:
            self._clear_env()

    def test_killswitch_default_off(self):
        """With NO env set, kill switch is OFF and other flags follow their env."""
        from cic_daily_report.core import config as cfg

        self._clear_env()
        try:
            assert cfg._wave_0_6_kill_switch_active() is False
            # Other flags also default OFF (their own default behavior)
            assert cfg._wave_0_6_enabled() is False
            assert cfg._wave_0_6_date_block_enabled() is False
            assert cfg._wave_0_6_2source_required() is False

            # Now set sub-flags ON without kill switch → they take effect
            os.environ["WAVE_0_6_ENABLED"] = "1"
            assert cfg._wave_0_6_enabled() is True
        finally:
            self._clear_env()

    def test_killswitch_truthy_variants(self):
        """Kill switch accepts 1/true/yes/on (case-insensitive) — same pattern."""
        from cic_daily_report.core import config as cfg

        self._clear_env()
        try:
            for val in ("1", "true", "TRUE", "yes", "YES", "on", "ON"):
                os.environ["WAVE_0_6_KILL_SWITCH"] = val
                assert cfg._wave_0_6_kill_switch_active() is True, f"failed for {val!r}"
            for val in ("0", "false", "no", "off", "", "garbage"):
                os.environ["WAVE_0_6_KILL_SWITCH"] = val
                assert cfg._wave_0_6_kill_switch_active() is False, f"failed for {val!r}"
        finally:
            self._clear_env()


# ---------------------------------------------------------------------------
# Wave06Metrics tests
# ---------------------------------------------------------------------------


class TestWave06Metrics:
    """Tests for breaking/wave06_metrics.py."""

    def test_wave06metrics_dataclass_default(self):
        """All counters default to 0 + extras dict default empty."""
        from cic_daily_report.breaking.wave06_metrics import Wave06Metrics

        m = Wave06Metrics()
        assert m.fact_check_passed == 0
        assert m.fact_check_rejected == 0
        assert m.fact_check_needs_revision == 0
        assert m.historical_inject_count == 0
        assert m.historical_no_match == 0
        assert m.date_block_strip_count == 0
        assert m.numeric_guard_strip_count == 0
        assert m.two_source_verified == 0
        assert m.two_source_single == 0
        assert m.two_source_conflict == 0
        assert m.extra == {}
        assert m.is_empty() is True

    def test_wave06metrics_increment_methods(self):
        """increment() bumps known fields + stashes unknown in extras."""
        from cic_daily_report.breaking.wave06_metrics import Wave06Metrics

        m = Wave06Metrics()
        m.increment("two_source_verified")
        m.increment("two_source_verified", delta=2)
        m.increment("date_block_strip_count", delta=5)
        m.increment("unknown_metric", delta=3)  # → extras

        assert m.two_source_verified == 3
        assert m.date_block_strip_count == 5
        assert m.extra == {"unknown_metric": 3}
        assert m.is_empty() is False

    def test_wave06metrics_to_log_line_format(self):
        """to_log_line returns deterministic single-line format with all counters."""
        from cic_daily_report.breaking.wave06_metrics import Wave06Metrics

        m = Wave06Metrics(
            fact_check_passed=5,
            fact_check_rejected=2,
            fact_check_needs_revision=1,
            historical_inject_count=8,
            historical_no_match=3,
            date_block_strip_count=4,
            numeric_guard_strip_count=2,
            two_source_verified=6,
            two_source_single=2,
            two_source_conflict=1,
        )
        line = m.to_log_line()
        # Single line, no newlines
        assert "\n" not in line
        # Contains all counter labels and values
        assert "factcheck=5/2/1" in line
        assert "rag=8/3" in line
        assert "dateblock=4" in line
        assert "numguard=2" in line
        assert "2src=6/2/1" in line
        assert line.startswith("wave06 |")

    def test_wave06metrics_is_empty_edge(self):
        """is_empty False if ONLY extras populated (no known counter)."""
        from cic_daily_report.breaking.wave06_metrics import Wave06Metrics

        m = Wave06Metrics()
        assert m.is_empty() is True
        m.extra["custom"] = 1
        assert m.is_empty() is False

    def test_wave06metrics_all_rejected_scenario(self):
        """Edge: all events fact-check-rejected → log line still emits, is_empty False."""
        from cic_daily_report.breaking.wave06_metrics import Wave06Metrics

        m = Wave06Metrics(fact_check_rejected=10)
        assert m.is_empty() is False
        line = m.to_log_line()
        assert "factcheck=0/10/0" in line
