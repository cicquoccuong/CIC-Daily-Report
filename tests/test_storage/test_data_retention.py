"""Tests for storage/data_retention.py."""

from unittest.mock import MagicMock

from cic_daily_report.storage.data_retention import (
    FORCE_CLEANUP_THRESHOLD,
    WARNING_THRESHOLD,
    _check_size_warning,
    _parse_date,
    run_cleanup,
)


class TestParseDate:
    def test_iso_format(self):
        dt = _parse_date("2026-03-09 08:00:00")
        assert dt is not None
        assert dt.year == 2026

    def test_date_only(self):
        dt = _parse_date("2026-03-09")
        assert dt is not None

    def test_dd_mm_yyyy(self):
        dt = _parse_date("09/03/2026")
        assert dt is not None

    def test_empty_returns_none(self):
        assert _parse_date("") is None
        assert _parse_date("  ") is None

    def test_invalid_returns_none(self):
        assert _parse_date("not-a-date") is None


class TestCheckSizeWarning:
    def test_warning_at_threshold(self, caplog):
        mock_sheets = MagicMock()
        mock_sheets.get_row_count.return_value = WARNING_THRESHOLD
        import logging

        with caplog.at_level(logging.WARNING):
            _check_size_warning(mock_sheets, "TIN_TUC_THO")

    def test_force_cleanup_warning(self, caplog):
        mock_sheets = MagicMock()
        mock_sheets.get_row_count.return_value = FORCE_CLEANUP_THRESHOLD
        import logging

        with caplog.at_level(logging.WARNING):
            _check_size_warning(mock_sheets, "TIN_TUC_THO")


class TestRunCleanup:
    def test_empty_tabs_no_errors(self):
        mock_sheets = MagicMock()
        mock_sheets.get_row_count.return_value = 0
        results = run_cleanup(mock_sheets, retention_raw_days=90, retention_generated_days=30)
        assert all(v == 0 for v in results.values())

    def test_returns_dict_of_tab_results(self):
        mock_sheets = MagicMock()
        mock_sheets.get_row_count.return_value = 0
        results = run_cleanup(mock_sheets)
        assert "TIN_TUC_THO" in results
        assert "NOI_DUNG_DA_TAO" in results
        assert "NHAT_KY_PIPELINE" in results
