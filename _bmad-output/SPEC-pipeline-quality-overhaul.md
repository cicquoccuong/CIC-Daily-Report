# SPEC: CIC Daily Report — Pipeline Quality Overhaul

> **Version**: 1.0 | **Date**: 2026-03-18
> **Track**: B — Feature | **Priority**: P0-P1
> **Requested by**: Anh Cường | **Spec by**: Team BMAD (Party Mode)
> **Status**: DRAFT — Chờ Anh Cường approve

---

## 1. BỐI CẢNH & VẤN ĐỀ

Anh Cường review output của CIC Daily Report (Breaking News + Daily Report) và phát hiện chất lượng chưa đạt yêu cầu. Team BMAD đã research sâu toàn bộ codebase và xác định **25 vấn đề gốc rễ** thuộc **6 nhóm**.

### Tóm tắt vấn đề (dễ hiểu)

| Vấn đề người dùng thấy | Nguyên nhân gốc rễ |
|------------------------|-------------------|
| Tin Breaking chung chung, không có giá trị | AI chỉ được cho xem tiêu đề, không được đọc bài gốc |
| Tin PIPPIN memecoin nhỏ gắn 🔴 ngang tin quốc gia | Hệ thống không phân biệt coin lớn/nhỏ, không lọc coin CIC |
| Daily Report lặp đi lặp lại giữa 5 tầng | Cùng data + cùng phân tích → 5 tầng viết giống nhau |
| Lãi suất Fed mâu thuẫn: 4.50% vs 3.75% | Ví dụ cứng trong prompt xung đột với data thật |
| AI vẫn viết "có thể ảnh hưởng đến thị trường" | Prompt cấm nhưng bộ lọc hậu kỳ không kiểm tra |
| Tin PIPPIN gửi 2 lần | Dedup dùng hash cứng, tiêu đề khác 1 từ thì qua |

---

## 2. DANH SÁCH VẤN ĐỀ CHI TIẾT (25 issues, 6 nhóm)

### NHÓM A: Breaking News — Thiếu nguyên liệu cho AI

| ID | Vấn đề | File | Dòng | Mức độ |
|----|--------|------|------|--------|
| A1 | CryptoPanic API không có nội dung bài — AI chỉ nhận tiêu đề (70% tin Breaking) | `breaking/content_generator.py` | 91-100 | P0 |
| A2 | Pipeline không gọi trafilatura cho Breaking — dù đã có sẵn thư viện | `breaking_pipeline.py` | 153-172 | P0 |
| A3 | Breaking không nhận data thị trường (giá BTC, F&G, DXY) | `breaking/content_generator.py` | 72-77 | P1 |
| A4 | Breaking không liên kết tin cũ — BREAKING_LOG có nhưng không dùng | `breaking/dedup_manager.py` | — | P1 |

### NHÓM B: Breaking News — Phân loại sai mức độ

| ID | Vấn đề | File | Dòng | Mức độ |
|----|--------|------|------|--------|
| B1 | Phần trăm bất kỳ ≥10% → auto CRITICAL (không phân biệt giá/volume/coin lớn/nhỏ) | `breaking/severity_classifier.py` | 156-163 | P0 |
| B2 | Không lọc coin CIC — nhận MỌI coin từ CryptoPanic "hot" feed | `breaking_pipeline.py` | 153-172 | P1 |
| B3 | Panic score dễ bị thổi phồng bởi vote spam trên CryptoPanic | `breaking/event_detector.py` | 189-216 | P2 |
| B4 | Keyword "crash" trong detection nhưng KHÔNG trong classification → logic rời rạc | `event_detector.py` + `severity_classifier.py` | 27-38, 35-68 | P1 |

### NHÓM C: Daily Report — Lặp lại giữa các tầng

| ID | Vấn đề | File | Dòng | Mức độ |
|----|--------|------|------|--------|
| C1 | Inter-tier context quá yếu — chỉ 120 ký tự/mục, tối đa 6 mục | `generators/article_generator.py` | 478-516 | P0 |
| C2 | Tất cả tầng nhận CÙNG Metrics Engine regime → cùng kết luận | `generators/metrics_engine.py` | 204-231 | P1 |
| C3 | Không có kiểm tra lặp sau khi viết xong 5 tầng | `daily_pipeline.py` | 542-559 | P1 |
| C4 | Template cứng "Tóm lược + Phân tích chi tiết" → lặp nội bộ mỗi tầng | `generators/template_engine.py` | 93-127 | P2 |

### NHÓM D: Daily Report — Số liệu mâu thuẫn

| ID | Vấn đề | File | Dòng | Mức độ |
|----|--------|------|------|--------|
| D1 | Tier context L3-L5 chứa ví dụ cứng (Fed 3.75%) xung đột data API thật (4.50%) | `daily_pipeline.py` | 452-511 | P0 |

### NHÓM E: AI & Bộ lọc chất lượng

| ID | Vấn đề | File | Dòng | Mức độ |
|----|--------|------|------|--------|
| E1 | NQ05 post-filter không kiểm tra filler phrases dù prompt đã cấm | `generators/nq05_filter.py` | 17-80 | P1 |
| E2 | Temperature 0.5 quá cao cho phân tích tài chính → AI bỏ qua quy tắc | `generators/article_generator.py` | 367 | P1 |
| E3 | Không có cổng đánh giá chất lượng trước khi gửi bài | — | — | P1 |
| E4 | Groq Llama fallback chất lượng thấp hơn Gemini, đặc biệt tiếng Việt | `adapters/llm_adapter.py` | 45 | P2 |
| E5 | NQ05 filter xóa NGUYÊN CÂU khi tìm thấy từ cấm → mất nội dung tốt | `generators/nq05_filter.py` | 83-102 | P1 |

### NHÓM F: Nguồn tin & Hạ tầng

| ID | Vấn đề | File | Dòng | Mức độ |
|----|--------|------|------|--------|
| F1 | full_text (2000 chars) bị mất trong data flow → AI chỉ nhận summary[:300] | `daily_pipeline.py` | 225-269 | P0 |
| F2 | 13 RSS news feeds KHÔNG được trích xuất nội dung (chỉ research feeds có) | `collectors/rss_collector.py` | 49-102 | P1 |
| F3 | 7 nguồn bị tắt (403/404) + 6 nguồn đã khảo sát nhưng chưa thêm | `collectors/rss_collector.py` | 49-102 | P1 |
| F4 | Dedup Breaking dùng hash cứng → tiêu đề khác 1 từ thì qua | `breaking/dedup_manager.py` | 79-82 | P1 |
| F5 | Bộ lọc crypto relevance xóa tin vĩ mô (Fed, lãi suất) không chứa từ "crypto" | `collectors/data_cleaner.py` | 290-326 | P1 |
| F6 | Pipeline không dừng khi data trống → AI viết bài "rỗng" | `daily_pipeline.py` | 206-221 | P2 |
| F7 | Telegram cắt bài dài >4000 ký tự không thông báo | `delivery/telegram_bot.py` | 119-150 | P2 |

---

## 3. PLAN GIẢI QUYẾT — CHIA THEO CỤM NGUYÊN NHÂN

> Gom theo chuỗi nguyên nhân (QUY-TRINH 9.2.2 rule 16g), không theo mức nguy hiểm.
> Cross-reference: fix Cụm 1 sẽ giải quyết phần nào Cụm 2 (cùng content_generator.py).

### CỤM 1: BREAKING NEWS CONTENT ENRICHMENT (A1, A2, A3, A4)
**Root cause chain**: CryptoPanic → no body → content_generator gets title only → generic output

#### Giải pháp đề xuất:

**1a. Thêm trafilatura vào Breaking pipeline (fix A1 + A2)**
- **Vị trí sửa**: `breaking/content_generator.py` hoặc `breaking_pipeline.py`
- **Cách làm**: Trước khi gọi AI viết, fetch URL bài gốc bằng trafilatura → trích xuất nội dung (tối đa 1500 ký tự)
- **Rủi ro**: Thêm 5-10 giây latency per event (trafilatura timeout)
- **Giảm thiểu**: Set timeout 8 giây, nếu fail thì fallback về title-only (như hiện tại)

**1b. Truyền market snapshot cho Breaking (fix A3)**
- **Vị trí sửa**: `breaking/content_generator.py` — thêm param `market_context`
- **Cách làm**: Khi generate breaking content, gọi nhanh market data API (BTC price, F&G, DXY) → inject vào prompt
- **Rủi ro**: Thêm API call → latency
- **Giảm thiểu**: Cache market data 5 phút (market_trigger đã collect rồi, reuse)

**1c. Truyền tin Breaking gần đây cho context (fix A4)**
- **Vị trí sửa**: `breaking/content_generator.py` — thêm param `recent_events`
- **Cách làm**: Lấy 3-5 tin breaking gần nhất từ BREAKING_LOG → thêm vào prompt
- **Ví dụ**: "Tin liên quan gần đây: Argentina chặn Polymarket (17/03), VN siết sàn nước ngoài (18/03)"
- **Lợi ích**: AI có thể nối các tin → thấy xu hướng

**1d. Thiết kế lại Breaking prompt (fix A1 tổng thể)**
- **Thay prompt cứng 3 phần** bằng prompt linh hoạt:
  - Phần 1: Tóm tắt nội dung cốt lõi (số liệu, ai liên quan, quy mô)
  - Phần 2: Đặt trong bối cảnh (liên kết thị trường, chính trị, vĩ mô, tin gần đây)
  - Phần 3: Ảnh hưởng cụ thể đến nhà đầu tư crypto
- **NQ05 compliance**: Giữ nguyên system prompt + post-filter

---

### CỤM 2: BREAKING NEWS SEVERITY & DEDUP (B1, B2, B3, B4, F4)
**Root cause chain**: No coin filter → any coin accepted → bad severity → duplicate alerts

#### Giải pháp đề xuất:

**2a. Thêm coin whitelist filter (fix B2)**
- **Vị trí sửa**: `breaking_pipeline.py` — sau detect, trước classify
- **Cách làm**: Load danh sách coin CIC từ CIC_DANH_SACH_COIN sheet → chỉ giữ events liên quan đến coin trong list
- **Exception**: Tin regulatory/macro (không gắn coin cụ thể) vẫn qua
- **Fallback**: Nếu không load được list → accept all (như hiện tại)

**2b. Phân biệt % giá vs % khác trong severity (fix B1)**
- **Vị trí sửa**: `breaking/severity_classifier.py` dòng 156-163
- **Cách làm**: Regex hiện tại bắt MỌI số %. Cần thêm context check:
  - Nếu tiêu đề chứa "volume", "trading volume", "open interest" → KHÔNG dùng % cho severity
  - Chỉ áp dụng % severity khi có keyword giá: "drops", "crashes", "surges", "gains", "falls", "plunges"
- **Thêm market cap check**: Nếu coin nhỏ (không trong top 100 CoinGecko) → cap severity ở IMPORTANT, không cho CRITICAL

**2c. Cải thiện dedup Breaking — thêm similarity check (fix F4)**
- **Vị trí sửa**: `breaking/dedup_manager.py`
- **Cách làm**: Sau hash check, thêm bước so sánh tiêu đề mới với 10 tiêu đề gần nhất → nếu similarity >70% → coi là trùng
- **Dùng**: SequenceMatcher (stdlib) — không cần thêm dependency

**2d. Đồng bộ keyword lists (fix B4)**
- **Vị trí sửa**: `event_detector.py` + `severity_classifier.py`
- **Cách làm**: Gộp "crash" vào DEFAULT_IMPORTANT_KEYWORDS (không phải critical)
- **Logic**: Crash = important, hack/exploit/ban = critical

---

### CỤM 3: DAILY REPORT — CHỐNG LẶP GIỮA CÁC TẦNG (C1, C2, C3, C4)
**Root cause chain**: Same data + same regime → weak inter-tier context → no post-gen check → repetition

#### Giải pháp đề xuất:

**3a. Tăng chất lượng inter-tier context (fix C1)**
- **Vị trí sửa**: `generators/article_generator.py` `_summarize_tier_output()`
- **Cách làm**: Thay vì 120 ký tự/mục, tóm tắt **key data points** đã phân tích:
  - "L1 đã cover: BTC=$74,589 (+0.0%), F&G=26, DXY=99.6. Tin chính: Fed meeting 19/03"
  - "L2 đã cover: TRX +3.6%, ADA +2.3%. Sector: DeFi yếu nhất"
- **Tăng limit**: 120 → 300 ký tự/mục, 6 → 10 mục

**3b. Tier-specific Metrics Engine output (fix C2)**
- **Vị trí sửa**: `generators/metrics_engine.py` `format_for_tier()`
- **Cách làm**: Thay vì gửi cùng regime cho mọi tầng, mỗi tầng nhận **góc nhìn khác**:
  - L1: "Regime = Recovery" (fact only)
  - L3: "Regime = Recovery, nhưng FR=-0.003% cho thấy derivatives trung tính" (WHY)
  - L4: "Regime = Recovery, NHƯNG F&G=26 mâu thuẫn → rủi ro pullback" (RISK)
  - L5: "Regime = Recovery. Base: sideways $73K-$77K. Bull trigger: DXY<99. Bear trigger: DXY>101" (SCENARIOS)

**3c. Post-generation repetition check (fix C3)**
- **Vị trí sửa**: `daily_pipeline.py` sau khi generate xong 5 tầng
- **Cách làm**: So sánh output L1-L5:
  - Extract key phrases (3+ words) xuất hiện >2 tầng → log warning
  - Nếu repetition score >50% → regenerate tầng vi phạm với stronger context
- **Lightweight**: Dùng set intersection, không cần LLM

**3d. Linh hoạt hóa template (fix C4)**
- **Vị trí sửa**: MAU_BAI_VIET Google Sheets
- **Cách làm**:
  - L1: Giữ "Tóm lược + Chi tiết" (người mới cần)
  - L3-L5: Chuyển sang "Insight trực tiếp" — không cần tóm lược riêng, viết thẳng phân tích

---

### CỤM 4: DAILY REPORT — DATA CONFLICTS (D1)
**Root cause chain**: Hardcoded example data → conflicts with real API data → LLM confusion

#### Giải pháp đề xuất:

**4a. Xóa số liệu cứng khỏi tier context (fix D1)**
- **Vị trí sửa**: `daily_pipeline.py` dòng 452-511
- **Cách làm**: Thay ví dụ có số liệu cụ thể (3.75%, 19/03) bằng ví dụ có placeholder:
  - TRƯỚC: `"Fed công bố lãi suất ngày 19/03, dự báo giữ 3.75%"`
  - SAU: `"[Sự kiện macro] — nếu [kết quả], [tác động lên DXY/crypto]"`
- **Hoặc**: Inject data thật vào ví dụ bằng code (thay `3.75%` bằng `{actual_fed_rate}`)

---

### CỤM 5: AI MODEL & FILTERS (E1, E2, E3, E4, E5)
**Root cause chain**: High temperature + no quality gate + incomplete filter → low quality output delivered

#### Giải pháp đề xuất:

**5a. Thêm filler phrases vào NQ05 post-filter (fix E1)**
- **Vị trí sửa**: `generators/nq05_filter.py`
- **Cách làm**: Thêm patterns:
  ```python
  FILLER_PATTERNS = [
      r"có thể ảnh hưởng đến",
      r"cần theo dõi (?:thêm|chặt chẽ)",
      r"điều này cho thấy",
      r"tuy nhiên cần lưu ý",
      r"trong bối cảnh",
  ]
  ```
- **Action**: KHÔNG xóa câu — thay bằng warning tag `[⚠️ GENERIC]` để AI regenerate hoặc operator review

**5b. Giảm temperature xuống 0.3 (fix E2)**
- **Vị trí sửa**: `generators/article_generator.py` dòng 367
- **Cách làm**: `temperature = 0.3` (từ 0.5)
- **Lý do**: Phân tích tài chính cần chính xác hơn sáng tạo

**5c. Thêm quality gate trước delivery (fix E3)**
- **Vị trí sửa**: `daily_pipeline.py` sau NQ05 filter
- **Cách làm**: Kiểm tra:
  - Min word count per tier (L1: 150, L5: 500)
  - Max filler phrase count (<3 per article)
  - Data citation count (≥2 số liệu cụ thể per section)
  - Cross-tier repetition score (<50%)
- **Action**: Nếu fail → log warning cho operator, vẫn gửi nhưng đánh dấu `[QUALITY: B]`

**5d. Sửa NQ05 filter — thay từ cấm thay vì xóa câu (fix E5)**
- **Vị trí sửa**: `generators/nq05_filter.py` dòng 83-102
- **Cách làm**: Thay vì xóa nguyên câu chứa "nên mua", chỉ xóa/thay cụm từ vi phạm
- **Ví dụ**: "BTC tăng 15% và nên mua vào" → "BTC tăng 15%" (giữ fact, xóa lời khuyên)

---

### CỤM 6: DATA PIPELINE & SOURCES (F1, F2, F3, F5, F6, F7)
**Root cause chain**: full_text lost → feeds not enriched → sources missing → data quality issues

#### Giải pháp đề xuất:

**6a. Giữ full_text trong data flow (fix F1)**
- **Vị trí sửa**: `daily_pipeline.py` dòng 225-245
- **Cách làm**: Thêm `"full_text": a.full_text` vào dict khi convert article
- **Sửa format**: Thay `summary[:300]` bằng `full_text[:1000]` hoặc `summary[:500]` (tuỳ token budget)
- **Token budget**: 30 articles × 1000 chars ≈ 7500 tokens — nằm trong giới hạn Gemini

**6b. Mở rộng trafilatura cho RSS news feeds (fix F2)**
- **Vị trí sửa**: `collectors/rss_collector.py`
- **Cách làm**: Hiện tại chỉ research feeds có trafilatura. Mở rộng cho TOP 5 news feeds quan trọng nhất:
  - CoinTelegraph, CoinDesk, TheBlock, Decrypt, Blockworks
- **Giới hạn**: Max 10 URLs per feed (không phải 20) để giữ tốc độ
- **Timeout**: 8 giây/URL

**6c. Thêm nguồn tin mới (fix F3)**
- **Vị trí sửa**: `collectors/rss_collector.py` DEFAULT_FEEDS
- **Thêm mới** (đã khảo sát, có RSS hoạt động):
  - `crypto.news/feed` (EN)
  - `bitcoinist.com/feed` (EN)
  - `cryptopotato.com/feed` (EN)
  - `blogtienao.com/feed` (VN)
- **Thử lại** feeds bị tắt: BeInCrypto_VN, CoinMetrics (có thể đã fix 403)

**6d. Cải thiện crypto relevance filter (fix F5)**
- **Vị trí sửa**: `collectors/data_cleaner.py` `_filter_non_crypto()`
- **Cách làm**: Thêm macro keywords vào whitelist:
  - "Fed", "FOMC", "interest rate", "lãi suất", "inflation", "CPI", "GDP", "tariff"
  - Tin chứa macro keywords → KHÔNG filter dù thiếu từ "crypto"

**6e. Thêm data quality gate (fix F6)**
- **Vị trí sửa**: `daily_pipeline.py` sau collection, trước generation
- **Cách làm**: Nếu `len(cleaned_news) < 5 AND market_data_empty`:
  - Log ERROR
  - Gửi thông báo cho operator: "Dữ liệu không đủ để tạo báo cáo hôm nay"
  - KHÔNG generate bài → tránh gửi bài rỗng

**6f. Thêm truncation warning cho Telegram (fix F7)**
- **Vị trí sửa**: `delivery/telegram_bot.py`
- **Cách làm**: Nếu bài >4000 ký tự, thêm footer: "... [Bài viết đã được rút gọn do giới hạn Telegram]"

---

## 4. THỨ TỰ THỰC HIỆN (ĐỀ XUẤT)

> Ưu tiên: Fix tầng nguyên liệu trước (data in) → fix tầng xử lý (AI/filter) → fix tầng hiển thị (delivery)

| Phase | Cụm | Issues | Effort | Dependency |
|-------|------|--------|--------|------------|
| **Phase 1** | Cụm 4 (D1) + Cụm 5a-5b (E1, E2) | 3 issues | Nhỏ | Không |
| **Phase 2** | Cụm 1 (A1-A4) | 4 issues | Lớn | Không |
| **Phase 3** | Cụm 2 (B1-B4, F4) | 5 issues | Vừa | Không |
| **Phase 4** | Cụm 6 (F1-F3, F5-F7) | 6 issues | Vừa | Không |
| **Phase 5** | Cụm 3 (C1-C4) + Cụm 5c-5e (E3, E4, E5) | 7 issues | Lớn | Phase 4 (cần data tốt hơn trước) |

### Phase 1 — Quick Wins (ít effort, impact cao)
- Xóa số liệu cứng khỏi tier context (D1)
- Thêm filler patterns vào NQ05 filter (E1)
- Giảm temperature 0.5 → 0.3 (E2)

### Phase 2 — Breaking News Enrichment (impact cao nhất)
- Trafilatura cho Breaking events
- Market context cho Breaking prompt
- Recent events context
- Redesign Breaking prompt

### Phase 3 — Breaking News Classification
- Coin whitelist filter
- Severity phân biệt giá/volume
- Dedup similarity check
- Keyword list cleanup

### Phase 4 — Data Pipeline Improvements
- Giữ full_text trong data flow
- Trafilatura cho top RSS feeds
- Thêm nguồn tin mới
- Fix crypto relevance filter
- Data quality gate
- Telegram truncation warning

### Phase 5 — Daily Report Anti-Repetition
- Cải thiện inter-tier context
- Tier-specific Metrics Engine
- Post-generation repetition check
- Template linh hoạt hóa
- Quality gate
- NQ05 filter sửa thay vì xóa

---

## 5. CROSS-REFERENCE CHECK

| Fix này... | ...cũng giải quyết phần nào... |
|-----------|-------------------------------|
| 1a (trafilatura Breaking) | → Giảm generic output (E1) vì AI có data cụ thể hơn |
| 6a (giữ full_text Daily) | → Giảm lặp (C1-C4) vì AI có nội dung khác nhau per article |
| 2a (coin whitelist) | → Giảm tin irrelevant (B1) vì lọc memecoin trước classify |
| 5b (temperature 0.3) | → Cải thiện compliance (E1) vì AI tuân thủ prompt tốt hơn |
| 4a (xóa ví dụ cứng) | → Giảm hallucination (E3) vì bớt data xung đột |

---

## 6. ACCEPTANCE CRITERIA (Anh Cường verify)

### Breaking News
- [ ] Tin Breaking có nội dung cốt lõi từ bài gốc (số liệu, ai liên quan, quy mô)
- [ ] Tin Breaking đặt trong bối cảnh (liên kết thị trường, tin gần đây)
- [ ] PIPPIN/memecoin nhỏ KHÔNG được gắn 🔴 CRITICAL
- [ ] Không gửi tin trùng (dù tiêu đề khác nhau)
- [ ] Tin vĩ mô (VN siết crypto) có đầy đủ chi tiết như bài gốc

### Daily Report
- [ ] 5 tầng có nội dung KHÁC NHAU — không lặp cùng câu/ý
- [ ] Số liệu NHẤT QUÁN giữa các tầng (không mâu thuẫn)
- [ ] Không còn câu "có thể ảnh hưởng đến thị trường" hoặc tương tự
- [ ] Tin Fed/macro KHÔNG bị lọc mất
- [ ] Bài viết có insight cụ thể, không chung chung

### Hệ thống
- [ ] ≥14 nguồn RSS hoạt động
- [ ] Khi data không đủ → thông báo operator, không gửi bài rỗng
- [ ] Bài dài bị cắt trên Telegram → có thông báo cho người đọc

---

## 7. GHI CHÚ

- Spec này chưa bao gồm thiết kế chi tiết (B3) — cần Anh Cường approve spec trước
- Mỗi Phase sẽ đi qua review + QA trước khi deploy (theo QUY-TRINH B5)
- Test coverage: Quinn sẽ viết test plan song song với implementation
