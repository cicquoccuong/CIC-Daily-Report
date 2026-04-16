"""Tests for QO.14 — Geo event digest + daily cap.

Geo events are grouped into digest messages instead of individual messages.
Max 3 geo digests per day. CRITICAL geo events (panic >= 90) bypass.
"""

from datetime import datetime, timezone

from cic_daily_report.breaking.dedup_manager import DedupEntry, DedupManager
from cic_daily_report.breaking.event_detector import (
    BreakingEvent,
    is_geo_event,
)
from cic_daily_report.breaking_pipeline import (
    GEO_CRITICAL_PANIC_THRESHOLD,
    MAX_GEO_DIGESTS_PER_DAY,
    _count_today_geo_digests,
)


def _event(title="BTC hack", source="CoinDesk", url="https://x.com", panic_score=80):
    return BreakingEvent(title=title, source=source, url=url, panic_score=panic_score)


# ============================================================================
# is_geo_event() — classification
# ============================================================================


class TestIsGeoEvent:
    """QO.14: is_geo_event() classifies geopolitical events correctly."""

    def test_war_is_geo(self):
        """War without crypto context → geo event."""
        assert is_geo_event("War erupts in Middle East") is True

    def test_sanctions_is_geo(self):
        assert is_geo_event("US imposes new sanctions on Russian oil") is True

    def test_fed_is_geo(self):
        """Fed rate decisions → geo (macro) event."""
        assert is_geo_event("Fed raises interest rate by 75 bps") is True

    def test_inflation_is_geo(self):
        assert is_geo_event("Inflation hits 9.1% in June — highest in 40 years") is True

    def test_missile_is_geo(self):
        assert is_geo_event("Missile strikes reported in Eastern Europe") is True

    def test_tariff_is_geo(self):
        assert is_geo_event("New tariff imposed on Chinese imports") is True

    def test_bitcoin_not_geo(self):
        """Pure crypto event → NOT geo."""
        assert is_geo_event("Bitcoin drops 10% in flash crash") is False

    def test_hack_not_geo(self):
        """Crypto hack → NOT geo."""
        assert is_geo_event("Major exchange hack — $100M stolen") is False

    def test_fed_with_bitcoin_context_not_geo(self):
        """Fed + crypto context → crypto event, NOT geo.
        WHY: 'Fed rate cut boosts Bitcoin' is a crypto event with macro context.
        """
        assert is_geo_event("Fed rate cut boosts Bitcoin to new highs") is False

    def test_sanctions_with_crypto_not_geo(self):
        """Sanctions + crypto context → NOT geo."""
        assert is_geo_event("Sanctions impact crypto exchange operations") is False

    def test_empty_title_not_geo(self):
        assert is_geo_event("") is False

    def test_normal_news_not_geo(self):
        assert is_geo_event("Apple releases new iPhone model") is False

    def test_invasion_is_geo(self):
        assert is_geo_event("Military invasion reported in Eastern Europe") is True

    def test_oil_crisis_is_geo(self):
        assert is_geo_event("Global oil crisis deepens as OPEC cuts supply") is True

    def test_interest_rate_is_geo(self):
        assert is_geo_event("ECB raises interest rate to combat inflation") is True

    def test_escalation_is_geo(self):
        assert is_geo_event("Military escalation in the Pacific") is True

    def test_war_with_mining_not_geo(self):
        """War + crypto mining context → NOT geo (crypto-specific)."""
        assert is_geo_event("War impacts crypto mining operations in region") is False


# ============================================================================
# Constants
# ============================================================================


class TestGeoConstants:
    """QO.14: Verify geo-related constants."""

    def test_max_geo_digests_per_day(self):
        assert MAX_GEO_DIGESTS_PER_DAY == 3

    def test_geo_critical_panic_threshold(self):
        assert GEO_CRITICAL_PANIC_THRESHOLD == 90


# ============================================================================
# _count_today_geo_digests
# ============================================================================


class TestCountTodayGeoDigests:
    """QO.14: _count_today_geo_digests counts sent_geo_digest events."""

    def test_empty_dedup(self):
        mgr = DedupManager()
        assert _count_today_geo_digests(mgr) == 0

    def test_counts_sent_geo_digest(self):
        now = datetime.now(timezone.utc)
        entries = [
            DedupEntry(
                hash=f"h{i}",
                title=f"Geo event {i}",
                source="S",
                status="sent_geo_digest",
                detected_at=now.isoformat(),
            )
            for i in range(3)
        ]
        mgr = DedupManager(existing_entries=entries)
        assert _count_today_geo_digests(mgr) == 3

    def test_excludes_sent_digest(self):
        """Regular sent_digest should NOT count as geo digest."""
        now = datetime.now(timezone.utc)
        entries = [
            DedupEntry(
                hash="h1",
                title="Crypto event",
                source="S",
                status="sent_digest",
                detected_at=now.isoformat(),
            )
        ]
        mgr = DedupManager(existing_entries=entries)
        assert _count_today_geo_digests(mgr) == 0

    def test_excludes_sent(self):
        """Regular 'sent' should NOT count as geo digest."""
        now = datetime.now(timezone.utc)
        entries = [
            DedupEntry(
                hash="h1",
                title="Event",
                source="S",
                status="sent",
                detected_at=now.isoformat(),
            )
        ]
        mgr = DedupManager(existing_entries=entries)
        assert _count_today_geo_digests(mgr) == 0

    def test_excludes_yesterday(self):
        """Yesterday's geo digests should NOT count."""
        from datetime import timedelta

        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        entries = [
            DedupEntry(
                hash="h1",
                title="Old geo event",
                source="S",
                status="sent_geo_digest",
                detected_at=yesterday.isoformat(),
            )
        ]
        mgr = DedupManager(existing_entries=entries)
        assert _count_today_geo_digests(mgr) == 0


# ============================================================================
# Geo event separation logic
# ============================================================================


class TestGeoEventSeparation:
    """QO.14: Geo events separated from crypto events for digest routing."""

    def test_geo_event_identified_for_digest(self):
        """Geo event with non-critical panic → should be routed to digest."""
        event = _event("War erupts in Middle East", panic_score=60)
        assert is_geo_event(event.title) is True
        assert event.panic_score < GEO_CRITICAL_PANIC_THRESHOLD

    def test_critical_geo_bypasses_digest(self):
        """Geo event with panic >= 90 → treated as crypto (individual)."""
        event = _event("Nuclear attack imminent — DEFCON 1", panic_score=95)
        # The pipeline checks: is_geo_event AND panic < 90
        # panic=95 >= 90, so it stays in crypto_events (individual)
        assert is_geo_event(event.title) is True
        assert event.panic_score >= GEO_CRITICAL_PANIC_THRESHOLD

    def test_crypto_event_stays_individual(self):
        """Crypto events are NOT classified as geo."""
        event = _event("Bitcoin drops 15% in flash crash", panic_score=80)
        assert is_geo_event(event.title) is False


# ============================================================================
# _count_today_sent_events includes geo digests
# ============================================================================


class TestCountTodaySentIncludesGeo:
    """QO.14: _count_today_sent_events counts sent_geo_digest too."""

    def test_sent_geo_digest_counted_in_daily_cap(self):
        """sent_geo_digest should count toward MAX_EVENTS_PER_DAY."""
        from cic_daily_report.breaking_pipeline import _count_today_sent_events

        now = datetime.now(timezone.utc)
        entries = [
            DedupEntry(
                hash="h1",
                title="Geo event",
                source="S",
                status="sent_geo_digest",
                detected_at=now.isoformat(),
            ),
            DedupEntry(
                hash="h2",
                title="Crypto event",
                source="S",
                status="sent",
                detected_at=now.isoformat(),
            ),
        ]
        mgr = DedupManager(existing_entries=entries)
        assert _count_today_sent_events(mgr) == 2
