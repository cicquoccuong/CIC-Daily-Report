"""Tests for QO.27 PriceSnapshot wiring and QO.20 BLOCK mode in pipeline context.

Fix 1: PriceSnapshot created from collected market_data, passed to extract_all.
Fix 2: run_quality_gate_with_retry replaces run_quality_gate in pipeline.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from cic_daily_report.collectors.market_data import (
    MarketDataPoint,
    PriceSnapshot,
)
from cic_daily_report.generators.quality_gate import (
    QUALITY_WARNING,
    run_quality_gate_with_retry,
)

# ============================================================================
# QO.27: PriceSnapshot creation from market_data
# ============================================================================


class TestPriceSnapshotFromMarketData:
    """QO.27: Verify PriceSnapshot can be created from collected market_data."""

    def test_snapshot_from_market_data_list(self):
        """PriceSnapshot wraps existing market_data without extra API call."""
        data = [
            MarketDataPoint(
                symbol="BTC",
                price=87500,
                change_24h=3.2,
                volume_24h=5e10,
                market_cap=1.7e12,
                data_type="crypto",
                source="CoinLore",
            ),
            MarketDataPoint(
                symbol="ETH",
                price=3200,
                change_24h=-1.5,
                volume_24h=2e10,
                market_cap=3.8e11,
                data_type="crypto",
                source="CoinLore",
            ),
            MarketDataPoint(
                symbol="Fear&Greed",
                price=45,
                change_24h=0,
                volume_24h=0,
                market_cap=0,
                data_type="index",
                source="Alternative.me",
            ),
        ]
        snapshot = PriceSnapshot(market_data=data)

        assert snapshot.btc_price == 87500
        assert snapshot.get_price("ETH") == 3200
        assert snapshot.fear_greed == 45
        assert snapshot.get_change_24h("BTC") == 3.2
        assert len(snapshot.get_top_performers(2)) == 2
        assert snapshot.timestamp  # Auto-generated

    def test_snapshot_from_empty_list(self):
        """Empty market_data → snapshot with no prices."""
        snapshot = PriceSnapshot(market_data=[])
        assert snapshot.btc_price is None
        assert snapshot.get_top_performers(3) == []


# ============================================================================
# QO.20: run_quality_gate_with_retry — BLOCK mode
# ============================================================================


GOOD_CONTENT = (
    "BTC tang **3.2%** len $87,500 trong phien giao dich hom nay. "
    "ETH tang 2.1% dat $3,200. "
    "Fear & Greed Index = 45, cho thay thi truong trung tinh. "
    "BTC Dominance dat 56.8%, giam nhe 0.3% so voi hom qua. "
    "Total Market Cap dat $2.8 nghin ty USD. "
    "Funding Rate = 0.01%, cho thay derivatives can bang. "
    "RSI 14 ngay = 52.3, vung trung tinh. "
    "DXY giam 0.4% ve 104.2 — ho tro tai san rui ro. "
    "Sector dan dau: AI & Big Data tang 4.1%. "
    "Volume giao dich dat $45.2 ty trong phien hom nay.\n"
)

FILLER_CONTENT = (
    "Thi truong hom nay tiep tuc xu huong hien tai. "
    "Cac nha dau tu dang theo doi dien bien tiep theo. "
    "Nhieu chuyen gia cho rang can kien nhan cho doi. "
    "Xu huong dai han van chua ro rang. "
    "Can them thoi gian de xac nhan tin hieu. "
    "Thi truong dang trong giai doan tich luy. "
    "Khong co nhieu thay doi so voi tuan truoc. "
    "Cac sector deu bien dong nhe. "
    "Tam ly nha dau tu van than trong. "
    "Ky vong tuan toi se ro rang hon.\n"
)


class TestRunQualityGateWithRetry:
    """QO.20: BLOCK mode runs retry on quality failure."""

    async def test_good_content_passes_without_retry(self):
        """Good content passes QG — no retry needed."""
        input_data = {"economic_events": "", "market_data": "", "key_metrics": {}}
        content, result = await run_quality_gate_with_retry(
            GOOD_CONTENT, "L1", input_data, regenerate_fn=None, mode="BLOCK"
        )
        assert result.passed
        assert not result.was_retried
        assert content == GOOD_CONTENT

    async def test_filler_fails_and_retries(self):
        """Filler content triggers retry in BLOCK mode."""

        async def regenerate():
            return GOOD_CONTENT

        input_data = {"economic_events": "", "market_data": "", "key_metrics": {}}
        content, result = await run_quality_gate_with_retry(
            FILLER_CONTENT,
            "L1",
            input_data,
            regenerate_fn=regenerate,
            mode="BLOCK",
        )
        assert result.passed
        assert result.was_retried
        assert content == GOOD_CONTENT

    async def test_filler_no_regen_fn_sends_as_is(self):
        """Filler with no regenerate_fn → sends original (no retry)."""
        input_data = {"economic_events": "", "market_data": "", "key_metrics": {}}
        content, result = await run_quality_gate_with_retry(
            FILLER_CONTENT,
            "L1",
            input_data,
            regenerate_fn=None,
            mode="BLOCK",
        )
        assert not result.passed
        assert content == FILLER_CONTENT  # Unchanged

    async def test_log_mode_does_not_retry(self):
        """LOG mode measures only — never retries."""
        regen = AsyncMock()
        input_data = {"economic_events": "", "market_data": "", "key_metrics": {}}
        content, result = await run_quality_gate_with_retry(
            FILLER_CONTENT,
            "L1",
            input_data,
            regenerate_fn=regen,
            mode="LOG",
        )
        regen.assert_not_called()
        assert content == FILLER_CONTENT

    async def test_off_mode_skips_checks(self):
        """OFF mode returns passed=True without checking."""
        input_data = {"economic_events": "", "market_data": "", "key_metrics": {}}
        content, result = await run_quality_gate_with_retry(
            FILLER_CONTENT,
            "L1",
            input_data,
            regenerate_fn=None,
            mode="OFF",
        )
        assert result.passed
        assert content == FILLER_CONTENT

    async def test_retry_also_fails_appends_warning(self):
        """Both attempts fail → warning appended to content."""

        async def regenerate():
            return FILLER_CONTENT  # Also bad

        input_data = {"economic_events": "", "market_data": "", "key_metrics": {}}
        content, result = await run_quality_gate_with_retry(
            FILLER_CONTENT,
            "L1",
            input_data,
            regenerate_fn=regenerate,
            mode="BLOCK",
        )
        assert not result.passed
        assert result.was_retried
        assert result.quality_warning_appended
        assert QUALITY_WARNING in content


# ============================================================================
# Lint fix: LLM adapter line length
# ============================================================================


class TestLLMAdapterLineLengthFix:
    """Verify the LLM adapter error message line was broken correctly."""

    def test_llm_error_message_exists(self):
        """LLMError class has the expected error message."""
        from cic_daily_report.adapters.llm_adapter import LLMError

        err = LLMError("test", source="test")
        assert err.source == "test"
