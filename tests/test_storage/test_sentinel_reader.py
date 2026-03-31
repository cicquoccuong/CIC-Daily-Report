"""Tests for storage/sentinel_reader.py — all mocked (P1.12)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from cic_daily_report.storage.sentinel_reader import (
    SentinelData,
    SentinelFAScore,
    SentinelReader,
    SentinelSeason,
    SonicRZones,
    _is_season_stale,
    _safe_float,
    format_sentinel_for_llm,
)

MODULE = "cic_daily_report.storage.sentinel_reader"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


SONICR_HEADER = [
    "SYMBOL",
    "EMA34",
    "EMA89",
    "EMA200",
    "EMA610",
    "SONICR_TREND",
    "FIB_ADCA_ZONE",
    "RSI_D1",
]

FA_HEADER = [
    "SYMBOL",
    "TOTAL_SCORE",
    "CLASSIFICATION",
    "CATEGORY",
    "SUGGESTED_LEVEL",
]


def _mock_worksheet(rows: list[list[str]]) -> MagicMock:
    """Create a mock gspread Worksheet that returns the given rows."""
    ws = MagicMock()
    ws.get_all_values.return_value = rows
    return ws


def _mock_spreadsheet(worksheets: dict[str, list[list[str]]]) -> MagicMock:
    """Create a mock gspread Spreadsheet with named worksheets."""
    ss = MagicMock()

    def worksheet_side_effect(name: str):
        import gspread

        if name not in worksheets:
            raise gspread.exceptions.WorksheetNotFound(name)
        return _mock_worksheet(worksheets[name])

    ss.worksheet.side_effect = worksheet_side_effect
    return ss


def _reader_with_mock_ss(worksheets: dict[str, list[list[str]]]) -> SentinelReader:
    """Create a SentinelReader connected to a mock spreadsheet."""
    reader = SentinelReader(credentials_b64="fake", sentinel_spreadsheet_id="fake_id")
    reader._spreadsheet = _mock_spreadsheet(worksheets)
    return reader


# ---------------------------------------------------------------------------
# Tests: Defaults
# ---------------------------------------------------------------------------


class TestSentinelDataDefaults:
    def test_empty_sentinel_data(self):
        """SentinelData with all defaults has None/empty fields."""
        data = SentinelData()
        assert data.season is None
        assert data.sonicr_btc is None
        assert data.sonicr_eth is None
        assert data.fa_top_movers == []
        assert data.registry == []
        assert data.nq05_blacklist == []
        assert data.read_timestamp == ""
        assert data.stale_flags == []


# ---------------------------------------------------------------------------
# Tests: read_season
# ---------------------------------------------------------------------------


class TestReadSeason:
    def test_read_season_success(self):
        """Read season data from CONFIG tab with expected keys."""
        now_iso = datetime.now(timezone.utc).isoformat()
        config_rows = [
            ["Key", "Value"],
            ["OFFICIAL_SEASON", "MUA_XUAN"],
            ["SEASON_HEAT_SCORE", "65.5"],
            ["SEASON_CONFIDENCE", "0.85"],
            ["SEASON_DETAIL", "Early spring signals detected"],
            ["SEASON_LAST_UPDATE", now_iso],
        ]
        reader = _reader_with_mock_ss({"CONFIG": config_rows})
        season = reader.read_season()

        assert season is not None
        assert season.phase == "MUA_XUAN"
        assert season.heat_score == 65.5
        assert season.confidence == 0.85
        assert season.detail == "Early spring signals detected"
        assert season.last_update == now_iso

    def test_read_season_missing_phase(self):
        """Returns None if OFFICIAL_SEASON key is missing."""
        config_rows = [
            ["Key", "Value"],
            ["SEASON_HEAT_SCORE", "50"],
        ]
        reader = _reader_with_mock_ss({"CONFIG": config_rows})
        assert reader.read_season() is None

    def test_read_season_stale(self):
        """Season older than 1 hour is flagged as stale."""
        old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        assert _is_season_stale(old_time) is True

    def test_read_season_fresh(self):
        """Season less than 1 hour old is not stale."""
        fresh_time = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        assert _is_season_stale(fresh_time) is False

    def test_read_season_empty_last_update(self):
        """Empty last_update string is treated as stale."""
        assert _is_season_stale("") is True

    def test_read_season_invalid_date(self):
        """Invalid date format is treated as stale."""
        assert _is_season_stale("not-a-date") is True


# ---------------------------------------------------------------------------
# Tests: read_sonicr
# ---------------------------------------------------------------------------


class TestReadSonicR:
    def test_read_sonicr_success(self):
        """Read SonicR zones for BTC from 03_SCORING_ENGINE tab."""
        rows = [
            SONICR_HEADER,
            ["BTC", "68000", "65000", "60000", "45000", "BULLISH", "ACCUMULATION", "55.3"],
            ["ETH", "3400", "3200", "3000", "2500", "NEUTRAL", "NEUTRAL", "48.7"],
        ]
        reader = _reader_with_mock_ss({"03_SCORING_ENGINE": rows})
        result = reader.read_sonicr("BTC")

        assert result is not None
        assert result.symbol == "BTC"
        assert result.ema34 == 68000.0
        assert result.ema89 == 65000.0
        assert result.ema200 == 60000.0
        assert result.ema610 == 45000.0
        assert result.sonicr_trend == "BULLISH"
        assert result.fib_adca_zone == "ACCUMULATION"
        assert result.rsi_d1 == 55.3

    def test_read_sonicr_not_found(self):
        """Returns None if symbol is not in the tab."""
        rows = [
            SONICR_HEADER,
            ["BTC", "68000", "65000", "60000", "45000", "BULLISH", "ACC", "55.3"],
        ]
        reader = _reader_with_mock_ss({"03_SCORING_ENGINE": rows})
        assert reader.read_sonicr("SOL") is None

    def test_read_sonicr_case_insensitive(self):
        """Symbol lookup is case-insensitive."""
        rows = [
            SONICR_HEADER,
            ["btc", "68000", "65000", "60000", "45000", "BULLISH", "ACC", "55.3"],
        ]
        reader = _reader_with_mock_ss({"03_SCORING_ENGINE": rows})
        result = reader.read_sonicr("BTC")
        assert result is not None
        assert result.symbol == "BTC"

    def test_read_sonicr_empty_tab(self):
        """Returns None if tab has no data rows."""
        rows = []
        reader = _reader_with_mock_ss({"03_SCORING_ENGINE": rows})
        assert reader.read_sonicr("BTC") is None


# ---------------------------------------------------------------------------
# Tests: read_fa_scores
# ---------------------------------------------------------------------------


class TestReadFAScores:
    def test_read_fa_scores_sorted(self):
        """FA scores are returned sorted by total_score descending."""
        rows = [
            ["SYMBOL", "TOTAL_SCORE", "CLASSIFICATION", "CATEGORY", "SUGGESTED_LEVEL"],
            ["BTC", "75", "TRU_COT", "Layer 1", "L1"],
            ["SHIB", "15", "RUI_RO", "Meme", "L5"],
            ["ETH", "70", "TRU_COT", "Layer 1", "L1"],
            ["SOL", "55", "TIEM_NANG", "Layer 1", "L3"],
        ]
        reader = _reader_with_mock_ss({"06_FA_SCORES": rows})
        result = reader.read_fa_scores(top_n=3)

        assert len(result) == 3
        assert result[0].symbol == "BTC"
        assert result[0].total_score == 75.0
        assert result[1].symbol == "ETH"
        assert result[1].total_score == 70.0
        assert result[2].symbol == "SOL"
        assert result[2].total_score == 55.0

    def test_read_fa_scores_empty(self):
        """Returns empty list if tab has only header."""
        rows = [["SYMBOL", "TOTAL_SCORE", "CLASSIFICATION", "CATEGORY", "SUGGESTED_LEVEL"]]
        reader = _reader_with_mock_ss({"06_FA_SCORES": rows})
        assert reader.read_fa_scores() == []


# ---------------------------------------------------------------------------
# Tests: read_registry
# ---------------------------------------------------------------------------


class TestReadRegistry:
    def test_read_registry_success(self):
        """Read all coins from 01_ASSET_IDENTITY tab."""
        rows = [
            ["CIC_ID", "SYMBOL", "NAME", "TIER", "FA_STATUS", "CIC_ACTION"],
            ["CIC001", "BTC", "Bitcoin", "L1", "ACTIVE", "theo-doi"],
            ["CIC002", "ETH", "Ethereum", "L1", "ACTIVE", "tich-luy"],
        ]
        reader = _reader_with_mock_ss({"01_ASSET_IDENTITY": rows})
        result = reader.read_registry()

        assert len(result) == 2
        assert result[0].cic_id == "CIC001"
        assert result[0].symbol == "BTC"
        assert result[0].name == "Bitcoin"
        assert result[0].tier == "L1"
        assert result[1].symbol == "ETH"

    def test_read_registry_skips_empty_symbol(self):
        """Rows with empty symbol are skipped."""
        rows = [
            ["CIC_ID", "SYMBOL", "NAME", "TIER", "FA_STATUS", "CIC_ACTION"],
            ["CIC001", "BTC", "Bitcoin", "L1", "ACTIVE", "theo-doi"],
            ["CIC003", "", "", "", "", ""],
        ]
        reader = _reader_with_mock_ss({"01_ASSET_IDENTITY": rows})
        assert len(reader.read_registry()) == 1


# ---------------------------------------------------------------------------
# Tests: read_nq05_blacklist
# ---------------------------------------------------------------------------


class TestReadNQ05Blacklist:
    def test_read_nq05_success(self):
        """Read NQ05 terms from NQ05_BLACKLIST tab."""
        rows = [
            ["TERM", "LANGUAGE", "CATEGORY", "SEVERITY", "SAFE_ALTERNATIVE", "SOURCE_SYSTEM"],
            ["mua ngay", "VI", "buy_signal", "BLOCK", "xem xet", "sentinel"],
            ["buy now", "EN", "buy_signal", "BLOCK", "consider", "shared"],
        ]
        reader = _reader_with_mock_ss({"NQ05_BLACKLIST": rows})
        result = reader.read_nq05_blacklist()

        assert len(result) == 2
        assert result[0].term == "mua ngay"
        assert result[0].language == "VI"
        assert result[0].severity == "BLOCK"
        assert result[1].term == "buy now"
        assert result[1].source_system == "shared"

    def test_read_nq05_tab_missing(self):
        """Returns empty list if NQ05_BLACKLIST tab doesn't exist."""
        # _reader_with_mock_ss raises WorksheetNotFound for missing tabs
        reader = _reader_with_mock_ss({})  # no tabs at all
        result = reader.read_nq05_blacklist()
        assert result == []

    def test_read_nq05_defaults(self):
        """Missing language/severity/source_system get default values."""
        rows = [
            ["TERM", "LANGUAGE", "CATEGORY", "SEVERITY", "SAFE_ALTERNATIVE", "SOURCE_SYSTEM"],
            ["sell", "", "sell_signal", "", "", ""],
        ]
        reader = _reader_with_mock_ss({"NQ05_BLACKLIST": rows})
        result = reader.read_nq05_blacklist()

        assert len(result) == 1
        assert result[0].language == "VI"  # default
        assert result[0].severity == "BLOCK"  # default
        assert result[0].source_system == "sentinel"  # default


# ---------------------------------------------------------------------------
# Tests: read_all
# ---------------------------------------------------------------------------


class TestReadAll:
    def test_read_all_partial_failure(self):
        """One tab fails, others still return data."""
        now_iso = datetime.now(timezone.utc).isoformat()
        reader = SentinelReader(credentials_b64="fake", sentinel_spreadsheet_id="fake_id")

        ss = MagicMock()

        # CONFIG tab works
        config_ws = _mock_worksheet(
            [
                ["Key", "Value"],
                ["OFFICIAL_SEASON", "MUA_DONG"],
                ["SEASON_HEAT_SCORE", "20"],
                ["SEASON_CONFIDENCE", "0.9"],
                ["SEASON_DETAIL", "Winter"],
                ["SEASON_LAST_UPDATE", now_iso],
            ]
        )

        # 03_SCORING_ENGINE tab raises error
        scoring_ws = MagicMock()
        scoring_ws.get_all_values.side_effect = Exception("API error")

        # 06_FA_SCORES — empty
        fa_ws = _mock_worksheet([FA_HEADER])

        # 01_ASSET_IDENTITY — works
        registry_ws = _mock_worksheet(
            [
                ["CIC_ID", "SYMBOL", "NAME", "TIER", "FA_STATUS", "CIC_ACTION"],
                ["CIC001", "BTC", "Bitcoin", "L1", "ACTIVE", "theo-doi"],
            ]
        )

        import gspread

        def worksheet_side_effect(name):
            if name == "CONFIG":
                return config_ws
            if name == "03_SCORING_ENGINE":
                return scoring_ws
            if name == "06_FA_SCORES":
                return fa_ws
            if name == "01_ASSET_IDENTITY":
                return registry_ws
            raise gspread.exceptions.WorksheetNotFound(name)

        ss.worksheet.side_effect = worksheet_side_effect
        reader._spreadsheet = ss

        result = reader.read_all()

        # Season should work
        assert result.season is not None
        assert result.season.phase == "MUA_DONG"

        # SonicR BTC should fail gracefully
        assert result.sonicr_btc is None
        assert "sonicr_btc_error" in result.stale_flags

        # SonicR ETH also fails (same tab)
        assert result.sonicr_eth is None
        assert "sonicr_eth_error" in result.stale_flags

        # Registry should work
        assert len(result.registry) == 1
        assert result.registry[0].symbol == "BTC"

        # NQ05 tab missing → empty
        assert result.nq05_blacklist == []

        assert result.read_timestamp != ""

    def test_no_credentials(self):
        """Returns empty SentinelData with sentinel_unreachable flag."""
        reader = SentinelReader(credentials_b64="", sentinel_spreadsheet_id="")
        result = reader.read_all()

        assert result.season is None
        assert result.sonicr_btc is None
        assert result.fa_top_movers == []
        assert result.registry == []
        assert result.nq05_blacklist == []
        assert "sentinel_unreachable" in result.stale_flags

    def test_read_all_season_stale_flag(self):
        """Season older than 1h gets season_stale flag."""
        old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        reader = SentinelReader(credentials_b64="fake", sentinel_spreadsheet_id="fake_id")

        ss = MagicMock()
        config_ws = _mock_worksheet(
            [
                ["Key", "Value"],
                ["OFFICIAL_SEASON", "MUA_HE"],
                ["SEASON_HEAT_SCORE", "80"],
                ["SEASON_CONFIDENCE", "0.7"],
                ["SEASON_DETAIL", "Summer"],
                ["SEASON_LAST_UPDATE", old_time],
            ]
        )

        import gspread

        def worksheet_side_effect(name):
            if name == "CONFIG":
                return config_ws
            raise gspread.exceptions.WorksheetNotFound(name)

        ss.worksheet.side_effect = worksheet_side_effect
        reader._spreadsheet = ss

        result = reader.read_all()
        assert result.season is not None
        assert "season_stale" in result.stale_flags


# ---------------------------------------------------------------------------
# Tests: format_sentinel_for_llm
# ---------------------------------------------------------------------------


class TestFormatSentinelForLLM:
    def test_format_with_data(self):
        """Format includes season, SonicR, and FA data."""
        data = SentinelData(
            season=SentinelSeason(
                phase="MUA_XUAN",
                heat_score=65.0,
                confidence=0.85,
                detail="Spring signals",
                last_update="2026-03-30T00:00:00Z",
            ),
            sonicr_btc=SonicRZones(
                symbol="BTC",
                ema34=68000,
                ema89=65000,
                ema200=60000,
                ema610=45000,
                sonicr_trend="BULLISH",
                fib_adca_zone="ACC",
                rsi_d1=55.0,
            ),
            fa_top_movers=[
                SentinelFAScore(
                    symbol="BTC",
                    total_score=75.0,
                    classification="TRU_COT",
                    category="L1",
                    suggested_level="L1",
                ),
            ],
            read_timestamp="2026-03-30T00:00:00Z",
        )
        text = format_sentinel_for_llm(data)
        assert "DU LIEU TU CIC SENTINEL" in text
        assert "MUA_XUAN" in text
        assert "BULLISH" in text
        assert "BTC: 75.0/80" in text

    def test_format_empty_data(self):
        """Empty/unreachable data returns empty string."""
        data = SentinelData(stale_flags=["sentinel_unreachable"])
        assert format_sentinel_for_llm(data) == ""

    def test_format_stale_season_note(self):
        """Stale season gets (DU LIEU CU) note."""
        data = SentinelData(
            season=SentinelSeason(
                phase="MUA_DONG",
                heat_score=20.0,
                confidence=0.5,
                detail="",
                last_update="old",
            ),
            stale_flags=["season_stale"],
            read_timestamp="now",
        )
        text = format_sentinel_for_llm(data)
        assert "DU LIEU CU" in text


# ---------------------------------------------------------------------------
# Tests: Helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_safe_float_valid(self):
        assert _safe_float("42.5") == 42.5

    def test_safe_float_comma(self):
        assert _safe_float("1,234.56") == 1234.56

    def test_safe_float_empty(self):
        assert _safe_float("") == 0.0

    def test_safe_float_invalid(self):
        assert _safe_float("abc") == 0.0
