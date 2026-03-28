"""Tests for P1.8 — Macro RSS feeds in rss_collector.py.

Verifies 5 macro FeedConfig entries, source_type propagation,
graceful failure isolation, and no regression on existing feeds.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from cic_daily_report.collectors.rss_collector import (
    DEFAULT_FEEDS,
    FeedConfig,
    NewsArticle,
    _sanitize_text,
    collect_rss,
)

# --- Constants derived from source of truth ---

MACRO_FEED_NAMES = {
    "Reuters_Business",
    "AP_Business",
    "CNBC_Economy",
    "OilPrice",
    "AlJazeera_Economy",
}

# Feeds that existed before P1.8 — must not be removed
PRE_EXISTING_CRYPTO_FEEDS = {
    "CoinTelegraph",
    "CoinDesk",
    "Decrypt",
    "TheBlock",
    "CryptoSlate",
    "UToday",
    "Coin68",
}


# --- Helpers ---


def _macro_feeds() -> list[FeedConfig]:
    """Return only macro FeedConfig entries from DEFAULT_FEEDS."""
    return [f for f in DEFAULT_FEEDS if f.source_type == "macro"]


def _make_mock_entry(title: str, link: str) -> MagicMock:
    """Create a mock feedparser entry."""
    entry = MagicMock()
    data = {
        "title": title,
        "link": link,
        "summary": f"Summary for {title}",
        "published": "2026-03-28",
    }
    entry.get = lambda k, d="": data.get(k, d)
    return entry


def _patch_http_and_feedparser(entries: list[MagicMock]):
    """Return context managers that mock httpx + feedparser for collect_rss."""
    mock_response = MagicMock()
    mock_response.text = "<rss>mock</rss>"
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    mock_parsed = MagicMock()
    mock_parsed.entries = entries

    http_patch = patch(
        "cic_daily_report.collectors.rss_collector.httpx.AsyncClient",
        return_value=mock_client,
    )
    fp_patch = patch(
        "cic_daily_report.collectors.rss_collector.feedparser.parse",
        return_value=mock_parsed,
    )
    return http_patch, fp_patch


# === Test classes ===


class TestMacroFeedsPresence:
    """Verify macro feed entries exist in DEFAULT_FEEDS with correct config."""

    def test_macro_feeds_in_default_feeds(self):
        """All 5 macro feeds present in DEFAULT_FEEDS."""
        macro_names = {f.source_name for f in _macro_feeds()}
        assert macro_names == MACRO_FEED_NAMES

    def test_macro_feed_count(self):
        """Exactly 5 macro feeds."""
        assert len(_macro_feeds()) == 5

    def test_macro_feed_source_type_is_macro(self):
        """Every macro feed has source_type='macro'."""
        for feed in _macro_feeds():
            assert feed.source_type == "macro", f"{feed.source_name} source_type wrong"

    def test_macro_feeds_are_enabled(self):
        """All macro feeds default to enabled=True."""
        for feed in _macro_feeds():
            assert feed.enabled is True, f"{feed.source_name} should be enabled"

    def test_macro_feeds_language_is_english(self):
        """All macro feeds are English."""
        for feed in _macro_feeds():
            assert feed.language == "en", f"{feed.source_name} should be 'en'"

    def test_macro_feeds_have_valid_urls(self):
        """Each macro feed URL starts with https."""
        for feed in _macro_feeds():
            assert feed.url.startswith("https://"), f"{feed.source_name} URL invalid"


class TestExistingFeedsNotRemoved:
    """P1.8 must not remove or break pre-existing crypto/research feeds."""

    def test_existing_crypto_feeds_still_present(self):
        """Core crypto feeds survive P1.8 addition."""
        all_names = {f.source_name for f in DEFAULT_FEEDS}
        for name in PRE_EXISTING_CRYPTO_FEEDS:
            assert name in all_names, f"{name} missing from DEFAULT_FEEDS"

    def test_research_feeds_still_present(self):
        """Research feeds (Messari, Glassnode) unchanged."""
        research = {f.source_name for f in DEFAULT_FEEDS if f.source_type == "research"}
        assert "Messari" in research
        assert "Glassnode_Insights" in research

    def test_total_feed_count_increased(self):
        """Total feeds >= 28 (23 original + 5 macro, minus 1 Reuters repurposed)."""
        # WHY: 23 feeds existed pre-P1.8; we replaced disabled Reuters with
        # Reuters_Business macro + added 4 new = net +4 entries.
        assert len(DEFAULT_FEEDS) >= 27


class TestSourceTypePropagation:
    """Verify FeedConfig.source_type flows to NewsArticle.source_type."""

    async def test_macro_articles_have_macro_source_type(self):
        """After parsing a macro feed, articles get source_type='macro'."""
        feed = FeedConfig(
            "https://test-macro.com/rss",
            "TestMacro",
            "en",
            source_type="macro",
        )
        entries = [_make_mock_entry("Rate hike looms", "https://test-macro.com/1")]
        http_patch, fp_patch = _patch_http_and_feedparser(entries)

        with http_patch, fp_patch:
            articles = await collect_rss(feeds=[feed])

        assert len(articles) == 1
        assert articles[0].source_type == "macro"

    async def test_news_articles_keep_news_source_type(self):
        """Non-macro feeds still produce source_type='news'."""
        feed = FeedConfig("https://test-news.com/rss", "TestNews", "en")
        entries = [_make_mock_entry("BTC pumps", "https://test-news.com/1")]
        http_patch, fp_patch = _patch_http_and_feedparser(entries)

        with http_patch, fp_patch:
            articles = await collect_rss(feeds=[feed])

        assert len(articles) == 1
        assert articles[0].source_type == "news"

    def test_macro_article_to_row_includes_source_type(self):
        """NewsArticle.to_row() puts source_type in the correct column."""
        article = NewsArticle(
            title="Fed raises rates",
            url="https://reuters.com/1",
            source_name="Reuters_Business",
            published_date="2026-03-28",
            summary="The Fed raised rates",
            language="en",
            source_type="macro",
        )
        row = article.to_row()
        # Column index 7 = event_type/source_type
        assert row[7] == "macro"


class TestCollectRssWithMacro:
    """Integration-level tests for collect_rss including macro feeds."""

    async def test_collect_rss_includes_macro_articles(self):
        """collect_rss returns macro articles alongside crypto articles."""
        crypto_feed = FeedConfig("https://crypto.test/rss", "CryptoTest", "en")
        macro_feed = FeedConfig("https://macro.test/rss", "MacroTest", "en", source_type="macro")

        def make_parsed(source: str):
            m = MagicMock()
            m.entries = [_make_mock_entry(f"{source} headline", f"https://{source}.test/1")]
            return m

        mock_response = MagicMock()
        mock_response.text = "<rss>mock</rss>"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        parseds = [make_parsed("crypto"), make_parsed("macro")]

        with (
            patch(
                "cic_daily_report.collectors.rss_collector.httpx.AsyncClient",
                return_value=mock_client,
            ),
            patch(
                "cic_daily_report.collectors.rss_collector.feedparser.parse",
                side_effect=parseds,
            ),
        ):
            articles = await collect_rss(feeds=[crypto_feed, macro_feed])

        assert len(articles) == 2
        types = {a.source_type for a in articles}
        assert "news" in types
        assert "macro" in types

    async def test_macro_feed_failure_graceful(self):
        """One macro feed failing does not block other feeds (NFR16)."""
        good_macro = FeedConfig(
            "https://good-macro.com/rss", "GoodMacro", "en", source_type="macro"
        )
        bad_macro = FeedConfig("https://bad-macro.com/rss", "BadMacro", "en", source_type="macro")

        entries = [_make_mock_entry("Good macro news", "https://good-macro.com/1")]
        mock_response = MagicMock()
        mock_response.text = "<rss>mock</rss>"
        mock_response.raise_for_status = MagicMock()

        mock_parsed = MagicMock()
        mock_parsed.entries = entries

        async def selective_get(url, **kwargs):
            if "bad-macro" in url:
                raise ConnectionError("Connection refused")
            return mock_response

        mock_client = AsyncMock()
        mock_client.get = selective_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "cic_daily_report.collectors.rss_collector.httpx.AsyncClient",
                return_value=mock_client,
            ),
            patch(
                "cic_daily_report.collectors.rss_collector.feedparser.parse",
                return_value=mock_parsed,
            ),
        ):
            articles = await collect_rss(feeds=[good_macro, bad_macro])

        assert len(articles) == 1
        assert articles[0].source_type == "macro"
        assert articles[0].source_name == "GoodMacro"


class TestMacroArticlesSanitized:
    """Macro articles go through the same _sanitize_text pipeline."""

    async def test_macro_articles_html_entities_cleaned(self):
        """HTML entities in macro feed titles/summaries are decoded."""
        feed = FeedConfig("https://macro-dirty.com/rss", "DirtyMacro", "en", source_type="macro")
        entry = MagicMock()
        data = {
            "title": "Oil &amp; Gas prices &lt;surge&gt;",
            "link": "https://macro-dirty.com/1",
            "summary": "Fed&#39;s decision on &quot;rates&quot;",
            "published": "2026-03-28",
        }
        entry.get = lambda k, d="": data.get(k, d)

        http_patch, fp_patch = _patch_http_and_feedparser([entry])
        with http_patch, fp_patch:
            articles = await collect_rss(feeds=[feed])

        assert len(articles) == 1
        # _sanitize_text decodes HTML entities
        assert "&amp;" not in articles[0].title
        assert "Oil & Gas" in articles[0].title
        assert "Fed's decision" in articles[0].summary

    def test_sanitize_text_handles_macro_content(self):
        """_sanitize_text works on typical macro news patterns."""
        raw = "S&amp;P 500 up 2%\x00\x0b &mdash; markets rally"
        cleaned = _sanitize_text(raw)
        assert "S&P 500" in cleaned
        assert "\x00" not in cleaned
        assert "\x0b" not in cleaned
