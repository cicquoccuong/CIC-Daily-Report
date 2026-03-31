"""CIC Market Insight Research Article Generator (P2-A).

Generates a >2500 word deep analysis article for BIC Group Level 1 (paid members).
Combines on-chain advanced metrics, derivatives, ETF flows, stablecoin data,
and macro context into a comprehensive daily research report.

Series: "CIC Market Insight — Ngày DD/MM/YYYY"
Frequency: 3-5 times/week
Target: BIC Group L1 (paid members only, NOT public)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

from cic_daily_report.adapters.llm_adapter import LLMAdapter, LLMResponse
from cic_daily_report.collectors.research_data import ResearchData
from cic_daily_report.core.logger import get_logger
from cic_daily_report.generators.article_generator import (
    DISCLAIMER,
    GenerationContext,
)
from cic_daily_report.generators.text_utils import truncate_to_limit

logger = get_logger("research_generator")

# Research article needs higher token limit for >2500 words
RESEARCH_MAX_TOKENS = 8192
RESEARCH_TEMPERATURE = 0.4
# P1.25: Upper bound for research articles to prevent unbounded content.
# 2500 Vietnamese words x ~6 chars/word + formatting + DISCLAIMER headroom
RESEARCH_MAX_CHARS = 18000

# NQ05-compliant system prompt — research-grade depth
RESEARCH_SYSTEM_PROMPT = (
    "VAI TRÒ: Bạn là chuyên gia phân tích thị trường tài sản mã hóa cấp cao, "
    "viết bài nghiên cứu chuyên sâu cho cộng đồng CIC (Crypto Inner Circle) — "
    "nhóm thành viên TRẢI PHÍ Level 1 (BIC Group L1). Họ là nhà đầu tư chiến lược "
    "dài hạn với kiến thức sâu về thị trường.\n\n"
    "PHONG CÁCH VIẾT:\n"
    "- Chuyên sâu như bài nghiên cứu, không phải tin tức tóm tắt\n"
    "- Mỗi chỉ số PHẢI kèm DIỄN GIẢI ý nghĩa + so sánh với ngưỡng lịch sử\n"
    "- Nối các chỉ số thành CHUỖI NHÂN-QUẢ logic (VD: MVRV thấp + Exchange outflow "
    "tăng = giai đoạn tích lũy)\n"
    "- Phân tích MÂU THUẪN giữa các tín hiệu (nếu có)\n"
    "- Viết tiếng Việt chuyên nghiệp, thuật ngữ chính xác, dễ đọc\n"
    "- Độ dài TỐI THIỂU 2500 từ — phân tích CHI TIẾT, không tóm tắt lướt\n\n"
    "NQ05: Chỉ phân tích và thông tin — dùng 'tài sản mã hóa' (không 'tiền điện tử').\n\n"
    "CHỐNG BỊA DỮ LIỆU:\n"
    "- CHỈ dùng data được cung cấp. KHÔNG tự thêm nguồn, con số, vùng giá.\n"
    "- Nếu thiếu dữ liệu cho một phần → bỏ qua, KHÔNG viết 'Chưa có dữ liệu'.\n"
    "- KHÔNG cite: Bloomberg, CryptoQuant, TradingView, Santiment, IntoTheBlock, Glassnode.\n\n"
)


@dataclass
class GeneratedResearchArticle:
    """A fully generated research article for BIC Group L1."""

    title: str
    content: str
    word_count: int
    llm_used: str
    generation_time_sec: float
    nq05_status: str = "pending"


async def generate_research_article(
    llm: LLMAdapter,
    context: GenerationContext,
    research_data: ResearchData,
    consensus_text: str = "",  # v2.0 P1.6: Expert Consensus formatted text
    master_analysis_text: str = "",  # P1.7: Master Analysis as additional context
) -> GeneratedResearchArticle | None:
    """Generate a >2500 word CIC Market Insight research article.

    Combines existing pipeline data (market, on-chain, derivatives, sector, news)
    with research-specific data (BGeometrics, ETF flows, stablecoins, Pi Cycle)
    to produce a comprehensive analysis for BIC Group L1 paid members.

    Args:
        llm: Multi-provider LLM adapter.
        context: Existing pipeline data from Stage 1 collection.
        research_data: Research-specific data from collect_research_data().

    Returns:
        GeneratedResearchArticle with content + disclaimer, or None if too short.
    """
    start = time.monotonic()
    today = datetime.now(timezone.utc).strftime("%d/%m/%Y")

    # Build comprehensive data context
    data_context = _build_research_context(
        context, research_data, consensus_text, master_analysis_text
    )
    prompt = _build_research_prompt(today, data_context)

    response: LLMResponse = await llm.generate(
        prompt=prompt,
        system_prompt=RESEARCH_SYSTEM_PROMPT,
        max_tokens=RESEARCH_MAX_TOKENS,
        temperature=RESEARCH_TEMPERATURE,
    )

    # NQ05 filtering handled by pipeline Stage 3 (consistent with tier articles)
    body = response.text.strip()

    # P1.25: Truncate body BEFORE appending DISCLAIMER to guarantee NQ05 disclaimer
    # is never cut. WHY: DISCLAIMER is mandatory for NQ05 compliance — if we append
    # it first and then truncate the combined string, the disclaimer can be chopped off.
    body_limit = RESEARCH_MAX_CHARS - len(DISCLAIMER)
    body, was_truncated = truncate_to_limit(body, body_limit)
    if was_truncated:
        logger.warning(
            f"Research article body truncated to fit DISCLAIMER: "
            f"{len(response.text.strip())} -> {len(body)} chars"
        )
    content = body + DISCLAIMER

    # WHY recalculate after truncation: word_count must reflect final delivered content
    word_count = len(content.split())
    elapsed = time.monotonic() - start

    # Quality gate: skip delivery if critically short (fallback LLM or truncated)
    if word_count < 800:
        logger.error(
            f"Research article critically short: {word_count} words (target >2500). "
            "Skipping — not delivering low-quality content to paid members."
        )
        return None

    if word_count < 1500:
        logger.warning(
            f"Research article below target: {word_count} words (target >2500). "
            "LLM may have returned truncated response."
        )

    logger.info(f"Research article: {word_count} words via {response.model} in {elapsed:.1f}s")

    return GeneratedResearchArticle(
        title=f"[CIC Market Insight] Phân tích thị trường chuyên sâu — Ngày {today}",
        content=content,
        word_count=word_count,
        llm_used=response.model,
        generation_time_sec=elapsed,
    )


def _build_research_context(
    context: GenerationContext,
    research_data: ResearchData,
    consensus_text: str = "",  # v2.0 P1.6
    master_analysis_text: str = "",  # P1.7: Master Analysis as additional context
) -> str:
    """Assemble all data sources into structured LLM context for research article."""
    parts: list[str] = []

    # 1. Key metrics table (from existing pipeline)
    if context.key_metrics:
        lines = []
        for name, value in context.key_metrics.items():
            if not name.startswith("⚠️"):
                lines.append(f"  {name}: {value}")
        if lines:
            parts.append("=== CHỈ SỐ CHÍNH ===\n" + "\n".join(lines))

    # 2. Market data (from existing pipeline)
    if context.market_data:
        parts.append(
            f"=== DỮ LIỆU THỊ TRƯỜNG (nguồn: CoinLore, CoinGecko) ===\n{context.market_data}"
        )

    # 3. Research-specific data (BGeometrics, ETF, stablecoins, Pi Cycle)
    research_text = research_data.format_for_llm()
    if research_text:
        parts.append(research_text)

    # 4. Existing on-chain & derivatives data (from pipeline)
    if context.onchain_data:
        parts.append(
            "=== ON-CHAIN & DERIVATIVES CƠ BẢN "
            "(nguồn: CoinMetrics, Coinalyze, OKX) ===\n"
            f"{context.onchain_data}"
        )

    # 5. Sector & DeFi data (from existing pipeline)
    if context.sector_data:
        parts.append(context.sector_data)

    # 6. Metrics Engine interpretation (from existing pipeline)
    if context.metrics_interpretation is not None:
        try:
            # Use L5-grade interpretation (most comprehensive)
            interp_text = context.metrics_interpretation.format_for_tier("L5")
            if interp_text:
                parts.append(
                    "=== PHÂN TÍCH TỰ ĐỘNG (Metrics Engine) ===\n"
                    "Dùng kết quả này làm NỀN TẢNG. Diễn giải chi tiết hơn, "
                    "KHÔNG copy nguyên văn.\n"
                    f"{interp_text}"
                )
        except Exception:
            if context.interpretation_notes:
                parts.append(f"=== PHÂN TÍCH TỰ ĐỘNG ===\n{context.interpretation_notes}")

    # 7. Economic events (from existing pipeline)
    if context.economic_events:
        parts.append(
            f"=== LỊCH SỰ KIỆN KINH TẾ (nguồn: FairEconomy) ===\n{context.economic_events}\n"
            "Lưu ý: phân biệt sự kiện ĐÃ QUA vs SẮP TỚI."
        )

    # 8. Whale data (from existing pipeline)
    if context.whale_data and "Không có dữ liệu" not in context.whale_data:
        parts.append(f"=== WHALE ALERT ===\n{context.whale_data}")

    # 9. Breaking news context (from existing pipeline)
    if context.recent_breaking:
        parts.append(f"=== SỰ KIỆN BREAKING 24H QUA ===\n{context.recent_breaking}")

    # 10. News highlights (top 15 for context)
    if context.news_summary:
        news_lines = context.news_summary.split("\n")
        short_news = "\n".join(news_lines[:30])
        parts.append(f"=== TIN TỨC NỔI BẬT ===\n{short_news}")

    # 11. Narratives (from existing pipeline)
    if context.narratives_text:
        parts.append(context.narratives_text)

    # 12. Expert Consensus (v2.0 P1.6)
    if consensus_text:
        parts.append(consensus_text)

    # 13. Master Analysis Context (P1.7)
    # WHY: When Master Analysis succeeded, its comprehensive narrative provides
    # additional context for the research article. Research stays INDEPENDENT
    # (uses raw data as primary source) but can reference Master's cross-signal
    # insights as supplementary context.
    if master_analysis_text:
        parts.append(
            "=== B\u1ed0I C\u1ea2NH T\u1eea MASTER ANALYSIS ===\n"
            "D\u00f9ng l\u00e0m tham kh\u1ea3o b\u1ed5 sung. "
            "PH\u00c2N T\u00cdCH \u0110\u1ed8C L\u1eacP t\u1eeb d\u1eef li\u1ec7u "
            "g\u1ed1c \u1edf tr\u00ean, KH\u00d4NG copy t\u1eeb Master.\n"
            f"{master_analysis_text[:3000]}"
        )

    return "\n\n".join(parts)


def _build_research_prompt(today: str, data_context: str) -> str:
    """Build the research article prompt with 8-section structure."""
    return (
        f"Viết bài nghiên cứu chuyên sâu 'CIC Market Insight' cho ngày {today}.\n"
        "Bài viết TỐI THIỂU 2500 từ, phân tích CHI TIẾT và SÂU.\n\n"
        "=== DỮ LIỆU ĐẦU VÀO ===\n"
        f"{data_context}\n\n"
        "=== CẤU TRÚC BÀI VIẾT (8 PHẦN) ===\n\n"
        f"PHẦN 1: Mở đầu bằng tiêu đề:\n"
        f"# [CIC Market Insight] Tiêu đề hấp dẫn — Ngày {today}\n\n"
        "## 1. Tổng quan thị trường\n"
        "Viết 2-3 đoạn văn phân tích nhân quả (KHÔNG bullet points):\n"
        "- BTC Dominance, Total Market Cap, Fear & Greed → đánh giá tâm lý thị trường\n"
        "- Xu hướng chính trong 24h qua\n"
        "- Kết nối các yếu tố thành câu chuyện logic\n"
        "(~300 từ)\n\n"
        "## 2. ⚠️ Cảnh báo sớm\n"
        "NẾU có Breaking News signal hoặc tín hiệu bất thường → phân tích chi tiết.\n"
        "NẾU KHÔNG có gì bất thường → viết ngắn 2-3 câu xác nhận 'không có tín hiệu cảnh báo'.\n"
        "(~100-300 từ tùy có/không có cảnh báo)\n\n"
        "## 3. Phân tích On-chain chuyên sâu\n"
        "Phân tích TỪNG chỉ số on-chain có trong dữ liệu:\n"
        "- MVRV Z-Score: giá trị + ý nghĩa + so sánh ngưỡng lịch sử "
        "(>7 = quá nóng, <0 = cơ hội, 2-3 = vùng trung tính)\n"
        "- NUPL: giá trị + phase hiện tại "
        "(0-0.25 = Hope, 0.25-0.5 = Optimism, 0.5-0.75 = Belief, >0.75 = Euphoria)\n"
        "- SOPR: >1 = người bán chốt lời, <1 = bán lỗ, =1 = breakeven\n"
        "- Puell Multiple: <0.5 = miner đầu hàng, >4 = miner chốt lời mạnh\n"
        "- Pi Cycle Top: khoảng cách giữa 2 đường SMA → tín hiệu đỉnh hay chưa\n"
        "- Exchange Flow: dòng tiền vào/ra sàn → tín hiệu tích lũy hay phân phối\n"
        "- Hash Rate, Miner Revenue: sức khỏe mạng lưới\n"
        "KẾT NỐI các chỉ số thành câu chuyện: VD 'MVRV thấp + Exchange outflow = tích lũy'\n"
        "(~500-600 từ)\n\n"
        "## 4. Stablecoin & Dòng tiền\n"
        "- USDT/USDC supply thay đổi 1d/7d/30d → dòng tiền mới vào crypto hay rút ra?\n"
        "- ETF Flow: phân tích chi tiết dòng tiền từng ETF lớn (IBIT, FBTC, GBTC...)\n"
        "  → Tổng dòng tiền + xu hướng + ý nghĩa cho thị trường\n"
        "- Kết nối: ETF flow + stablecoin flow + exchange flow → bức tranh tổng thể dòng tiền\n"
        "(~400-500 từ)\n\n"
        "## 5. Phân tích Derivatives\n"
        "- Funding Rate: dương/âm → tâm lý long/short\n"
        "- Open Interest: tăng/giảm → leverage đang được thêm hay rút\n"
        "- Long/Short Ratio: bên nào đang thắng thế\n"
        "- Taker Buy/Sell Ratio: bên mua hay bán đang chủ động\n"
        "- Liquidation: nếu có dữ liệu → mô tả áp lực thanh lý\n"
        "KẾT NỐI: Derivatives + on-chain → retail vs smart money, ai đang đúng?\n"
        "(~350-400 từ)\n\n"
        "## 6. Macro & Sự kiện\n"
        "- Phân tích tác động của sự kiện kinh tế từ lịch sự kiện (nếu có)\n"
        "- Lịch FOMC / sự kiện kinh tế sắp tới → tác động tiềm năng cụ thể\n"
        "- Tin tức quốc tế đáng chú ý → ảnh hưởng lên thị trường crypto\n"
        "- KẾT NỐI: sự kiện macro → tác động lên dòng tiền → tác động lên giá\n"
        "(~300-400 từ)\n\n"
        "## 7. Bảng tổng hợp chỉ số chính\n"
        "Tạo BẢNG tổng hợp tất cả chỉ số CÓ trong dữ liệu:\n"
        "| Chỉ số | Giá trị | Đánh giá |\n"
        "Gồm: BTC Price, F&G, MVRV Z-Score, NUPL, SOPR, Funding Rate, ETF Flow, "
        "Stablecoin supply (chỉ các chỉ số CÓ DATA)\n"
        "Cột 'Đánh giá': 1-2 từ mô tả ý nghĩa (VD: 'Vùng sợ hãi', 'Tích lũy', "
        "'Dòng tiền vào')\n"
        "(~200-300 từ)\n\n"
        "## 8. Tổng kết & Nhận định\n"
        "- Tổng hợp TẤT CẢ tín hiệu thành BỨC TRANH NHẤT QUÁN\n"
        "- Chỉ ra các tín hiệu ĐỒNG THUẬN và MÂU THUẪN\n"
        "- Nêu các ngưỡng/sự kiện cần theo dõi CỤ THỂ (con số, ngày)\n"
        "(~200-300 từ)\n\n"
        "=== XỬ LÝ THIẾU DỮ LIỆU ===\n"
        "- NẾU dữ liệu cho một phần KHÔNG có trong 'DỮ LIỆU ĐẦU VÀO' → BỎ QUA phần đó\n"
        "- KHÔNG viết 'Chưa có dữ liệu', 'Không có thông tin' hay tương tự\n"
        "- KHÔNG bịa số liệu thay thế\n"
        "- Phân bổ từ sang các phần CÓ dữ liệu để đạt tổng >2500 từ\n\n"
        "=== QUY TẮC CHUNG ===\n"
        "- Viết TỐI THIỂU 2500 từ, phân tích CHI TIẾT mỗi phần\n"
        "- Ngôn ngữ: tiếng Việt chuyên nghiệp\n"
        "- Dùng **bold** cho số liệu quan trọng\n"
        "- Mỗi chỉ số on-chain PHẢI kèm diễn giải ý nghĩa và ngưỡng tham chiếu\n"
        "- NỐI NHÂN-QUẢ giữa các phần: on-chain → derivatives → dòng tiền → macro\n"
        "- KHÔNG bịa dữ liệu. Chỉ dùng data được cung cấp ở trên.\n"
        "- Kết thúc bài = kết thúc section 8. KHÔNG thêm phần nào khác.\n"
    )
