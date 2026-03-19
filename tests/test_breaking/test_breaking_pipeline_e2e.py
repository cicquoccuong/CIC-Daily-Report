"""End-to-end integration tests for breaking news pipeline (Story 5.5).

Verifies full flow: detect → dedup → generate → classify → deliver.
Includes fallback chain tests: CryptoPanic → RSS+LLM → Market triggers.
All external APIs mocked.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from cic_daily_report.adapters.llm_adapter import LLMResponse
from cic_daily_report.breaking.content_generator import generate_breaking_content
from cic_daily_report.breaking.dedup_manager import DedupEntry, DedupManager, compute_hash
from cic_daily_report.breaking.event_detector import BreakingEvent
from cic_daily_report.breaking.llm_scorer import score_rss_articles
from cic_daily_report.breaking.market_trigger import detect_market_triggers
from cic_daily_report.breaking.severity_classifier import (
    CRITICAL,
    IMPORTANT,
    NOTABLE,
    VN_TZ,
    classify_batch,
    classify_event,
)
from cic_daily_report.collectors.market_data import MarketDataPoint
from cic_daily_report.collectors.rss_collector import NewsArticle
from cic_daily_report.generators.article_generator import DISCLAIMER


def _event(title="BTC hack alert", source="CoinDesk", panic_score=85) -> BreakingEvent:
    return BreakingEvent(
        title=title,
        source=source,
        url="https://example.com/news",
        panic_score=panic_score,
    )


def _mock_llm() -> AsyncMock:
    mock = AsyncMock()
    mock.generate = AsyncMock(
        return_value=LLMResponse(
            text="Tin nóng: sự kiện tài sản mã hóa quan trọng.",
            tokens_used=50,
            model="test-model",
        )
    )
    mock.last_provider = "groq"
    return mock


def _vn_time(hour: int) -> datetime:
    return datetime(2026, 3, 9, hour, 0, tzinfo=VN_TZ)


class TestFullBreakingFlow:
    async def test_new_event_detected_and_sent(self):
        """Full flow: detect → dedup (new) → classify → generate → content ready."""
        event = _event("Major exchange hack", "Reuters", 90)
        llm = _mock_llm()

        # Dedup: new event passes
        mgr = DedupManager()
        dedup_result = mgr.check_and_filter([event])
        assert len(dedup_result.new_events) == 1

        # Classify: critical
        classified = classify_event(event, now=_vn_time(12))
        assert classified.severity == CRITICAL
        assert classified.delivery_action == "send_now"

        # Generate content
        content = await generate_breaking_content(event, llm, severity=classified.severity)
        assert content.ai_generated
        assert content.word_count > 0

    async def test_duplicate_event_skipped(self):
        """Duplicate event within cooldown window is skipped."""
        event = _event()
        mgr = DedupManager()

        # First detection
        result1 = mgr.check_and_filter([event])
        assert len(result1.new_events) == 1

        # Same event again
        result2 = mgr.check_and_filter([event])
        assert len(result2.new_events) == 0
        assert result2.duplicates_skipped == 1

    async def test_night_mode_critical_sends_immediately(self):
        """🔴 Critical events sent even during night (01:00 VN)."""
        event = _event("Exchange collapse", "Reuters", 95)
        classified = classify_event(event, now=_vn_time(1))
        assert classified.severity == CRITICAL
        assert classified.delivery_action == "send_now"

    async def test_night_mode_important_deferred_morning(self):
        """🟠 Important events deferred to morning during night."""
        event = _event("SEC investigation", "Bloomberg", 50)
        classified = classify_event(event, now=_vn_time(2))
        assert classified.severity == IMPORTANT
        assert classified.delivery_action == "deferred_to_morning"
        assert classified.is_deferred

    async def test_night_mode_notable_skipped(self):
        """C2: Notable events skipped during night (was deferred_to_daily, never consumed)."""
        event = _event("Whale movement", "Blockchain.com", 30)
        classified = classify_event(event, now=_vn_time(3))
        assert classified.severity == NOTABLE
        assert classified.delivery_action == "skipped"

    async def test_edge_case_2259_vn_not_night(self):
        """22:59 VN = NOT night mode, 🟠 sends immediately."""
        event = _event("SEC update", "Reuters", 50)
        now = datetime(2026, 3, 9, 22, 59, tzinfo=VN_TZ)
        classified = classify_event(event, now=now)
        assert classified.severity == IMPORTANT
        assert classified.delivery_action == "send_now"

    async def test_edge_case_2301_vn_is_night(self):
        """23:01 VN = night mode, 🟠 deferred."""
        event = _event("SEC update", "Reuters", 50)
        now = datetime(2026, 3, 9, 23, 1, tzinfo=VN_TZ)
        classified = classify_event(event, now=now)
        assert classified.severity == IMPORTANT
        assert classified.delivery_action == "deferred_to_morning"

    async def test_content_has_nq05_disclaimer(self):
        """All generated content includes NQ05 disclaimer."""
        llm = _mock_llm()
        content = await generate_breaking_content(_event(), llm)
        assert "Tuyên bố miễn trừ trách nhiệm" in content.content

    async def test_llm_failure_raw_fallback(self):
        """When all LLMs fail, raw data sent with warning."""
        llm = AsyncMock()
        llm.generate = AsyncMock(side_effect=Exception("All failed"))
        content = await generate_breaking_content(_event(), llm)
        assert not content.ai_generated
        assert "AI không khả dụng" in content.content
        assert DISCLAIMER in content.content

    async def test_batch_classify_mixed_severities(self):
        """Multiple events classified with different severities."""
        events = [
            _event("Exchange hack", "A", 90),
            _event("SEC hearing", "B", 50),
            _event("Market dip", "C", 20),
        ]
        results = classify_batch(events, now=_vn_time(12))
        severities = [r.severity for r in results]
        assert CRITICAL in severities
        assert IMPORTANT in severities
        assert NOTABLE in severities

    async def test_dedup_cleanup_old_entries(self):
        """Old entries (>7 days) cleaned up."""
        old_time = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        recent_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        entries = [
            DedupEntry(hash="old", title="Old", source="S", detected_at=old_time),
            DedupEntry(hash="new", title="New", source="S", detected_at=recent_time),
        ]
        mgr = DedupManager(existing_entries=entries)
        removed = mgr.cleanup_old_entries()
        assert removed == 1
        assert len(mgr.entries) == 1

    async def test_deferred_events_retrievable(self):
        """Deferred events can be retrieved for morning batch delivery."""
        mgr = DedupManager()
        event = _event("SEC news", "Reuters", 50)
        mgr.check_and_filter([event])
        h = compute_hash(event.title, event.source)
        mgr.update_entry_status(h, "deferred_to_morning")
        deferred = mgr.get_deferred_events("deferred_to_morning")
        assert len(deferred) == 1
        assert deferred[0].title == "SEC news"


class TestFallbackChain:
    """Tests for CryptoPanic → RSS+LLM → Market trigger fallback chain."""

    async def test_rss_fallback_detects_keyword_events(self):
        """RSS fallback catches breaking events via keyword matching."""
        articles = [
            NewsArticle(
                title="Major exchange hack discovered",
                url="https://example.com/hack",
                source_name="CoinDesk",
                published_date="",
                summary="A major hack was detected.",
                language="en",
            ),
            NewsArticle(
                title="Normal market update",
                url="https://example.com/normal",
                source_name="Reuters",
                published_date="",
                summary="Markets are stable.",
                language="en",
            ),
        ]
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value=MagicMock(text='[{"index": 0, "score": 30}]'))

        events = await score_rss_articles(articles, mock_llm)
        assert len(events) == 1
        assert "hack" in events[0].matched_keywords
        assert events[0].raw_data["source_type"] == "rss_fallback"

    async def test_rss_fallback_then_classify_and_generate(self):
        """Full chain: RSS fallback → classify → generate content."""
        articles = [
            NewsArticle(
                title="Crypto exchange collapse reported",
                url="https://example.com/collapse",
                source_name="Reuters",
                published_date="",
                summary="Major exchange has collapsed.",
                language="en",
            ),
        ]
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value=MagicMock(text='[{"index": 0, "score": 30}]'))

        events = await score_rss_articles(articles, mock_llm)
        assert len(events) == 1

        # Classify
        classified = classify_event(events[0], now=_vn_time(12))
        assert classified.severity == CRITICAL  # "collapse" keyword
        assert classified.delivery_action == "send_now"

        # Generate content
        gen_llm = _mock_llm()
        content = await generate_breaking_content(events[0], gen_llm, severity=classified.severity)
        assert content.ai_generated
        assert content.word_count > 0

    async def test_market_trigger_btc_crash(self):
        """Market trigger detects BTC crash and creates event."""
        market_data = [
            MarketDataPoint(
                symbol="BTC",
                price=42000,
                change_24h=-9.5,
                volume_24h=1e10,
                market_cap=8e11,
                data_type="crypto",
                source="CoinLore",
            ),
        ]

        events = detect_market_triggers(market_data)
        assert len(events) == 1
        assert "BTC" in events[0].title
        assert events[0].raw_data["source_type"] == "market_trigger"

        # "crash" is an important keyword (not critical)
        classified = classify_event(events[0], now=_vn_time(14))
        assert classified.severity == IMPORTANT

    async def test_market_trigger_no_crash(self):
        """Normal market conditions produce no events."""
        market_data = [
            MarketDataPoint(
                symbol="BTC",
                price=50000,
                change_24h=-2.0,
                volume_24h=1e10,
                market_cap=1e12,
                data_type="crypto",
                source="CoinLore",
            ),
        ]
        events = detect_market_triggers(market_data)
        assert len(events) == 0

    async def test_combined_sources_dedup(self):
        """Events from multiple sources are deduped correctly."""
        # Simulate: RSS fallback + market trigger both fire
        rss_event = _event("BTC crash alert", "CoinDesk", 80)
        market_event = BreakingEvent(
            title="BTC giảm -8.0% trong 24h — giá hiện tại $46,000",
            source="market_data",
            url="",
            panic_score=72,
            matched_keywords=["crash"],
            raw_data={"source_type": "market_trigger"},
        )

        all_events = [rss_event, market_event]

        # Dedup should keep both (different titles/hashes)
        mgr = DedupManager()
        dedup_result = mgr.check_and_filter(all_events)
        assert len(dedup_result.new_events) == 2

    async def test_rss_llm_failure_graceful(self):
        """When LLM scoring fails, only keyword matches survive."""
        articles = [
            NewsArticle(
                title="SEC bans crypto trading",
                url="https://example.com/sec",
                source_name="Reuters",
                published_date="",
                summary="SEC imposes new ban.",
                language="en",
            ),
            NewsArticle(
                title="Normal market update",
                url="https://example.com/normal",
                source_name="CNN",
                published_date="",
                summary="Nothing happened.",
                language="en",
            ),
        ]
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(side_effect=Exception("LLM timeout"))

        events = await score_rss_articles(articles, mock_llm)
        # Only "SEC" and "ban" keyword matches survive
        assert len(events) == 1
        assert "SEC" in events[0].matched_keywords or "ban" in events[0].matched_keywords


class TestPhase2Helpers:
    """Phase 2: Market snapshot and recent events formatting helpers."""

    def test_format_market_snapshot(self):
        """Market data → formatted string with BTC, ETH, F&G, DXY."""
        from cic_daily_report.breaking_pipeline import _format_market_snapshot

        market_data = [
            MarketDataPoint(
                symbol="BTC",
                price=74589,
                change_24h=0.5,
                volume_24h=1e10,
                market_cap=1e12,
                data_type="crypto",
                source="CoinLore",
            ),
            MarketDataPoint(
                symbol="ETH",
                price=2450,
                change_24h=-1.2,
                volume_24h=5e9,
                market_cap=3e11,
                data_type="crypto",
                source="CoinLore",
            ),
            MarketDataPoint(
                symbol="Fear_Greed",
                price=26,
                change_24h=0,
                volume_24h=0,
                market_cap=0,
                data_type="index",
                source="Alternative.me",
            ),
            MarketDataPoint(
                symbol="DXY",
                price=99.8,
                change_24h=-0.3,
                volume_24h=0,
                market_cap=0,
                data_type="index",
                source="FairEconomy",
            ),
        ]
        result = _format_market_snapshot(market_data)
        assert "BTC: $74,589" in result
        assert "ETH: $2,450" in result
        assert "Fear & Greed: 26" in result
        assert "DXY: 99.8" in result

    def test_format_market_snapshot_empty(self):
        from cic_daily_report.breaking_pipeline import _format_market_snapshot

        assert _format_market_snapshot(None) == ""
        assert _format_market_snapshot([]) == ""

    def test_format_recent_events(self):
        """10 entries → return top 5 most recent."""
        from cic_daily_report.breaking_pipeline import _format_recent_events

        entries = [
            DedupEntry(
                hash=f"h{i}",
                title=f"Event {i}",
                source="src",
                severity="notable",
                detected_at=f"2026-03-18T0{i}:00:00Z",
            )
            for i in range(10)
        ]
        result = _format_recent_events(entries)
        assert "Tin Breaking gần đây" in result
        # Top 5 most recent (by detected_at descending)
        assert "Event 9" in result
        assert "Event 5" in result
        assert "Event 4" not in result  # 6th most recent, excluded

    def test_format_recent_events_empty(self):
        from cic_daily_report.breaking_pipeline import _format_recent_events

        assert _format_recent_events([]) == ""


class TestPhase3CoinFilter:
    """Phase 3 B2: Coin whitelist filter."""

    def test_filter_non_cic_coin(self):
        """PIPPIN event → filtered out (not in CIC list)."""
        from cic_daily_report.breaking_pipeline import _filter_non_cic_coins

        events = [_event("PIPPIN crashes 49%", "CoinDesk")]
        tracked = {"BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE"}
        result = _filter_non_cic_coins(events, tracked)
        assert len(result) == 0

    def test_keep_cic_coin(self):
        """BTC event → kept."""
        from cic_daily_report.breaking_pipeline import _filter_non_cic_coins

        events = [_event("BTC drops 5%", "CoinDesk")]
        tracked = {"BTC", "ETH", "SOL"}
        result = _filter_non_cic_coins(events, tracked)
        assert len(result) == 1

    def test_keep_macro_event(self):
        """Non-coin event (regulatory/macro) → kept."""
        from cic_daily_report.breaking_pipeline import _filter_non_cic_coins

        events = [_event("Argentina bans Polymarket", "Reuters")]
        tracked = {"BTC", "ETH", "SOL"}
        result = _filter_non_cic_coins(events, tracked)
        assert len(result) == 1  # No known coin symbol → always keep

    def test_empty_whitelist_keeps_all(self):
        """No whitelist → keep all events."""
        from cic_daily_report.breaking_pipeline import _filter_non_cic_coins

        events = [_event("PIPPIN crashes"), _event("BTC drops")]
        result = _filter_non_cic_coins(events, set())
        assert len(result) == 2
