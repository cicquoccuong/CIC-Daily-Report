"""Tier Article Generator — 5 tiers, cumulative (FR13-FR22).

Generates L1→L5 articles using templates + LLM adapter.
"""

from __future__ import annotations

import asyncio
import os
import re
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

# v0.31.0: Adaptive cooldown replaces fixed 60s — see llm.suggest_cooldown().
# Set to 0 in tests. In production, LLMAdapter.suggest_cooldown() calculates
# based on actual tokens used and provider-specific TPM limits.
_IS_PRODUCTION = os.getenv("GITHUB_ACTIONS") == "true"
_TIER_RETRY_WAIT = 120  # seconds to wait before retrying a failed tier (429)

# FR17: NQ05-compliant disclaimer (Vietnamese)
DISCLAIMER = (
    "\n\n---\n"
    "⚠️ *Tuyên bố miễn trừ trách nhiệm:* "
    "Nội dung trên chỉ mang tính chất thông tin và phân tích, "
    "KHÔNG phải lời khuyên đầu tư. Tài sản mã hóa có rủi ro cao. "
    "Hãy tự nghiên cứu (DYOR) trước khi đưa ra quyết định đầu tư."
)

# NQ05 prompt-layer instructions (QĐ4 Layer 1) — v0.26.0: investor-focused + anti-filler
NQ05_SYSTEM_PROMPT = (
    "VAI TRÒ: Bạn là nhà phân tích thị trường tài sản mã hóa cho cộng đồng CIC "
    "(Crypto Inner Circle). Thành viên CIC là NHÀ ĐẦU TƯ CHIẾN LƯỢC (không phải trader) "
    "— họ tích lũy dài hạn, dùng chiến lược ADCA, và đánh giá thị trường theo chu kỳ "
    "(Đông-Xuân-Hè-Thu). Họ bận rộn và chỉ đọc khi nội dung có GIÁ TRỊ thật sự.\n\n"
    "QUY TRÌNH PHÂN TÍCH (tuân thủ theo thứ tự):\n"
    "1. TỔNG HỢP: Đọc toàn bộ dữ liệu, xác định 3-5 điểm quan trọng nhất\n"
    "2. TÌM MÂU THUẪN: Chỉ số nào XUNG ĐỘT nhau? (VD: F&G thấp nhưng Funding Rate dương "
    "= retail sợ nhưng pro traders vẫn lạc quan — đây là insight có giá trị)\n"
    "3. DIỄN GIẢI cho NHÀ ĐẦU TƯ: Mỗi con số → ảnh hưởng gì đến người đang TÍCH LŨY dài hạn?\n"
    "4. KẾT NỐI NHÂN-QUẢ: Nối ít nhất 2 sự kiện/chỉ số thành chuỗi tác động logic\n"
    "5. TRÌNH BÀY: Kể câu chuyện thị trường — KHÔNG liệt kê số liệu rời rạc\n\n"
    "PHONG CÁCH: Chuyên nghiệp, rõ ràng, gần gũi. "
    "Thuật ngữ tài chính chính xác. Viết tiếng Việt tự nhiên.\n\n"
    "YÊU CẦU INSIGHT BẮT BUỘC (mỗi bài viết PHẢI có ÍT NHẤT):\n"
    "✓ 1 câu liên kết NHÂN-QUẢ giữa 2+ chỉ số (A xảy ra → B bị ảnh hưởng VÌ C)\n"
    "✓ 1 điều BẤT THƯỜNG hoặc MÂU THUẪN rút ra từ data (nếu tất cả bình thường → nói rõ)\n"
    "✓ 0 câu chỉ lặp lại số liệu mà không giải thích ý nghĩa\n\n"
    "NQ05: Chỉ phân tích và thông tin — dùng 'tài sản mã hóa' (không 'tiền điện tử').\n\n"
    "CHỐNG BỊA DỮ LIỆU:\n"
    "- CHỈ dùng data được cung cấp trong prompt. KHÔNG tự thêm nguồn, con số, vùng giá.\n"
    "- Nếu thiếu dữ liệu → bỏ qua phần đó, KHÔNG viết 'Chưa có dữ liệu'.\n"
    "- KHÔNG cite: Bloomberg, CryptoQuant, TradingView, Santiment, IntoTheBlock.\n\n"
)

TIERS = ["L1", "L2", "L3", "L4", "L5"]

TIER_MAX_TOKENS = {
    "L1": 2048,
    "L2": 3072,
    "L3": 4096,
    "L4": 4096,
    "L5": 6144,
}

# v0.26.0: Tier-specific temperature — analytical tiers get slightly higher temp
# for more creative causal reasoning and insight generation.
# L1-L2: 0.3 (factual, concise) | L3-L4: 0.4 (causal analysis) | L5: 0.45 (strategic)
TIER_TEMPERATURE = {
    "L1": 0.3,
    "L2": 0.3,
    "L3": 0.4,
    "L4": 0.4,
    "L5": 0.45,
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
    data_quality_notes: str = ""  # v0.21.0: quality warnings for LLM
    whale_data: str = ""  # v0.24.0: whale transaction summary from Whale Alert


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

        # v0.26.0: Build inter-tier context — L5 gets FULLER context for synthesis
        prev_context = ""
        if previous_tiers_summary:
            if tier == "L5":
                # L5 Master Investors need to SYNTHESIZE all previous tiers,
                # so give them richer summaries (not just dedup hints)
                prev_context = (
                    "=== NỘI DUNG CÁC TIER TRƯỚC (dùng để TỔNG HỢP, không lặp lại) ===\n"
                    "Bạn đang viết cho Master Investor — họ ĐÃ ĐỌC tất cả nội dung dưới đây.\n"
                    "Nhiệm vụ: TỔNG HỢP thành bức tranh chiến lược MỚI, không lặp.\n\n"
                    + "\n".join(previous_tiers_summary)
                )
            else:
                prev_context = (
                    "⚠️ CÁC TIER TRƯỚC ĐÃ VIẾT (KHÔNG được lặp lại nội dung này):\n"
                    + "\n".join(previous_tiers_summary)
                )

        # v0.21.0 Phase 3: Tier-specific data filtering — less noise for lower tiers
        filtered = _filter_data_for_tier(tier, context, metrics_table)
        filtered["data_quality_notes"] = context.data_quality_notes

        variables = {
            "coin_list": coin_str,
            "coin_count": str(len(coins)),
            "market_data": filtered["market_data"],
            "news_summary": filtered["news_summary"],
            "onchain_data": filtered["onchain_data"],
            "key_metrics_table": filtered["key_metrics_table"],
            "tier": tier,
            "tier_context": context.tier_context.get(tier, ""),
            "interpretation_notes": tier_interpretation,
            "economic_events": filtered["economic_events"],
            "recent_breaking": context.recent_breaking,
            "previous_tiers": prev_context,
            "narratives": filtered["narratives"],
            "sector_data": filtered["sector_data"],
            "whale_data": filtered["whale_data"],
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
                # v0.31.0: Adaptive cooldown based on provider + tokens used
                if _IS_PRODUCTION and tier != TIERS[-1]:
                    cooldown = llm.suggest_cooldown()
                    logger.info(
                        f"Adaptive cooldown: {cooldown}s "
                        f"({llm.last_provider}, {llm.last_tokens_used} tokens)"
                    )
                    await asyncio.sleep(cooldown)
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


def _get_tier_data_sources(tier: str) -> str:
    """Return tier-specific data source attribution string.

    Prevents L1 from claiming CoinGecko sector data it doesn't receive,
    and ensures each tier only cites sources whose data it actually gets.
    """
    sources = {
        "L1": "CoinLore, alternative.me",
        "L2": "CoinLore, CoinGecko, MEXC",
        "L3": "CoinLore, CoinGecko, yfinance, Coinalyze, CoinMetrics, FairEconomy, Whale Alert",
        "L4": "CoinLore, CoinGecko, yfinance, Coinalyze, CoinMetrics, FairEconomy, Whale Alert",
        "L5": "CoinLore, CoinGecko, yfinance, Coinalyze, CoinMetrics, FairEconomy, Whale Alert",
    }
    return sources.get(tier, "CoinLore, CoinGecko")


def _filter_data_for_tier(
    tier: str,
    context: GenerationContext,
    metrics_table: str,
) -> dict[str, str]:
    """Filter data blocks per tier to reduce noise and focus the LLM.

    L1: BTC/ETH prices + top news only (no on-chain, no sector, no econ calendar)
    L2: All market data + sector + news (no on-chain details)
    L3: Market + on-chain + macro + econ calendar (full analytical data)
    L4: On-chain + sector + econ (risk-focused, less news)
    L5: Top 20 news + on-chain + sector + econ (reduced from ALL to prevent 413)
    """
    full = {
        "market_data": context.market_data,
        "news_summary": context.news_summary,
        "onchain_data": context.onchain_data,
        "key_metrics_table": metrics_table,
        "economic_events": context.economic_events,
        "narratives": context.narratives_text,
        "sector_data": context.sector_data,
        "whale_data": context.whale_data,
    }

    if tier == "L1":
        # Beginners: only BTC/ETH prices, F&G, top 5 news headlines
        market_lines = context.market_data.split("\n")
        keywords = ["BTC:", "ETH:", "Fear", "Total_MCap"]
        btc_eth_lines = [ln for ln in market_lines if any(s in ln for s in keywords)]
        news_lines = context.news_summary.split("\n")
        # Keep first ~15 lines of news (roughly top 5 articles with summaries)
        short_news = "\n".join(news_lines[:15]) if news_lines else ""
        full["market_data"] = "\n".join(btc_eth_lines) if btc_eth_lines else context.market_data
        full["news_summary"] = short_news
        full["onchain_data"] = ""  # L1 doesn't analyze on-chain
        full["economic_events"] = ""  # L1 doesn't analyze macro events
        full["sector_data"] = ""  # L1 doesn't analyze sectors
        full["narratives"] = ""  # L1 just reports, doesn't need narrative context
        full["whale_data"] = ""  # L1 doesn't analyze whale activity

    elif tier == "L2":
        # Altcoin overview: full market + sector, no on-chain details
        full["onchain_data"] = ""  # L2 focuses on coins, not derivatives
        full["economic_events"] = ""  # macro is for L3+
        full["whale_data"] = ""  # L2 focuses on altcoins, not whale flow

    elif tier == "L3":
        # Deep analysis: full market + on-chain + macro, less news (already in L1/L2)
        news_lines = context.news_summary.split("\n")
        full["news_summary"] = "\n".join(news_lines[:10]) if news_lines else ""

    elif tier == "L4":
        # Risk analysis: on-chain + sector + macro focus, minimal news
        news_lines = context.news_summary.split("\n")
        full["news_summary"] = "\n".join(news_lines[:5]) if news_lines else ""

    elif tier == "L5":
        # v0.22.0: L5 was getting ALL data → Groq 413 Payload Too Large.
        # Reduce news to top 20 lines. Metrics Engine + narratives already summarize.
        news_lines = context.news_summary.split("\n")
        full["news_summary"] = "\n".join(news_lines[:20]) if news_lines else ""

    return full


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

    # v0.22.0: Restructured prompt — "context first, questions last" (Gemini best practice)
    # v0.28.0: Tier-specific data source headers to prevent wrong attribution
    data_sources = _get_tier_data_sources(tier)

    # Layer 1: ALL DATA (context for Gemini to process first)
    full_prompt = (
        f"=== DỮ LIỆU THỊ TRƯỜNG (nguồn: {data_sources}) ===\n"
        f"{variables.get('market_data') or 'Không có dữ liệu'}\n\n"
        f"=== BẢNG CHỈ SỐ CHÍNH ===\n"
        f"{variables.get('key_metrics_table', 'N/A')}\n\n"
    )
    # Optional data blocks
    news = variables.get("news_summary") or ""
    if news:
        full_prompt += f"=== TIN TỨC (nguồn: RSS feeds) ===\n{news}\n\n"
    onchain = variables.get("onchain_data") or ""
    if onchain:
        full_prompt += (
            f"=== DỮ LIỆU ON-CHAIN & DERIVATIVES "
            f"(nguồn: Coinalyze, CoinMetrics, OKX) ===\n{onchain}\n\n"
        )
    whale = variables.get("whale_data", "")
    if whale and "Không có dữ liệu" not in whale:
        full_prompt += f"=== WHALE ALERT (nguồn: Whale Alert) ===\n{whale}\n\n"
    sector = variables.get("sector_data", "")
    if sector:
        full_prompt += f"{sector}\n\n"
    econ_events = variables.get("economic_events", "")
    if econ_events:
        full_prompt += (
            f"=== LỊCH SỰ KIỆN KINH TẾ (nguồn: FairEconomy) ===\n{econ_events}\n"
            "Lưu ý: phân biệt sự kiện ĐÃ QUA vs SẮP TỚI.\n\n"
        )
    breaking_ctx = variables.get("recent_breaking", "")
    if breaking_ctx:
        full_prompt += f"=== SỰ KIỆN BREAKING 24H QUA ===\n{breaking_ctx}\n\n"
    narr = variables.get("narratives", "")
    if narr:
        full_prompt += f"{narr}\n\n"

    # Layer 2: METRICS ENGINE (pre-computed analysis — MANDATORY to use)
    interp = variables.get("interpretation_notes", "")
    if interp:
        full_prompt += (
            f"=== PHÂN TÍCH TỰ ĐỘNG (Metrics Engine) ===\n"
            f"Dùng kết quả này làm NỀN TẢNG phân tích. "
            f"Diễn giải bằng ngôn ngữ tự nhiên, KHÔNG copy nguyên văn.\n"
            f"{interp}\n\n"
        )

    # Layer 3: Data quality warnings
    dq_notes = variables.get("data_quality_notes", "")
    if dq_notes:
        full_prompt += f"{dq_notes}\n\n"

    # Layer 4: Inter-tier context (what previous tiers already wrote)
    prev_tiers = variables.get("previous_tiers", "")
    if prev_tiers:
        full_prompt += f"{prev_tiers}\n\n"

    # Layer 5: TASK + QUESTIONS (at the END — Gemini processes context first)
    full_prompt += (
        f"=== NHIỆM VỤ: Viết bài tier {tier} cho cộng đồng CIC ===\n"
        f"Danh sách coin: {variables.get('coin_list', 'N/A')}\n\n"
        f"{variables.get('tier_context', '')}\n\n"
    )

    # Layer 6: FORMAT + QUALITY RULES (concise, positive-first)
    # v0.28.0: Removed dual "Tóm lược/Phân tích chi tiết" format that caused within-tier repetition
    full_prompt += (
        "ĐỊNH DẠNG:\n"
        "- ## cho tiêu đề section (kèm emoji: 📈📉⚡📊🔍💡 tùy nội dung)\n"
        "- **bold** cho số liệu quan trọng, • cho bullet\n"
        "- Viết đoạn ngắn 2-3 câu, dễ đọc trên điện thoại\n"
        "- Mở đầu section = 1 câu insight chính, phân tích chi tiết liền sau\n\n"
        "CHẤT LƯỢNG:\n"
        "1. SO SÁNH 2+ chỉ số → đồng thuận hay mâu thuẫn?\n"
        "2. NHÂN QUẢ: A xảy ra → B bị ảnh hưởng VÌ C\n"
        "3. Mỗi số liệu = giải thích nó quan trọng THẾ NÀO cho nhà đầu tư\n\n"
        "CÁCH KẾT THÚC MỖI ĐOẠN:\n"
        "- Câu cuối = HỆ QUẢ CỤ THỂ (ai bị ảnh hưởng, bao nhiêu, khi nào)\n"
        "- KHÔNG viết câu chung chung kiểu 'Điều này cho thấy...', "
        "'có thể ảnh hưởng đến...', 'trong bối cảnh...', "
        "'cần theo dõi chặt chẽ...'\n"
        "- Thay bằng HỆ QUẢ CỤ THỂ hoặc bỏ qua\n\n"
        "⛔ KHÔNG:\n"
        "- Bịa data không có trong input (MVRV, SOPR, Bloomberg, TradingView...)\n"
        "- Bắt đầu section bằng 'TL;DR:' hoặc 'Tóm lược:'\n"
        "- Viết lời khuyên đầu tư ('nên mua', 'cần theo dõi', "
        "'quyết định đầu tư thông minh')\n\n"
        "CÁC PHẦN BÀI VIẾT:\n\n" + "\n\n".join(section_prompts)
    )

    response: LLMResponse = await llm.generate(
        prompt=full_prompt,
        system_prompt=NQ05_SYSTEM_PROMPT,
        max_tokens=TIER_MAX_TOKENS.get(tier, 4096),
        temperature=TIER_TEMPERATURE.get(tier, 0.3),
    )

    content = response.text.strip()

    # Validate response quality — reject too-short or empty responses
    word_count_raw = len(content.split())
    if word_count_raw < 50:
        raise LLMError(
            f"LLM response too short for {tier}: {word_count_raw} words (min 50)",
            source="article_generator",
        )

    # Post-generation validation: detect AND strip fabricated data (v0.28.0)
    content, warnings = _validate_and_clean_output(content, tier, variables.get("onchain_data", ""))
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


def _validate_and_clean_output(content: str, tier: str, onchain_data: str) -> tuple[str, list[str]]:
    """Post-generation validation: detect AND strip fabricated data.

    v0.28.0: Upgraded from warn-only to actively removing fabricated sentences.
    Returns (cleaned_content, list_of_warnings).
    """
    warnings = []
    cleaned = content

    # v0.31.0: Strip TL;DR prefixes that Google Sheets templates may inject.
    # Pattern: "TL;DR:" or "TL; DR:" at the start of a line (with optional whitespace)
    tldr_pattern = re.compile(r"^(\s*)(?:TL[;/]?\s*DR\s*[:.]?\s*)", re.IGNORECASE | re.MULTILINE)
    if tldr_pattern.search(cleaned):
        cleaned = tldr_pattern.sub(r"\1", cleaned)
        warnings.append("Stripped TL;DR prefix(es) from output")

    # Check for fabricated metrics not in pipeline data — REMOVE sentences containing them
    for pattern_str, name in _FABRICATED_METRIC_PATTERNS:
        pattern = re.compile(pattern_str, re.IGNORECASE)
        if pattern.search(cleaned):
            # Only act if metric is NOT in the actual onchain data
            if name.upper() not in onchain_data.upper():
                warnings.append(f"Fabricated metric REMOVED: {name} (not in input data)")
                # Remove lines containing the fabricated metric
                lines = cleaned.split("\n")
                cleaned = "\n".join(ln for ln in lines if not pattern.search(ln))

    # L2 should mention multiple coins — warn if too few
    # v0.28.0: Also count project names (Ripple → XRP) via coin_mapping
    if tier == "L2":
        from cic_daily_report.core.coin_mapping import extract_coins_from_text

        l2_coins = {
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
        }
        mentioned_coins = extract_coins_from_text(cleaned, l2_coins)
        if len(mentioned_coins) < 10:
            warnings.append(f"L2 only mentions {len(mentioned_coins)} coins (target: ≥10 of 19)")

    # Check for banned source citations — REMOVE sentences citing them
    banned_sources = ["Bloomberg", "CryptoQuant", "TradingView", "Santiment", "IntoTheBlock"]
    for src in banned_sources:
        pattern = re.compile(re.escape(src), re.IGNORECASE)
        if pattern.search(cleaned):
            warnings.append(f"Banned source REMOVED: {src} (not in pipeline data)")
            lines = cleaned.split("\n")
            cleaned = "\n".join(ln for ln in lines if not pattern.search(ln))

    # Clean up double blank lines from removals
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    return cleaned, warnings


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
    """Create structured summary of tier's key data points for dedup and synthesis.

    v0.26.0: Enhanced to provide richer context for L5 synthesis.
    Extracts specific data points (numbers, coins, key conclusions) so the
    next tier knows exactly what was already covered — preventing repetition
    while enabling L5 to synthesize a complete strategic picture.
    """
    focus = _TIER_FOCUS.get(tier, "")

    # Extract data points mentioned (numbers, percentages, coin names)
    numbers = re.findall(r"[\$€]?[\d,]+\.?\d*[%KMB]?", content)
    coins = re.findall(r"\b(?:BTC|ETH|SOL|BNB|XRP|ADA|DOGE|AVAX|TRX|LINK)\b", content)

    # Extract key conclusions (sentences with strong verbs or insight markers)
    sentences = re.split(r"[.!?\n]", content)
    key_sentences = [s.strip() for s in sentences if 30 < len(s.strip()) < 200][:7]

    parts = [f"[{tier}] ({focus}):"]
    if coins:
        parts.append(f"  Coins đã phân tích: {', '.join(sorted(set(coins)))}")
    if numbers:
        parts.append(f"  Số liệu đã dùng: {', '.join(numbers[:10])}")
    # v0.26.0: Include more key sentences for richer synthesis by L5
    for s in key_sentences[:5]:
        parts.append(f"  - {s[:200]}")

    return "\n".join(parts)
