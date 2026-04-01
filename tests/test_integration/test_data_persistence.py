"""Integration tests for data persistence — A1-A6 fixes.

Verifies that collected data is written to the correct Sheets tabs
and that breaking pipeline loads/persists dedup entries.
All Sheets calls are mocked.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cic_daily_report.collectors.market_data import MarketDataPoint
from cic_daily_report.collectors.onchain_data import OnChainMetric


class TestWriteRawData:
    """Tests for _write_raw_data in daily_pipeline (A1-A3)."""

    async def test_writes_news_to_tin_tuc_tho(self):
        from cic_daily_report.collectors.rss_collector import NewsArticle

        mock_sheets = MagicMock()
        mock_sheets.batch_append = MagicMock(return_value=1)

        articles = [
            NewsArticle(
                title="BTC news",
                url="https://x.com",
                source_name="CoinDesk",
                published_date="2026-01-01",
                summary="Summary",
                language="en",
            )
        ]

        from cic_daily_report.daily_pipeline import _write_raw_data

        with patch("cic_daily_report.daily_pipeline.asyncio") as mock_aio:
            # Make to_thread just call the function synchronously
            mock_aio.to_thread = AsyncMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))
            await _write_raw_data(mock_sheets, articles, [], [], [])

        mock_sheets.batch_append.assert_called_once()
        call_args = mock_sheets.batch_append.call_args
        assert call_args[0][0] == "TIN_TUC_THO"
        assert len(call_args[0][1]) == 1  # 1 row

    async def test_writes_market_data_to_du_lieu_thi_truong(self):
        mock_sheets = MagicMock()
        mock_sheets.batch_append = MagicMock(return_value=1)

        market = [
            MarketDataPoint("BTC", 105000, 2.5, 1e9, 2e12, "crypto", "CoinLore"),
        ]

        from cic_daily_report.daily_pipeline import _write_raw_data

        with patch("cic_daily_report.daily_pipeline.asyncio") as mock_aio:
            mock_aio.to_thread = AsyncMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))
            await _write_raw_data(mock_sheets, [], [], market, [])

        # Should be called once for market data
        mock_sheets.batch_append.assert_called_once()
        call_args = mock_sheets.batch_append.call_args
        assert call_args[0][0] == "DU_LIEU_THI_TRUONG"
        rows = call_args[0][1]
        assert len(rows) == 1
        assert rows[0][2] == "BTC"  # symbol column

    async def test_writes_onchain_to_du_lieu_onchain(self):
        mock_sheets = MagicMock()
        mock_sheets.batch_append = MagicMock(return_value=1)

        onchain = [
            OnChainMetric("BTC_Funding_Rate", 0.01, "Coinglass"),
        ]

        from cic_daily_report.daily_pipeline import _write_raw_data

        with patch("cic_daily_report.daily_pipeline.asyncio") as mock_aio:
            mock_aio.to_thread = AsyncMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))
            await _write_raw_data(mock_sheets, [], [], [], onchain)

        mock_sheets.batch_append.assert_called_once()
        assert mock_sheets.batch_append.call_args[0][0] == "DU_LIEU_ONCHAIN"

    async def test_skips_empty_collections(self):
        mock_sheets = MagicMock()
        mock_sheets.batch_append = MagicMock(return_value=0)

        from cic_daily_report.daily_pipeline import _write_raw_data

        with patch("cic_daily_report.daily_pipeline.asyncio") as mock_aio:
            mock_aio.to_thread = AsyncMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))
            await _write_raw_data(mock_sheets, [], [], [], [])

        mock_sheets.batch_append.assert_not_called()


class TestWriteGeneratedContent:
    """Tests for _write_generated_content in daily_pipeline (A4)."""

    async def test_writes_articles_to_noi_dung_da_tao(self):
        mock_sheets = MagicMock()
        mock_sheets.batch_append = MagicMock(return_value=2)

        articles = [
            {"tier": "L1", "content": "Article 1"},
            {"tier": "L2", "content": "Article 2"},
        ]

        from cic_daily_report.daily_pipeline import _write_generated_content

        with patch("cic_daily_report.daily_pipeline.asyncio") as mock_aio:
            mock_aio.to_thread = AsyncMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))
            await _write_generated_content(mock_sheets, articles)

        mock_sheets.batch_append.assert_called_once()
        call_args = mock_sheets.batch_append.call_args
        assert call_args[0][0] == "NOI_DUNG_DA_TAO"
        assert len(call_args[0][1]) == 2

    async def test_skips_empty_articles(self):
        mock_sheets = MagicMock()

        from cic_daily_report.daily_pipeline import _write_generated_content

        await _write_generated_content(mock_sheets, [])
        mock_sheets.batch_append.assert_not_called()


class TestBreakingPipelineSheets:
    """Tests for breaking pipeline Sheets integration (A5-A6)."""

    async def test_load_dedup_from_sheets(self):
        """_load_dedup_from_sheets returns DedupManager with loaded entries."""
        mock_records = [
            {
                "Hash": "abc123",
                "Tiêu đề": "BTC hack",
                "Nguồn": "CoinDesk",
                "Mức độ": "critical",
                "Thời gian": "2026-03-09T00:00:00",
                "Trạng thái gửi": "sent",
            }
        ]

        mock_sheets = MagicMock()
        mock_sheets.read_all = MagicMock(return_value=mock_records)

        with patch(
            "cic_daily_report.storage.sheets_client.SheetsClient",
            return_value=mock_sheets,
        ):
            from cic_daily_report.breaking_pipeline import _load_dedup_from_sheets

            mgr = await _load_dedup_from_sheets()

        assert len(mgr.entries) == 1
        assert mgr.entries[0].hash == "abc123"

    async def test_load_dedup_from_sheets_fatal_on_failure(self):
        """v0.30.0: Raises RuntimeError after retries instead of silently returning empty."""
        with patch(
            "cic_daily_report.storage.sheets_client.SheetsClient",
            side_effect=Exception("No sheets"),
        ):
            from cic_daily_report.breaking_pipeline import _load_dedup_from_sheets

            with pytest.raises(RuntimeError, match="CRITICAL.*Cannot load BREAKING_LOG"):
                await _load_dedup_from_sheets()

    async def test_write_breaking_run_log(self):
        """_write_breaking_run_log writes to NHAT_KY_PIPELINE."""
        from cic_daily_report.breaking_pipeline import BreakingRunLog, _write_breaking_run_log

        run_log = BreakingRunLog(
            started_at="2026-03-09T00:00:00",
            finished_at="2026-03-09T00:01:00",
            duration_seconds=60,
            status="success",
            events_sent=2,
        )

        mock_sheets = MagicMock()
        mock_sheets.batch_append = MagicMock(return_value=1)

        with patch(
            "cic_daily_report.storage.sheets_client.SheetsClient",
            return_value=mock_sheets,
        ):
            await _write_breaking_run_log(run_log)

        mock_sheets.batch_append.assert_called_once()
        assert mock_sheets.batch_append.call_args[0][0] == "NHAT_KY_PIPELINE"


class TestCooldownChange:
    """Verify cooldown is now 12 hours (VD-02 fix)."""

    def test_cooldown_is_12_hours(self):
        from cic_daily_report.breaking.dedup_manager import COOLDOWN_HOURS

        assert COOLDOWN_HOURS == 12
