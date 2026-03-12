# CIC Daily Report

## System
- **Version**: 0.13.0 | **Platform**: Python 3.12 + GitHub Actions + Google Sheets
- **Purpose**: Automated crypto daily report pipeline for CIC community (BIC Group/BIC Chat)
- **Output**: 5 tier articles (L1→L5 cumulative) + 1 BIC Chat summary + Breaking news alerts
- **Operator**: Anh Cường (no-code user, receives on Telegram, copy-pastes to BIC)
- **Cost Target**: $0/month (all free tiers)

## Tech Stack
- **Language**: Python 3.12+, async (asyncio + httpx)
- **Package Manager**: uv
- **Linting**: ruff (line-length=100)
- **Testing**: pytest + pytest-asyncio + pytest-mock + pytest-cov (fail-under=60)
- **CI/CD**: GitHub Actions (3 workflows: daily-pipeline, breaking-news, test)
- **Storage**: Google Sheets (9 tabs, gspread + batch_update)
- **AI**: Gemini Flash (primary) → Gemini Flash Lite → Groq Llama 3.3 (fallback chain)
- **Delivery**: Telegram Bot (python-telegram-bot) + SMTP email backup
- **Dashboard**: GitHub Pages (static HTML + JSON, orphan branch gh-pages)

## Project Structure
```
src/cic_daily_report/
├── core/           # error_handler, logger, config, quota_manager, retry_utils
├── collectors/     # rss, cryptopanic, market_data, onchain_data, telegram_scraper, data_cleaner
├── generators/     # article_generator, summary_generator, template_engine, nq05_filter
├── adapters/       # llm_adapter (multi-provider)
├── delivery/       # telegram_bot, email_backup, delivery_manager
├── breaking/       # event_detector, content_generator, dedup_manager, severity_classifier
├── storage/        # sheets_client, config_loader
├── dashboard/      # data_generator
├── daily_pipeline.py
└── breaking_pipeline.py
tests/
├── conftest.py
├── fixtures/       # {module}_{scenario}.json
├── test_*/         # mirrors src/ structure
gh-pages/           # index.html, style.css, dashboard-data.json
docs/               # planning docs, guides
.github/workflows/  # daily-pipeline.yml, breaking-news.yml, test.yml
```

## Google Sheets Schema (9 tabs - Vietnamese no-diacritics UPPER_SNAKE_CASE)
| Tab | Purpose |
|-----|---------|
| TIN_TUC_THO | Raw news data |
| DU_LIEU_THI_TRUONG | Market & macro data |
| DU_LIEU_ONCHAIN | On-chain metrics |
| NOI_DUNG_DA_TAO | Generated content |
| NHAT_KY_PIPELINE | Pipeline run logs |
| MAU_BAI_VIET | Article templates per tier |
| DANH_SACH_COIN | Coin list per tier (cumulative) |
| CAU_HINH | System configuration |
| BREAKING_LOG | Breaking news dedup & history |

## Pipelines
| Pipeline | Schedule | Duration Target |
|----------|----------|----------------|
| Daily | 01:00 UTC (08:00 VN) | ≤40 min |
| Breaking | Hourly (`0 * * * *`) | ≤20 min |

## Quy Trình Làm Việc (MANDATORY)

> ⚠️ Đọc và tuân thủ quy trình chuẩn tại:
> `{project-root}/_bmad/_config/custom/optimized-team-flow/QUY-TRINH-LAM-VIEC-CHUAN.md` (v1.1)
> Áp dụng cho TẤT CẢ agents, TẤT CẢ sessions. **KHÔNG có ngoại lệ.**

## Rules (MANDATORY)
- **Absolute imports only**: `from cic_daily_report.collectors.rss_collector import ...`
- **English snake_case** for code + JSON fields
- **Vietnamese no-diacritics UPPER_SNAKE_CASE** for Sheet tab names
- **Vietnamese WITH diacritics** for Sheet column headers
- **gspread.batch_update()** for ALL Sheet writes (never cell-by-cell)
- **Retry**: exponential backoff 3 attempts (2s→4s→8s) via shared `core/retry_utils.py`
- **NQ05 compliance**: No buy/sell recommendations, disclaimer mandatory, "tài sản mã hóa" not "tiền điện tử"
- **Mock ALL external APIs** in tests — no real API calls in CI
- **Test fixtures**: `tests/fixtures/{module}_{scenario}.json`
- **CI fails** if coverage below 60%
- **Environment detection**: `IS_PRODUCTION = os.getenv("GITHUB_ACTIONS") == "true"`

## Architectural Decisions (QĐ1-QĐ8)
| QĐ | Decision |
|----|----------|
| QĐ1 | Google Sheets 9-tab schema |
| QĐ2 | Multi-LLM Adapter Pattern (Gemini Flash → Flash Lite → Groq) |
| QĐ3 | Centralized Error Handler (CICError class) |
| QĐ4 | NQ05 Dual-layer compliance (Prompt + Post-filter) |
| QĐ5 | Async parallel data collection (asyncio + httpx) |
| QĐ6 | Smart TG message splitting by section |
| QĐ7 | Health Dashboard via JSON + GitHub Pages (orphan branch) |
| QĐ8 | Breaking news config on Google Sheets (tab CAU_HINH) |

## Context Loading (Tiered)
**Tier 0 (this file)**: Tech stack, rules, structure — already in context.

**Tier 1 — Read ON-DEMAND:**
- Sprint progress → `_bmad-output/implementation-artifacts/sprint-status.yaml`
- Current story → `_bmad-output/implementation-artifacts/{story-key}.md`
- Recent changes → `CHANGELOG.md` (top 30 lines)

**Tier 2 — Read ONLY for deep work:**
- Full requirements → `docs/prd.md`
- Architecture details → `docs/architecture.md`
- All epics/stories → `docs/epics.md`

> **DO NOT** read PRD/Architecture/Epics at session start. This file has what you need.

## After Code Changes (Doc-Sync)
1. **Always**: `CHANGELOG.md` + version in `src/cic_daily_report/__init__.py`
2. **If pipeline/config changed**: Update this `CLAUDE.md`
3. **End of session**: Update sprint-status.yaml

## Debug Traces
| Symptom | Check |
|---------|-------|
| Collection fails | `collectors/` → specific collector → API key env var |
| LLM generation fails | `adapters/llm_adapter.py` → fallback chain → API keys |
| Delivery fails | `delivery/telegram_bot.py` → BOT_TOKEN + CHAT_ID |
| NQ05 violation | `generators/nq05_filter.py` → banned keywords in CAU_HINH |
| Dashboard stale | `dashboard/data_generator.py` → gh-pages commit step |
| Breaking news missed | `breaking/event_detector.py` → panic_score threshold in CAU_HINH |

## Related System
- **CIC Sentinel** (separate repo): GAS + Google Sheets, 10-worker pipeline. Daily Report feeds news data to Sentinel for FA enrichment (Phase 2).
