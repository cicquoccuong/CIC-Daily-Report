---
stepsCompleted: [1, 2, 3]
inputDocuments:
  - 'CIC Daily Report/docs/prd.md'
  - 'CIC Daily Report/docs/prd-validation-report.md'
  - 'CIC Daily Report/docs/architecture.md'
---

# CIC Daily Report - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for CIC Daily Report, decomposing the requirements from the PRD and Architecture requirements into implementable stories.

## Requirements Inventory

### Functional Requirements

**A. Data Collection & Ingestion (12 FRs)**
- FR1: Pipeline can thu thập tin tức từ RSS feeds song song (15+ sites, VN + EN)
- FR2: Pipeline can extract full-text từ CryptoPanic original URLs (trafilatura)
- FR3: Pipeline can thu thập macro data từ yfinance (Gold, Oil, VIX, SPX, DXY)
- FR4: Pipeline can thu thập on-chain BTC data từ Glassnode free (MVRV Z-Score, SOPR, Exchange Reserves)
- FR5: Pipeline can thu thập derivatives data từ Coinglass (Funding rates, OI, Liquidations)
- FR6: Pipeline can thu thập price/market cap từ CoinLore (primary) + MEXC (OHLCV)
- FR7: Pipeline can thu thập news sentiment scores từ CryptoPanic (panic_score + votes bullish/bearish)
- FR8: Pipeline can thu thập messages từ Telegram channels (5-7 VN channels ưu tiên, batch collection)
- FR9: Pipeline can thu thập macro data từ FRED API (DGS10, CPI, Fed Balance Sheet)
- FR10: Pipeline can thu thập Fear & Greed Index, Altcoin Season Index, USDT/VND rate
- FR11: Pipeline can phát hiện và gộp tin trùng lặp từ nhiều nguồn
- FR12: Pipeline can flag thông tin mâu thuẫn giữa các nguồn để AI xử lý cẩn thận

**B. Content Generation & Quality (10 FRs)**
- FR13: AI can generate 5 bài tier articles (L1→L5) với cumulative coin coverage
- FR14: AI can generate dual-layer content (TL;DR không thuật ngữ + Full Analysis chuyên sâu)
- FR15: AI can generate 1 BIC Chat summary post (market overview table + key highlights)
- FR16: AI can áp dụng NQ05 compliance filter (không khuyến nghị mua/bán)
- FR17: AI can auto-append disclaimer vào cuối mỗi bài
- FR18: AI can generate content tiếng Việt tự nhiên từ nguồn EN + VN (operator review pass rate ≥90%)
- FR19: AI can ghi source attribution trong content (nguồn dữ liệu rõ ràng)
- FR20: AI can generate Key Metrics Table (7 chỉ số bắt buộc)
- FR21: AI can xử lý bilingual input (EN→VN) với thuật ngữ tài chính chính xác
- FR22: AI can cross-verify số liệu giá từ nhiều nguồn trước khi đưa vào content

**C. Breaking News Pipeline (6 FRs)**
- FR23: Pipeline can phát hiện breaking events qua CryptoPanic panic score thresholds + keyword triggers
- FR24: Pipeline can auto-generate breaking news summary (300-400 từ, Vietnamese, NQ05-compliant)
- FR25: Pipeline can generate/fetch hình minh họa cho breaking news (text-only fallback nếu fail) — MVP: text-only
- FR26: Pipeline can deliver breaking news về Telegram operator với format phù hợp mobile
- FR27: Pipeline can phân loại alert theo 3 cấp severity (🔴🟠🟡)
- FR28: Pipeline can áp dụng Night Mode (🔴 gửi mọi lúc, 🟠 chỉ 7AM-11PM, 🟡 gom vào daily report)

**D. Delivery & Notification (6 FRs)**
- FR29: Telegram Bot can gửi 5 tier articles + 1 summary (6 messages total)
- FR30: Pipeline can format content copy-paste ready cho BIC Group (format giữ nguyên sau khi paste lên BIC Group)
- FR31: Pipeline can tag content với tier labels ([L1]-[L5])
- FR32: Bot can gửi partial delivery kèm status rõ ràng
- FR33: Bot can gửi error notifications với actionable status
- FR33b: Pipeline can gửi email backup khi Telegram Bot fail, cho tất cả addresses trong Google Sheets config (plain text, subject convention [CIC Daily]/[CIC Breaking])

**E. Reliability & Error Handling (5 FRs)**
- FR34: Pipeline supports multi-LLM fallback (Groq → Gemini Flash → Gemini Flash Lite)
- FR35: Pipeline can retry failed operations (tối đa 3 lần)
- FR36: Pipeline supports partial delivery (gửi tiers có sẵn, retry phần còn lại)
- FR37: Pipeline can graceful degrade khi data sources unavailable
- FR38: Pipeline can quản lý API quotas across tất cả services

**F. Configuration & Management (6 FRs)**
- FR39: Operator can quản lý content templates qua Google Sheets
- FR40: Operator can quản lý coin lists per tier qua Google Sheets
- FR41: Pipeline đọc config từ Google Sheets mỗi lần chạy (hot-reload)
- FR42: Pipeline lưu raw data trên Google Sheets
- FR43: Pipeline auto-cleanup data quá retention period (90 ngày raw, 30 ngày generated)
- FR44: Data schema thiết kế sẵn cho Sentinel integration 2 chiều

**G. Pipeline Health Dashboard (6 FRs)**
- FR45: Dashboard hiển thị last run time và status
- FR46: Dashboard hiển thị LLM đang dùng (primary vs fallback)
- FR47: Dashboard hiển thị tier delivery status (per tier)
- FR48: Dashboard hiển thị error history (7 ngày gần nhất)
- FR49: Dashboard hiển thị data freshness per source
- FR50: Dashboard auto-update qua pipeline JSON output (GitHub Pages static)

**H. Onboarding & Setup (4 FRs)**
- FR51: Setup guide có visual screenshots (no-code friendly)
- FR52: API keys lưu trong GitHub Secrets
- FR53: One-click test run qua GitHub Actions manual trigger
- FR54: Test run gửi confirmation message về Telegram

**I. Data Quality & Filtering (2 FRs)**
- FR55: Pipeline can lọc spam/nhiễu qua multi-layer filtering
- FR56: Pipeline can chống alert trùng lặp với cooldown logic

**J. Pipeline Execution (3 FRs)**
- FR57: Pipeline can tự động chạy theo daily schedule VÀ trigger thủ công
- FR58: Pipeline can ghi log mỗi lần chạy vào NHAT_KY_PIPELINE
- FR59: Pipeline can áp dụng cumulative tier logic (L2=L1+L2, L3=L1+L2+L3...)

### NonFunctional Requirements

**Performance (5 NFRs)**
- NFR1: Pipeline total runtime ≤40 phút
- NFR2: Content ready trước 9:00 AM VN
- NFR3: Breaking news response ≤20 phút từ event detection
- NFR4: Data collection (parallel) ≤10 phút
- NFR5: AI content generation ≤25 phút cho 5 tiers + 1 summary

**Reliability (5 NFRs)**
- NFR6: Daily pipeline uptime ≥95% (miss ≤1.5 ngày/tháng)
- NFR7: Partial delivery khi lỗi — 100%, luôn gửi cái gì đó
- NFR8: LLM fallback success ≥99% qua 3-tier fallback
- NFR9: Data source degradation — pipeline hoạt động nếu ≤3 sources fail đồng thời
- NFR10: Error notification — 100%, mọi lỗi đều báo operator

**Security (5 NFRs)**
- NFR11: API keys storage — GitHub Secrets encrypted
- NFR12: TG session protection — encrypted session
- NFR13: Google Sheets access — Service Account key, scope giới hạn
- NFR14: No sensitive data in logs
- NFR15: Repo access — Private repository

**Integration (4 NFRs)**
- NFR16: API failure isolation — 1 API fail không kéo pipeline crash
- NFR17: Google Sheets API latency ≤5 giây per batch write
- NFR18: Telegram Bot delivery ≤30 giây cho 6 messages
- NFR19: Sentinel data compatibility — schema compatible cho Phase 2

**Maintainability (5 NFRs)**
- NFR20: Config changes (no-code) có hiệu lực ngay lần chạy sau
- NFR21: Add/remove coin — operator tự làm trong ≤2 phút
- NFR22: Add/remove content section — operator tự làm trong ≤5 phút
- NFR23: Debug/troubleshoot — pipeline log đủ chi tiết
- NFR24: Code documentation — README + setup guide cho non-dev

**Cost (4 NFRs)**
- NFR25: Monthly operational cost $0/tháng
- NFR26: GitHub Actions usage ≤1,900 min/tháng
- NFR27: API quota usage ≤80% free tier mỗi service
- NFR28: No paid upgrade required — MVP hoàn toàn free tiers

**NQ05 Compliance (3 NFRs)**
- NFR29: Zero compliance violations trong output
- NFR30: Disclaimer presence — 100% bài có disclaimer
- NFR31: Terminology compliance — 100% dùng đúng thuật ngữ NQ05

### Additional Requirements

**Từ Architecture Document:**

1. **Starter Template: Custom Clean Structure** — uv + ruff + pytest + pytest-cov. Project initialization là story đầu tiên (Story 1.1)
2. **8 Architectural Decisions (QĐ1-QĐ8):**
   - QĐ1: Google Sheets 9-tab schema (TIN_TUC_THO, DU_LIEU_THI_TRUONG, DU_LIEU_ONCHAIN, NOI_DUNG_DA_TAO, NHAT_KY_PIPELINE, MAU_BAI_VIET, DANH_SACH_COIN, CAU_HINH, BREAKING_LOG)
   - QĐ2: Multi-LLM Adapter Pattern (Groq → Gemini Flash → Gemini Flash Lite)
   - QĐ3: Centralized Error Handler (CICError class)
   - QĐ4: NQ05 Dual-layer compliance (Prompt + Post-filter)
   - QĐ5: Async parallel data collection (asyncio + httpx)
   - QĐ6: Smart TG message splitting theo section
   - QĐ7: Health Dashboard via JSON + GitHub Pages (orphan branch gh-pages)
   - QĐ8: Breaking news config trên Google Sheets (tab CAU_HINH)
3. **Implementation Patterns:**
   - Absolute imports only: `from cic_daily_report.*`
   - English snake_case cho code + JSON fields
   - Vietnamese no-diacritics UPPER_SNAKE_CASE cho Sheet tab names
   - Vietnamese with diacritics cho Sheet column headers
   - gspread.batch_update() cho tất cả Sheet writes
   - Retry: exponential backoff 3 lần (2s→4s→8s)
   - Breaking news dedup: hash(title+source), 4h TTL
   - Sheet size: max 5,000 rows/tab, auto-cleanup 30 ngày
   - Test coverage: core ≥80%, utils ≥60%, adapters interface test bắt buộc
   - CI fail nếu coverage dưới threshold (--cov-fail-under=60)
4. **Infrastructure Requirements:**
   - 3 GitHub Actions workflows: daily-pipeline.yml, breaking-news.yml, test.yml
   - GitHub Pages orphan branch cho health dashboard
   - pyproject.toml scripts: cic-daily, cic-breaking
   - Environment detection: IS_PRODUCTION = GITHUB_ACTIONS env var
5. **Testing Strategy:**
   - pytest + pytest-asyncio + pytest-mock + pytest-cov
   - Fixture-based: tests/fixtures/{module}_{scenario}.json
   - Mock tất cả external APIs (không gọi API thật)
6. **External Integration Points:** 10 services (Google Sheets, Groq, Gemini x2, Telegram Bot, CryptoPanic, FRED, RSS, yfinance, Glassnode/Coinglass, SMTP)
7. **Architecture Suggested Implementation Sequence:**
   1. Project init → 2. Sheets schema + storage → 3. Config loader → 4. Data collectors → 5. LLM abstraction → 6. NQ05 filter → 7. Content generator → 8. Error handler → 9. TG delivery → 10. Email backup → 11. Breaking news → 12. Dashboard → 13. Onboarding
8. **Deferred for Post-MVP:**
   - FR25: Image generation cho breaking news (text-only MVP)
   - Sentinel integration chi tiết (schema-ready)
   - TG channel parsing advanced fallback

### FR Coverage Map

| FR | Epic | Mô tả |
|----|------|-------|
| FR1-FR12 | Epic 2 | Data Collection (13+ sources) |
| FR13-FR22 | Epic 3 | AI Content Generation + NQ05 |
| FR23-FR28 | Epic 5 | Breaking News Pipeline |
| FR29-FR33 | Epic 4 | Delivery (TG + Email) |
| FR33b | Epic 4 | Email backup khi TG fail |
| FR34 | Epic 3 | Multi-LLM fallback |
| FR35-FR37 | Epic 4 | Retry, partial delivery, graceful degrade |
| FR38 | Epic 1 | Quota management (skeleton) |
| FR39-FR44 | Epic 1 | Configuration & management |
| FR45-FR50 | Epic 6 | Health Dashboard |
| FR51-FR54 | Epic 7 | Onboarding |
| FR55 | Epic 2 | Spam/noise filtering |
| FR56 | Epic 5 | Alert dedup cooldown |
| FR57-FR58 | Epic 1 | Pipeline execution & logging |
| FR59 | Epic 3 | Cumulative tier logic |

**Coverage: 60/60 FRs mapped (100%)**

## Epic List

### Epic 1: Foundation — Project Setup & Configuration Management
Anh Cường có spreadsheet 9 tabs sẵn sàng, quản lý config (coins, templates, thresholds) trực tiếp trên Google Sheets. Project structure chạy được, error handling + logging hoạt động.
**FRs covered:** FR38, FR39, FR40, FR41, FR42, FR43, FR44, FR57, FR58
**NFRs addressed:** NFR11, NFR14, NFR15, NFR17, NFR20, NFR21, NFR22, NFR23, NFR25
**Notes:** Project init (uv, pyproject.toml, ruff, pytest-cov), Google Sheets 9-tab schema (QĐ1), config_loader (QĐ8), error_handler (QĐ3), logger, quota_manager. README.md nằm trong epic này (dev docs).

### Epic 2: Daily Data Collection Pipeline
Pipeline tự động thu thập data từ 13+ sources song song, lưu vào Google Sheets. Data sạch (đã lọc spam, gộp trùng lặp), sẵn sàng cho AI phân tích.
**FRs covered:** FR1, FR2, FR3, FR4, FR5, FR6, FR7, FR8, FR9, FR10, FR11, FR12, FR55
**NFRs addressed:** NFR4, NFR9, NFR16, NFR27
**Notes:** FR8 (TG scraping) = story cuối, có fallback AC. Async parallel (QĐ5). Mỗi collector có timeout riêng. Kết thúc bằng integration test story.

### Epic 3: AI Content Generation & NQ05 Compliance
AI tự động generate 5 bài tier articles (L1→L5 cumulative) + 1 BIC Chat summary, dual-layer content (TL;DR + Full Analysis), tiếng Việt tự nhiên, tuân thủ NQ05 100%.
**FRs covered:** FR13, FR14, FR15, FR16, FR17, FR18, FR19, FR20, FR21, FR22, FR34, FR59
**NFRs addressed:** NFR5, NFR8, NFR29, NFR30, NFR31
**Notes:** LLM Adapter Pattern (QĐ2). NQ05 dual-layer (QĐ4). FR59 cumulative tier (L1=2, L2=19, L3=63, L4=133, L5=171). Kết thúc bằng integration test story.

### Epic 4: Content Delivery & Reliability
Anh Cường nhận đủ 6 messages trên Telegram mỗi sáng, format copy-paste ready cho BIC Group + BIC Chat. Nếu lỗi → partial delivery + email backup. Không bao giờ "im lặng".
**FRs covered:** FR29, FR30, FR31, FR32, FR33, FR33b, FR35, FR36, FR37
**NFRs addressed:** NFR1, NFR2, NFR6, NFR7, NFR10, NFR18
**Notes:** Smart message splitting (QĐ6). Email backup plain text. BIC Chat format = story riêng. FR30 test copy-paste thực tế. Kết thúc bằng integration test story.

### Epic 5: Breaking News Intelligence
Pipeline tự phát hiện breaking events (hourly), phân loại severity (🔴🟠🟡), apply Night Mode, gửi alert về Telegram — Anh Cường review 30 giây rồi forward lên BIC Chat.
**FRs covered:** FR23, FR24, FR25, FR26, FR27, FR28, FR56
**NFRs addressed:** NFR3, NFR26
**Notes:** FR25 MVP text-only. Dedup hash(title+source) TTL 4h. Config trên Sheets (QĐ8). Có thể làm song song với Epic 6.

### Epic 6: Pipeline Health Dashboard
Anh Cường xem dashboard trên web — pipeline status, LLM used, tier delivery, error history 7 ngày, data freshness. Auto-update mỗi lần pipeline chạy.
**FRs covered:** FR45, FR46, FR47, FR48, FR49, FR50
**NFRs addressed:** NFR25
**Notes:** JSON + GitHub Pages orphan branch (QĐ7). Có thể làm song song với Epic 5.

### Epic 7: Onboarding & Operational Readiness
Bất kỳ operator nào cũng setup được hệ thống từ đầu trong 15-20 phút, không cần biết code. Visual guide, one-click test, confirmation message.
**FRs covered:** FR51, FR52, FR53, FR54
**NFRs addressed:** NFR24, NFR28
**Notes:** Map đúng 15 env vars. Docs có thể viết song song sớm. FR53-54 cần pipeline hoạt động. Usability test thực tế với operator.

---

## Epic 1: Foundation — Project Setup & Configuration Management

Anh Cường có spreadsheet 9 tabs sẵn sàng, quản lý config (coins, templates, thresholds) trực tiếp trên Google Sheets. Project structure chạy được, error handling + logging hoạt động.

### Story 1.1: Project Initialization

As a **developer**,
I want **a fully configured Python project with modern tooling (uv, ruff, pytest-cov)**,
So that **I can start building pipeline modules immediately with consistent code quality**.

**Acceptance Criteria:**

**Given** the repository is cloned fresh
**When** I run `uv sync`
**Then** all dependencies install successfully (gspread, google-auth, trafilatura, httpx, feedparser, python-telegram-bot, pyyaml)
**And** dev dependencies install (pytest, pytest-asyncio, pytest-mock, pytest-cov, ruff, mypy)

**Given** the project structure exists
**When** I inspect the directory tree
**Then** all folders match Architecture spec: `src/cic_daily_report/` with `collectors/`, `generators/`, `delivery/`, `adapters/`, `breaking/`, `storage/`, `dashboard/`, `core/` — each with `__init__.py`
**And** `tests/` with `conftest.py`, `fixtures/`, `test_collectors/`, `test_generators/`, `test_adapters/`, `test_delivery/`, `test_breaking/`, `test_storage/`
**And** `gh-pages/`, `docs/`, `.github/workflows/`

**Given** pyproject.toml is configured
**When** I check scripts section
**Then** `cic-daily` maps to `cic_daily_report.daily_pipeline:main`
**And** `cic-breaking` maps to `cic_daily_report.breaking_pipeline:main`
**And** ruff is configured (line-length=100, target Python 3.12)
**And** pytest-cov is configured (`--cov-fail-under=60`)

**Given** the project has supporting files
**When** I check root directory
**Then** `.env.example` lists all 15 env vars (6 required, 9 optional) with descriptions
**And** `.gitignore` excludes `.env`, `__pycache__/`, `.venv/`, `*.pyc`
**And** `README.md` has project description, tech stack, dev workflow commands (`uv sync`, `uv run pytest`, `uv run ruff check`)

### Story 1.2: Core Utilities — Error Handler, Logger & Config

As a **developer**,
I want **centralized error handling, structured logging, and environment detection**,
So that **all future modules have consistent error reporting and I can distinguish dev from production mode**.

**Acceptance Criteria:**

**Given** `core/error_handler.py` exists
**When** I raise a `CICError(code="COLLECTOR_TIMEOUT", message="RSS feed timeout", source="rss_collector", retry=True)`
**Then** the error has attributes `code`, `message`, `source`, `retry`
**And** all custom errors inherit from `CICError`

**Given** `core/logger.py` exists
**When** I call the logger with level INFO from module `news_collector`
**Then** output follows format `[2026-03-09 08:00:00] [INFO] [news_collector] message`
**And** supported levels are DEBUG, INFO, WARNING, ERROR, CRITICAL

**Given** `core/config.py` exists
**When** running on GitHub Actions (`GITHUB_ACTIONS=true`)
**Then** `IS_PRODUCTION` is `True`
**When** running locally (no env var)
**Then** `IS_PRODUCTION` is `False`

**Given** all core modules
**When** I run `uv run pytest tests/`
**Then** unit tests pass for error_handler, logger, config
**And** coverage for `core/` ≥80%

### Story 1.3: Google Sheets Schema & Storage Client

As an **operator (Anh Cường)**,
I want **a Google Sheets spreadsheet with 9 tabs properly structured**,
So that **pipeline can store data and I can manage config directly on Sheets**.

**Acceptance Criteria:**

**Given** `storage/sheets_client.py` exists with Google Service Account auth
**When** I call `create_schema()` (hoặc chạy setup script)
**Then** 9 tabs are created: TIN_TUC_THO, DU_LIEU_THI_TRUONG, DU_LIEU_ONCHAIN, NOI_DUNG_DA_TAO, NHAT_KY_PIPELINE, MAU_BAI_VIET, DANH_SACH_COIN, CAU_HINH, BREAKING_LOG
**And** tab names are Vietnamese without diacritics, UPPER_SNAKE_CASE

**Given** each tab has column headers
**When** I open any tab in Google Sheets
**Then** headers are Vietnamese WITH diacritics (e.g., `Tiêu đề`, `Nguồn tin`, `Ngày thu thập`)
**And** columns match Architecture spec for each tab

**Given** `sheets_client.py` write methods
**When** I write multiple rows of data
**Then** it uses `gspread.batch_update()` (never cell-by-cell writes)
**And** write completes within ≤5 seconds for standard batch (NFR17)

**Given** FR44 Sentinel compatibility
**When** I inspect data schema for TIN_TUC_THO and DU_LIEU_THI_TRUONG
**Then** columns include `event_type`, `coin_symbol`, `sentiment_score`, `action_category`

**Given** unit tests
**When** I run `uv run pytest tests/test_storage/`
**Then** tests pass with mocked gspread (no real API calls)

### Story 1.4: Configuration Management (Hot-Reload)

As an **operator (Anh Cường)**,
I want **to manage content templates, coin lists, and settings on Google Sheets**,
So that **I can customize pipeline behavior without touching code, and changes apply next run**.

**Acceptance Criteria:**

**Given** `storage/config_loader.py` exists
**When** pipeline starts
**Then** it reads tab CAU_HINH for settings (retention days, max rows, email list, breaking thresholds)
**And** it reads tab MAU_BAI_VIET for article templates per tier
**And** it reads tab DANH_SACH_COIN for coin list per tier

**Given** FR41 hot-reload
**When** Anh Cường changes a value in CAU_HINH (e.g., retention từ 90→60 ngày)
**Then** next pipeline run reads the updated value automatically
**And** no code change or restart needed

**Given** FR39 template management
**When** Anh Cường adds a new section row in MAU_BAI_VIET
**Then** config_loader returns the new section in template list
**And** section has fields: tier, section_name, enabled, order, prompt_template, max_words

**Given** FR40 coin list management
**When** Anh Cường adds SOL to tier L2 in DANH_SACH_COIN
**Then** config_loader returns SOL in L2 list
**And** cumulative logic works: L3 list = all L1 + L2 + L3 coins

**Given** NFR21 timing
**When** operator adds/removes a coin on Sheets
**Then** the change is reflected in config within ≤2 minutes (next pipeline read)

### Story 1.5: Quota Manager

As a **developer**,
I want **a centralized quota manager that tracks API usage across all services**,
So that **pipeline never exceeds free tier limits and can circuit-break when needed**.

**Acceptance Criteria:**

**Given** `core/quota_manager.py` exists
**When** a module registers an API call (e.g., `quota.track("groq", 1)`)
**Then** quota_manager increments the counter for that service
**And** logs current usage vs daily limit

**Given** rate limiting rules
**When** an API has 30 req/min limit (Groq)
**Then** quota_manager enforces 1s delay between calls to that service
**And** returns `False` from `quota.can_call("groq")` if rate exceeded

**Given** circuit breaker for GitHub Actions
**When** monthly usage exceeds 80% of 2,000 minutes (NFR27)
**Then** quota_manager signals to reduce breaking news frequency
**And** logs WARNING

**Given** FR38 quota management
**When** pipeline run completes
**Then** quota usage summary is logged (service: calls_made/daily_limit)

### Story 1.6: Data Retention & Auto-Cleanup

As an **operator (Anh Cường)**,
I want **pipeline to automatically clean up old data on Google Sheets**,
So that **Sheets stay fast and don't hit the 10M cell limit**.

**Acceptance Criteria:**

**Given** FR43 auto-cleanup
**When** pipeline runs
**Then** it deletes rows older than 90 days in TIN_TUC_THO, DU_LIEU_THI_TRUONG, DU_LIEU_ONCHAIN
**And** it deletes rows older than 30 days in NOI_DUNG_DA_TAO, NHAT_KY_PIPELINE

**Given** configurable retention
**When** Anh Cường changes retention period in CAU_HINH tab
**Then** cleanup uses the new value next run

**Given** sheet size management
**When** any tab reaches 4,000 rows (80% of 5,000 max)
**Then** logger writes WARNING with tab name and row count
**When** any tab reaches 5,000 rows
**Then** force-cleanup oldest rows regardless of retention setting

**Given** cleanup safety
**When** cleanup removes rows
**Then** it logs number of rows removed per tab
**And** never removes header row

### Story 1.7: Pipeline Execution Framework & CI

As a **developer**,
I want **pipeline entry points and GitHub Actions workflows ready**,
So that **pipeline can run on schedule, manually, and tests run on every push**.

**Acceptance Criteria:**

**Given** `daily_pipeline.py` entry point
**When** I run `uv run cic-daily`
**Then** it executes main() which will orchestrate the daily pipeline
**And** in dev mode (IS_PRODUCTION=False) it logs "Development mode — skipping real API calls"

**Given** `breaking_pipeline.py` entry point
**When** I run `uv run cic-breaking`
**Then** it executes main() which will orchestrate the breaking news check

**Given** FR57 GitHub Actions workflows
**When** I check `.github/workflows/daily-pipeline.yml`
**Then** cron is set to `0 1 * * *` (01:00 UTC = 08:00 VN)
**And** has manual trigger (`workflow_dispatch`)
**When** I check `.github/workflows/breaking-news.yml`
**Then** cron is set to `0 * * * *` (hourly)
**And** has manual trigger

**Given** FR58 pipeline logging
**When** a pipeline run completes (success or error)
**Then** it writes a log entry to NHAT_KY_PIPELINE tab with: timestamp, duration, status, LLM_used, errors

**Given** CI workflow
**When** I check `.github/workflows/test.yml`
**Then** it triggers on push and PR
**And** runs: `uv sync` → `ruff check` → `ruff format --check` → `pytest --cov`
**And** fails if coverage below 60%

---

## Epic 2: Daily Data Collection Pipeline

Pipeline tự động thu thập data từ 13+ sources song song, lưu vào Google Sheets. Data sạch (đã lọc spam, gộp trùng lặp), sẵn sàng cho AI phân tích.

### Story 2.1: RSS News Collector

As an **operator (Anh Cường)**,
I want **pipeline to collect news from 15+ RSS feeds (VN + EN) in parallel**,
So that **daily report has fresh news data from multiple sources**.

**Acceptance Criteria:**

**Given** `collectors/rss_collector.py` exists
**When** pipeline triggers data collection
**Then** it fetches RSS feeds from 15+ sites in parallel using `asyncio` + `httpx`
**And** each feed has individual timeout of 30s
**And** 1 feed failing does not block others (NFR16)

**Given** successful RSS fetch
**When** articles are parsed
**Then** each article has: title, url, source_name, published_date, summary
**And** data is written to TIN_TUC_THO tab via batch write

**Given** FR1 bilingual sources
**When** feeds include both Vietnamese and English sites
**Then** both are collected and stored with `language` field ("vi" or "en")

**Given** RSS feed list configuration
**When** pipeline reads feed URLs
**Then** URLs are loaded from config (CAU_HINH tab or code constants), dễ thêm/bớt
**And** each feed entry has: url, source_name, language, enabled

### Story 2.2: CryptoPanic News & Sentiment

As an **operator (Anh Cường)**,
I want **pipeline to collect news and sentiment scores from CryptoPanic**,
So that **daily report includes market sentiment and trending news**.

**Acceptance Criteria:**

**Given** `collectors/cryptopanic_client.py` exists
**When** pipeline calls CryptoPanic API
**Then** it retrieves latest news with panic_score and votes (bullish/bearish) (FR7)
**And** respects rate limit 5 req/min with 1s delay between calls

**Given** FR2 full-text extraction
**When** CryptoPanic returns article URLs
**Then** pipeline uses `trafilatura` to extract full-text from original URLs
**And** stores both summary and full_text in TIN_TUC_THO
**And** trafilatura has timeout 10s per URL
**And** max 50 URLs per run (tránh pipeline chạy quá lâu)

**Given** API key from GitHub Secrets
**When** `CRYPTOPANIC_API_KEY` is missing
**Then** collector logs ERROR and skips (does not crash pipeline)

### Story 2.3: Market & Macro Data Collector

As an **operator (Anh Cường)**,
I want **pipeline to collect price, macro, and market indicators**,
So that **daily report has accurate market context (DXY, Gold, VIX, Fear & Greed)**.

**Acceptance Criteria:**

**Given** `collectors/market_data.py` exists
**When** pipeline triggers market data collection
**Then** it collects from yfinance: Gold, Oil, VIX, SPX, DXY (FR3)
**And** collects from CoinLore (primary) + MEXC (OHLCV) for crypto prices (FR6)
**And** collects Fear & Greed Index, Altcoin Season Index, USDT/VND rate (FR10)

**Given** yfinance is not async-native
**When** calling yfinance
**Then** it uses `asyncio.to_thread()` wrapper to avoid blocking event loop

**Given** successful collection
**When** data is processed
**Then** all market data is written to DU_LIEU_THI_TRUONG tab with Vietnamese column headers
**And** price data includes: symbol, price, change_24h, volume, market_cap, collected_at

### Story 2.4: On-Chain & Derivatives Data Collector

As an **operator (Anh Cường)**,
I want **pipeline to collect on-chain BTC data and derivatives metrics**,
So that **daily report includes deep technical analysis (MVRV, SOPR, Funding Rates)**.

**Acceptance Criteria:**

**Given** `collectors/onchain_data.py` exists
**When** pipeline triggers on-chain collection
**Then** it collects from Glassnode free: MVRV Z-Score, SOPR, Exchange Reserves (FR4)
**And** collects from Coinglass: Funding rates, Open Interest, Liquidations (FR5)

**Given** data is collected
**When** writing to Sheets
**Then** all on-chain data is written to DU_LIEU_ONCHAIN tab
**And** each metric has: metric_name, value, source, collected_at

**Given** FR9 FRED API
**When** pipeline calls FRED
**Then** it collects DGS10 (10Y Treasury), CPI, Fed Balance Sheet
**And** stores in DU_LIEU_THI_TRUONG tab (macro section)

**Given** optional API keys (Glassnode, Coinglass)
**When** API key is missing
**Then** collector skips that source and logs WARNING (NFR9 graceful degradation)

### Story 2.5: Telegram Channel Scraper

As an **operator (Anh Cường)**,
I want **pipeline to collect messages from 5-7 key Vietnamese Telegram channels**,
So that **daily report captures local crypto community sentiment and breaking info from VN sources**.

**Acceptance Criteria:**

**Given** `collectors/telegram_scraper.py` exists
**When** pipeline triggers TG scraping with valid session
**Then** it collects recent messages from configured channels (FR8)
**And** stores in TIN_TUC_THO tab with source="telegram", channel_name

**Given** TG session credentials from GitHub Secrets
**When** `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION` are all present
**Then** scraper initializes Telegram user session
**When** any of the 3 secrets are missing
**Then** scraper skips entirely, logs WARNING "TG scraping disabled — missing credentials"
**And** pipeline continues normally with other sources (fallback AC)

**Given** session expiry risk
**When** TG session is invalid or expired
**Then** scraper catches auth error, logs ERROR with message "TG session expired — manual re-auth needed"
**And** pipeline continues without TG data

**Given** batch collection
**When** scraping 5-7 channels
**Then** it collects messages from last 24h only
**And** respects Telegram rate limits

### Story 2.6: Data Deduplication & Conflict Detection

As an **operator (Anh Cường)**,
I want **pipeline to detect and merge duplicate news from multiple sources**,
So that **AI doesn't process the same news twice and conflicting info is flagged**.

**Acceptance Criteria:**

**Given** FR11 deduplication
**When** multiple sources report the same event
**Then** pipeline identifies duplicates via title similarity + URL matching
**And** merges into single entry with multiple source attributions

**Given** FR12 conflict detection
**When** 2 sources report conflicting information (e.g., different price figures)
**Then** pipeline flags the entry with `conflict=true`
**And** includes all conflicting values for AI to handle carefully

**Given** dedup runs after all collectors
**When** processing collected data
**Then** dedup summary is logged: "X duplicates merged, Y conflicts flagged"

### Story 2.7: Data Quality — Spam & Noise Filter

As an **operator (Anh Cường)**,
I want **pipeline to filter out spam and low-quality news**,
So that **AI generates reports from reliable, relevant data only**.

**Acceptance Criteria:**

**Given** `collectors/data_cleaner.py` exists (FR55)
**When** raw news data is collected
**Then** multi-layer filtering applies:
1. Keyword blacklist filter (configurable on CAU_HINH tab)
2. AI classify (optional, if LLM quota allows)
3. Quality scoring based on source reputation + content length + relevance

**Given** filtered results
**When** a news item is classified as spam/noise
**Then** it is marked `filtered=true` in TIN_TUC_THO (not deleted, for audit)
**And** filtered items are excluded from AI content generation input

### Story 2.8: Parallel Collection Integration Test

As a **developer**,
I want **all collectors running in parallel within ≤10 minutes**,
So that **data collection phase meets NFR4 performance target**.

**Acceptance Criteria:**

**Given** all collectors from Stories 2.1-2.7 are implemented
**When** `daily_pipeline.py` triggers full data collection
**Then** all collectors run in parallel using `asyncio.gather()`
**And** each collector has independent timeout (30s per source)
**And** total collection time ≤10 minutes (NFR4)

**Given** partial source failure (NFR9)
**When** up to 3 data sources fail simultaneously
**Then** pipeline continues with remaining sources
**And** logs which sources failed and which succeeded
**And** summary written to NHAT_KY_PIPELINE

**Given** quota tracking
**When** collection completes
**Then** quota_manager logs total API calls per service
**And** all collected data is stored in appropriate Sheets tabs

**Given** CI compatibility
**When** integration test runs in CI (GitHub Actions)
**Then** all external APIs are mocked using fixture-based test data (tests/fixtures/)
**And** test verifies parallel execution, error handling, and data flow without real API calls

---

## Epic 3: AI Content Generation & NQ05 Compliance

AI tự động generate 5 bài tier articles (L1→L5 cumulative) + 1 BIC Chat summary, dual-layer content (TL;DR + Full Analysis), tiếng Việt tự nhiên, tuân thủ NQ05 100%.

**Dependency order:** 3.1 → 3.3 → 3.2 → 3.4 → 3.5 → 3.6

### Story 3.1: LLM Adapter Pattern (Multi-Provider)

As a **developer**,
I want **a unified LLM adapter that supports Groq, Gemini Flash, and Gemini Flash Lite with automatic fallback**,
So that **content generation always succeeds even if primary LLM is unavailable**.

**Acceptance Criteria:**

**Given** `adapters/llm_adapter.py` exists
**When** I call `llm.generate(prompt, max_tokens)` with Groq as primary
**Then** it sends request to Groq API
**And** returns normalized response: `{"text": "...", "tokens_used": N, "model": "groq-..."}`
**And** all providers return the same response format regardless of provider-specific API differences

**Given** FR34 multi-LLM fallback (QĐ2)
**When** Groq fails (timeout, rate limit, error)
**Then** adapter automatically tries Gemini Flash
**When** Gemini Flash also fails
**Then** adapter tries Gemini Flash Lite
**And** logs which provider was used: `"LLM fallback: groq → gemini-flash → gemini-flash-lite"`

**Given** provider configuration
**When** adapter initializes
**Then** it reads API keys from env: `GROQ_API_KEY`, `GEMINI_API_KEY`
**And** missing key = skip that provider (not crash)
**And** at least 1 provider must be available or raise `CICError(code="NO_LLM_AVAILABLE")`

**Given** quota integration
**When** each LLM call completes
**Then** `quota_manager.track(provider_name, 1)` is called
**And** adapter respects rate limits per provider (Groq 30 req/min)

**Given** unit tests
**When** I run `uv run pytest tests/test_adapters/`
**Then** tests cover: successful call, fallback chain, all-fail scenario, missing keys
**And** all API calls are mocked (no real LLM calls)

### Story 3.3: Template Engine (Configurable Sections)

As an **operator (Anh Cường)**,
I want **article sections and prompts managed on Google Sheets (MAU_BAI_VIET tab)**,
So that **I can customize content structure without touching code**.

**Acceptance Criteria:**

**Given** `generators/template_engine.py` exists
**When** template engine loads templates from MAU_BAI_VIET tab
**Then** each template has: tier, section_name, enabled, order, prompt_template, max_words
**And** templates are grouped by tier (L1-L5)

**Given** FR39 template management
**When** Anh Cường disables a section (enabled=false) in Sheets
**Then** that section is skipped in content generation
**And** no code change needed

**Given** prompt template variables
**When** template has placeholders like `{coin_list}`, `{market_data}`, `{news_summary}`
**Then** template engine substitutes with actual data before sending to LLM

**Given** FR20 Key Metrics Table
**When** template includes "Key Metrics" section
**Then** it renders table with 7 bắt buộc indicators: BTC Price, BTC Dominance, Total Market Cap, Fear & Greed, DXY, Gold, Funding Rate

**Given** unit tests
**When** I run template engine tests
**Then** tests verify: template loading, variable substitution, section ordering, disabled sections excluded

### Story 3.2: Tier Article Generator (5 Tiers, Dual-Layer, Cumulative)

As an **operator (Anh Cường)**,
I want **AI to generate 5 tier articles with cumulative coin coverage and dual-layer content**,
So that **each tier serves the right audience with appropriate depth**.

**Acceptance Criteria:**

**Given** `generators/article_generator.py` exists
**When** pipeline triggers content generation
**Then** it generates 5 articles: L1 (2 coins), L2 (19 coins), L3 (63 coins), L4 (133 coins), L5 (171 coins) (FR59)
**And** uses templates from Story 3.3 template engine

**Given** FR14 dual-layer content
**When** each article is generated
**Then** it contains:
1. **TL;DR** — ngôn ngữ đơn giản, không thuật ngữ, 2-3 dòng per section
2. **Full Analysis** — phân tích chuyên sâu, có số liệu, thuật ngữ chính xác

**Given** FR59 cumulative logic
**When** generating L3 article
**Then** coin list = all L1 + L2 + L3 coins (cumulative)
**And** article reads from DANH_SACH_COIN tab via config_loader

**Given** FR18 Vietnamese quality
**When** AI generates content from EN + VN sources
**Then** output is Vietnamese tự nhiên, thuật ngữ tài chính chính xác
**And** operator review pass rate target ≥90% (NFR: no awkward machine translation)

**Given** FR19 source attribution
**When** article references data
**Then** source is cited: "Theo CoinLore...", "Dữ liệu Glassnode cho thấy..."

**Given** FR17 disclaimer
**When** each article is generated
**Then** disclaimer is auto-appended at the end (NQ05 compliant)

**Given** FR22 price cross-verification
**When** article includes price data
**Then** price is cross-verified from at least 2 sources before inclusion

### Story 3.4: BIC Chat Summary Generator

As an **operator (Anh Cường)**,
I want **AI to generate 1 BIC Chat summary post with market overview**,
So that **I can copy-paste directly into BIC Chat group**.

**Acceptance Criteria:**

**Given** `generators/summary_generator.py` exists
**When** pipeline triggers summary generation
**Then** it generates 1 BIC Chat summary (FR15) AFTER tier articles are generated
**And** summary uses data from tier articles (đã processed) thay vì raw data — tiết kiệm tokens

**Given** summary format
**When** summary is generated
**Then** it contains:
1. Market overview table (7 key metrics from FR20)
2. Key highlights (3-5 bullet points)
3. Disclaimer

**Given** copy-paste ready
**When** summary is output
**Then** format works when pasted into Telegram group (no broken formatting)

**Given** NQ05 compliance
**When** summary is generated
**Then** no buy/sell recommendations
**And** disclaimer present

### Story 3.5: NQ05 Compliance Dual-Layer Filter

As an **operator (Anh Cường)**,
I want **all content automatically checked for NQ05 compliance**,
So that **zero compliance violations appear in published content**.

**Acceptance Criteria:**

**Given** `generators/nq05_filter.py` exists (QĐ4)
**When** content goes through NQ05 filter
**Then** dual-layer filtering applies:
1. **Prompt layer:** LLM instructions include NQ05 rules (no buy/sell, proper terminology)
2. **Post-filter:** Regex-based scan for banned keywords/patterns

**Given** FR16 banned keywords
**When** post-filter scans content
**Then** it detects: "nên mua", "nên bán", "khuyến nghị", "guaranteed", "chắc chắn tăng/giảm"
**And** banned keywords are loaded from config (CAU_HINH tab), operator có thể thêm/bớt keywords
**And** flagged content is rewritten or removed

**Given** FR17 disclaimer check
**When** filter runs on any article
**Then** it verifies disclaimer exists at end
**And** if missing, auto-appends standard disclaimer

**Given** FR31 terminology compliance
**When** filter runs
**Then** it checks terminology matches NQ05 approved terms
**And** replaces non-compliant terms automatically

**Given** filter results
**When** filtering completes
**Then** logs: "NQ05 filter: X violations found, Y auto-fixed, Z flagged for review"

**Given** NFR29 zero violations
**When** all content passes through filter
**Then** final output has zero NQ05 violations

### Story 3.6: Content Generation Integration Test

As a **developer**,
I want **full content generation pipeline tested end-to-end**,
So that **5 tier articles + 1 summary are generated within NFR5 time limit**.

**Acceptance Criteria:**

**Given** all generators from Stories 3.1-3.5 are implemented
**When** pipeline triggers full content generation with mock data
**Then** it produces: 5 tier articles (L1-L5) + 1 BIC Chat summary
**And** all content passes NQ05 filter
**And** all content is Vietnamese
**And** all content has disclaimers

**Given** NFR5 performance
**When** content generation runs
**Then** total generation time ≤25 minutes for all 6 outputs
**And** each article generation time is logged

**Given** content written to Sheets
**When** generation completes
**Then** all 6 outputs are written to NOI_DUNG_DA_TAO tab
**And** each has: tier, title, content, word_count, llm_used, generated_at, nq05_status

**Given** LLM fallback scenario
**When** primary LLM fails during generation
**Then** fallback kicks in and generation completes
**And** NHAT_KY_PIPELINE logs which LLM was used per article

**Given** CI compatibility
**When** integration test runs in CI
**Then** all LLM calls are mocked with fixture data
**And** test verifies: article count, cumulative logic, NQ05 pass, dual-layer presence

---

## Epic 4: Content Delivery & Reliability

Anh Cường nhận đủ 6 messages trên Telegram mỗi sáng, format copy-paste ready cho BIC Group + BIC Chat. Nếu lỗi → partial delivery + email backup. Không bao giờ "im lặng".

### Story 4.1: Telegram Bot Delivery & Formatting

As an **operator (Anh Cường)**,
I want **Telegram Bot to send 5 tier articles + 1 summary as 6 properly formatted messages**,
So that **I receive the full daily report on Telegram and can copy-paste directly into BIC Group**.

**Acceptance Criteria:**

**Given** `delivery/telegram_bot.py` exists
**When** pipeline triggers delivery with 6 content pieces (5 tiers + 1 summary)
**Then** Bot sends 6 messages to configured chat_id (FR29)
**And** total delivery time ≤30 seconds (NFR18)
**And** messages sent in order: L1 → L2 → L3 → L4 → L5 → Summary
**And** 1-2s delay between messages to avoid Telegram rate limiting

**Given** FR31 tier labels
**When** each message is sent
**Then** message starts with tier tag: `[L1]`, `[L2]`, `[L3]`, `[L4]`, `[L5]`, `[Summary]`

**Given** QĐ6 smart message splitting
**When** a single article exceeds Telegram's 4096 char limit
**Then** it splits by section (not mid-sentence)
**And** each split part has tier label + part indicator `[L3 - Phần 2/3]`

**Given** FR30 copy-paste ready format
**When** content is formatted for Telegram
**Then** it uses Telegram MarkdownV2 format
**And** bold headers, bullet points, line breaks render correctly
**And** MarkdownV2 special characters are properly escaped
**And** when copied from Telegram and pasted into another Telegram group (BIC Group), format giữ nguyên

**Given** BIC Chat summary format
**When** summary message is sent
**Then** market overview table renders as monospace block (for alignment)
**And** key highlights render as bullet list

**Given** Bot token from env
**When** `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID` is missing
**Then** delivery raises `CICError(code="TG_CONFIG_MISSING")`

**Given** unit tests
**When** I run delivery tests
**Then** all Telegram API calls are mocked
**And** tests verify: message count, order, splitting, tier labels, MarkdownV2 escaping

### Story 4.2: Retry & Partial Delivery

As an **operator (Anh Cường)**,
I want **pipeline to retry failed deliveries and send whatever is available**,
So that **I always receive something, even if some tiers failed to generate**.

**Acceptance Criteria:**

**Given** FR35 retry logic
**When** a Telegram send fails (network error, rate limit)
**Then** pipeline retries using shared `@retry` decorator from `core/retry_utils.py`
**And** max 3 retries with exponential backoff (2s → 4s → 8s)
**And** each retry is logged with attempt number
**And** retry logic is the SAME utility used across all modules (not delivery-specific implementation)

**Given** FR36 partial delivery
**When** only 3 out of 5 tiers generated successfully
**Then** Bot sends the 3 available tiers + summary
**And** includes status message: `"⚠️ Partial delivery: L1 ✅ L2 ✅ L3 ✅ L4 ❌ L5 ❌"` (FR32)
**And** status shows which tiers succeeded and which failed

**Given** FR37 graceful degradation
**When** content generation partially fails
**Then** delivery module receives available content and delivers it
**And** never blocks on missing tiers — sends what's ready

**Given** NFR7 always deliver something
**When** ALL tiers fail but summary generated
**Then** Bot sends summary only with error status
**When** nothing generated
**Then** Bot sends error notification (→ Story 4.3)

### Story 4.3: Error Notifications (Actionable, Vietnamese)

As an **operator (Anh Cường)**,
I want **Telegram Bot to notify me about pipeline errors with clear, actionable status in Vietnamese**,
So that **I know exactly what went wrong and what to do, without needing technical knowledge**.

**Acceptance Criteria:**

**Given** FR33 error notifications
**When** pipeline encounters an error
**Then** Bot sends error notification in Vietnamese with:
1. Loại lỗi (thu thập dữ liệu, tạo nội dung, gửi bài)
2. Component bị ảnh hưởng (worker/tier nào)
3. Thời gian
4. Hướng dẫn cụ thể (action suggestion)

**Given** action suggestions from error code mapping
**When** error has code `GROQ_API_ERROR`
**Then** suggestion reads: "Kiểm tra GROQ_API_KEY trong GitHub → Settings → Secrets → Actions"
**And** each `CICError` code maps to a specific Vietnamese action suggestion
**And** suggestions are NOT hardcoded strings — loaded from error code mapping (dict/config)

**Given** NFR10 100% error notification
**When** any error occurs during pipeline run
**Then** error notification is always sent (never silent failure)

**Given** error severity levels
**When** error is recoverable (e.g., 1 source timeout)
**Then** message uses ⚠️ prefix
**When** error is critical (e.g., no LLM available)
**Then** message uses 🔴 prefix

**Given** error grouping
**When** multiple errors occur in one run
**Then** they are grouped into 1 error notification message (not spam)

### Story 4.4: Email Backup Delivery

As an **operator (Anh Cường)**,
I want **pipeline to send email backup when Telegram Bot fails completely**,
So that **I still receive the daily report even if Telegram is down**.

**Acceptance Criteria:**

**Given** `delivery/email_backup.py` exists (FR33b)
**When** Telegram delivery fails after all 3 retries
**Then** pipeline sends email with full report content
**And** email is plain text (no HTML)

**Given** email recipients
**When** sending backup email
**Then** recipients are read from CAU_HINH tab (Google Sheets config)
**And** supports multiple email addresses

**Given** email subject convention
**When** daily report email is sent
**Then** subject follows format: `[CIC Daily] {date} - Daily Report`
**When** breaking news email is sent
**Then** subject follows format: `[CIC Breaking] {date} - {severity emoji} {headline}`

**Given** SMTP configuration
**When** `SMTP_SERVER`, `SMTP_EMAIL`, `SMTP_PASSWORD` env vars are set
**Then** email sends via SMTP (Gmail App Password — 16-char app-specific password)
**When** SMTP vars are missing
**Then** email backup is skipped, logs WARNING "Email backup disabled — missing SMTP config"
**And** pipeline doesn't crash

**Given** SMTP health check
**When** pipeline starts and SMTP vars are present
**Then** it tests SMTP connection (connect + auth, no send)
**And** if test fails, logs WARNING "SMTP connection failed — email backup may not work"
**And** pipeline continues (health check is non-blocking)

### Story 4.5: Daily Pipeline Orchestration & End-to-End Test

As an **operator (Anh Cường)**,
I want **the full daily pipeline to run from data collection to delivery within 40 minutes**,
So that **I receive the complete report before 9:00 AM VN every day**.

**Acceptance Criteria:**

**Given** `delivery/delivery_manager.py` orchestrates all delivery logic
**When** pipeline calls `delivery_manager.deliver(content)`
**Then** delivery_manager handles: TG send → retry → if fail → email backup
**And** `daily_pipeline.py` only calls delivery_manager (separation of concerns)
**And** delivery method is logged ("telegram" or "email_backup")

**Given** `daily_pipeline.py` orchestrates full pipeline
**When** pipeline runs (cron or manual trigger)
**Then** execution order: Data Collection → Content Generation → NQ05 Filter → Delivery
**And** total runtime ≤40 minutes (NFR1)
**And** content ready before 9:00 AM VN (NFR2)

**Given** pipeline-level timeout
**When** pipeline has been running for 40 minutes
**Then** it triggers graceful shutdown
**And** delivers whatever content is ready (partial delivery)
**And** sends error notification: "⚠️ Pipeline timeout — partial delivery"
**And** logs timeout event to NHAT_KY_PIPELINE

**Given** full pipeline logging (FR58)
**When** pipeline completes (success, partial, or timeout)
**Then** NHAT_KY_PIPELINE log entry includes: start_time, end_time, duration, status, tiers_delivered, llm_used, errors, delivery_method

**Given** end-to-end integration test
**When** test runs with all external APIs mocked
**Then** full pipeline executes: mock data → mock LLM → mock delivery
**And** verifies: 6 messages prepared, NQ05 passed, log entry created
**And** test includes timeout scenario verification
**And** test runs in CI without real API calls

---

## Epic 5: Breaking News Intelligence

Pipeline tự phát hiện breaking events (hourly), phân loại severity (🔴🟠🟡), apply Night Mode, gửi alert về Telegram — Anh Cường review 30 giây rồi forward lên BIC Chat.

**Dependency order:** 5.1 → 5.4 → 5.2 → 5.3 → 5.5

### Story 5.1: Breaking Event Detector

As an **operator (Anh Cường)**,
I want **pipeline to automatically detect breaking crypto events every hour**,
So that **I'm alerted about significant market events before they become old news**.

**Acceptance Criteria:**

**Given** `breaking/event_detector.py` exists
**When** breaking pipeline runs (hourly cron)
**Then** it queries CryptoPanic API for recent news
**And** evaluates each item against panic_score thresholds (FR23)

**Given** panic_score thresholds configurable on CAU_HINH tab (QĐ8)
**When** an item has panic_score ≥ configured threshold (e.g., ≥70)
**Then** it is flagged as breaking event

**Given** keyword triggers
**When** news title/content matches configured keywords (e.g., "hack", "exploit", "SEC", "ban", "crash")
**Then** item is flagged as breaking event regardless of panic_score
**And** keywords are configurable on CAU_HINH tab (operator can add/remove)

**Given** CryptoPanic API key
**When** `CRYPTOPANIC_API_KEY` is missing
**Then** breaking pipeline logs ERROR and exits gracefully (no crash)

**Given** detection performance
**When** event detector runs
**Then** detection phase completes within ≤2 minutes
**And** detected events are passed to dedup check (Story 5.4) before content generation

**Given** unit tests
**When** I run detector tests
**Then** tests cover: threshold detection, keyword matching, missing API key, empty results
**And** all API calls are mocked

### Story 5.4: Alert Dedup & Cooldown

As an **operator (Anh Cường)**,
I want **pipeline to prevent duplicate alerts for the same event**,
So that **I don't receive the same breaking news multiple times**.

**Acceptance Criteria:**

**Given** `breaking/dedup_manager.py` exists (FR56)
**When** a breaking event is detected
**Then** it generates dedup hash: `hash(title + source)`
**And** checks hash against BREAKING_LOG tab on Google Sheets (persistent, not in-memory)

**Given** 4h TTL cooldown
**When** hash exists in BREAKING_LOG with timestamp < 4h ago
**Then** event is skipped as duplicate
**And** logs: "Dedup: skipped duplicate event '{title}'"

**Given** new event (no duplicate)
**When** hash does not exist in BREAKING_LOG
**Then** event proceeds to content generation (Story 5.2)
**And** hash + metadata written to BREAKING_LOG tab immediately

**Given** BREAKING_LOG schema
**When** writing to BREAKING_LOG
**Then** each entry has: hash, title, source, severity, detected_at, status (sent/deferred/skipped), delivered_at

**Given** cleanup
**When** BREAKING_LOG entries are older than 7 days
**Then** auto-cleanup removes them (same pattern as Story 1.6)

### Story 5.2: Breaking News Content Generator

As an **operator (Anh Cường)**,
I want **AI to auto-generate a breaking news summary in Vietnamese**,
So that **I can quickly review and forward to BIC Chat within 30 seconds**.

**Acceptance Criteria:**

**Given** `breaking/content_generator.py` exists
**When** a new (non-duplicate) breaking event is detected
**Then** AI generates breaking summary using LLM adapter from Story 3.1 (reuse, no duplicate code)
**And** summary is 300-400 từ target (FR24)
**And** for 🔴 severity events, up to 500 từ is allowed

**Given** FR24 content quality
**When** summary is generated
**Then** content is Vietnamese tự nhiên
**And** includes: event summary, market context, potential impact
**And** source attribution present (FR19)

**Given** NQ05 compliance
**When** summary is generated
**Then** it passes through NQ05 filter from Story 3.5 (reuse)
**And** disclaimer is auto-appended (FR17)
**And** no buy/sell recommendations

**Given** FR25 MVP text-only
**When** breaking news is generated
**Then** output is text only (no image generation)
**And** format optimized for mobile reading on Telegram

**Given** LLM fallback
**When** primary LLM fails
**Then** fallback chain activates (same as daily pipeline)
**And** if all LLMs fail, raw event data is sent as-is with note "⚠️ AI unavailable — raw data"

### Story 5.3: Severity Classification & Night Mode

As an **operator (Anh Cường)**,
I want **breaking alerts classified by severity with Night Mode respect**,
So that **I only get woken up for truly critical events**.

**Acceptance Criteria:**

**Given** FR27 severity classification
**When** breaking event is detected
**Then** it is classified into one of 3 levels:
- 🔴 Critical: major hack/exploit, exchange collapse, regulatory ban, BTC ±10% in 1h
- 🟠 Important: significant partnership, large liquidation, notable regulatory news
- 🟡 Notable: market trend shift, minor regulatory update, notable whale movement
**And** classification rules are configurable on CAU_HINH tab

**Given** FR28 Night Mode
**When** current time is between 23:00 and 07:00 VN time (UTC+7)
**Then** 🔴 events: gửi ngay lập tức (mọi lúc)
**And** 🟠 events: deferred, lưu BREAKING_LOG với `status="deferred_to_morning"`, gửi lúc 07:00
**And** 🟡 events: lưu BREAKING_LOG với `status="deferred_to_daily"`, gom vào daily report

**Given** 🟡 deferred to daily
**When** daily pipeline runs (Epic 2-3)
**Then** it reads BREAKING_LOG for entries with `status="deferred_to_daily"` from last 4h
**And** includes them in daily report as "Breaking Events" section
**And** updates BREAKING_LOG status to "included_in_daily"

**Given** Night Mode timezone
**When** evaluating Night Mode
**Then** all time comparisons use VN timezone (UTC+7)
**And** edge cases handled: 22:59 VN = 🟠 gửi ngay, 23:01 VN = 🟠 deferred

**Given** deferred morning delivery
**When** it's 07:00 VN and there are deferred 🟠 events
**Then** they are sent as a batch with header "🌅 Tin quan trọng qua đêm:"

### Story 5.5: Breaking Pipeline Integration & Delivery

As an **operator (Anh Cường)**,
I want **complete breaking news pipeline working end-to-end with hourly schedule**,
So that **breaking alerts arrive on my Telegram automatically**.

**Acceptance Criteria:**

**Given** `breaking_pipeline.py` orchestrates full breaking flow
**When** hourly cron triggers
**Then** execution order: Detect (5.1) → Dedup (5.4) → Generate (5.2) → Classify (5.3) → Deliver
**And** total time ≤20 minutes from detection to delivery (NFR3)
**And** "≤20 phút" means from pipeline start, not from when event actually occurred

**Given** FR26 delivery via shared delivery_manager
**When** breaking alert is ready to send
**Then** it uses `delivery_manager.deliver(content, message_type="breaking")` from Epic 4
**And** format is mobile-friendly: severity emoji + headline + summary
**And** if TG fails after retries → email backup with subject `[CIC Breaking] {date} - {emoji} {headline}`

**Given** GitHub Actions workflow
**When** I check `.github/workflows/breaking-news.yml`
**Then** cron is set to `0 * * * *` (hourly)
**And** has manual trigger (`workflow_dispatch`)
**And** job timeout ≤25 minutes

**Given** pipeline logging
**When** breaking pipeline completes
**Then** NHAT_KY_PIPELINE entry includes: pipeline_type="breaking", events_detected, events_sent, events_deferred, duration

**Given** NFR26 GitHub Actions quota
**When** breaking pipeline runs hourly (24 runs/day × 30 days)
**Then** total breaking usage ≤720 runs/month
**And** each run uses ≤5 minutes (target)
**And** combined with daily pipeline, stays within 1,900 min/month

**Given** end-to-end integration test
**When** test runs with all external APIs mocked
**Then** full flow: mock CryptoPanic → detect → dedup → mock LLM → classify → mock delivery
**And** tests cover: new event flow, duplicate skip, Night Mode deferred, 🔴 immediate send
**And** Night Mode edge cases tested: 22:59 VN vs 23:01 VN (UTC+7)
**And** test runs in CI without real API calls

---

## Epic 6: Pipeline Health Dashboard

Anh Cường xem dashboard trên web — pipeline status, LLM used, tier delivery, error history 7 ngày, data freshness. Auto-update mỗi lần pipeline chạy.

### Story 6.1: Dashboard Data Generator (JSON Output)

As an **operator (Anh Cường)**,
I want **pipeline to output health data as JSON after every run**,
So that **dashboard always has fresh data to display**.

**Acceptance Criteria:**

**Given** `dashboard/data_generator.py` exists
**When** daily or breaking pipeline completes
**Then** it generates `dashboard-data.json` with:
- `last_run`: timestamp + status (success/partial/error) (FR45)
- `llm_used`: provider name + fallback info (FR46)
- `tier_delivery`: per-tier status (sent/failed/skipped) (FR47)
- `data_freshness`: last collect time per source (FR49)

**Given** FR48 error history
**When** JSON is generated
**Then** it includes `error_history`: array of last 7 days errors
**And** each error has: timestamp, code, message, severity

**Given** JSON output location
**When** pipeline runs on GitHub Actions
**Then** JSON file is generated locally (Story 6.3 handles commit/deploy to gh-pages)

**Given** unit tests
**When** I run dashboard tests
**Then** tests verify JSON schema, all required fields present, date formatting

### Story 6.2: GitHub Pages Static Dashboard

As an **operator (Anh Cường)**,
I want **a simple web dashboard showing pipeline health**,
So that **I can check system status anytime from my phone or computer**.

**Acceptance Criteria:**

**Given** `gh-pages/index.html` exists
**When** I open the GitHub Pages URL
**Then** dashboard loads and displays data from `dashboard-data.json`
**And** auto-refreshes every 5 minutes

**Given** FR45 last run display
**When** dashboard renders
**Then** shows: last run time, status (color-coded: green=success, yellow=partial, red=error)

**Given** FR46 LLM status
**When** dashboard renders
**Then** shows which LLM was used (e.g., "Groq ✅" or "Gemini Flash (fallback) ⚠️")

**Given** FR47 tier delivery
**When** dashboard renders
**Then** shows 5 tiers + summary with status icons (✅/❌) per tier

**Given** FR48 error history
**When** dashboard renders
**Then** shows last 7 days error timeline (date, error code, severity)

**Given** FR49 data freshness
**When** dashboard renders
**Then** shows per-source last collection time with freshness indicator (green < 2h, yellow < 6h, red > 6h)

**Given** FR50 auto-update
**When** pipeline runs and commits new JSON to gh-pages
**Then** dashboard reflects new data within 5 minutes (GitHub Pages CDN cache)

**Given** visible timestamp
**When** dashboard renders
**Then** shows "Cập nhật lần cuối: {datetime}" prominently at top
**And** operator can see exactly when data was last refreshed

**Given** mobile-friendly
**When** Anh Cường opens dashboard on phone
**Then** layout is responsive, readable without zooming

**Given** dashboard smoke test
**When** I run dashboard tests
**Then** HTML is valid (no syntax errors)
**And** JavaScript JSON fetch logic works with mock dashboard-data.json
**And** all dashboard sections render without errors

### Story 6.3: Dashboard Deployment & CI Integration

As a **developer**,
I want **dashboard auto-deployed via GitHub Actions**,
So that **dashboard updates automatically without manual intervention**.

**Acceptance Criteria:**

**Given** gh-pages branch setup
**When** repository is configured
**Then** `gh-pages` is an orphan branch with only dashboard files (index.html, style.css, dashboard-data.json)
**And** GitHub Pages is enabled pointing to gh-pages branch

**Given** auto-update from pipeline
**When** daily or breaking pipeline completes on GitHub Actions
**Then** workflow step commits updated `dashboard-data.json` to gh-pages branch
**And** uses `actions/checkout` with gh-pages branch + `git push` with `GITHUB_TOKEN` (default token)
**And** only commits when JSON content has changed (hash comparison to avoid unnecessary commits)
**And** commit message: `"chore: update dashboard data {timestamp}"`

**Given** dashboard static files
**When** dashboard UI needs updating
**Then** developer updates files in `gh-pages/` directory in main branch
**And** CI copies to gh-pages branch on deploy

**Given** zero cost (NFR25)
**When** dashboard is hosted
**Then** it uses GitHub Pages free tier (no additional hosting cost)

---

## Epic 7: Onboarding & Operational Readiness

Bất kỳ operator nào cũng setup được hệ thống từ đầu trong 15-20 phút, không cần biết code. Visual guide, one-click test, confirmation message.

### Story 7.1: Setup Guide with Visual Screenshots

As an **operator (bất kỳ ai)**,
I want **a step-by-step setup guide with visual screenshots**,
So that **I can set up the entire system without coding knowledge in 15-20 minutes**.

**Acceptance Criteria:**

**Given** `docs/SETUP_GUIDE.md` exists (FR51)
**When** a new operator reads the guide
**Then** it covers all setup steps in order:
1. Fork/clone repository
2. Create Google Cloud Service Account + enable Sheets API
3. Create Google Sheets spreadsheet (or run schema setup)
4. Configure GitHub Secrets (all 15 env vars)
5. Create Telegram Bot via BotFather
6. Enable GitHub Actions workflows
7. Run test (Story 7.3)

**Given** visual screenshots
**When** guide explains a step (e.g., "Create GitHub Secret")
**Then** text descriptions with numbered steps are the primary guide content
**And** annotated screenshots supplement the text (stored in `docs/images/`)
**And** screenshots use numbered callouts (①②③)

**Given** FR52 API keys in GitHub Secrets
**When** guide lists env vars to configure
**Then** it shows all 15 env vars with:
- Name (exact spelling)
- Required vs optional
- Where to get the value (e.g., "Groq → console.groq.com → API Keys")
- Example format (masked: `gsk_abc...xyz`)

**Given** no-code friendly (NFR24)
**When** guide uses technical terms
**Then** Vietnamese explanations are provided in parentheses
**And** no assumption of programming knowledge

### Story 7.2: Operator Operations Guide

As an **operator (Anh Cường)**,
I want **a guide explaining daily operations and common tasks**,
So that **I can manage the system confidently without developer help**.

**Acceptance Criteria:**

**Given** `docs/OPERATIONS_GUIDE.md` exists
**When** operator reads the guide
**Then** it covers:
1. Daily workflow: what to expect each morning (6 messages on TG)
2. How to add/remove coins on DANH_SACH_COIN tab (NFR21: ≤2 min)
3. How to modify content sections on MAU_BAI_VIET tab (NFR22: ≤5 min)
4. How to change settings on CAU_HINH tab
5. How to read the health dashboard
6. What to do when you receive error notifications
7. How to manually trigger a pipeline run

**Given** troubleshooting section
**When** operator encounters common issues
**Then** guide has FAQ with solutions:
- "Pipeline không chạy" → check GitHub Actions status
- "Không nhận tin trên Telegram" → check Bot token, chat_id
- "Nội dung sai/thiếu" → check DANH_SACH_COIN, MAU_BAI_VIET

**Given** Vietnamese language
**When** guide is written
**Then** entire guide is in Vietnamese with diacritics
**And** technical terms have English in parentheses where needed

### Story 7.3: One-Click Test Run & Confirmation

As an **operator (bất kỳ ai)**,
I want **to run a test with one click and receive confirmation on Telegram**,
So that **I know the system is set up correctly before going live**.

**Acceptance Criteria:**

**Given** FR53 one-click test via GitHub Actions
**When** operator goes to Actions → "Daily Pipeline" → "Run workflow"
**Then** they can click "Run workflow" button (manual trigger)
**And** pipeline runs in test mode

**Given** test mode behavior (lite — saves quota)
**When** pipeline runs with `workflow_dispatch`
**Then** it executes pipeline in lite mode: 2-3 data sources only (not full 13+), 1 tier article (not 5), 1 message (not 6)
**And** uses real API calls to verify connectivity
**And** sends to operator's chat only (not public)
**And** prefixes all messages with `[TEST]` to distinguish from production

**Given** test data cleanup
**When** test run completes
**Then** test data rows are cleaned up from Sheets (marked with `test=true` and removed after verification)
**And** no side effects left on Sheets from repeated test runs

**Given** FR54 confirmation message
**When** test run completes successfully
**Then** Bot sends confirmation: "✅ Test thành công! Hệ thống đã sẵn sàng."
**And** includes summary: data sources connected (X/Y), LLM working, delivery OK

**Given** test failure
**When** test run encounters errors
**Then** Bot sends error details: "❌ Test thất bại: {error details}"
**And** includes specific fix instructions (reuse error code mapping from Story 4.3)

**Given** setup guide integration
**When** Story 7.1 setup guide reaches step 7
**Then** it references this test run as the final verification step

### Story 7.4: README & Project Documentation

As a **developer or operator**,
I want **comprehensive README and project documentation**,
So that **anyone can understand the system and contribute**.

**Acceptance Criteria:**

**Given** `README.md` exists (update existing from Story 1.1 — do NOT create new file)
**When** someone visits the repository
**Then** README contains:
1. Project description (1 paragraph)
2. Features list (key capabilities)
3. Architecture overview (diagram or text)
4. Quick start (link to SETUP_GUIDE.md)
5. Tech stack
6. Project structure (directory tree)
7. Development workflow (how to run locally, test, lint)
8. License

**Given** NFR24 documentation
**When** docs/ directory is checked
**Then** it contains: SETUP_GUIDE.md, OPERATIONS_GUIDE.md, CHANGELOG.md
**And** all user-facing docs are in Vietnamese

**Given** developer docs
**When** developer wants to contribute
**Then** README has: how to set up dev environment, run tests, code style (ruff), PR process
