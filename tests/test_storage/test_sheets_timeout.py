"""R5-10: Tests for Sheets operation timeout (SHEETS_OP_TIMEOUT).

Verifies that asyncio.wait_for wrapping is applied to Sheets operations
and that TimeoutError is caught gracefully.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from cic_daily_report.daily_pipeline import SHEETS_OP_TIMEOUT


class TestSheetsOpTimeout:
    """R5-10: SHEETS_OP_TIMEOUT constant and usage."""

    def test_timeout_constant_exists(self):
        """SHEETS_OP_TIMEOUT is defined and reasonable."""
        assert SHEETS_OP_TIMEOUT == 60

    async def test_write_run_log_timeout_handled(self):
        """_write_run_log catches TimeoutError and logs warning (no crash)."""
        from cic_daily_report.daily_pipeline import _write_run_log

        run_log = {
            "start_time": "2026-03-30 08:00:00",
            "end_time": "2026-03-30 08:30:00",
            "duration_sec": 1800,
            "status": "success",
            "llm_used": "gemini-flash",
            "errors": [],
            "tiers_delivered": 5,
            "research_word_count": 500,
            "delivery_method": "telegram",
        }

        # WHY: Mock SheetsClient so batch_append blocks forever,
        # triggering the 60s timeout (we patch wait_for to raise immediately).
        with patch(
            "cic_daily_report.daily_pipeline.asyncio.wait_for",
            side_effect=asyncio.TimeoutError(),
        ):
            # Should NOT raise — timeout is caught inside _write_run_log
            await _write_run_log(run_log)

    async def test_load_recent_breaking_timeout_handled(self):
        """_load_recent_breaking_context catches Sheets timeout gracefully."""
        from cic_daily_report.daily_pipeline import _load_recent_breaking_context

        with patch(
            "cic_daily_report.daily_pipeline.asyncio.wait_for",
            side_effect=asyncio.TimeoutError(),
        ):
            # Should return empty string on timeout (not crash)
            result = await _load_recent_breaking_context()
            assert result == ""

    async def test_write_raw_data_timeout_propagates(self):
        """_write_raw_data lets TimeoutError bubble up to caller's try/except."""
        from cic_daily_report.daily_pipeline import _write_raw_data

        mock_sheets = MagicMock()

        # WHY: Need at least one article with to_row() so the code path
        # reaches the asyncio.wait_for call — empty lists skip writes entirely.
        fake_article = MagicMock()
        fake_article.to_row.return_value = ["a", "b", "c"]

        # Patch asyncio at module level to raise TimeoutError
        with (
            patch(
                "cic_daily_report.daily_pipeline.asyncio.wait_for",
                side_effect=asyncio.TimeoutError(),
            ),
            pytest.raises(asyncio.TimeoutError),
        ):
            # _write_raw_data doesn't catch TimeoutError itself —
            # it propagates to the caller in _execute_stages which does catch it
            await _write_raw_data(mock_sheets, [fake_article], [], [], [])
