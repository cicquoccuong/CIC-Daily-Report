"""Breaking News Content Generator (Story 5.2) — AI-generated breaking summaries.

Reuses LLM adapter (QĐ2) and NQ05 filter (QĐ4). 300-400 words target,
up to 500 for critical events. Raw data fallback if all LLMs fail.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

try:
    import trafilatura
except ImportError:
    trafilatura = None  # type: ignore[assignment]

from cic_daily_report.adapters.llm_adapter import append_nq05_disclaimer
from cic_daily_report.breaking.event_detector import BreakingEvent
from cic_daily_report.core.config import _wave_0_6_date_block_enabled, _wave_0_6_enabled
from cic_daily_report.core.logger import get_logger
from cic_daily_report.generators.article_generator import NQ05_SYSTEM_PROMPT
from cic_daily_report.generators.nq05_constants import DISCLAIMER_SHORT
from cic_daily_report.generators.nq05_filter import check_and_fix
from cic_daily_report.generators.numeric_sanity import apply_all_numeric_guards
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
(cộng đồng CIC đã có kiến thức cơ bản về crypto — KHÔNG giải thích khái niệm cơ bản).

<source>
Tiêu đề: {title}
Nguồn: {source}
{summary_section}</source>
{market_context}{price_lock}
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
- Đoạn 2 — TẠI SAO QUAN TRỌNG cho CIC: 2-3 câu hệ quả cho cộng đồng CIC. \
CHỈ viết khi có data từ source article. \
KHÔNG dùng cụm "nhà đầu tư chiến lược". \
KHÔNG lặp lại thông tin đoạn 1. \
Nếu source article KHÔNG có thông tin về tác động/hệ quả → viết EXACTLY: \
"Đây là tin nhanh, chưa có thông tin chi tiết về tác động lên thị trường tài sản mã hóa. \
Anh em theo dõi diễn biến tiếp theo trên BIC Group." \
TUYỆT ĐỐI KHÔNG BỊA "có thể ảnh hưởng", "nhà phân tích cho rằng", "diễn biến này có thể"...
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
(cộng đồng CIC đã có kiến thức cơ bản về crypto — KHÔNG giải thích khái niệm cơ bản).

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
    # Wave 0.8.4 F5: surface judge availability so the pipeline can bump
    # Wave06Metrics.judge_unavailable. True = at least one judge call hit
    # the fail-open path (Cerebras 429 / network / parse error) during
    # this content generation. Pipeline reads this once after generation.
    judge_unavailable: bool = False

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
    # Wave 0.5 (alpha.18): Expanded map — audit found internal source IDs leaking
    # into Telegram (e.g., "Reuters_Business" instead of "Reuters Business").
    "Reuters_Business": "Reuters Business",
    "CoinTelegraph": "CoinTelegraph",
    "CoinDesk": "CoinDesk",
    "CryptoSlate": "CryptoSlate",
    "Decrypt": "Decrypt",
    "NewsBTC": "NewsBTC",
    "UToday": "U.Today",
    "Bitcoinist": "Bitcoinist",
    "TheBlock": "The Block",
    "Blockworks": "Blockworks",
    "CryptoNews": "Crypto News",
    "AMBCrypto": "AMBCrypto",
}


def _format_source(source: str) -> str:
    """Wave 0.5 (alpha.18): Resolve source identifier to user-friendly display.

    Order: explicit map → underscore-to-space fallback. The fallback is only
    cosmetic (e.g., "Some_New_Source" → "Some New Source") so unknown
    sources still render readably without needing a code change.
    """
    if source in _SOURCE_DISPLAY_MAP:
        return _SOURCE_DISPLAY_MAP[source]
    return source.replace("_", " ").strip()


def _format_source_link(source: str, url: str) -> str:
    """Format source as Telegram HTML hyperlink (PA E)."""
    import html as _html

    display_name = _format_source(source)
    safe_source = _html.escape(display_name)
    if url:
        return f'<a href="{url}">Nguồn: {safe_source} ↗</a>'
    return f"Nguồn: {safe_source}"


# Wave 0.5 (alpha.18): Date freshness check — match dd/mm or dd-mm[-yyyy].
_DATE_PATTERN = re.compile(r"\b(\d{1,2})[\/\-](\d{1,2})(?:[\/\-](\d{2,4}))?\b")
# Future-tense indicators in Vietnamese that suggest LLM thinks date is upcoming.
_FUTURE_TENSE_MARKERS = ("dự kiến", "sắp tới", "sắp diễn ra")

# Wave 0.6 Story 0.6.3 (alpha.21): if more than this many sentences get
# stripped for stale-date violation, the whole article is too compromised
# to ship — caller marks delivery_failed.
_DATE_STRIP_THRESHOLD = 2


def _split_sentences(content: str) -> list[str]:
    """Cheap sentence splitter on `.`/`!`/`?`/newline boundaries.

    WHY not nltk: avoid heavy dependency for one-shot use. We accept some
    over-splits (e.g., "Mr.") because the strip path only removes sentences
    that contain BOTH a past date AND a future marker — rare overlap with
    Mr./Dr. abbreviations.
    """
    # Keep delimiters by splitting via regex with capture group, then re-pair.
    parts = re.split(r"([.!?\n]+)", content)
    out: list[str] = []
    buf = ""
    for part in parts:
        if re.fullmatch(r"[.!?\n]+", part):
            buf += part
            if buf.strip():
                out.append(buf)
            buf = ""
        else:
            buf += part
    if buf.strip():
        out.append(buf)
    return out


def _sentence_has_stale_future_date(sentence: str, today: datetime.date | None = None) -> bool:
    """True if sentence contains a past date AND a future-tense marker."""
    if today is None:
        today = datetime.now(timezone.utc).date()
    sentence_lc = sentence.lower()
    has_marker = any(marker in sentence_lc for marker in _FUTURE_TENSE_MARKERS)
    if not has_marker:
        return False
    for m in _DATE_PATTERN.finditer(sentence):
        try:
            day, month = int(m.group(1)), int(m.group(2))
            year_str = m.group(3)
            year = int(year_str) if year_str else today.year
            if year < 100:
                year += 2000
            ref_date = datetime(year, month, day).date()
        except (ValueError, IndexError):
            continue
        # Wave 0.6.6 B4: year rollover. dd/mm without year + already past +
        # significantly far in the past (>90 days) → likely refers to NEXT year
        # (e.g., "01/01 sắp tới" written on 31/12 means Jan 1 of next year).
        # WHY 90 days threshold: tolerate near-past references (last week's
        # data referenced as "sắp tới" was likely a real LLM error). Only
        # flip year when the parsed date is so far in the past that next-year
        # interpretation is the only sensible reading.
        if not year_str and ref_date < today and (today - ref_date).days > 90:
            try:
                ref_date = datetime(year + 1, month, day).date()
            except ValueError:
                pass  # leap-day edge: keep original
        if ref_date < today:
            return True
    return False


def _check_stale_dates(content: str) -> int:
    """Wave 0.5 (alpha.18): LOG-ONLY warning when LLM presents past dates as future.

    WHY LOG-ONLY mode kept: tests + back-compat. Wave 0.6 Story 0.6.3 adds
    the HARD-BLOCK path via `_check_and_handle_stale_dates()` gated behind
    flag `WAVE_0_6_DATE_BLOCK`.

    Returns count of stale-date warnings emitted (for tests).
    """
    today = datetime.now(timezone.utc).date()
    warn_count = 0
    for m in _DATE_PATTERN.finditer(content):
        try:
            day, month = int(m.group(1)), int(m.group(2))
            year_str = m.group(3)
            year = int(year_str) if year_str else today.year
            if year < 100:
                year += 2000
            ref_date = datetime(year, month, day).date()
        except (ValueError, IndexError):
            continue
        if ref_date >= today:
            continue
        # Wave 0.5.2 (alpha.19) Fix 5 (Codex finding): Check 50 chars BEFORE
        # AND AFTER the date for future-tense markers. Old check missed cases
        # like "06/03 sắp tới" where marker appears AFTER the date.
        prefix = content[max(0, m.start() - 50) : m.start()].lower()
        suffix = content[m.end() : m.end() + 50].lower()
        combined = prefix + " " + suffix
        if any(marker in combined for marker in _FUTURE_TENSE_MARKERS):
            logger.warning(
                f"Stale date in breaking content: {m.group(0)} (parsed={ref_date}, today={today})"
            )
            warn_count += 1
    return warn_count


def _check_and_handle_stale_dates(
    content: str,
    today: datetime.date | None = None,
    block_enabled: bool | None = None,
) -> tuple[str, list[str], bool]:
    """Wave 0.6 Story 0.6.3 (alpha.21): conditional stale-date enforcement.

    Args:
        content: Generated article text.
        today: Date to compare against. None → use UTC today (production).
            Tests inject explicit today for determinism.
        block_enabled: Override flag. None → read from env via
            `_wave_0_6_date_block_enabled()`. Tests inject explicit value.

    Returns:
        (cleaned_content, issues_list, delivery_failed):
        - LOG-ONLY mode (flag OFF): cleaned == content unchanged, issues
          contain warnings, delivery_failed always False (Wave 0.5.2
          behavior preserved).
        - BLOCK mode (flag ON): sentences with past-date + future-marker
          stripped from content. If >_DATE_STRIP_THRESHOLD sentences get
          stripped, delivery_failed=True (article too damaged to ship).

    WHY return tuple (not raise): caller (content_generator) wants to log
    + decide. Pipeline test path may want to inspect issues count without
    crashing the pipeline.
    """
    if today is None:
        today = datetime.now(timezone.utc).date()
    if block_enabled is None:
        block_enabled = _wave_0_6_date_block_enabled()

    issues: list[str] = []

    # LOG-ONLY path (Wave 0.5.2 behavior, unchanged).
    if not block_enabled:
        warn_count = 0
        for m in _DATE_PATTERN.finditer(content):
            try:
                day, month = int(m.group(1)), int(m.group(2))
                year_str = m.group(3)
                year = int(year_str) if year_str else today.year
                if year < 100:
                    year += 2000
                ref_date = datetime(year, month, day).date()
            except (ValueError, IndexError):
                continue
            # Wave 0.6.6 B4: same year-rollover heuristic as
            # _sentence_has_stale_future_date — "01/01 sắp tới" near year-end
            # actually means next year, not last Jan-1.
            if not year_str and ref_date < today and (today - ref_date).days > 90:
                try:
                    ref_date = datetime(year + 1, month, day).date()
                except ValueError:
                    pass
            if ref_date >= today:
                continue
            prefix = content[max(0, m.start() - 50) : m.start()].lower()
            suffix = content[m.end() : m.end() + 50].lower()
            combined = prefix + " " + suffix
            if any(marker in combined for marker in _FUTURE_TENSE_MARKERS):
                msg = (
                    f"Stale date in breaking content (LOG-ONLY): {m.group(0)} "
                    f"(parsed={ref_date}, today={today})"
                )
                logger.warning(msg)
                issues.append(msg)
                warn_count += 1
        return content, issues, False

    # BLOCK path: strip offending sentences.
    sentences = _split_sentences(content)
    kept: list[str] = []
    stripped_count = 0
    for sent in sentences:
        if _sentence_has_stale_future_date(sent, today):
            stripped_count += 1
            issues.append(
                f"Stripped stale-date sentence: '{sent.strip()[:120]}...' (today={today})"
            )
            logger.warning(issues[-1])
        else:
            kept.append(sent)

    cleaned = "".join(kept)
    # Wave 0.6.6 B5: also fail delivery when stripping leaves an empty body.
    # WHY 50 chars threshold: a real article body is much longer than that —
    # if all that remains is short metadata/disclaimer fragments, shipping
    # would deliver a near-empty Telegram message (operator confusion).
    cleaned_body_len = len(cleaned.strip())
    delivery_failed = stripped_count > _DATE_STRIP_THRESHOLD or (
        stripped_count > 0 and cleaned_body_len < 50
    )
    if delivery_failed:
        logger.error(
            f"Stale-date BLOCK: stripped {stripped_count} sentences "
            f"(>{_DATE_STRIP_THRESHOLD}) or empty body ({cleaned_body_len}<50 chars) "
            "— marking delivery_failed."
        )
    return cleaned, issues, delivery_failed


_TRAFILATURA_TIMEOUT = 12  # seconds — balance speed vs content depth


def _get_historical_context(
    event: BreakingEvent,
    top_k: int = 3,
    sheets_client: object | None = None,
) -> tuple[str, list[dict]]:
    """Wave 0.6 Story 0.6.2: Query RAG, format historical events as prompt context.

    Returns:
        (context_text, raw_results). context_text is empty string when no
        match (caller decides whether to instruct LLM "no historical").
        raw_results is the unformatted RAG dicts — passed to the judge so
        it can verify historical analogies match documented events.

    WHY return both: prompt needs human-readable text; judge needs structured
    JSON. Building once here avoids re-querying.

    WHY exclude_recent_hours=24.0 (Wave 0.8.4 F4): bumped from 1.0 after
    Bug 4 (01/05) where Wasabi tin self-cited "30/4/2026" because the same
    batch event was less than 24h old and dedup hash differed — RAG returned
    the very event being written about as "lịch sử". 24h floor matches our
    "recent enough = same news cycle, not history" heuristic.

    WHY exclude_url: belt-and-suspenders for the timestamp filter — even if
    clock skew or parse failure lets a same-URL match through, URL match
    catches it directly. The URL of the current event is the strongest
    self-reference signal we have.

    WHY exclude_title + exclude_entities (Wave 0.8.5 F7 — Devil B1): URL
    exact match misses when the SAME event is reported by 2+ outlets with
    different URLs (Wasabi 02:05 AMBCrypto vs Wasabi 08:47 The Block in
    01/05 batch). Title fuzzy (ratio>=0.7) + entity overlap (>=2) close
    that hole — same event still gets flagged as same-batch self-ref.
    """
    if not _wave_0_6_enabled():
        return ("", [])

    try:
        from cic_daily_report.breaking.dedup_manager import _extract_entities
        from cic_daily_report.breaking.rag_index import get_or_build_index

        idx = get_or_build_index(sheets_client=sheets_client)
        query = (
            (event.title or "")
            + " "
            + ((event.raw_data or {}).get("summary", "") if event.raw_data else "")
        )
        # Wave 0.8.5 F7: extract entities once from current event title for
        # the entity-overlap filter inside RAGIndex.query.
        title_entities = _extract_entities(event.title or "")
        results = idx.query(
            query=query,
            top_k=top_k,
            min_score=0.5,
            # Wave 0.8.4 F4: 1.0 → 24.0 hours
            exclude_recent_hours=24.0,
            # Wave 0.8.4 F4: belt-and-suspenders — exclude the URL of the
            # current event explicitly (defends against timestamp parse drift).
            exclude_url=(event.url or None),
            # Wave 0.8.5 F7: 2 extra layers when 2+ outlets cover same event
            # with different URLs but near-identical content.
            exclude_title=(event.title or None),
            exclude_entities=(title_entities or None),
            # Wave 0.8.7 Bug 10 (alpha.33): lower entity overlap threshold to
            # 1 here. Both current event and indexed events are "breaking"
            # severity; a single shared entity (Alex Lab "Canada" self-ref
            # 01/05) is enough signal that we're looking at the same story
            # being recycled. Backward compat preserved at the caller default.
            entity_overlap_min=1,
        )
    except Exception as e:
        # WHY catch broad: RAG failure (sheets down, sqlite corrupt, BM25
        # error) MUST NOT block content generation. Fail-open with empty
        # context — LLM will get the "no historical" instruction.
        logger.warning(
            f"RAG query failed ({type(e).__name__}: {e!r}) — skipping historical context"
        )
        return ("", [])

    if not results:
        return ("", [])

    # Format as bullet list inside <historical_events> XML-ish block —
    # matches the prompt's other <source>/<historical_context> conventions.
    lines = ["<historical_events>"]
    for r in results:
        ts = r.get("timestamp", "?")
        title = r.get("title", "?")
        btc = r.get("btc_price")
        btc_str = f"${btc:,.0f}" if isinstance(btc, (int, float)) and btc > 0 else "N/A"
        score = r.get("score", 0.0)
        src = r.get("source", "?")
        lines.append(f"- [{ts}] {title} (BTC: {btc_str}, score: {score:.2f}) — Nguồn: {src}")
    lines.append("</historical_events>")
    return ("\n".join(lines), results)


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


# Wave 0.6 Story 0.6.4 (alpha.22): coin-name + price detection regex.
# Matches "BTC ... $76,000" or "Bitcoin $76k" within 60-char window.
# WHY 60 chars: balances precision (avoid matching unrelated price elsewhere)
# vs flexibility (LLM may insert qualifiers like "hiện đạt" between name + price).
_COIN_PRICE_PATTERN_BTC = re.compile(
    r"(?P<name>BTC|Bitcoin)(?P<gap>[^$\n]{0,60}?)\$(?P<price>[\d,]+(?:\.\d+)?)\s*(?P<suffix>k|K)?",
    re.IGNORECASE,
)
_COIN_PRICE_PATTERN_ETH = re.compile(
    r"(?P<name>ETH|Ethereum)(?P<gap>[^$\n]{0,60}?)\$(?P<price>[\d,]+(?:\.\d+)?)\s*(?P<suffix>k|K)?",
    re.IGNORECASE,
)


def _replace_off_snapshot_prices(
    content: str,
    coin: str,
    snapshot_price: float,
    tolerance_pct: float = 1.0,
) -> str:
    """Wave 0.6 Story 0.6.4: Replace coin prices that drift from snapshot.

    Scans content for "BTC ... $X" or "ETH ... $X" patterns. If $X is within
    tolerance_pct of snapshot_price → keep as-is (already correct). If $X is
    >tolerance_pct off (but still within 50% range — beyond that
    numeric_sanity already stripped) → replace with snapshot price formatted
    as "${snapshot:,.0f}".

    Args:
        content: Generated article text.
        coin: "BTC" or "ETH".
        snapshot_price: Frozen price from PriceSnapshot.
        tolerance_pct: Replace any price more than this % off snapshot.

    Returns:
        Content with off-snapshot prices replaced. Logs each replacement.

    WHY tolerance 1%: snapshot is "the truth for this run"; any drift means
    LLM hallucinated a slightly different value. Even small drift across 3
    breaking msgs in same run looks unprofessional ($76k → $74k → $77k).
    """
    pattern = _COIN_PRICE_PATTERN_BTC if coin.upper() == "BTC" else _COIN_PRICE_PATTERN_ETH

    def _maybe_replace(m: re.Match) -> str:
        raw_price = m.group("price").replace(",", "")
        try:
            extracted = float(raw_price)
        except ValueError:
            return m.group(0)
        suffix = m.group("suffix") or ""
        if suffix.lower() == "k":
            extracted *= 1000
        # Skip absurdly off prices (>50% drift) — numeric_sanity should have
        # already stripped those; if it didn't, replacing here would mask a
        # real bug in the upstream guard.
        drift_pct = abs(extracted - snapshot_price) / snapshot_price * 100
        if drift_pct > 50:
            return m.group(0)
        if drift_pct <= tolerance_pct:
            return m.group(0)  # within tolerance — keep
        # Replace the $X portion only (preserve coin name + gap text).
        # Reconstruct: <name><gap><new_price>  (drop suffix since we use full number).
        new_price_str = f"${snapshot_price:,.0f}"
        replacement = m.group("name") + m.group("gap") + new_price_str
        logger.info(
            f"Story 0.6.4: Replaced off-snapshot {coin} price "
            f"${extracted:,.0f} → ${snapshot_price:,.0f} (drift {drift_pct:.1f}%)"
        )
        return replacement

    return pattern.sub(_maybe_replace, content)


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
    sheets_client: object | None = None,
    price_snapshot: object | None = None,
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

    # Wave 0.6 Story 0.6.4 (alpha.22): Inject explicit price-lock instruction when
    # PriceSnapshot is provided. WHY: Audit Round 2 found 3 breaking msg in 4 min
    # showing BTC at $76k / $74k / $77k — different per LLM call. Locking BTC/ETH
    # to snapshot in BOTH the prompt (lock note) AND post-process (replace wrong
    # numbers near coin name) eliminates inconsistency across the run.
    price_lock_section = ""
    snapshot_btc: float | None = None
    snapshot_eth: float | None = None
    if price_snapshot is not None:
        snapshot_btc = price_snapshot.get_price("BTC")
        snapshot_eth = price_snapshot.get_price("ETH")
        lock_lines = []
        if snapshot_btc and snapshot_btc > 0:
            lock_lines.append(
                f"BTC price = ${snapshot_btc:,.0f}. KHÔNG dùng giá khác cho BTC trong toàn bài."
            )
        if snapshot_eth and snapshot_eth > 0:
            lock_lines.append(
                f"ETH price = ${snapshot_eth:,.0f}. KHÔNG dùng giá khác cho ETH trong toàn bài."
            )
        if lock_lines:
            price_lock_section = "\nGIÁ ĐÃ KHÓA (BẮT BUỘC dùng đúng):\n" + "\n".join(lock_lines)
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

    # Wave 0.6 Story 0.6.2: RAG-grounded historical context.
    # WHY: Wave 0.5 audit found 87.5% LLM "historical references" fabricated
    # (Poly Network "$6B" vs real $0.6B; "BTC tăng 2022" vs real bear -75%).
    # Story 0.6.1 built BM25 index over BREAKING_LOG; this wires it in.
    # Two paths:
    #   - RAG hit → inject <historical_events> block + ALLOW historical sentence
    #     constrained to those events.
    #   - No hit (or flag off) → INSTRUCT no historical reference to prevent
    #     fabrication. Mirrors Wave 0.5 safe behavior.
    rag_context_text, rag_results = _get_historical_context(event, sheets_client=sheets_client)
    if rag_context_text:
        historical_instruction_text = (
            "\n- (Optional) 1 câu THAM CHIẾU LỊCH SỬ — CHỈ dùng events có "
            "trong <historical_events> dưới đây. KHÔNG TỰ BỊA số/ngày/sự "
            "kiện khác.\n"
            # Wave 0.8.4 F4: explicit guard against 24h-window self-ref —
            # even if a same-day event slips into <historical_events> via
            # filter edge case, the LLM is told NOT to treat it as history.
            "- KHÔNG ref event xảy ra trong 24h qua làm 'lịch sử' — đó là "
            "tin cùng batch (cùng news cycle), KHÔNG phải lịch sử.\n"
            f"\n{rag_context_text}\n"
        )
    else:
        historical_instruction_text = (
            "\n- KHÔNG viết tham chiếu lịch sử (chưa có data verify được).\n"
        )

    prompt = BREAKING_PROMPT_TEMPLATE.format(
        title=event.title,
        source=event.source,
        url=event.url,
        summary_section=summary_section,
        market_context=market_section,
        price_lock=price_lock_section,
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

    # Wave 0.6 Story 0.6.2: Fact-check pass — Cerebras Qwen3 235B verifies
    # numerical/historical/quote claims. Only for high-impact severities to
    # save quota (notable severity has weaker hallucination risk + higher
    # volume).
    # WHY retry inside this function (not pipeline): retry needs the same
    # prompt + context. Surfacing retry to pipeline would leak prompt details.
    judge_skipped = not _wave_0_6_enabled() or severity not in ("critical", "important")
    # Wave 0.8.4 F1: track judge retry to apply hard word-count gate later.
    # Only applied when judge actually retried (the retry path is where
    # short outputs were observed in Bug 1 — see retry_prompt below).
    judge_retried = False
    judge_unavailable_seen = False  # Wave 0.8.4 F5
    if not judge_skipped:
        judge1 = await llm.judge_factual_claims(
            content=response.text,
            source_text=summary_text or event.title,
            historical_context=rag_results,
        )
        # Wave 0.8.4 F5: detect judge unavailability via the
        # "judge_unavailable:" issue prefix (existing convention from
        # llm_adapter.judge_factual_claims fail-open path). Caller
        # (breaking_pipeline) reads this off the BreakingContent so the
        # Wave06Metrics counter can be bumped without coupling the LLM
        # adapter to metrics.
        for issue in judge1.issues or []:
            if isinstance(issue, str) and issue.startswith("judge_unavailable:"):
                judge_unavailable_seen = True
                break
        if judge1.verdict == "rejected":
            logger.warning(
                f"Fact-check rejected (1st pass): {judge1.issues[:3]} (model={judge1.model_used})"
            )
            judge_retried = True
            # WHY 1 retry only: more retries waste quota; the issues list
            # already tells the LLM what to avoid.
            # Wave 0.8.4 F1: re-emphasize word_target + 2 đoạn after judge
            # reject. Bug 1 (01/05): retry produced 1-câu output because
            # the original word_target hint got buried under fact-check
            # complaints — model defaulted to "tóm tắt cho an toàn".
            issues_text = "; ".join(judge1.issues[:5])
            retry_prompt = (
                prompt
                + f"\n\nLẦN TRƯỚC bị reject: {issues_text}.\n"
                + f"VIẾT LẠI tin {word_target} từ, ĐỦ 2 đoạn: "
                + "(1) sự kiện chi tiết, "
                + "(2) TẠI SAO QUAN TRỌNG cho cộng đồng CIC. "
                + "CHỈ dùng fact verify được trong <source>. "
                + "KHÔNG bịa số/ngày/sự kiện."
            )
            response = await llm.generate(
                prompt=retry_prompt,
                max_tokens=2048,
                temperature=0.3,
                system_prompt=NQ05_SYSTEM_PROMPT,
            )
            judge2 = await llm.judge_factual_claims(
                content=response.text,
                source_text=summary_text or event.title,
                historical_context=rag_results,
            )
            # Wave 0.8.4 F5: also check 2nd-pass judge availability
            for issue in judge2.issues or []:
                if isinstance(issue, str) and issue.startswith("judge_unavailable:"):
                    judge_unavailable_seen = True
                    break
            if judge2.verdict == "rejected":
                # WHY raise instead of return broken content: pipeline must
                # be told this event failed so it logs + skips delivery.
                # Mirroring v0.29.0 (A4) — propagate rather than swallow.
                from cic_daily_report.core.error_handler import LLMError

                logger.error(f"Fact-check rejected (2nd pass): {judge2.issues[:3]}")
                raise LLMError(
                    f"Fact-check rejected after retry: {judge2.issues[:3]}",
                    source="breaking_content_factcheck",
                    retry=False,
                )
        elif judge1.verdict == "needs_revision":
            # Log + ship — minor issues acceptable for non-critical content.
            logger.warning(
                f"Fact-check needs revision: {judge1.issues[:3]} "
                f"(model={judge1.model_used}) — shipping anyway"
            )

    # Apply NQ05 post-filter
    filtered = check_and_fix(response.text, extra_banned_keywords)

    # Strip any LLM-generated disclaimer to prevent duplication
    clean_content = _DISCLAIMER_RE.sub("", filtered.content).rstrip()

    word_count = len(clean_content.split())
    model_used = getattr(llm, "last_provider", response.model)

    # v0.33.0: Guard against NQ05 filter stripping too much content.
    # WHY: REMOVE_FILLER_PATTERNS could delete most sentences, leaving <50 words.
    # Wave 0.5.2 (alpha.19) Fix 1: Re-run NQ05 keyword filter on raw fallback
    # so the keyword strip is still applied even when filler-removal drops too
    # much. Old code used response.text directly → bypassed banned-keyword
    # filter entirely → NQ05 violations could ship to Telegram.
    # WHY no raise on still-short: tests intentionally feed short content to
    # exercise truncation/disclaimer paths, and short raw-but-NQ05-clean text
    # is acceptable (fallback delivery, no spec violation). If we want to
    # surface "too short" as a hard failure, that's better done in the
    # pipeline by inspecting BreakingContent.word_count after return.
    if word_count < 50:
        logger.warning(
            f"Breaking content too short after NQ05 filter ({word_count} words), "
            "re-running NQ05 keyword check on pre-filter content (Fix 1)"
        )
        refiltered = check_and_fix(response.text, extra_banned_keywords)
        clean_content = _DISCLAIMER_RE.sub("", refiltered.content).rstrip()
        word_count = len(clean_content.split())
        if word_count < 50:
            # Still short — keep going (NQ05 keyword filter has been applied),
            # but log clearly so pipeline / ops dashboards can spot it.
            logger.warning(
                f"Fix 1: content still <50 words after re-filter ({word_count}). "
                "Shipping NQ05-clean short content rather than raw bypass."
            )

    # Wave 0.8.4 F1: HARD GATE — block ship when judge retried but final
    # output remains <80 words. Bug 1+6 (01/05): 3/5 tin had no Đoạn 2
    # because retry produced 1-câu output and only word_count<50 was
    # logged (not blocked). 80 chosen per Winston condition: even
    # critical alerts deserve at least Đoạn 1 (3-5 câu) + 1-câu Đoạn 2.
    # WHY only when judge_retried: tests + non-judge paths intentionally
    # feed short content; we must not break those flows.
    if judge_retried and word_count < 80:
        from cic_daily_report.core.error_handler import LLMError

        logger.error(
            f"Wave 0.8.4 F1 HARD BLOCK: word_count={word_count} <80 after "
            f"judge retry — refusing to ship 1-câu output (severity={severity})"
        )
        raise LLMError(
            f"content too short after judge retry ({word_count} words)",
            source="breaking_content_word_gate",
            retry=False,
        )

    # Wave 0.8.7 (alpha.33) Bug 9 — UNIVERSAL gate: tin Coinbase 1-đoạn
    # (01/05) lọt qua because judge approved 1st-pass + word_count=72. F1
    # only fired on retry path. Now: when Wave 0.6 is enabled (judge available
    # / fail-open / skip), enforce >=80 words for any final output.
    # WHY only when Wave 0.6 ON: legacy non-Wave-0.6 paths intentionally allow
    # short content (raw fallback, tests pre-Wave-0.6). Once Wave 0.6 is
    # enabled, the system promises a minimum 2-paragraph quality bar.
    if not judge_retried and _wave_0_6_enabled() and word_count < 80:
        from cic_daily_report.core.error_handler import LLMError

        logger.error(
            f"Wave 0.8.7 Bug 9 UNIVERSAL GATE: word_count={word_count} <80 "
            f"(judge_retried=False, judge_skipped={judge_skipped}, "
            f"judge_unavailable_seen={judge_unavailable_seen}) — refusing to ship"
        )
        raise LLMError(
            f"content too short on universal gate ({word_count} words)",
            source="breaking_content_word_gate_universal",
            retry=False,
        )

    logger.info(f"Breaking content generated: {word_count} words via {model_used}")

    # Wave 0.6 Story 0.6.3/0.6.4 (alpha.21/22): full numeric guard suite.
    # WHY here: after NQ05 filter so we don't sanitize content that gets
    # rewritten by re-filter; before truncation so cap doesn't push past limit.
    # Story 0.6.4: PriceSnapshot now wired — passes BTC/ETH snapshot to tighten
    # range to ±50% of frozen price (vs global $10k-$200k for BTC).
    clean_content, guard_issues = apply_all_numeric_guards(
        clean_content, btc_snapshot=snapshot_btc, eth_snapshot=snapshot_eth
    )

    # Wave 0.6 Story 0.6.4 (alpha.22): Post-process price replace.
    # WHY: numeric_sanity flags out-of-range prices but does NOT replace; LLM
    # may still write $80k BTC when snapshot says $76k (within range, valid
    # but inconsistent). Replace any BTC/ETH price within ±10% of snapshot
    # to lock to snapshot value. >10% off → numeric_sanity already flagged.
    if snapshot_btc and snapshot_btc > 0:
        clean_content = _replace_off_snapshot_prices(
            clean_content, "BTC", snapshot_btc, tolerance_pct=1.0
        )
    if snapshot_eth and snapshot_eth > 0:
        clean_content = _replace_off_snapshot_prices(
            clean_content, "ETH", snapshot_eth, tolerance_pct=1.0
        )
    if guard_issues:
        logger.warning(
            f"Story 0.6.3 numeric guards: {len(guard_issues)} issue(s). "
            f"Examples: {guard_issues[:2]}"
        )
        word_count = len(clean_content.split())

    # Wave 0.6 Story 0.6.3 (alpha.21): Date freshness — LOG or BLOCK based on flag.
    # WHY: Audit found LLM frequently writes "dự kiến diễn ra vào ngày X/Y" using
    # past dates (e.g., today=27/04 but content says "diễn ra vào 06/03 sắp tới").
    # Flag default OFF → LOG-ONLY (Wave 0.5.2 behavior). Flag ON → strip stale
    # sentences; if too many stripped, mark delivery_failed for caller to skip.
    clean_content, _date_issues, _date_failed = _check_and_handle_stale_dates(clean_content)
    if _date_failed:
        # WHY raise instead of return: pipeline must mark event delivery_failed.
        # Mirror pattern from fact-check rejection (LLMError raise path).
        from cic_daily_report.core.error_handler import LLMError

        raise LLMError(
            "Stale-date BLOCK: too many stripped sentences (Story 0.6.3)",
            source="breaking_content_date_block",
            retry=False,
        )
    if clean_content != "":
        word_count = len(clean_content.split())

    # P1.25 + NQ05: Truncate body BEFORE appending suffix to guarantee the
    # mandatory DISCLAIMER is never cut off by the character limit.
    # QO.07 (VD-36): Breaking news uses short disclaimer — full version takes
    # 15-20% of a 300-400 word message. Daily articles keep full DISCLAIMER.
    source_html = _format_source_link(event.source, event.url)
    # WHY suffix calc keeps DISCLAIMER_SHORT len: append_nq05_disclaimer adds the
    # disclaimer at end via centralized helper (Wave C+ NQ05 single source);
    # truncation budget unchanged so existing limit tests + NQ05-never-cut
    # invariant remain valid (see tests/test_breaking/test_content_generator_limits.py).
    source_block = f"\n\n🔗 {source_html}"
    # WHY len(source_block) + len(DISCLAIMER_SHORT): truncation budget must reserve
    # room for both source link AND disclaimer (appended via helper). Avoids raw
    # `+ DISCLAIMER_SHORT` concat which the NQ05 linter forbids.
    body_limit = BREAKING_MAX_CHARS - len(source_block) - len(DISCLAIMER_SHORT)
    # BUG-15: Floor at 500 chars — if suffix is extremely long, body_limit
    # could go negative, causing text[:negative] → empty string → content lost.
    if body_limit < 500:
        body_limit = 500
    clean_content, was_truncated = truncate_to_limit(clean_content, body_limit)
    if was_truncated:
        logger.warning(
            f"Breaking content body truncated to fit suffix: body_limit={body_limit} chars"
        )
    content_with_disclaimer = append_nq05_disclaimer(clean_content + source_block, short=True)

    return BreakingContent(
        event=event,
        content=content_with_disclaimer,
        word_count=len(content_with_disclaimer.split()),
        ai_generated=True,
        model_used=model_used,
        image_url=event.image_url,
        # Wave 0.8.4 F5: pass through to pipeline metrics
        judge_unavailable=judge_unavailable_seen,
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
    current_event_time: datetime | None = None,
    min_age_hours: float = 1.0,
) -> dict[str, str]:
    """QO.36: Build enrichment context dict for breaking content generation.

    Assembles cross-asset correlation, Polymarket shift, and related breaking
    history into text strings that can be passed to generate_breaking_content().

    Args:
        market_data: List of MarketDataPoint objects from market_data collector.
        prediction_data: PredictionMarketsData object from prediction_markets collector.
        dedup_entries: List of DedupEntry objects from dedup_manager (for history).
        event_title: Current event title (for finding related history).
        current_event_time: Wave 0.5.2 Fix 3 — anchor for self-reference filter
            on breaking_history. If None, no time filter applied (legacy behavior).
        min_age_hours: history entries newer than this are excluded.

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

    # 3. Related breaking history (Wave 0.5.2 Fix 3 self-reference filter)
    if dedup_entries and event_title:
        result["breaking_history"] = _build_related_history(
            dedup_entries,
            event_title,
            current_event_time=current_event_time,
            min_age_hours=min_age_hours,
        )

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


def _build_related_history(
    dedup_entries: list,
    event_title: str,
    current_event_time: datetime | None = None,
    min_age_hours: float = 1.0,
) -> str:
    """QO.36: Find related events from breaking history.

    WHY: Gives LLM context about what was already reported on this topic,
    enabling it to write follow-up angles instead of repeating.

    Wave 0.5.2 (alpha.19) Fix 3: same timestamp filter as _format_recent_events
    in breaking_pipeline — entries newer than ``current_event_time -
    min_age_hours`` are excluded so a sibling event from the same batch can't
    pose as "lịch sử" of the current event.
    """
    title_lower = event_title.lower()
    # WHY: Extract key entities from title for matching
    title_words = set(title_lower.split())
    # Filter to significant words (>3 chars, not common words)
    _STOP_WORDS = {"the", "and", "for", "that", "with", "from", "this", "have", "been"}
    key_words = {w for w in title_words if len(w) > 3 and w not in _STOP_WORDS}

    if not key_words:
        return ""

    cutoff = None
    if current_event_time is not None:
        from datetime import timedelta

        cutoff = current_event_time - timedelta(hours=min_age_hours)

    related = []
    for entry in dedup_entries:
        entry_title = getattr(entry, "title", "").lower()
        entry_status = getattr(entry, "status", "")
        # WHY: Only include sent events (skip pending/skipped)
        if entry_status not in ("sent", "sent_geo_digest"):
            continue

        # Wave 0.5.2 Fix 3: timestamp filter to prevent self-reference
        if cutoff is not None:
            entry_at = getattr(entry, "detected_at", "")
            if not entry_at:
                continue
            try:
                entry_time = datetime.fromisoformat(entry_at)
            except (ValueError, TypeError):
                continue
            if entry_time > cutoff:
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

    # Wave 0.6 Story 0.6.3 (alpha.21): full numeric guard suite for digest path too.
    clean_content, digest_guard_issues = apply_all_numeric_guards(clean_content)
    if digest_guard_issues:
        logger.warning(
            f"Story 0.6.3 (digest) numeric guards: {len(digest_guard_issues)} issue(s). "
            f"Examples: {digest_guard_issues[:2]}"
        )

    # P1.25 + NQ05: Truncate body BEFORE appending suffix to guarantee the
    # mandatory DISCLAIMER is never cut off by the character limit.
    # QO.07 (VD-36): Digest is breaking news → use short disclaimer.
    links = "\n".join(f"🔗 {_format_source_link(e.source, e.url)}" for e in events if e.url)
    links_block = f"\n\n{links}"
    # Budget = total - links_block - disclaimer (helper appends disclaimer at end).
    body_limit = BREAKING_MAX_CHARS - len(links_block) - len(DISCLAIMER_SHORT)
    # BUG-15: Floor at 500 chars — too many event links can make suffix huge,
    # pushing body_limit negative → text[:negative] → empty body → content lost.
    # When this happens, truncate the links list to fit.
    if body_limit < 500:
        max_link_chars = BREAKING_MAX_CHARS - 500 - len(DISCLAIMER_SHORT)
        links = links[:max_link_chars].rsplit("\n", 1)[0]  # Cut at last complete link
        links_block = f"\n\n{links}"
        body_limit = BREAKING_MAX_CHARS - len(links_block) - len(DISCLAIMER_SHORT)
    clean_content, was_truncated = truncate_to_limit(clean_content, body_limit)
    if was_truncated:
        logger.warning(
            f"Digest content body truncated to fit suffix: body_limit={body_limit} chars"
        )
    # Wave C+ NQ05 centralization: disclaimer via helper (single source of truth).
    content_with_links = append_nq05_disclaimer(clean_content + links_block, short=True)

    logger.info(f"Digest generated: {len(events)} events via {model_used}")

    return BreakingContent(
        event=events[0],  # Primary event for metadata
        content=content_with_links,
        word_count=len(content_with_links.split()),
        ai_generated=True,
        model_used=model_used,
    )
