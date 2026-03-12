"""BIC Chat Summary Generator — 1 summary post for BIC Chat group (FR15).

Generates market overview table + key highlights from already-generated articles.
Copy-paste ready for Telegram group.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from cic_daily_report.adapters.llm_adapter import LLMAdapter, LLMResponse
from cic_daily_report.core.logger import get_logger
from cic_daily_report.generators.article_generator import (
    DISCLAIMER,
    NQ05_SYSTEM_PROMPT,
    GeneratedArticle,
)
from cic_daily_report.generators.template_engine import render_key_metrics_table

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
) -> GeneratedSummary:
    """Generate BIC Chat summary from tier articles + metrics.

    Uses already-processed article content to save LLM tokens.
    """
    start = time.monotonic()

    metrics_table = render_key_metrics_table(key_metrics)

    # Extract key content from articles for context
    article_summaries = []
    for article in articles:
        # Take first 800 chars as excerpt
        excerpt = article.content[:800].replace(DISCLAIMER, "").strip()
        article_summaries.append(f"[{article.tier}]: {excerpt}...")

    articles_context = "\n".join(article_summaries) if article_summaries else "Không có dữ liệu"

    prompt = (
        "Viết 1 bài tóm tắt thị trường cho BIC Chat.\n\n"
        f"BẢNG CHỈ SỐ CHÍNH:\n{metrics_table}\n\n"
        f"TÓM TẮT TỪ CÁC BÀI PHÂN TÍCH:\n{articles_context}\n\n"
        "YÊU CẦU:\n"
        "1. Bảng tổng quan thị trường (dùng bảng chỉ số ở trên)\n"
        "2. 3-5 điểm nhấn quan trọng nhất (bullet points)\n"
        "3. Ngắn gọn, dễ đọc trên mobile\n"
        "4. Copy-paste ready cho Telegram group\n"
        "5. KHÔNG khuyến nghị mua/bán (NQ05)\n"
        "Tối đa 400 từ."
    )

    response: LLMResponse = await llm.generate(
        prompt=prompt,
        system_prompt=NQ05_SYSTEM_PROMPT,
        max_tokens=2048,
        temperature=0.5,
    )

    content = response.text.strip() + DISCLAIMER
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
