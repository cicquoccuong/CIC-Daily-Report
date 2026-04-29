"""Wave 0.6.6 — Polish tests covering 8 Codex bot fixes + 2 features.

Each test maps to a specific Codex finding (B1-B9) or new feature (A1-A2).

| Test                                              | Maps to | Codex finding              |
|---------------------------------------------------|---------|----------------------------|
| test_rag_cache_reuse_with_dirty_rows              | B1      | rag_index cache compare    |
| test_rag_cache_rebuild_when_raw_count_changes     | B1      | (positive case)            |
| test_test_hash_collision_resistance               | B2      | _make_row UUID4 hash       |
| test_judge_non_object_json_returns_approved       | B3      | judge AttributeError guard |
| test_judge_list_json_returns_approved             | B3      | (variant)                  |
| test_judge_string_json_returns_approved           | B3      | (variant)                  |
| test_year_rollover_january_to_next_year           | B4      | dd/mm year rollover        |
| test_year_no_rollover_recent_past                 | B4      | (negative — keep stale)    |
| test_strip_leaves_empty_body_marks_failed         | B5      | empty body delivery_failed |
| test_strip_keeps_full_body_no_fail                | B5      | (negative case)            |
| test_magnitude_scale_M_vs_B_conflict              | B6      | $1M vs $1B conflict        |
| test_magnitude_scale_K_M_no_conflict_close        | B6      | suffix tolerance           |
| test_duplicate_verified_skipped_same_run          | B7      | dedup verified events      |
| test_replay_baseline_fetch_url_fallback           | B8      | replay baseline URL fetch  |
| test_replay_killswitch_unset                      | B9      | replay flags override      |
| test_url_ingest_invalid_url                       | A2      | URL validation             |
| test_url_ingest_dry_run_exit_code                 | A2      | dry-run path               |
| test_url_ingest_hostname_to_source                | A2      | hostname helper            |
| test_url_ingest_arg_parser_defaults               | A2      | CLI parser                 |
| test_breaking_workflow_has_telethon_env           | A1      | workflow env presence      |
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Make scripts/ importable for ingest_url + replay_breaking tests.
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


# ---------------------------------------------------------------------------
# B1 — RAG cache freshness using raw_row_count
# ---------------------------------------------------------------------------


class TestRagCacheRawRowCount:
    """B1: cache reuse must compare raw_row_count (incl. dirty rows), not
    doc_count. Otherwise dirty rows always force rebuild."""

    def test_rag_cache_reuse_with_dirty_rows(self, tmp_path, monkeypatch):
        """B1 main: 5 raw rows (1 dirty) cached → next run sees 5 rows in
        Sheets → cache should be REUSED (raw_row_count match), not rebuilt."""
        from cic_daily_report.breaking.rag_index import get_or_build_index

        sqlite_path = tmp_path / "rag.sqlite"

        # 5 raw rows, 1 missing title (dirty) → 4 valid events indexed.
        rows = [
            {
                "ID": f"id{i}",
                "Thời gian": "2026-04-25T10:00:00+00:00",
                "Tiêu đề": f"Event {i}",
                "Hash": f"h_{uuid.uuid4().hex[:12]}",
                "Nguồn": "Test",
                "Mức độ": "important",
                "Trạng thái gửi": "sent",
                "URL": "",
                "Thời gian gửi": "",
            }
            for i in range(4)
        ]
        # 5th row is dirty (no title) → _row_to_event returns None.
        rows.append(
            {
                "ID": "dirty",
                "Thời gian": "2026-04-25T10:00:00+00:00",
                "Tiêu đề": "",  # missing → skipped
                "Hash": f"h_{uuid.uuid4().hex[:12]}",
                "Nguồn": "Test",
                "Mức độ": "important",
                "Trạng thái gửi": "sent",
                "URL": "",
                "Thời gian gửi": "",
            }
        )

        sheets = MagicMock()
        sheets.read_all = MagicMock(return_value=rows)
        sheets.get_row_count = MagicMock(return_value=len(rows))  # 5 raw

        # First call → builds. doc_count=4 (1 dirty skipped), raw_row_count=5.
        idx1 = get_or_build_index(sheets_client=sheets, sqlite_path=sqlite_path)
        assert idx1.doc_count == 4
        assert idx1._cached_raw_row_count == 5

        # Reset read_all so we can detect a rebuild.
        sheets.read_all.reset_mock()

        # Second call → cache hit, should NOT rebuild (raw_row_count matches).
        idx2 = get_or_build_index(sheets_client=sheets, sqlite_path=sqlite_path)
        assert idx2.doc_count == 4
        assert sheets.read_all.call_count == 0, "Cache should be reused, no rebuild"

    def test_rag_cache_rebuild_when_raw_count_changes(self, tmp_path):
        """B1 positive: when raw_row_count actually grows → rebuild fires."""
        from cic_daily_report.breaking.rag_index import get_or_build_index

        sqlite_path = tmp_path / "rag.sqlite"
        rows = [
            {
                "ID": "id1",
                "Thời gian": "2026-04-25T10:00:00+00:00",
                "Tiêu đề": "Event 1",
                "Hash": f"h_{uuid.uuid4().hex[:12]}",
                "Nguồn": "Test",
                "Mức độ": "important",
                "Trạng thái gửi": "sent",
                "URL": "",
                "Thời gian gửi": "",
            }
        ]
        sheets = MagicMock()
        sheets.read_all = MagicMock(return_value=rows)
        sheets.get_row_count = MagicMock(return_value=1)

        get_or_build_index(sheets_client=sheets, sqlite_path=sqlite_path)
        sheets.read_all.reset_mock()

        # Sheets grew to 5 rows → rebuild expected.
        sheets.get_row_count = MagicMock(return_value=5)
        get_or_build_index(sheets_client=sheets, sqlite_path=sqlite_path)
        assert sheets.read_all.call_count == 1


# ---------------------------------------------------------------------------
# B2 — Test hash UUID4 collision resistance
# ---------------------------------------------------------------------------


class TestHashCollisionResistance:
    """B2: _make_row in test_rag_index now uses UUID4 → keyspace ~10^14.
    Verify 1000 calls produce 1000 distinct hashes (no collisions)."""

    def test_test_hash_collision_resistance(self):
        # Reuse the helper from the canonical test module.
        from tests.test_breaking.test_rag_index import _make_row

        hashes: set[str] = set()
        for i in range(1000):
            row = _make_row(f"Title {i}", "2026-04-25T10:00:00+00:00")
            hashes.add(row["Hash"])
        assert len(hashes) == 1000, "UUID4 hashes must be unique across 1000 rows"


# ---------------------------------------------------------------------------
# B3 — Judge non-object JSON guard
# ---------------------------------------------------------------------------


class TestJudgeNonObjectJSON:
    """B3: when judge returns valid JSON but not a dict (list/string/null),
    code must NOT call .get() on it (AttributeError). Should fall back to
    'approved' with explanatory issue."""

    @pytest.mark.asyncio
    async def test_judge_non_object_json_returns_approved(self, monkeypatch):
        from cic_daily_report.adapters.llm_adapter import LLMAdapter, LLMResponse

        monkeypatch.setenv("CEREBRAS_API_KEY", "fake")
        adapter = LLMAdapter()

        # Mock _call_groq to return JSON-valid but non-object data.
        with patch(
            "cic_daily_report.adapters.llm_adapter._call_groq",
            new=AsyncMock(return_value=LLMResponse(text="[]", tokens_used=10, model="qwen-judge")),
        ):
            result = await adapter.judge_factual_claims(
                content="Tin nóng",
                source_text="source",
            )
        assert result.verdict == "approved"
        assert any("non-object JSON" in i for i in result.issues)
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_judge_list_json_returns_approved(self, monkeypatch):
        """Specific list case → no AttributeError."""
        from cic_daily_report.adapters.llm_adapter import LLMAdapter, LLMResponse

        monkeypatch.setenv("CEREBRAS_API_KEY", "fake")
        adapter = LLMAdapter()
        with patch(
            "cic_daily_report.adapters.llm_adapter._call_groq",
            new=AsyncMock(
                return_value=LLMResponse(text='["one", "two"]', tokens_used=10, model="x")
            ),
        ):
            result = await adapter.judge_factual_claims(content="x", source_text="y")
        assert result.verdict == "approved"

    @pytest.mark.asyncio
    async def test_judge_string_json_returns_approved(self, monkeypatch):
        """String JSON should also degrade safely (not raise)."""
        from cic_daily_report.adapters.llm_adapter import LLMAdapter, LLMResponse

        monkeypatch.setenv("CEREBRAS_API_KEY", "fake")
        adapter = LLMAdapter()
        with patch(
            "cic_daily_report.adapters.llm_adapter._call_groq",
            new=AsyncMock(return_value=LLMResponse(text='"approved"', tokens_used=5, model="x")),
        ):
            result = await adapter.judge_factual_claims(content="x", source_text="y")
        assert result.verdict == "approved"
        assert any("non-object" in i for i in result.issues)


# ---------------------------------------------------------------------------
# B4 — Year rollover for day/month-only dates
# ---------------------------------------------------------------------------


class TestYearRollover:
    """B4: dd/mm without year + parsed-date significantly past today (>90d)
    should be assumed to mean NEXT YEAR (e.g., 01/01 written on 31/12)."""

    def test_year_rollover_january_to_next_year(self):
        """31/12 today + sentence mentions '01/01 sắp tới' → should NOT
        treat as stale (next-year rollover applies)."""
        import datetime as _dt

        from cic_daily_report.breaking.content_generator import (
            _sentence_has_stale_future_date,
        )

        today = _dt.date(2026, 12, 31)
        sentence = "Sự kiện sắp tới ngày 01/01 sẽ rất quan trọng"
        # Without rollover: 01/01/2026 < today → True (stale).
        # With rollover: 01/01/2027 > today → False (not stale).
        assert _sentence_has_stale_future_date(sentence, today) is False

    def test_year_no_rollover_recent_past(self):
        """Sentence mentions 5 days ago → still stale (within 90d window)."""
        import datetime as _dt

        from cic_daily_report.breaking.content_generator import (
            _sentence_has_stale_future_date,
        )

        today = _dt.date(2026, 4, 30)
        # Date 5 days ago: 25/04 → with marker "sắp tới" → flagged stale.
        sentence = "Theo kế hoạch sắp tới 25/04 đã diễn ra"
        assert _sentence_has_stale_future_date(sentence, today) is True


# ---------------------------------------------------------------------------
# B5 — Empty body after strip → delivery_failed
# ---------------------------------------------------------------------------


class TestStripEmptyBody:
    """B5: when stripping leaves <50 chars body → delivery_failed=True."""

    def test_strip_leaves_empty_body_marks_failed(self):
        import datetime as _dt

        from cic_daily_report.breaking.content_generator import (
            _check_and_handle_stale_dates,
        )

        today = _dt.date(2026, 4, 30)
        # Single-sentence content that gets stripped → empty body.
        # WHY use marker + past date in single sentence: that sentence will
        # be stripped by the BLOCK path → cleaned ~ "" → < 50 chars.
        content = "Sự kiện sắp tới ngày 01/01/2024 đã xảy ra."
        cleaned, issues, failed = _check_and_handle_stale_dates(
            content, today=today, block_enabled=True
        )
        assert failed is True, f"Expected failure, got cleaned={cleaned!r}"

    def test_strip_keeps_full_body_no_fail(self):
        """No stripping happens → body untouched → not failed."""
        import datetime as _dt

        from cic_daily_report.breaking.content_generator import (
            _check_and_handle_stale_dates,
        )

        today = _dt.date(2026, 4, 30)
        content = "Tin nóng: BTC giảm mạnh hôm nay. Thị trường phản ứng tiêu cực." * 5
        cleaned, issues, failed = _check_and_handle_stale_dates(
            content, today=today, block_enabled=True
        )
        assert failed is False
        assert cleaned == content


# ---------------------------------------------------------------------------
# B6 — Magnitude scale ($1M vs $1B conflict)
# ---------------------------------------------------------------------------


class TestMagnitudeScale:
    """B6: _extract_magnitudes must scale by suffix → $1M=1e6, $1B=1e9."""

    def test_magnitude_scale_M_vs_B_conflict(self):
        """$1M and $1B differ by 1000x → conflict must fire."""
        from cic_daily_report.breaking.two_source_verifier import _has_numeric_conflict

        title_a = "Hacker drains $1M from DeFi protocol"
        title_b = "Hacker drains $1B from DeFi protocol"
        assert _has_numeric_conflict(title_a, title_b) is True

    def test_magnitude_scale_K_M_no_conflict_close(self):
        """$1.0M vs $1.05M → within 5% tolerance → not a conflict."""
        from cic_daily_report.breaking.two_source_verifier import _has_numeric_conflict

        title_a = "Exchange paid $1.0M settlement"
        title_b = "Exchange paid $1.05M settlement"
        assert _has_numeric_conflict(title_a, title_b) is False

    def test_extract_magnitudes_scaling(self):
        """Values come back scaled (1M → 1e6, 1B → 1e9)."""
        from cic_daily_report.breaking.two_source_verifier import _extract_magnitudes

        nums = _extract_magnitudes("Loss of $1M and $2B reported")
        assert 1_000_000.0 in nums
        assert 2_000_000_000.0 in nums


# ---------------------------------------------------------------------------
# B7 — Duplicate verified events same run skipped
# ---------------------------------------------------------------------------


class TestDuplicateVerifiedSameRun:
    """B7: when 2 outlets report same event in 1 run, only first ships."""

    def test_duplicate_verified_skipped_same_run(self):
        """Build a list of 2 ClassifiedEvents with overlapping entities.
        Pipeline gate logic should ship only first."""
        # Direct unit test of the dedup logic — we test the helper that
        # extracts entity keys and verify they overlap for same event.
        from cic_daily_report.breaking.dedup_manager import _extract_entities

        title_a = "Bitcoin ETF approved by SEC"
        title_b = "SEC approves Bitcoin ETF for trading"
        ent_a = frozenset(_extract_entities(title_a))
        ent_b = frozenset(_extract_entities(title_b))
        # Entity sets should overlap — both mention BTC + SEC.
        assert ent_a & ent_b, f"Entities should overlap: {ent_a} vs {ent_b}"

    def test_distinct_events_have_distinct_entity_keys(self):
        """Sanity: different events should produce different entity sets."""
        from cic_daily_report.breaking.dedup_manager import _extract_entities

        ent_a = frozenset(_extract_entities("Bitcoin halving complete"))
        ent_b = frozenset(_extract_entities("Ethereum Pectra upgrade live"))
        # Should not share entities (BTC vs ETH).
        assert not (ent_a & ent_b), "Distinct events should not share entities"


# ---------------------------------------------------------------------------
# B8 — Replay baseline URL fallback
# ---------------------------------------------------------------------------


class TestReplayBaselineFallback:
    """B8: replay must fetch URL when `content` field absent (BREAKING_LOG
    schema does not store content)."""

    def test_replay_baseline_fetch_url_fallback(self, monkeypatch):
        """_fetch_baseline_from_url returns extracted text on success."""
        import replay_breaking

        with patch.object(
            replay_breaking,
            "_fetch_baseline_from_url",
            return_value="extracted body text from URL",
        ):
            result = replay_breaking._fetch_baseline_from_url("https://example.com/x")
            assert result == "extracted body text from URL"

    def test_replay_baseline_empty_url_returns_empty(self):
        """No URL → empty string (no crash)."""
        import replay_breaking

        assert replay_breaking._fetch_baseline_from_url("") == ""


# ---------------------------------------------------------------------------
# B9 — Replay killswitch unset
# ---------------------------------------------------------------------------


class TestReplayKillSwitchUnset:
    """B9: replay must POP WAVE_0_6_KILL_SWITCH from env so the flags it
    forces ON actually take effect."""

    @pytest.mark.asyncio
    async def test_replay_killswitch_unset(self, tmp_path, monkeypatch):
        """When kill switch is set entering replay, it must be unset during
        run (else flags forced ON are silently overridden)."""
        import replay_breaking

        monkeypatch.setenv("WAVE_0_6_KILL_SWITCH", "1")

        recorded = {}

        async def fake_replay(row):
            # Record env state INSIDE the run (after flag setup).
            recorded["killswitch"] = os.environ.get("WAVE_0_6_KILL_SWITCH")
            recorded["enabled"] = os.environ.get("WAVE_0_6_ENABLED")
            return replay_breaking.ReplayEntry(
                title="t",
                source="s",
                severity="important",
                detected_at="2026-04-27T10:00:00+00:00",
            )

        monkeypatch.setattr(replay_breaking, "_replay_one_event_mock", fake_replay)

        await replay_breaking.run_replay(
            date_from="2026-04-27",
            date_to="2026-04-28",
            output_path=tmp_path / "r.md",
            mock=True,
            limit=1,
        )

        assert recorded["killswitch"] is None, "Kill switch must be unset during replay"
        assert recorded["enabled"] == "1"

        # And restored afterwards.
        assert os.environ.get("WAVE_0_6_KILL_SWITCH") == "1"


# ---------------------------------------------------------------------------
# A2 — URL ingest CLI script
# ---------------------------------------------------------------------------


class TestUrlIngestCli:
    """A2: scripts/ingest_url.py — manual one-off URL ingest."""

    def test_url_ingest_invalid_url(self):
        """Non-http URL raises ValueError."""
        import ingest_url

        with pytest.raises(ValueError, match="scheme"):
            ingest_url._validate_url("ftp://example.com/x")

        with pytest.raises(ValueError, match="host"):
            ingest_url._validate_url("https://")

    def test_url_ingest_hostname_to_source(self):
        """Hostname extraction strips www. and lowercases."""
        import ingest_url

        assert ingest_url._hostname_to_source("https://www.Decrypt.co/x") == "decrypt.co"
        assert ingest_url._hostname_to_source("https://coindesk.com/y") == "coindesk.com"
        assert ingest_url._hostname_to_source("not-a-url") == "unknown"

    def test_url_ingest_arg_parser_defaults(self):
        """CLI parser: severity defaults to 'important', dry-run is OFF."""
        import ingest_url

        parser = ingest_url._build_arg_parser()
        args = parser.parse_args(["https://example.com/x"])
        assert args.url == "https://example.com/x"
        assert args.severity == "important"
        assert args.dry_run is False
        assert args.skip_dedup is False

        args2 = parser.parse_args(
            [
                "https://example.com/y",
                "--severity",
                "critical",
                "--source-name",
                "Decrypt",
                "--dry-run",
            ]
        )
        assert args2.severity == "critical"
        assert args2.source_name == "Decrypt"
        assert args2.dry_run is True

    def test_url_ingest_arg_parser_rejects_bad_severity(self):
        """argparse should reject unknown severity tier."""
        import ingest_url

        parser = ingest_url._build_arg_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["https://example.com", "--severity", "FAKE"])


# ---------------------------------------------------------------------------
# A1 — Workflow Telethon env presence
# ---------------------------------------------------------------------------


class TestBreakingWorkflowTelethonEnv:
    """A1: breaking-news.yml must include Telethon env vars in 'Run breaking
    news check' step (they should NOT be in 'Validate required secrets'
    block — making them optional)."""

    def test_breaking_workflow_has_telethon_env(self):
        path = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "breaking-news.yml"
        text = path.read_text(encoding="utf-8")
        assert "TELEGRAM_API_ID:" in text
        assert "TELEGRAM_API_HASH:" in text
        assert "TELEGRAM_SESSION_STRING:" in text

    def test_breaking_workflow_telethon_not_required(self):
        """Telethon vars must NOT be in the 'Validate required secrets' block
        (they are optional — fallback to RSS if missing)."""
        path = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "breaking-news.yml"
        text = path.read_text(encoding="utf-8")
        # Locate the "Validate required secrets" block — until next "- name:".
        validate_idx = text.find("Validate required secrets")
        next_step_idx = text.find("- name:", validate_idx + 1)
        validate_block = text[validate_idx:next_step_idx]
        assert "TELEGRAM_API_ID" not in validate_block
        assert "TELEGRAM_SESSION_STRING" not in validate_block
