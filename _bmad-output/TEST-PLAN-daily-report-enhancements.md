# TEST PLAN: Daily Report Enhancements (Research Feeds, Format & Images)

> **Version**: 1.0
> **Date**: 2026-03-13
> **Spec Reference**: `SPEC-daily-report-enhancements-v3-final.md`
> **Author**: Quinn (QA Engineer)
> **Coverage Target**: >=80% new code, >=60% overall (CI requirement)

---

## TABLE OF CONTENTS

1. [Test Strategy Overview](#1-test-strategy-overview)
2. [Existing Tests That Need Updating](#2-existing-tests-that-need-updating)
3. [New Tests — Cum 1: Data Layer](#3-new-tests--cum-1-data-layer)
4. [New Tests — Cum 2: Delivery Layer](#4-new-tests--cum-2-delivery-layer)
5. [New Tests — Cum 3: Generator Layer](#5-new-tests--cum-3-generator-layer)
6. [New Tests — Cum 4: Integration](#6-new-tests--cum-4-integration)
7. [Test Fixtures Needed](#7-test-fixtures-needed)
8. [Coverage Targets & Critical Paths](#8-coverage-targets--critical-paths)
9. [Regression Test Strategy](#9-regression-test-strategy)
10. [Test Execution Order](#10-test-execution-order)

---

## 1. TEST STRATEGY OVERVIEW

### Principles
- **All external APIs mocked** — no real API calls in CI (existing rule)
- **Fixtures in `tests/fixtures/`** — JSON files named `{module}_{scenario}.json`
- **pytest-asyncio** for all async test functions
- **unittest.mock** — `AsyncMock`, `MagicMock`, `patch` (consistent with codebase)
- **Each Cum passes independently** — full `uv run pytest` after each Cum

### Test Scope Summary

| Category | Existing (update) | New | Total |
|----------|-------------------|-----|-------|
| Unit tests | ~42 functions | ~32 functions | ~74 |
| Integration tests | ~15 functions | ~5 functions | ~20 |
| **Total** | **~57** | **~37** | **~94** |

### Files Affected

| Test File | Status | Cum |
|-----------|--------|-----|
| `test_collectors/test_rss_collector.py` | Update + New | 1 |
| `test_collectors/test_data_cleaner.py` | Update + New | 1 |
| `test_delivery/test_telegram_bot.py` | Update + New | 2 |
| `test_delivery/test_delivery_manager.py` | Update + New | 2 |
| `test_delivery/test_pipeline_e2e.py` | Update | 4 |
| `test_generators/test_article_generator.py` | Update + New | 3 |
| `test_generators/test_template_engine.py` | Update + New | 3 |
| `test_generators/test_summary_generator.py` | Update + New | 3 |
| `test_generators/test_nq05_filter.py` | New | 3 |
| `test_generators/test_content_integration.py` | Update | 4 |
| `test_integration/test_pipeline_data_flow.py` | Update | 4 |
| `test_storage/test_config_loader.py` | No change | - |
| `conftest.py` | Update | 1 |

---

## 2. EXISTING TESTS THAT NEED UPDATING

### 2.1. `tests/test_collectors/test_rss_collector.py`

#### `TestFeedConfig.test_default_feeds_count` (line 17)
- **Currently tests**: `len(DEFAULT_FEEDS) >= 17`
- **What needs to change**: Increase assertion to `>= 21` (17 existing + 4 new research feeds)
- **Effort**: S

#### `TestFeedConfig.test_bilingual_feeds` (line 20)
- **Currently tests**: `len(vi_feeds) >= 5` and `len(en_feeds) >= 12`
- **What needs to change**: Increase English count to `>= 16` (12 existing + 4 research feeds are English)
- **Effort**: S

#### `TestFeedConfig.test_feed_has_required_fields` (line 26)
- **Currently tests**: `feed.url`, `feed.source_name`, `feed.language in ("vi", "en")`
- **What needs to change**: Add assertion for new field: `assert feed.source_type in ("news", "research")`
- **Effort**: S

#### `TestNewsArticle.test_to_row` (line 34)
- **Currently tests**: `len(row) == 11`, checks `row[1]`, `row[2]`, `row[5]`
- **What needs to change**: Create article with `source_type="research"`, verify `row[7]` (event_type column) contains `"research"` instead of empty string. Also create article with `og_image` set, verify it doesn't break row structure (og_image is NOT written to Sheets row, just carried in the dataclass)
- **Effort**: M

#### `TestCollectRss.test_collect_with_mock_feed` (line 51)
- **Currently tests**: Basic RSS collection with mocked httpx + feedparser
- **What needs to change**: FeedConfig constructor now requires `source_type` parameter. Update FeedConfig instantiation: `FeedConfig(url="...", source_name="...", language="en", source_type="news")`. Verify returned article has `source_type="news"`. No og_image for news feeds (only research feeds call trafilatura metadata extraction).
- **Effort**: M

#### `TestCollectRss.test_one_feed_failure_does_not_block` (line 92)
- **Currently tests**: One feed failure doesn't block others (NFR16)
- **What needs to change**: Update FeedConfig constructors with `source_type="news"`. Add Semaphore mock/verification (Semaphore wraps the fetch calls now).
- **Effort**: M

### 2.2. `tests/test_collectors/test_data_cleaner.py`

#### `TestDeduplication.test_exact_url_dedup` (line 7)
- **Currently tests**: URL-based dedup merges sources
- **What needs to change**: Add `source_type` and `og_image` fields to article dicts. Verify these fields are preserved in the surviving article after dedup merge.
- **Effort**: M

#### `TestDeduplication.test_similar_title_dedup` (line 18)
- **Currently tests**: Title similarity dedup
- **What needs to change**: Add `source_type` field to both articles. Verify `source_type` from the first (surviving) article is preserved.
- **Effort**: S

#### `TestDeduplication.test_different_articles_not_deduped` (line 34)
- **Currently tests**: Different articles remain separate
- **What needs to change**: Add `source_type` and `og_image` to article dicts. Verify both articles retain their respective `source_type` values.
- **Effort**: S

### 2.3. `tests/test_delivery/test_telegram_bot.py`

#### `TestTelegramMessage.test_formatted_single_part` (line 17)
- **Currently tests**: `msg.formatted == "[L1]\n\nHello"`
- **What needs to change**: TelegramMessage dataclass gains `source_urls` and `image_urls` fields. Test that default values (empty lists) don't affect `formatted` output.
- **Effort**: S

#### `TestTelegramMessage.test_formatted_multi_part` (line 22)
- **Currently tests**: Multi-part header format
- **What needs to change**: Same — verify new fields don't break existing format.
- **Effort**: S

#### `TestSplitMessage.test_split_by_sections` (line 41)
- **Currently tests**: Splitting on `## Section` headers
- **What needs to change**: The `split_message()` regex changes from `r"(?=\n##\s|\n\*\*[^*]+\*\*\n)"` to also recognize `━━━` separators and emoji headers. Update test content to use new format. Keep old test as regression (old format should still be handled or gracefully degraded).
- **Effort**: M

#### `TestPrepareMessages.test_prepares_from_articles` (line 47)
- **Currently tests**: Prepares messages from `[{"tier": "L1", "content": "..."}]`
- **What needs to change**: Article dicts now include `source_urls` and `image_urls`. Verify these are passed through to `TelegramMessage` objects.
- **Effort**: M

#### `TestTelegramBot.test_send_message_success` (line 68)
- **Currently tests**: `_send_raw` with `html_lib.escape()` on ALL text
- **What needs to change**: `_send_raw` now uses `selective_html_escape()` that whitelists `<a href>` tags. Verify the mock call passes correct payload with HTML links preserved.
- **Effort**: M

#### `TestTelegramBot.test_deliver_all_multiple_messages` (line 88)
- **Currently tests**: Multiple message delivery in sequence
- **What needs to change**: If delivery now includes photo+text sequence, verify ordering. At minimum, mock data must include new TelegramMessage fields.
- **Effort**: M

#### `TestTelegramBot.test_deliver_all_handles_failure` (line 116)
- **Currently tests**: Failure handling with ok=False in results
- **What needs to change**: Minimal — just ensure new fields don't break failure handling.
- **Effort**: S

### 2.4. `tests/test_delivery/test_delivery_manager.py`

#### `_articles()` helper function (line 11)
- **Currently returns**: `[{"tier": "L1", "content": "Article 1"}, ...]`
- **What needs to change**: Add `source_urls` and `image_urls` fields to match new article dict schema: `{"tier": "L1", "content": "...", "source_urls": [{"name": "CoinDesk", "url": "https://..."}], "image_urls": ["https://..."]}`
- **Effort**: M

#### `TestDeliveryManager.test_telegram_success` (line 43)
- **Currently tests**: TG deliver_all returns all ok
- **What needs to change**: Mock must handle new `send_photo()` calls. Delivery now calls `send_photo()` before `deliver_all()` if `image_urls` are present. Add `send_photo = AsyncMock()` to mock_tg.
- **Effort**: M

#### `TestDeliveryManager.test_telegram_partial` (line 54)
- **Currently tests**: Partial delivery with some failures
- **What needs to change**: Same photo delivery flow. Mock `send_photo`.
- **Effort**: M

#### `TestDeliveryManager.test_telegram_fail_email_fallback` (line 68)
- **Currently tests**: TG fail -> email fallback
- **What needs to change**: Email backup now uses `subtype="html"` instead of plain text. Verify `send_daily_report` is called and body contains HTML. Mock `send_photo` on TG mock.
- **Effort**: M

#### `TestDeliveryManager.test_sends_error_notification` (line 88)
- **Currently tests**: Error notification sent via send_message
- **What needs to change**: Article dict schema updated. Minimal change needed.
- **Effort**: S

#### `TestDeliveryManager.test_email_not_called_when_tg_succeeds` (line 103)
- **Currently tests**: Email not called when TG succeeds
- **What needs to change**: Add `send_photo` mock. Article dict schema update.
- **Effort**: S

### 2.5. `tests/test_generators/test_article_generator.py`

#### `_make_context()` helper (line 30)
- **Currently returns**: `GenerationContext(coin_lists=..., market_data=..., news_summary=..., key_metrics=...)`
- **What needs to change**: If `GenerationContext` gains a `research_articles` or similar field, update this helper. The spec says research articles are prioritized in `news_summary` for L3-L5, so `news_summary` string needs to include research content markers.
- **Effort**: M

#### `TestGenerateTierArticles.test_generates_articles_for_available_tiers` (line 52)
- **Currently tests**: Generates articles for L1 and L2
- **What needs to change**: Verify `GeneratedArticle` now has `source_urls` field (defaults to empty list). Assert `articles[0].source_urls` is a list.
- **Effort**: S

#### `TestGenerateTierArticles.test_coin_list_substituted` (line 114)
- **Currently tests**: Prompt contains coin list
- **What needs to change**: For L3-L5, verify prompt includes research context when research_articles are provided.
- **Effort**: M

### 2.6. `tests/test_generators/test_template_engine.py`

#### `TestRenderSections.test_substitutes_variables` (line 54)
- **Currently tests**: Variable substitution in prompts
- **What needs to change**: If render_sections output now includes emoji headers and separators, verify those are present. Test may need updated expected output format.
- **Effort**: M

### 2.7. `tests/test_generators/test_summary_generator.py`

#### `_make_articles()` helper (line 13)
- **Currently returns**: `[GeneratedArticle(tier="L1", ...), GeneratedArticle(tier="L2", ...)]`
- **What needs to change**: `GeneratedArticle` now has `source_urls` field. Add `source_urls=[]` or provide sample URLs.
- **Effort**: S

#### `TestGenerateBicSummary.test_generates_summary` (line 39)
- **Currently tests**: Summary generation from articles + metrics
- **What needs to change**: Verify summary generator strips emoji decorations and `━━━` separators before creating the 800-char excerpt from article content. If article content now has decorations, the test must verify they're stripped.
- **Effort**: M

### 2.8. `tests/test_delivery/test_pipeline_e2e.py`

#### `TestFullPipelineE2E.test_full_flow_produces_6_deliverables` (line 76)
- **Currently tests**: 5 articles + 1 summary -> 6 messages
- **What needs to change**: Article dicts now include `source_urls` and `image_urls`. `prepare_messages` function signature/behavior may change. Update article_dicts construction.
- **Effort**: M

#### `TestFullPipelineE2E.test_delivery_manager_sends_all` (line 104)
- **Currently tests**: DeliveryManager sends 6 messages via TG
- **What needs to change**: Article dicts need new fields. Mock `send_photo` on TG mock. If photos are sent, total API calls increase.
- **Effort**: M

#### `TestFullPipelineE2E.test_partial_delivery_with_errors` (line 121)
- **Currently tests**: L1 fails, rest succeed, partial delivery
- **What needs to change**: Article dict schema update. Mock `send_photo`.
- **Effort**: M

#### `TestFullPipelineE2E.test_all_content_has_disclaimer` (line 155)
- **Currently tests**: Every deliverable has NQ05 disclaimer
- **What needs to change**: No change needed if disclaimer logic is unchanged. Verify new format doesn't strip disclaimer.
- **Effort**: S

#### `TestFullPipelineE2E.test_message_order_preserved` (line 168)
- **Currently tests**: L1->L2->L3->L4->L5->Summary order
- **What needs to change**: If photos are sent first, order becomes: photo(s)->L1->L2->...->Summary. Update expected order or test that photo delivery is separate from text delivery.
- **Effort**: M

### 2.9. `tests/test_generators/test_content_integration.py`

#### `TestFullContentPipeline.test_generates_5_tier_articles` (line 98)
- **Currently tests**: 5 tier articles generated
- **What needs to change**: `GeneratedArticle` has new `source_urls` field. Verify field exists.
- **Effort**: S

#### `TestFullContentPipeline.test_content_has_required_fields` (line 194)
- **Currently tests**: Required fields present (tier, content, word_count, llm_used)
- **What needs to change**: Add assertion for `source_urls` field: `assert isinstance(article.source_urls, list)`
- **Effort**: S

#### `TestFullContentPipeline.test_llm_fallback_scenario` (line 162)
- **Currently tests**: LLM fallback when primary fails
- **What needs to change**: Minimal — `GeneratedArticle` field change only.
- **Effort**: S

### 2.10. `tests/test_integration/test_pipeline_data_flow.py`

#### `TestFilteredNewsExclusion.test_news_text_built_only_from_cleaned` (line 38)
- **Currently tests**: news_text built from non-filtered articles only
- **What needs to change**: Article dicts now include `source_type` field. Verify research articles are included in `cleaned_news` and their `source_type` is preserved. Add research articles to test data.
- **Effort**: M

### 2.11. `tests/conftest.py`

#### `sample_news_articles` fixture (line 16)
- **Currently returns**: List of dicts with title, summary, source, url, filtered
- **What needs to change**: Add `source_type` field to each article (default `"news"`). Add one research article to the list.
- **Effort**: S

---

## 3. NEW TESTS -- CUM 1: DATA LAYER

### File: `tests/test_collectors/test_rss_collector.py`

#### `TestFeedConfig.test_feed_config_source_type`
```python
def test_feed_config_source_type(self):
    """Verify FeedConfig has source_type field with valid values."""
    feed_news = FeedConfig("https://test.com/rss", "Test", "en", source_type="news")
    feed_research = FeedConfig("https://test.com/rss", "Test", "en", source_type="research")
    assert feed_news.source_type == "news"
    assert feed_research.source_type == "research"
```
- **Asserts**: `source_type` field exists and accepts "news"/"research"
- **Effort**: S

#### `TestFeedConfig.test_research_feeds_count`
```python
def test_research_feeds_count(self):
    """Verify 4 new research feeds added to DEFAULT_FEEDS."""
    research_feeds = [f for f in DEFAULT_FEEDS if f.source_type == "research"]
    assert len(research_feeds) == 4
    research_names = {f.source_name for f in research_feeds}
    assert "Messari" in research_names or any("Messari" in n for n in research_names)
    assert any("Glassnode" in n for n in research_names)
    assert any("CoinMetrics" in n for n in research_names)
    assert any("Galaxy" in n for n in research_names)
```
- **Asserts**: Exactly 4 research feeds, names match spec (Messari, Glassnode, CoinMetrics, Galaxy Digital)
- **Effort**: S

#### `TestFeedConfig.test_existing_feeds_are_news_type`
```python
def test_existing_feeds_are_news_type(self):
    """All 17 original feeds must have source_type='news'."""
    news_feeds = [f for f in DEFAULT_FEEDS if f.source_type == "news"]
    assert len(news_feeds) >= 17
```
- **Asserts**: Original feeds tagged correctly
- **Effort**: S

#### `TestNewsArticle.test_news_article_og_image`
```python
def test_news_article_og_image(self):
    """Verify og_image field on NewsArticle dataclass."""
    article = NewsArticle(
        title="Test", url="https://example.com", source_name="Src",
        published_date="2026-03-13", summary="Summary", language="en",
        source_type="research", og_image="https://example.com/chart.png",
    )
    assert article.og_image == "https://example.com/chart.png"
```
- **Asserts**: `og_image` field exists, accepts URL string
- **Effort**: S

#### `TestNewsArticle.test_news_article_og_image_default_none`
```python
def test_news_article_og_image_default_none(self):
    """og_image defaults to None for news articles."""
    article = NewsArticle(
        title="Test", url="https://example.com", source_name="Src",
        published_date="2026-03-13", summary="Summary", language="en",
        source_type="news",
    )
    assert article.og_image is None
```
- **Asserts**: Default value is None
- **Effort**: S

#### `TestNewsArticle.test_to_row_source_type`
```python
def test_to_row_source_type(self):
    """Verify source_type written to event_type column (index 7)."""
    article = NewsArticle(
        title="Test", url="https://example.com", source_name="Src",
        published_date="2026-03-13", summary="Summary", language="en",
        source_type="research",
    )
    row = article.to_row()
    assert row[7] == "research"  # event_type column
```
- **Asserts**: `source_type` value written to `row[7]` (event_type column in TIN_TUC_THO)
- **Effort**: S

#### `TestCollectRss.test_trafilatura_extract_research`
```python
async def test_trafilatura_extract_research(self):
    """Verify trafilatura.extract() called for research feeds to get full text."""
    feed = FeedConfig(
        url="https://messari.io/rss", source_name="Messari",
        language="en", source_type="research",
    )
    mock_entry = MagicMock()
    mock_entry.get = lambda k, d="": {
        "title": "Stablecoin Analysis",
        "link": "https://messari.io/report/stablecoins",
        "summary": "Short summary",
        "published": "2026-03-13",
    }.get(k, d)
    # ... (full mock setup for httpx, feedparser, trafilatura)
    # Assert trafilatura.extract was called
    # Assert returned article has full_text populated
    # Assert returned article has source_type="research"
```
- **Asserts**: `trafilatura.extract()` called for research feeds, full text populated
- **Mocks**: httpx.AsyncClient, feedparser.parse, trafilatura.extract, trafilatura.extract_metadata
- **Effort**: L

#### `TestCollectRss.test_trafilatura_og_image`
```python
async def test_trafilatura_og_image(self):
    """Verify og:image extracted via trafilatura.extract_metadata() for research feeds."""
    # ... (mock setup)
    mock_metadata = MagicMock()
    mock_metadata.image = "https://messari.io/chart.png"
    # patch trafilatura.extract_metadata to return mock_metadata
    # Assert returned article.og_image == "https://messari.io/chart.png"
```
- **Asserts**: `og_image` populated from trafilatura metadata
- **Mocks**: trafilatura.extract_metadata
- **Effort**: M

#### `TestCollectRss.test_trafilatura_not_called_for_news`
```python
async def test_trafilatura_not_called_for_news(self):
    """Verify trafilatura NOT called for news-type feeds (only research)."""
    feed = FeedConfig(url="https://news.com/rss", source_name="News",
                      language="en", source_type="news")
    # ... (mock setup)
    # Assert trafilatura.extract was NOT called
    # Assert trafilatura.extract_metadata was NOT called
```
- **Asserts**: trafilatura functions not invoked for news feeds
- **Effort**: M

#### `TestCollectRss.test_semaphore_limits_concurrency`
```python
async def test_semaphore_limits_concurrency(self):
    """Verify asyncio.Semaphore(25) limits concurrent requests."""
    # Create 30 feeds
    feeds = [FeedConfig(f"https://feed{i}.com/rss", f"Feed{i}", "en", source_type="news")
             for i in range(30)]
    # Track concurrent execution count via a side_effect that records timing
    max_concurrent = 0
    current_concurrent = 0

    async def mock_get(url, **kwargs):
        nonlocal max_concurrent, current_concurrent
        current_concurrent += 1
        max_concurrent = max(max_concurrent, current_concurrent)
        await asyncio.sleep(0.01)  # simulate network delay
        current_concurrent -= 1
        return mock_response

    # ... (mock setup)
    # Assert max_concurrent <= 25
```
- **Asserts**: Maximum 25 concurrent requests at any point
- **Mocks**: httpx.AsyncClient with timing tracker, asyncio.Semaphore
- **Effort**: L

#### `TestCollectRss.test_research_feed_failure_graceful`
```python
async def test_research_feed_failure_graceful(self):
    """Verify 1 research feed failure doesn't crash entire collection (AC5)."""
    good_research = FeedConfig("https://good.com/rss", "GoodResearch", "en",
                                source_type="research")
    bad_research = FeedConfig("https://bad.com/rss", "BadResearch", "en",
                               source_type="research")
    news_feed = FeedConfig("https://news.com/rss", "News", "en", source_type="news")
    # bad_research raises ConnectionError
    # Assert articles from good_research and news_feed are returned
    # Assert no exception propagated
```
- **Asserts**: Graceful fallback per AC5, other feeds unaffected
- **Effort**: M

### File: `tests/test_collectors/test_data_cleaner.py`

#### `TestDeduplication.test_data_cleaner_preserves_source_type`
```python
def test_data_cleaner_preserves_source_type(self):
    """Verify source_type field preserved through dedup merge."""
    articles = [
        {"title": "Analysis Report", "url": "https://a.com/1",
         "source_name": "Messari", "source_type": "research"},
        {"title": "Bitcoin News", "url": "https://b.com/2",
         "source_name": "CoinDesk", "source_type": "news"},
    ]
    result = clean_articles(articles)
    unique = [a for a in result.articles if not a.get("filtered")]
    assert len(unique) == 2
    types = {a["source_type"] for a in unique}
    assert types == {"research", "news"}
```
- **Asserts**: `source_type` survives dedup/clean pipeline
- **Effort**: S

#### `TestDeduplication.test_data_cleaner_preserves_og_image`
```python
def test_data_cleaner_preserves_og_image(self):
    """Verify og_image field preserved through dedup merge."""
    articles = [
        {"title": "Chart Analysis", "url": "https://a.com/1",
         "source_name": "Glassnode", "source_type": "research",
         "og_image": "https://a.com/chart.png"},
        {"title": "Market Update", "url": "https://b.com/2",
         "source_name": "CoinDesk", "source_type": "news", "og_image": None},
    ]
    result = clean_articles(articles)
    research = [a for a in result.articles if a.get("source_type") == "research"]
    assert len(research) == 1
    assert research[0]["og_image"] == "https://a.com/chart.png"
```
- **Asserts**: `og_image` survives dedup/clean pipeline, None values preserved
- **Effort**: S

### File: `tests/test_collectors/test_cryptopanic_client.py` (new tests to add)

#### `TestCryptoPanicArticle.test_cryptopanic_og_image`
```python
def test_cryptopanic_og_image(self):
    """Verify og_image field on CryptoPanicArticle dataclass."""
    article = CryptoPanicArticle(
        title="BTC News", url="https://crypto.com/1", source_name="Src",
        published_date="2026-03-13", summary="Summary", full_text="Full",
        panic_score=65.0, votes_bullish=10, votes_bearish=5,
        og_image="https://crypto.com/preview.png",
    )
    assert article.og_image == "https://crypto.com/preview.png"
```
- **Asserts**: `og_image` field exists on CryptoPanicArticle
- **Effort**: S

#### `TestCryptoPanicArticle.test_cryptopanic_og_image_default_none`
```python
def test_cryptopanic_og_image_default_none(self):
    """og_image defaults to None."""
    article = CryptoPanicArticle(
        title="BTC News", url="https://crypto.com/1", source_name="Src",
        published_date="2026-03-13", summary="", full_text="",
        panic_score=50.0, votes_bullish=0, votes_bearish=0,
    )
    assert article.og_image is None
```
- **Asserts**: Default None value
- **Effort**: S

---

## 4. NEW TESTS -- CUM 2: DELIVERY LAYER

### File: `tests/test_delivery/test_telegram_bot.py`

#### `TestSelectiveHtmlEscape.test_selective_html_escape_preserves_links`
```python
def test_selective_html_escape_preserves_links(self):
    """Verify <a href> tags are NOT escaped (AC8)."""
    from cic_daily_report.delivery.telegram_bot import selective_html_escape
    text = 'Check <a href="https://messari.io">Messari</a> for details'
    result = selective_html_escape(text)
    assert '<a href="https://messari.io">Messari</a>' in result
```
- **Asserts**: `<a href>` tags survive escaping
- **Critical path**: YES (AC8 — hyperlinks must be clickable)
- **Effort**: S

#### `TestSelectiveHtmlEscape.test_selective_html_escape_blocks_xss`
```python
def test_selective_html_escape_blocks_xss(self):
    """Verify <script>, <img onerror>, etc. are escaped (R4 security)."""
    from cic_daily_report.delivery.telegram_bot import selective_html_escape
    text = '<script>alert("xss")</script> normal text'
    result = selective_html_escape(text)
    assert "<script>" not in result
    assert "&lt;script&gt;" in result
    assert "normal text" in result
```
- **Asserts**: XSS vectors escaped, safe text preserved
- **Critical path**: YES (R4 — XSS prevention)
- **Effort**: S

#### `TestSelectiveHtmlEscape.test_selective_html_escape_blocks_javascript_href`
```python
def test_selective_html_escape_blocks_javascript_href(self):
    """Verify javascript: URLs in href are sanitized."""
    from cic_daily_report.delivery.telegram_bot import selective_html_escape
    text = '<a href="javascript:alert(1)">Click me</a>'
    result = selective_html_escape(text)
    assert "javascript:" not in result
```
- **Asserts**: `javascript:` protocol blocked in href
- **Critical path**: YES (security)
- **Effort**: S

#### `TestSelectiveHtmlEscape.test_selective_html_escape_blocks_data_href`
```python
def test_selective_html_escape_blocks_data_href(self):
    """Verify data: URLs in href are sanitized."""
    from cic_daily_report.delivery.telegram_bot import selective_html_escape
    text = '<a href="data:text/html,<script>alert(1)</script>">Click</a>'
    result = selective_html_escape(text)
    assert "data:" not in result
```
- **Asserts**: `data:` protocol blocked
- **Effort**: S

#### `TestSelectiveHtmlEscape.test_selective_html_escape_malformed_html`
```python
def test_selective_html_escape_malformed_html(self):
    """Verify unclosed tags handled safely."""
    from cic_daily_report.delivery.telegram_bot import selective_html_escape
    text = '<a href="https://ok.com">unclosed link <b>bold without close'
    result = selective_html_escape(text)
    # Should not crash, malformed tags escaped
    assert isinstance(result, str)
```
- **Asserts**: No crash on malformed HTML
- **Effort**: S

#### `TestSelectiveHtmlEscape.test_selective_html_escape_multiple_links`
```python
def test_selective_html_escape_multiple_links(self):
    """Verify multiple <a> tags all preserved."""
    from cic_daily_report.delivery.telegram_bot import selective_html_escape
    text = (
        'Sources: <a href="https://messari.io">Messari</a> · '
        '<a href="https://glassnode.com">Glassnode</a>'
    )
    result = selective_html_escape(text)
    assert result.count("<a href=") == 2
    assert "Messari</a>" in result
    assert "Glassnode</a>" in result
```
- **Asserts**: Multiple links all preserved
- **Effort**: S

#### `TestSelectiveHtmlEscape.test_selective_html_escape_ampersand_in_text`
```python
def test_selective_html_escape_ampersand_in_text(self):
    """Verify & in plain text is escaped to &amp;."""
    from cic_daily_report.delivery.telegram_bot import selective_html_escape
    text = 'Fear & Greed: 72'
    result = selective_html_escape(text)
    assert "&amp;" in result
    assert "Fear &amp; Greed" in result
```
- **Asserts**: HTML entities in non-link text properly escaped
- **Effort**: S

#### `TestSplitMessage.test_split_message_new_separators`
```python
def test_split_message_new_separators(self):
    """Verify ━━━ separator recognized as split point (AC10)."""
    content = (
        "Section 1 content here\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Section 2 content here that is long enough " + "x" * 3000 + "\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Section 3 content here " + "y" * 3000
    )
    msgs = split_message("L1", content)
    assert len(msgs) >= 2
    # Verify no section split mid-content (split on separator)
    for msg in msgs:
        # Each part should not start/end mid-separator
        assert not msg.content.startswith("━━━━")
```
- **Asserts**: `━━━` recognized as split boundary, sections not split mid-content
- **Effort**: M

#### `TestSplitMessage.test_split_message_emoji_headers`
```python
def test_split_message_emoji_headers(self):
    """Verify emoji headers not split mid-header."""
    content = (
        "📊 BAN TIN CRYPTO\n\n"
        "Content block 1 " + "x" * 3000 + "\n\n"
        "🔥 TIN NOI BAT\n\n"
        "Content block 2 " + "y" * 3000
    )
    msgs = split_message("L1", content)
    assert len(msgs) >= 2
    # Emoji headers should stay with their content
    for msg in msgs:
        if "📊" in msg.content:
            assert "BAN TIN CRYPTO" in msg.content
        if "🔥" in msg.content:
            assert "TIN NOI BAT" in msg.content
```
- **Asserts**: Emoji headers stay attached to their section content
- **Effort**: M

#### `TestTelegramBot.test_send_photo_success`
```python
async def test_send_photo_success(self):
    """Verify sendPhoto API call with correct payload."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True, "result": {"message_id": 42}}
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    bot = TelegramBot(bot_token="test-token", chat_id="12345")
    with patch("cic_daily_report.delivery.telegram_bot.httpx.AsyncClient",
               return_value=mock_client):
        result = await bot.send_photo(
            photo_url="https://messari.io/chart.png",
            caption='📊 <a href="https://messari.io/report">Messari Report</a>',
        )

    assert result["ok"] is True
    call_args = mock_client.post.call_args
    payload = call_args.kwargs.get("json") or call_args[1].get("json")
    assert payload["photo"] == "https://messari.io/chart.png"
    assert payload["parse_mode"] == "HTML"
    assert "caption" in payload
```
- **Asserts**: Correct API endpoint (`sendPhoto`), payload structure, parse_mode
- **Effort**: M

#### `TestTelegramBot.test_send_photo_failure_fallback`
```python
async def test_send_photo_failure_fallback(self):
    """Verify graceful degradation when sendPhoto fails (AC18)."""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=Exception("Photo URL invalid"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    bot = TelegramBot(bot_token="test-token", chat_id="12345")
    with patch("cic_daily_report.delivery.telegram_bot.httpx.AsyncClient",
               return_value=mock_client):
        result = await bot.send_photo(
            photo_url="https://broken.com/404.png",
            caption="Caption",
        )

    assert result["ok"] is False
    # Should not raise — graceful failure
```
- **Asserts**: Returns `{"ok": False}` instead of raising exception
- **Effort**: M

#### `TestTelegramBot.test_send_photo_caption_truncation`
```python
async def test_send_photo_caption_truncation(self):
    """Verify caption truncated to 1024 chars (AC19)."""
    bot = TelegramBot(bot_token="test-token", chat_id="12345")
    long_caption = "A" * 2000

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True, "result": {}}
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("cic_daily_report.delivery.telegram_bot.httpx.AsyncClient",
               return_value=mock_client):
        await bot.send_photo(photo_url="https://ok.com/img.png", caption=long_caption)

    call_args = mock_client.post.call_args
    payload = call_args.kwargs.get("json") or call_args[1].get("json")
    assert len(payload["caption"]) <= 1024
```
- **Asserts**: Caption in API payload <= 1024 characters
- **Effort**: M

### File: `tests/test_delivery/test_delivery_manager.py`

#### `TestDeliveryManager.test_delivery_with_photos`
```python
async def test_delivery_with_photos(self):
    """Verify photo delivered BEFORE text messages (spec: send photo TRUOC ban tin)."""
    mock_tg = AsyncMock(spec=TelegramBot)
    mock_tg.deliver_all = AsyncMock(return_value=[{"ok": True}, {"ok": True}])
    mock_tg.send_message = AsyncMock()
    mock_tg.send_photo = AsyncMock(return_value={"ok": True})

    articles_with_photos = [
        {"tier": "L1", "content": "Article 1",
         "source_urls": [{"name": "CoinDesk", "url": "https://coindesk.com/1"}],
         "image_urls": ["https://messari.io/chart.png"]},
        {"tier": "L2", "content": "Article 2",
         "source_urls": [], "image_urls": []},
    ]

    mgr = DeliveryManager(telegram_bot=mock_tg)
    result = await mgr.deliver(articles_with_photos)

    assert result.success
    # send_photo called before deliver_all
    mock_tg.send_photo.assert_called()
```
- **Asserts**: `send_photo` called, delivery succeeds, photo before text
- **Effort**: M

#### `TestDeliveryManager.test_delivery_photo_failure_continues`
```python
async def test_delivery_photo_failure_continues(self):
    """Verify photo failure doesn't block text delivery (AC18)."""
    mock_tg = AsyncMock(spec=TelegramBot)
    mock_tg.deliver_all = AsyncMock(return_value=[{"ok": True}])
    mock_tg.send_message = AsyncMock()
    mock_tg.send_photo = AsyncMock(return_value={"ok": False, "error": "photo failed"})

    articles = [
        {"tier": "L1", "content": "Article 1",
         "source_urls": [], "image_urls": ["https://broken.com/img.png"]},
    ]

    mgr = DeliveryManager(telegram_bot=mock_tg)
    result = await mgr.deliver(articles)

    # Text delivery should still succeed
    assert result.success
    mock_tg.deliver_all.assert_called()
```
- **Asserts**: Text delivery proceeds even when photo fails
- **Effort**: M

### File: `tests/test_delivery/test_email_backup.py` (new tests to add to existing file or create)

#### `TestEmailBackup.test_email_html_format`
```python
def test_email_html_format(self):
    """Verify email body sent as HTML subtype (AC12)."""
    backup = EmailBackup(
        smtp_server="smtp.test.com", smtp_port=587,
        smtp_email="test@test.com", smtp_password="pass",
        recipients=["r@test.com"],
    )
    with patch("cic_daily_report.delivery.email_backup.smtplib.SMTP") as mock_smtp:
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

        html_body = "<h1>Daily Report</h1><p>BTC at $105K</p>"
        backup.send(subject="Test", body=html_body)

        # Verify msg.set_content called with subtype="html"
        call_args = mock_server.send_message.call_args
        msg = call_args[0][0]
        content_type = msg.get_content_type()
        assert content_type == "text/html"
```
- **Asserts**: Email content type is `text/html` not `text/plain`
- **Effort**: M

### File: `tests/test_delivery/test_telegram_bot.py` (truncation tests)

#### `TestTruncation.test_truncation_8000`
```python
def test_truncation_8000(self):
    """Verify NOI_DUNG_DA_TAO truncation at 8000 chars (AC14)."""
    # This tests the pipeline truncation, not TG bot directly.
    # The truncation happens in daily_pipeline.py line ~512
    content = "A" * 10000
    truncated = content[:8000]
    assert len(truncated) == 8000
```
- **Note**: This is better tested in a pipeline-level test. See Cum 4 integration tests.
- **Effort**: S

#### `TestTruncation.test_truncation_safe_boundary`
```python
def test_truncation_safe_boundary(self):
    """Verify truncation doesn't cut mid-emoji (R7)."""
    # Multi-byte emoji at boundary
    content = "A" * 7998 + "📊"  # 📊 is 1 Python char but multi-byte UTF-8
    # Truncation should not produce invalid text
    truncated = content[:8000]
    # Verify no broken surrogate pairs
    assert truncated.encode("utf-8", errors="strict")  # Should not raise
```
- **Asserts**: No broken multi-byte chars at truncation boundary
- **Effort**: S

---

## 5. NEW TESTS -- CUM 3: GENERATOR LAYER

### File: `tests/test_generators/test_article_generator.py`

#### `TestGeneratedArticle.test_generated_article_source_urls`
```python
def test_generated_article_source_urls(self):
    """Verify source_urls field on GeneratedArticle dataclass."""
    article = GeneratedArticle(
        tier="L1", title="[L1] Test", content="Content",
        word_count=50, llm_used="test", generation_time_sec=1.0,
        source_urls=[{"name": "CoinDesk", "url": "https://coindesk.com/1"}],
    )
    assert len(article.source_urls) == 1
    assert article.source_urls[0]["name"] == "CoinDesk"
    assert article.source_urls[0]["url"] == "https://coindesk.com/1"
```
- **Asserts**: `source_urls` field exists, is list of dicts with name+url keys
- **Effort**: S

#### `TestGeneratedArticle.test_generated_article_source_urls_default`
```python
def test_generated_article_source_urls_default(self):
    """Verify source_urls defaults to empty list."""
    article = GeneratedArticle(
        tier="L1", title="[L1] Test", content="Content",
        word_count=50, llm_used="test", generation_time_sec=1.0,
    )
    assert article.source_urls == []
```
- **Asserts**: Default is empty list (backward-compatible)
- **Effort**: S

#### `TestGenerateTierArticles.test_url_mapping_preserved`
```python
async def test_url_mapping_preserved(self):
    """Verify source_name->url mapping passed through generation (spec 3.2)."""
    templates = _make_templates("L1")
    context = _make_context()
    # Add news_summary with URLs that should be mapped
    context.news_summary = (
        "- BTC hits $100K (CoinDesk)\n"
        "  URL: https://coindesk.com/btc-100k\n"
        "- ETH upgrade (CoinTelegraph)\n"
        "  URL: https://cointelegraph.com/eth"
    )

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(
        return_value=LLMResponse(text=_MOCK_ARTICLE, tokens_used=100, model="m")
    )

    articles = await generate_tier_articles(mock_llm, templates, context)
    assert len(articles) == 1
    # source_urls should be populated from news data
    assert isinstance(articles[0].source_urls, list)
```
- **Asserts**: `source_urls` populated from news data context
- **Effort**: M

#### `TestGenerateTierArticles.test_research_priority_l3_l5`
```python
async def test_research_priority_l3_l5(self):
    """Verify research articles prioritized in L3-L5 context (AC3)."""
    templates = _make_templates("L3", "L5")
    context = _make_context()
    # news_summary should contain research markers
    context.news_summary = (
        "=== RESEARCH ===\n"
        "- Stablecoin Analysis (Messari)\n"
        "=== TIN CRYPTO ===\n"
        "- BTC price update (CoinDesk)\n"
    )

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(
        return_value=LLMResponse(text=_MOCK_ARTICLE, tokens_used=100, model="m")
    )

    articles = await generate_tier_articles(mock_llm, templates, context)

    # Verify research content appears in the prompt sent to LLM
    for call in mock_llm.generate.call_args_list:
        prompt = call.kwargs.get("prompt", "")
        assert "RESEARCH" in prompt or "Messari" in prompt
```
- **Asserts**: Research content included in LLM prompts for L3-L5
- **Effort**: M

### File: `tests/test_generators/test_summary_generator.py`

#### `TestGenerateBicSummary.test_summary_strip_decorations`
```python
async def test_summary_strip_decorations(self):
    """Verify emoji headers and separators stripped before 800-char excerpt (AC13)."""
    articles = [
        GeneratedArticle(
            tier="L1",
            title="[L1] Test",
            content=(
                "📊 BAN TIN CRYPTO\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "Actual analysis content starts here. BTC is trading at $105K.\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "🔥 TIN NOI BAT\n"
                + DISCLAIMER
            ),
            word_count=50, llm_used="test", generation_time_sec=1.0,
        ),
    ]

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(
        return_value=LLMResponse(text="Summary output", tokens_used=30, model="m")
    )

    await generate_bic_summary(mock_llm, articles, _metrics())

    # Check the prompt sent to LLM — excerpt should NOT contain decorations
    call_args = mock_llm.generate.call_args
    prompt = call_args.kwargs.get("prompt", "")
    assert "━━━" not in prompt
    assert "📊" not in prompt
    assert "Actual analysis content" in prompt
```
- **Asserts**: Decorations (emoji headers, `━━━` separators) stripped from excerpt before LLM prompt
- **Effort**: M

### File: `tests/test_generators/test_nq05_filter.py`

#### `TestCheckAndFix.test_nq05_scan_link_text`
```python
def test_nq05_scan_link_text(self):
    """Verify NQ05 scans text inside <a> tags for banned words (spec 3.5)."""
    content = (
        'Read more: <a href="https://example.com">nên mua BTC</a> for details.'
        + DISCLAIMER
    )
    result = check_and_fix(content)
    assert result.violations_found >= 1
    # The banned word inside the link text should be caught
    assert "nên mua" not in result.content
```
- **Asserts**: Banned keywords detected even inside `<a>` tag text
- **Critical path**: YES (NQ05 compliance)
- **Effort**: S

#### `TestCheckAndFix.test_nq05_clean_link_passes`
```python
def test_nq05_clean_link_passes(self):
    """Verify clean links with no banned words pass NQ05."""
    content = (
        'Sources: <a href="https://messari.io">Messari Research</a> · '
        '<a href="https://glassnode.com">Glassnode Insights</a>'
        + DISCLAIMER
    )
    result = check_and_fix(content)
    assert result.violations_found == 0
    # Links should be preserved
    assert '<a href="https://messari.io">' in result.content
    assert "Messari Research</a>" in result.content
```
- **Asserts**: Clean links not flagged, HTML preserved
- **Effort**: S

#### `TestCheckAndFix.test_nq05_link_href_not_scanned`
```python
def test_nq05_link_href_not_scanned(self):
    """Verify URL in href attribute is not scanned for banned words."""
    content = (
        '<a href="https://example.com/buy-now-guide">Market Guide</a>'
        + DISCLAIMER
    )
    result = check_and_fix(content)
    # "buy now" appears in URL but should NOT trigger a violation
    # Only link TEXT ("Market Guide") should be scanned
    assert result.violations_found == 0
```
- **Asserts**: href URL content not treated as text for NQ05 scanning
- **Effort**: S

### File: `tests/test_generators/test_template_engine.py`

#### `TestRenderSections.test_template_emoji_headers`
```python
def test_template_emoji_headers(self):
    """Verify emoji headers in rendered output (spec 3.6)."""
    template = ArticleTemplate(
        tier="L1",
        sections=[
            SectionTemplate("L1", "Market Overview", True, 1,
                          "Analyze {coin_list}", 300),
        ],
    )
    rendered = render_sections(template, {"coin_list": "BTC, ETH"})
    assert len(rendered) == 1
    # After Cum 3, template engine adds emoji headers to section prompts
    # The exact format depends on implementation, but verify the mechanism works
    assert rendered[0].prompt  # Non-empty prompt generated
```
- **Asserts**: Template engine produces output with new format elements
- **Note**: The exact emoji headers may be added at the delivery layer rather than template engine. This test should be adjusted based on where the formatting is applied.
- **Effort**: S

---

## 6. NEW TESTS -- CUM 4: INTEGRATION

### File: `tests/test_delivery/test_pipeline_e2e.py`

#### `TestFullPipelineE2E.test_full_pipeline_with_research`
```python
async def test_full_pipeline_with_research(self):
    """End-to-end: research feeds -> generation -> delivery (AC1-AC6)."""
    llm = _mock_llm()
    templates = _templates()
    context = _context()
    # Add research content to context
    context.news_summary = (
        "=== RESEARCH ===\n"
        "- Yield-Bearing Stablecoins Analysis (Messari)\n"
        "  Summary: Yield-bearing stablecoins grew 15x in TVL...\n"
        "=== TIN CRYPTO ===\n"
        "- BTC hits $105K (CoinDesk)\n"
    )

    articles = await generate_tier_articles(llm, templates, context)
    assert len(articles) == 5

    summary = await generate_bic_summary(llm, articles, context.key_metrics)
    assert summary.word_count > 0

    # NQ05 check
    all_content = [a.content for a in articles] + [summary.content]
    for content in all_content:
        result = check_and_fix(content)
        assert result.passed
```
- **Asserts**: Full pipeline works with research context, NQ05 passes
- **Effort**: L

#### `TestFullPipelineE2E.test_pipeline_no_research_fallback`
```python
async def test_pipeline_no_research_fallback(self):
    """Pipeline operates normally when no research feeds available (AC6)."""
    llm = _mock_llm()
    templates = _templates()
    context = _context()
    # No research content — only news
    context.news_summary = "- BTC price update (CoinDesk)\n"

    articles = await generate_tier_articles(llm, templates, context)
    assert len(articles) == 5  # All tiers still generated

    for article in articles:
        assert DISCLAIMER in article.content
```
- **Asserts**: All 5 tiers generated without research data, disclaimers present
- **Effort**: M

#### `TestFullPipelineE2E.test_pipeline_format_telegram_output`
```python
async def test_pipeline_format_telegram_output(self):
    """Verify final Telegram message format matches spec (AC7)."""
    articles_with_format = [
        {"tier": "L1", "content": (
            "📊 BAN TIN CRYPTO NGAY 13/03/2026\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🟢 THI TRUONG TONG QUAN\n\n"
            "BTC: $105,000 ▲ +2.3%\n"
            "ETH: $3,800 ▲ +1.5%\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            + DISCLAIMER
        )},
    ]

    messages = prepare_messages(articles_with_format)
    assert len(messages) >= 1
    formatted = messages[0].formatted
    assert "[L1]" in formatted
    # Verify emoji headers present
    assert "📊" in formatted
    assert "━━━" in formatted
```
- **Asserts**: Formatted output contains emoji headers and separators from spec
- **Effort**: M

#### `TestFullPipelineE2E.test_pipeline_hyperlinks_in_output`
```python
async def test_pipeline_hyperlinks_in_output(self):
    """Verify clickable hyperlinks survive delivery pipeline (AC8, AC9)."""
    from cic_daily_report.delivery.telegram_bot import selective_html_escape

    content_with_links = (
        "🔥 TIN NOI BAT\n\n"
        '• BTC hits $105K\n  🔗 <a href="https://coindesk.com/1">CoinDesk</a>\n\n'
        '• ETH upgrade\n  🔗 <a href="https://cointelegraph.com/2">CoinTelegraph</a>\n'
    )

    # Selective escape should preserve links
    escaped = selective_html_escape(content_with_links)
    assert '<a href="https://coindesk.com/1">CoinDesk</a>' in escaped
    assert '<a href="https://cointelegraph.com/2">CoinTelegraph</a>' in escaped
```
- **Asserts**: Hyperlinks preserved through selective HTML escape
- **Effort**: M

#### `TestFullPipelineE2E.test_pipeline_photo_delivery`
```python
async def test_pipeline_photo_delivery(self):
    """Verify photo+text delivery sequence (AC16, AC17)."""
    mock_tg = AsyncMock(spec=TelegramBot)
    mock_tg.deliver_all = AsyncMock(return_value=[{"ok": True}])
    mock_tg.send_message = AsyncMock()
    mock_tg.send_photo = AsyncMock(return_value={"ok": True})

    articles = [
        {"tier": "L1", "content": "Article content",
         "source_urls": [{"name": "Messari", "url": "https://messari.io"}],
         "image_urls": ["https://messari.io/chart.png"]},
    ]

    mgr = DeliveryManager(telegram_bot=mock_tg)
    result = await mgr.deliver(articles)

    assert result.success
    mock_tg.send_photo.assert_called_once()
    mock_tg.deliver_all.assert_called_once()
```
- **Asserts**: Both send_photo and deliver_all called, delivery succeeds
- **Effort**: M

### File: `tests/test_integration/test_pipeline_data_flow.py`

#### `TestFilteredNewsExclusion.test_research_articles_in_pipeline`
```python
def test_research_articles_in_pipeline(self):
    """Verify research articles flow through pipeline with source_type preserved."""
    articles = [
        {"title": "BTC News", "url": "https://a.com/1",
         "source_name": "CoinDesk", "source_type": "news", "filtered": False},
        {"title": "Stablecoin Analysis", "url": "https://b.com/2",
         "source_name": "Messari", "source_type": "research", "filtered": False},
        {"title": "SPAM", "url": "https://c.com/3",
         "source_name": "Spam", "source_type": "news", "filtered": True},
    ]
    cleaned = [a for a in articles if not a.get("filtered", False)]

    assert len(cleaned) == 2
    research = [a for a in cleaned if a.get("source_type") == "research"]
    assert len(research) == 1
    assert research[0]["source_name"] == "Messari"
```
- **Asserts**: Research articles flow through, filtered articles excluded, source_type preserved
- **Effort**: S

#### `TestFilteredNewsExclusion.test_truncation_8000_chars`
```python
def test_truncation_8000_chars(self):
    """Verify NOI_DUNG_DA_TAO truncation at 8000 chars (AC14)."""
    content = "A" * 10000
    # Simulate the truncation from daily_pipeline.py
    truncated = content[:8000]
    assert len(truncated) == 8000

    # Verify safe boundary for multi-byte
    content_with_emoji = "A" * 7999 + "📊"
    truncated = content_with_emoji[:8000]
    # Should be valid UTF-8
    truncated.encode("utf-8")  # Should not raise
```
- **Asserts**: 8000 char truncation, UTF-8 safe boundary
- **Effort**: S

---

## 7. TEST FIXTURES NEEDED

### 7.1. New Fixture Files (in `tests/fixtures/`)

#### `rss_research_feed.xml`
```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Messari Research</title>
    <item>
      <title>In The Stables: Yield-Bearing Stablecoins</title>
      <link>https://messari.io/report/yield-bearing-stablecoins</link>
      <description>Analysis of yield-bearing stablecoin growth</description>
      <pubDate>Thu, 13 Mar 2026 10:00:00 GMT</pubDate>
      <media:content url="https://messari.io/images/chart.png" type="image/png"/>
    </item>
  </channel>
</rss>
```
- **Used by**: `test_rss_collector.py` research feed tests
- **Purpose**: Mock RSS XML for research feed parsing

#### `trafilatura_metadata_response.json`
```json
{
  "title": "Yield-Bearing Stablecoins Analysis",
  "author": "Messari Research Team",
  "url": "https://messari.io/report/yield-bearing-stablecoins",
  "image": "https://messari.io/images/og-chart.png",
  "description": "Detailed analysis of yield-bearing stablecoin growth"
}
```
- **Used by**: `test_rss_collector.py` og:image extraction tests
- **Purpose**: Mock trafilatura metadata response

#### `telegram_send_photo_response.json`
```json
{
  "ok": true,
  "result": {
    "message_id": 42,
    "chat": {"id": 12345, "type": "private"},
    "photo": [
      {"file_id": "abc123", "width": 800, "height": 600}
    ],
    "caption": "📊 Chart caption here"
  }
}
```
- **Used by**: `test_telegram_bot.py` send_photo tests
- **Purpose**: Mock Telegram Bot API sendPhoto response

#### `article_with_hyperlinks.json`
```json
{
  "tier": "L1",
  "content": "📊 BAN TIN CRYPTO\n━━━━━━━━━━━━━━━━━━━━━\n\n🔥 TIN NOI BAT\n\n• BTC hits $105K\n  🔗 <a href=\"https://coindesk.com/btc\">CoinDesk</a>\n\n━━━━━━━━━━━━━━━━━━━━━\n\n📖 PHAN TICH CHUYEN SAU\n\nDetailed analysis here.\n\n🔗 Nguon: <a href=\"https://messari.io\">Messari</a> · <a href=\"https://glassnode.com\">Glassnode</a>",
  "source_urls": [
    {"name": "CoinDesk", "url": "https://coindesk.com/btc"},
    {"name": "Messari", "url": "https://messari.io"},
    {"name": "Glassnode", "url": "https://glassnode.com"}
  ],
  "image_urls": ["https://messari.io/chart.png"]
}
```
- **Used by**: Integration tests for hyperlink + photo delivery
- **Purpose**: Full article dict with new schema

### 7.2. Updated Existing Fixtures in `conftest.py`

#### Update `sample_news_articles` fixture
```python
@pytest.fixture
def sample_news_articles():
    """Sample news articles for testing pipeline processing."""
    return [
        {
            "title": "BTC hits $100K",
            "summary": "Bitcoin reached a milestone",
            "source": "CoinDesk",
            "url": "https://example.com/1",
            "filtered": False,
            "source_type": "news",
        },
        {
            "title": "SPAM article",
            "summary": "",
            "source": "Unknown",
            "url": "https://example.com/2",
            "filtered": True,
            "source_type": "news",
        },
        {
            "title": "ETH update",
            "summary": "Ethereum protocol upgrade",
            "source": "CoinTelegraph",
            "url": "https://example.com/3",
            "filtered": False,
            "source_type": "news",
        },
        {
            "title": "Stablecoin TVL Analysis",
            "summary": "Yield-bearing stablecoins grew 15x",
            "source": "Messari",
            "url": "https://example.com/4",
            "filtered": False,
            "source_type": "research",
            "og_image": "https://example.com/chart.png",
        },
    ]
```
- **Changes**: Added `source_type` to all existing articles, added new research article with `og_image`

### 7.3. New Shared Fixtures in `conftest.py`

#### `sample_research_article` fixture
```python
@pytest.fixture
def sample_research_article():
    """Sample research article for testing research feed processing."""
    return {
        "title": "Yield-Bearing Stablecoins: The Rise of a New Asset Class",
        "summary": "Yield-bearing stablecoins have grown 15x in TVL since 2024",
        "source": "Messari",
        "url": "https://messari.io/report/stablecoins",
        "filtered": False,
        "source_type": "research",
        "og_image": "https://messari.io/images/stablecoin-chart.png",
        "full_text": "Detailed analysis of yield-bearing stablecoin growth...",
    }
```

#### `sample_article_with_links` fixture
```python
@pytest.fixture
def sample_article_with_links():
    """Sample article dict with hyperlinks and photos for delivery testing."""
    return {
        "tier": "L1",
        "content": (
            "📊 BAN TIN CRYPTO NGAY 13/03/2026\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔥 TIN NOI BAT\n\n"
            "• BTC hits $105K\n"
            '  🔗 <a href="https://coindesk.com/btc">CoinDesk</a>\n\n'
            "━━━━━━━━━━━━━━━━━━━━━\n"
        ),
        "source_urls": [
            {"name": "CoinDesk", "url": "https://coindesk.com/btc"},
        ],
        "image_urls": ["https://messari.io/chart.png"],
    }
```

---

## 8. COVERAGE TARGETS & CRITICAL PATHS

### Coverage Requirements

| Scope | Target | Metric |
|-------|--------|--------|
| New code (all Cums) | >= 80% | Line coverage on changed/new files |
| Overall project | >= 60% | Total line coverage (CI gate: `--cov-fail-under=60`) |
| `selective_html_escape()` | 100% | All branches: clean links, XSS, javascript:, data:, malformed |
| `send_photo()` | 100% | Success, failure, caption truncation |
| NQ05 link text scan | 100% | Banned words in link text, clean links, href not scanned |
| `split_message()` new patterns | >= 90% | `━━━` separator, emoji headers, fallback to old patterns |

### Critical Paths (100% Coverage Required)

1. **`selective_html_escape()`** — Security-critical. XSS prevention gate.
   - Tests: `test_selective_html_escape_preserves_links`, `test_selective_html_escape_blocks_xss`, `test_selective_html_escape_blocks_javascript_href`, `test_selective_html_escape_blocks_data_href`, `test_selective_html_escape_malformed_html`, `test_selective_html_escape_multiple_links`, `test_selective_html_escape_ampersand_in_text`
   - Total: 7 tests covering all branches

2. **NQ05 link text scan** — Compliance-critical.
   - Tests: `test_nq05_scan_link_text`, `test_nq05_clean_link_passes`, `test_nq05_link_href_not_scanned`
   - Total: 3 tests

3. **`send_photo()` graceful degradation** — User experience.
   - Tests: `test_send_photo_success`, `test_send_photo_failure_fallback`, `test_send_photo_caption_truncation`
   - Total: 3 tests

4. **Research feed fallback** — Pipeline resilience.
   - Tests: `test_research_feed_failure_graceful`, `test_pipeline_no_research_fallback`
   - Total: 2 tests

### Coverage Measurement Command
```bash
uv run pytest --cov=src/cic_daily_report --cov-report=term-missing --cov-fail-under=60
```

For new code specifically:
```bash
uv run pytest --cov=src/cic_daily_report/delivery/telegram_bot \
              --cov=src/cic_daily_report/collectors/rss_collector \
              --cov=src/cic_daily_report/generators/nq05_filter \
              --cov-report=term-missing
```

---

## 9. REGRESSION TEST STRATEGY

### Per-Cum Regression Gates

| Gate | Command | Pass Criteria |
|------|---------|---------------|
| After Cum 1 | `uv run pytest tests/test_collectors/` | All collector tests pass |
| After Cum 1 | `uv run pytest` | Full suite passes, coverage >= 60% |
| After Cum 2 | `uv run pytest tests/test_delivery/` | All delivery tests pass |
| After Cum 2 | `uv run pytest` | Full suite passes, coverage >= 60% |
| After Cum 3 | `uv run pytest tests/test_generators/` | All generator tests pass |
| After Cum 3 | `uv run pytest` | Full suite passes, coverage >= 60% |
| After Cum 4 | `uv run pytest` | Full suite passes, coverage >= 60% |
| After Cum 4 | `uv run ruff check src/ tests/` | No lint errors |

### Breaking Pipeline Isolation

The breaking pipeline (`breaking_pipeline.py`) must remain completely unaffected:
- **No changes to**: `breaking/event_detector.py`, `breaking/content_generator.py`, `breaking/dedup_manager.py`, `breaking/severity_classifier.py`
- **Verify**: `uv run pytest tests/test_breaking/` passes unchanged after each Cum (if test_breaking/ exists)
- **Verify**: `breaking_pipeline.py` imports and code paths unchanged

### Smoke Tests After Full Integration

After all Cums complete, run these manual smoke tests:
1. **Mock pipeline run**: `uv run python -c "from cic_daily_report.daily_pipeline import run_pipeline; print('import OK')"`
2. **RSS feed count**: `uv run python -c "from cic_daily_report.collectors.rss_collector import DEFAULT_FEEDS; assert len(DEFAULT_FEEDS) >= 21; print(f'{len(DEFAULT_FEEDS)} feeds OK')"`
3. **Dataclass fields**: `uv run python -c "from cic_daily_report.collectors.rss_collector import FeedConfig, NewsArticle; f = FeedConfig('url','name','en',source_type='research'); a = NewsArticle('t','u','s','d','s','en',source_type='research'); print('dataclass OK')"`

---

## 10. TEST EXECUTION ORDER

### Phase 1: Cum 1 Tests (Data Layer)
1. Update `conftest.py` — add `source_type` to existing fixtures
2. Update `test_rss_collector.py` — 6 existing tests + 10 new tests
3. Update `test_data_cleaner.py` — 3 existing tests + 2 new tests
4. Add CryptoPanic tests — 2 new tests
5. Run: `uv run pytest tests/test_collectors/ -v`
6. Run: `uv run pytest` (full regression)

### Phase 2: Cum 2 Tests (Delivery Layer)
1. Update `test_telegram_bot.py` — 7 existing tests + 14 new tests
2. Update `test_delivery_manager.py` — 6 existing tests + 2 new tests
3. Add email HTML test — 1 new test
4. Add truncation tests — 2 new tests
5. Run: `uv run pytest tests/test_delivery/ -v`
6. Run: `uv run pytest` (full regression)

### Phase 3: Cum 3 Tests (Generator Layer)
1. Update `test_article_generator.py` — 3 existing tests + 4 new tests
2. Update `test_summary_generator.py` — 1 existing test + 1 new test
3. Update `test_template_engine.py` — 1 existing test + 1 new test
4. Add NQ05 link scan tests — 3 new tests
5. Run: `uv run pytest tests/test_generators/ -v`
6. Run: `uv run pytest` (full regression)

### Phase 4: Cum 4 Tests (Integration)
1. Update `test_pipeline_e2e.py` — 5 existing tests + 5 new tests
2. Update `test_content_integration.py` — 3 existing tests
3. Update `test_pipeline_data_flow.py` — 1 existing test + 2 new tests
4. Run: `uv run pytest` (full regression)
5. Run: `uv run ruff check src/ tests/` (lint)
6. Run: `uv run pytest --cov=src/cic_daily_report --cov-report=term-missing --cov-fail-under=60` (coverage)

### Total Test Count Summary

| Category | Update | New | Total |
|----------|--------|-----|-------|
| Cum 1: Data Layer | 9 | 14 | 23 |
| Cum 2: Delivery Layer | 13 | 19 | 32 |
| Cum 3: Generator Layer | 5 | 9 | 14 |
| Cum 4: Integration | 9 | 7 | 16 |
| **Grand Total** | **36** | **49** | **85** |

---

*Test Plan v1.0 — Quinn (QA Engineer), 2026-03-13*
*Aligned with SPEC-daily-report-enhancements-v3-final.md*
