"""On-Chain & Derivatives Data Collector (FR4, FR5, FR9)."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from cic_daily_report.core.logger import get_logger

logger = get_logger("onchain_data")


@dataclass
class OnChainMetric:
    """Single on-chain or derivatives metric."""

    metric_name: str
    value: float
    source: str
    note: str = ""

    def to_row(self) -> list[str]:
        collected_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        return [
            "",  # ID
            collected_at,
            self.metric_name,
            str(self.value),
            self.source,
            self.note,
        ]


async def collect_onchain() -> list[OnChainMetric]:
    """Collect on-chain + derivatives + FRED macro data.

    v0.24.0: Coinalyze (primary derivatives) + CoinMetrics (primary on-chain),
    with Glassnode/OKX/Binance/Bybit as fallbacks.
    """
    logger.info("Collecting on-chain & derivatives data")

    # Phase 1: Collect from all sources in parallel
    tasks = [
        _collect_coinalyze_or_fallback(),
        _collect_coinmetrics_or_fallback(),
        _collect_fred(),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_metrics: list[OnChainMetric] = []
    source_names = ["Derivatives", "On-chain", "FRED"]
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning(f"{source_names[i]} failed: {result}")
        else:
            all_metrics.extend(result)

    logger.info(f"On-chain data collected: {len(all_metrics)} metrics")
    return all_metrics


async def _collect_coinalyze_or_fallback() -> list[OnChainMetric]:
    """Coinalyze → OKX → Binance → Bybit fallback chain for derivatives."""
    try:
        from cic_daily_report.collectors.coinalyze_data import (
            collect_coinalyze_derivatives,
        )

        metrics = await collect_coinalyze_derivatives()
        if metrics:
            return metrics
        logger.info("Coinalyze returned empty — falling back to exchange APIs")
    except Exception as e:
        logger.warning(f"Coinalyze failed: {e}")

    # Fallback to existing exchange API chain
    return await _collect_derivatives()


async def _collect_coinmetrics_or_fallback() -> list[OnChainMetric]:
    """CoinMetrics → Glassnode fallback chain for on-chain fundamentals."""
    try:
        from cic_daily_report.collectors.coinmetrics_data import (
            collect_coinmetrics_onchain,
        )

        metrics = await collect_coinmetrics_onchain()
        if metrics:
            return metrics
        logger.info("CoinMetrics returned empty — falling back to Glassnode")
    except Exception as e:
        logger.warning(f"CoinMetrics failed: {e}")

    # Fallback to existing Glassnode
    return await _collect_glassnode()


async def _collect_glassnode() -> list[OnChainMetric]:
    """Collect BTC on-chain from Glassnode free tier (FR4).

    Free endpoints: MVRV Z-Score, SOPR, Exchange Reserves.
    Note: Glassnode free API is limited. Falls back gracefully.
    """
    # Glassnode free API has very limited access
    # Using community endpoints where available
    metrics: list[OnChainMetric] = []

    endpoints = [
        ("https://api.glassnode.com/v1/metrics/market/mvrv_z_score", "MVRV_Z_Score"),
        ("https://api.glassnode.com/v1/metrics/indicators/sopr", "SOPR"),
        (
            "https://api.glassnode.com/v1/metrics/distribution/balance_exchanges",
            "Exchange_Reserves",
        ),
    ]

    api_key = os.getenv("GLASSNODE_API_KEY", "")

    for url, name in endpoints:
        try:
            params: dict[str, str] = {"a": "BTC", "i": "24h"}
            if api_key:
                params["api_key"] = api_key

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    if data and isinstance(data, list) and len(data) > 0:
                        latest = data[-1]
                        metrics.append(
                            OnChainMetric(
                                metric_name=name,
                                value=float(latest.get("v", 0)) if "v" in latest else 0.0,
                                source="Glassnode",
                            )
                        )
                else:
                    logger.warning(
                        f"Glassnode {name}: HTTP {resp.status_code}"
                        " (endpoint may require paid tier)"
                    )
        except Exception as e:
            logger.warning(f"Glassnode {name} failed: {e}")

    if not metrics:
        logger.warning("Glassnode: no metrics available (free tier limited)")
    return metrics


async def _collect_derivatives() -> list[OnChainMetric]:
    """Collect BTC derivatives — OKX → Binance Futures → Bybit fallback (FR5).

    Metrics: BTC_Funding_Rate, BTC_Open_Interest, BTC_Long_Short_Ratio, BTC_Taker_Buy_Sell_Ratio
    All public endpoints — no API key required.
    v0.22.0: OKX first — Binance (both Spot & Futures) and Bybit are geo-blocked/403 from
    GitHub Actions. OKX is the only reliable provider on CI.
    """
    providers = [
        ("OKX", _derivatives_okx),
        ("Binance_Futures", _derivatives_binance),
        ("Bybit", _derivatives_bybit),
    ]
    for provider_name, collector in providers:
        try:
            metrics = await collector()
            if metrics:
                logger.info(f"Derivatives: {len(metrics)} metrics from {provider_name}")
                return metrics
        except Exception as e:
            logger.warning(f"Derivatives {provider_name} failed: {e}")

    logger.warning("Derivatives: all providers failed")
    return []


async def _derivatives_binance() -> list[OnChainMetric]:
    """Binance Futures public endpoints — primary derivatives source."""
    metrics: list[OnChainMetric] = []
    base = "https://fapi.binance.com"

    async with httpx.AsyncClient(timeout=15) as client:
        # Funding Rate (latest 8h rate)
        try:
            resp = await client.get(
                f"{base}/fapi/v1/fundingRate",
                params={"symbol": "BTCUSDT", "limit": "1"},
            )
            resp.raise_for_status()
            data = resp.json()
            if data:
                metrics.append(
                    OnChainMetric(
                        "BTC_Funding_Rate", float(data[0]["fundingRate"]), "Binance", "8h rate"
                    )
                )
        except Exception as e:
            logger.debug(f"Binance fundingRate: {e}")

        # Open Interest
        try:
            resp = await client.get(f"{base}/fapi/v1/openInterest", params={"symbol": "BTCUSDT"})
            resp.raise_for_status()
            data = resp.json()
            metrics.append(
                OnChainMetric(
                    "BTC_Open_Interest", float(data["openInterest"]), "Binance", "BTC contracts"
                )
            )
        except Exception as e:
            logger.debug(f"Binance openInterest: {e}")

        # Long/Short Account Ratio
        try:
            resp = await client.get(
                f"{base}/futures/data/globalLongShortAccountRatio",
                params={"symbol": "BTCUSDT", "period": "5m", "limit": "1"},
            )
            resp.raise_for_status()
            data = resp.json()
            if data:
                metrics.append(
                    OnChainMetric(
                        "BTC_Long_Short_Ratio",
                        float(data[0]["longShortRatio"]),
                        "Binance",
                        "global account ratio",
                    )
                )
        except Exception as e:
            logger.debug(f"Binance longShortRatio: {e}")

        # Taker Buy/Sell Volume Ratio
        try:
            resp = await client.get(
                f"{base}/futures/data/takerBuySellVol",
                params={"symbol": "BTCUSDT", "period": "5m", "limit": "1"},
            )
            resp.raise_for_status()
            data = resp.json()
            if data:
                metrics.append(
                    OnChainMetric(
                        "BTC_Taker_Buy_Sell_Ratio",
                        float(data[0]["buySellRatio"]),
                        "Binance",
                        "taker buy/sell volume ratio",
                    )
                )
        except Exception as e:
            logger.debug(f"Binance takerBuySellVol: {e}")

    return metrics


async def _derivatives_bybit() -> list[OnChainMetric]:
    """Bybit v5 public API — first fallback derivatives source."""
    metrics: list[OnChainMetric] = []
    base = "https://api.bybit.com/v5/market"

    async with httpx.AsyncClient(timeout=15) as client:
        # Funding Rate
        try:
            resp = await client.get(
                f"{base}/funding/history",
                params={"category": "linear", "symbol": "BTCUSDT", "limit": "1"},
            )
            resp.raise_for_status()
            data = resp.json()
            entries = data.get("result", {}).get("list", [])
            if entries:
                metrics.append(
                    OnChainMetric(
                        "BTC_Funding_Rate", float(entries[0]["fundingRate"]), "Bybit", "8h rate"
                    )
                )
        except Exception as e:
            logger.debug(f"Bybit fundingRate: {e}")

        # Open Interest
        try:
            resp = await client.get(
                f"{base}/open-interest",
                params={
                    "category": "linear",
                    "symbol": "BTCUSDT",
                    "intervalTime": "1h",
                    "limit": "1",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            entries = data.get("result", {}).get("list", [])
            if entries:
                oi = float(entries[0]["openInterest"])
                metrics.append(OnChainMetric("BTC_Open_Interest", oi, "Bybit", "BTC contracts"))
        except Exception as e:
            logger.debug(f"Bybit openInterest: {e}")

        # Long/Short Ratio (derived from buy/sell account ratio)
        try:
            resp = await client.get(
                f"{base}/account-ratio",
                params={"category": "linear", "symbol": "BTCUSDT", "period": "1h", "limit": "1"},
            )
            resp.raise_for_status()
            data = resp.json()
            entries = data.get("result", {}).get("list", [])
            if entries:
                buy_ratio = float(entries[0]["buyRatio"])
                sell_ratio = float(entries[0]["sellRatio"])
                ls_ratio = round(buy_ratio / sell_ratio, 4) if sell_ratio > 0 else 1.0
                metrics.append(
                    OnChainMetric(
                        "BTC_Long_Short_Ratio", ls_ratio, "Bybit", "buy/sell account ratio"
                    )
                )
        except Exception as e:
            logger.debug(f"Bybit accountRatio: {e}")

    return metrics


async def _derivatives_okx() -> list[OnChainMetric]:
    """OKX v5 public API — second fallback derivatives source."""
    metrics: list[OnChainMetric] = []
    base = "https://www.okx.com/api/v5/public"

    async with httpx.AsyncClient(timeout=15) as client:
        # Funding Rate
        try:
            resp = await client.get(f"{base}/funding-rate", params={"instId": "BTC-USDT-SWAP"})
            resp.raise_for_status()
            data = resp.json()
            entries = data.get("data", [])
            if entries:
                metrics.append(
                    OnChainMetric(
                        "BTC_Funding_Rate", float(entries[0]["fundingRate"]), "OKX", "8h rate"
                    )
                )
        except Exception as e:
            logger.debug(f"OKX fundingRate: {e}")

        # Open Interest
        try:
            resp = await client.get(
                f"{base}/open-interest",
                params={"instType": "SWAP", "instId": "BTC-USDT-SWAP"},
            )
            resp.raise_for_status()
            data = resp.json()
            entries = data.get("data", [])
            if entries:
                metrics.append(
                    OnChainMetric(
                        "BTC_Open_Interest", float(entries[0]["oi"]), "OKX", "BTC contracts"
                    )
                )
        except Exception as e:
            logger.debug(f"OKX openInterest: {e}")

    return metrics


async def _collect_fred() -> list[OnChainMetric]:
    """Collect macro data from FRED API (FR9)."""
    api_key = os.getenv("FRED_API_KEY", "")
    if not api_key:
        logger.warning("FRED_API_KEY not set — skipping FRED data")
        return []

    series = {
        "DGS10": "US_10Y_Treasury",
        "CPIAUCSL": "CPI",
        "WALCL": "Fed_Balance_Sheet",
    }

    metrics: list[OnChainMetric] = []

    for series_id, name in series.items():
        try:
            url = "https://api.stlouisfed.org/fred/series/observations"
            params = {
                "series_id": series_id,
                "api_key": api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": "1",
            }
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()

            data = resp.json()
            obs = data.get("observations", [])
            if obs:
                value_str = obs[0].get("value", "0")
                try:
                    value = float(value_str)
                except ValueError:
                    value = 0.0
                metrics.append(
                    OnChainMetric(
                        metric_name=name,
                        value=value,
                        source="FRED",
                        note=f"Series: {series_id}",
                    )
                )
        except Exception as e:
            logger.warning(f"FRED {name} failed: {e}")

    return metrics
