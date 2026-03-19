"""Tests for breaking/severity_classifier.py."""

from datetime import datetime, timezone

from cic_daily_report.breaking.event_detector import BreakingEvent
from cic_daily_report.breaking.severity_classifier import (
    CRITICAL,
    IMPORTANT,
    NOTABLE,
    VN_TZ,
    ClassificationConfig,
    _determine_action,
    _determine_severity,
    _is_night_mode,
    classify_batch,
    classify_event,
)


def _event(title="News", panic_score=50) -> BreakingEvent:
    return BreakingEvent(title=title, source="Src", url="", panic_score=panic_score)


def _vn_time(hour: int, minute: int = 0) -> datetime:
    """Create datetime at specific VN hour."""
    return datetime(2026, 3, 9, hour, minute, tzinfo=VN_TZ)


class TestDetermineSeverity:
    def test_critical_keyword(self):
        assert _determine_severity(_event("Exchange hack"), ClassificationConfig()) == CRITICAL

    def test_critical_panic_score(self):
        assert _determine_severity(_event("Some news", 90), ClassificationConfig()) == CRITICAL

    def test_important_keyword(self):
        assert _determine_severity(_event("SEC investigation"), ClassificationConfig()) == IMPORTANT

    def test_important_panic_score(self):
        assert _determine_severity(_event("Some news", 65), ClassificationConfig()) == IMPORTANT

    def test_notable_default(self):
        assert _determine_severity(_event("Market update", 30), ClassificationConfig()) == NOTABLE

    def test_custom_keywords(self):
        cfg = ClassificationConfig(critical_keywords=["moon"])
        assert _determine_severity(_event("BTC to the moon"), cfg) == CRITICAL


class TestIsNightMode:
    def test_midnight_is_night(self):
        assert _is_night_mode(_vn_time(0))

    def test_3am_is_night(self):
        assert _is_night_mode(_vn_time(3))

    def test_6am_is_night(self):
        assert _is_night_mode(_vn_time(6))

    def test_7am_not_night(self):
        assert not _is_night_mode(_vn_time(7))

    def test_noon_not_night(self):
        assert not _is_night_mode(_vn_time(12))

    def test_2259_not_night(self):
        assert not _is_night_mode(_vn_time(22, 59))

    def test_2300_is_night(self):
        assert _is_night_mode(_vn_time(23, 0))

    def test_2301_is_night(self):
        assert _is_night_mode(_vn_time(23, 1))

    def test_utc_converted_correctly(self):
        # 16:00 UTC = 23:00 VN → night
        utc_time = datetime(2026, 3, 9, 16, 0, tzinfo=timezone.utc)
        assert _is_night_mode(utc_time)

    def test_utc_day_not_night(self):
        # 05:00 UTC = 12:00 VN → day
        utc_time = datetime(2026, 3, 9, 5, 0, tzinfo=timezone.utc)
        assert not _is_night_mode(utc_time)


class TestDetermineAction:
    def test_critical_always_send_now(self):
        assert _determine_action(CRITICAL, is_night=True) == "send_now"
        assert _determine_action(CRITICAL, is_night=False) == "send_now"

    def test_important_day_send_now(self):
        assert _determine_action(IMPORTANT, is_night=False) == "send_now"

    def test_important_night_deferred_morning(self):
        assert _determine_action(IMPORTANT, is_night=True) == "deferred_to_morning"

    def test_notable_day_send_now(self):
        assert _determine_action(NOTABLE, is_night=False) == "send_now"

    def test_notable_night_skipped(self):
        """C2: Notable events at night are skipped (was deferred_to_daily, never consumed)."""
        assert _determine_action(NOTABLE, is_night=True) == "skipped"


class TestClassifyEvent:
    def test_critical_event(self):
        result = classify_event(_event("Major hack", 90), now=_vn_time(12))
        assert result.severity == CRITICAL
        assert "\U0001f534" in result.emoji
        assert result.delivery_action == "send_now"

    def test_important_night_deferred(self):
        result = classify_event(_event("SEC news", 50), now=_vn_time(1))
        assert result.severity == IMPORTANT
        assert result.delivery_action == "deferred_to_morning"

    def test_notable_night_skipped(self):
        """C2: Notable events at night are now skipped."""
        result = classify_event(_event("Market shift", 30), now=_vn_time(2))
        assert result.severity == NOTABLE
        assert result.delivery_action == "skipped"

    def test_is_deferred_property(self):
        result = classify_event(_event("SEC news", 50), now=_vn_time(1))
        assert result.is_deferred

    def test_not_deferred_property(self):
        result = classify_event(_event("Major hack", 90), now=_vn_time(1))
        assert not result.is_deferred

    def test_header_format(self):
        result = classify_event(_event("Hack alert", 90), now=_vn_time(12))
        assert "CRITICAL" in result.header
        assert "Hack alert" in result.header


class TestNewKeywordsAndPriceMovement:
    """v0.19.0: New important keywords and price-movement detection."""

    def test_drops_keyword_is_important(self):
        cfg = ClassificationConfig()
        result = _determine_severity(_event("BTC drops below 60K"), cfg)
        assert result == IMPORTANT

    def test_iran_keyword_is_important(self):
        cfg = ClassificationConfig()
        result = _determine_severity(_event("Iran tensions rise"), cfg)
        assert result == IMPORTANT

    def test_percentage_3_or_more_is_important(self):
        cfg = ClassificationConfig()
        result = _determine_severity(_event("ETH drops 3.5% today"), cfg)
        assert result == IMPORTANT

    def test_percentage_10_or_more_is_critical(self):
        cfg = ClassificationConfig()
        result = _determine_severity(_event("SOL surges 12% overnight"), cfg)
        assert result == CRITICAL

    def test_percentage_below_3_stays_notable(self):
        cfg = ClassificationConfig()
        result = _determine_severity(_event("BTC moves 2.1%", 30), cfg)
        assert result == NOTABLE


class TestWordBoundaryMatching:
    """v0.19.0 fix: keyword matching uses word boundaries."""

    def test_ban_does_not_match_binance(self):
        """'ban' keyword should NOT match inside 'Binance'."""
        cfg = ClassificationConfig()
        result = _determine_severity(_event("Binance launches new feature"), cfg)
        assert result != CRITICAL

    def test_ban_matches_standalone(self):
        """'ban' keyword should match standalone 'ban'."""
        cfg = ClassificationConfig()
        result = _determine_severity(_event("Country to ban crypto trading"), cfg)
        assert result == CRITICAL

    def test_ban_matches_word_boundary(self):
        """'ban' should match at word boundaries like 'crypto ban'."""
        cfg = ClassificationConfig()
        result = _determine_severity(_event("New crypto ban announced"), cfg)
        assert result == CRITICAL


class TestPhase3Classification:
    """Phase 3: Volume vs price %, crash keyword sync."""

    def test_volume_pct_not_critical(self):
        """B1: Volume percentage should NOT trigger severity."""
        cfg = ClassificationConfig()
        result = _determine_severity(_event("Zcash 108% trading volume surge", 40), cfg)
        assert result == NOTABLE  # Volume %, not price

    def test_price_drop_pct_critical(self):
        """B1: Price drop 12% → critical."""
        cfg = ClassificationConfig()
        result = _determine_severity(_event("BTC drop 12% in flash crash", 40), cfg)
        assert result == CRITICAL

    def test_price_surge_pct_important(self):
        """B1: Price surge 5% → important."""
        cfg = ClassificationConfig()
        result = _determine_severity(_event("ETH surge 5% on ETF news", 40), cfg)
        assert result == IMPORTANT

    def test_crash_keyword_important(self):
        """B4: 'crash' keyword → important severity."""
        cfg = ClassificationConfig()
        result = _determine_severity(_event("Market crash fears grow", 40), cfg)
        assert result == IMPORTANT


class TestClassifyBatch:
    def test_classifies_all(self):
        events = [_event("Hack", 90), _event("Update", 30)]
        results = classify_batch(events, now=_vn_time(12))
        assert len(results) == 2
        assert results[0].severity == CRITICAL
        assert results[1].severity == NOTABLE
