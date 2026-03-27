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


class TestExpandedNQ05Patterns:
    """v0.32.0: Broadened NQ05 semantic patterns (Fix 3.4-3.5)."""

    def test_co_the_can_nhac_mua(self):
        """'có thể cân nhắc mua' → NQ05 violation (new trigger word)."""
        content = "Nhà đầu tư có thể cân nhắc mua BTC." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "có thể cân nhắc" not in result.content

    def test_can_xem_xet_tich_luy(self):
        """'cần xem xét tích lũy' → NQ05 violation (new trigger word)."""
        content = "Nhà đầu tư cần xem xét tích lũy SOL." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "cần xem xét" not in result.content

    def test_neu_can_nhac_ban(self):
        """'nếu cân nhắc bán' → NQ05 violation (new trigger word)."""
        content = "Nếu cân nhắc bán BTC nên chờ thêm." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "nếu cân nhắc" not in result.content

    def test_xem_xet_viec_tich_luy(self):
        """'xem xét việc tích lũy' → NQ05 violation (new standalone pattern)."""
        content = "Có thể xem xét việc tích lũy BTC ở vùng giá hiện tại." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "xem xét việc tích lũy" not in result.content

    def test_xem_xet_mua_vao(self):
        """'xem xét mua vào' → NQ05 violation (new standalone pattern)."""
        content = "Nên xem xét mua vào khi giá giảm." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "xem xét mua vào" not in result.content

    def test_xem_xet_mua_them(self):
        """'xem xét mua thêm' → NQ05 violation (new standalone pattern)."""
        content = "Nhà đầu tư xem xét mua thêm ETH." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "xem xét mua thêm" not in result.content


class TestSentenceLevelRemoval:
    """v0.29.1: NQ05 removes entire SENTENCE containing violation (not just phrase).

    Phrase-only removal (pre-v0.29.1) destroyed sentence structure by leaving
    subject/object without verbs. Sentence-level removal keeps grammar intact.
    """

    def test_single_sentence_with_violation_removed_entirely(self):
        """One sentence containing violation → entire sentence removed."""
        content = "BTC tăng 15% và nên mua vào ngay." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "nên mua" not in result.content
        # Entire sentence removed (not just phrase) — prevents broken grammar
        assert "BTC tăng 15%" not in result.content

    def test_multi_sentence_keeps_clean_sentence(self):
        """Two sentences on same line — only violating sentence removed."""
        content = "BTC tăng 15% lên $75,000. Nhà đầu tư nên cân nhắc mua vào." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "nên cân nhắc" not in result.content
        # Clean sentence preserved
        assert "BTC tăng 15%" in result.content

    def test_remove_bullet_entirely(self):
        """Bullet point with violation → entire bullet removed."""
        content = "Tin tức:\n- Nên mua BTC ngay\n- ETH tăng 5%." + DISCLAIMER
        result = check_and_fix(content)
        assert "Nên mua" not in result.content
        assert "ETH tăng 5%" in result.content

    def test_all_sentences_violating_removes_line(self):
        """All sentences on a line have violations → entire line removed."""
        content = "Nên mua BTC ngay. Cơ hội tốt để tích lũy SOL." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 2
        assert "BTC" not in result.content.split("---")[0]  # Before disclaimer


class TestFillerRemoval:
    """v0.32.0: Top 3 filler phrases are REMOVED at sentence level.

    "điều này cho thấy", "có thể ảnh hưởng đến", "trong bối cảnh"
    are removed because they appear most frequently and add zero information.
    Remaining fillers stay WARN-only.
    """

    def test_top3_filler_removed(self):
        """Top 3 fillers removed: 'có thể ảnh hưởng đến'."""
        content = "BTC tăng 5% có thể ảnh hưởng đến thị trường." + DISCLAIMER
        result = check_and_fix(content)
        assert "có thể ảnh hưởng đến" not in result.content
        assert result.auto_fixed >= 1

    def test_dieu_nay_cho_thay_removed(self):
        """Top 3 fillers removed: 'điều này cho thấy'."""
        content = "Điều này cho thấy xu hướng tích cực.\nBTC giá $75,000." + DISCLAIMER
        result = check_and_fix(content)
        assert "Điều này cho thấy" not in result.content
        assert "BTC giá $75,000" in result.content

    def test_trong_boi_canh_removed(self):
        """Top 3 fillers removed: 'trong bối cảnh'."""
        content = "BTC giảm trong bối cảnh thị trường biến động.\nETH tăng 3%." + DISCLAIMER
        result = check_and_fix(content)
        assert "trong bối cảnh" not in result.content
        assert "ETH tăng 3%" in result.content

    def test_remaining_fillers_still_warned_only(self):
        """Non-top-3 fillers are still WARN-only (kept in content)."""
        content = "Cần theo dõi thêm diễn biến thị trường." + DISCLAIMER
        result = check_and_fix(content)
        assert result.filler_count >= 1
        assert "Cần theo dõi thêm" in result.content

    def test_mixed_remove_and_warn(self):
        """Top 3 removed, others warned only."""
        content = (
            "BTC tăng 5% có thể ảnh hưởng đến thị trường.\n"
            "Điều này cho thấy xu hướng tích cực.\n"
            "Tuy nhiên cần lưu ý rủi ro vĩ mô." + DISCLAIMER
        )
        result = check_and_fix(content)
        # Top 3 removed
        assert "có thể ảnh hưởng đến" not in result.content
        assert "Điều này cho thấy" not in result.content
        # Remaining filler kept (warn-only)
        assert "cần lưu ý" in result.content
        assert result.filler_count >= 1

    def test_filler_detection_no_filler(self):
        """Clean content → filler_count=0."""
        content = "BTC tăng 5% lên $75,000 với volume $2.1B." + DISCLAIMER
        result = check_and_fix(content)
        assert result.filler_count == 0

    def test_filler_not_in_flagged_for_review(self):
        """Warn-only fillers → NOT in flagged_for_review."""
        content = "Cần theo dõi thêm diễn biến thị trường." + DISCLAIMER
        result = check_and_fix(content)
        assert result.filler_count >= 1
        assert not any("Filler" in f for f in result.flagged_for_review)


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
