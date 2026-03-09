# Changelog

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
