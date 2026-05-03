"""Research Data Collector — BGeometrics, ETF Flows, Stablecoins, Pi Cycle (P2-A).

Collects advanced on-chain and market data for the CIC Market Insight research article.
All sources are free, no API keys required (except where noted).

Sources:
  - BGeometrics: MVRV Z-Score, NUPL, SOPR, Puell Multiple (15 req/day)
  - btcetffundflow.com: Spot Bitcoin ETF daily flows (scraping __NEXT_DATA__)
  - DefiLlama: Stablecoin supply & flow data (USDT, USDC, total)
  - Blockchain.com: Miner Revenue, Difficulty (complementary)
  - Binance Spot: Pi Cycle Top indicator (calculated from 111SMA & 350SMA*2)
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from cic_daily_report.core.logger import get_logger

logger = get_logger("research_data")

REQUEST_TIMEOUT = 20


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class OnChainAdvanced:
    """Advanced on-chain metric from BGeometrics or calculated."""

    name: str
    value: float
    source: str
    date: str = ""


@dataclass
class ETFFlowEntry:
    """Single ETF daily flow entry."""

    etf_name: str
    flow_usd: float
    btc_holdings: float = 0.0
    date: str = ""


@dataclass
class ETFFlowData:
    """Aggregated ETF flow data."""

    entries: list[ETFFlowEntry] = field(default_factory=list)
    total_flow_usd: float = 0.0
    date: str = ""
    source: str = "btcetffundflow.com"
    recent_total_flows: list[tuple[str, float]] = field(default_factory=list)  # Last 5 days


@dataclass
class StablecoinData:
    """Stablecoin supply and flow."""

    name: str
    market_cap: float
    change_1d: float = 0.0
    change_7d: float = 0.0
    change_30d: float = 0.0


@dataclass
class PiCycleData:
    """Pi Cycle Top indicator values."""

    sma_111: float = 0.0
    sma_350x2: float = 0.0
    is_crossed: bool = False
    distance_pct: float = 0.0


@dataclass
class ResearchData:
    """All research-specific data collected for the article."""

    onchain_advanced: list[OnChainAdvanced] = field(default_factory=list)
    etf_flows: ETFFlowData | None = None
    stablecoins: list[StablecoinData] = field(default_factory=list)
    blockchain_stats: dict[str, float] = field(default_factory=dict)
    pi_cycle: PiCycleData | None = None
    collected_at: str = ""

    def format_for_llm(self) -> str:
        """Format all research data as structured text for LLM prompt."""
        parts: list[str] = []

        # On-chain advanced — filter out 0.0 values to prevent LLM misinterpretation (VD-27)
        _BGEOMETRICS_NAMES = {"MVRV_Z_Score", "NUPL", "SOPR", "Puell_Multiple"}
        if self.onchain_advanced:
            # WHY: BGeometrics returns 0.0000 when data unavailable; LLM interprets
            # this as "market is dead/stagnant" which produces misleading analysis.
            valid = [m for m in self.onchain_advanced if m.value != 0.0]
            zero_bgeometrics = [
                m for m in self.onchain_advanced if m.value == 0.0 and m.name in _BGEOMETRICS_NAMES
            ]
            if valid:
                lines = []
                for m in valid:
                    lines.append(f"  {m.name}: {m.value:.4f} ({m.source}, {m.date})")
                parts.append("=== ON-CHAIN NÂNG CAO (nguồn: BGeometrics) ===\n" + "\n".join(lines))
            if len(zero_bgeometrics) == len(_BGEOMETRICS_NAMES):
                # v0.33.0: More specific warning so LLM doesn't skip ALL on-chain analysis.
                # WHY: Vague "on-chain n\u00e2ng cao" text caused LLM to omit Pi Cycle,
                # Hash Rate, Exchange Flow etc. which are from DIFFERENT sources.
                parts.append(
                    "\u26a0\ufe0f CH\u00da \u00dd: BGeometrics API tr\u1ea3 v\u1ec1 0.0 "
                    "cho 4 ch\u1ec9 s\u1ed1 (MVRV Z-Score, NUPL, SOPR, Puell Multiple) "
                    "\u2014 d\u1eef li\u1ec7u CH\u01af\u0041 C\u1eac\u0050 NH\u1eac\u0054. "
                    "C\u00e1c ngu\u1ed3n on-chain KH\u00c1C (Pi Cycle, Blockchain.com, "
                    "Mempool) KH\u00d4NG b\u1ecb \u1ea3nh h\u01b0\u1edfng v\u00e0 "
                    "v\u1eabn ho\u1ea1t \u0111\u1ed9ng b\u00ecnh th\u01b0\u1eddng."
                )

        # ETF Flows
        if self.etf_flows and self.etf_flows.entries:
            etf = self.etf_flows
            lines = [
                f"  Ngày mới nhất: {etf.date}",
                f"  Tổng dòng tiền: ${etf.total_flow_usd:,.0f}",
            ]
            for e in sorted(etf.entries, key=lambda x: abs(x.flow_usd), reverse=True)[:8]:
                sign = "+" if e.flow_usd >= 0 else ""
                lines.append(f"  {e.etf_name}: {sign}${e.flow_usd:,.0f}")
            # 5-day trend for analysis
            if etf.recent_total_flows:
                lines.append("  --- Xu hướng 5 ngày gần nhất ---")
                for date, total in etf.recent_total_flows:
                    sign = "+" if total >= 0 else ""
                    lines.append(f"  {date}: {sign}${total:,.0f}")
            parts.append(
                f"=== SPOT BITCOIN ETF FLOW (nguồn: {etf.source}) ===\n" + "\n".join(lines)
            )

        # Stablecoins
        if self.stablecoins:
            lines = []
            for s in self.stablecoins:
                d1 = f"{s.change_1d:+,.0f}"
                d7 = f"{s.change_7d:+,.0f}"
                d30 = f"{s.change_30d:+,.0f}"
                lines.append(
                    f"  {s.name}: ${s.market_cap / 1e9:,.2f}B (1d: ${d1}, 7d: ${d7}, 30d: ${d30})"
                )
            parts.append("=== STABLECOIN SUPPLY (nguồn: DefiLlama) ===\n" + "\n".join(lines))

        # Blockchain stats
        if self.blockchain_stats:
            lines = []
            for name, value in self.blockchain_stats.items():
                if abs(value) >= 1e9:
                    lines.append(f"  {name}: {value / 1e9:,.2f}B")
                elif abs(value) >= 1e6:
                    lines.append(f"  {name}: {value / 1e6:,.2f}M")
                else:
                    lines.append(f"  {name}: {value:,.2f}")
            parts.append("=== BLOCKCHAIN STATS (nguồn: Blockchain.com) ===\n" + "\n".join(lines))

        # Pi Cycle Top
        if self.pi_cycle and self.pi_cycle.sma_111 > 0:
            pc = self.pi_cycle
            status = "⚠️ CROSSED (tín hiệu đỉnh!)" if pc.is_crossed else "Chưa cross"
            parts.append(
                "=== PI CYCLE TOP INDICATOR (tính từ Binance OHLCV) ===\n"
                f"  111-day SMA: ${pc.sma_111:,.0f}\n"
                f"  350-day SMA × 2: ${pc.sma_350x2:,.0f}\n"
                f"  Khoảng cách: {pc.distance_pct:+.1f}%\n"
                f"  Trạng thái: {status}"
            )

        return "\n\n".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def collect_research_data() -> ResearchData:
    """Collect all research-specific data in parallel.

    Returns ResearchData with whatever was successfully collected.
    Individual source failures are logged but don't fail the whole collection.
    """
    logger.info("Collecting research data (BGeometrics, ETF, Stablecoins, Pi Cycle)")

    tasks = [
        _collect_bgeometrics(),
        _collect_etf_flows(),
        _collect_stablecoin_data(),
        _collect_blockchain_stats(),
        _collect_pi_cycle(),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    research = ResearchData(
        collected_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    )

    source_names = ["BGeometrics", "ETF Flows", "Stablecoins", "Blockchain.com", "Pi Cycle"]
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning(f"Research {source_names[i]} failed: {result}")
            continue

        if i == 0:
            research.onchain_advanced = result
        elif i == 1:
            research.etf_flows = result
        elif i == 2:
            research.stablecoins = result
        elif i == 3:
            research.blockchain_stats = result
        elif i == 4:
            research.pi_cycle = result

    metrics_count = (
        len(research.onchain_advanced)
        + (1 if research.etf_flows and research.etf_flows.entries else 0)
        + len(research.stablecoins)
        + len(research.blockchain_stats)
        + (1 if research.pi_cycle and research.pi_cycle.sma_111 > 0 else 0)
    )
    logger.info(f"Research data collected: {metrics_count} data points")
    return research


# ---------------------------------------------------------------------------
# BGeometrics — MVRV Z-Score, NUPL, SOPR, Puell Multiple
# Free tier: 8 req/hour, 15 req/day. No API key required.
# ---------------------------------------------------------------------------

_BGEOMETRICS_BASE = "https://bitcoin-data.com/v1"
_BGEOMETRICS_ENDPOINTS = [
    ("mvrv-zscore", "MVRV_Z_Score"),
    ("nupl", "NUPL"),
    ("sopr", "SOPR"),
    ("puell-multiple", "Puell_Multiple"),
]


async def _collect_bgeometrics() -> list[OnChainAdvanced]:
    """Fetch advanced on-chain metrics from BGeometrics.

    Rate limit: 8 req/hour, 15 req/day — we use exactly 4 calls.
    Each endpoint returns daily time-series; we take the latest entry.
    """
    metrics: list[OnChainAdvanced] = []

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        for endpoint, name in _BGEOMETRICS_ENDPOINTS:
            try:
                resp = await client.get(f"{_BGEOMETRICS_BASE}/{endpoint}")
                if resp.status_code == 429:
                    logger.warning(f"BGeometrics {name}: rate limited (429)")
                    continue
                resp.raise_for_status()
                data = resp.json()

                if isinstance(data, list) and len(data) > 0:
                    latest = data[-1]
                    # BGeometrics returns {"d": "YYYY-MM-DD", "v": float_value}
                    value = float(latest.get("v", latest.get("value", 0)))
                    date = latest.get("d", latest.get("date", ""))
                    metrics.append(
                        OnChainAdvanced(name=name, value=value, source="BGeometrics", date=date)
                    )
                elif isinstance(data, dict):
                    # Some endpoints return single object
                    value = float(data.get("v", data.get("value", 0)))
                    date = data.get("d", data.get("date", ""))
                    metrics.append(
                        OnChainAdvanced(name=name, value=value, source="BGeometrics", date=date)
                    )
            except httpx.HTTPStatusError as e:
                logger.warning(f"BGeometrics {name}: HTTP {e.response.status_code}")
            except Exception as e:
                logger.warning(f"BGeometrics {name}: {e}")

            # Small delay between requests to be kind to rate limits
            await asyncio.sleep(0.5)

    if metrics:
        logger.info(f"BGeometrics: {len(metrics)} metrics collected")
    else:
        logger.warning("BGeometrics: no metrics collected")
    return metrics


# ---------------------------------------------------------------------------
# ETF Flows — btcetffundflow.com (Next.js __NEXT_DATA__ scraping)
# ---------------------------------------------------------------------------


async def _collect_etf_flows() -> ETFFlowData | None:
    """Fetch Spot Bitcoin ETF daily flow data from btcetffundflow.com.

    Extracts __NEXT_DATA__ JSON embedded in the page HTML.
    Returns the most recent day's flows for all tracked ETFs.
    """
    url = "https://btcetffundflow.com/us"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    }

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            html = resp.text

        # Extract __NEXT_DATA__ JSON
        # Wave 0.8.7.3: bound to 500KB max — HTML untrusted, defensive vs ReDoS
        match = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">([^<]{0,500000})</script>',
            html,
        )
        if not match:
            logger.warning("ETF flows: __NEXT_DATA__ not found in page")
            return None

        next_data = json.loads(match.group(1))

        # Navigate: props.pageProps.dehydratedState.queries[0].state.data.data
        queries = (
            next_data.get("props", {})
            .get("pageProps", {})
            .get("dehydratedState", {})
            .get("queries", [])
        )
        if not queries:
            logger.warning("ETF flows: no queries in __NEXT_DATA__")
            return None

        # v0.31.0: queries[0] may be a list instead of dict if API structure changes
        first_query = queries[0]
        if not isinstance(first_query, dict):
            logger.warning(f"ETF flows: queries[0] is {type(first_query).__name__}, expected dict")
            return None

        # v0.32.0: Defensive type checks — __NEXT_DATA__ structure can change.
        # Each nested value might be a list instead of dict after site updates.
        state_data = first_query.get("state", {}).get("data", {})
        if isinstance(state_data, list):
            logger.warning(f"ETF flows: state.data is list (len={len(state_data)}), expected dict")
            state_data = state_data[0] if state_data else {}
        if not isinstance(state_data, dict):
            logger.warning(f"ETF flows: state.data is {type(state_data).__name__}, expected dict")
            return None

        inner_data = state_data.get("data", {})
        if isinstance(inner_data, list):
            logger.warning(
                f"ETF flows: state.data.data is list (len={len(inner_data)}), expected dict"
            )
            inner_data = inner_data[0] if inner_data else {}
        if not isinstance(inner_data, dict):
            logger.warning(
                f"ETF flows: state.data.data is {type(inner_data).__name__}, expected dict"
            )
            return None

        etf_data = inner_data
        providers = etf_data.get("providers", {})
        # WHY: API response can return providers as list instead of dict after
        # site updates, causing 'list' object has no attribute 'get' at line
        # where we do providers.get(key, key). Convert list to empty dict.
        if isinstance(providers, list):
            logger.warning(f"ETF flows: providers is list (len={len(providers)}), expected dict")
            providers = {}
        chart2 = etf_data.get("chart2", {})  # USD net flows
        # WHY: Same defensive check — chart2 could become list after API changes
        if isinstance(chart2, list):
            logger.warning(f"ETF flows: chart2 is list (len={len(chart2)}), expected dict")
            return None

        if not chart2:
            logger.warning("ETF flows: no chart2 (USD flow) data")
            return None

        # chart2 structure: {"dates": [...], "IBIT": [...], "FBTC": [...], ...}
        dates = chart2.get("dates", [])
        if not dates:
            logger.warning("ETF flows: no dates in chart2")
            return None

        # Get the most recent day
        latest_idx = len(dates) - 1
        latest_date = dates[latest_idx]

        entries: list[ETFFlowEntry] = []
        total_flow = 0.0

        for key, values in chart2.items():
            if key == "dates" or not isinstance(values, list):
                continue
            if latest_idx < len(values) and values[latest_idx] is not None:
                flow = float(values[latest_idx])
                etf_name = providers.get(key, key)
                entries.append(ETFFlowEntry(etf_name=etf_name, flow_usd=flow, date=latest_date))
                total_flow += flow

        # Collect last 5 days total flows for trend analysis
        recent_total_flows: list[tuple[str, float]] = []
        num_days = min(5, len(dates))
        for day_offset in range(num_days):
            idx = len(dates) - num_days + day_offset
            day_date = dates[idx]
            day_total = 0.0
            for key, values in chart2.items():
                if key == "dates" or not isinstance(values, list):
                    continue
                if idx < len(values) and values[idx] is not None:
                    day_total += float(values[idx])
            recent_total_flows.append((day_date, day_total))

        if entries:
            logger.info(
                f"ETF flows: {len(entries)} ETFs, total ${total_flow:,.0f} on {latest_date}"
            )
        return ETFFlowData(
            entries=entries,
            total_flow_usd=total_flow,
            date=latest_date,
            recent_total_flows=recent_total_flows,
        )

    except Exception as e:
        logger.warning(f"ETF flows collection failed: {e}")
        return None


# ---------------------------------------------------------------------------
# DefiLlama Stablecoins — USDT, USDC, total supply + flow
# ---------------------------------------------------------------------------

_DEFILLAMA_STABLECOINS_URL = "https://stablecoins.llama.fi/stablecoins"


async def _collect_stablecoin_data() -> list[StablecoinData]:
    """Fetch stablecoin supply and flow data from DefiLlama.

    Returns top stablecoins with market cap and 1d/7d/30d supply changes.
    """
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(
                _DEFILLAMA_STABLECOINS_URL,
                params={"includePrices": "false"},
            )
            resp.raise_for_status()
            data = resp.json()

        stables = data.get("peggedAssets", [])
        if not stables:
            logger.warning("DefiLlama stablecoins: no data")
            return []

        # Filter to top stablecoins by market cap
        target_names = {"Tether", "USDC", "DAI", "First Digital USD", "USDS", "Ethena USDe"}
        result: list[StablecoinData] = []

        for s in stables:
            name = s.get("name", "")
            symbol = s.get("symbol", "")

            if name not in target_names and symbol not in {"USDT", "USDC", "DAI", "FDUSD", "USDS"}:
                continue

            # Use circulating.peggedUSD as single source of truth
            circ = s.get("circulating", {})
            current_peg = circ.get("peggedUSD", 0)

            if current_peg < 1e8:  # Skip if less than $100M
                continue

            # Calculate changes from previous periods
            change_1d = 0.0
            change_7d = 0.0
            change_30d = 0.0

            prev_day = s.get("circulatingPrevDay", {})
            prev_week = s.get("circulatingPrevWeek", {})
            prev_month = s.get("circulatingPrevMonth", {})

            if prev_day.get("peggedUSD"):
                change_1d = current_peg - prev_day["peggedUSD"]
            if prev_week.get("peggedUSD"):
                change_7d = current_peg - prev_week["peggedUSD"]
            if prev_month.get("peggedUSD"):
                change_30d = current_peg - prev_month["peggedUSD"]

            result.append(
                StablecoinData(
                    name=f"{name} ({symbol})",
                    market_cap=current_peg,
                    change_1d=change_1d,
                    change_7d=change_7d,
                    change_30d=change_30d,
                )
            )

        # Sort by market cap descending
        result.sort(key=lambda x: x.market_cap, reverse=True)

        if result:
            total = sum(s.market_cap for s in result)
            logger.info(f"Stablecoins: {len(result)} tracked, total ${total / 1e9:.1f}B")
        return result

    except Exception as e:
        logger.warning(f"Stablecoin data collection failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Blockchain.com — Miner Revenue, Difficulty (complementary stats)
# ---------------------------------------------------------------------------

_BLOCKCHAIN_STATS_URL = "https://api.blockchain.info/stats"


async def _collect_blockchain_stats() -> dict[str, float]:
    """Fetch Bitcoin network stats from Blockchain.com API.

    Complements CoinMetrics with miner revenue and difficulty data.
    """
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(_BLOCKCHAIN_STATS_URL)
            resp.raise_for_status()
            data = resp.json()

        stats: dict[str, float] = {}
        mappings = {
            "miners_revenue_usd": "Miner_Revenue_USD",
            "difficulty": "Difficulty",
            "hash_rate": "Hash_Rate_TH",
            "n_tx": "Transactions_24h",
            "total_fees_btc": "Total_Fees_BTC",
            "mempool_size": "Mempool_Size_Bytes",
            "n_blocks_mined": "Blocks_Mined_24h",
        }

        for api_key, metric_name in mappings.items():
            value = data.get(api_key)
            if value is not None:
                stats[metric_name] = float(value)

        if stats:
            logger.info(f"Blockchain.com: {len(stats)} stats collected")
        return stats

    except Exception as e:
        logger.warning(f"Blockchain.com stats failed: {e}")
        return {}


# ---------------------------------------------------------------------------
# Pi Cycle Top — calculated from Binance BTC daily OHLCV
# Uses 111-day SMA and 350-day SMA × 2. When 111SMA crosses above
# 350SMA×2, it has historically signaled a market cycle top.
# ---------------------------------------------------------------------------

_BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

# v0.32.0: CoinGecko fallback for Pi Cycle — Binance returns 451 from GitHub Actions (geo-blocked)
_COINGECKO_MARKET_CHART_URL = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"


async def _collect_pi_cycle() -> PiCycleData | None:
    """Calculate Pi Cycle Top indicator from BTC daily price data.

    Fetches 365 daily candles and computes:
    - 111-day Simple Moving Average
    - 350-day Simple Moving Average x 2
    - Whether 111SMA has crossed above 350SMA x 2 (cycle top signal)

    v0.32.0: Tries Binance first, falls back to CoinGecko on failure (451 geo-block).
    """
    closes = await _fetch_pi_cycle_closes_binance()

    if closes is None:
        logger.info("Pi Cycle: Binance failed, falling back to CoinGecko")
        closes = await _fetch_pi_cycle_closes_coingecko()

    if closes is None:
        return None

    if len(closes) < 350:
        logger.warning(f"Pi Cycle: only {len(closes)} prices (need 350)")
        return None

    return _calculate_pi_cycle_from_closes(closes)


async def _fetch_pi_cycle_closes_binance() -> list[float] | None:
    """Fetch 365 daily closing prices from Binance klines API."""
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(
                _BINANCE_KLINES_URL,
                params={
                    "symbol": "BTCUSDT",
                    "interval": "1d",
                    "limit": "365",
                },
            )
            resp.raise_for_status()
            klines = resp.json()

        # Extract closing prices (index 4 in kline array)
        return [float(k[4]) for k in klines]

    except Exception as e:
        logger.warning(f"Pi Cycle Binance failed: {e}")
        return None


async def _fetch_pi_cycle_closes_coingecko() -> list[float] | None:
    """Fetch 365 daily prices from CoinGecko market_chart (free, no geo-block).

    CoinGecko returns: {"prices": [[timestamp_ms, price], ...]}
    """
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(
                _COINGECKO_MARKET_CHART_URL,
                params={
                    "vs_currency": "usd",
                    "days": "365",
                    "interval": "daily",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        prices = data.get("prices", [])
        if not prices:
            logger.warning("Pi Cycle CoinGecko: no prices returned")
            return None

        # Each entry is [timestamp_ms, price] — extract prices
        closes = [float(p[1]) for p in prices]
        logger.info(f"Pi Cycle CoinGecko: {len(closes)} daily prices fetched")
        return closes

    except Exception as e:
        logger.warning(f"Pi Cycle CoinGecko failed: {e}")
        return None


def _calculate_pi_cycle_from_closes(closes: list[float]) -> PiCycleData:
    """Calculate Pi Cycle Top indicator from closing prices."""
    sma_111 = sum(closes[-111:]) / 111
    sma_350 = sum(closes[-350:]) / 350
    sma_350x2 = sma_350 * 2

    # Check for cross: 111SMA > 350SMA x 2
    is_crossed = sma_111 > sma_350x2

    # Distance between the two (negative = 111SMA below 350SMA x 2)
    distance_pct = ((sma_111 - sma_350x2) / sma_350x2) * 100

    logger.info(
        f"Pi Cycle: 111SMA=${sma_111:,.0f}, 350SMA x 2=${sma_350x2:,.0f}, "
        f"distance={distance_pct:+.1f}%, crossed={is_crossed}"
    )

    return PiCycleData(
        sma_111=sma_111,
        sma_350x2=sma_350x2,
        is_crossed=is_crossed,
        distance_pct=distance_pct,
    )
