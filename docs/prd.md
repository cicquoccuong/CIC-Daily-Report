---
stepsCompleted: ['step-01-init', 'step-02-discovery', 'step-03-success', 'step-04-journeys', 'step-05-domain', 'step-07-project-type', 'step-08-scoping', 'step-09-functional', 'step-10-nonfunctional', 'step-11-polish', 'step-12-complete']
inputDocuments: ['CIC Daily Report/docs/brainstorming/brainstorming-session-2026-03-03.md']
workflowType: 'prd'
classification:
  projectType: 'Automated Content Intelligence & Delivery Pipeline'
  domain: 'fintech-crypto + content-publishing-socialfi'
  complexity: 'high'
  projectContext: 'greenfield-with-asset-reuse'
  primaryPlatform: 'BIC Group (articles) → BIC Chat (overview)'
  postingOrder: 'BIC Group FIRST → BIC Chat SECOND'
  outputCount: '5 tier articles (cumulative L1→L5) + 1 BIC Chat summary post'
  coinCoverage: 'tier-locked: L1=2, L2=19, L3=63, L4=133, L5=171 coins'
  videoGeneration: 'manual-mvp (NotebookLM), Phase2 automate'
  timeConstraint: 'pipeline run 8:00-8:30AM VN (sau nến ngày đóng 7AM), done trước 9AM'
  assetReuse: 'SonicR PAC TA engine from CIC Sentinel'
---

# Product Requirements Document - CIC Daily Report

**Author:** Anh Cường
**Date:** 2026-03-04

---

## Executive Summary

**Product:** CIC Daily Report — hệ thống tự động thu thập, phân tích và tạo báo cáo thị trường crypto hàng ngày cho cộng đồng Crypto Inner Circle (CIC) trên BIC Group/BIC Chat.

**Vision:** Mỗi sáng, 2,278+ members CIC nhận được bản phân tích thị trường chuyên sâu, đúng tier (L1→L5, cumulative 2→171 coins), tuân thủ NQ05 — tất cả được tạo tự động, tiết kiệm 2-3 tiếng/ngày cho operator.

**Differentiator:** Pipeline zero-cost (GitHub Actions + free APIs) với dual-layer content (TL;DR dễ hiểu + Full Analysis chuyên sâu), 13+ data sources, multi-LLM fallback, breaking news detection, và NQ05 compliance tự động.

**Target Users:**
- **Anh Cường (Operator)**: Nhận report trên Telegram, review, copy-paste lên BIC Group → BIC Chat
- **Members CIC L1-L5**: Đọc báo cáo hàng ngày trên BIC Group, nhận overview trên BIC Chat

**Tech Stack:** Python + GitHub Actions + Google Sheets + Groq/Gemini AI + Telegram Bot

**Integration:** Data từ Daily Report bổ trợ CIC Sentinel (FA scoring, event tracking, AI insights per coin)

---

## Success Criteria

### User Success

**Anh Cường (Operator):**
- Mỗi sáng sau 8:30 AM, **5 bài phân tích tier L1-L5 đã được generate sẵn** — Anh Cường chỉ cần đọc, review, tạo slides/video thủ công (NotebookLM) và post lên BIC Group → BIC Chat
- **Tiết kiệm 1.5–3 tiếng/ngày** so với quy trình thủ công hiện tại (tìm đọc → tổng hợp → viết → format)
- **Breaking news không bị block**: Khi có tin quan trọng/gấp, Anh Cường vẫn post riêng lên BIC Chat ngay lập tức — ngoài luồng pipeline tự động
- Cảm giác: **vui vẻ, thoải mái vào buổi sáng** — còn thời gian cho chiến lược và công việc khác

**Members CIC (L1–L5):**
- Nhận bản tin **đúng tier mình** mỗi sáng — phù hợp với số coin và độ phức tạp của tier
- **Không bị hoang mang hoặc FOMO** nhờ có market context đầy đủ (macro, on-chain, sentiment, technical) mỗi ngày
- Cảm giác **"CIC luôn đồng hành"** — dù thị trường tăng hay giảm, CIC vẫn có mặt với phân tích chất lượng
- **Khác biệt rõ ràng** với các group thông thường: thông tin được kiểm chứng, phân tích chuyên sâu, nhắc nhở chiến lược đầu tư đã có của CIC — không phải tín hiệu mua/bán rủi ro
- Tên coin **có thể được đề cập** trong ngữ cảnh tin tức và phân tích thị trường
- **Bài cuối có disclaimer**: "Nội dung mang tính cung cấp thông tin và giáo dục, không phải lời khuyên đầu tư" (NQ05-aligned)

### Business Success

- **Duy trì hoạt động cộng đồng**: Post đều đặn hàng ngày → engagement BIC Chat/Group ổn định, community sống động
- **Giữ chân members**: Members thấy value của membership qua nội dung chất lượng hàng ngày — không cần ra ngoài tìm thông tin từ các nguồn kém tin cậy
- **Uy tín CIC như research source**: Nhất quán, chuyên sâu, tuân thủ pháp lý — positioning khác biệt so với các group crypto thông thường
- **NOT in scope (MVP)**: Tăng số members mới — đây là sản phẩm phục vụ và giữ chân cộng đồng hiện tại

### Technical Success

> *Detailed measurement criteria for each metric: see Non-Functional Requirements section.*

| Metric | Target | Ghi chú |
|--------|--------|---------|
| Pipeline runtime | ≤40 phút | Run 8:00 AM, done trước 8:45 AM VN |
| Content ready | Trước 9:00 AM VN | Anh Cường review + post ~9:30-10:00 AM |
| Daily reliability | ≥95% | Pipeline miss ≤3 ngày/tháng |
| NQ05 compliance | 0 violations | Không khuyến nghị mua/bán cụ thể; disclaimer bắt buộc; tên coin OK trong ngữ cảnh tin tức |
| Tier coverage | 5 bài đúng cumulative | L1=2, L2=19, L3=63, L4=133, L5=171 coins |
| Content quality | Vietnamese tự nhiên | Không "robot-sounding", readable trong 5-10 phút |
| Cost | $0/tháng | Toàn bộ free tiers |
| Data freshness | After 7:00 AM VN | Sau khi nến ngày BTC đóng (00:00 UTC = 07:00 VN) |
| VN source coverage | ≥3 VN sites | Nguồn VN publish từ 7:30-8:00 AM VN trở đi |

### Measurable Outcomes

**3 tháng đầu:**
- Pipeline chạy ổn định ≥25 ngày/tháng (không miss)
- Anh Cường tiết kiệm ≥1.5 tiếng/ngày
- Ít nhất 1 member/tuần comment tích cực về chất lượng báo cáo trên BIC Chat

**6 tháng:**
- Tỷ lệ engagement (reactions/comments) trên BIC Chat posts tăng hoặc duy trì so với baseline
- CIC được nhắc đến như "nguồn phân tích tin cậy" trong community

---

## User Journeys

### J1 — Anh Cường: Morning Happy Path (Operator)

**Persona**: Anh Cường, người vận hành CIC, dậy lúc 8:45 AM.

**Opening Scene**: Anh Cường vừa pha cà phê, lấy điện thoại lên. Hôm qua thị trường pump mạnh, members BIC Chat chắc đang nóng lòng chờ phân tích. Trước đây, anh phải ngồi mở 10 tab, đọc từng trang, rồi ngồi soạn... mất 2–3 tiếng.

**Rising Action**: Anh mở Telegram. Bot đã gửi sẵn 6 tin nhắn từ 8:35 AM:
- 5 bài phân tích tier L1→L5 (copy-paste ready, format đúng BIC Group)
- 1 post tổng quát cho BIC Chat (market overview table + key highlights)

Anh đọc lướt bài L5 — phân tích BTC on-chain khá hay, diễn giải tự nhiên. L1 thì ngắn gọn, đúng 2 coin. Format chuẩn, có tier tag `[L2]`, `[L4]`, disclaimer cuối bài.

**Climax**: Anh copy bài L1, paste vào BIC Group → post. Tiếp tục L2, L3, L4, L5. Sau đó copy summary post → paste vào BIC Chat với video NotebookLM đã render xong. Toàn bộ quy trình: **15–20 phút** thay vì 3 tiếng.

**Resolution**: 9:15 AM, Anh Cường đã post xong. Members bắt đầu react và comment. Anh còn cả buổi sáng để làm việc khác.

**Requirements revealed**: Telegram delivery, formatted copy-paste content, tier-tagged articles, disclaimer auto-append, BIC Group + BIC Chat dual format.

---

### J2 — Anh Cường: Breaking News (Automated Pipeline)

**Persona**: Anh Cường, đang họp buổi chiều, không theo dõi thị trường.

**Opening Scene**: 2:30 PM — SEC Mỹ vừa công bố approve ETF Solana. Thị trường đang bùng nổ. Members BIC Chat flood comments hỏi "CIC nói gì?". Anh đang trong cuộc họp, không thể soạn bài ngay.

**Rising Action**: Hệ thống Breaking News Pipeline phát hiện sự kiện qua CryptoPanic panic score đột biến + RSS keywords ("SEC", "ETF", "approval"). Pipeline tự động kích hoạt:

1. **Auto-collect**: Thu thập full-text từ 5-7 nguồn tin nhanh nhất
2. **Auto-generate**: Groq Llama 3.3 viết bản tóm tắt breaking news ngắn (300-400 từ, Vietnamese, NQ05-compliant)
3. **Auto-illustrate**: Tạo/fetch hình ảnh minh họa liên quan (price chart snapshot + event graphic). **Nếu image fail → gửi text-only version trước**, anh tự thêm hình sau nếu cần
4. **Auto-deliver**: Gửi về Telegram của Anh Cường — format sẵn cho BIC Chat, kèm hình ảnh (nếu có). **Format dễ đọc và edit trên điện thoại**

**Climax**: Anh Cường nhận notification trên điện thoại. Đọc 30 giây — content tốt, chỉ sửa nhẹ 1 câu. Forward lên BIC Chat. **Tổng thời gian: 2 phút.**

**Resolution**: Members nhận được phân tích breaking news từ CIC trong vòng 15-20 phút sau sự kiện. CIC maintains reputation là nguồn tin nhanh và đáng tin. Anh Cường không bị interrupt công việc quá nhiều.

**Requirements revealed**: Event detection (panic score + keyword triggers), auto content generation, image generation/fetch with text-only fallback, Telegram push with mobile-friendly review UX, NQ05 compliance.

---

### J3 — Minh: L1 Member Journey (Dual-Layer Content)

**Persona**: Minh, 27 tuổi, mới gia nhập CIC L1 được 3 tháng. Chỉ có BTC và ETH. Thị trường biến động mạnh khiến anh lo lắng.

**Opening Scene**: 9:30 AM, Minh mở BIC Group. Thấy Anh Cường vừa post bài phân tích. Title: *"CIC Daily Report 04/03 — BTC: Điều chỉnh lành mạnh hay bắt đầu bear?"*

**Bài viết có cấu trúc dual-layer:**

**TL;DR (ai đọc cũng hiểu)**: *"BTC điều chỉnh -5% hôm nay sau chuỗi tăng 18 ngày. Đây là điều chỉnh bình thường — giống những lần điều chỉnh trước đây ở năm 2023-2024. Các chỉ số cho thấy thị trường chưa quá nóng."*

→ Minh đọc 3 câu đầu → hiểu ngay tình huống → bớt lo. Tò mò hơn, anh đọc tiếp phần chi tiết.

**Full analysis (cho members muốn hiểu sâu hơn)**: Giải thích MVRV Z-Score là gì, tại sao đang ở mức neutral, lịch sử các lần điều chỉnh tương tự — viết dễ hiểu kèm context.

**Rising Action**: Minh đọc phần chi tiết — hiểu thêm một chút. Comment hỏi "MVRV là gì vậy anh?" — member khác giải thích, tạo engagement trong group.

**Climax**: Minh thấy CIC "có mặt" mỗi sáng với phân tích rõ ràng, không phán đoán kiểu "mua/bán ngay". Anh không bị FOMO hay panic sell.

**Resolution**: Cuối tháng, Minh thấy mình hiểu market context tốt hơn, tự tin hơn với quyết định giữ BTC/ETH. Cảm giác membership có giá trị.

**Requirements revealed**: Dual-layer content structure (TL;DR dễ hiểu + full analysis chuyên sâu), accessible language ở TL;DR (không dùng thuật ngữ), technical depth ở phần chi tiết, BIC Group article format.

---

### J4 — Hưng: L5 Master Member Journey (Dual-Layer Content)

**Persona**: Hưng, 34 tuổi, L5 Master, đã trade crypto 5 năm. Portfolio 171 coins. Đọc report mỗi sáng như đọc báo.

**Opening Scene**: 9:00 AM, Hưng mở BIC Group trên desktop. Bài L5 đã có — 171 coins, full market context. Hưng skip TL;DR (anh đã biết market context) và đi thẳng vào phần phân tích chi tiết.

**Cấu trúc bài cho L5 — dual-layer:**

- **TL;DR**: Tóm tắt 3 câu ai đọc cũng hiểu (vẫn có vì L5 cũng có members mới!)
- **Macro**: DXY correlation, Gold/Oil signals, VIX spike analysis
- **On-chain deep dive**: Glassnode SOPR by cohort, Exchange reserves trend, Funding rates
- **Sector analysis**: DeFi vs L1s vs AI tokens — rotation signals
- **Risk flags**: Coins có FA score giảm đáng kể tuần này — breakdown

**Rising Action**: Hưng đọc phần sector analysis — thấy signal rotation từ AI tokens sang L2s đang được data support. Cross-reference với portfolio của mình. Ra quyết định rebalance.

**Climax**: Hưng comment vào bài: "Phần analysis rất hay, thấy rõ long-term holders đang accumulate." → Members khác react và reply → Discussion chất lượng cao → Anh Cường thấy engagement → Confirm pipeline đang tạo value.

**Resolution**: Hưng tiết kiệm 1-2 tiếng research buổi sáng. Tin tưởng CIC hơn vì phân tích có data source rõ ràng. Renew membership không do dự.

**Requirements revealed**: Multi-level content trong cùng 1 bài (TL;DR → macro → on-chain → sector → risk flags), 171-coin coverage, FA score delta tracking, on-chain data integration, engagement flywheel (member comment → discussion → operator sees value).

---

### J5 — Pipeline Failure: Error Recovery

**Persona**: Hệ thống. Người bị ảnh hưởng: Anh Cường.

**Opening Scene**: 8:50 AM — Anh Cường mở Telegram. Không có tin nhắn từ Bot. Chỉ có 1 tin cảnh báo: *"⚠️ Pipeline failed at 08:23 AM. Error: Groq API rate limit exceeded. Retry #3 failed."*

**Rising Action**:
- Pipeline đã tự retry 3 lần — thất bại do Groq quota hết
- Bot tự động switch sang Gemini 2.0 Flash (fallback LLM)
- Gemini generate xong L1, L2 — nhưng timeout tại L3 do content quá dài

**Climax**: Bot gửi partial delivery kèm status rõ ràng: *"✅ L1 và L2 ready. ⚠️ L3-L5 đang retry với Gemini Flash Lite. ETA: 9:15 AM."*

Anh Cường post L1 và L2 trước, báo members: *"Bài L3-L5 delay nhẹ, có trong 15 phút."*

**Resolution**: 9:12 AM — L3, L4, L5 delivered. Anh post xong lúc 9:30 AM — trễ 30 phút so với target nhưng không miss hoàn toàn. Daily reliability maintained.

**Requirements revealed**: Multi-LLM fallback (Groq → Gemini Flash → Flash Lite), partial delivery support, error notification to Telegram with clear status (cái nào xong, cái nào retry, ETA), retry logic, graceful degradation.

---

### J6 — Anh Cường: First-Time Setup (Onboarding)

**Persona**: Anh Cường, lần đầu cài đặt pipeline. Không biết code.

**Opening Scene**: Anh Cường vừa nhận repo từ team dev. README nói "chạy 5 bước là xong". Anh mở máy tính, hít một hơi...

**Rising Action**: Setup wizard hướng dẫn từng bước:

1. **Fork repo** trên GitHub (có hình minh hoạ)
2. **Nhập API keys** vào GitHub Secrets: Groq key, Gemini key, Telegram Bot Token — mỗi key có link đăng ký + hướng dẫn bấm nút nào
3. **Chạy test pipeline** bằng nút "Run workflow" trên GitHub Actions — không cần terminal
4. **Nhận tin nhắn test** trên Telegram: "🎉 Pipeline hoạt động! Đây là bài test L1..."
5. **Confirm schedule** — pipeline tự chạy mỗi sáng 8:00 AM VN

**Climax**: Anh nhận tin nhắn test đầu tiên trên Telegram. Content format đúng, đọc được, copy-paste được. **Tổng thời gian setup: 15-20 phút.**

**Resolution**: Sáng hôm sau, 8:35 AM, pipeline chạy tự động lần đầu. Telegram nhận 6 tin nhắn. Anh Cường mỉm cười — hệ thống hoạt động.

**Requirements revealed**: Visual setup guide (có hình), GitHub Secrets cho API keys (không cần .env local), one-click test run (GitHub Actions manual trigger), test message confirmation, zero-terminal setup path.

---

### Journey Requirements Summary

| Capability | Revealed by Journeys |
|------------|---------------------|
| **Telegram Bot delivery** | J1, J2, J5, J6 |
| **Formatted copy-paste articles** (BIC Group + BIC Chat format) | J1, J6 |
| **Tier-tagged content** (cumulative L1→L5) | J1, J3, J4 |
| **NQ05 disclaimer auto-append** | J1, J3 |
| **Breaking news detection** (panic score + keywords) | J2 |
| **Auto-generate breaking news summary + image** | J2 |
| **Image-fail fallback** (text-only delivery) | J2 |
| **Mobile-friendly Telegram review UX** | J2 |
| **Dual-layer content** (TL;DR dễ hiểu + analysis chuyên sâu) | J3, J4 |
| **On-chain data** (MVRV, SOPR, Exchange Reserves, Funding Rates) | J4 |
| **FA score delta / risk flags** | J4 |
| **Engagement flywheel** (comment → discussion → operator value) | J4 |
| **Multi-LLM fallback** (Groq → Gemini) | J5 |
| **Partial delivery + clear status notifications** | J5 |
| **Retry logic với graceful degradation** | J5 |
| **Visual setup guide** (no-code friendly) | J6 |
| **GitHub Secrets for API keys** | J6 |
| **One-click test run** (GitHub Actions manual trigger) | J6 |

### Design Principle: Dual-Layer Content

Mọi bài phân tích (tất cả tier L1→L5) đều phải có cấu trúc dual-layer:
- **TL;DR** (đầu bài): Ai đọc cũng hiểu — không dùng thuật ngữ chuyên môn. Newcomers trong group đọc xong hiểu ngay tình hình.
- **Full Analysis** (phần sau): Chuyên sâu, có data, có thuật ngữ kèm giải thích. Experienced members đọc để ra quyết định.

Lý do: Mỗi tier group đều có cả thành viên mới và thành viên lâu năm. Content phải phục vụ được cả hai nhóm trong cùng 1 bài viết.

---

## Domain-Specific Requirements

### Compliance & Regulatory (NQ05/2025/NQ-CP)

| Quy định | Áp dụng | Chi tiết |
|----------|---------|----------|
| Không khuyến nghị mua/bán | Bắt buộc | Content không được chứa lời khuyên đầu tư cụ thể |
| Disclaimer cuối bài | Bắt buộc | "Nội dung mang tính cung cấp thông tin và giáo dục, không phải lời khuyên đầu tư" |
| Nêu tên coin | Cho phép | Trong ngữ cảnh tin tức và phân tích thị trường |
| Quảng cáo sàn chưa cấp phép | Cấm | Không đề cập/quảng cáo sàn giao dịch chưa được cấp phép tại VN |

### Technical Constraints (Free Tier Limits)

| Service | Rate Limit | Daily Limit | Fallback |
|---------|-----------|-------------|----------|
| Groq (Llama 3.3 70B) | 30 req/min | 14,400 req/day | → Gemini Flash |
| Gemini 2.0 Flash | 15 req/min | 1,500 req/day | → Gemini Flash Lite |
| CryptoPanic API | 5 req/min | Unlimited | — |
| Glassnode (free) | Limited endpoints | Daily data only | — |
| Coinglass (free) | Limited endpoints | — | — |
| GitHub Actions | — | 2,000 min/month | — |

### Platform Constraints (BIC/Beincom)

- **Không có API** → Anh Cường copy-paste thủ công từ Telegram
- **BIC Group**: Long-form articles, Table of Contents, series, tier tags
- **BIC Chat**: Short posts, media (video/hình), thread-based
- **Posting order**: BIC Group trước → BIC Chat sau
- **Không có algorithm** → guaranteed reach cho tất cả members trong group

### Data Accuracy Requirements

| Data Type | Source | Acceptable Delay | Accuracy Need |
|-----------|--------|-----------------|---------------|
| Giá coin | Multi-source consensus | Real-time (< 5 min) | High — sai giá = mất uy tín |
| On-chain (MVRV, SOPR) | Glassnode free | 1-24h delay OK | Medium — daily trend |
| Macro (DXY, Gold, VIX) | yfinance | 15 min delay OK | Medium — context only |
| News/Events | CryptoPanic + RSS | < 30 min | High — freshness matters |
| Funding rates | Coinglass | < 1h delay OK | Medium — sentiment indicator |

> **Risk Analysis:** See "Risk Mitigation Strategy" in Project Scoping section for detailed risk breakdown (Technical, Market, Resource).

---

## Pipeline Architecture Requirements

### Project-Type Overview

CIC Daily Report là **Data Pipeline + Content Generation + Delivery System** với đặc điểm:
- **Stateful** — lưu dữ liệu trên Google Sheets giữa các lần chạy
- **Parallel collection** — thu thập data song song để tối ưu thời gian
- **Template-driven** — operator customize format mà không cần sửa code
- **Dual-system integration** — data feed ngược lại CIC Sentinel để bổ trợ phân tích portfolio

### Technical Architecture

```
[GitHub Actions Cron 01:00 UTC]
        │
        ▼
[PARALLEL DATA COLLECTION] ─── 5-10 phút
  ├── RSS feeds (trafilatura)
  ├── CryptoPanic API
  ├── yfinance (macro)
  ├── Glassnode (on-chain)
  └── Coinglass (funding/OI)
        │
        ▼
[AGGREGATE → Google Sheets] ─── Lưu raw data
        │
        ▼
[AI CONTENT GENERATION] ─── 15-25 phút
  ├── Groq Llama 3.3 (primary)
  └── Gemini Flash (fallback)
        │
        ▼
[TEMPLATE ENGINE] ─── Apply per-tier templates
  ├── L1 template (2 coins, ngắn)
  ├── L2 template (19 coins)
  ├── L3 template (63 coins)
  ├── L4 template (133 coins)
  └── L5 template (171 coins, full)
        │
        ▼
[DELIVERY → Telegram Bot]
        │
        ▼
[Google Sheets ← → CIC Sentinel]
  └── News data bổ trợ phân tích portfolio
```

### Data Storage (Google Sheets)

| Sheet | Mục đích | Retention |
|-------|---------|-----------|
| **RAW_NEWS** | Tin tức thu thập hàng ngày | 90 ngày |
| **RAW_MARKET** | Price, volume, macro data | 90 ngày |
| **RAW_ONCHAIN** | MVRV, SOPR, reserves | 90 ngày |
| **GENERATED_CONTENT** | Bài viết đã generate | 30 ngày |
| **PIPELINE_LOG** | Run history, errors, timing | 30 ngày |
| **CONFIG_TEMPLATES** | Templates per tier | Permanent |
| **CONFIG_COINS** | Coin list per tier (L1→L5) | Permanent |

**Lợi ích Google Sheets:**
- Anh Cường quản lý trực tiếp (thêm/bớt coin, sửa template) — không cần code
- Data accessible cho CIC Sentinel integration
- Free, familiar interface

### Template System (No-Code Customization)

Anh Cường customize qua Google Sheet `CONFIG_TEMPLATES`:

| Cột | Ví dụ | Mô tả |
|-----|-------|-------|
| `tier` | L3 | Tier áp dụng |
| `section_name` | macro_overview | Tên section |
| `enabled` | TRUE/FALSE | Bật/tắt section |
| `order` | 2 | Thứ tự hiển thị |
| `prompt_template` | "Phân tích macro..." | AI prompt cho section |
| `max_words` | 300 | Giới hạn độ dài |

→ Thêm/bớt/sắp xếp sections bằng cách sửa Google Sheet. Pipeline đọc config mỗi lần chạy.

### Coin List Management (Google Sheet)

Sheet `CONFIG_COINS`:

| tier | symbol | name | category | added_date |
|------|--------|------|----------|------------|
| L1 | BTC | Bitcoin | Store of Value | 2024-01-01 |
| L1 | ETH | Ethereum | Smart Contract | 2024-01-01 |
| L2 | SOL | Solana | L1 | 2024-03-15 |

Cumulative logic: L3 report includes all L1 + L2 + L3 coins.

### Pipeline Health Dashboard

Dashboard đơn giản trên Google Sheets (hoặc GitHub Pages):

| Metric | Hiển thị |
|--------|---------|
| Last run time | "08:32 AM VN — 35 phút" |
| Status | "Success" / "Partial" / "Failed" |
| LLM used | "Groq (primary)" / "Gemini (fallback)" |
| Tiers delivered | "L1 ✅ L2 ✅ L3 ✅ L4 ✅ L5 ✅" |
| Errors (last 7 days) | "2 errors — Groq rate limit (x2)" |
| Data freshness | "News: 8:15 AM, Price: 8:20 AM, On-chain: 7:00 AM" |

### CIC Sentinel Integration (Data Bridge)

Dữ liệu tin tức thu thập bởi Daily Report pipeline **bổ trợ cho CIC Sentinel**:

```
Daily Report Pipeline → Google Sheets (RAW_NEWS)
                              ↕
                     CIC Sentinel System
                     (đọc news data để bổ trợ
                      phân tích portfolio coins)
```

**Data synergy** giữa 2 hệ thống:
- Daily Report: Thu thập + phân tích tin tức hàng ngày
- Sentinel: Dùng tin tức để enrichment cho FA scoring và risk assessment

### Implementation Considerations

- **Google Sheets API**: Cần Service Account key (1 key duy nhất, setup 1 lần)
- **Parallel execution**: Python `asyncio` hoặc `concurrent.futures` cho data collection
- **Template hot-reload**: Pipeline đọc CONFIG sheets mỗi lần chạy — thay đổi apply ngay lần chạy sau
- **Sheet size management**: Auto-cleanup data > 90 ngày để tránh sheet quá nặng

---

## Project Scoping & Phased Development

### MVP Strategy & Philosophy

**MVP Approach:** Problem-Solving MVP — giải quyết vấn đề cốt lõi (tiết kiệm 2-3h/ngày cho operator) + breaking news responsiveness.

**Resource Requirements:** 1 developer (full-stack Python + basic frontend), ~2-3 tuần dev time.

### MVP Feature Set (Phase 1)

**Core User Journeys Supported:** J1 (Morning Happy Path), J2 (Breaking News), J5 (Error Recovery), J6 (Onboarding)

**Must-Have Capabilities:**

| # | Capability | Lý do MVP |
|---|-----------|-----------|
| 1 | Parallel data collection (RSS, CryptoPanic, yfinance, Glassnode, Coinglass) | Không có data = không có report |
| 2 | AI content generation (Groq + Gemini fallback) | Core value — tự động viết bài |
| 3 | 5 tier articles (L1→L5, cumulative, dual-layer) | Đây là sản phẩm chính |
| 4 | 1 BIC Chat summary post | Members cần overview |
| 5 | Telegram Bot delivery | Kênh giao tiếp duy nhất với operator |
| 6 | NQ05 filter + disclaimer auto-append | Compliance bắt buộc |
| 7 | Template system (Google Sheets config) | Operator cần customize không cần code |
| 8 | Coin list management (Google Sheets) | Thêm/bớt coin thường xuyên |
| 9 | Google Sheets data storage | Stateful pipeline + Sentinel integration |
| 10 | Multi-LLM fallback + partial delivery | Pipeline reliability ≥95% |
| 11 | Breaking news pipeline (cron mỗi 60 phút) | Operator cần phản ứng nhanh với sự kiện |
| 12 | Health dashboard (GitHub Pages, static) | Monitoring pipeline health |
| 13 | Visual setup guide + one-click test | No-code onboarding |

**GitHub Actions Budget (MVP):**
- Daily pipeline: ~15 min/run × 1 run/ngày = ~450 min/tháng
- Breaking news check: ~2 min/run × 24 runs/ngày × 30 = ~1,440 min/tháng
- **Total: ~1,890 min/tháng** (vừa đủ free tier 2,000 min)

### Post-MVP Features

**Phase 2 — Growth (Tháng 2-3):**
- TG channel parsing (10-15 channels quan trọng nhất)
- Deribit public API (options max pain, IV)
- Mempool.space (BTC network health)
- Better BIC Group formatting (auto Table of Contents)
- NotebookLM automation research
- CIC Sentinel data bridge (news → FA enrichment)

**Phase 3 — Vision:**
- Beincom API/partnership → auto-post
- Historical pattern matching database
- Engagement analytics per tier
- Monthly digest tự động
- A/B test content formats

### Risk Mitigation Strategy

**Technical Risks:**

| Risk | Probability | Mitigation |
|------|------------|-----------|
| Free API quota exceeded | Medium | Multi-LLM fallback chain, rate limiting, partial delivery |
| AI hallucination | Medium | Source attribution mandatory, cross-verify price data |
| GitHub Actions downtime | Low | Manual trigger backup, local run option |
| Google Sheets API limit | Low | Batch writes, caching |

**Market Risks:**

| Risk | Probability | Mitigation |
|------|------------|-----------|
| Content quality không đủ tốt | Medium | Operator review trước khi post, iterative prompt tuning |
| Members không engage | Low | Dual-layer content, breaking news timeliness |
| NQ05 enforcement thay đổi | Low | Configurable filter rules, easy to tighten |

**Resource Risks:**

| Risk | Probability | Mitigation |
|------|------------|-----------|
| Solo developer unavailable | Medium | Well-documented code, GitHub Actions self-running |
| Pipeline cần maintenance thường xuyên | Medium | Template-driven (config changes không cần code) |
| Scope creep | High | Clear phase boundaries, MVP-first mindset |

---

## Functional Requirements

> **Capability Contract**: Mọi tính năng phải nằm trong danh sách FRs này thì mới được thiết kế và build. FRs define WHAT capabilities — không define HOW to implement.

### A. Data Collection & Ingestion

- **FR1**: Pipeline can thu thập tin tức từ RSS feeds song song (15+ sites, VN + EN)
- **FR2**: Pipeline can extract full-text từ CryptoPanic original URLs (trafilatura)
- **FR3**: Pipeline can thu thập macro data từ yfinance (Gold, Oil, VIX, SPX, DXY)
- **FR4**: Pipeline can thu thập on-chain BTC data từ Glassnode free (MVRV Z-Score, SOPR, Exchange Reserves)
- **FR5**: Pipeline can thu thập derivatives data từ Coinglass (Funding rates, OI, Liquidations)
- **FR6**: Pipeline can thu thập price/market cap từ CoinLore (primary) + MEXC (OHLCV)
- **FR7**: Pipeline can thu thập news sentiment scores từ CryptoPanic (panic_score + votes bullish/bearish)
- **FR8**: Pipeline can thu thập messages từ Telegram channels (5-7 VN channels ưu tiên, batch collection)
- **FR9**: Pipeline can thu thập macro data từ FRED API (DGS10, CPI, Fed Balance Sheet)
- **FR10**: Pipeline can thu thập Fear & Greed Index, Altcoin Season Index, USDT/VND rate
- **FR11**: Pipeline can phát hiện và gộp tin trùng lặp từ nhiều nguồn
- **FR12**: Pipeline can flag thông tin mâu thuẫn giữa các nguồn để AI xử lý cẩn thận

### B. Content Generation & Quality

- **FR13**: AI can generate 5 bài tier articles (L1→L5) với cumulative coin coverage
- **FR14**: AI can generate dual-layer content (TL;DR không thuật ngữ + Full Analysis chuyên sâu)
- **FR15**: AI can generate 1 BIC Chat summary post (market overview table + key highlights)
- **FR16**: AI can áp dụng NQ05 compliance filter (không khuyến nghị mua/bán)
- **FR17**: AI can auto-append disclaimer vào cuối mỗi bài
- **FR18**: AI can generate content tiếng Việt tự nhiên từ nguồn EN + VN (operator review pass rate ≥90% — không cần chỉnh sửa ngữ pháp/ngữ nghĩa)
- **FR19**: AI can ghi source attribution trong content (nguồn dữ liệu rõ ràng)
- **FR20**: AI can generate Key Metrics Table (7 chỉ số bắt buộc: Market Cap, BTC.D, ETH.D, TOTAL3, Fear & Greed, Altcoin Season, USDT/VND)
- **FR21**: AI can xử lý bilingual input (EN→VN) với thuật ngữ tài chính chính xác
- **FR22**: AI can cross-verify số liệu giá từ nhiều nguồn trước khi đưa vào content

### C. Breaking News Pipeline

- **FR23**: Pipeline can phát hiện breaking events qua CryptoPanic panic score thresholds + keyword triggers
- **FR24**: Pipeline can auto-generate breaking news summary (300-400 từ, Vietnamese, NQ05-compliant)
- **FR25**: Pipeline can generate/fetch hình minh họa cho breaking news (text-only fallback nếu fail)
- **FR26**: Pipeline can deliver breaking news về Telegram operator với format phù hợp mobile (đọc tốt trên viewport ≤768px, không cần scroll ngang)
- **FR27**: Pipeline can phân loại alert theo 3 cấp severity (🔴 Khẩn cấp — stablecoin depeg, sàn sập, flash crash >10%; 🟠 Quan trọng — BTC ±5%, whale >$100M, liquidation cascade; 🟡 Chú ý — BTC ±3%, funding rate cực đoan)
- **FR28**: Pipeline can áp dụng Night Mode (🔴 gửi mọi lúc, 🟠 chỉ 7AM-11PM, 🟡 gom vào daily report)

### D. Delivery & Notification

- **FR29**: Telegram Bot can gửi 5 tier articles + 1 summary (6 messages total)
- **FR30**: Pipeline can format content copy-paste ready cho BIC Group (không cần chỉnh format sau khi paste)
- **FR31**: Pipeline can tag content với tier labels ([L1], [L2], [L3], [L4], [L5])
- **FR32**: Bot can gửi partial delivery kèm status rõ ràng (tier nào xong, tier nào đang retry, ETA)
- **FR33**: Bot can gửi error notifications với actionable status

### E. Reliability & Error Handling

- **FR34**: Pipeline supports multi-LLM fallback (Groq → Gemini Flash → Gemini Flash Lite)
- **FR35**: Pipeline can retry failed operations (tối đa 3 lần)
- **FR36**: Pipeline supports partial delivery (gửi tiers có sẵn, retry phần còn lại)
- **FR37**: Pipeline can graceful degrade khi data sources unavailable
- **FR38**: Pipeline can quản lý API quotas across tất cả services (rate limiting, daily caps, cooldown)

### F. Configuration & Management

- **FR39**: Operator can quản lý content templates qua Google Sheets (thêm/bớt/sắp xếp sections)
- **FR40**: Operator can quản lý coin lists per tier qua Google Sheets
- **FR41**: Pipeline đọc config từ Google Sheets mỗi lần chạy (hot-reload)
- **FR42**: Pipeline lưu raw data trên Google Sheets (RAW_NEWS, RAW_MARKET, RAW_ONCHAIN)
- **FR43**: Pipeline auto-cleanup data quá retention period (90 ngày raw, 30 ngày generated)
- **FR44**: Data schema thiết kế sẵn cho Sentinel integration 2 chiều (event_type, coin_symbol, sentiment_score, action_category)

### G. Pipeline Health Dashboard

- **FR45**: Dashboard hiển thị last run time và status (Success/Partial/Failed)
- **FR46**: Dashboard hiển thị LLM đang dùng (primary vs fallback)
- **FR47**: Dashboard hiển thị tier delivery status (✅/❌ per tier)
- **FR48**: Dashboard hiển thị error history (7 ngày gần nhất)
- **FR49**: Dashboard hiển thị data freshness per source
- **FR50**: Dashboard auto-update qua pipeline JSON output (GitHub Pages static)

### H. Onboarding & Setup

- **FR51**: Setup guide có visual screenshots (no-code friendly)
- **FR52**: API keys lưu trong GitHub Secrets (không cần .env local)
- **FR53**: One-click test run qua GitHub Actions manual trigger
- **FR54**: Test run gửi confirmation message về Telegram

### I. Data Quality & Filtering

- **FR55**: Pipeline can lọc spam/nhiễu qua multi-layer filtering (keyword blacklist + AI classify + quality scoring)
- **FR56**: Pipeline can chống alert trùng lặp với cooldown logic (không gửi lại cùng loại trong 1 giờ, trừ khi severity tăng)

### J. Pipeline Execution

- **FR57**: Pipeline can tự động chạy theo daily schedule VÀ có thể trigger thủ công khi cần
- **FR58**: Pipeline can ghi log mỗi lần chạy (thời gian, duration, status, LLM used, errors) vào PIPELINE_LOG
- **FR59**: Pipeline can áp dụng cumulative tier logic (L2 = L1+L2 coins, L3 = L1+L2+L3 coins, tương tự L4, L5)

### Phase 2 Capabilities (Ghi nhận — không trong MVP)

- SonicR PAC TA engine (reuse từ CIC Sentinel)
- Context-aware narrative (AI nhớ trend tuần trước, viết narrative liên tục)
- Sections sáng tạo ("Đèn Tín Hiệu 🟢🟡🔴", "3 Điều Bạn Chưa Biết", "Sự Kiện Tuần Này", "Phụ Lục Dữ Liệu Thô")
- Tần suất post khác nhau theo tier (L1 daily, L2 2-3x/week, L3-L5 on-demand)
- Sentinel integration 2 chiều hoàn chỉnh (events/trends → dashboard, AI insights per coin, gợi ý hành động)

---

## Non-Functional Requirements

> NFRs define HOW WELL the system must perform. Chỉ document categories thực sự quan trọng cho sản phẩm này.

### Performance

| NFR | Target | Measurement |
|-----|--------|-------------|
| **NFR1**: Pipeline total runtime | ≤40 phút | Từ trigger đến delivery hoàn tất |
| **NFR2**: Content ready time | Trước 9:00 AM VN | Anh Cường nhận đủ 6 messages trên TG |
| **NFR3**: Breaking news response | ≤20 phút từ event detection | Từ CryptoPanic panic score spike → TG alert delivered |
| **NFR4**: Data collection (parallel) | ≤10 phút | Tất cả sources (RSS + APIs + TG) hoàn tất |
| **NFR5**: AI content generation | ≤25 phút cho 5 tiers + 1 summary | Bao gồm retry nếu cần |

### Reliability

| NFR | Target | Measurement |
|-----|--------|-------------|
| **NFR6**: Daily pipeline uptime | ≥95% (miss ≤1.5 ngày/tháng) | Report delivered thành công |
| **NFR7**: Partial delivery khi lỗi | 100% — luôn gửi cái gì đó | Không bao giờ "im lặng" hoàn toàn |
| **NFR8**: LLM fallback success | ≥99% qua 3-tier fallback | Groq fail → Gemini → Flash Lite |
| **NFR9**: Data source degradation | Pipeline hoạt động nếu ≤3 sources fail đồng thời | Graceful degradation, không crash |
| **NFR10**: Error notification | 100% — mọi lỗi đều báo operator | Không bao giờ fail im lặng |

### Security

| NFR | Target | Measurement |
|-----|--------|-------------|
| **NFR11**: API keys storage | GitHub Secrets encrypted | Không hardcode, không .env trong repo |
| **NFR12**: TG session protection | Encrypted session trong GitHub Secrets | Không lưu plaintext |
| **NFR13**: Google Sheets access | Service Account key, scope giới hạn | Chỉ access sheets cần thiết |
| **NFR14**: No sensitive data in logs | Pipeline logs không chứa API keys/tokens | Masked trong output |
| **NFR15**: Repo access | Private repository | Code + config không public |

### Integration

| NFR | Target | Measurement |
|-----|--------|-------------|
| **NFR16**: API failure isolation | 1 API fail không kéo pipeline crash | Mỗi source có timeout + fallback riêng |
| **NFR17**: Google Sheets API latency | ≤5 giây per batch write | Batch writes, không write từng row |
| **NFR18**: Telegram Bot delivery | ≤30 giây cho 6 messages | Sequential send với rate limit respect |
| **NFR19**: Sentinel data compatibility | Schema compatible cho Phase 2 integration | Fields sẵn sàng, format đúng |

### Maintainability

| NFR | Target | Measurement |
|-----|--------|-------------|
| **NFR20**: Config changes (no-code) | Có hiệu lực ngay lần chạy sau | Google Sheets hot-reload |
| **NFR21**: Add/remove coin | Operator tự làm trong ≤2 phút | Sửa Google Sheet, không cần code |
| **NFR22**: Add/remove content section | Operator tự làm trong ≤5 phút | Sửa template sheet |
| **NFR23**: Debug/troubleshoot | Pipeline log đủ chi tiết | Timestamps, source status, LLM used, error messages |
| **NFR24**: Code documentation | README + setup guide cho non-dev | Visual screenshots, step-by-step |

### Cost

| NFR | Target | Measurement |
|-----|--------|-------------|
| **NFR25**: Monthly operational cost | $0/tháng | Toàn bộ free tiers |
| **NFR26**: GitHub Actions usage | ≤1,900 min/tháng (budget 2,000) | Daily ~450 + breaking ~1,440 |
| **NFR27**: API quota usage | ≤80% của free tier mỗi service | Buffer 20% cho retry/spike |
| **NFR28**: No paid upgrade required | MVP hoạt động hoàn toàn trên free tiers | Không dependency vào paid plan |

### NQ05 Compliance

| NFR | Target | Measurement |
|-----|--------|-------------|
| **NFR29**: Zero compliance violations | 0 NQ05 violations trong output | Không khuyến nghị mua/bán, disclaimer có |
| **NFR30**: Disclaimer presence | 100% bài có disclaimer | Auto-append, không thể bị quên |
| **NFR31**: Terminology compliance | 100% dùng đúng thuật ngữ NQ05 | "tài sản mã hóa" thay "tiền điện tử" |
