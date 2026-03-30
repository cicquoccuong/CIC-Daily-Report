"""Tests for storage/historical_metrics.py — all external APIs mocked."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from cic_daily_report.storage.historical_metrics import (
    LICH_SU_METRICS_HEADERS,
    TAB_NAME,
    HistoricalSnapshot,
    build_snapshot_from_pipeline,
    format_historical_for_llm,
    read_historical,
    save_daily_snapshot,
)

# --- Helpers ---


def _make_snapshot(
    date: str = "2026-03-28",
    btc_price: float = 87500.0,
    f_and_g: int = 45,
    rsi_btc: float = 52.1,
    mvrv_z: float = 1.8,
    **kwargs,
) -> HistoricalSnapshot:
    """Create a HistoricalSnapshot with sensible defaults for testing."""
    defaults = {
        "date": date,
        "btc_price": btc_price,
        "eth_price": 3200.0,
        "f_and_g": f_and_g,
        "dxy": 99.4,
        "gold": 2650.0,
        "oil": 72.5,
        "vix": 18.3,
        "funding_rate": 0.0006,
        "btc_dominance": 56.8,
        "altcoin_season": 35.0,
        "consensus_score": 0.0,
        "consensus_label": "N/A",
        "rsi_btc": rsi_btc,
        "ma50_btc": 85000.0,
        "ma200_btc": 78000.0,
        "mvrv_z": mvrv_z,
        "nupl": 0.45,
        "sopr": 1.02,
        "puell_multiple": 0.9,
        "pi_cycle_gap_pct": 25.0,
        "etf_net_flow": 150000000.0,
        "stablecoin_total_chg_7d": 2.5,
    }
    defaults.update(kwargs)
    return HistoricalSnapshot(**defaults)


def _make_mock_sheets(existing_tabs=None, all_values=None):
    """Create a mock SheetsClient with configurable tab state.

    WHY: We need to mock _connect() to return a mock spreadsheet with
    worksheets() and worksheet() methods that behave like gspread.
    """
    mock_ws = MagicMock()
    mock_ws.get_all_values.return_value = all_values or [LICH_SU_METRICS_HEADERS]
    mock_ws.append_rows = MagicMock()
    mock_ws.update = MagicMock()
    mock_ws.delete_rows = MagicMock()

    mock_ss = MagicMock()
    tabs = existing_tabs or [TAB_NAME]
    mock_worksheets = [MagicMock(title=t) for t in tabs]
    mock_ss.worksheets.return_value = mock_worksheets
    mock_ss.worksheet.return_value = mock_ws
    mock_ss.add_worksheet.return_value = mock_ws

    mock_client = MagicMock()
    mock_client._connect.return_value = mock_ss
    mock_client._spreadsheet = mock_ss

    return mock_client, mock_ws, mock_ss


# --- HistoricalSnapshot dataclass tests ---


class TestHistoricalSnapshot:
    def test_instantiation_all_fields(self):
        """All 23 fields can be set and accessed."""
        snap = _make_snapshot()
        assert snap.date == "2026-03-28"
        assert snap.btc_price == 87500.0
        assert snap.eth_price == 3200.0
        assert snap.f_and_g == 45
        assert snap.dxy == 99.4
        assert snap.gold == 2650.0
        assert snap.oil == 72.5
        assert snap.vix == 18.3
        assert snap.funding_rate == 0.0006
        assert snap.btc_dominance == 56.8
        assert snap.altcoin_season == 35.0
        assert snap.consensus_score == 0.0
        assert snap.consensus_label == "N/A"
        assert snap.rsi_btc == 52.1
        assert snap.ma50_btc == 85000.0
        assert snap.ma200_btc == 78000.0
        assert snap.mvrv_z == 1.8
        assert snap.nupl == 0.45
        assert snap.sopr == 1.02
        assert snap.puell_multiple == 0.9
        assert snap.pi_cycle_gap_pct == 25.0
        assert snap.etf_net_flow == 150000000.0
        assert snap.stablecoin_total_chg_7d == 2.5

    def test_to_row_matches_header_count(self):
        """to_row() returns a list with same length as LICH_SU_METRICS_HEADERS."""
        snap = _make_snapshot()
        row = snap.to_row()
        assert len(row) == len(LICH_SU_METRICS_HEADERS)

    def test_to_row_values_order(self):
        """to_row() returns values in the same order as headers."""
        snap = _make_snapshot(date="2026-03-28", btc_price=87500.0, f_and_g=45)
        row = snap.to_row()
        assert row[0] == "2026-03-28"  # Ngay
        assert row[1] == 87500.0  # BTC_Gia
        assert row[3] == 45  # F_and_G

    def test_from_row_roundtrip(self):
        """from_row(to_row()) reconstructs the same snapshot."""
        original = _make_snapshot()
        row = original.to_row()
        reconstructed = HistoricalSnapshot.from_row(row)
        assert reconstructed.date == original.date
        assert reconstructed.btc_price == original.btc_price
        assert reconstructed.f_and_g == original.f_and_g
        assert reconstructed.consensus_label == original.consensus_label

    def test_from_row_handles_short_row(self):
        """from_row() handles rows shorter than expected (graceful defaults)."""
        short_row = ["2026-03-28", "87500", "3200"]
        snap = HistoricalSnapshot.from_row(short_row)
        assert snap.date == "2026-03-28"
        assert snap.btc_price == 87500.0
        assert snap.f_and_g == 0  # default
        assert snap.consensus_label == "N/A"  # default

    def test_from_row_handles_empty_strings(self):
        """from_row() treats empty strings as defaults."""
        row = [
            "2026-03-28",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "N/A",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ]
        snap = HistoricalSnapshot.from_row(row)
        assert snap.btc_price == 0.0
        assert snap.f_and_g == 0


# --- build_snapshot_from_pipeline tests ---


class TestBuildSnapshotFromPipeline:
    def test_full_data_extracts_all_fields(self):
        """With full pipeline data, all snapshot fields are populated."""

        @dataclass
        class MockMarketPoint:
            symbol: str
            price: float
            data_type: str

        @dataclass
        class MockTechIndicator:
            symbol: str
            rsi_14d: float
            ma_50: float
            ma_200: float

        @dataclass
        class MockOnChainAdvanced:
            name: str
            value: float

        @dataclass
        class MockPiCycle:
            distance_pct: float

        @dataclass
        class MockETFFlows:
            total_flow_usd: float

        @dataclass
        class MockStablecoin:
            change_7d: float

        @dataclass
        class MockResearchData:
            onchain_advanced: list
            pi_cycle: object
            etf_flows: object
            stablecoins: list

        market_points = [
            MockMarketPoint("BTC", 87500.0, "crypto"),
            MockMarketPoint("ETH", 3200.0, "crypto"),
            MockMarketPoint("Fear&Greed", 45.0, "index"),
            MockMarketPoint("DXY", 99.4, "macro"),
            MockMarketPoint("Gold", 2650.0, "macro"),
            MockMarketPoint("Oil", 72.5, "macro"),
            MockMarketPoint("VIX", 18.3, "macro"),
            MockMarketPoint("BTC_Dominance", 56.8, "index"),
            MockMarketPoint("Altcoin_Season", 35.0, "index"),
        ]
        tech = [MockTechIndicator("BTC", 52.1, 85000.0, 78000.0)]
        research = MockResearchData(
            onchain_advanced=[
                MockOnChainAdvanced("MVRV_Z_Score", 1.8),
                MockOnChainAdvanced("NUPL", 0.45),
                MockOnChainAdvanced("SOPR", 1.02),
                MockOnChainAdvanced("Puell_Multiple", 0.9),
            ],
            pi_cycle=MockPiCycle(25.0),
            etf_flows=MockETFFlows(150000000.0),
            stablecoins=[MockStablecoin(1.5), MockStablecoin(1.0)],
        )
        onchain_text = "- BTC_Funding_Rate: 0.0006 (Coinalyze)"

        snap = build_snapshot_from_pipeline(
            market_data_points=market_points,
            onchain_text=onchain_text,
            key_metrics={},
            research_data=research,
            technical_indicators=tech,
        )

        assert snap.btc_price == 87500.0
        assert snap.eth_price == 3200.0
        assert snap.f_and_g == 45
        assert snap.dxy == 99.4
        assert snap.gold == 2650.0
        assert snap.rsi_btc == 52.1
        assert snap.ma50_btc == 85000.0
        assert snap.mvrv_z == 1.8
        assert snap.nupl == 0.45
        assert snap.sopr == 1.02
        assert snap.puell_multiple == 0.9
        assert snap.pi_cycle_gap_pct == 25.0
        assert snap.etf_net_flow == 150000000.0
        assert snap.stablecoin_total_chg_7d == 2.5
        # Phase 1a defaults
        assert snap.consensus_score == 0.0
        assert snap.consensus_label == "N/A"

    def test_missing_data_graceful_defaults(self):
        """With empty/None data, all fields default to 0.0 or equivalent."""
        snap = build_snapshot_from_pipeline(
            market_data_points=[],
            onchain_text="",
            key_metrics={},
            research_data=None,
            technical_indicators=[],
        )

        assert snap.btc_price == 0.0
        assert snap.eth_price == 0.0
        assert snap.f_and_g == 0
        assert snap.dxy == 0.0
        assert snap.rsi_btc == 0.0
        assert snap.mvrv_z == 0.0
        assert snap.etf_net_flow == 0.0
        assert snap.consensus_score == 0.0
        assert snap.consensus_label == "N/A"
        # Date should still be today
        assert snap.date == datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def test_partial_market_data(self):
        """With some market points missing, available ones are extracted."""

        @dataclass
        class MockMarketPoint:
            symbol: str
            price: float
            data_type: str

        market_points = [
            MockMarketPoint("BTC", 90000.0, "crypto"),
            # No ETH, no F&G, etc.
        ]
        snap = build_snapshot_from_pipeline(
            market_data_points=market_points,
            onchain_text="",
            key_metrics={},
            research_data=None,
            technical_indicators=[],
        )
        assert snap.btc_price == 90000.0
        assert snap.eth_price == 0.0  # not available -> default

    def test_consensus_score_label_passed_to_snapshot(self):
        """G5: consensus_score and consensus_label params override defaults."""
        snap = build_snapshot_from_pipeline(
            market_data_points=[],
            onchain_text="",
            key_metrics={},
            research_data=None,
            technical_indicators=[],
            consensus_score=0.45,
            consensus_label="BULLISH",
        )
        assert snap.consensus_score == 0.45
        assert snap.consensus_label == "BULLISH"

    def test_consensus_defaults_when_not_passed(self):
        """G5: Without consensus params, defaults to 0.0 / 'N/A'."""
        snap = build_snapshot_from_pipeline(
            market_data_points=[],
            onchain_text="",
            key_metrics={},
            research_data=None,
            technical_indicators=[],
        )
        assert snap.consensus_score == 0.0
        assert snap.consensus_label == "N/A"


# --- format_historical_for_llm tests ---


class TestFormatHistoricalForLLM:
    def test_empty_list_returns_empty_string(self):
        """Empty history -> empty string (no prompt pollution)."""
        result = format_historical_for_llm([])
        assert result == ""

    def test_seven_days_format(self):
        """7 days of data -> 7-day section + comparison section."""
        history = []
        for i in range(7):
            date = (datetime(2026, 3, 22, tzinfo=timezone.utc) + timedelta(days=i)).strftime(
                "%Y-%m-%d"
            )
            history.append(
                _make_snapshot(
                    date=date,
                    btc_price=85000 + i * 500,
                    f_and_g=40 + i,
                    rsi_btc=48 + i * 0.5,
                    mvrv_z=1.5 + i * 0.05,
                )
            )

        result = format_historical_for_llm(history)

        # Should contain 7-day section header
        assert "LICH SU 7 NGAY GAN NHAT" in result
        # Should contain comparison section (>= 7 days)
        assert "SO SANH" in result
        # Should contain most recent date (28/03)
        assert "28/03" in result
        # Should contain oldest date (22/03)
        assert "22/03" in result
        # Should contain BTC price
        assert "87,500" in result or "88,000" in result

    def test_one_day_no_comparison(self):
        """1 day of data -> 7-day section only, no 30d comparison."""
        history = [_make_snapshot(date="2026-03-28")]
        result = format_historical_for_llm(history)

        assert "LICH SU 7 NGAY GAN NHAT" in result
        # Only 1 day -> no comparison section (needs >= 7)
        assert "SO SANH" not in result

    def test_thirty_days_format(self):
        """30 days of data -> both sections with meaningful deltas."""
        history = []
        for i in range(30):
            date = (datetime(2026, 2, 27, tzinfo=timezone.utc) + timedelta(days=i)).strftime(
                "%Y-%m-%d"
            )
            history.append(
                _make_snapshot(
                    date=date,
                    btc_price=80000 + i * 250,
                    f_and_g=28 + i,
                    rsi_btc=45 + i * 0.3,
                    mvrv_z=1.4 + i * 0.02,
                )
            )

        result = format_historical_for_llm(history)

        assert "LICH SU 7 NGAY GAN NHAT" in result
        assert "SO SANH 30 NGAY" in result
        # Should show percentage change
        assert "%" in result

    def test_format_date_dd_mm(self):
        """Dates are formatted as DD/MM (Vietnamese style)."""
        history = [_make_snapshot(date="2026-03-28")]
        result = format_historical_for_llm(history)
        assert "28/03" in result

    def test_fg_label_extreme_fear(self):
        """F&G <= 20 is labeled 'Extreme Fear'."""
        history = []
        for i in range(7):
            date = (datetime(2026, 3, 22, tzinfo=timezone.utc) + timedelta(days=i)).strftime(
                "%Y-%m-%d"
            )
            history.append(_make_snapshot(date=date, f_and_g=15))

        result = format_historical_for_llm(history)
        assert "Extreme Fear" in result


# --- save_daily_snapshot tests ---


class TestSaveDailySnapshot:
    def test_save_new_snapshot(self):
        """Saving a new snapshot appends row and returns True."""
        mock_client, mock_ws, _ = _make_mock_sheets(
            existing_tabs=[TAB_NAME],
            all_values=[LICH_SU_METRICS_HEADERS],  # empty tab (header only)
        )
        snap = _make_snapshot(date="2026-03-28")

        result = save_daily_snapshot(mock_client, snap)

        assert result is True
        mock_ws.append_rows.assert_called_once()
        # Verify the row data
        appended_row = mock_ws.append_rows.call_args[0][0][0]
        assert appended_row[0] == "2026-03-28"
        assert appended_row[1] == 87500.0

    def test_duplicate_detection_returns_false(self):
        """If date already exists, returns False and does NOT append."""
        existing_row = _make_snapshot(date="2026-03-28").to_row()
        mock_client, mock_ws, _ = _make_mock_sheets(
            existing_tabs=[TAB_NAME],
            all_values=[LICH_SU_METRICS_HEADERS, existing_row],
        )
        snap = _make_snapshot(date="2026-03-28")

        result = save_daily_snapshot(mock_client, snap)

        assert result is False
        mock_ws.append_rows.assert_not_called()

    def test_creates_tab_if_not_exists(self):
        """If LICH_SU_METRICS tab doesn't exist, it's created with headers."""
        mock_client, mock_ws, mock_ss = _make_mock_sheets(
            existing_tabs=["CAU_HINH"],  # No LICH_SU_METRICS
            all_values=[LICH_SU_METRICS_HEADERS],
        )
        snap = _make_snapshot(date="2026-03-28")

        result = save_daily_snapshot(mock_client, snap)

        assert result is True
        # Should have called add_worksheet
        mock_ss.add_worksheet.assert_called_once_with(
            title=TAB_NAME, rows=100, cols=len(LICH_SU_METRICS_HEADERS)
        )

    def test_save_handles_exception_gracefully(self):
        """On exception, returns False (non-critical, doesn't crash pipeline)."""
        mock_client = MagicMock()
        mock_client._connect.side_effect = Exception("Connection failed")
        snap = _make_snapshot()

        result = save_daily_snapshot(mock_client, snap)
        assert result is False


# --- read_historical tests ---


class TestReadHistorical:
    def test_read_with_data_filters_and_sorts(self):
        """Reads rows, filters by lookback, returns sorted ascending."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        old_date = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%d")

        row_today = _make_snapshot(date=today).to_row()
        row_yesterday = _make_snapshot(date=yesterday, btc_price=86000).to_row()
        row_old = _make_snapshot(date=old_date, btc_price=75000).to_row()

        mock_client, mock_ws, _ = _make_mock_sheets(
            existing_tabs=[TAB_NAME],
            all_values=[LICH_SU_METRICS_HEADERS, row_old, row_yesterday, row_today],
        )

        result = read_historical(mock_client, lookback_days=30)

        # Old date (60 days ago) should be filtered out
        assert len(result) == 2
        # Should be sorted ascending
        assert result[0].date == yesterday
        assert result[1].date == today

    def test_read_empty_tab_returns_empty_list(self):
        """Tab exists but only has header -> empty list."""
        mock_client, _, _ = _make_mock_sheets(
            existing_tabs=[TAB_NAME],
            all_values=[LICH_SU_METRICS_HEADERS],
        )

        result = read_historical(mock_client, lookback_days=30)
        assert result == []

    def test_read_no_tab_returns_empty_list(self):
        """Tab doesn't exist -> empty list (graceful for first run)."""
        mock_client, _, _ = _make_mock_sheets(
            existing_tabs=["CAU_HINH"],  # No LICH_SU_METRICS
        )

        result = read_historical(mock_client, lookback_days=30)
        assert result == []

    def test_read_handles_exception_gracefully(self):
        """On exception, returns empty list (non-critical)."""
        mock_client = MagicMock()
        mock_client._connect.side_effect = Exception("Connection failed")

        result = read_historical(mock_client, lookback_days=30)
        assert result == []

    def test_read_skips_malformed_rows(self):
        """Malformed rows are skipped without crashing."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        good_row = _make_snapshot(date=today).to_row()
        bad_row = ["not-a-date", "abc", "def"]  # will parse but date string passes

        mock_client, _, _ = _make_mock_sheets(
            existing_tabs=[TAB_NAME],
            all_values=[LICH_SU_METRICS_HEADERS, bad_row, good_row],
        )

        # Should not crash
        result = read_historical(mock_client, lookback_days=30)
        # bad_row date "not-a-date" won't pass the >= cutoff filter
        assert len(result) >= 1


# --- Integration: GenerationContext + filter tests ---


class TestGenerationContextHistorical:
    def test_context_accepts_historical_context(self):
        """GenerationContext can be instantiated with historical_context."""
        from cic_daily_report.generators.article_generator import GenerationContext

        ctx = GenerationContext(historical_context="=== LICH SU ===\nBTC went up")
        assert ctx.historical_context == "=== LICH SU ===\nBTC went up"

    def test_context_defaults_empty_historical(self):
        """historical_context defaults to empty string."""
        from cic_daily_report.generators.article_generator import GenerationContext

        ctx = GenerationContext()
        assert ctx.historical_context == ""

    def test_filter_l1_excludes_historical(self):
        """L1 filter excludes historical_context (beginners don't need it)."""
        from cic_daily_report.generators.article_generator import (
            GenerationContext,
            _filter_data_for_tier,
        )

        ctx = GenerationContext(
            historical_context="=== LICH SU ===\nSome history",
            market_data="BTC: $87,500",
        )
        filtered = _filter_data_for_tier("L1", ctx, "")
        assert filtered["historical_context"] == ""

    def test_filter_l2_excludes_historical(self):
        """L2 filter excludes historical_context."""
        from cic_daily_report.generators.article_generator import (
            GenerationContext,
            _filter_data_for_tier,
        )

        ctx = GenerationContext(
            historical_context="=== LICH SU ===\nSome history",
            market_data="BTC: $87,500",
        )
        filtered = _filter_data_for_tier("L2", ctx, "")
        assert filtered["historical_context"] == ""

    def test_filter_l3_includes_historical(self):
        """L3 filter includes historical_context (analytical tier)."""
        from cic_daily_report.generators.article_generator import (
            GenerationContext,
            _filter_data_for_tier,
        )

        hist = "=== LICH SU ===\nSome history"
        ctx = GenerationContext(
            historical_context=hist,
            market_data="BTC: $87,500",
            news_summary="Some news",
        )
        filtered = _filter_data_for_tier("L3", ctx, "")
        assert filtered["historical_context"] == hist

    def test_filter_l4_includes_historical(self):
        """L4 filter includes historical_context."""
        from cic_daily_report.generators.article_generator import (
            GenerationContext,
            _filter_data_for_tier,
        )

        hist = "=== LICH SU ===\nSome history"
        ctx = GenerationContext(
            historical_context=hist,
            market_data="BTC: $87,500",
            news_summary="Some news",
        )
        filtered = _filter_data_for_tier("L4", ctx, "")
        assert filtered["historical_context"] == hist

    def test_filter_l5_includes_historical(self):
        """L5 filter includes historical_context."""
        from cic_daily_report.generators.article_generator import (
            GenerationContext,
            _filter_data_for_tier,
        )

        hist = "=== LICH SU ===\nSome history"
        ctx = GenerationContext(
            historical_context=hist,
            market_data="BTC: $87,500",
            news_summary="Some news",
        )
        filtered = _filter_data_for_tier("L5", ctx, "")
        assert filtered["historical_context"] == hist
