"""Tests for generators/data_quality.py — data completeness scoring."""

from cic_daily_report.collectors.market_data import MarketDataPoint
from cic_daily_report.collectors.onchain_data import OnChainMetric
from cic_daily_report.generators.data_quality import (
    DataQualityReport,
    assess_data_quality,
)


def _btc_price() -> MarketDataPoint:
    return MarketDataPoint("BTC", 105000, 2.5, 50e9, 2e12, "crypto", "coinlore")


def _eth_price() -> MarketDataPoint:
    return MarketDataPoint("ETH", 3800, 1.2, 20e9, 450e9, "crypto", "coinlore")


def _extra_coins(n: int) -> list[MarketDataPoint]:
    names = ["SOL", "ADA", "AVAX", "DOT", "LINK", "MATIC", "DOGE", "SHIB"]
    return [
        MarketDataPoint(names[i % len(names)], 100 + i, 0.5, 1e9, 10e9, "crypto", "coinlore")
        for i in range(n)
    ]


def _funding_rate() -> OnChainMetric:
    return OnChainMetric("BTC_Funding_Rate", 0.01, "okx")


def _open_interest() -> OnChainMetric:
    return OnChainMetric("BTC_Open_Interest", 18e9, "okx")


def _long_short() -> OnChainMetric:
    return OnChainMetric("BTC_Long_Short_Ratio", 1.05, "okx")


# ---------------------------------------------------------------------------
# DataQualityReport
# ---------------------------------------------------------------------------


class TestDataQualityReport:
    def test_grade_a(self):
        report = DataQualityReport(score=85, grade="A")
        assert not report.is_degraded
        assert report.format_for_llm() == ""  # no warnings = empty

    def test_grade_f_is_degraded(self):
        report = DataQualityReport(score=15, grade="F", warnings=["No data"])
        assert report.is_degraded

    def test_format_for_llm_with_warnings(self):
        report = DataQualityReport(score=30, grade="D", warnings=["Missing BTC", "No news"])
        text = report.format_for_llm()
        assert "D (30/100)" in text
        assert "Missing BTC" in text
        assert "No news" in text

    def test_format_for_log(self):
        report = DataQualityReport(
            score=60, grade="B", issues=["Only 5 news", "Partial derivatives"]
        )
        log = report.format_for_log()
        assert "B (60/100)" in log
        assert "Only 5 news" in log

    def test_threshold_boundary(self):
        assert DataQualityReport(score=40, grade="C").is_degraded is False
        assert DataQualityReport(score=39, grade="D").is_degraded is True


# ---------------------------------------------------------------------------
# assess_data_quality
# ---------------------------------------------------------------------------


class TestAssessDataQuality:
    def test_perfect_score(self):
        """All data present → grade A."""
        market = [_btc_price(), _eth_price()] + _extra_coins(5)
        onchain = [_funding_rate(), _open_interest(), _long_short()]
        report = assess_data_quality(
            news_count=15,
            market_data=market,
            onchain_data=onchain,
            has_sector_data=True,
            has_econ_calendar=True,
        )
        assert report.score == 100
        assert report.grade == "A"
        assert report.issues == []
        assert report.warnings == []

    def test_no_data_at_all(self):
        """Nothing collected → grade F."""
        report = assess_data_quality(news_count=0, market_data=[], onchain_data=[])
        assert report.score == 0
        assert report.grade == "F"
        assert report.is_degraded
        assert len(report.warnings) >= 3  # no news, no prices, no derivatives

    def test_partial_news(self):
        """5 out of 10 expected news → proportional score."""
        market = [_btc_price()] + _extra_coins(4)
        report = assess_data_quality(news_count=5, market_data=market, onchain_data=[])
        # News: 25 * 5/10 = 12, Market: 10 (BTC) + 15 (5 coins) = 25
        assert report.score >= 30
        assert "5 news" in str(report.issues) or "5 tin" in str(report.warnings)

    def test_btc_missing_is_critical(self):
        """No BTC price → warning about unreliable data."""
        market = [_eth_price()] + _extra_coins(4)
        report = assess_data_quality(news_count=10, market_data=market, onchain_data=[])
        assert any("BTC" in w for w in report.warnings)
        assert any("BTC" in i for i in report.issues)

    def test_partial_derivatives(self):
        """Only Funding Rate, no OI/LS → partial score + issue noted."""
        market = [_btc_price()] + _extra_coins(5)
        onchain = [_funding_rate()]
        report = assess_data_quality(news_count=10, market_data=market, onchain_data=onchain)
        # Funding: 8 pts, OI: 0, LS: 0 → onchain_score=8
        assert any("OI" in i for i in report.issues)
        assert any("Long/Short" in i for i in report.issues)

    def test_all_derivatives_present(self):
        """All three derivatives → full 20 pts, no derivatives issues."""
        market = [_btc_price()] + _extra_coins(5)
        onchain = [_funding_rate(), _open_interest(), _long_short()]
        report = assess_data_quality(news_count=10, market_data=market, onchain_data=onchain)
        assert not any("derivatives" in i.lower() for i in report.issues)

    def test_sector_data_adds_15pts(self):
        """With vs without sector data → 15 point difference."""
        market = [_btc_price()] + _extra_coins(5)
        without = assess_data_quality(
            news_count=10, market_data=market, onchain_data=[], has_sector_data=False
        )
        with_sector = assess_data_quality(
            news_count=10, market_data=market, onchain_data=[], has_sector_data=True
        )
        assert with_sector.score - without.score == 15

    def test_econ_calendar_adds_15pts(self):
        """With vs without econ calendar → 15 point difference."""
        market = [_btc_price()] + _extra_coins(5)
        without = assess_data_quality(
            news_count=10, market_data=market, onchain_data=[], has_econ_calendar=False
        )
        with_econ = assess_data_quality(
            news_count=10, market_data=market, onchain_data=[], has_econ_calendar=True
        )
        assert with_econ.score - without.score == 15

    def test_grade_boundaries(self):
        """Verify grade assignment at exact boundaries."""
        market = [_btc_price()] + _extra_coins(5)
        # Score ~50 → grade C (BTC 10 + coins 15 + news 25 = 50)
        report = assess_data_quality(news_count=10, market_data=market, onchain_data=[])
        assert report.grade in ("B", "C")  # 50 = C boundary
        assert not report.is_degraded

    def test_no_crypto_prices_warning(self):
        """No crypto data at all → specific warning."""
        macro_only = [MarketDataPoint("DXY", 104, 0.3, 0, 0, "macro", "yfinance")]
        report = assess_data_quality(news_count=10, market_data=macro_only, onchain_data=[])
        assert any("giá" in w for w in report.warnings)
