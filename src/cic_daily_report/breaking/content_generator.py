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
Phóng viên thị trường tài sản mã hóa, viết cho cộng đồng CIC \
(nhà đầu tư chiến lược, đã có kiến thức — KHÔNG giải thích khái niệm cơ bản).

<source>
Tiêu đề: {title}
Nguồn: {source}
{summary_section}</source>
{market_context}
{recent_events}

NHIỆM VỤ: Viết bản tin {word_target} từ, tiếng Việt.

FORMAT (KHÔNG thêm nguồn hay disclaimer — hệ thống tự thêm):
- Dòng 1: 📌 Tiêu đề ngắn gọn tiếng Việt (tên tài sản/tổ chức + con số nếu có)
- (dòng trống)
- Đoạn 1 (3-5 câu): 📰 Trích xuất CHI TIẾT từ bài gốc trong <source> — \
ai làm gì, con số cụ thể, quy mô, timeline. Dùng **bold** cho số liệu quan trọng.
- (dòng trống)
- Đoạn 2 (2-3 câu): 📊 Bối cảnh — xu hướng gần đây, \
data thị trường (nếu được cung cấp), tác động cụ thể. **Bold** số liệu.

KHÔNG dùng heading cứng (Nội dung cốt lõi, Bối cảnh & tác động...). \
Viết đoạn ngắn 2-3 câu, cách nhau 1 dòng trống cho dễ đọc trên điện thoại.

KHI THIẾU THÔNG TIN:
- Source chỉ có tiêu đề → viết ngắn 2-3 câu từ tiêu đề, KHÔNG suy diễn thêm.
- Không có số liệu → KHÔNG bịa số. Mô tả định tính.
- Không có data thị trường → bỏ qua đoạn bối cảnh.

CHỈ dùng thông tin trong <source> và data được cung cấp. \
KHÔNG tự thêm nguồn, con số, hoặc trích dẫn. \
Dùng 'tài sản mã hóa' thay 'tiền điện tử'."""

DIGEST_PROMPT_TEMPLATE = """\
Phóng viên tài sản mã hóa, viết cho cộng đồng CIC \
(nhà đầu tư chiến lược, đã có kiến thức).

<source>
{events_list}
</source>
{market_context}

NHIỆM VỤ: Viết bản tổng hợp 200-300 từ cho {count} sự kiện trên, tiếng Việt.

FORMAT:
- Dòng 1: 📌 Tiêu đề tổng hợp (nêu chủ đề chung)
- Từng sự kiện: đánh số (1️⃣ 2️⃣ 3️⃣), tiêu đề ngắn + 2-3 câu chi tiết từ <source>, \
**bold** số liệu quan trọng
- Cuối: 📊 1-2 câu kết nối bức tranh chung

CHỈ dùng thông tin trong <source>. KHÔNG bịa thêm nguồn hay con số. \
Dùng 'tài sản mã hóa' thay 'tiền điện tử'."""

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


_TRAFILATURA_TIMEOUT = 12  # seconds — balance speed vs content depth


async def _fetch_article_text(url: str, max_chars: int = 3000) -> str:
    """Fetch and extract article body text via trafilatura.

    Returns extracted text (max max_chars) or empty string on failure.
    v0.30.0: Increased from 1500→3000 chars, 8→12s timeout for deeper content.
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
    word_target = "300-400" if severity == "critical" else "200-300"

    # Build summary section from raw_data if available
    summary_text = event.raw_data.get("summary", "") if event.raw_data else ""

    # v0.29.0 (B4): Skip article fetch when providers are known down
    if not skip_enrichment and not summary_text and event.url:
        article_text = await _fetch_article_text(event.url)
        if article_text:
            summary_text = article_text
            logger.info(f"Enriched breaking event with article text ({len(article_text)} chars)")

    # v0.30.1: Clean labels without markdown — prevent bold leaking into output
    summary_section = f"\nNội dung bài gốc:\n{summary_text}" if summary_text else ""

    # v0.30.0 (Fix 3.4): Only include market/recent context when meaningful
    market_section = (
        f"\nData thị trường hiện tại:\n{market_context}" if market_context.strip() else ""
    )
    recent_section = f"\nTin breaking gần đây:\n{recent_events}" if recent_events.strip() else ""

    prompt = BREAKING_PROMPT_TEMPLATE.format(
        title=event.title,
        source=event.source,
        url=event.url,
        summary_section=summary_section,
        market_context=market_section,
        recent_events=recent_section,
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
