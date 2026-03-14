"""Tier Article Generator — 5 tiers, dual-layer, cumulative (FR13-FR22).

Generates L1→L5 articles using templates + LLM adapter.
Each article has TL;DR (simple) + Full Analysis (technical).
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field

from cic_daily_report.adapters.llm_adapter import LLMAdapter, LLMResponse
from cic_daily_report.core.error_handler import LLMError
from cic_daily_report.core.logger import get_logger
from cic_daily_report.generators.template_engine import (
    ArticleTemplate,
    render_key_metrics_table,
    render_sections,
)

logger = get_logger("article_generator")

# Inter-tier cooldown (seconds) to avoid free-tier LLM rate limits (429).
# Set to 0 in tests via env var or when IS_PRODUCTION is False.
_TIER_COOLDOWN = 45 if os.getenv("GITHUB_ACTIONS") == "true" else 0
_TIER_RETRY_WAIT = 60  # seconds to wait before retrying a failed tier (429)

# FR17: NQ05-compliant disclaimer (Vietnamese)
DISCLAIMER = (
    "\n\n---\n"
    "⚠️ *Tuyên bố miễn trừ trách nhiệm:* "
    "Nội dung trên chỉ mang tính chất thông tin và phân tích, "
    "KHÔNG phải lời khuyên đầu tư. Tài sản mã hóa có rủi ro cao. "
    "Hãy tự nghiên cứu (DYOR) trước khi đưa ra quyết định đầu tư."
)

# NQ05 prompt-layer instructions (QĐ4 Layer 1)
NQ05_SYSTEM_PROMPT = (
    "Bạn là chuyên gia phân tích thị trường tài sản mã hóa cho cộng đồng CIC.\n"
    "QUY TẮC BẮT BUỘC (NQ05 Compliance):\n"
    "- KHÔNG BAO GIỜ khuyến nghị mua, bán, hoặc giữ bất kỳ tài sản nào\n"
    "- KHÔNG dùng từ: 'nên mua', 'nên bán', 'khuyến nghị', 'guaranteed', "
    "'chắc chắn tăng/giảm'\n"
    "- Dùng 'tài sản mã hóa' thay vì 'tiền điện tử' hoặc 'tiền ảo'\n"
    "- Chỉ PHÂN TÍCH và THÔNG TIN, để người đọc tự quyết định\n"
    "- CHỐNG BỊA DỮ LIỆU: CHỈ trích dẫn nguồn khi dữ liệu THỰC SỰ có trong phần "
    "DỮ LIỆU được cung cấp. KHÔNG BAO GIỜ tự thêm nguồn, con số, vùng giá, "
    "hoặc thông tin không có trong dữ liệu đầu vào.\n"
    "- Nếu không có dữ liệu cho một khía cạnh, viết 'Chưa có dữ liệu cập nhật' "
    "thay vì bịa số liệu.\n"
    "Viết bằng tiếng Việt tự nhiên, thuật ngữ tài chính chính xác."
)

TIERS = ["L1", "L2", "L3", "L4", "L5"]

TIER_MAX_TOKENS = {
    "L1": 2048,
    "L2": 3072,
    "L3": 4096,
    "L4": 4096,
    "L5": 6144,
}


@dataclass
class GeneratedArticle:
    """A fully generated tier article."""

    tier: str
    title: str
    content: str
    word_count: int
    llm_used: str
    generation_time_sec: float
    nq05_status: str = "pending"


@dataclass
class GenerationContext:
    """All data needed to generate articles."""

    coin_lists: dict[str, list[str]] = field(default_factory=dict)
    market_data: str = ""
    news_summary: str = ""
    onchain_data: str = ""
    key_metrics: dict[str, str | float] = field(default_factory=dict)
    tier_context: dict[str, str] = field(default_factory=dict)
    interpretation_notes: str = ""
    economic_events: str = ""
    recent_breaking: str = ""  # v0.19.0: breaking news context from last 24h


async def generate_tier_articles(
    llm: LLMAdapter,
    templates: dict[str, ArticleTemplate],
    context: GenerationContext,
) -> list[GeneratedArticle]:
    """Generate articles for all configured tiers.

    Args:
        llm: Multi-provider LLM adapter.
        templates: Per-tier templates from template_engine.
        context: Collected data for variable substitution.

    Returns:
        List of GeneratedArticle, one per tier that has templates.
    """
    articles: list[GeneratedArticle] = []
    metrics_table = render_key_metrics_table(context.key_metrics)

    for tier in TIERS:
        template = templates.get(tier)
        if not template:
            logger.warning(f"No template for tier {tier}, skipping")
            continue

        coins = context.coin_lists.get(tier, [])
        coin_str = ", ".join(coins) if coins else "N/A"

        variables = {
            "coin_list": coin_str,
            "coin_count": str(len(coins)),
            "market_data": context.market_data,
            "news_summary": context.news_summary,
            "onchain_data": context.onchain_data,
            "key_metrics_table": metrics_table,
            "tier": tier,
            "tier_context": context.tier_context.get(tier, ""),
            "interpretation_notes": context.interpretation_notes,
            "economic_events": context.economic_events,
            "recent_breaking": context.recent_breaking,
        }

        # Try generation with 1 retry on 429 rate limit errors
        for attempt in range(2):
            try:
                article = await _generate_single_article(llm, template, variables, tier)
                articles.append(article)
                logger.info(
                    f"Generated {tier}: {article.word_count} words "
                    f"via {article.llm_used} in {article.generation_time_sec:.1f}s"
                )
                # Rate limit cooldown: free-tier Gemini/Groq share RPM+TPM limits.
                if _TIER_COOLDOWN and tier != TIERS[-1]:
                    logger.info(f"Rate limit cooldown: waiting {_TIER_COOLDOWN}s before next tier")
                    await asyncio.sleep(_TIER_COOLDOWN)
                break  # success, move to next tier
            except Exception as e:
                if attempt == 0 and "429" in str(e):
                    logger.warning(
                        f"{tier} hit rate limit, waiting {_TIER_RETRY_WAIT}s before retry..."
                    )
                    await asyncio.sleep(_TIER_RETRY_WAIT)
                    continue  # retry once
                logger.error(f"Failed to generate {tier}: {e}")
                break  # give up on this tier

    logger.info(f"Generated {len(articles)}/{len(TIERS)} tier articles")
    return articles


async def _generate_single_article(
    llm: LLMAdapter,
    template: ArticleTemplate,
    variables: dict[str, str],
    tier: str,
) -> GeneratedArticle:
    """Generate a single tier article with dual-layer content (FR14)."""
    start = time.monotonic()

    sections = render_sections(template, variables)

    # Build combined prompt for all sections
    section_prompts = []
    for sec in sections:
        section_prompts.append(
            f"## {sec.section_name}\n{sec.prompt}\n(Tối đa {sec.max_words} từ cho phần này)"
        )

    full_prompt = (
        f"Viết bài phân tích thị trường tier {tier} cho cộng đồng CIC.\n\n"
        f"HƯỚNG DẪN PHÂN TÍCH CHO TIER NÀY:\n"
        f"{variables.get('tier_context', '')}\n\n"
        f"Danh sách coin: {variables.get('coin_list', 'N/A')}\n\n"
        f"⚠️ QUY TẮC DỮ LIỆU TUYỆT ĐỐI:\n"
        f"Bạn CHỈ được sử dụng dữ liệu bên dưới. KHÔNG ĐƯỢC:\n"
        f"- Tự thêm nguồn (Glassnode, Bloomberg, CryptoQuant, TradingView...)\n"
        f"- Tự bịa vùng giá support/resistance\n"
        f"- Tự tạo con số % tăng/giảm không có trong dữ liệu\n"
        f"- Viết 'theo [nguồn X]' nếu nguồn X không nằm trong dữ liệu dưới đây\n"
        f"Nếu thiếu dữ liệu → viết 'Chưa có dữ liệu cập nhật', KHÔNG bịa.\n\n"
        f"DỮ LIỆU THỊ TRƯỜNG (nguồn: CoinLore, CoinGecko, yfinance):\n"
        f"{variables.get('market_data') or 'Không có dữ liệu'}\n\n"
        f"TIN TỨC (nguồn: CoinDesk, CoinTelegraph, Decrypt, RSS feeds):\n"
        f"{variables.get('news_summary') or 'Không có tin tức'}\n\n"
        f"DỮ LIỆU ON-CHAIN & DERIVATIVES (nguồn: Glassnode, Binance Futures, Bybit, OKX, FRED):\n"
        f"{variables.get('onchain_data') or 'Không có dữ liệu'}\n\n"
        f"BẢNG CHỈ SỐ CHÍNH (nguồn: tổng hợp từ các API trên):\n"
        f"{variables.get('key_metrics_table', 'N/A')}\n\n"
    )
    # Add economic calendar events if available (FR60)
    econ_events = variables.get("economic_events", "")
    if econ_events:
        full_prompt += (
            f"LỊCH SỰ KIỆN KINH TẾ VĨ MÔ (nguồn: FairEconomy):\n{econ_events}\n"
            "→ Trích dẫn CỤ THỂ: tên sự kiện, ngày giờ, số liệu forecast/previous.\n"
            "→ Chú ý phân biệt: sự kiện 'ĐÃ DIỄN RA' (kết quả thực tế) vs "
            "'SẮP TỚI' (cần theo dõi). KHÔNG viết sự kiện đã qua như 'sắp tới'.\n\n"
        )
    # Add recent breaking news context (v0.19.0 — pipeline context sharing)
    breaking_ctx = variables.get("recent_breaking", "")
    if breaking_ctx:
        full_prompt += (
            f"SỰ KIỆN BREAKING GẦN ĐÂY (24h qua — PHẢI nhắc đến trong bài):\n{breaking_ctx}\n"
            "→ Bài viết sáng nay PHẢI cập nhật tình hình sau các sự kiện trên.\n\n"
        )
    # Add interpretation notes if available
    interp = variables.get("interpretation_notes", "")
    if interp:
        full_prompt += (
            f"DIỄN GIẢI QUAN TRỌNG (dùng để phân tích sâu, KHÔNG copy nguyên văn):\n{interp}\n\n"
        )
    full_prompt += (
        "ĐỊNH DẠNG BẮT BUỘC (Markdown):\n"
        "- BẮT BUỘC dùng ## cho tiêu đề mỗi section\n"
        "- BẮT BUỘC dùng **bold** cho số liệu quan trọng và từ khóa nổi bật\n"
        "- Dùng - cho bullet points khi liệt kê\n"
        "- Dùng *italic* cho nguồn trích dẫn\n\n"
        "CẤU TRÚC MỖI SECTION (BẮT BUỘC theo đúng format này):\n"
        "## [Tên section]\n"
        "**Tóm lược:** [2-3 câu ngắn gọn, ai đọc cũng hiểu, KHÔNG dùng thuật ngữ, "
        "PHẢI có insight/nhận định rõ ràng — không chỉ lặp lại số liệu]\n\n"
        "**Phân tích chi tiết:**\n"
        "[Phân tích chuyên sâu với số liệu cụ thể. PHẢI giải thích Ý NGHĨA — "
        "tại sao con số đó quan trọng, nó cho thấy điều gì, "
        "mối quan hệ với các chỉ số khác ra sao]\n\n"
        "VÍ DỤ OUTPUT ĐÚNG:\n"
        "## Tổng quan thị trường\n"
        "**Tóm lược:** Thị trường đang trong vùng **sợ hãi cực độ** (Fear & Greed: 16) — "
        "đây thường là vùng tích lũy trước đợt tăng mới. BTC giảm nhẹ **0.5%** nhưng "
        "vốn hóa vẫn giữ trên **$1,400B**, cho thấy lực bán đang yếu dần.\n\n"
        "**Phân tích chi tiết:**\n"
        "- **BTC $71,115** (-0.5%) — biến động rất nhẹ, volume **$42.3B** không đột biến "
        "→ thị trường đang chờ đợi catalyst mới...\n\n"
        "YÊU CẦU PHÂN TÍCH (BẮT BUỘC — đây là tiêu chí đánh giá bài viết):\n"
        "1. SO SÁNH: Khi có 2+ chỉ số, PHẢI so sánh và chỉ ra mâu thuẫn/đồng thuận.\n"
        "   VD: 'BTC giảm **2%** NHƯNG volume tăng **30%** → có lực mua mạnh đang bắt đáy'\n"
        "2. GIẢI THÍCH Ý NGHĨA: Mỗi con số PHẢI kèm giải thích nó có nghĩa gì.\n"
        "   VD: 'Fear & Greed Index ở mức **16** (sợ hãi cực độ) — "
        "lịch sử cho thấy đây thường là vùng tích lũy trước đợt phục hồi'\n"
        "3. MỐI QUAN HỆ NHÂN QUẢ: Chỉ ra chuỗi tác động giữa các yếu tố.\n"
        "   VD: 'DXY tăng **0.8%** → USD mạnh lên → BTC chịu áp lực giảm vì "
        "dòng tiền chảy về USD'\n\n"
        "LƯU Ý:\n"
        "- KHÔNG dùng 'TL;DR' — dùng '**Tóm lược:**' thay thế\n"
        "- CHỈ sử dụng dữ liệu được cung cấp ở trên. KHÔNG tự tạo tin/số liệu.\n"
        "- Nếu không có dữ liệu cho phần nào, ghi 'Chưa có dữ liệu cập nhật'.\n\n"
        "⛔ KIỂM TRA CUỐI CÙNG (bắt buộc trước khi trả lời):\n"
        "- Mọi nguồn bạn cite PHẢI nằm trong: CoinLore, CoinGecko, yfinance, "
        "Glassnode, Binance Futures, Bybit, OKX, FRED, alternative.me, FairEconomy, "
        "Messari, và các nguồn tin RSS được liệt kê ở trên.\n"
        "- KHÔNG ĐƯỢC cite: Bloomberg, CryptoQuant, TradingView, "
        "Santiment, IntoTheBlock, Chainalysis (trừ khi có trong TIN TỨC ở trên).\n"
        "- Mọi con số trong bài PHẢI truy nguyên được về dữ liệu ở trên.\n\n"
        "CÁC PHẦN BÀI VIẾT:\n\n" + "\n\n".join(section_prompts)
    )

    response: LLMResponse = await llm.generate(
        prompt=full_prompt,
        system_prompt=NQ05_SYSTEM_PROMPT,
        max_tokens=TIER_MAX_TOKENS.get(tier, 4096),
        temperature=0.5,
    )

    content = response.text.strip()

    # Validate response quality — reject too-short or empty responses
    word_count_raw = len(content.split())
    if word_count_raw < 50:
        raise LLMError(
            f"LLM response too short for {tier}: {word_count_raw} words (min 50)",
            source="article_generator",
        )

    content_with_disclaimer = content + DISCLAIMER
    word_count = len(content_with_disclaimer.split())
    elapsed = time.monotonic() - start

    return GeneratedArticle(
        tier=tier,
        title=f"[{tier}] Phân tích thị trường tài sản mã hóa",
        content=content_with_disclaimer,
        word_count=word_count,
        llm_used=response.model,
        generation_time_sec=elapsed,
    )
