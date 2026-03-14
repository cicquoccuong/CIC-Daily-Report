# SPEC: CIC Daily Report — Nâng cấp Research Feeds, Format Telegram & Hình ảnh

> **Version**: 2.0 | **Date**: 2026-03-13
> **Track**: B (Feature) | **Priority**: P1
> **Requested by**: Anh Cường | **Spec by**: John (PM)
> **Origin**: Party Mode discussion session 2026-03-13
> **Audit**: 2-pass deep audit completed (Mary + Winston + Quinn)

---

## 1. BỐI CẢNH & MỤC TIÊU

### Vấn đề hiện tại
1. **Thiếu nguồn phân tích chuyên sâu**: Pipeline hiện tại dùng 17 RSS feeds + CryptoPanic — toàn tin tức bề mặt, chưa có research/analysis từ nguồn chất lượng cao. L3-L5 thiếu insight sâu.
2. **Bản tin Telegram khó đọc**: Hiện tại hiển thị raw markdown (`##` headers), tường chữ không phân tách, số liệu lẫn trong text, thiếu visual markers.
3. **Thiếu hình ảnh minh họa**: Không có chart/visualization kèm bản tin.

### Mục tiêu
- Tích hợp 4+ nguồn research chất lượng cao vào pipeline
- Format lại bản tin Telegram cho dễ đọc (emoji headers, separator, data dạng bảng)
- Thêm hyperlink nguồn trích dẫn cho mỗi tin
- Gửi 1-2 hình chart/infographic từ research sources mỗi ngày

### Quyết định Anh Cường (2026-03-13)
- Giữ nguyên tier tags `[L1]`-`[L5]`
- Dùng chung format Telegram cho BIC Group (không format riêng)
- NQ05 chỉ kiểm duyệt OUTPUT, không kiểm duyệt input (giữ research insights dù có từ cấm)
- NotebookLM: copy/paste thủ công — không vào scope lần này

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
- [ ] Thêm field `source_type` vào `FeedConfig` dataclass ("news" | "research")
- [ ] Gắn `source_type: "research"` cho 4 feeds mới, `"news"` cho 17 feeds hiện tại
- [ ] Tận dụng cột `event_type` (hiện ghi empty string) trong `NewsArticle.to_row()` để lưu `source_type` — KHÔNG thêm cột mới vào Sheets schema
- [ ] Dùng `trafilatura.extract()` cho research articles để lấy full text (chưa có trong RSS collector, chỉ CryptoPanic dùng)
- [ ] Dùng `trafilatura.extract_metadata()` để lấy `og:image` URL (xem Việc 3)
- [ ] Research articles ưu tiên đưa vào context cho L3-L5 prompts
- [ ] Prompt template L3-L5 cập nhật: hướng dẫn LLM tổng hợp research insights
- [ ] NQ05 filter KHÔNG scan input articles — chỉ scan LLM output (Anh Cường quyết định)
- [ ] Thêm `asyncio.Semaphore(25)` giới hạn concurrent requests (hiện không có limit)

**Acceptance Criteria:**
- AC1: Pipeline collect được bài từ ít nhất 3/4 nguồn research mới
- AC2: Bài research được gắn `source_type: "research"` trong data (lưu vào cột `event_type` trên Sheets)
- AC3: L3-L5 articles tổng hợp research insights khi có bài mới
- AC4: Không ảnh hưởng performance pipeline (thêm ≤5s collection time, tổng ≤10 min NFR4)
- AC5: Graceful fallback nếu feed nào không available
- AC6: Ngày không có research mới → bản tin vẫn chạy bình thường dùng news data

### 2.2. Việc 2 — Format lại Telegram Output

**Mô tả**: Thiết kế lại layout bản tin + thêm hyperlink nguồn + fix các vấn đề hệ thống liên quan.

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

**Hyperlink mapping strategy:**
- **Section "Tin Nổi Bật"**: Mỗi bullet = 1 tin = 1 URL rõ ràng → link riêng/tin
- **Section "Phân Tích Chuyên Sâu"**: Tổng hợp nhiều nguồn → liệt kê tất cả nguồn cuối section
- **Hyperlinks được thêm ở DELIVERY LAYER** (không phải LLM sinh) → LLM vẫn sinh plain text, delivery layer wrap `<a>` tags dựa trên source URL metadata

**Source URL data flow (SỬA LẠI từ v1):**
```
RSS collector ──→ unified dict ──→ article_generator ──→ plain text article
  (link field)    (url field)       (news_summary        (KHÔNG có HTML)
                   preserved)        có source_name           │
                                     KHÔNG có URL)            ↓
                                                        DELIVERY LAYER
                                                    ├─ Thêm emoji headers
                                                    ├─ Thêm ━━━ separators
                                                    ├─ Wrap <a href> hyperlinks
                                                    │   (từ source URL metadata
                                                    │    truyền song song)
                                                    ├─ Selective HTML escape
                                                    │   (escape text, GIỮ <a> tags)
                                                    └─ send_message() hoặc send_photo()
```

**Yêu cầu kỹ thuật:**

*Telegram Bot (`telegram_bot.py`):*
- [ ] Sửa HTML escaping logic: escape content text nhưng GIỮ NGUYÊN `<a>` tags (hiện tại `html_lib.escape()` escape TẤT CẢ → phá link). Codebase ghi chú tại line 139-140: "If HTML formatting tags are needed in future, move escaping to caller level"
- [ ] Cập nhật `split_message()`: nhận diện `━━━` separator + emoji headers thay vì `##` và `**...**`
- [ ] Giữ tier tags `[L1]`-`[L5]` (FR31 PRD compliance)
- [ ] Mở rộng `TelegramMessage` dataclass: thêm `source_urls: list[dict]` field
- [ ] Thêm format method: nhận plain text article + source URLs → output HTML formatted message

*Delivery Manager (`delivery_manager.py`):*
- [ ] Mở rộng article dict schema: `{"tier", "content", "source_urls", "image_urls"}` (hiện chỉ có `tier` + `content`)
- [ ] Orchestrate: format article → add hyperlinks → selective escape → send

*Article Generator (`article_generator.py`):*
- [ ] Mở rộng `GeneratedArticle` dataclass: thêm `source_urls: list[dict[str, str]]` (mỗi dict = `{"name": "Messari", "url": "https://..."}`)
- [ ] Truyền source URLs metadata song song với article content (KHÔNG embed URL trong LLM prompt — LLM sinh URL sai)
- [ ] Thêm news summary format mới cho LLM: vẫn `- {title} ({source_name})\n  Tóm tắt: {summary[:300]}` nhưng article_generator GIỮ LẠI mapping `{source_name → url}` để truyền cho delivery

*Email Backup (`email_backup.py`):*
- [ ] Đổi từ plain text → HTML format: `msg.set_content(body, subtype="html")` (hiện tại `msg.set_content(body)` → HTML tags hiện thô)

*Summary Generator (`summary_generator.py`):*
- [ ] Strip emoji + separator decorations TRƯỚC khi cắt 800-char excerpt: `re.sub(r'[━─═]+', '', content)` + bỏ emoji header lines

*NQ05 Filter (`nq05_filter.py`):*
- [ ] Thêm scan link text trong HTML `<a>` tags ở output — verify text bên trong `<a>...</a>` không chứa từ cấm NQ05
- [ ] KHÔNG scan input/source articles (Anh Cường quyết định: research có từ cấm vẫn lấy)

*Sheets Storage (`daily_pipeline.py`):*
- [ ] Tăng truncation limit `NOI_DUNG_DA_TAO` từ 5000 → 8000 ký tự (Google Sheets cho phép 50,000/cell, hiện tại code cắt ở 5000 quá thấp cho format mới)

**Acceptance Criteria:**
- AC7: Bản tin Telegram hiển thị đúng format mới (emoji headers, separators, data bảng)
- AC8: Mỗi tin nổi bật có hyperlink click được đến bài gốc (KHÔNG bị escape)
- AC9: Section phân tích có danh sách nguồn trích dẫn hyperlink cuối section
- AC10: Smart splitting nhận diện `━━━` separator, không cắt giữa section
- AC11: NQ05 disclaimer hiển thị cuối mỗi bản tin
- AC12: Email backup hiển thị HTML format đúng (link click được, emoji hiển thị)
- AC13: Summary generator không cắt giữa emoji/separator decorations
- AC14: NOI_DUNG_DA_TAO lưu được bài viết đầy đủ (≤8000 ký tự)

### 2.3. Việc 3 — Hình ảnh từ Research Sources

**Mô tả**: Gửi 1-2 hình preview (chart/infographic) từ nguồn research kèm bản tin.

**Quy tắc chọn hình:**

| Ưu tiên | Nguồn | Lý do |
|---------|-------|-------|
| 1 | Research sources (`source_type="research"`) | Hầu như luôn là chart/data |
| 2 | Bỏ qua news sources (`source_type="news"`) | Thường là stock photo |

**og:image extraction (dùng trafilatura — KHÔNG cần dependency mới):**
```python
# Trong RSS collector, SAU khi fetch feed:
metadata = trafilatura.extract_metadata(resp.text)
if metadata and metadata.image:
    article.og_image = metadata.image

# Fallback: RSS <media:content> hoặc <enclosure> tag
# feedparser đã parse sẵn: entry.get("media_content", [{}])[0].get("url")
```

**Yêu cầu kỹ thuật:**
- [ ] Thêm field `og_image: str | None` vào `NewsArticle` dataclass
- [ ] Thêm field `og_image: str | None` vào `CryptoPanicArticle` dataclass
- [ ] Extract og:image qua `trafilatura.extract_metadata()` cho research feeds
- [ ] Fallback: RSS `<media:content>` tag (feedparser đã parse)
- [ ] `telegram_bot.py`: Thêm method `send_photo(photo_url, caption, parse_mode="HTML")`
- [ ] Caption ≤1024 ký tự (Telegram API limit) — format: title + 1-2 câu + 🔗 link
- [ ] Gửi hình TRƯỚC bản tin text (điểm nhấn visual)
- [ ] Tối đa 2-3 hình/ngày, chỉ từ research sources
- [ ] Graceful fallback: hình lỗi/không có → gửi text bình thường
- [ ] `delivery_manager.py`: Orchestrate photo → text delivery sequence

**Acceptance Criteria:**
- AC15: Pipeline extract được og:image URL từ research articles qua trafilatura
- AC16: Hình được gửi qua Telegram `sendPhoto` API với caption có hyperlink
- AC17: Tối đa 2-3 hình/ngày, chỉ từ research sources
- AC18: Nếu không có research mới hoặc hình lỗi → bản tin text vẫn gửi bình thường
- AC19: Caption ≤1024 ký tự, format đúng HTML

---

## 3. PHẠM VI ẢNH HƯỞNG (ĐÃ AUDIT 2 LẦN)

### Files cần sửa

| File | Thay đổi | Audit notes |
|------|----------|-------------|
| `collectors/rss_collector.py` | Thêm 4 research feeds + `source_type` field + `og_image` field + trafilatura extract + Semaphore(25) | `FeedConfig` + `NewsArticle` dataclass + `to_row()` + `_fetch_feed()` |
| `collectors/cryptopanic_client.py` | Thêm `og_image` field + extract_metadata() | `CryptoPanicArticle` dataclass + `_extract_fulltext()` |
| `collectors/data_cleaner.py` | Preserve `source_type` + `og_image` qua dedup | Verify merge logic giữ metadata |
| `delivery/telegram_bot.py` | Selective HTML escape + `send_photo()` + `split_message()` update | CRITICAL: line 144 html_lib.escape() phải sửa |
| `delivery/delivery_manager.py` | Mở rộng article dict schema + orchestrate photo+text | `prepare_messages()` + delivery flow |
| `delivery/email_backup.py` | Plain text → HTML format | `msg.set_content(body, subtype="html")` |
| `generators/article_generator.py` | Thêm `source_urls` field + giữ URL mapping | `GeneratedArticle` dataclass + prompt flow |
| `generators/summary_generator.py` | Strip decorations trước cắt 800 chars | Line ~53: excerpt logic |
| `generators/template_engine.py` | Emoji headers + separators trong rendered output | `render_sections()` |
| `generators/nq05_filter.py` | Thêm scan link text trong `<a>` tags | Chỉ scan output, không scan input |
| `daily_pipeline.py` | Tăng truncation 5000→8000 + truyền source_urls/og_image qua pipeline | Line ~512 + unified dict schema |
| Google Sheets `MAU_BAI_VIET` | Cập nhật L3-L5 prompt templates | Operator update (không cần code change) |

### KHÔNG thay đổi (confirmed safe)
- ✅ Breaking pipeline (`breaking/` — independent code paths, verified)
- ✅ Market data / on-chain collectors
- ✅ Google Sheets tab schema (không thêm tab/cột mới)
- ✅ GitHub Actions workflows (không thay schedule/timeout)
- ✅ Dashboard data generator (không parse article content)
- ✅ Config loader (không thay schema)

### Tests bị ảnh hưởng (57 functions / 11 files)

| Mức | Files | Tests | Cần sửa |
|-----|-------|-------|---------|
| Nghiêm trọng | `test_article_generator.py`, `test_template_engine.py`, `test_config_loader.py` | ~17 | Mock data + schema changes |
| Trung bình | `test_telegram_bot.py`, `test_delivery_manager.py`, `test_pipeline_e2e.py` | ~16 | Format assertions |
| Nhẹ | `test_rss_collector.py`, `test_data_cleaner.py`, `test_summary_generator.py` | ~13 | Data structure changes |
| Mới | Tests mới cho: selective escape, send_photo, og:image, semaphore | ~15-20 | Viết mới |

---

## 4. RỦI RO & GIẢM THIỂU

| # | Rủi ro | Mức | Giảm thiểu |
|---|--------|-----|-----------|
| R1 | Messari Free chỉ cho summary ngắn | Thấp | 3 nguồn còn lại cho full content |
| R2 | Research feeds weekly → nhiều ngày không có bài mới | Trung bình | Graceful fallback: dùng news data, bỏ qua research reference |
| R3 | `og:image` bị block/unavailable | Thấp | Fallback RSS `<media:content>` → skip hình → text only |
| R4 | Selective HTML escape bỏ sót XSS | Trung bình | Whitelist ONLY `<a href>` tags, escape mọi thứ khác. Sanitize href URL (no `javascript:`) |
| R5 | Email clients render HTML khác nhau | Thấp | Test Gmail + Outlook. Emoji có thể hiển thị khác nhau |
| R6 | 71 concurrent requests gây nghẽn | Trung bình | Semaphore(25) cap concurrent connections |
| R7 | Truncation 8000 chars cắt giữa emoji | Thấp | Validate: nếu cắt giữa multi-byte char → lùi về safe boundary |
| R8 | trafilatura.extract_metadata() chậm | Thấp | Chỉ gọi cho research feeds (4 feeds), không gọi cho 17 news feeds |

---

## 5. PHÂN CÔNG THỰC HIỆN

| Bước | Agent | Việc | Phụ thuộc |
|------|-------|------|-----------|
| B3 | **Winston** | Thiết kế kỹ thuật chi tiết (data flow, interfaces, selective escape logic) | Spec v2 approved |
| B3 | **Quinn** | Test plan song song (bao gồm 57 tests cần update + ~20 tests mới) | Spec v2 approved |
| B4.1 | **Amelia** | Implement Việc 1: Research Feeds + source_type + og:image + Semaphore | Thiết kế done |
| B4.2 | **Amelia** | Implement Việc 2: Format Telegram + selective escape + hyperlinks + email HTML | Việc 1 done |
| B4.3 | **Amelia** | Implement Việc 3: send_photo() + image selection logic | Việc 2 done |
| B4.* | **Quinn** | Viết test song song với mỗi bước implement | Song song với Amelia |
| B5 | **Winston** | Code review: kiến trúc, selective escape security, cross-module impact | All implement done |
| B5 | **Mary** | Code review: business logic, NQ05 compliance, format đúng spec | All implement done |
| B5 | **Quinn** | QA: full regression (57 updated + ~20 new tests) + ≥80% coverage | Reviews done |
| B6 | **Paige** | CHANGELOG + CLAUDE.md + docs update | QA pass |
| B7 | **Bob** | Báo cáo kết quả cho Anh Cường | All done |

---

## 6. AUDIT LOG

### Lần 1 (2026-03-13)
- Đối chiếu PRD (FR29-33, FR31, FR30) + Architecture (QĐ4-QĐ6)
- Phát hiện: HTML escape phá links, article dict thiếu metadata, URLs không truyền vào LLM, split logic cần update, Sheets schema tận dụng cột có sẵn, trafilatura không cần dependency mới

### Lần 2 (2026-03-13)
- Deep audit 10 modules bổ sung
- Phát hiện: NQ05 bỏ sót HTML tags, email backup plain text, Sheets cắt 5000 chars, summary cắt 800 chars, 71 concurrent requests không limit, CryptoPanic chưa lấy og:image

### Quyết định Anh Cường (2026-03-13)
- NQ05 chỉ scan output, giữ input nguyên
- Email format giống Telegram
- Tăng giới hạn Sheets
- Giữ tier tags [L1]-[L5]
- NotebookLM: thủ công, không vào scope

---

## 7. TÓM TẮT CHO ANH CƯỜNG (Bob)

### Yêu cầu ban đầu
1. Kéo bài phân tích từ Messari và nguồn tương tự vào Daily Report
2. Sửa lại giao diện bản tin cho dễ đọc + thêm link nguồn
3. Thêm hình ảnh minh họa (chart, infographic)

### Team sẽ làm
- **Thêm 4 nguồn phân tích** (Messari, Glassnode, CoinMetrics, Galaxy Digital) — miễn phí
- **Thiết kế lại bản tin** — biểu tượng, đường kẻ, link nguồn click được
- **Gửi hình chart** từ nguồn phân tích (1-2 hình/ngày)
- **Sửa 6 vấn đề hệ thống** phát hiện qua audit (link bị hỏng, email hiển thị lỗi, giới hạn ký tự...)

### Ảnh hưởng
- Sửa 12 files code + cập nhật mẫu bài viết trên Google Sheets
- Cập nhật ~57 bài kiểm tra tự động + viết thêm ~20 bài mới
- **Không** ảnh hưởng bản tin Breaking News (đã kiểm tra 2 lần)
- **Không** thay đổi giờ chạy (08:05 sáng)
- Nếu ngày không có bài phân tích mới → bản tin chạy bình thường như cũ

### Effort
**Lớn hơn dự kiến ban đầu** — do phát hiện 12 vấn đề hệ thống cần sửa đồng bộ. Nhưng sửa ngay tốt hơn để sau — đúng nguyên tắc "fix hết, không chừa".

---

*Spec v2.0 — Cần Anh Cường approve trước khi team triển khai.*
