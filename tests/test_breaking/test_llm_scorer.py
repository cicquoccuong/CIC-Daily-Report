"""Tests for breaking/llm_scorer.py — RSS-based LLM scoring."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from cic_daily_report.breaking.llm_scorer import (
    _article_to_event,
    _filter_recent_articles,
    _parse_date,
    _parse_scores,
    score_rss_articles,
)
from cic_daily_report.collectors.rss_collector import NewsArticle


def _make_article(
    title="BTC breaks record",
    source="CoinDesk",
    published_date="",
    summary="Bitcoin reaches new ATH.",
    language="en",
) -> NewsArticle:
    return NewsArticle(
        title=title,
        url=f"https://example.com/{title.replace(' ', '-')}",
        source_name=source,
        published_date=published_date,
        summary=summary,
        language=language,
    )


class TestParseScores:
    def test_valid_json(self):
        output = '[{"index": 0, "score": 85}, {"index": 1, "score": 30}]'
        assert _parse_scores(output, 2) == [85, 30]

    def test_json_in_markdown(self):
        output = '```json\n[{"index": 0, "score": 90}]\n```'
        assert _parse_scores(output, 1) == [90]

    def test_invalid_json(self):
        assert _parse_scores("not json at all", 3) == [0, 0, 0]

    def test_out_of_range_scores_clamped(self):
        output = '[{"index": 0, "score": 150}, {"index": 1, "score": -10}]'
        scores = _parse_scores(output, 2)
        assert scores[0] == 100
        assert scores[1] == 0

    def test_missing_indices(self):
        output = '[{"index": 0, "score": 80}]'
        scores = _parse_scores(output, 3)
        assert scores == [80, 0, 0]

    def test_non_dict_items_skipped(self):
        output = '[42, {"index": 0, "score": 60}]'
        scores = _parse_scores(output, 2)
        assert scores == [60, 0]


class TestFilterRecentArticles:
    def test_recent_included(self):
        now = datetime.now(timezone.utc)
        article = _make_article(published_date=now.isoformat())
        assert len(_filter_recent_articles([article])) == 1

    def test_old_excluded(self):
        old = datetime.now(timezone.utc) - timedelta(hours=12)
        article = _make_article(published_date=old.isoformat())
        assert len(_filter_recent_articles([article])) == 0

    def test_unparseable_date_included(self):
        article = _make_article(published_date="not a date")
        assert len(_filter_recent_articles([article])) == 1

    def test_empty_date_included(self):
        article = _make_article(published_date="")
        assert len(_filter_recent_articles([article])) == 1


class TestParseDate:
    def test_iso_format(self):
        dt = _parse_date("2026-03-13T10:00:00+00:00")
        assert dt is not None

    def test_rfc2822(self):
        dt = _parse_date("Thu, 13 Mar 2026 10:00:00 +0000")
        assert dt is not None

    def test_empty(self):
        assert _parse_date("") is None

    def test_garbage(self):
        assert _parse_date("not a date") is None

    def test_iso_with_z(self):
        dt = _parse_date("2026-03-13T10:00:00Z")
        assert dt is not None


class TestArticleToEvent:
    def test_basic_conversion(self):
        article = _make_article(title="Major hack")
        event = _article_to_event(article, score=85, matched_keywords=["hack"])
        assert event.title == "Major hack"
        assert event.panic_score == 85
        assert event.matched_keywords == ["hack"]
        assert event.raw_data["source_type"] == "rss_fallback"

    def test_no_keywords(self):
        article = _make_article(title="News")
        event = _article_to_event(article, score=50)
        assert event.matched_keywords == []


class TestScoreRssArticles:
    async def test_keyword_bypass_llm(self):
        """Articles matching keywords should not need LLM scoring."""
        articles = [_make_article(title="Exchange hack reported")]
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock()

        events = await score_rss_articles(articles, mock_llm)
        assert len(events) == 1
        assert events[0].matched_keywords == ["hack"]
        mock_llm.generate.assert_not_called()

    async def test_llm_scoring_above_threshold(self):
        """Non-keyword articles scored above threshold become events."""
        articles = [_make_article(title="Bitcoin ETF news update")]
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '[{"index": 0, "score": 80}]'
        mock_llm.generate = AsyncMock(return_value=mock_response)

        events = await score_rss_articles(articles, mock_llm, threshold=70)
        assert len(events) == 1
        assert events[0].panic_score == 80

    async def test_llm_scoring_below_threshold(self):
        """Articles below threshold should not become events."""
        articles = [_make_article(title="Minor update")]
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '[{"index": 0, "score": 30}]'
        mock_llm.generate = AsyncMock(return_value=mock_response)

        events = await score_rss_articles(articles, mock_llm, threshold=70)
        assert len(events) == 0

    async def test_llm_failure_returns_keyword_only(self):
        """LLM failure should return only keyword matches, not crash."""
        articles = [
            _make_article(title="Exchange hack"),
            _make_article(title="Normal update"),
        ]
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(side_effect=Exception("LLM down"))

        events = await score_rss_articles(articles, mock_llm)
        assert len(events) == 1  # Only keyword match

    async def test_empty_articles(self):
        events = await score_rss_articles([], AsyncMock())
        assert events == []

    async def test_mixed_keyword_and_llm(self):
        """Mix of keyword matches and LLM-scored articles."""
        articles = [
            _make_article(title="Crypto exchange hack alert"),
            _make_article(title="New regulation update"),
            _make_article(title="Normal market day"),
        ]
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '[{"index": 0, "score": 75}, {"index": 1, "score": 40}]'
        mock_llm.generate = AsyncMock(return_value=mock_response)

        events = await score_rss_articles(articles, mock_llm, threshold=70)
        # 1 keyword match (hack) + 1 LLM scored above 70
        assert len(events) == 2
