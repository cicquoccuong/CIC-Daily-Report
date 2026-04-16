"""Tests for DR_EXPORT tab exporter (QO.40).

Covers: export_daily_summary, _ensure_tab_exists, DR_EXPORT_HEADERS.
All Google Sheets calls are mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from cic_daily_report.storage.dr_exporter import (
    DR_EXPORT_HEADERS,
    _ensure_tab_exists,
    export_daily_summary,
)

# --- Fixtures ---


def _make_mock_sheets_client(tab_exists: bool = True) -> MagicMock:
    """Create a mock SheetsClient with configurable DR_EXPORT tab state."""
    mock_client = MagicMock()

    # Mock _connect() for _ensure_tab_exists
    mock_ss = MagicMock()
    mock_ws_existing = MagicMock()
    mock_ws_existing.title = "NHAT_KY_PIPELINE"

    if tab_exists:
        mock_ws_dr = MagicMock()
        mock_ws_dr.title = "DR_EXPORT"
        mock_ss.worksheets.return_value = [mock_ws_existing, mock_ws_dr]
    else:
        mock_ss.worksheets.return_value = [mock_ws_existing]

    mock_ws_new = MagicMock()
    mock_ss.add_worksheet.return_value = mock_ws_new

    mock_client._connect.return_value = mock_ss
    mock_client.batch_append = MagicMock()

    return mock_client


# === DR_EXPORT_HEADERS Tests ===


class TestDRExportHeaders:
    """Verify header constants."""

    def test_header_count(self):
        assert len(DR_EXPORT_HEADERS) == 10

    def test_header_names(self):
        # WHY: these are Vietnamese with diacritics per project rules
        assert DR_EXPORT_HEADERS[0] == "Ngày"
        assert "BTC" in DR_EXPORT_HEADERS[1]
        assert "ETH" in DR_EXPORT_HEADERS[2]
        assert "F&G" in DR_EXPORT_HEADERS[3]
        assert "Sentiment" in DR_EXPORT_HEADERS[4]

    def test_no_empty_headers(self):
        for h in DR_EXPORT_HEADERS:
            assert h.strip() != ""


# === export_daily_summary Tests ===


class TestExportDailySummary:
    """Tests for export_daily_summary."""

    def test_successful_export(self):
        """Happy path — data written to DR_EXPORT tab."""
        mock_client = _make_mock_sheets_client(tab_exists=True)
        result = export_daily_summary(
            sheets_client=mock_client,
            date="2026-04-15",
            btc_price=84500.50,
            eth_price=1620.25,
            fg_index=65,
            market_sentiment="Neutral",
            consensus_labels="BTC:BULLISH|ETH:NEUTRAL",
            top_news_summary="Fed holds rates, Bitcoin rallies",
            articles_generated=5,
            quality_pass_rate=0.85,
            breaking_events_today=3,
        )
        assert result is True
        mock_client.batch_append.assert_called_once()
        call_args = mock_client.batch_append.call_args
        assert call_args[0][0] == "DR_EXPORT"
        row = call_args[0][1][0]
        assert row[0] == "2026-04-15"
        assert row[1] == "84500.5"
        assert row[2] == "1620.25"
        assert row[3] == "65"
        assert row[4] == "Neutral"
        assert row[5] == "BTC:BULLISH|ETH:NEUTRAL"

    def test_default_date(self):
        """If date is empty, uses today's UTC date."""
        mock_client = _make_mock_sheets_client(tab_exists=True)
        result = export_daily_summary(sheets_client=mock_client)
        assert result is True
        call_args = mock_client.batch_append.call_args
        row = call_args[0][1][0]
        # WHY: date should be in YYYY-MM-DD format
        assert len(row[0]) == 10
        assert "-" in row[0]

    def test_truncates_long_news(self):
        """Top news summary is truncated to 200 chars."""
        long_news = "A" * 500
        mock_client = _make_mock_sheets_client(tab_exists=True)
        export_daily_summary(
            sheets_client=mock_client,
            top_news_summary=long_news,
        )
        call_args = mock_client.batch_append.call_args
        row = call_args[0][1][0]
        # WHY: news is at index 6
        assert len(row[6]) == 200

    def test_empty_news_not_truncated(self):
        """Empty news summary stays empty."""
        mock_client = _make_mock_sheets_client(tab_exists=True)
        export_daily_summary(sheets_client=mock_client, top_news_summary="")
        call_args = mock_client.batch_append.call_args
        row = call_args[0][1][0]
        assert row[6] == ""

    def test_price_rounding(self):
        """Prices are rounded to 2 decimal places."""
        mock_client = _make_mock_sheets_client(tab_exists=True)
        export_daily_summary(
            sheets_client=mock_client,
            btc_price=84500.12345,
            eth_price=1620.9999,
        )
        call_args = mock_client.batch_append.call_args
        row = call_args[0][1][0]
        assert row[1] == "84500.12"
        assert row[2] == "1621.0"

    def test_quality_rate_rounding(self):
        """Quality pass rate is rounded to 2 decimal places."""
        mock_client = _make_mock_sheets_client(tab_exists=True)
        export_daily_summary(
            sheets_client=mock_client,
            quality_pass_rate=0.8567,
        )
        call_args = mock_client.batch_append.call_args
        row = call_args[0][1][0]
        assert row[8] == "0.86"

    def test_batch_append_failure_returns_false(self):
        """If batch_append fails, returns False (never raises)."""
        mock_client = _make_mock_sheets_client(tab_exists=True)
        mock_client.batch_append.side_effect = Exception("Sheets API error")
        result = export_daily_summary(sheets_client=mock_client, date="2026-04-15")
        assert result is False

    def test_ensure_tab_called(self):
        """_ensure_tab_exists is called before batch_append."""
        mock_client = _make_mock_sheets_client(tab_exists=False)
        export_daily_summary(sheets_client=mock_client, date="2026-04-15")
        # WHY: _connect should be called to check for tab existence
        mock_client._connect.assert_called()

    def test_all_values_as_strings(self):
        """All row values should be strings (for Sheets compatibility)."""
        mock_client = _make_mock_sheets_client(tab_exists=True)
        export_daily_summary(
            sheets_client=mock_client,
            date="2026-04-15",
            btc_price=84500.0,
            eth_price=1620.0,
            fg_index=65,
            articles_generated=5,
            quality_pass_rate=0.85,
            breaking_events_today=3,
        )
        call_args = mock_client.batch_append.call_args
        row = call_args[0][1][0]
        for val in row:
            assert isinstance(val, str), f"Expected string, got {type(val)}: {val}"

    def test_zero_values(self):
        """Zero values should still write valid row."""
        mock_client = _make_mock_sheets_client(tab_exists=True)
        result = export_daily_summary(
            sheets_client=mock_client,
            date="2026-04-15",
            btc_price=0.0,
            eth_price=0.0,
            fg_index=0,
        )
        assert result is True
        call_args = mock_client.batch_append.call_args
        row = call_args[0][1][0]
        assert row[1] == "0.0"  # btc_price: float → "0.0"
        assert row[3] == "0"  # fg_index: int → "0"


# === _ensure_tab_exists Tests ===


class TestEnsureTabExists:
    """Tests for _ensure_tab_exists — lazy tab creation."""

    def test_tab_already_exists(self):
        """If DR_EXPORT tab exists, do nothing."""
        mock_client = _make_mock_sheets_client(tab_exists=True)
        _ensure_tab_exists(mock_client)
        mock_ss = mock_client._connect.return_value
        mock_ss.add_worksheet.assert_not_called()

    def test_tab_does_not_exist(self):
        """If DR_EXPORT tab is missing, create it with headers."""
        mock_client = _make_mock_sheets_client(tab_exists=False)
        _ensure_tab_exists(mock_client)
        mock_ss = mock_client._connect.return_value
        mock_ss.add_worksheet.assert_called_once()
        call_args = mock_ss.add_worksheet.call_args
        assert call_args[1]["title"] == "DR_EXPORT"
        assert call_args[1]["cols"] == len(DR_EXPORT_HEADERS)
        # WHY: headers should be written to the new worksheet
        mock_ws = mock_ss.add_worksheet.return_value
        mock_ws.update.assert_called_once()
        update_args = mock_ws.update.call_args
        assert update_args[0][0] == [DR_EXPORT_HEADERS]

    def test_connect_failure_graceful(self):
        """If _connect fails, don't raise."""
        mock_client = MagicMock()
        mock_client._connect.side_effect = Exception("Connection failed")
        # WHY: should not raise — function has try/except
        _ensure_tab_exists(mock_client)

    def test_add_worksheet_failure_graceful(self):
        """If add_worksheet fails, don't raise."""
        mock_client = _make_mock_sheets_client(tab_exists=False)
        mock_ss = mock_client._connect.return_value
        mock_ss.add_worksheet.side_effect = Exception("Quota exceeded")
        # WHY: should not raise
        _ensure_tab_exists(mock_client)
