"""Wave 0.5 EMERGENCY hotfix (alpha.18) — regression tests for the 6 P0 fixes.

Audit 27-28/04/2026 found 18 bugs in breaking pipeline (87.5% fabricated
historical claims). These tests lock in the corrective behavior so the bugs
cannot silently regress.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cic_daily_report.breaking.content_generator import (
    BREAKING_PROMPT_TEMPLATE,
    _check_stale_dates,
    _format_source,
    generate_breaking_content,
)
from cic_daily_report.breaking.dedup_manager import (
    SIMILARITY_THRESHOLD,
    DedupEntry,
    DedupManager,
    _extract_reg_bill_ids,
    _is_similar_to_recent,
)
from cic_daily_report.breaking.event_detector import BreakingEvent
from cic_daily_report.generators.nq05_filter import check_and_fix

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _event(
    title: str = "Sample breaking event",
    url: str = "https://example.com/x",
) -> BreakingEvent:
    return BreakingEvent(
        title=title,
        source="rss",
        url=url,
        panic_score=80,
        raw_data={"summary": "Body text for testing."},
    )


def _mock_llm(response_text: str = "Sample generated body. " * 20) -> MagicMock:
    llm = MagicMock()
    response = MagicMock()
    response.text = response_text
    response.model = "test-llm"
    llm.generate = AsyncMock(return_value=response)
    llm.last_provider = "test"
    return llm


# ---------------------------------------------------------------------------
# Fix 1 — Historical instruction REMOVED (smoking gun)
# ---------------------------------------------------------------------------


class TestFix1HistoricalRemoved:
    """Wave 0.5: prompt MUST NOT contain hardcoded historical example."""

    def test_template_has_no_hardcoded_fed_example(self):
        # Template still has the {historical_instruction} placeholder, but the
        # interpolated value must be empty — so the rendered prompt cannot
        # contain the smoking-gun example anymore.
        assert "{historical_instruction}" in BREAKING_PROMPT_TEMPLATE
        # The example string must NOT appear in the static template either.
        assert "06/2022" not in BREAKING_PROMPT_TEMPLATE
        assert "75 bps" not in BREAKING_PROMPT_TEMPLATE
        assert "BTC giảm 15% trong 48h" not in BREAKING_PROMPT_TEMPLATE

    @pytest.mark.asyncio
    async def test_critical_prompt_excludes_historical(self):
        llm = _mock_llm()
        await generate_breaking_content(_event(), llm, severity="critical")
        prompt = llm.generate.call_args.kwargs.get("prompt") or llm.generate.call_args.args[0]
        assert "THAM CHIẾU LỊCH SỬ" not in prompt
        assert "Fed" not in prompt or "Lần cuối Fed" not in prompt
        assert "15%" not in prompt
        assert "06/2022" not in prompt


# ---------------------------------------------------------------------------
# Fix 2 — NQ05 patterns expanded
# ---------------------------------------------------------------------------


class TestFix2NQ05Patterns:
    """Wave 0.5: 3 new advisory patterns must be filtered."""

    @pytest.mark.parametrize(
        "phrase",
        [
            "Nhà đầu tư tích lũy dài hạn cần theo dõi diễn biến.",
            "Nhà đầu tư chiến lược cần lưu ý rủi ro thanh khoản.",
            "Đây là khuyến nghị cho nhà đầu tư chiến lược.",
        ],
    )
    def test_new_patterns_are_filtered(self, phrase: str):
        result = check_and_fix(phrase)
        # The violating sentence must be removed from output.
        assert phrase not in result.content
        assert result.violations_found >= 1


# ---------------------------------------------------------------------------
# Fix 3 — Dedup similarity 0.55 + bill ID detector
# ---------------------------------------------------------------------------


class TestFix3DedupBillID:
    """Wave 0.5: SIMILARITY_THRESHOLD=0.55 + regulatory bill ID auto-dedup."""

    def test_similarity_threshold_lowered_to_055(self):
        assert SIMILARITY_THRESHOLD == 0.55

    def test_extract_bill_id_canada(self):
        ids = _extract_reg_bill_ids("Canada Bill C-25 targets crypto")
        assert ids == {"bill c-25"}

    def test_extract_bill_id_mica(self):
        ids = _extract_reg_bill_ids("EU MiCA framework expands to stablecoins")
        assert "mica" in ids

    def test_two_titles_share_bill_id_flag_duplicate(self):
        recent = [
            DedupEntry(
                hash="h1",
                title="Canada Bill C-25 hạn chế quyên góp crypto",
                source="rss",
                detected_at=datetime.now(timezone.utc).isoformat(),
            )
        ]
        # Different wording, same bill ID → must be flagged.
        assert _is_similar_to_recent("Canada cấm crypto donate via Bill C-25 amendment", recent)

    def test_unrelated_titles_no_bill_match(self):
        recent = [
            DedupEntry(
                hash="h1",
                title="Bitcoin price hits new high",
                source="rss",
                detected_at=datetime.now(timezone.utc).isoformat(),
            )
        ]
        assert not _is_similar_to_recent("Solana ecosystem expands", recent)

    def test_dedup_manager_e2e_bill_id(self):
        """End-to-end: DedupManager flags bill-ID duplicate via check_and_filter."""
        existing = DedupEntry(
            hash="h1",
            title="MiCA regulation goes live in EU",
            source="rss",
            detected_at=datetime.now(timezone.utc).isoformat(),
            url="https://eu.example.com/mica1",
        )
        mgr = DedupManager(existing_entries=[existing])
        new_evt = BreakingEvent(
            title="EU implements MiCA framework for stablecoins",
            source="cryptopanic",
            url="https://eu.example.com/mica2",
            panic_score=70,
        )
        result = mgr.check_and_filter([new_evt])
        assert result.duplicates_skipped == 1
        assert len(result.new_events) == 0


# ---------------------------------------------------------------------------
# Fix 4 — Daily pipeline failure alert (enriched)
# ---------------------------------------------------------------------------


class TestFix4PipelineAlert:
    """Wave 0.5: failure path must call send_admin_alert with run-id + ts info."""

    @pytest.mark.asyncio
    async def test_alert_called_on_pipeline_failure(self):
        """Mock _execute_stages → raises → verify send_admin_alert is awaited."""
        from cic_daily_report import daily_pipeline as dp

        deliver_result = MagicMock(messages_total=0, messages_sent=0)
        alert_target = "cic_daily_report.delivery.telegram_bot.send_admin_alert"
        with (
            patch.object(dp, "_execute_stages", AsyncMock(side_effect=RuntimeError("boom"))),
            patch.object(dp, "_deliver", AsyncMock(return_value=deliver_result)),
            patch.object(dp, "_write_run_log", AsyncMock()),
            patch.object(dp, "_write_dashboard_data"),
            patch(alert_target, new_callable=AsyncMock) as mock_alert,
            patch.dict(os.environ, {"GITHUB_RUN_ID": "wave05-test-run"}, clear=False),
        ):
            status = await dp._run_pipeline()
            assert status == "error"
            assert mock_alert.called, "send_admin_alert should fire on failure"
            msg = mock_alert.call_args.args[0]
            # Spec: alert must mention run id + first error type + timestamp marker.
            assert "wave05-test-run" in msg
            assert "RuntimeError" in msg
            assert "THẤT BẠI" in msg


# ---------------------------------------------------------------------------
# Fix 5 — Date freshness post-check (LOG-ONLY)
# ---------------------------------------------------------------------------


class TestFix5DateFreshness:
    """Wave 0.5: _check_stale_dates emits warning when LLM presents past date as future."""

    def test_past_date_with_future_marker_warns(self):
        # Use a date 30 days in the past, prefixed by "dự kiến diễn ra vào ngày".
        past = datetime.now(timezone.utc).date() - timedelta(days=30)
        text = f"Sự kiện dự kiến diễn ra vào ngày {past.day}/{past.month}/{past.year}."
        assert _check_stale_dates(text) >= 1

    def test_future_date_no_warn(self):
        future = datetime.now(timezone.utc).date() + timedelta(days=30)
        text = f"Sự kiện sắp tới {future.day}/{future.month}/{future.year}."
        assert _check_stale_dates(text) == 0

    def test_past_date_no_future_marker_no_warn(self):
        # Past date but described in past tense → not a stale-future bug.
        past = datetime.now(timezone.utc).date() - timedelta(days=30)
        text = f"Sự kiện đã diễn ra ngày {past.day}/{past.month}/{past.year}."
        assert _check_stale_dates(text) == 0


# ---------------------------------------------------------------------------
# Fix 6 — SOURCE_DISPLAY_MAP expansion + auto-format fallback
# ---------------------------------------------------------------------------


class TestFix6SourceDisplay:
    """Wave 0.5: source identifiers render readably in Telegram."""

    def test_explicit_map_reuters(self):
        assert _format_source("Reuters_Business") == "Reuters Business"

    def test_explicit_map_utoday_with_dot(self):
        assert _format_source("UToday") == "U.Today"

    def test_unknown_source_underscore_fallback(self):
        assert _format_source("Some_Brand_New_Source") == "Some Brand New Source"

    def test_unknown_source_no_underscore_passthrough(self):
        assert _format_source("FooBar") == "FooBar"
