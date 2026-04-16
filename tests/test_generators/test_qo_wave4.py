"""Tests for Wave 4 tasks (QO.37, QO.38, QO.41, QO.48).

Covers:
- QO.37: Expanded news content (2000 chars, 50 articles)
- QO.38: Cross-tier consistency check configurable toggle
- QO.41: Price unification from Sentinel consensus
- QO.48: Headline price validation against PriceSnapshot
"""

from __future__ import annotations

from unittest.mock import MagicMock

from cic_daily_report.collectors.cryptopanic_client import (
    MAX_ARTICLES_PER_FETCH,
    MAX_CONTENT_CHARS,
)
from cic_daily_report.collectors.market_data import MarketDataPoint, PriceSnapshot
from cic_daily_report.collectors.rss_collector import (
    MAX_ARTICLES_PER_FEED,
    MAX_SUMMARY_CHARS,
)
from cic_daily_report.generators.quality_gate import (
    DEFAULT_CROSS_TIER_CHECK_ENABLED,
    PRICE_DEVIATION_THRESHOLD,
    PriceValidationResult,
    is_cross_tier_check_enabled,
    validate_headline_prices,
)
from cic_daily_report.storage.sentinel_reader import (
    SentinelData,
    SentinelPrice,
    SentinelReader,
)

# ---------------------------------------------------------------------------
# QO.37: Expanded news content
# ---------------------------------------------------------------------------


class TestQO37ExpandedContent:
    """QO.37: Content limits increased for richer context."""

    def test_rss_summary_max_chars_is_2000(self):
        """RSS summary limit increased from 500 to 2000."""
        assert MAX_SUMMARY_CHARS == 2000

    def test_rss_articles_per_feed_is_50(self):
        """RSS articles per feed increased from 20 to 50."""
        assert MAX_ARTICLES_PER_FEED == 50

    def test_cryptopanic_content_chars_is_2000(self):
        """CryptoPanic content limit increased from 500 to 2000."""
        assert MAX_CONTENT_CHARS == 2000

    def test_cryptopanic_articles_per_fetch_is_50(self):
        """CryptoPanic articles per fetch increased from 30 to 50."""
        assert MAX_ARTICLES_PER_FETCH == 50


# ---------------------------------------------------------------------------
# QO.38: Cross-tier consistency check toggle
# ---------------------------------------------------------------------------


class TestQO38CrossTierToggle:
    """QO.38: CROSS_TIER_CHECK_ENABLED configurable in CAU_HINH."""

    def test_default_is_true(self):
        """Default should be True — cross-tier check is active."""
        assert DEFAULT_CROSS_TIER_CHECK_ENABLED is True

    def test_enabled_without_config_loader(self):
        """Without config_loader, returns default (True)."""
        assert is_cross_tier_check_enabled(None) is True

    def test_enabled_from_config_true(self):
        """Config returns 'TRUE' → check enabled."""
        mock_config = MagicMock()
        mock_config.get_setting_bool.return_value = True
        assert is_cross_tier_check_enabled(mock_config) is True
        mock_config.get_setting_bool.assert_called_once_with("CROSS_TIER_CHECK_ENABLED", True)

    def test_disabled_from_config_false(self):
        """Config returns False → check disabled."""
        mock_config = MagicMock()
        mock_config.get_setting_bool.return_value = False
        assert is_cross_tier_check_enabled(mock_config) is False

    def test_config_error_returns_default(self):
        """Config throws exception → returns default (True)."""
        mock_config = MagicMock()
        mock_config.get_setting_bool.side_effect = Exception("Sheets error")
        assert is_cross_tier_check_enabled(mock_config) is True


# ---------------------------------------------------------------------------
# QO.41: Price unification from Sentinel consensus
# ---------------------------------------------------------------------------


def _mock_worksheet(rows: list[list[str]]) -> MagicMock:
    ws = MagicMock()
    ws.get_all_values.return_value = rows
    return ws


def _mock_spreadsheet(worksheets: dict[str, list[list[str]]]) -> MagicMock:
    ss = MagicMock()

    def worksheet_side_effect(name: str):
        import gspread

        if name not in worksheets:
            raise gspread.exceptions.WorksheetNotFound(name)
        return _mock_worksheet(worksheets[name])

    ss.worksheet.side_effect = worksheet_side_effect
    return ss


def _reader_with_mock(worksheets: dict[str, list[list[str]]]) -> SentinelReader:
    reader = SentinelReader(credentials_b64="fake", sentinel_spreadsheet_id="fake_id")
    reader._spreadsheet = _mock_spreadsheet(worksheets)
    return reader


class TestQO41SentinelPrice:
    """QO.41: SentinelPrice dataclass tests."""

    def test_sentinel_price_defaults(self):
        sp = SentinelPrice(symbol="BTC", price=87500.0, change_24h=3.2)
        assert sp.symbol == "BTC"
        assert sp.price == 87500.0
        assert sp.change_24h == 3.2
        assert sp.source == "sentinel"

    def test_sentinel_data_has_consensus_prices_field(self):
        """SentinelData includes consensus_prices field (default empty)."""
        data = SentinelData()
        assert data.consensus_prices == []

    def test_sentinel_data_with_prices(self):
        prices = [SentinelPrice("BTC", 87500.0, 3.2), SentinelPrice("ETH", 3200.0, 2.1)]
        data = SentinelData(consensus_prices=prices)
        assert len(data.consensus_prices) == 2
        assert data.consensus_prices[0].symbol == "BTC"


class TestQO41ReadPrices:
    """QO.41: SentinelReader.read_prices() tests."""

    def test_read_prices_basic(self):
        """Read prices from scoring engine tab with PRICE column."""
        rows = [
            ["SYMBOL", "EMA34", "PRICE", "CHANGE_24H"],
            ["BTC", "85000", "87500", "3.2"],
            ["ETH", "3100", "3200", "2.1"],
        ]
        reader = _reader_with_mock({"03_SCORING_ENGINE": rows})
        prices = reader.read_prices()
        assert len(prices) == 2
        assert prices[0].symbol == "BTC"
        assert prices[0].price == 87500.0
        assert prices[0].change_24h == 3.2
        assert prices[1].symbol == "ETH"
        assert prices[1].price == 3200.0

    def test_read_prices_no_price_column(self):
        """No PRICE column → returns empty list (graceful degradation)."""
        rows = [
            ["SYMBOL", "EMA34", "EMA89"],
            ["BTC", "85000", "83000"],
        ]
        reader = _reader_with_mock({"03_SCORING_ENGINE": rows})
        prices = reader.read_prices()
        assert prices == []

    def test_read_prices_skips_zero_price(self):
        """Rows with price=0 should be skipped."""
        rows = [
            ["SYMBOL", "PRICE", "CHANGE_24H"],
            ["BTC", "87500", "3.2"],
            ["DEAD_COIN", "0", "0"],
        ]
        reader = _reader_with_mock({"03_SCORING_ENGINE": rows})
        prices = reader.read_prices()
        assert len(prices) == 1
        assert prices[0].symbol == "BTC"

    def test_read_prices_alternative_column_names(self):
        """Vietnamese column names (GIA, THAY_DOI_24H) should work."""
        rows = [
            ["MA_COIN", "GIA", "THAY_DOI_24H"],
            ["SOL", "145.5", "-1.5"],
        ]
        reader = _reader_with_mock({"03_SCORING_ENGINE": rows})
        prices = reader.read_prices()
        assert len(prices) == 1
        assert prices[0].symbol == "SOL"
        assert prices[0].price == 145.5
        assert prices[0].change_24h == -1.5

    def test_read_prices_no_change_column(self):
        """Missing CHANGE_24H column → change defaults to 0.0."""
        rows = [
            ["SYMBOL", "PRICE"],
            ["BTC", "87500"],
        ]
        reader = _reader_with_mock({"03_SCORING_ENGINE": rows})
        prices = reader.read_prices()
        assert len(prices) == 1
        assert prices[0].change_24h == 0.0

    def test_read_prices_empty_tab(self):
        """Empty tab → returns empty list."""
        rows = [["SYMBOL", "PRICE"]]
        reader = _reader_with_mock({"03_SCORING_ENGINE": rows})
        prices = reader.read_prices()
        assert prices == []


class TestQO41PriceSnapshotMerge:
    """QO.41: Sentinel prices merged into PriceSnapshot."""

    def test_sentinel_prices_override_market_data(self):
        """Sentinel consensus price should override same-symbol market_data."""
        market_data = [
            MarketDataPoint("BTC", 86000.0, 2.0, 1e9, 1.7e12, "crypto", "CoinLore"),
            MarketDataPoint("DXY", 104.2, -0.4, 0, 0, "macro", "FRED"),
        ]
        sentinel_prices = [
            SentinelPrice("BTC", 87500.0, 3.2),
        ]

        # WHY: Build merged data the same way daily_pipeline does
        sentinel_symbols = {sp.symbol for sp in sentinel_prices}
        sentinel_points = [
            MarketDataPoint(
                symbol=sp.symbol,
                price=sp.price,
                change_24h=sp.change_24h,
                volume_24h=0.0,
                market_cap=0.0,
                data_type="crypto",
                source="sentinel_consensus",
            )
            for sp in sentinel_prices
            if sp.price > 0
        ]
        non_sentinel = [dp for dp in market_data if dp.symbol not in sentinel_symbols]
        merged = sentinel_points + non_sentinel

        snapshot = PriceSnapshot(market_data=merged)
        # BTC should come from Sentinel
        assert snapshot.btc_price == 87500.0
        btc_dp = snapshot.get_data_point("BTC")
        assert btc_dp is not None
        assert btc_dp.source == "sentinel_consensus"
        # DXY should still come from market_data
        dxy = snapshot.get_data_point("DXY")
        assert dxy is not None
        assert dxy.source == "FRED"

    def test_empty_sentinel_prices_uses_market_data(self):
        """Empty sentinel_prices → snapshot uses market_data only."""
        market_data = [
            MarketDataPoint("BTC", 86000.0, 2.0, 1e9, 1.7e12, "crypto", "CoinLore"),
        ]
        snapshot = PriceSnapshot(market_data=market_data)
        assert snapshot.btc_price == 86000.0


# ---------------------------------------------------------------------------
# QO.48: Headline price validation
# ---------------------------------------------------------------------------


def _make_snapshot(prices: dict[str, float]) -> PriceSnapshot:
    """Build a PriceSnapshot from a {symbol: price} dict."""
    points = [
        MarketDataPoint(
            symbol=sym,
            price=price,
            change_24h=0.0,
            volume_24h=0.0,
            market_cap=0.0,
            data_type="crypto",
            source="test",
        )
        for sym, price in prices.items()
    ]
    return PriceSnapshot(market_data=points)


class TestQO48HeadlinePriceValidation:
    """QO.48: Validate prices in generated text against PriceSnapshot."""

    def test_threshold_is_5_percent(self):
        """Default threshold is 5%."""
        assert PRICE_DEVIATION_THRESHOLD == 0.05

    def test_accurate_prices_pass(self):
        """Text with accurate prices → passes."""
        snapshot = _make_snapshot({"BTC": 87500.0, "ETH": 3200.0})
        content = "BTC đang giao dịch ở $87,500 trong khi ETH đạt $3,200."
        result = validate_headline_prices(content, snapshot)
        assert result.passed is True
        assert result.deviation_count == 0
        assert result.checked_count == 2

    def test_minor_deviation_passes(self):
        """Price within 5% threshold → passes."""
        snapshot = _make_snapshot({"BTC": 87500.0})
        # 87500 * 1.04 = 91000 → within 5%
        content = "BTC tăng lên $91,000 trong phiên giao dịch."
        result = validate_headline_prices(content, snapshot)
        assert result.passed is True

    def test_major_deviation_warns(self):
        """Price deviating >5% from snapshot → warning."""
        snapshot = _make_snapshot({"BTC": 87500.0})
        # 95000 is ~8.6% deviation
        content = "BTC tăng mạnh lên $95,000 trong phiên giao dịch."
        result = validate_headline_prices(content, snapshot)
        assert result.passed is False
        assert result.deviation_count == 1
        assert len(result.warnings) == 1
        assert "BTC" in result.warnings[0]
        assert "95,000" in result.warnings[0]

    def test_no_price_snapshot_passes(self):
        """No PriceSnapshot → skip validation, pass."""
        result = validate_headline_prices("BTC at $87,500", None)
        assert result.passed is True
        assert result.checked_count == 0

    def test_no_content_passes(self):
        """Empty content → skip validation, pass."""
        snapshot = _make_snapshot({"BTC": 87500.0})
        result = validate_headline_prices("", snapshot)
        assert result.passed is True

    def test_no_price_mentions_passes(self):
        """Content without price patterns → passes with 0 checks."""
        snapshot = _make_snapshot({"BTC": 87500.0})
        content = "Thị trường hôm nay tiếp tục xu hướng tăng."
        result = validate_headline_prices(content, snapshot)
        assert result.passed is True
        assert result.checked_count == 0

    def test_name_to_symbol_mapping(self):
        """Full names like 'Bitcoin' should map to 'BTC'."""
        snapshot = _make_snapshot({"BTC": 87500.0})
        content = "Bitcoin đã vượt $87,500 trong phiên hôm nay."
        result = validate_headline_prices(content, snapshot)
        assert result.passed is True
        assert result.checked_count == 1

    def test_ethereum_name_mapping(self):
        """'Ethereum' maps to 'ETH'."""
        snapshot = _make_snapshot({"ETH": 3200.0})
        content = "Ethereum đạt mốc $3,200."
        result = validate_headline_prices(content, snapshot)
        assert result.passed is True
        assert result.checked_count == 1

    def test_multiple_assets_mixed_results(self):
        """Multiple assets — some accurate, some deviated."""
        snapshot = _make_snapshot({"BTC": 87500.0, "ETH": 3200.0})
        # BTC accurate, ETH off by ~15.6%
        content = "BTC ở mức $87,500. ETH tụt xuống $2,700."
        result = validate_headline_prices(content, snapshot)
        assert result.passed is False
        assert result.checked_count == 2
        assert result.deviation_count == 1
        assert any("ETH" in w for w in result.warnings)

    def test_symbol_not_in_snapshot_skipped(self):
        """Symbol mentioned but not in snapshot → skipped, not flagged."""
        snapshot = _make_snapshot({"BTC": 87500.0})
        content = "SOL reaches $145 while BTC holds $87,500."
        result = validate_headline_prices(content, snapshot)
        assert result.passed is True
        # Only BTC should be checked (SOL not in snapshot)
        assert result.checked_count == 1

    def test_returns_price_validation_result_type(self):
        """Verify return type is PriceValidationResult."""
        result = validate_headline_prices("", None)
        assert isinstance(result, PriceValidationResult)
