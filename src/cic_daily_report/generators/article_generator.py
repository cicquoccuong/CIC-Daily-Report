"""Tier Article Generator — 5 tiers, dual-layer, cumulative (FR13-FR22).

Generates L1→L5 articles using templates + LLM adapter.
Each article has TL;DR (simple) + Full Analysis (technical).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from cic_daily_report.adapters.llm_adapter import LLMAdapter, LLMResponse
from cic_daily_report.core.logger import get_logger
from cic_daily_report.generators.template_engine import (
    ArticleTemplate,
    render_key_metrics_table,
    render_sections,
)

logger = get_logger("article_generator")

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
    "- Trích nguồn rõ ràng: 'Theo CoinLore...', 'Dữ liệu Glassnode cho thấy...'\n"
    "Viết bằng tiếng Việt tự nhiên, thuật ngữ tài chính chính xác."
)

TIERS = ["L1", "L2", "L3", "L4", "L5"]


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

    def to_row(self) -> list[Any]:
        """Convert to row for NOI_DUNG_DA_TAO sheet."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        return [
            now,
            self.tier,
            self.title,
            self.content,
            self.word_count,
            self.llm_used,
            f"{self.generation_time_sec:.1f}s",
            self.nq05_status,
        ]


@dataclass
class GenerationContext:
    """All data needed to generate articles."""

    coin_lists: dict[str, list[str]] = field(default_factory=dict)
    market_data: str = ""
    news_summary: str = ""
    onchain_data: str = ""
    key_metrics: dict[str, str | float] = field(default_factory=dict)


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
        }

        try:
            article = await _generate_single_article(llm, template, variables, tier)
            articles.append(article)
            logger.info(
                f"Generated {tier}: {article.word_count} words "
                f"via {article.llm_used} in {article.generation_time_sec:.1f}s"
            )
        except Exception as e:
            logger.error(f"Failed to generate {tier}: {e}")
            continue

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
        f"Danh sách coin: {variables.get('coin_list', 'N/A')}\n\n"
        f"DỮ LIỆU THỊ TRƯỜNG (dùng số liệu này, KHÔNG tự bịa):\n"
        f"{variables.get('market_data') or 'Không có dữ liệu'}\n\n"
        f"TIN TỨC MỚI NHẤT (chỉ phân tích tin dưới đây, KHÔNG bịa tin):\n"
        f"{variables.get('news_summary') or 'Không có tin tức'}\n\n"
        f"DỮ LIỆU ON-CHAIN:\n"
        f"{variables.get('onchain_data') or 'Không có dữ liệu'}\n\n"
        f"BẢNG CHỈ SỐ CHÍNH:\n"
        f"{variables.get('key_metrics_table', 'N/A')}\n\n"
        "BÀI VIẾT CẦN CÓ 2 LỚP (FR14 Dual-Layer):\n"
        "1. **TL;DR** — Ngôn ngữ đơn giản, không thuật ngữ, 2-3 dòng per section\n"
        "2. **Phân tích chi tiết** — Chuyên sâu, có số liệu, thuật ngữ chính xác\n\n"
        "QUAN TRỌNG: CHỈ sử dụng dữ liệu được cung cấp ở trên. "
        "KHÔNG tự tạo tin tức, sự kiện, hoặc số liệu. "
        "Nếu không có dữ liệu cho phần nào, ghi 'Chưa có dữ liệu cập nhật'.\n\n"
        "CÁC PHẦN BÀI VIẾT:\n\n" + "\n\n".join(section_prompts)
    )

    response: LLMResponse = await llm.generate(
        prompt=full_prompt,
        system_prompt=NQ05_SYSTEM_PROMPT,
        max_tokens=4096,
        temperature=0.3,
    )

    content = response.text.strip()

    # Validate response quality — reject too-short or empty responses
    word_count_raw = len(content.split())
    if word_count_raw < 50:
        raise ValueError(
            f"LLM response too short for {tier}: {word_count_raw} words (min 50)"
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
