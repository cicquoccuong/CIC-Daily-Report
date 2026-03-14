"""Tests for daily_pipeline._format_onchain_value() — v0.19.0."""

from cic_daily_report.daily_pipeline import _format_onchain_value


class TestFormatOnchainValue:
    def test_format_onchain_funding_rate(self):
        """Funding Rate should be formatted as percentage."""
        result = _format_onchain_value("BTC Funding Rate", -0.000056)
        assert result == "-0.0056%"

    def test_format_onchain_ratio(self):
        """Ratio metrics should show 4 decimal places."""
        result = _format_onchain_value("Long/Short Ratio", 1.2345)
        assert result == "1.2345"

    def test_format_onchain_large_number(self):
        """Numbers >= 1B should use B suffix."""
        result = _format_onchain_value("Open Interest", 15_300_000_000)
        assert result == "15.30B"

    def test_format_onchain_small_number(self):
        """Numbers >= 1M should use M suffix."""
        result = _format_onchain_value("Volume", 42_500_000)
        assert result == "42.50M"
