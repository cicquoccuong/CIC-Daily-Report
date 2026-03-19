"""Tests for pipeline data flow — filtered news exclusion (Wave C)."""

from __future__ import annotations

from dataclasses import dataclass


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


@dataclass
class _MockArticle:
    tier: str
    content: str


class TestCrossTierRepetition:
    """Phase 5 C3: Cross-tier repetition detection."""

    def test_repetition_detected(self):
        """3 articles with same phrase → detected."""
        from cic_daily_report.daily_pipeline import _check_cross_tier_repetition

        common = "thị trường đang trong trạng thái phục hồi sau đợt giảm mạnh"
        articles = [
            _MockArticle("L1", f"BTC tăng 5%. {common}. Giá ổn định."),
            _MockArticle("L3", f"Macro yếu. {common}. Funding Rate trung tính."),
            _MockArticle("L5", f"Kịch bản base. {common}. Bullish nếu DXY giảm."),
        ]
        result = _check_cross_tier_repetition(articles)
        assert result["repeated_count"] > 0

    def test_no_repetition_clean(self):
        """3 articles with different content → no repetition."""
        from cic_daily_report.daily_pipeline import _check_cross_tier_repetition

        articles = [
            _MockArticle("L1", "BTC tăng 5% lên 75000 với volume cao. ETH giảm nhẹ."),
            _MockArticle("L3", "Funding Rate +0.004% gần trung tính. DXY giảm về 99.8."),
            _MockArticle("L5", "Base case Recovery. Bullish nếu Fed dovish. Bear nếu hawkish."),
        ]
        result = _check_cross_tier_repetition(articles)
        assert result["repeated_count"] == 0
