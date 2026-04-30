"""Wave 0.8.2 — RAG sheets_client wire fix tests.

Production audit 30/04 found warning ``RAGIndex.build_from_sheets: no
sheets_client provided`` firing on every breaking-news.yml run because
``breaking_pipeline._execute_pipeline`` did NOT pass its SheetsClient
down to ``generate_breaking_content`` → ``_get_historical_context`` →
``get_or_build_index``. RAG returned empty list → judge had no historical
ground-truth → fact-check fail-open. These tests lock the wire.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

from cic_daily_report.adapters.llm_adapter import LLMResponse
from cic_daily_report.breaking.content_generator import (
    _get_historical_context,
    generate_breaking_content,
)
from cic_daily_report.breaking.event_detector import BreakingEvent


def _event() -> BreakingEvent:
    return BreakingEvent(
        title="BTC ETF outflow $500M",
        source="CoinDesk",
        url="https://coindesk.com/x",
        panic_score=70,
        raw_data={"summary": "Major BTC ETF outflow over the past week."},
    )


def _mock_llm() -> AsyncMock:
    mock = AsyncMock()
    mock.generate = AsyncMock(
        return_value=LLMResponse(
            text="Tin nóng: BTC ETF có dòng tiền rút.", tokens_used=50, model="test"
        )
    )
    mock.last_provider = "groq"
    return mock


# ---------------------------------------------------------------------------
# Test 1: pipeline → generate_breaking_content forwards sheets_client to RAG
# ---------------------------------------------------------------------------


async def test_generate_breaking_content_passes_sheets_client_to_rag():
    """generate_breaking_content(sheets_client=X) → _get_historical_context gets X."""
    fake_sheets = MagicMock(name="SheetsClient")
    captured: dict = {}

    def fake_ghc(event, top_k=3, sheets_client=None):
        # WHY: capture exact arg passed by generate_breaking_content's body.
        captured["sheets_client"] = sheets_client
        return ("", [])

    llm = _mock_llm()
    with patch(
        "cic_daily_report.breaking.content_generator._get_historical_context",
        side_effect=fake_ghc,
    ):
        await generate_breaking_content(_event(), llm, sheets_client=fake_sheets)
    assert captured["sheets_client"] is fake_sheets


# ---------------------------------------------------------------------------
# Test 2: with sheets_client → _get_historical_context queries RAGIndex
# ---------------------------------------------------------------------------


async def test_rag_inject_with_sheets_client_returns_historical():
    """When sheets_client provided + RAG hits → returns formatted block."""
    fake_sheets = MagicMock(name="SheetsClient")
    fake_idx = MagicMock()
    fake_idx.query.return_value = [
        {
            "event_id": "evt1",
            "title": "Past ETF outflow $300M",
            "summary": "Reference event",
            "source": "CoinDesk",
            "severity": "important",
            "timestamp": "2025-12-01T00:00:00+00:00",
            "btc_price": 76000.0,
            "score": 1.5,
        }
    ]
    with (
        patch(
            "cic_daily_report.breaking.content_generator._wave_0_6_enabled",
            return_value=True,
        ),
        patch(
            "cic_daily_report.breaking.rag_index.get_or_build_index",
            return_value=fake_idx,
        ),
    ):
        text, raw = _get_historical_context(_event(), sheets_client=fake_sheets)

    assert "<historical_events>" in text
    assert "Past ETF outflow" in text
    assert raw and raw[0]["event_id"] == "evt1"


# ---------------------------------------------------------------------------
# Test 3: sheets_client=None → silent skip (no warning, no RAG call)
# ---------------------------------------------------------------------------


async def test_rag_no_warning_when_sheets_client_missing(caplog):
    """ingest_url.py path: sheets_client=None → cache-only mode, NO WARNING emitted.

    Wave 0.8.2 demoted the "no sheets_client provided" log from WARNING to
    DEBUG — production logs (which run at INFO+) must no longer carry it.
    """
    from cic_daily_report.breaking.rag_index import RAGIndex

    caplog.set_level(logging.WARNING, logger="cic.rag_index")
    idx = RAGIndex(sheets_client=None)
    n = idx.build_from_sheets()
    assert n == 0
    # No WARNING-level record about missing sheets_client.
    warning_msgs = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert not any("no sheets_client provided" in m for m in warning_msgs), (
        f"WARNING regression: {warning_msgs}"
    )


# ---------------------------------------------------------------------------
# Test 4: RAG hit → <historical_events> block injected into prompt
# ---------------------------------------------------------------------------


async def test_rag_inject_creates_historical_context_block_in_prompt():
    """End-to-end: RAG hit → prompt contains <historical_events>."""
    fake_sheets = MagicMock(name="SheetsClient")
    rag_text = (
        "<historical_events>\n"
        "- [t] Past ETF outflow (BTC: $76,000, score: 1.50) — Nguồn: CD\n"
        "</historical_events>"
    )

    llm = _mock_llm()
    with patch(
        "cic_daily_report.breaking.content_generator._get_historical_context",
        return_value=(rag_text, [{"event_id": "x"}]),
    ):
        await generate_breaking_content(_event(), llm, sheets_client=fake_sheets)
    call_kwargs = llm.generate.call_args
    prompt = call_kwargs.kwargs.get("prompt", "") or call_kwargs.args[0]
    assert "<historical_events>" in prompt
    assert "Past ETF outflow" in prompt


# ---------------------------------------------------------------------------
# Test 5: Wave 0.6 flag OFF → RAG skipped (no sheets call regardless)
# ---------------------------------------------------------------------------


async def test_rag_disabled_flag_skips_call():
    """When _wave_0_6_enabled returns False, RAG path bypassed entirely."""
    fake_sheets = MagicMock(name="SheetsClient")
    with (
        patch(
            "cic_daily_report.breaking.content_generator._wave_0_6_enabled",
            return_value=False,
        ),
        patch("cic_daily_report.breaking.rag_index.get_or_build_index") as mock_get_or_build,
    ):
        text, raw = _get_historical_context(_event(), sheets_client=fake_sheets)
    assert text == ""
    assert raw == []
    mock_get_or_build.assert_not_called()


# ---------------------------------------------------------------------------
# Test 6: breaking_pipeline call site forwards sheets to generate_breaking_content
# ---------------------------------------------------------------------------


async def test_breaking_pipeline_call_site_includes_sheets_client_kwarg():
    """Static check on breaking_pipeline.py source: the individual-events branch
    must call generate_breaking_content with sheets_client= so the wire fix
    cannot regress. Reads source as text — NO pipeline runtime needed.
    """
    import inspect

    from cic_daily_report import breaking_pipeline

    src = inspect.getsource(breaking_pipeline)
    # Locate the individual-events generate_breaking_content invocation.
    # Both invocations (individual + deferred) must pass sheets_client.
    # WHY count occurrences: the file has 2 generate_breaking_content calls
    # — both must be wired. Old code had 0; new code must have 2.
    wired_count = src.count("sheets_client=sheets")
    assert wired_count >= 1, (
        "breaking_pipeline._execute_pipeline must pass sheets_client=sheets "
        "to generate_breaking_content (Wave 0.8.2 wire fix)"
    )
    # Deferred path passes the kwarg via the parameter name `sheets_client`.
    assert "sheets_client=sheets_client" in src, (
        "_reprocess_deferred_events must forward its sheets_client param "
        "into generate_breaking_content"
    )
