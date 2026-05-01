"""Wave 0.8.4 EMERGENCY hotfix — 6 fixes test suite.

Context: batch sáng 01/05/2026 (5 tin breaking, sau khi bật Wave 0.6 + Cerebras
key 30/04) phát hiện 4 bug visible + 2 latent risk:

- Bug 1: 3/5 tin chỉ có 1 câu (no Đoạn 2)
- Bug 2: tin truncated giữa câu ("...tính đến tháng 4 năm…")
- Bug 3: Wasabi gửi 2 lần (02:05 + 08:47, khác source) — entity miss
- Bug 4: CRITICAL — Wasabi 02:05 self-cited "30/4/2026" làm "lịch sử"
- Bug 5: Cerebras 429 silently fail-open, no metric/alert
- Bug 6: word_count<50 chỉ log, no block ship

6 fixes mapped:
- F1: word_count hard gate (>=80) sau judge retry + retry prompt re-emphasizes word_target
- F2: text_utils truncate prefer single \\n boundary (over hard cut)
- F3: dedup _ENTITY_PATTERN expand: Wasabi, EigenLayer, Spark, Symbiotic, Babylon, ...
- F4: RAG self-ref: exclude_recent_hours 1.0→24.0 + exclude_url param + prompt rule
- F5: Wave06Metrics.judge_unavailable counter + WARNING log + BreakingContent flag
- F6: Prompt template — bỏ phrase cho phép Đoạn 2 "ngắn hoặc bỏ qua"
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cic_daily_report.adapters.llm_adapter import JudgeResult, LLMResponse
from cic_daily_report.breaking.content_generator import (
    BREAKING_PROMPT_TEMPLATE,
    BreakingContent,
    generate_breaking_content,
)
from cic_daily_report.breaking.dedup_manager import _extract_entities
from cic_daily_report.breaking.event_detector import BreakingEvent
from cic_daily_report.breaking.rag_index import RAGEvent, RAGIndex
from cic_daily_report.breaking.wave06_metrics import Wave06Metrics
from cic_daily_report.core.error_handler import LLMError
from cic_daily_report.generators.text_utils import truncate_to_limit

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _event(
    title: str = "Wasabi wallet update",
    url: str = "https://example.com/wasabi",
    summary: str = "",
) -> BreakingEvent:
    return BreakingEvent(
        title=title,
        source="CoinDesk",
        url=url,
        panic_score=85,
        raw_data={"summary": summary} if summary else {},
    )


def _mock_llm(text: str = "Tin nóng test."):
    mock = AsyncMock()
    mock.generate = AsyncMock(
        return_value=LLMResponse(text=text, tokens_used=100, model="test-model")
    )
    mock.judge_factual_claims = AsyncMock(
        return_value=JudgeResult(verdict="approved", confidence=0.9)
    )
    mock.last_provider = "groq"
    return mock


@pytest.fixture
def wave06_on(monkeypatch):
    monkeypatch.setenv("WAVE_0_6_ENABLED", "1")
    yield


# ---------------------------------------------------------------------------
# F1 — word_count hard gate (>=80) + retry word constraint
# ---------------------------------------------------------------------------


class TestF1WordCountGate:
    """Bug 1 + Bug 6 (01/05): retry produced 1-câu output, only logged not blocked."""

    @pytest.mark.asyncio
    async def test_short_retry_output_raises_llmerror(self, wave06_on):
        """Judge retry produces <80 words → HARD BLOCK via LLMError."""
        # 11-word text — under 80
        short_text = "Tin nóng: tài sản mã hóa bị hack 100 triệu USD."
        with patch("cic_daily_report.breaking.rag_index.get_or_build_index") as mock_get:
            mock_get.return_value.query.return_value = []
            llm = _mock_llm(text=short_text)
            llm.judge_factual_claims = AsyncMock(
                side_effect=[
                    JudgeResult(verdict="rejected", issues=["bịa số"]),
                    JudgeResult(verdict="approved", confidence=0.9),
                ]
            )
            with pytest.raises(LLMError) as exc_info:
                await generate_breaking_content(_event(), llm, severity="critical")
        assert "too short after judge retry" in str(exc_info.value)
        # Source identifier must be the dedicated word-gate marker
        assert exc_info.value.source == "breaking_content_word_gate"

    @pytest.mark.asyncio
    async def test_short_no_retry_does_not_block(self, wave06_on):
        """Judge approved 1st try → no retry → no F1 gate (legacy behavior preserved)."""
        # Short content but no judge retry → must NOT raise
        short_text = "Tin nóng: hack 100 triệu USD."
        with patch("cic_daily_report.breaking.rag_index.get_or_build_index") as mock_get:
            mock_get.return_value.query.return_value = []
            llm = _mock_llm(text=short_text)
            # judge approved — NO retry path
            result = await generate_breaking_content(_event(), llm, severity="critical")
        # Ships short content (legacy behavior — no judge retry triggered)
        assert isinstance(result, BreakingContent)

    @pytest.mark.asyncio
    async def test_long_retry_output_passes_gate(self, wave06_on):
        """Judge retry produces >=80 words → ships normally."""
        long_text = " ".join(["từ"] * 120)  # 120 words
        with patch("cic_daily_report.breaking.rag_index.get_or_build_index") as mock_get:
            mock_get.return_value.query.return_value = []
            llm = _mock_llm(text=long_text)
            llm.judge_factual_claims = AsyncMock(
                side_effect=[
                    JudgeResult(verdict="rejected", issues=["bịa"]),
                    JudgeResult(verdict="approved", confidence=0.9),
                ]
            )
            result = await generate_breaking_content(_event(), llm, severity="critical")
        assert result.ai_generated
        assert llm.generate.call_count == 2  # original + retry

    @pytest.mark.asyncio
    async def test_retry_prompt_re_emphasizes_word_target(self, wave06_on):
        """Retry prompt MUST include word_target + 2-đoạn instruction."""
        long_text = " ".join(["từ"] * 100)
        with patch("cic_daily_report.breaking.rag_index.get_or_build_index") as mock_get:
            mock_get.return_value.query.return_value = []
            llm = _mock_llm(text=long_text)
            llm.judge_factual_claims = AsyncMock(
                side_effect=[
                    JudgeResult(verdict="rejected", issues=["bịa số X"]),
                    JudgeResult(verdict="approved", confidence=0.9),
                ]
            )
            await generate_breaking_content(_event(), llm, severity="critical")
        retry_prompt = llm.generate.call_args_list[1].kwargs["prompt"]
        # word_target for critical = "300-400"
        assert "300-400 từ" in retry_prompt
        assert "ĐỦ 2 đoạn" in retry_prompt
        assert "TẠI SAO QUAN TRỌNG cho cộng đồng CIC" in retry_prompt

    @pytest.mark.asyncio
    async def test_retry_prompt_includes_issue_text(self, wave06_on):
        """Retry prompt must surface judge issues so LLM knows what to fix."""
        long_text = " ".join(["từ"] * 100)
        with patch("cic_daily_report.breaking.rag_index.get_or_build_index") as mock_get:
            mock_get.return_value.query.return_value = []
            llm = _mock_llm(text=long_text)
            llm.judge_factual_claims = AsyncMock(
                side_effect=[
                    JudgeResult(verdict="rejected", issues=["bịa $6B Poly", "bịa ngày"]),
                    JudgeResult(verdict="approved", confidence=0.9),
                ]
            )
            await generate_breaking_content(_event(), llm, severity="critical")
        retry_prompt = llm.generate.call_args_list[1].kwargs["prompt"]
        assert "bịa $6B Poly" in retry_prompt
        assert "bịa ngày" in retry_prompt


# ---------------------------------------------------------------------------
# F2 — text_utils truncate boundary (single newline fallback)
# ---------------------------------------------------------------------------


class TestF2TruncateBoundary:
    """Bug 2 (01/05): truncation cut mid-sentence ("...tính đến tháng 4 năm…")."""

    def test_truncate_prefers_paragraph_break_first(self):
        """Paragraph break (\\n\\n) wins over single newline + sentence."""
        text = "Đoạn 1.\n\nĐoạn 2 dài hơn nhiều với nhiều câu khác nhau ở đây."
        # max_chars = 25 → must break at \n\n
        result, was_trunc = truncate_to_limit(text, 25)
        assert was_trunc
        assert result == "Đoạn 1."

    def test_truncate_prefers_sentence_over_newline(self):
        """Sentence boundary (. ) wins over single \\n if both fit."""
        # ". " at idx 7, "\n" at idx 30 — sentence boundary closer to limit
        text = "Câu 1. Câu 2 dài.\nDòng 2 nữa."
        result, was_trunc = truncate_to_limit(text, 18)
        assert was_trunc
        # Should cut at "Câu 2 dài." — sentence end before \n
        assert result.endswith(".")
        # Must NOT contain "Dòng 2"
        assert "Dòng 2" not in result

    def test_truncate_falls_back_to_single_newline_no_sentence(self):
        """No sentence boundary in window → single \\n fallback (Wave 0.8.4 F2)."""
        # No "."/"!"/"?" in first 30 chars; \n at idx 20
        text = "Tiêu đề rất dài đây\nNội dung phía dưới đây"
        result, was_trunc = truncate_to_limit(text, 25)
        assert was_trunc
        # Must cut at \n (idx 20) → "Tiêu đề rất dài đây"
        assert result == "Tiêu đề rất dài đây"
        # Must NOT include any of the post-newline content
        assert "Nội dung" not in result

    def test_truncate_avoids_mid_sentence_cut_via_newline(self):
        """Bug 2 regression: prefer \\n over hard mid-word cut.

        Production-shape input: long sentence with \\n line break, no
        sentence-ending punctuation in window, but \\n is present BEFORE
        the limit. Old behavior would hard-cut mid-word; new fallback
        uses \\n boundary for clean truncation.
        """
        text = "Bitcoin đạt cao mới tháng 4\nDòng kế tiếp ở đây"
        result, was_trunc = truncate_to_limit(text, 35)
        assert was_trunc
        # Should cut at \n (idx 27), not mid-word
        assert result == "Bitcoin đạt cao mới tháng 4"
        assert "Dòng" not in result


# ---------------------------------------------------------------------------
# F3 — dedup entity pattern expand (Wasabi + DeFi protocols)
# ---------------------------------------------------------------------------


class TestF3EntityPatternExpand:
    """Bug 3 (01/05): Wasabi sent twice (different sources) — entity miss."""

    def test_wasabi_extracted_as_entity(self):
        """Wasabi must be detected by _ENTITY_PATTERN."""
        entities = _extract_entities("Wasabi wallet announces v3 update")
        assert "wasabi" in entities

    def test_eigenlayer_extracted_as_entity(self):
        """EigenLayer must be detected (recurring in restaking news)."""
        entities = _extract_entities("EigenLayer restaking TVL hits $20B")
        assert "eigenlayer" in entities

    def test_spark_extracted_as_entity(self):
        """Spark / Sparklend must be detected (DeFi protocol)."""
        entities = _extract_entities("Spark protocol expands to L2")
        assert "spark" in entities

    def test_existing_entities_still_extracted(self):
        """No regression: BTC, Aave, MakerDAO still extracted."""
        # MakerDAO synonyms map to "mkr" (NAME_TO_TICKER) — accept either form.
        entities = _extract_entities("BTC, Aave, MakerDAO see flows")
        assert "btc" in entities
        assert "aave" in entities
        # MakerDAO normalized via _ENTITY_SYNONYMS — accept "mkr" or "makerdao"
        assert ("makerdao" in entities) or ("mkr" in entities)


# ---------------------------------------------------------------------------
# F4 — RAG self-ref filter (CRITICAL — Bug 4)
# ---------------------------------------------------------------------------


class TestF4RAGSelfRefFilter:
    """Bug 4 CRITICAL (01/05): Wasabi tin self-cited "30/4/2026" làm "lịch sử"."""

    @pytest.mark.asyncio
    async def test_query_called_with_24h_exclude_default(self, wave06_on):
        """exclude_recent_hours default bumped 1.0 → 24.0."""
        mock_idx = MagicMock()
        mock_idx.query.return_value = []
        with patch(
            "cic_daily_report.breaking.rag_index.get_or_build_index",
            return_value=mock_idx,
        ):
            llm = _mock_llm()
            await generate_breaking_content(_event(), llm)
        kwargs = mock_idx.query.call_args.kwargs
        assert kwargs.get("exclude_recent_hours") == 24.0

    @pytest.mark.asyncio
    async def test_query_called_with_exclude_url(self, wave06_on):
        """exclude_url passed = current event URL (belt-and-suspenders)."""
        mock_idx = MagicMock()
        mock_idx.query.return_value = []
        ev = _event(url="https://coindesk.com/wasabi-update")
        with patch(
            "cic_daily_report.breaking.rag_index.get_or_build_index",
            return_value=mock_idx,
        ):
            llm = _mock_llm()
            await generate_breaking_content(ev, llm)
        kwargs = mock_idx.query.call_args.kwargs
        assert kwargs.get("exclude_url") == "https://coindesk.com/wasabi-update"

    def test_rag_query_excludes_event_with_matching_url(self):
        """RAGIndex.query: exclude_url filter removes events with matching URL.

        Tests the core fix — even if timestamp filter fails, URL match catches.
        """
        # Build minimal index in-memory with 2 events (one with matching URL)
        idx = RAGIndex(sqlite_path=":memory:", sheets_client=None)
        idx._events = [
            RAGEvent(
                event_id="e1",
                title="Wasabi update news",
                summary="",
                source="CoinDesk",
                timestamp="2020-01-01T00:00:00+00:00",  # very old → not recency-filtered
                metadata={"url": "https://coindesk.com/wasabi"},
            ),
            RAGEvent(
                event_id="e2",
                title="Wasabi unrelated history",
                summary="",
                source="Reuters",
                timestamp="2020-01-01T00:00:00+00:00",
                metadata={"url": "https://reuters.com/other"},
            ),
        ]
        # Build BM25 over the events
        from rank_bm25 import BM25Okapi

        from cic_daily_report.breaking.rag_index import _tokenize

        idx._tokenized_corpus = [_tokenize(e.to_doc_text()) for e in idx._events]
        idx._bm25 = BM25Okapi(idx._tokenized_corpus)

        # Without exclude_url → both events match
        results_all = idx.query("Wasabi", min_score=0.0, exclude_recent_hours=0)
        urls_all = {r.get("url") for r in results_all}
        assert "https://coindesk.com/wasabi" in urls_all
        assert "https://reuters.com/other" in urls_all

        # With exclude_url → matching URL filtered out
        results_filtered = idx.query(
            "Wasabi",
            min_score=0.0,
            exclude_recent_hours=0,
            exclude_url="https://coindesk.com/wasabi",
        )
        urls_filtered = {r.get("url") for r in results_filtered}
        assert "https://coindesk.com/wasabi" not in urls_filtered
        # Other event still returned
        assert "https://reuters.com/other" in urls_filtered

    def test_rag_query_exclude_url_case_insensitive_trailing_slash(self):
        """URL match tolerates case + trailing slash difference (RSS variance)."""
        idx = RAGIndex(sqlite_path=":memory:", sheets_client=None)
        idx._events = [
            RAGEvent(
                event_id="e1",
                title="Wasabi news",
                timestamp="2020-01-01T00:00:00+00:00",
                metadata={"url": "https://CoinDesk.com/wasabi/"},
            ),
        ]
        from rank_bm25 import BM25Okapi

        from cic_daily_report.breaking.rag_index import _tokenize

        idx._tokenized_corpus = [_tokenize(e.to_doc_text()) for e in idx._events]
        idx._bm25 = BM25Okapi(idx._tokenized_corpus)

        # Pass URL with different case + no trailing slash
        results = idx.query(
            "Wasabi",
            min_score=0.0,
            exclude_recent_hours=0,
            exclude_url="https://coindesk.com/wasabi",
        )
        # Should be filtered out despite case + trailing slash difference
        assert results == []

    @pytest.mark.asyncio
    async def test_prompt_contains_24h_self_ref_warning_when_rag_hits(self, wave06_on):
        """When RAG returns hits, prompt instructs LLM not to treat 24h events as history."""
        fake_results = [
            {
                "timestamp": "2025-12-01T10:00:00+00:00",
                "title": "Old Wasabi news",
                "btc_price": 32000.0,
                "score": 1.5,
                "source": "Reuters",
            },
        ]
        mock_idx = MagicMock()
        mock_idx.query.return_value = fake_results
        with patch(
            "cic_daily_report.breaking.rag_index.get_or_build_index",
            return_value=mock_idx,
        ):
            llm = _mock_llm()
            await generate_breaking_content(_event(), llm, severity="critical")
        prompt = llm.generate.call_args.kwargs["prompt"]
        # The new explicit guard text
        assert "KHÔNG ref event xảy ra trong 24h qua làm 'lịch sử'" in prompt
        assert "tin cùng batch" in prompt


# ---------------------------------------------------------------------------
# F5 — Cerebras judge_unavailable metric + WARNING log
# ---------------------------------------------------------------------------


class TestF5JudgeUnavailableMetric:
    """Bug 5 (01/05): Cerebras 429 silently fail-open, no metric/alert."""

    def test_wave06_metrics_has_judge_unavailable_field(self):
        """Wave06Metrics dataclass includes judge_unavailable counter."""
        m = Wave06Metrics()
        assert hasattr(m, "judge_unavailable")
        assert m.judge_unavailable == 0

    def test_wave06_metrics_increment_judge_unavailable(self):
        """increment() works for judge_unavailable."""
        m = Wave06Metrics()
        m.increment("judge_unavailable")
        m.increment("judge_unavailable", delta=2)
        assert m.judge_unavailable == 3

    def test_wave06_metrics_log_line_contains_judge_unavail(self):
        """to_log_line() surfaces judge_unavailable count for ops grep."""
        m = Wave06Metrics()
        m.judge_unavailable = 5
        line = m.to_log_line()
        assert "judge_unavail=5" in line

    def test_wave06_metrics_is_empty_considers_judge_unavailable(self):
        """is_empty() returns False when judge_unavailable > 0."""
        m = Wave06Metrics()
        assert m.is_empty()
        m.judge_unavailable = 1
        assert not m.is_empty()

    @pytest.mark.asyncio
    async def test_breaking_content_flags_judge_unavailable(self, wave06_on):
        """generate_breaking_content sets judge_unavailable=True when judge fail-open."""
        with patch("cic_daily_report.breaking.rag_index.get_or_build_index") as mock_get:
            mock_get.return_value.query.return_value = []
            llm = _mock_llm(text=" ".join(["từ"] * 120))
            # Simulate Cerebras outage: judge returns approved + "judge_unavailable:" issue
            llm.judge_factual_claims = AsyncMock(
                return_value=JudgeResult(
                    verdict="approved",
                    issues=["judge_unavailable: TimeoutError"],
                    confidence=0.0,
                )
            )
            result = await generate_breaking_content(_event(), llm, severity="critical")
        assert result.judge_unavailable is True

    @pytest.mark.asyncio
    async def test_breaking_content_judge_available_flag_false(self, wave06_on):
        """When judge is healthy, judge_unavailable flag stays False."""
        with patch("cic_daily_report.breaking.rag_index.get_or_build_index") as mock_get:
            mock_get.return_value.query.return_value = []
            llm = _mock_llm(text=" ".join(["từ"] * 120))
            llm.judge_factual_claims = AsyncMock(
                return_value=JudgeResult(verdict="approved", confidence=0.95)
            )
            result = await generate_breaking_content(_event(), llm, severity="critical")
        assert result.judge_unavailable is False


# ---------------------------------------------------------------------------
# F6 — Prompt template fix (no "ngắn hoặc bỏ qua")
# ---------------------------------------------------------------------------


class TestF6PromptNoBoQua:
    """Prompt no longer permits Đoạn 2 to be skipped."""

    def test_template_does_not_contain_bo_qua(self):
        """Wave 0.8.4 F6: phrase 'ngắn hoặc bỏ qua' removed from prompt."""
        assert "ngắn hoặc bỏ qua" not in BREAKING_PROMPT_TEMPLATE
        # And the affirmative replacement is present
        assert "BẮT BUỘC 2-3 câu" in BREAKING_PROMPT_TEMPLATE
        assert "KHÔNG bỏ qua đoạn này" in BREAKING_PROMPT_TEMPLATE
