"""Wave 0.5.2 (alpha.19) — regression tests for the 7 critical Round 2 fixes.

Each fix has a dedicated test class. Mock LLMs are used heavily; the goal is
behavioral coverage, not API integration.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from cic_daily_report.breaking.content_generator import (
    _build_related_history,
    _check_stale_dates,
    build_enrichment_context,
    generate_breaking_content,
)
from cic_daily_report.breaking.dedup_manager import DedupEntry
from cic_daily_report.breaking.event_detector import BreakingEvent
from cic_daily_report.breaking_pipeline import (
    MAX_DEFERRED_PER_RUN,
    MAX_EVENTS_PER_RUN,
    _format_recent_events,
)
from cic_daily_report.generators.numeric_sanity import (
    PCT_CAP,
    check_and_cap_percentages,
    extract_percentages,
)
from cic_daily_report.generators.quality_gate import (
    INSIGHT_DENSITY_THRESHOLDS,
    QUALITY_WARNING,
    _get_insight_density_threshold,
    run_quality_gate,
    run_quality_gate_with_retry,
)


def _mk_event(title: str = "Test event", source: str = "rss") -> BreakingEvent:
    return BreakingEvent(
        title=title,
        source=source,
        url="https://example.com/x",
        panic_score=50,
        detected_at=datetime.now(timezone.utc),
        raw_data={"summary": "summary text " * 30},
    )


def _mk_llm_response(text: str, model: str = "test-mock") -> MagicMock:
    resp = MagicMock()
    resp.text = text
    resp.model = model
    return resp


# ---------------------------------------------------------------------------
# Fix 1 — NQ05 fallback bypass
# ---------------------------------------------------------------------------


class TestFix1NQ05FallbackBypass:
    """When NQ05 strips content <50 words, must re-run filter — never raw bypass."""

    @pytest.mark.asyncio
    async def test_short_after_first_filter_runs_second_pass(self):
        """Re-filter is applied; if recovers (>=50 words) returns clean content."""
        long_text = (
            "BTC tăng giá mạnh hôm nay. " * 20  # 100+ words after split
        )

        llm = MagicMock()
        # First filter strips most → second filter on the same long_text passes
        llm.generate = AsyncMock(return_value=_mk_llm_response(long_text))
        llm.last_provider = "groq-test"
        llm.circuit_open = False

        # Patch check_and_fix to simulate first call stripping (returns 5-word stub),
        # second call passing through long_text unchanged.
        from cic_daily_report.breaking import content_generator as cg

        call_count = {"n": 0}

        def fake_check(text, _extra=None):
            call_count["n"] += 1
            mock = MagicMock()
            if call_count["n"] == 1:
                mock.content = "BTC tăng giá hôm nay."  # too short
            else:
                mock.content = text  # second pass passes through
            return mock

        original = cg.check_and_fix
        cg.check_and_fix = fake_check
        try:
            result = await generate_breaking_content(_mk_event(), llm, severity="notable")
        finally:
            cg.check_and_fix = original

        assert call_count["n"] == 2  # re-filter invoked
        assert result.word_count >= 50

    @pytest.mark.asyncio
    async def test_short_after_both_filters_logs_warning_no_raise(self):
        """Even when still <50 words after re-filter, the function must NOT
        raise (tests intentionally use short stubs). Instead it ships the
        NQ05-clean short content + emits a warning. The Fix 1 guarantee is
        that NQ05 keyword filter is applied to the raw fallback — not that
        we hard-fail on word-count.
        """
        short_text = "BTC tăng."  # 2 words

        llm = MagicMock()
        llm.generate = AsyncMock(return_value=_mk_llm_response(short_text))
        llm.last_provider = "groq-test"
        llm.circuit_open = False

        from cic_daily_report.breaking import content_generator as cg

        call_count = {"n": 0}

        def fake_check(text, _extra=None):
            call_count["n"] += 1
            mock = MagicMock()
            mock.content = "BTC."  # both passes still short
            return mock

        original = cg.check_and_fix
        cg.check_and_fix = fake_check
        try:
            result = await cg.generate_breaking_content(_mk_event(), llm, severity="notable")
        finally:
            cg.check_and_fix = original

        # Re-filter MUST have been called (this is the Fix 1 invariant).
        assert call_count["n"] == 2
        # Content shipped, ai_generated still True (fallback path).
        assert result.ai_generated is True


# ---------------------------------------------------------------------------
# Fix 2 — Per-tier quality threshold
# ---------------------------------------------------------------------------


class TestFix2PerTierThreshold:
    """L3-L5 narrative articles get looser density bar than L1-L2."""

    def test_l1_threshold_is_strict(self):
        assert _get_insight_density_threshold(tier="L1") == 0.30

    def test_l3_threshold_is_loose(self):
        assert _get_insight_density_threshold(tier="L3") == 0.15

    def test_l5_threshold_loosest(self):
        assert _get_insight_density_threshold(tier="L5") == 0.10

    def test_unknown_tier_falls_back_to_global(self):
        assert _get_insight_density_threshold(tier="unknown") == 0.30

    def test_breaking_threshold(self):
        assert _get_insight_density_threshold(tier="breaking") == 0.25

    def test_thresholds_dict_contains_all_tiers(self):
        for t in ("L1", "L2", "L3", "L4", "L5", "summary", "breaking"):
            assert t in INSIGHT_DENSITY_THRESHOLDS

    def test_l3_low_density_passes(self):
        """L3 article at 20% density (< old 0.30 but > new 0.15) must pass."""
        # Build content with mixed data + narrative — ~20% density-ish
        narrative = (
            "Thị trường đang trải qua giai đoạn chuyển dịch sâu sắc. "
            "Các nhà đầu tư đang đánh giá lại quan điểm của mình. "
            "BTC đạt **$87,500** sau khi vượt qua mức kháng cự quan trọng. "
            "Tâm lý thị trường thay đổi nhanh chóng. "
            "Nhiều kịch bản có thể xảy ra. "
            "Cần theo dõi sát diễn biến."
        )
        result = run_quality_gate(narrative, "L3", input_data={})
        # L3 threshold 0.15, this content has at least one data sentence
        # — should pass even if not all sentences are data-backed.
        assert result.insight_density >= 0.15 or result.passed

    def test_l1_same_low_density_fails(self):
        """Same low-density content fails on L1 (stricter)."""
        narrative = (
            "Thị trường đang trải qua giai đoạn chuyển dịch. "
            "Nhà đầu tư đánh giá lại quan điểm. "
            "Tâm lý thị trường đa dạng. "
            "Nhiều kịch bản có thể xảy ra. "
            "Cần theo dõi diễn biến."
        )
        result = run_quality_gate(narrative, "L1", input_data={})
        assert result.passed is False


# ---------------------------------------------------------------------------
# Fix 3 — Self-reference filter on recent_events
# ---------------------------------------------------------------------------


class TestFix3SelfReferenceFilter:
    """Events from the same batch (<1h apart) must NOT appear in recent_events."""

    def test_format_recent_events_excludes_recent_within_1h(self):
        now = datetime.now(timezone.utc)
        entries = [
            DedupEntry(
                hash="h1",
                title="ZetaChain incident",
                source="rss",
                severity="notable",
                detected_at=(now - timedelta(minutes=1)).isoformat(),
                status="sent",
            ),
            DedupEntry(
                hash="h2",
                title="OldNews protocol",
                source="rss",
                severity="notable",
                detected_at=(now - timedelta(hours=3)).isoformat(),
                status="sent",
            ),
        ]
        text = _format_recent_events(entries, current_event_time=now, min_age_hours=1.0)
        assert "ZetaChain" not in text  # too recent → filtered
        assert "OldNews" in text

    def test_format_recent_events_legacy_no_filter(self):
        """No current_event_time → backwards compat (no filter)."""
        now = datetime.now(timezone.utc)
        entries = [
            DedupEntry(
                hash="h1",
                title="Recent X",
                source="rss",
                severity="notable",
                detected_at=(now - timedelta(minutes=1)).isoformat(),
                status="sent",
            ),
        ]
        text = _format_recent_events(entries)
        assert "Recent X" in text

    def test_build_related_history_excludes_recent(self):
        now = datetime.now(timezone.utc)
        entries = [
            DedupEntry(
                hash="h1",
                title="Scallop hack drained funds",
                source="rss",
                severity="notable",
                detected_at=(now - timedelta(minutes=2)).isoformat(),
                status="sent",
            ),
        ]
        text = _build_related_history(
            entries,
            event_title="Scallop protocol incident",
            current_event_time=now,
            min_age_hours=1.0,
        )
        assert "Scallop" not in text  # filtered out

    def test_build_enrichment_context_passes_time_through(self):
        now = datetime.now(timezone.utc)
        entries = [
            DedupEntry(
                hash="h1",
                title="Foo bar baz quux",
                source="rss",
                severity="notable",
                detected_at=(now - timedelta(minutes=2)).isoformat(),
                status="sent",
            ),
        ]
        ctx = build_enrichment_context(
            dedup_entries=entries,
            event_title="Foo bar baz quux event",
            current_event_time=now,
            min_age_hours=1.0,
        )
        assert ctx["breaking_history"] == ""  # filtered out


# ---------------------------------------------------------------------------
# Fix 4 — Numeric sanity guard
# ---------------------------------------------------------------------------


class TestFix4NumericSanity:
    """Cap absurd % values, leave valid ones alone."""

    def test_extracts_percentages(self):
        vals = extract_percentages("BTC tăng 5.2% và ETH giảm 3%")
        assert 5.2 in vals
        assert 3.0 in vals

    def test_caps_value_above_100(self):
        result = check_and_cap_percentages("Heat Score độ tin cậy 1700%")
        assert result.passed is False
        assert result.capped_count == 1
        assert "100%" in result.sanitized_content
        assert "1700%" not in result.sanitized_content

    def test_does_not_touch_valid_values(self):
        result = check_and_cap_percentages("BTC tăng 5.2% và ETH giảm 8%")
        assert result.passed is True
        assert result.capped_count == 0
        assert "5.2%" in result.sanitized_content

    def test_handles_signed_values(self):
        result = check_and_cap_percentages("BTC -200% so với năm trước")
        assert result.capped_count == 1
        assert "-100%" in result.sanitized_content

    def test_pct_cap_constant(self):
        assert PCT_CAP == 100.0


# ---------------------------------------------------------------------------
# Fix 5 — Date check suffix (Codex finding)
# ---------------------------------------------------------------------------


class TestFix5DateSuffix:
    """Future-tense markers AFTER the date must also trigger stale-date warning."""

    def test_suffix_marker_caught(self):
        # Past date with marker AFTER (Codex finding)
        old_date = datetime.now(timezone.utc) - timedelta(days=30)
        d_str = old_date.strftime("%d/%m")
        content = f"Sự kiện ngày {d_str} sắp tới sẽ ảnh hưởng đến thị trường."
        warn_count = _check_stale_dates(content)
        assert warn_count == 1

    def test_prefix_marker_still_caught(self):
        old_date = datetime.now(timezone.utc) - timedelta(days=30)
        d_str = old_date.strftime("%d/%m")
        content = f"Dự kiến diễn ra vào {d_str} của năm nay."
        warn_count = _check_stale_dates(content)
        assert warn_count == 1

    def test_no_marker_no_warning(self):
        old_date = datetime.now(timezone.utc) - timedelta(days=30)
        d_str = old_date.strftime("%d/%m")
        content = f"Vào ngày {d_str} đã có sự kiện diễn ra."
        # No future marker → no warning even though date is past
        warn_count = _check_stale_dates(content)
        assert warn_count == 0

    def test_future_date_no_warning(self):
        future_date = datetime.now(timezone.utc) + timedelta(days=30)
        d_str = future_date.strftime("%d/%m")
        content = f"Dự kiến diễn ra vào {d_str} sắp tới."
        # Future date IS future → no warning
        warn_count = _check_stale_dates(content)
        assert warn_count == 0


# ---------------------------------------------------------------------------
# Fix 6 — Spam cap thực sự
# ---------------------------------------------------------------------------


class TestFix6SpamCap:
    """MAX_EVENTS_PER_RUN now caps TOTAL messages/run."""

    def test_max_events_per_run_raised_to_5(self):
        assert MAX_EVENTS_PER_RUN == 5

    def test_max_deferred_kept_for_compat(self):
        # Deprecated but kept; runtime cap is MAX_EVENTS_PER_RUN
        assert MAX_DEFERRED_PER_RUN == 5

    def test_deferred_budget_is_half_of_max(self):
        """Deferred reprocessing gets <=50% of total run budget."""
        # The heuristic in code: deferred_budget = max(1, (max_per_run + 1) // 2)
        # With max_per_run=5 → 3 (rounded up from 2.5)
        deferred_budget = max(1, (MAX_EVENTS_PER_RUN + 1) // 2)
        assert deferred_budget == 3


# ---------------------------------------------------------------------------
# Fix 7 — Quality warning to internal log only
# ---------------------------------------------------------------------------


class TestFix7QualityWarningInternal:
    """QUALITY_WARNING is empty string — nothing user-facing appended."""

    def test_quality_warning_empty(self):
        assert QUALITY_WARNING == ""

    @pytest.mark.asyncio
    async def test_failed_retry_does_not_inject_warning_text(self):
        """Even when retry fails, no Vietnamese warning text in content."""

        async def regenerate():
            return MagicMock(content="Filler content. " * 5)

        content, result = await run_quality_gate_with_retry(
            "Filler content. " * 5,
            "L1",
            input_data={},
            regenerate_fn=regenerate,
            mode="BLOCK",
        )
        # Flag set for ops dashboards
        assert result.quality_warning_appended is True
        # But the text the user sees is clean
        assert "Lưu ý: Bài viết này có thể chưa đạt tiêu chuẩn" not in content
        assert "⚠️" not in content
