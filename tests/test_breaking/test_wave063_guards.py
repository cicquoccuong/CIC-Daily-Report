"""Wave 0.6 Story 0.6.3 (alpha.21) — Date freshness HARD BLOCK + extended numeric guards.

Tests:
1. Date block flag OFF → LOG-ONLY behavior (Wave 0.5.2 unchanged).
2. Date block flag ON → strip past+marker sentences.
3. Threshold > 2 → delivery_failed.
4-8. BTC/ETH price sanity (low, high, in-range).
9-10. Year sanity (future suspicious, historical OK).
11. Combined guard suite.
12-15. Edge cases (empty, unicode, no numbers, very long).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from cic_daily_report.breaking.content_generator import (
    _check_and_handle_stale_dates,
)
from cic_daily_report.generators.numeric_sanity import (
    BTC_PRICE_MAX,
    BTC_PRICE_MIN,
    apply_all_numeric_guards,
    check_btc_price_sanity,
    check_eth_price_sanity,
    check_year_sanity,
)

# ---------------------------------------------------------------------------
# Part A — Date block flag (OFF vs ON)
# ---------------------------------------------------------------------------


class TestDateBlockFlag:
    """Verify flag default (OFF) preserves Wave 0.5.2 behavior; ON enforces strip."""

    def test_date_block_disabled_log_only(self):
        """Flag OFF → content unchanged, only warnings logged."""
        today = date(2026, 4, 27)
        content = "Dự kiến diễn ra vào 06/03 sắp tới sẽ ảnh hưởng đến thị trường."
        cleaned, issues, failed = _check_and_handle_stale_dates(
            content, today=today, block_enabled=False
        )
        assert cleaned == content  # untouched
        assert failed is False
        # issues list contains warning entries even in log-only mode
        assert len(issues) >= 1

    def test_date_block_enabled_strip(self):
        """Flag ON + 1 violation → sentence stripped, delivery_failed=False."""
        today = date(2026, 4, 27)
        content = (
            "BTC tăng mạnh hôm nay. "
            "Dự kiến diễn ra vào 06/03 sắp tới sẽ tác động lớn. "
            "Thị trường ETF tăng trưởng tốt."
        )
        cleaned, issues, failed = _check_and_handle_stale_dates(
            content, today=today, block_enabled=True
        )
        assert "06/03 sắp tới" not in cleaned
        assert "BTC tăng mạnh hôm nay" in cleaned
        assert "ETF tăng trưởng tốt" in cleaned
        assert failed is False  # only 1 sentence stripped
        assert len(issues) == 1

    def test_date_block_too_many_strip_delivery_failed(self):
        """Flag ON + 3 violations (>2 threshold) → delivery_failed=True."""
        today = date(2026, 4, 27)
        content = (
            "Dự kiến 06/03 sắp tới có sự kiện. "
            "Sự kiện ngày 10/02 sắp tới quan trọng. "
            "Dự kiến triển khai vào 15/01 sắp tới. "
            "Đoạn này là lành mạnh."
        )
        cleaned, issues, failed = _check_and_handle_stale_dates(
            content, today=today, block_enabled=True
        )
        assert failed is True  # 3 stripped > threshold of 2
        assert len(issues) == 3
        assert "Đoạn này là lành mạnh" in cleaned

    def test_date_block_no_marker_kept(self):
        """Date past but no future marker → kept (legit historical reference)."""
        today = date(2026, 4, 27)
        content = "Vào ngày 06/03 đã xảy ra sự kiện quan trọng trong quá khứ."
        cleaned, issues, failed = _check_and_handle_stale_dates(
            content, today=today, block_enabled=True
        )
        assert cleaned == content
        assert failed is False
        assert issues == []

    def test_date_block_future_date_kept(self):
        """Future date + future marker → kept (legit upcoming event)."""
        today = date(2026, 4, 27)
        content = "Dự kiến diễn ra vào 30/06/2026 sắp tới."
        cleaned, issues, failed = _check_and_handle_stale_dates(
            content, today=today, block_enabled=True
        )
        assert cleaned == content
        assert failed is False


# ---------------------------------------------------------------------------
# Part B — Numeric guards: BTC/ETH/year
# ---------------------------------------------------------------------------


class TestBTCPriceSanity:
    def test_btc_price_low_flagged(self):
        """BTC at $5k → flag (impossible in 2026)."""
        content = "BTC hiện đang giao dịch quanh $5,000 sau biến động."
        _, issues = check_btc_price_sanity(content)
        assert len(issues) == 1
        assert "out of range" in issues[0]

    def test_btc_price_high_flagged(self):
        """BTC at $300k → flag (above max)."""
        content = "Bitcoin chạm đỉnh $300,000 trong phiên giao dịch."
        _, issues = check_btc_price_sanity(content)
        assert len(issues) == 1
        assert "300,000" in issues[0] or "300000" in issues[0]

    def test_btc_price_in_range_pass(self):
        """BTC at $76k → pass."""
        content = "BTC ổn định ở mức $76,000 sau tin tức từ Fed."
        _, issues = check_btc_price_sanity(content)
        assert issues == []

    def test_btc_price_no_context_ignored(self):
        """$5k near 'fee' (no BTC ctx) → ignored to avoid false positive."""
        content = "Anh Cường trả phí $5,000 cho gói VIP."
        _, issues = check_btc_price_sanity(content)
        assert issues == []

    def test_btc_price_with_k_suffix(self):
        """'$5k' near BTC → flag as low."""
        content = "BTC giảm xuống $5k theo dự báo bi quan."
        _, issues = check_btc_price_sanity(content)
        assert len(issues) == 1


class TestETHPriceSanity:
    def test_eth_price_low_flagged(self):
        """ETH at $500 → flag."""
        content = "ETH rơi xuống $500 sau tin xấu."
        _, issues = check_eth_price_sanity(content)
        assert len(issues) == 1

    def test_eth_price_in_range_pass(self):
        """ETH at $2,300 → pass."""
        content = "Ethereum giao dịch quanh $2,300 trong tuần qua."
        _, issues = check_eth_price_sanity(content)
        assert issues == []

    def test_eth_price_no_context_ignored(self):
        """$500 near 'gift' (no ETH ctx) → ignored."""
        content = "Phần thưởng $500 cho người tham gia."
        _, issues = check_eth_price_sanity(content)
        assert issues == []


class TestYearSanity:
    def test_year_far_future_flagged(self):
        """Year 2030 with current=2026 (buffer 1) → flag."""
        content = "Bitcoin halving dự kiến diễn ra năm 2030."
        _, issues = check_year_sanity(content, current_year=2026, future_buffer=1)
        assert len(issues) == 1
        assert "2030" in issues[0]

    def test_year_historical_ok(self):
        """Year 2014 → pass (legit historical)."""
        content = "Mt.Gox sụp đổ năm 2014, làm rúng động ngành crypto."
        _, issues = check_year_sanity(content, current_year=2026)
        assert issues == []

    def test_year_within_buffer_ok(self):
        """Year 2027 with buffer 1 → pass (next year, plausible forecast)."""
        content = "ETF Spot dự kiến phê duyệt năm 2027."
        _, issues = check_year_sanity(content, current_year=2026, future_buffer=1)
        assert issues == []

    def test_year_uses_today_when_none(self):
        """current_year=None → uses datetime.now().year."""
        actual_year = datetime.now(timezone.utc).year
        # Year 5 years in future is always flagged regardless of "today".
        content = f"Sự kiện năm {actual_year + 5}."
        _, issues = check_year_sanity(content, current_year=None)
        assert len(issues) == 1


# ---------------------------------------------------------------------------
# Combined wrapper
# ---------------------------------------------------------------------------


class TestApplyAllGuards:
    def test_all_guards_combined_violations(self):
        """Multiple violations across % + BTC + year all detected."""
        content = "Heat Score 1700% và BTC giao dịch ở $5,000. Dự kiến halving năm 2032."
        # Pin current year via env-free path: year guard reads datetime.now,
        # so we just verify >= 2 issues + % cap applied.
        sanitized, issues = apply_all_numeric_guards(content)
        # % cap → 1700% becomes 100%
        assert "1700%" not in sanitized
        assert "100%" in sanitized
        # BTC + year both flagged → at least 2 issues beyond % warning
        assert len(issues) >= 3

    def test_apply_with_snapshot_tightens_range(self):
        """Snapshot $76k → tight range $38k-$114k. $5k still flagged, $30k flagged too."""
        content = "BTC tăng từ $30,000 lên $80,000."
        # Without snapshot: $30k inside default $10k-$200k → no flag
        _, issues_default = apply_all_numeric_guards(content)
        # With snapshot $76k → ±50% = $38k-$114k → $30k now flagged
        _, issues_tight = apply_all_numeric_guards(content, btc_snapshot=76_000.0)
        assert len(issues_tight) > len(issues_default)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_content_no_crash(self):
        """Empty content → no crash, no issues."""
        cleaned, issues = apply_all_numeric_guards("")
        assert cleaned == ""
        assert issues == []

    def test_no_numbers_no_issues(self):
        """Content without numerics → pass clean."""
        content = "BTC tiếp tục dao động trong vùng giá hiện tại."
        cleaned, issues = apply_all_numeric_guards(content)
        assert cleaned == content
        assert issues == []

    def test_unicode_vietnamese_no_crash(self):
        """Vietnamese diacritics (đ, ơ, ư) handled correctly."""
        content = "Tăng trưởng của Bitcoin đạt đỉnh $76,000 vào năm 2026."
        cleaned, issues = apply_all_numeric_guards(content)
        # In-range BTC + current year → no issues
        assert issues == []

    def test_very_long_content_no_crash(self):
        """5000-char content processes without error."""
        content = "BTC tại $76,000 ổn định. " * 200
        cleaned, issues = apply_all_numeric_guards(content)
        # All in-range → no issues despite repetition
        assert issues == []

    def test_btc_price_constants_sanity(self):
        """Constants are non-trivial sane values."""
        assert BTC_PRICE_MIN == 10_000.0
        assert BTC_PRICE_MAX == 200_000.0
        assert BTC_PRICE_MIN < BTC_PRICE_MAX


# ---------------------------------------------------------------------------
# Config flag wiring
# ---------------------------------------------------------------------------


class TestConfigFlag:
    def test_default_flag_is_off(self, monkeypatch):
        """Default: WAVE_0_6_DATE_BLOCK env var unset → False."""
        monkeypatch.delenv("WAVE_0_6_DATE_BLOCK", raising=False)
        from cic_daily_report.core.config import _wave_0_6_date_block_enabled

        assert _wave_0_6_date_block_enabled() is False

    @pytest.mark.parametrize("val", ["1", "true", "yes", "on", "TRUE"])
    def test_flag_truthy_values(self, monkeypatch, val):
        monkeypatch.setenv("WAVE_0_6_DATE_BLOCK", val)
        from cic_daily_report.core.config import _wave_0_6_date_block_enabled

        assert _wave_0_6_date_block_enabled() is True

    @pytest.mark.parametrize("val", ["0", "false", "no", "off", ""])
    def test_flag_falsy_values(self, monkeypatch, val):
        monkeypatch.setenv("WAVE_0_6_DATE_BLOCK", val)
        from cic_daily_report.core.config import _wave_0_6_date_block_enabled

        assert _wave_0_6_date_block_enabled() is False
