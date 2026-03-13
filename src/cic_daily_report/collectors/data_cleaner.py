"""Data Deduplication, Conflict Detection & Spam Filter (FR11, FR12, FR55)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from cic_daily_report.core.logger import get_logger

logger = get_logger("data_cleaner")

# Default spam keywords (supplemented by CAU_HINH config)
DEFAULT_SPAM_KEYWORDS = [
    "airdrop free",
    "guaranteed profit",
    "100x gem",
    "pump signal",
    "join group",
    "referral link",
    "giveaway",
    "click here",
    "limited time",
]

SIMILARITY_THRESHOLD = 0.75  # title similarity for dedup


@dataclass
class CleanResult:
    """Result of cleaning pipeline."""

    articles: list[dict[str, Any]]
    duplicates_merged: int = 0
    conflicts_flagged: int = 0
    spam_filtered: int = 0


def clean_articles(
    articles: list[dict[str, Any]],
    spam_keywords: list[str] | None = None,
) -> CleanResult:
    """Run full cleaning pipeline: dedup → conflict detection → spam filter.

    Args:
        articles: List of article dicts with keys: title, url, source_name, etc.
        spam_keywords: Additional spam keywords from config.
    """
    keywords = (spam_keywords or []) + DEFAULT_SPAM_KEYWORDS
    keywords_lower = [k.lower() for k in keywords]

    # Step 1: Deduplicate
    deduped, dup_count = _deduplicate(articles)

    # Step 2: Detect conflicts
    conflict_count = _detect_conflicts(deduped)

    # Step 3: Filter spam
    cleaned, spam_count = _filter_spam(deduped, keywords_lower)

    result = CleanResult(
        articles=cleaned,
        duplicates_merged=dup_count,
        conflicts_flagged=conflict_count,
        spam_filtered=spam_count,
    )

    logger.info(
        f"Data cleaning: {dup_count} duplicates merged, "
        f"{conflict_count} conflicts flagged, {spam_count} spam filtered. "
        f"{len(cleaned)} articles remaining."
    )

    return result


def _deduplicate(articles: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Deduplicate by title similarity + URL matching (FR11)."""
    if not articles:
        return [], 0

    unique: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    dup_count = 0

    for article in articles:
        url = article.get("url", "").strip()
        title = article.get("title", "").strip()

        # Exact URL match
        url_hash = _url_hash(url)
        if url_hash in seen_urls:
            dup_count += 1
            # Merge: add source to existing article
            _merge_source(unique, article)
            continue

        # Title similarity check
        is_dup = False
        for existing in unique:
            existing_title = existing.get("title", "")
            similarity = SequenceMatcher(None, title.lower(), existing_title.lower()).ratio()
            if similarity >= SIMILARITY_THRESHOLD:
                is_dup = True
                dup_count += 1
                _merge_source_list(existing, article)
                break

        if not is_dup:
            article.setdefault("sources", [article.get("source_name", "")])
            unique.append(article)
            if url:
                seen_urls.add(url_hash)

    return unique, dup_count


def _detect_conflicts(articles: list[dict[str, Any]]) -> int:
    """Detect conflicting information between sources (FR12)."""
    conflict_count = 0

    for article in articles:
        sources = article.get("sources", [])
        if len(sources) > 1:
            # If same event from multiple sources, flag for AI review
            article["conflict"] = True
            conflict_count += 1
        else:
            article["conflict"] = False

    return conflict_count


def _filter_spam(
    articles: list[dict[str, Any]],
    keywords: list[str],
) -> tuple[list[dict[str, Any]], int]:
    """Filter spam/noise using keyword blacklist (FR55)."""
    cleaned = []
    spam_count = 0

    for article in articles:
        title = article.get("title", "").lower()
        summary = article.get("summary", "").lower()
        text = f"{title} {summary}"

        is_spam = any(kw in text for kw in keywords)

        if is_spam:
            article["filtered"] = True
            spam_count += 1
        else:
            article["filtered"] = False

        cleaned.append(article)  # keep all, mark filtered ones

    return cleaned, spam_count


def _url_hash(url: str) -> str:
    """Hash URL for dedup lookup."""
    normalized = re.sub(r"[?#].*$", "", url.strip().lower())
    return hashlib.md5(normalized.encode()).hexdigest()


def _merge_source(unique: list[dict[str, Any]], dup: dict[str, Any]) -> None:
    """Merge duplicate source into existing article."""
    dup_url = dup.get("url", "").strip()
    for existing in unique:
        existing_url = existing.get("url", "").strip()
        if _url_hash(existing_url) == _url_hash(dup_url):
            _merge_source_list(existing, dup)
            return


def _merge_source_list(existing: dict[str, Any], dup: dict[str, Any]) -> None:
    """Add dup's source to existing's sources list."""
    sources = existing.setdefault("sources", [existing.get("source_name", "")])
    dup_source = dup.get("source_name", "")
    if dup_source and dup_source not in sources:
        sources.append(dup_source)
    # Preserve og_image — prefer non-None
    if not existing.get("og_image") and dup.get("og_image"):
        existing["og_image"] = dup["og_image"]
    # Preserve source_type — "research" takes priority over "news"
    if dup.get("source_type") == "research":
        existing["source_type"] = "research"
