# Hotfix Wave B — Spec (Approved 2026-03-12)

## Context
Pipeline daily không chạy sáng 12/03/2026. Root cause analysis phát hiện 20 vấn đề.
Đợt 1 sửa 5 vấn đề critical/high cần làm ngay.

## Fixes

### C1: Tách Concurrency Group + Offset Cron
- **Gốc rễ**: Daily pipeline và Breaking News dùng chung concurrency group `gh-pages-deploy` → block nhau khi trigger cùng lúc 01:00 UTC
- **Phân tích**: Group ban đầu để tránh git push conflict khi cả 2 push gh-pages. Nhưng code ĐÃ CÓ retry 3 lần với `git pull --rebase` → group là THỪA, chỉ tạo thêm vấn đề
- **Giải pháp**:
  - `daily-pipeline.yml`: `group: daily-pipeline`, cron `5 1 * * *` (offset 5 phút)
  - `breaking-news.yml`: `group: breaking-news`
- **Risk**: Git push conflict khi cả 2 push cùng lúc → đã handle bằng retry
- **Files**: `.github/workflows/daily-pipeline.yml`, `.github/workflows/breaking-news.yml`

### C3: Pipeline Fail Khi Delivery Gửi 0 Tin
- **Gốc rễ**: `_deliver()` catch exception và chỉ log, KHÔNG append vào errors list. `DeliveryResult` bị bỏ qua.
- **Giải pháp**:
  1. `_deliver()` return `DeliveryResult` thay vì `None`
  2. `_run_pipeline()` check `result.messages_sent == 0 AND messages_total > 0` → append error, set status "error"
  3. `_run_pipeline()` return status string
  4. `main()` nhận status, `sys.exit(1)` nếu "error"
- **Edge cases**:
  - Partial delivery (3/6 sent): status = "partial", pipeline KHÔNG fail
  - Full failure (0/6 sent): status = "error", pipeline fail → retry step chạy
  - No content (0/0): status vẫn theo collector/generator errors
- **Files**: `src/cic_daily_report/daily_pipeline.py`

### C5: Fix pyproject.toml Version
- **Gốc rễ**: `pyproject.toml` version `0.12.0` không khớp `core/config.py` version `0.13.0`
- **Giải pháp**: Sửa `pyproject.toml` line 3: `0.12.0` → `0.13.0`
- **Files**: `pyproject.toml`

### H6: Validate Groq Empty Response
- **Gốc rễ**: Gemini có 2 lớp validation (no candidates + empty text). Groq có 0 lớp.
- **Giải pháp**: 2 tầng validation:
  1. `_call_groq()`: check `not text.strip()` → raise `LLMError("Groq returned empty text")`
  2. `generate()` (safety net): check `not response.text.strip()` → raise `LLMError` — cover TẤT CẢ provider hiện tại và tương lai
- **Risk**: Double validate cho Gemini — chấp nhận được (zero cost, extra safety)
- **Files**: `src/cic_daily_report/adapters/llm_adapter.py`

### M1: HTML Escape cho Telegram Messages
- **Gốc rễ**: `parse_mode="HTML"` nhưng không escape ký tự `<`, `>`, `&` trong nội dung
- **Giải pháp**: `html.escape(text)` trong `_send_raw()` — tầng thấp nhất, cover MỌI message
- **Lý do chọn _send_raw()**: Mọi code path (daily, breaking, error notification) đều đi qua `_send_raw()` → không thể sót
- **Risk**: Nếu tương lai muốn dùng HTML tag (<b>, <i>), cần escape TRƯỚC khi thêm tag
- **Files**: `src/cic_daily_report/delivery/telegram_bot.py`

## Test Requirements
- C1: Không cần test (YAML config change)
- C3: Test case: mock delivery fail → verify pipeline status = "error"
- C5: Không cần test (metadata only)
- H6: Test case: mock Groq return empty → verify raise LLMError + fallback to next provider
- M1: Test case: message with `<`, `>`, `&` → verify escaped correctly

## Doc-Sync
- CHANGELOG.md: v0.13.1 entry
- CLAUDE.md: Update pipeline schedule "01:05 UTC"
- __init__.py: version bump to 0.13.1
