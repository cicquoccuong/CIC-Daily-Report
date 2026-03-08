"""Tests for collectors/onchain_data.py — all mocked."""

from unittest.mock import patch

from cic_daily_report.collectors.onchain_data import (
    OnChainMetric,
    collect_onchain,
)


class TestOnChainMetric:
    def test_to_row(self):
        m = OnChainMetric(
            metric_name="MVRV_Z_Score",
            value=2.5,
            source="Glassnode",
            note="test",
        )
        row = m.to_row()
        assert len(row) == 6  # matches DU_LIEU_ONCHAIN columns
        assert row[2] == "MVRV_Z_Score"
        assert row[4] == "Glassnode"


class TestCollectOnchain:
    async def test_all_sources_fail_returns_empty(self):
        """NFR9: graceful degradation when all optional sources fail."""
        with (
            patch(
                "cic_daily_report.collectors.onchain_data._collect_glassnode",
                side_effect=Exception("API down"),
            ),
            patch(
                "cic_daily_report.collectors.onchain_data._collect_coinglass",
                side_effect=Exception("API down"),
            ),
            patch(
                "cic_daily_report.collectors.onchain_data._collect_fred",
                side_effect=Exception("API down"),
            ),
        ):
            metrics = await collect_onchain()

        assert metrics == []

    async def test_partial_success(self):
        """One source succeeds, others fail."""
        fred_metric = OnChainMetric("US_10Y_Treasury", 4.25, "FRED")
        with (
            patch(
                "cic_daily_report.collectors.onchain_data._collect_glassnode",
                side_effect=Exception("fail"),
            ),
            patch(
                "cic_daily_report.collectors.onchain_data._collect_coinglass",
                side_effect=Exception("fail"),
            ),
            patch(
                "cic_daily_report.collectors.onchain_data._collect_fred",
                return_value=[fred_metric],
            ),
        ):
            metrics = await collect_onchain()

        assert len(metrics) == 1
        assert metrics[0].metric_name == "US_10Y_Treasury"
