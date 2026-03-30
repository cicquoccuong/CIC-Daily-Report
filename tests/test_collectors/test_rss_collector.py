"""Tests for collectors/rss_collector.py — all mocked."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from cic_daily_report.collectors.rss_collector import (
    DEFAULT_FEEDS,
    FeedConfig,
    NewsArticle,
    _sanitize_text,
    collect_rss,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestFeedConfig:
    def test_default_feeds_count(self):
        assert len(DEFAULT_FEEDS) >= 17

    def test_bilingual_feeds(self):
        vi_feeds = [f for f in DEFAULT_FEEDS if f.language == "vi"]
        en_feeds = [f for f in DEFAULT_FEEDS if f.language == "en"]
        assert len(vi_feeds) >= 5
        assert len(en_feeds) >= 12

    def test_feed_has_required_fields(self):
        for feed in DEFAULT_FEEDS:
            assert feed.url
            assert feed.source_name
            assert feed.language in ("vi", "en")


class TestNewsArticle:
    def test_to_row(self):
        article = NewsArticle(
            title="Test Title",
            url="https://example.com",
            source_name="TestSource",
            published_date="2026-03-09",
            summary="A summary",
            language="en",
        )
        row = article.to_row()
        assert len(row) == 11  # matches TIN_TUC_THO columns
        assert row[1] == "Test Title"
        assert row[2] == "https://example.com"
        assert row[5] == "en"


class TestCollectRss:
    async def test_collect_with_mock_feed(self):
        """Test RSS collection with mocked httpx + feedparser."""
        feed = FeedConfig(
            url="https://test.com/rss",
            source_name="TestFeed",
            language="en",
        )

        mock_entry = MagicMock()
        mock_entry.get = lambda k, d="": {
            "title": "Test Article",
            "link": "https://test.com/article-1",
            "summary": "Article summary",
            "published": "2026-03-09",
        }.get(k, d)

        mock_parsed = MagicMock()
        mock_parsed.entries = [mock_entry]

        with (
            patch("cic_daily_report.collectors.rss_collector.httpx.AsyncClient") as mock_http,
            patch("cic_daily_report.collectors.rss_collector.feedparser.parse") as mock_fp,
        ):
            mock_response = MagicMock()
            mock_response.text = "<rss>mock</rss>"
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_http.return_value = mock_client

            mock_fp.return_value = mock_parsed

            articles = await collect_rss(feeds=[feed])

        assert len(articles) == 1
        assert articles[0].title == "Test Article"
        assert articles[0].source_name == "TestFeed"

    async def test_one_feed_failure_does_not_block(self):
        """NFR16: one feed failing does not block others."""
        good_feed = FeedConfig("https://good.com/rss", "Good", "en")
        bad_feed = FeedConfig("https://bad.com/rss", "Bad", "en")

        mock_entry = MagicMock()
        mock_entry.get = lambda k, d="": {
            "title": "Good Article",
            "link": "https://good.com/1",
            "summary": "Good",
            "published": "2026-03-09",
        }.get(k, d)

        with (
            patch("cic_daily_report.collectors.rss_collector.httpx.AsyncClient") as mock_http,
            patch("cic_daily_report.collectors.rss_collector.feedparser.parse") as mock_fp,
        ):
            mock_response = MagicMock()
            mock_response.text = "<rss>mock</rss>"
            mock_response.raise_for_status = MagicMock()

            call_count = 0

            async def mock_get(url, **kwargs):
                nonlocal call_count
                call_count += 1
                if "bad.com" in url:
                    raise ConnectionError("Connection refused")
                return mock_response

            mock_client = AsyncMock()
            mock_client.get = mock_get
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_http.return_value = mock_client

            mock_parsed = MagicMock()
            mock_parsed.entries = [mock_entry]
            mock_fp.return_value = mock_parsed

            articles = await collect_rss(feeds=[good_feed, bad_feed])

        # Good feed should succeed even though bad feed failed
        assert len(articles) == 1
        assert articles[0].source_name == "Good"


class TestPhase4FeedEnhancements:
    """Phase 4: New feeds, enrich flag, feed config."""

    def test_new_feeds_active(self):
        """F3: 4 new feeds added and enabled."""
        names = {f.source_name for f in DEFAULT_FEEDS if f.enabled}
        assert "CryptoNews" in names
        assert "Bitcoinist" in names
        assert "CryptoPotato" in names
        assert "BlogTienAo" in names

    def test_enriched_feeds_flagged(self):
        """F2: Top 5 news feeds have enrich=True."""
        enriched = [f for f in DEFAULT_FEEDS if f.enrich]
        enriched_names = {f.source_name for f in enriched}
        assert "CoinTelegraph" in enriched_names
        assert "CoinDesk" in enriched_names
        assert "TheBlock" in enriched_names
        assert "Decrypt" in enriched_names
        assert "Blockworks" in enriched_names

    def test_feed_config_has_enrich_field(self):
        """FeedConfig dataclass has enrich field."""
        feed = FeedConfig("https://test.com/rss", "Test", "en", enrich=True)
        assert feed.enrich is True
        default = FeedConfig("https://test.com/rss", "Test", "en")
        assert default.enrich is False


class TestSanitizeText:
    """SEC-05: _sanitize_text strips HTML tags."""

    def test_strips_html_tags(self):
        assert _sanitize_text("<p>Hello</p>") == "Hello"

    def test_strips_anchor_tags(self):
        assert _sanitize_text('<a href="http://x.com">link</a> text') == "link text"

    def test_preserves_plain_text(self):
        assert _sanitize_text("No HTML here") == "No HTML here"

    def test_strips_nested_tags(self):
        assert _sanitize_text("<div><p>nested</p></div>") == "nested"

    def test_html_entities_decoded(self):
        """HTML entities are decoded AFTER tag stripping — &lt;tag&gt; becomes literal <tag>."""
        result = _sanitize_text("&amp; &lt;tag&gt;")
        assert "&" in result
        # &lt;tag&gt; decodes to literal text "<tag>" — this is desired user content
        assert "<tag>" in result
