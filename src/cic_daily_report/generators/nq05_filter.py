"""NQ05 Compliance Dual-Layer Filter (QĐ4).

Layer 1 (Prompt): NQ05 rules injected into LLM system prompt (in article_generator).
Layer 2 (Post-filter): Regex-based scan + auto-fix for banned keywords/patterns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from cic_daily_report.core.logger import get_logger
from cic_daily_report.generators.article_generator import DISCLAIMER

logger = get_logger("nq05_filter")

# Default banned keywords — operator can add more via CAU_HINH tab
DEFAULT_BANNED_KEYWORDS = [
    "nên mua",
    "nên bán",
    "khuyến nghị",
    "guaranteed",
    "chắc chắn tăng",
    "chắc chắn giảm",
    "đảm bảo lợi nhuận",
    "cam kết lãi",
    "mua ngay",
    "bán ngay",
    "cơ hội vàng",
    "không thể bỏ lỡ",
    "must buy",
    "must sell",
    "buy now",
    "sell now",
]

# Terminology replacements (NQ05 approved terms)
TERMINOLOGY_FIXES = {
    "tiền điện tử": "tài sản mã hóa",
    "tiền ảo": "tài sản mã hóa",
    "đồng coin": "tài sản mã hóa",
    "cryptocurrency": "tài sản mã hóa",
    "crypto currency": "tài sản mã hóa",
}


@dataclass
class FilterResult:
    """Result of NQ05 compliance check."""

    content: str
    violations_found: int = 0
    auto_fixed: int = 0
    flagged_for_review: list[str] = field(default_factory=list)
    disclaimer_present: bool = False
    passed: bool = True

    @property
    def status(self) -> str:
        if not self.passed:
            return "fail"
        if self.flagged_for_review:
            return "review"
        return "pass"


def check_and_fix(
    content: str,
    extra_banned_keywords: list[str] | None = None,
) -> FilterResult:
    """Run NQ05 post-filter on content.

    1. Scan for banned keywords → remove or flag
    2. Fix terminology (non-compliant → NQ05 approved)
    3. Ensure disclaimer present

    Args:
        content: Article/summary content to check.
        extra_banned_keywords: Additional banned keywords from CAU_HINH config.

    Returns:
        FilterResult with cleaned content and compliance report.
    """
    result = FilterResult(content=content)
    all_banned = DEFAULT_BANNED_KEYWORDS + (extra_banned_keywords or [])

    # Step 1: Scan and remove banned keywords
    for keyword in all_banned:
        pattern = re.compile(re.escape(keyword), re.IGNORECASE)
        matches = pattern.findall(result.content)
        if matches:
            result.violations_found += len(matches)
            result.content = pattern.sub("[đã biên tập]", result.content)
            result.auto_fixed += len(matches)
            result.flagged_for_review.append(f"Removed: '{keyword}' ({len(matches)}x)")

    # Step 2: Fix terminology
    for wrong, correct in TERMINOLOGY_FIXES.items():
        pattern = re.compile(re.escape(wrong), re.IGNORECASE)
        matches = pattern.findall(result.content)
        if matches:
            result.content = pattern.sub(correct, result.content)
            result.auto_fixed += len(matches)

    # Step 3: Check disclaimer (FR17)
    result.disclaimer_present = "Tuyên bố miễn trừ trách nhiệm" in result.content
    if not result.disclaimer_present:
        result.content = result.content.rstrip() + DISCLAIMER
        result.disclaimer_present = True
        result.auto_fixed += 1

    # Determine pass/fail
    result.passed = True  # Auto-fixed violations count as passed

    logger.info(
        f"NQ05 filter: {result.violations_found} violations found, "
        f"{result.auto_fixed} auto-fixed, "
        f"{len(result.flagged_for_review)} flagged for review"
    )

    return result


def batch_filter(
    contents: list[str],
    extra_banned_keywords: list[str] | None = None,
) -> list[FilterResult]:
    """Run NQ05 filter on multiple content pieces."""
    return [check_and_fix(c, extra_banned_keywords) for c in contents]
