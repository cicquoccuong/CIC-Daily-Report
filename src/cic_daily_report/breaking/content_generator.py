"""Breaking News Content Generator (Story 5.2) — AI-generated breaking summaries.

Reuses LLM adapter (QĐ2) and NQ05 filter (QĐ4). 300-400 words target,
up to 500 for critical events. Raw data fallback if all LLMs fail.
"""

from __future__ import annotations

from dataclasses import dataclass

from cic_daily_report.breaking.event_detector import BreakingEvent
from cic_daily_report.core.logger import get_logger
from cic_daily_report.generators.article_generator import DISCLAIMER, NQ05_SYSTEM_PROMPT
from cic_daily_report.generators.nq05_filter import check_and_fix

logger = get_logger("breaking_content")

BREAKING_PROMPT_TEMPLATE = """\
Bạn là chuyên gia phân tích tài sản mã hóa cho CIC (Crypto Inner Circle).

Viết bản tin BREAKING NEWS bằng tiếng Việt dựa trên sự kiện sau:

**Tiêu đề:** {title}
**Nguồn:** {source}
**URL:** {url}

Yêu cầu:
- Viết {word_target} từ
- Bao gồm: tóm tắt sự kiện, bối cảnh thị trường, tác động tiềm năng
- Ghi nguồn tin (attribution)
- Định dạng tối ưu cho đọc trên Telegram mobile
- KHÔNG đưa ra khuyến nghị mua/bán

Cấu trúc:
1. Tiêu đề ngắn gọn (1 dòng)
2. Tóm tắt sự kiện (2-3 câu)
3. Bối cảnh & Phân tích (2-3 đoạn)
4. Tác động tiềm năng (1-2 đoạn)
5. Nguồn: {source}"""

RAW_DATA_TEMPLATE = """⚠️ AI không khả dụng — dữ liệu thô

📰 {title}
📌 Nguồn: {source}
🔗 {url}

{disclaimer}"""


@dataclass
class BreakingContent:
    """Generated breaking news content."""

    event: BreakingEvent
    content: str
    word_count: int
    ai_generated: bool
    model_used: str = ""
    image_url: str | None = None  # FR25: illustration image URL

    @property
    def formatted(self) -> str:
        """Format for Telegram delivery: emoji + headline + content."""
        return self.content


async def generate_breaking_content(
    event: BreakingEvent,
    llm,
    severity: str = "notable",
    extra_banned_keywords: list[str] | None = None,
) -> BreakingContent:
    """Generate breaking news content for a detected event.

    Args:
        event: The breaking event to write about.
        llm: LLM adapter instance (from Story 3.1).
        severity: Event severity ("critical", "important", "notable").
        extra_banned_keywords: Additional NQ05 banned keywords from config.

    Returns:
        BreakingContent with AI-generated or raw-data content.
    """
    word_target = "400-500" if severity == "critical" else "300-400"

    prompt = BREAKING_PROMPT_TEMPLATE.format(
        title=event.title,
        source=event.source,
        url=event.url,
        word_target=word_target,
    )

    try:
        response = await llm.generate(
            prompt=prompt,
            max_tokens=2048,
            temperature=0.5,
            system_prompt=NQ05_SYSTEM_PROMPT,
        )

        # Apply NQ05 post-filter
        filtered = check_and_fix(response.text, extra_banned_keywords)

        word_count = len(filtered.content.split())
        model_used = getattr(llm, "last_provider", response.model)

        logger.info(f"Breaking content generated: {word_count} words via {model_used}")

        return BreakingContent(
            event=event,
            content=filtered.content,
            word_count=word_count,
            ai_generated=True,
            model_used=model_used,
            image_url=event.image_url,
        )

    except Exception as e:
        logger.warning(f"All LLMs failed for breaking content: {e}")
        return _raw_data_fallback(event)


def _raw_data_fallback(event: BreakingEvent) -> BreakingContent:
    """Fallback: send raw event data when all LLMs fail."""
    content = RAW_DATA_TEMPLATE.format(
        title=event.title,
        source=event.source,
        url=event.url,
        disclaimer=DISCLAIMER,
    )

    return BreakingContent(
        event=event,
        content=content,
        word_count=len(content.split()),
        ai_generated=False,
        model_used="raw_data",
        image_url=event.image_url,
    )
