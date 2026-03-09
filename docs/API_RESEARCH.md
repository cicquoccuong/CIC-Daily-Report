# API Research — Data Source Audit (2026-03-09)

> Research kỹ trước khi implement. Mỗi API đều verified live hoặc confirmed từ docs.

## Tóm tắt quyết định

| FR | API | Free? | Quyết định | Lý do |
|----|-----|-------|-----------|-------|
| FR6 | MEXC `/api/v3/ticker/24hr` | Yes, no key | **LÀM** | Sentinel đã dùng, verified |
| FR10b | CoinGecko `simple/price?ids=tether&vs_currencies=vnd` | Yes, no key | **LÀM** | Verified live |
| FR20 | CoinLore `/api/global/` | Yes, no key | **LÀM** | btc_d + total_mcap |
| FR22 | CoinLore vs MEXC comparison | — | **LÀM** | Flag deviation >5% |
| FR5 | Coinglass v4 Liquidations | No ($29/mo) | **DEFER** | Vi phạm $0/month target |
| FR10a | Coinglass v4 Altcoin Season | No ($29/mo) | **DEFER** | Không có free source |
| FR21 | Bilingual EN→VN | — | **ACCEPT** | AI generate trực tiếp tiếng Việt |
| FR44 | Sentinel integration | — | **DEFER** | Phase 2 |

---

## 1. MEXC Public API (FR6)

**Endpoint**: `GET https://api.mexc.com/api/v3/ticker/24hr`
- Không cần API key
- 1 request = ALL tickers (~2000+ pairs)
- Rate limit: 500 req/10s (rất generous)

**Response format** (verified live):
```json
{
  "symbol": "BTCUSDT",
  "lastPrice": "67535.25",
  "priceChangePercent": "0.007",
  "prevClosePrice": "67062.81",
  "openPrice": "67062.81",
  "highPrice": "68199.99",
  "lowPrice": "65633.93",
  "volume": "14533.65",
  "quoteVolume": "973690933.7"
}
```

**Fields cần extract**: `lastPrice`, `priceChangePercent`, `quoteVolume`

**Sentinel reference**: `Worker_1_Market_Data.gs` lines 1087-1166
- Symbol matching: `{SYMBOL}USDT` format
- Consensus weight: 0.35 (equal to OKX)

---

## 2. CoinGecko USDT/VND (FR10b)

**Endpoint**: `GET https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=vnd&include_24hr_change=true`
- Free, no key (Demo plan)
- Rate limit: 30 calls/min

**Response** (verified live):
```json
{
  "tether": {
    "vnd": 26287,
    "vnd_24h_change": 0.264,
    "last_updated_at": 1773038019
  }
}
```

**Alternatives considered**:
- Binance P2P: Deprecated/unreliable, undocumented
- ExchangeRate-API: Only fiat USD/VND, not USDT/VND

---

## 3. CoinLore Global (FR20 — BTC Dominance + Total MCap)

**Endpoint**: `GET https://api.coinlore.net/api/global/`
- Free, no key, no rate limit
- Đã dùng `/api/tickers/` trong market_data.py

**Response format**:
```json
[{
  "coins_count": 14200,
  "active_markets": 52000,
  "total_mcap": 2450000000000,
  "total_volume": 95000000000,
  "btc_d": "52.15",
  "eth_d": "16.80",
  "mcap_change": "1.25",
  "volume_change": "-2.30"
}]
```

**Fields cần extract**: `btc_d` → "BTC Dominance", `total_mcap` → "Total Market Cap"

---

## 4. Coinglass — DEPRECATION WARNING

### Hiện tại đang dùng (v2 — DEPRECATED):
```
https://open-api.coinglass.com/public/v2/funding?symbol=BTC
https://open-api.coinglass.com/public/v2/open_interest?symbol=BTC
```
- Header: `coinglassSecret: {API_KEY}`
- **v2 đã deprecated**, có thể ngừng bất cứ lúc nào

### v4 (mới):
```
https://open-api-v4.coinglass.com/api/futures/...
```
- Header: `CG-API-KEY: {API_KEY}`
- Free plan: 10,000 calls/month, chỉ real-time market data
- Liquidation history + Altcoin Season: Cần Hobbyist plan ($29/mo)

### Khuyến nghị:
1. **Ngắn hạn**: Giữ v2 endpoints, chạy được thì chạy, fail thì graceful degrade
2. **Trung hạn**: Migrate sang v4 khi v2 ngừng hoạt động
3. **Dài hạn**: Nếu cần Liquidations/Altcoin Season → nâng plan Coinglass

---

## 5. Sentinel Consensus Pricing (Reference cho FR22)

Sentinel dùng weighted average với deviation detection:

**Source weights**:
| Source | Weight |
|--------|--------|
| MEXC | 0.35 |
| OKX | 0.35 |
| DexScreener | 0.25 |
| CoinLore | 0.20 |

**Consensus algorithm**:
```
consensus_price = sum(price_i × weight_i) / sum(weight_i)
deviation = max(|price_i - avg| / avg × 100)
```

**Daily Report simplified version** (CoinLore + MEXC only):
- Fetch cả 2 nguồn
- So sánh: nếu deviation >5% → flag warning, dùng average
- Nếu ≤5% → dùng CoinLore price (đã có sẵn)
- Nếu 1 nguồn fail → dùng nguồn còn lại (no cross-verify)

---

## 6. Fear & Greed Index (đã implement, reference)

**Endpoint**: `GET https://api.alternative.me/fng/?limit=1`
- Free, no key
- Rate limit: 60 req/min

**Note**: Alternative.me KHÔNG có Altcoin Season API. Trang web có nói "coming soon" nhưng chưa có.
