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
        return_exceptions=True,
    )

    rss_articles = results[0] if not isinstance(results[0], Exception) else []
    crypto_articles = results[1] if not isinstance(results[1], Exception) else []
    market_data = results[2] if not isinstance(results[2], Exception) else []
    onchain_data = results[3] if not isinstance(results[3], Exception) else []
    tg_messages = results[4] if not isinstance(results[4], Exception) else []
    from cic_daily_report.collectors.economic_calendar import CalendarResult

    econ_calendar = results[5] if not isinstance(results[5], Exception) else CalendarResult()

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

    # Build interpretation notes for LLM context
    interpretation_notes: list[str] = []
    fg_raw = key_metrics.get("Fear & Greed")
    if isinstance(fg_raw, int):
        if fg_raw <= 20:
            interpretation_notes.append(
                f"Fear & Greed = {fg_raw} (Extreme Fear) — mức sợ hãi cực độ, "
                "thị trường đang hoảng loạn. Sentiment tiêu cực mạnh."
            )
        elif fg_raw <= 40:
            interpretation_notes.append(
                f"Fear & Greed = {fg_raw} (Fear) — thị trường thận trọng, "
                "cần theo dõi volume để xác nhận xu hướng"
            )
        elif fg_raw >= 80:
            interpretation_notes.append(
                f"Fear & Greed = {fg_raw} (Extreme Greed) — lịch sử cho thấy "
                "rủi ro điều chỉnh tăng cao ở vùng này"
            )
        elif fg_raw >= 60:
            interpretation_notes.append(
                f"Fear & Greed = {fg_raw} (Greed) — tâm lý tích cực nhưng cần "
                "cảnh giác nếu tiếp tục tăng"
            )
    for p in market_data:
        if p.symbol == "BTC" and p.data_type == "crypto":
            if abs(p.change_24h) >= 5:
                interpretation_notes.append(
                    f"BTC biến động {p.change_24h:+.1f}% trong 24h — mức biến động bất thường, "
                    "cần phân tích nguyên nhân (tin tức, liquidation, whale activity)"
                )
            elif abs(p.change_24h) < 1:
                interpretation_notes.append(
                    f"BTC biến động chỉ {p.change_24h:+.1f}% — thị trường đi ngang, "
                    "thường báo hiệu giai đoạn tích lũy trước breakout"
                )
    alt_season = key_metrics.get("Altcoin Season")
    if isinstance(alt_season, int):
        if alt_season >= 75:
            interpretation_notes.append(
                f"Altcoin Season Index = {alt_season} — đang là mùa altcoin, "
                "dòng tiền chảy mạnh vào altcoin"
            )
        elif alt_season <= 25:
            interpretation_notes.append(
                f"Altcoin Season Index = {alt_season} — BTC season, altcoin underperform so với BTC"
            )
    dxy_val = key_metrics.get("DXY")
    if isinstance(dxy_val, (int, float)):
        if dxy_val >= 105:
            interpretation_notes.append(
                f"DXY = {dxy_val} (cao) — USD mạnh thường gây áp lực giảm lên crypto"
            )
        elif dxy_val <= 100:
            interpretation_notes.append(
                f"DXY = {dxy_val} (thấp) — USD yếu thường hỗ trợ crypto tăng giá"
            )

    # Funding Rate + derivatives correlation hints
    funding_rate_val = None
    oi_val = None
    for m in onchain_data:
        if m.metric_name == "BTC_Funding_Rate":
            funding_rate_val = m.value
        elif m.metric_name == "BTC_Open_Interest":
            oi_val = m.value
    if funding_rate_val is not None:
        fr_pct = funding_rate_val * 100
        if fr_pct < -0.01:
            note = (
                f"Funding Rate = {fr_pct:.4f}% (âm) — short đang trả phí cho long, "
                "thường báo hiệu thị trường đang bị bán quá mức"
            )
            if oi_val and oi_val > 0:
                oi_fmt = _format_onchain_value("BTC_Open_Interest", oi_val)
                note += f". Open Interest = {oi_fmt} BTC contracts"
            interpretation_notes.append(note)
        elif fr_pct > 0.05:
            interpretation_notes.append(
                f"Funding Rate = {fr_pct:.4f}% (cao bất thường) — long đang trả phí cao, "
                "rủi ro squeeze tăng nếu giá giảm đột ngột"
            )

    # Build per-tier analysis context — each tier answers a DIFFERENT question.
    # Members see ALL lower tiers (L5 sees L4→L1), so content MUST NOT repeat.
    tier_context: dict[str, str] = {}
    tier_context["L1"] = (
        "Tier L1 — CÂU HỎI CHÍNH: 'Hôm nay thị trường thế nào?'\n"
        "ĐỐI TƯỢNG: Người mới, chỉ quan tâm BTC và ETH.\n"
        "GIỌNG VĂN: Thân thiện, dễ hiểu, như giải thích cho bạn bè.\n"
        "NỘI DUNG BẮT BUỘC:\n"
        "- Giá BTC và ETH hiện tại + biến động 24h (lấy từ dữ liệu)\n"
        "- Fear & Greed Index: con số + giải thích đơn giản nó nghĩa là gì\n"
        "- 1-2 tin tức quan trọng nhất hôm nay (tóm gọn 1-2 câu mỗi tin)\n"
        "- Kết luận ngắn: thị trường đang bullish/bearish/sideways\n"
        "KHÔNG LÀM:\n"
        "- KHÔNG dùng thuật ngữ phức tạp (funding rate, OI, correlation...)\n"
        "- KHÔNG phân tích on-chain hay macro\n"
        "- KHÔNG liệt kê hơn 2 coins\n"
    )
    tier_context["L2"] = (
        "Tier L2 — CÂU HỎI CHÍNH: 'Coins nào đáng chú ý hôm nay?'\n"
        "ĐỐI TƯỢNG: Đã hiểu cơ bản, muốn biết tổng quan altcoin.\n"
        "GIỌNG VĂN: Chuyên nghiệp nhưng dễ hiểu.\n"
        "⚠️ MEMBER ĐÃ ĐỌC L1 — KHÔNG lặp lại phân tích BTC/ETH cơ bản.\n"
        "NỘI DUNG BẮT BUỘC:\n"
        "- Tổng quan nhanh BTC Dominance + Altcoin Season Index (nếu có)\n"
        "- PHẢI nhắc đến TỐI THIỂU 10/19 coins trong danh sách\n"
        "- Nhóm coins theo sector: L1 (SOL, AVAX, ADA...), DeFi, L2, Meme, AI\n"
        "- Highlight coins biến động mạnh (>3%) — giải thích ngắn lý do nếu có tin\n"
        "- So sánh volume giữa các nhóm sector\n"
        "- USDT/VND rate (nếu có trong dữ liệu)\n"
        "KHÔNG LÀM:\n"
        "- KHÔNG lặp nội dung L1 (giá BTC/ETH, F&G đã có ở L1)\n"
        "- KHÔNG phân tích on-chain/derivatives (để cho L3-L5)\n"
        "- KHÔNG bịa vùng giá support/resistance\n"
        "CHỈ dùng giá và % từ dữ liệu được cung cấp.\n"
    )
    tier_context["L3"] = (
        "Tier L3 — CÂU HỎI CHÍNH: 'Tại sao thị trường diễn biến như vậy?'\n"
        "ĐỐI TƯỢNG: Có kinh nghiệm, muốn hiểu nguyên nhân sâu.\n"
        "GIỌNG VĂN: Phân tích chuyên sâu, có logic nhân-quả rõ ràng.\n"
        "⚠️ MEMBER ĐÃ ĐỌC L1+L2 — KHÔNG lặp giá coin hay liệt kê biến động.\n"
        "NỘI DUNG BẮT BUỘC:\n"
        "- Phân tích MỐI QUAN HỆ macro → crypto: DXY tác động BTC thế nào?\n"
        "  Gold đang signal gì? Lịch kinh tế có sự kiện nào quan trọng?\n"
        "- On-chain interpretation (CHỈ dữ liệu có sẵn):\n"
        "  + Funding Rate: dương = long trả phí cho short (thị trường lạc quan),\n"
        "    âm = short trả phí (thị trường bi quan). Cực đoan → rủi ro squeeze.\n"
        "  + Open Interest: tăng + giá tăng = trend mạnh, tăng + giá giảm = rủi ro.\n"
        "  + Long/Short Ratio: >1 = thiên long, <1 = thiên short.\n"
        "- Chuỗi nhân quả: nối các điểm dữ liệu thành câu chuyện logic\n"
        "- Sự kiện kinh tế vĩ mô: nêu RÕ ngày cụ thể và tác động dự kiến\n"
        "KHÔNG LÀM:\n"
        "- KHÔNG liệt kê giá từng coin (đã có ở L2)\n"
        "- KHÔNG phân tích rủi ro/scenario (để cho L4-L5)\n"
        "- KHÔNG bịa dữ liệu MVRV, SOPR, Exchange Reserves (không có trong input)\n"
    )
    tier_context["L4"] = (
        "Tier L4 — CÂU HỎI CHÍNH: 'Rủi ro hiện tại là gì?'\n"
        "ĐỐI TƯỢNG: Trader/investor có kinh nghiệm, cần đánh giá rủi ro.\n"
        "GIỌNG VĂN: Nghiêm túc, cảnh báo rõ ràng, có data backing.\n"
        "⚠️ MEMBER ĐÃ ĐỌC L1+L2+L3 — KHÔNG lặp phân tích macro/on-chain.\n"
        "NỘI DUNG BẮT BUỘC:\n"
        "- Derivatives risk: Funding Rate cực đoan? OI quá cao = rủi ro cascade?\n"
        "  Long/Short ratio lệch → rủi ro squeeze bên nào?\n"
        "- Sector risk comparison: sector nào đang chịu áp lực? Sector nào hold?\n"
        "- Red flags từ dữ liệu: chỉ số nào ở vùng nguy hiểm?\n"
        "- Macro risk: DXY trend, lịch sự kiện sắp tới có thể gây volatility?\n"
        "- Correlation breakdown: khi nào BTC-altcoin decouple? Dấu hiệu?\n"
        "KHÔNG LÀM:\n"
        "- KHÔNG lặp nội dung L1/L2/L3\n"
        "- KHÔNG đưa tỷ lệ phân bổ % cụ thể — VI PHẠM NQ05\n"
        "- KHÔNG gợi ý mua/bán/hold bất kỳ tài sản nào\n"
        "- KHÔNG bịa dữ liệu liquidation, whale movement (không có trong input)\n"
    )
    tier_context["L5"] = (
        "Tier L5 — CÂU HỎI CHÍNH: 'Nếu X xảy ra thì sao? Bức tranh tổng thể?'\n"
        "ĐỐI TƯỢNG: Master members, tư duy chiến lược, cần scenario analysis.\n"
        "GIỌNG VĂN: Formal, framework-based, dùng thuật ngữ chính xác.\n"
        "⚠️ MEMBER ĐÃ ĐỌC L1→L4 — CHỈ viết nội dung HOÀN TOÀN MỚI.\n"
        "NỘI DUNG BẮT BUỘC:\n"
        "- Scenario analysis (DỰA TRÊN DỮ LIỆU CÓ SẴN, KHÔNG BỊA):\n"
        "  + Bullish case: nếu [điều kiện từ data] → kỳ vọng gì?\n"
        "  + Bearish case: nếu [điều kiện từ data] → rủi ro gì?\n"
        "  + Base case: khả năng cao nhất dựa trên dữ liệu hiện tại\n"
        "- Tổng hợp tín hiệu: macro + on-chain + sentiment đồng thuận hay mâu thuẫn?\n"
        "- Sector rotation insight: dòng tiền đang chảy về đâu?\n"
        "  (dựa trên volume comparison + price action từ dữ liệu)\n"
        "- Key levels to watch: mức giá/chỉ số quan trọng cần theo dõi\n"
        "  (CHỈ từ dữ liệu có sẵn, KHÔNG bịa support/resistance)\n"
        "- Timeline: sự kiện sắp tới trong 7 ngày (từ lịch kinh tế)\n"
        "KHÔNG LÀM:\n"
        "- KHÔNG lặp BẤT KỲ nội dung nào từ L1-L4\n"
        "- KHÔNG bịa correlation coefficient, MVRV, SOPR, whale data\n"
        "- KHÔNG khuyến nghị mua/bán/phân bổ — VI PHẠM NQ05\n"
    )

    # Format interpretation notes for LLM
    interpretation_text = ""
    if interpretation_notes:
        interpretation_text = "\n".join(f"• {n}" for n in interpretation_notes)

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
        interpretation_notes=interpretation_text,
        economic_events=economic_events_text,
        recent_breaking=recent_breaking_text,
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
