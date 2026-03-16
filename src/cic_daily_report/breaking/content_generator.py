"""Breaking News Content Generator (Story 5.2) — AI-generated breaking summaries.

Reuses LLM adapter (QĐ2) and NQ05 filter (QĐ4). 300-400 words target,
up to 500 for critical events. Raw data fallback if all LLMs fail.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from cic_daily_report.breaking.event_detector import BreakingEvent
from cic_daily_report.core.logger import get_logger
from cic_daily_report.generators.article_generator import DISCLAIMER, NQ05_SYSTEM_PROMPT
from cic_daily_report.generators.nq05_filter import check_and_fix

logger = get_logger("breaking_content")

# Pattern to strip LLM-generated disclaimers (prevents double disclaimer)
_DISCLAIMER_RE = re.compile(
    r"\n*-{2,}\n*⚠️.*$",
    re.DOTALL,
)

BREAKING_PROMPT_TEMPLATE = """\
Viết bản tin BREAKING NEWS ngắn gọn bằng tiếng Việt.

**Sự kiện:** {title}
**Nguồn:** {source}
**Link:** {url}
{summary_section}
Yêu cầu TUYỆT ĐỐI:
- Viết {word_target} từ — NGẮN GỌN, đi thẳng vào vấn đề
- KHÔNG viết nước đôi ("có thể tăng hoặc giảm", "tuy nhiên cũng có thể...")
- KHÔNG bịa thêm dữ liệu, nguồn, hoặc con số không có ở trên
- KHÔNG đưa ra khuyến nghị mua/bán
- Dùng 'tài sản mã hóa' thay vì 'tiền điện tử'
- ĐƯỢC PHÉP nêu tên cụ thể các tài sản (BTC, ETH, SOL...) khi liên quan đến sự kiện
- CHỈ phân tích dựa trên thông tin sự kiện ở trên, KHÔNG thêm bối cảnh bịa

Cấu trúc BẮT BUỘC (CHỈ viết 3 phần này, KHÔNG thêm nguồn hay tuyên bố miễn trừ):
1. **Tiêu đề** (1 dòng tiếng Việt, ngắn gọn, nêu rõ tên tài sản nếu có)
2. **Chuyện gì xảy ra:** (2-3 câu — SỰ KIỆN cụ thể, dùng dữ liệu từ trên)
3. **Tại sao quan trọng:** (2-3 câu — tác động trực tiếp đến thị trường)"""

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
    word_target = "200-250" if severity == "critical" else "100-150"

    # Build summary section from raw_data if available
    summary_text = event.raw_data.get("summary", "") if event.raw_data else ""
    summary_section = f"**Tóm tắt nguồn:** {summary_text}\n" if summary_text else ""

    prompt = BREAKING_PROMPT_TEMPLATE.format(
        title=event.title,
        source=event.source,
        url=event.url,
        summary_section=summary_section,
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

        # Strip any LLM-generated disclaimer to prevent duplication
        clean_content = _DISCLAIMER_RE.sub("", filtered.content).rstrip()

        word_count = len(clean_content.split())
        model_used = getattr(llm, "last_provider", response.model)

        logger.info(f"Breaking content generated: {word_count} words via {model_used}")

        # Append source link + standard disclaimer
        content_with_disclaimer = (
            clean_content + f"\n\n🔗 Nguồn: {event.source} — {event.url}" + DISCLAIMER
        )

        return BreakingContent(
            event=event,
            content=content_with_disclaimer,
            word_count=len(content_with_disclaimer.split()),
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
