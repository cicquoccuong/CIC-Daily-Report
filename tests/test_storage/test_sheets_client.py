"""Tests for storage/sheets_client.py — all mocked, no real API calls."""

from unittest.mock import MagicMock

import pytest

from cic_daily_report.core.error_handler import StorageError
from cic_daily_report.storage.sheets_client import TABS, SheetsClient


class TestSheetsClientInit:
    def test_missing_credentials_raises(self):
        client = SheetsClient(spreadsheet_id="test", credentials_b64="")
        with pytest.raises(StorageError, match="CREDENTIALS"):
            client._connect()

    def test_missing_spreadsheet_id_raises(self):
        client = SheetsClient(spreadsheet_id="", credentials_b64="dGVzdA==")
        with pytest.raises(StorageError, match="SPREADSHEET_ID"):
            client._connect()


class TestTabSchema:
    def test_has_9_tabs(self):
        assert len(TABS) == 9

    def test_tab_names_are_upper_snake_case(self):
        for name in TABS:
            assert name == name.upper()
            assert " " not in name

    def test_all_tabs_have_headers(self):
        for name, headers in TABS.items():
            assert len(headers) > 0, f"{name} has no headers"

    def test_sentinel_compatible_columns(self):
        news_cols = TABS["TIN_TUC_THO"]
        assert "Loại sự kiện" in news_cols
        assert "Mã coin" in news_cols
        assert "Điểm sentiment" in news_cols
        assert "Phân loại hành động" in news_cols


class TestSheetsClientOperations:
    @pytest.fixture
    def mock_client(self):
        """Create a SheetsClient with mocked gspread connection."""
        client = SheetsClient(spreadsheet_id="test_id", credentials_b64="dGVzdA==")
        mock_ss = MagicMock()
        client._spreadsheet = mock_ss
        return client, mock_ss

    def test_batch_append_empty_rows(self, mock_client):
        client, _ = mock_client
        result = client.batch_append("TIN_TUC_THO", [])
        assert result == 0

    def test_batch_append_writes_rows(self, mock_client):
        client, mock_ss = mock_client
        mock_ws = MagicMock()
        mock_ss.worksheet.return_value = mock_ws

        rows = [["a", "b"], ["c", "d"]]
        result = client.batch_append("TIN_TUC_THO", rows)

        assert result == 2
        mock_ws.append_rows.assert_called_once_with(rows, value_input_option="RAW")

    def test_batch_append_error_raises_storage_error(self, mock_client):
        client, mock_ss = mock_client
        mock_ss.worksheet.side_effect = Exception("API error")

        with pytest.raises(StorageError, match="batch_append"):
            client.batch_append("TIN_TUC_THO", [["data"]])

    def test_read_all_returns_records(self, mock_client):
        client, mock_ss = mock_client
        mock_ws = MagicMock()
        mock_ws.get_all_records.return_value = [{"Khóa": "k1", "Giá trị": "v1"}]
        mock_ss.worksheet.return_value = mock_ws

        result = client.read_all("CAU_HINH")
        assert result == [{"Khóa": "k1", "Giá trị": "v1"}]

    def test_get_row_count(self, mock_client):
        client, mock_ss = mock_client
        mock_ws = MagicMock()
        mock_ws.get_all_values.return_value = [["header"], ["row1"], ["row2"]]
        mock_ss.worksheet.return_value = mock_ws

        assert client.get_row_count("TIN_TUC_THO") == 2

    def test_delete_rows_protects_header(self, mock_client):
        client, mock_ss = mock_client
        mock_ws = MagicMock()
        mock_ss.worksheet.return_value = mock_ws

        client.delete_rows("TIN_TUC_THO", start_row=1, end_row=5)
        mock_ws.delete_rows.assert_called_once_with(2, 5)

    def test_create_schema_skips_existing(self, mock_client):
        client, mock_ss = mock_client
        existing_ws = MagicMock()
        existing_ws.title = "TIN_TUC_THO"
        mock_ss.worksheets.return_value = [existing_ws]

        new_ws = MagicMock()
        mock_ss.add_worksheet.return_value = new_ws

        client.create_schema()

        # Should create 8 tabs (9 total - 1 existing)
        assert mock_ss.add_worksheet.call_count == 8
