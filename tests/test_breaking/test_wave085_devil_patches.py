"""Wave 0.8.5 — Devil's Advocate cross-check patches on top of Wave 0.8.4.

Context: Wave 0.8.4 shipped 6 fixes. Devil HOLD called out 2 remaining holes:

- B1 (F7): URL exact match misses when SAME event reported by 2+ outlets with
  different URLs. Scenario: Wasabi 02:05 from AMBCrypto (URL A) → Wasabi 08:47
  from The Block (URL B) — URL filter passes both → second tin self-cites first
  as "lịch sử 30/4/2026" → LLM bịa.
- A3 (F8): Wave 0.8.4 F6 made Đoạn 2 BẮT BUỘC + KHÔNG bỏ qua → invitation to
  hallucinate when source lacks impact data → LLM bịa "có thể ảnh hưởng",
  "nhà phân tích cho rằng" → rolls back Wave 0.6 guardrail.

Patches:
- F7: RAGIndex.query() gains exclude_title (SequenceMatcher ratio>=0.7) +
  exclude_entities (intersection>=2) using dedup_manager._extract_entities.
  content_generator passes both for current event.
- F8: BREAKING_PROMPT_TEMPLATE Đoạn 2 — escape clause: if no source data on
  impact, write EXACT disclaimer sentence; explicit forbid of "có thể ảnh
  hưởng", "nhà phân tích cho rằng", "diễn biến này có thể".
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rank_bm25 import BM25Okapi

from cic_daily_report.adapters.llm_adapter import JudgeResult, LLMResponse
from cic_daily_report.breaking.content_generator import (
    BREAKING_PROMPT_TEMPLATE,
    generate_breaking_content,
)
from cic_daily_report.breaking.event_detector import BreakingEvent
from cic_daily_report.breaking.rag_index import RAGEvent, RAGIndex, _tokenize

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _event(
    title: str = "Wasabi shuts down 5M wallet",
    url: str = "https://ambcrypto.com/wasabi-shutdown",
    summary: str = "",
) -> BreakingEvent:
    return BreakingEvent(
        title=title,
        source="AMBCrypto",
        url=url,
        panic_score=85,
        raw_data={"summary": summary} if summary else {},
    )


def _mock_llm(text: str = "Tin nóng test với đủ nội dung để vượt qua các kiểm tra word count."):
    mock = AsyncMock()
    # Pad to >80 words so F1 hard gate doesn't trigger
    long_text = (text + " ") * 30
    mock.generate = AsyncMock(
        return_value=LLMResponse(text=long_text, tokens_used=100, model="test-model")
    )
    mock.judge_factual_claims = AsyncMock(
        return_value=JudgeResult(verdict="approved", confidence=0.9)
    )
    mock.last_provider = "groq"
    return mock


def _build_index_with(events: list[RAGEvent]) -> RAGIndex:
    """Build an in-memory RAGIndex from explicit events (no Sheets call)."""
    idx = RAGIndex(sqlite_path=":memory:", sheets_client=None)
    idx._events = events
    idx._tokenized_corpus = [_tokenize(e.to_doc_text()) for e in events]
    idx._bm25 = BM25Okapi(idx._tokenized_corpus) if idx._tokenized_corpus else None
    return idx


@pytest.fixture
def wave06_on(monkeypatch):
    monkeypatch.setenv("WAVE_0_6_ENABLED", "1")
    yield


# ---------------------------------------------------------------------------
# F7 — Title fuzzy + entity overlap exclusion
# ---------------------------------------------------------------------------


class TestF7TitleFuzzyAndEntity:
    """Devil B1: 2 outlets cover same event with different URLs → still self-ref."""

    def test_query_excludes_title_fuzzy_match(self):
        """SequenceMatcher ratio >= 0.7 → exclude (same event, reworded title)."""
        idx = _build_index_with(
            [
                RAGEvent(
                    event_id="e1",
                    # Near-identical title to what we'll pass as exclude_title
                    title="Wasabi shuts down 5M wallet service",
                    timestamp="2020-01-01T00:00:00+00:00",
                    metadata={"url": "https://theblock.co/wasabi"},
                ),
            ]
        )
        results = idx.query(
            "Wasabi wallet",
            min_score=0.0,
            exclude_recent_hours=0,
            exclude_title="Wasabi shuts down 5M wallet",
        )
        # Title ratio should be >= 0.7 → filtered out
        assert results == []

    def test_query_excludes_entity_overlap_2plus(self):
        """When 2+ shared entities (per dedup_manager pattern) — exclude.

        Uses entities the actual `_extract_entities` regex captures:
        Wasabi + DOJ are both in `_ENTITY_PATTERN` → overlap == 2 → exclude.
        """
        idx = _build_index_with(
            [
                RAGEvent(
                    event_id="e1",
                    # Both "Wasabi" and "DOJ" are token-matched by _ENTITY_PATTERN
                    title="Coinjoin tool Wasabi exits market after DOJ probe",
                    timestamp="2020-01-01T00:00:00+00:00",
                    metadata={"url": "https://reuters.com/wasabi-exit"},
                ),
            ]
        )
        # Pass the same 2 entities the regex would extract from current event
        results = idx.query(
            "Wasabi DOJ",
            min_score=0.0,
            exclude_recent_hours=0,
            exclude_entities={"wasabi", "doj"},
        )
        assert results == []

    def test_query_does_not_exclude_low_similarity(self):
        """ratio < 0.7 AND entity overlap < 2 → event passes through."""
        idx = _build_index_with(
            [
                RAGEvent(
                    event_id="e1",
                    title="Bitcoin halving 2024 reduces miner reward",
                    timestamp="2020-01-01T00:00:00+00:00",
                    metadata={"url": "https://example.com/halving"},
                ),
            ]
        )
        # Different topic — fuzzy and entity overlap should both miss
        results = idx.query(
            "Bitcoin halving",
            min_score=0.0,
            exclude_recent_hours=0,
            exclude_title="Wasabi wallet shuts down 5M",
            exclude_entities={"wasabi"},
        )
        # Should still return the event
        assert len(results) == 1
        assert results[0]["event_id"] == "e1"

    def test_two_outlets_same_event_filtered(self):
        """End-to-end: AMBCrypto Wasabi event indexed, query for The Block Wasabi."""
        # Indexed: AMBCrypto's version of the Wasabi 5M shutdown story.
        idx = _build_index_with(
            [
                RAGEvent(
                    event_id="ambcrypto_wasabi",
                    title="Wasabi Wallet shuts down 5M user service after DOJ pressure",
                    summary="The privacy wallet announced...",
                    source="AMBCrypto",
                    timestamp="2020-01-01T00:00:00+00:00",
                    metadata={"url": "https://ambcrypto.com/wasabi-5m-shutdown"},
                ),
            ]
        )
        # Now query as if we're writing about The Block's version of the same story
        # — different URL, near-identical title, same entities.
        results = idx.query(
            "Wasabi shuts down",
            min_score=0.0,
            exclude_recent_hours=0,
            exclude_url="https://theblock.co/wasabi-shutdown-5m",  # different URL!
            exclude_title="Wasabi Wallet shuts down 5M users after DOJ probe",
            exclude_entities={"wasabi", "doj"},
        )
        # Bug 4 redux: indexed event must NOT be returned as "history" of itself
        assert results == []

    @pytest.mark.asyncio
    async def test_get_historical_context_passes_title_and_entities(self, wave06_on):
        """content_generator._get_historical_context passes both new params."""
        ev = _event(
            title="Wasabi Wallet shuts down 5M user service",
            url="https://ambcrypto.com/wasabi",
        )
        with patch("cic_daily_report.breaking.rag_index.get_or_build_index") as mock_get:
            mock_idx = MagicMock()
            mock_idx.query.return_value = []
            mock_get.return_value = mock_idx
            llm = _mock_llm()
            await generate_breaking_content(ev, llm)
        kwargs = mock_idx.query.call_args.kwargs
        # F7: both new params must be supplied
        assert kwargs.get("exclude_title") == "Wasabi Wallet shuts down 5M user service"
        # exclude_entities should be a non-None set (at least Wasabi extracted)
        ents = kwargs.get("exclude_entities")
        assert ents is not None
        assert isinstance(ents, set)
        # Wasabi is in the F3 expanded entity pattern (Wave 0.8.4) so it must extract
        assert "wasabi" in ents


# ---------------------------------------------------------------------------
# F8 — Escape clause prompt instead of "BẮT BUỘC viết Đoạn 2"
# ---------------------------------------------------------------------------


class TestF8EscapeClause:
    """Devil A3: Wave 0.8.4 F6 invites hallucination when source lacks impact data."""

    def test_template_contains_escape_clause(self):
        """Prompt now includes the EXACT escape sentence."""
        # The escape clause body — must be present verbatim so LLM can copy it.
        # Build via concat to keep each source line under 100 chars (ruff E501).
        escape_part1 = (
            "Đây là tin nhanh, chưa có thông tin chi tiết về "
            "tác động lên thị trường tài sản mã hóa."
        )
        assert escape_part1 in BREAKING_PROMPT_TEMPLATE
        assert "Anh em theo dõi diễn biến tiếp theo trên BIC Group." in BREAKING_PROMPT_TEMPLATE

    def test_template_no_longer_says_BAT_BUOC_must_have_2_paragraphs(self):
        """Wave 0.8.4 F6 phrasing 'BẮT BUỘC 2-3 câu' must be removed from Đoạn 2."""
        # The exact F6 phrasing that invited hallucination
        assert "BẮT BUỘC 2-3 câu" not in BREAKING_PROMPT_TEMPLATE
        # And the "KHÔNG bỏ qua đoạn này" forced-write phrase
        assert "KHÔNG bỏ qua đoạn này" not in BREAKING_PROMPT_TEMPLATE
        # And the F6 fallback "viết 1 câu generic về tác động chung"
        assert "viết 1 câu generic về tác động chung" not in BREAKING_PROMPT_TEMPLATE

    def test_template_explicit_forbid_phrases(self):
        """Prompt explicitly forbids the 3 hallucination phrases Devil flagged."""
        # These phrases were observed in batch 01/05 when model padded Đoạn 2
        assert "có thể ảnh hưởng" in BREAKING_PROMPT_TEMPLATE
        assert "nhà phân tích cho rằng" in BREAKING_PROMPT_TEMPLATE
        assert "diễn biến này có thể" in BREAKING_PROMPT_TEMPLATE
        # And the TUYỆT ĐỐI KHÔNG BỊA framing
        assert "TUYỆT ĐỐI KHÔNG BỊA" in BREAKING_PROMPT_TEMPLATE

    def test_escape_clause_full_text_match(self):
        """Verify the full 2-sentence escape clause appears together in template."""
        # Full text must appear together so LLM uses it as one block, not fragmented.
        # Built via concat to keep each source line under 100 chars (ruff E501).
        full_clause = (
            "Đây là tin nhanh, chưa có thông tin chi tiết về "
            "tác động lên thị trường tài sản mã hóa. "
            "Anh em theo dõi diễn biến tiếp theo trên BIC Group."
        )
        # Allow either single-line or whitespace-flexible match
        # (template uses backslash-continuation which collapses to single line at format time)
        assert full_clause in BREAKING_PROMPT_TEMPLATE


# ---------------------------------------------------------------------------
# Integration — Wasabi 2-outlet scenario end-to-end
# ---------------------------------------------------------------------------


class TestE2EWasabiScenario:
    """Devil B1 E2E: 2nd Wasabi tin must NOT receive 1st Wasabi tin as history."""

    @pytest.mark.asyncio
    async def test_e2e_wasabi_scenario(self, wave06_on):
        """When AMBCrypto Wasabi already indexed, The Block Wasabi gets empty history."""
        # 1st event already in RAG cache (sent earlier in batch — but URL differs)
        ambcrypto_event = RAGEvent(
            event_id="ev1",
            title="Wasabi Wallet shuts down 5M user service after DOJ probe",
            summary="Privacy mixer Wasabi closes after pressure",
            source="AMBCrypto",
            timestamp="2020-01-01T00:00:00+00:00",  # very old → bypasses time filter
            metadata={"url": "https://ambcrypto.com/wasabi-5m"},
        )
        idx = _build_index_with([ambcrypto_event])

        # 2nd event being written about — different outlet, different URL,
        # SAME story. Without F7, RAG.query would return ev1 as "history" →
        # LLM self-cites "30/4/2026" hallucination.
        the_block_event = _event(
            title="Wasabi Wallet shuts down 5M users following DOJ scrutiny",
            url="https://theblock.co/wasabi-shutdown-5m-doj",
        )

        with patch("cic_daily_report.breaking.rag_index.get_or_build_index", return_value=idx):
            llm = _mock_llm()
            await generate_breaking_content(the_block_event, llm)

        # After F7 — when the LLM was actually called, the prompt must NOT
        # contain the AMBCrypto event as "historical context".
        prompt_passed = llm.generate.call_args.kwargs.get("prompt", "")
        # The 1st event's title fragment must NOT appear in <historical_events> block
        # If it did, the prompt would include "Wasabi Wallet shuts down 5M" within a
        # historical bullet — that's the Bug 4 / Devil B1 condition.
        assert "<historical_events>" not in prompt_passed, (
            "Wave 0.8.5 F7 failed: same-event from different outlet leaked into "
            "<historical_events> block — would cause self-ref hallucination."
        )
