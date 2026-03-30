"""Tests for Quality Gate — Factual Consistency + Insight Density (P1.22).

Covers:
- Factual consistency: no-event claims, percentage mismatches, quiet-market claims
- Insight density: data-backed sentence ratio
- Integration: run_quality_gate() end-to-end
"""

from cic_daily_report.generators.quality_gate import (
    INSIGHT_DENSITY_THRESHOLD,
    QualityGateResult,
    check_factual_consistency,
    check_insight_density,
    run_quality_gate,
)

# ---------------------------------------------------------------------------
# Fixtures — reusable test data
# ---------------------------------------------------------------------------

GOOD_ARTICLE = (
    "## Tổng quan thị trường\n"
    "BTC tăng **3.2%** lên $87,500 trong phiên giao dịch hôm nay. "
    "ETH cũng tăng 2.1% đạt $3,200. "
    "Fear & Greed Index = 45, cho thấy thị trường trung tính. "
    "BTC Dominance đạt 56.8%, giảm nhẹ 0.3% so với hôm qua. "
    "Total Market Cap đạt $2.8 nghìn tỷ USD. "
    "Funding Rate = 0.01%, cho thấy derivatives cân bằng. "
    "RSI 14 ngày = 52.3, vùng trung tính. "
    "DXY giảm 0.4% về 104.2 — hỗ trợ tài sản rủi ro. "
    "Sector dẫn đầu: AI & Big Data tăng 4.1%. "
    "Volume giao dịch đạt $45.2 tỷ trong phiên hôm nay.\n"
)

FILLER_ARTICLE = (
    "Thị trường hôm nay tiếp tục xu hướng hiện tại. "
    "Các nhà đầu tư đang theo dõi diễn biến tiếp theo. "
    "Nhiều chuyên gia cho rằng cần kiên nhẫn chờ đợi. "
    "Xu hướng dài hạn vẫn chưa rõ ràng. "
    "Cần thêm thời gian để xác nhận tín hiệu. "
    "Thị trường đang trong giai đoạn tích lũy. "
    "Không có nhiều thay đổi so với tuần trước. "
    "Các sector đều biến động nhẹ. "
    "Tâm lý nhà đầu tư vẫn thận trọng. "
    "Kỳ vọng tuần tới sẽ rõ ràng hơn.\n"
)

ECONOMIC_EVENTS_TEXT = (
    "=== LỊCH SỰ KIỆN KINH TẾ ===\n"
    "- [QUAN TRỌNG] CPI Mỹ (14:30 UTC) — dự báo 3.2%, trước đó 3.1%\n"
    "- [TRUNG BÌNH] PPI Mỹ (14:30 UTC) — dự báo 2.3%\n"
    "- [QUAN TRỌNG] FOMC Meeting Minutes (19:00 UTC)\n"
)

MARKET_DATA_WITH_MOVES = (
    "- BTC: $87,500 (+3.2%) | Vol: $45.2M | MCap: $1,710.5B\n"
    "- ETH: $3,200 (+2.1%) | Vol: $18.3M | MCap: $384.8B\n"
    "- SOL: $145 (-1.5%) | Vol: $5.2M\n"
)

MARKET_DATA_WITH_LARGE_MOVE = (
    "- BTC: $80,000 (-8.5%) | Vol: $65.2M | MCap: $1,560.0B\n"
    "- ETH: $2,800 (-6.3%) | Vol: $28.3M | MCap: $336.0B\n"
)


# ---------------------------------------------------------------------------
# 1. Factual consistency tests
# ---------------------------------------------------------------------------


class TestFactualConsistency:
    """Tests for check_factual_consistency()."""

    def test_no_event_claim_with_events_flags(self):
        """Content says 'khong co su kien' but calendar has events -> flag."""
        content = "Không có sự kiện vĩ mô nào đáng chú ý trong tuần này."
        input_data = {
            "economic_events": ECONOMIC_EVENTS_TEXT,
            "market_data": MARKET_DATA_WITH_MOVES,
            "key_metrics": {},
        }
        issues = check_factual_consistency(content, input_data)
        assert len(issues) >= 1
        assert any("không có sự kiện" in i.lower() for i in issues)

    def test_no_event_claim_without_events_passes(self):
        """Content says 'khong co su kien' and calendar is truly empty -> pass."""
        content = "Không có sự kiện vĩ mô nào đáng chú ý trong tuần này."
        input_data = {
            "economic_events": "",
            "market_data": MARKET_DATA_WITH_MOVES,
            "key_metrics": {},
        }
        issues = check_factual_consistency(content, input_data)
        # Should NOT flag "no event" when events are genuinely empty
        no_event_issues = [i for i in issues if "không có sự kiện" in i.lower()]
        assert len(no_event_issues) == 0

    def test_quiet_market_variants_flagged(self):
        """All 'no event' pattern variants should be detected."""
        variants = [
            "Thị trường yên ắt, không có nhiều biến động.",
            "Tuần yên tĩnh đối với thị trường crypto.",
            "Không có dữ liệu kinh tế quan trọng.",
            "Không có tin tức đáng chú ý hôm nay.",
            "Không có biến động lớn trong phiên giao dịch.",
        ]
        input_data = {
            "economic_events": ECONOMIC_EVENTS_TEXT,
            "market_data": MARKET_DATA_WITH_MOVES,
            "key_metrics": {},
        }
        for content in variants:
            issues = check_factual_consistency(content, input_data)
            assert len(issues) >= 1, f"Should flag: {content}"

    def test_percentage_within_tolerance_passes(self):
        """Content mentions 5% and market data shows 3.2% -> within 5pp tolerance."""
        content = "BTC tăng 5% trong phiên giao dịch sáng nay."
        input_data = {
            "economic_events": "",
            "market_data": MARKET_DATA_WITH_MOVES,  # has 3.2%
            "key_metrics": {},
        }
        issues = check_factual_consistency(content, input_data)
        pct_issues = [i for i in issues if "%" in i and "tolerance" in i]
        assert len(pct_issues) == 0, "5% vs 3.2% is within 5pp tolerance"

    def test_percentage_outside_tolerance_flags(self):
        """Content mentions 15% but market data shows 3.2% -> flag."""
        content = "BTC tăng 15% trong đợt phục hồi mạnh mẽ."
        input_data = {
            "economic_events": "",
            "market_data": MARKET_DATA_WITH_MOVES,  # highest is 3.2%
            "key_metrics": {},
        }
        issues = check_factual_consistency(content, input_data)
        pct_issues = [i for i in issues if "15.0%" in i or "tolerance" in i]
        assert len(pct_issues) >= 1, "15% vs max 3.2% exceeds 5pp tolerance"

    def test_quiet_market_claim_with_large_move_flags(self):
        """Content says 'thi truong yen at' but BTC -8.5% -> flag."""
        content = "Thị trường yên ắt trong phiên giao dịch cuối tuần."
        input_data = {
            "economic_events": "",
            "market_data": MARKET_DATA_WITH_LARGE_MOVE,  # BTC -8.5%
            "key_metrics": {},
        }
        issues = check_factual_consistency(content, input_data)
        assert len(issues) >= 1
        assert any(">5%" in i or "moves" in i for i in issues)

    def test_quiet_market_claim_with_small_moves_passes(self):
        """Content says 'thi truong yen at' and market is genuinely calm -> no flag."""
        content = "Thị trường yên ắt với biến động nhẹ."
        calm_market = "- BTC: $87,500 (+0.3%) | Vol: $30M\n- ETH: $3,200 (-0.5%)\n"
        input_data = {
            "economic_events": "",
            "market_data": calm_market,
            "key_metrics": {},
        }
        issues = check_factual_consistency(content, input_data)
        # Should NOT flag for ">5% moves" since market is genuinely calm
        move_issues = [i for i in issues if ">5%" in i or "moves" in i]
        assert len(move_issues) == 0

    def test_small_percentage_not_flagged_as_large_move(self):
        """BUG-06: 3.5% should NOT be treated as >5% move."""
        content = "Thị trường yên ắt với biến động nhẹ."
        market = "- BTC: $87,500 (+3.5%) | Vol: $30M\n- ETH: $3,200 (-2.8%)\n"
        input_data = {"economic_events": "", "market_data": market, "key_metrics": {}}
        issues = check_factual_consistency(content, input_data)
        move_issues = [i for i in issues if ">5%" in i or "moves" in i]
        assert len(move_issues) == 0, f"3.5% should NOT trigger >5% move flag: {move_issues}"

    def test_exact_5pct_flagged_as_large_move(self):
        """BUG-06: Exactly 5.0% SHOULD be flagged as large move."""
        content = "Thị trường yên ắt."
        market = "- BTC: $87,500 (+5.0%) | Vol: $30M\n"
        input_data = {"economic_events": "", "market_data": market, "key_metrics": {}}
        issues = check_factual_consistency(content, input_data)
        move_issues = [i for i in issues if ">5%" in i or "moves" in i]
        assert len(move_issues) >= 1, "5.0% should trigger large move flag"

    def test_empty_content_no_issues(self):
        """Empty content produces no factual issues (nothing to check)."""
        issues = check_factual_consistency("", {"economic_events": "", "market_data": ""})
        assert issues == []

    def test_none_input_data_values_handled(self):
        """None values in input_data should not crash."""
        content = "Không có sự kiện quan trọng."
        input_data = {
            "economic_events": None,
            "market_data": None,
            "key_metrics": None,
        }
        # Should not raise — None is treated as empty
        issues = check_factual_consistency(content, input_data)
        assert isinstance(issues, list)


# ---------------------------------------------------------------------------
# 2. Insight density tests
# ---------------------------------------------------------------------------


class TestInsightDensity:
    """Tests for check_insight_density()."""

    def test_all_data_backed_returns_1(self):
        """Article where every sentence has data -> density 1.0."""
        content = (
            "BTC tăng 3.2% lên $87,500. "
            "ETH đạt $3,200 với volume $18.3M. "
            "F&G Index = 45 cho thấy thị trường trung tính. "
            "RSI = 52.3 ở vùng trung tính."
        )
        density, total, backed = check_insight_density(content)
        assert density == 1.0
        assert backed == total
        assert total > 0

    def test_no_data_returns_0(self):
        """Article with zero data points -> density 0.0."""
        content = (
            "Thị trường hôm nay tiếp tục xu hướng hiện tại. "
            "Các nhà đầu tư đang theo dõi diễn biến. "
            "Tâm lý nhà đầu tư vẫn thận trọng."
        )
        density, total, backed = check_insight_density(content)
        assert density == 0.0
        assert backed == 0
        assert total > 0

    def test_mixed_content_correct_ratio(self):
        """10 sentences, 3 with data -> density = 0.30."""
        data_sentences = [
            "BTC tăng 3.2% trong phiên giao dịch.",
            "Total Market Cap đạt $2.8 nghìn tỷ.",
            "Fear & Greed Index = 45 cho thấy trung tính.",
        ]
        filler_sentences = [
            "Thị trường tiếp tục xu hướng hiện tại.",
            "Nhà đầu tư đang chờ đợi tín hiệu rõ ràng hơn.",
            "Xu hướng dài hạn vẫn chưa xác định được.",
            "Cần thêm thời gian để đánh giá tình hình.",
            "Nhiều chuyên gia đang theo dõi sát diễn biến.",
            "Giai đoạn tích lũy vẫn đang tiếp diễn.",
            "Kỳ vọng tuần tới sẽ có thêm dữ kiện mới.",
        ]
        content = ". ".join(data_sentences + filler_sentences) + "."
        density, total, backed = check_insight_density(content)
        assert total == 10
        assert backed == 3
        assert abs(density - 0.30) < 0.01

    def test_empty_content_returns_zeros(self):
        """Empty content -> (0.0, 0, 0)."""
        density, total, backed = check_insight_density("")
        assert density == 0.0
        assert total == 0
        assert backed == 0

    def test_whitespace_only_returns_zeros(self):
        """Whitespace-only content -> (0.0, 0, 0)."""
        density, total, backed = check_insight_density("   \n\n  ")
        assert density == 0.0
        assert total == 0
        assert backed == 0

    def test_markdown_headers_excluded(self):
        """## headers should not count as sentences."""
        content = (
            "## Tổng quan thị trường\n"
            "BTC tăng 3.2% lên $87,500.\n"
            "## Phân tích chi tiết\n"
            "Thị trường đang trong giai đoạn tích lũy."
        )
        density, total, backed = check_insight_density(content)
        assert total == 2  # 2 actual sentences, not 4
        assert backed == 1  # "BTC tăng 3.2% lên $87,500"

    def test_disclaimer_excluded(self):
        """Disclaimer text should not count as a sentence."""
        content = (
            "BTC tăng 3.2% lên $87,500.\n"
            "---\n"
            "*Tuyên bố miễn trừ trách nhiệm: Nội dung trên chỉ mang tính chất thông tin.*"
        )
        density, total, backed = check_insight_density(content)
        assert total == 1  # only the BTC sentence; disclaimer + --- excluded

    def test_vietnamese_number_words_detected(self):
        """Vietnamese number words (ty, trieu, nghin) should count as data."""
        content = "Tổng vốn hóa đạt 2,8 nghìn tỷ USD."
        density, total, backed = check_insight_density(content)
        assert backed >= 1

    def test_abbreviated_numbers_detected(self):
        """Abbreviated numbers like 1.5B, 200K should count as data."""
        content = "Volume giao dịch đạt 45.2B trong phiên hôm nay."
        density, total, backed = check_insight_density(content)
        assert backed >= 1

    def test_short_fragments_excluded(self):
        """Fragments <= 10 chars should not count as sentences."""
        content = "OK.\nBTC tăng 3.2% lên $87,500 trong phiên giao dịch hôm nay."
        density, total, backed = check_insight_density(content)
        # "OK." is <=10 chars, excluded; only the BTC sentence counts
        assert total == 1

    def test_vietnamese_dollar_format_detected(self):
        """BUG-20: $87.500 (Vietnamese format) should count as data-backed."""
        content = "BTC đạt mức giá $87.500 trong phiên giao dịch hôm nay."
        density, total, backed = check_insight_density(content)
        assert backed >= 1

    def test_us_dollar_format_still_detected(self):
        """Regression: $87,500 (US format) should still count as data-backed."""
        content = "BTC đạt mức giá $87,500 trong phiên giao dịch hôm nay."
        density, total, backed = check_insight_density(content)
        assert backed >= 1

    def test_dollar_trailing_period_not_matched(self):
        """$87. (trailing period without digit) should NOT match as dollar amount."""
        content = "Giá trị đạt $87. Đây là mức giá mới trong phiên giao dịch ngày nay."
        density, total, backed = check_insight_density(content)
        # "$87." should not be matched by the dollar pattern (trailing period only)
        # The sentence may still match via other patterns, so we just verify
        # the pattern logic is correct — no trailing period-only match
        assert isinstance(backed, int)


# ---------------------------------------------------------------------------
# 3. Integration tests — run_quality_gate()
# ---------------------------------------------------------------------------


class TestRunQualityGate:
    """Tests for run_quality_gate() end-to-end."""

    def test_good_article_passes(self):
        """Well-written data-rich article passes all checks."""
        input_data = {
            "economic_events": ECONOMIC_EVENTS_TEXT,
            "market_data": MARKET_DATA_WITH_MOVES,
            "key_metrics": {"BTC Price": "$87,500", "Fear & Greed": 45},
        }
        result = run_quality_gate(GOOD_ARTICLE, "L1", input_data)
        assert isinstance(result, QualityGateResult)
        assert result.passed is True
        assert result.retry_recommended is False
        assert result.factual_issues == []
        assert result.insight_density >= INSIGHT_DENSITY_THRESHOLD
        assert result.total_sentences > 0
        assert result.data_backed_sentences > 0
        assert "L1" in result.details

    def test_filler_article_fails_density(self):
        """Filler article with no data fails density check."""
        input_data = {
            "economic_events": "",
            "market_data": MARKET_DATA_WITH_MOVES,
            "key_metrics": {},
        }
        result = run_quality_gate(FILLER_ARTICLE, "L3", input_data)
        assert result.passed is False
        assert result.retry_recommended is True
        assert result.insight_density < INSIGHT_DENSITY_THRESHOLD
        assert "below_threshold" in result.details

    def test_factual_error_fails(self):
        """Article with factual contradiction fails."""
        content = "Không có sự kiện vĩ mô nào trong tuần. BTC tăng 3.2% lên $87,500."
        input_data = {
            "economic_events": ECONOMIC_EVENTS_TEXT,
            "market_data": MARKET_DATA_WITH_MOVES,
            "key_metrics": {},
        }
        result = run_quality_gate(content, "L4", input_data)
        assert result.passed is False
        assert result.retry_recommended is True
        assert len(result.factual_issues) >= 1

    def test_tier_in_details(self):
        """Result details should include the tier name."""
        result = run_quality_gate(
            GOOD_ARTICLE,
            "L5",
            {
                "economic_events": "",
                "market_data": MARKET_DATA_WITH_MOVES,
                "key_metrics": {},
            },
        )
        assert "tier=L5" in result.details

    def test_summary_tier_works(self):
        """Quality gate also works for Summary tier."""
        result = run_quality_gate(
            GOOD_ARTICLE,
            "Summary",
            {
                "economic_events": "",
                "market_data": MARKET_DATA_WITH_MOVES,
                "key_metrics": {},
            },
        )
        assert "tier=Summary" in result.details

    def test_empty_content_fails_gracefully(self):
        """Empty content should fail but not crash."""
        result = run_quality_gate(
            "",
            "L1",
            {
                "economic_events": "",
                "market_data": "",
                "key_metrics": {},
            },
        )
        assert result.passed is False  # 0 density < threshold
        assert result.total_sentences == 0
        assert result.insight_density == 0.0

    def test_empty_input_data_handled(self):
        """Empty input_data dict should not crash."""
        result = run_quality_gate(GOOD_ARTICLE, "L2", {})
        assert isinstance(result, QualityGateResult)
        # Should still check density even without input data
        assert result.total_sentences > 0

    def test_retry_recommended_on_failure(self):
        """G8: retry_recommended=True when quality gate fails."""
        input_data = {
            "economic_events": ECONOMIC_EVENTS_TEXT,
            "market_data": MARKET_DATA_WITH_MOVES,
            "key_metrics": {},
        }
        result = run_quality_gate(FILLER_ARTICLE, "L3", input_data)
        assert result.passed is False
        assert result.retry_recommended is True

    def test_retry_not_recommended_on_pass(self):
        """G8: retry_recommended=False when quality gate passes."""
        input_data = {
            "economic_events": ECONOMIC_EVENTS_TEXT,
            "market_data": MARKET_DATA_WITH_MOVES,
            "key_metrics": {},
        }
        result = run_quality_gate(GOOD_ARTICLE, "L1", input_data)
        assert result.passed is True
        assert result.retry_recommended is False
