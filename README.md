# CIC Daily Report

Automated crypto daily report pipeline for CIC community (BIC Group/BIC Chat).

## Tech Stack

- **Python 3.12+** with async (asyncio + httpx)
- **uv** package manager
- **ruff** linting (line-length=100)
- **pytest** + pytest-asyncio + pytest-cov
- **GitHub Actions** (daily pipeline + breaking news + CI)
- **Google Sheets** (9 tabs — storage + config)
- **Groq/Gemini** AI (multi-LLM fallback)
- **Telegram Bot** delivery + SMTP email backup

## Development

```bash
# Install dependencies
uv sync --dev

# Run linter
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/

# Run tests
uv run pytest --cov

# Run pipelines locally (dev mode)
uv run cic-daily
uv run cic-breaking
```

## Project Structure

```
src/cic_daily_report/
├── core/           # error_handler, logger, config, quota_manager, retry_utils
├── collectors/     # rss, cryptopanic, market_data, onchain_data, telegram_scraper
├── generators/     # article_generator, summary_generator, template_engine, nq05_filter
├── adapters/       # llm_adapter (multi-provider)
├── delivery/       # telegram_bot, email_backup, delivery_manager
├── breaking/       # event_detector, content_generator, dedup_manager
├── storage/        # sheets_client, config_loader
├── dashboard/      # data_generator
├── daily_pipeline.py
└── breaking_pipeline.py
```

## Pipelines

| Pipeline | Schedule | Duration |
|----------|----------|----------|
| Daily Report | 01:00 UTC (08:00 VN) | ≤40 min |
| Breaking News | Hourly | ≤20 min |
| CI Tests | On push/PR | ~2 min |
