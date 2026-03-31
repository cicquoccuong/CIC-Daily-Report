"""Tests for collectors/fred_macro.py — all mocked (P1.19)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from cic_daily_report.collectors.fred_macro import (
    FREDDataPoint,
    collect_fred_macro,
    format_fred_for_llm,
)

MODULE = "cic_daily_report.collectors.fred_macro"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_fred_response(series_id: str, value: str, date: str) -> dict:
    """Build a mock FRED API response for a single series."""
    return {
        "observations": [
            {"date": date, "value": value},
        ]
    }


def _mock_httpx_client(responses: list[dict]):
    """Create a mock httpx.AsyncClient that returns responses in order.

    Each call to client.get() returns the next response from the list.
    """
    mock_client = AsyncMock()
    mock_responses = []
    for resp_data in responses:
        mock_resp = MagicMock()
        mock_resp.json.return_value = resp_data
        mock_resp.raise_for_status = MagicMock()
        mock_responses.append(mock_resp)

    mock_client.get = AsyncMock(side_effect=mock_responses)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


# ---------------------------------------------------------------------------
# Tests: collect_fred_macro
# ---------------------------------------------------------------------------


class TestCollectFredMacro:
    async def test_no_api_key(self):
        """Returns empty list when FRED_API_KEY is not set."""
        with patch.dict("os.environ", {}, clear=True):
            result = await collect_fred_macro()
        assert result == []

    async def test_collect_success(self):
        """Mock FRED API returns 3 data points for 3 series."""
        responses = [
            _mock_fred_response("DGS10", "4.25", "2026-03-28"),
            _mock_fred_response("CPIAUCSL", "315.2", "2026-02-01"),
            _mock_fred_response("WALCL", "7234000", "2026-03-26"),
        ]
        mock_client = _mock_httpx_client(responses)

        with (
            patch.dict("os.environ", {"FRED_API_KEY": "test_key"}),
            patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await collect_fred_macro()

        assert len(result) == 3
        assert result[0].series_id == "DGS10"
        assert result[0].value == 4.25
        assert result[0].date == "2026-03-28"
        assert result[0].unit == "percent"

        assert result[1].series_id == "CPIAUCSL"
        assert result[1].value == 315.2
        assert result[1].unit == "index"

        assert result[2].series_id == "WALCL"
        assert result[2].value == 7234000.0
        assert result[2].unit == "billions"

    async def test_api_error_graceful(self):
        """Returns empty list when API raises an exception."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("API down"))

        with (
            patch.dict("os.environ", {"FRED_API_KEY": "test_key"}),
            patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await collect_fred_macro()

        assert result == []

    async def test_missing_observation_value(self):
        """FRED returns '.' for missing data — should be skipped."""
        responses = [
            _mock_fred_response("DGS10", ".", "2026-03-28"),  # missing
            _mock_fred_response("CPIAUCSL", "315.2", "2026-02-01"),
            {"observations": []},  # empty
        ]
        mock_client = _mock_httpx_client(responses)

        with (
            patch.dict("os.environ", {"FRED_API_KEY": "test_key"}),
            patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await collect_fred_macro()

        # Only CPI should succeed (DGS10 has ".", WALCL has no observations)
        assert len(result) == 1
        assert result[0].series_id == "CPIAUCSL"

    async def test_partial_series_failure(self):
        """If one series fails, others still collected."""
        good_resp = MagicMock()
        good_resp.json.return_value = _mock_fred_response("DGS10", "4.25", "2026-03-28")
        good_resp.raise_for_status = MagicMock()

        bad_resp = MagicMock()
        bad_resp.raise_for_status.side_effect = Exception("500 error")

        good_resp2 = MagicMock()
        good_resp2.json.return_value = _mock_fred_response("WALCL", "7000000", "2026-03-26")
        good_resp2.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[good_resp, bad_resp, good_resp2])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.dict("os.environ", {"FRED_API_KEY": "test_key"}),
            patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await collect_fred_macro()

        assert len(result) == 2
        assert result[0].series_id == "DGS10"
        assert result[1].series_id == "WALCL"


# ---------------------------------------------------------------------------
# Tests: format_fred_for_llm
# ---------------------------------------------------------------------------


class TestFormatFredForLLM:
    def test_format_with_data(self):
        """Format includes all 3 series with correct formatting."""
        data = [
            FREDDataPoint("DGS10", "10Y Treasury Yield", 4.25, "2026-03-28", "percent"),
            FREDDataPoint("CPIAUCSL", "CPI (Consumer Price Index)", 315.2, "2026-02-01", "index"),
            FREDDataPoint("WALCL", "Fed Balance Sheet", 7234, "2026-03-26", "billions"),
        ]
        text = format_fred_for_llm(data)

        assert "DU LIEU KINH TE VI MO (FRED)" in text
        assert "4.25%" in text
        assert "315.2" in text
        assert "$7,234B" in text

    def test_format_empty(self):
        """Returns empty string for empty data."""
        assert format_fred_for_llm([]) == ""
