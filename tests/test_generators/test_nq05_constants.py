"""Tests for `generators/nq05_constants.py` — Wave C+.1 (2026-05-01).

Locks:
1. Module imports cleanly (no project deps → no circular).
2. Backward compat: `from generators.article_generator import DISCLAIMER` still works.
3. Markers are UNIQUE per variant (FULL marker NOT in SHORT body, vice versa).
4. Cross-contamination guard: append helper detects FULL even when caller asks SHORT.
"""

from __future__ import annotations


class TestModuleImports:
    """nq05_constants is a leaf module — must import without pulling in deps."""

    def test_imports_clean_no_circular(self) -> None:
        # WHY: file purpose is to break cycle between adapters/llm_adapter và
        # generators/article_generator. If we accidentally re-add a project
        # import here, the cycle returns silently. This test catches that.
        import importlib

        mod = importlib.import_module("cic_daily_report.generators.nq05_constants")
        assert hasattr(mod, "DISCLAIMER")
        assert hasattr(mod, "DISCLAIMER_SHORT")
        assert hasattr(mod, "DISCLAIMER_MARKER_FULL")
        assert hasattr(mod, "DISCLAIMER_MARKER_SHORT")

    def test_no_internal_project_deps(self) -> None:
        """Module must not import other cic_daily_report subpackages."""
        from pathlib import Path

        # Locate file via package
        import cic_daily_report.generators.nq05_constants as mod

        src = Path(mod.__file__).read_text(encoding="utf-8")
        # Strip docstrings (lazy approach: only check actual import lines)
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                # Allow only stdlib + __future__
                assert "cic_daily_report" not in stripped, (
                    f"nq05_constants must NOT import from project: {stripped}"
                )


class TestBackwardCompat:
    """Existing imports `from generators.article_generator import DISCLAIMER`
    must continue to work — many tests + 3 src/ modules still use that path."""

    def test_article_generator_reexports_disclaimer(self) -> None:
        from cic_daily_report.generators.article_generator import (
            DISCLAIMER,
            DISCLAIMER_SHORT,
        )
        from cic_daily_report.generators.nq05_constants import (
            DISCLAIMER as DC,
        )
        from cic_daily_report.generators.nq05_constants import (
            DISCLAIMER_SHORT as DCS,
        )

        # Same object — re-export is `from ... import` not duplicate definition.
        assert DISCLAIMER is DC
        assert DISCLAIMER_SHORT is DCS


class TestMarkersUnique:
    """The whole point of 2 markers: each variant has a marker NOT in the other.

    If markers cross-match → idempotent helper would skip when caller switches
    variant on same text → NQ05 leak.
    """

    def test_full_marker_not_in_short(self) -> None:
        from cic_daily_report.generators.nq05_constants import (
            DISCLAIMER_MARKER_FULL,
            DISCLAIMER_SHORT,
        )

        assert DISCLAIMER_MARKER_FULL not in DISCLAIMER_SHORT, (
            "FULL marker must NOT appear in SHORT — would cause cross-contamination"
        )

    def test_short_marker_not_in_full(self) -> None:
        from cic_daily_report.generators.nq05_constants import (
            DISCLAIMER,
            DISCLAIMER_MARKER_SHORT,
        )

        assert DISCLAIMER_MARKER_SHORT not in DISCLAIMER, (
            "SHORT marker must NOT appear in FULL — would cause cross-contamination"
        )

    def test_full_marker_present_in_full(self) -> None:
        from cic_daily_report.generators.nq05_constants import (
            DISCLAIMER,
            DISCLAIMER_MARKER_FULL,
        )

        assert DISCLAIMER_MARKER_FULL in DISCLAIMER

    def test_short_marker_present_in_short(self) -> None:
        from cic_daily_report.generators.nq05_constants import (
            DISCLAIMER_MARKER_SHORT,
            DISCLAIMER_SHORT,
        )

        assert DISCLAIMER_MARKER_SHORT in DISCLAIMER_SHORT


class TestCrossContaminationGuard:
    """Real bug Wave C+.1 fixes: caller mixes FULL+SHORT on same text.

    Pre-fix: signature 200 chars same prefix → SHORT signature might appear in
    text already containing FULL → helper appends DUPLICATE NQ05 disclaimer.

    Post-fix: 2 unique markers → if FULL marker present, SHORT-mode call also
    skips (and vice versa). Single disclaimer guaranteed.
    """

    def test_text_with_full_skips_short_append(self) -> None:
        from cic_daily_report.adapters.llm_adapter import append_nq05_disclaimer
        from cic_daily_report.generators.nq05_constants import DISCLAIMER

        # Caller appended FULL earlier in pipeline.
        text = "Bài tier viết sẵn. " + DISCLAIMER

        # Now a different caller (e.g. breaking refactor) calls with short=True.
        # MUST detect FULL-marker is present → no append.
        result = append_nq05_disclaimer(text, short=True)
        assert result == text, "short=True must NOT append when FULL already present"

    def test_text_with_short_skips_full_append(self) -> None:
        from cic_daily_report.adapters.llm_adapter import append_nq05_disclaimer
        from cic_daily_report.generators.nq05_constants import DISCLAIMER_SHORT

        text = "Tin breaking. " + DISCLAIMER_SHORT
        result = append_nq05_disclaimer(text, short=False)
        assert result == text, "short=False must NOT append when SHORT already present"

    def test_disclaimer_in_middle_of_long_text_detected(self) -> None:
        """Wave C+.1 fix #2 — research articles ~15K chars; LLM can hallucinate
        disclaimer at position 8K-13K, OUTSIDE old tail(1500) window.

        Marker scan covers entire text → idempotent regardless of position.
        """
        from cic_daily_report.adapters.llm_adapter import append_nq05_disclaimer
        from cic_daily_report.generators.nq05_constants import DISCLAIMER

        # Position disclaimer at index ~8K (well outside last-1500 tail).
        prefix = "Phần đầu nghiên cứu. " * 400  # ~8000 chars
        suffix = "Phần kết luận. " * 200  # ~3000 chars
        text = prefix + DISCLAIMER + suffix

        result = append_nq05_disclaimer(text)
        # Must NOT double-append — marker detected anywhere in text.
        assert result == text
        # Sanity: only ONE FULL marker in result (no duplicate).
        from cic_daily_report.generators.nq05_constants import DISCLAIMER_MARKER_FULL

        assert result.count(DISCLAIMER_MARKER_FULL) == 1
