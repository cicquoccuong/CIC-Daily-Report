"""Market & Macro Data Collector (FR3, FR6, FR10)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from cic_daily_report.core.error_handler import CollectorError
from cic_daily_report.core.logger import get_logger

logger = get_logger("market_data")


@dataclass
class MarketDataPoint:
    """Single market data point."""

    symbol: str
    price: float
    change_24h: float
    volume_24h: float
    market_cap: float
    data_type: str  # "crypto", "macro", "index"
    source: str

    def to_row(self) -> list[str]:
        collected_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        return [
            "",  # ID
            collected_at,
            self.symbol,
            str(self.price),
            str(self.change_24h),
            str(self.market_cap),
            str(self.volume_24h),
            self.data_type,
            self.source,
        ]


async def collect_market_data() -> list[MarketDataPoint]:
    """Collect all market & macro data in parallel."""
    logger.info("Collecting market & macro data")

    tasks = [
        _collect_coinlore(),
        _collect_macro_indices(),
        _collect_fear_greed(),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_data: list[MarketDataPoint] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning(f"Market data source {i} failed: {result}")
        else:
            all_data.extend(result)

    logger.info(f"Market data collected: {len(all_data)} data points")
    return all_data


async def _collect_coinlore() -> list[MarketDataPoint]:
    """Collect crypto prices from CoinLore (FR6 primary)."""
    url = "https://api.coinlore.net/api/tickers/"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params={"start": 0, "limit": 50})
            resp.raise_for_status()

        data = resp.json()
        points = []
        for coin in data.get("data", []):
            points.append(
                MarketDataPoint(
                    symbol=coin.get("symbol", ""),
                    price=float(coin.get("price_usd", 0)),
                    change_24h=float(coin.get("percent_change_24h", 0)),
                    volume_24h=float(coin.get("volume24", 0)),
                    market_cap=float(coin.get("market_cap_usd", 0)),
                    data_type="crypto",
                    source="CoinLore",
                )
            )
        return points

    except Exception as e:
        raise CollectorError(f"CoinLore failed: {e}", source="market_data") from e


async def _collect_macro_indices() -> list[MarketDataPoint]:
    """Collect macro indices: DXY, Gold, Oil, VIX, SPX via yfinance (FR3).

    Uses asyncio.to_thread() since yfinance is sync.
    """
    try:
        import yfinance as _yf  # noqa: F401
    except ImportError:
        logger.warning("yfinance not installed — skipping macro indices")
        return []

    symbols = {
        "DX-Y.NYB": ("DXY", "macro"),
        "GC=F": ("Gold", "macro"),
        "CL=F": ("Oil", "macro"),
        "^VIX": ("VIX", "index"),
        "^GSPC": ("SPX", "index"),
    }

    async def _fetch_yf(ticker: str, label: str, dtype: str) -> MarketDataPoint | None:
        try:
            data = await asyncio.to_thread(_yf_get_price, ticker)
            if data:
                return MarketDataPoint(
                    symbol=label,
                    price=data["price"],
                    change_24h=data["change_pct"],
                    volume_24h=0,
                    market_cap=0,
                    data_type=dtype,
                    source="yfinance",
                )
        except Exception as e:
            logger.warning(f"yfinance {label} failed: {e}")
        return None

    tasks = [_fetch_yf(t, label, dtype) for t, (label, dtype) in symbols.items()]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if isinstance(r, MarketDataPoint)]


def _yf_get_price(ticker: str) -> dict[str, float] | None:
    """Sync yfinance price fetch (run in thread)."""
    import yfinance as yf

    t = yf.Ticker(ticker)
    hist = t.history(period="2d")
    if hist.empty or len(hist) < 1:
        return None

    current = hist["Close"].iloc[-1]
    prev = hist["Close"].iloc[-2] if len(hist) >= 2 else current
    change_pct = ((current - prev) / prev * 100) if prev != 0 else 0

    return {"price": round(float(current), 2), "change_pct": round(float(change_pct), 2)}


async def _collect_fear_greed() -> list[MarketDataPoint]:
    """Collect Fear & Greed Index (FR10)."""
    url = "https://api.alternative.me/fng/"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        data = resp.json()
        fng = data.get("data", [{}])[0]
        value = float(fng.get("value", 50))

        return [
            MarketDataPoint(
                symbol="Fear&Greed",
                price=value,
                change_24h=0,
                volume_24h=0,
                market_cap=0,
                data_type="index",
                source="alternative.me",
            )
        ]
    except Exception as e:
        logger.warning(f"Fear & Greed Index failed: {e}")
        return []
