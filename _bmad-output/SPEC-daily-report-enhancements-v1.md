# SPEC: CIC Daily Report — Nâng cấp Research Feeds, Format Telegram & Hình ảnh

> **Version**: 1.0 | **Date**: 2026-03-13
> **Track**: B (Feature) | **Priority**: P1
> **Requested by**: Anh Cường | **Spec by**: John (PM)
> **Origin**: Party Mode discussion session 2026-03-13

---

## 1. BỐI CẢNH & MỤC TIÊU

### Vấn đề hiện tại
1. **Thiếu nguồn phân tích chuyên sâu**: Pipeline hiện tại dùng 17 RSS feeds + CryptoPanic — toàn tin tức bề mặt, chưa có research/analysis từ nguồn chất lượng cao (Messari, Glassnode, CoinMetrics...). L3-L5 thiếu insight sâu.
2. **Bản tin Telegram khó đọc**: Hiện tại hiển thị raw markdown (`##` headers), tường chữ không phân tách, số liệu lẫn trong text, thiếu visual markers.
3. **Thiếu hình ảnh minh họa**: Không có chart/visualization kèm bản tin — người đọc phải tưởng tượng data.

### Mục tiêu
- Tích hợp 4+ nguồn research chất lượng cao vào pipeline
- Format lại bản tin Telegram cho dễ đọc (emoji headers, separator, data dạng bảng)
- Thêm hyperlink nguồn trích dẫn cho mỗi tin
- Gửi 1-2 hình chart/infographic từ research sources mỗi ngày

---

## 2. YÊU CẦU CHI TIẾT

### 2.1. Việc 1 — Research Feeds Layer

**Mô tả**: Thêm lớp collector mới chuyên cho bài phân tích/research, tách biệt với news feeds hiện tại.

**Nguồn mới (4 RSS feeds):**

| # | Nguồn | URL Feed | Loại | Tần suất |
|---|-------|----------|------|----------|
| R1 | Messari Research | RSS public (messari.io) | Sector research, protocol analysis | Weekly |
| R2 | Glassnode Insights | Blog RSS (insights.glassnode.com) | On-chain analysis chuyên sâu | 2-3x/week |
| R3 | CoinMetrics "State of the Network" | Substack RSS | Network data + macro-crypto | Weekly |
| R4 | Galaxy Digital Research | Blog RSS | Institutional-grade macro + sector | Weekly |

**Yêu cầu kỹ thuật:**
- [ ] Thêm 4 feed URLs vào `rss_collector.py`
- [ ] Gắn tag `source_type: "research"` cho các feed mới (phân biệt với `"news"`)
- [ ] `trafilatura` extract full text cho research articles (đã có sẵn cơ chế)
- [ ] Nếu Messari Free chỉ cho summary (~200-300 từ) → vẫn giữ, vì 3 nguồn kia cho full content
- [ ] Research articles ưu tiên đưa vào context cho L3-L5 (tầng phân tích sâu)
- [ ] Prompt template L3-L5 cần cập nhật: hướng dẫn LLM trích dẫn research insights

**Acceptance Criteria:**
- AC1: Pipeline collect được bài từ ít nhất 3/4 nguồn research mới
- AC2: Bài research được gắn tag `source_type: "research"` trong data
- AC3: L3-L5 articles có trích dẫn/reference từ research sources khi có bài mới
- AC4: Không ảnh hưởng performance pipeline hiện tại (thêm ≤5s collection time)
- AC5: Graceful fallback nếu feed nào không available

### 2.2. Việc 2 — Format lại Telegram Output

**Mô tả**: Thiết kế lại layout bản tin Telegram cho dễ đọc, thêm hyperlink nguồn.

**Format mới đề xuất (đã được Anh Cường approve):**

```
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

**Yêu cầu kỹ thuật:**
- [ ] `telegram_bot.py`: Đổi sang `parse_mode="HTML"` (nếu chưa)
- [ ] Thay `##` markdown headers → emoji headers + `━━━` separator lines
- [ ] Data thị trường format dạng bảng ngắn gọn (symbol + giá + % thay đổi)
- [ ] Mỗi tin có `🔗 <a href="url">Tên nguồn</a>` hyperlink
- [ ] Cuối section phân tích: liệt kê nguồn research đã tham khảo
- [ ] Giữ nguyên logic smart splitting (QĐ6) — điều chỉnh split points cho format mới
- [ ] Disclaimer cuối bản tin (NQ05 compliance)
- [ ] Thay label `[L1]`, `[L2]`... bằng tên tier dễ hiểu cho người đọc

**Source URL flow:**
```
RSS collector (link field) ──→ article_generator (truyền URL) ──→ telegram_bot (format <a> tag)
CryptoPanic (url field) ──────┘
```

**Acceptance Criteria:**
- AC6: Bản tin Telegram hiển thị đúng format mới (emoji headers, separators, data bảng)
- AC7: Mỗi tin nổi bật có hyperlink click được đến bài gốc
- AC8: Section phân tích có danh sách nguồn trích dẫn hyperlink
- AC9: Smart splitting không cắt giữa section/câu
- AC10: NQ05 disclaimer hiển thị đúng ở cuối mỗi bản tin
- AC11: Labels tier dễ hiểu (không dùng L1/L2/L3 raw)

### 2.3. Việc 3 — Hình ảnh từ Research Sources

**Mô tả**: Gửi 1-2 hình preview (chart/infographic) từ nguồn research kèm bản tin.

**Quy tắc chọn hình:**

| Ưu tiên | Nguồn | Lý do |
|---------|-------|-------|
| 1 | Research sources (Glassnode, CoinMetrics, Messari, Galaxy) | Hầu như luôn là chart/data — có giá trị thông tin cao |
| 2 | Bỏ qua news sources (CoinDesk, CoinTelegraph...) | Thường là stock photo — không có giá trị thông tin |

**Logic chọn hình (source-based, không cần AI vision):**
```
1. Lấy og:image từ TẤT CẢ bài viết (1 request/bài, parse <meta property="og:image">)
2. Lọc: chỉ giữ hình từ source_type="research"
3. Chọn top 2-3 hình gắn với tin/research nổi bật nhất
4. Nếu ngày nào không có research mới → bỏ qua hình, chỉ gửi text
```

**Yêu cầu kỹ thuật:**
- [ ] Extract `og:image` URL từ mỗi bài viết (thêm vào RSS collector hoặc riêng)
- [ ] Fallback: RSS `<media:content>` hoặc `<enclosure>` tag
- [ ] `telegram_bot.py`: Thêm method `send_photo(chat_id, photo=url, caption=text, parse_mode="HTML")`
- [ ] Caption tối đa 1024 ký tự (giới hạn Telegram API) — format ngắn gọn
- [ ] Gửi hình TRƯỚC hoặc GIỮA bản tin text (không gửi cuối — mất chú ý)
- [ ] Tối đa 2-3 hình/ngày — không gửi nhiều hơn
- [ ] Graceful fallback: nếu không lấy được hình → gửi text bình thường

**Acceptance Criteria:**
- AC12: Pipeline extract được og:image URL từ research articles
- AC13: Hình được gửi qua Telegram `send_photo` với caption có hyperlink
- AC14: Tối đa 2-3 hình/ngày, chỉ từ research sources
- AC15: Nếu không có research mới hoặc hình lỗi → bản tin text vẫn gửi bình thường
- AC16: Caption ≤1024 ký tự, format đúng HTML

---

## 3. PHẠM VI ẢNH HƯỞNG

### Files cần sửa/thêm

| File | Thay đổi |
|------|----------|
| `src/cic_daily_report/collectors/rss_collector.py` | Thêm 4 research feeds + `source_type` tag + `og:image` extraction |
| `src/cic_daily_report/delivery/telegram_bot.py` | Format mới + `send_photo()` method + HTML parse mode |
| `src/cic_daily_report/delivery/delivery_manager.py` | Orchestrate photo + text delivery |
| `src/cic_daily_report/generators/article_generator.py` | Truyền source URLs vào generated content + ưu tiên research cho L3-L5 |
| `src/cic_daily_report/generators/template_engine.py` | Template format mới (emoji headers, separators) |
| Google Sheets `MAU_BAI_VIET` | Cập nhật prompt templates cho L3-L5 (trích dẫn research) |
| Google Sheets `MAU_BAI_VIET` | Cập nhật format output (emoji layout) |
| `tests/` | Tests mới cho tất cả thay đổi |

### Không thay đổi
- Breaking pipeline (giữ nguyên)
- Market data / on-chain collectors (giữ nguyên)
- Google Sheets schema (không thêm tab mới)
- GitHub Actions workflows (không thay schedule)

---

## 4. RỦI RO & GIẢM THIỂU

| Rủi ro | Mức | Giảm thiểu |
|--------|-----|-----------|
| Messari Free chỉ cho summary ngắn | Thấp | 3 nguồn còn lại cho full content — Messari summary vẫn có giá trị |
| Research feeds ít bài (weekly) → ngày không có research | Trung bình | Graceful fallback: ngày không có research → bản tin chỉ dùng news như cũ |
| `og:image` bị block/unavailable | Thấp | Fallback RSS `<media:content>` → nếu vẫn không có → skip hình, gửi text |
| Telegram `send_photo` rate limit | Thấp | Giữ delay 1.5s giữa messages, tối đa 2-3 hình |
| Caption 1024 char limit quá ngắn | Trung bình | Format caption ngắn gọn: title + 1-2 câu insight + hyperlink |
| HTML parse lỗi trên một số Telegram client | Thấp | Test trên Android + iOS + Desktop, escape đúng HTML entities |

---

## 5. PHÂN CÔNG THỰC HIỆN (DỰ KIẾN)

| Agent | Việc | Phụ thuộc |
|-------|------|-----------|
| **Winston** | Thiết kế kỹ thuật chi tiết (data flow, interface) | Spec approved |
| **Quinn** | Test plan song song với thiết kế | Spec approved |
| **Amelia** | Implement Việc 1 (Research Feeds) | Thiết kế done |
| **Amelia** | Implement Việc 2 (Format Telegram) | Thiết kế done |
| **Amelia** | Implement Việc 3 (Hình ảnh) | Việc 1 done (cần og:image data) |
| **Quinn** | Test + QA (≥80% coverage + regression) | Implementation done |
| **Winston + Mary** | Code review | Implementation done |
| **Paige** | CHANGELOG + docs update | Review + QA pass |

---

## 6. TÓM TẮT CHO ANH CƯỜNG (Bob)

### Yêu cầu ban đầu
Anh Cường muốn:
1. Kéo bài phân tích từ Messari và các nguồn tương tự vào Daily Report
2. Sửa lại giao diện bản tin cho dễ đọc
3. Thêm hình ảnh minh họa (chart, infographic)

### Team đề xuất
- **Thêm 4 nguồn research** (Messari, Glassnode Insights, CoinMetrics, Galaxy Digital) — toàn miễn phí, chất lượng cao, bổ trợ tầng phân tích sâu L3-L5
- **Thiết kế lại bản tin** — dùng biểu tượng đánh dấu section, đường kẻ phân tách, số liệu dạng bảng, link nguồn click được
- **Gửi hình chart** từ nguồn research (1-2 hình/ngày) — chỉ lấy hình từ nguồn phân tích (thường là chart/data có giá trị), bỏ qua hình từ nguồn tin tức (thường là ảnh stock vô nghĩa)

### Ảnh hưởng
- Sửa ~7 files code + cập nhật template trên Google Sheets
- Không ảnh hưởng bản tin Breaking News
- Không thay đổi lịch chạy (vẫn 08:05 sáng)
- Nếu ngày nào không có bài research mới → bản tin chạy bình thường như cũ

### Effort
**Vừa** — cần thiết kế kỹ thuật + implement + test + review

---

*Spec này cần Anh Cường approve trước khi team triển khai.*
