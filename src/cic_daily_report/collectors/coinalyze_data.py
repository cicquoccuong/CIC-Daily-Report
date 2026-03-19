"""Coinalyze Derivatives Data Collector (v0.24.0).

Derivatives data via Coinalyze API — replaces direct OKX/Binance/Bybit calls
as primary source for Funding Rate, OI, Liquidations, Long/Short Ratio.
Uses Binance USDT perpetuals (most liquid). No geo-blocking from GitHub Actions.

API: api.coinalyze.net/v1/ (free tier, 40 req/min)
Endpoints: /funding-rate, /open-interest (current snapshots)
           /liquidation-history, /long-short-ratio-history (daily history)
"""

from __future__ import annotations

import asyncio
import os

import httpx

from cic_daily_report.collectors.onchain_data import OnChainMetric
from cic_daily_report.core.logger import get_logger

logger = get_logger("coinalyze_data")

BASE_URL = "https://api.coinalyze.net/v1"
REQUEST_TIMEOUT = 15

# Coinalyze uses exchange-specific symbols: {BASE}{QUOTE}_{TYPE}.{EXCHANGE_CODE}
# Exchange codes come from /exchanges endpoint. Known: A = Binance.
# Using Binance USDT-margined perpetuals (most liquid market).
SYMBOLS = {
    "BTC": "BTCUSDT_PERP.A",
    "ETH": "ETHUSDT_PERP.A",
}


async def collect_coinalyze_derivatives() -> list[OnChainMetric]:
    """Collect derivatives metrics from Coinalyze for BTC and ETH.

    Returns OnChainMetric objects compatible with existing pipeline.
    Graceful degradation: returns empty list on failure.
    """
    api_key = os.getenv("COINALYZE_API_KEY", "")
    if not api_key:
        logger.warning("COINALYZE_API_KEY not set — skipping Coinalyze")
        return []

    symbols_str = ",".join(SYMBOLS.values())
    tasks = [
        _fetch_funding_rate(api_key, symbols_str),
        _fetch_open_interest(api_key, symbols_str),
        _fetch_liquidations(api_key, symbols_str),
        _fetch_long_short_ratio(api_key, symbols_str),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    metrics: list[OnChainMetric] = []
    endpoint_names = ["funding_rate", "open_interest", "liquidations", "long_short_ratio"]
    for name, result in zip(endpoint_names, results):
        if isinstance(result, Exception):
            logger.warning(f"Coinalyze {name}: {result}")
        else:
            metrics.extend(result)

    if metrics:
        logger.info(f"Coinalyze: {len(metrics)} derivatives metrics collected")
    else:
        logger.warning("Coinalyze: no metrics collected")
    return metrics


def _symbol_to_coin(symbol: str) -> str:
    """Map Coinalyze symbol back to coin name."""
    for coin, sym in SYMBOLS.items():
        if sym == symbol:
            return coin
    return symbol.split("USD")[0] if "USD" in symbol else symbol


async def _fetch_funding_rate(api_key: str, symbols: str) -> list[OnChainMetric]:
    """Fetch current funding rate for symbols."""
    metrics: list[OnChainMetric] = []
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(
                f"{BASE_URL}/funding-rate",
                params={"symbols": symbols, "api_key": api_key},
            )
            resp.raise_for_status()

        data = resp.json()
        if not isinstance(data, list):
            logger.warning(f"Coinalyze funding rate: unexpected response: {data}")
            return metrics

        for item in data:
            coin = _symbol_to_coin(item.get("symbol", ""))
            value = item.get("value", 0.0)
            if isinstance(value, (int, float)):
                metrics.append(
                    OnChainMetric(
                        metric_name=f"{coin}_Funding_Rate",
                        value=float(value),
                        source="Coinalyze",
                        note="Binance perpetual",
                    )
                )
    except Exception as e:
        logger.debug(f"Coinalyze funding rate: {e}")
    return metrics


async def _fetch_open_interest(api_key: str, symbols: str) -> list[OnChainMetric]:
    """Fetch current open interest for symbols."""
    metrics: list[OnChainMetric] = []
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(
                f"{BASE_URL}/open-interest",
                params={
                    "symbols": symbols,
                    "api_key": api_key,
                    "convert_to_usd": "true",
                },
            )
            resp.raise_for_status()

        data = resp.json()
        if not isinstance(data, list):
            logger.warning(f"Coinalyze open interest: unexpected response: {data}")
            return metrics

        for item in data:
            coin = _symbol_to_coin(item.get("symbol", ""))
            value = item.get("value", 0.0)
            if isinstance(value, (int, float)):
                metrics.append(
                    OnChainMetric(
                        metric_name=f"{coin}_Open_Interest",
                        value=float(value),
                        source="Coinalyze",
                        note="USD, Binance perpetual",
                    )
                )
    except Exception as e:
        logger.debug(f"Coinalyze open interest: {e}")
    return metrics


async def _fetch_liquidations(api_key: str, symbols: str) -> list[OnChainMetric]:
    """Fetch daily liquidation data for symbols.

    Response format: [{"symbol": "...", "history": [{"t": ts, "l": long_vol, "s": short_vol}]}]
    """
    metrics: list[OnChainMetric] = []
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(
                f"{BASE_URL}/liquidation-history",
                params={
                    "symbols": symbols,
                    "api_key": api_key,
                    "interval": "daily",
                    "convert_to_usd": "true",
                },
            )
            resp.raise_for_status()

        data = resp.json()
        if not isinstance(data, list):
            logger.warning(f"Coinalyze liquidations: unexpected response: {data}")
            return metrics

        for item in data:
            coin = _symbol_to_coin(item.get("symbol", ""))
            history = item.get("history", [])
            if not history:
                continue
            latest = history[-1]  # most recent entry (ascending order)
            long_liq = float(latest.get("l", 0))
            short_liq = float(latest.get("s", 0))
            total = long_liq + short_liq
            if total > 0:
                metrics.append(
                    OnChainMetric(
                        metric_name=f"{coin}_Liquidations_24h",
                        value=total,
                        source="Coinalyze",
                        note=f"long={long_liq:.0f} short={short_liq:.0f}",
                    )
                )
    except Exception as e:
        logger.debug(f"Coinalyze liquidations: {e}")
    return metrics


async def _fetch_long_short_ratio(api_key: str, symbols: str) -> list[OnChainMetric]:
    """Fetch long/short ratio for symbols.

    No current snapshot endpoint — must use history.
    Response: [{"symbol": "...", "history": [{"t": ts, "r": ratio, "l": %, "s": %}]}]
    """
    metrics: list[OnChainMetric] = []
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(
                f"{BASE_URL}/long-short-ratio-history",
                params={
                    "symbols": symbols,
                    "api_key": api_key,
                    "interval": "daily",
                },
            )
            resp.raise_for_status()

        data = resp.json()
        if not isinstance(data, list):
            logger.warning(f"Coinalyze long/short ratio: unexpected response: {data}")
            return metrics

        for item in data:
            coin = _symbol_to_coin(item.get("symbol", ""))
            history = item.get("history", [])
            if not history:
                continue
            latest = history[-1]  # most recent entry (ascending order)
            value = latest.get("r", 0.0)
            if isinstance(value, (int, float)) and value > 0:
                longs_pct = latest.get("l", 0)
                shorts_pct = latest.get("s", 0)
                metrics.append(
                    OnChainMetric(
                        metric_name=f"{coin}_Long_Short_Ratio",
                        value=float(value),
                        source="Coinalyze",
                        note=f"longs={longs_pct:.1f}% shorts={shorts_pct:.1f}%",
                    )
                )
    except Exception as e:
        logger.debug(f"Coinalyze long/short ratio: {e}")
    return metrics
