"""BIC Chat Summary Generator — story-based market digest (FR15, v0.31.0).

Generates a cross-signal story digest for BIC Chat:
  Hook: 1-2 sentences — cross-signal divergence or surprising number
  Market Overview: 1 paragraph with numbers woven into causal narrative
  Stories: 5-8 news stories (top 2-3 deep, rest concise)
  Forward Look: macro/crypto events in next 3-7 days

Copy-paste ready for Telegram group.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

from cic_daily_report.adapters.llm_adapter import (
    LLMAdapter,
    LLMResponse,
    append_nq05_disclaimer,
)
from cic_daily_report.core.logger import get_logger
from cic_daily_report.generators.article_generator import (
    NQ05_SYSTEM_PROMPT,
    GeneratedArticle,
)
from cic_daily_report.generators.nq05_constants import DISCLAIMER
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
    consensus_text: str = "",  # v2.0 P1.6: Expert Consensus formatted text
) -> GeneratedSummary:
    """Generate BIC Chat summary with full data context.

    v0.31.0: Story-based digest with cross-signal hook,
    narrative market overview, and prioritized news stories.
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
        consensus_text=consensus_text,
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
    content = append_nq05_disclaimer(filtered.content)
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
    consensus_text: str = "",  # v2.0 P1.6: Expert Consensus
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

    # 8.5. Expert Consensus (v2.0 P1.6)
    if consensus_text:
        parts.append(consensus_text)

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
    """Build the story-based digest prompt (v0.31.0)."""
    return (
        f"Viết bản tin tổng hợp thị trường tài sản mã hóa cho BIC Chat, "
        f"ngày {today}.\n\n"
        "=== DỮ LIỆU ===\n"
        f"{data_context}\n\n"
        "=== CẤU TRÚC BẮT BUỘC ===\n\n"
        "PHẦN MỞ ĐẦU — HOOK (1-2 câu):\n"
        "Mở đầu bằng 1 PHÁT HIỆN THÚ VỊ từ dữ liệu. Ưu tiên:\n"
        "- Mâu thuẫn giữa các tín hiệu (VD: F&G thấp nhưng whale đang tích lũy)\n"
        "- Số liệu bất ngờ (VD: lần đầu tiên kể từ...)\n"
        "- Bối cảnh lịch sử (VD: lần cuối chỉ số này ở mức đó, BTC đang ở $X)\n"
        "KHÔNG mở đầu bằng 'Hôm nay thị trường...' hay 'Tổng quan thị trường...'\n\n"
        "CẬP NHẬT THỊ TRƯỜNG (1 đoạn):\n"
        "Viết **Cập nhật Thị trường** làm tiêu đề đậm.\n"
        "Sau đó 1 đoạn văn xuôi lồng số liệu: tổng vốn hóa, BTC, ETH, "
        "sector nổi bật. Nối NGUYÊN NHÂN → HỆ QUẢ, không liệt kê.\n"
        "VD đúng: 'Tổng vốn hóa giảm 1,46% xuống 2,43 nghìn tỷ USD. "
        "Bitcoin giảm 1,59% xuống 68.200 USD, trong khi...'\n"
        "VD sai: 'BTC: $68,200 (-1.59%). ETH: ...' (liệt kê khô)\n\n"
        "TIN TỨC (5-8 tin, sắp theo mức quan trọng):\n"
        "Mỗi tin là 1 section riêng:\n"
        "- Tiêu đề: **[Tiêu đề mô tả bằng tiếng Việt]** (in đậm)\n"
        "- 2-3 TIN QUAN TRỌNG NHẤT: viết 1-2 đoạn phân tích sâu:\n"
        "  + Đoạn 1: Chuyện gì xảy ra + bối cảnh + con số cụ thể\n"
        "  + Đoạn 2: Tại sao quan trọng + hệ quả cụ thể cho nhà đầu tư\n"
        "- 3-5 TIN PHỤ: viết 1 đoạn ngắn (3-4 câu) gồm sự kiện + ý nghĩa\n"
        "Câu cuối mỗi tin = HỆ QUẢ CỤ THỂ (ai bị ảnh hưởng, bao nhiêu, khi nào), "
        "KHÔNG viết chung chung kiểu 'cần theo dõi' hay 'có thể ảnh hưởng'.\n\n"
        "SẮP TỚI (1-2 dòng cuối):\n"
        "📅 Sự kiện sắp tới trong 3-7 ngày (FOMC, CPI, NFP, crypto event...). "
        "Mỗi sự kiện: tên + ngày + tại sao quan trọng (1 câu).\n"
        "Nếu không có sự kiện đáng kể trong dữ liệu → bỏ qua phần này.\n\n"
        "=== QUY TẮC ===\n"
        "- Tiếng Việt có dấu, đọc tốt trên điện thoại\n"
        "- Dùng 'tài sản mã hóa' (KHÔNG dùng 'tiền điện tử')\n"
        "- Mỗi đoạn TỐI ĐA 3 câu — dài hơn sẽ khó đọc trên mobile\n"
        "- **bold** CHỈ cho tiêu đề tin và số liệu then chốt\n"
        "- Copy-paste ready cho Telegram (không dùng heading #, "
        "không dùng link, không bảng)\n"
        "- CHỈ dùng DỮ LIỆU THỰC từ phần DỮ LIỆU ở trên — "
        "KHÔNG bịa số, KHÔNG thêm nguồn không có trong data\n"
        "- KHÔNG viết lời khuyên đầu tư ('nên mua', 'nên bán', "
        "'quyết định đầu tư thông minh')\n"
        "- KHÔNG bắt đầu bằng 'TL;DR' hay 'Tóm lược'\n"
    )
