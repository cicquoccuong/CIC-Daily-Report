"""Breaking News Content Generator (Story 5.2) — AI-generated breaking summaries.

Reuses LLM adapter (QĐ2) and NQ05 filter (QĐ4). 300-400 words target,
up to 500 for critical events. Raw data fallback if all LLMs fail.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

try:
    import trafilatura
except ImportError:
    trafilatura = None  # type: ignore[assignment]

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
Viết bản tin BREAKING NEWS bằng tiếng Việt cho cộng đồng đầu tư crypto CIC.

**Sự kiện:** {title}
**Nguồn:** {source}
**Link:** {url}
{summary_section}
{market_context}
{recent_events}

Yêu cầu TUYỆT ĐỐI:
- Viết {word_target} từ
- KHÔNG bịa thêm dữ liệu, nguồn, hoặc con số không có ở trên
- KHÔNG đưa ra khuyến nghị mua/bán
- Dùng 'tài sản mã hóa' thay vì 'tiền điện tử'
- Dựa trên NỘI DUNG BÀI GỐC (nếu có), KHÔNG chỉ tiêu đề

Cấu trúc (CHỈ viết 3 phần, KHÔNG thêm nguồn hay tuyên bố miễn trừ):

1. **Tiêu đề** (1 dòng tiếng Việt, nêu rõ tên tài sản nếu có)

2. **Nội dung cốt lõi:** (3-4 câu)
   - Tóm tắt SỰ KIỆN + SỐ LIỆU quan trọng từ bài gốc
   - Ai liên quan? Quy mô bao lớn? Con số cụ thể nào?

3. **Bối cảnh & tác động:** (2-3 câu)
   - Tin này nằm trong xu hướng gì? (liên kết tin gần đây nếu có)
   - Ảnh hưởng CỤ THỂ gì đến thị trường/nhà đầu tư crypto?
   - Nếu có data thị trường, nối với bối cảnh hiện tại"""

DIGEST_PROMPT_TEMPLATE = """\
Viết bản tin TỔNG HỢP BREAKING NEWS bằng tiếng Việt cho cộng đồng CIC.

**Danh sách sự kiện ({count} tin):**
{events_list}

{market_context}

Yêu cầu TUYỆT ĐỐI:
- Viết 200-300 từ tổng hợp TẤT CẢ sự kiện trên
- KHÔNG bịa thêm dữ liệu, nguồn, hoặc con số
- KHÔNG đưa ra khuyến nghị mua/bán
- Dùng 'tài sản mã hóa' thay vì 'tiền điện tử'

Cấu trúc:
1. **Tiêu đề tổng hợp** (1 dòng, nêu chủ đề chung)
2. **Tóm tắt từng sự kiện** (1-2 câu mỗi sự kiện, dùng bullet points)
3. **Nhận định chung** (2 câu — xu hướng + tác động tổng thể)"""

RAW_DATA_TEMPLATE = """⚠️ AI không khả dụng — dữ liệu thô

📰 {title}
🔗 {source_link}

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


def _format_source_link(source: str, url: str) -> str:
    """Format source as Telegram HTML hyperlink (PA E)."""
    import html as _html

    safe_source = _html.escape(source)
    if url:
        return f'<a href="{url}">Nguồn: {safe_source} ↗</a>'
    return f"Nguồn: {safe_source}"


_TRAFILATURA_TIMEOUT = 8  # seconds — fail fast, fallback to title-only


async def _fetch_article_text(url: str, max_chars: int = 1500) -> str:
    """Fetch and extract article body text via trafilatura.

    Returns extracted text (max max_chars) or empty string on failure.
    Timeout: 8s — breaking news must be fast.
    """
    if trafilatura is None:
        return ""

    try:
        async with httpx.AsyncClient(timeout=_TRAFILATURA_TIMEOUT) as client:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()

        text = trafilatura.extract(resp.text, include_comments=False, include_tables=False)
        if text:
            return text[:max_chars]
    except Exception as e:
        logger.debug(f"Article extraction failed for {url}: {e}")
    return ""


async def generate_breaking_content(
    event: BreakingEvent,
    llm,
    severity: str = "notable",
    extra_banned_keywords: list[str] | None = None,
    market_context: str = "",
    recent_events: str = "",
    skip_enrichment: bool = False,
) -> BreakingContent:
    """Generate breaking news content for a detected event.

    Args:
        event: The breaking event to write about.
        llm: LLM adapter instance (from Story 3.1).
        severity: Event severity ("critical", "important", "notable").
        extra_banned_keywords: Additional NQ05 banned keywords from config.
        market_context: Brief market snapshot (BTC/ETH price, F&G, DXY).
        recent_events: Recent breaking events for cross-reference.
        skip_enrichment: v0.29.0 (B4) — skip article fetch when LLM is known down.

    Returns:
        BreakingContent with AI-generated content.

    Raises:
        LLMError: v0.29.0 (A4) — propagates to caller instead of silently
            returning raw_data_fallback. Caller decides whether to defer or skip.
    """
    word_target = "200-250" if severity == "critical" else "100-150"

    # Build summary section from raw_data if available
    summary_text = event.raw_data.get("summary", "") if event.raw_data else ""

    # v0.29.0 (B4): Skip article fetch when providers are known down
    if not skip_enrichment and not summary_text and event.url:
        article_text = await _fetch_article_text(event.url)
        if article_text:
            summary_text = article_text
            logger.info(f"Enriched breaking event with article text ({len(article_text)} chars)")

    summary_section = f"**Nội dung bài gốc:**\n{summary_text}\n" if summary_text else ""

    prompt = BREAKING_PROMPT_TEMPLATE.format(
        title=event.title,
        source=event.source,
        url=event.url,
        summary_section=summary_section,
        market_context=market_context,
        recent_events=recent_events,
        word_target=word_target,
    )

    # v0.29.0 (A4): No longer catch-and-swallow LLM errors.
    # Exception propagates to caller, which marks event as generation_failed.
    response = await llm.generate(
        prompt=prompt,
        max_tokens=2048,
        temperature=0.3,
        system_prompt=NQ05_SYSTEM_PROMPT,
    )

    # Apply NQ05 post-filter
    filtered = check_and_fix(response.text, extra_banned_keywords)

    # Strip any LLM-generated disclaimer to prevent duplication
    clean_content = _DISCLAIMER_RE.sub("", filtered.content).rstrip()

    word_count = len(clean_content.split())
    model_used = getattr(llm, "last_provider", response.model)

    logger.info(f"Breaking content generated: {word_count} words via {model_used}")

    # Append source hyperlink + standard disclaimer
    source_html = _format_source_link(event.source, event.url)
    content_with_disclaimer = clean_content + f"\n\n🔗 {source_html}" + DISCLAIMER

    return BreakingContent(
        event=event,
        content=content_with_disclaimer,
        word_count=len(content_with_disclaimer.split()),
        ai_generated=True,
        model_used=model_used,
        image_url=event.image_url,
    )


def _raw_data_fallback(event: BreakingEvent) -> BreakingContent:
    """Fallback: send raw event data when all LLMs fail."""
    content = RAW_DATA_TEMPLATE.format(
        title=event.title,
        source_link=_format_source_link(event.source, event.url),
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


async def generate_digest_content(
    events: list[BreakingEvent],
    llm,
    market_context: str = "",
) -> BreakingContent:
    """Generate a single digest message summarizing multiple breaking events.

    v0.29.0 (B5): When >DIGEST_THRESHOLD events need sending, generate one
    combined summary instead of individual messages to avoid spamming.

    Raises:
        LLMError: If LLM fails (caller should mark all events as generation_failed).
    """
    events_list = "\n".join(
        f"- [{e.source}] {e.title}" + (f" ({e.url})" if e.url else "") for e in events
    )

    prompt = DIGEST_PROMPT_TEMPLATE.format(
        count=len(events),
        events_list=events_list,
        market_context=market_context,
    )

    response = await llm.generate(
        prompt=prompt,
        max_tokens=2048,
        temperature=0.3,
        system_prompt=NQ05_SYSTEM_PROMPT,
    )

    filtered = check_and_fix(response.text)
    clean_content = _DISCLAIMER_RE.sub("", filtered.content).rstrip()
    model_used = getattr(llm, "last_provider", response.model)

    # Append links for all events
    links = "\n".join(f"🔗 {_format_source_link(e.source, e.url)}" for e in events if e.url)
    content_with_links = clean_content + f"\n\n{links}" + DISCLAIMER

    logger.info(f"Digest generated: {len(events)} events via {model_used}")

    return BreakingContent(
        event=events[0],  # Primary event for metadata
        content=content_with_links,
        word_count=len(content_with_links.split()),
        ai_generated=True,
        model_used=model_used,
    )
