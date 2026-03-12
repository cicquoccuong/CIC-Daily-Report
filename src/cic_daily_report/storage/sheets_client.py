"""Google Sheets client — batch operations, schema management (QĐ1)."""

from __future__ import annotations

import base64
import json
import os
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

from cic_daily_report.core.error_handler import StorageError
from cic_daily_report.core.logger import get_logger

logger = get_logger("sheets_client")

# Default rows seeded into CAU_HINH on first setup (key, default_value, description)
# seed_setting() skips any key that already exists — never overwrites user data.
_DEFAULT_CONFIG_SEEDS: list[tuple[str, str, str]] = [
    (
        "email_recipients",
        "",
        (
            "Danh sách email nhận báo cáo hàng ngày. "
            "THÊM email: gõ thêm địa chỉ vào cuối, cách nhau bằng dấu phẩy. "
            "XÓA email: xóa địa chỉ đó khỏi ô Giá trị. "
            "Để trống = hệ thống dùng GitHub Secrets (SMTP_RECIPIENTS). "
            "Ví dụ: cuong@evol.vn, bao@evol.vn"
        ),
    ),
    (
        "email_backup_enabled",
        "TRUE",
        "Bật/tắt email backup khi Telegram thất bại. Giá trị: TRUE hoặc FALSE.",
    ),
]

# 9-tab schema (QĐ1)
TABS = {
    "TIN_TUC_THO": [
        "ID",
        "Tiêu đề",
        "URL",
        "Nguồn tin",
        "Ngày thu thập",
        "Ngôn ngữ",
        "Tóm tắt",
        "Loại sự kiện",
        "Mã coin",
        "Điểm sentiment",
        "Phân loại hành động",
    ],
    "DU_LIEU_THI_TRUONG": [
        "ID",
        "Ngày",
        "Mã tài sản",
        "Giá",
        "Thay đổi 24h %",
        "Vốn hóa",
        "Khối lượng 24h",
        "Loại",
        "Nguồn",
    ],
    "DU_LIEU_ONCHAIN": [
        "ID",
        "Ngày",
        "Chỉ số",
        "Giá trị",
        "Nguồn",
        "Ghi chú",
    ],
    "NOI_DUNG_DA_TAO": [
        "ID",
        "Ngày tạo",
        "Loại nội dung",
        "Cấp tier",
        "Nội dung",
        "LLM sử dụng",
        "Trạng thái gửi",
        "Ghi chú",
    ],
    "NHAT_KY_PIPELINE": [
        "ID",
        "Thời gian bắt đầu",
        "Thời gian kết thúc",
        "Thời lượng (giây)",
        "Trạng thái",
        "LLM sử dụng",
        "Lỗi",
        "Ghi chú",
    ],
    "MAU_BAI_VIET": [
        "Cấp tier",
        "Tên phần",
        "Bật/Tắt",
        "Thứ tự",
        "Prompt mẫu",
        "Số từ tối đa",
    ],
    "DANH_SACH_COIN": [
        "Mã coin",
        "Tên đầy đủ",
        "Cấp tier",
        "Bật/Tắt",
        "Ghi chú",
    ],
    "CAU_HINH": [
        "Khóa",
        "Giá trị",
        "Mô tả",
    ],
    "BREAKING_LOG": [
        "ID",
        "Thời gian",
        "Tiêu đề",
        "Hash",
        "Nguồn",
        "Mức độ",
        "Trạng thái gửi",
    ],
}


class SheetsClient:
    """Google Sheets client with batch operations."""

    def __init__(self, spreadsheet_id: str | None = None, credentials_b64: str | None = None):
        self._spreadsheet_id = spreadsheet_id or os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "")
        self._credentials_b64 = credentials_b64 or os.getenv("GOOGLE_SHEETS_CREDENTIALS", "")
        self._client: gspread.Client | None = None
        self._spreadsheet: gspread.Spreadsheet | None = None

    def _connect(self) -> gspread.Spreadsheet:
        """Lazy connection to Google Sheets."""
        if self._spreadsheet is not None:
            return self._spreadsheet

        if not self._credentials_b64:
            raise StorageError("GOOGLE_SHEETS_CREDENTIALS not set", source="sheets_client")
        if not self._spreadsheet_id:
            raise StorageError("GOOGLE_SHEETS_SPREADSHEET_ID not set", source="sheets_client")

        try:
            creds_json = json.loads(base64.b64decode(self._credentials_b64))
            creds = Credentials.from_service_account_info(
                creds_json,
                scopes=["https://www.googleapis.com/auth/spreadsheets"],
            )
            self._client = gspread.authorize(creds)
            self._spreadsheet = self._client.open_by_key(self._spreadsheet_id)
            logger.info(f"Connected to spreadsheet: {self._spreadsheet_id}")
            return self._spreadsheet
        except Exception as e:
            raise StorageError(f"Failed to connect: {e}", source="sheets_client") from e

    def create_schema(self) -> None:
        """Create all 9 tabs with headers if they don't exist."""
        ss = self._connect()
        existing = {ws.title for ws in ss.worksheets()}

        for tab_name, headers in TABS.items():
            if tab_name in existing:
                logger.info(f"Tab '{tab_name}' already exists, skipping")
                continue

            ws = ss.add_worksheet(title=tab_name, rows=100, cols=len(headers))
            ws.update([headers], value_input_option="RAW")
            logger.info(f"Created tab '{tab_name}' with {len(headers)} columns")

        # Seed default config rows (skips keys that already have values)
        try:
            self.seed_default_config()
        except Exception as e:
            logger.warning(f"Could not seed default config: {e}")

    def seed_setting(self, key: str, default_value: str, description: str) -> None:
        """Add key to CAU_HINH only if it does not already exist.

        Unlike upsert_setting, this never overwrites existing values.
        Safe to call repeatedly — idempotent.
        """
        ss = self._connect()
        try:
            ws = ss.worksheet("CAU_HINH")
            all_values = ws.get_all_values()
            for row in all_values[1:]:
                if row and row[0] == key:
                    logger.debug(f"CAU_HINH seed skipped (key exists): {key}")
                    return
            ws.append_rows([[key, default_value, description]], value_input_option="RAW")
            logger.info(f"Seeded CAU_HINH setting: {key}")
        except Exception as e:
            raise StorageError(
                f"seed_setting failed for {key}: {e}", source="sheets_client"
            ) from e

    def seed_default_config(self) -> None:
        """Seed all default CAU_HINH rows that don't exist yet.

        Safe to call repeatedly — never overwrites values the user has set.
        Called automatically by create_schema().
        """
        for key, default_value, description in _DEFAULT_CONFIG_SEEDS:
            self.seed_setting(key, default_value, description)
        logger.info("Default CAU_HINH config seeded")

    def batch_append(self, tab_name: str, rows: list[list[Any]]) -> int:
        """Append rows using batch update. Returns number of rows written."""
        if not rows:
            return 0

        ss = self._connect()
        try:
            ws = ss.worksheet(tab_name)
            ws.append_rows(rows, value_input_option="RAW")
            logger.info(f"Appended {len(rows)} rows to {tab_name}")
            return len(rows)
        except Exception as e:
            raise StorageError(
                f"batch_append failed for {tab_name}: {e}", source="sheets_client"
            ) from e

    def batch_write(self, tab_name: str, range_str: str, values: list[list[Any]]) -> None:
        """Write values to a specific range using batch update."""
        ss = self._connect()
        try:
            ws = ss.worksheet(tab_name)
            ws.update(range_str, values, value_input_option="RAW")
        except Exception as e:
            raise StorageError(
                f"batch_write failed for {tab_name}: {e}", source="sheets_client"
            ) from e

    def read_all(self, tab_name: str) -> list[dict[str, Any]]:
        """Read all rows from a tab as list of dicts (header-keyed)."""
        ss = self._connect()
        try:
            ws = ss.worksheet(tab_name)
            return ws.get_all_records()
        except Exception as e:
            raise StorageError(
                f"read_all failed for {tab_name}: {e}", source="sheets_client"
            ) from e

    def get_row_count(self, tab_name: str) -> int:
        """Get number of data rows (excluding header)."""
        ss = self._connect()
        try:
            ws = ss.worksheet(tab_name)
            return len(ws.get_all_values()) - 1  # exclude header
        except Exception as e:
            raise StorageError(
                f"get_row_count failed for {tab_name}: {e}", source="sheets_client"
            ) from e

    def delete_rows(self, tab_name: str, start_row: int, end_row: int) -> None:
        """Delete rows by index (1-based, inclusive). Never deletes row 1 (header)."""
        if start_row <= 1:
            start_row = 2  # protect header
        ss = self._connect()
        try:
            ws = ss.worksheet(tab_name)
            ws.delete_rows(start_row, end_row)
            logger.info(f"Deleted rows {start_row}-{end_row} from {tab_name}")
        except Exception as e:
            raise StorageError(
                f"delete_rows failed for {tab_name}: {e}", source="sheets_client"
            ) from e

    def upsert_setting(self, key: str, value: str, description: str = "") -> None:
        """Find row by key in CAU_HINH and update it, or append if not found."""
        ss = self._connect()
        try:
            ws = ss.worksheet("CAU_HINH")
            all_values = ws.get_all_values()
            row_idx = None
            for i, row in enumerate(all_values[1:], start=2):
                if row and row[0] == key:
                    row_idx = i
                    break
            if row_idx is not None:
                ws.update(
                    f"A{row_idx}:C{row_idx}", [[key, value, description]], value_input_option="RAW"
                )
                logger.info(f"Updated CAU_HINH setting: {key}")
            else:
                ws.append_rows([[key, value, description]], value_input_option="RAW")
                logger.info(f"Added CAU_HINH setting: {key}")
        except Exception as e:
            raise StorageError(
                f"upsert_setting failed for {key}: {e}", source="sheets_client"
            ) from e

    def clear_and_rewrite(self, sheet_name: str, rows: list[list[Any]]) -> None:
        """Clear all data rows (row 2+) in sheet_name, then append rows.

        Raises StorageError on any failure — caller is responsible for fallback.
        """
        ss = self._connect()
        try:
            ws = ss.worksheet(sheet_name)
            all_vals = ws.get_all_values()
            if len(all_vals) > 1:
                ws.delete_rows(2, len(all_vals))
                logger.info(f"Cleared {len(all_vals) - 1} data rows from {sheet_name}")
            if rows:
                ws.append_rows(rows, value_input_option="RAW")
                logger.info(f"Wrote {len(rows)} rows to {sheet_name}")
        except Exception as e:
            raise StorageError(
                f"clear_and_rewrite failed for {sheet_name}: {e}", source="sheets_client"
            ) from e
