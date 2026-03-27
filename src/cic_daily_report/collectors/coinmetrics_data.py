"""CoinMetrics Community API — On-Chain Fundamentals Collector (v0.24.0).

Replaces Glassnode (limited free tier) as primary on-chain data source.
API: community-api.coinmetrics.io/v4/ (no key needed, ~100 req/min)
License: Non-commercial (fits CIC community use).
"""

from __future__ import annotations

import asyncio

import httpx

from cic_daily_report.collectors.onchain_data import OnChainMetric
from cic_daily_report.core.logger import get_logger

logger = get_logger("coinmetrics_data")

BASE_URL = "https://community-api.coinmetrics.io/v4"
REQUEST_TIMEOUT = 20

# Metrics to collect per asset
# Ref: https://docs.coinmetrics.io/api/v4#operation/getTimeseriesAssetMetrics
# Community (free) tier metrics — verified available 2026-03-18.
# PRO ONLY (not included): SOPR, FlowInExNtv, FlowOutExNtv, FlowInExUSD, FlowOutExUSD
METRICS_CONFIG = {
    "btc": [
        ("NVTAdj", "NVT_Ratio", "Network Value to Transactions"),
        ("CapMVRVCur", "MVRV_Ratio", "Market Value to Realized Value"),
        ("AdrActCnt", "Active_Addresses", "Active addresses in 24h"),
        ("HashRate", "Hash_Rate", "Network hash rate"),
    ],
    "eth": [
        ("NVTAdj", "NVT_Ratio", "Network Value to Transactions"),
        ("CapMVRVCur", "MVRV_Ratio", "Market Value to Realized Value"),
        ("AdrActCnt", "Active_Addresses", "Active addresses in 24h"),
    ],
}


async def collect_coinmetrics_onchain() -> list[OnChainMetric]:
    """Collect on-chain fundamentals from CoinMetrics Community API.

    Returns OnChainMetric objects compatible with existing pipeline.
    No API key required — community tier.
    """
    tasks = [_fetch_asset_metrics(asset, metrics) for asset, metrics in METRICS_CONFIG.items()]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_metrics: list[OnChainMetric] = []
    for asset, result in zip(METRICS_CONFIG.keys(), results):
        if isinstance(result, Exception):
            logger.warning(f"CoinMetrics {asset}: {result}")
        else:
            all_metrics.extend(result)

    if all_metrics:
        logger.info(f"CoinMetrics: {len(all_metrics)} on-chain metrics collected")
    else:
        logger.warning("CoinMetrics: no metrics collected")
    return all_metrics


async def _fetch_asset_metrics(
    asset: str,
    metric_configs: list[tuple[str, str, str]],
) -> list[OnChainMetric]:
    """Fetch latest metrics for a single asset from CoinMetrics."""
    metric_ids = [m[0] for m in metric_configs]
    metrics_param = ",".join(metric_ids)

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(
                f"{BASE_URL}/timeseries/asset-metrics",
                params={
                    "assets": asset,
                    "metrics": metrics_param,
                    "frequency": "1d",
                    "limit_per_asset": 1,
                    "sort": "time",
                    "sort_direction": "desc",
                },
            )
            resp.raise_for_status()

        data = resp.json()
        rows = data.get("data", [])
        if not rows:
            logger.warning(f"CoinMetrics {asset}: no data returned")
            return []

        latest = rows[0]
        coin = asset.upper()
        metrics: list[OnChainMetric] = []

        for cm_id, metric_name, note in metric_configs:
            value_str = latest.get(cm_id)
            if value_str is not None and value_str != "":
                try:
                    value = float(value_str)
                    metrics.append(
                        OnChainMetric(
                            metric_name=f"{coin}_{metric_name}",
                            value=value,
                            source="CoinMetrics",
                            note=note,
                        )
                    )
                except (ValueError, TypeError):
                    logger.debug(f"CoinMetrics {coin} {cm_id}: invalid value '{value_str}'")

        return metrics

    except httpx.HTTPStatusError as e:
        # v0.32.0: Log response body for 400 errors — helps debug metric name changes
        error_body = ""
        try:
            error_body = e.response.text[:500]
        except Exception:
            pass
        logger.warning(
            f"CoinMetrics {asset}: HTTP {e.response.status_code}"
            + (f" — {error_body}" if error_body else "")
        )
        return []
    except Exception as e:
        logger.warning(f"CoinMetrics {asset}: {e}")
        return []
