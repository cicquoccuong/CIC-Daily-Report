"""Tests for adapters/llm_adapter.append_nq05_disclaimer (Wave C+ NQ05 centralization).

WHY: Helper là single source of truth for NQ05 disclaimer append. Test must lock:
- Idempotency (no double-append)
- Correct variant selection (short vs full)
- Empty input handling
- Existing-disclaimer no-op
"""

from __future__ import annotations

from cic_daily_report.adapters.llm_adapter import append_nq05_disclaimer
from cic_daily_report.generators.article_generator import DISCLAIMER, DISCLAIMER_SHORT

# Sentinel substring used by helper's idempotency check (first non-empty line of disclaimer).
_NQ05_SENTINEL = "⚠️ *Tuyên bố miễn trừ trách nhiệm:"


class TestAppendBasic:
    """Basic append behavior."""

    def test_appends_full_disclaimer_by_default(self) -> None:
        text = "Bài phân tích thị trường tài sản mã hóa hôm nay."
        result = append_nq05_disclaimer(text)
        assert text in result
        # Full disclaimer signature substrings — both must appear after append.
        assert "DYOR" in result
        assert "KHÔNG phải lời khuyên đầu tư" in result

    def test_short_true_uses_short_disclaimer(self) -> None:
        text = "Tin breaking ngắn."
        result = append_nq05_disclaimer(text, short=True)
        # Short variant signature: "Rủi ro cao." present, full "---" separator absent.
        assert "Rủi ro cao" in result
        assert "---" not in result, "DISCLAIMER_SHORT phải KHÔNG chứa '---' separator"

    def test_short_false_uses_full_disclaimer(self) -> None:
        text = "Bài viết tier."
        result = append_nq05_disclaimer(text, short=False)
        # Full variant has "---" separator that short does not.
        assert "---" in result
        assert "Hãy tự nghiên cứu (DYOR) trước khi đưa ra quyết định" in result


class TestIdempotency:
    """Calling helper twice (or with text already containing disclaimer) must NOT
    double-append — caller can call it safely after any post-processing chain."""

    def test_double_call_no_double_append_full(self) -> None:
        text = "Nội dung."
        once = append_nq05_disclaimer(text)
        twice = append_nq05_disclaimer(once)
        assert once == twice, "Helper must be idempotent for full disclaimer"
        # Sentinel must appear exactly once.
        assert twice.count(_NQ05_SENTINEL) == 1

    def test_double_call_no_double_append_short(self) -> None:
        text = "Tin breaking."
        once = append_nq05_disclaimer(text, short=True)
        twice = append_nq05_disclaimer(once, short=True)
        assert once == twice
        assert twice.count(_NQ05_SENTINEL) == 1

    def test_text_already_contains_disclaimer_full_noop(self) -> None:
        # WHY: simulate caller that built content_with_disclaimer manually then
        # forgot to remove old append site → helper must not re-append.
        text = "Body trước đó.\n\n" + DISCLAIMER.lstrip("\n")
        result = append_nq05_disclaimer(text)
        assert result == text
        assert result.count(_NQ05_SENTINEL) == 1

    def test_text_already_contains_short_disclaimer_noop_for_short(self) -> None:
        text = "Body trước đó." + DISCLAIMER_SHORT
        result = append_nq05_disclaimer(text, short=True)
        assert result == text
        assert result.count(_NQ05_SENTINEL) == 1


class TestEdgeCases:
    """Boundary inputs."""

    def test_empty_text_still_appends(self) -> None:
        result = append_nq05_disclaimer("")
        assert _NQ05_SENTINEL in result
        assert result.startswith("\n\n") or result.startswith("⚠️")

    def test_empty_text_short_still_appends(self) -> None:
        result = append_nq05_disclaimer("", short=True)
        assert _NQ05_SENTINEL in result
        assert "Rủi ro cao" in result

    def test_whitespace_only_text_appends_clean(self) -> None:
        # rstrip() in helper removes trailing whitespace before disclaimer separator.
        result = append_nq05_disclaimer("   \n\n  ")
        assert _NQ05_SENTINEL in result
        # Should not have stray leading whitespace lines before the disclaimer block.
        assert "   \n\n  " not in result

    def test_separator_is_blank_line_not_double_blank(self) -> None:
        # Helper does rstrip + "\n\n" + lstrip(disclaimer leading \n) → exactly
        # one blank line (i.e. "text\n\n⚠️..."), no triple-newline mess.
        text = "Body."
        result = append_nq05_disclaimer(text)
        # Quadruple newline would mean we forgot lstrip on disclaimer leading \n\n.
        assert "\n\n\n\n" not in result

    def test_substring_collision_safe(self) -> None:
        # WHY (updated 2026-05-01 per heterogeneous verifier finding): old behavior
        # treated bare sentinel match as no-op → user citation in body blocked
        # real disclaimer append → NQ05 leak. New behavior requires 200-char
        # signature match within tail(1500) → casual cite in body no longer blocks.
        text = "Body có chứa: ⚠️ *Tuyên bố miễn trừ trách nhiệm: phần trích dẫn."
        result = append_nq05_disclaimer(text)
        # Casual citation in middle (no full disclaimer) → MUST append now.
        assert result != text
        assert "DYOR" in result


class TestStrongerIdempotency:
    """Edge cases caught by heterogeneous verifier (2026-05-01).

    Old sentinel-only check failed two scenarios:
    1. User content cites bot disclaimer prefix in middle → real disclaimer skipped.
    2. Partial sentinel anywhere blocked legitimate append.

    New check: 200-char signature of full disclaimer must appear in tail(1500).
    """

    def test_user_citation_does_not_block_append(self) -> None:
        """User content cites bot disclaimer trong middle → vẫn append disclaimer thật."""
        text = "Hôm qua bot báo: '⚠️ *Tuyên bố miễn trừ trách nhiệm: ...' và sau đó BTC tăng."
        result = append_nq05_disclaimer(text)
        # Phải có disclaimer ở CUỐI (real append) không chỉ trong middle
        assert result.endswith(DISCLAIMER.rstrip()) or DISCLAIMER.strip()[:200] in result[-1500:]
        assert result != text  # Không skip

    def test_partial_sentinel_in_body_does_not_block(self) -> None:
        """Sentinel prefix xuất hiện ở body (không phải tail) → vẫn append."""
        text = "Một câu chứa '⚠️ *Tuyên bố' nhưng không phải disclaimer thật. " + ("blah " * 500)
        result = append_nq05_disclaimer(text)
        assert result != text  # Phải append

    def test_full_disclaimer_in_tail_skip(self) -> None:
        """Disclaimer thật đã ở tail → skip (idempotent giữ nguyên)."""
        text = "Body content. " + DISCLAIMER
        result = append_nq05_disclaimer(text)
        assert result == text  # Idempotent
