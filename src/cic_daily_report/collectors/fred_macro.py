"""FRED Macro Economic Data Collector (P1.19).

Collects latest observations from FRED (Federal Reserve Economic Data):
- DGS10: 10-Year Treasury Yield (percent)
- CPIAUCSL: CPI — Consumer Price Index (index)
- WALCL: Fed Balance Sheet Total Assets (billions USD)

Free tier: 120 requests/min (more than enough for 3 series).
Requires FRED_API_KEY environment variable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from cic_daily_report.core.logger import get_logger

logger = get_logger("fred_macro")

FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
REQUEST_TIMEOUT = 15

# WHY: Only 3 series — these are the most impactful macro indicators
# for crypto market context (rates, inflation, liquidity).
SERIES_CONFIG: list[dict[str, str]] = [
    {"series_id": "DGS10", "name": "10Y Treasury Yield", "unit": "percent"},
    {"series_id": "CPIAUCSL", "name": "CPI (Consumer Price Index)", "unit": "index"},
    {"series_id": "WALCL", "name": "Fed Balance Sheet", "unit": "billions"},
]


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class FREDDataPoint:
    """Single FRED observation."""

    series_id: str  # e.g., "DGS10"
    name: str  # human-readable
    value: float
    date: str  # observation date YYYY-MM-DD
    unit: str  # "percent", "index", "billions"


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


async def collect_fred_macro() -> list[FREDDataPoint]:
    """Fetch latest observation for each FRED series.

    Returns empty list if FRED_API_KEY is not set or API fails.
    WHY graceful: FRED data is supplementary — pipeline must not fail
    if this optional data source is unavailable.
    """
    api_key = os.getenv("FRED_API_KEY", "")
    if not api_key:
        logger.info("FRED_API_KEY not set — skipping macro data collection")
        return []

    results: list[FREDDataPoint] = []

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            for series in SERIES_CONFIG:
                try:
                    point = await _fetch_series(client, api_key, series)
                    if point:
                        results.append(point)
                except Exception as e:
                    logger.warning(f"FRED {series['series_id']} failed: {e}")
    except Exception as e:
        logger.warning(f"FRED collector failed: {e}")
        return []

    if results:
        logger.info(f"FRED macro: collected {len(results)}/{len(SERIES_CONFIG)} series")

    return results


async def _fetch_series(
    client: httpx.AsyncClient,
    api_key: str,
    series: dict[str, str],
) -> FREDDataPoint | None:
    """Fetch the latest observation for a single FRED series."""
    params = {
        "series_id": series["series_id"],
        "api_key": api_key,
        "sort_order": "desc",
        "limit": "1",
        "file_type": "json",
    }

    resp = await client.get(FRED_BASE_URL, params=params)
    resp.raise_for_status()
    data = resp.json()

    observations = data.get("observations", [])
    if not observations:
        return None

    obs = observations[0]
    raw_value = obs.get("value", "")

    # WHY: FRED returns "." for missing/pending observations
    if not raw_value or raw_value == ".":
        return None

    return FREDDataPoint(
        series_id=series["series_id"],
        name=series["name"],
        value=float(raw_value),
        date=obs.get("date", ""),
        unit=series["unit"],
    )


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_fred_for_llm(data: list[FREDDataPoint]) -> str:
    """Format FRED data for LLM context injection.

    Output:
    === DU LIEU KINH TE VI MO (FRED) ===
    - 10Y Treasury: 4.25% (2026-03-28)
    - CPI: 315.2 (2026-02-01)
    - Fed Balance Sheet: $7,234B (2026-03-26)
    """
    if not data:
        return ""

    lines: list[str] = ["=== DU LIEU KINH TE VI MO (FRED) ==="]
    for d in data:
        if d.unit == "percent":
            lines.append(f"- {d.name}: {d.value:.2f}% ({d.date})")
        elif d.unit == "billions":
            lines.append(f"- {d.name}: ${d.value:,.0f}B ({d.date})")
        else:
            lines.append(f"- {d.name}: {d.value:,.1f} ({d.date})")

    return "\n".join(lines)
