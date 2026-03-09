"""Daily pipeline entry point — orchestrates full daily report generation.

Execution order: Data Collection → Content Generation → NQ05 Filter → Delivery.
Timeout: 40 minutes (NFR1). Partial delivery on timeout/error (NFR7).
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone

from cic_daily_report.core.logger import get_logger

logger = get_logger("daily_pipeline")

PIPELINE_TIMEOUT_SEC = 40 * 60  # 40 minutes (NFR1)


def is_test_mode() -> bool:
    """Check if pipeline was triggered manually (workflow_dispatch)."""
    return os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch"


def main() -> None:
    """Run the daily pipeline."""
    is_production = os.getenv("GITHUB_ACTIONS") == "true"

    if not is_production:
        logger.info("Development mode — skipping real API calls")
        return

    if is_test_mode():
        logger.info("[TEST] Manual trigger detected — running in test mode")

    asyncio.run(_run_pipeline())


async def _run_pipeline() -> None:
    """Execute the daily pipeline with timeout and error handling."""
    start = time.monotonic()
    run_log = _new_run_log()
    errors: list[Exception] = []
    articles: list[dict[str, str]] = []

    try:
        articles, errors = await asyncio.wait_for(
            _execute_stages(),
            timeout=PIPELINE_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        logger.error("Pipeline timeout — delivering partial content")
        run_log["status"] = "timeout"
        errors.append(Exception("Pipeline timeout after 40 minutes"))
    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        run_log["status"] = "error"
        errors.append(e)

    # Deliver whatever we have (NFR7: always send something)
    try:
        await _deliver(articles, errors)
    except Exception as e:
        logger.error(f"Delivery failed: {e}")

    # Log pipeline run
    elapsed = time.monotonic() - start
    run_log["duration_sec"] = round(elapsed, 1)
    if run_log["status"] == "running":
        run_log["status"] = "success" if not errors else "partial"
    run_log["errors"] = [str(e) for e in errors]
    run_log["tiers_delivered"] = len(articles)

    logger.info(
        f"Pipeline complete: {run_log['status']} in {elapsed:.0f}s, "
        f"{len(articles)} articles, {len(errors)} errors"
    )

    # Write log to Sheets (best effort)
    try:
        await _write_run_log(run_log)
    except Exception as e:
        logger.error(f"Failed to write pipeline log: {e}")


async def _execute_stages() -> tuple[list[dict[str, str]], list[Exception]]:
    """Run all pipeline stages: collect → generate → NQ05 filter.

    Returns (articles_as_dicts, non_fatal_errors).
    """
    from cic_daily_report.adapters.llm_adapter import LLMAdapter
    from cic_daily_report.collectors.cryptopanic_client import collect_cryptopanic
    from cic_daily_report.collectors.data_cleaner import clean_articles
    from cic_daily_report.collectors.market_data import collect_market_data
    from cic_daily_report.collectors.onchain_data import collect_onchain
    from cic_daily_report.collectors.rss_collector import collect_rss
    from cic_daily_report.collectors.telegram_scraper import collect_telegram
    from cic_daily_report.generators.article_generator import (
        GenerationContext,
        generate_tier_articles,
    )
    from cic_daily_report.generators.nq05_filter import check_and_fix
    from cic_daily_report.generators.summary_generator import generate_bic_summary
    from cic_daily_report.generators.template_engine import load_templates
    from cic_daily_report.storage.config_loader import ConfigLoader
    from cic_daily_report.storage.sheets_client import SheetsClient

    errors: list[Exception] = []

    # --- Stage 1: Data Collection (parallel, QĐ5) ---
    logger.info("Stage 1: Data Collection")
    results = await asyncio.gather(
        collect_rss(),
        collect_cryptopanic(),
        collect_market_data(),
        collect_onchain(),
        collect_telegram(),
        return_exceptions=True,
    )

    rss_articles = results[0] if not isinstance(results[0], Exception) else []
    crypto_articles = results[1] if not isinstance(results[1], Exception) else []
    market_data = results[2] if not isinstance(results[2], Exception) else []
    onchain_data = results[3] if not isinstance(results[3], Exception) else []

    for r in results:
        if isinstance(r, Exception):
            logger.warning(f"Collector error (non-fatal): {r}")
            errors.append(r)

    # Clean & dedup news (FR11, FR12, FR55)
    all_news = []
    for a in rss_articles:
        all_news.append({
            "title": a.title, "url": a.url,
            "source": a.source_name, "summary": a.summary,
        })
    for a in crypto_articles:
        all_news.append({
            "title": a.title, "url": a.url,
            "source": a.source_name, "summary": a.summary,
        })
    cleaned_news = clean_articles(all_news)

    # Build text summaries for LLM context
    news_text = "\n".join(
        f"- {a.get('title', '')} ({a.get('source', '')})"
        for a in cleaned_news[:30]
    )
    market_text = "\n".join(
        f"- {p.symbol}: ${p.price} ({p.change_24h:+.1f}%)"
        for p in market_data[:20]
    )
    onchain_text = "\n".join(
        f"- {m.metric_name}: {m.value} ({m.source})" for m in onchain_data
    )

    # Build key metrics dict (FR20)
    key_metrics: dict[str, str | float] = {}
    for p in market_data:
        if p.symbol == "BTC" and p.data_type == "crypto":
            key_metrics["BTC Price"] = f"${p.price:,.0f}"
        elif p.symbol == "Fear&Greed":
            key_metrics["Fear & Greed"] = int(p.price)
        elif p.symbol == "DXY":
            key_metrics["DXY"] = p.price
        elif p.symbol == "Gold":
            key_metrics["Gold"] = f"${p.price:,.0f}"
    for m in onchain_data:
        if m.metric_name == "BTC_Funding_Rate":
            key_metrics["Funding Rate"] = f"{m.value:.4f}"

    logger.info(
        f"Collection done: {len(cleaned_news)} news, "
        f"{len(market_data)} market, {len(onchain_data)} onchain"
    )

    # --- Stage 2: Content Generation (QĐ2) ---
    logger.info("Stage 2: Content Generation")
    try:
        llm = LLMAdapter()
    except Exception as e:
        logger.error(f"LLM init failed: {e}")
        errors.append(e)
        return [], errors

    # Load config from Sheets (QĐ8, FR41)
    templates = {}
    coin_lists: dict[str, list[str]] = {}
    try:
        sheets = SheetsClient()
        config = ConfigLoader(sheets)
        raw_templates = config.get_templates()
        coin_lists = config.get_coin_list()
        templates = load_templates(raw_templates)
    except Exception as e:
        logger.warning(f"Config load failed, using defaults: {e}")
        errors.append(e)

    context = GenerationContext(
        coin_lists=coin_lists,
        market_data=market_text,
        news_summary=news_text,
        onchain_data=onchain_text,
        key_metrics=key_metrics,
    )

    generated = []
    try:
        generated = await generate_tier_articles(llm, templates, context)
    except Exception as e:
        logger.error(f"Article generation failed: {e}")
        errors.append(e)

    # Generate BIC Chat summary (FR15)
    summary = None
    if generated:
        try:
            summary = await generate_bic_summary(llm, generated, key_metrics)
        except Exception as e:
            logger.error(f"Summary generation failed: {e}")
            errors.append(e)

    # --- Stage 3: NQ05 Post-filter (QĐ4 Layer 2) ---
    logger.info("Stage 3: NQ05 Post-filter")
    articles_out: list[dict[str, str]] = []
    for article in generated:
        filtered = check_and_fix(article.content)
        articles_out.append({"tier": article.tier, "content": filtered.content})

    if summary:
        filtered = check_and_fix(summary.content)
        articles_out.append({"tier": "Summary", "content": filtered.content})

    logger.info(f"Pipeline stages complete: {len(articles_out)} articles ready")
    return articles_out, errors


async def _deliver(
    articles: list[dict[str, str]],
    errors: list[Exception],
) -> None:
    """Deliver content via DeliveryManager (TG → email backup)."""
    from cic_daily_report.delivery.delivery_manager import DeliveryManager
    from cic_daily_report.delivery.email_backup import EmailBackup
    from cic_daily_report.delivery.telegram_bot import TelegramBot

    tg = TelegramBot()
    email = EmailBackup()
    manager = DeliveryManager(telegram_bot=tg, email_backup=email)

    pipeline_errors = errors if errors else None
    result = await manager.deliver(articles, pipeline_errors)

    logger.info(
        f"Delivery: {result.method}, "
        f"{result.messages_sent}/{result.messages_total} sent, "
        f"status: {result.status_line()}"
    )


async def _write_run_log(run_log: dict) -> None:
    """Write run log entry to NHAT_KY_PIPELINE sheet."""
    from cic_daily_report.storage.sheets_client import SheetsClient

    try:
        sheets = SheetsClient()
        row = [
            run_log.get("start_time", ""),
            run_log.get("end_time", ""),
            str(run_log.get("duration_sec", 0)),
            run_log.get("status", ""),
            str(run_log.get("tiers_delivered", 0)),
            run_log.get("llm_used", ""),
            "; ".join(run_log.get("errors", [])),
            run_log.get("delivery_method", ""),
        ]
        sheets.batch_append("NHAT_KY_PIPELINE", [row])
    except Exception as e:
        logger.warning(f"Run log write failed (non-critical): {e}")


def _new_run_log() -> dict:
    """Create a new pipeline run log entry template."""
    return {
        "start_time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "end_time": "",
        "duration_sec": 0,
        "status": "running",
        "tiers_delivered": 0,
        "llm_used": "",
        "errors": [],
        "delivery_method": "",
    }


if __name__ == "__main__":
    main()
