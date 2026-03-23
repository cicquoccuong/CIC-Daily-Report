"""Shared test fixtures for CIC Daily Report."""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _no_production_cooldown():
    """Disable inter-tier cooldown so tests never sleep in CI.

    article_generator uses adaptive cooldown (llm.suggest_cooldown()) only
    when _IS_PRODUCTION is True. Force it to False so tests skip all sleeps.
    """
    with patch("cic_daily_report.generators.article_generator._IS_PRODUCTION", False):
        yield


@pytest.fixture
def mock_llm_response():
    """Create a mock LLM response."""
    from cic_daily_report.adapters.llm_adapter import LLMResponse

    return LLMResponse(text="Test generated content", tokens_used=100, model="mock")


@pytest.fixture
def sample_news_articles():
    """Sample news articles for testing pipeline processing."""
    return [
        {
            "title": "BTC hits $100K",
            "summary": "Bitcoin reached a milestone",
            "source": "CoinDesk",
            "url": "https://example.com/1",
            "filtered": False,
        },
        {
            "title": "SPAM article",
            "summary": "",
            "source": "Unknown",
            "url": "https://example.com/2",
            "filtered": True,
        },
        {
            "title": "ETH update",
            "summary": "Ethereum protocol upgrade",
            "source": "CoinTelegraph",
            "url": "https://example.com/3",
            "filtered": False,
        },
    ]


@pytest.fixture
def sample_market_data():
    """Sample market data points for testing."""
    from cic_daily_report.collectors.market_data import MarketDataPoint

    return [
        MarketDataPoint(
            symbol="BTC",
            price=100000,
            change_24h=2.5,
            volume_24h=50000000000,
            market_cap=1950000000000,
            data_type="crypto",
            source="CoinGecko",
        ),
        MarketDataPoint(
            symbol="ETH",
            price=3500,
            change_24h=-1.2,
            volume_24h=20000000000,
            market_cap=420000000000,
            data_type="crypto",
            source="CoinGecko",
        ),
        MarketDataPoint(
            symbol="Fear_Greed",
            price=75,
            change_24h=0,
            volume_24h=0,
            market_cap=0,
            data_type="index",
            source="Alternative.me",
        ),
    ]
