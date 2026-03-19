# THIẾT KẾ KỸ THUẬT: Pipeline Quality Overhaul

> **Version**: 1.0 | **Date**: 2026-03-18
> **Author**: Winston (Architect) + Quinn (QA, test plan song song)
> **Spec ref**: `_bmad-output/SPEC-pipeline-quality-overhaul.md`
> **Status**: DRAFT — Chờ review + Anh Cường approve

---

## PHASE 1 — Quick Wins (D1, E1, E2)

### 1.1. Xóa số liệu cứng khỏi tier context (D1)

**File**: `src/cic_daily_report/daily_pipeline.py` dòng 452-511

**Hiện tại**: Tier context L3/L4/L5 chứa ví dụ output có số liệu thật (3.75%, 19/03, $73K-$77K) xung đột với data API.

**Thay đổi**: Chuyển ví dụ sang dạng **placeholder** — giữ cấu trúc nhưng không có số cụ thể:

```python
# L3 — TRƯỚC (dòng 466-467):
"Sự kiện quan trọng: Fed công bố lãi suất ngày 19/03, "
'dự báo giữ 3.75% — nếu đúng, DXY có thể tiếp tục giảm."'

# L3 — SAU:
'"[Sự kiện macro quan trọng nhất tuần] — phân tích tác động lên DXY → crypto. '
'Nối với Funding Rate để đánh giá tâm lý thị trường phái sinh."'

# L4 — TRƯỚC (dòng 485):
"Rủi ro lớn nhất tuần này: Fed meeting 19/03 — nếu bất ngờ hawkish, "

# L4 — SAU:
'"Rủi ro lớn nhất: [sự kiện từ lịch kinh tế] — nếu kết quả bất ngờ, '
'DXY tăng → áp lực bán. Kèm cross-signal nào ủng hộ/phản bác."'

# L5 — TRƯỚC (dòng 504-509):
"Base case (Recovery, medium confidence)": BTC sideway $73K-$77K chờ FOMC. "
"Bullish trigger: Fed dovish 19/03 + DXY <99..."

# L5 — SAU:
'"Base case ([regime từ Metrics Engine]): [mô tả kỳ vọng dựa trên signals]. '
'Bullish trigger: [điều kiện cụ thể từ data]. '
'Bearish trigger: [rủi ro từ L4]. '
'Dòng tiền: [sector data + TVL + narrative nổi bật]."'
```

**Nguyên tắc**: Ví dụ hướng dẫn **CẤU TRÚC** phân tích, không chứa **SỐ LIỆU** cụ thể.

**Files thay đổi**: 1 file
**Dòng thay đổi**: ~30 dòng (452-511)
**Rủi ro**: Rất thấp — chỉ thay text trong prompt

---

### 1.2. Thêm filler phrase detection vào NQ05 post-filter (E1)

**File**: `src/cic_daily_report/generators/nq05_filter.py`

**Hiện tại**: Chỉ kiểm tra 16 banned keywords (mua/bán) + 5 semantic patterns + 3 allocation patterns. KHÔNG kiểm tra filler phrases dù system prompt cấm.

**Thay đổi**: Thêm `FILLER_PATTERNS` list và tích hợp vào `check_and_fix()`.

**Quan trọng**: Filler phrases KHÔNG xóa câu — chỉ **log warning** và **đếm** để quality gate (Phase 5) dùng. Lý do: xóa câu filler có thể mất nội dung (đã là vấn đề E5), còn regenerate thì tốn quota.

```python
# Thêm sau SEMANTIC_NQ05_PATTERNS (dòng 80):

# Filler phrases banned by system prompt — detected and COUNTED (not removed).
# Used by quality gate to flag low-quality output.
FILLER_PATTERNS = [
    r"có thể ảnh hưởng đến",
    r"cần theo dõi (?:thêm|chặt chẽ|sát sao)",
    r"điều này cho thấy",
    r"tuy nhiên cần lưu ý",
    r"trong bối cảnh",
    r"có thể tác động (?:trực tiếp|đến)",
    r"có thể (?:tạo ra|dẫn đến) (?:sự )?(?:thay đổi|biến động)",
]
```

**Tích hợp vào `check_and_fix()`** — thêm Step 1e sau Step 1d (CJK sanitization):

```python
    # Step 1e: Detect filler phrases (WARN only, do NOT remove)
    filler_count = 0
    for pattern_str in FILLER_PATTERNS:
        pattern = re.compile(pattern_str, re.IGNORECASE)
        matches = pattern.findall(result.content)
        if matches:
            filler_count += len(matches)
            result.flagged_for_review.append(
                f"Filler detected (not removed): '{pattern_str}' ({len(matches)}x)"
            )
    result.filler_count = filler_count  # New field in FilterResult
```

**Cập nhật `FilterResult` dataclass** — thêm field:

```python
@dataclass
class FilterResult:
    content: str
    violations_found: int = 0
    auto_fixed: int = 0
    flagged_for_review: list[str] = field(default_factory=list)
    disclaimer_present: bool = False
    passed: bool = True
    filler_count: int = 0  # NEW: count of detected filler phrases
```

**Files thay đổi**: 1 file (`nq05_filter.py`)
**Dòng thêm**: ~25 dòng
**Rủi ro**: Rất thấp — chỉ detect, không thay đổi content

---

### 1.3. Giảm temperature 0.5 → 0.3 (E2)

**File**: `src/cic_daily_report/generators/article_generator.py` dòng 367
**File**: `src/cic_daily_report/breaking/content_generator.py` dòng 107

**Thay đổi**:
```python
# article_generator.py dòng 367:
temperature=0.3,  # was 0.5 — lower for better instruction compliance

# content_generator.py dòng 107:
temperature=0.3,  # was 0.5
```

**Files thay đổi**: 2 files
**Dòng thay đổi**: 2 dòng
**Rủi ro**: Rất thấp — rollback = thay 1 số

---

### PHASE 1 TEST PLAN (Quinn)

| Test | File | Mô tả |
|------|------|-------|
| `test_tier_context_no_hardcoded_numbers` | `tests/test_generators/test_article_generator.py` | Verify tier_context L3-L5 không chứa regex `\d+\.\d+%` (số thập phân %) |
| `test_filler_detection` | `tests/test_generators/test_nq05_filter.py` | Input chứa "có thể ảnh hưởng đến" → `filler_count=1`, content KHÔNG bị thay đổi |
| `test_filler_multiple` | `tests/test_generators/test_nq05_filter.py` | Input chứa 3 filler phrases → `filler_count=3` |
| `test_temperature_daily` | `tests/test_generators/test_article_generator.py` | Verify LLM call dùng `temperature=0.3` |
| `test_temperature_breaking` | `tests/test_breaking/test_content_generator.py` | Verify LLM call dùng `temperature=0.3` |

---

## PHASE 2 — Breaking News Enrichment (A1, A2, A3, A4)

### 2.1. Trafilatura cho Breaking events (A1 + A2)

**File mới**: KHÔNG — reuse logic từ `collectors/cryptopanic_client.py` `_extract_fulltext()`

**File sửa**: `breaking/content_generator.py`

**Thay đổi**: Thêm hàm `_fetch_article_text()` và gọi trước khi build prompt.

```python
# Thêm imports:
import asyncio
import httpx

# Thêm hàm helper:
_TRAFILATURA_TIMEOUT = 8  # seconds — fail fast, fallback to title-only

async def _fetch_article_text(url: str, max_chars: int = 1500) -> str:
    """Fetch and extract article body text via trafilatura.

    Returns extracted text (max max_chars) or empty string on failure.
    Timeout: 8s — breaking news must be fast.
    """
    try:
        import trafilatura  # optional dependency
    except ImportError:
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
```

**Sửa `generate_breaking_content()`** — thêm article fetch trước build prompt:

```python
async def generate_breaking_content(
    event: BreakingEvent,
    llm,
    severity: str = "notable",
    extra_banned_keywords: list[str] | None = None,
    market_context: str = "",       # NEW: Phase 2.2
    recent_events: str = "",        # NEW: Phase 2.3
) -> BreakingContent:
    word_target = "200-250" if severity == "critical" else "100-150"

    # NEW: Fetch article body if no summary in raw_data
    summary_text = event.raw_data.get("summary", "") if event.raw_data else ""
    if not summary_text and event.url:
        article_text = await _fetch_article_text(event.url)
        if article_text:
            summary_text = article_text
            logger.info(f"Enriched breaking event with article text ({len(article_text)} chars)")

    summary_section = f"**Nội dung bài gốc:**\n{summary_text}\n" if summary_text else ""
    # ... rest of function
```

**Rủi ro**: Trung bình — thêm 5-8s latency per event
**Giảm thiểu**: Timeout 8s + fallback về title-only nếu fail

---

### 2.2. Market context cho Breaking prompt (A3)

**File sửa**: `breaking_pipeline.py` + `breaking/content_generator.py`

**Cách làm**: Breaking pipeline đã có `_market_trigger_detection()` gọi market data. Reuse data này và truyền cho content generator.

**Sửa `breaking_pipeline.py`** — truyền market snapshot:

```python
# Trong hàm chính, sau khi collect market data cho triggers:
market_snapshot = _format_market_snapshot(market_data)  # NEW helper

# Truyền cho content generator:
content = await generate_breaking_content(
    event=event,
    llm=llm,
    severity=classified.severity,
    market_context=market_snapshot,  # NEW
    recent_events=recent_events_text,  # NEW (Phase 2.3)
)
```

**Helper `_format_market_snapshot()`**:
```python
def _format_market_snapshot(market_data: list | None) -> str:
    """Format brief market context for breaking news prompt."""
    if not market_data:
        return ""
    lines = []
    for dp in market_data:
        if dp.symbol in ("BTC", "ETH"):
            lines.append(f"{dp.symbol}: ${dp.price:,.0f} ({dp.change_24h:+.1f}%)")
    # Add F&G if available
    for dp in market_data:
        if dp.symbol == "Fear_Greed":
            lines.append(f"Fear & Greed: {int(dp.price)}")
        elif dp.symbol == "DXY":
            lines.append(f"DXY: {dp.price:.1f}")
    return "Bối cảnh thị trường hiện tại: " + " | ".join(lines) if lines else ""
```

---

### 2.3. Recent events context (A4)

**File sửa**: `breaking_pipeline.py`

**Cách làm**: Lấy 3-5 tin gần nhất từ BREAKING_LOG (đã load cho dedup) → format → truyền cho content generator.

```python
def _format_recent_events(dedup_entries: list, max_events: int = 5) -> str:
    """Format recent breaking events for context injection."""
    recent = sorted(dedup_entries, key=lambda e: e.detected_at, reverse=True)[:max_events]
    if not recent:
        return ""
    lines = ["Tin Breaking gần đây (để liên kết nếu liên quan):"]
    for entry in recent:
        lines.append(f"- {entry.title} ({entry.source}, {entry.severity})")
    return "\n".join(lines)
```

---

### 2.4. Redesign Breaking prompt (A1 tổng thể)

**File sửa**: `breaking/content_generator.py` — thay `BREAKING_PROMPT_TEMPLATE`

```python
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
```

**Thay đổi chính**:
- "Chuyện gì xảy ra" → "Nội dung cốt lõi" (hướng AI tóm tắt SỐ LIỆU từ bài)
- "Tại sao quan trọng" → "Bối cảnh & tác động" (liên kết tin + market data)
- Thêm `{market_context}` và `{recent_events}` vào template
- Hướng dẫn cụ thể: "Ai liên quan? Quy mô? Con số?"

---

### PHASE 2 TEST PLAN (Quinn)

| Test | File | Mô tả |
|------|------|-------|
| `test_fetch_article_text_success` | `test_breaking/test_content_generator.py` | Mock httpx + trafilatura → return 1500 chars |
| `test_fetch_article_text_timeout` | `test_breaking/test_content_generator.py` | Mock timeout → return "" (graceful) |
| `test_breaking_with_article_body` | `test_breaking/test_content_generator.py` | Event có article body → prompt chứa "Nội dung bài gốc" |
| `test_breaking_with_market_context` | `test_breaking/test_content_generator.py` | market_context="BTC: $74,589" → prompt chứa "Bối cảnh thị trường" |
| `test_breaking_with_recent_events` | `test_breaking/test_content_generator.py` | recent_events có 3 tin → prompt chứa "Tin Breaking gần đây" |
| `test_breaking_without_enrichment` | `test_breaking/test_content_generator.py` | Mọi enrichment fail → fallback về title-only (backward compatible) |
| `test_format_market_snapshot` | `test_breaking/test_breaking_pipeline.py` | Input market data → format "BTC: $74,589 (+0.0%) \| F&G: 26" |
| `test_format_recent_events` | `test_breaking/test_breaking_pipeline.py` | Input 10 entries → return top 5 mới nhất |

---

## PHASE 3 — Breaking News Classification (B1, B2, B4, F4)

### 3.1. Coin whitelist filter (B2)

**File sửa**: `breaking_pipeline.py`

**Thêm sau event detection, trước severity classification:**

```python
# Load CIC tracked coins from DANH_SACH_COIN sheet
tracked_coins = await _load_tracked_coins()  # returns set of symbols

# Filter: keep only events about tracked coins OR non-coin-specific events
filtered_events = []
for event in events:
    # Extract coin symbols from title
    coins_in_title = _extract_coins_from_title(event.title, tracked_coins)

    if coins_in_title:
        # Coin-specific event: keep only if coin is tracked
        if coins_in_title & tracked_coins:
            filtered_events.append(event)
        else:
            logger.info(f"Filtered non-CIC coin event: {event.title}")
    else:
        # Non-coin-specific (regulatory, macro): always keep
        filtered_events.append(event)

events = filtered_events
```

**Helper `_extract_coins_from_title()`**:
```python
_COIN_PATTERN = re.compile(r'\b([A-Z]{2,10})\b')  # Match uppercase 2-10 chars

def _extract_coins_from_title(title: str, known_coins: set[str]) -> set[str]:
    """Extract known coin symbols from title."""
    candidates = set(_COIN_PATTERN.findall(title.upper()))
    # Filter: only return symbols that are known coins (avoid false positives like "SEC", "ETF")
    return candidates & known_coins
```

---

### 3.2. Phân biệt % giá vs % volume (B1)

**File sửa**: `breaking/severity_classifier.py` dòng 156-163

```python
# TRƯỚC:
pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", event.title)
if pct_match:
    pct_value = float(pct_match.group(1))
    if pct_value >= 10:
        return CRITICAL

# SAU:
pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", event.title)
if pct_match:
    pct_value = float(pct_match.group(1))
    title_lower = event.title.lower()

    # Only apply percentage severity for PRICE movements, not volume/OI/etc.
    VOLUME_KEYWORDS = {"volume", "trading volume", "open interest", "oi", "tvl"}
    PRICE_KEYWORDS = {"drop", "crash", "fall", "plunge", "surge", "soar", "gain", "rise", "jump"}

    is_volume = any(kw in title_lower for kw in VOLUME_KEYWORDS)
    is_price = any(kw in title_lower for kw in PRICE_KEYWORDS)

    if is_price and not is_volume:
        if pct_value >= 10:
            return "critical"
        if pct_value >= 3:
            return "important"
    # Volume % or ambiguous → do NOT use percentage for severity
```

---

### 3.3. Dedup similarity check (F4)

**File sửa**: `breaking/dedup_manager.py`

**Thêm sau hash check, trước return:**

```python
from difflib import SequenceMatcher

def _is_similar_to_recent(title: str, recent_entries: list, threshold: float = 0.70) -> bool:
    """Check if title is similar to any recent entry (beyond hash match)."""
    title_lower = title.strip().lower()
    for entry in recent_entries:
        existing_lower = entry.title.strip().lower()
        ratio = SequenceMatcher(None, title_lower, existing_lower).ratio()
        if ratio >= threshold:
            logger.info(f"Similarity dedup: '{title[:50]}' ~ '{entry.title[:50]}' ({ratio:.2f})")
            return True
    return False
```

**Tích hợp vào `is_duplicate()`**: Sau hash check fail (hash mới), thêm similarity check.

---

### 3.4. Đồng bộ keyword lists (B4)

**File sửa**: `breaking/severity_classifier.py`

```python
# Thêm "crash" vào IMPORTANT (không phải CRITICAL):
DEFAULT_IMPORTANT_KEYWORDS = [
    "crash",  # NEW — was only in event_detector, not classifier
    "partnership",
    "liquidation",
    # ... (rest unchanged)
]
```

---

### PHASE 3 TEST PLAN (Quinn)

| Test | Mô tả |
|------|-------|
| `test_filter_non_cic_coin` | PIPPIN event → filtered out (not in CIC list) |
| `test_keep_cic_coin` | BTC event → kept |
| `test_keep_macro_event` | "Argentina bans Polymarket" (no coin) → kept |
| `test_volume_pct_not_critical` | "Zcash 108% volume" → NOT critical |
| `test_price_pct_critical` | "BTC drops 12%" → critical |
| `test_dedup_similar_title` | "PIPPIN crashes 49%..." vs "Sự sụp đổ của PIPPIN" → duplicate |
| `test_dedup_different_event` | "BTC drops 10%" vs "ETH drops 8%" → NOT duplicate |
| `test_crash_keyword_important` | Title contains "crash" → severity = important (not critical) |

---

## PHASE 4 — Data Pipeline Improvements (F1, F2, F3, F5, F6, F7)

### 4.1. Giữ full_text trong data flow (F1)

**File sửa**: `daily_pipeline.py` dòng 225-245

```python
# TRƯỚC (dòng 228-234):
all_news.append({
    "title": a.title,
    "url": a.url,
    "source_name": a.source_name,
    "summary": a.summary,
    ...
})

# SAU — thêm full_text:
all_news.append({
    "title": a.title,
    "url": a.url,
    "source_name": a.source_name,
    "summary": a.summary,
    "full_text": getattr(a, "full_text", ""),  # NEW: preserve full text
    ...
})
```

**Sửa format cho LLM** (dòng 269):

```python
# TRƯỚC:
line += f"\n  Tóm tắt: {summary[:300]}"

# SAU — dùng full_text nếu có, fallback summary:
text_for_llm = a.get("full_text", "") or a.get("summary", "")
if text_for_llm:
    line += f"\n  Nội dung: {text_for_llm[:800]}"  # 300 → 800 chars
```

**Token budget check**: 30 articles × 800 chars ≈ 24,000 chars ≈ 6,000 tokens. Gemini Flash context = 1M tokens → OK. Groq 128K → OK.

---

### 4.2. Trafilatura cho top RSS news feeds (F2)

**File sửa**: `collectors/rss_collector.py`

**Thay đổi**: Thêm `enrich=True` cho top 5 news feeds (sources có bài dài, chất lượng cao):

```python
FeedConfig("https://cointelegraph.com/rss", "CoinTelegraph", "en", enrich=True),
FeedConfig("https://coindesk.com/arc/outboundfeeds/rss/", "CoinDesk", "en", enrich=True),
FeedConfig("https://theblock.co/rss.xml", "TheBlock", "en", enrich=True),
FeedConfig("https://decrypt.co/feed", "Decrypt", "en", enrich=True),
FeedConfig("https://blockworks.co/feed/", "Blockworks", "en", enrich=True),
```

**Sửa collection logic**: Hiện tại chỉ `source_type="research"` mới enrich. Thêm check `enrich=True`:

```python
# Trong _collect_single_feed():
if feed.source_type == "research" or getattr(feed, "enrich", False):
    # Run trafilatura extraction
    article.full_text = await _extract_text(article.url, max_chars=2000)
```

**FeedConfig dataclass** — thêm field:
```python
@dataclass
class FeedConfig:
    url: str
    name: str
    language: str
    source_type: str = "news"
    enabled: bool = True
    enrich: bool = False  # NEW: enable trafilatura for this feed
```

---

### 4.3. Thêm nguồn tin mới (F3)

**File sửa**: `collectors/rss_collector.py` — thêm vào DEFAULT_FEEDS:

```python
# New sources (researched, RSS confirmed working):
FeedConfig("https://crypto.news/feed/", "CryptoNews", "en"),
FeedConfig("https://bitcoinist.com/feed/", "Bitcoinist", "en"),
FeedConfig("https://cryptopotato.com/feed/", "CryptoPotato", "en"),
FeedConfig("https://blogtienao.com/feed/", "BlogTienAo", "vi"),

# Re-test disabled feeds:
FeedConfig("https://vn.beincrypto.com/feed/", "BeInCrypto_VN", "vi"),  # re-enable, test
```

**Sau thêm**: Chạy test verify mỗi feed → nếu vẫn 403/404 → set `enabled=False` lại.

---

### 4.4. Cải thiện crypto relevance filter (F5)

**File sửa**: `collectors/data_cleaner.py` trong `_filter_non_crypto()`

**Thêm macro whitelist** — tin chứa macro keywords KHÔNG bị filter:

```python
MACRO_WHITELIST_KEYWORDS = {
    "fed", "fomc", "interest rate", "lãi suất", "inflation", "lạm phát",
    "cpi", "gdp", "tariff", "thuế quan", "treasury", "bond", "trái phiếu",
    "dollar", "dxy", "gold", "vàng", "oil", "dầu",
    "sec", "regulation", "quy định", "ban", "cấm",
}

def _filter_non_crypto(articles, keywords_lower):
    for article in articles:
        text = f"{article.get('title', '')} {article.get('summary', '')}".lower()

        # Skip filter for macro-relevant articles
        if any(kw in text for kw in MACRO_WHITELIST_KEYWORDS):
            article["filtered"] = False
            continue

        is_relevant = _text_has_crypto_keyword(text, keywords_lower)
        if not is_relevant:
            article["filtered"] = True
            logger.info(f"Non-crypto filtered: {article.get('title', '')[:60]}")  # info, not debug
```

**Thay đổi log level**: `debug` → `info` để filtered articles hiện trong log bình thường.

---

### 4.5. Data quality gate (F6)

**File sửa**: `daily_pipeline.py` — sau collection, trước generation

```python
# After all collection completes:
min_news = 5
has_market = bool(market_data)

if len(cleaned_news) < min_news and not has_market:
    logger.error(f"Data quality FAIL: {len(cleaned_news)} news, market={has_market}")
    # Notify operator instead of generating empty report
    await _notify_operator_data_insufficient(len(cleaned_news), has_market)
    return  # Skip generation
```

---

### 4.6. Telegram truncation warning (F7)

**File sửa**: `delivery/telegram_bot.py`

```python
# Trong send function, khi split message:
if len(content) > TG_MAX_LENGTH:
    logger.warning(f"Article truncated: {len(content)} > {TG_MAX_LENGTH}")
    # Add truncation notice before sending
    content = content[:TG_MAX_LENGTH - 80] + "\n\n... [Bài viết đã được rút gọn]"
```

---

### PHASE 4 TEST PLAN (Quinn)

| Test | Mô tả |
|------|-------|
| `test_full_text_preserved_in_pipeline` | RSS article có full_text → dict chứa full_text |
| `test_llm_receives_800_chars` | Verify LLM prompt chứa `Nội dung:` với ≤800 chars |
| `test_enriched_feed_extracts_full_text` | Feed có enrich=True → trafilatura gọi |
| `test_non_enriched_feed_no_extraction` | Feed không có enrich → trafilatura KHÔNG gọi |
| `test_new_feeds_active` | 4 new feeds trong DEFAULT_FEEDS, enabled=True |
| `test_macro_not_filtered` | "Fed giữ lãi suất" → KHÔNG bị crypto filter |
| `test_non_crypto_still_filtered` | "Taylor Swift concert" → bị filter |
| `test_data_quality_gate_blocks` | 0 news + no market → pipeline return early |
| `test_data_quality_gate_passes` | 10 news + market → pipeline continues |
| `test_telegram_truncation_notice` | 5000 char article → output chứa "[Bài viết đã được rút gọn]" |

---

## PHASE 5 — Daily Report Anti-Repetition (C1, C2, C3, C4, E3, E5)

### 5.1. Cải thiện inter-tier context (C1)

**File sửa**: `generators/article_generator.py` hàm `_summarize_tier_output()`

**Thay đổi**: Thay vì extract section headers + 120 chars, tạo **structured data summary**:

```python
def _summarize_tier_output(tier: str, content: str) -> str:
    """Create structured summary of tier's key data points for dedup."""
    focus = _TIER_FOCUS.get(tier, "")

    # Extract data points mentioned (numbers, percentages, coin names)
    numbers = re.findall(r'[\$€]?[\d,]+\.?\d*[%KMB]?', content)
    coins = re.findall(r'\b(?:BTC|ETH|SOL|BNB|XRP|ADA|DOGE|AVAX|TRX|LINK)\b', content)

    # Extract key conclusions (sentences with strong verbs)
    sentences = re.split(r'[.!?\n]', content)
    key_sentences = [s.strip() for s in sentences
                     if len(s.strip()) > 30 and len(s.strip()) < 200][:5]

    parts = [f"[{tier}] ({focus}):"]
    if coins:
        parts.append(f"  Coins đã phân tích: {', '.join(set(coins))}")
    if numbers:
        parts.append(f"  Số liệu đã dùng: {', '.join(numbers[:10])}")
    for s in key_sentences[:3]:
        parts.append(f"  - {s[:200]}")

    return "\n".join(parts)
```

**Tăng limit snippet**: 120 → 200 chars, 6 → max 8 items.

---

### 5.2. Tier-specific Metrics Engine output (C2)

**File sửa**: `generators/metrics_engine.py` hàm `format_for_tier()`

**Thay đổi**: Mỗi tier nhận **góc nhìn khác** từ cùng data:

```python
def format_for_tier(self, tier: str) -> str:
    parts = []

    if tier in ("L1", "L2"):
        parts.append(f"TRẠNG THÁI: {self.regime.format_vi()}")
        parts.append(f"SENTIMENT: {self.sentiment_analysis}")

    elif tier == "L3":
        parts.append(f"TRẠNG THÁI: {self.regime.format_vi()}")
        # L3 focus: WHY — causal chain
        parts.append("PHÂN TÍCH NGUYÊN NHÂN (cho L3 — giải thích TẠI SAO):")
        parts.append(f"  Macro: {self.macro_analysis}")
        parts.append(f"  Derivatives: {self.derivatives_analysis}")
        parts.append("  → Nối macro + derivatives thành chuỗi nhân-quả.")

    elif tier == "L4":
        # L4 focus: RISK — contradictions
        parts.append("PHÂN TÍCH RỦI RO (cho L4 — chỉ ra MÂU THUẪN):")
        parts.append(f"  {self.cross_signal_summary}")
        parts.append("  → Mâu thuẫn = rủi ro gì cho trader?")

    elif tier == "L5":
        # L5 focus: SCENARIOS — multiple outcomes
        parts.append("PHÂN TÍCH KỊCH BẢN (cho L5 — base/bull/bear):")
        parts.append(f"  Regime: {self.regime.format_vi()}")
        parts.append(f"  Signals: {self.cross_signal_summary}")
        if self.volume_analysis:
            parts.append(f"  Volume: {self.volume_analysis}")
        parts.append("  → Xây dựng 3 kịch bản từ data trên.")

    return "\n".join(parts)
```

---

### 5.3. Post-generation repetition check (C3)

**File sửa**: `daily_pipeline.py` — sau generate, trước deliver

```python
def _check_cross_tier_repetition(articles: list) -> dict:
    """Check for repeated phrases across tier articles."""
    from collections import Counter

    # Extract 4-gram phrases from each tier
    tier_phrases = {}
    for article in articles:
        words = article.content.lower().split()
        ngrams = [" ".join(words[i:i+4]) for i in range(len(words)-3)]
        tier_phrases[article.tier] = set(ngrams)

    # Find phrases appearing in 3+ tiers
    all_phrases = Counter()
    for phrases in tier_phrases.values():
        for p in phrases:
            all_phrases[p] += 1

    repeated = {p: c for p, c in all_phrases.items() if c >= 3}

    if repeated:
        logger.warning(f"Cross-tier repetition: {len(repeated)} phrases in 3+ tiers")
        for phrase, count in list(repeated.items())[:5]:
            logger.warning(f"  '{phrase}' in {count} tiers")

    return {"repeated_count": len(repeated), "total_phrases": len(all_phrases)}
```

**Gọi sau generation**: Log only (Phase 1). Tương lai: regenerate nếu score quá cao.

---

### 5.4. NQ05 filter sửa thay vì xóa (E5)

**File sửa**: `generators/nq05_filter.py` hàm `_remove_sentences_with_pattern()`

**Thay đổi**: Thay vì xóa cả câu, chỉ xóa cụm từ vi phạm:

```python
def _remove_violation_from_text(text: str, pattern: re.Pattern) -> str:
    """Remove only the violating phrase, keep the rest of the sentence."""
    # For bullet points: remove entire bullet (unchanged — bullets are short)
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        if pattern.search(line):
            if line.strip().startswith(("-", "•")):
                continue  # Remove whole bullet
            else:
                # Remove only the matching phrase + surrounding filler
                cleaned_line = pattern.sub("", line)
                # Clean up double spaces, orphaned punctuation
                cleaned_line = re.sub(r'\s{2,}', ' ', cleaned_line)
                cleaned_line = re.sub(r'\s+([,.])', r'\1', cleaned_line)
                if cleaned_line.strip():
                    cleaned.append(cleaned_line)
        else:
            cleaned.append(line)
    return "\n".join(cleaned)
```

---

### PHASE 5 TEST PLAN (Quinn)

| Test | Mô tả |
|------|-------|
| `test_improved_tier_summary` | L1 output về BTC → summary chứa "BTC" trong "Coins đã phân tích" |
| `test_tier_specific_metrics_l3` | L3 nhận "PHÂN TÍCH NGUYÊN NHÂN" không nhận "PHÂN TÍCH RỦI RO" |
| `test_tier_specific_metrics_l4` | L4 nhận "PHÂN TÍCH RỦI RO" |
| `test_repetition_check_detects` | 3 articles chứa "thị trường đi ngang" → repeated_count > 0 |
| `test_repetition_check_clean` | 3 articles nội dung khác nhau → repeated_count = 0 |
| `test_nq05_remove_phrase_keep_sentence` | "BTC tăng 15% và nên mua vào" → "BTC tăng 15%" |
| `test_nq05_remove_bullet_entirely` | "- Nên mua BTC ngay" → bullet removed |

---

## TỔNG HỢP FILES THAY ĐỔI

| Phase | Files sửa | Files mới | Dòng thay đổi (ước lượng) |
|-------|-----------|-----------|--------------------------|
| 1 | 3 files | 0 | ~60 dòng |
| 2 | 2 files | 0 | ~120 dòng |
| 3 | 3 files | 0 | ~80 dòng |
| 4 | 4 files | 0 | ~70 dòng |
| 5 | 3 files | 0 | ~100 dòng |
| **Tổng** | **10 files unique** | **0** | **~430 dòng** |

**Không tạo file mới** — tất cả sửa vào files hiện có.

---

## RỦI RO & GIẢM THIỂU

| Rủi ro | Phase | Giảm thiểu |
|--------|-------|------------|
| Trafilatura tăng latency Breaking | 2 | Timeout 8s + fallback title-only |
| Full_text tăng token count Daily | 4 | Cap 800 chars/article, token budget OK |
| New feeds 403/404 | 4 | Test trước → disable nếu fail |
| Temperature thấp = output cứng nhắc | 1 | Monitor output quality 1 tuần, rollback nếu cần |
| Coin whitelist chặn tin quan trọng | 3 | Macro/regulatory events bypass whitelist |
| Post-gen check false positive | 5 | Log only, không auto-reject |
