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
        # Sentence containing violation is removed entirely (not replaced with placeholder)

    def test_detects_multiple_violations(self):
        # Put violations on separate lines so both are independently detected
        content = "Nên mua BTC ngay.\nKhuyến nghị bán ETH." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 2
        assert "nên mua" not in result.content.lower()
        assert "khuyến nghị" not in result.content.lower()

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

    def test_reports_disclaimer_missing(self):
        content = "Clean content without disclaimer."
        result = check_and_fix(content)
        # Filter no longer auto-appends disclaimer (caller responsibility)
        assert not result.disclaimer_present

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
        # Sentence containing violation is removed entirely
        assert "50% BTC" not in result.content

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


class TestSemanticNQ05Patterns:
    """Tests for semantic NQ05 violation detection (Phase 1)."""

    def test_removes_vung_tich_luy(self):
        content = "Đây là vùng tích lũy trước đợt tăng mới." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "vùng tích lũy" not in result.content

    def test_removes_co_hoi_tot(self):
        content = "Đây là cơ hội tốt để tích lũy BTC." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "cơ hội tốt" not in result.content

    def test_removes_smart_money(self):
        content = "Smart money đang mua vào mạnh mẽ." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "smart money" not in result.content.lower()

    def test_removes_thoi_diem_tot(self):
        content = "Đây là thời điểm tốt để mua vào." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "thời điểm tốt" not in result.content

    def test_removes_nen_can_nhac(self):
        content = "Nhà đầu tư nên cân nhắc mua BTC." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "nên cân nhắc" not in result.content

    def test_clean_content_not_flagged_by_semantic(self):
        content = "BTC giảm 2% trong bối cảnh thị trường biến động." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found == 0


class TestPhase5PhraseRemoval:
    """Phase 5 E5: NQ05 removes phrase, not entire sentence."""

    def test_remove_phrase_keep_sentence(self):
        """Violation phrase removed, rest of sentence preserved."""
        content = "BTC tăng 15% và nên mua vào ngay." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        # "nên mua" removed, but "BTC tăng 15%" should remain
        assert "nên mua" not in result.content
        assert "BTC tăng 15%" in result.content

    def test_remove_bullet_entirely(self):
        """Bullet point with violation → entire bullet removed."""
        content = "Tin tức:\n- Nên mua BTC ngay\n- ETH tăng 5%." + DISCLAIMER
        result = check_and_fix(content)
        assert "Nên mua" not in result.content
        assert "ETH tăng 5%" in result.content


class TestFillerDetection:
    """Phase 1 E1: Filler phrase detection (count only, do NOT remove)."""

    def test_filler_detection_single(self):
        """Single filler phrase → filler_count=1, content unchanged."""
        content = "BTC tăng 5% có thể ảnh hưởng đến thị trường." + DISCLAIMER
        result = check_and_fix(content)
        assert result.filler_count == 1
        # Filler NOT removed — content preserved
        assert "có thể ảnh hưởng đến" in result.content

    def test_filler_detection_multiple(self):
        """Multiple filler phrases → filler_count=3."""
        content = (
            "BTC tăng 5% có thể ảnh hưởng đến thị trường.\n"
            "Điều này cho thấy xu hướng tích cực.\n"
            "Tuy nhiên cần lưu ý rủi ro vĩ mô." + DISCLAIMER
        )
        result = check_and_fix(content)
        assert result.filler_count == 3
        # All fillers still present in content
        assert "có thể ảnh hưởng đến" in result.content
        assert "Điều này cho thấy" in result.content
        assert "cần lưu ý" in result.content

    def test_filler_detection_no_filler(self):
        """Clean content → filler_count=0."""
        content = "BTC tăng 5% lên $75,000 với volume $2.1B." + DISCLAIMER
        result = check_and_fix(content)
        assert result.filler_count == 0

    def test_filler_flagged_for_review(self):
        """Filler phrases show up in flagged_for_review."""
        content = "Cần theo dõi thêm diễn biến thị trường." + DISCLAIMER
        result = check_and_fix(content)
        assert result.filler_count >= 1
        assert any("Filler detected" in f for f in result.flagged_for_review)


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
