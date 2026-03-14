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


class TestNonCryptoFilter:
    """v0.19.0: _filter_non_crypto removes articles without crypto keywords."""

    def test_non_crypto_article_filtered(self):
        articles = [
            {
                "title": "Apple releases new iPhone model",
                "url": "https://tech.com/1",
                "source_name": "TechNews",
                "summary": "The new phone has better camera",
            },
        ]
        result = clean_articles(articles)
        filtered = [a for a in result.articles if a.get("filtered")]
        assert len(filtered) == 1

    def test_crypto_article_passes(self):
        articles = [
            {
                "title": "Bitcoin ETF sees record inflows",
                "url": "https://crypto.com/1",
                "source_name": "CryptoNews",
                "summary": "BTC ETF trading volume surges",
            },
        ]
        result = clean_articles(articles)
        filtered = [a for a in result.articles if a.get("filtered")]
        assert len(filtered) == 0

    def test_crypto_source_bypass_check(self):
        """Known crypto sources bypass the keyword check."""
        articles = [
            {
                "title": "New regulations announced today",
                "url": "https://coin68.com/1",
                "source_name": "Coin68",
                "summary": "Government updates policy framework",
            },
        ]
        result = clean_articles(articles)
        filtered = [a for a in result.articles if a.get("filtered")]
        assert len(filtered) == 0

    def test_macro_terms_pass_filter(self):
        """Macro/finance terms like SEC, ETF, Fed should pass crypto filter."""
        articles = [
            {
                "title": "SEC approves new ETF filing",
                "url": "https://news.com/1",
                "source_name": "Reuters",
                "summary": "The SEC has approved a new filing",
            },
        ]
        result = clean_articles(articles)
        filtered = [a for a in result.articles if a.get("filtered")]
        assert len(filtered) == 0

    def test_short_keyword_no_false_positive(self):
        """Short keywords like 'sol' should not match inside 'solution'."""
        articles = [
            {
                "title": "New solution for cloud computing",
                "url": "https://tech.com/1",
                "source_name": "TechNews",
                "summary": "A method to solve ethical problems",
            },
        ]
        result = clean_articles(articles)
        filtered = [a for a in result.articles if a.get("filtered")]
        assert len(filtered) == 1  # should be filtered (no crypto relevance)

    def test_short_keyword_matches_standalone(self):
        """Short keywords like 'ETH' should match as standalone words."""
        articles = [
            {
                "title": "ETH price surges today",
                "url": "https://crypto.com/1",
                "source_name": "CryptoNews",
                "summary": "ETH reaches new highs",
            },
        ]
        result = clean_articles(articles)
        filtered = [a for a in result.articles if a.get("filtered")]
        assert len(filtered) == 0
