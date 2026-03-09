---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8]
inputDocuments: ['CIC Daily Report/docs/prd.md', 'CIC Daily Report/docs/prd-validation-report.md']
workflowType: 'architecture'
lastStep: 8
status: 'complete'
completedAt: '2026-03-08'
project_name: 'CIC Daily Report'
user_name: 'Anh Cường'
date: '2026-03-08'
---

# Architecture Decision Document

_This document builds collaboratively through step-by-step discovery. Sections are appended as we work through each architectural decision together._

## Project Context Analysis

### Requirements Overview

**Functional Requirements:**
59 FRs trong 10 nhóm (A-J), covering:
- **Data Collection (A)**: 12 FRs — parallel ingestion từ 13+ sources (RSS, CryptoPanic, yfinance, Glassnode, Coinglass, CoinLore, MEXC, Telegram channels, FRED API). Bao gồm deduplication và conflict flagging.
- **Content Generation (B)**: 10 FRs — AI generate 5 tier articles (cumulative L1→L5) + 1 BIC Chat summary, dual-layer content (TL;DR + Full Analysis), NQ05 compliance, Vietnamese natural language, source attribution, Key Metrics Table.
- **Breaking News (C)**: 6 FRs — event detection (panic score + keywords), auto-generate summary + image, 3-level severity (🔴🟠🟡), Night Mode filtering.
- **Delivery (D)**: 5 FRs — Telegram Bot delivery, copy-paste ready format, tier tags, partial delivery with status, error notifications.
- **Reliability (E)**: 5 FRs — multi-LLM fallback (Groq → Gemini Flash → Flash Lite), retry logic, partial delivery, graceful degradation, quota management.
- **Configuration (F)**: 6 FRs — Google Sheets config (templates, coin lists), hot-reload, data storage, auto-cleanup, Sentinel schema design.
- **Health Dashboard (G)**: 6 FRs — pipeline status, LLM tracking, tier delivery status, error history, data freshness, GitHub Pages static.
- **Onboarding (H)**: 4 FRs — visual guide, GitHub Secrets, one-click test, confirmation message.
- **Data Quality (I)**: 2 FRs — spam filtering, alert deduplication with cooldown.
- **Pipeline Execution (J)**: 3 FRs — scheduled + manual trigger, logging, cumulative tier logic.

**Non-Functional Requirements:**
31 NFRs trong 7 categories:
- **Performance**: Pipeline ≤40 min, content ready trước 9AM, breaking news ≤20 min
- **Reliability**: ≥95% uptime, 100% partial delivery, 3-tier LLM fallback ≥99%
- **Security**: GitHub Secrets, encrypted TG session, Service Account, no sensitive data in logs
- **Integration**: API failure isolation, Google Sheets ≤5s batch write, TG ≤30s cho 6 messages
- **Maintainability**: No-code config changes, operator self-service ≤2-5 min
- **Cost**: $0/tháng, GitHub Actions ≤1,900 min/tháng, API quota ≤80%
- **NQ05 Compliance**: 0 violations, 100% disclaimer, thuật ngữ chuẩn

### Scale & Complexity

- **Primary domain**: Data Pipeline + Content Generation + Delivery System
- **Complexity level**: HIGH
  - 13+ data sources parallel ingestion
  - Multi-LLM fallback chain
  - 5 cumulative tier articles + 1 summary per run
  - Breaking news detection pipeline riêng biệt
  - NQ05 regulatory compliance
  - Google Sheets as stateful database + config store
  - CIC Sentinel integration (schema-ready MVP, full Phase 2)
- **Estimated architectural components**: 8-10 modules
- **2 hot paths tách biệt** (confirmed — không cần FastUpdate):
  1. **Daily Pipeline**: 8AM cron → full data + AI content → 6 TG messages
  2. **Breaking News**: Hourly cron → event detection → alert → TG notification

### Technical Constraints & Dependencies

**Platform Constraints:**
- **GitHub Actions**: 2,000 min/tháng free tier. Budget: Daily ~450 + Breaking ~1,440 = ~1,890 min (5.5% buffer). Cần circuit breaker nếu breaking news spike bất thường → tự giảm frequency để không vượt quota.
- **Google Sheets**: 10 triệu cells limit. 7 sheets × 90 ngày retention. Estimated ~15,000-20,000 rows → an toàn nhưng cần auto-cleanup mechanism (FR43).
- **Telegram Bot**: 4,096 ký tự/message limit, 30 messages/phút rate limit. L4 và L5 articles (133-171 coins) có thể vượt limit → cần message splitting strategy.
- **Free API quotas**: Groq 30 req/min + 14,400/day, Gemini 15 req/min + 1,500/day, CryptoPanic 5 req/min. Token throughput (output tokens/min) là constraint thực tế hơn request count cho LLM.
- **Image Generation (FR25)**: Free image services (Unsplash, Pexels) không có crypto charts/graphics. AI image gen không free. MVP khả năng cao dùng text-only breaking news, image là Phase 2.
- **Telegram Channel Parsing (FR8)**: Cần Telegram user session (không phải Bot API) — rủi ro kỹ thuật cao nhất trong data collection. Session có thể expire, bị ban, cần manual re-auth. Cần fallback plan nếu TG channel scraping fail.

**Key Dependencies:**
- Python 3.x + GitHub Actions runners
- Google Sheets API (Service Account)
- Telegram Bot API + Telegram User Session (cho channel parsing)
- Groq API + Gemini API (LLM providers)
- CryptoPanic API (news + sentiment)
- yfinance, Glassnode, Coinglass (market data)

**Notification Fallback:**
- Primary: Telegram Bot
- Backup: Email (configurable list — operator quản lý trên Google Sheets, hỗ trợ nhiều email addresses)
- Khi TG Bot fail → pipeline tự động gửi email backup cho tất cả addresses trong config

### Cross-Cutting Concerns Identified

1. **NQ05 Compliance**: Phải apply ở mọi layer — content generation, breaking news, template engine. Không chỉ là filter cuối cùng mà phải được embed trong AI prompts.
2. **Rate Limiting / Quota Management**: Ảnh hưởng tất cả external API calls — cần centralized quota manager.
3. **Error Handling & Notification**: Mọi component phải report errors → centralized error handler → TG notification (hoặc Email fallback khi TG fail).
4. **Google Sheets as Central Hub**: Vừa là database, vừa là config store, vừa là Sentinel bridge. Schema design ảnh hưởng tất cả components.
5. **Monitoring Bootstrapping**: Pipeline health dashboard cần data từ pipeline runs. Email backup cần hoạt động trước khi TG Bot được setup xong — đây là dependency vòng cần resolve trong onboarding sequence.
6. **Multi-LLM Abstraction**: Groq/Gemini/Flash Lite có APIs khác nhau. Cần abstraction layer thống nhất để switching transparent.
7. **Telegram Message Splitting**: Articles dài (L4/L5 với 133-171 coins) có thể vượt 4,096 chars → cần smart splitting mà vẫn giữ format đẹp, đọc liền mạch.

## Starter Template Evaluation

### Primary Technology Domain

**Python Data Pipeline + GitHub Actions Automation** — dựa trên PRD requirements.

Đặc điểm: Pipeline chạy theo schedule (cron), không phải web server. GitHub Actions là orchestrator — không cần Airflow/Dagster/Prefect (quá nặng và tốn phí cho use case này).

### Starter Options Considered

#### Option A: Custom Clean Structure (uv + ruff + pytest) ✅ SELECTED

Tự setup project structure theo modern Python best practices:
- **uv** — package manager siêu nhanh (thay pip/poetry), chuẩn Python 2026
- **ruff** — linter + formatter (thay black + flake8 + isort), viết bằng Rust
- **pytest** — testing framework chuẩn

**Ưu điểm:** Linh hoạt nhất, structure thiết kế đúng cho data pipeline, không code thừa.
**Nhược điểm:** Phải tự setup (nhưng AI agent làm nhanh).

#### Option B: Cookiecutter Python Template — REJECTED

Thiết kế cho Python library/package, không phải data pipeline. Nhiều file thừa (PyPI publishing, docs generation).

#### Option C: Dagster/Prefect Pipeline Framework — REJECTED

Quá nặng, cần server riêng, không chạy trên GitHub Actions free tier. Vi phạm NFR25 ($0/tháng).

### Selected Starter: Custom Clean Structure

**Rationale:**
- Project là data pipeline đơn giản (2 pipelines, chạy trên GitHub Actions)
- GitHub Actions đã là orchestrator — không cần thêm framework
- Custom structure cho phép thiết kế đúng cho use case
- Modern tooling (uv + ruff + pytest) đảm bảo code quality
- Zero cost — không dependency nào cần paid plan

**Initialization Command:**

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Initialize project
uv init cic-daily-report
cd cic-daily-report

# Core dependencies
uv add gspread google-auth trafilatura httpx feedparser python-telegram-bot pyyaml

# Dev dependencies
uv add --group dev pytest pytest-asyncio pytest-mock pytest-cov ruff mypy
```

### Architectural Decisions Provided by Starter

**Language & Runtime:**
- Python 3.12+ (latest stable)
- Type hints encouraged (mypy for checking)

**Package Management:**
- uv — lockfile (`uv.lock`), fast installs, virtual env management
- `pyproject.toml` as single config file

**Code Quality:**
- ruff — linting + formatting (replaces black + flake8 + isort)
- Line length: 100 chars, target Python 3.12

**Testing Framework:**
- pytest + pytest-asyncio (cho async data collection)
- pytest-mock (mock external APIs trong tests)

**Project Structure:**

```
cic-daily-report/
├── .github/
│   └── workflows/
│       ├── daily-pipeline.yml      # 8AM VN daily cron
│       ├── breaking-news.yml       # Hourly breaking news check
│       └── test.yml                # CI tests on push
├── src/
│   └── cic_daily_report/
│       ├── __init__.py
│       ├── collectors/             # Data collection (FR1-FR12)
│       │   ├── rss_collector.py
│       │   ├── cryptopanic_client.py
│       │   ├── market_data.py
│       │   ├── onchain_data.py
│       │   └── telegram_scraper.py
│       ├── generators/             # AI content generation (FR13-FR22)
│       │   ├── llm_client.py       # Multi-LLM abstraction
│       │   ├── article_generator.py
│       │   ├── template_engine.py
│       │   └── nq05_filter.py
│       ├── delivery/               # Notification & delivery (FR29-FR33)
│       │   ├── telegram_bot.py
│       │   ├── email_sender.py     # Email backup
│       │   └── message_splitter.py
│       ├── storage/                # Google Sheets operations (FR39-FR44)
│       │   ├── sheets_client.py
│       │   └── config_loader.py
│       ├── breaking/               # Breaking news pipeline (FR23-FR28)
│       │   ├── event_detector.py
│       │   └── alert_manager.py
│       ├── core/                   # Shared utilities
│       │   ├── quota_manager.py
│       │   ├── error_handler.py
│       │   └── logger.py
│       ├── daily_pipeline.py       # Daily pipeline entry point
│       └── breaking_pipeline.py    # Breaking news entry point
├── tests/
│   ├── conftest.py
│   ├── test_collectors/
│   ├── test_generators/
│   ├── test_delivery/
│   └── test_breaking/
├── docs/
│   └── setup-guide/                # Visual setup guide (FR51)
├── pyproject.toml                  # All config in one file
├── uv.lock
└── README.md
```

**Note:** Project initialization using this structure should be the first implementation story.

## Core Architectural Decisions

### Decision Priority Analysis

**Critical Decisions (Block Implementation):**
- QĐ1-QĐ7: Tất cả đã quyết định — xem chi tiết bên dưới

**Important Decisions (Shape Architecture):**
- QĐ8: Breaking news config trên Google Sheets

**Deferred Decisions (Post-MVP):**
- Image generation cho breaking news (FR25) — MVP text-only
- Sentinel integration chi tiết — schema sẵn, kết nối Phase 2
- TG channel parsing fallback — cần test thực tế trước

### Data Architecture

**QĐ1: Google Sheets Schema**
- **Lựa chọn:** 1 spreadsheet, 9 tabs riêng biệt
- **Naming:** Tên sheets thuần tiếng Việt không dấu (UPPER_SNAKE_CASE), column headers tiếng Việt có dấu
- **Rationale:** Đơn giản, dễ quản lý trực quan cho operator no-code
- **Tabs:** TIN_TUC_THO, DU_LIEU_THI_TRUONG, DU_LIEU_ONCHAIN, NOI_DUNG_DA_TAO, NHAT_KY_PIPELINE, MAU_BAI_VIET, DANH_SACH_COIN, CAU_HINH, BREAKING_LOG
- **Affects:** storage/, generators/, delivery/, breaking/
- **Ghi chú:** Nếu gặp conflict (pipeline ghi data cùng lúc operator chỉnh config) → tách ra 2 spreadsheets (CONFIG vs DATA) là giải pháp

### API & Communication Patterns

**QĐ2: Multi-LLM Abstraction**
- **Lựa chọn:** Adapter Pattern
- **Rationale:** Chung 1 interface `llm.generate(prompt)`, mỗi LLM (Groq, Gemini Flash, Gemini Flash Lite) có 1 adapter riêng. Thêm LLM mới = thêm 1 file adapter. Nhất quán với CIC Sentinel approach.
- **Fallback chain:** Groq → Gemini Flash → Gemini Flash Lite (tự động)
- **Affects:** generators/llm_client.py

**QĐ5: Data Collection Pattern**
- **Lựa chọn:** Async parallel (`asyncio` + `httpx`)
- **Rationale:** 13+ sources cần thu thập trong ≤10 phút (NFR4). Parallel là bắt buộc. Mỗi source có timeout riêng, 1 source chậm không block các source khác.
- **Lưu ý implementation:** yfinance không async-native → cần `asyncio.to_thread()` wrapper hoặc gọi API trực tiếp qua httpx
- **Affects:** collectors/

**QĐ6: Telegram Message Splitting**
- **Lựa chọn:** Smart split theo section
- **Rationale:** Cắt bài thành nhiều messages theo ranh giới section (TL;DR, Macro, Sector...). Header "📊 L5 — Phần X/Y" cho mỗi message. Đọc tự nhiên, copy-paste lên BIC Group dễ dàng.
- **Trigger:** Chỉ split khi content > 4,000 ký tự (buffer 96 chars so với limit 4,096)
- **Affects:** delivery/message_splitter.py

### Error Handling & Reliability

**QĐ3: Error Handling Strategy**
- **Lựa chọn:** Centralized Error Handler
- **Rationale:** 1 module xử lý lỗi duy nhất. Mọi component báo lỗi về trung tâm → quyết định retry/skip/thông báo. Log vào NHẬT_KÝ_PIPELINE trên Google Sheets. Gửi thông báo qua TG (hoặc Email fallback). Nhất quán với CIC Sentinel `Error_Handler.gs`.
- **Affects:** core/error_handler.py, tất cả modules

**QĐ4: NQ05 Compliance Architecture**
- **Lựa chọn:** Dual-layer (Prompt + Post-filter)
- **Layer 1:** Embed NQ05 rules vào AI prompt (dặn AI "không khuyến nghị mua/bán")
- **Layer 2:** Post-generation scan keywords vi phạm ("nên mua", "bán ngay", "khuyến nghị") + auto-append disclaimer
- **Rationale:** 2 lớp bảo vệ đảm bảo 0 violations (NFR29). AI có thể "quên" lệnh, post-filter catch lại.
- **Affects:** generators/nq05_filter.py, generators/article_generator.py (prompt design)

### Infrastructure & Deployment

**QĐ7: Health Dashboard Architecture**
- **Lựa chọn:** Pipeline ghi JSON → GitHub Pages đọc hiển thị
- **Mechanism:** Mỗi lần pipeline chạy xong → ghi `status.json` → commit vào orphan branch `gh-pages` (không lẫn vào main branch). GitHub Pages host HTML đọc JSON hiển thị dashboard.
- **Rationale:** Zero cost, không cần backend, không cần share Google Sheets access
- **Affects:** core/logger.py (ghi JSON), .github/workflows/ (commit to gh-pages)

### Configuration Management

**QĐ8: Breaking News Config**
- **Lựa chọn:** Google Sheets (tab riêng trong spreadsheet CONFIG)
- **Content:** Panic score thresholds, keyword trigger list, severity levels, Night Mode schedule
- **Rationale:** Operator (Anh Cường) cần tự chỉnh được — ví dụ thêm keyword "ETF" vào trigger list, điều chỉnh panic score threshold từ 3.0 xuống 2.5
- **Affects:** breaking/event_detector.py, storage/config_loader.py

**Secrets vs Config phân biệt:**
- **GitHub Secrets** (encrypted): API keys (Groq, Gemini, TG Bot Token, Google Service Account key)
- **Google Sheets** (operator-managed): Business config (templates, coin lists, email backup list, breaking news thresholds/keywords)

### Testing Strategy (Ghi nhận)

- **Unit tests:** pytest + pytest-mock, mock tất cả external APIs
- **Integration tests:** Fixture-based — lưu sample API responses vào `tests/fixtures/`, replay trong tests. Không gọi API thật, không tốn quota.
- **CI:** GitHub Actions workflow `test.yml` chạy on push

### Decision Impact Analysis

**Implementation Sequence:**
1. Project init (uv, structure, pyproject.toml)
2. Google Sheets schema + storage module (QĐ1)
3. Config loader (QĐ8) — đọc templates, coin lists, breaking thresholds
4. Data collectors — async parallel (QĐ5)
5. LLM abstraction + adapters (QĐ2)
6. NQ05 filter (QĐ4)
7. Content generator + template engine
8. Error handler (QĐ3)
9. TG delivery + message splitter (QĐ6)
10. Email backup delivery
11. Breaking news pipeline
12. Health dashboard (QĐ7)
13. Setup guide + onboarding

**Cross-Component Dependencies:**
- QĐ1 (Sheets schema) → ảnh hưởng QĐ8 (config tabs) và storage module
- QĐ2 (LLM adapter) → ảnh hưởng QĐ4 (NQ05 prompt design)
- QĐ3 (Error handler) → ảnh hưởng tất cả modules (mọi component phải report errors)
- QĐ5 (Async parallel) → ảnh hưởng QĐ3 (error handling trong async context)
- QĐ7 (JSON dashboard) → ảnh hưởng QĐ3 (error handler ghi status data)

## Implementation Patterns & Consistency Rules

### Pattern Categories Defined

**Critical Conflict Points Identified:** 6 core areas + 8 Party Mode additions where AI agents could make different choices

### Naming Patterns

**Google Sheets Naming:**
- Tab names: Vietnamese WITHOUT diacritics, UPPER_SNAKE_CASE → `TIN_TUC_THO`, `BAO_CAO_TONG_HOP`, `CAU_HINH`
- Column headers: Vietnamese WITH diacritics → `Tiêu đề`, `Nguồn tin`, `Ngày thu thập`
- Named ranges: English UPPER_SNAKE_CASE → `CONFIG_RANGE`, `NEWS_HEADER`

**Code Naming (Python):**
- Files: `snake_case.py` → `news_collector.py`, `telegram_sender.py`
- Functions: `snake_case()` → `collect_news()`, `send_report()`
- Variables: `snake_case` → `raw_news_list`, `report_content`
- Classes: `PascalCase` → `NewsCollector`, `TelegramSender`
- Constants: `UPPER_SNAKE_CASE` → `MAX_RETRIES`, `GROQ_MODEL`

**JSON/API Internal Fields:**
- English `snake_case` → `source_name`, `collected_at`, `sentiment_score`
- NOT Vietnamese → tránh encoding issues, dễ debug, chuẩn industry

**Test & Fixture Naming:**
- Test files: `test_{module}.py` → `test_news_collector.py`
- Fixtures: `tests/fixtures/{module}_{scenario}.json` → `tests/fixtures/news_collector_empty_response.json`

### Structure Patterns

**Project Organization:**
```
cic-daily-report/
├── src/cic_daily_report/
│   ├── collectors/       # News sources (RSS, API, scraper)
│   ├── generators/       # AI summarization, NQ05 filter
│   ├── delivery/         # Telegram, Email, message splitter
│   ├── adapters/         # LLM adapter (Groq/Gemini swap)
│   ├── breaking/         # Breaking news detection + dedup
│   ├── storage/          # Google Sheets read/write
│   ├── dashboard/        # Health status writer
│   └── core/             # Error handler, config, logger
├── tests/
│   ├── fixtures/         # {module}_{scenario}.json
│   └── test_*/           # Grouped by module
├── .github/workflows/    # daily-pipeline.yml, breaking-news.yml, test.yml
├── gh-pages/             # GitHub Pages static dashboard
├── docs/                 # Architecture, PRD, setup guide
└── pyproject.toml        # uv + ruff + pytest config
```

**Import Rules:**
- **Absolute imports ONLY** → `from cic_daily_report.collectors.rss_collector import RSSCollector`
- **NO relative imports** → cấm `from ..utils import helper`
- Lý do: tránh confuse khi refactor, dễ trace, dễ debug

### Format Patterns

**API Response Format (internal JSON):**
```json
{
  "status": "success|error",
  "data": { ... },
  "error": { "code": "ERR_001", "message": "..." },
  "collected_at": "2026-03-08T08:00:00Z"
}
```

**Date/Time Format:**
- Internal: ISO 8601 UTC → `2026-03-08T08:00:00Z`
- Google Sheets display: `dd/MM/yyyy HH:mm` (Vietnamese convention)
- Telegram display: `08/03/2026 08:00` (Vietnamese convention)

**Error Response:**
```json
{
  "status": "error",
  "error": {
    "code": "COLLECTOR_TIMEOUT",
    "message": "RSS feed timeout after 30s",
    "source": "news_collector",
    "retry_count": 3
  }
}
```

### Communication Patterns

**Logging Format:**
```
[2026-03-08 08:00:00] [INFO] [news_collector] Collected 15 articles from CoinDesk
[2026-03-08 08:00:05] [ERROR] [telegram_sender] Send failed: 429 Too Many Requests
```
- Levels: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`
- Format: `[timestamp] [level] [module] message`

**Google Sheets Batch Write:**
- **Always use `gspread.batch_update()`** cho multiple cell updates
- **NEVER write cell-by-cell** → tránh quota exhaustion
- Pattern:
```python
cells = []
for row_idx, item in enumerate(data, start=2):
    cells.append(gspread.Cell(row_idx, 1, item["title"]))
    cells.append(gspread.Cell(row_idx, 2, item["source"]))
sheet.update_cells(cells, value_input_option="USER_ENTERED")
```

**Telegram Message Format:**
- Header: `📊 CIC Daily Report — dd/MM/yyyy` hoặc `🔴 CIC Breaking — Tiêu đề`
- Section separator: `———`
- Disclaimer: cuối MỖI message (không phải cuối bài)
- Breaking news subject (email): `[CIC Breaking] Tiêu đề sự kiện`
- Daily report subject (email): `[CIC Daily] dd/MM/yyyy`

**Email Backup:**
- Format: Plain text (không HTML) — đảm bảo tương thích mọi email client
- Subject convention: `[CIC Daily] dd/MM/yyyy` hoặc `[CIC Breaking] Tiêu đề`

### Process Patterns

**Error Handling (Centralized):**
```python
class CICError(Exception):
    def __init__(self, code, message, source, retry=True):
        self.code = code
        self.message = message
        self.source = source
        self.retry = retry
```
- All errors inherit `CICError`
- Centralized handler logs + decides retry vs skip vs alert
- Telegram notification on CRITICAL errors only

**Retry Pattern:**
- Max retries: **3 lần**
- Backoff: **Exponential** → 2s → 4s → 8s
- Sau max retry: **skip + log ERROR + alert** (không crash pipeline)
- Mỗi retry ghi log WARNING với retry count

**NQ05 Compliance (Dual-layer):**
- Layer 1: AI prompt includes "không khuyến nghị mua/bán"
- Layer 2: Post-processing regex scan for banned keywords
- Mandatory disclaimer appended to every Telegram message

**Environment Detection:**
```python
import os
IS_PRODUCTION = os.getenv("GITHUB_ACTIONS") == "true"
# Production: real APIs, real Sheets, real Telegram
# Development: mock data, test sheet, console output
```
- GitHub Actions sets `GITHUB_ACTIONS=true` automatically
- Local dev: no env var → development mode
- No `.env` file needed for this detection

**Config Management:**
- **Secrets** → GitHub Actions Secrets, truy cập qua `os.getenv("KEY")`
- **Non-secret config** → Google Sheets tab `CAU_HINH` hoặc `config.py`
- Pattern: `os.getenv("GROQ_API_KEY", "")` — default empty string, fail rõ ràng

**LLM Adapter Pattern:**
```python
class LLMAdapter:
    def summarize(self, text: str) -> str: ...
class GroqAdapter(LLMAdapter): ...
class GeminiAdapter(LLMAdapter): ...
# Config chọn adapter, swap không đổi code
```

**Rate Limiting:**
- Mỗi external API call: timeout **30s**
- Giữa các API calls: delay **1s** (tránh rate limit)
- Log số calls mỗi lần pipeline chạy → monitor quota usage
- Circuit breaker: nếu >80% monthly quota → giảm breaking news frequency

**Breaking News Dedup:**
- Dedup key: `hash(title + source)`
- Lưu sent keys trong Google Sheets tab `BREAKING_LOG`
- TTL: **24 giờ** — xóa keys cũ hơn 24h mỗi lần chạy
- Tránh gửi trùng tin khi hourly cron chạy 24 lần/ngày

**Google Sheets Size Management:**
- Max rows per tab: **5,000** (soft limit, configurable trong `CAU_HINH`)
- Auto-cleanup: xóa data cũ hơn **30 ngày** mỗi lần pipeline chạy
- Warning log khi đạt **80%** limit (4,000 rows)
- Đảm bảo không vượt 10M cells limit của Google Sheets

### Test Coverage Standards

- **Core modules** (collectors, generators, delivery): **≥80%** coverage
- **Utils/helpers**: **≥60%** coverage
- **Adapters**: interface test **bắt buộc** (verify mỗi adapter implement đúng interface)
- CI fail nếu coverage dưới threshold
- Tool: `pytest-cov` — config trong `pyproject.toml`:
```toml
[tool.pytest.ini_options]
addopts = "--cov=cic_daily_report --cov-fail-under=60"
```

### Enforcement Guidelines

**All AI Agents MUST:**
- Use absolute imports only (no relative imports)
- Use English snake_case for all internal code and JSON fields
- Use Vietnamese (no diacritics) for Google Sheets tab names
- Use Vietnamese (with diacritics) for Google Sheets column headers
- Use `gspread.batch_update()` for all Sheet writes (never cell-by-cell)
- Check `IS_PRODUCTION` before calling real APIs
- Run NQ05 dual-layer compliance on all user-facing text
- Name test fixtures as `tests/fixtures/{module}_{scenario}.json`
- Implement retry with exponential backoff (3 retries, 2s→4s→8s)
- Add 1s delay between external API calls
- Check breaking news dedup before sending notifications
- Log quota usage after each pipeline run

**Anti-Patterns (FORBIDDEN):**
- ❌ Relative imports: `from ..utils import config`
- ❌ Vietnamese in JSON keys: `"tiêu_đề": "..."`
- ❌ Cell-by-cell Sheet writes: `sheet.update_cell(1, 1, val)`
- ❌ Hardcoded API keys in source code
- ❌ Buy/sell recommendations in any output text
- ❌ Diacritics in Sheet tab names: `TIN_TỨC_THÔ`
- ❌ HTML email format (plain text only)
- ❌ Unlimited retries or no backoff
- ❌ Missing dedup check for breaking news

## Project Structure & Boundaries

### Complete Project Directory Structure

```
cic-daily-report/
├── .github/
│   └── workflows/
│       ├── daily-pipeline.yml              # 8AM VN cron → full pipeline
│       ├── breaking-news.yml               # Hourly cron → event detection
│       └── test.yml                        # CI tests on push/PR
├── src/
│   └── cic_daily_report/
│       ├── __init__.py
│       ├── daily_pipeline.py               # Entry point: Daily 8AM
│       ├── breaking_pipeline.py            # Entry point: Breaking hourly
│       │
│       ├── collectors/                     # FR1-FR12: Data collection
│       │   ├── __init__.py
│       │   ├── rss_collector.py            # FR1: RSS feeds (CoinDesk, CoinTelegraph...)
│       │   ├── cryptopanic_client.py       # FR2: CryptoPanic API + sentiment
│       │   ├── market_data.py              # FR3-4: yfinance, CoinLore, MEXC
│       │   ├── onchain_data.py             # FR5-6: Glassnode, Coinglass
│       │   ├── telegram_scraper.py         # FR8: TG channel parsing
│       │   ├── fred_client.py              # FR7: FRED API (macro data)
│       │   └── data_cleaner.py             # FR55-56: Spam filter + dedup
│       │
│       ├── generators/                     # FR13-FR22: AI content
│       │   ├── __init__.py
│       │   ├── article_generator.py        # FR13-17: 5 tier articles + BIC Chat
│       │   ├── template_engine.py          # FR18-19: Vietnamese templates
│       │   └── nq05_filter.py              # FR20-22: Dual-layer NQ05
│       │
│       ├── adapters/                       # QĐ2: LLM abstraction
│       │   ├── __init__.py
│       │   ├── base.py                     # LLMAdapter interface
│       │   ├── groq_adapter.py             # Groq API adapter
│       │   ├── gemini_flash.py             # Gemini Flash adapter
│       │   └── gemini_lite.py              # Gemini Flash Lite adapter
│       │
│       ├── delivery/                       # FR29-FR33: Notifications
│       │   ├── __init__.py
│       │   ├── telegram_bot.py             # FR29-31: TG Bot delivery
│       │   ├── email_sender.py             # QĐ8+PM: Email backup (plain text)
│       │   └── message_splitter.py         # QĐ6: Smart section split
│       │
│       ├── breaking/                       # FR23-FR28: Breaking news
│       │   ├── __init__.py
│       │   ├── event_detector.py           # FR23-24: Panic score + keywords
│       │   ├── alert_manager.py            # FR25-26: Severity + Night Mode
│       │   └── dedup_manager.py            # PM: Hash dedup, 4h TTL
│       │
│       ├── storage/                        # FR39-FR44: Google Sheets
│       │   ├── __init__.py
│       │   ├── sheets_client.py            # Batch write, size management
│       │   └── config_loader.py            # Read CAU_HINH tab
│       │
│       ├── dashboard/                      # FR45-FR50: Health dashboard
│       │   ├── __init__.py
│       │   └── status_writer.py            # Ghi status.json → gh-pages branch
│       │
│       └── core/                           # Cross-cutting concerns
│           ├── __init__.py
│           ├── error_handler.py            # QĐ3: Centralized errors
│           ├── quota_manager.py            # Rate limiting, quota tracking
│           ├── logger.py                   # Structured logging
│           └── config.py                   # IS_PRODUCTION, constants
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                         # Shared fixtures, mocks
│   ├── fixtures/                           # {module}_{scenario}.json
│   │   ├── rss_collector_success.json
│   │   ├── rss_collector_empty.json
│   │   ├── cryptopanic_response.json
│   │   ├── groq_summary.json
│   │   └── market_data_sample.json
│   ├── test_collectors/
│   │   ├── __init__.py
│   │   ├── test_rss_collector.py
│   │   ├── test_cryptopanic_client.py
│   │   ├── test_market_data.py
│   │   └── test_data_cleaner.py
│   ├── test_generators/
│   │   ├── __init__.py
│   │   ├── test_article_generator.py
│   │   └── test_nq05_filter.py
│   ├── test_adapters/
│   │   ├── __init__.py
│   │   └── test_llm_adapters.py            # Interface compliance tests
│   ├── test_delivery/
│   │   ├── __init__.py
│   │   ├── test_telegram_bot.py
│   │   ├── test_email_sender.py
│   │   └── test_message_splitter.py
│   ├── test_breaking/
│   │   ├── __init__.py
│   │   ├── test_event_detector.py
│   │   └── test_dedup_manager.py
│   └── test_storage/
│       ├── __init__.py
│       ├── test_sheets_client.py
│       └── test_config_loader.py
│
├── docs/
│   ├── architecture.md                     # This document
│   ├── prd.md                              # Product requirements
│   └── setup-guide/                        # FR51: Visual onboarding
│       └── README.md
│
├── gh-pages/                               # GitHub Pages template (initial setup)
│   └── index.html                          # Health dashboard UI template
│   # Note: CI copies index.html + commits status.json to orphan branch `gh-pages`
│
├── pyproject.toml                          # uv + ruff + pytest + scripts config
├── uv.lock                                # Lockfile
├── .env.example                            # Required secrets documentation
├── .gitignore
└── README.md
```

### Script Entry Points (pyproject.toml)

```toml
[project.scripts]
cic-daily = "cic_daily_report.daily_pipeline:main"
cic-breaking = "cic_daily_report.breaking_pipeline:main"
```

### Environment Variables (.env.example)

```bash
# === REQUIRED: LLM Providers ===
GROQ_API_KEY=                   # Groq API (primary LLM)
GEMINI_API_KEY=                 # Google Gemini (fallback LLM)

# === REQUIRED: Delivery ===
TELEGRAM_BOT_TOKEN=             # Telegram Bot API token
TELEGRAM_CHAT_ID=               # Target chat/channel ID

# === REQUIRED: Storage ===
GOOGLE_SERVICE_ACCOUNT_JSON=    # Service Account key (base64 encoded)
GOOGLE_SHEETS_ID=               # Spreadsheet ID

# === REQUIRED: Data Sources ===
CRYPTOPANIC_API_KEY=            # CryptoPanic news API
FRED_API_KEY=                   # FRED macro data API

# === OPTIONAL: Data Sources ===
GLASSNODE_API_KEY=              # Glassnode on-chain data
COINGLASS_API_KEY=              # Coinglass derivatives data

# === OPTIONAL: Email Backup ===
SMTP_HOST=                      # SMTP server (e.g. smtp.gmail.com)
SMTP_PORT=                      # SMTP port (e.g. 587)
SMTP_USER=                      # SMTP username
SMTP_PASSWORD=                  # SMTP app password

# === OPTIONAL: Telegram Scraping ===
TELEGRAM_API_ID=                # Telegram user API ID
TELEGRAM_API_HASH=              # Telegram user API hash
TELEGRAM_SESSION=               # Telegram user session string
```

### Architectural Boundaries

**Data Flow (Daily Pipeline):**
```
collectors/ → storage/(ghi Sheets) → generators/(AI content) → nq05_filter → delivery/(TG + Email)
                                          ↑                                        ↓
                                    adapters/(Groq/Gemini)              dashboard/(status.json)
```

**Data Flow (Breaking News):**
```
collectors/(subset) → breaking/event_detector → breaking/dedup_manager → delivery/(TG alert)
                              ↑
                    storage/config_loader (thresholds từ CAU_HINH)
```

**Component Boundaries:**

| Boundary | Rule |
|----------|------|
| `collectors/` → `storage/` | Collectors return dicts, storage writes to Sheets |
| `storage/` → `generators/` | Generators read processed data from Sheets |
| `generators/` → `delivery/` | Generators return strings, delivery formats + sends |
| `adapters/` → `generators/` | Adapters exposed via `LLMAdapter` interface only |
| `core/` → ALL | Error handler, logger, config imported by all modules |
| `breaking/` | Independent pipeline, shares `collectors/` + `delivery/` |

**External Integration Points:**

| Service | Module | Auth |
|---------|--------|------|
| Google Sheets API | `storage/sheets_client.py` | Service Account (GitHub Secret) |
| Groq API | `adapters/groq_adapter.py` | API Key (GitHub Secret) |
| Gemini API | `adapters/gemini_flash.py`, `gemini_lite.py` | API Key (GitHub Secret) |
| Telegram Bot API | `delivery/telegram_bot.py` | Bot Token (GitHub Secret) |
| CryptoPanic API | `collectors/cryptopanic_client.py` | API Key (GitHub Secret) |
| FRED API | `collectors/fred_client.py` | API Key (GitHub Secret) |
| RSS Feeds | `collectors/rss_collector.py` | None (public) |
| yfinance | `collectors/market_data.py` | None (public) |
| Glassnode/Coinglass | `collectors/onchain_data.py` | API Keys (GitHub Secret) |
| SMTP (Email) | `delivery/email_sender.py` | App password (GitHub Secret) |

### Requirements to Structure Mapping

| FR Group | Directory | Key Files |
|----------|-----------|-----------|
| A: Data Collection (FR1-12) | `collectors/` | 7 collector modules + data_cleaner |
| B: Content Generation (FR13-22) | `generators/` + `adapters/` | article_generator, nq05_filter, 3 adapters |
| C: Breaking News (FR23-28) | `breaking/` | event_detector, alert_manager, dedup_manager |
| D: Delivery (FR29-33) | `delivery/` | telegram_bot, email_sender, message_splitter |
| E: Reliability (FR34-38) | `adapters/` + `core/` | LLM fallback chain, error_handler |
| F: Configuration (FR39-44) | `storage/` | sheets_client, config_loader |
| G: Health Dashboard (FR45-50) | `dashboard/` + `gh-pages/` | status_writer, index.html |
| H: Onboarding (FR51-54) | `docs/setup-guide/` | Visual guide |
| I: Data Quality (FR55-56) | `collectors/data_cleaner.py` + `breaking/dedup_manager.py` | Spam filter + dedup |
| J: Pipeline Execution (FR57-59) | `.github/workflows/` | daily-pipeline.yml, breaking-news.yml |

### Google Sheets Tab Mapping

| Tab Name | Purpose | Written By | Read By |
|----------|---------|------------|---------|
| `TIN_TUC_THO` | Raw collected news | `collectors/` | `generators/` |
| `DU_LIEU_THI_TRUONG` | Market data (prices, volume) | `collectors/market_data` | `generators/` |
| `DU_LIEU_ONCHAIN` | On-chain metrics | `collectors/onchain_data` | `generators/` |
| `NOI_DUNG_DA_TAO` | Generated articles | `generators/` | `delivery/` |
| `NHAT_KY_PIPELINE` | Pipeline logs, errors | `core/logger` | `dashboard/` |
| `MAU_BAI_VIET` | Article templates | Operator (manual) | `generators/template_engine` |
| `DANH_SACH_COIN` | Coin list per tier | Operator (manual) | `generators/` |
| `CAU_HINH` | Config (thresholds, emails, limits) | Operator (manual) | `storage/config_loader` |
| `BREAKING_LOG` | Sent breaking news dedup keys | `breaking/dedup_manager` | `breaking/dedup_manager` |

### Development Workflow

**Local Development:**
```bash
uv sync                          # Install dependencies
uv run cic-daily                  # Run daily pipeline (dev mode)
uv run cic-breaking               # Run breaking pipeline (dev mode)
uv run pytest                     # Run all tests
uv run ruff check src/            # Lint
uv run ruff format src/           # Format
```

**CI/CD (GitHub Actions):**
- `test.yml`: On push/PR → install → lint → test → coverage check
- `daily-pipeline.yml`: Cron 8AM VN → full daily pipeline (production)
- `breaking-news.yml`: Cron hourly → breaking news check (production)

## Architecture Validation Results

### Coherence Validation ✅

**Decision Compatibility:**
- Python 3.12 + uv + ruff + pytest → chuẩn modern Python stack, tất cả tương thích
- Adapter Pattern (QĐ2) + Centralized Error Handler (QĐ3) + Async parallel (QĐ5) → hoạt động tốt cùng nhau
- Google Sheets (QĐ1) + GitHub Pages (QĐ7) + GitHub Actions → zero cost, không conflict
- 9 tabs schema (QĐ1) phù hợp với config management (QĐ8) và breaking dedup

**Pattern Consistency:**
- Code naming: English snake_case thống nhất toàn bộ ✅
- JSON fields: English snake_case thống nhất ✅
- Sheet tabs: Vietnamese no-diacritics UPPER_SNAKE_CASE thống nhất ✅
- Sheet columns: Vietnamese with diacritics thống nhất ✅
- Import paths: `from cic_daily_report.*` thống nhất ✅

**Structure Alignment:**
- Mỗi QĐ có files/folders rõ ràng trong cây thư mục ✅
- Boundaries rõ ràng giữa 8 modules ✅
- Data flow diagrams khớp với component boundaries ✅

### Requirements Coverage Validation ✅

| FR Group | Coverage | Notes |
|----------|----------|-------|
| A: Data Collection (FR1-12) | ✅ 100% | 7 collectors + data_cleaner |
| B: Content Generation (FR13-22) | ✅ 100% | article_generator + nq05_filter + 3 adapters |
| C: Breaking News (FR23-28) | ✅ ~90% | FR25 image generation → deferred MVP text-only |
| D: Delivery (FR29-33) | ✅ 100% | TG + Email + message_splitter |
| E: Reliability (FR34-38) | ✅ 100% | LLM fallback + retry + partial delivery pattern |
| F: Configuration (FR39-44) | ✅ 100% | config_loader + CAU_HINH tab |
| G: Health Dashboard (FR45-50) | ✅ 100% | status_writer + gh-pages orphan branch |
| H: Onboarding (FR51-54) | ✅ 100% | docs/setup-guide + .env.example |
| I: Data Quality (FR55-56) | ✅ 100% | data_cleaner + dedup_manager |
| J: Pipeline Execution (FR57-59) | ✅ 100% | 2 workflows + script entries |

**NFR Coverage:**
- Performance (≤40 min) → Async parallel (QĐ5) ✅
- Reliability (≥95%) → LLM fallback + retry 3x + partial delivery ✅
- Security → GitHub Secrets + env detection ✅
- Cost ($0/month) → GitHub Actions free + Sheets free ✅
- NQ05 → Dual-layer (QĐ4) ✅
- Maintainability → No-code config on Sheets ✅

**Partial Delivery Pattern (FR36):**
- `delivery/telegram_bot.py` kiểm tra `NOI_DUNG_DA_TAO` tab
- Có bao nhiêu articles thì gửi bấy nhiêu
- Kèm status note `⚠️ Thiếu L4, L5 do lỗi LLM` nếu không đủ 5 tiers
- Pipeline KHÔNG fail — luôn gửi partial content

### Implementation Readiness Validation ✅

**Decision Completeness:**
- 8 decisions documented với rationale rõ ràng ✅
- Technology versions specified (Python 3.12+, uv, ruff) ✅
- Implementation patterns comprehensive (naming, structure, format, process) ✅
- Concrete code examples provided cho mỗi major pattern ✅

**Structure Completeness:**
- 40+ files defined trong project tree ✅
- 8 module boundaries documented ✅
- 10 external integration points mapped ✅
- 9 Google Sheets tabs fully mapped (written by / read by) ✅

**Pattern Completeness:**
- 12 enforcement rules for AI agents ✅
- 9 anti-patterns documented ✅
- Test coverage thresholds + pytest-cov config ✅
- Dev workflow commands documented ✅

### Gap Analysis Results

**Critical Gaps:** NONE ✅

**Important Gaps (Acknowledged, Not Blocking):**
1. **FR25 Image Generation** → Deferred MVP, text-only breaking news
2. **Telegram Session Management** → FR8 TG channel scraping rủi ro session expire. Cần test thực tế
3. **Sentinel Integration** → Schema-ready, full integration Phase 2

**Nice-to-Have:**
- Dashboard auto-refresh interval → quyết định khi implement
- Detailed column schemas per tab → define trong Epics & Stories

### Architecture Completeness Checklist

**✅ Requirements Analysis**
- [x] Project context thoroughly analyzed (59 FRs, 31 NFRs)
- [x] Scale and complexity assessed (HIGH)
- [x] Technical constraints identified (GitHub Actions 2K min, Sheets 10M cells, TG 4096 chars)
- [x] Cross-cutting concerns mapped (7 concerns)

**✅ Architectural Decisions**
- [x] 8 critical decisions documented (QĐ1-QĐ8)
- [x] Technology stack fully specified (Python 3.12, uv, ruff, pytest, pytest-cov)
- [x] Integration patterns defined (adapter, centralized error, async)
- [x] Performance considerations addressed (parallel, batch write, rate limit)

**✅ Implementation Patterns**
- [x] Naming conventions established (code, JSON, Sheets)
- [x] Structure patterns defined (folders, imports, tests)
- [x] Communication patterns specified (logging, TG format, email)
- [x] Process patterns documented (retry, dedup, size management, NQ05)

**✅ Project Structure**
- [x] Complete directory structure (40+ files)
- [x] Component boundaries established (8 modules, 6 boundaries)
- [x] Integration points mapped (10 external services)
- [x] Requirements to structure mapping complete (10 FR groups → specific files)
- [x] Google Sheets 9-tab schema fully mapped
- [x] Script entry points defined
- [x] Environment variables documented

### Architecture Readiness Assessment

**Overall Status:** ✅ READY FOR IMPLEMENTATION

**Confidence Level:** HIGH

**Key Strengths:**
- Zero-cost architecture hoàn toàn phù hợp NFR
- Clear boundaries — mỗi module có trách nhiệm rõ ràng
- Multiple Party Mode reviews caught gaps (dedup, rate limit, size management, partial delivery...)
- Comprehensive patterns — AI agents có đủ rules để code consistent
- NQ05 compliance dual-layer — bảo vệ 2 lớp
- Partial delivery đảm bảo reliability

**Deferred for Post-MVP:**
- FR25: Image generation cho breaking news
- Sentinel integration chi tiết (schema-ready)
- TG channel parsing advanced fallback

### Implementation Handoff

**AI Agent Guidelines:**
- Follow all 8 architectural decisions exactly as documented
- Use implementation patterns consistently across all components
- Respect project structure and 6 component boundaries
- Use `from cic_daily_report.*` absolute imports only
- Refer to this document for all architectural questions

**Suggested First 3 Stories:**
1. **Project Initialization** — `uv init`, setup `pyproject.toml`, create folder structure, configure ruff + pytest-cov
2. **Google Sheets Schema** — Create 9 tabs với column headers, implement `storage/sheets_client.py` + `config_loader.py`
3. **Config Loader + Error Handler** — `core/config.py` (env detection), `core/error_handler.py` (CICError class), `core/logger.py`
