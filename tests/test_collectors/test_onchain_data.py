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
                "cic_daily_report.collectors.onchain_data._collect_coinalyze_or_fallback",
                side_effect=Exception("API down"),
            ),
            patch(
                "cic_daily_report.collectors.onchain_data._collect_coinmetrics_or_fallback",
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
                "cic_daily_report.collectors.onchain_data._collect_coinalyze_or_fallback",
                side_effect=Exception("fail"),
            ),
            patch(
                "cic_daily_report.collectors.onchain_data._collect_coinmetrics_or_fallback",
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

    async def test_coinalyze_primary_derivatives(self):
        """Coinalyze metrics are used when available."""
        coinalyze_metrics = [
            OnChainMetric("BTC_Funding_Rate", 0.0001, "Coinalyze"),
            OnChainMetric("BTC_Open_Interest", 15e9, "Coinalyze"),
        ]
        cm_metrics = [
            OnChainMetric("BTC_NVT_Ratio", 45.2, "CoinMetrics"),
        ]
        with (
            patch(
                "cic_daily_report.collectors.onchain_data._collect_coinalyze_or_fallback",
                return_value=coinalyze_metrics,
            ),
            patch(
                "cic_daily_report.collectors.onchain_data._collect_coinmetrics_or_fallback",
                return_value=cm_metrics,
            ),
            patch(
                "cic_daily_report.collectors.onchain_data._collect_fred",
                return_value=[],
            ),
        ):
            metrics = await collect_onchain()

        assert len(metrics) == 3
        sources = {m.source for m in metrics}
        assert "Coinalyze" in sources
        assert "CoinMetrics" in sources

    async def test_fallback_chain_coinalyze_to_okx(self):
        """When Coinalyze fails, falls back to OKX via _collect_derivatives."""
        okx_metrics = [
            OnChainMetric("BTC_Funding_Rate", 0.0002, "OKX"),
        ]
        with (
            patch(
                "cic_daily_report.collectors.coinalyze_data.collect_coinalyze_derivatives",
                return_value=[],  # Coinalyze returns empty
            ),
            patch(
                "cic_daily_report.collectors.onchain_data._collect_derivatives",
                return_value=okx_metrics,
            ),
            patch(
                "cic_daily_report.collectors.onchain_data._collect_coinmetrics_or_fallback",
                return_value=[],
            ),
            patch(
                "cic_daily_report.collectors.onchain_data._collect_fred",
                return_value=[],
            ),
        ):
            metrics = await collect_onchain()

        assert len(metrics) == 1
        assert metrics[0].source == "OKX"

    async def test_fallback_chain_coinmetrics_to_glassnode(self):
        """When CoinMetrics fails, falls back to Glassnode."""
        glassnode_metrics = [
            OnChainMetric("MVRV_Z_Score", 2.5, "Glassnode"),
        ]
        with (
            patch(
                "cic_daily_report.collectors.onchain_data._collect_coinalyze_or_fallback",
                return_value=[],
            ),
            patch(
                "cic_daily_report.collectors.coinmetrics_data.collect_coinmetrics_onchain",
                return_value=[],  # CoinMetrics returns empty
            ),
            patch(
                "cic_daily_report.collectors.onchain_data._collect_glassnode",
                return_value=glassnode_metrics,
            ),
            patch(
                "cic_daily_report.collectors.onchain_data._collect_fred",
                return_value=[],
            ),
        ):
            metrics = await collect_onchain()

        assert len(metrics) == 1
        assert metrics[0].source == "Glassnode"
