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
        articles, errors, llm_used, research_wc = await asyncio.wait_for(
            _execute_stages(),
            timeout=PIPELINE_TIMEOUT_SEC,
        )
        run_log["llm_used"] = llm_used
        run_log["research_word_count"] = research_wc
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


async def _execute_stages() -> tuple[list[dict[str, str]], list[Exception], str, int]:
    """Run all pipeline stages: collect → generate → NQ05 filter.

    Returns (articles_as_dicts, non_fatal_errors, llm_models_used, research_word_count).
    """
    from cic_daily_report.adapters.llm_adapter import LLMAdapter
    from cic_daily_report.collectors.cryptopanic_client import collect_cryptopanic
    from cic_daily_report.collectors.data_cleaner import clean_articles
    from cic_daily_report.collectors.economic_calendar import collect_economic_calendar
    from cic_daily_report.collectors.market_data import collect_market_data
    from cic_daily_report.collectors.onchain_data import collect_onchain
    from cic_daily_report.collectors.research_data import ResearchData, collect_research_data
    from cic_daily_report.collectors.rss_collector import collect_rss
    from cic_daily_report.collectors.sector_data import SectorSnapshot, collect_sector_data
    from cic_daily_report.collectors.telegram_scraper import collect_telegram
    from cic_daily_report.collectors.whale_alert import WhaleAlertSummary, collect_whale_alerts
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
    from cic_daily_report.generators.research_generator import generate_research_article
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
        collect_whale_alerts(),
        collect_research_data(),
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
    whale_data: WhaleAlertSummary = (
        results[7] if not isinstance(results[7], Exception) else WhaleAlertSummary()
    )
    research_data: ResearchData = (
        results[8] if not isinstance(results[8], Exception) else ResearchData()
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
                "full_text": getattr(a, "full_text", ""),
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

    # Data quality gate: minimum viable data check
    min_news = 5
    has_market = bool(market_data)
    if len(cleaned_news) < min_news and not has_market:
        logger.error(f"Data quality FAIL: {len(cleaned_news)} news, market={has_market}")
        raise RuntimeError(
            f"Insufficient data for report: {len(cleaned_news)} news articles "
            f"(min {min_news}), market_data={'yes' if has_market else 'no'}"
        )

    # Split news into crypto vs macro categories for LLM context
    crypto_items = []
    macro_items = []
    for a in cleaned_news[:30]:
        line = f"- {a.get('title', '')} ({a.get('source_name', '')})"
        url = a.get("url", "")
        if url:
            line += f"\n  Link: {url}"
        text_for_llm = a.get("full_text", "") or a.get("summary", "")
        if text_for_llm:
            line += f"\n  Nội dung: {text_for_llm[:800]}"
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
        has_sector_data=bool(sector_snapshot.sectors or (sector_snapshot.defi_total_tvl or 0) > 0),
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
    #
    # v0.26.0: Rewritten with INVESTOR persona (not trader) matching CIC philosophy.
    # CIC members are long-term strategic investors using ADCA strategy, NOT traders.
    # Each Level corresponds to a specific member group with different asset scope
    # and investment capital. Content must be relevant to their investment horizon.
    tier_context: dict[str, str] = {}
    tier_context["L1"] = (
        "Tier L1 — 'Thị trường hôm nay có gì BẤT THƯỜNG không?'\n"
        "ĐỐI TƯỢNG: Nhà đầu tư MỚI, chỉ hold BTC & ETH, vốn 10-30 triệu. "
        "Họ bận rộn, chỉ đọc 30 giây. Họ dùng chiến lược tích lũy dài hạn (ADCA), "
        "KHÔNG phải trader lướt sóng.\n"
        "GIỌNG VĂN: Thân thiện, dễ hiểu, như kể cho bạn bè.\n\n"
        "TRẢ LỜI 3 CÂU HỎI NÀY (dùng data ở trên):\n"
        "1. Hôm nay có gì KHÁC BIỆT hay BẤT THƯỜNG không? "
        "(dùng Market Regime từ Metrics Engine — nếu không có gì đặc biệt, nói rõ)\n"
        "2. BTC và ETH đang ở đâu? Biến động này có ý nghĩa gì cho người đang "
        "TÍCH LŨY dài hạn? (VD: giảm nhẹ 1-2% = bình thường, không cần lo)\n"
        "3. MỘT tin tức duy nhất quan trọng nhất hôm nay — giải thích TẠI SAO "
        "người hold BTC/ETH nên biết tin này\n\n"
        "VÍ DỤ OUTPUT TỐT (tham khảo style, KHÔNG copy):\n"
        '"Thị trường hôm nay không có gì bất thường — BTC giảm nhẹ **1.4%** về '
        "$70,524, ETH giảm **3.6%**. Đây là mức dao động bình thường trong giai đoạn "
        "tích lũy. Điều đáng chú ý: F&G=11 (hoảng loạn cực độ) — lịch sử cho thấy "
        "đây thường là vùng mà nhà đầu tư dài hạn tích lũy được giá tốt. "
        "Tin nổi bật: Fed giữ nguyên lãi suất — "
        'môi trường lãi suất ổn định hỗ trợ tài sản rủi ro."\n\n'
        "KHÔNG: thuật ngữ phức tạp (funding rate, OI...) | on-chain/macro | quá 2 coins | "
        "gợi ý mua/bán\n"
    )
    tier_context["L2"] = (
        "Tier L2 — 'Các bluechip đáng chú ý và dòng tiền đang chảy đi đâu?'\n"
        "ĐỐI TƯỢNG: Nhà đầu tư muốn đa dạng hóa sang bluechip, vốn 30-60 triệu. "
        "Họ hold BTC/ETH + các mã lớn (SOL, BNB, XRP, ADA, DOT, LINK...). "
        "Chiến lược: phân bổ danh mục theo mức rủi ro.\n"
        "⚠️ Member ĐÃ ĐỌC L1 — KHÔNG lặp BTC/ETH/F&G.\n\n"
        "TRẢ LỜI 4 CÂU HỎI NÀY:\n"
        "1. Sector nào DẪN ĐẦU hôm nay? (dùng CoinGecko sector data: market_cap_change_24h)\n"
        "   → Nối với xu hướng: sector này dẫn đầu vì LÝ DO gì?\n"
        "2. Trong danh sách coins theo dõi, coin nào BIẾN ĐỘNG MẠNH nhất (>3%)? "
        "TẠI SAO? (nối với narrative nếu có)\n"
        "3. BTC Dominance + Altcoin Season → tiền đang chảy VÀO hay RA khỏi altcoin? "
        "Xu hướng này thuận lợi hay bất lợi cho người đang giữ danh mục bluechip?\n"
        "4. USDT/VND rate hôm nay có gì đặc biệt?\n\n"
        "YÊU CẦU: Nhóm coins theo SECTOR (DeFi, L1, L2, AI, Meme, RWA...). "
        "Nhắc tối thiểu 10/19 coins trong danh sách.\n\n"
        "VÍ DỤ OUTPUT TỐT:\n"
        '"📈 Sector dẫn đầu: Layer 1 (+3.5%) — dòng tiền quay lại các blockchain nền tảng '
        "sau giai đoạn ưu tiên BTC. Đáng chú ý: XRP bứt phá **+8.1%** (narrative ETF đang nóng), "
        "SOL **+3.2%** nhờ TVL DeFi tăng. BTC Dominance 56.8% — altcoins đang dần lấy lại "
        'momentum, có lợi cho danh mục đa dạng hóa."\n\n'
        "KHÔNG: lặp L1 | on-chain/derivatives | bịa support/resistance\n"
    )
    tier_context["L3"] = (
        "Tier L3 — 'TẠI SAO thị trường di chuyển thế này? Nguyên nhân gốc rễ?'\n"
        "ĐỐI TƯỢNG: Nhà đầu tư KINH NGHIỆM, danh mục mid-cap (>50 mã), vốn 60-150 triệu. "
        "Họ cần hiểu nguyên nhân sâu xa, không chỉ biết giá lên/xuống. "
        "Họ chấp nhận rủi ro cao hơn, cần thông tin để đánh giá sector nào đáng theo dõi.\n"
        "⚠️ Member ĐÃ ĐỌC L1+L2 — KHÔNG lặp giá coin, KHÔNG lặp sector đã nêu ở L2.\n\n"
        "TRẢ LỜI 3 CÂU HỎI NÀY:\n"
        "1. CHUỖI NHÂN-QUẢ: DXY → USD → Gold → Crypto — mối liên hệ hôm nay là gì? "
        "(dùng data macro thực tế, nối thành câu chuyện logic)\n"
        "2. Derivatives đang kể câu chuyện gì? (dùng Metrics Engine: Funding Rate, OI) "
        "→ Diễn giải: dân chuyên nghiệp (derivatives) đang nghĩ KHÁC hay GIỐNG retail (F&G)? "
        "Nếu KHÁC → đây là mâu thuẫn đáng chú ý.\n"
        "3. Tổng hợp: macro + derivatives + sentiment → câu chuyện LOGIC nhất quán là gì? "
        "Nếu các tín hiệu mâu thuẫn nhau, chỉ rõ mâu thuẫn đó.\n\n"
        "VÍ DỤ OUTPUT TỐT:\n"
        '"DXY = 99.4 (USD yếu) — bình thường đây là tín hiệu tích cực cho crypto vì dòng tiền '
        "tìm tài sản thay thế. NHƯNG F&G = 11 (hoảng loạn cực độ) cho thấy retail đang bán tháo, "
        "trong khi Funding Rate = 0.06% (dương) nghĩa là dân derivatives VẪN đang đặt cược tăng. "
        "Mâu thuẫn này cho thấy: retail hoảng loạn, nhưng dân chuyên nghiệp chưa từ bỏ — "
        "đây thường là đặc điểm của giai đoạn tích lũy cuối cùng "
        'trước khi thị trường phục hồi."\n\n'
        "KHÔNG: giá coin (đã ở L2) | rủi ro/scenario (để L4-L5) | bịa MVRV/SOPR\n"
    )
    tier_context["L4"] = (
        "Tier L4 — 'Rủi ro nào cần chú ý cho danh mục DeFi/hạ tầng?'\n"
        "ĐỐI TƯỢNG: Nhà đầu tư CHUYÊN SÂU DeFi & hạ tầng, vốn 150-300 triệu. "
        "Họ hold >100 mã bao gồm AAVE, UNI, CRV, GMX, PENDLE, LDO, ENS... "
        "Họ cần đánh giá rủi ro CỤ THỂ cho các sector DeFi, L2, AI, Gaming.\n"
        "GIỌNG VĂN: Nghiêm túc, cảnh báo cụ thể, data-driven.\n"
        "⚠️ Member ĐÃ ĐỌC L1→L3 — KHÔNG lặp macro/on-chain đã phân tích.\n\n"
        "TRẢ LỜI 4 CÂU HỎI NÀY:\n"
        "1. Chỉ số nào đang MÂU THUẪN nhau? (dùng cross-signal từ Metrics Engine)\n"
        "   → Giải thích: mâu thuẫn đó = rủi ro GÌ cho người đang giữ danh mục DeFi/hạ tầng?\n"
        "2. Sector nào đang YẾU NHẤT? Sector nào đang MẠNH NHẤT? "
        "(CoinGecko market_cap_change + DefiLlama TVL)\n"
        "   → Dòng tiền đang ROTATE từ đâu sang đâu trong hệ sinh thái DeFi?\n"
        "3. Sự kiện vĩ mô nào SẮP TỚI có thể gây volatility? (từ lịch kinh tế)\n"
        "   → Nếu kết quả bất ngờ, sector nào bị ảnh hưởng NHIỀU NHẤT?\n"
        "4. Red flags: chỉ số nào ở vùng NGUY HIỂM? "
        "Funding Rate cực đoan + F&G cực đoan cùng lúc = tín hiệu gì?\n\n"
        "VÍ DỤ OUTPUT TỐT:\n"
        '"⚠️ **Tín hiệu mâu thuẫn**: F&G=11 (retail hoảng loạn) vs Funding Rate=0.06% '
        "(derivatives vẫn lạc quan) — nếu giá giảm thêm, rủi ro cascade liquidation ở "
        "derivatives sẽ kéo theo token DeFi giảm mạnh hơn (DeFi sector đã -2.3% hôm nay). "
        "Sector yếu nhất: DeFi (TVL giảm, market cap -2.3%). "
        "Sector mạnh nhất: AI & Big Data (+1.1%). "
        "Dòng tiền đang rotate từ DeFi truyền thống sang AI-related tokens. "
        "Sự kiện sắp tới: PPI report — nếu PPI cao hơn dự báo "
        '→ DXY tăng → áp lực bán DeFi tokens."\n\n'
        "KHÔNG: lặp L1-L3 | % phân bổ (NQ05) | mua/bán | bịa liquidation/whale data\n"
    )
    tier_context["L5"] = (
        "Tier L5 — 'Bức tranh tổng thể: chúng ta đang ở đâu trong chu kỳ?'\n"
        "ĐỐI TƯỢNG: MASTER INVESTOR, vốn >300 triệu, danh mục TOÀN BỘ thị trường "
        "(bao gồm cả mã đầu cơ cao). Họ cần tầm nhìn CHIẾN LƯỢC dài hạn — "
        "không phải giá ngày hôm nay mà là XU HƯỚNG tuần/tháng. "
        "Họ hiểu mô hình 4 mùa (Đông-Xuân-Hè-Thu) và cần biết tín hiệu để "
        "quyết định chiến lược tích lũy hay chốt lời.\n"
        "GIỌNG VĂN: Formal, framework-based, strategic thinking.\n"
        "⚠️ Member ĐÃ ĐỌC L1→L4 — CHỈ viết nội dung MỚI, tầm nhìn RỘNG hơn.\n\n"
        "TRẢ LỜI 4 CÂU HỎI NÀY:\n"
        "1. SCENARIO ANALYSIS (dùng Market Regime + confidence + tất cả signals):\n"
        "   - Base case: regime hiện tại + tín hiệu chính → kỳ vọng 2-4 tuần tới?\n"
        "   - Bullish trigger: điều kiện CỤ THỂ nào (sự kiện, ngưỡng giá, chỉ số) "
        "sẽ xác nhận chuyển sang giai đoạn tích cực?\n"
        "   - Bearish trigger: điều kiện nào sẽ xác nhận xu hướng giảm sâu hơn?\n"
        "2. Dòng tiền đang ROTATE đi đâu? (CoinGecko sectors + DefiLlama TVL + narratives)\n"
        "   → Sector nào đang hút tiền, sector nào đang mất tiền? Xu hướng này "
        "phù hợp với giai đoạn nào trong chu kỳ thị trường?\n"
        "3. Tín hiệu TỔNG HỢP: tất cả chỉ số đang ĐỒNG THUẬN hay MÂU THUẪN?\n"
        "   (dùng cross_signal_summary từ Metrics Engine)\n"
        "   → Nếu đồng thuận: mức độ tin cậy? Nếu mâu thuẫn: ai đúng, ai sai?\n"
        "4. Timeline: sự kiện nào trong 7 ngày tới có thể THAY ĐỔI bức tranh? "
        "Nếu không có sự kiện lớn, nói rõ 'tuần tới yên tĩnh'.\n\n"
        "VÍ DỤ OUTPUT TỐT:\n"
        '"🔍 **Base case (Suy giảm, tin cậy trung bình)**: Thị trường đang trong giai đoạn '
        "điều chỉnh — F&G=11 + BTC -1.4% + DeFi -2.3%. Tuy nhiên, DXY yếu (99.4) + "
        "Funding Rate dương cho thấy đây chưa phải capitulation. Dòng tiền đang rotate "
        "từ DeFi sang AI & Big Data — phù hợp với xu hướng narrative mới. "
        "**Bullish trigger**: F&G vượt 25 + BTC giữ trên $68K + volume tăng. "
        "**Bearish trigger**: BTC mất $65K + DXY vượt 102. "
        'Tuần tới: PPI report là sự kiện chính — kết quả sẽ ảnh hưởng kỳ vọng lãi suất."\n\n'
        "KHÔNG: lặp L1-L4 | bịa correlation/MVRV/whale | mua/bán/phân bổ (NQ05)\n"
    )

    # Format economic calendar events for LLM context (FR60)
    economic_events_text = econ_calendar.format_for_llm()

    # v0.24.0: Whale Alert data for LLM context
    whale_text = whale_data.format_for_llm()
    if whale_data.total_count > 0:
        logger.info(f"Whale data: {whale_data.total_count} transactions for LLM context")

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
        whale_data=whale_text,  # v0.24.0: Whale Alert transactions
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

    # Post-generation: cross-tier repetition check (log only)
    if len(generated) >= 3:
        _check_cross_tier_repetition(generated)

    # Generate BIC Chat summary (FR15, v0.24.0: full data context)
    summary = None
    if generated:
        try:
            summary = await generate_bic_summary(
                llm=llm,
                articles=generated,
                key_metrics=key_metrics,
                cleaned_news=cleaned_news,
                market_data=market_data,
                onchain_data=onchain_data,
                sector_snapshot=sector_snapshot,
                econ_calendar=econ_calendar,
                metrics_interp=metrics_interp,
                narratives_text=narratives_text,
                whale_data=whale_data,
            )
        except Exception as e:
            logger.error(f"Summary generation failed: {e}")
            errors.append(e)

    # Generate CIC Market Insight research article (P2-A: BIC Group L1)
    research_article = None
    if generated:
        try:
            research_article = await generate_research_article(
                llm=llm,
                context=context,
                research_data=research_data,
            )
            if research_article:
                logger.info(
                    f"Research article: {research_article.word_count} words "
                    f"via {research_article.llm_used}"
                )
            else:
                logger.warning("Research article skipped: content too short for paid members")
        except Exception as e:
            logger.error(f"Research article generation failed: {e}")
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

    if research_article:
        # Research article already NQ05-filtered in generator; apply Layer 2 post-filter
        filtered = check_and_fix(research_article.content)
        content = _append_source_references(filtered.content, source_url_map)
        articles_out.append(
            {
                "tier": "Research",
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

    # Collect LLM models used for run log
    llm_models = sorted({a.llm_used for a in generated})
    if research_article:
        llm_models = sorted(set(llm_models) | {research_article.llm_used})

    research_wc = research_article.word_count if research_article else 0
    logger.info(f"Pipeline stages complete: {len(articles_out)} articles ready")
    return articles_out, errors, ", ".join(llm_models), research_wc


def _check_cross_tier_repetition(articles: list) -> dict:
    """Check for repeated phrases across tier articles (log only).

    Uses 4-gram analysis to detect phrases appearing in 3+ tiers.
    """
    from collections import Counter

    tier_phrases: dict[str, set[str]] = {}
    for article in articles:
        words = article.content.lower().split()
        ngrams = {" ".join(words[i : i + 4]) for i in range(len(words) - 3)}
        tier_phrases[article.tier] = ngrams

    # Find phrases appearing in 3+ tiers
    all_phrases: Counter = Counter()
    for phrases in tier_phrases.values():
        for p in phrases:
            all_phrases[p] += 1

    repeated = {p: c for p, c in all_phrases.items() if c >= 3}

    if repeated:
        logger.warning(f"Cross-tier repetition: {len(repeated)} phrases in 3+ tiers")
        for phrase, count in list(repeated.items())[:5]:
            logger.warning(f"  '{phrase}' in {count} tiers")

    return {"repeated_count": len(repeated), "total_phrases": len(all_phrases)}


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
                article.get("content", "")[:45000],  # truncate for Sheets cell limit (50K max)
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
            f" | research: {run_log.get('research_word_count', 0)}w"
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
    """Append hyperlinked source reference footer (FR19 + FR30).

    Appends a "Nguồn tham khảo" section with clickable hyperlinks.
    Only includes sources whose names actually appear in the content.
    """
    import html as _html
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
        safe_name = _html.escape(name)
        footer += f'• <a href="{url}">{safe_name}</a>\n'
    return content + footer


if __name__ == "__main__":
    main()
