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
        _collect_mexc(),
        _collect_coinlore_global(),
        _collect_usdt_vnd(),
        _collect_macro_indices(),
        _collect_fear_greed(),
        _collect_altcoin_season(),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_data: list[MarketDataPoint] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning(f"Market data source {i} failed: {result}")
        else:
            all_data.extend(result)

    # Cross-verify CoinLore vs MEXC prices (FR22)
    all_data = _cross_verify_prices(all_data)

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


async def _collect_mexc() -> list[MarketDataPoint]:
    """Collect crypto prices from MEXC (FR6 secondary, FR22 cross-verify).

    Free API, no key required. Endpoint: GET /api/v3/ticker/24hr
    Returns all tickers (~2000+). We filter to USDT pairs for top coins.
    """
    url = "https://api.mexc.com/api/v3/ticker/24hr"
    target_symbols = {
        "BTCUSDT",
        "ETHUSDT",
        "BNBUSDT",
        "SOLUSDT",
        "XRPUSDT",
        "ADAUSDT",
        "DOGEUSDT",
        "AVAXUSDT",
        "DOTUSDT",
        "LINKUSDT",
        "MATICUSDT",
        "UNIUSDT",
        "LTCUSDT",
        "ATOMUSDT",
        "NEARUSDT",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        tickers = resp.json()
        points = []
        for ticker in tickers:
            sym = ticker.get("symbol", "")
            if sym not in target_symbols:
                continue
            # Strip USDT suffix for symbol name
            coin_symbol = sym.replace("USDT", "")
            pct_change = float(ticker.get("priceChangePercent", 0))
            points.append(
                MarketDataPoint(
                    symbol=coin_symbol,
                    price=float(ticker.get("lastPrice", 0)),
                    change_24h=pct_change * 100,  # MEXC returns as decimal (0.007 = 0.7%)
                    volume_24h=float(ticker.get("quoteVolume", 0)),
                    market_cap=0,  # MEXC doesn't provide market cap
                    data_type="crypto",
                    source="MEXC",
                )
            )
        logger.info(f"MEXC: {len(points)} tickers collected")
        return points

    except Exception as e:
        logger.warning(f"MEXC failed: {e}")
        return []


async def _collect_coinlore_global() -> list[MarketDataPoint]:
    """Collect BTC/ETH Dominance + Total Market Cap from CoinGecko /api/v3/global (FR20).

    Switched from CoinLore (inaccurate data) to CoinGecko (free, no key, accurate).
    CoinGecko global returns: total_market_cap, market_cap_percentage (dominance).
    """
    url = "https://api.coingecko.com/api/v3/global"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        raw = resp.json()
        global_data = raw.get("data", {})
        if not global_data:
            logger.warning("CoinGecko global: empty data")
            return []

        points = []
        dominance = global_data.get("market_cap_percentage", {})

        btc_d = float(dominance.get("btc", 0))
        if btc_d > 0:
            points.append(
                MarketDataPoint(
                    symbol="BTC_Dominance",
                    price=btc_d,
                    change_24h=0,
                    volume_24h=0,
                    market_cap=0,
                    data_type="index",
                    source="CoinGecko",
                )
            )

        total_mcap = float(global_data.get("total_market_cap", {}).get("usd", 0))
        total_vol = float(global_data.get("total_volume", {}).get("usd", 0))
        mcap_change = float(global_data.get("market_cap_change_percentage_24h_usd", 0))
        if total_mcap > 0:
            points.append(
                MarketDataPoint(
                    symbol="Total_MCap",
                    price=total_mcap,
                    change_24h=mcap_change,
                    volume_24h=total_vol,
                    market_cap=total_mcap,
                    data_type="index",
                    source="CoinGecko",
                )
            )

        eth_d = float(dominance.get("eth", 0))
        if eth_d > 0:
            points.append(
                MarketDataPoint(
                    symbol="ETH_Dominance",
                    price=eth_d,
                    change_24h=0,
                    volume_24h=0,
                    market_cap=0,
                    data_type="index",
                    source="CoinGecko",
                )
            )

        # TOTAL3 = Total MCap - BTC MCap - ETH MCap (altcoin market)
        btc_mcap = total_mcap * btc_d / 100 if btc_d > 0 else 0
        eth_mcap = total_mcap * eth_d / 100 if eth_d > 0 else 0
        altcoin_mcap = total_mcap - btc_mcap - eth_mcap
        if altcoin_mcap > 0:
            points.append(
                MarketDataPoint(
                    symbol="TOTAL3",
                    price=altcoin_mcap,
                    change_24h=0,
                    volume_24h=0,
                    market_cap=0,
                    data_type="index",
                    source="CoinGecko",
                )
            )

        return points

    except Exception as e:
        logger.warning(f"CoinGecko global failed: {e}")
        return []


async def _collect_usdt_vnd() -> list[MarketDataPoint]:
    """Collect USDT/VND P2P rate (FR10b).

    Fallback chain: Binance P2P → HTX OTC → CoinGecko (official rate).
    P2P rates reflect actual trading price in Vietnam (~3-4% premium over official).
    """
    # 1. Binance P2P — highest liquidity in VN
    rate = await _fetch_binance_p2p_vnd()
    if rate:
        return [rate]

    # 2. HTX (Huobi) OTC — independent P2P source
    rate = await _fetch_htx_otc_vnd()
    if rate:
        return [rate]

    # 3. CoinGecko official rate (last resort)
    logger.warning("USDT/VND: P2P sources failed, falling back to CoinGecko official rate")
    return await _fetch_coingecko_vnd()


async def _fetch_binance_p2p_vnd() -> MarketDataPoint | None:
    """Fetch USDT/VND from Binance P2P (median of top 5 BUY ads)."""
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; CIC-Daily-Report/1.0)",
    }
    body = {
        "asset": "USDT",
        "fiat": "VND",
        "tradeType": "BUY",
        "page": 1,
        "rows": 5,
        "payTypes": [],
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()

        data = resp.json()
        ads = data.get("data", [])
        if not ads:
            logger.warning("Binance P2P: no ads returned")
            return None

        prices = sorted(float(ad["adv"]["price"]) for ad in ads if "adv" in ad)
        if not prices:
            return None

        # Median price for stability
        mid = len(prices) // 2
        median_price = prices[mid] if len(prices) % 2 else (prices[mid - 1] + prices[mid]) / 2

        logger.info(f"Binance P2P USDT/VND: {median_price:,.0f} (from {len(prices)} ads)")
        return MarketDataPoint(
            symbol="USDT/VND",
            price=median_price,
            change_24h=0,
            volume_24h=0,
            market_cap=0,
            data_type="macro",
            source="Binance P2P",
        )

    except Exception as e:
        logger.warning(f"Binance P2P USDT/VND failed: {e}")
        return None


async def _fetch_htx_otc_vnd() -> MarketDataPoint | None:
    """Fetch USDT/VND from HTX (Huobi) OTC market."""
    url = "https://otc-api.trygofast.com/v1/data/trade-market"
    params = {
        "coinId": 2,       # USDT
        "currencyId": 75,  # VND
        "tradeType": "buy",
        "blockType": "general",
        "online": 1,
        "range": 0,
        "payMethod": 0,
        "page": 1,
        "size": 3,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()

        data = resp.json()
        trades = data.get("data", [])
        if not trades:
            logger.warning("HTX OTC: no trades returned")
            return None

        price = float(trades[0].get("price", 0))
        if price <= 0:
            return None

        logger.info(f"HTX OTC USDT/VND: {price:,.0f}")
        return MarketDataPoint(
            symbol="USDT/VND",
            price=price,
            change_24h=0,
            volume_24h=0,
            market_cap=0,
            data_type="macro",
            source="HTX OTC",
        )

    except Exception as e:
        logger.warning(f"HTX OTC USDT/VND failed: {e}")
        return None


async def _fetch_coingecko_vnd() -> list[MarketDataPoint]:
    """Fetch USDT/VND official rate from CoinGecko (last resort fallback)."""
    url = "https://api.coingecko.com/api/v3/simple/price"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                url,
                params={
                    "ids": "tether",
                    "vs_currencies": "vnd",
                    "include_24hr_change": "true",
                },
            )
            resp.raise_for_status()

        data = resp.json()
        tether = data.get("tether", {})
        vnd_price = float(tether.get("vnd", 0))
        vnd_change = float(tether.get("vnd_24h_change", 0))

        if vnd_price > 0:
            return [
                MarketDataPoint(
                    symbol="USDT/VND",
                    price=vnd_price,
                    change_24h=vnd_change,
                    volume_24h=0,
                    market_cap=0,
                    data_type="macro",
                    source="CoinGecko (official)",
                )
            ]
        return []

    except Exception as e:
        logger.warning(f"CoinGecko USDT/VND failed: {e}")
        return []


def _cross_verify_prices(data: list[MarketDataPoint]) -> list[MarketDataPoint]:
    """Cross-verify CoinLore vs MEXC prices (FR22).

    If deviation >5% for any symbol, log warning.
    Removes MEXC duplicates when CoinLore has the same symbol (CoinLore is primary).
    Keeps MEXC-only symbols (coins not in CoinLore top 50).
    """
    coinlore: dict[str, MarketDataPoint] = {}
    mexc: dict[str, MarketDataPoint] = {}

    for p in data:
        if p.source == "CoinLore" and p.data_type == "crypto":
            coinlore[p.symbol] = p
        elif p.source == "MEXC":
            mexc[p.symbol] = p

    for symbol in coinlore:
        if symbol not in mexc:
            continue
        cl_price = coinlore[symbol].price
        mx_price = mexc[symbol].price
        if cl_price == 0 or mx_price == 0:
            continue
        avg = (cl_price + mx_price) / 2
        deviation = abs(cl_price - mx_price) / avg * 100
        if deviation > 5:
            logger.warning(
                f"FR22: {symbol} price deviation {deviation:.1f}% "
                f"(CoinLore=${cl_price:.2f} vs MEXC=${mx_price:.2f})"
            )

    # Remove MEXC duplicates — keep CoinLore as primary (has market cap)
    mexc_only_symbols = set(mexc.keys()) - set(coinlore.keys())
    return [p for p in data if p.source != "MEXC" or p.symbol in mexc_only_symbols]


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


async def _collect_altcoin_season() -> list[MarketDataPoint]:
    """Collect Altcoin Season Index (FR10)."""
    urls = [
        "https://api.blockchaincenter.net/api/altcoin-season-index",
        "https://api.blockchaincenter.net/api/altcoin-season-index?t=30",
    ]
    for url in urls:
        try:
            async with httpx.AsyncClient(timeout=15, verify=False) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.warning(
                        f"Altcoin Season Index: HTTP {resp.status_code} from {url}"
                    )
                    continue
                data = resp.json()
                value = float(data.get("value", 50))
                # Validate range: ensure 0 <= value <= 100
                if not (0 <= value <= 100):
                    logger.warning(f"Altcoin Season Index out of range: {value}")
                    value = max(0, min(100, value))
                return [
                    MarketDataPoint(
                        symbol="Altcoin_Season",
                        price=value,
                        change_24h=0,
                        volume_24h=0,
                        market_cap=0,
                        data_type="index",
                        source="BlockchainCenter",
                    )
                ]
        except Exception as e:
            logger.warning(f"Altcoin Season Index failed ({url}): {e}")

    # Fallback: return neutral default so report is not missing this metric
    logger.warning("Altcoin Season Index: all sources failed, using fallback value 50")
    return [
        MarketDataPoint(
            symbol="Altcoin_Season",
            price=50,
            change_24h=0,
            volume_24h=0,
            market_cap=0,
            data_type="index",
            source="BlockchainCenter (fallback)",
        )
    ]
