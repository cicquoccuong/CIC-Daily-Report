"""Tests for collectors/cryptopanic_client.py — all mocked."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from cic_daily_report.collectors.cryptopanic_client import (
    CryptoPanicArticle,
    _calc_panic_score,
    collect_cryptopanic,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestCalcPanicScore:
    def test_neutral_when_no_votes(self):
        assert _calc_panic_score({}) == 50.0

    def test_bullish(self):
        score = _calc_panic_score({"positive": 80, "negative": 20})
        assert score == 80.0

    def test_bearish(self):
        score = _calc_panic_score({"positive": 10, "negative": 90})
        assert score == 10.0


class TestCryptoPanicArticle:
    def test_to_row(self):
        article = CryptoPanicArticle(
            title="Test",
            url="https://example.com",
            source_name="CoinDesk",
            published_date="2026-03-09",
            summary="Summary",
            full_text="Full text here",
            panic_score=75.0,
            votes_bullish=75,
            votes_bearish=25,
        )
        row = article.to_row()
        assert len(row) == 11
        assert "CryptoPanic:CoinDesk" in row[3]

    def test_to_row_stores_currencies(self):
        """v0.28.0: currencies from API should be stored, not discarded."""
        article = CryptoPanicArticle(
            title="BTC ETF",
            url="https://example.com",
            source_name="S",
            published_date="2026-03-09",
            summary="S",
            full_text="F",
            panic_score=50.0,
            votes_bullish=50,
            votes_bearish=50,
            currencies=["BTC", "ETH"],
        )
        row = article.to_row()
        assert row[8] == "BTC,ETH"  # coin_symbol column

    def test_to_row_empty_currencies(self):
        """No currencies → empty string (not 'None')."""
        article = CryptoPanicArticle(
            title="T",
            url="u",
            source_name="S",
            published_date="d",
            summary="S",
            full_text="F",
            panic_score=50.0,
            votes_bullish=0,
            votes_bearish=0,
        )
        row = article.to_row()
        assert row[8] == ""


class TestCollectCryptopanic:
    async def test_skips_when_no_api_key(self):
        with patch.dict("os.environ", {}, clear=True):
            result = await collect_cryptopanic(api_key="")
        assert result == []

    async def test_collect_with_mock_api(self):
        fixture = json.loads((FIXTURES / "cryptopanic_response.json").read_text())

        with patch("cic_daily_report.collectors.cryptopanic_client.httpx.AsyncClient") as mock_http:
            mock_response = MagicMock()
            mock_response.json.return_value = fixture
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_http.return_value = mock_client

            articles = await collect_cryptopanic(api_key="test_key", extract_fulltext=False)

        assert len(articles) == 2
        assert articles[0].title == "SEC approves Bitcoin ETF"
        assert articles[0].panic_score == 80.0
