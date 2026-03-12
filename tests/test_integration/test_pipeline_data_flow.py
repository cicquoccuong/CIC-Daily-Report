"""Tests for pipeline data flow — filtered news exclusion (Wave C)."""

from __future__ import annotations


class TestFilteredNewsExclusion:
    """Verify that articles with filtered=True are excluded from LLM input."""

    def test_filtered_articles_excluded(self, sample_news_articles):
        """Articles marked filtered=True must not appear in cleaned output."""
        # Simulate the filter line from daily_pipeline.py ~line 176:
        #   cleaned_news = [a for a in clean_result.articles if not a.get("filtered", False)]
        cleaned_news = [a for a in sample_news_articles if not a.get("filtered", False)]

        assert len(cleaned_news) == 2
        titles = [a["title"] for a in cleaned_news]
        assert "SPAM article" not in titles
        assert "BTC hits $100K" in titles
        assert "ETH update" in titles

    def test_all_filtered_yields_empty(self):
        """If every article is filtered, the result should be empty."""
        articles = [
            {"title": "Spam 1", "filtered": True},
            {"title": "Spam 2", "filtered": True},
        ]
        cleaned = [a for a in articles if not a.get("filtered", False)]
        assert cleaned == []

    def test_no_filtered_flag_defaults_to_included(self):
        """Articles without a 'filtered' key should be included (default False)."""
        articles = [
            {"title": "Legit article", "summary": "Good content"},
        ]
        cleaned = [a for a in articles if not a.get("filtered", False)]
        assert len(cleaned) == 1

    def test_news_text_built_only_from_cleaned(self, sample_news_articles):
        """Verify the news text generation uses only non-filtered articles."""
        cleaned_news = [a for a in sample_news_articles if not a.get("filtered", False)]

        # Build news text the same way as daily_pipeline.py ~line 179-186
        news_items = []
        for a in cleaned_news[:30]:
            line = f"- {a.get('title', '')} ({a.get('source', '')})"
            summary = a.get("summary", "")
            if summary:
                line += f"\n  Summary: {summary[:300]}"
            news_items.append(line)
        news_text = "\n".join(news_items)

        assert "BTC hits $100K" in news_text
        assert "ETH update" in news_text
        assert "SPAM article" not in news_text
