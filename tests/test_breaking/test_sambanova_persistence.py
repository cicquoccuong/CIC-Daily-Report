"""Tests for SambaNova daily usage counter persistence (Fix 3).

WHY: Module-level counter resets each process. With 4 runs/day, could
attempt 80 API calls against 20 RPD quota. File-based persistence
tracks calls across process restarts within the same day.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from cic_daily_report.breaking.event_detector import BreakingEvent
from cic_daily_report.breaking.llm_scorer import (
    _get_usage_file_path,
    _load_daily_count,
    _save_daily_count,
    get_sambanova_calls_today,
    reset_sambanova_counter,
    score_event_impact,
)


def _event(title="BTC hack"):
    return BreakingEvent(
        title=title,
        source="CoinDesk",
        url="https://example.com",
        panic_score=80,
        raw_data={"summary": "Major event occurred"},
    )


# ============================================================================
# _get_usage_file_path
# ============================================================================


class TestGetUsageFilePath:
    def test_uses_github_workspace_when_set(self):
        with patch.dict(os.environ, {"GITHUB_WORKSPACE": "/tmp/repo"}):
            path = _get_usage_file_path()
        assert path.startswith("/tmp/repo")
        assert path.endswith("sambanova_usage.json")

    def test_uses_tempdir_when_no_github_workspace(self):
        env = os.environ.copy()
        env.pop("GITHUB_WORKSPACE", None)
        with patch.dict(os.environ, env, clear=True):
            path = _get_usage_file_path()
        assert path.endswith("sambanova_usage.json")


# ============================================================================
# _load_daily_count / _save_daily_count
# ============================================================================


class TestLoadSaveDailyCount:
    def test_save_and_load_roundtrip(self, tmp_path):
        """Save count, then load it back — same day."""
        usage_file = str(tmp_path / "sambanova_usage.json")
        with patch(
            "cic_daily_report.breaking.llm_scorer._get_usage_file_path",
            return_value=usage_file,
        ):
            _save_daily_count(7)
            count = _load_daily_count()
        assert count == 7

    def test_load_returns_0_when_file_missing(self, tmp_path):
        """No file → count = 0."""
        usage_file = str(tmp_path / "nonexistent.json")
        with patch(
            "cic_daily_report.breaking.llm_scorer._get_usage_file_path",
            return_value=usage_file,
        ):
            count = _load_daily_count()
        assert count == 0

    def test_load_returns_0_when_date_is_stale(self, tmp_path):
        """File exists but date is yesterday → count = 0."""
        usage_file = str(tmp_path / "sambanova_usage.json")
        with open(usage_file, "w") as f:
            json.dump({"date": "2020-01-01", "calls": 15}, f)
        with patch(
            "cic_daily_report.breaking.llm_scorer._get_usage_file_path",
            return_value=usage_file,
        ):
            count = _load_daily_count()
        assert count == 0

    def test_load_returns_0_on_corrupt_json(self, tmp_path):
        """Corrupt JSON → count = 0 (graceful)."""
        usage_file = str(tmp_path / "sambanova_usage.json")
        with open(usage_file, "w") as f:
            f.write("not json at all")
        with patch(
            "cic_daily_report.breaking.llm_scorer._get_usage_file_path",
            return_value=usage_file,
        ):
            count = _load_daily_count()
        assert count == 0

    def test_save_overwrites_previous(self, tmp_path):
        """Successive saves overwrite the file."""
        usage_file = str(tmp_path / "sambanova_usage.json")
        with patch(
            "cic_daily_report.breaking.llm_scorer._get_usage_file_path",
            return_value=usage_file,
        ):
            _save_daily_count(3)
            _save_daily_count(5)
            count = _load_daily_count()
        assert count == 5

    def test_save_writes_today_date(self, tmp_path):
        """File contains today's date."""
        usage_file = str(tmp_path / "sambanova_usage.json")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with patch(
            "cic_daily_report.breaking.llm_scorer._get_usage_file_path",
            return_value=usage_file,
        ):
            _save_daily_count(2)
        with open(usage_file) as f:
            data = json.load(f)
        assert data["date"] == today
        assert data["calls"] == 2


# ============================================================================
# reset_sambanova_counter — now also clears file
# ============================================================================


class TestResetCounterWithPersistence:
    def test_reset_clears_both_memory_and_file(self, tmp_path):
        """reset_sambanova_counter zeroes both in-memory and on-disk count."""
        import cic_daily_report.breaking.llm_scorer as mod

        usage_file = str(tmp_path / "sambanova_usage.json")
        with patch(
            "cic_daily_report.breaking.llm_scorer._get_usage_file_path",
            return_value=usage_file,
        ):
            mod._sambanova_calls_today = 10
            _save_daily_count(10)
            reset_sambanova_counter()

        assert get_sambanova_calls_today() == 0
        with patch(
            "cic_daily_report.breaking.llm_scorer._get_usage_file_path",
            return_value=usage_file,
        ):
            assert _load_daily_count() == 0


# ============================================================================
# score_event_impact — persistence integration
# ============================================================================


class TestScoreEventImpactPersistence:
    def setup_method(self):
        reset_sambanova_counter()

    async def test_loads_persisted_count_on_first_call(self, tmp_path):
        """First call in a new process loads count from file."""
        import cic_daily_report.breaking.llm_scorer as mod

        usage_file = str(tmp_path / "sambanova_usage.json")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Simulate a previous process having made 18 calls
        with open(usage_file, "w") as f:
            json.dump({"date": today, "calls": 18}, f)

        mod._sambanova_calls_today = 0  # Simulate fresh process

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": "7"}}]}
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.dict(os.environ, {"SAMBANOVA_API_KEY": "test-key"}),
            patch(
                "cic_daily_report.breaking.llm_scorer._get_usage_file_path",
                return_value=usage_file,
            ),
            patch(
                "cic_daily_report.breaking.llm_scorer.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            score = await score_event_impact(_event())

        # Should have loaded 18, made 1 more call = 19
        assert mod._sambanova_calls_today == 19
        assert score == 7

    async def test_persists_count_after_successful_call(self, tmp_path):
        """After a successful SambaNova call, count is written to file."""
        import cic_daily_report.breaking.llm_scorer as mod

        usage_file = str(tmp_path / "sambanova_usage.json")
        mod._sambanova_calls_today = 0

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": "5"}}]}
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.dict(os.environ, {"SAMBANOVA_API_KEY": "test-key"}),
            patch(
                "cic_daily_report.breaking.llm_scorer._get_usage_file_path",
                return_value=usage_file,
            ),
            patch(
                "cic_daily_report.breaking.llm_scorer.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            await score_event_impact(_event())

        # Verify file was written
        with open(usage_file) as f:
            data = json.load(f)
        assert data["calls"] == 1

    async def test_blocks_at_20_after_loading_persisted_count(self, tmp_path):
        """If persisted count = 20, immediately returns 10 (pass-through)."""
        import cic_daily_report.breaking.llm_scorer as mod

        usage_file = str(tmp_path / "sambanova_usage.json")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        with open(usage_file, "w") as f:
            json.dump({"date": today, "calls": 20}, f)

        mod._sambanova_calls_today = 0  # Simulate fresh process

        with (
            patch.dict(os.environ, {"SAMBANOVA_API_KEY": "test-key"}),
            patch(
                "cic_daily_report.breaking.llm_scorer._get_usage_file_path",
                return_value=usage_file,
            ),
        ):
            score = await score_event_impact(_event())

        assert score == 10  # Pass-through due to quota
        assert mod._sambanova_calls_today == 20
