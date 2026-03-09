"""End-to-end integration tests for breaking news pipeline (Story 5.5).

Verifies full flow: detect → dedup → generate → classify → deliver.
All external APIs mocked.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

from cic_daily_report.adapters.llm_adapter import LLMResponse
from cic_daily_report.breaking.content_generator import generate_breaking_content
from cic_daily_report.breaking.dedup_manager import DedupEntry, DedupManager, compute_hash
from cic_daily_report.breaking.event_detector import BreakingEvent
from cic_daily_report.breaking.severity_classifier import (
    CRITICAL,
    IMPORTANT,
    NOTABLE,
    VN_TZ,
    classify_batch,
    classify_event,
)
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

    async def test_night_mode_notable_deferred_daily(self):
        """🟡 Notable events deferred to daily report during night."""
        event = _event("Whale movement", "Blockchain.com", 30)
        classified = classify_event(event, now=_vn_time(3))
        assert classified.severity == NOTABLE
        assert classified.delivery_action == "deferred_to_daily"

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
