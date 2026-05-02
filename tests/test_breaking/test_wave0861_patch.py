"""Wave 0.8.6.1 (alpha.34) — patch tests for Fix #2 (LLMError wrap + telemetry).

Fix #2: when ``generate_breaking_content`` raises ``LLMError`` whose source
contains ``breaking_content_word_gate`` (Wave 0.8.7 Bug 9 universal gate),
the breaking_pipeline must:
  1. Skip the event silently (NOT raise to broad-except → would mark
     generation_failed → trigger deferred-retry that repeats the same gate)
  2. Bump ``Wave06Metrics.breaking_skipped_short_content`` counter
  3. Mark dedup status ``skipped_short_content`` (distinct status to avoid
     C3 retry loop)

These are unit-level tests against the ``Wave06Metrics`` field + a focused
exception-handling smoke check (full e2e pipeline simulation lives in
existing test_breaking_pipeline_e2e.py + test_wave084_quality_fix.py).
"""

from __future__ import annotations

from cic_daily_report.breaking.wave06_metrics import Wave06Metrics
from cic_daily_report.core.error_handler import LLMError


class TestBreakingSkippedShortContentMetric:
    """Wave06Metrics.breaking_skipped_short_content counter wiring."""

    def test_counter_starts_at_zero(self):
        m = Wave06Metrics()
        assert m.breaking_skipped_short_content == 0

    def test_increment_bumps_counter(self):
        m = Wave06Metrics()
        m.increment("breaking_skipped_short_content")
        m.increment("breaking_skipped_short_content")
        assert m.breaking_skipped_short_content == 2

    def test_is_empty_false_when_counter_set(self):
        m = Wave06Metrics()
        m.increment("breaking_skipped_short_content")
        # Otherwise empty metrics with this counter set must NOT be empty —
        # signal preserved for ops to spot recurring short-output sources.
        assert not m.is_empty()

    def test_is_empty_true_when_no_counters(self):
        m = Wave06Metrics()
        assert m.is_empty()


class TestLLMErrorSourceMatching:
    """Source-string matching used by Fix #2 except clause in breaking_pipeline."""

    def test_word_gate_source_matches(self):
        # WHY: pipeline's `if "breaking_content_word_gate" in (e.source or "")`
        # must catch BOTH the original (`breaking_content_word_gate`) and the
        # universal gate variant (`breaking_content_word_gate_universal`).
        e1 = LLMError("too short", source="breaking_content_word_gate")
        e2 = LLMError("too short universal", source="breaking_content_word_gate_universal")
        assert "breaking_content_word_gate" in (e1.source or "")
        assert "breaking_content_word_gate" in (e2.source or "")

    def test_other_llm_error_does_not_match(self):
        # Non-gate LLMErrors must NOT be silently skipped — they should fall
        # through to the broad-except handling (generation_failed status).
        e = LLMError("model timeout", source="cerebras_judge")
        assert "breaking_content_word_gate" not in (e.source or "")

    def test_empty_source_safe(self):
        # Defensive — `e.source or ""` must handle None / empty.
        e = LLMError("generic", source="")
        assert "breaking_content_word_gate" not in (e.source or "")


class TestBreakingPipelineImportsLLMError:
    """Static check: breaking_pipeline.py imports LLMError so Fix #2 compiles."""

    def test_breaking_pipeline_imports_llm_error(self):
        from cic_daily_report import breaking_pipeline

        # LLMError must be available on the module (imported at module-level)
        assert hasattr(breaking_pipeline, "LLMError")

    def test_breaking_pipeline_handles_word_gate_skip(self):
        """Source code contains the fix #2 except branch — regression guard."""
        import inspect

        from cic_daily_report import breaking_pipeline

        src = inspect.getsource(breaking_pipeline)
        # Both call sites (primary + deferred) must include the gate check
        assert src.count("breaking_content_word_gate") >= 2
        # Telemetry counter incremented at least once (primary path)
        assert "breaking_skipped_short_content" in src
        # Distinct dedup status used so deferred-retry does not loop
        assert "skipped_short_content" in src
