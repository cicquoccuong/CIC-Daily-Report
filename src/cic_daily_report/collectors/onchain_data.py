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
    """Collect on-chain + derivatives + FRED macro data."""
    logger.info("Collecting on-chain & derivatives data")

    tasks = [
        _collect_glassnode(),
        _collect_coinglass(),
        _collect_fred(),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_metrics: list[OnChainMetric] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            source_names = ["Glassnode", "Coinglass", "FRED"]
            logger.warning(f"{source_names[i]} failed: {result}")
        else:
            all_metrics.extend(result)

    logger.info(f"On-chain data collected: {len(all_metrics)} metrics")
    return all_metrics


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


async def _collect_coinglass() -> list[OnChainMetric]:
    """Collect derivatives data from Coinglass (FR5).

    Funding rates, Open Interest, Liquidations.

    DEPRECATION WARNING: Using Coinglass v2 public endpoints which are deprecated.
    v2 may stop working at any time. When it does:
    - Migrate to v4: https://open-api-v4.coinglass.com/api/futures/...
    - v4 header: CG-API-KEY (not coinglassSecret)
    - v4 free plan: 10,000 calls/month (sufficient for hourly pipeline)
    - Liquidation history + Altcoin Season require Hobbyist plan ($29/mo)
    See docs/API_RESEARCH.md for full details.
    """
    metrics: list[OnChainMetric] = []

    # Coinglass public endpoints
    endpoints = [
        (
            "https://open-api.coinglass.com/public/v2/funding",
            "BTC_Funding_Rate",
            lambda d: d.get("data", [{}])[0].get("rate", 0) if d.get("data") else 0,
        ),
        (
            "https://open-api.coinglass.com/public/v2/open_interest",
            "BTC_Open_Interest",
            lambda d: d.get("data", [{}])[0].get("openInterest", 0) if d.get("data") else 0,
        ),
    ]

    api_key = os.getenv("COINGLASS_API_KEY", "")

    for url, name, extractor in endpoints:
        try:
            headers = {}
            if api_key:
                headers["coinglassSecret"] = api_key

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, params={"symbol": "BTC"}, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    value = extractor(data)
                    if value == 0:
                        logger.warning(
                            f"Coinglass {name}: returned 0 — skipping to avoid "
                            "misleading data. v2 public API is deprecated; "
                            "migrate to v4 (open-api-v4.coinglass.com) with CG-API-KEY header"
                        )
                        continue
                    metrics.append(
                        OnChainMetric(
                            metric_name=name,
                            value=float(value),
                            source="Coinglass",
                        )
                    )
                else:
                    logger.debug(f"Coinglass {name}: HTTP {resp.status_code}")
        except Exception as e:
            logger.debug(f"Coinglass {name} failed: {e}")

    if not metrics:
        logger.warning("Coinglass: no data available")
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
