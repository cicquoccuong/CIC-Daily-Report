# Changelog

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
