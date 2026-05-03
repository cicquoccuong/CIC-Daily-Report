"""NQ05 Compliance Dual-Layer Filter (QĐ4).

Layer 1 (Prompt): NQ05 rules injected into LLM system prompt (in article_generator).
Layer 2 (Post-filter): Regex-based scan + auto-fix for banned keywords/patterns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from cic_daily_report.core.logger import get_logger

if TYPE_CHECKING:
    from cic_daily_report.storage.sentinel_reader import NQ05Term

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
    filler_count: int = 0  # Count of filler phrases detected (v0.29.1: warn-only, not removed)

    @property
    def status(self) -> str:
        if not self.passed:
            return "fail"
        if self.flagged_for_review:
            return "review"
        return "pass"


# v0.33.0: REMOVE_FILLER_PATTERNS emptied — sentence-level removal was too
# aggressive, causing empty digest bodies when most sentences contained these
# common Vietnamese phrases. Moved back to WARN-only in FILLER_PATTERNS.
REMOVE_FILLER_PATTERNS: list[str] = []

# Filler phrases discouraged by system prompt — detected and WARNED (v0.29.1).
# v0.28.0 upgraded to REMOVE, but removing structural Vietnamese grammar (verbs,
# prepositions) from prose destroyed sentence structure. Reverted to WARN-only.
# v0.32.0: Top 3 most frequent fillers moved to REMOVE_FILLER_PATTERNS.
# v0.33.0: Moved back here — removal too aggressive, caused empty bodies.
FILLER_PATTERNS = [
    r"cần theo dõi (?:thêm|chặt chẽ|sát sao)",
    r"tuy nhiên cần lưu ý",
    r"có thể tác động (?:trực tiếp|đến)",
    r"có thể (?:tạo ra|dẫn đến) (?:sự )?(?:thay đổi|biến động)",
    r"điều này cho thấy",
    r"có thể ảnh hưởng đến",
    r"trong bối cảnh",
]

# Semantic patterns that imply NQ05 violations even without exact keyword match
SEMANTIC_NQ05_PATTERNS = [
    r"vùng tích lũy\s+trước\s+đợt\s+(?:tăng|phục hồi)",
    r"cơ hội\s+(?:tốt|vàng)\s+để\s+(?:tích lũy|mua vào)",
    r"smart money\s+(?:đang\s+)?(?:mua|tích lũy|accumulate)",
    r"thời điểm\s+(?:tốt|thích hợp)\s+để\s+(?:mua|vào lệnh|entry)",
    r"(?:nên|hãy|có thể|cần|nếu)\s+(?:cân nhắc|xem xét)\s+(?:mua|bán|tích lũy)",
    # v0.28.0: Additional semantic patterns from QA audit
    # v0.30.0: Narrowed to avoid stripping legitimate analysis for CIC members
    r"dự báo\s+(?:giá|thị trường)\s+sẽ\s+(?:tăng|giảm|đạt)",
    r"chắc chắn\s+(?:tăng|giảm|phục hồi|bứt phá)",
    r"nhà đầu tư\s+nên\s+(?:cân nhắc|xem xét)\s+(?:mua|bán|tích lũy)",
    r"cơ hội\s+(?:tốt|vàng)\s+cho\s+(?:nhà đầu tư|trader)",
    r"(?:mục tiêu|target)\s+(?:giá|price)\s*[:=]?\s*\$?\d",
    # v0.30.1: Broader patterns from real output violations (2026-03-22)
    r"cơ hội(?:\s+\w+){0,6}\s+(?:tích lũy|mua vào|mua thêm)",
    r"(?:nhà đầu tư|bạn|trader)\s+nên\s+(?:\w+\s+){0,3}"
    r"(?:mua|bán|tích lũy|vào lệnh|chốt lời|chốt lỗ)",
    # v0.31.0: Advisory phrases = implicit NQ05 violations (from daily output 2026-03-23)
    r"(?:nhà đầu tư|bạn)\s+cần\s+theo dõi\s+chặt chẽ",
    r"quyết định đầu tư\s+(?:thông minh|sáng suốt|hợp lý)",
    r"giai đoạn\s+tích lũy\s+(?:cuối cùng\s+)?trước\s+khi\s+"
    r"(?:tăng trưởng|phục hồi|bứt phá)",
    # v0.32.0: Broader "xem xét" + action pattern (advisory language = NQ05 violation)
    r"xem xét\s+(?:việc\s+)?(?:tích lũy|mua vào|mua thêm)",
    # v0.33.0: Additional advisory patterns (VD-17, VD-18)
    r"cơ hội\s+(?:\w+\s+){0,6}(?:bình quân giá|DCA|mua giá thấp)",
    r"xem\s+đây\s+là\s+cơ hội",
    r"quyết định\s+(?:chiến lược\s+)?(?:tích lũy|chốt lời|mua|bán)",
    # QO.24: Expanded VN-specific buy/sell recommendation patterns (VD-18)
    # WHY: LLM output frequently uses these Vietnamese phrases that constitute
    # implicit investment advice — NQ05 violation even without explicit "nên mua/bán".
    r"(?:gia|tăng)\s+tăng\s+tỷ\s+trọng",  # "gia tang ty trong" = increase allocation
    r"vùng\s+mua\s+lý\s+tưởng",  # "vung mua ly tuong" = ideal buy zone
    r"(?:nên|hãy)\s+(?:mua\s+vào|bán\s+ra)",  # "nen mua vao / nen ban ra"
    r"cơ\s+hội\s+tốt\s+để",  # "co hoi tot de" = good opportunity to (action)
    r"thời\s+điểm\s+thích\s+hợp\s+(?:để\s+)?(?:mua|bán|tích lũy|vào lệnh)",
    r"(?:nên|hãy)\s+tích\s+lũy",  # "nen tich luy" = should accumulate
    r"(?:nên|hãy)\s+chốt\s+lời",  # "nen chot loi" = should take profit
    # "vung gia tot de mua/tich luy" = good price zone (to buy)
    r"vùng\s+giá\s+tốt\s+(?:để\s+)?(?:mua|tích lũy|vào)",
    r"không\s+nên\s+bỏ\s+lỡ",  # "khong nen bo lo" = don't miss out (FOMO)
    r"(?:mua|bán)\s+mạnh",  # "mua manh / ban manh" = strong buy/sell
    r"khuyến\s+nghị\s+(?:mua|bán)",  # "khuyen nghi mua/ban" = recommend buy/sell
    # Wave 0.5 (alpha.18): Audit 27-28/04/2026 caught these advisory phrases slipping through.
    # WHY: implicit accumulation/strategy advice = NQ05 violation (no buy/sell rec).
    r"tích\s+lũy\s+(?:dài\s+hạn|dài\s+hơi|chiến\s+lược)",
    r"nhà\s+đầu\s+tư\s+(?:chiến\s+lược\s+)?cần\s+(?:theo\s+dõi|lưu\s+ý|cân\s+nhắc)",
    # WHY refine (Quinn Wave 0.5 finding): bare phrase = false positive 100% — LLM
    # echoes "nhà đầu tư chiến lược" as audience descriptor (from prompts). Require
    # action verb (nên/cần/hãy/phải) so we only block actual advisory, not noun use.
    r"nhà\s+đầu\s+tư\s+chiến\s+lược\s+(?:nên|cần|hãy|phải)\s+",
    # Wave 0.8.6 (alpha.33) — Daily 11:59 SA 01/05 audit caught 4 advisory
    # phrases addressing the reader directly (bạn/anh/chị) — implicit invest
    # advice = NQ05 violation even when missing the literal "nên mua".
    # WHY direct-address focus: LLM personalizes recommendations using
    # 2nd-person pronouns to soften the advice → still recommendation.
    #
    # Wave 0.8.6.1 (alpha.34) Fix #5 — pronouns expanded to cover broader
    # community phrasing (chúng ta / mọi người / nhà đầu tư / ai). Wave 0.8.6
    # only caught 2nd-person — but cross-check found "tích lũy như chúng ta",
    # "nhà đầu tư có thể mua tài sản", "lúc nhà đầu tư có thể mua" all slip
    # through. Same advisory intent regardless of pronoun.
    r"(?:tích\s+lũy|gom|mua)\s+(?:dài\s+hạn|dài\s+hơi)?\s*như\s+"
    r"(?:bạn|anh|chị|chúng\s+ta|mọi\s+người|nhà\s+đầu\s+tư|ai)",
    r"(?:bạn|anh|chị|chúng\s+ta|mọi\s+người|nhà\s+đầu\s+tư|ai)\s+"
    r"(?:có\s+thể|nên|hãy)\s+mua\s+(?:được|tại|với|qua)?\s*"
    r"(?:tài\s+sản|coin|token|BTC|ETH)",
    r"lúc\s+(?:bạn|anh|chị|chúng\s+ta|mọi\s+người|nhà\s+đầu\s+tư|ai)\s+"
    r"(?:có\s+thể|nên)\s+mua",
    # Wave 0.8.6.1 (alpha.34) Fix #4 — drop branch "hơn" from pattern 4.
    # WHY: "Giá BTC tốt hơn so với cuối tháng" is legit market commentary
    # (price comparison, no advice). Only "để mua / cho việc mua" carry
    # advisory intent. Removing "hơn" eliminates a frequent false positive
    # without losing real violations.
    r"giá\s+(?:tốt|rẻ|hấp\s+dẫn)\s+(?:để\s+mua|cho\s+việc\s+mua)",
    # Wave 0.8.7.6 (alpha.39) — 3 patterns mới từ Daily 03/05 14:28 audit.
    # LEAK source (Summary): "các nhà đầu tư có thể cân nhắc phân bổ vốn vào
    # các narrative mới nổi như AI" → khuyến nghị tăng tỷ trọng vào sector
    # cụ thể = NQ05 violation, lọt qua mọi pattern Wave 0.8.6.x.
    # WHY 3 patterns thay vì 1: (a) full subject+verb+action chain bắt
    # advisory rõ ràng; (b) bare "cân nhắc phân bổ ..." không có pronoun
    # vẫn là khuyến nghị; (c) "duy trì/giữ tỷ trọng" = hold-recommendation
    # cùng họ — cùng cấu trúc khuyên hành động đầu tư, khác động từ.
    r"(?:bạn|anh|chị|chúng\s+ta|mọi\s+người|nhà\s+đầu\s+tư|ai|họ|investor|trader|mình)"
    r"\s+(?:có\s+thể|nên|hãy|cần)\s+"
    r"(?:cân\s+nhắc|xem\s+xét|tính\s+đến|tham\s+gia|thử)\s*"
    r"(?:phân\s+bổ|tăng\s+tỷ\s+trọng|gia\s+tăng|nâng\s+tỷ\s+trọng|"
    r"đầu\s+tư\s+vào|rót\s+vốn\s+vào|chuyển\s+vốn|đặt\s+cược)",
    r"(?:cân\s+nhắc|xem\s+xét)\s+"
    r"(?:phân\s+bổ|tăng\s+tỷ\s+trọng|tỷ\s+trọng|đầu\s+tư|rót\s+vốn)\s+"
    r"(?:vào|cho|sang|đến)?\s*(?:các|những)?",
    r"(?:duy\s+trì|giữ)\s+tỷ\s+trọng\s+"
    r"(?:ở|tại|trong)?\s*(?:các|những|lĩnh\s+vực|sector|coin)",
]


def merge_blacklist(sentinel_terms: list[NQ05Term]) -> list[str]:
    """Merge Sentinel NQ05 blacklist with hardcoded DEFAULT_BANNED_KEYWORDS.

    P1.14: Combines two sources of banned terms into a single deduplicated list.
    Only includes terms with severity="BLOCK" from Sentinel (WARN terms are
    logged but not added to the block list).

    WHY separate function: keeps merge logic testable and pipeline integration
    clean — caller passes result as extra_banned_keywords to check_and_fix().

    Args:
        sentinel_terms: NQ05Term list from SentinelReader.read_nq05_blacklist().

    Returns:
        Deduplicated list of all banned keywords (hardcoded + sentinel BLOCK terms).
    """
    # WHY: Start with hardcoded as base, then add Sentinel terms.
    # Using a set for deduplication (case-insensitive via lowering).
    seen = {kw.lower() for kw in DEFAULT_BANNED_KEYWORDS}
    merged = list(DEFAULT_BANNED_KEYWORDS)

    warn_count = 0
    for term in sentinel_terms:
        key = term.term.strip().lower()
        if not key:
            continue
        if term.severity.upper() == "WARN":
            warn_count += 1
            continue
        if key not in seen:
            seen.add(key)
            merged.append(term.term.strip())

    added = len(merged) - len(DEFAULT_BANNED_KEYWORDS)
    if added or warn_count:
        logger.info(
            f"NQ05 merge: {added} BLOCK terms added from Sentinel, {warn_count} WARN-only skipped"
        )
    return merged


def _remove_sentences_with_pattern(text: str, pattern: re.Pattern) -> str:
    """Remove sentences containing the violating pattern from text.

    For bullet points: remove entire bullet line.
    For prose: split into sentences, remove only sentence(s) containing the match,
    keep the rest. v0.29.1: Changed from phrase-only removal to sentence-level
    removal — removing just a phrase from prose often destroys grammar.
    """
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        if pattern.search(line):
            # For bullet points, remove the whole line
            if line.strip().startswith(("-", "•", "*")):
                continue
            # For prose: split into sentences, remove only violating ones
            sentences = re.split(r"(?<=[.!?])\s+", line)
            kept = [s for s in sentences if not pattern.search(s)]
            if kept:
                cleaned_line = " ".join(kept)
                cleaned_line = re.sub(r"\s{2,}", " ", cleaned_line)
                if cleaned_line.strip():
                    cleaned_lines.append(cleaned_line)
            # If all sentences match → entire line removed (no append)
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

    # Step 1e-1: REMOVE top 3 filler phrases at sentence level (v0.32.0).
    # WHY: These 3 appear most frequently and add zero information value.
    # Sentence-level removal preserves grammar (unlike phrase-level removal in v0.28.0).
    for pattern_str in REMOVE_FILLER_PATTERNS:
        pattern = re.compile(pattern_str, re.IGNORECASE)
        matches = pattern.findall(result.content)
        if matches:
            result.content = _remove_sentences_with_pattern(result.content, pattern)
            result.auto_fixed += len(matches)
            logger.info(f"NQ05 filler removed: '{pattern_str}' ({len(matches)}x)")

    # Step 1e-2: Detect remaining filler phrases — WARN-only, do NOT remove.
    # v0.29.1: Reverted from REMOVE (v0.28.0) back to WARN because these patterns
    # are structural Vietnamese grammar (verbs, prepositions) — removing them from
    # prose sentences destroys sentence structure, producing unreadable text.
    # Filler reduction is handled via LLM prompt instructions instead.
    filler_count = 0
    for pattern_str in FILLER_PATTERNS:
        pattern = re.compile(pattern_str, re.IGNORECASE)
        matches = pattern.findall(result.content)
        if matches:
            filler_count += len(matches)
            logger.info(f"NQ05 filler detected (kept): '{pattern_str}' ({len(matches)}x)")
    result.filler_count = filler_count

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
