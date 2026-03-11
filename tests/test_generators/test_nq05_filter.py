"""Tests for generators/nq05_filter.py."""

from cic_daily_report.generators.article_generator import DISCLAIMER
from cic_daily_report.generators.nq05_filter import (
    batch_filter,
    check_and_fix,
)


class TestCheckAndFix:
    def test_clean_content_passes(self):
        content = "BTC tăng 2% hôm nay." + DISCLAIMER
        result = check_and_fix(content)
        assert result.passed
        assert result.violations_found == 0
        assert result.status == "pass"

    def test_detects_banned_keyword(self):
        content = "Bạn nên mua BTC ngay hôm nay." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "nên mua" not in result.content
        assert "[đã biên tập]" in result.content

    def test_detects_multiple_violations(self):
        content = "Nên mua BTC, khuyến nghị bán ETH." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 2

    def test_case_insensitive(self):
        content = "GUARANTEED profit!" + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "GUARANTEED" not in result.content

    def test_fixes_terminology(self):
        content = "Tiền điện tử BTC rất phổ biến." + DISCLAIMER
        result = check_and_fix(content)
        assert "tài sản mã hóa" in result.content
        assert "Tiền điện tử" not in result.content

    def test_fixes_multiple_terminology(self):
        content = "Tiền ảo và tiền điện tử khác nhau." + DISCLAIMER
        result = check_and_fix(content)
        # Both should be replaced
        assert "tiền ảo" not in result.content.lower()
        assert "tiền điện tử" not in result.content.lower()
        assert result.content.count("tài sản mã hóa") >= 2

    def test_appends_disclaimer_if_missing(self):
        content = "Clean content without disclaimer."
        result = check_and_fix(content)
        assert result.disclaimer_present
        assert "Tuyên bố miễn trừ trách nhiệm" in result.content

    def test_keeps_existing_disclaimer(self):
        content = "Content here." + DISCLAIMER
        result = check_and_fix(content)
        assert result.disclaimer_present
        # Should not duplicate disclaimer
        assert result.content.count("Tuyên bố miễn trừ trách nhiệm") == 1

    def test_extra_banned_keywords(self):
        content = "Coin này sẽ moon chắc luôn." + DISCLAIMER
        result = check_and_fix(content, extra_banned_keywords=["moon chắc luôn"])
        assert result.violations_found >= 1
        assert "moon chắc luôn" not in result.content

    def test_status_pass_after_autofix(self):
        content = "Nên mua BTC." + DISCLAIMER
        result = check_and_fix(content)
        # Auto-fixed → still passes
        assert result.passed
        assert result.status == "review"  # Has flagged items


class TestAllocationPatterns:
    """Tests for NQ05 allocation percentage pattern detection (Wave D)."""

    def test_detects_percentage_for_btc(self):
        content = "Phân bổ 30% cho BTC trong danh mục." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "30% cho BTC" not in result.content

    def test_detects_allocation_keyword_with_percentage(self):
        content = "Gợi ý phân bổ: 50% BTC, 30% ETH." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "[đã biên tập]" in result.content

    def test_detects_ty_trong_pattern(self):
        content = "Tỷ trọng: 40% cho SOL là hợp lý." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1

    def test_clean_percentage_not_flagged(self):
        """Generic percentage not tied to allocation should pass."""
        content = "BTC tăng 5% trong 24h qua." + DISCLAIMER
        result = check_and_fix(content)
        # Should not flag non-allocation percentages
        assert "5%" in result.content


class TestBatchFilter:
    def test_filters_multiple(self):
        contents = [
            "Clean content." + DISCLAIMER,
            "Nên mua everything." + DISCLAIMER,
        ]
        results = batch_filter(contents)
        assert len(results) == 2
        assert results[0].violations_found == 0
        assert results[1].violations_found >= 1

    def test_empty_list(self):
        assert batch_filter([]) == []
