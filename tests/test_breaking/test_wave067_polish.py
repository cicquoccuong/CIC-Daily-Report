"""Wave 0.6.7 polish 2 — micro fix tests.

Two fixes covered:
1. scripts/ingest_url.py — DedupManager constructor signature mismatch
   (was `DedupManager(sheets_client=sheets)` → TypeError → silent skip).
2. breaking/content_generator.py — drop "nhà đầu tư chiến lược" from prompt
   templates (3 occurrences) to reduce stale repeat phrasing + future-proof
   against NQ05 false positives.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure scripts/ is importable as a top-level package for the CLI module.
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


# ---------------------------------------------------------------------------
# Fix 1 — DedupManager signature mismatch in ingest_url.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_url_dedup_check_works():
    """Dedup branch must construct DedupManager via existing_entries (NOT
    sheets_client) — verifies the Wave 0.6.7 fix wires the correct kwarg.

    WHY: prior code used DedupManager(sheets_client=sheets) → TypeError
    swallowed by broad except → ALL ingests bypassed dedup silently.
    """
    import ingest_url as ing  # type: ignore[import-not-found]

    # Mock fetch_article so we don't hit the network.
    fake_article = ("Bitcoin hits new all-time high", "Body text about BTC ATH.")

    # Mock SheetsClient.read_all → return one prior entry that does NOT match
    # the new event (so dedup_result.duplicates_skipped == 0 → flow continues).
    fake_sheets = MagicMock()
    fake_sheets.read_all.return_value = [
        {
            "Hash": "deadbeef0000",
            "Tiêu đề": "Some unrelated story",
            "Nguồn": "decrypt.co",
            "Mức độ": "important",
            "Thời gian": "2026-04-01T00:00:00+00:00",
            "Trạng thái gửi": "sent",
            "URL": "https://example.com/old",
            "Thời gian gửi": "2026-04-01T00:00:00+00:00",
        }
    ]

    # Mock LLM + content generator so we exit before Telegram.
    fake_content = MagicMock(formatted="📌 Test\n\nBody.")

    async def _fake_generate(*_a, **_kw):
        return fake_content

    with (
        patch.object(ing, "fetch_article", return_value=fake_article),
        patch(
            "cic_daily_report.storage.sheets_client.SheetsClient",
            return_value=fake_sheets,
        ),
        patch("cic_daily_report.adapters.llm_adapter.LLMAdapter"),
        patch(
            "cic_daily_report.breaking.content_generator.generate_breaking_content",
            side_effect=_fake_generate,
        ),
    ):
        rc = await ing.ingest_one_url(
            url="https://example.com/btc-ath",
            severity="important",
            source_name="Decrypt",
            dry_run=True,
            skip_dedup=False,
        )

    # Dry-run + non-duplicate → should succeed (rc == 0). If the constructor
    # mismatch returned, we'd see "[WARN] Dedup check failed" in stderr but
    # rc still 0 (since dedup is non-fatal). Assert the SheetsClient was
    # actually called with read_all — proves the new code path executed.
    assert rc == 0
    fake_sheets.read_all.assert_called_once_with("BREAKING_LOG")


@pytest.mark.asyncio
async def test_ingest_url_dedup_skip_duplicate():
    """When BREAKING_LOG already contains the exact URL → return code 2."""
    import ingest_url as ing  # type: ignore[import-not-found]

    fake_article = ("Same article", "Same body.")
    target_url = "https://example.com/already-ingested"

    fake_sheets = MagicMock()
    fake_sheets.read_all.return_value = [
        {
            "Hash": "abc123def456",
            "Tiêu đề": "Same article",
            "Nguồn": "example.com",
            "Mức độ": "important",
            # Recent so URL-dedup window catches it.
            "Thời gian": "2099-01-01T00:00:00+00:00",
            "Trạng thái gửi": "sent",
            "URL": target_url,
            "Thời gian gửi": "2099-01-01T00:00:00+00:00",
        }
    ]

    with (
        patch.object(ing, "fetch_article", return_value=fake_article),
        patch(
            "cic_daily_report.storage.sheets_client.SheetsClient",
            return_value=fake_sheets,
        ),
    ):
        rc = await ing.ingest_one_url(
            url=target_url,
            severity="important",
            source_name="example.com",
            dry_run=True,
            skip_dedup=False,
        )

    assert rc == 2  # exit code 2 = duplicate per docstring contract


# ---------------------------------------------------------------------------
# Fix 2 — Prompt no longer mentions "nhà đầu tư chiến lược"
# ---------------------------------------------------------------------------


def test_prompt_no_longer_contains_strategic_investor():
    """BREAKING_PROMPT_TEMPLATE + DIGEST_PROMPT_TEMPLATE must not use the
    phrase "nhà đầu tư chiến lược" as an AUDIENCE DESCRIPTOR — replaced
    with "cộng đồng CIC".

    NOTE: The breaking template DOES contain the phrase exactly once inside
    a quoted forbid clause (KHÔNG dùng cụm "nhà đầu tư chiến lược") — that's
    intentional, telling the LLM not to echo it. This test verifies:
    - DIGEST template: zero occurrences (the phrase is fully removed).
    - BREAKING template: max 1 occurrence (the explicit forbid quote only).
    """
    from cic_daily_report.breaking.content_generator import (
        BREAKING_PROMPT_TEMPLATE,
        DIGEST_PROMPT_TEMPLATE,
    )

    assert "nhà đầu tư chiến lược" not in DIGEST_PROMPT_TEMPLATE
    assert BREAKING_PROMPT_TEMPLATE.count("nhà đầu tư chiến lược") <= 1
    # If 1 occurrence, it MUST be inside the forbid clause (not as descriptor).
    if "nhà đầu tư chiến lược" in BREAKING_PROMPT_TEMPLATE:
        assert 'KHÔNG dùng cụm "nhà đầu tư chiến lược"' in BREAKING_PROMPT_TEMPLATE


def test_prompt_uses_community():
    """Both templates should now refer to "cộng đồng CIC" branding."""
    from cic_daily_report.breaking.content_generator import (
        BREAKING_PROMPT_TEMPLATE,
        DIGEST_PROMPT_TEMPLATE,
    )

    assert "cộng đồng CIC" in BREAKING_PROMPT_TEMPLATE
    assert "cộng đồng CIC" in DIGEST_PROMPT_TEMPLATE


def test_audience_descriptor_no_jargon():
    """The new audience descriptor must mention 'kiến thức cơ bản về crypto'
    and explicitly tell the LLM NOT to explain basic concepts.
    Replaces old "nhà đầu tư chiến lược, đã có kiến thức" wording.
    """
    from cic_daily_report.breaking.content_generator import (
        BREAKING_PROMPT_TEMPLATE,
        DIGEST_PROMPT_TEMPLATE,
    )

    expected = "cộng đồng CIC đã có kiến thức cơ bản về crypto"
    assert expected in BREAKING_PROMPT_TEMPLATE
    assert expected in DIGEST_PROMPT_TEMPLATE
    # New copy must keep the "don't explain basics" guidance.
    assert "KHÔNG giải thích khái niệm cơ bản" in BREAKING_PROMPT_TEMPLATE
    assert "KHÔNG giải thích khái niệm cơ bản" in DIGEST_PROMPT_TEMPLATE


def test_paragraph2_instruction_updated():
    """Paragraph 2 instruction in BREAKING_PROMPT_TEMPLATE must keep CIC
    community framing AND explicitly forbid the old "nhà đầu tư chiến lược"
    phrase. Wave 0.8.5 reframed Đoạn 2 from "BẮT BUỘC viết" to escape-clause
    pattern (write only when source has data, else exact disclaimer) so the
    "Nêu hệ quả CỤ THỂ" affirmative phrase no longer appears verbatim — the
    "cộng đồng CIC" framing is preserved via "hệ quả cho cộng đồng CIC".
    """
    from cic_daily_report.breaking.content_generator import BREAKING_PROMPT_TEMPLATE

    # CIC community framing preserved (post-Wave 0.8.5 wording).
    assert "hệ quả cho cộng đồng CIC" in BREAKING_PROMPT_TEMPLATE
    # Explicit forbid line — preserved across Wave 0.6.7 + 0.8.5.
    assert 'KHÔNG dùng cụm "nhà đầu tư chiến lược"' in BREAKING_PROMPT_TEMPLATE


def test_research_generator_strategic_investor_preserved():
    """Sanity check: research_generator (BIC L1 specific) deliberately keeps
    "nhà đầu tư chiến lược" — that's research-tier branding for paid Level 1
    members, NOT breaking news. Wave 0.6.7 only sanitizes breaking prompts.
    """
    from cic_daily_report.generators.research_generator import RESEARCH_SYSTEM_PROMPT

    assert "nhà đầu tư chiến lược" in RESEARCH_SYSTEM_PROMPT
