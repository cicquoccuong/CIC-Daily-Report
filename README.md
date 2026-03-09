# CIC Daily Report

Automated crypto daily report pipeline for the CIC (Crypto Inner Circle) community. Collects market data from 5+ sources, generates AI-powered articles in Vietnamese for 5 membership tiers, and delivers via Telegram Bot — all running on GitHub Actions at $0/month.

## Features

- **5-Tier Articles** — Cumulative content (L1 basic → L5 comprehensive) + BIC Chat summary
- **Breaking News** — Hourly detection via CryptoPanic, severity classification (Critical/Important/Notable), Night Mode
- **Multi-LLM Fallback** — Groq Llama 3.3 → Gemini Flash → Gemini Flash Lite
- **NQ05 Compliance** — Dual-layer filter (prompt + post-filter), no buy/sell recommendations
- **Smart Delivery** — Telegram Bot with section-based splitting, retry, email backup
- **Health Dashboard** — GitHub Pages with auto-refresh, error history, data freshness
- **Zero Cost** — All free tiers (GitHub Actions, Groq, Google Sheets, Telegram)

## Architecture

```
Data Sources → Collectors → LLM Generator → NQ05 Filter → Telegram/Email
     │              │              │              │              │
  RSS/CryptoPanic  Async      Groq/Gemini    Banned KW     Smart Split
  Market/OnChain   Parallel   Fallback       Terminology   Partial Delivery
```

## Quick Start

1. Fork this repository
2. Follow [Setup Guide](docs/SETUP_GUIDE.md) (15-20 min, no coding required)
3. Run test via GitHub Actions → "Run workflow"
4. Receive daily reports on Telegram

## Tech Stack

- **Python 3.12+** with async (asyncio + httpx)
- **uv** package manager
- **ruff** linting (line-length=100)
- **pytest** + pytest-asyncio + pytest-cov (319 tests, 80%+ coverage)
- **GitHub Actions** (daily pipeline + breaking news + CI)
- **Google Sheets** (9 tabs — storage + config)
- **Groq/Gemini** AI (multi-LLM fallback chain)
- **Telegram Bot** delivery + SMTP email backup
- **GitHub Pages** health dashboard

## Project Structure

```
src/cic_daily_report/
├── core/           # error_handler, logger, config, quota_manager, retry_utils
├── collectors/     # rss, cryptopanic, market_data, onchain_data, telegram_scraper
├── generators/     # article_generator, summary_generator, template_engine, nq05_filter
├── adapters/       # llm_adapter (multi-provider fallback)
├── delivery/       # telegram_bot, email_backup, delivery_manager
├── breaking/       # event_detector, content_generator, dedup_manager, severity_classifier
├── storage/        # sheets_client, config_loader
├── dashboard/      # data_generator (JSON for GitHub Pages)
├── daily_pipeline.py
└── breaking_pipeline.py
tests/              # mirrors src/ structure, all APIs mocked
gh-pages/           # index.html, style.css, dashboard-data.json
docs/               # SETUP_GUIDE.md, OPERATIONS_GUIDE.md
.github/workflows/  # daily-pipeline.yml, breaking-news.yml, test.yml
```

## Pipelines

| Pipeline | Schedule | Duration | Trigger |
|----------|----------|----------|---------|
| Daily Report | 01:00 UTC (08:00 VN) | ≤40 min | Cron + manual |
| Breaking News | Hourly | ≤20 min | Cron + manual |
| CI Tests | On push/PR | ~2 min | Auto |

## Development

```bash
# Install dependencies
uv sync --dev

# Run linter
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/

# Run tests with coverage
uv run pytest --cov

# Run pipelines locally (dev mode — no API calls)
uv run cic-daily
uv run cic-breaking
```

## Documentation

- [Setup Guide](docs/SETUP_GUIDE.md) — First-time setup (Vietnamese, no-code friendly)
- [Operations Guide](docs/OPERATIONS_GUIDE.md) — Daily operations (Vietnamese)
- [CHANGELOG](CHANGELOG.md) — Version history

## License

MIT
