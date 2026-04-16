"""Tests for collectors/token_unlock_collector.py — all mocked (QO.46)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from cic_daily_report.collectors.token_unlock_collector import (
    MIN_SUPPLY_PCT,
    MIN_VALUE_USD,
    TokenUnlock,
    _is_significant,
    _is_within_horizon,
    _timestamp_to_iso,
    collect_token_unlocks,
)

MODULE = "cic_daily_report.collectors.token_unlock_collector"


def _future_ts(days_ahead: int = 3) -> int:
    """Return a Unix timestamp N days from now."""
    dt = datetime.now(timezone.utc) + timedelta(days=days_ahead)
    return int(dt.timestamp())


def _past_ts(days_ago: int = 3) -> int:
    """Return a Unix timestamp N days ago."""
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return int(dt.timestamp())


def _make_protocol(
    name: str = "TestToken",
    price: float = 10.0,
    max_supply: float = 1_000_000,
    events: list[dict] | None = None,
) -> dict:
    """Build a mock DeFiLlama unlock protocol dict."""
    if events is None:
        events = [{"timestamp": _future_ts(3), "noOfTokens": [200_000]}]
    return {
        "name": name,
        "price": price,
        "maxSupply": max_supply,
        "events": events,
    }


def _mock_httpx_client(response_data):
    """Create a mock httpx.AsyncClient returning response_data as JSON."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = response_data
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


# --- Unit tests ---


class TestIsSignificant:
    def test_high_value(self):
        assert _is_significant(2_000_000, 0.5) is True

    def test_high_supply_pct(self):
        assert _is_significant(500_000, 2.0) is True

    def test_both_high(self):
        assert _is_significant(5_000_000, 5.0) is True

    def test_both_low(self):
        assert _is_significant(500_000, 0.5) is False

    def test_boundary_value(self):
        assert _is_significant(MIN_VALUE_USD, 0.0) is False  # not > MIN
        assert _is_significant(MIN_VALUE_USD + 1, 0.0) is True

    def test_boundary_supply(self):
        assert _is_significant(0, MIN_SUPPLY_PCT) is False  # not > MIN
        assert _is_significant(0, MIN_SUPPLY_PCT + 0.1) is True


class TestIsWithinHorizon:
    def test_future_within(self):
        ts = _future_ts(3)
        assert _is_within_horizon(ts, 7) is True

    def test_future_beyond(self):
        ts = _future_ts(10)
        assert _is_within_horizon(ts, 7) is False

    def test_past_ts(self):
        ts = _past_ts(2)
        assert _is_within_horizon(ts, 7) is False

    def test_empty_string(self):
        assert _is_within_horizon("", 7) is False

    def test_iso_string_within(self):
        future = datetime.now(timezone.utc) + timedelta(days=3)
        iso = future.strftime("%Y-%m-%dT%H:%M:%SZ")
        assert _is_within_horizon(iso, 7) is True


class TestTimestampToIso:
    def test_unix_timestamp(self):
        ts = 1745193600  # some future timestamp
        result = _timestamp_to_iso(ts)
        assert result.endswith("Z")
        assert "T" in result

    def test_string_passthrough(self):
        assert _timestamp_to_iso("2026-04-20") == "2026-04-20"

    def test_invalid_returns_str(self):
        assert _timestamp_to_iso("invalid") == "invalid"


class TestTokenUnlock:
    def test_to_dict(self):
        u = TokenUnlock(
            token_name="ARB",
            unlock_date="2026-04-20T00:00:00Z",
            amount=50_000_000,
            percentage_of_supply=5.0,
            value_usd=50_000_000,
        )
        d = u.to_dict()
        assert d["token_name"] == "ARB"
        assert d["value_usd"] == 50_000_000
        assert d["source"] == "DeFiLlama"


# --- Integration tests (mocked HTTP) ---


class TestCollectTokenUnlocks:
    async def test_successful_fetch(self):
        """DeFiLlama returns protocols with significant upcoming unlocks."""
        protocol = _make_protocol(
            name="Arbitrum",
            price=1.5,
            max_supply=10_000_000_000,
            events=[{"timestamp": _future_ts(3), "noOfTokens": [1_000_000]}],
        )
        # 1M tokens * $1.5 = $1.5M > $1M threshold
        mock_client = _mock_httpx_client([protocol])

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_token_unlocks()

        assert len(result) == 1
        assert result[0]["token_name"] == "Arbitrum"
        assert result[0]["value_usd"] == 1_500_000.0
        assert result[0]["source"] == "DeFiLlama"

    async def test_filters_insignificant_unlocks(self):
        """Small unlocks (< $1M and < 1% supply) are excluded."""
        protocol = _make_protocol(
            name="SmallToken",
            price=0.001,
            max_supply=100_000_000_000,
            events=[{"timestamp": _future_ts(3), "noOfTokens": [100]}],
        )
        # 100 * $0.001 = $0.1 — not significant
        mock_client = _mock_httpx_client([protocol])

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_token_unlocks()

        assert len(result) == 0

    async def test_filters_past_events(self):
        """Events in the past are excluded."""
        protocol = _make_protocol(
            name="PastToken",
            price=10.0,
            max_supply=1_000_000,
            events=[{"timestamp": _past_ts(5), "noOfTokens": [200_000]}],
        )
        mock_client = _mock_httpx_client([protocol])

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_token_unlocks()

        assert len(result) == 0

    async def test_filters_beyond_horizon(self):
        """Events beyond 7-day horizon are excluded."""
        protocol = _make_protocol(
            name="FarToken",
            price=10.0,
            max_supply=1_000_000,
            events=[{"timestamp": _future_ts(14), "noOfTokens": [200_000]}],
        )
        mock_client = _mock_httpx_client([protocol])

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_token_unlocks()

        assert len(result) == 0

    async def test_significant_by_supply_pct(self):
        """Unlock significant by supply % (> 1%) even if value < $1M."""
        protocol = _make_protocol(
            name="HighPctToken",
            price=0.01,  # cheap token
            max_supply=1_000_000,
            events=[{"timestamp": _future_ts(3), "noOfTokens": [20_000]}],
        )
        # 20K/1M = 2% supply > 1% threshold. Value = $200 < $1M.
        mock_client = _mock_httpx_client([protocol])

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_token_unlocks()

        assert len(result) == 1
        assert result[0]["percentage_of_supply"] == 2.0

    async def test_sorted_by_value_descending(self):
        """Results sorted by USD value, highest first."""
        protocols = [
            _make_protocol(
                name="Small",
                price=1.0,
                max_supply=100_000_000,
                events=[{"timestamp": _future_ts(3), "noOfTokens": [2_000_000]}],
            ),
            _make_protocol(
                name="Large",
                price=5.0,
                max_supply=100_000_000,
                events=[{"timestamp": _future_ts(3), "noOfTokens": [10_000_000]}],
            ),
        ]
        mock_client = _mock_httpx_client(protocols)

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_token_unlocks()

        assert len(result) == 2
        assert result[0]["token_name"] == "Large"  # $50M
        assert result[1]["token_name"] == "Small"  # $2M

    async def test_timeout_returns_empty(self):
        """Timeout returns empty list."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_token_unlocks()

        assert result == []

    async def test_http_error_returns_empty(self):
        """HTTP error returns empty list."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock(status_code=500)
        )
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_token_unlocks()

        assert result == []

    async def test_generic_exception_returns_empty(self):
        """Any unexpected exception returns empty list."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Boom"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_token_unlocks()

        assert result == []

    async def test_unexpected_format_returns_empty(self):
        """Non-list response returns empty list."""
        mock_client = _mock_httpx_client({"not": "a list"})

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_token_unlocks()

        assert result == []

    async def test_no_events_key(self):
        """Protocol without events key is skipped gracefully."""
        protocol = {"name": "NoEvents", "price": 1.0, "maxSupply": 1000000}
        mock_client = _mock_httpx_client([protocol])

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_token_unlocks()

        assert result == []

    async def test_no_of_tokens_as_scalar(self):
        """noOfTokens can be a scalar (not wrapped in list)."""
        protocol = _make_protocol(
            name="ScalarToken",
            price=10.0,
            max_supply=1_000_000,
            events=[{"timestamp": _future_ts(3), "noOfTokens": 200_000}],
        )
        mock_client = _mock_httpx_client([protocol])

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_token_unlocks()

        assert len(result) == 1
        assert result[0]["value_usd"] == 2_000_000.0
