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
                    change_24h=pct_change * 100,  # MEXC returns decimal (0.023 = 2.3%)
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
        "coinId": 2,  # USDT
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
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.warning(f"Altcoin Season Index: HTTP {resp.status_code} from {url}")
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
    # ⚠️ Marked as synthetic — LLM and metrics engine should NOT interpret this as real data
    logger.warning("Altcoin Season Index: all sources failed, using SYNTHETIC fallback value 50")
    return [
        MarketDataPoint(
            symbol="Altcoin_Season",
            price=50,
            change_24h=0,
            volume_24h=0,
            market_cap=0,
            data_type="index",
            source="SYNTHETIC (BlockchainCenter unavailable)",
        )
    ]


# ---------------------------------------------------------------------------
# Technical Indicators: RSI 14d, MA50, MA200 for BTC/ETH (P1.11)
# ---------------------------------------------------------------------------


@dataclass
class TechnicalIndicators:
    """Technical analysis indicators for a single asset (P1.11).

    Computed from yfinance daily OHLCV data using standard formulas:
    - RSI uses Wilder's smoothing (matches TradingView default)
    - MA = Simple Moving Average of daily close prices
    """

    symbol: str  # "BTC" or "ETH"
    rsi_14d: float
    ma_50: float
    ma_200: float
    price_vs_ma50: str  # "above" or "below"
    price_vs_ma200: str  # "above" or "below"
    golden_cross: bool  # MA50 > MA200
    rsi_signal: str  # "overbought" / "neutral" / "oversold"
    source: str = "yfinance"


def _calculate_rsi(closes: list[float], period: int = 14) -> float:
    """Calculate RSI using Wilder's smoothing (exponential moving average).

    WHY Wilder's: This matches TradingView's default RSI, which is the industry
    standard CIC members compare against. Simple-average RSI diverges significantly.

    Args:
        closes: List of closing prices, oldest first. Needs >= period+1 values.
        period: RSI lookback period (default 14).

    Returns:
        RSI value (0-100). Returns 50.0 if insufficient data.
    """
    if len(closes) < period + 1:
        return 50.0  # neutral fallback when insufficient data

    # Calculate price changes
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    # Seed: simple average of first `period` gains/losses
    gains = [max(d, 0) for d in deltas[:period]]
    losses = [abs(min(d, 0)) for d in deltas[:period]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    # Wilder's smoothing for remaining deltas
    for d in deltas[period:]:
        gain = max(d, 0)
        loss = abs(min(d, 0))
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    # WHY: Flat prices (no movement) means avg_gain=0 AND avg_loss=0.
    # This is neutral (50.0), not bullish. Must check before avg_loss==0.
    if avg_gain == 0 and avg_loss == 0:
        return 50.0  # flat prices — no gains, no losses → neutral
    if avg_loss == 0:
        return 100.0  # all gains, no losses
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _yf_get_technical(ticker: str) -> dict | None:
    """Sync yfinance fetch for technical indicator computation (run in thread).

    Fetches 210 daily candles — enough for MA200 + 10 buffer days for weekends/holidays.
    Returns dict with closes list and current price, or None on failure.
    """
    import yfinance as yf

    t = yf.Ticker(ticker)
    # WHY 250 days: MA200 needs 200 points. yfinance "1y" = ~252 trading days.
    # Using explicit period to ensure enough data even with holidays.
    hist = t.history(period="1y")
    if hist.empty or len(hist) < 50:
        # Need at least 50 for MA50; fewer means data is unreliable
        return None

    closes = hist["Close"].tolist()
    return {"closes": closes, "current_price": closes[-1]}


async def collect_technical_indicators() -> list[TechnicalIndicators]:
    """Collect RSI 14d, MA50, MA200 for BTC and ETH (P1.11).

    Separate from collect_market_data() to keep return types clean.
    Uses asyncio.to_thread() since yfinance is synchronous (established pattern).

    Returns:
        List of TechnicalIndicators (0-2 items). Empty list on total failure.
    """
    try:
        import yfinance as _yf  # noqa: F401
    except ImportError:
        logger.warning("yfinance not installed — skipping technical indicators")
        return []

    # WHY BTC-USD and ETH-USD: These are the two core assets CIC tracks.
    # Spec Section 2.5 explicitly requires these two.
    targets = [("BTC-USD", "BTC"), ("ETH-USD", "ETH")]
    indicators: list[TechnicalIndicators] = []

    async def _fetch_one(ticker: str, label: str) -> TechnicalIndicators | None:
        try:
            data = await asyncio.to_thread(_yf_get_technical, ticker)
            if not data:
                logger.warning(f"Technical indicators: no data for {label}")
                return None

            closes = data["closes"]
            current = data["current_price"]

            rsi = _calculate_rsi(closes, 14)

            # MA50 and MA200 — use as many closes as available
            ma_50 = sum(closes[-50:]) / min(len(closes), 50) if len(closes) >= 50 else 0.0
            ma_200 = sum(closes[-200:]) / min(len(closes), 200) if len(closes) >= 200 else 0.0

            # Determine signals
            if rsi > 70:
                rsi_signal = "overbought"
            elif rsi < 30:
                rsi_signal = "oversold"
            else:
                rsi_signal = "neutral"

            return TechnicalIndicators(
                symbol=label,
                rsi_14d=round(rsi, 1),
                ma_50=round(ma_50, 2),
                ma_200=round(ma_200, 2) if ma_200 > 0 else 0.0,
                price_vs_ma50="above" if current > ma_50 else "below",
                price_vs_ma200=("above" if ma_200 > 0 and current > ma_200 else "below"),
                golden_cross=ma_50 > ma_200 if ma_200 > 0 else False,
                rsi_signal=rsi_signal,
            )
        except Exception as e:
            logger.warning(f"Technical indicators for {label} failed: {e}")
            return None

    tasks = [_fetch_one(ticker, label) for ticker, label in targets]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for r in results:
        if isinstance(r, TechnicalIndicators):
            indicators.append(r)
        elif isinstance(r, Exception):
            logger.warning(f"Technical indicator task failed: {r}")

    logger.info(f"Technical indicators collected: {len(indicators)} assets")
    return indicators


def format_technical_for_llm(indicators: list[TechnicalIndicators]) -> str:
    """Format technical indicators as LLM-readable text block.

    Output example:
        === CHI BAO KY THUAT (nguon: yfinance) ===
        BTC: RSI(14) = 45.2 (Trung tinh) | MA50 = $68,500 | MA200 = $62,300 | Golden Cross
        ETH: RSI(14) = 38.7 (Trung tinh) | MA50 = $3,200 | MA200 = $2,800 | Golden Cross
    """
    if not indicators:
        return ""

    # WHY Vietnamese labels: matches existing market_text format for LLM consistency
    signal_labels = {
        "overbought": "Qua mua",
        "oversold": "Qua ban",
        "neutral": "Trung tinh",
    }

    lines = ["=== CHI BAO KY THUAT (nguon: yfinance) ==="]
    for ind in indicators:
        label = signal_labels.get(ind.rsi_signal, ind.rsi_signal)
        cross = "Golden Cross" if ind.golden_cross else "Death Cross"
        # WHY conditional MA200: if 0, data insufficient — don't show misleading "MA200 = $0"
        ma200_str = f" | MA200 = ${ind.ma_200:,.0f}" if ind.ma_200 > 0 else ""
        line = (
            f"{ind.symbol}: RSI(14) = {ind.rsi_14d} ({label}) | MA50 = ${ind.ma_50:,.0f}{ma200_str}"
        )
        if ind.ma_200 > 0:
            line += f" | {cross}"
        lines.append(line)

    return "\n".join(lines)
