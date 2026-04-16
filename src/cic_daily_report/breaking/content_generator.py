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
from cic_daily_report.generators.article_generator import (
    DISCLAIMER_SHORT,
    NQ05_SYSTEM_PROMPT,
)
from cic_daily_report.generators.nq05_filter import check_and_fix
from cic_daily_report.generators.text_utils import truncate_to_limit

logger = get_logger("breaking_content")

# 4000 not 4096 — leave room for Telegram formatting overhead
BREAKING_MAX_CHARS = 4000

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
{consensus_section}
{recent_events}
{enrichment_context}
NHIỆM VỤ: Viết bản tin {word_target} từ, tiếng Việt.

FORMAT (KHÔNG thêm nguồn hay disclaimer — hệ thống tự thêm):
- Dòng 1: 📌 Tiêu đề ngắn gọn (tên tài sản/tổ chức + con số nếu có)
- (dòng trống)
- Đoạn 1 — CHUYỆN GÌ XẢY RA (3-5 câu): Trích xuất từ <source> — \
ai làm gì, **con số** cụ thể, quy mô, timeline. Dùng **bold** cho mọi số liệu.
- (dòng trống)
- Đoạn 2 — TẠI SAO QUAN TRỌNG cho CIC (2-3 câu): \
Nêu hệ quả CỤ THỂ cho nhà đầu tư chiến lược dài hạn. \
KHÔNG lặp lại thông tin đoạn 1. Nếu không có info mới → viết 1 câu ngắn hoặc bỏ qua.
{historical_instruction}
CÁCH KẾT THÚC MỖI ĐOẠN:
- Câu cuối = HỆ QUẢ CỤ THỂ (ai bị ảnh hưởng, bao nhiêu, khi nào)
- KHÔNG viết câu chung chung kiểu "Điều này cho thấy...", \
"có thể ảnh hưởng đến...", "trong bối cảnh..."

GIỌNG VĂN TRUNG LẬP:
- Tin tốt → nêu sự kiện + con số, KHÔNG tô hồng
- Tin xấu (hack, lỗ hổng, sụp đổ) → nêu rủi ro THẬT, KHÔNG giảm nhẹ
- Đưa SỰ KIỆN, không đưa ý kiến

NHIỀU CHỦ ĐỀ TRONG SOURCE:
- Nếu <source> chứa NHIỀU sự kiện không liên quan → chỉ viết về sự kiện \
QUAN TRỌNG NHẤT (ưu tiên: con số cụ thể > quy mô lớn > ảnh hưởng rộng).

KHI THIẾU THÔNG TIN:
- Source chỉ có tiêu đề → viết ngắn 2-3 câu, KHÔNG suy diễn thêm.
- Không có số liệu → KHÔNG bịa số.
- Không có data thị trường → bỏ qua.

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
- Dòng 1: 📌 Tiêu đề tổng hợp (nêu chủ đề chung nếu có, hoặc "Tổng hợp tin")
- Từng sự kiện: đánh số (1️⃣ 2️⃣ 3️⃣...), tiêu đề ngắn + 2-3 câu trích từ <source>
- Dùng **bold** cho MỌI số liệu (giá, %, số lượng, ngày)
- Cuối mỗi item = 1 câu HỆ QUẢ CỤ THỂ (ai bị ảnh hưởng, bao nhiêu)
- Cuối bài: 📊 1-2 câu kết nối bức tranh chung bằng NHÂN QUẢ

KHÔNG viết câu chung chung kiểu "Điều này cho thấy...", \
"có thể ảnh hưởng đến...", "trong bối cảnh...". \
Thay bằng HỆ QUẢ CỤ THỂ hoặc bỏ qua.

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


# v0.33.0 (VD-29): Map internal source names to user-friendly Vietnamese labels.
# WHY: "market_data" / "market_trigger" are internal identifiers that leak into
# Telegram messages without this mapping.
_SOURCE_DISPLAY_MAP: dict[str, str] = {
    "market_data": "Dữ liệu thị trường",
    "market_trigger": "Cảnh báo thị trường",
}


def _format_source_link(source: str, url: str) -> str:
    """Format source as Telegram HTML hyperlink (PA E)."""
    import html as _html

    display_name = _SOURCE_DISPLAY_MAP.get(source, source)
    safe_source = _html.escape(display_name)
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
    consensus_snapshot: str = "",
    cross_asset_context: str = "",
    polymarket_shift: str = "",
    breaking_history: str = "",
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
        consensus_snapshot: QO.19 — Current market consensus text (from consensus_engine).
            If empty, the consensus section is omitted from the prompt.
        cross_asset_context: QO.36 — Cross-asset correlation data (e.g., "BTC dropped
            while Gold surged — risk-off signal"). Empty string = omitted from prompt.
        polymarket_shift: QO.36 — Polymarket prediction shift text (e.g., "BTC 100K
            probability dropped from 65% to 52% in 24h"). Empty = omitted.
        breaking_history: QO.36 — Recent related events from breaking history for
            dedup context. Different from recent_events: this is filtered to events
            related to the SAME topic/asset. Empty = omitted.

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

    # QO.19: Consensus snapshot — current market consensus from consensus_engine.
    # WHY in prompt: gives LLM context to write more relevant "TẠI SAO QUAN TRỌNG"
    # section by connecting the event to current market sentiment.
    consensus_section_text = (
        f"\nĐồng thuận thị trường hiện tại:\n{consensus_snapshot}"
        if consensus_snapshot.strip()
        else ""
    )

    # QO.36: Cross-asset correlation data — helps LLM identify risk-on/risk-off signals.
    # WHY conditional: only meaningful when actual correlation data exists.
    cross_asset_section = (
        f"\nTương quan liên thị trường:\n{cross_asset_context}"
        if cross_asset_context.strip()
        else ""
    )

    # QO.36: Polymarket prediction shift — shows how betting markets reacted.
    # WHY valuable: prediction markets reflect real-money sentiment shifts,
    # more reliable than social media sentiment.
    polymarket_section = (
        f"\nDịch chuyển thị trường dự đoán:\n{polymarket_shift}" if polymarket_shift.strip() else ""
    )

    # QO.36: Breaking history for related events — helps LLM avoid repeating
    # information and provides continuity context.
    # WHY separate from recent_events: this is filtered to same topic/asset,
    # while recent_events is a general list of all recent breaking events.
    history_section = (
        f"\nLịch sử tin liên quan:\n{breaking_history}" if breaking_history.strip() else ""
    )

    # Combine QO.36 enrichment into a single block
    enrichment_text = cross_asset_section + polymarket_section + history_section

    # QO.19: Historical parallel instruction — ask LLM to reference similar past events.
    # WHY conditional: only include when the event is significant enough (critical/important)
    # to warrant historical comparison. Notable events are too minor for parallels.
    historical_instruction_text = ""
    if severity in ("critical", "important"):
        historical_instruction_text = (
            "\n- (Nếu có thể) 1 câu THAM CHIẾU LỊCH SỬ: "
            "sự kiện tương tự trong quá khứ và BTC/thị trường đã phản ứng thế nào. "
            "Ví dụ: 'Lần cuối Fed tăng lãi suất 75 bps (06/2022), BTC giảm 15% trong 48h.' "
            "CHỈ viết khi có sự kiện tương đồng RÕ RÀNG, KHÔNG ép.\n"
        )

    prompt = BREAKING_PROMPT_TEMPLATE.format(
        title=event.title,
        source=event.source,
        url=event.url,
        summary_section=summary_section,
        market_context=market_section,
        consensus_section=consensus_section_text,
        recent_events=recent_section,
        enrichment_context=enrichment_text,
        word_target=word_target,
        historical_instruction=historical_instruction_text,
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

    # v0.33.0: Guard against NQ05 filter stripping too much content.
    # WHY: REMOVE_FILLER_PATTERNS could delete most sentences, leaving <50 words.
    # Fallback to raw LLM output (still NQ05 keyword-checked, just not filler-stripped).
    if word_count < 50:
        logger.warning(
            f"Breaking content too short after NQ05 filter ({word_count} words), "
            "using pre-filter content"
        )
        clean_content = _DISCLAIMER_RE.sub("", response.text).rstrip()
        word_count = len(clean_content.split())

    logger.info(f"Breaking content generated: {word_count} words via {model_used}")

    # P1.25 + NQ05: Truncate body BEFORE appending suffix to guarantee the
    # mandatory DISCLAIMER is never cut off by the character limit.
    # QO.07 (VD-36): Breaking news uses short disclaimer — full version takes
    # 15-20% of a 300-400 word message. Daily articles keep full DISCLAIMER.
    source_html = _format_source_link(event.source, event.url)
    suffix = f"\n\n🔗 {source_html}" + DISCLAIMER_SHORT
    body_limit = BREAKING_MAX_CHARS - len(suffix)
    # BUG-15: Floor at 500 chars — if suffix is extremely long, body_limit
    # could go negative, causing text[:negative] → empty string → content lost.
    if body_limit < 500:
        body_limit = 500
    clean_content, was_truncated = truncate_to_limit(clean_content, body_limit)
    if was_truncated:
        logger.warning(
            f"Breaking content body truncated to fit suffix: body_limit={body_limit} chars"
        )
    content_with_disclaimer = clean_content + suffix

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
    # QO.07: Raw fallback is also a breaking message → short disclaimer
    content = RAW_DATA_TEMPLATE.format(
        title=event.title,
        source_link=_format_source_link(event.source, event.url),
        disclaimer=DISCLAIMER_SHORT,
    )

    return BreakingContent(
        event=event,
        content=content,
        word_count=len(content.split()),
        ai_generated=False,
        model_used="raw_data",
        image_url=event.image_url,
    )


def build_enrichment_context(
    market_data: list | None = None,
    prediction_data: object | None = None,
    dedup_entries: list | None = None,
    event_title: str = "",
) -> dict[str, str]:
    """QO.36: Build enrichment context dict for breaking content generation.

    Assembles cross-asset correlation, Polymarket shift, and related breaking
    history into text strings that can be passed to generate_breaking_content().

    Args:
        market_data: List of MarketDataPoint objects from market_data collector.
        prediction_data: PredictionMarketsData object from prediction_markets collector.
        dedup_entries: List of DedupEntry objects from dedup_manager (for history).
        event_title: Current event title (for finding related history).

    Returns:
        Dict with keys: cross_asset_context, polymarket_shift, breaking_history.
        Each value is a string (empty if data unavailable).

    WHY helper function: Keeps enrichment logic separate from the generation
    function. Caller (breaking_pipeline) builds context once and passes to
    generate_breaking_content() for each event.
    """
    result = {
        "cross_asset_context": "",
        "polymarket_shift": "",
        "breaking_history": "",
    }

    # 1. Cross-asset correlation data
    if market_data:
        result["cross_asset_context"] = _build_cross_asset_text(market_data)

    # 2. Polymarket prediction shift
    if prediction_data:
        result["polymarket_shift"] = _build_polymarket_shift_text(prediction_data)

    # 3. Related breaking history
    if dedup_entries and event_title:
        result["breaking_history"] = _build_related_history(dedup_entries, event_title)

    return result


def _build_cross_asset_text(market_data: list) -> str:
    """QO.36: Build cross-asset correlation text from market data.

    Identifies risk-on/risk-off signals by comparing crypto vs traditional
    asset movements. E.g., "BTC dropped while Gold surged — risk-off signal."

    WHY: Cross-asset correlation helps LLM write more insightful analysis.
    """
    btc_change = 0.0
    _eth_change = 0.0  # WHY prefixed: reserved for future ETH correlation logic
    gold_change = 0.0
    dxy_change = 0.0
    oil_change = 0.0
    vix_value = 0.0

    for dp in market_data:
        symbol = getattr(dp, "symbol", "")
        change = getattr(dp, "change_24h", 0.0)
        price = getattr(dp, "price", 0.0)
        data_type = getattr(dp, "data_type", "")
        if symbol == "BTC" and data_type == "crypto":
            btc_change = change
        elif symbol == "ETH" and data_type == "crypto":
            _eth_change = change
        elif symbol == "Gold":
            gold_change = change
        elif symbol == "DXY":
            dxy_change = change
        elif symbol == "Oil":
            oil_change = change
        elif symbol == "VIX":
            vix_value = price

    parts = []

    # Risk-off signal: BTC down + Gold up
    if btc_change < -2 and gold_change > 0.5:
        parts.append(
            f"BTC giam {btc_change:+.1f}% trong khi Vang tang {gold_change:+.1f}% "
            "— tin hieu risk-off"
        )
    # Risk-on signal: BTC up + Gold down
    elif btc_change > 2 and gold_change < -0.5:
        parts.append(
            f"BTC tang {btc_change:+.1f}% trong khi Vang giam {gold_change:+.1f}% "
            "— tin hieu risk-on"
        )

    # Dollar correlation: BTC vs DXY
    if abs(btc_change) > 2 and abs(dxy_change) > 0.5:
        if (btc_change > 0 and dxy_change < 0) or (btc_change < 0 and dxy_change > 0):
            parts.append(
                f"BTC ({btc_change:+.1f}%) va DXY ({dxy_change:+.1f}%) di nguoc — "
                "tuong quan am binh thuong"
            )
        else:
            parts.append(
                f"BTC ({btc_change:+.1f}%) va DXY ({dxy_change:+.1f}%) cung chieu — "
                "bat thuong, can theo doi"
            )

    # VIX fear signal
    if vix_value >= 30:
        parts.append(f"VIX = {vix_value:.1f} (>= 30) — thi truong truyen thong hoang so")

    # Oil spike
    if abs(oil_change) > 5:
        direction = "tang" if oil_change > 0 else "giam"
        parts.append(f"Dau {direction} {abs(oil_change):.1f}% — anh huong macro")

    return " | ".join(parts) if parts else ""


def _build_polymarket_shift_text(prediction_data: object) -> str:
    """QO.36: Build Polymarket prediction shift text.

    WHY: Polymarket reflects real-money bets — shifts in probabilities
    signal changes in informed sentiment.
    """
    markets = getattr(prediction_data, "markets", [])
    if not markets:
        return ""

    parts = []
    for market in markets[:5]:  # WHY limit 5: avoid prompt bloat
        question = getattr(market, "question", "")
        yes_prob = getattr(market, "outcome_yes", 0.0)
        volume = getattr(market, "volume", 0.0)
        if question and yes_prob > 0 and volume > 10000:
            # WHY format: concise for LLM context
            parts.append(
                f'"{question[:80]}" — Yes: {yes_prob * 100:.0f}% (vol: ${volume / 1000:.0f}K)'
            )

    if not parts:
        return ""

    return "Polymarket: " + " | ".join(parts)


def _build_related_history(dedup_entries: list, event_title: str) -> str:
    """QO.36: Find related events from breaking history.

    WHY: Gives LLM context about what was already reported on this topic,
    enabling it to write follow-up angles instead of repeating.
    """
    title_lower = event_title.lower()
    # WHY: Extract key entities from title for matching
    title_words = set(title_lower.split())
    # Filter to significant words (>3 chars, not common words)
    _STOP_WORDS = {"the", "and", "for", "that", "with", "from", "this", "have", "been"}
    key_words = {w for w in title_words if len(w) > 3 and w not in _STOP_WORDS}

    if not key_words:
        return ""

    related = []
    for entry in dedup_entries:
        entry_title = getattr(entry, "title", "").lower()
        entry_status = getattr(entry, "status", "")
        # WHY: Only include sent events (skip pending/skipped)
        if entry_status not in ("sent", "sent_geo_digest"):
            continue

        # Check word overlap between event title and history entry
        entry_words = set(entry_title.split())
        overlap = key_words & entry_words
        # WHY threshold 2: at least 2 key words must match for relevance
        if len(overlap) >= 2:
            detected_at = getattr(entry, "detected_at", "")
            related.append(f"- [{detected_at}] {getattr(entry, 'title', '')}")

    if not related:
        return ""

    # WHY limit 3: too much history bloats the prompt without adding value
    return "\n".join(related[:3])


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

    # v0.33.0: Guard against NQ05 filter stripping too much content.
    # WHY: REMOVE_FILLER_PATTERNS could delete most sentences, leaving <50 words.
    digest_word_count = len(clean_content.split())
    if digest_word_count < 50:
        logger.warning(
            f"Digest content too short after NQ05 filter ({digest_word_count} words), "
            "using pre-filter content"
        )
        clean_content = _DISCLAIMER_RE.sub("", response.text).rstrip()

    # P1.25 + NQ05: Truncate body BEFORE appending suffix to guarantee the
    # mandatory DISCLAIMER is never cut off by the character limit.
    # QO.07 (VD-36): Digest is breaking news → use short disclaimer.
    links = "\n".join(f"🔗 {_format_source_link(e.source, e.url)}" for e in events if e.url)
    suffix = f"\n\n{links}" + DISCLAIMER_SHORT
    body_limit = BREAKING_MAX_CHARS - len(suffix)
    # BUG-15: Floor at 500 chars — too many event links can make suffix huge,
    # pushing body_limit negative → text[:negative] → empty body → content lost.
    # When this happens, truncate the links list to fit.
    if body_limit < 500:
        max_link_chars = BREAKING_MAX_CHARS - 500 - len(DISCLAIMER_SHORT)
        links = links[:max_link_chars].rsplit("\n", 1)[0]  # Cut at last complete link
        suffix = f"\n\n{links}" + DISCLAIMER_SHORT
        body_limit = BREAKING_MAX_CHARS - len(suffix)
    clean_content, was_truncated = truncate_to_limit(clean_content, body_limit)
    if was_truncated:
        logger.warning(
            f"Digest content body truncated to fit suffix: body_limit={body_limit} chars"
        )
    content_with_links = clean_content + suffix

    logger.info(f"Digest generated: {len(events)} events via {model_used}")

    return BreakingContent(
        event=events[0],  # Primary event for metadata
        content=content_with_links,
        word_count=len(content_with_links.split()),
        ai_generated=True,
        model_used=model_used,
    )
