"""Tests for collectors/mempool_data.py — all mocked (P1.20)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cic_daily_report.collectors.mempool_data import (
    MempoolData,
    collect_mempool_data,
    format_mempool_for_llm,
)

MODULE = "cic_daily_report.collectors.mempool_data"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_hashrate_response() -> dict:
    """Build mock /mining/hashrate/3d response (Wave 0.7.1: switched from /1w)."""
    return {
        "currentHashrate": 650e18,  # 650 EH/s in H/s
        "currentDifficulty": 80e12,
        "hashrates": [
            {"avgHashrate": 630e18, "timestamp": 1000},
            {"avgHashrate": 640e18, "timestamp": 2000},
            {"avgHashrate": 650e18, "timestamp": 3000},
        ],
    }


def _make_fees_response() -> dict:
    """Build mock /fees/recommended response."""
    return {
        "fastestFee": 25,
        "halfHourFee": 15,
        "hourFee": 8,
        "economyFee": 5,
        "minimumFee": 1,
    }


def _make_difficulty_response() -> dict:
    """Build mock /difficulty-adjustment response."""
    return {
        "progressPercent": 60.5,
        "difficultyChange": 3.14,
        "estimatedRetargetDate": 1711843200,
        "remainingBlocks": 1200,
        "remainingTime": 432000,  # ~5 days in seconds
        "previousRetarget": 2.1,
    }


def _mock_httpx_client(hashrate=None, fees=None, difficulty=None, raise_on=None):
    """Create a mock httpx.AsyncClient for 3 Mempool endpoints.

    Args:
        hashrate: Response for /mining/hashrate/3d
        fees: Response for /fees/recommended
        difficulty: Response for /difficulty-adjustment
        raise_on: If set, endpoint name ("hashrate", "fees", "difficulty")
                  that should raise an exception.
    """
    if hashrate is None:
        hashrate = _make_hashrate_response()
    if fees is None:
        fees = _make_fees_response()
    if difficulty is None:
        difficulty = _make_difficulty_response()

    url_responses = {
        "/mining/hashrate/3d": hashrate,
        "/fees/recommended": fees,
        "/difficulty-adjustment": difficulty,
    }
    url_raises = {}
    if raise_on == "hashrate":
        url_raises["/mining/hashrate/3d"] = Exception("hashrate error")
    elif raise_on == "fees":
        url_raises["/fees/recommended"] = Exception("fees error")
    elif raise_on == "difficulty":
        url_raises["/difficulty-adjustment"] = Exception("difficulty error")

    async def mock_get(url: str):
        # Match by URL suffix
        for path, resp_data in url_responses.items():
            if url.endswith(path):
                if path in url_raises:
                    raise url_raises[path]
                mock_resp = MagicMock()
                mock_resp.json.return_value = resp_data
                mock_resp.raise_for_status = MagicMock()
                return mock_resp
        raise Exception(f"Unexpected URL: {url}")

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=mock_get)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


# ---------------------------------------------------------------------------
# Tests: collect_mempool_data
# ---------------------------------------------------------------------------


class TestCollectMempoolData:
    async def test_collect_success(self):
        """Mock all 3 endpoints, get valid MempoolData."""
        mock_client = _mock_httpx_client()
        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_mempool_data()

        assert result is not None
        assert result.hashrate_eh == pytest.approx(650.0, rel=0.01)
        # 7d change: (650e18 - 630e18) / 630e18 * 100 ≈ 3.17%
        assert result.hashrate_change_7d == pytest.approx(3.17, rel=0.1)
        assert result.fee_fast == 25
        assert result.fee_medium == 15
        assert result.fee_slow == 8
        assert result.difficulty_change == pytest.approx(3.14, rel=0.01)
        assert result.difficulty_remaining_blocks == 1200
        assert result.difficulty_remaining_time == 432000

    async def test_api_error_returns_none(self):
        """API error returns None gracefully."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("Network error"))

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_mempool_data()

        assert result is None

    async def test_hashrate_endpoint_fails(self):
        """If hashrate endpoint fails, returns None (all 3 required)."""
        mock_client = _mock_httpx_client(raise_on="hashrate")
        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_mempool_data()

        assert result is None

    async def test_fees_endpoint_fails(self):
        """If fees endpoint fails, returns None."""
        mock_client = _mock_httpx_client(raise_on="fees")
        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_mempool_data()

        assert result is None

    async def test_difficulty_endpoint_fails(self):
        """If difficulty endpoint fails, returns None."""
        mock_client = _mock_httpx_client(raise_on="difficulty")
        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_mempool_data()

        assert result is None

    async def test_hashrate_no_history(self):
        """Hashrate with no history entries → change_7d = 0."""
        mock_client = _mock_httpx_client(hashrate={"currentHashrate": 650e18, "hashrates": []})
        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_mempool_data()

        assert result is not None
        assert result.hashrate_change_7d == 0.0


# ---------------------------------------------------------------------------
# Tests: format_mempool_for_llm
# ---------------------------------------------------------------------------


class TestFormatMempoolForLLM:
    def test_format_with_data(self):
        """Format includes hashrate, fees, and difficulty."""
        data = MempoolData(
            hashrate_eh=650.0,
            hashrate_change_7d=2.3,
            fee_fast=25,
            fee_medium=15,
            fee_slow=8,
            difficulty_change=3.1,
            difficulty_remaining_blocks=1200,
            difficulty_remaining_time=432000,
        )
        text = format_mempool_for_llm(data)

        assert "BTC NETWORK (Mempool.space)" in text
        assert "650 EH/s" in text
        assert "+2.3% 7d" in text
        assert "Fast 25 sat/vB" in text
        assert "Medium 15" in text
        assert "Slow 8" in text
        assert "+3.1% adjustment" in text
        assert "1200 blocks" in text

    def test_format_none(self):
        """Returns empty string for None data."""
        assert format_mempool_for_llm(None) == ""
