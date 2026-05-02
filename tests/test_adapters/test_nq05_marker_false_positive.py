"""Wave C+.2 fix #3 — guard against false-positive marker matches.

WHY (regression context):
    Wave C+.1 introduced 2 short markers ("Nội dung trên" 5 chars,
    "Không phải lời khuyên đầu tư. Rủi ro cao. DYOR" 45 chars). Both are
    common Vietnamese phrases that LLM-generated articles legitimately
    contain (e.g. "Nội dung trên Twitter cho thấy...", quote từ Binance
    "...không phải lời khuyên đầu tư..."). Result: idempotent guard
    triggers on benign text → NQ05 disclaimer never appended → silent leak.

Wave C+.2 hardens markers to require ⚠️ emoji + markdown asterisk format
+ NQ05-specific Vietnamese wording — combination that organic article body
cannot produce by accident. This file LOCKS that property: feed common
Vietnamese phrases through `append_nq05_disclaimer`; helper MUST append
disclaimer (i.e. result != input).
"""

from __future__ import annotations

import pytest

from cic_daily_report.adapters.llm_adapter import append_nq05_disclaimer
from cic_daily_report.generators.nq05_constants import (
    DISCLAIMER,
    DISCLAIMER_MARKER_FULL,
    DISCLAIMER_MARKER_SHORT,
    DISCLAIMER_SHORT,
)

# Corpus of legitimate phrases that an LLM article body might contain.
# Each phrase contains a substring of the OLD short markers (Wave C+.1)
# but NOT the hardened Wave C+.2 marker (no emoji + no `*Tuyên bố`).
_COMMON_VIETNAMESE_PHRASES = [
    # "Nội dung trên" common usage — old FULL marker false positive
    "Nội dung trên Twitter cho thấy thị trường lạc quan.",
    "Nội dung trên blockchain Ethereum chứng minh smart contract hoạt động.",
    "Nội dung trên Bloomberg báo cáo quý 1 với doanh thu tăng 12%.",
    "Theo nội dung trên báo cáo của Glassnode, MVRV-Z hiện ở mức 2.5.",
    # "Không phải lời khuyên đầu tư. Rủi ro cao. DYOR" common quote pattern —
    # old SHORT marker false positive (exchanges/influencers thường viết).
    (
        "Quote từ Binance research: Không phải lời khuyên đầu tư. "
        "Rủi ro cao. DYOR là nguyên tắc cơ bản."
    ),
    # Mixed phrase — both old markers present in single sentence.
    (
        "Nội dung trên Twitter của CZ nhấn mạnh: Không phải lời khuyên "
        "đầu tư. Rủi ro cao. DYOR khi tham gia."
    ),
]


@pytest.mark.parametrize("phrase", _COMMON_VIETNAMESE_PHRASES)
def test_marker_not_false_positive_on_common_vietnamese_full(phrase: str) -> None:
    """short=False (FULL disclaimer) MUST append even when phrase looks like
    old marker substring."""
    result = append_nq05_disclaimer(phrase, short=False)
    assert result != phrase, f"FALSE POSITIVE skip on common phrase (short=False): {phrase[:60]}..."
    # Stronger lock: verify FULL disclaimer body actually appended.
    assert DISCLAIMER_MARKER_FULL in result, (
        f"FULL marker missing after append on: {phrase[:60]}..."
    )


@pytest.mark.parametrize("phrase", _COMMON_VIETNAMESE_PHRASES)
def test_marker_not_false_positive_on_common_vietnamese_short(phrase: str) -> None:
    """short=True (SHORT disclaimer) MUST append even when phrase looks like
    old marker substring."""
    result = append_nq05_disclaimer(phrase, short=True)
    assert result != phrase, f"FALSE POSITIVE skip on common phrase (short=True): {phrase[:60]}..."
    assert DISCLAIMER_MARKER_SHORT in result, (
        f"SHORT marker missing after append on: {phrase[:60]}..."
    )


def test_real_full_disclaimer_still_idempotent() -> None:
    """Sanity: real DISCLAIMER text MUST still trigger skip (Wave C+.1 contract).
    Hardening must NOT break the legitimate idempotent path."""
    text = "Bài tier viết sẵn." + DISCLAIMER
    result = append_nq05_disclaimer(text, short=False)
    assert result == text
    # Only one disclaimer in result.
    assert result.count(DISCLAIMER_MARKER_FULL) == 1


def test_real_short_disclaimer_still_idempotent() -> None:
    """Sanity: real DISCLAIMER_SHORT must still skip."""
    text = "Tin breaking." + DISCLAIMER_SHORT
    result = append_nq05_disclaimer(text, short=True)
    assert result == text
    assert result.count(DISCLAIMER_MARKER_SHORT) == 1


def test_marker_mismatch_no_longer_emits_warning() -> None:
    """Wave 0.8.7.1: FULL và SHORT unified → marker cũng unified.

    WHY old test expected warning: pre-Wave 0.8.7.1, FULL marker khác SHORT
    marker → caller mix variant trên cùng text triggered "mismatch" WARNING
    để alert ops về upstream budget overflow.

    Post Wave 0.8.7.1: marker SHORT == marker FULL (cùng wording). Helper
    detect cùng marker bất kể caller pass short=True/False → KHÔNG còn
    "mismatch" condition. Idempotent guard vẫn skip đúng nhưng warning
    dead-code. Test này lock contract mới: NO warning emitted.

    WHY direct handler spy (not caplog): core.logger.get_logger() sets
    propagate=False on `cic.*` loggers, caplog's root handler không nhận.
    """
    import logging

    captured: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    target = logging.getLogger("cic.llm_adapter")
    handler = _Capture(level=logging.WARNING)
    target.addHandler(handler)
    try:
        text = "Bài viết." + DISCLAIMER
        result = append_nq05_disclaimer(text, short=True)
    finally:
        target.removeHandler(handler)

    assert result == text  # idempotent guard still wins (single marker matches)
    # Wave 0.8.7.1: marker unified → mismatch warning không còn trigger.
    assert not any("nq05_marker_mismatch" in rec.getMessage() for rec in captured), (
        f"Wave 0.8.7.1: marker unified — warning phải DEAD. Got: "
        f"{[r.getMessage() for r in captured]}"
    )
