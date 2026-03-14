"""Tests for economic_calendar collector (FR60)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from cic_daily_report.collectors.economic_calendar import (
    CalendarResult,
    EconomicEvent,
    _is_crypto_relevant,
    collect_economic_calendar,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "economic_calendar_sample.json"


@pytest.fixture
def sample_events() -> list[dict]:
    return json.loads(FIXTURE.read_text())


# --- Unit tests ---


class TestIsCryptoRelevant:
    def test_exact_match(self):
        assert _is_crypto_relevant("CPI m/m") is True
        assert _is_crypto_relevant("FOMC Statement") is True
        assert _is_crypto_relevant("Unemployment Claims") is True

    def test_prefix_match(self):
        assert _is_crypto_relevant("FOMC Member Waller Speaks") is True

    def test_not_relevant(self):
        assert _is_crypto_relevant("German CPI y/y") is False
        assert _is_crypto_relevant("Daylight Saving Time") is False
        assert _is_crypto_relevant("Empire State Manufacturing Index") is False

    def test_empty_string(self):
        assert _is_crypto_relevant("") is False


class TestEconomicEvent:
    def test_dataclass_fields(self):
        ev = EconomicEvent(
            title="CPI m/m",
            country="USD",
            date="2026-03-14T08:30:00-04:00",
            impact="High",
            forecast="0.3%",
            previous="0.2%",
        )
        assert ev.title == "CPI m/m"
        assert ev.impact == "High"
        assert ev.forecast == "0.3%"


class TestCalendarResult:
    def test_format_empty(self):
        result = CalendarResult()
        assert result.format_for_llm() == ""

    def test_format_today_events(self):
        ev = EconomicEvent(
            title="CPI m/m",
            country="USD",
            date="2026-03-14T08:30:00-04:00",
            impact="High",
            forecast="0.3%",
            previous="0.2%",
        )
        result = CalendarResult(events=[ev], today_events=[ev])
        text = result.format_for_llm()
        assert "HÔM NAY" in text
        assert "CPI m/m" in text
        assert "0.3%" in text
        assert "0.2%" in text

    def test_format_upcoming_events(self):
        ev = EconomicEvent(
            title="Fed Interest Rate Decision",
            country="USD",
            date="2026-03-18T14:00:00-04:00",
            impact="High",
            forecast="4.50%",
            previous="4.75%",
        )
        result = CalendarResult(events=[ev], upcoming_events=[ev])
        text = result.format_for_llm()
        assert "SẮP TỚI" in text
        assert "Fed Interest Rate Decision" in text

    def test_format_both(self):
        today = EconomicEvent("CPI m/m", "USD", "2026-03-14T08:30:00-04:00", "High", "0.3%", "")
        upcoming = EconomicEvent(
            "FOMC Statement", "USD", "2026-03-18T14:00:00-04:00", "High", "", ""
        )
        result = CalendarResult(
            events=[today, upcoming],
            today_events=[today],
            upcoming_events=[upcoming],
        )
        text = result.format_for_llm()
        assert "HÔM NAY" in text
        assert "SẮP TỚI" in text


# --- Integration tests (mocked HTTP) ---


class TestCollectEconomicCalendar:
    @pytest.mark.asyncio
    async def test_successful_fetch(self, sample_events):
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_events
        mock_resp.raise_for_status = MagicMock()

        with patch("cic_daily_report.collectors.economic_calendar.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await collect_economic_calendar()

        # Should filter: only High + USD + crypto-relevant
        # From fixture: Fed Interest Rate, FOMC Statement, CPI m/m, Core CPI m/m,
        #   Unemployment Claims, Retail Sales = 6 events
        # German CPI (EUR) excluded, Trade Balance (Medium) excluded,
        # Daylight Saving (Holiday) excluded, Empire State (Low) excluded
        assert len(result.events) == 6
        titles = {ev.title for ev in result.events}
        assert "Fed Interest Rate Decision" in titles
        assert "CPI m/m" in titles
        assert "German CPI y/y" not in titles  # EUR, not USD
        assert "Trade Balance" not in titles  # Medium impact

    @pytest.mark.asyncio
    async def test_http_error_returns_empty(self):
        with patch("cic_daily_report.collectors.economic_calendar.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "404", request=MagicMock(), response=MagicMock(status_code=404)
            )
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await collect_economic_calendar()

        assert len(result.events) == 0

    @pytest.mark.asyncio
    async def test_request_error_returns_empty(self):
        with patch("cic_daily_report.collectors.economic_calendar.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.RequestError("Connection failed")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await collect_economic_calendar()

        assert len(result.events) == 0

    @pytest.mark.asyncio
    async def test_invalid_json_returns_empty(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"not": "a list"}
        mock_resp.raise_for_status = MagicMock()

        with patch("cic_daily_report.collectors.economic_calendar.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await collect_economic_calendar()

        assert len(result.events) == 0

    @pytest.mark.asyncio
    async def test_empty_feed_returns_empty(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()

        with patch("cic_daily_report.collectors.economic_calendar.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await collect_economic_calendar()

        assert len(result.events) == 0
        assert result.format_for_llm() == ""
