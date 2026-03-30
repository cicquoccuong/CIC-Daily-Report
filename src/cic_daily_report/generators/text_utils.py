"""Text utilities for post-generation content processing.

P1.25: Hard character limits to prevent Telegram delivery failures
and unbounded content length.
"""

from __future__ import annotations


def truncate_to_limit(
    text: str,
    max_chars: int,
    preserve: str = "paragraph",
) -> tuple[str, bool]:
    """Truncate text to max_chars, respecting paragraph or sentence boundaries.

    Truncation strategy (in order of preference):
    1. If text fits → return unchanged
    2. preserve="paragraph" → cut at last paragraph break (\\n\\n) before limit
    3. Sentence boundary → cut at last `. ` or `.\\n` or `.` at end before limit
    4. Hard cut at max_chars (last resort)

    Args:
        text: The text to truncate.
        max_chars: Maximum allowed character count.
        preserve: Boundary type — "paragraph" tries \\n\\n first then sentence,
                  "sentence" skips paragraph search and goes straight to sentence.

    Returns:
        Tuple of (possibly truncated text, whether truncation occurred).
    """
    if len(text) <= max_chars:
        return (text, False)

    search_region = text[:max_chars]

    # WHY paragraph-first: cleaner visual break for Telegram messages
    if preserve == "paragraph":
        para_idx = search_region.rfind("\n\n")
        if para_idx > 0:
            return (search_region[:para_idx].rstrip(), True)

    # Sentence boundary: find last sentence-ending punctuation (. ! ?) followed
    # by space/newline, or at the exact end of the search region.
    # WHY all three punctuation marks: `. ` only misses `! ` and `? ` boundaries,
    # causing truncation to cut mid-paragraph after exclamatory/question sentences.
    best_sentence_idx = -1
    for pattern in [". ", ".\n", "! ", "!\n", "? ", "?\n"]:
        pos = search_region.rfind(pattern)
        if pos > best_sentence_idx:
            best_sentence_idx = pos
    # Also check if the search region ends exactly on a sentence-ending character
    if max_chars - 1 > best_sentence_idx and search_region[-1:] in ".!?":
        best_sentence_idx = max_chars - 1

    # BUG-09: Changed > 0 to >= 0 to handle boundary at position 0.
    # Guard: don't return just a punctuation mark (len <= 1).
    if best_sentence_idx >= 0:
        result = search_region[: best_sentence_idx + 1].rstrip()
        if len(result) > 1:
            return (result, True)

    # Hard cut — no boundary found (e.g., one giant word block)
    return (search_region.rstrip(), True)
