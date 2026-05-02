"""Wave 0.8.6 (alpha.33) — Daily sanity guards: negative value strip + sector total flag.

Wave 0.8.6.1 (alpha.34) — sector check now REPLACES violating sentences
with VN placeholder (was log-only) + cross-tier consistency check added.
"""

from __future__ import annotations

import pytest

from cic_daily_report.generators.numeric_sanity import (
    check_negative_value,
    check_sector_total_pct_le_100,
    cross_tier_consistency_check,
)

# Same default field list as daily_pipeline.NEGATIVE_FIELD_GUARDS — kept
# inline here so the test stays decoupled from pipeline internals.
NEGATIVE_FIELDS = [
    "Total_Fees",
    "Total Fees",
    "Miner_Revenue",
    "Miner Revenue",
    "Tổng phí",
    "Doanh thu thợ đào",
]


class TestCheckNegativeValue:
    """Bug from Daily 11:59 SA 01/05: 'Total_Fees: -40.62B USD' shipped."""

    def test_strips_negative_total_fees_line(self):
        text = "BTC tăng 2%.\nTotal_Fees: -40.62B USD\nMiner active OK."
        cleaned, removed = check_negative_value(text, NEGATIVE_FIELDS)
        assert removed == 1
        assert "Total_Fees: -40.62B" not in cleaned
        # Other lines preserved
        assert "BTC tăng 2%" in cleaned
        assert "Miner active OK" in cleaned

    def test_positive_value_passes_through(self):
        text = "Total_Fees: 40.62B USD"
        cleaned, removed = check_negative_value(text, NEGATIVE_FIELDS)
        assert removed == 0
        assert cleaned == text

    def test_handles_vietnamese_field_names(self):
        text = "Tổng phí: -12.5M USD trong ngày."
        cleaned, removed = check_negative_value(text, NEGATIVE_FIELDS)
        assert removed == 1
        assert "Tổng phí: -12.5M" not in cleaned

    def test_multiple_negative_fields(self):
        text = "Tin BTC.\nTotal_Fees: -40B USD\nMiner_Revenue: -5B USD\nETH ổn định."
        cleaned, removed = check_negative_value(text, NEGATIVE_FIELDS)
        assert removed >= 2
        assert "Tin BTC" in cleaned
        assert "ETH ổn định" in cleaned

    def test_empty_inputs(self):
        assert check_negative_value("", NEGATIVE_FIELDS) == ("", 0)
        assert check_negative_value("text", []) == ("text", 0)

    def test_no_colon_no_match(self):
        # Prose like "Total Fees giảm 40%" must NOT match (no field:value)
        text = "Total Fees giảm 40% so với hôm qua."
        cleaned, removed = check_negative_value(text, NEGATIVE_FIELDS)
        assert removed == 0
        assert cleaned == text


class TestCheckSectorTotalPct:
    """Bug from Daily 11:59 SA 01/05: 'Layer 1: 140%, DeFi: 30%' totals 170%.

    Wave 0.8.6.1 (alpha.34) Fix #3 — REPLACE sentences with placeholder
    (previously log-only). Counter now reports # sentences replaced.
    """

    def test_flags_violation_when_sum_exceeds_tolerance(self):
        text = "Phân tích: Layer 1: 140%, DeFi: 30%, GameFi: 10%."
        result_text, replaced = check_sector_total_pct_le_100(text)
        # Sum 180 > 105 tolerance → at least 1 sentence replaced
        assert replaced >= 1
        # Placeholder appears in cleaned text
        assert "[Số liệu sector đang được xác minh" in result_text
        # Original "140%" no longer present (the violating chunk is removed)
        assert "140%" not in result_text

    def test_passes_when_sum_within_tolerance(self):
        text = "Layer 1: 60%, DeFi: 30%, NFT: 10%."  # = 100 exactly
        result_text, replaced = check_sector_total_pct_le_100(text)
        assert replaced == 0
        assert result_text == text

    def test_passes_with_small_rounding_buffer(self):
        # Sum = 102.5, under 105 tolerance
        text = "Layer 1: 50.5%, DeFi: 30%, NFT: 12%, AI: 10%."
        result_text, replaced = check_sector_total_pct_le_100(text)
        assert replaced == 0
        assert result_text == text

    def test_no_sectors_no_flag(self):
        text = "BTC tăng 2% hôm nay."
        result_text, replaced = check_sector_total_pct_le_100(text)
        assert replaced == 0
        assert result_text == text

    def test_custom_tolerance_override(self):
        text = "Layer 1: 60%, DeFi: 50%."  # 110, over default
        # Tighter tolerance still flags + replaces
        cleaned, replaced = check_sector_total_pct_le_100(text, tolerance=100.0)
        assert replaced >= 1
        assert "60%" not in cleaned and "50%" not in cleaned
        # Looser tolerance passes (no replacement)
        cleaned2, none_replaced = check_sector_total_pct_le_100(text, tolerance=120.0)
        assert none_replaced == 0
        assert cleaned2 == text

    def test_unaffected_text_preserved(self):
        # Wave 0.8.6.1 Fix #3: only the offending sentence replaced; other prose intact.
        text = (
            "BTC tăng mạnh trong phiên hôm nay.\n"
            "Layer 1: 140%, DeFi: 30%, NFT: 20%.\n"
            "Khối lượng giao dịch ổn định."
        )
        cleaned, replaced = check_sector_total_pct_le_100(text)
        assert replaced >= 1
        assert "BTC tăng mạnh" in cleaned
        assert "Khối lượng giao dịch ổn định" in cleaned
        assert "[Số liệu sector đang được xác minh" in cleaned


class TestCrossTierConsistencyCheck:
    """Wave 0.8.6.1 (alpha.34) Fix #1 — cross-tier macro consistency check.

    Bug 1 (Daily 11:59 SA 01/05): Total Market Cap mismatch $1.5T vs $2.65T
    across L1/L3 tiers — same data source, different LLM hallucinations.
    """

    def test_consistent_total_market_cap_no_violations(self):
        articles = {
            "L1": "Total Market Cap: $2.6T USD ổn định.",
            "L2": "Tổng vốn hóa: $2.65T tăng nhẹ.",
            "L3": "Total Market Cap: $2.7T trong tuần.",
        }
        _, violations = cross_tier_consistency_check(articles, tolerance_pct=10.0)
        # Spread 2.6→2.7 = 3.8% << 10% tolerance → no violation
        assert violations == []

    def test_inconsistent_total_market_cap_flags_violation(self):
        articles = {
            "L1": "Total Market Cap: $1.5T USD",
            "L2": "Tổng vốn hóa: $2.6T USD",
            "L3": "Total Market Cap: $2.65T USD",
        }
        _, violations = cross_tier_consistency_check(articles, tolerance_pct=10.0)
        # Spread 1.5T → 2.65T = 76% over → violation
        assert len(violations) >= 1
        assert "Total Market Cap" in violations[0]
        assert "L1" in violations[0]  # outlier identified

    def test_btc_dominance_inconsistency(self):
        articles = {
            "L1": "BTC.D 50.1%",
            "L2": "Dominance của BTC: 60.5%",
        }
        _, violations = cross_tier_consistency_check(articles, tolerance_pct=10.0)
        assert any("BTC Dominance" in v for v in violations)

    def test_total_volume_inconsistency(self):
        articles = {
            "L1": "Total Volume: $50B",
            "L2": "Tổng volume: $200B",
        }
        _, violations = cross_tier_consistency_check(articles, tolerance_pct=10.0)
        assert any("Total Volume" in v for v in violations)

    def test_single_tier_no_check(self):
        # Need ≥2 tiers for cross-check
        articles = {"L1": "Total Market Cap: $1.5T"}
        _, violations = cross_tier_consistency_check(articles)
        assert violations == []

    def test_articles_unchanged(self):
        articles = {
            "L1": "Total Market Cap: $1.5T",
            "L2": "Total Market Cap: $2.65T",
        }
        result, _ = cross_tier_consistency_check(articles)
        # Articles must pass through unchanged — no auto-fix
        assert result == articles

    def test_no_macro_data_no_violations(self):
        articles = {
            "L1": "BTC tăng giá hôm nay.",
            "L2": "ETH ổn định.",
        }
        _, violations = cross_tier_consistency_check(articles)
        assert violations == []

    def test_unit_conversion_t_b_normalized(self):
        # $2.5T (L1) vs $2500B (L2) should be IDENTICAL after normalization
        articles = {
            "L1": "Total Market Cap: $2.5T USD",
            "L2": "Total Market Cap: $2500B USD",
        }
        _, violations = cross_tier_consistency_check(articles, tolerance_pct=10.0)
        # 2500B == 2.5T → no violation
        assert violations == []


@pytest.mark.parametrize(
    "field, sample",
    [
        ("Total_Fees", "Total_Fees: -40.62B USD"),
        ("Miner Revenue", "Miner Revenue: -1.5M USD trong tháng"),
    ],
)
def test_negative_value_parametrized(field, sample):
    cleaned, removed = check_negative_value(sample, [field])
    assert removed == 1
    assert sample not in cleaned
