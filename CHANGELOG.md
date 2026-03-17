# Changelog

## [0.22.0] - 2026-03-17

### Prompt Architecture Overhaul

- **Fix Gemini API**: Use `system_instruction` parameter instead of concatenating
  system+user prompt. Gemini now processes NQ05 rules with higher priority.
- **Rewrite system prompt**: Role (analyst + investor perspective), 4-step process
  (summarize→find patterns→interpret→present), filler phrase blacklist.
- **Question-driven tier prompts**: Each tier has 3-4 specific questions to answer
  instead of open-ended "write analysis". Includes few-shot example paragraphs.
- **Reduce L5 data**: Cap news at top 20 lines to prevent Groq 413 Payload Too Large.
- **Prompt restructured**: "Context first, questions last" following Gemini best practices.

### Bug Fixes

- **DefiLlama None comparison**: Guard against `tvl=None` from API causing TypeError.
- **Derivatives fallback reorder**: OKX first (only provider working on GitHub Actions),
  removed Binance Spot (also 451 geo-blocked). Binance Futures + Bybit kept as fallbacks.
- **Sector data None guards**: All format_for_llm() comparisons now handle None values.

## [0.21.0] - 2026-03-16

### Phase 1 — Data Architecture Overhaul (Metrics Engine + Inter-Tier Context)

**Root cause (3rd time)**: Previous fixes (v0.13 data enrichment, v0.19 anti-hallucination,
v0.20 tier context redesign) were all prompt engineering — addressing symptoms, not architecture.
All 5 tiers received IDENTICAL data, no inter-tier awareness, and missing pre-computed insights
caused AI to guess/repeat instead of analyze.

**1a. Metrics Engine (NEW: generators/metrics_engine.py):**
- Pre-computed data interpretation replaces LLM guessing
- Funding Rate, OI, Long/Short Ratio → structured conclusions with reasoning
- DXY, Gold, BTC Dominance → macro analysis with cause-effect
- Fear & Greed, Altcoin Season → labeled sentiment with historical context
- Cross-signal analysis: detects agreement vs conflict between indicators
- Volume pattern analysis: top coins + divergence detection
- Tier-specific output: L1-L2 get sentiment only, L3-L5 get derivatives + macro + cross-signals

**1b. Market Regime Classification (in metrics_engine.py):**
- Scoring system classifies: Bull / Bear / Recovery / Distribution / Neutral
- Inputs: BTC price action, F&G, Altcoin Season, DXY, Funding Rate
- Confidence levels: high/medium/low based on signal agreement
- Vietnamese-formatted output included in every tier's prompt

**1c. Inter-Tier Context Passing (article_generator.py):**
- After generating each tier, section headers + first lines are summarized
- Summary passed to next tier as "CÁC TIER TRƯỚC ĐÃ VIẾT" context
- L2 knows what L1 covered, L3 knows L1+L2, etc.
- Eliminates content repetition at the architectural level (not just prompt hints)

**1d. Narrative Detection (in metrics_engine.py):**
- Keyword clustering from RSS news titles (15 narrative categories)
- Categories: ETF, Regulation, DeFi, AI, Exchange, Hack, Stablecoin, L2, etc.
- Top narratives with sample headlines passed to LLM as "CHỦ ĐỀ NÓNG HÔM NAY"
- AI can now write about dominant themes instead of random news

**Pipeline integration (daily_pipeline.py):**
- Removed 80+ lines of scattered interpretation_notes code
- Replaced with 3-line Metrics Engine call: interpret + narratives + format
- GenerationContext extended with metrics_interpretation + narratives_text fields
- Backward compatible: old interpretation_notes field kept as empty fallback

**Phase 2 — Data Source Expansion:**

**2a. Sector Data Collector (NEW: collectors/sector_data.py):**
- CoinGecko `/categories` endpoint — 12 tracked sectors (DeFi, L1, L2, AI, Gaming, Meme, RWA, etc.)
- Market cap + 24h change + volume + top 3 coins per sector
- Formatted as "PHÂN TÍCH THEO SECTOR" context for LLM

**2b. DefiLlama TVL (in sector_data.py):**
- Total DeFi TVL from historical endpoint
- Top 15 protocols by TVL with chain, category, 1d change
- Free API, no key required, no rate limit

**2c. Binance Spot Fallback (onchain_data.py):**
- Added `_derivatives_binance_spot()` using `api.binance.com` (not geo-blocked)
- Provides BTC spot volume, price change as derivatives proxy
- Attempts Binance Coin-M funding rate (alternative endpoint)
- Fallback chain now: Binance Futures → Binance Spot → Bybit → OKX

**Pipeline integration:**
- `collect_sector_data()` added to parallel Stage 1 collection
- `SectorSnapshot.format_for_llm()` passed to each tier via `sector_data` field
- GenerationContext extended with `sector_data: str` field
- L2-L5 now have real sector data for analysis (previously empty)

**Phase 3 — Prompt Optimization (leveraging new data architecture):**

**3a. Tier-Specific Data Filtering (article_generator.py):**
- `_filter_data_for_tier()` reduces noise for lower tiers
- L1: BTC/ETH prices + F&G + top 5 news only (no on-chain, sector, macro events)
- L2: Full market + sector + news (no on-chain details)
- L3: Full analytical data, reduced news (already in L1/L2)
- L4: On-chain + sector + macro focus, minimal news
- L5: Everything (scenario analysis needs full context)

**3b. Data Quality Monitor (NEW: generators/data_quality.py):**
- `assess_data_quality()` scores data completeness 0-100 (A/B/C/D/F)
- Scoring: News 25pts, Market 25pts, On-chain 20pts, Sector 15pts, Econ 15pts
- Vietnamese warnings passed to LLM when data is degraded
- `is_degraded` flag (score < 40) for pipeline-level decisions
- Integrated into daily_pipeline.py with logging

**3c. Tier Prompt Refinement (daily_pipeline.py):**
- L1: Uses Market Regime from Metrics Engine (no more LLM guessing bullish/bearish)
- L2: References CoinGecko/DefiLlama sector data for grouping coins
- L3: Delegates derivatives interpretation to Metrics Engine (removed inline guide)
- L4: Uses cross-signal analysis for risk detection, sector risk from DefiLlama
- L5: Uses sector rotation data + regime confidence for scenario analysis
- Trimmed redundant "KIẾN THỨC NỀN" block in prompt (Metrics Engine handles this)

**Tests: 80 new tests total (562 total, 100% pass)**
- TestMarketRegime: 9 tests (bull, bear, neutral, recovery, distribution, edge cases)
- TestInterpretMetrics: 11 tests (tier formatting, derivatives, cross-signals)
- TestNarrativeDetection: 9 tests (detection, filtering, formatting)
- TestSummarizeTierOutput: 5 tests (header extraction, fallback, truncation)
- TestSectorSnapshot: 3 tests (formatting with/without data)
- TestCoinGeckoCategories: 4 tests (parsing, HTTP error, network error, sorting)
- TestDefiLlama: 2 tests (TVL + protocols, failure handling)
- TestCollectSectorData: 2 tests (integration, partial failure)
- TestDataQualityReport: 5 tests (grades, formatting, threshold boundaries)
- TestAssessDataQuality: 10 tests (perfect score, no data, partial, boundaries)
- TestFilterDataL1-L5: 20 tests (per-tier data filtering)
- TestFilterDataEdgeCases: 2 tests (empty context, metrics table preservation)

## [0.20.0] - 2026-03-15

### Phase 1 — Prompt Redesign & Output Quality (ICS Anti-Repetition)

**Root cause**: All 5 tiers received same data with nearly identical prompts, causing massive
content repetition visible to higher-tier members who see all lower-tier content via ICS structure.

**1A. Tier Context Redesign (daily_pipeline.py):**
- Each tier now answers a DIFFERENT question:
  L1="Hôm nay thế nào?", L2="Coins nào?", L3="Tại sao?", L4="Rủi ro?", L5="Nếu X thì sao?"
- Each tier explicitly states "MEMBER ĐÃ ĐỌC tier thấp hơn — KHÔNG lặp lại"
- Different tone per tier: L1=casual, L2=professional, L3=analytical, L4=risk-focused, L5=formal
- L2 must mention ≥10/19 coins with sector grouping
- L3-L5 have explicit "KHÔNG LÀM" lists to prevent content overlap
- Each tier has specific "NỘI DUNG BẮT BUỘC" checklist

**1B. Prompt Engineering (article_generator.py):**
- Removed bad example "vùng tích lũy trước đợt tăng mới" (NQ05 borderline prediction)
- Added domain knowledge block: Funding Rate, OI, F&G, BTC Dominance, DXY interpretation
- Added negative examples with ⚠️ SAI markers (wrong FR/OI interpretation, NQ05 violations)
- Added anti-fabrication examples (MVRV, correlation coefficient, smart money)
- URLs now passed in news_text for LLM to reference actual source links

**1C. NQ05 Filter Overhaul (nq05_filter.py):**
- Banned keywords now remove ENTIRE SENTENCE (was: replace with "[đã biên tập]" leaving broken text)
- New `_remove_sentences_with_pattern()` handles both prose and bullet points
- Added 5 semantic NQ05 patterns: "vùng tích lũy trước đợt tăng", "cơ hội tốt để tích lũy",
  "smart money đang mua", "thời điểm tốt để mua", "nên cân nhắc mua"
- Removed auto-append disclaimer (was causing double disclaimer with article_generator)

**1D. Summary Generator Fix (summary_generator.py):**
- Added `check_and_fix()` NQ05 filter call before appending disclaimer (was skipped entirely)

**1E. Breaking News Improvements (content_generator.py):**
- Prompt now receives event URL + summary from raw_data (was: title only → filler content)
- Clarified NQ05 allows naming specific assets (BTC, ETH, SOL...)
- Structured output now includes 🔗 source link

**1F. Post-Generation Validation (article_generator.py):**
- New `_validate_output()` scans LLM output for fabricated metrics
  (MVRV, SOPR, Exchange Reserves, whale data, liquidation data, correlation coefficients)
- L2 coin count check: warns if <5 coins mentioned (target: ≥10)
- Banned source citation check (Bloomberg, CryptoQuant, TradingView, etc.)
- All warnings logged for pipeline monitoring

**1G. Pipeline Stability Fixes (post-deploy):**
- `_TIER_COOLDOWN` 45→60s, `_TIER_RETRY_WAIT` 60→120s — Groq free tier TPM limit
  caused L3-L5 rate limit failures with insufficient cooldown
- Fixed NQ05 violation in interpretation note: "giai đoạn tích lũy trước breakout"
  → "volume thấp thường đi kèm biến động mạnh sau đó (hướng chưa rõ)"
- On-chain prompt header: removed "Glassnode, Binance Futures, Bybit" (geo-blocked/unavailable),
  now shows only "OKX, FRED" to prevent LLM citing unavailable sources
- Disabled 7 dead RSS feeds (BeInCrypto_VN 403, CCN 403, DLNews 404, Reuters DNS fail,
  Bankless 403, CoinMetrics 403, Galaxy_Digital 404) — `enabled=False` for easy re-enable
- `sheets_client.read_all()`: filters out empty-key dict entries from corrupt sheet headers
- `sheets_client.clear_and_rewrite()`: auto-repairs header row against schema definition
  (fixes BREAKING_LOG duplicate empty columns causing context load failure)

## [0.19.0] - 2026-03-15

### Anti-Hallucination & Output Quality

**Fix 1 — Anti-Hallucination (article_generator.py):**
- Removed "Theo CoinLore/Glassnode" example from NQ05_SYSTEM_PROMPT that was INSTRUCTING LLM to cite fabricated sources
- Added "CHỐNG BỊA DỮ LIỆU" rule: LLM can only cite sources from provided data
- Added "QUY TẮC DỮ LIỆU TUYỆT ĐỐI" block in article prompt with source whitelist/blocklist
- Added "KIỂM TRA CUỐI CÙNG" guardrail: whitelist of allowed sources at end of prompt
- Glassnode + Messari moved to ALLOWED list (they ARE real data sources in onchain_data.py + rss_collector.py)
- On-chain source label updated: "Glassnode, Binance Futures, Bybit, OKX, FRED"
- L2 tier_context: removed "support/resistance" instruction that invited LLM to fabricate price levels

**Fix 2 — Data Cleaning Before LLM (daily_pipeline.py, economic_calendar.py):**
- New `_format_onchain_value()`: Funding Rate → percentage format (e.g. -0.0056% instead of -5.55e-05), large numbers → B/M suffixes, ratios → 4 decimal places
- Key metrics Funding Rate now shows percentage format
- Economic events `recent_events`: label changed to "ĐÃ DIỄN RA" with "ĐÃ QUA" tag — prevents LLM from writing past events as "sắp tới"
- Added Funding Rate + OI correlation hints in interpretation notes (OI uses `_format_onchain_value()` instead of hardcoded "B USD")
- Economic events prompt instruction: explicit "KHÔNG viết sự kiện đã qua như 'sắp tới'"

**Fix 3 — Severity Classifier (severity_classifier.py):**
- Added 16 new important keywords: drops, falls, plunges, surges, soars, selloff, rally, war, attack, missile, sanctions, Iran, escalation, invasion, liquidated, sell-off
- Added price-movement percentage detection: X% in title where X≥3 → important, X≥10 → critical
- Word-boundary matching (`\b`) for ALL keywords — fixes "ban" matching inside "Binance" (false CRITICAL)

**Fix 4 — Breaking News Format (breaking_pipeline.py, content_generator.py, dedup_manager.py):**
- Breaking prompt rewritten: 300-400 → 100-150 words (critical: 200-250), no hedge language, structured as "Chuyện gì xảy ra" + "Tại sao quan trọng"
- AI-generated breaking content now includes NQ05 DISCLAIMER (was only on raw fallback)
- DedupEntry: added `url` field (8-column schema) — deferred events now retain URL
- BREAKING_LOG schema in sheets_client.py: 7 → 8 columns (added URL header)
- `_load_dedup_from_sheets()`: now reads URL column from sheet
- Fixed double dedup load: single `dedup_mgr` shared across pipeline stages (was loading twice, second overwriting first)
- Removed dead `url=` kwarg from content_generator `.format()` call
- Deferred morning alert: sorted by severity, includes severity emoji + URL link

**Fix 5 — Crypto Relevance Filter (data_cleaner.py):**
- New `_filter_non_crypto()` step in cleaning pipeline
- 70+ keywords: 50 crypto + 18 macro/finance (SEC, ETF, Fed, FOMC, CPI, inflation, tariff, DXY, etc.)
- Word-boundary matching for short keywords (≤3 chars) — prevents "sol" matching "solution", "eth" matching "method"
- Crypto-only sources (Coin68, TapChiBitcoin, BeInCrypto) bypass keyword check

**Fix 6 — Breaking → Daily Context Sharing (daily_pipeline.py, article_generator.py):**
- New `_load_recent_breaking_context()`: reads BREAKING_LOG for events within 24h
- New `recent_breaking` field in GenerationContext
- Injected into article prompt: "SỰ KIỆN BREAKING GẦN ĐÂY (24h qua — PHẢI nhắc đến trong bài)"
- Daily report now references breaking news from previous night

**Tests:** 471 passed (+21 new), 0 regressions
- Severity classifier: keyword tests, percentage detection, word-boundary tests (ban vs Binance)
- Data cleaner: non-crypto filter, crypto bypass, macro terms, substring false positive tests
- Article generator: anti-hallucination guardrails, Glassnode in allowed list
- Content generator: AI path DISCLAIMER, word targets
- Daily pipeline: `_format_onchain_value()` for funding rate, ratio, large/small numbers
- Dedup manager: URL field, 8-column row

## [0.18.0] - 2026-03-14

### FR60 — Economic Calendar Integration + Template Upgrade

**Economic Calendar Collector (NEW):**
- New `collectors/economic_calendar.py`: fetches macro-economic events from FairEconomy feed
- Filters High-impact USD events relevant to crypto (Fed, FOMC, CPI, PPI, NFP, GDP, etc.)
- 30+ event titles in `CRYPTO_RELEVANT_EVENTS` set (exact + prefix matching)
- Auto-splits events into today vs upcoming, formats as Vietnamese text for LLM prompt
- Graceful fallback: returns empty CalendarResult on any error (HTTP, JSON, timeout)
- Integrated as 6th parallel collector in `daily_pipeline.py` via `asyncio.gather()`
- New `economic_events` field in `GenerationContext` dataclass

**Template Upgrade (AutoSetup.gs):**
- L1: 2→3 sections (added "Kết luận & Sự kiện sắp tới")
- L2: 2→3 sections (added "Xu hướng & Sự kiện vĩ mô")
- L3: 2→4 sections (On-chain + Vĩ mô & Lịch sự kiện + Derivatives + Tổng hợp)
- L4: 2→4 sections (Sector + Sentiment & Derivatives + Sự kiện vĩ mô + Cảnh báo)
- L5: 2→6 sections (Executive Summary + Macro + On-chain + Sector + Liên thị trường + Risk)
- Each section prompt includes specific economic event analysis instructions
- L4 TIER_MAX_TOKENS: 3072→4096 (supports 4 sections)

**Article Generator:**
- `economic_events` variable injected into LLM prompt with "LỊCH SỰ KIỆN KINH TẾ VĨ MÔ" header
- Economic context only added when events are available (no empty sections)

**Tests:** 440 passed (+14 new), 0 regressions
- 14 new tests: `_is_crypto_relevant()`, `EconomicEvent`, `CalendarResult.format_for_llm()`, `collect_economic_calendar()` (5 scenarios)
- Test fixture: `economic_calendar_sample.json` (10 events)

**Version sync:** config.py, pyproject.toml, Menu.gs, test_config.py → 0.18.0

---

## [0.17.0] - 2026-03-14

### PRD Remediation — 24 findings across 5 clusters (R1→R3→R2→R4→R5)

**R1 — Config & Templates:**
- Improved all 8 template prompts in AutoSetup.gs: dual-layer (TL;DR + detail), source attribution
- Added 2 new sections: L4 "Tín hiệu cảnh báo" + L5 "Phân tích liên thị trường" (8→10 total)
- Fixed L4 NQ05 violation: removed "Nêu tỷ trọng phân bổ %" → replaced with risk analysis
- Added `resetTemplates()` GAS function + menu item for Anh Cường to apply updates
- Updated GAS version to 0.17.0

**R3 — Crash Notification & Stability:**
- Added TG failure notification step to both GitHub Actions workflows (daily + breaking)
- Fixed test mode timing bug: `_send_test_confirmation` now runs AFTER run_log finalized
- Pipeline operator gets Telegram alert when both pipeline attempts fail

**R2 — Validation Layer:**
- Pre-flight validation: checks templates exist for all 5 tiers before generating
- Pre-flight validation: warns when coin lists are empty for a tier
- Early exit when NO templates loaded (prevents silent empty report)
- Post-generation validation: checks all 5 tiers were generated, logs missing tiers
- Post-generation validation: checks FR14 dual-layer (TL;DR marker)

**R4 — Format & Delivery:**
- FR30 copy-paste fix: replaced `<a href>` HTML injection with plain-text source footer
- New `_append_source_references()`: appends "Nguồn tham khảo" section with up to 5 sources
- Content now copy-paste ready for BIC Group (Beincom) — no raw HTML tags
- FR28 deferred event reprocessing: breaking pipeline reprocesses `deferred_to_morning` events

**R5 — Bug Fixes & Sync:**
- CJK character sanitization in NQ05 filter: strips Chinese/Japanese/Korean chars from LLM output
- FR12 conflict detection: passes conflict flag to LLM context with warning marker
- FR43 data retention: `run_cleanup()` now called at end of daily pipeline (was orphaned)
- Version sync: config.py, pyproject.toml, GAS Menu.gs all at 0.17.0

**Tests:** 426 passed, 0 regressions

---

## [0.16.0] - 2026-03-13

### Added — CryptoPanic Fallback: RSS + LLM Scoring + Market Triggers

**LLM Scorer (`breaking/llm_scorer.py`) — NEW:**
- RSS-based breaking event scoring when CryptoPanic unavailable
- Batch LLM prompt: scores up to 20 articles in 1 call (efficiency)
- Keyword pre-filter: matching articles bypass LLM (faster, no quota)
- Time filter: only scores articles published within last 6 hours
- Graceful degradation: LLM failure returns keyword-only matches

**Market Trigger (`breaking/market_trigger.py`) — NEW:**
- Always-on price crash detection (not a fallback, runs every time)
- BTC drop > 7% in 24h → automatic breaking event
- ETH drop > 10% in 24h → automatic breaking event
- Fear & Greed Index < 10 → Extreme Fear breaking event
- Uses existing market data collector (no new API calls)

**Breaking Pipeline Fallback Chain:**
- 3-layer detection: CryptoPanic (primary) → RSS+LLM (fallback) → Market triggers (always-on)
- CryptoPanic failure (quota/error/timeout) triggers automatic RSS fallback
- Market triggers run alongside primary detection (additive, not exclusive)
- All sources merge before dedup — no duplicate alerts
- 50 new tests, 426 total, 0 regression

---

## [0.15.0] - 2026-03-13

### Added — Research Integration + Telegram Formatting + CryptoPanic Quota Fix

**Research Feed Integration (Cụm 1):**
- 4 research feeds: Messari, Glassnode Insights, CoinMetrics, Galaxy Digital
- `source_type` field ("news" vs "research") on FeedConfig + NewsArticle
- `og_image` extraction via trafilatura for research articles
- `full_text` enrichment for research articles (up to 2000 chars)
- `asyncio.Semaphore(25)` limits concurrent HTTP requests
- Data cleaner preserves `og_image` and `source_type` through dedup

**CryptoPanic API Quota Fix (GP1-4):**
- Breaking pipeline: hourly → every 3h, skip UTC 0-5 (750→180 calls/month)
- QuotaManager integrated into both CryptoPanic collectors
- File-based cache (2h TTL) prevents redundant API calls
- New `core/cache.py` module for simple file-based caching

**Delivery Layer Enhancements (Cụm 2):**
- Selective HTML escape: preserves safe `<a href>` hyperlinks
- `send_photo()` method for sending research chart images via Telegram
- Image delivery: up to 3 research images per daily report
- Email backup supports HTML alternative (for hyperlinks)
- Sheets truncation increased from 5000 to 8000 chars

**Hyperlink Injection (Cụm 3):**
- Source URLs collected and injected AFTER NQ05 filter (security-safe)
- First occurrence of each source name wrapped in clickable `<a href>` tag
- `source_urls` and `image_urls` passed through article dict to delivery

---

## [0.14.3] - 2026-03-12

### Changed — F2: CAU_HINH Self-Documenting Email Config

**Operator (no-code user) chỉ cần mở Google Sheet để quản lý email:**
- Tab CAU_HINH được seed sẵn row `email_recipients` khi setup lần đầu
- Cột "Mô tả" hướng dẫn đầy đủ tiếng Việt: THÊM / XÓA / Ví dụ format
- Không cần terminal, không cần tool — edit trực tiếp cell trong Sheet
- `seed_setting()`: append row nếu key chưa có, skip nếu đã có (không overwrite)
- `seed_default_config()`: seed tất cả default rows, idempotent
- `create_schema()` tự gọi `seed_default_config()` khi setup

**Xóa `scripts/manage_email_recipients.py`** — CLI tool không phù hợp no-code user.

**Thêm `scripts/setup_schema.py`** — one-time dev script khi tạo spreadsheet mới.

---

## [0.14.2] - 2026-03-12

### Added — F2 (Tiếp): Email Recipients Management via CAU_HINH

**SheetsClient.upsert_setting():**
- Tìm key trong CAU_HINH → update nếu có, append nếu chưa có
- Cột: `Khóa | Giá trị | Mô tả`

**ConfigLoader.set_email_recipients():**
- Ghi danh sách email vào CAU_HINH (upsert), tự động xóa cache sau khi lưu

**scripts/manage_email_recipients.py:**
- CLI tool để quản lý email backup từ terminal (không cần vào GitHub)
- Commands: `list`, `add <email>`, `remove <email>`, `set <email1,email2,...>`

---

## [0.14.1] - 2026-03-12

### Added — F2: Email Backup với Lý Do Telegram Thất Bại

**Email body giờ bao gồm lý do Telegram fail:**
- `send_daily_report()` nhận param mới `telegram_error: str | None`
- Khi Telegram fail hoàn toàn hoặc partial → lý do + timestamp UTC append vào body
- `delivery_manager.py` tự động capture error và truyền qua

**Email recipients cấu hình được từ Google Sheets (CAU_HINH):**
- `ConfigLoader.get_email_recipients()` đọc key `email_recipients` từ CAU_HINH
- Format: `a@gmail.com, b@gmail.com` (comma-separated, có thể thêm nhiều người)
- Fallback: `SMTP_RECIPIENTS` env var nếu chưa có trong sheet
- `_deliver()` đọc từ sheet mỗi lần chạy — không cần redeploy khi đổi email

---

## [0.14.0] - 2026-03-12

### Added — F1: Derivatives Data Migration (Binance Futures)

**Thay thế Coinglass v2 (deprecated) bằng Binance Futures public API:**
- Binance Futures làm primary source (GitHub Actions servers ở US/EU, không bị chặn)
- Bybit v5 làm first fallback, OKX v5 làm second fallback
- 4 metrics mới: `BTC_Funding_Rate`, `BTC_Open_Interest`, `BTC_Long_Short_Ratio`, `BTC_Taker_Buy_Sell_Ratio`
- Không cần API key — tất cả public endpoints
- Provider-level fallback: nếu Binance fail thì thử Bybit, rồi OKX

### Added — F3: RSS Feed Expansion (+5 sources)

**Thêm 5 nguồn tin mới (từ 12 lên 17 feeds):**
- `BeInCrypto_VN` — vn.beincrypto.com (Vietnamese)
- `CCN` — ccn.com (English crypto news)
- `Blockworks` — blockworks.co (institutional crypto)
- `DLNews` — dlnews.com (DL News)
- `Reuters` — feeds.reuters.com/reuters/businessNews (financial news)
- `Bankless` — banklesshq.substack.com (DeFi/Web3)

---

## [0.13.1] - 2026-03-12

### Fixed — Hotfix Wave E (Cleanup)

**E1: Xóa 3 RSS feed chết**
- `TNCK` (404), `BitcoinMag` (403), `BeInCrypto` (403) bị gọi mỗi ngày nhưng không bao giờ thành công
- DEFAULT_FEEDS: 15 → 12 feeds

**E2: Refactor breaking_pipeline dùng private `sheets._connect()`**
- Thêm public method `SheetsClient.clear_and_rewrite()` thay thế truy cập private
- Fix luôn bug cũ: `batch_append` luôn chạy kể cả khi delete thành công (double-write)
- Thêm 4 test cases cho `clear_and_rewrite()`

### Fixed — Hotfix Wave B (Pipeline Reliability)

**D1: Fix test version mismatch**
- Test assert `VERSION == "0.13.0"` → `"0.13.1"` (CI sẽ fail nếu không sửa)

**D2: ValueError → LLMError trong article_generator**
- `raise ValueError(...)` → `raise LLMError(...)` — đúng chuẩn QĐ3 (CICError hierarchy)

**D3: Xóa dead code escape_markdown_v2()**
- Hàm `escape_markdown_v2()` trong telegram_bot.py không được gọi ở đâu → xóa cùng tests

**D5: Bật SSL verification cho Altcoin Season Index**
- `verify=False` → `verify=True` — sửa lỗ hổng bảo mật HTTPS

**D6: Fix ErrorEntry mutation side effect**
- `_trim_error_history()` sửa trực tiếp input object → dùng `dataclasses.replace()` tạo copy

**D7+D8: Xóa dead code to_row() trong GeneratedArticle + GeneratedSummary**
- Hai hàm `to_row()` không được gọi trong pipeline (pipeline dùng dict trực tiếp) → xóa cùng tests + unused imports

**C1: Tách Concurrency Group + Offset Cron**
- Daily pipeline và Breaking News dùng chung concurrency group → block nhau khi trigger cùng lúc
- Tách thành `daily-pipeline` / `breaking-news` groups, daily cron offset 5 phút (01:05 UTC)

**C3: Pipeline Fail Khi Delivery Gửi 0 Tin**
- `_deliver()` catch exception nhưng không propagate → pipeline báo "success" dù delivery fail
- `_deliver()` giờ return `DeliveryResult`, `_run_pipeline()` check 0-sent → set status "error" + `sys.exit(1)`
- Partial delivery (ví dụ 3/6 sent) vẫn là "partial", không fail pipeline

**C5: Fix pyproject.toml Version**
- Version `0.12.0` không khớp `core/config.py` `0.13.0` → sửa đồng bộ

**H6: Validate Groq Empty Response**
- Groq thiếu validation empty text (Gemini đã có 2 lớp)
- Thêm validation trong `_call_groq()` + safety net trong `generate()` cho TẤT CẢ providers

**M1: HTML Escape cho Telegram Messages**
- `parse_mode="HTML"` nhưng không escape `<`, `>`, `&` → TG parsing error
- Thêm `html.escape()` trong `_send_raw()` — tầng thấp nhất, cover mọi message

## [0.13.0] - 2026-03-11

### Fixed — Data Context Starvation (Root Cause of Generic Output)

**Root cause**: Pipeline collected rich data but compressed it to titles+prices before passing to LLM, causing generic output lacking insight.

**Wave A — Quick Wins (LLM Context Enrichment):**
- Spam articles (`filtered=True`) now excluded from LLM context (was polluting prompt)
- News text enriched with article summaries (300 chars each) instead of titles only
- Market text enriched with volume + market cap alongside price/change
- CryptoPanic `summary` field populated from full_text when API returns empty
- LLM temperature 0.3 → 0.5 for more natural, varied analysis
- BIC Chat summary excerpt 300 → 800 chars for richer source context

**Wave B — Data Enrichment (New Metrics FR10/FR20):**
- Added **ETH Dominance** collection from CoinLore API
- Added **TOTAL3** (altcoin market cap) calculated from dominance percentages
- Added **Altcoin Season Index** from BlockchainCenter API (graceful degradation)
- KEY_METRICS_LABELS expanded 7 → 11 items (ETH Dominance, TOTAL3, Altcoin Season, USDT/VND)
- Key metrics mapping in pipeline: ETH_Dominance, TOTAL3, Altcoin_Season → dashboard
- Anomaly detection flags: Extreme Fear/Greed (≤20/≥80), significant BTC moves (≥5%)
- Gemini `_call_gemini()` now raises `LLMError` on empty candidates/text (was silently returning "")
- Improved on-chain collector logging (Glassnode warnings, Coinglass zero-value alerts)

**Wave C — Tier Differentiation:**
- Per-tier Vietnamese analysis instructions (L1=beginner, L2=technical, L3=on-chain+macro, L4=risk, L5=comprehensive)
- `TIER_MAX_TOKENS` dict: L1=2048, L2=3072, L3=4096, L4=3072, L5=6144 (was fixed 4096)
- `GenerationContext.tier_context` field added to pass tier-specific instructions to LLM
- L4 tier explicitly warns: "TUYỆT ĐỐI KHÔNG đưa ra tỷ lệ phân bổ cụ thể (%) — vi phạm NQ05"

**Wave D — NQ05 Hardening:**
- Added `ALLOCATION_PATTERNS` (3 regex patterns) detecting portfolio allocation percentages
- `check_and_fix()` Step 1b: scans and removes allocation patterns (e.g., "30% cho BTC")
- Per-violation audit trail logging with `logger.warning()`

**Wave E — Infrastructure & Breaking News:**
- gh-pages deploy: replaced git-stash-based approach with proper fetch/checkout (race condition fix)
- Dashboard `_trim_error_history()`: assigns default timestamp for errors without one
- Breaking `_calculate_panic_score()`: clarified docstring (panic score ≠ sentiment score)

### Tests
- Fixed 4 tests broken by Wave A-E changes (Gemini empty candidates, coinlore 4 points, 11 metrics)
- All tests passing: 357+ passed, 0 failed

### Stats
- Version: 0.12.0 → 0.13.0
- Metrics tracked: 7 → 11 (KEY_METRICS_LABELS)
- LLM context: ~5% of collected data → ~60% (summaries, volume, mcap, anomalies)
- NQ05 patterns: keyword-only → keywords + allocation regex + per-tier warnings

## [0.12.0] - 2026-03-09

### Added — GAS Menu & Auto Setup
- **Google Apps Script Menu** (`gas/Menu.gs`): menu "📊 CIC Daily Report" trên Google Sheets
  - ⚙️ Thiết Lập Tự Động — tạo 9 tab + header + định dạng (idempotent)
  - 🔄 Đồng Bộ Cột Thiếu — thêm cột mới mà không xóa dữ liệu
  - 🎨 Định Dạng Lại — sửa format bị lộn xộn
  - 📊 Trạng Thái Hệ Thống + 📏 Đếm Dữ Liệu
  - 🗑️ Dọn Dẹp Dữ Liệu Cũ (>30 ngày)
- **Auto Setup** (`gas/AutoSetup.gs`): 9 tab schema khớp 100% với Python `sheets_client.py`
  - Header: chữ đậm, nền xanh, chữ trắng, đóng băng hàng đầu
  - Number formats: giá, phần trăm, khối lượng tự định dạng
  - Default data: tab CAU_HINH ghi sẵn 9 cấu hình mặc định
  - Xóa "Sheet1" mặc định tự động

### Improved — GitHub Actions
- Thêm bước **Validate required secrets** vào daily-pipeline + breaking-news
  - Kiểm tra 6 secrets bắt buộc trước khi chạy → báo lỗi rõ ràng nếu thiếu
- Bật **uv cache** (`enable-cache: true`) cho tất cả 3 workflows → cài nhanh hơn
- Thêm **timeout-minutes: 10** cho test workflow
- Thêm **SMTP_**** env vars vào daily-pipeline (email backup)
- Test workflow trigger trên cả `main` và `master` branches

### Updated — Documentation
- `docs/SETUP_GUIDE.md`: thêm hướng dẫn cài GAS menu + Base64 encode + đánh dấu CRYPTOPANIC_API_KEY là bắt buộc
- `gas/README.md`: hướng dẫn cài đặt GAS từng bước

## [0.11.0] - 2026-03-09

### Fixed — Comprehensive 13-Item Fix Batch (Đợt 3 final)

**Nhóm A — Data Persistence (CRITICAL):**
- **A1**: News data (RSS + CryptoPanic) now written to `TIN_TUC_THO` Sheet tab
- **A2**: Market data (CoinLore, MEXC, CoinGecko, Fear&Greed) now written to `DU_LIEU_THI_TRUONG`
- **A3**: On-chain data (Coinglass, Glassnode, FRED) now written to `DU_LIEU_ONCHAIN`
- **A4**: Generated articles now written to `NOI_DUNG_DA_TAO` Sheet tab
- **A5**: Breaking pipeline now loads/persists dedup entries from `BREAKING_LOG` Sheet (was in-memory only)
- **A6**: Breaking pipeline now writes run logs to `NHAT_KY_PIPELINE` Sheet

**Nhóm B — Broken/Incomplete Features:**
- **B1**: Email backup now reads `SMTP_RECIPIENTS` env var (was always empty → never sent)
- **B2**: Telegram scraper placeholder kept (decided: defer implementation)
- **B4**: Breaking news cooldown changed from 24h → 4h (user-approved)

**Nhóm C — Code Quality:**
- **C1**: All `.to_row()` methods now have call sites (previously dead code)
- **C2**: Fixed 2 bare `except: pass` → added logging in `data_retention.py` and `cryptopanic_client.py`
- **C3**: Version single source of truth: `__init__.py` imports from `core/config.py`
- **C4**: 18 new integration tests for data persistence, email recipients, cooldown

### Stats
- Tests: 326 → 344 (+18)
- All 9 Sheet tabs now have write paths (was 2/9)
- Lint: 0 errors (ruff)

## [0.10.0] - 2026-03-09

### Fixed — P0 Critical Bugs (Dot 3)
- **CRASH FIX**: `clean_articles()` returns `CleanResult`, not list — was crashing daily pipeline
- **DATA FIX**: `source_name` key mismatch in news dict construction (2 places + news_text builder)
- **SCHEMA FIX**: `NHAT_KY_PIPELINE` row format — now matches 8-column Sheet schema
- **SCHEMA FIX**: `BREAKING_LOG` field order — `to_row()`/`from_row()` reordered to match Sheet columns
- **ASYNC FIX**: Wrapped `SheetsClient` + `EmailBackup` sync calls with `asyncio.to_thread()`
- **WIRING FIX**: Dashboard data write (`_write_dashboard_data()`) now called after delivery
- **DATA FIX**: Telegram messages (results[4]) no longer silently dropped
- **DELIVERY FIX**: Breaking news rate limit delay (1.5s between messages)
- Removed dead dependencies: `python-telegram-bot`, `pyyaml` (TG bot uses raw httpx)

### Added — P2 Features (Dot 3)
- **FR6**: MEXC collector — free API, no key, top 15 USDT pairs (`api.mexc.com/api/v3/ticker/24hr`)
- **FR22**: Cross-verify CoinLore vs MEXC prices — logs warning if deviation >5%
- **FR10b**: USDT/VND rate via CoinGecko (`simple/price?ids=tether&vs_currencies=vnd`)
- **FR20**: BTC Dominance + Total Market Cap via CoinLore `/api/global/`
- **FR54**: Test mode TG confirmation message (pipeline status summary)
- **T10**: Inner timeout (60s) for breaking pipeline detection stage
- **T6**: Coinglass v2 deprecation warning with v4 migration notes
- Key metrics expanded: BTC Dominance, Total MCap, USDT/VND in LLM context
- Test fixtures: `mexc_tickers.json`, `coinlore_global.json`, `coingecko_usdt_vnd.json`
- 7 new test classes (11→ tests in test_market_data.py)

### Documentation
- `docs/API_RESEARCH.md`: Full API audit — MEXC, CoinGecko, CoinLore, Coinglass v2/v4
- Updated CLAUDE.md with new collectors and data sources

## [0.9.0] - 2026-03-09

### Fixed — Comprehensive Audit (Dot 1 + Dot 2)
- **CRITICAL**: Wired `daily_pipeline.py` — was placeholder, now connects all collectors → generators → NQ05 → delivery → run log
- **CRITICAL**: Wired `breaking_pipeline.py` — added `_deliver_breaking()` to actually send alerts via Telegram
- Version alignment: `__init__.py`, `config.py`, `pyproject.toml`, `CLAUDE.md` all → 0.9.0
- SMTP env var mismatch: code now reads `SMTP_HOST` / `SMTP_USER` (matches `.env.example`)
- f-string bug in `delivery_manager.py` `_combine_content()` separator
- Added `yfinance>=0.2` to `pyproject.toml` dependencies
- Added `GLASSNODE_API_KEY` + `COINGLASS_API_KEY` to `.env.example`
- Fixed test assertion for version string (0.1.0 → 0.9.0)

## [0.8.0] - 2026-03-09

### Added — Epic 7: Onboarding & Operational Readiness
- Setup Guide: Vietnamese step-by-step, no-code friendly, 15-20 min setup (FR51-FR52)
- Operations Guide: daily workflow, coin management, config, troubleshooting FAQ (Vietnamese)
- Test mode: pipeline detects workflow_dispatch for lite mode (FR53)
- README: comprehensive project overview, architecture, quick start, dev workflow

## [0.7.0] - 2026-03-09

### Added — Epic 6: Pipeline Health Dashboard
- Dashboard Data Generator: JSON output with last_run, llm_used, tier_delivery, error_history, data_freshness (FR45-FR49)
- GitHub Pages static dashboard: dark theme, responsive, auto-refresh 5min, Vietnamese locale (QĐ7)
- CI Integration: both daily + breaking workflows auto-commit dashboard-data.json to gh-pages branch
- Error history: 7-day retention with merge/trim logic
- 18 new tests (319 total), 80.5% coverage

## [0.6.0] - 2026-03-09

### Added — Epic 5: Breaking News Intelligence
- Event Detector: CryptoPanic API, panic_score thresholds, keyword triggers (FR23)
- Alert Dedup & Cooldown: hash(title+source), BREAKING_LOG, 24h TTL, 7-day cleanup (FR56)
- Breaking Content Generator: reuses LLM adapter + NQ05 filter, 300-500 words, raw data fallback
- Severity Classification: 🔴 Critical / 🟠 Important / 🟡 Notable, configurable keywords
- Night Mode: 23:00-07:00 VN (UTC+7), 🔴 always sends, 🟠 deferred to morning, 🟡 to daily (FR28)
- Breaking Pipeline: detect → dedup → generate → classify → deliver, ≤20min timeout
- GitHub Actions workflow: hourly cron, 25min timeout, manual dispatch
- 94 new tests (301 total), 80% coverage

## [0.5.0] - 2026-03-09

### Added — Epic 4: Content Delivery & Reliability
- Telegram Bot: send 6 messages (5 tiers + summary), smart splitting (QĐ6, 4096 char limit)
- Retry & partial delivery: shared retry_utils, status line per tier, always deliver something (NFR7)
- Error notifications: Vietnamese action suggestions, error grouping, severity levels (🔴/⚠️)
- Email backup: SMTP/Gmail, plain text, health check, daily + breaking formats (FR33b)
- Delivery Manager: TG → retry → email fallback orchestration
- Daily pipeline orchestration: timeout (40 min), partial delivery, run logging (FR58)
- E2E integration test: full flow mock (6 deliverables, NQ05 pass, partial delivery)

## [0.4.0] - 2026-03-09

### Added — Epic 3: AI Content Generation & NQ05 Compliance
- LLM Adapter: Multi-provider fallback chain (Groq → Gemini Flash → Flash Lite) with quota integration
- Template Engine: configurable sections from MAU_BAI_VIET, variable substitution, FR20 Key Metrics Table
- Article Generator: 5 tier articles (L1→L5), dual-layer content (TL;DR + Full Analysis), cumulative coins
- BIC Chat Summary Generator: market overview + key highlights, copy-paste ready for Telegram
- NQ05 Filter: dual-layer compliance (prompt + post-filter), banned keywords, terminology fixes, auto-disclaimer
- Integration test: full pipeline mock test (5 articles + 1 summary, NQ05 pass, fallback scenario)

## [0.3.0] - 2026-03-09

### Added — Epic 2: Data Collection Pipeline
- RSS collector: 15+ feeds, parallel async, bilingual VN+EN
- CryptoPanic client: news + sentiment scores + full-text extraction
- Market data: CoinLore crypto prices, yfinance macro (DXY, Gold, VIX), Fear & Greed
- On-chain data: Glassnode, Coinglass, FRED API (graceful degradation)
- Telegram scraper: placeholder with graceful fallback
- Data dedup: title similarity + URL hash matching
- Spam filter: keyword blacklist (configurable from CAU_HINH)

## [0.2.0] - 2026-03-09

### Added — Epic 1: Foundation
- Core: CICError hierarchy, structured logger, config (IS_PRODUCTION)
- Storage: SheetsClient (9-tab schema, batch ops), ConfigLoader (hot-reload)
- QuotaManager: rate limits, daily limits, 6 pre-configured services
- RetryUtils: exponential backoff (2s→4s→8s)
- Data retention: auto-cleanup by age, size warnings
- Pipeline entry points: daily_pipeline.py, breaking_pipeline.py
- 3 GitHub Actions workflows (test, daily-pipeline, breaking-news)

## [0.1.0] - 2026-03-09

### Added
- Project initialization with pyproject.toml (uv + ruff + pytest)
- Planning docs: PRD, Architecture, Epics & Stories
- Sprint status tracking (sprint-status.yaml)
- CLAUDE.md project context for AI-assisted development
- Directory structure: src/cic_daily_report/ with 8 subpackages
