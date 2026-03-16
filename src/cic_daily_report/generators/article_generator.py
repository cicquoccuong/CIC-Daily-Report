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
_TIER_COOLDOWN = 60 if os.getenv("GITHUB_ACTIONS") == "true" else 0
_TIER_RETRY_WAIT = 120  # seconds to wait before retrying a failed tier (429)

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
    metrics_interpretation: object | None = None  # v0.21.0: MetricsInterpretation from engine
    narratives_text: str = ""  # v0.21.0: detected narratives from news
    sector_data: str = ""  # v0.21.0: sector/DeFi data from CoinGecko + DefiLlama


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
    previous_tiers_summary: list[str] = []  # v0.21.0: inter-tier context

    for tier in TIERS:
        template = templates.get(tier)
        if not template:
            logger.warning(f"No template for tier {tier}, skipping")
            continue

        coins = context.coin_lists.get(tier, [])
        coin_str = ", ".join(coins) if coins else "N/A"

        # v0.21.0: Build tier-specific interpretation from Metrics Engine
        tier_interpretation = context.interpretation_notes  # fallback to old format
        if context.metrics_interpretation is not None:
            try:
                tier_interpretation = context.metrics_interpretation.format_for_tier(tier)
            except Exception:
                pass  # fallback to old interpretation_notes

        # v0.21.0: Build inter-tier context (what previous tiers already covered)
        prev_context = ""
        if previous_tiers_summary:
            prev_context = (
                "⚠️ CÁC TIER TRƯỚC ĐÃ VIẾT (KHÔNG được lặp lại nội dung này):\n"
                + "\n".join(previous_tiers_summary)
            )

        variables = {
            "coin_list": coin_str,
            "coin_count": str(len(coins)),
            "market_data": context.market_data,
            "news_summary": context.news_summary,
            "onchain_data": context.onchain_data,
            "key_metrics_table": metrics_table,
            "tier": tier,
            "tier_context": context.tier_context.get(tier, ""),
            "interpretation_notes": tier_interpretation,
            "economic_events": context.economic_events,
            "recent_breaking": context.recent_breaking,
            "previous_tiers": prev_context,
            "narratives": context.narratives_text,
            "sector_data": context.sector_data,
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
                # v0.21.0: Build summary of this tier for inter-tier context
                summary = _summarize_tier_output(tier, article.content)
                previous_tiers_summary.append(summary)
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
        f"DỮ LIỆU ON-CHAIN & DERIVATIVES (nguồn: OKX, FRED):\n"
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
    # v0.21.0: Add sector data if available
    sector = variables.get("sector_data", "")
    if sector:
        full_prompt += f"{sector}\n\n"
    # v0.21.0: Add inter-tier context (what previous tiers already wrote)
    prev_tiers = variables.get("previous_tiers", "")
    if prev_tiers:
        full_prompt += f"{prev_tiers}\n\n"
    # v0.21.0: Add detected narratives
    narr = variables.get("narratives", "")
    if narr:
        full_prompt += f"{narr}\n\n"
    # Add interpretation notes if available (v0.21.0: now tier-specific from Metrics Engine)
    interp = variables.get("interpretation_notes", "")
    if interp:
        full_prompt += (
            f"PHÂN TÍCH DỮ LIỆU TỰ ĐỘNG (Metrics Engine — dùng làm nền tảng, "
            f"KHÔNG copy nguyên văn):\n{interp}\n\n"
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
        "KIẾN THỨC NỀN (dùng để DIỄN GIẢI dữ liệu, KHÔNG copy vào bài):\n"
        "- Funding Rate: phí mà long trả cho short (dương) hoặc ngược lại (âm).\n"
        "  Dương = thị trường thiên long/lạc quan. Âm = thiên short/bi quan.\n"
        "  Cực đoan (>0.05% hoặc <-0.03%) = rủi ro liquidation cascade.\n"
        "  ⚠️ SAI: 'Funding Rate dương cho thấy áp lực bán' (NGƯỢC LẠI!)\n"
        "  ⚠️ SAI: 'Funding Rate tích cực' (nó là phí, không phải tín hiệu tích cực)\n"
        "- Open Interest (OI): tổng hợp đồng derivatives đang mở.\n"
        "  OI tăng + giá tăng = trend mạnh, tiền mới vào.\n"
        "  OI tăng + giá giảm = short mới mở, rủi ro squeeze.\n"
        "  OI giảm = đóng vị thế, momentum yếu.\n"
        "  ⚠️ SAI: 'OI tăng là tín hiệu tăng giá' (phải xem cùng hướng giá)\n"
        "- Fear & Greed: 0-24 Extreme Fear, 25-49 Fear, 50 Neutral,\n"
        "  51-74 Greed, 75-100 Extreme Greed.\n"
        "  ⚠️ SAI: 'F&G thấp = vùng tích lũy trước đợt tăng' (KHÔNG CHẮC CHẮN,\n"
        "  đây là vi phạm NQ05 vì ngụ ý dự đoán giá)\n"
        "- BTC Dominance: % vốn hóa BTC so với toàn thị trường.\n"
        "  Tăng = tiền chảy về BTC (risk-off). Giảm = altcoin season.\n"
        "- DXY (Dollar Index): USD mạnh thường gây áp lực lên BTC.\n"
        "  Nhưng correlation KHÔNG phải lúc nào cũng đúng.\n\n"
        "YÊU CẦU PHÂN TÍCH (BẮT BUỘC — tiêu chí đánh giá bài viết):\n"
        "1. SO SÁNH: Khi có 2+ chỉ số, PHẢI so sánh và chỉ ra mâu thuẫn/đồng thuận.\n"
        "   VD: 'BTC giảm **2%** NHƯNG volume tăng **30%** → lực mua đang tăng'\n"
        "2. GIẢI THÍCH Ý NGHĨA: Mỗi con số PHẢI kèm giải thích nó có nghĩa gì.\n"
        "   VD: 'Fear & Greed ở mức **16** (sợ hãi cực độ) — thị trường đang hoảng loạn'\n"
        "3. MỐI QUAN HỆ NHÂN QUẢ: Chỉ ra chuỗi tác động giữa các yếu tố.\n"
        "   VD: 'DXY tăng **0.8%** → USD mạnh lên → BTC chịu áp lực giảm'\n\n"
        "⛔ VÍ DỤ SAI (TUYỆT ĐỐI KHÔNG viết kiểu này):\n"
        "- 'đây là vùng tích lũy trước đợt tăng mới' → DỰ ĐOÁN GIÁ = NQ05 violation\n"
        "- 'cơ hội tốt để tích lũy' → KHUYẾN NGHỊ MUA = NQ05 violation\n"
        "- 'smart money đang mua vào' → BỊA DỮ LIỆU (không có whale data)\n"
        "- 'theo Glassnode, MVRV đang ở mức...' → BỊA NGUỒN (không có MVRV trong data)\n"
        "- 'tương quan BTC-Gold đạt 0.85' → BỊA SỐ (không có correlation data)\n\n"
        "LƯU Ý:\n"
        "- KHÔNG dùng 'TL;DR' — dùng '**Tóm lược:**' thay thế\n"
        "- CHỈ sử dụng dữ liệu được cung cấp ở trên. KHÔNG tự tạo tin/số liệu.\n"
        "- Nếu không có dữ liệu cho phần nào, ghi 'Chưa có dữ liệu cập nhật'.\n"
        "- Khi trích dẫn tin tức, ƯU TIÊN kèm link nếu có trong dữ liệu.\n\n"
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

    # Post-generation validation: scan for common LLM fabrication patterns
    warnings = _validate_output(content, tier, variables.get("onchain_data", ""))
    for w in warnings:
        logger.warning(f"[{tier}] Post-gen validation: {w}")

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


# Metrics that the pipeline does NOT collect — if LLM mentions these, it fabricated them
_FABRICATED_METRIC_PATTERNS = [
    (r"\bMVRV\b", "MVRV"),
    (r"\bSOPR\b", "SOPR"),
    (r"\bExchange\s+Reserve", "Exchange Reserves"),
    (r"\bwhale\s+(?:movement|transaction|accumulation)", "whale data"),
    (r"\bliquidation\s+(?:data|map|level|cascade)", "liquidation data"),
    (r"\b(?:tương quan|correlation)\s*[=:]\s*[\d.]+", "correlation coefficient"),
    (r"\bNUPL\b", "NUPL"),
    (r"\bPuell\s+Multiple\b", "Puell Multiple"),
]


def _validate_output(content: str, tier: str, onchain_data: str) -> list[str]:
    """Post-generation validation: detect fabricated data and quality issues.

    Returns a list of warning strings (empty = all good).
    """
    import re

    warnings = []

    # Check for fabricated metrics not in pipeline data
    for pattern, name in _FABRICATED_METRIC_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            # Only flag if metric is NOT in the actual onchain data
            if name.upper() not in onchain_data.upper():
                warnings.append(f"Possibly fabricated metric: {name} (not in input data)")

    # L2 should mention multiple coins — warn if too few
    if tier == "L2":
        coin_symbols = [
            "BTC",
            "ETH",
            "SOL",
            "BNB",
            "XRP",
            "ADA",
            "DOGE",
            "AVAX",
            "DOT",
            "MATIC",
            "LINK",
            "UNI",
            "ATOM",
            "LTC",
            "NEAR",
            "APT",
            "ARB",
            "OP",
            "SUI",
        ]
        mentioned = sum(1 for s in coin_symbols if s in content.upper())
        if mentioned < 10:
            warnings.append(f"L2 only mentions {mentioned} coins (target: ≥10 of 19)")

    # Check for banned source citations (sources not in our pipeline)
    banned_sources = ["Bloomberg", "CryptoQuant", "TradingView", "Santiment", "IntoTheBlock"]
    for src in banned_sources:
        if src.lower() in content.lower():
            warnings.append(f"Banned source cited: {src} (not in pipeline data)")

    return warnings


# ---------------------------------------------------------------------------
# v0.21.0: Inter-tier context helpers
# ---------------------------------------------------------------------------

# Approximate tier focus for summary labels
_TIER_FOCUS = {
    "L1": "Tổng quan BTC/ETH, F&G, tin chính",
    "L2": "Altcoin, sector, BTC Dominance",
    "L3": "Nguyên nhân, macro, on-chain, nhân quả",
    "L4": "Rủi ro, derivatives, cảnh báo",
    "L5": "Scenario analysis, tổng hợp tín hiệu",
}


def _summarize_tier_output(tier: str, content: str) -> str:
    """Create a concise summary of a tier's output for inter-tier context.

    Extracts section titles and first sentence of each section to give
    the next tier a sense of what was already covered — without sending
    the full content (which would bloat the prompt).
    """
    import re

    focus = _TIER_FOCUS.get(tier, "")
    lines = content.split("\n")

    # Extract section headers and their first substantive line
    sections: list[str] = []
    for i, line in enumerate(lines):
        if line.startswith("## "):
            header = line.lstrip("# ").strip()
            # Find first non-empty line after header
            for j in range(i + 1, min(i + 5, len(lines))):
                candidate = lines[j].strip()
                if candidate and not candidate.startswith("#"):
                    # Take first 120 chars
                    snippet = candidate[:120]
                    if len(candidate) > 120:
                        snippet += "..."
                    sections.append(f"  - {header}: {snippet}")
                    break
            else:
                sections.append(f"  - {header}")

    summary_parts = [f"[{tier}] ({focus}):"]
    if sections:
        summary_parts.extend(sections[:6])  # max 6 sections
    else:
        # Fallback: first 200 chars of content
        preview = re.sub(r"\s+", " ", content[:200]).strip()
        summary_parts.append(f"  Nội dung: {preview}...")

    return "\n".join(summary_parts)
