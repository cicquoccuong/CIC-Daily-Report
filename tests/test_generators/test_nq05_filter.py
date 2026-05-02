"""Tests for generators/nq05_filter.py."""

from cic_daily_report.generators.article_generator import DISCLAIMER
from cic_daily_report.generators.nq05_filter import (
    DEFAULT_BANNED_KEYWORDS,
    batch_filter,
    check_and_fix,
    merge_blacklist,
)
from cic_daily_report.storage.sentinel_reader import NQ05Term


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
    """v0.33.0: ALL filler phrases are WARN-only (no removal).

    v0.32.0 removed top 3 at sentence level, but this was too aggressive —
    caused empty digest bodies. Now all 7 patterns are warn-only.
    REMOVE_FILLER_PATTERNS is empty.
    """

    def test_former_top3_now_warned_not_removed(self):
        """v0.33.0: Former top-3 fillers are now WARNED, not removed."""
        content = "BTC tăng 5% có thể ảnh hưởng đến thị trường." + DISCLAIMER
        result = check_and_fix(content)
        # v0.33.0: Content is KEPT (warn-only), not removed
        assert "có thể ảnh hưởng đến" in result.content
        assert result.filler_count >= 1

    def test_dieu_nay_cho_thay_warned(self):
        """v0.33.0: 'điều này cho thấy' warned, not removed."""
        content = "Điều này cho thấy xu hướng tích cực.\nBTC giá $75,000." + DISCLAIMER
        result = check_and_fix(content)
        # v0.33.0: Content is KEPT (warn-only)
        assert "Điều này cho thấy" in result.content
        assert "BTC giá $75,000" in result.content
        assert result.filler_count >= 1

    def test_trong_boi_canh_warned(self):
        """v0.33.0: 'trong bối cảnh' warned, not removed."""
        content = "BTC giảm trong bối cảnh thị trường biến động.\nETH tăng 3%." + DISCLAIMER
        result = check_and_fix(content)
        # v0.33.0: Content is KEPT (warn-only)
        assert "trong bối cảnh" in result.content
        assert "ETH tăng 3%" in result.content
        assert result.filler_count >= 1

    def test_remaining_fillers_still_warned_only(self):
        """Non-former-top-3 fillers are still WARN-only (kept in content)."""
        content = "Cần theo dõi thêm diễn biến thị trường." + DISCLAIMER
        result = check_and_fix(content)
        assert result.filler_count >= 1
        assert "Cần theo dõi thêm" in result.content

    def test_all_fillers_warned_not_removed(self):
        """v0.33.0: All fillers warned, content fully preserved."""
        content = (
            "BTC tăng 5% có thể ảnh hưởng đến thị trường.\n"
            "Điều này cho thấy xu hướng tích cực.\n"
            "Tuy nhiên cần lưu ý rủi ro vĩ mô." + DISCLAIMER
        )
        result = check_and_fix(content)
        # All fillers kept (warn-only)
        assert "có thể ảnh hưởng đến" in result.content
        assert "Điều này cho thấy" in result.content
        assert "cần lưu ý" in result.content
        assert result.filler_count >= 3

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

    def test_remove_filler_patterns_is_empty(self):
        """v0.33.0: REMOVE_FILLER_PATTERNS must be empty list."""
        from cic_daily_report.generators.nq05_filter import REMOVE_FILLER_PATTERNS

        assert REMOVE_FILLER_PATTERNS == []


class TestMergeBlacklist:
    """P1.14: Merge Sentinel NQ05 blacklist with hardcoded DEFAULT_BANNED_KEYWORDS."""

    def _make_term(self, term: str, severity: str = "BLOCK", language: str = "VI") -> NQ05Term:
        return NQ05Term(
            term=term,
            language=language,
            category="test",
            severity=severity,
            safe_alternative="",
            source_system="sentinel",
        )

    def test_empty_sentinel_returns_defaults_only(self):
        result = merge_blacklist([])
        assert result == DEFAULT_BANNED_KEYWORDS

    def test_adds_new_sentinel_terms(self):
        terms = [self._make_term("pump signal"), self._make_term("guaranteed profit")]
        result = merge_blacklist(terms)
        assert "pump signal" in result
        # "guaranteed profit" is new (hardcoded has "guaranteed" but not "guaranteed profit")
        assert "guaranteed profit" in result
        assert len(result) > len(DEFAULT_BANNED_KEYWORDS)

    def test_deduplicates_case_insensitive(self):
        """Sentinel term matching a hardcoded keyword (case-insensitive) is not duplicated."""
        terms = [self._make_term("Nên mua")]  # Already in DEFAULT_BANNED_KEYWORDS
        result = merge_blacklist(terms)
        count = sum(1 for kw in result if kw.lower() == "nên mua")
        assert count == 1

    def test_warn_terms_excluded(self):
        """WARN severity terms are skipped (not added to block list)."""
        terms = [
            self._make_term("caution phrase", severity="WARN"),
            self._make_term("blocked phrase", severity="BLOCK"),
        ]
        result = merge_blacklist(terms)
        assert "caution phrase" not in result
        assert "blocked phrase" in result

    def test_empty_terms_skipped(self):
        terms = [self._make_term(""), self._make_term("  "), self._make_term("valid term")]
        result = merge_blacklist(terms)
        assert "valid term" in result
        # Empty/whitespace should not be added
        assert "" not in result

    def test_merged_list_works_with_check_and_fix(self):
        """End-to-end: merged list catches Sentinel-added term."""
        terms = [self._make_term("pump tín hiệu")]
        merged = merge_blacklist(terms)
        # Extract sentinel-only extras
        extras = merged[len(DEFAULT_BANNED_KEYWORDS) :]
        content = "Đây là pump tín hiệu rõ ràng." + DISCLAIMER
        result = check_and_fix(content, extra_banned_keywords=extras)
        assert result.violations_found >= 1
        assert "pump tín hiệu" not in result.content


class TestQO24NQ05PatternExpansion:
    """QO.24: Expanded VN-specific buy/sell recommendation patterns."""

    def test_gia_tang_ty_trong(self):
        """'gia tang ty trong' (increase allocation) → NQ05 violation."""
        content = "Nhà đầu tư nên gia tăng tỷ trọng BTC." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "tăng tỷ trọng" not in result.content

    def test_vung_mua_ly_tuong(self):
        """'vung mua ly tuong' (ideal buy zone) → NQ05 violation."""
        content = "Đây là vùng mua lý tưởng cho BTC." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "vùng mua lý tưởng" not in result.content

    def test_nen_mua_vao(self):
        """'nen mua vao' (should buy in) → NQ05 violation."""
        content = "Nhà đầu tư nên mua vào ở mức giá này." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "nên mua vào" not in result.content

    def test_nen_ban_ra(self):
        """'nen ban ra' (should sell) → NQ05 violation."""
        content = "Nhà đầu tư nên bán ra để chốt lời." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "nên bán ra" not in result.content

    def test_co_hoi_tot_de(self):
        """'co hoi tot de' (good opportunity to) → NQ05 violation."""
        content = "Đây là cơ hội tốt để mua thêm ETH." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "cơ hội tốt để" not in result.content

    def test_thoi_diem_thich_hop_mua(self):
        """'thoi diem thich hop' (appropriate time to buy) → NQ05 violation."""
        content = "Đây là thời điểm thích hợp để mua BTC." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "thời điểm thích hợp" not in result.content

    def test_thoi_diem_thich_hop_tich_luy(self):
        """'thoi diem thich hop de tich luy' → NQ05 violation."""
        content = "Thời điểm thích hợp tích lũy altcoin." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "thời điểm thích hợp" not in result.content

    def test_nen_tich_luy(self):
        """'nen tich luy' (should accumulate) → NQ05 violation."""
        content = "Nhà đầu tư nên tích lũy BTC dần dần." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "nên tích lũy" not in result.content

    def test_hay_tich_luy(self):
        """'hay tich luy' (let's accumulate) → NQ05 violation."""
        content = "Hãy tích lũy thêm ETH trong giai đoạn này." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "Hãy tích lũy" not in result.content

    def test_nen_chot_loi(self):
        """'nen chot loi' (should take profit) → NQ05 violation."""
        content = "Nhà đầu tư nên chốt lời khi BTC đạt $100K." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "nên chốt lời" not in result.content

    def test_hay_chot_loi(self):
        """'hay chot loi' (let's take profit) → NQ05 violation."""
        content = "Hãy chốt lời một phần danh mục." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "Hãy chốt lời" not in result.content

    def test_vung_gia_tot_de_mua(self):
        """'vung gia tot de mua' (good price zone to buy) → NQ05 violation."""
        content = "Đây là vùng giá tốt để mua BTC." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "vùng giá tốt" not in result.content

    def test_vung_gia_tot_de_tich_luy(self):
        """'vung gia tot de tich luy' → NQ05 violation."""
        content = "BTC đang ở vùng giá tốt để tích lũy." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "vùng giá tốt" not in result.content

    def test_khong_nen_bo_lo(self):
        """'khong nen bo lo' (don't miss out — FOMO) → NQ05 violation."""
        content = "Cơ hội này không nên bỏ lỡ." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "không nên bỏ lỡ" not in result.content

    def test_mua_manh(self):
        """'mua manh' (strong buy) → NQ05 violation."""
        content = "Các cá voi đang mua mạnh BTC." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "mua mạnh" not in result.content

    def test_ban_manh(self):
        """'ban manh' (strong sell) → NQ05 violation."""
        content = "Nhà đầu tư bán mạnh ETH hôm nay." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "bán mạnh" not in result.content

    def test_khuyen_nghi_mua(self):
        """'khuyen nghi mua' (recommend buy) → NQ05 violation."""
        content = "Chúng tôi khuyến nghị mua BTC." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "khuyến nghị mua" not in result.content

    def test_khuyen_nghi_ban(self):
        """'khuyen nghi ban' (recommend sell) → NQ05 violation."""
        content = "Phân tích khuyến nghị bán ETH." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "khuyến nghị bán" not in result.content

    def test_clean_content_not_falsely_flagged(self):
        """Regular market analysis should not be flagged by QO.24 patterns."""
        content = (
            "BTC tăng 5% lên $75,000. Khối lượng giao dịch tăng 20%. "
            "Chỉ số Fear & Greed ở mức 45 (Trung lập)." + DISCLAIMER
        )
        result = check_and_fix(content)
        assert result.violations_found == 0


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


class TestWave086SemanticPatterns:
    """Wave 0.8.6 (alpha.33) — 4 new direct-address NQ05 patterns from
    Daily 11:59 SA 01/05 audit. LLM softens advice with 2nd-person pronouns
    (bạn/anh/chị) — still recommendation, still NQ05 violation.
    """

    def test_pattern_tich_luy_nhu_ban(self):
        # "tích lũy dài hạn như bạn"
        content = "Đây là cơ hội tích lũy dài hạn như bạn nhà đầu tư." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "tích lũy dài hạn như bạn" not in result.content.lower()

    def test_pattern_ban_co_the_mua(self):
        # "bạn có thể mua được tài sản"
        content = "Bạn có thể mua được tài sản BTC tại đây." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "bạn có thể mua được tài sản" not in result.content.lower()

    def test_pattern_luc_ban_co_the_mua(self):
        # "lúc bạn có thể mua được"
        content = "Đây chính là lúc bạn có thể mua được giá tốt." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "lúc bạn có thể mua" not in result.content.lower()

    def test_pattern_gia_tot_de_mua(self):
        # Wave 0.8.6.1 (alpha.34) Fix #4: pattern 4 narrowed — "hơn" branch
        # removed (false positive on legit market commentary). Only "để mua"
        # / "cho việc mua" still trigger.
        content = "Đây là giá tốt để mua vào." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "giá tốt để mua" not in result.content.lower()

    def test_pattern_gia_hap_dan_cho_viec_mua(self):
        # Wave 0.8.6.1 Fix #4 — "cho việc mua" branch still fires
        content = "Giá hấp dẫn cho việc mua vào BTC." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "giá hấp dẫn cho việc mua" not in result.content.lower()

    def test_clean_text_not_falsely_flagged(self):
        # Negative control — none of the 4 new patterns should fire here
        content = "Bitcoin tăng giá mạnh trong phiên hôm nay theo CoinDesk." + DISCLAIMER
        result = check_and_fix(content)
        # may have 0 or some unrelated violations, but specifically no removal
        # of this clean sentence
        assert "Bitcoin tăng giá mạnh" in result.content


class TestWave0861PatchPatterns:
    """Wave 0.8.6.1 (alpha.34) — patches from cross-check Wave 0.8.6+0.8.7.
    Fix #4: pattern 4 drops "hơn" branch (false positive).
    Fix #5: patterns 1-3 expand pronouns to chúng ta / mọi người / nhà đầu tư / ai.
    """

    def test_fix4_gia_tot_hon_legit_market_commentary_passes(self):
        # Fix #4 — legit price comparison must NOT block
        content = "Giá BTC tốt hơn so với cuối tháng trước." + DISCLAIMER
        result = check_and_fix(content)
        # Sentence preserved (the new pattern 4 only catches "để mua" / "cho việc mua")
        assert "tốt hơn so với cuối tháng" in result.content.lower()

    def test_fix5_pattern1_chung_ta(self):
        # Pattern 1 expanded: "tích lũy như chúng ta"
        content = "Đây là cơ hội tích lũy dài hạn như chúng ta thường nói." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "tích lũy dài hạn như chúng ta" not in result.content.lower()

    def test_fix5_pattern1_moi_nguoi(self):
        # Pattern 1 expanded: "gom như mọi người"
        content = "Hãy gom như mọi người đang làm." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "gom" not in result.content.lower() or "như mọi người" not in result.content.lower()

    def test_fix5_pattern2_nha_dau_tu_co_the_mua(self):
        # Pattern 2 expanded: "nhà đầu tư có thể mua tài sản"
        content = "Nhà đầu tư có thể mua được tài sản này tại sàn." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "nhà đầu tư có thể mua được tài sản" not in result.content.lower()

    def test_fix5_pattern2_chung_ta_nen_mua(self):
        # Pattern 2 expanded: "chúng ta nên mua coin"
        content = "Chúng ta nên mua coin này ngay hôm nay." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "chúng ta nên mua coin" not in result.content.lower()

    def test_fix5_pattern3_luc_nha_dau_tu_co_the_mua(self):
        # Pattern 3 expanded: "lúc nhà đầu tư có thể mua"
        content = "Đây chính là lúc nhà đầu tư có thể mua giá tốt." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "lúc nhà đầu tư có thể mua" not in result.content.lower()

    def test_fix5_pattern3_luc_moi_nguoi_nen_mua(self):
        # Pattern 3 expanded: "lúc mọi người nên mua"
        content = "Đây là lúc mọi người nên mua vào." + DISCLAIMER
        result = check_and_fix(content)
        assert result.violations_found >= 1
        assert "lúc mọi người nên mua" not in result.content.lower()
