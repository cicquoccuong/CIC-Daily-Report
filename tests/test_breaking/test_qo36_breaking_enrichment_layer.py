"""Tests for QO.36 — Breaking enrichment layer.

Tests: build_enrichment_context, _build_cross_asset_text,
_build_polymarket_shift_text, _build_related_history,
and integration of QO.36 params into generate_breaking_content.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

from cic_daily_report.adapters.llm_adapter import LLMResponse
from cic_daily_report.breaking.content_generator import (
    _build_cross_asset_text,
    _build_polymarket_shift_text,
    _build_related_history,
    build_enrichment_context,
    generate_breaking_content,
)
from cic_daily_report.breaking.event_detector import BreakingEvent

# --- Helpers ---


@dataclass
class FakeMarketDataPoint:
    symbol: str
    change_24h: float = 0.0
    price: float = 0.0
    data_type: str = "crypto"


@dataclass
class FakePolymarket:
    question: str
    outcome_yes: float = 0.0
    volume: float = 0.0


@dataclass
class FakePredictionData:
    markets: list


@dataclass
class FakeDedupEntry:
    title: str
    status: str = "sent"
    detected_at: str = "2026-04-15T00:00:00"


def _event():
    return BreakingEvent(
        title="Fed raises rates by 75 bps",
        source="Reuters",
        url="https://reuters.com/fed",
        panic_score=85,
    )


def _mock_llm(text="Tin nong: su kien tai san ma hoa quan trong."):
    mock = AsyncMock()
    mock.generate = AsyncMock(
        return_value=LLMResponse(text=text, tokens_used=100, model="test-model")
    )
    mock.last_provider = "test"
    return mock


# === _build_cross_asset_text Tests ===


class TestBuildCrossAssetText:
    """Tests for cross-asset correlation text builder."""

    def test_risk_off_signal(self):
        """BTC down + Gold up = risk-off."""
        data = [
            FakeMarketDataPoint("BTC", change_24h=-3.5, data_type="crypto"),
            FakeMarketDataPoint("Gold", change_24h=1.2),
        ]
        text = _build_cross_asset_text(data)
        assert "risk-off" in text
        assert "BTC" in text
        assert "Vang" in text

    def test_risk_on_signal(self):
        """BTC up + Gold down = risk-on."""
        data = [
            FakeMarketDataPoint("BTC", change_24h=4.0, data_type="crypto"),
            FakeMarketDataPoint("Gold", change_24h=-1.0),
        ]
        text = _build_cross_asset_text(data)
        assert "risk-on" in text

    def test_dxy_inverse_correlation(self):
        """BTC up + DXY down = normal inverse correlation."""
        data = [
            FakeMarketDataPoint("BTC", change_24h=3.0, data_type="crypto"),
            FakeMarketDataPoint("DXY", change_24h=-0.8),
        ]
        text = _build_cross_asset_text(data)
        assert "tuong quan am" in text

    def test_dxy_same_direction_abnormal(self):
        """BTC up + DXY up = abnormal."""
        data = [
            FakeMarketDataPoint("BTC", change_24h=3.0, data_type="crypto"),
            FakeMarketDataPoint("DXY", change_24h=0.8),
        ]
        text = _build_cross_asset_text(data)
        assert "bat thuong" in text

    def test_vix_fear_signal(self):
        """VIX >= 30 triggers fear signal."""
        data = [FakeMarketDataPoint("VIX", price=35.0)]
        text = _build_cross_asset_text(data)
        assert "hoang so" in text
        assert "VIX" in text

    def test_vix_below_threshold(self):
        """VIX < 30 — no signal."""
        data = [FakeMarketDataPoint("VIX", price=20.0)]
        text = _build_cross_asset_text(data)
        assert text == ""

    def test_oil_spike(self):
        """Oil change > 5% triggers signal."""
        data = [FakeMarketDataPoint("Oil", change_24h=7.5)]
        text = _build_cross_asset_text(data)
        assert "Dau" in text
        assert "tang" in text

    def test_oil_crash(self):
        """Oil change < -5% triggers signal."""
        data = [FakeMarketDataPoint("Oil", change_24h=-6.0)]
        text = _build_cross_asset_text(data)
        assert "Dau" in text
        assert "giam" in text

    def test_no_signals(self):
        """Small movements — no signals."""
        data = [
            FakeMarketDataPoint("BTC", change_24h=0.5, data_type="crypto"),
            FakeMarketDataPoint("Gold", change_24h=0.1),
        ]
        assert _build_cross_asset_text(data) == ""

    def test_empty_data(self):
        assert _build_cross_asset_text([]) == ""

    def test_multiple_signals_joined(self):
        """Multiple signals joined with pipe separator."""
        data = [
            FakeMarketDataPoint("BTC", change_24h=-5.0, data_type="crypto"),
            FakeMarketDataPoint("Gold", change_24h=2.0),
            FakeMarketDataPoint("VIX", price=35.0),
        ]
        text = _build_cross_asset_text(data)
        assert "|" in text
        assert "risk-off" in text
        assert "VIX" in text


# === _build_polymarket_shift_text Tests ===


class TestBuildPolymarketShiftText:
    """Tests for Polymarket prediction shift text builder."""

    def test_with_valid_markets(self):
        pred = FakePredictionData(
            markets=[
                FakePolymarket("Will BTC reach 100K?", outcome_yes=0.65, volume=50000),
                FakePolymarket("ETH to 5K by June?", outcome_yes=0.30, volume=20000),
            ]
        )
        text = _build_polymarket_shift_text(pred)
        assert "Polymarket" in text
        assert "BTC" in text
        assert "65%" in text

    def test_low_volume_filtered(self):
        """Markets with volume < 10000 are skipped."""
        pred = FakePredictionData(
            markets=[
                FakePolymarket("Some question", outcome_yes=0.5, volume=5000),
            ]
        )
        assert _build_polymarket_shift_text(pred) == ""

    def test_zero_probability_filtered(self):
        """Markets with 0 probability are skipped."""
        pred = FakePredictionData(
            markets=[
                FakePolymarket("Some question", outcome_yes=0.0, volume=50000),
            ]
        )
        assert _build_polymarket_shift_text(pred) == ""

    def test_empty_markets(self):
        pred = FakePredictionData(markets=[])
        assert _build_polymarket_shift_text(pred) == ""

    def test_no_markets_attribute(self):
        """Object without markets attribute."""
        assert _build_polymarket_shift_text(object()) == ""

    def test_max_5_markets(self):
        """Only first 5 markets included."""
        pred = FakePredictionData(
            markets=[FakePolymarket(f"Q{i}", outcome_yes=0.5, volume=50000) for i in range(10)]
        )
        text = _build_polymarket_shift_text(pred)
        # WHY: should have at most 5 entries separated by pipe
        assert text.count("|") <= 4

    def test_long_question_truncated(self):
        """Questions are truncated to 80 chars."""
        long_q = "A" * 200
        pred = FakePredictionData(
            markets=[
                FakePolymarket(long_q, outcome_yes=0.5, volume=50000),
            ]
        )
        text = _build_polymarket_shift_text(pred)
        # WHY: question in output should be max 80 chars
        assert len(text) < 200


# === _build_related_history Tests ===


class TestBuildRelatedHistory:
    """Tests for related breaking history builder."""

    def test_matching_entries(self):
        """Entries with >= 2 matching key words are included."""
        entries = [
            FakeDedupEntry("Federal Reserve raises interest rates"),
            FakeDedupEntry("Bitcoin drops below 80000"),
        ]
        text = _build_related_history(entries, "Federal Reserve announces rate decision")
        assert "Federal Reserve" in text

    def test_no_matching_entries(self):
        """No entries match — empty string."""
        entries = [
            FakeDedupEntry("Ethereum merge completed"),
        ]
        text = _build_related_history(entries, "Federal Reserve raises rates")
        assert text == ""

    def test_non_sent_entries_skipped(self):
        """Only 'sent' and 'sent_geo_digest' entries are considered."""
        entries = [
            FakeDedupEntry("Federal Reserve raises rates", status="pending"),
        ]
        text = _build_related_history(entries, "Federal Reserve announces new policy")
        assert text == ""

    def test_sent_geo_digest_included(self):
        """sent_geo_digest entries are included."""
        entries = [
            FakeDedupEntry(
                "Federal Reserve raises interest rates",
                status="sent_geo_digest",
            ),
        ]
        text = _build_related_history(entries, "Federal Reserve announces rate decision")
        assert "Federal" in text

    def test_max_3_entries(self):
        """At most 3 related entries are included."""
        entries = [FakeDedupEntry(f"Bitcoin price update {i}") for i in range(10)]
        text = _build_related_history(entries, "Bitcoin price drops sharply")
        lines = [line for line in text.split("\n") if line.strip()]
        assert len(lines) <= 3

    def test_short_words_filtered(self):
        """Words <= 3 chars are not used for matching."""
        entries = [
            FakeDedupEntry("The big event for all"),
        ]
        # WHY: "the", "big", "for", "all" are <= 3 chars or stop words
        text = _build_related_history(entries, "The big plan for all")
        # No matches since all key words are too short or stop words
        assert text == ""

    def test_empty_entries(self):
        assert _build_related_history([], "Some event") == ""

    def test_empty_title(self):
        entries = [FakeDedupEntry("Some event")]
        assert _build_related_history(entries, "") == ""


# === build_enrichment_context Tests ===


class TestBuildEnrichmentContext:
    """Tests for the top-level enrichment context builder."""

    def test_all_data_provided(self):
        """All three enrichment sources populated."""
        market_data = [
            FakeMarketDataPoint("BTC", change_24h=-5.0, data_type="crypto"),
            FakeMarketDataPoint("Gold", change_24h=2.0),
        ]
        pred_data = FakePredictionData(
            markets=[
                FakePolymarket("Will BTC reach 100K?", outcome_yes=0.65, volume=50000),
            ]
        )
        dedup_entries = [
            FakeDedupEntry("Federal Reserve raises interest rates"),
        ]
        result = build_enrichment_context(
            market_data=market_data,
            prediction_data=pred_data,
            dedup_entries=dedup_entries,
            event_title="Federal Reserve announces rate decision",
        )
        assert "cross_asset_context" in result
        assert "polymarket_shift" in result
        assert "breaking_history" in result
        assert result["cross_asset_context"] != ""
        assert result["polymarket_shift"] != ""

    def test_no_data_provided(self):
        """All empty — returns dict with empty strings."""
        result = build_enrichment_context()
        assert result["cross_asset_context"] == ""
        assert result["polymarket_shift"] == ""
        assert result["breaking_history"] == ""

    def test_partial_data(self):
        """Only market_data provided."""
        market_data = [
            FakeMarketDataPoint("VIX", price=35.0),
        ]
        result = build_enrichment_context(market_data=market_data)
        assert result["cross_asset_context"] != ""
        assert result["polymarket_shift"] == ""
        assert result["breaking_history"] == ""


# === Integration: QO.36 params in generate_breaking_content ===


class TestQO36Integration:
    """Verify QO.36 params are passed through to the prompt."""

    @pytest.mark.asyncio
    async def test_cross_asset_in_prompt(self):
        """cross_asset_context appears in the LLM prompt."""
        llm = _mock_llm()
        await generate_breaking_content(
            event=_event(),
            llm=llm,
            cross_asset_context="BTC giam -5% trong khi Vang tang +2% — risk-off",
        )
        prompt = llm.generate.call_args[1].get(
            "prompt",
            llm.generate.call_args[0][0] if llm.generate.call_args[0] else "",
        )
        if not prompt:
            prompt = str(llm.generate.call_args)
        # WHY: The enrichment context should be part of the prompt
        assert "risk-off" in prompt or "cross_asset_context" in str(llm.generate.call_args)

    @pytest.mark.asyncio
    async def test_polymarket_in_prompt(self):
        """polymarket_shift appears in the LLM prompt."""
        llm = _mock_llm()
        await generate_breaking_content(
            event=_event(),
            llm=llm,
            polymarket_shift="BTC 100K probability dropped from 65% to 52%",
        )
        call_kwargs = llm.generate.call_args[1]
        prompt = call_kwargs.get("prompt", "")
        assert "52%" in prompt or "polymarket" in prompt.lower()

    @pytest.mark.asyncio
    async def test_history_in_prompt(self):
        """breaking_history appears in the LLM prompt."""
        llm = _mock_llm()
        await generate_breaking_content(
            event=_event(),
            llm=llm,
            breaking_history="- [2026-04-14] Fed signals rate pause",
        )
        call_kwargs = llm.generate.call_args[1]
        prompt = call_kwargs.get("prompt", "")
        assert "rate pause" in prompt

    @pytest.mark.asyncio
    async def test_empty_enrichment_omitted(self):
        """Empty enrichment strings should not bloat the prompt."""
        llm = _mock_llm()
        await generate_breaking_content(
            event=_event(),
            llm=llm,
            cross_asset_context="",
            polymarket_shift="",
            breaking_history="",
        )
        call_kwargs = llm.generate.call_args[1]
        prompt = call_kwargs.get("prompt", "")
        # WHY: empty sections should not add labels to prompt
        assert "Tuong quan lien thi truong:" not in prompt
        assert "Dich chuyen thi truong du doan:" not in prompt
        assert "Lich su tin lien quan:" not in prompt

    @pytest.mark.asyncio
    async def test_consensus_snapshot_in_prompt(self):
        """consensus_snapshot (QO.19) is still wired correctly."""
        llm = _mock_llm()
        await generate_breaking_content(
            event=_event(),
            llm=llm,
            consensus_snapshot="BTC: BULLISH (3/5 sources)",
        )
        call_kwargs = llm.generate.call_args[1]
        prompt = call_kwargs.get("prompt", "")
        assert "BULLISH" in prompt
