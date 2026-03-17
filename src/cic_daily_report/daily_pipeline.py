"""Daily pipeline entry point — orchestrates full daily report generation.

Execution order: Data Collection → Content Generation → NQ05 Filter → Delivery.
Timeout: 40 minutes (NFR1). Partial delivery on timeout/error (NFR7).
"""

from __future__ import annotations

import asyncio
import os
import sys
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

    status = asyncio.run(_run_pipeline())
    if status == "error":
        sys.exit(1)


async def _run_pipeline() -> str:
    """Execute the daily pipeline with timeout and error handling.

    Returns pipeline status: "success", "partial", "timeout", or "error".
    """
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
        delivery_result = await _deliver(articles, errors)
        # C3 fix: detect full delivery failure (0 sent but had messages to send)
        if delivery_result.messages_total > 0 and delivery_result.messages_sent == 0:
            logger.error(
                f"Delivery failed: 0 messages sent out of {delivery_result.messages_total}"
            )
            errors.append(
                Exception(f"Delivery failed: 0/{delivery_result.messages_total} messages sent")
            )
            run_log["status"] = "error"
    except Exception as e:
        logger.error(f"Delivery failed: {e}")
        errors.append(e)
        run_log["status"] = "error"

    # Finalize run log BEFORE test confirmation (so status/duration are accurate)
    elapsed = time.monotonic() - start
    run_log["duration_sec"] = round(elapsed, 1)
    if run_log["status"] == "running":
        run_log["status"] = "success" if not errors else "partial"
    run_log["errors"] = [str(e) for e in errors]
    run_log["tiers_delivered"] = len(articles)

    # FR54: Send test mode confirmation (after run_log finalized)
    if is_test_mode():
        try:
            await _send_test_confirmation(run_log, articles, errors)
        except Exception as e:
            logger.warning(f"Test confirmation failed (non-critical): {e}")

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

    # FR43: Data retention cleanup (run after each daily pipeline)
    try:
        from cic_daily_report.storage.data_retention import run_cleanup
        from cic_daily_report.storage.sheets_client import SheetsClient

        sheets = SheetsClient()
        cleanup = await asyncio.to_thread(run_cleanup, sheets)
        total_removed = sum(cleanup.values())
        if total_removed > 0:
            logger.info(f"Data cleanup: removed {total_removed} old rows — {cleanup}")
    except Exception as e:
        logger.warning(f"Data cleanup failed (non-critical): {e}")

    return run_log["status"]


def _format_onchain_value(metric_name: str, value: float) -> str:
    """Format on-chain metric values for human readability.

    Funding Rate: convert to percentage (e.g. -0.0056%).
    Large numbers: use K/M/B suffixes.
    Small floats: avoid scientific notation.
    """
    name_lower = metric_name.lower()
    if "funding" in name_lower:
        return f"{value * 100:.4f}%"
    if "ratio" in name_lower:
        return f"{value:.4f}"
    if abs(value) >= 1e9:
        return f"{value / 1e9:,.2f}B"
    if abs(value) >= 1e6:
        return f"{value / 1e6:,.2f}M"
    if abs(value) >= 1e3:
        return f"{value:,.2f}"
    if abs(value) < 0.01 and value != 0:
        return f"{value:.6f}"
    return f"{value:.4f}"


async def _execute_stages() -> tuple[list[dict[str, str]], list[Exception]]:
    """Run all pipeline stages: collect → generate → NQ05 filter.

    Returns (articles_as_dicts, non_fatal_errors).
    """
    from cic_daily_report.adapters.llm_adapter import LLMAdapter
    from cic_daily_report.collectors.cryptopanic_client import collect_cryptopanic
    from cic_daily_report.collectors.data_cleaner import clean_articles
    from cic_daily_report.collectors.economic_calendar import collect_economic_calendar
    from cic_daily_report.collectors.market_data import collect_market_data
    from cic_daily_report.collectors.onchain_data import collect_onchain
    from cic_daily_report.collectors.rss_collector import collect_rss
    from cic_daily_report.collectors.sector_data import SectorSnapshot, collect_sector_data
    from cic_daily_report.collectors.telegram_scraper import collect_telegram
    from cic_daily_report.generators.article_generator import (
        GenerationContext,
        generate_tier_articles,
    )
    from cic_daily_report.generators.data_quality import assess_data_quality
    from cic_daily_report.generators.metrics_engine import (
        detect_narratives,
        format_narratives_for_llm,
        interpret_metrics,
    )
    from cic_daily_report.generators.nq05_filter import check_and_fix
    from cic_daily_report.generators.summary_generator import generate_bic_summary
    from cic_daily_report.generators.template_engine import load_templates
    from cic_daily_report.storage.config_loader import ConfigLoader
    from cic_daily_report.storage.sheets_client import SheetsClient

    errors: list[Exception] = []

    # Seed default CAU_HINH config rows on first run (idempotent, non-fatal)
    try:
        await asyncio.to_thread(SheetsClient().seed_default_config)
    except Exception as e:
        logger.warning(f"CAU_HINH seed skipped: {e}")

    # --- Stage 1: Data Collection (parallel, QĐ5) ---
    logger.info("Stage 1: Data Collection")
    results = await asyncio.gather(
        collect_rss(),
        collect_cryptopanic(),
        collect_market_data(),
        collect_onchain(),
        collect_telegram(),
        collect_economic_calendar(),
        collect_sector_data(),
        return_exceptions=True,
    )

    rss_articles = results[0] if not isinstance(results[0], Exception) else []
    crypto_articles = results[1] if not isinstance(results[1], Exception) else []
    market_data = results[2] if not isinstance(results[2], Exception) else []
    onchain_data = results[3] if not isinstance(results[3], Exception) else []
    tg_messages = results[4] if not isinstance(results[4], Exception) else []
    from cic_daily_report.collectors.economic_calendar import CalendarResult

    econ_calendar = results[5] if not isinstance(results[5], Exception) else CalendarResult()
    sector_snapshot: SectorSnapshot = (
        results[6] if not isinstance(results[6], Exception) else SectorSnapshot([], 0.0, [])
    )

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
                "source_type": getattr(a, "source_type", "news"),
                "og_image": getattr(a, "og_image", None),
            }
        )
    for a in crypto_articles:
        all_news.append(
            {
                "title": a.title,
                "url": a.url,
                "source_name": a.source_name,
                "summary": a.summary,
                "news_type": getattr(a, "news_type", "crypto"),
                "og_image": getattr(a, "og_image", None),
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

    # Split news into crypto vs macro categories for LLM context
    crypto_items = []
    macro_items = []
    for a in cleaned_news[:30]:
        line = f"- {a.get('title', '')} ({a.get('source_name', '')})"
        url = a.get("url", "")
        if url:
            line += f"\n  Link: {url}"
        summary = a.get("summary", "")
        if summary:
            line += f"\n  Tóm tắt: {summary[:300]}"
        if a.get("conflict"):
            line += "\n  ⚠️ [FR12] Nhiều nguồn đưa tin khác nhau — cần đối chiếu cẩn thận"
        if a.get("news_type") == "macro":
            macro_items.append(line)
        else:
            crypto_items.append(line)

    news_text = ""
    if crypto_items:
        news_text += "=== TIN CRYPTO ===\n" + "\n".join(crypto_items)
    if macro_items:
        news_text += "\n\n=== TIN VĨ MÔ ===\n" + "\n".join(macro_items)
    market_items = []
    for p in market_data[:20]:
        line = f"- {p.symbol}: ${p.price:,.2f} ({p.change_24h:+.1f}%)"
        if p.volume_24h > 0:
            line += f" | Vol: ${p.volume_24h / 1e6:,.1f}M"
        if p.market_cap > 0:
            line += f" | MCap: ${p.market_cap / 1e9:,.1f}B"
        market_items.append(line)
    market_text = "\n".join(market_items)
    onchain_text = "\n".join(
        f"- {m.metric_name}: {_format_onchain_value(m.metric_name, m.value)} ({m.source})"
        for m in onchain_data
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
            key_metrics["Funding Rate"] = f"{m.value * 100:.4f}%"

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

    # v0.21.0: Data quality assessment (Phase 3b)
    quality = assess_data_quality(
        news_count=len(cleaned_news),
        market_data=market_data,
        onchain_data=onchain_data,
        has_sector_data=bool(sector_snapshot.sectors or sector_snapshot.defi_total_tvl > 0),
        has_econ_calendar=bool(econ_calendar.events if hasattr(econ_calendar, "events") else False),
    )
    if quality.is_degraded:
        logger.warning(f"DATA QUALITY DEGRADED: {quality.grade} ({quality.score}/100)")
        for issue in quality.issues:
            logger.warning(f"  → {issue}")

    logger.info(
        f"Collection done: {len(cleaned_news)} news, "
        f"{len(market_data)} market, {len(onchain_data)} onchain "
        f"| Quality: {quality.grade} ({quality.score}/100)"
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

    # Pre-flight validation: templates + coins (FR13, QĐ8)
    expected_tiers = {"L1", "L2", "L3", "L4", "L5"}
    loaded_tiers = set(templates.keys())
    missing_tiers = expected_tiers - loaded_tiers
    if missing_tiers:
        msg = f"Templates missing for tiers: {sorted(missing_tiers)}"
        logger.error(msg)
        errors.append(Exception(msg))
    if not templates:
        msg = "No templates loaded — cannot generate articles"
        logger.error(msg)
        errors.append(Exception(msg))
        return [], errors
    for tier in sorted(loaded_tiers):
        coins = coin_lists.get(tier, [])
        if not coins:
            logger.warning(f"No coins configured for tier {tier}")

    # v0.21.0: Metrics Engine — pre-computed data interpretation (Phase 1a/1b)
    metrics_interp = interpret_metrics(market_data, onchain_data, key_metrics)
    logger.info(f"Metrics Engine: regime={metrics_interp.regime.regime}")

    # v0.21.0: Narrative Detection (Phase 1d)
    narratives = detect_narratives(cleaned_news)
    narratives_text = format_narratives_for_llm(narratives)
    if narratives:
        logger.info(f"Narratives detected: {[n.name for n in narratives[:5]]}")

    # v0.21.0: Format sector data for LLM context (Phase 2)
    sector_text = sector_snapshot.format_for_llm()

    # Build per-tier analysis context — each tier answers a DIFFERENT question.
    # Members see ALL lower tiers (L5 sees L4→L1), so content MUST NOT repeat.
    tier_context: dict[str, str] = {}
    tier_context["L1"] = (
        "Tier L1 — 'Sáng nay thị trường crypto thế nào?'\n"
        "ĐỐI TƯỢNG: Người mới, đọc 30 giây hiểu xong.\n"
        "GIỌNG VĂN: Thân thiện, dễ hiểu, như kể cho bạn bè.\n\n"
        "TRẢ LỜI 3 CÂU HỎI NÀY (dùng data ở trên):\n"
        "1. Sáng nay thị trường có gì KHÁC? "
        "(dùng Market Regime từ Metrics Engine)\n"
        "2. BTC và ETH đang ở đâu? Tăng hay giảm bao nhiêu?\n"
        "3. Tin tức quan trọng nhất mà người mới CẦN BIẾT? "
        "(tóm 1-2 tin, giải thích TẠI SAO)\n\n"
        "VÍ DỤ OUTPUT TỐT (tham khảo style, KHÔNG copy):\n"
        "\"Thị trường crypto sáng nay khởi sắc — trạng thái "
        "PHỤC HỒI. BTC tăng **2.8%** lên $74,834, ETH **+6.2%**. "
        "F&G=28 (Fear) nhưng đã cải thiện. Tin nổi bật: "
        "Hàn Quốc phạt Bithumb $24M — giám sát mạnh tay hơn.\"\n\n"
        "KHÔNG: thuật ngữ phức tạp (funding rate, OI...) | on-chain/macro | quá 2 coins\n"
    )
    tier_context["L2"] = (
        "Tier L2 — 'Coins và sectors nào đáng chú ý hôm nay?'\n"
        "ĐỐI TƯỢNG: Có altcoin, muốn biết tổng quan.\n"
        "⚠️ Member ĐÃ ĐỌC L1 — KHÔNG lặp BTC/ETH/F&G.\n\n"
        "TRẢ LỜI 4 CÂU HỎI NÀY:\n"
        "1. Sector nào DẪN ĐẦU hôm nay? (dùng CoinGecko sector data: market_cap_change_24h)\n"
        "2. Coins nào BIẾN ĐỘNG MẠNH nhất (>3%)? TẠI SAO? (nối với narrative nếu có)\n"
        "3. BTC Dominance + Altcoin Season → tiền đang chảy vào đâu?\n"
        "4. USDT/VND rate hôm nay có gì đặc biệt?\n\n"
        "YÊU CẦU: Nhóm coins theo SECTOR (DeFi, L1, L2, AI, Meme, RWA...). "
        "Nhắc tối thiểu 10/19 coins trong danh sách.\n\n"
        "VÍ DỤ OUTPUT TỐT:\n"
        "\"📈 Sector dẫn đầu: Meme (+5.5%), DeFi (+3.4%), Layer 1 (+3.5%). "
        "Đáng chú ý: XRP bứt phá **+8.1%** với volume $3.7B — narrative "
        "XRP ETF đang nóng lại. Nhóm AI (FET, RENDER) tăng nhẹ 1-2%. "
        "BTC Dominance 56.8% — altcoins đang lấy lại momentum.\"\n\n"
        "KHÔNG: lặp L1 | on-chain/derivatives | bịa support/resistance\n"
    )
    tier_context["L3"] = (
        "Tier L3 — 'TẠI SAO thị trường diễn biến như vậy?'\n"
        "ĐỐI TƯỢNG: Trader có kinh nghiệm, muốn hiểu nguyên nhân.\n"
        "⚠️ Member ĐÃ ĐỌC L1+L2 — KHÔNG lặp giá coin.\n\n"
        "TRẢ LỜI 3 CÂU HỎI NÀY:\n"
        "1. DXY, Gold, lịch kinh tế → TÁC ĐỘNG thế nào đến crypto? (chuỗi nhân-quả)\n"
        "2. Derivatives đang nói gì? (dùng Metrics Engine: Funding Rate, OI đã tính sẵn)\n"
        "   → Diễn giải bằng ngôn ngữ tự nhiên, NỐI với macro. KHÔNG copy Metrics Engine.\n"
        "3. Tổng hợp: macro + derivatives + sentiment → câu chuyện LOGIC là gì?\n\n"
        "VÍ DỤ OUTPUT TỐT:\n"
        "\"DXY giảm về **99.87** — USD yếu đi tạo điều kiện thuận lợi cho crypto. "
        "Cùng lúc, Funding Rate **+0.004%** (gần trung tính) cho thấy thị trường phái sinh "
        "không quá lạc quan dù giá đang hồi. Đây là dấu hiệu phục hồi CÓ KIỀM CHẾ — "
        "khác với đợt pump tháng trước khi FR lên 0.05%. "
        "Sự kiện quan trọng: Fed công bố lãi suất ngày 19/03, "
        "dự báo giữ 3.75% — nếu đúng, DXY có thể tiếp tục giảm.\"\n\n"
        "KHÔNG: giá coin (đã ở L2) | rủi ro/scenario (để L4-L5) | bịa MVRV/SOPR\n"
    )
    tier_context["L4"] = (
        "Tier L4 — 'Rủi ro LỚN NHẤT hiện tại là gì?'\n"
        "ĐỐI TƯỢNG: Trader có position, cần đánh giá rủi ro.\n"
        "GIỌNG VĂN: Nghiêm túc, cảnh báo cụ thể.\n"
        "⚠️ Member ĐÃ ĐỌC L1→L3 — KHÔNG lặp macro/on-chain.\n\n"
        "TRẢ LỜI 4 CÂU HỎI NÀY:\n"
        "1. Chỉ số nào đang MÂU THUẪN nhau? (dùng cross-signal từ Metrics Engine)\n"
        "   → Giải thích: mâu thuẫn đó = rủi ro GÌ cho trader?\n"
        "2. Sector nào đang YẾU NHẤT? (CoinGecko market_cap_change_24h âm, DefiLlama TVL giảm)\n"
        "3. Sự kiện vĩ mô nào SẮP TỚI có thể gây volatility? (từ lịch kinh tế)\n"
        "4. Red flags: chỉ số nào ở vùng NGUY HIỂM?\n\n"
        "VÍ DỤ OUTPUT TỐT:\n"
        "\"⚠️ **Tín hiệu mâu thuẫn**: Giá BTC +2.8% nhưng F&G vẫn 28 (Fear) — "
        "price action tăng mà sentiment KHÔNG theo. Lần gần nhất xảy ra tình huống này "
        "(01/2024) BTC sideway 2 tuần rồi giảm 8%. "
        "Rủi ro lớn nhất tuần này: Fed meeting 19/03 — nếu bất ngờ hawkish, "
        "DXY tăng mạnh sẽ tạo áp lực bán đột ngột.\"\n\n"
        "KHÔNG: lặp L1-L3 | % phân bổ (NQ05) | mua/bán | bịa liquidation/whale data\n"
    )
    tier_context["L5"] = (
        "Tier L5 — 'Bức tranh tổng thể và các kịch bản?'\n"
        "ĐỐI TƯỢNG: Master members, tư duy chiến lược.\n"
        "GIỌNG VĂN: Formal, framework-based.\n"
        "⚠️ Member ĐÃ ĐỌC L1→L4 — CHỈ viết nội dung MỚI.\n\n"
        "TRẢ LỜI 4 CÂU HỎI NÀY:\n"
        "1. SCENARIO ANALYSIS (dùng Market Regime + confidence từ Metrics Engine):\n"
        "   - Base case: regime hiện tại → kỳ vọng gì?\n"
        "   - Bullish case: nếu [điều kiện cụ thể] → scenario?\n"
        "   - Bearish case: nếu [rủi ro từ L4] → hậu quả?\n"
        "2. Dòng tiền đang CHẢY ĐI ĐÂU? (CoinGecko sectors + DefiLlama TVL + narratives)\n"
        "3. Tín hiệu TỔNG HỢP: macro + derivatives + sentiment đang ĐỒNG THUẬN hay MÂU THUẪN?\n"
        "   (dùng cross_signal_summary từ Metrics Engine)\n"
        "4. Timeline: sự kiện nào trong 7 ngày tới có thể THAY ĐỔI bức tranh?\n\n"
        "VÍ DỤ OUTPUT TỐT:\n"
        "\"🔍 **Base case (Recovery, medium confidence)**: BTC sideway $73K-$77K chờ FOMC. "
        "DXY yếu + FR trung tính ủng hộ kịch bản này. "
        "**Bullish trigger**: Fed dovish 19/03 + DXY <99 → BTC test $80K. "
        "**Bearish trigger**: Fed hawkish + DXY >101 → risk-off, BTC về $70K. "
        "Dòng tiền: DeFi TVL $100.8B ổn định, Meme sector dẫn đầu (+5.5%) — "
        "tiền đang chảy vào speculative assets, tín hiệu risk-on ngắn hạn.\"\n\n"
        "KHÔNG: lặp L1-L4 | bịa correlation/MVRV/whale | mua/bán/phân bổ (NQ05)\n"
    )

    # Format economic calendar events for LLM context (FR60)
    economic_events_text = econ_calendar.format_for_llm()

    # v0.19.0: Load recent breaking news context for pipeline integration
    recent_breaking_text = await _load_recent_breaking_context()

    context = GenerationContext(
        coin_lists=coin_lists,
        market_data=market_text,
        news_summary=news_text,
        onchain_data=onchain_text,
        key_metrics=key_metrics,
        tier_context=tier_context,
        interpretation_notes="",  # v0.21.0: replaced by metrics_interpretation per tier
        economic_events=economic_events_text,
        recent_breaking=recent_breaking_text,
        metrics_interpretation=metrics_interp,  # v0.21.0: Metrics Engine
        narratives_text=narratives_text,  # v0.21.0: Narrative Detection
        sector_data=sector_text,  # v0.21.0: Sector + DeFi data (Phase 2)
        data_quality_notes=quality.format_for_llm(),  # v0.21.0: Quality warnings
    )

    generated = []
    try:
        generated = await generate_tier_articles(llm, templates, context)
    except Exception as e:
        logger.error(f"Article generation failed: {e}")
        errors.append(e)

    # Post-generation validation (FR13, FR14)
    generated_tiers = {a.tier for a in generated}
    missing_gen = expected_tiers - generated_tiers
    if missing_gen:
        msg = f"Articles not generated for tiers: {sorted(missing_gen)}"
        logger.error(msg)
        errors.append(Exception(msg))
    for article in generated:
        # FR14 dual-layer check: Tóm lược marker should exist
        content_lower = article.content.lower()
        has_summary = (
            "tóm lược" in content_lower or "tl;dr" in content_lower or "tl; dr" in content_lower
        )
        if not has_summary:
            logger.warning(
                f"[{article.tier}] Missing Tóm lược section — FR14 dual-layer may be incomplete"
            )

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

    # Build source URL mapping and image list from cleaned news
    source_url_map: dict[str, str] = {}
    image_urls: list[str] = []
    for a in cleaned_news[:30]:
        name = a.get("source_name", "")
        url = a.get("url", "")
        if name and url:
            source_url_map[name] = url
        og = a.get("og_image")
        if og and a.get("source_type") == "research" and len(image_urls) < 3:
            image_urls.append(og)

    source_urls = [{"title": name, "url": url} for name, url in source_url_map.items()]

    articles_out: list[dict[str, str]] = []
    for article in generated:
        filtered = check_and_fix(article.content)
        content = _append_source_references(filtered.content, source_url_map)
        articles_out.append(
            {
                "tier": article.tier,
                "content": content,
                "source_urls": source_urls,
                "image_urls": image_urls,
            }
        )

    if summary:
        filtered = check_and_fix(summary.content)
        content = _append_source_references(filtered.content, source_url_map)
        articles_out.append(
            {
                "tier": "Summary",
                "content": content,
                "source_urls": source_urls,
                "image_urls": image_urls,
            }
        )

    # --- Write generated content to Sheets (A4) ---
    try:
        sheets_w2 = SheetsClient()
        await _write_generated_content(sheets_w2, articles_out)
    except Exception as e:
        logger.warning(f"Generated content write failed (non-critical): {e}")
        errors.append(e)

    logger.info(f"Pipeline stages complete: {len(articles_out)} articles ready")
    return articles_out, errors


async def _load_recent_breaking_context() -> str:
    """v0.19.0: Load recent breaking events (24h) from BREAKING_LOG for daily context.

    Returns formatted text for LLM prompt, or empty string if no events.
    """
    try:
        from cic_daily_report.storage.sheets_client import SheetsClient

        sheets = SheetsClient()
        rows = await asyncio.to_thread(sheets.read_all, "BREAKING_LOG")
        if not rows:
            return ""

        now = datetime.now(timezone.utc)
        recent_lines = []
        for row in rows:
            detected_at = str(row.get("Thời gian", ""))
            title = str(row.get("Tiêu đề", ""))
            source = str(row.get("Nguồn", ""))
            severity = str(row.get("Mức độ", ""))
            if not detected_at or not title:
                continue
            try:
                dt = datetime.fromisoformat(detected_at)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                age = now - dt
                if age.total_seconds() <= 86400:  # 24 hours
                    recent_lines.append(f"- [{severity}] {title} ({source})")
            except (ValueError, TypeError):
                continue

        if not recent_lines:
            return ""

        logger.info(f"Loaded {len(recent_lines)} recent breaking events for daily context")
        return "\n".join(recent_lines)

    except Exception as e:
        logger.warning(f"Breaking context load failed (non-critical): {e}")
        return ""


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
                article.get("content", "")[:8000],  # truncate for Sheets cell limit
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
) -> object:
    """Deliver content via DeliveryManager (TG → email backup).

    Returns DeliveryResult so caller can detect full delivery failure (C3 fix).
    """
    from cic_daily_report.delivery.delivery_manager import DeliveryManager
    from cic_daily_report.delivery.email_backup import EmailBackup
    from cic_daily_report.delivery.telegram_bot import TelegramBot
    from cic_daily_report.storage.config_loader import ConfigLoader
    from cic_daily_report.storage.sheets_client import SheetsClient

    # Read email recipients from CAU_HINH (editable in GSheet) — fallback to env var
    email_recipients: list[str] | None = None
    try:
        cfg = ConfigLoader(SheetsClient())
        recipients = await asyncio.to_thread(cfg.get_email_recipients)
        email_recipients = recipients or None
    except Exception as e:
        logger.warning(f"Could not read email_recipients from CAU_HINH: {e}")

    tg = TelegramBot()
    email = EmailBackup(recipients=email_recipients)
    manager = DeliveryManager(telegram_bot=tg, email_backup=email)

    pipeline_errors = errors if errors else None
    result = await manager.deliver(articles, pipeline_errors)

    logger.info(
        f"Delivery: {result.method}, "
        f"{result.messages_sent}/{result.messages_total} sent, "
        f"status: {result.status_line()}"
    )
    return result


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


def _append_source_references(content: str, source_url_map: dict[str, str]) -> str:
    """Append plain-text source reference footer (FR19 + FR30 copy-paste ready).

    Instead of injecting <a href> HTML (which breaks copy-paste to BIC Group),
    appends a "Nguồn tham khảo" section with source names and URLs.
    Only includes sources whose names actually appear in the content.
    """
    import re as _re

    mentioned: list[tuple[str, str]] = []
    for source_name, url in source_url_map.items():
        if not source_name or not url:
            continue
        pattern = _re.compile(
            r"(?<![a-zA-Z0-9])" + _re.escape(source_name) + r"(?![a-zA-Z0-9])",
            _re.IGNORECASE,
        )
        if pattern.search(content):
            mentioned.append((source_name, url))

    if not mentioned:
        return content

    footer = "\n\n📎 Nguồn tham khảo:\n"
    for name, url in mentioned[:5]:  # Limit to 5 sources to keep it concise
        footer += f"• {name}: {url}\n"
    return content + footer


if __name__ == "__main__":
    main()
