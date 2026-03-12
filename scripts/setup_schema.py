"""One-time setup script: tạo Google Sheets schema + seed cấu hình mặc định.

Chạy MỘT LẦN sau khi tạo spreadsheet mới và thiết lập env vars:

    uv run python scripts/setup_schema.py

Requires env vars:
    GOOGLE_SHEETS_SPREADSHEET_ID
    GOOGLE_SHEETS_CREDENTIALS (base64-encoded service account JSON)

Kết quả:
- Tạo 9 tab theo schema (TIN_TUC_THO, DU_LIEU_THI_TRUONG, ...)
- Seed các cài đặt mặc định vào tab CAU_HINH (bao gồm email_recipients)
- Idempotent: chạy lại sẽ skip các tab/row đã tồn tại
"""

from __future__ import annotations

import sys

from cic_daily_report.storage.sheets_client import SheetsClient


def main() -> None:
    print("=== CIC Daily Report — Setup Schema ===")

    client = SheetsClient()

    print("\n[1/2] Tạo 9 tab schema...")
    try:
        client.create_schema()
        print("      ✓ Schema OK")
    except Exception as e:
        print(f"      ✗ Lỗi: {e}")
        sys.exit(1)

    print("\n[2/2] Seed cấu hình mặc định vào CAU_HINH...")
    try:
        client.seed_default_config()
        print("      ✓ Seed OK")
    except Exception as e:
        print(f"      ✗ Lỗi seed config: {e}")
        sys.exit(1)

    print(
        "\n✅ Setup hoàn tất!\n"
        "\nBước tiếp theo:\n"
        "  1. Mở Google Sheet → tab CAU_HINH\n"
        "  2. Tìm dòng 'email_recipients'\n"
        "  3. Điền email vào cột 'Giá trị' (cách nhau bằng dấu phẩy)\n"
        "  4. Lưu → pipeline sẽ tự đọc email từ đây mỗi lần chạy\n"
    )


if __name__ == "__main__":
    main()
