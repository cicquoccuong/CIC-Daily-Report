"""Tests for collectors/prediction_markets.py — all mocked (P1.4)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from cic_daily_report.collectors.prediction_markets import (
    MAX_MARKETS_PER_ASSET,
    PredictionMarket,
    PredictionMarketsData,
    _cap_per_asset,
    _detect_asset,
    _format_volume,
    _parse_and_filter,
    _parse_outcome_prices,
    collect_prediction_markets,
)

# --- Fixtures ---

MODULE = "cic_daily_report.collectors.prediction_markets"


def _make_raw_market(
    question: str = "Will Bitcoin exceed $100K by April 2026?",
    outcome_prices: str = "[0.72, 0.28]",
    volume: str = "50000",
    liquidity: str = "25000",
    slug: str = "btc-100k-april-2026",
    active: bool = True,
    closed: bool = False,
    end_date: str = "2026-04-30T00:00:00Z",
) -> dict:
    """Build a raw Gamma API market dict for testing."""
    return {
        "question": question,
        "outcomePrices": outcome_prices,
        "volume": volume,
        "liquidity": liquidity,
        "slug": slug,
        "active": active,
        "closed": closed,
        "endDate": end_date,
    }


def _make_prediction_market(**overrides) -> PredictionMarket:
    """Build a PredictionMarket with sensible defaults."""
    defaults = {
        "question": "Will Bitcoin exceed $100K by April 2026?",
        "outcome_yes": 0.72,
        "outcome_no": 0.28,
        "volume": 50000.0,
        "liquidity": 25000.0,
        "end_date": "2026-04-30T00:00:00Z",
        "url": "https://polymarket.com/event/btc-100k-april-2026",
        "asset": "BTC",
    }
    defaults.update(overrides)
    return PredictionMarket(**defaults)


def _mock_httpx_client(response_data: list[dict]):
    """Create a mock httpx.AsyncClient that returns response_data."""
    mock_response = MagicMock()
    mock_response.json.return_value = response_data
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


# --- Tests: collect_prediction_markets (integration) ---


class TestCollectPredictionMarkets:
    async def test_collect_success(self):
        """Mock API returns valid BTC + ETH markets in a single call."""
        btc_market = _make_raw_market(
            question="Will Bitcoin exceed $100K by April 2026?",
            volume="500000",
            slug="btc-100k",
        )
        eth_market = _make_raw_market(
            question="Will Ethereum reach $5K by June 2026?",
            outcome_prices="[0.45, 0.55]",
            volume="200000",
            slug="eth-5k",
        )

        # WHY: single _fetch_markets() call — API ignores keyword param
        mock_client = _mock_httpx_client([btc_market, eth_market])

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_prediction_markets()

        assert len(result.markets) == 2
        assert result.source == "polymarket"
        assert result.fetch_timestamp != ""

        # Sorted by volume desc
        assert result.markets[0].volume == 500000.0
        assert result.markets[0].asset == "BTC"
        assert result.markets[1].volume == 200000.0
        assert result.markets[1].asset == "ETH"

    async def test_collect_filters_inactive_markets(self):
        """Inactive/closed markets are excluded."""
        active = _make_raw_market(question="BTC above 90K?", volume="100000")
        inactive = _make_raw_market(question="BTC above 80K?", volume="100000", active=False)
        closed = _make_raw_market(question="BTC above 70K?", volume="100000", closed=True)

        mock_client = _mock_httpx_client([active, inactive, closed])
        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_prediction_markets()

        # Only the active, non-closed market should survive
        assert len(result.markets) == 1
        assert result.markets[0].question == "BTC above 90K?"

    async def test_collect_filters_low_volume(self):
        """Markets with volume < $10K are excluded."""
        high_vol = _make_raw_market(question="BTC above 100K?", volume="50000")
        low_vol = _make_raw_market(question="BTC above 50K?", volume="5000")

        mock_client = _mock_httpx_client([high_vol, low_vol])
        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_prediction_markets()

        assert len(result.markets) == 1
        assert result.markets[0].volume == 50000.0

    async def test_api_failure_graceful(self):
        """API error returns empty PredictionMarketsData."""
        import httpx as real_httpx

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=real_httpx.HTTPStatusError(
                "500 Server Error",
                request=MagicMock(),
                response=MagicMock(status_code=500),
            )
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_prediction_markets()

        assert result.markets == []
        assert result.fetch_timestamp != ""

    async def test_api_timeout_graceful(self):
        """Timeout returns empty PredictionMarketsData."""
        import httpx as real_httpx

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=real_httpx.TimeoutException("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_prediction_markets()

        assert result.markets == []
        assert result.fetch_timestamp != ""

    async def test_dedup_markets(self):
        """Same question from different searches produces only 1 entry."""
        # WHY: "bitcoin" search and "ethereum" search may both return
        # a market like "Will Bitcoin or Ethereum lead?" — we deduplicate by question
        shared_question = "Will Bitcoin exceed $100K?"
        market = _make_raw_market(question=shared_question, volume="100000")

        # Both searches return the same market
        mock_client = _mock_httpx_client([market, market])
        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_prediction_markets()

        assert len(result.markets) == 1


# --- Tests: Asset detection ---


class TestAssetDetection:
    def test_detect_btc_from_bitcoin(self):
        assert _detect_asset("Will Bitcoin exceed $100K?") == "BTC"

    def test_detect_btc_from_btc(self):
        assert _detect_asset("BTC price above 90K?") == "BTC"

    def test_detect_btc_case_insensitive(self):
        assert _detect_asset("BITCOIN rally continues") == "BTC"

    def test_detect_eth_from_ethereum(self):
        assert _detect_asset("Will Ethereum reach $5K?") == "ETH"

    def test_detect_eth_from_eth(self):
        assert _detect_asset("ETH staking rewards increase?") == "ETH"

    def test_detect_generic_no_keyword(self):
        assert _detect_asset("Will crypto market cap reach $5T?") == "CRYPTO"

    def test_detect_btc_takes_priority_over_eth(self):
        """If both keywords present, BTC wins (checked first)."""
        assert _detect_asset("Bitcoin vs Ethereum: which wins?") == "BTC"


# --- Tests: Outcome prices parsing ---


class TestOutcomePricesParsing:
    def test_valid_prices(self):
        result = _parse_outcome_prices("[0.72, 0.28]")
        assert result == (0.72, 0.28)

    def test_prices_exact_bounds(self):
        result = _parse_outcome_prices("[0.0, 1.0]")
        assert result == (0.0, 1.0)

    def test_empty_string(self):
        assert _parse_outcome_prices("") is None

    def test_invalid_json(self):
        assert _parse_outcome_prices("not json") is None

    def test_missing_second_element(self):
        assert _parse_outcome_prices("[0.72]") is None

    def test_out_of_range_high(self):
        assert _parse_outcome_prices("[1.5, 0.3]") is None

    def test_out_of_range_negative(self):
        assert _parse_outcome_prices("[-0.1, 0.3]") is None

    def test_non_list_json(self):
        assert _parse_outcome_prices('{"yes": 0.72}') is None


# --- Tests: format_for_llm ---


class TestFormatForLLM:
    def test_format_with_markets(self):
        data = PredictionMarketsData(
            markets=[
                _make_prediction_market(
                    question="Will Bitcoin exceed $100K?",
                    outcome_yes=0.72,
                    volume=5_200_000,
                    asset="BTC",
                ),
                _make_prediction_market(
                    question="Will Ethereum reach $5K?",
                    outcome_yes=0.45,
                    volume=200_000,
                    asset="ETH",
                ),
            ],
            fetch_timestamp="2026-03-28T08:00:00Z",
        )
        text = data.format_for_llm()

        assert "=== Polymarket Prediction Markets ===" in text
        assert "[BTC]" in text
        assert "[ETH]" in text
        assert "YES 72%" in text
        assert "Vol: $5.2M" in text
        assert "YES 45%" in text

    def test_format_empty_markets(self):
        data = PredictionMarketsData(markets=[], fetch_timestamp="2026-03-28T08:00:00Z")
        assert data.format_for_llm() == ""


# --- Tests: format_for_consensus ---


class TestFormatForConsensus:
    def test_consensus_with_mixed_assets(self):
        data = PredictionMarketsData(
            markets=[
                _make_prediction_market(question="BTC > $100K?", outcome_yes=0.7, asset="BTC"),
                _make_prediction_market(question="BTC > $120K?", outcome_yes=0.3, asset="BTC"),
                _make_prediction_market(question="ETH > $5K?", outcome_yes=0.5, asset="ETH"),
            ],
            fetch_timestamp="2026-03-28T08:00:00Z",
        )
        result = data.format_for_consensus()

        # BTC avg: (0.7 + 0.3) / 2 = 0.5 → 50%
        assert result["btc_bullish_pct"] == 50.0
        # ETH avg: 0.5 → 50%
        assert result["eth_bullish_pct"] == 50.0
        assert len(result["key_markets"]) == 3

    def test_consensus_empty_markets(self):
        data = PredictionMarketsData(markets=[], fetch_timestamp="2026-03-28T08:00:00Z")
        result = data.format_for_consensus()

        assert result["btc_bullish_pct"] == 0.0
        assert result["eth_bullish_pct"] == 0.0
        assert result["key_markets"] == []

    def test_consensus_key_markets_format(self):
        data = PredictionMarketsData(
            markets=[
                _make_prediction_market(
                    question="BTC > $100K?",
                    outcome_yes=0.72,
                    volume=50000.0,
                    asset="BTC",
                ),
            ],
            fetch_timestamp="2026-03-28T08:00:00Z",
        )
        result = data.format_for_consensus()
        km = result["key_markets"][0]

        assert km["question"] == "BTC > $100K?"
        assert km["yes_pct"] == 72.0
        assert km["volume"] == 50000.0
        assert km["asset"] == "BTC"


# --- Tests: URL construction ---


class TestURLConstruction:
    def test_slug_to_url(self):
        raw = [_make_raw_market(slug="btc-100k-april-2026", volume="50000")]
        result = _parse_and_filter(raw)
        assert len(result) == 1
        assert result[0].url == "https://polymarket.com/event/btc-100k-april-2026"


# --- Tests: _cap_per_asset ---


class TestCapPerAsset:
    def test_caps_at_max(self):
        """More than MAX_MARKETS_PER_ASSET for one asset gets capped."""
        markets = [
            _make_prediction_market(
                question=f"BTC question {i}",
                volume=float(100000 - i * 1000),
                asset="BTC",
            )
            for i in range(15)
        ]
        result = _cap_per_asset(markets)
        assert len(result) == MAX_MARKETS_PER_ASSET

    def test_different_assets_not_affected(self):
        """Each asset gets its own cap."""
        btc = [_make_prediction_market(question=f"BTC q{i}", asset="BTC") for i in range(5)]
        eth = [_make_prediction_market(question=f"ETH q{i}", asset="ETH") for i in range(5)]
        result = _cap_per_asset(btc + eth)
        assert len(result) == 10


# --- Tests: _format_volume ---


class TestFormatVolume:
    def test_millions(self):
        assert _format_volume(5_200_000) == "$5.2M"

    def test_thousands(self):
        assert _format_volume(120_000) == "$120K"

    def test_small_amount(self):
        assert _format_volume(999) == "$999"

    def test_exact_million(self):
        assert _format_volume(1_000_000) == "$1.0M"


# --- Tests: _parse_and_filter edge cases ---


class TestParseAndFilter:
    def test_missing_volume_defaults_zero(self):
        """Market with missing volume field is filtered out (< MIN_VOLUME)."""
        raw = [_make_raw_market(volume="")]
        result = _parse_and_filter(raw)
        assert len(result) == 0

    def test_malformed_outcome_prices_skipped(self):
        """Market with bad outcomePrices is skipped entirely."""
        raw = [_make_raw_market(outcome_prices="not-json", volume="50000")]
        result = _parse_and_filter(raw)
        assert len(result) == 0

    def test_none_volume_defaults_zero(self):
        """Market with None volume is filtered out."""
        raw_market = _make_raw_market(volume="50000")
        raw_market["volume"] = None
        result = _parse_and_filter([raw_market])
        assert len(result) == 0


# --- Tests: BUG-01 fixes (v2.0 Wave 0+1) ---


class TestBug01NoSlugContains:
    """BUG-01: slug_contains is silently ignored by Gamma API."""

    async def test_no_slug_contains_in_params(self):
        """_fetch_markets must NOT include slug_contains in API params."""
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        from cic_daily_report.collectors.prediction_markets import _fetch_markets

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            await _fetch_markets()

        # Inspect the params sent to httpx.get()
        call_args = mock_client.get.call_args
        params = call_args.kwargs.get("params") or (call_args[1] if len(call_args) > 1 else {})
        assert "slug_contains" not in params

    async def test_params_include_volume_ordering(self):
        """_fetch_markets should order by volume descending."""
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        from cic_daily_report.collectors.prediction_markets import _fetch_markets

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            await _fetch_markets()

        call_args = mock_client.get.call_args
        params = call_args.kwargs.get("params") or (call_args[1] if len(call_args) > 1 else {})
        assert params.get("order") == "volume"
        assert params.get("ascending") == "false"
        assert params.get("limit") == "100"


class TestBug01WordBoundary:
    """BUG-01: Word boundary matching for short keywords like 'eth'."""

    def test_method_does_not_match_eth(self):
        """'method' should NOT trigger ETH detection."""
        assert _detect_asset("Will the new method work?") == "CRYPTO"

    def test_whether_does_not_match_eth(self):
        """'whether' should NOT trigger ETH detection."""
        assert _detect_asset("Whether prices rise or fall") == "CRYPTO"

    def test_eth_price_matches_eth(self):
        """'eth price' should match ETH."""
        assert _detect_asset("Will ETH price reach $5K?") == "ETH"

    def test_eth_standalone_matches(self):
        """Standalone 'eth' should match."""
        assert _detect_asset("eth staking rewards") == "ETH"

    def test_ethereum_still_matches_eth(self):
        """Longer keyword 'ethereum' still works."""
        assert _detect_asset("Ethereum merge update") == "ETH"

    def test_btc_word_boundary(self):
        """'btc' as standalone word matches BTC."""
        assert _detect_asset("BTC dominance increasing") == "BTC"

    def test_bitcoin_still_matches(self):
        """Longer keyword 'bitcoin' still works."""
        assert _detect_asset("Bitcoin halving 2028") == "BTC"


# --- Tests: Single API call (v2.0 — duplicate fetch fix) ---


class TestSingleApiCall:
    """_fetch_markets takes no keyword param — single call replaces duplicate gather."""

    async def test_fetch_markets_no_keyword_param(self):
        """_fetch_markets() accepts no arguments."""
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        from cic_daily_report.collectors.prediction_markets import _fetch_markets

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await _fetch_markets()

        assert result == []
        # Only 1 HTTP call, not 2
        assert mock_client.get.call_count == 1

    async def test_collect_makes_single_http_call(self):
        """collect_prediction_markets makes exactly 1 HTTP call (not 2)."""
        btc_market = _make_raw_market(question="Will Bitcoin exceed $100K?", volume="100000")
        mock_client = _mock_httpx_client([btc_market])

        with patch(f"{MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await collect_prediction_markets()

        assert len(result.markets) == 1
        # WHY: single _fetch_markets() call — only 1 httpx.get()
        assert mock_client.get.call_count == 1
