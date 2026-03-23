"""BIC Chat Summary Generator — comprehensive market overview (FR15, v0.24.0).

Generates a 4-section summary matching Anh Cường's manual BIC Chat format:
  Section 1: ⭐ Tổng quan Thị trường (causal analysis paragraphs)
  Section 2: 📊 Bảng chỉ số (metrics table with emoji markers)
  Section 3: 👉🏻 Đáng chú ý (VN news + upcoming macro events)
  Section 4: Các tin tức nổi bật (5-8 news articles with analysis)

Copy-paste ready for Telegram group.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

from cic_daily_report.adapters.llm_adapter import LLMAdapter, LLMResponse
from cic_daily_report.core.logger import get_logger
from cic_daily_report.generators.article_generator import (
    DISCLAIMER,
    NQ05_SYSTEM_PROMPT,
    GeneratedArticle,
)
from cic_daily_report.generators.nq05_filter import check_and_fix

logger = get_logger("summary_generator")


@dataclass
class GeneratedSummary:
    """A BIC Chat summary post."""

    title: str
    content: str
    word_count: int
    llm_used: str
    generation_time_sec: float
    nq05_status: str = "pending"


async def generate_bic_summary(
    llm: LLMAdapter,
    articles: list[GeneratedArticle],
    key_metrics: dict[str, str | float],
    cleaned_news: list[dict] | None = None,
    market_data: list | None = None,
    onchain_data: list | None = None,
    sector_snapshot: object | None = None,
    econ_calendar: object | None = None,
    metrics_interp: object | None = None,
    narratives_text: str = "",
    whale_data: object | None = None,
) -> GeneratedSummary:
    """Generate BIC Chat summary with full data context.

    v0.24.0: Receives raw data directly (not just article excerpts)
    to produce comprehensive 4-section market overview.
    """
    start = time.monotonic()
    today = datetime.now(timezone.utc).strftime("%d/%m/%Y")

    # Build rich data context for LLM
    data_context = _build_data_context(
        key_metrics=key_metrics,
        cleaned_news=cleaned_news or [],
        market_data=market_data or [],
        onchain_data=onchain_data or [],
        sector_snapshot=sector_snapshot,
        econ_calendar=econ_calendar,
        metrics_interp=metrics_interp,
        narratives_text=narratives_text,
        whale_data=whale_data,
        articles=articles,
    )

    prompt = _build_prompt(today, data_context)

    response: LLMResponse = await llm.generate(
        prompt=prompt,
        system_prompt=NQ05_SYSTEM_PROMPT,
        max_tokens=4096,
        temperature=0.3,
    )

    # Apply NQ05 post-filter before appending disclaimer
    filtered = check_and_fix(response.text.strip())
    raw_word_count = len(filtered.content.split())
    if raw_word_count < 50:
        logger.warning(
            f"BIC Chat summary too short ({raw_word_count} words), "
            f"LLM may have returned empty response"
        )
    content = filtered.content + DISCLAIMER
    word_count = len(content.split())
    elapsed = time.monotonic() - start

    logger.info(f"BIC Chat summary: {word_count} words via {response.model} in {elapsed:.1f}s")

    return GeneratedSummary(
        title="[Summary] Tổng quan thị trường tài sản mã hóa",
        content=content,
        word_count=word_count,
        llm_used=response.model,
        generation_time_sec=elapsed,
    )


def _build_data_context(
    key_metrics: dict[str, str | float],
    cleaned_news: list[dict],
    market_data: list,
    onchain_data: list,
    sector_snapshot: object | None,
    econ_calendar: object | None,
    metrics_interp: object | None,
    narratives_text: str,
    whale_data: object | None,
    articles: list[GeneratedArticle],
) -> str:
    """Assemble all data sources into structured LLM context."""
    parts: list[str] = []

    # 1. Key metrics table
    metrics_lines = []
    for name, value in key_metrics.items():
        if not name.startswith("⚠️"):
            metrics_lines.append(f"  {name}: {value}")
    if metrics_lines:
        parts.append("=== CHỈ SỐ CHÍNH ===\n" + "\n".join(metrics_lines))

    # 2. Market regime from Metrics Engine
    if metrics_interp is not None:
        regime = getattr(metrics_interp, "regime", None)
        if regime is not None:
            parts.append(f"=== TRẠNG THÁI THỊ TRƯỜNG ===\n{regime.format_vi()}")
        deriv = getattr(metrics_interp, "derivatives_analysis", "")
        if deriv:
            parts.append(f"=== DERIVATIVES ===\n{deriv}")
        macro = getattr(metrics_interp, "macro_analysis", "")
        if macro:
            parts.append(f"=== MACRO ===\n{macro}")
        sentiment = getattr(metrics_interp, "sentiment_analysis", "")
        if sentiment:
            parts.append(f"=== SENTIMENT ===\n{sentiment}")
        cross = getattr(metrics_interp, "cross_signal_summary", "")
        if cross:
            parts.append(f"=== CROSS-SIGNAL ===\n{cross}")

    # 3. Market data (top coins)
    if market_data:
        market_lines = []
        for p in market_data[:15]:
            symbol = getattr(p, "symbol", "")
            price = getattr(p, "price", 0)
            change = getattr(p, "change_24h", 0)
            dtype = getattr(p, "data_type", "")
            if dtype == "crypto" and price > 0:
                market_lines.append(f"  {symbol}: ${price:,.2f} ({change:+.1f}%)")
        if market_lines:
            parts.append("=== TOP COINS ===\n" + "\n".join(market_lines))

    # 4. On-chain data
    if onchain_data:
        oc_lines = []
        for m in onchain_data:
            name = getattr(m, "metric_name", "")
            value = getattr(m, "value", 0)
            source = getattr(m, "source", "")
            oc_lines.append(f"  {name}: {value} ({source})")
        if oc_lines:
            parts.append("=== ON-CHAIN & DERIVATIVES ===\n" + "\n".join(oc_lines))

    # 5. Whale data
    if whale_data is not None:
        whale_text = ""
        if hasattr(whale_data, "format_for_llm"):
            whale_text = whale_data.format_for_llm()
        elif isinstance(whale_data, str):
            whale_text = whale_data
        if whale_text and "Không có dữ liệu" not in whale_text:
            parts.append(whale_text)

    # 6. Sector snapshot
    if sector_snapshot is not None and hasattr(sector_snapshot, "format_for_llm"):
        sector_text = sector_snapshot.format_for_llm()
        if sector_text:
            parts.append(sector_text)

    # 7. Economic calendar
    if econ_calendar is not None and hasattr(econ_calendar, "format_for_llm"):
        econ_text = econ_calendar.format_for_llm()
        if econ_text:
            parts.append(f"=== LỊCH KINH TẾ ===\n{econ_text}")

    # 8. Narratives
    if narratives_text:
        parts.append(f"=== XU HƯỚNG TIN TỨC ===\n{narratives_text}")

    # 9. News articles (top 15 for summary)
    if cleaned_news:
        news_lines = []
        vn_news = []
        intl_news = []
        for a in cleaned_news[:30]:
            title = a.get("title", "")
            source = a.get("source_name", "")
            summary = a.get("summary", "") or a.get("full_text", "")
            language = a.get("language", "en")
            entry = f"  [{source}] {title}"
            if summary:
                entry += f"\n    {summary[:300]}"
            if language == "vi":
                vn_news.append(entry)
            else:
                intl_news.append(entry)

        if vn_news:
            news_lines.append("--- Tin Việt Nam ---")
            news_lines.extend(vn_news[:5])
        if intl_news:
            news_lines.append("--- Tin quốc tế ---")
            news_lines.extend(intl_news[:15])
        if news_lines:
            parts.append("=== TIN TỨC ===\n" + "\n".join(news_lines))

    # 10. Tier article excerpts (supplementary context)
    if articles:
        excerpts = []
        for article in articles[:3]:
            excerpt = article.content[:500].replace(DISCLAIMER, "").strip()
            excerpts.append(f"  [{article.tier}]: {excerpt}...")
        if excerpts:
            parts.append("=== TÓM TẮT BÀI PHÂN TÍCH ===\n" + "\n".join(excerpts))

    return "\n\n".join(parts)


def _build_prompt(today: str, data_context: str) -> str:
    """Build the 4-section summary prompt."""
    return (
        f"Viết bài TỔNG QUAN THỊ TRƯỜNG cho BIC Chat, ngày {today}.\n"
        "Bài viết gồm ĐÚNG 4 phần theo format dưới đây.\n\n"
        "=== DỮ LIỆU ===\n"
        f"{data_context}\n\n"
        "=== FORMAT BẮT BUỘC ===\n\n"
        "PHẦN 1: Mở đầu bằng dòng:\n"
        f"⭐ TỔNG QUAN THỊ TRƯỜNG TÀI SẢN MÃ HÓA\nNgày {today}\n\n"
        "Viết 2-3 đoạn văn PHÂN TÍCH NHÂN QUẢ (không liệt kê bullet points):\n"
        "- Đoạn 1: Bối cảnh macro/sự kiện lớn → tác động lên crypto\n"
        "- Đoạn 2: BTC và ETH diễn biến thế nào, lý do cụ thể\n"
        "- Đoạn 3: Tâm lý thị trường + dòng tiền (dùng F&G, whale data, "
        "funding rate nếu có)\n"
        "Phải NỐI NGUYÊN NHÂN → HỆ QUẢ, không chỉ liệt kê số liệu.\n\n"
        "PHẦN 2: Bảng chỉ số với format:\n"
        "📊 CHỈ SỐ        | GIÁ TRỊ     | THAY ĐỔI\n"
        "Mỗi dòng: tên chỉ số | giá trị | emoji (🔴 giảm, 🟢 tăng, ➡️ ngang)\n"
        "Gồm: BTC, ETH, BTC Dominance, Total MCap, Fear & Greed, DXY, Gold\n"
        "Dùng emoji: 🔴 khi giảm >0.5%, 🟢 khi tăng >0.5%, ➡️ khi đi ngang\n"
        "Fear & Greed: 😱 (≤25), 😰 (26-45), 😐 (46-55), 😏 (56-74), 🤑 (≥75)\n\n"
        "PHẦN 3: Tiêu đề: 👉🏻 Đáng chú ý\n"
        "- 2-3 tin đáng chú ý cho cộng đồng crypto Việt Nam "
        "(ưu tiên tin VN, sự kiện sắp diễn ra)\n"
        "- Sự kiện kinh tế/macro SẮP TỚI trong 3-7 ngày (FOMC, CPI, v.v.)\n"
        "- Mỗi điểm: 1-2 câu ngắn gọn\n\n"
        "PHẦN 4: Tiêu đề: 📰 Các tin tức nổi bật\n"
        "Chọn 5-8 tin QUỐC TẾ quan trọng nhất từ dữ liệu ở trên.\n"
        "Mỗi tin có format:\n"
        "  [số]. [Tiêu đề tin bằng tiếng Việt]\n"
        "  → 2-3 câu phân tích: chuyện gì xảy ra, tại sao quan trọng, "
        "ảnh hưởng gì đến thị trường\n\n"
        "=== QUY TẮC ===\n"
        "- Tiếng Việt, dễ hiểu, đọc tốt trên điện thoại\n"
        "- Dùng 'tài sản mã hóa' (không 'tiền điện tử')\n"
        "- Copy-paste ready cho Telegram (không markdown phức tạp)\n"
        "- **bold** cho số liệu quan trọng\n"
        "- CHỈ dùng DỮ LIỆU THỰC từ trên, không bịa số\n"
        "- Tin tức phải có phân tích ngắn, không chỉ đưa tiêu đề\n"
    )
