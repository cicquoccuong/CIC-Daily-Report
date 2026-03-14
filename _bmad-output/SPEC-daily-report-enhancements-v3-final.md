# SPEC: CIC Daily Report — Nâng cấp Research Feeds, Format Telegram & Hình ảnh

> **Version**: 3.0 (Final — includes full discussion log + implementation plan)
> **Date**: 2026-03-13
> **Track**: B (Feature) | **Priority**: P1
> **Requested by**: Anh Cường | **Spec by**: John (PM)
> **Approved by**: Anh Cường (2026-03-13)

---

## MỤC LỤC

1. [Bối cảnh & Mục tiêu](#1-bối-cảnh--mục-tiêu)
2. [Yêu cầu chi tiết](#2-yêu-cầu-chi-tiết)
3. [Phạm vi ảnh hưởng](#3-phạm-vi-ảnh-hưởng)
4. [Implementation Plan](#4-implementation-plan)
5. [Rủi ro & Giảm thiểu](#5-rủi-ro--giảm-thiểu)
6. [Quyết định Anh Cường](#6-quyết-định-anh-cường)
7. [Audit Log](#7-audit-log)
8. [Discussion Log](#8-discussion-log-full)
9. [Tóm tắt cho Anh Cường](#9-tóm-tắt-cho-anh-cường)

---

## 1. BỐI CẢNH & MỤC TIÊU

### Vấn đề hiện tại
1. **Thiếu nguồn phân tích chuyên sâu**: Pipeline hiện tại dùng 17 RSS feeds + CryptoPanic — toàn tin tức bề mặt, chưa có research/analysis từ nguồn chất lượng cao. L3-L5 thiếu insight sâu.
2. **Bản tin Telegram khó đọc**: Raw markdown (`##` headers), tường chữ không phân tách, số liệu lẫn trong text, thiếu visual markers.
3. **Thiếu hình ảnh minh họa**: Không có chart/visualization kèm bản tin.

### Mục tiêu
- Tích hợp 4+ nguồn research chất lượng cao vào pipeline
- Format lại bản tin Telegram cho dễ đọc (emoji headers, separator, data dạng bảng)
- Thêm hyperlink nguồn trích dẫn cho mỗi tin
- Gửi 1-2 hình chart/infographic từ research sources mỗi ngày

---

## 2. YÊU CẦU CHI TIẾT

### 2.1. Việc 1 — Research Feeds Layer

**Mô tả**: Thêm 4 nguồn research vào RSS collector, gắn tag `source_type` để phân biệt.

**Nguồn mới (4 RSS feeds):**

| # | Nguồn | Loại | Tần suất |
|---|-------|------|----------|
| R1 | Messari Research | Sector research, protocol analysis | Weekly |
| R2 | Glassnode Insights | On-chain analysis chuyên sâu | 2-3x/week |
| R3 | CoinMetrics "State of the Network" | Network data + macro-crypto | Weekly |
| R4 | Galaxy Digital Research | Institutional-grade macro + sector | Weekly |

**Yêu cầu kỹ thuật:**
- [ ] Thêm 4 feed URLs vào `rss_collector.py` → `DEFAULT_FEEDS`
- [ ] Thêm field `source_type` ("news" | "research") vào `FeedConfig` dataclass
- [ ] Gắn `source_type: "research"` cho 4 feeds mới, `"news"` cho 17 feeds hiện tại
- [ ] Tận dụng cột `event_type` (hiện ghi empty string) trong `NewsArticle.to_row()` để lưu `source_type` — KHÔNG thêm cột mới vào Sheets
- [ ] Dùng `trafilatura.extract()` cho research articles để lấy full text
- [ ] Dùng `trafilatura.extract_metadata()` để lấy `og:image` URL (xem Việc 3)
- [ ] Research articles ưu tiên đưa vào context cho L3-L5 prompts
- [ ] Cập nhật L3-L5 prompt templates trên Google Sheets: hướng dẫn LLM tổng hợp research insights
- [ ] NQ05 filter KHÔNG scan input — chỉ scan LLM output
- [ ] Thêm `asyncio.Semaphore(25)` giới hạn concurrent requests

**Acceptance Criteria:**
- AC1: Pipeline collect được bài từ ít nhất 3/4 nguồn research mới
- AC2: Bài research gắn `source_type: "research"` (lưu vào cột `event_type` trên Sheets)
- AC3: L3-L5 articles tổng hợp research insights khi có bài mới
- AC4: Collection time tổng ≤10 phút (NFR4)
- AC5: Graceful fallback nếu feed nào không available
- AC6: Ngày không có research mới → bản tin chạy bình thường dùng news data

### 2.2. Việc 2 — Format lại Telegram Output

**Mô tả**: Thiết kế lại layout bản tin + thêm hyperlink nguồn + fix các vấn đề hệ thống.

**Format mới (Anh Cường approved):**

```
[L1]
📊 BẢN TIN CRYPTO NGÀY DD/MM/YYYY
━━━━━━━━━━━━━━━━━━━━━

🟢 THỊ TRƯỜNG TỔNG QUAN

₿ BTC: $XX,XXX  ▲ +X.X%
Ξ ETH: $X,XXX   ▲ +X.X%
📈 Fear & Greed: XX (Mô tả)
💵 DXY: XX.XX   ▼/▲

━━━━━━━━━━━━━━━━━━━━━

🔥 TIN NỔI BẬT

• Tin 1...
  🔗 <a href="url">Tên nguồn</a>

• Tin 2...
  🔗 <a href="url">Tên nguồn</a>

━━━━━━━━━━━━━━━━━━━━━

📖 PHÂN TÍCH CHUYÊN SÂU

Nội dung phân tích...

🔗 Nguồn: <a href="url1">Messari</a> · <a href="url2">Glassnode</a>

━━━━━━━━━━━━━━━━━━━━━

⚠️ Nội dung chỉ mang tính thông tin,
KHÔNG phải lời khuyên đầu tư. DYOR.
```

**Kiến trúc hyperlink (CRITICAL DESIGN DECISION):**

Hyperlinks được thêm ở **DELIVERY LAYER**, không phải trong LLM output:

```
LLM sinh plain text → NQ05 scan plain text → Delivery layer thêm:
                                                ├─ Emoji headers + ━━━ separators
                                                ├─ <a href> hyperlinks (từ URL metadata)
                                                ├─ Selective HTML escape
                                                └─ send_message() / send_photo()
```

**Hyperlink mapping:**
- "Tin Nổi Bật": mỗi bullet = 1 tin = 1 URL → link riêng/tin
- "Phân Tích Chuyên Sâu": tổng hợp → liệt kê nguồn cuối section

**Yêu cầu kỹ thuật:**

| File | Thay đổi | Chi tiết |
|------|----------|----------|
| `telegram_bot.py` | Selective HTML escape | Line 144: `html_lib.escape()` escape TẤT CẢ HTML → sửa: whitelist `<a href>` tags, escape phần còn lại. Sanitize href (no `javascript:`) |
| `telegram_bot.py` | `split_message()` update | Nhận diện `━━━` separator + emoji headers thay vì `##` và `**...**` |
| `telegram_bot.py` | `TelegramMessage` mở rộng | Thêm `source_urls: list[dict]` field |
| `delivery_manager.py` | Article dict schema | Mở rộng: `{"tier", "content", "source_urls", "image_urls"}` |
| `article_generator.py` | `GeneratedArticle` mở rộng | Thêm `source_urls: list[dict[str, str]]` (`{"name": "...", "url": "..."}`) |
| `article_generator.py` | URL mapping | Giữ mapping `{source_name → url}` từ news data, truyền cho delivery (KHÔNG embed URL trong LLM prompt) |
| `email_backup.py` | HTML format | `msg.set_content(body, subtype="html")` thay vì plain text |
| `summary_generator.py` | Strip decorations | `re.sub(r'[━─═]+', '', content)` + bỏ emoji header lines trước khi cắt 800-char excerpt |
| `nq05_filter.py` | Scan link text | Thêm regex scan text bên trong `<a>...</a>` tags cho từ cấm NQ05. CHỈ scan output |
| `daily_pipeline.py` | Truncation limit | Tăng 5000 → 8000 ký tự cho `NOI_DUNG_DA_TAO` |
| `template_engine.py` | Format mới | Emoji headers + separators trong rendered output |

**Acceptance Criteria:**
- AC7: Bản tin Telegram hiển thị format mới (emoji headers, separators, data bảng)
- AC8: Hyperlinks click được (KHÔNG bị HTML escape)
- AC9: Section phân tích có danh sách nguồn hyperlink cuối section
- AC10: Smart splitting nhận diện `━━━` separator
- AC11: NQ05 disclaimer cuối mỗi bản tin
- AC12: Email backup hiển thị HTML format đúng
- AC13: Summary generator không cắt giữa decorations
- AC14: NOI_DUNG_DA_TAO lưu ≤8000 ký tự

### 2.3. Việc 3 — Hình ảnh từ Research Sources

**Mô tả**: Gửi 1-2 hình preview từ research sources kèm bản tin.

**Quy tắc chọn:**
- Chỉ lấy hình từ `source_type="research"` (chart/data có giá trị)
- Bỏ qua `source_type="news"` (stock photo)
- Tối đa 2-3 hình/ngày

**og:image extraction (dùng trafilatura — không cần dependency mới):**
```python
metadata = trafilatura.extract_metadata(resp.text)
if metadata and metadata.image:
    article.og_image = metadata.image
# Fallback: RSS <media:content> tag (feedparser đã parse)
```

**Yêu cầu kỹ thuật:**
- [ ] Thêm `og_image: str | None` vào `NewsArticle` + `CryptoPanicArticle` dataclass
- [ ] Extract og:image qua `trafilatura.extract_metadata()` cho research feeds
- [ ] Fallback: RSS `<media:content>` tag
- [ ] `telegram_bot.py`: method `send_photo(photo_url, caption, parse_mode="HTML")`
- [ ] Caption ≤1024 ký tự — format: title + 1-2 câu + 🔗 link
- [ ] Gửi hình TRƯỚC bản tin text
- [ ] Graceful fallback: hình lỗi → gửi text bình thường

**Acceptance Criteria:**
- AC15: Extract og:image từ research articles
- AC16: Gửi qua Telegram `sendPhoto` với caption + hyperlink
- AC17: Tối đa 2-3 hình/ngày, chỉ từ research sources
- AC18: Fallback text nếu không có hình
- AC19: Caption ≤1024 ký tự

---

## 3. PHẠM VI ẢNH HƯỞNG

### Files cần sửa (12 files)

| # | File | Thay đổi chính |
|---|------|----------------|
| 1 | `collectors/rss_collector.py` | +4 feeds, +source_type, +og_image, +trafilatura, +Semaphore(25) |
| 2 | `collectors/cryptopanic_client.py` | +og_image field, +extract_metadata() |
| 3 | `collectors/data_cleaner.py` | Preserve source_type + og_image qua dedup |
| 4 | `delivery/telegram_bot.py` | Selective HTML escape, +send_photo(), split_message() update |
| 5 | `delivery/delivery_manager.py` | Mở rộng article dict, orchestrate photo+text |
| 6 | `delivery/email_backup.py` | Plain text → HTML format |
| 7 | `generators/article_generator.py` | +source_urls field, URL mapping |
| 8 | `generators/summary_generator.py` | Strip decorations trước cắt excerpt |
| 9 | `generators/template_engine.py` | Emoji headers + separators |
| 10 | `generators/nq05_filter.py` | +scan link text trong `<a>` tags |
| 11 | `daily_pipeline.py` | Truncation 5000→8000, truyền metadata qua pipeline |
| 12 | Google Sheets `MAU_BAI_VIET` | L3-L5 prompt templates cập nhật |

### KHÔNG thay đổi (confirmed safe qua 2 lần audit)
- ✅ Breaking pipeline (independent code paths)
- ✅ Market data / on-chain collectors
- ✅ Google Sheets tab schema (không thêm tab/cột)
- ✅ GitHub Actions workflows
- ✅ Dashboard data generator
- ✅ Config loader

### Tests ảnh hưởng

| Loại | Số lượng | Files |
|------|----------|-------|
| Cần update | ~57 functions / 11 files | test_rss_collector, test_telegram_bot, test_delivery_manager, test_article_generator, test_template_engine, test_config_loader, test_data_cleaner, test_summary_generator, test_pipeline_e2e, test_content_integration, test_pipeline_data_flow |
| Viết mới | ~20 functions | selective_escape, send_photo, og_image, semaphore, email_html, nq05_link_scan |

---

## 4. IMPLEMENTATION PLAN

### Tổng quan phân cụm

```
Cụm 0: Hạ tầng (fix hệ thống — prerequisite cho tất cả)
   ↓
Cụm 1: Research Feeds (Việc 1 — data collection)
   ↓
Cụm 2: Format & Hyperlinks (Việc 2 — delivery)
   ↓
Cụm 3: Hình ảnh (Việc 3 — phụ thuộc Cụm 1 cho og:image)
   ↓
Cụm 4: Integration test + QA + Review
```

### Cross-reference check (Quy tắc 16e-16g)

| Cụm | Files overlap với cụm khác? | Ghi chú |
|-----|------------------------------|---------|
| 0↔1 | `rss_collector.py` — Cụm 0 thêm Semaphore, Cụm 1 thêm feeds + source_type | Gộp: Semaphore làm trong Cụm 1 luôn |
| 0↔2 | `telegram_bot.py` — Cụm 0 fix escape, Cụm 2 thêm format | Gộp: fix escape trong Cụm 2 luôn (cùng file) |
| 1↔3 | `rss_collector.py` — Cụm 1 thêm feeds, Cụm 3 thêm og:image | Gộp: og:image làm trong Cụm 1 luôn (cùng lúc sửa dataclass) |
| 2↔3 | `telegram_bot.py` — Cụm 2 format, Cụm 3 send_photo | Tách: send_photo riêng method, không conflict |

**Kết quả cross-reference → Gộp lại thành 3 cụm:**

```
Cụm 1: Data Layer (feeds + source_type + og:image + Semaphore + trafilatura)
   ↓
Cụm 2: Delivery Layer (format + escape + hyperlinks + email + send_photo + truncation)
   ↓
Cụm 3: Generator Layer (article_generator URLs + summary strip + nq05 link scan + templates)
   ↓
Integration Test + QA + Review
```

---

### CỤM 1: DATA LAYER

**Mục tiêu:** Thu thập data research + og:image, giới hạn concurrent requests

**Files:** `rss_collector.py`, `cryptopanic_client.py`, `data_cleaner.py`

| Task | Mô tả | File:Lines | Agent |
|------|--------|-----------|-------|
| 1.1 | Thêm `source_type` field vào `FeedConfig` dataclass | rss_collector.py:32-39 | Amelia |
| 1.2 | Thêm `source_type` + `og_image` fields vào `NewsArticle` dataclass | rss_collector.py:67-93 | Amelia |
| 1.3 | Cập nhật `to_row()`: lưu `source_type` vào cột `event_type` (index 7, hiện empty) | rss_collector.py:to_row() | Amelia |
| 1.4 | Thêm 4 research feed URLs vào `DEFAULT_FEEDS` với `source_type="research"` | rss_collector.py:43-64 | Amelia |
| 1.5 | Gắn `source_type="news"` cho 17 feeds hiện tại | rss_collector.py:43-64 | Amelia |
| 1.6 | Thêm `trafilatura.extract()` cho research feeds (full text) | rss_collector.py:_fetch_feed() | Amelia |
| 1.7 | Thêm `trafilatura.extract_metadata()` cho research feeds (og:image) | rss_collector.py:_fetch_feed() | Amelia |
| 1.8 | Thêm `asyncio.Semaphore(25)` cho concurrent requests | rss_collector.py:collect_rss() | Amelia |
| 1.9 | Thêm `og_image` field vào `CryptoPanicArticle` + extract_metadata() | cryptopanic_client.py:22-37, _extract_fulltext() | Amelia |
| 1.10 | Verify `data_cleaner.py` preserve `source_type` + `og_image` qua dedup merge | data_cleaner.py:79-117 | Amelia |
| 1.11 | Viết tests cho tasks 1.1-1.10 | test_rss_collector.py, test_data_cleaner.py | Quinn |
| **Log** | *(Ghi sau khi implement)* | | |

**Pre-flight check:** Cụm 1 là cụm đầu tiên — không có cụm trước để check overlap.

**Downstream check sau Cụm 1:**
- `daily_pipeline.py` unified dict phải truyền `source_type` + `og_image`
- `article_generator.py` phải nhận `source_type` để ưu tiên research cho L3-L5
- `delivery_manager.py` phải nhận `og_image` cho send_photo

---

### CỤM 2: DELIVERY LAYER

**Mục tiêu:** Format bản tin mới + hyperlinks + send_photo + email HTML + truncation

**Files:** `telegram_bot.py`, `delivery_manager.py`, `email_backup.py`, `daily_pipeline.py`

| Task | Mô tả | File:Lines | Agent |
|------|--------|-----------|-------|
| 2.1 | Sửa HTML escaping: selective escape (whitelist `<a href>` tags, sanitize href no `javascript:`) | telegram_bot.py:144 | Amelia |
| 2.2 | Cập nhật `split_message()`: nhận diện `━━━` separator + emoji headers | telegram_bot.py:47-91 | Amelia |
| 2.3 | Mở rộng `TelegramMessage` dataclass: thêm `source_urls`, `image_urls` | telegram_bot.py:28-44 | Amelia |
| 2.4 | Thêm format method: plain text + source URLs → HTML formatted message | telegram_bot.py (new method) | Amelia |
| 2.5 | Thêm `send_photo()` method: `sendPhoto` API + caption ≤1024 chars | telegram_bot.py (new method) | Amelia |
| 2.6 | Mở rộng article dict: `{"tier", "content", "source_urls", "image_urls"}` | delivery_manager.py:66-76 | Amelia |
| 2.7 | Cập nhật `prepare_messages()`: truyền source_urls + image_urls | delivery_manager.py:prepare_messages() | Amelia |
| 2.8 | Orchestrate delivery: send_photo (nếu có) → send_message sequence | delivery_manager.py:deliver() | Amelia |
| 2.9 | Email backup: `msg.set_content(body, subtype="html")` | email_backup.py:95 | Amelia |
| 2.10 | Tăng truncation 5000 → 8000 ký tự | daily_pipeline.py:~512 | Amelia |
| 2.11 | Viết tests cho tasks 2.1-2.10 | test_telegram_bot.py, test_delivery_manager.py | Quinn |
| **Log** | *(Ghi sau khi implement)* | | |

**Pre-flight check trước Cụm 2:**
- [ ] Cụm 1 đã pass tests? → source_type + og_image data available
- [ ] daily_pipeline.py unified dict đã truyền metadata?

**Downstream check sau Cụm 2:**
- Email backup phải hoạt động đúng với HTML format
- Dashboard không bị ảnh hưởng (confirmed: không parse article content)

---

### CỤM 3: GENERATOR LAYER

**Mục tiêu:** Article generator truyền URLs, summary strip decorations, NQ05 scan links, templates

**Files:** `article_generator.py`, `summary_generator.py`, `nq05_filter.py`, `template_engine.py`, `daily_pipeline.py`

| Task | Mô tả | File:Lines | Agent |
|------|--------|-----------|-------|
| 3.1 | Mở rộng `GeneratedArticle` dataclass: thêm `source_urls: list[dict[str, str]]` | article_generator.py:56-66 | Amelia |
| 3.2 | Giữ mapping `{source_name → url}` từ news data, truyền cho delivery | article_generator.py + daily_pipeline.py | Amelia |
| 3.3 | Cập nhật news summary cho LLM: ưu tiên research articles cho L3-L5 context | daily_pipeline.py:204-221 | Amelia |
| 3.4 | Strip emoji + separator decorations trước cắt 800-char excerpt | summary_generator.py:~53 | Amelia |
| 3.5 | Thêm scan link text trong `<a>` tags cho NQ05 post-filter (chỉ output) | nq05_filter.py:96 | Amelia |
| 3.6 | Cập nhật template_engine: emoji headers + separators trong rendered output | template_engine.py:render_sections() | Amelia |
| 3.7 | Cập nhật Google Sheets `MAU_BAI_VIET`: L3-L5 prompts hướng dẫn trích dẫn research | Google Sheets (manual operator update) | Anh Cường |
| 3.8 | Viết tests cho tasks 3.1-3.6 | test_article_generator.py, test_summary_generator.py, test_nq05_filter.py, test_template_engine.py | Quinn |
| **Log** | *(Ghi sau khi implement)* | | |

**Pre-flight check trước Cụm 3:**
- [ ] Cụm 1 source_type data flowing correctly?
- [ ] Cụm 2 delivery layer nhận source_urls?
- [ ] Issues nào từ Cụm 1-2 đã auto-resolve tasks ở Cụm 3?

---

### CỤM 4: INTEGRATION TEST + QA + REVIEW

| Task | Mô tả | Agent |
|------|--------|-------|
| 4.1 | Update ~57 existing test functions (mock data + assertions) | Quinn |
| 4.2 | Integration test: full pipeline mock run (collect → generate → deliver) | Quinn |
| 4.3 | Test selective HTML escape: XSS prevention, `javascript:` blocked, normal links work | Quinn |
| 4.4 | Test send_photo: success, timeout, invalid URL, caption truncation | Quinn |
| 4.5 | Test email HTML: Gmail + Outlook rendering (manual verify) | Quinn |
| 4.6 | Test graceful fallback: no research feeds → normal operation | Quinn |
| 4.7 | Test graceful fallback: og:image fail → text-only delivery | Quinn |
| 4.8 | Test Semaphore: 25 concurrent limit respected | Quinn |
| 4.9 | Full regression: `uv run pytest` — ALL tests pass | Quinn |
| 4.10 | Coverage check: ≥80% cho code mới, ≥60% tổng (CI requirement) | Quinn |
| 4.11 | Code review: kiến trúc, selective escape security, cross-module impact | Winston |
| 4.12 | Code review: business logic, NQ05 compliance, format đúng spec | Mary |
| 4.13 | PIVP: exhaustive grep scan trước + sau thay đổi | Winston + Mary |
| **Log** | *(Ghi sau khi complete)* | | |

---

### CỤM 5: DOCUMENTATION + REPORT

| Task | Mô tả | Agent |
|------|--------|-------|
| 5.1 | Cập nhật `CHANGELOG.md` — version bump + 3 features + 6 fixes | Paige |
| 5.2 | Cập nhật `CLAUDE.md` — new collectors, new delivery features | Paige |
| 5.3 | Cập nhật `src/cic_daily_report/__init__.py` — version number | Paige |
| 5.4 | Cập nhật `docs/architecture.md` — research feeds layer, selective escape | Paige |
| 5.5 | Ghi Implementation Log vào spec này (Section 4 mỗi cụm) | Paige |
| 5.6 | Báo cáo cuối cho Anh Cường | Bob |

---

## 5. RỦI RO & GIẢM THIỂU

| # | Rủi ro | Mức | Giảm thiểu |
|---|--------|-----|-----------|
| R1 | Messari Free chỉ cho summary ngắn | Thấp | 3 nguồn còn lại cho full content |
| R2 | Research feeds weekly → nhiều ngày không có bài | Trung bình | Fallback: dùng news data |
| R3 | og:image bị block/unavailable | Thấp | Fallback RSS media → skip hình → text only |
| R4 | Selective HTML escape bỏ sót XSS | Trung bình | Whitelist ONLY `<a href>`, sanitize href (no `javascript:`), Quinn test kỹ |
| R5 | Email clients render HTML khác nhau | Thấp | Test Gmail + Outlook |
| R6 | 71 concurrent requests gây nghẽn | Trung bình | Semaphore(25) |
| R7 | Truncation 8000 chars cắt giữa emoji | Thấp | Validate: lùi về safe boundary nếu cắt multi-byte |
| R8 | trafilatura.extract_metadata() chậm | Thấp | Chỉ gọi cho 4 research feeds |

---

## 6. QUYẾT ĐỊNH ANH CƯỜNG (2026-03-13)

| # | Quyết định | Lý do |
|---|-----------|-------|
| QĐ-A | Giữ tier tags `[L1]`-`[L5]` | Đã quen, không cần đổi |
| QĐ-B | Dùng chung format Telegram cho BIC Group | Không cần format riêng |
| QĐ-C | NQ05 chỉ scan OUTPUT, không scan input | Research articles có từ cấm trong context phân tích — vẫn cần lấy insights |
| QĐ-D | Email format giống Telegram (HTML) | Tìm giải pháp → đổi sang HTML |
| QĐ-E | Tăng giới hạn Sheets | Tìm giải pháp → tăng 5000→8000 |
| QĐ-F | Summary strip decorations | Tìm giải pháp → strip trước cắt |
| QĐ-G | NotebookLM: thủ công, không vào scope | Tạm thời copy/paste |

---

## 7. AUDIT LOG

### Lần 1 (2026-03-13) — Đối chiếu PRD + Architecture + Source Code
**Agents:** Mary (PRD/Architecture), Winston (Source code), Quinn (Tests)

**Phát hiện 6 vấn đề:**
1. HTML escaping phá hyperlinks (`telegram_bot.py:144` — `html_lib.escape()`)
2. Article dict chỉ có `tier` + `content` (thiếu metadata)
3. Source URLs không truyền vào LLM (news_summary không có URL)
4. `split_message()` cần separator mới
5. Sheets schema: tận dụng cột `event_type` có sẵn
6. trafilatura đã có sẵn, không cần dependency mới

### Lần 2 (2026-03-13) — Deep audit 10 modules bổ sung
**Agents:** Mary + Winston (audit), John (NotebookLM research)

**Phát hiện thêm 6 vấn đề:**
7. NQ05 filter bỏ sót HTML tags (`nq05_filter.py:96`)
8. Email backup plain text (`email_backup.py:95`)
9. Sheets truncation 5000 chars (`daily_pipeline.py:~512`)
10. Summary generator cắt 800 chars, có thể cắt giữa emoji
11. 71 concurrent requests không limit
12. CryptoPanic chưa lấy og:image

### Cross-reference (Quy tắc 16e)
- Cụm 0↔1 overlap `rss_collector.py` → gộp Semaphore vào Cụm 1
- Cụm 0↔2 overlap `telegram_bot.py` → gộp escape fix vào Cụm 2
- Cụm 1↔3 overlap `rss_collector.py` → gộp og:image vào Cụm 1

---

## 8. DISCUSSION LOG (FULL)

### Phiên 1: Khởi động + Yêu cầu ban đầu (Party Mode)

**Anh Cường** đưa yêu cầu:
> "Có cách nào để kéo các bài viết Messari cho AI tổng hợp và phân tích đưa vào Daily Report mỗi ngày không? Ngoài ra cần sửa lại định dạng output của bản tin."

Anh Cường chia sẻ:
- Screenshot email Messari Research Alert: "In The Stables: The Rise of Yield-Bearing Stablecoins"
- Screenshot bài full trên messari.io (Alexander Beaudry, Austin Freimuth)
- Screenshot bản tin Telegram hiện tại (Crypto Daily Report [L1], [L2]) — khó đọc

**John (PM)**: Tách 2 yêu cầu — (1) Tích hợp Messari research, (2) Format lại output. Hỏi: Anh dùng Messari Free hay Pro?

**Winston (Architect)**: Đề xuất 3 hướng: RSS public (free), Web scrape (trafilatura), Messari API (Enterprise). Khuyến nghị hướng A (RSS) trước.

**Mary (Analyst)**: Phân tích giá trị bài Messari — yield-bearing stablecoins tăng 15x, Mastercard+SoFi integration, $3.7B net inflows. L3/L5 sẽ chất lượng hơn.

**Sally (UX)**: Phân tích vấn đề format — tường chữ, thiếu emoji, data lẫn text, `##` raw markdown. Đề xuất format mới với emoji headers + separators.

**Amelia (Dev)**: Đánh giá effort — RSS thêm feed nhỏ, format sửa `telegram_bot.py` + prompt templates.

### Phiên 2: Anh Cường phản hồi

**Anh Cường**: Dùng Messari Free. Hỏi: nếu RSS không lấy được thì có nguồn tương tự?

**Mary**: Liệt kê 8 nguồn research miễn phí — đánh giá Glassnode Insights + CoinMetrics cao nhất.

**Winston**: Đề xuất "Research Feed Layer" — tách riêng collector cho research vs news.

**Sally**: Cập nhật format: thêm `🔗` hyperlink nguồn cho mỗi tin + cuối section.

**Amelia**: Telegram hỗ trợ `<a href>` trong HTML parse mode.

### Phiên 3: Hình ảnh

**Anh Cường**: Có lấy được hình từ bài research/tin tức không?

**Winston**: Phân tích 4 cách lấy hình — og:image, RSS media, inline images, OG tags. Đề xuất og:image (dễ nhất, chất lượng).

**Mary**: Phân biệt hình đáng lấy (chart, infographic) vs không đáng (stock photo, avatar).

**Amelia**: Đề xuất lọc theo source thay vì phân tích hình — research sites luôn dùng chart, news sites dùng stock photo. Độ chính xác ~85-90%.

**Sally**: Format bản tin: tin nổi bật = text only, phân tích chuyên sâu = ảnh + caption.

**Amelia**: `send_photo` caption tối đa 1024 chars — chỉ phù hợp cho tin ngắn/highlight.

### Phiên 4: Chọn hình khi nhiều nguồn

**Anh Cường**: Nếu nhiều nguồn có hình thì lấy hình nào?

**Winston**: Đề xuất Image Scoring (Source Weight 40% + Content Type 35% + Topic Relevance 25%).

**Mary**: Phân tích hình đáng vs không đáng lấy.

**Amelia**: Đề xuất đơn giản — lọc theo source (research > news), không cần AI vision. Tối đa 2-3 hình/ngày.

**Sally**: Quy tắc: tin tổng quan = text only, phân tích chuyên sâu = ảnh + caption.

**John**: Tóm tắt scope 3 việc — Anh Cường đồng ý → tạo spec.

### Phiên 5: Spec v1 + Yêu cầu audit

**Paige**: Ghi spec v1 từ thảo luận.
**Bob**: Tóm tắt cho Anh Cường.

**Anh Cường**: Yêu cầu double check — ảnh hưởng hệ thống, đối chiếu design docs, ý tưởng cải tiến?

### Phiên 6: Audit lần 1

**Mary**: Đối chiếu PRD — phát hiện FR31 (tier tags mandatory), FR30 (copy-paste ready), URLs không truyền vào LLM, research weekly.

**Winston**: Audit source code — phát hiện HTML escape phá links, article dict thiếu metadata, split_message cần update, trafilatura có sẵn.

**Quinn**: 57 test functions / 11 files bị ảnh hưởng. Breaking pipeline SAFE.

**John**: Đề xuất cập nhật spec. 2 câu hỏi cho Anh Cường: tier tags + BIC Group format.

### Phiên 7: Anh Cường quyết định + Audit lần 2

**Anh Cường**: Giữ tier tags. Dùng chung format. Tìm hiểu NotebookLM.

**Winston + Mary (Audit lần 2)**: Phát hiện thêm 6 vấn đề — NQ05 bỏ sót HTML, email plain text, Sheets truncation, summary cắt lỗi, concurrent requests, CryptoPanic thiếu og:image.

**John (NotebookLM research)**: Enterprise API có (trả phí, chỉ audio). SDK không chính thức có (full nhưng rủi ro). Đề xuất: tạm thủ công.

### Phiên 8: Anh Cường phản hồi audit lần 2

**Anh Cường** quyết định cho 6 vấn đề:
1. NQ05: chỉ kiểm duyệt output (research có từ cấm vẫn lấy)
2. Email: chỉnh format giống Telegram
3. Sheets: tìm giải pháp → tăng limit
4. Summary: tìm giải pháp → strip decorations
5. Concurrent: tìm giải pháp → Semaphore
6. og:image: tìm giải pháp → trafilatura metadata
7. NotebookLM: copy/paste thủ công

**Winston**: Giải pháp kỹ thuật cho từng vấn đề.
**Mary**: Cross-check + phát hiện thêm: cần hyperlink mapping strategy.
**Quinn**: Đề xuất kết hợp: tin nổi bật link riêng, phân tích gộp nguồn cuối.

### Phiên 9: Approve spec + Lên plan

**Anh Cường**: Approve spec v2. Yêu cầu:
> "Log lại toàn bộ thảo luận vào spec, lên plan chi tiết rồi team dựa vào đó phân công test → double check → QA/QC → Review → update vào doc → báo cáo anh"

→ Spec v3 (final) được tạo — bao gồm toàn bộ discussion log + implementation plan.

---

## 9. TÓM TẮT CHO ANH CƯỜNG (Bob)

### Yêu cầu ban đầu
1. Kéo bài phân tích từ Messari và nguồn tương tự vào Daily Report
2. Sửa lại giao diện bản tin cho dễ đọc + thêm link nguồn
3. Thêm hình ảnh minh họa

### Team sẽ làm
- **3 việc chính**: Thêm 4 nguồn phân tích + format bản tin mới + gửi hình chart
- **6 fix hệ thống**: Link bị hỏng, email hiển thị lỗi, giới hạn ký tự, cắt lỗi, nghẽn mạng, thiếu hình
- **Sửa 12 files** code + cập nhật mẫu trên Google Sheets
- **~77 bài kiểm tra** (57 cập nhật + 20 mới)

### Quy trình thực hiện
Cụm 1 (thu thập data) → Cụm 2 (gửi tin) → Cụm 3 (viết bài) → Kiểm tra toàn bộ → Cập nhật tài liệu → Báo cáo

### Không ảnh hưởng
- Bản tin Breaking News
- Giờ chạy (08:05 sáng)
- Ngày không có bài phân tích mới → chạy bình thường

---

*Spec v3.0 Final — Approved by Anh Cường 2026-03-13. Ready for implementation.*
