"""Tests for core/coin_mapping.py — unified name↔ticker resolution."""

from cic_daily_report.core.coin_mapping import (
    _FALLBACK_NAME_TO_TICKER,
    NAME_TO_TICKER,
    PROJECT_NAMES,
    _rebuild_derived,
    extract_coins_from_text,
    load_from_config,
    load_from_sentinel,
    normalize_to_ticker,
)
from cic_daily_report.storage.sentinel_reader import SentinelCoin


class TestNormalizeToTicker:
    def test_project_name_ripple(self):
        assert normalize_to_ticker("Ripple") == "XRP"

    def test_project_name_cardano(self):
        assert normalize_to_ticker("Cardano") == "ADA"

    def test_project_name_case_insensitive(self):
        assert normalize_to_ticker("BITCOIN") == "BTC"
        assert normalize_to_ticker("ethereum") == "ETH"

    def test_ticker_resolves_to_canonical(self):
        assert normalize_to_ticker("btc") == "BTC"
        assert normalize_to_ticker("SOL") == "SOL"

    def test_unknown_returns_none(self):
        assert normalize_to_ticker("unknown") is None
        assert normalize_to_ticker("") is None

    def test_whitespace_trimmed(self):
        assert normalize_to_ticker("  Ripple  ") == "XRP"


class TestExtractCoinsFromText:
    def test_uppercase_tickers(self):
        result = extract_coins_from_text("BTC surges as ETH follows")
        assert "BTC" in result
        assert "ETH" in result

    def test_project_names(self):
        result = extract_coins_from_text("Ripple partners with bank, Cardano summit next")
        assert "XRP" in result
        assert "ADA" in result

    def test_mixed_names_and_tickers(self):
        result = extract_coins_from_text("Bitcoin hits $100K, ETH also rises")
        assert "BTC" in result
        assert "ETH" in result

    def test_known_coins_filter(self):
        """Only returns coins in the known_coins whitelist."""
        result = extract_coins_from_text("BTC and ETH and SOL surge", known_coins={"BTC", "ETH"})
        assert result == {"BTC", "ETH"}

    def test_no_matches(self):
        assert extract_coins_from_text("NBA draft picks announced") == set()

    def test_case_insensitive_project_names(self):
        result = extract_coins_from_text("dogecoin and AVALANCHE news")
        assert "DOGE" in result
        assert "AVAX" in result

    def test_near_protocol(self):
        """'near' and 'near protocol' both resolve to NEAR."""
        result = extract_coins_from_text("Near Protocol announces upgrade")
        assert "NEAR" in result


class TestProjectNames:
    def test_all_names_lowercase(self):
        for name in PROJECT_NAMES:
            assert name == name.lower(), f"PROJECT_NAMES should be lowercase: {name}"

    def test_major_names_present(self):
        for name in ("bitcoin", "ethereum", "ripple", "cardano", "solana", "dogecoin"):
            assert name in PROJECT_NAMES, f"Missing major project name: {name}"


class TestNameToTickerConsistency:
    def test_values_are_uppercase(self):
        for name, ticker in NAME_TO_TICKER.items():
            assert ticker == ticker.upper(), f"Ticker should be uppercase: {name} → {ticker}"


class TestLoadFromConfig:
    """v0.28.0: Config-driven mapping from DANH_SACH_COIN 'Tên dự án' column."""

    def setup_method(self):
        """Reset NAME_TO_TICKER to fallback-only before each test."""
        NAME_TO_TICKER.clear()
        NAME_TO_TICKER.update(_FALLBACK_NAME_TO_TICKER)
        _rebuild_derived()

    def test_adds_new_entries(self):
        """Config entries not in fallback should be added."""
        added = load_from_config({"pepe": "PEPE", "floki": "FLOKI"})
        assert added == 2
        assert normalize_to_ticker("pepe") == "PEPE"
        assert normalize_to_ticker("floki") == "FLOKI"

    def test_config_overrides_fallback(self):
        """Config takes precedence — operator can correct a mapping."""
        # Fallback has "ripple" → "XRP". Config overrides it (same value is fine).
        load_from_config({"ripple": "XRP"})
        assert normalize_to_ticker("ripple") == "XRP"

    def test_empty_config_no_change(self):
        """Empty config dict should not break anything."""
        before = len(NAME_TO_TICKER)
        added = load_from_config({})
        assert added == 0
        assert len(NAME_TO_TICKER) == before

    def test_derived_lookups_updated(self):
        """PROJECT_NAMES and _TICKER_CANONICAL should include new config entries."""
        load_from_config({"pepe": "PEPE"})
        assert "pepe" in PROJECT_NAMES
        assert normalize_to_ticker("PEPE") == "PEPE"  # ticker → canonical

    def test_extract_finds_config_names(self):
        """extract_coins_from_text should find config-loaded names."""
        load_from_config({"pepe": "PEPE"})
        result = extract_coins_from_text("Pepe surges 50% today")
        assert "PEPE" in result

    def teardown_method(self):
        """Restore fallback state after each test."""
        NAME_TO_TICKER.clear()
        NAME_TO_TICKER.update(_FALLBACK_NAME_TO_TICKER)
        _rebuild_derived()


class TestLoadFromSentinel:
    """P1.15: Sentinel registry sync into coin mapping."""

    def _make_coin(self, name: str, symbol: str) -> SentinelCoin:
        return SentinelCoin(
            cic_id=f"CIC-{symbol}",
            symbol=symbol,
            name=name,
            tier="L3",
            fa_status="ACTIVE",
            cic_action="theo-doi",
        )

    def setup_method(self):
        """Reset NAME_TO_TICKER to fallback-only before each test."""
        NAME_TO_TICKER.clear()
        NAME_TO_TICKER.update(_FALLBACK_NAME_TO_TICKER)
        _rebuild_derived()

    def test_adds_new_sentinel_coins(self):
        """New coins from Sentinel registry are added."""
        coins = [self._make_coin("Pendle", "PENDLE"), self._make_coin("Jupiter", "JUP")]
        added = load_from_sentinel(coins)
        assert added == 2
        assert normalize_to_ticker("pendle") == "PENDLE"
        assert normalize_to_ticker("jupiter") == "JUP"

    def test_does_not_override_existing(self):
        """Sentinel must NOT override existing fallback/config mappings."""
        # "bitcoin" -> "BTC" is in fallback. Even if Sentinel has different mapping,
        # existing entry should not be overridden.
        coins = [self._make_coin("Bitcoin", "BTC2")]
        added = load_from_sentinel(coins)
        assert added == 0
        assert normalize_to_ticker("bitcoin") == "BTC"  # Unchanged

    def test_empty_name_skipped(self):
        coins = [self._make_coin("", "EMPTY"), self._make_coin("Valid", "VLD")]
        added = load_from_sentinel(coins)
        assert added == 1
        assert normalize_to_ticker("valid") == "VLD"

    def test_empty_symbol_skipped(self):
        coins = [self._make_coin("NoSymbol", "")]
        added = load_from_sentinel(coins)
        assert added == 0

    def test_extract_finds_sentinel_names(self):
        """extract_coins_from_text should find Sentinel-loaded names."""
        coins = [self._make_coin("Render", "RNDR")]
        load_from_sentinel(coins)
        result = extract_coins_from_text("Render network partnership announced")
        assert "RNDR" in result

    def test_project_names_updated(self):
        """PROJECT_NAMES set should include Sentinel-loaded names."""
        coins = [self._make_coin("Injective", "INJ")]
        load_from_sentinel(coins)
        assert "injective" in PROJECT_NAMES

    def test_empty_registry(self):
        added = load_from_sentinel([])
        assert added == 0

    def teardown_method(self):
        """Restore fallback state after each test."""
        NAME_TO_TICKER.clear()
        NAME_TO_TICKER.update(_FALLBACK_NAME_TO_TICKER)
        _rebuild_derived()
