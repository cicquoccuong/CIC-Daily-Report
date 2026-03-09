"""Data retention & auto-cleanup — keeps Sheets within size limits."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from cic_daily_report.core.logger import get_logger
from cic_daily_report.storage.sheets_client import SheetsClient

logger = get_logger("data_retention")

# Tabs with date-based cleanup and their date column index (0-based)
RAW_TABS = ["TIN_TUC_THO", "DU_LIEU_THI_TRUONG", "DU_LIEU_ONCHAIN"]
GENERATED_TABS = ["NOI_DUNG_DA_TAO", "NHAT_KY_PIPELINE"]

# Date column positions (0-based, in raw values)
DATE_COLUMNS = {
    "TIN_TUC_THO": 4,  # "Ngày thu thập"
    "DU_LIEU_THI_TRUONG": 1,  # "Ngày"
    "DU_LIEU_ONCHAIN": 1,  # "Ngày"
    "NOI_DUNG_DA_TAO": 1,  # "Ngày tạo"
    "NHAT_KY_PIPELINE": 1,  # "Thời gian bắt đầu"
}

WARNING_THRESHOLD = 4000  # 80% of 5000 max
FORCE_CLEANUP_THRESHOLD = 5000


def run_cleanup(
    sheets: SheetsClient,
    retention_raw_days: int = 90,
    retention_generated_days: int = 30,
) -> dict[str, int]:
    """Run cleanup on all data tabs. Returns {tab_name: rows_removed}."""
    results: dict[str, int] = {}

    for tab in RAW_TABS:
        removed = _cleanup_tab(sheets, tab, retention_raw_days)
        results[tab] = removed

    for tab in GENERATED_TABS:
        removed = _cleanup_tab(sheets, tab, retention_generated_days)
        results[tab] = removed

    # Check size warnings
    for tab in RAW_TABS + GENERATED_TABS:
        _check_size_warning(sheets, tab)

    total = sum(results.values())
    if total > 0:
        logger.info(f"Cleanup complete: {total} rows removed total")
    return results


def _cleanup_tab(sheets: SheetsClient, tab_name: str, retention_days: int) -> int:
    """Remove rows older than retention period from a tab."""
    try:
        row_count = sheets.get_row_count(tab_name)
        if row_count == 0:
            return 0

        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        date_col = DATE_COLUMNS.get(tab_name, 1)

        # Read all values to find rows to delete
        ss = sheets._connect()
        ws = ss.worksheet(tab_name)
        all_values = ws.get_all_values()

        if len(all_values) <= 1:  # only header
            return 0

        rows_to_delete: list[int] = []  # 1-based row indices
        for i, row in enumerate(all_values[1:], start=2):  # skip header
            if date_col < len(row):
                try:
                    date_str = row[date_col]
                    row_date = _parse_date(date_str)
                    if row_date and row_date < cutoff:
                        rows_to_delete.append(i)
                except (ValueError, IndexError):
                    continue

        if not rows_to_delete:
            return 0

        # Delete from bottom up to preserve row indices
        for row_idx in reversed(rows_to_delete):
            ws.delete_rows(row_idx)

        logger.info(f"{tab_name}: removed {len(rows_to_delete)} rows (>{retention_days} days)")
        return len(rows_to_delete)

    except Exception as e:
        logger.error(f"Cleanup failed for {tab_name}: {e}")
        return 0


def _check_size_warning(sheets: SheetsClient, tab_name: str) -> None:
    """Log warning if tab is approaching size limit."""
    try:
        row_count = sheets.get_row_count(tab_name)
        if row_count >= FORCE_CLEANUP_THRESHOLD:
            logger.warning(f"{tab_name}: {row_count} rows — AT LIMIT! Force cleanup needed.")
        elif row_count >= WARNING_THRESHOLD:
            logger.warning(f"{tab_name}: {row_count} rows — approaching limit (80%)")
    except Exception as e:
        logger.debug(f"Size check skipped for {tab_name}: {e}")


def _parse_date(date_str: str) -> datetime | None:
    """Try to parse a date string in common formats."""
    if not date_str or not date_str.strip():
        return None

    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None
