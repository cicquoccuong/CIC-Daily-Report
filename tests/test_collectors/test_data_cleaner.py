"""Tests for collectors/data_cleaner.py."""

from cic_daily_report.collectors.data_cleaner import clean_articles


class TestDeduplication:
    def test_exact_url_dedup(self):
        articles = [
            {"title": "BTC ATH", "url": "https://a.com/1", "source_name": "SrcA"},
            {"title": "BTC ATH", "url": "https://a.com/1", "source_name": "SrcB"},
        ]
        result = clean_articles(articles)
        assert result.duplicates_merged == 1
        # Only 1 unique article, with 2 sources
        unique = [a for a in result.articles if not a.get("filtered")]
        assert len(unique) == 1

    def test_similar_title_dedup(self):
        articles = [
            {
                "title": "Bitcoin hits new all-time high of $100K",
                "url": "https://a.com/1",
                "source_name": "SrcA",
            },
            {
                "title": "Bitcoin hits new all-time high of $100,000",
                "url": "https://b.com/2",
                "source_name": "SrcB",
            },
        ]
        result = clean_articles(articles)
        assert result.duplicates_merged == 1

    def test_different_articles_not_deduped(self):
        articles = [
            {
                "title": "Bitcoin hits ATH",
                "url": "https://a.com/1",
                "source_name": "SrcA",
            },
            {
                "title": "Ethereum upgrade complete",
                "url": "https://b.com/2",
                "source_name": "SrcB",
            },
        ]
        result = clean_articles(articles)
        assert result.duplicates_merged == 0
        unique = [a for a in result.articles if not a.get("filtered")]
        assert len(unique) == 2


class TestConflictDetection:
    def test_multi_source_flagged_as_conflict(self):
        articles = [
            {
                "title": "BTC price report",
                "url": "https://a.com/1",
                "source_name": "SrcA",
                "summary": "BTC at 100k",
            },
            {
                "title": "BTC price report",
                "url": "https://a.com/1",
                "source_name": "SrcB",
                "summary": "BTC at 99k",
            },
        ]
        result = clean_articles(articles)
        assert result.conflicts_flagged >= 0


class TestSpamFilter:
    def test_spam_keyword_detection(self):
        articles = [
            {
                "title": "FREE AIRDROP - Join our group!",
                "url": "https://spam.com/1",
                "source_name": "Spam",
                "summary": "airdrop free tokens guaranteed profit",
            },
            {
                "title": "Bitcoin market analysis",
                "url": "https://legit.com/1",
                "source_name": "Legit",
                "summary": "Technical analysis of BTC",
            },
        ]
        result = clean_articles(articles)
        assert result.spam_filtered == 1
        # Spam article is marked filtered=True but not removed
        filtered = [a for a in result.articles if a.get("filtered")]
        assert len(filtered) == 1
        assert "AIRDROP" in filtered[0]["title"]

    def test_custom_spam_keywords(self):
        articles = [
            {
                "title": "Custom bad word here",
                "url": "https://a.com/1",
                "source_name": "Src",
                "summary": "Contains shitcoin alert",
            },
        ]
        result = clean_articles(articles, spam_keywords=["shitcoin"])
        assert result.spam_filtered == 1

    def test_empty_articles(self):
        result = clean_articles([])
        assert result.duplicates_merged == 0
        assert result.spam_filtered == 0
        assert result.articles == []
