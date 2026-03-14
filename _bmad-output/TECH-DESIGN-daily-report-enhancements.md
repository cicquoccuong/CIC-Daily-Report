# Technical Design: Daily Report Enhancements

> **Version**: 1.0
> **Date**: 2026-03-13
> **Author**: Winston (Architect)
> **Spec Reference**: `SPEC-daily-report-enhancements-v3-final.md`
> **Status**: Ready for review

---

## Table of Contents

1. [Data Structure Changes](#1-data-structure-changes)
2. [Selective HTML Escape Implementation](#2-selective-html-escape-implementation)
3. [Data Flow Through Pipeline](#3-data-flow-through-pipeline)
4. [Hyperlink Injection at Delivery Layer](#4-hyperlink-injection-at-delivery-layer)
5. [send_photo() Method Design](#5-send_photo-method-design)
6. [RSS Collector Changes](#6-rss-collector-changes)
7. [Template Engine Format Changes](#7-template-engine-format-changes)
8. [NQ05 Filter Enhancement](#8-nq05-filter-enhancement)
9. [Interface Contracts](#9-interface-contracts)

---

## 1. Data Structure Changes

### 1.1. `FeedConfig` — `rss_collector.py:32-39`

**Current fields:**
```python
@dataclass
class FeedConfig:
    """RSS feed configuration."""
    url: str
    source_name: str
    language: str  # "vi" or "en"
    enabled: bool = True
```

**New fields to add:**
```python
@dataclass
class FeedConfig:
    """RSS feed configuration."""
    url: str
    source_name: str
    language: str  # "vi" or "en"
    enabled: bool = True
    source_type: str = "news"  # "news" or "research"
```

**Migration notes:**
- Default `source_type="news"` preserves backward compatibility for all 17 existing feeds.
- No constructor call changes required for existing code.
- `DEFAULT_FEEDS` entries do not need modification (they inherit the default).
- The 4 new research feeds will explicitly pass `source_type="research"`.

---

### 1.2. `NewsArticle` — `rss_collector.py:67-93`

**Current fields:**
```python
@dataclass
class NewsArticle:
    """Parsed news article from RSS."""
    title: str
    url: str
    source_name: str
    published_date: str
    summary: str
    language: str
```

**New fields to add:**
```python
@dataclass
class NewsArticle:
    """Parsed news article from RSS."""
    title: str
    url: str
    source_name: str
    published_date: str
    summary: str
    language: str
    source_type: str = "news"        # "news" or "research"
    og_image: str | None = None      # Open Graph image URL (research feeds)
    full_text: str = ""              # Full article text (research feeds only, via trafilatura)
```

**`to_row()` change:**
```python
def to_row(self) -> list[str]:
    """Convert to Sheets row for TIN_TUC_THO tab."""
    collected_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return [
        "",  # ID (auto)
        self.title,
        self.url,
        self.source_name,
        collected_at,
        self.language,
        self.summary,
        self.source_type,  # was: "" (event_type column) — now stores source_type
        "",  # coin_symbol
        "",  # sentiment_score
        "",  # action_category
    ]
```

**Migration notes:**
- `source_type` defaults to `"news"` — backward compatible.
- `og_image` defaults to `None` — no impact on existing flows.
- `full_text` defaults to `""` — only populated for research feeds.
- The `event_type` column (index 7) in Sheets is currently always empty string. Writing `source_type` there requires no schema change.

---

### 1.3. `CryptoPanicArticle` — `cryptopanic_client.py:22-37`

**Current fields:**
```python
@dataclass
class CryptoPanicArticle:
    """News article from CryptoPanic with sentiment."""
    title: str
    url: str
    source_name: str
    published_date: str
    summary: str
    full_text: str
    panic_score: float
    votes_bullish: int
    votes_bearish: int
    currencies: list[str] | None = None
    news_type: str = "crypto"
    language: str = "en"
```

**New fields to add:**
```python
@dataclass
class CryptoPanicArticle:
    """News article from CryptoPanic with sentiment."""
    title: str
    url: str
    source_name: str
    published_date: str
    summary: str
    full_text: str
    panic_score: float
    votes_bullish: int
    votes_bearish: int
    currencies: list[str] | None = None
    news_type: str = "crypto"
    language: str = "en"
    og_image: str | None = None  # Open Graph image URL
```

**Where og_image is extracted — `_extract_fulltext()` modification:**
```python
async def _extract_one(article: CryptoPanicArticle) -> None:
    try:
        async with httpx.AsyncClient(timeout=TRAFILATURA_TIMEOUT) as client:
            resp = await client.get(article.url, follow_redirects=True)
        text = await asyncio.to_thread(
            trafilatura.extract, resp.text, include_comments=False
        )
        if text:
            article.full_text = text[:2000]
            if not article.summary:
                article.summary = text[:500]
        # NEW: extract og:image metadata
        metadata = await asyncio.to_thread(trafilatura.extract_metadata, resp.text)
        if metadata and metadata.image:
            article.og_image = metadata.image
    except Exception as e:
        logger.debug(f"Full-text extraction failed for {article.url}: {e}")
```

**Migration notes:**
- `og_image` defaults to `None` — backward compatible.
- CryptoPanic articles are `source_type="news"` implicitly. Their og:image will be extracted but only used if relevant (research-like content). In practice, image selection logic filters by `source_type`, so CryptoPanic images are deprioritized.

---

### 1.4. `GeneratedArticle` — `article_generator.py:56-66`

**Current fields:**
```python
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
```

**New fields to add:**
```python
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
    source_urls: list[dict[str, str]] = field(default_factory=list)
    # Each dict: {"name": "CoinTelegraph", "url": "https://..."}
    # Populated from news articles used as LLM context
```

**Migration notes:**
- `source_urls` defaults to empty list via `field(default_factory=list)`.
- Requires `from dataclasses import field` import (already imported in module).
- Existing code constructing `GeneratedArticle` in `_generate_single_article()` will need to pass `source_urls`.

---

### 1.5. `GenerationContext` — `article_generator.py:69-79`

**Current fields:**
```python
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
```

**New fields to add:**
```python
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
    source_url_map: list[dict[str, str]] = field(default_factory=list)
    # Master list of {"name": "source_name", "url": "article_url", "source_type": "news"|"research"}
    # Used to attach source URLs to GeneratedArticle after generation
    research_summary: str = ""
    # Separate research text block for L3-L5 prioritization
```

**Migration notes:**
- Both new fields default to empty — backward compatible.
- `source_url_map` is populated from `cleaned_news` in the pipeline.
- `research_summary` is populated with research-only articles for L3-L5 context.

---

### 1.6. `TelegramMessage` — `telegram_bot.py:28-44`

**Current fields:**
```python
@dataclass
class TelegramMessage:
    """A message ready to send via Telegram Bot API."""
    tier_label: str
    content: str
    part: int = 1
    total_parts: int = 1
```

**New fields to add:**
```python
@dataclass
class TelegramMessage:
    """A message ready to send via Telegram Bot API."""
    tier_label: str
    content: str
    part: int = 1
    total_parts: int = 1
    source_urls: list[dict[str, str]] = field(default_factory=list)
    # {"name": "...", "url": "..."} — for hyperlink injection
    image_urls: list[str] = field(default_factory=list)
    # og:image URLs to send via sendPhoto before text
```

**Migration notes:**
- Both new fields default to empty list — backward compatible.
- `formatted` property does not change (hyperlink injection happens at a different layer).
- Requires `from dataclasses import field` import (not currently imported — add it).

---

### 1.7. `DeliveryResult` — `delivery_manager.py:25-50`

**Current fields — NO CHANGES needed.** `DeliveryResult` tracks delivery status, not content. The article dict schema change (Section 1.8 below) is sufficient.

---

### 1.8. Article Dict Schema (Pipeline → Delivery)

**Current schema (used throughout pipeline):**
```python
{"tier": "L1", "content": "..."}
```

**New schema:**
```python
{
    "tier": "L1",
    "content": "...",                    # plain text from LLM (no HTML)
    "source_urls": [                     # NEW
        {"name": "CoinTelegraph", "url": "https://..."},
        {"name": "Messari", "url": "https://..."},
    ],
    "image_urls": ["https://..."],       # NEW — og:image URLs from research sources
}
```

**Migration notes:**
- All code reading article dicts uses `.get()` with defaults, so missing keys are safe.
- `source_urls` and `image_urls` are optional — empty list if absent.
- The schema change propagates from `_execute_stages()` through `_deliver()` to `DeliveryManager.deliver()`.

---

## 2. Selective HTML Escape Implementation

### 2.1. Problem Statement

**Current code at `telegram_bot.py:144`:**
```python
text = html_lib.escape(text)
```
This escapes ALL HTML, including `<a href="...">` tags that Telegram needs for clickable hyperlinks. Any `<a>` tag injected by the delivery layer will be escaped to `&lt;a href=...&gt;` and rendered as literal text.

### 2.2. Design: `selective_html_escape()` Function

```python
import re
import html as html_lib

# Strict whitelist: only <a href="...">text</a> tags are preserved
_SAFE_A_TAG = re.compile(
    r'<a\s+href="([^"]*)">(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)

# Dangerous href schemes to block
_DANGEROUS_SCHEMES = re.compile(
    r'^\s*(javascript|data|vbscript|file)\s*:',
    re.IGNORECASE,
)

# Characters that must be escaped outside of whitelisted tags
_AMP_OUTSIDE = re.compile(r'&(?!amp;|lt;|gt;|quot;)')


def selective_html_escape(text: str) -> str:
    """Escape HTML entities while preserving safe <a href="..."> tags.

    Security strategy:
    1. Extract all <a> tags from text
    2. Validate each href (block javascript:, data:, etc.)
    3. Escape the link text inside <a> tags
    4. Escape everything else with html.escape()
    5. Re-insert validated <a> tags

    Args:
        text: Raw text potentially containing <a href="..."> tags.

    Returns:
        HTML-safe text with only valid <a> tags preserved.
    """
    if '<a ' not in text.lower():
        # Fast path: no links at all, escape everything
        return html_lib.escape(text)

    # Step 1: Extract <a> tags and replace with placeholders
    placeholders: dict[str, str] = {}
    placeholder_idx = 0

    def _replace_tag(match: re.Match) -> str:
        nonlocal placeholder_idx
        href = match.group(1)
        link_text = match.group(2)

        # Step 2: Validate href — block dangerous schemes
        if _DANGEROUS_SCHEMES.match(href):
            # Dangerous link — escape it entirely (render as text)
            return html_lib.escape(match.group(0))

        # Step 3: Sanitize href — escape special chars in URL
        safe_href = (
            href.replace("&", "&amp;")
            .replace('"', "&quot;")
            .replace("'", "&#x27;")
        )

        # Step 4: Escape link text (prevent nested HTML)
        safe_text = html_lib.escape(link_text)

        # Step 5: Build safe <a> tag
        safe_tag = f'<a href="{safe_href}">{safe_text}</a>'

        placeholder = f"\x00LINK{placeholder_idx}\x00"
        placeholders[placeholder] = safe_tag
        placeholder_idx += 1
        return placeholder

    text_with_placeholders = _SAFE_A_TAG.sub(_replace_tag, text)

    # Step 6: Escape everything else
    escaped = html_lib.escape(text_with_placeholders)

    # Step 7: Re-insert safe <a> tags
    for placeholder, safe_tag in placeholders.items():
        escaped_placeholder = html_lib.escape(placeholder)
        escaped = escaped.replace(escaped_placeholder, safe_tag)

    return escaped
```

### 2.3. Integration Point

In `telegram_bot.py`, replace line 144:

**Before:**
```python
text = html_lib.escape(text)
```

**After:**
```python
text = selective_html_escape(text)
```

### 2.4. Edge Cases Handled

| Edge Case | Handling |
|-----------|----------|
| `<a href="javascript:alert(1)">XSS</a>` | Blocked — entire tag escaped to visible text |
| `<a href="data:text/html,...">Click</a>` | Blocked — dangerous scheme |
| `<a href="https://ok.com">Safe <b>bold</b></a>` | Inner `<b>` escaped: `Safe &lt;b&gt;bold&lt;/b&gt;` |
| `<a href="url1"><a href="url2">nested</a></a>` | Regex is non-greedy (`.*?`) — matches innermost first. Outer broken `<a>` is escaped. |
| `<a href="url">unclosed` | Does not match regex — escaped entirely |
| `<script>alert(1)</script>` | Does not match `<a>` whitelist — escaped entirely |
| `<a href="url" onclick="...">text</a>` | Regex requires `<a\s+href="...">`  — `onclick` attribute not captured, tag not matched, escaped entirely |
| `&` in text outside tags | Escaped to `&amp;` by `html_lib.escape()` |
| No `<a>` tags at all | Fast path — `html_lib.escape()` on entire string |

### 2.5. XSS Prevention Strategy

1. **Whitelist-only**: Only `<a href="...">text</a>` is allowed. All other HTML tags are escaped.
2. **Scheme validation**: `javascript:`, `data:`, `vbscript:`, `file:` schemes are blocked.
3. **Attribute restriction**: The regex only matches `href` — no `onclick`, `onmouseover`, etc.
4. **Link text escaping**: Text inside `<a>` tags is HTML-escaped to prevent nested tag injection.
5. **URL sanitization**: `&`, `"`, `'` in URLs are entity-encoded.

---

## 3. Data Flow Through Pipeline

### 3.1. Current Flow (simplified)

```
collect_rss() → list[NewsArticle]
collect_cryptopanic() → list[CryptoPanicArticle]
    ↓
    Unified dict: {"title", "url", "source_name", "summary", "news_type"}
    ↓
clean_articles() → CleanResult.articles (list[dict])
    ↓
    news_text (plain string for LLM context)
    ↓
GenerationContext(news_summary=news_text)
    ↓
generate_tier_articles() → list[GeneratedArticle]
    ↓
check_and_fix() → FilterResult
    ↓
    articles_out: [{"tier": "L1", "content": "..."}]
    ↓
DeliveryManager.deliver(articles_out) → DeliveryResult
    ↓
TelegramBot.deliver_all(messages)
```

### 3.2. New Flow — with source_urls, og_image, source_type

```
collect_rss() → list[NewsArticle]
                  ↑ now includes: source_type, og_image, full_text
collect_cryptopanic() → list[CryptoPanicArticle]
                  ↑ now includes: og_image
    ↓
    Unified dict (CHANGED):
    {
        "title": str,
        "url": str,
        "source_name": str,
        "summary": str,
        "news_type": str,         # existing (crypto/macro)
        "source_type": str,       # NEW: "news" or "research"
        "og_image": str | None,   # NEW: og:image URL
        "full_text": str,         # NEW: research full text
    }
    ↓
clean_articles() → CleanResult.articles
    ↑ Preserve source_type, og_image, full_text through dedup merge
    ↓
    Build source_url_map:
    [{"name": "CoinTelegraph", "url": "https://...", "source_type": "news"}, ...]
    ↓
    Build news_text (unchanged for L1-L2)
    Build research_text (NEW — research articles only, for L3-L5):
        "=== RESEARCH INSIGHTS ===\n- Title (Source)\n  Full: full_text[:500]"
    ↓
    Collect image_urls:
    [url for url in og_images if source_type == "research"][:3]
    ↓
GenerationContext(
    news_summary=news_text,
    research_summary=research_text,       # NEW
    source_url_map=source_url_map,        # NEW
)
    ↓
generate_tier_articles() → list[GeneratedArticle]
    ↑ Each GeneratedArticle now has source_urls populated
    ↑ L3-L5 prompts include research_summary in context
    ↓
check_and_fix() → FilterResult (unchanged — scans plain text)
    ↓
    articles_out (CHANGED):
    [
        {
            "tier": "L1",
            "content": "...",
            "source_urls": [{"name": "...", "url": "..."}],    # NEW
            "image_urls": ["https://og-image-url.jpg"],         # NEW
        }
    ]
    ↓
DeliveryManager.deliver(articles_out)
    ↑ Orchestrates: send photos → format text with hyperlinks → send messages
    ↓
TelegramBot.send_photo() → photo messages    # NEW
TelegramBot.deliver_all() → text messages
    ↑ selective_html_escape() preserves <a> tags
```

### 3.3. Exact Dict Keys at Each Stage

**Stage: RSS → Unified Dict** (`daily_pipeline.py:172-200`)

```python
# For RSS articles (CHANGED):
for a in rss_articles:
    all_news.append({
        "title": a.title,
        "url": a.url,
        "source_name": a.source_name,
        "summary": a.summary,
        "source_type": a.source_type,      # NEW
        "og_image": a.og_image,            # NEW
        "full_text": a.full_text,          # NEW
    })

# For CryptoPanic articles (CHANGED):
for a in crypto_articles:
    all_news.append({
        "title": a.title,
        "url": a.url,
        "source_name": a.source_name,
        "summary": a.summary,
        "news_type": getattr(a, "news_type", "crypto"),
        "source_type": "news",             # CryptoPanic is always news
        "og_image": a.og_image,            # NEW
    })

# For Telegram messages (unchanged — no source_type/og_image):
for m in tg_messages:
    all_news.append({
        "title": m.message_text[:100] if m.message_text else "",
        "url": "",
        "source_name": f"TG:{m.channel_name}",
        "summary": m.message_text or "",
        "source_type": "news",             # TG scraper is always news
    })
```

**Stage: Cleaned News → Source URL Map** (`daily_pipeline.py`, new code)

```python
# After clean_articles():
source_url_map: list[dict[str, str]] = []
image_urls: list[str] = []

for a in cleaned_news[:30]:
    if a.get("url"):
        source_url_map.append({
            "name": a.get("source_name", ""),
            "url": a.get("url", ""),
            "source_type": a.get("source_type", "news"),
        })
    # Collect research images only
    if a.get("source_type") == "research" and a.get("og_image"):
        image_urls.append(a["og_image"])

image_urls = image_urls[:3]  # max 3 images per day
```

**Stage: Build Research Summary Text** (`daily_pipeline.py`, new code)

```python
# Separate research summary for L3-L5
research_items = []
for a in cleaned_news[:30]:
    if a.get("source_type") == "research":
        line = f"- {a.get('title', '')} ({a.get('source_name', '')})"
        full = a.get("full_text", "")
        if full:
            line += f"\n  Full: {full[:500]}"
        elif a.get("summary"):
            line += f"\n  Summary: {a['summary'][:300]}"
        research_items.append(line)

research_text = ""
if research_items:
    research_text = "=== RESEARCH INSIGHTS ===\n" + "\n".join(research_items)
```

**Stage: GenerationContext → GeneratedArticle** (`article_generator.py`, modified)

```python
# In generate_tier_articles(), after generating content:
article = GeneratedArticle(
    tier=tier,
    title=f"[{tier}] Phân tích thị trường tài sản mã hóa",
    content=content_with_disclaimer,
    word_count=word_count,
    llm_used=response.model,
    generation_time_sec=elapsed,
    source_urls=context.source_url_map,  # NEW — pass through
)
```

**Stage: NQ05 Filter → articles_out** (`daily_pipeline.py:437-444`, modified)

```python
articles_out: list[dict[str, str]] = []
for article in generated:
    filtered = check_and_fix(article.content)
    articles_out.append({
        "tier": article.tier,
        "content": filtered.content,
        "source_urls": article.source_urls,    # NEW — pass through
        "image_urls": image_urls if article.tier in ("L1", "L3", "L5") else [],  # NEW
    })
```

Note: `image_urls` is shared across tiers and attached to specific tiers (L1 for hero image, L3/L5 for research charts). The exact tier assignment is configurable; initial implementation attaches to L1 only since it is sent first.

**Revised approach for image_urls:**
- Attach `image_urls` only to the FIRST article dict (L1). The delivery manager sends photos before the first text message.
- This avoids duplicate photo sending across tiers.

```python
first_article = True
for article in generated:
    filtered = check_and_fix(article.content)
    entry = {
        "tier": article.tier,
        "content": filtered.content,
        "source_urls": article.source_urls,
    }
    if first_article:
        entry["image_urls"] = image_urls  # Only on first article
        first_article = False
    articles_out.append(entry)
```

---

## 4. Hyperlink Injection at Delivery Layer

### 4.1. Design Principle

Hyperlinks are injected at the delivery layer, NOT in LLM output. This ensures:
- NQ05 filter scans plain text (no HTML parsing complexity).
- Source URLs come from metadata, not LLM hallucination.
- Consistent formatting across all tiers.

### 4.2. Format Function — `format_with_hyperlinks()`

New function in `telegram_bot.py`:

```python
def format_with_hyperlinks(
    content: str,
    source_urls: list[dict[str, str]],
    tier: str,
) -> str:
    """Inject hyperlinks into article content at delivery time.

    For "Tin Nổi Bật" sections (L1/L2): maps each bullet to its source URL.
    For "Phân Tích Chuyên Sâu" sections (L3-L5): appends source list at section end.

    Args:
        content: Plain text article content (post NQ05 filter).
        source_urls: List of {"name": "...", "url": "..."} from article metadata.
        tier: Article tier ("L1", "L2", ..., "Summary").

    Returns:
        Content with <a href="...">source</a> tags inserted.
    """
    if not source_urls:
        return content

    # Build name → url lookup (deduplicated by name)
    url_lookup: dict[str, str] = {}
    for src in source_urls:
        name = src.get("name", "")
        url = src.get("url", "")
        if name and url and name not in url_lookup:
            url_lookup[name] = url

    if not url_lookup:
        return content

    # Strategy 1: Bullet-level links for news sections
    # Match lines like "• Tin 1... (CoinTelegraph)" and add link
    lines = content.split("\n")
    formatted_lines = []
    for line in lines:
        matched = False
        for name, url in url_lookup.items():
            # Check if source name appears in the line (parenthesized or at end)
            if name in line and line.strip().startswith(("•", "-", "*")):
                # Add link below the bullet
                formatted_lines.append(line)
                formatted_lines.append(f'  \U0001f517 <a href="{url}">{name}</a>')
                matched = True
                break
        if not matched:
            formatted_lines.append(line)

    content = "\n".join(formatted_lines)

    # Strategy 2: Research source footer for L3-L5
    if tier in ("L3", "L4", "L5"):
        research_sources = [
            src for src in source_urls
            if src.get("source_type") == "research" and src.get("url")
        ]
        if research_sources:
            seen = set()
            links = []
            for src in research_sources:
                name = src.get("name", "")
                if name not in seen:
                    seen.add(name)
                    url = src.get("url", "")
                    links.append(f'<a href="{url}">{name}</a>')
            if links:
                footer = "\n\U0001f517 Ngu\u1ed3n: " + " \u00b7 ".join(links)
                content = content.rstrip() + "\n" + footer

    return content
```

### 4.3. Format Function — `format_telegram_message()`

New function for applying emoji headers and separators:

```python
SEPARATOR = "\u2501" * 21  # ━━━━━━━━━━━━━━━━━━━━━

# Emoji header mappings
TIER_HEADERS: dict[str, str] = {
    "L1": "\U0001f4ca B\u1ea2N TIN CRYPTO NG\u00c0Y {date}",
    "Summary": "\U0001f4ca T\u1ed4NG QUAN TH\u1eca TR\u01af\u1edcNG",
}

SECTION_EMOJI_MAP: dict[str, str] = {
    "THỊ TRƯỜNG TỔNG QUAN": "\U0001f7e2",
    "TIN NỔI BẬT": "\U0001f525",
    "PHÂN TÍCH CHUYÊN SÂU": "\U0001f4d6",
    "PHÂN TÍCH RỦI RO": "\u26a0\ufe0f",
    "ON-CHAIN": "\U0001f50d",
}

NQ05_DISCLAIMER_FORMATTED = (
    "\n" + SEPARATOR + "\n\n"
    "\u26a0\ufe0f N\u1ed9i dung ch\u1ec9 mang t\u00ednh th\u00f4ng tin,\n"
    "KH\u00d4NG ph\u1ea3i l\u1eddi khuy\u00ean \u0111\u1ea7u t\u01b0. DYOR."
)


def format_telegram_message(
    tier: str,
    content: str,
    source_urls: list[dict[str, str]] | None = None,
    date_str: str = "",
) -> str:
    """Format article content for Telegram display.

    Applies:
    1. Emoji headers for known section names
    2. ━━━ separators between sections
    3. Hyperlinks from source_urls
    4. NQ05 disclaimer at end

    Args:
        tier: Article tier label.
        content: Plain text content (post NQ05).
        source_urls: Source URL metadata for hyperlink injection.
        date_str: Date string for header (DD/MM/YYYY).

    Returns:
        Formatted HTML-safe text ready for Telegram.
    """
    # Step 1: Inject hyperlinks
    if source_urls:
        content = format_with_hyperlinks(content, source_urls, tier)

    # Step 2: Replace ## headers with emoji headers
    for section_name, emoji in SECTION_EMOJI_MAP.items():
        # Match both "## SECTION" and "**SECTION**" patterns
        content = re.sub(
            rf"(?m)^##\s*{re.escape(section_name)}",
            f"{SEPARATOR}\n\n{emoji} {section_name}",
            content,
        )
        content = re.sub(
            rf"(?m)^\*\*{re.escape(section_name)}\*\*",
            f"{SEPARATOR}\n\n{emoji} {section_name}",
            content,
        )

    # Step 3: Clean up any remaining ## headers
    content = re.sub(r"(?m)^##\s*(.+)$", rf"{SEPARATOR}\n\n\1", content)
    content = re.sub(r"(?m)^\*\*(.+?)\*\*$", r"\1", content)

    return content
```

### 4.4. Integration into `deliver()` Flow

The formatting chain in delivery is:

```
articles_out (plain text + metadata)
    ↓
DeliveryManager._format_article(article_dict)
    → format_telegram_message(tier, content, source_urls, date)
    → selective_html_escape()  (in _send_raw)
    ↓
TelegramBot.send_message(formatted_text)
```

The `format_telegram_message()` call happens in `prepare_messages()` — before `split_message()` so that the splitter can recognize `━━━` separators.

---

## 5. send_photo() Method Design

### 5.1. Method Signature

```python
async def send_photo(
    self,
    photo_url: str,
    caption: str = "",
    parse_mode: str = "HTML",
) -> dict[str, Any]:
    """Send a photo via Telegram Bot API sendPhoto endpoint.

    Args:
        photo_url: URL of the image to send. Telegram fetches it server-side.
        caption: Optional caption text (max 1024 chars).
        parse_mode: "HTML" or "MarkdownV2" (default "HTML").

    Returns:
        Telegram API response dict.

    Raises:
        DeliveryError: If API call fails after retries.
    """
```

### 5.2. Implementation

```python
async def send_photo(
    self,
    photo_url: str,
    caption: str = "",
    parse_mode: str = "HTML",
) -> dict[str, Any]:
    """Send a photo via Telegram Bot API sendPhoto endpoint."""
    return await retry_async(
        self._send_photo_raw,
        photo_url=photo_url,
        caption=caption,
        parse_mode=parse_mode,
    )

async def _send_photo_raw(
    self,
    photo_url: str,
    caption: str = "",
    parse_mode: str = "HTML",
) -> dict[str, Any]:
    """Raw sendPhoto — called by retry wrapper."""
    url = f"https://api.telegram.org/bot{self._token}/sendPhoto"

    # Truncate caption to 1024 chars (Telegram limit)
    if len(caption) > 1024:
        # Find last complete sentence or newline before limit
        truncated = caption[:1020]
        # Try to break at last sentence boundary
        for boundary in [". ", ".\n", "\n"]:
            pos = truncated.rfind(boundary)
            if pos > 800:  # don't truncate too aggressively
                truncated = truncated[:pos + 1]
                break
        caption = truncated + "..."

    # Apply selective HTML escape to caption
    caption = selective_html_escape(caption)

    payload = {
        "chat_id": self._chat_id,
        "photo": photo_url,
        "caption": caption,
        "parse_mode": parse_mode,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()

    data = resp.json()
    if not data.get("ok"):
        raise DeliveryError(
            f"Telegram sendPhoto error: {data.get('description', 'unknown')}",
            source="telegram_bot",
        )
    return data
```

### 5.3. Caption Format

```python
def _build_photo_caption(
    title: str,
    source_name: str,
    source_url: str,
    summary: str = "",
) -> str:
    """Build caption for sendPhoto (max 1024 chars).

    Format:
        Title
        Summary (1-2 sentences)
        🔗 <a href="url">Source</a>
    """
    parts = [title]
    if summary:
        # Take first 2 sentences
        sentences = re.split(r'(?<=[.!?])\s+', summary)
        short_summary = " ".join(sentences[:2])
        if len(short_summary) > 500:
            short_summary = short_summary[:497] + "..."
        parts.append(short_summary)
    parts.append(f'\U0001f517 <a href="{source_url}">{source_name}</a>')

    caption = "\n\n".join(parts)
    return caption[:1024]
```

### 5.4. Error Handling + Retry

- Uses existing `retry_async()` with default 3 attempts, exponential backoff (2s, 4s, 8s).
- If all retries fail, the error is caught in `deliver_all()` and logged. The text message is still sent (graceful degradation).
- Common failure modes:
  - **Invalid photo URL (404)**: Telegram returns `400 Bad Request: wrong file identifier/HTTP URL specified`. Retry will not help — fails fast after 3 attempts.
  - **Photo too large (>10MB)**: Telegram returns `400 Bad Request: file is too big`. Same as above.
  - **Network timeout**: Retry handles this.

### 5.5. Integration with `deliver_all()` Flow

Modified `deliver_all()` in `TelegramBot`:

```python
async def deliver_all(
    self,
    messages: list[TelegramMessage],
) -> list[dict[str, Any]]:
    """Send all messages in order with delay between each (NFR18).

    Photos are sent BEFORE their associated text message.
    """
    results: list[dict[str, Any]] = []

    for i, msg in enumerate(messages):
        try:
            # Send associated photos first (if any, only for part 1)
            if msg.image_urls and msg.part == 1:
                for photo_url in msg.image_urls:
                    try:
                        caption = ""  # Caption on photo is optional
                        photo_result = await self.send_photo(photo_url, caption)
                        results.append(photo_result)
                        await asyncio.sleep(SEND_DELAY)
                    except Exception as e:
                        logger.warning(f"Photo send failed (non-fatal): {e}")
                        # Continue — photo failure does not block text

            # Send text message
            result = await self.send_message(msg.formatted)
            results.append(result)
            logger.info(f"Sent [{msg.tier_label}] part {msg.part}/{msg.total_parts}")

            if i < len(messages) - 1:
                await asyncio.sleep(SEND_DELAY)

        except Exception as e:
            logger.error(f"Failed to send [{msg.tier_label}]: {e}")
            results.append({"ok": False, "error": str(e), "tier": msg.tier_label})

    sent = sum(1 for r in results if r.get("ok"))
    logger.info(f"Delivery complete: {sent}/{len(results)} items sent")
    return results
```

**Alternative approach (delivery_manager-level orchestration):**

Instead of embedding photo logic in `deliver_all()`, the `DeliveryManager` handles photo sending before calling `deliver_all()`:

```python
# In DeliveryManager.deliver():
# Step 1: Send photos (before text messages)
for article in articles:
    for photo_url in article.get("image_urls", []):
        try:
            await self._tg.send_photo(photo_url)
            await asyncio.sleep(SEND_DELAY)
        except Exception as e:
            logger.warning(f"Photo delivery failed (non-fatal): {e}")

# Step 2: Send text messages (existing flow)
messages = prepare_messages(articles)
tg_results = await self._tg.deliver_all(messages)
```

**Recommendation:** Use the delivery_manager-level approach. It keeps `TelegramBot` focused on raw API calls and `DeliveryManager` on orchestration. The `TelegramMessage` dataclass does not need `image_urls` in this approach — simplifying the data flow.

---

## 6. RSS Collector Changes

### 6.1. Semaphore Placement

Add `asyncio.Semaphore(25)` to limit concurrent HTTP requests across all feeds.

```python
# Module-level constant
MAX_CONCURRENT_REQUESTS = 25

async def collect_rss(
    feeds: list[FeedConfig] | None = None,
) -> list[NewsArticle]:
    """Collect news from RSS feeds in parallel."""
    feeds = feeds or [f for f in DEFAULT_FEEDS if f.enabled]
    logger.info(f"Collecting from {len(feeds)} RSS feeds")

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async def _limited_fetch(feed: FeedConfig) -> list[NewsArticle]:
        async with semaphore:
            return await _fetch_feed(feed)

    tasks = [_limited_fetch(feed) for feed in feeds]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    # ... rest unchanged
```

### 6.2. Trafilatura for Research Feeds

Only research feeds get full-text extraction via trafilatura. News feeds continue with RSS summary only.

```python
async def _fetch_feed(feed: FeedConfig) -> list[NewsArticle]:
    """Fetch and parse a single RSS feed."""
    try:
        async with httpx.AsyncClient(timeout=FEED_TIMEOUT) as client:
            response = await client.get(feed.url, follow_redirects=True)
            response.raise_for_status()

        parsed = await asyncio.to_thread(feedparser.parse, response.text)
        articles = []

        for entry in parsed.entries[:20]:
            title = _sanitize_text(entry.get("title", ""))
            url = entry.get("link", "").strip()
            summary = _sanitize_text(entry.get("summary", ""))[:500]
            published = entry.get("published", "")

            # Extract og:image from RSS <media:content> tag (fallback)
            og_image = None
            media = entry.get("media_content", [])
            if media and isinstance(media, list):
                for m in media:
                    if isinstance(m, dict) and m.get("url"):
                        og_image = m["url"]
                        break
            # Also check <media:thumbnail>
            if not og_image:
                thumb = entry.get("media_thumbnail", [])
                if thumb and isinstance(thumb, list) and thumb[0].get("url"):
                    og_image = thumb[0]["url"]

            if title and url:
                article = NewsArticle(
                    title=title,
                    url=url,
                    source_name=feed.source_name,
                    published_date=published,
                    summary=summary,
                    language=feed.language,
                    source_type=feed.source_type,
                    og_image=og_image,
                )
                articles.append(article)

        # For research feeds: extract full text + better og:image via trafilatura
        if feed.source_type == "research":
            await _enrich_research_articles(articles)

        return articles

    except httpx.TimeoutException:
        raise CollectorError(...)
    except Exception as e:
        raise CollectorError(...) from e


async def _enrich_research_articles(articles: list[NewsArticle]) -> None:
    """Extract full text and og:image for research articles via trafilatura."""
    try:
        import trafilatura
    except ImportError:
        logger.warning("trafilatura not installed — skipping research enrichment")
        return

    async def _enrich_one(article: NewsArticle) -> None:
        try:
            async with httpx.AsyncClient(timeout=FEED_TIMEOUT) as client:
                resp = await client.get(article.url, follow_redirects=True)

            # Extract full text
            text = await asyncio.to_thread(
                trafilatura.extract, resp.text, include_comments=False
            )
            if text:
                article.full_text = text[:3000]  # research gets more text
                if not article.summary or len(article.summary) < 100:
                    article.summary = text[:500]

            # Extract og:image via metadata (overrides RSS fallback)
            metadata = await asyncio.to_thread(trafilatura.extract_metadata, resp.text)
            if metadata and metadata.image:
                article.og_image = metadata.image

        except Exception as e:
            logger.debug(f"Research enrichment failed for {article.url}: {e}")

    tasks = [_enrich_one(a) for a in articles]
    await asyncio.gather(*tasks, return_exceptions=True)
    enriched = sum(1 for a in articles if a.full_text)
    logger.info(f"Research articles enriched: {enriched}/{len(articles)}")
```

### 6.3. og:image Extraction Logic

Priority order:
1. `trafilatura.extract_metadata().image` — most reliable, extracts `<meta property="og:image">`.
2. RSS `<media:content>` tag — feedparser parses this into `entry.media_content`.
3. RSS `<media:thumbnail>` tag — feedparser parses this into `entry.media_thumbnail`.
4. `None` — no image found, skip gracefully.

### 6.4. New Research Feed URLs

| Source | RSS URL | Status |
|--------|---------|--------|
| Messari Research | `https://messari.io/rss` | TBD — verify availability; Messari's public RSS may be limited to headlines only. Fallback: `https://messari.io/feed` |
| Glassnode Insights | `https://insights.glassnode.com/rss/` | Confirmed — public RSS feed with full content |
| CoinMetrics | `https://coinmetrics.substack.com/feed` | Confirmed — Substack-based, full content via RSS |
| Galaxy Digital Research | `https://www.galaxy.com/research/feed/` | TBD — verify; may use `https://www.galaxy.com/insights/feed.xml` |

**DEFAULT_FEEDS additions:**

```python
# Research feeds (source_type="research")
FeedConfig(
    "https://messari.io/rss",
    "Messari",
    "en",
    source_type="research",
),
FeedConfig(
    "https://insights.glassnode.com/rss/",
    "Glassnode",
    "en",
    source_type="research",
),
FeedConfig(
    "https://coinmetrics.substack.com/feed",
    "CoinMetrics",
    "en",
    source_type="research",
),
FeedConfig(
    "https://www.galaxy.com/research/feed/",
    "Galaxy",
    "en",
    source_type="research",
),
```

**Validation plan:** During Cluster 1 implementation, verify each URL returns valid RSS/Atom XML. If a URL is unavailable, disable it (`enabled=False`) and log a warning. AC5 requires graceful fallback.

---

## 7. Template Engine Format Changes

### 7.1. Where Formatting Happens

The spec defines emoji headers + separators in the Telegram output. This formatting should happen at the **delivery layer**, NOT in `template_engine.py`.

**Rationale:**
- `template_engine.py` renders prompts for the LLM. Adding emoji/separators there would mean the LLM sees them as part of the prompt, which wastes tokens and confuses the model.
- `template_engine.py` output → LLM → plain text response → NQ05 filter → delivery formatting.
- Formatting is a presentation concern, not a generation concern.

### 7.2. Template Engine Changes (Minimal)

`template_engine.py` requires no structural changes. The only changes are:

1. **L3-L5 prompt enhancement**: When `research_summary` is available in `GenerationContext`, include it in the prompt variables. This is done in `article_generator.py`, not `template_engine.py`.

```python
# In article_generator.py, inside generate_tier_articles():
variables = {
    "coin_list": coin_str,
    # ... existing variables ...
    "research_insights": context.research_summary,  # NEW
}
```

And in the full_prompt construction:

```python
# After "TIN TỨC MỚI NHẤT" section:
if variables.get("research_insights"):
    full_prompt += (
        f"NGHIÊN CỨU CHUYÊN SÂU (dùng để bổ sung phân tích cho L3-L5):\n"
        f"{variables.get('research_insights')}\n\n"
    )
```

2. **No changes to `template_engine.py` itself.** The emoji headers/separators are injected by `format_telegram_message()` in the delivery layer (see Section 4.3).

### 7.3. Interaction with LLM Prompt Templates (Google Sheets)

The `MAU_BAI_VIET` tab on Google Sheets contains prompt templates per tier/section. For L3-L5, the operator (Anh Cuong) should update prompts to reference research insights:

Example L3 prompt template update:
```
Phân tích mối quan hệ on-chain và macro.
{onchain_data}
{market_data}
{research_insights}

Nếu có research insights, hãy:
- Trích dẫn nguồn cụ thể (ví dụ: "Theo Glassnode...")
- Kết hợp research findings với dữ liệu on-chain
- Đưa ra nhận định dựa trên cả hai nguồn
```

This is a manual operator update (Task 3.7 in the spec), not a code change.

---

## 8. NQ05 Filter Enhancement

### 8.1. Current State

`nq05_filter.py:96` scans for banned keywords using `re.compile(re.escape(keyword), re.IGNORECASE)`. This regex operates on raw text and does not understand HTML structure. If the output contains `<a href="url">nên mua BTC</a>`, the current filter would:
- Match `nên mua` in the visible text: correct.
- Replace it with `[đã biên tập]`: correct, but breaks the `<a>` tag structure.

### 8.2. Design: Scan Link Text Inside `<a>` Tags

Since NQ05 scans OUTPUT only (and output now contains `<a>` tags from delivery layer), the filter needs to:

1. Extract text content from `<a>` tags.
2. Scan that text for banned keywords.
3. If violation found, remove the entire `<a>` tag (not just the keyword).

**However, there is an important ordering consideration:**

Looking at the pipeline flow:
```
LLM generates plain text → NQ05 scans plain text → Delivery layer adds <a> tags
```

The NQ05 filter runs BEFORE hyperlinks are injected. Therefore, the NQ05 filter will never see `<a>` tags in the content it scans.

**But:** The `format_with_hyperlinks()` function (Section 4.2) injects link text that comes from source names (e.g., "Messari", "Glassnode"). These source names are unlikely to contain NQ05-banned keywords. The actual hyperlink text is the source name, not article content.

**Revised design:** Add an `<a>` tag-aware scan as a safety net for any future code path that might pass HTML-containing content through the filter (e.g., email backup, summary generator consuming formatted output).

```python
# NEW: Regex to extract text from <a> tags
_A_TAG_TEXT = re.compile(r'<a\s+[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)


def _strip_html_tags(text: str) -> str:
    """Strip all HTML tags, returning only visible text for NQ05 scan."""
    return re.sub(r'<[^>]+>', '', text)


def check_and_fix(
    content: str,
    extra_banned_keywords: list[str] | None = None,
) -> FilterResult:
    """Run NQ05 post-filter on content.

    Enhanced: also scans text inside <a> tags for banned keywords.
    If violation found inside a link, the entire <a> tag is removed
    and replaced with the link text (escaped).
    """
    result = FilterResult(content=content)
    all_banned = DEFAULT_BANNED_KEYWORDS + (extra_banned_keywords or [])

    # Step 0 (NEW): Scan and sanitize text inside <a> tags
    def _check_link_text(match: re.Match) -> str:
        link_text = match.group(1)
        for keyword in all_banned:
            if re.search(re.escape(keyword), link_text, re.IGNORECASE):
                result.violations_found += 1
                result.auto_fixed += 1
                result.flagged_for_review.append(
                    f"NQ05 violation in link text: '{keyword}' in <a>...{link_text}...</a>"
                )
                # Remove the <a> tag entirely, keep sanitized text
                return "[đã biên tập]"
        return match.group(0)  # Keep link unchanged

    if '<a ' in result.content.lower():
        result.content = _A_TAG_TEXT.sub(_check_link_text, result.content)

    # Step 1: Scan plain text for banned keywords (strip HTML for scanning)
    scan_text = _strip_html_tags(result.content)
    for keyword in all_banned:
        pattern = re.compile(re.escape(keyword), re.IGNORECASE)
        matches = pattern.findall(scan_text)
        if matches:
            result.violations_found += len(matches)
            # Apply replacement on original content (with HTML)
            result.content = pattern.sub("[đã biên tập]", result.content)
            result.auto_fixed += len(matches)
            result.flagged_for_review.append(f"Removed: '{keyword}' ({len(matches)}x)")

    # Steps 1b, 2, 3 remain unchanged...
```

### 8.3. What Happens When Violation Found in Link Text

| Scenario | Action |
|----------|--------|
| `<a href="url">nên mua BTC ngay</a>` | Entire `<a>` tag replaced with `[đã biên tập]` |
| `<a href="url">Messari Research</a>` | No violation — tag preserved |
| `Hãy nên mua BTC` (plain text, no `<a>`) | `nên mua` replaced with `[đã biên tập]` (existing behavior) |
| `<a href="url">Analysis</a> nên bán ETH` | Link preserved, `nên bán` in plain text replaced |

---

## 9. Interface Contracts

### 9.1. `rss_collector` → `daily_pipeline` Unified Dict

**Producer:** `collect_rss()` returns `list[NewsArticle]`.
**Consumer:** `_execute_stages()` converts to unified dicts.

```python
# Contract: unified news dict
UnifiedNewsDict = TypedDict("UnifiedNewsDict", {
    "title": str,
    "url": str,
    "source_name": str,
    "summary": str,
    "news_type": NotRequired[str],      # "crypto" | "macro" (from CryptoPanic)
    "source_type": str,                  # "news" | "research"
    "og_image": NotRequired[str | None], # og:image URL
    "full_text": NotRequired[str],       # research full text
})
```

**Key guarantee:** `source_type` is always present and defaults to `"news"`. Consumer code can safely use `.get("source_type", "news")`.

---

### 9.2. `article_generator` Output → `delivery_manager` Input

**Producer:** `_execute_stages()` builds article dicts after NQ05 filter.
**Consumer:** `DeliveryManager.deliver()`.

```python
# Contract: article dict for delivery
ArticleDict = TypedDict("ArticleDict", {
    "tier": str,                                    # "L1"|"L2"|"L3"|"L4"|"L5"|"Summary"
    "content": str,                                 # NQ05-filtered plain text
    "source_urls": NotRequired[list[SourceUrlDict]],# source metadata for hyperlinks
    "image_urls": NotRequired[list[str]],           # og:image URLs for sendPhoto
})

SourceUrlDict = TypedDict("SourceUrlDict", {
    "name": str,         # e.g. "CoinTelegraph"
    "url": str,          # e.g. "https://cointelegraph.com/..."
    "source_type": str,  # "news" | "research"
})
```

**Key guarantees:**
- `tier` and `content` are always present (existing contract).
- `source_urls` and `image_urls` may be absent — consumer uses `.get("source_urls", [])`.
- `content` is plain text at this point — no HTML tags. Hyperlinks are injected by the delivery layer.

---

### 9.3. `delivery_manager` → `telegram_bot`

**Producer:** `DeliveryManager.deliver()` calls `prepare_messages()` and orchestrates delivery.
**Consumer:** `TelegramBot.deliver_all()` and `TelegramBot.send_photo()`.

```python
# Contract: TelegramBot.send_message(text)
#   text: str — HTML-formatted text (hyperlinks already injected)
#   Internally calls selective_html_escape() before sending

# Contract: TelegramBot.send_photo(photo_url, caption, parse_mode)
#   photo_url: str — direct URL to image file
#   caption: str — max 1024 chars, may contain <a> tags
#   parse_mode: str — "HTML" (default)

# Contract: TelegramBot.deliver_all(messages)
#   messages: list[TelegramMessage]
#   TelegramMessage.content: str — already formatted with emoji/separators/hyperlinks
#   Returns: list[dict] — Telegram API responses
```

**Formatting responsibility chain:**

```
DeliveryManager:
  1. For each article dict:
     a. Extract image_urls → send via send_photo() (if any)
     b. Format content: format_telegram_message(tier, content, source_urls, date)
     c. Pass to prepare_messages() for splitting

TelegramBot:
  1. prepare_messages() → split_message() recognizes ━━━ separators
  2. deliver_all() sends messages in order with delay
  3. _send_raw() applies selective_html_escape() before API call
```

---

### 9.4. `data_cleaner` Preservation Contract

`clean_articles()` must preserve all new fields through dedup/merge.

**Current behavior:** `_deduplicate()` operates on dict keys `title`, `url`, `source_name`. When merging duplicates, it only modifies `sources` list.

**New requirement:** When two articles are merged (same URL or similar title), the surviving dict must retain:
- `source_type`: keep the higher-priority value (`"research"` > `"news"`)
- `og_image`: keep non-None value
- `full_text`: keep non-empty value

```python
def _merge_source_list(existing: dict[str, Any], dup: dict[str, Any]) -> None:
    """Add dup's source to existing's sources list."""
    sources = existing.setdefault("sources", [existing.get("source_name", "")])
    dup_source = dup.get("source_name", "")
    if dup_source and dup_source not in sources:
        sources.append(dup_source)

    # NEW: Preserve metadata from research sources
    if dup.get("source_type") == "research":
        existing["source_type"] = "research"  # research takes priority
    if dup.get("og_image") and not existing.get("og_image"):
        existing["og_image"] = dup["og_image"]
    if dup.get("full_text") and not existing.get("full_text"):
        existing["full_text"] = dup["full_text"]
```

---

### 9.5. `summary_generator` — Strip Decorations

**Current code in `summary_generator.py:52-53`:**
```python
excerpt = article.content[:800].replace(DISCLAIMER, "").strip()
```

**New behavior — strip emoji headers and separators before cutting excerpt:**
```python
def _strip_decorations(text: str) -> str:
    """Remove emoji headers and separators for clean excerpt."""
    # Remove separator lines (━━━, ───, ═══)
    text = re.sub(r'[━─═]+', '', text)
    # Remove lines that are pure emoji + header text
    text = re.sub(r'(?m)^[\U0001f300-\U0001faff\u2600-\u27bf\ufe0f\s]*[A-Z\u00C0-\u024F\s]{3,}$', '', text)
    # Collapse multiple newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

# In generate_bic_summary():
excerpt = _strip_decorations(article.content).replace(DISCLAIMER, "")[:800].strip()
```

Note: Since `summary_generator` takes `GeneratedArticle.content` as input, and that content is plain text (pre-formatting), the strip_decorations function is a defensive measure. If the content somehow contains decorations (e.g., LLM generates emoji headers spontaneously), they will be cleaned before the 800-char cut.

---

### 9.6. `email_backup` — HTML Format

**Current code in `email_backup.py:95`:**
```python
msg.set_content(body)
```

**New code:**
```python
msg.set_content(body, subtype="html")
```

This changes the email MIME type from `text/plain` to `text/html`. The `body` passed to `send_daily_report()` will now contain HTML (same format as Telegram output, with `<a>` tags and special characters properly escaped).

**Impact on `_combine_content()` in `delivery_manager.py:161-168`:**

The `_combine_content()` function currently joins articles with plain text separators. It needs to output HTML:

```python
def _combine_content(articles: list[dict[str, str]]) -> str:
    """Combine all articles into HTML body for email."""
    parts = []
    for article in articles:
        tier = article.get("tier", "")
        content = article.get("content", "")
        # Format the content with hyperlinks (same as Telegram)
        source_urls = article.get("source_urls", [])
        formatted = format_telegram_message(tier, content, source_urls)
        # Wrap in HTML paragraph
        parts.append(f"<h2>[{html_lib.escape(tier)}]</h2>\n<p>{formatted}</p>")
    return "<br><hr><br>".join(parts)
```

---

### 9.7. `daily_pipeline` — Truncation Increase

**Current code in `daily_pipeline.py:512`:**
```python
article.get("content", "")[:5000],  # truncate for Sheets cell limit
```

**New code:**
```python
article.get("content", "")[:8000],  # truncate for Sheets cell limit (increased for research content)
```

**Multi-byte safety:** Python string slicing on `[:8000]` cuts at character boundary (not byte boundary), so multi-byte Unicode characters (including emoji) will not be split mid-character. No additional validation needed.

---

### 9.8. `split_message()` Update

**Current separator detection in `telegram_bot.py:59`:**
```python
sections = re.split(r"(?=\n##\s|\n\*\*[^*]+\*\*\n)", content)
```

**New separator detection:**
```python
sections = re.split(
    r"(?=\n[━─═]{3,}|\n##\s|\n\*\*[^*]+\*\*\n)",
    content,
)
```

This adds recognition of `━━━` (and similar box-drawing) separator lines as section boundaries for message splitting, in addition to the existing `##` and `**...**` patterns.

---

## Appendix A: File Change Summary

| File | Changes | Estimated LOC |
|------|---------|---------------|
| `rss_collector.py` | +`source_type` field, +`og_image`/`full_text` fields, +4 feeds, +Semaphore, +`_enrich_research_articles()` | ~80 |
| `cryptopanic_client.py` | +`og_image` field, +metadata extraction in `_extract_one()` | ~10 |
| `data_cleaner.py` | +metadata preservation in `_merge_source_list()` | ~10 |
| `telegram_bot.py` | +`selective_html_escape()`, +`send_photo()`, +`format_telegram_message()`, +`format_with_hyperlinks()`, split_message update, TelegramMessage fields | ~150 |
| `delivery_manager.py` | +photo orchestration in `deliver()`, +HTML `_combine_content()` | ~30 |
| `email_backup.py` | `set_content(body, subtype="html")` | ~2 |
| `article_generator.py` | +`source_urls` field, +`research_insights` in prompt, GenerationContext fields | ~20 |
| `summary_generator.py` | +`_strip_decorations()` | ~15 |
| `nq05_filter.py` | +`<a>` tag text scanning, +`_strip_html_tags()` | ~25 |
| `template_engine.py` | No changes | 0 |
| `daily_pipeline.py` | +unified dict fields, +source_url_map/image_urls building, +research_text, truncation 5000→8000 | ~40 |
| **Total estimated** | | **~382 LOC** |

---

## Appendix B: Dependency Analysis

| Dependency | Status | Used For |
|------------|--------|----------|
| `trafilatura` | Already installed (used by `cryptopanic_client.py`) | Full text + og:image extraction |
| `feedparser` | Already installed | RSS parsing (no change) |
| `httpx` | Already installed | HTTP client (no change) |
| `html` (stdlib) | Already used | HTML escaping |
| `re` (stdlib) | Already used | Regex patterns |

No new dependencies required.

---

## Appendix C: Risk Mitigations

| Risk | Mitigation in Design |
|------|---------------------|
| Selective escape XSS | Strict whitelist regex, scheme validation, link text escaping |
| Research feed unavailability | `enabled=True` default + graceful fallback in `collect_rss()` — existing error handling returns empty list per feed |
| og:image 404/timeout | `send_photo()` failure is non-fatal — logged and skipped |
| Split message breaks mid-link | `split_message()` updated to recognize `━━━` separators; `<a>` tags are short (source name only) and unlikely to span split boundaries |
| NQ05 false positive on link text | Link text is source name only (e.g., "Messari") — extremely low risk |
| Email HTML rendering issues | Use simple HTML: `<a>`, `<h2>`, `<p>`, `<br>`, `<hr>` — universally supported |

---

*Document version 1.0 — Winston (Architect), 2026-03-13. Ready for Amelia (Dev) + Quinn (QA) review.*
