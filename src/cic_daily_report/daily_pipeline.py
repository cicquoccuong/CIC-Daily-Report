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

    # FR54: Send test mode confirmation
    if is_test_mode():
        try:
            await _send_test_confirmation(run_log, articles, errors)
        except Exception as e:
            logger.warning(f"Test confirmation failed (non-critical): {e}")

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

    # Write dashboard data to disk (FR45-FR49, QĐ7)
    try:
        _write_dashboard_data(run_log, articles, errors)
    except Exception as e:
        logger.error(f"Dashboard data write failed (non-critical): {e}")


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
    tg_messages = results[4] if not isinstance(results[4], Exception) else []

    for r in results:
        if isinstance(r, Exception):
            logger.warning(f"Collector error (non-fatal): {r}")
            errors.append(r)

    # Clean & dedup news (FR11, FR12, FR55)
    all_news = []
    for a in rss_articles:
        all_news.append(
            {
                "title": a.title,
                "url": a.url,
                "source_name": a.source_name,
                "summary": a.summary,
            }
        )
    for a in crypto_articles:
        all_news.append(
            {
                "title": a.title,
                "url": a.url,
                "source_name": a.source_name,
                "summary": a.summary,
            }
        )
    for m in tg_messages:
        all_news.append(
            {
                "title": m.message_text[:100] if m.message_text else "",
                "url": "",
                "source_name": f"TG:{m.channel_name}",
                "summary": m.message_text or "",
            }
        )
    clean_result = clean_articles(all_news)
    cleaned_news = [a for a in clean_result.articles if not a.get("filtered", False)]

    # Build text summaries for LLM context
    news_items = []
    for a in cleaned_news[:30]:
        line = f"- {a.get('title', '')} ({a.get('source_name', '')})"
        summary = a.get("summary", "")
        if summary:
            line += f"\n  Tóm tắt: {summary[:300]}"
        news_items.append(line)
    news_text = "\n".join(news_items)
    market_items = []
    for p in market_data[:20]:
        line = f"- {p.symbol}: ${p.price:,.2f} ({p.change_24h:+.1f}%)"
        if p.volume_24h > 0:
            line += f" | Vol: ${p.volume_24h / 1e6:,.1f}M"
        if p.market_cap > 0:
            line += f" | MCap: ${p.market_cap / 1e9:,.1f}B"
        market_items.append(line)
    market_text = "\n".join(market_items)
    onchain_text = "\n".join(f"- {m.metric_name}: {m.value} ({m.source})" for m in onchain_data)

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
        elif p.symbol == "BTC_Dominance":
            key_metrics["BTC Dominance"] = f"{p.price:.1f}%"
        elif p.symbol == "Total_MCap":
            key_metrics["Total Market Cap"] = f"${p.price / 1e12:.2f}T"
        elif p.symbol == "USDT/VND":
            key_metrics["USDT/VND"] = f"{p.price:,.0f}"
        elif p.symbol == "ETH_Dominance":
            key_metrics["ETH Dominance"] = f"{p.price:.1f}%"
        elif p.symbol == "TOTAL3":
            key_metrics["TOTAL3"] = f"${p.price / 1e9:,.1f}B"
        elif p.symbol == "Altcoin_Season":
            key_metrics["Altcoin Season"] = int(p.price)
    for m in onchain_data:
        if m.metric_name == "BTC_Funding_Rate":
            key_metrics["Funding Rate"] = f"{m.value:.4f}"

    # Anomaly detection flags for LLM context
    fg_value = key_metrics.get("Fear & Greed")
    if isinstance(fg_value, int):
        if fg_value <= 20:
            key_metrics["⚠️ Sentiment"] = f"EXTREME FEAR ({fg_value}) — historically rare level"
        elif fg_value >= 80:
            key_metrics["⚠️ Sentiment"] = f"EXTREME GREED ({fg_value}) — historically rare level"
    for p in market_data:
        if p.symbol == "BTC" and p.data_type == "crypto" and abs(p.change_24h) >= 5:
            key_metrics["⚠️ BTC Move"] = f"{p.change_24h:+.1f}% — significant daily move"

    # Warn if critical data is missing
    if not cleaned_news:
        logger.warning("No news articles collected — LLM will have no news context")
    if not market_data:
        logger.warning("No market data collected — LLM will have no price context")

    logger.info(
        f"Collection done: {len(cleaned_news)} news, "
        f"{len(market_data)} market, {len(onchain_data)} onchain"
    )

    # --- Write raw data to Sheets (A1-A3) ---
    try:
        sheets_w = SheetsClient()
        await _write_raw_data(sheets_w, rss_articles, crypto_articles, market_data, onchain_data)
    except Exception as e:
        logger.warning(f"Raw data write failed (non-critical): {e}")
        errors.append(e)

    # --- Stage 2: Content Generation (QĐ2) ---
    logger.info("Stage 2: Content Generation")
    try:
        llm = LLMAdapter()
    except Exception as e:
        logger.error(f"LLM init failed: {e}")
        errors.append(e)
        return [], errors

    # Load config from Sheets (QĐ8, FR41) — gspread is sync, wrap with to_thread
    templates = {}
    coin_lists: dict[str, list[str]] = {}
    try:
        sheets = SheetsClient()
        config = ConfigLoader(sheets)
        raw_templates = await asyncio.to_thread(config.get_templates)
        coin_lists = await asyncio.to_thread(config.get_coin_list)
        templates = load_templates(raw_templates)
    except Exception as e:
        logger.warning(f"Config load failed, using defaults: {e}")
        errors.append(e)

    # Build per-tier analysis context (different tiers get different focus)
    tier_context: dict[str, str] = {}
    tier_context["L1"] = (
        "Tier L1: Viết cho người mới, chỉ BTC và ETH. "
        "Tập trung: giá hiện tại, xu hướng ngắn hạn, tâm lý thị trường. "
        "Giải thích đơn giản, không thuật ngữ phức tạp."
    )
    tier_context["L2"] = (
        "Tier L2: Phân tích kỹ thuật cho 19 coins. "
        "Tập trung: support/resistance dựa trên giá hiện tại, volume analysis, "
        "altcoin nổi bật (biến động >3%). "
        "Nêu rõ mức hỗ trợ/kháng cự cụ thể nếu có data."
    )
    tier_context["L3"] = (
        "Tier L3: Phân tích on-chain + macro chuyên sâu. "
        "Tập trung: DXY-BTC correlation, Gold signal, on-chain metrics interpretation, "
        "funding rate ý nghĩa gì cho sentiment. "
        "Giải thích mối quan hệ giữa macro và crypto."
    )
    tier_context["L4"] = (
        "Tier L4: Phân tích rủi ro và quản lý danh mục. "
        "Tập trung: phân tích rủi ro theo sector (L1/DeFi/L2/AI), "
        "so sánh hiệu suất giữa các nhóm coin. "
        "TUYỆT ĐỐI KHÔNG đưa ra tỷ lệ phân bổ cụ thể (%) — vi phạm NQ05. "
        "Chỉ phân tích rủi ro, KHÔNG gợi ý mua/bán/phân bổ."
    )
    tier_context["L5"] = (
        "Tier L5: Báo cáo chuyên sâu toàn diện cho Master members. "
        "Tập trung: macro-crypto correlation, on-chain deep dive, "
        "sector rotation analysis (DeFi vs L1 vs AI tokens), "
        "derivatives insight (funding rate, OI), risk flags. "
        "Viết chuyên sâu, dùng thuật ngữ chính xác, có dẫn chứng data."
    )

    context = GenerationContext(
        coin_lists=coin_lists,
        market_data=market_text,
        news_summary=news_text,
        onchain_data=onchain_text,
        key_metrics=key_metrics,
        tier_context=tier_context,
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

    # --- Write generated content to Sheets (A4) ---
    try:
        sheets_w2 = SheetsClient()
        await _write_generated_content(sheets_w2, articles_out)
    except Exception as e:
        logger.warning(f"Generated content write failed (non-critical): {e}")
        errors.append(e)

    logger.info(f"Pipeline stages complete: {len(articles_out)} articles ready")
    return articles_out, errors


async def _write_raw_data(
    sheets: object,
    rss_articles: list,
    crypto_articles: list,
    market_data: list,
    onchain_data: list,
) -> None:
    """Write collected raw data to Sheets tabs (A1-A3)."""
    import asyncio as _aio

    # A1: News → TIN_TUC_THO
    news_rows = []
    for a in rss_articles:
        if hasattr(a, "to_row"):
            news_rows.append(a.to_row())
    for a in crypto_articles:
        if hasattr(a, "to_row"):
            news_rows.append(a.to_row())
    if news_rows:
        await _aio.to_thread(sheets.batch_append, "TIN_TUC_THO", news_rows)
        logger.info(f"Wrote {len(news_rows)} rows to TIN_TUC_THO")

    # A2: Market data → DU_LIEU_THI_TRUONG
    market_rows = [p.to_row() for p in market_data]
    if market_rows:
        await _aio.to_thread(sheets.batch_append, "DU_LIEU_THI_TRUONG", market_rows)
        logger.info(f"Wrote {len(market_rows)} rows to DU_LIEU_THI_TRUONG")

    # A3: Onchain data → DU_LIEU_ONCHAIN
    onchain_rows = [m.to_row() for m in onchain_data]
    if onchain_rows:
        await _aio.to_thread(sheets.batch_append, "DU_LIEU_ONCHAIN", onchain_rows)
        logger.info(f"Wrote {len(onchain_rows)} rows to DU_LIEU_ONCHAIN")


async def _write_generated_content(
    sheets: object,
    articles: list[dict[str, str]],
) -> None:
    """Write generated articles to NOI_DUNG_DA_TAO (A4)."""
    import asyncio as _aio

    if not articles:
        return

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for article in articles:
        rows.append(
            [
                "",  # ID
                now,
                "daily_report",
                article.get("tier", ""),
                article.get("content", "")[:5000],  # truncate for Sheets cell limit
                "",  # LLM sử dụng
                "pending",
                "",  # Ghi chú
            ]
        )
    await _aio.to_thread(sheets.batch_append, "NOI_DUNG_DA_TAO", rows)
    logger.info(f"Wrote {len(rows)} rows to NOI_DUNG_DA_TAO")


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
        # Schema: ID, Thời gian bắt đầu, Thời gian kết thúc, Thời lượng (giây),
        #         Trạng thái, LLM sử dụng, Lỗi, Ghi chú
        row = [
            "",  # ID — auto-generated or blank
            run_log.get("start_time", ""),
            run_log.get("end_time", ""),
            str(run_log.get("duration_sec", 0)),
            run_log.get("status", ""),
            run_log.get("llm_used", ""),
            "; ".join(run_log.get("errors", [])),
            f"daily | {run_log.get('tiers_delivered', 0)} tiers"
            f" | {run_log.get('delivery_method', '')}",
        ]
        await asyncio.to_thread(sheets.batch_append, "NHAT_KY_PIPELINE", [row])
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


def _write_dashboard_data(
    run_log: dict,
    articles: list[dict[str, str]],
    errors: list[Exception],
) -> None:
    """Write dashboard-data.json to gh-pages/ directory (QĐ7)."""
    import pathlib

    from cic_daily_report.dashboard.data_generator import (
        DashboardData,
        ErrorEntry,
        LastRun,
        TierStatus,
        generate_dashboard_data,
    )

    last_run = LastRun(
        timestamp=run_log.get("start_time", ""),
        status=run_log.get("status", "unknown"),
        pipeline_type="daily",
        duration_seconds=run_log.get("duration_sec", 0),
    )

    tier_delivery = [TierStatus(tier=a.get("tier", ""), status="sent") for a in articles]

    error_history = [
        ErrorEntry(
            timestamp=run_log.get("start_time", ""),
            message=str(e),
            severity="error",
        )
        for e in errors
    ]

    # Try to merge with existing dashboard data
    gh_pages = pathlib.Path("gh-pages")
    gh_pages.mkdir(exist_ok=True)
    data_file = gh_pages / "dashboard-data.json"

    existing_errors: list[ErrorEntry] = []
    if data_file.exists():
        try:
            existing = DashboardData.from_json(data_file.read_text(encoding="utf-8"))
            existing_errors = existing.error_history
        except Exception:
            pass  # Start fresh if can't parse

    from cic_daily_report.dashboard.data_generator import merge_error_history

    merged_errors = merge_error_history(existing_errors, error_history)

    dashboard = generate_dashboard_data(
        last_run=last_run,
        tier_delivery=tier_delivery,
        error_history=merged_errors,
    )

    data_file.write_text(dashboard.to_json(), encoding="utf-8")
    logger.info(f"Dashboard data written to {data_file}")


async def _send_test_confirmation(
    run_log: dict,
    articles: list[dict[str, str]],
    errors: list[Exception],
) -> None:
    """FR54: Send test mode confirmation message to operator via TG."""
    from cic_daily_report.delivery.telegram_bot import TelegramBot

    status = run_log.get("status", "unknown")
    duration = run_log.get("duration_sec", 0)
    tier_count = len(articles)
    error_count = len(errors)

    msg = (
        f"[TEST MODE] Pipeline hoàn tất\n\n"
        f"Trạng thái: {status}\n"
        f"Thời gian: {duration:.0f}s\n"
        f"Số bài: {tier_count}\n"
        f"Lỗi: {error_count}\n"
    )
    if errors:
        msg += "\nLỗi chi tiết:\n" + "\n".join(f"- {e}" for e in errors[:5])

    try:
        bot = TelegramBot()
        await bot.send_message(msg)
    except Exception:
        logger.debug("Test confirmation skipped — TG not configured")


if __name__ == "__main__":
    main()
