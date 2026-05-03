"""Wave 0.8.7.2 regression test — ReDoS hotfix.

Scenario: Master Analysis text with "RSI/MVRV/NUPL/SOPR" + long prose WITHOUT
trailing digit → regex MUST NOT hang. Bug 02-03/05/2026 caused Daily Pipeline
to hang for 2 consecutive days (GitHub Actions killed after 2h timeout).

Root cause: quality_gate.py:102-103 nested quantifier `(?:\\w+\\s*)*` is a
classic ReDoS pattern — exponential backtracking when keyword found but no
trailing digit to anchor the match.

Fix: bounded non-greedy `[^.\\n]{0,40}?\\d` (kills nested quantifier).
"""

from __future__ import annotations

import time

from cic_daily_report.generators.quality_gate import _DATA_PATTERNS

# Pathological input: RSI/MVRV/NUPL/SOPR keywords + ~3K chars prose, NO digit
# trailing. Matches the LLM output shape that triggered the 02-03/05 hang.
PATHOLOGICAL_TEXT = (
    "RSI cho thấy thị trường đang trong vùng cân bằng và tâm lý nhà đầu tư "
    "tương đối ổn định với các chỉ báo on-chain MVRV NUPL SOPR đều phản ánh "
    "xu hướng tích lũy dài hạn của các nhà đầu tư lớn trên thị trường "
) * 30  # ~3K chars


def _get_metrics_pattern():
    """Locate the metrics-with-values pattern (the one that was ReDoS-prone)."""
    for p in _DATA_PATTERNS:
        if "RSI" in p.pattern and "MVRV" in p.pattern:
            return p
    raise AssertionError("metrics pattern not found in _DATA_PATTERNS")


def test_regex_no_redos_on_pathological_text():
    """Wave 0.8.7.2: regex MUST NOT hang >1s on pathological 3K char input.

    Pre-fix: 60s+ hang (catastrophic backtracking).
    Post-fix: <0.1s expected.
    """
    pattern = _get_metrics_pattern()

    start = time.time()
    matches = list(pattern.finditer(PATHOLOGICAL_TEXT))
    elapsed = time.time() - start

    assert elapsed < 1.0, (
        f"ReDoS regression: {elapsed:.2f}s on {len(PATHOLOGICAL_TEXT)} chars "
        f"(was 60s+ before Wave 0.8.7.2 fix)"
    )
    # Sanity: no matches expected (no digit after keywords)
    assert matches == [], f"Expected zero matches (no digit), got {len(matches)}"


def test_regex_still_matches_normal_metrics_with_digit():
    """Wave 0.8.7.2: semantic preserved — regex still detects keyword + digit."""
    pattern = _get_metrics_pattern()

    text = "Hôm nay RSI: 65, MVRV ở mức 0.8, F&G 70, Fear & Greed = 72."
    matches = [m.group() for m in pattern.finditer(text)]

    # Expect at least RSI, MVRV, F&G, Fear & Greed → 4 matches
    assert len(matches) >= 3, f"Expected >=3 matches with digits, got {matches}"


def test_regex_does_not_match_keyword_without_digit():
    """Wave 0.8.7.2: keyword without trailing digit should NOT match (intent)."""
    pattern = _get_metrics_pattern()

    text = "RSI cho thấy thị trường ổn định. MVRV trong vùng tích lũy."
    matches = list(pattern.finditer(text))

    assert matches == [], f"Expected no matches (no digits), got {[m.group() for m in matches]}"
