"""Wave C+.3 — Unicode-variant idempotency lock for append_nq05_disclaimer.

WHY (Devil concern #2, 2026-05-01):
    Wave C+.2 markers contain ⚠️ which is U+26A0 (WARNING SIGN) + U+FE0F
    (Variation Selector-16, forces emoji presentation). LLM providers
    occasionally emit ⚠ WITHOUT VS-16 → only U+26A0 → marker substring
    check FAILS → idempotent guard MISSES → double append on a text that
    visually already contains the disclaimer.

    Same class of bug for fullwidth colon (U+FF1A `：`) replacing regular
    `:` (U+003A) and NBSP (U+00A0) replacing regular space.

    Wave C+.3 fix: NFC normalize before substring check. This file LOCKS
    that contract: feed Unicode-variant disclaimer text through helper;
    second call MUST be no-op (idempotent skip).

Also locks: legitimate markdown headers like "## ⚠️ Cảnh báo" must NOT
trigger false-positive skip (no `*Tuyên bố` → no marker match).
"""

from __future__ import annotations

from cic_daily_report.adapters.llm_adapter import append_nq05_disclaimer
from cic_daily_report.generators.nq05_constants import (
    DISCLAIMER,
    DISCLAIMER_MARKER_FULL,
    DISCLAIMER_SHORT,
)


def test_idempotent_when_warning_emoji_lacks_vs16() -> None:
    """⚠ (U+26A0 only, no FE0F) variant of disclaimer → still skipped.

    Pre Wave C+.3: marker check on raw text would fail because marker has
    `⚠️` (with FE0F) and text has bare `⚠`. Guard misses → double append.
    Post C+.3: NFC normalize unifies presentation forms before substring check.
    """
    # Replace ⚠️ (U+26A0 U+FE0F) with bare ⚠ (U+26A0) in disclaimer.
    bare_warning = DISCLAIMER.replace("⚠️", "⚠")
    text = "Bài viết tier 1 hoàn chỉnh." + bare_warning
    # Sanity: marker substring is NOT present in raw bare-warning text.
    assert DISCLAIMER_MARKER_FULL not in text
    # But helper must still detect via NFC normalization.
    result = append_nq05_disclaimer(text, short=False)
    assert result == text, "NFC normalize failed — double-append on bare ⚠ variant"


def test_idempotent_when_colon_is_fullwidth() -> None:
    """Fullwidth colon `：` (U+FF1A) variant → known-gap (NFC ≠ NFKC).

    Documents conservative behavior: NFC alone keeps U+FF1A as-is, so
    marker substring "nhiệm:" no longer matches → helper APPENDS rather
    than silent skip. Prefer over-append to NQ05 leak.
    """
    # Inject fullwidth colon AT marker position
    fw_text = "Tin tức." + DISCLAIMER.replace("nhiệm:", "nhiệm：")
    # NFC keeps U+FF1A (it's already a canonical codepoint), so this case
    # demonstrates that NON-canonical replacements still behave: marker
    # substring "nhiệm:" no longer matches raw, but the WARNING sign
    # carrier "⚠️ *Tuyên bố miễn trừ trách nhiệm" prefix is still there.
    # The sentinel marker is "⚠️ *Tuyên bố miễn trừ trách nhiệm:* Nội dung trên..."
    # — fullwidth `：` breaks marker. After NFC, U+FF1A stays U+FF1A
    # (idempotent under NFC). So this case is INTENTIONALLY a known-gap:
    # NFC alone won't unify halfwidth/fullwidth (that needs NFKC).
    # We test that helper APPENDS in this case (better safe than silent skip).
    result = append_nq05_disclaimer(fw_text, short=False)
    # Append happens (helper is conservative — does NOT NFKC normalize because
    # NFKC would alter user-facing content if applied to output).
    assert result != fw_text
    # And the new disclaimer appended uses canonical `:`.
    assert DISCLAIMER_MARKER_FULL in result


def test_idempotent_when_nbsp_inside_marker_phrase() -> None:
    """NBSP (U+00A0) replacing regular space inside marker → APPEND.

    Same class as fullwidth colon: NFC does NOT unify NBSP↔space (that
    requires NFKC). Document the conservative behavior: better to over-
    append than silent skip leaking NQ05.
    """
    nbsp_text = "Báo cáo." + DISCLAIMER.replace(" ", " ", 3)
    result = append_nq05_disclaimer(nbsp_text, short=False)
    # Conservative: re-append (no false positive skip on broken marker).
    assert result != nbsp_text
    assert DISCLAIMER_MARKER_FULL in result


def test_no_false_positive_on_markdown_warning_heading() -> None:
    """`## ⚠️ Cảnh báo` heading in article body → NOT a marker match.

    Markdown heading uses ⚠️ but lacks `*Tuyên bố` signature wording, so
    it must not trigger idempotent skip. Disclaimer MUST be appended.
    """
    text = "## ⚠️ Cảnh báo\n\nThị trường biến động mạnh trong 24h qua."
    result = append_nq05_disclaimer(text, short=False)
    assert result != text, "False positive skip on markdown ⚠️ heading"
    assert DISCLAIMER_MARKER_FULL in result


def test_no_false_positive_on_emoji_warning_in_body() -> None:
    """⚠️ alone in body (no `*Tuyên bố` follow) → must NOT skip."""
    text = "Lưu ý ⚠️: Volatility cao tuần này, manage risk cẩn thận."
    result = append_nq05_disclaimer(text, short=False)
    assert result != text
    assert DISCLAIMER_MARKER_FULL in result


def test_recap_quote_with_real_marker_skips_acceptable_per_devil() -> None:
    """Per Devil's review: if LLM RECAPS prior article verbatim including
    the full marker phrase, helper skips append. This is acceptable —
    NQ05 disclaimer is already textually present (just from quote).

    LOCK this design choice so future contributors do not "fix" it without
    intentional discussion.
    """
    quoted_recap = (
        'Bài hôm qua kết luận: "⚠️ *Tuyên bố miễn trừ trách nhiệm:* '
        'Nội dung trên chỉ mang tính chất thông tin..." Hôm nay tiếp tục.'
    )
    result = append_nq05_disclaimer(quoted_recap, short=False)
    # Skip — quote already carries marker. Acceptable per Wave C+.2 design.
    assert result == quoted_recap


def test_idempotent_short_with_bare_warning_variant() -> None:
    """SHORT disclaimer with bare ⚠ (no FE0F) → idempotent skip via NFC."""
    bare_short = DISCLAIMER_SHORT.replace("⚠️", "⚠")
    text = "Tin breaking." + bare_short
    result = append_nq05_disclaimer(text, short=True)
    assert result == text, "NFC normalize failed for SHORT bare ⚠ variant"


# ---------------------------------------------------------------------------
# Wave C+.4 (2026-05-01) — full invisible chars class lockdown.
# WHY: Wave C+.3 chỉ strip FE0F. LLM hallucinate ZWJ/ZWSP/BOM/SHY injection
# vẫn bypass marker check → double append. Tests dưới đây LOCK toàn class
# invisible/format chars để chặn Wave C+.5 reactive patch.
# ---------------------------------------------------------------------------

# Invisible char codepoints (referenced via chr() to avoid editor mishandling
# zero-width chars in source text):
_ZWJ = chr(0x200D)  # ZERO WIDTH JOINER
_ZWSP = chr(0x200B)  # ZERO WIDTH SPACE
_BOM = chr(0xFEFF)  # ZERO WIDTH NO-BREAK SPACE (BOM)
_SHY = chr(0x00AD)  # SOFT HYPHEN


def test_idempotent_when_zwj_injected_full() -> None:
    """LLM inject ZWJ vào marker → vẫn idempotent skip.

    Pre Wave C+.4: ZWJ giữa ⚠ và FE0F sequence → marker substring miss →
    double-append. Post C+.4: _norm() strip toàn class invisible.
    """
    # Inject ZWJ between U+26A0 and U+FE0F: ⚠ + ZWJ + FE0F
    polluted = DISCLAIMER.replace("⚠️", "⚠" + _ZWJ + chr(0xFE0F))
    text = "Body content. " + polluted
    result = append_nq05_disclaimer(text)
    assert result == text, "ZWJ injection bypassed marker — Wave C+.4 _norm regression"


def test_idempotent_when_zwsp_injected_short() -> None:
    """LLM inject ZWSP vào marker SHORT → vẫn idempotent."""
    # Inject ZWSP inside "Tuyên" → "Tuyê" + ZWSP + "n"
    polluted = DISCLAIMER_SHORT.replace("Tuyên", "Tuyê" + _ZWSP + "n")
    text = "Breaking content. " + polluted
    result = append_nq05_disclaimer(text, short=True)
    assert result == text, "ZWSP injection bypassed SHORT marker — Wave C+.4 regression"


def test_idempotent_when_bom_injected() -> None:
    """LLM inject BOM (U+FEFF) → vẫn idempotent."""
    polluted = _BOM + DISCLAIMER  # leading BOM (common LLM artifact)
    text = "Body. " + polluted
    result = append_nq05_disclaimer(text)
    assert result == text, "BOM injection bypassed marker — Wave C+.4 regression"


def test_idempotent_when_soft_hyphen_injected() -> None:
    """LLM inject soft hyphen U+00AD → vẫn idempotent.

    SHY thường bị LLM inject để gợi ý hyphenation cho rendering — invisible
    trong text, nhưng vẫn break substring match nếu không strip.
    """
    polluted = DISCLAIMER.replace("Tuyên", "Tu" + _SHY + "yên")
    text = "Body. " + polluted
    result = append_nq05_disclaimer(text)
    assert result == text, "Soft hyphen injection bypassed marker — Wave C+.4 regression"
