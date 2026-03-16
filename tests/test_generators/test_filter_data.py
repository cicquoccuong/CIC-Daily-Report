"""Tests for _filter_data_for_tier in article_generator.py (Phase 3a)."""

from cic_daily_report.generators.article_generator import (
    GenerationContext,
    _filter_data_for_tier,
)


def _make_context() -> GenerationContext:
    """Build a context with all data fields populated."""
    return GenerationContext(
        market_data=(
            "BTC: $105,000 (+2.5%)\n"
            "ETH: $3,800 (+1.2%)\n"
            "SOL: $180 (+5.0%)\n"
            "Fear & Greed: 65 (Greed)\n"
            "Total_MCap: $3.2T\n"
            "DXY: 104.5 (+0.3%)\n"
        ),
        news_summary="\n".join([f"News headline {i}" for i in range(20)]),
        onchain_data="Funding Rate: 0.01%\nOI: $18B\nLong/Short: 1.05",
        key_metrics={"BTC Price": "$105,000"},
        economic_events="FOMC meeting March 19\nCPI data March 12",
        narratives_text="Narrative: ETF inflows continue",
        sector_data="DeFi market cap: $90B (+2.5%)\nLayer 2: $30B",
    )


_METRICS_TABLE = "| Metric | Value |\n| BTC | $105K |"


class TestFilterDataL1:
    def test_only_btc_eth_fear_mcap(self):
        ctx = _make_context()
        result = _filter_data_for_tier("L1", ctx, _METRICS_TABLE)
        assert "BTC" in result["market_data"]
        assert "ETH" in result["market_data"]
        assert "Fear" in result["market_data"]
        # SOL should be filtered out
        assert "SOL" not in result["market_data"]

    def test_no_onchain(self):
        ctx = _make_context()
        result = _filter_data_for_tier("L1", ctx, _METRICS_TABLE)
        assert result["onchain_data"] == ""

    def test_no_economic_events(self):
        ctx = _make_context()
        result = _filter_data_for_tier("L1", ctx, _METRICS_TABLE)
        assert result["economic_events"] == ""

    def test_no_sector_data(self):
        ctx = _make_context()
        result = _filter_data_for_tier("L1", ctx, _METRICS_TABLE)
        assert result["sector_data"] == ""

    def test_no_narratives(self):
        ctx = _make_context()
        result = _filter_data_for_tier("L1", ctx, _METRICS_TABLE)
        assert result["narratives"] == ""

    def test_limited_news(self):
        ctx = _make_context()
        result = _filter_data_for_tier("L1", ctx, _METRICS_TABLE)
        news_lines = result["news_summary"].split("\n")
        assert len(news_lines) <= 15


class TestFilterDataL2:
    def test_full_market_data(self):
        ctx = _make_context()
        result = _filter_data_for_tier("L2", ctx, _METRICS_TABLE)
        assert "SOL" in result["market_data"]
        assert "BTC" in result["market_data"]

    def test_no_onchain(self):
        ctx = _make_context()
        result = _filter_data_for_tier("L2", ctx, _METRICS_TABLE)
        assert result["onchain_data"] == ""

    def test_has_sector_data(self):
        ctx = _make_context()
        result = _filter_data_for_tier("L2", ctx, _METRICS_TABLE)
        assert "DeFi" in result["sector_data"]

    def test_no_economic_events(self):
        ctx = _make_context()
        result = _filter_data_for_tier("L2", ctx, _METRICS_TABLE)
        assert result["economic_events"] == ""

    def test_full_news(self):
        ctx = _make_context()
        result = _filter_data_for_tier("L2", ctx, _METRICS_TABLE)
        # L2 gets full news
        assert "News headline 19" in result["news_summary"]


class TestFilterDataL3:
    def test_has_onchain(self):
        ctx = _make_context()
        result = _filter_data_for_tier("L3", ctx, _METRICS_TABLE)
        assert "Funding Rate" in result["onchain_data"]

    def test_has_economic_events(self):
        ctx = _make_context()
        result = _filter_data_for_tier("L3", ctx, _METRICS_TABLE)
        assert "FOMC" in result["economic_events"]

    def test_reduced_news(self):
        ctx = _make_context()
        result = _filter_data_for_tier("L3", ctx, _METRICS_TABLE)
        news_lines = result["news_summary"].split("\n")
        assert len(news_lines) <= 10


class TestFilterDataL4:
    def test_has_onchain(self):
        ctx = _make_context()
        result = _filter_data_for_tier("L4", ctx, _METRICS_TABLE)
        assert "Funding Rate" in result["onchain_data"]

    def test_has_sector_data(self):
        ctx = _make_context()
        result = _filter_data_for_tier("L4", ctx, _METRICS_TABLE)
        assert "DeFi" in result["sector_data"]

    def test_minimal_news(self):
        ctx = _make_context()
        result = _filter_data_for_tier("L4", ctx, _METRICS_TABLE)
        news_lines = result["news_summary"].split("\n")
        assert len(news_lines) <= 5


class TestFilterDataL5:
    def test_gets_everything(self):
        ctx = _make_context()
        result = _filter_data_for_tier("L5", ctx, _METRICS_TABLE)
        assert "SOL" in result["market_data"]
        assert "Funding Rate" in result["onchain_data"]
        assert "FOMC" in result["economic_events"]
        assert "DeFi" in result["sector_data"]
        assert "ETF" in result["narratives"]
        # Full news
        assert "News headline 19" in result["news_summary"]


class TestFilterDataEdgeCases:
    def test_empty_context(self):
        """All empty data should not crash."""
        ctx = GenerationContext()
        for tier in ["L1", "L2", "L3", "L4", "L5"]:
            result = _filter_data_for_tier(tier, ctx, "")
            assert isinstance(result, dict)
            assert "market_data" in result

    def test_preserves_metrics_table(self):
        """All tiers get the key_metrics_table."""
        ctx = _make_context()
        for tier in ["L1", "L2", "L3", "L4", "L5"]:
            result = _filter_data_for_tier(tier, ctx, _METRICS_TABLE)
            assert result["key_metrics_table"] == _METRICS_TABLE
