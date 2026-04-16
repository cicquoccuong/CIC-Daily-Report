"""Tests for QO.18 — LLM Impact Scoring via SambaNova.

SambaNova API integration for scoring event importance 1-10.
Score < 4 → skip, 4-6 → digest, >= 7 → send individually.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

from cic_daily_report.breaking.event_detector import BreakingEvent
from cic_daily_report.breaking.llm_scorer import (
    IMPACT_DIGEST_THRESHOLD,
    IMPACT_SCORING_PROMPT,
    IMPACT_SKIP_THRESHOLD,
    SAMBANOVA_API_BASE,
    SAMBANOVA_MAX_RPD,
    SAMBANOVA_MODEL,
    SAMBANOVA_TIMEOUT,
    _parse_impact_score,
    classify_by_impact,
    get_sambanova_calls_today,
    reset_sambanova_counter,
    score_event_impact,
)


def _event(title="BTC hack", summary="Major exchange hack occurred"):
    return BreakingEvent(
        title=title,
        source="CoinDesk",
        url="https://example.com",
        panic_score=80,
        raw_data={"summary": summary},
    )


# ============================================================================
# Constants
# ============================================================================


class TestSambaNovaConstants:
    """QO.18: Verify SambaNova configuration constants."""

    def test_api_base(self):
        assert SAMBANOVA_API_BASE == "https://api.sambanova.ai/v1"

    def test_model(self):
        assert SAMBANOVA_MODEL == "Meta-Llama-3.3-70B-Instruct"

    def test_timeout(self):
        assert SAMBANOVA_TIMEOUT == 15

    def test_max_rpd(self):
        assert SAMBANOVA_MAX_RPD == 20

    def test_skip_threshold(self):
        assert IMPACT_SKIP_THRESHOLD == 4

    def test_digest_threshold(self):
        assert IMPACT_DIGEST_THRESHOLD == 7

    def test_prompt_template_has_placeholders(self):
        assert "{title}" in IMPACT_SCORING_PROMPT
        assert "{summary}" in IMPACT_SCORING_PROMPT


# ============================================================================
# _parse_impact_score
# ============================================================================


class TestParseImpactScore:
    """QO.18: Parse integer score from LLM response."""

    def test_simple_number(self):
        assert _parse_impact_score("7") == 7

    def test_number_with_text(self):
        assert _parse_impact_score("Score: 8") == 8

    def test_number_slash_format(self):
        assert _parse_impact_score("7/10") == 7

    def test_clamp_high(self):
        """Score > 10 clamped to 10."""
        assert _parse_impact_score("15") == 10

    def test_clamp_low(self):
        """Score < 1 clamped to 1."""
        assert _parse_impact_score("0") == 1

    def test_no_number_defaults_to_10(self):
        """No parseable number → default 10 (pass through)."""
        assert _parse_impact_score("I cannot score this") == 10

    def test_empty_string(self):
        assert _parse_impact_score("") == 10

    def test_decimal_takes_integer_part(self):
        assert _parse_impact_score("7.5") == 7

    def test_score_with_explanation(self):
        assert _parse_impact_score("Score is 9 because it's very important") == 9


# ============================================================================
# classify_by_impact
# ============================================================================


class TestClassifyByImpact:
    """QO.18: Classify event action based on impact score."""

    def test_score_1_skip(self):
        assert classify_by_impact(1) == "skip"

    def test_score_2_skip(self):
        assert classify_by_impact(2) == "skip"

    def test_score_3_skip(self):
        assert classify_by_impact(3) == "skip"

    def test_score_4_digest(self):
        assert classify_by_impact(4) == "digest"

    def test_score_5_digest(self):
        assert classify_by_impact(5) == "digest"

    def test_score_6_digest(self):
        assert classify_by_impact(6) == "digest"

    def test_score_7_send(self):
        assert classify_by_impact(7) == "send"

    def test_score_8_send(self):
        assert classify_by_impact(8) == "send"

    def test_score_9_send(self):
        assert classify_by_impact(9) == "send"

    def test_score_10_send(self):
        assert classify_by_impact(10) == "send"


# ============================================================================
# score_event_impact
# ============================================================================


class TestScoreEventImpact:
    """QO.18: score_event_impact() calls SambaNova API."""

    def setup_method(self):
        reset_sambanova_counter()

    async def test_no_api_key_returns_10(self):
        """No SAMBANOVA_API_KEY → graceful fallback (score=10, pass through)."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove key if present
            os.environ.pop("SAMBANOVA_API_KEY", None)
            score = await score_event_impact(_event())
        assert score == 10

    async def test_api_call_success(self):
        """Successful API call returns parsed score."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": "8"}}]}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.dict(os.environ, {"SAMBANOVA_API_KEY": "test-key"}),
            patch(
                "cic_daily_report.breaking.llm_scorer.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            score = await score_event_impact(_event())

        assert score == 8
        assert get_sambanova_calls_today() == 1

    async def test_api_failure_returns_10(self):
        """API error → graceful fallback (score=10)."""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("Connection timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.dict(os.environ, {"SAMBANOVA_API_KEY": "test-key"}),
            patch(
                "cic_daily_report.breaking.llm_scorer.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            score = await score_event_impact(_event())

        assert score == 10

    async def test_rate_limit_enforcement(self):
        """After SAMBANOVA_MAX_RPD calls, returns 10 without calling API."""
        # Simulate reaching the limit
        import cic_daily_report.breaking.llm_scorer as scorer_module

        scorer_module._sambanova_calls_today = SAMBANOVA_MAX_RPD

        with patch.dict(os.environ, {"SAMBANOVA_API_KEY": "test-key"}):
            score = await score_event_impact(_event())

        assert score == 10
        # Counter should NOT have increased
        assert scorer_module._sambanova_calls_today == SAMBANOVA_MAX_RPD

        # Cleanup
        reset_sambanova_counter()

    async def test_counter_increments_on_success(self):
        """Successful call increments the counter."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": "5"}}]}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        assert get_sambanova_calls_today() == 0

        with (
            patch.dict(os.environ, {"SAMBANOVA_API_KEY": "test-key"}),
            patch(
                "cic_daily_report.breaking.llm_scorer.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            await score_event_impact(_event())
            await score_event_impact(_event())

        assert get_sambanova_calls_today() == 2

    async def test_event_without_raw_data(self):
        """Event with no raw_data → summary defaults to N/A."""
        event = BreakingEvent(
            title="Test event",
            source="S",
            url="https://x.com",
            panic_score=50,
            raw_data={},
        )

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": "6"}}]}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.dict(os.environ, {"SAMBANOVA_API_KEY": "test-key"}),
            patch(
                "cic_daily_report.breaking.llm_scorer.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            score = await score_event_impact(event)

        assert score == 6


# ============================================================================
# reset_sambanova_counter
# ============================================================================


class TestResetCounter:
    def test_reset(self):
        import cic_daily_report.breaking.llm_scorer as mod

        mod._sambanova_calls_today = 15
        reset_sambanova_counter()
        assert get_sambanova_calls_today() == 0


# ============================================================================
# Integration: _score_events_impact in pipeline
# ============================================================================


class TestScoreEventsImpactPipeline:
    """QO.18: _score_events_impact filters events by impact score."""

    async def test_low_impact_removed(self):
        """Events with score < 4 removed from list."""
        from cic_daily_report.breaking_pipeline import _score_events_impact

        events = [_event("Minor update about nothing important")]

        with patch(
            "cic_daily_report.breaking.llm_scorer.score_event_impact",
            return_value=2,
        ):
            result = await _score_events_impact(events)

        assert len(result) == 0

    async def test_high_impact_kept(self):
        """Events with score >= 7 kept."""
        from cic_daily_report.breaking_pipeline import _score_events_impact

        events = [_event("Major Bitcoin ETF approved by SEC")]

        with patch(
            "cic_daily_report.breaking.llm_scorer.score_event_impact",
            return_value=9,
        ):
            result = await _score_events_impact(events)

        assert len(result) == 1
        assert result[0].raw_data["impact_score"] == 9
        assert result[0].raw_data["impact_action"] == "send"

    async def test_digest_impact_kept(self):
        """Events with score 4-6 kept (routed to digest)."""
        from cic_daily_report.breaking_pipeline import _score_events_impact

        events = [_event("Moderate market update")]

        with patch(
            "cic_daily_report.breaking.llm_scorer.score_event_impact",
            return_value=5,
        ):
            result = await _score_events_impact(events)

        assert len(result) == 1
        assert result[0].raw_data["impact_action"] == "digest"

    async def test_scoring_failure_passes_through(self):
        """If scoring fails for an event, it passes through."""
        from cic_daily_report.breaking_pipeline import _score_events_impact

        events = [_event("Event that causes scoring error")]

        with patch(
            "cic_daily_report.breaking.llm_scorer.score_event_impact",
            side_effect=Exception("API error"),
        ):
            result = await _score_events_impact(events)

        assert len(result) == 1  # Still passes through

    async def test_empty_events_returns_empty(self):
        from cic_daily_report.breaking_pipeline import _score_events_impact

        result = await _score_events_impact([])
        assert result == []

    async def test_mixed_scores(self):
        """Mix of skip, digest, and send events."""
        from cic_daily_report.breaking_pipeline import _score_events_impact

        events = [
            _event("Low impact event"),
            _event("Medium impact event"),
            _event("High impact event"),
        ]

        scores = iter([2, 5, 9])

        async def mock_score(event):
            return next(scores)

        with patch(
            "cic_daily_report.breaking.llm_scorer.score_event_impact",
            side_effect=mock_score,
        ):
            result = await _score_events_impact(events)

        assert len(result) == 2  # Low impact removed
