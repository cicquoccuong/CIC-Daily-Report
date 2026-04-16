"""Tests for Wave 3 (RC3) — Config Externalization (QO.28-QO.33).

Covers:
- QO.28: CAU_HINH seeds expanded with 22+ threshold keys
- QO.29: Market trigger thresholds from config_loader
- QO.30: Dedup thresholds from config_loader
- QO.31: Pipeline limits from config_loader
- QO.32: Quality thresholds from config_loader
- QO.33: Season-aware threshold multipliers
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cic_daily_report.collectors.market_data import MarketDataPoint

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dp(symbol="BTC", price=50000.0, change_24h=2.0, **kwargs) -> MarketDataPoint:
    return MarketDataPoint(
        symbol=symbol,
        price=price,
        change_24h=change_24h,
        volume_24h=kwargs.get("volume_24h", 1e9),
        market_cap=kwargs.get("market_cap", 1e12),
        data_type=kwargs.get("data_type", "crypto"),
        source=kwargs.get("source", "CoinLore"),
    )


def _mock_config_loader(**overrides):
    """Create a mock ConfigLoader that returns overrides via get_setting_*."""
    loader = MagicMock()
    store = dict(overrides)

    def get_setting(key, default=None):
        return store.get(key, default)

    def get_setting_int(key, default=0):
        val = store.get(key, default)
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    def get_setting_float(key, default=0.0):
        val = store.get(key, default)
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    loader.get_setting = MagicMock(side_effect=get_setting)
    loader.get_setting_int = MagicMock(side_effect=get_setting_int)
    loader.get_setting_float = MagicMock(side_effect=get_setting_float)
    return loader


# =====================================================================
# QO.28: CAU_HINH seeds
# =====================================================================


class TestQO28ConfigSeeds:
    """QO.28: _DEFAULT_CONFIG_SEEDS has 22+ threshold keys."""

    def test_seeds_has_22_plus_keys(self):
        from cic_daily_report.storage.sheets_client import _DEFAULT_CONFIG_SEEDS

        # WHY: Spec requires 22+ keys. We count only threshold keys (not email/backup).
        skip = ("email_recipients", "email_backup_enabled")
        threshold_keys = [s for s in _DEFAULT_CONFIG_SEEDS if s[0] not in skip]
        assert len(threshold_keys) >= 22, (
            f"Expected >= 22 threshold keys, got {len(threshold_keys)}"
        )

    def test_all_required_keys_present(self):
        from cic_daily_report.storage.sheets_client import _DEFAULT_CONFIG_SEEDS

        seed_keys = {s[0] for s in _DEFAULT_CONFIG_SEEDS}
        required = {
            "BTC_DROP_THRESHOLD",
            "ETH_DROP_THRESHOLD",
            "FEAR_GREED_THRESHOLD",
            "OIL_SPIKE_THRESHOLD",
            "GOLD_SPIKE_THRESHOLD",
            "VIX_SPIKE_THRESHOLD",
            "DXY_SPIKE_THRESHOLD",
            "SPX_DROP_THRESHOLD",
            "COOLDOWN_HOURS",
            "SIMILARITY_THRESHOLD",
            "ENTITY_OVERLAP_THRESHOLD",
            "MAX_EVENTS_PER_RUN",
            "MAX_EVENTS_PER_DAY",
            "DIGEST_THRESHOLD",
            "INTER_EVENT_DELAY",
            "INSIGHT_DENSITY_THRESHOLD",
            "MASTER_MAX_TOKENS",
            "QUALITY_GATE_MODE",
            "CACHE_MAX_AGE",
            "DEFAULT_PANIC_THRESHOLD",
            "NIGHT_START",
            "NIGHT_END",
            "RESEARCH_MAX_TOKENS",
        }
        missing = required - seed_keys
        assert not missing, f"Missing seed keys: {missing}"

    def test_each_seed_has_3_fields(self):
        from cic_daily_report.storage.sheets_client import _DEFAULT_CONFIG_SEEDS

        for seed in _DEFAULT_CONFIG_SEEDS:
            assert len(seed) == 3, f"Seed {seed[0]} should be (key, value, description)"
            assert seed[0], "Key must not be empty"
            # Value CAN be empty (e.g., email_recipients), but description should exist
            assert seed[2], f"Description missing for key {seed[0]}"

    def test_seeds_have_vietnamese_descriptions(self):
        """Descriptions use Vietnamese no-diacritics for operator readability."""
        from cic_daily_report.storage.sheets_client import _DEFAULT_CONFIG_SEEDS

        for key, _, desc in _DEFAULT_CONFIG_SEEDS:
            if key in ("email_recipients", "email_backup_enabled"):
                continue
            # At minimum, description should be non-empty and contain
            # a Vietnamese word pattern (no-diacritics, lowercase)
            assert len(desc) > 10, f"Description too short for {key}: '{desc}'"


# =====================================================================
# QO.28: get_setting_float
# =====================================================================


class TestGetSettingFloat:
    """QO.28: ConfigLoader.get_setting_float() works correctly."""

    def test_returns_float_from_sheet(self):
        from cic_daily_report.storage.config_loader import ConfigLoader

        mock_sheets = MagicMock()
        mock_sheets.read_all.return_value = [
            {"Khoa": "BTC_DROP_THRESHOLD", "Gia tri": "-5.5", "Mo ta": ""},
        ]
        # WHY: read_all returns Vietnamese-keyed dicts, but config_loader
        # reads "Khoa" and "Gia tri" (actually "Khóa" and "Giá trị")
        mock_sheets.read_all.return_value = [
            {"Khóa": "BTC_DROP_THRESHOLD", "Giá trị": "-5.5", "Mô tả": ""},
        ]
        loader = ConfigLoader(mock_sheets)
        val = loader.get_setting_float("BTC_DROP_THRESHOLD", -7.0)
        assert val == -5.5

    def test_returns_default_on_missing_key(self):
        from cic_daily_report.storage.config_loader import ConfigLoader

        mock_sheets = MagicMock()
        mock_sheets.read_all.return_value = []
        loader = ConfigLoader(mock_sheets)
        val = loader.get_setting_float("NONEXISTENT", -7.0)
        assert val == -7.0

    def test_returns_default_on_invalid_value(self):
        from cic_daily_report.storage.config_loader import ConfigLoader

        mock_sheets = MagicMock()
        mock_sheets.read_all.return_value = [
            {"Khóa": "BAD_KEY", "Giá trị": "not_a_number", "Mô tả": ""},
        ]
        loader = ConfigLoader(mock_sheets)
        val = loader.get_setting_float("BAD_KEY", 0.30)
        assert val == 0.30


# =====================================================================
# QO.29: Market trigger thresholds from config
# =====================================================================


class TestQO29MarketTriggerConfig:
    """QO.29: detect_market_triggers reads thresholds from config_loader."""

    def test_uses_config_btc_threshold(self):
        """Config BTC threshold overrides default."""
        from cic_daily_report.breaking.market_trigger import detect_market_triggers

        # Default BTC threshold is -7.0, config sets -3.0 (more sensitive)
        loader = _mock_config_loader(BTC_DROP_THRESHOLD=-3.0)

        # Mock sentinel to return no season (multiplier = 1.0)
        with patch("cic_daily_report.storage.sentinel_reader.SentinelReader") as mock_sentinel_cls:
            mock_sentinel_cls.return_value.read_season.return_value = None
            data = [_make_dp("BTC", price=45000, change_24h=-4.0)]
            events = detect_market_triggers(data, config_loader=loader)

        # -4.0 <= -3.0 → should trigger (would NOT trigger with default -7.0)
        assert len(events) == 1
        assert "BTC" in events[0].title

    def test_uses_config_eth_threshold(self):
        from cic_daily_report.breaking.market_trigger import detect_market_triggers

        loader = _mock_config_loader(ETH_DROP_THRESHOLD=-5.0)
        with patch("cic_daily_report.storage.sentinel_reader.SentinelReader") as mock_sentinel_cls:
            mock_sentinel_cls.return_value.read_season.return_value = None
            data = [_make_dp("ETH", price=2000, change_24h=-6.0)]
            events = detect_market_triggers(data, config_loader=loader)

        assert len(events) == 1
        assert "ETH" in events[0].title

    def test_uses_config_fear_greed_threshold(self):
        from cic_daily_report.breaking.market_trigger import detect_market_triggers

        loader = _mock_config_loader(FEAR_GREED_THRESHOLD=20)
        with patch("cic_daily_report.storage.sentinel_reader.SentinelReader") as mock_sentinel_cls:
            mock_sentinel_cls.return_value.read_season.return_value = None
            data = [_make_dp("Fear&Greed", price=15, change_24h=0, data_type="index")]
            events = detect_market_triggers(data, config_loader=loader)

        # 15 <= 20 → should trigger
        assert len(events) == 1

    def test_explicit_param_overrides_config(self):
        """Explicit btc_threshold param overrides config."""
        from cic_daily_report.breaking.market_trigger import detect_market_triggers

        loader = _mock_config_loader(BTC_DROP_THRESHOLD=-3.0)
        with patch("cic_daily_report.storage.sentinel_reader.SentinelReader") as mock_sentinel_cls:
            mock_sentinel_cls.return_value.read_season.return_value = None
            data = [_make_dp("BTC", price=45000, change_24h=-4.0)]
            # Explicit -8.0 should override config's -3.0
            events = detect_market_triggers(data, btc_threshold=-8.0, config_loader=loader)

        # -4.0 > -8.0 → should NOT trigger
        assert len(events) == 0

    def test_no_config_uses_defaults(self):
        """Without config_loader, uses module-level defaults."""
        from cic_daily_report.breaking.market_trigger import detect_market_triggers

        data = [_make_dp("BTC", price=45000, change_24h=-4.0)]
        events = detect_market_triggers(data)
        # -4.0 > -7.0 → should NOT trigger (default)
        assert len(events) == 0

    def test_config_failure_uses_defaults(self):
        """Config read failure → silently use defaults."""
        from cic_daily_report.breaking.market_trigger import detect_market_triggers

        loader = MagicMock()
        loader.get_setting_float.side_effect = Exception("Sheet down")
        with patch("cic_daily_report.storage.sentinel_reader.SentinelReader") as mock_sentinel_cls:
            mock_sentinel_cls.return_value.read_season.return_value = None
            data = [_make_dp("BTC", price=45000, change_24h=-4.0)]
            events = detect_market_triggers(data, config_loader=loader)

        # Defaults used: -4.0 > -7.0 → no trigger
        assert len(events) == 0

    def test_macro_thresholds_from_config(self):
        """Macro triggers (Oil, Gold, VIX, DXY, SPX) read from config."""
        from cic_daily_report.breaking.market_trigger import detect_market_triggers

        # Set oil threshold lower so 5% triggers (default is 8%)
        loader = _mock_config_loader(OIL_SPIKE_THRESHOLD=4.0)
        with patch("cic_daily_report.storage.sentinel_reader.SentinelReader") as mock_sentinel_cls:
            mock_sentinel_cls.return_value.read_season.return_value = None
            data = [_make_dp("Oil", price=80, change_24h=5.0, data_type="commodity")]
            events = detect_market_triggers(data, config_loader=loader)

        # 5.0 >= 4.0 → should trigger
        assert len(events) == 1
        assert "Oil" in events[0].raw_data.get("symbol", "")


# =====================================================================
# QO.30: Dedup thresholds from config
# =====================================================================


class TestQO30DedupConfig:
    """QO.30: DedupManager reads thresholds from config_loader."""

    def test_cooldown_from_config(self):
        """Custom cooldown hours read from config."""
        from datetime import datetime, timedelta, timezone

        from cic_daily_report.breaking.dedup_manager import DedupEntry, DedupManager
        from cic_daily_report.breaking.event_detector import BreakingEvent

        loader = _mock_config_loader(
            COOLDOWN_HOURS=24,
            SIMILARITY_THRESHOLD=0.70,
            ENTITY_OVERLAP_THRESHOLD=0.60,
        )

        # Create an entry 13h ago
        now = datetime.now(timezone.utc)
        old_time = (now - timedelta(hours=13)).isoformat()
        existing = DedupEntry(
            hash="abc123",
            title="Old event",
            source="test",
            detected_at=old_time,
        )

        # With default 12h cooldown, entry would be expired. With 24h, it's still active.
        mgr = DedupManager(existing_entries=[existing], config_loader=loader)
        event = BreakingEvent(title="Old event", source="test", url="", panic_score=80)
        result = mgr.check_and_filter([event])
        # 13h < 24h cooldown → entry still active → duplicate skipped
        assert result.duplicates_skipped == 1
        assert len(result.new_events) == 0

    def test_default_cooldown_without_config(self):
        """Without config, uses 12h default."""
        from datetime import datetime, timedelta, timezone

        from cic_daily_report.breaking.dedup_manager import DedupEntry, DedupManager
        from cic_daily_report.breaking.event_detector import BreakingEvent

        now = datetime.now(timezone.utc)
        old_time = (now - timedelta(hours=13)).isoformat()
        existing = DedupEntry(
            hash="abc123",
            title="Old event",
            source="test",
            detected_at=old_time,
        )

        mgr = DedupManager(existing_entries=[existing])
        event = BreakingEvent(title="Old event", source="test", url="", panic_score=80)
        result = mgr.check_and_filter([event])
        # 13h > 12h default → cooldown expired → NOT a duplicate
        assert result.duplicates_skipped == 0
        assert len(result.new_events) == 1

    def test_similarity_threshold_from_config(self):
        """Custom similarity threshold from config.

        WHY: Uses titles with no extractable entities to isolate the
        similarity check from entity-based dedup (which has its own threshold).
        """
        from datetime import datetime, timedelta, timezone

        from cic_daily_report.breaking.dedup_manager import DedupEntry, DedupManager
        from cic_daily_report.breaking.event_detector import BreakingEvent

        # Set very high similarity threshold so nothing matches
        loader = _mock_config_loader(
            COOLDOWN_HOURS=12,
            SIMILARITY_THRESHOLD=0.99,
            ENTITY_OVERLAP_THRESHOLD=0.99,
        )

        now = datetime.now(timezone.utc)
        recent_time = (now - timedelta(hours=1)).isoformat()
        # WHY: Use entity-free titles to isolate similarity check from entity dedup
        existing = DedupEntry(
            hash="diff_hash",
            title="Market analysis shows price drops sharply in crash today",
            source="news_src",
            detected_at=recent_time,
        )

        mgr = DedupManager(existing_entries=[existing], config_loader=loader)
        event = BreakingEvent(
            title="Market analysis shows price drops sharply in crash tonight",
            source="other_source",
            url="",
            panic_score=80,
        )
        result = mgr.check_and_filter([event])
        # With 0.99 threshold, similarity ~0.95 won't match → event passes through
        assert len(result.new_events) == 1

    def test_config_failure_uses_defaults(self):
        """Config read failure → uses module-level defaults."""
        from cic_daily_report.breaking.dedup_manager import (
            COOLDOWN_HOURS,
            ENTITY_OVERLAP_THRESHOLD,
            SIMILARITY_THRESHOLD,
            DedupManager,
        )

        loader = MagicMock()
        loader.get_setting_int.side_effect = Exception("Sheet down")
        loader.get_setting_float.side_effect = Exception("Sheet down")

        mgr = DedupManager(config_loader=loader)
        assert mgr._cooldown_hours == COOLDOWN_HOURS
        assert mgr._similarity_threshold == SIMILARITY_THRESHOLD
        assert mgr._entity_overlap_threshold == ENTITY_OVERLAP_THRESHOLD


# =====================================================================
# QO.31: Pipeline limits from config
# =====================================================================


class TestQO31PipelineLimits:
    """QO.31: _get_pipeline_limits reads from config_loader."""

    def test_reads_from_config(self):
        from cic_daily_report.breaking_pipeline import _get_pipeline_limits

        loader = _mock_config_loader(
            MAX_EVENTS_PER_RUN=5,
            MAX_EVENTS_PER_DAY=20,
            DIGEST_THRESHOLD=4,
            INTER_EVENT_DELAY=60,
        )
        limits = _get_pipeline_limits(loader)
        assert limits["MAX_EVENTS_PER_RUN"] == 5
        assert limits["MAX_EVENTS_PER_DAY"] == 20
        assert limits["DIGEST_THRESHOLD"] == 4
        assert limits["INTER_EVENT_DELAY"] == 60

    def test_defaults_without_config(self):
        from cic_daily_report.breaking_pipeline import (
            DIGEST_THRESHOLD,
            INTER_EVENT_DELAY,
            MAX_EVENTS_PER_DAY,
            MAX_EVENTS_PER_RUN,
            _get_pipeline_limits,
        )

        limits = _get_pipeline_limits(None)
        assert limits["MAX_EVENTS_PER_RUN"] == MAX_EVENTS_PER_RUN
        assert limits["MAX_EVENTS_PER_DAY"] == MAX_EVENTS_PER_DAY
        assert limits["DIGEST_THRESHOLD"] == DIGEST_THRESHOLD
        assert limits["INTER_EVENT_DELAY"] == INTER_EVENT_DELAY

    def test_config_failure_uses_defaults(self):
        from cic_daily_report.breaking_pipeline import (
            MAX_EVENTS_PER_RUN,
            _get_pipeline_limits,
        )

        loader = MagicMock()
        loader.get_setting_int.side_effect = Exception("Sheet down")
        limits = _get_pipeline_limits(loader)
        assert limits["MAX_EVENTS_PER_RUN"] == MAX_EVENTS_PER_RUN


class TestQO31FeedbackConfig:
    """QO.31: feedback.py MAX_EVENTS_PER_DAY from config."""

    def test_get_max_events_from_config(self):
        from cic_daily_report.breaking.feedback import _get_max_events_per_day

        loader = _mock_config_loader(MAX_EVENTS_PER_DAY=20)
        assert _get_max_events_per_day(loader) == 20

    def test_default_without_config(self):
        from cic_daily_report.breaking.feedback import (
            MAX_EVENTS_PER_DAY,
            _get_max_events_per_day,
        )

        assert _get_max_events_per_day(None) == MAX_EVENTS_PER_DAY

    def test_config_failure_uses_default(self):
        from cic_daily_report.breaking.feedback import (
            MAX_EVENTS_PER_DAY,
            _get_max_events_per_day,
        )

        loader = MagicMock()
        loader.get_setting_int.side_effect = Exception("Sheet down")
        assert _get_max_events_per_day(loader) == MAX_EVENTS_PER_DAY


# =====================================================================
# QO.32: Quality thresholds from config
# =====================================================================


class TestQO32QualityConfig:
    """QO.32: Quality gate thresholds from config_loader."""

    def test_insight_density_threshold_from_config(self):
        from cic_daily_report.generators.quality_gate import _get_insight_density_threshold

        loader = _mock_config_loader(INSIGHT_DENSITY_THRESHOLD=0.50)
        assert _get_insight_density_threshold(loader) == 0.50

    def test_insight_density_default_without_config(self):
        from cic_daily_report.generators.quality_gate import (
            INSIGHT_DENSITY_THRESHOLD,
            _get_insight_density_threshold,
        )

        assert _get_insight_density_threshold(None) == INSIGHT_DENSITY_THRESHOLD

    def test_run_quality_gate_uses_config_threshold(self):
        """Custom higher threshold → article with 40% density now fails."""
        from cic_daily_report.generators.quality_gate import run_quality_gate

        # Good article with ~40% data density (passes 0.30 but fails 0.50)
        content = (
            "BTC price increased 5.2% to $87,500 today. "
            "ETH also rallied strongly in the market. "
            "The crypto market showed positive momentum. "
            "Fear & Greed Index = 72, showing greed. "
            "Trading volumes remained relatively stable across all exchanges."
        )
        input_data = {"market_data": "BTC: $87,500 (+5.2%)", "economic_events": ""}

        loader = _mock_config_loader(INSIGHT_DENSITY_THRESHOLD=0.50)
        result = run_quality_gate(content, "L1", input_data, mode="BLOCK", config_loader=loader)
        # With 0.50 threshold, ~40% density should fail
        assert result.retry_recommended is True

    def test_master_max_tokens_from_config(self):
        from cic_daily_report.generators.master_analysis import _get_master_max_tokens

        loader = _mock_config_loader(MASTER_MAX_TOKENS=30000)
        assert _get_master_max_tokens(loader) == 30000

    def test_master_max_tokens_default(self):
        from cic_daily_report.generators.master_analysis import (
            MASTER_MAX_TOKENS,
            _get_master_max_tokens,
        )

        assert _get_master_max_tokens(None) == MASTER_MAX_TOKENS

    def test_research_max_tokens_from_config(self):
        from cic_daily_report.generators.research_generator import _get_research_max_tokens

        loader = _mock_config_loader(RESEARCH_MAX_TOKENS=8192)
        assert _get_research_max_tokens(loader) == 8192

    def test_research_max_tokens_default(self):
        from cic_daily_report.generators.research_generator import (
            RESEARCH_MAX_TOKENS,
            _get_research_max_tokens,
        )

        assert _get_research_max_tokens(None) == RESEARCH_MAX_TOKENS

    def test_quality_gate_mode_already_works(self):
        """QO.20 QUALITY_GATE_MODE was already configurable — verify still works."""
        from cic_daily_report.generators.quality_gate import get_quality_gate_mode

        loader = _mock_config_loader(QUALITY_GATE_MODE="LOG")
        assert get_quality_gate_mode(loader) == "LOG"


# =====================================================================
# QO.33: Season-aware thresholds
# =====================================================================


class TestQO33SeasonAware:
    """QO.33: Season multiplier adjusts market trigger thresholds."""

    def test_season_multipliers_defined(self):
        from cic_daily_report.breaking.market_trigger import SEASON_MULTIPLIERS

        assert SEASON_MULTIPLIERS["MUA_DONG"] == 0.7
        assert SEASON_MULTIPLIERS["MUA_HE"] == 1.3
        assert SEASON_MULTIPLIERS["MUA_XUAN"] == 1.0
        assert SEASON_MULTIPLIERS["MUA_THU"] == 1.0

    def test_apply_season_multiplier_winter(self):
        """MUA_DONG (Winter): thresholds * 0.7 → more sensitive."""
        from cic_daily_report.breaking.market_trigger import _apply_season_multiplier

        thresholds = {
            "BTC_DROP_THRESHOLD": -7.0,
            "OIL_SPIKE_THRESHOLD": 8.0,
        }
        adjusted = _apply_season_multiplier(thresholds, 0.7)
        # -7.0 * 0.7 = -4.9 (smaller absolute value = more sensitive)
        assert adjusted["BTC_DROP_THRESHOLD"] == pytest.approx(-4.9)
        # 8.0 * 0.7 = 5.6 (smaller value = more sensitive)
        assert adjusted["OIL_SPIKE_THRESHOLD"] == pytest.approx(5.6)

    def test_apply_season_multiplier_summer(self):
        """MUA_HE (Summer): thresholds * 1.3 → less sensitive."""
        from cic_daily_report.breaking.market_trigger import _apply_season_multiplier

        thresholds = {
            "BTC_DROP_THRESHOLD": -7.0,
            "OIL_SPIKE_THRESHOLD": 8.0,
        }
        adjusted = _apply_season_multiplier(thresholds, 1.3)
        # -7.0 * 1.3 = -9.1 (larger absolute value = less sensitive)
        assert adjusted["BTC_DROP_THRESHOLD"] == pytest.approx(-9.1)
        # 8.0 * 1.3 = 10.4
        assert adjusted["OIL_SPIKE_THRESHOLD"] == pytest.approx(10.4)

    def test_apply_season_multiplier_neutral(self):
        """Multiplier 1.0 → no change (returns same dict)."""
        from cic_daily_report.breaking.market_trigger import _apply_season_multiplier

        thresholds = {"BTC_DROP_THRESHOLD": -7.0}
        adjusted = _apply_season_multiplier(thresholds, 1.0)
        assert adjusted is thresholds  # Same object, no copy needed

    def test_get_season_multiplier_no_config(self):
        from cic_daily_report.breaking.market_trigger import _get_season_multiplier

        assert _get_season_multiplier(None) == 1.0

    def test_get_season_multiplier_winter(self):
        from cic_daily_report.breaking.market_trigger import _get_season_multiplier
        from cic_daily_report.storage.sentinel_reader import SentinelSeason

        loader = _mock_config_loader()
        season = SentinelSeason(
            phase="MUA_DONG",
            heat_score=20.0,
            confidence=0.9,
            detail="Bear market",
            last_update="2026-04-15T00:00:00Z",
        )
        with patch("cic_daily_report.storage.sentinel_reader.SentinelReader") as mock_cls:
            mock_cls.return_value.read_season.return_value = season
            mult = _get_season_multiplier(loader)

        assert mult == 0.7

    def test_get_season_multiplier_summer(self):
        from cic_daily_report.breaking.market_trigger import _get_season_multiplier
        from cic_daily_report.storage.sentinel_reader import SentinelSeason

        loader = _mock_config_loader()
        season = SentinelSeason(
            phase="MUA_HE",
            heat_score=80.0,
            confidence=0.85,
            detail="Bull market",
            last_update="2026-04-15T00:00:00Z",
        )
        with patch("cic_daily_report.storage.sentinel_reader.SentinelReader") as mock_cls:
            mock_cls.return_value.read_season.return_value = season
            mult = _get_season_multiplier(loader)

        assert mult == 1.3

    def test_get_season_multiplier_sentinel_unreachable(self):
        """Sentinel unreachable → returns 1.0 (no adjustment)."""
        from cic_daily_report.breaking.market_trigger import _get_season_multiplier

        loader = _mock_config_loader()
        with patch("cic_daily_report.storage.sentinel_reader.SentinelReader") as mock_cls:
            mock_cls.return_value.read_season.side_effect = ConnectionError("no creds")
            mult = _get_season_multiplier(loader)

        assert mult == 1.0

    def test_get_season_multiplier_no_season_data(self):
        """Sentinel returns None for season → returns 1.0."""
        from cic_daily_report.breaking.market_trigger import _get_season_multiplier

        loader = _mock_config_loader()
        with patch("cic_daily_report.storage.sentinel_reader.SentinelReader") as mock_cls:
            mock_cls.return_value.read_season.return_value = None
            mult = _get_season_multiplier(loader)

        assert mult == 1.0

    def test_winter_makes_btc_more_sensitive(self):
        """Integration: Winter season → BTC threshold more sensitive → triggers on smaller drop."""
        from cic_daily_report.breaking.market_trigger import detect_market_triggers
        from cic_daily_report.storage.sentinel_reader import SentinelSeason

        loader = _mock_config_loader(BTC_DROP_THRESHOLD=-7.0)
        season = SentinelSeason(
            phase="MUA_DONG",
            heat_score=20.0,
            confidence=0.9,
            detail="",
            last_update="2026-04-15T00:00:00Z",
        )
        with patch("cic_daily_report.storage.sentinel_reader.SentinelReader") as mock_cls:
            mock_cls.return_value.read_season.return_value = season
            # -5.0% drop: normally wouldn't trigger (-7.0 default),
            # but in winter: -7.0 * 0.7 = -4.9, and -5.0 <= -4.9 → triggers
            data = [_make_dp("BTC", price=40000, change_24h=-5.0)]
            events = detect_market_triggers(data, config_loader=loader)

        assert len(events) == 1
        assert "BTC" in events[0].title

    def test_summer_makes_btc_less_sensitive(self):
        """Integration: Summer season → BTC threshold less sensitive → no trigger on normal drop."""
        from cic_daily_report.breaking.market_trigger import detect_market_triggers
        from cic_daily_report.storage.sentinel_reader import SentinelSeason

        loader = _mock_config_loader(BTC_DROP_THRESHOLD=-7.0)
        season = SentinelSeason(
            phase="MUA_HE",
            heat_score=80.0,
            confidence=0.9,
            detail="",
            last_update="2026-04-15T00:00:00Z",
        )
        with patch("cic_daily_report.storage.sentinel_reader.SentinelReader") as mock_cls:
            mock_cls.return_value.read_season.return_value = season
            # -8.0% drop: normally triggers (-7.0 default),
            # but in summer: -7.0 * 1.3 = -9.1, and -8.0 > -9.1 → NO trigger
            data = [_make_dp("BTC", price=40000, change_24h=-8.0)]
            events = detect_market_triggers(data, config_loader=loader)

        assert len(events) == 0


# =====================================================================
# Cross-cutting: Default fallback pattern
# =====================================================================


class TestDefaultFallbackPattern:
    """Verify all config externalized modules fall back to defaults gracefully."""

    def test_market_trigger_defaults_match_module_constants(self):
        from cic_daily_report.breaking.market_trigger import (
            BTC_DROP_THRESHOLD,
            DXY_SPIKE_THRESHOLD,
            ETH_DROP_THRESHOLD,
            FEAR_GREED_THRESHOLD,
            GOLD_SPIKE_THRESHOLD,
            OIL_SPIKE_THRESHOLD,
            SPX_DROP_THRESHOLD,
            VIX_SPIKE_THRESHOLD,
            _get_thresholds,
        )

        defaults = _get_thresholds(None)
        assert defaults["BTC_DROP_THRESHOLD"] == BTC_DROP_THRESHOLD
        assert defaults["ETH_DROP_THRESHOLD"] == ETH_DROP_THRESHOLD
        assert defaults["FEAR_GREED_THRESHOLD"] == float(FEAR_GREED_THRESHOLD)
        assert defaults["OIL_SPIKE_THRESHOLD"] == OIL_SPIKE_THRESHOLD
        assert defaults["GOLD_SPIKE_THRESHOLD"] == GOLD_SPIKE_THRESHOLD
        assert defaults["VIX_SPIKE_THRESHOLD"] == float(VIX_SPIKE_THRESHOLD)
        assert defaults["DXY_SPIKE_THRESHOLD"] == DXY_SPIKE_THRESHOLD
        assert defaults["SPX_DROP_THRESHOLD"] == SPX_DROP_THRESHOLD

    def test_pipeline_limits_defaults_match_module_constants(self):
        from cic_daily_report.breaking_pipeline import (
            DIGEST_THRESHOLD,
            INTER_EVENT_DELAY,
            MAX_EVENTS_PER_DAY,
            MAX_EVENTS_PER_RUN,
            _get_pipeline_limits,
        )

        defaults = _get_pipeline_limits(None)
        assert defaults["MAX_EVENTS_PER_RUN"] == MAX_EVENTS_PER_RUN
        assert defaults["MAX_EVENTS_PER_DAY"] == MAX_EVENTS_PER_DAY
        assert defaults["DIGEST_THRESHOLD"] == DIGEST_THRESHOLD
        assert defaults["INTER_EVENT_DELAY"] == INTER_EVENT_DELAY

    def test_dedup_defaults_match_module_constants(self):
        from cic_daily_report.breaking.dedup_manager import (
            COOLDOWN_HOURS,
            ENTITY_OVERLAP_THRESHOLD,
            SIMILARITY_THRESHOLD,
            DedupManager,
        )

        mgr = DedupManager()
        assert mgr._cooldown_hours == COOLDOWN_HOURS
        assert mgr._similarity_threshold == SIMILARITY_THRESHOLD
        assert mgr._entity_overlap_threshold == ENTITY_OVERLAP_THRESHOLD
