"""NQ05 Compliance Dual-Layer Filter (QĐ4).

Layer 1 (Prompt): NQ05 rules injected into LLM system prompt (in article_generator).
Layer 2 (Post-filter): Regex-based scan + auto-fix for banned keywords/patterns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from cic_daily_report.core.logger import get_logger

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

# Patterns that suggest specific portfolio allocation (NQ05 violation)
ALLOCATION_PATTERNS = [
    r"\b(\d{1,3})\s*%\s+(?:cho\s+|to\s+|vào\s+)?(?:BTC|ETH|SOL|BNB|XRP|ADA|DOGE|AVAX|Altcoin|Stablecoin)\b",
    r"(?:phân bổ|allocat|tỷ trọng|tỷ lệ)\s*[:\-]?\s*\d{1,3}\s*%",
    r"(?:gợi ý|recommend|suggest)\s+(?:phân bổ|allocation|portfolio)",
]


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


# Semantic patterns that imply NQ05 violations even without exact keyword match
SEMANTIC_NQ05_PATTERNS = [
    r"vùng tích lũy\s+trước\s+đợt\s+(?:tăng|phục hồi)",
    r"cơ hội\s+(?:tốt|vàng)\s+để\s+(?:tích lũy|mua vào)",
    r"smart money\s+(?:đang\s+)?(?:mua|tích lũy|accumulate)",
    r"thời điểm\s+(?:tốt|thích hợp)\s+để\s+(?:mua|vào lệnh|entry)",
    r"(?:nên|hãy)\s+(?:cân nhắc|xem xét)\s+(?:mua|bán|tích lũy)",
]


def _remove_sentences_with_pattern(text: str, pattern: re.Pattern) -> str:
    """Remove entire sentences/bullet points containing a pattern match.

    Handles both prose sentences (ending with .) and bullet points (lines starting with -).
    """
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        if pattern.search(line):
            # For bullet points, remove the whole line
            if line.strip().startswith("-") or line.strip().startswith("•"):
                continue
            # For prose, remove individual sentences containing the pattern
            sentences = re.split(r"(?<=[.!?])\s+", line)
            kept = [s for s in sentences if not pattern.search(s)]
            if kept:
                cleaned_lines.append(" ".join(kept))
        else:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


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

    # Step 1: Scan and remove ENTIRE SENTENCES containing banned keywords.
    # Previous approach replaced keywords with "[đã biên tập]" which left broken text.
    for keyword in all_banned:
        pattern = re.compile(re.escape(keyword), re.IGNORECASE)
        matches = pattern.findall(result.content)
        if matches:
            result.violations_found += len(matches)
            result.content = _remove_sentences_with_pattern(result.content, pattern)
            result.auto_fixed += len(matches)
            result.flagged_for_review.append(f"Removed: '{keyword}' ({len(matches)}x)")

    # Step 1b: Check allocation percentage patterns (NQ05 violation)
    for pattern_str in ALLOCATION_PATTERNS:
        pattern = re.compile(pattern_str, re.IGNORECASE)
        matches = pattern.findall(result.content)
        if matches:
            result.violations_found += len(matches)
            result.content = _remove_sentences_with_pattern(result.content, pattern)
            result.auto_fixed += len(matches)
            result.flagged_for_review.append(
                f"Allocation pattern removed: '{pattern_str}' ({len(matches)}x)"
            )

    # Step 1c: Check semantic NQ05 patterns (implicit violations)
    for pattern_str in SEMANTIC_NQ05_PATTERNS:
        pattern = re.compile(pattern_str, re.IGNORECASE)
        matches = pattern.findall(result.content)
        if matches:
            result.violations_found += len(matches)
            result.content = _remove_sentences_with_pattern(result.content, pattern)
            result.auto_fixed += len(matches)
            result.flagged_for_review.append(
                f"Semantic NQ05 violation removed: '{pattern_str}' ({len(matches)}x)"
            )

    # Step 1d: Sanitize non-Vietnamese characters (Chinese/Japanese/Korean)
    # LLMs sometimes output CJK chars in Vietnamese content
    cjk_pattern = re.compile(r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]+")
    cjk_matches = cjk_pattern.findall(result.content)
    if cjk_matches:
        result.content = cjk_pattern.sub("", result.content)
        result.auto_fixed += len(cjk_matches)
        logger.warning(f"Removed {len(cjk_matches)} CJK character sequences from content")

    # Step 2: Fix terminology
    for wrong, correct in TERMINOLOGY_FIXES.items():
        pattern = re.compile(re.escape(wrong), re.IGNORECASE)
        matches = pattern.findall(result.content)
        if matches:
            result.content = pattern.sub(correct, result.content)
            result.auto_fixed += len(matches)

    # Step 3: Check disclaimer presence (FR17) — report only, do NOT append.
    # Disclaimer is appended by article_generator/content_generator to avoid duplication.
    result.disclaimer_present = "Tuyên bố miễn trừ trách nhiệm" in result.content

    # Determine pass/fail
    result.passed = True  # Auto-fixed violations count as passed

    if result.flagged_for_review:
        for flag in result.flagged_for_review:
            logger.warning(f"NQ05 audit: {flag}")
    logger.info(
        f"NQ05 filter: {result.violations_found} violations, "
        f"{result.auto_fixed} auto-fixed, status={result.status}"
    )

    return result


def batch_filter(
    contents: list[str],
    extra_banned_keywords: list[str] | None = None,
) -> list[FilterResult]:
    """Run NQ05 filter on multiple content pieces."""
    return [check_and_fix(c, extra_banned_keywords) for c in contents]
