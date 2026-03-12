---
stepsCompleted: [1, 2, 3, 4]
inputDocuments: []
session_topic: 'CIC Daily Crypto Report — Hệ thống tự động tổng hợp & phân tích tin tức crypto 24h'
session_goals: 'Thu thập dữ liệu đa nguồn, AI phân tích chuyên sâu, gửi bản tin sáng qua Telegram, anh Cường copy-paste lên BIC Chat cho 5 tier thành viên CIC'
selected_approach: 'ai-recommended'
techniques_used: ['Mind Mapping', 'Morphological Analysis', 'Six Thinking Hats', 'What-If Persona Analysis']
ideas_generated: 152
technique_execution_complete: true
facilitation_notes: 'Session cực kỳ productive — anh Cường liên tục phát hiện gaps quan trọng (spam filter, realtime alerts, tier-based content, BIC Chat constraints). Nhiều pivot moments mở ra hướng mới. POST-SESSION: Cross-referenced với CIC Sentinel experience → Binance block VN, CoinGecko rate limit → đã cập nhật MVP combo (MEXC+CoinLore thay Binance+CoinGecko). DEEP RESEARCH (04/03/2026): +11 new international sources (crypto.news, protos.com, bitcoinist.com, cryptopotato.com, finbold.com, cryptodaily.co.uk, cryptonews.com), +2 VN sources (blogtienao.com, bitcoinvn.io), free-crypto-news open-source MCP aggregator, BIS/IMF/Fed regulatory RSS, Stacy_muur framework mapped to CIC pipeline (100% aligned). Layer 5→7 hybrid strategy upgrade.'
---

# CIC Daily Crypto Report — Brainstorming Session

**Facilitator:** Anh Cường
**Date:** 2026-03-03
**Total Ideas Generated:** 152
**Techniques Used:** Mind Mapping → Morphological Analysis → Six Thinking Hats → What-If Persona Analysis

---

## I. PROJECT OVERVIEW

### Mục tiêu
Xây dựng hệ thống tự động thu thập tin tức crypto 24h từ 37+ nguồn (10 web + 27 Telegram channels), AI phân tích chuyên sâu, tạo report chất lượng hơn con người, gửi qua Telegram mỗi sáng. Anh Cường copy-paste lên BIC Chat (Beincom) cho cộng đồng CIC 2,278+ thành viên.

### Constraints
- **Budget:** Zero cost — toàn bộ free tier
- **Infrastructure:** Không có VPS, dùng free cloud
- **AI Models:** Gemini (Google) + Groq, backup các nguồn AI free khác
- **BIC Chat:** Không có API — phải post thủ công
- **NQ05 Compliance:** Nghị quyết 05/2025/NQ-CP — hạn chế nêu tên token
- **1-person operation:** Anh Cường là người duy nhất post content
- **Timeline MVP:** Ngày 04/03/2026

### Platforms
- **Input:** Telegram channels + APIs (CryptoPanic, CoinGecko, Binance, alternative.me)
- **Processing:** GitHub Actions + Gemini + Groq + Python
- **Output:** Telegram Bot → Anh Cường → BIC Chat (manual copy-paste)
- **Community:** Beincom (BIC Chat) — ICS structure, 5 tier levels

---

## II. DATA SOURCES — 37+ Nguồn

### Web Sources (10)

| # | Source | URL | Loại dữ liệu |
|---|--------|-----|--------------|
| 1 | SoSoValue | sosovalue.com | ETF flows, market data |
| 2 | HulkCrypto | hulkcrypto.com | Crypto news |
| 3 | 5PhutCrypto | 5phutcrypto.io | VN crypto news |
| 4 | Coin68 | coin68.com | VN crypto news |
| 5 | Coin98 | coin98.net | VN crypto ecosystem |
| 6 | Alternative.me | alternative.me/crypto/fear-and-greed-index/ | Fear & Greed Index |
| 7 | Blockchain Center | blockchaincenter.net/en/altcoin-season-index/ | Altcoin Season Index |
| 8 | PriceDancing | pricedancing.com/vi/Binance-P2P-USDT-VND-chart-ZqzaQWc | USDT/VND P2P chart |
| 9 | CoinMarketCap | coinmarketcap.com | Market data |
| 10 | CryptoRank | cryptorank.io | Rankings, data |

### Telegram Channels (27) — TẤT CẢ ĐỀU PUBLIC

#### Tier 1 — Quality Insight (10 kênh, ưu tiên cao nhất)

| # | Username | Tên | Subscribers | Ngôn ngữ |
|---|----------|-----|------------|----------|
| 1 | @HCCapital_Channel | HC CAPITAL | 75,421 | VN |
| 2 | @Fivemincryptoann | 5 Phut Crypto | 62,960 | VN |
| 3 | @coin369channel | Tin nhanh - Coin369 | 12,628 | VN |
| 4 | @vnwallstreet | VN Wall Street | 31,170 | VN |
| 5 | @kryptonewsresearch | Krypto News Research | 415 | VN |
| 6 | @hctradecoin_channel | HC Tradecoin | 38,994 | VN |
| 7 | @Coin98Insights | Upside (Coin98) | 31,017 | VN |
| 8 | @A1Aofficial | A1Academy | 43,169 | VN |
| 9 | @coin68 | Coin68 | 27,615 | VN |
| 10 | @wublockchainenglish | Wu Blockchain | 323,669 | EN |

#### Tier 2 — Major News (7 kênh)

| # | Username | Tên | Subscribers | Ngôn ngữ |
|---|----------|-----|------------|----------|
| 11 | @cointelegraph | Cointelegraph | 388,397 | EN |
| 12 | @binance_announcements | Binance | 4,574,927 | EN |
| 13 | @WatcherGuru | Watcher Guru | 627,618 | EN |
| 14 | @CryptoRankNews | CryptoRank Analytics | 859,431 | EN |
| 15 | @layergg | Layergg | 21,209 | VN |
| 16 | @bitcoin | Bitcoin | 215,508 | EN |
| 17 | @coffeecryptonews | Coffee Crypto News | 11,644 | VN |

#### Tier 3 — Data Alerts (Structured, dễ parse) (8 kênh)

| # | Username | Tên | Subscribers | Loại data |
|---|----------|-----|------------|-----------|
| 18 | @whale_alert_io | Whale Alert | 327,631 | Whale transactions |
| 19 | @cryptoquant_official | CryptoQuant | 56,575 | On-chain analytics |
| 20 | @cryptoquant_alert | CryptoQuant Alert | 77,248 | On-chain alerts |
| 21 | @FundingRates1 | Funding Rates | 5,606 | Funding rate data |
| 22 | @oi_detector | OI Pump/Dump Screener | 5,205 | Open Interest |
| 23 | @bitcoin_price | Bitcoin Price | 60,695 | BTC price alerts |
| 24 | @eth_price | ETH Price | 16,109 | ETH price alerts |
| 25 | @Database52Hz | 52Hz Database | 9,456 | VN on-chain data |

#### Groups (2 — xử lý khác channels)

| # | Username | Tên | Members |
|---|----------|-----|---------|
| 26 | @Coinank_Community | CoinAnk Community | 3,168 |
| 27 | @messaricrypto | Messari | 6,220 |

### API Sources (Bổ sung)

| API | Free Tier | Dữ liệu | Ghi chú |
|-----|-----------|----------|---------|
| CryptoPanic | 5 req/min | Tin tức aggregated + sentiment | Anh Cường đã có account |
| CoinGecko | 10 RPM free (10K/month) | Giá, market cap, volume, 14,000+ assets | ⚠️ **HAY BỊ RATE LIMIT** — CIC Sentinel đã demote xuống fallback |
| CoinLore | Không giới hạn, không cần key | Market cap, giá | ✅ Sentinel dùng thay CoinGecko cho price data |
| CryptoCompare | 100K calls/month free | Social + Dev data | ✅ Sentinel PRIMARY cho social data (v9.0.84+) |
| MEXC Public | 500 req/min, không cần key | Giá, OHLCV, volume | ✅ **Sentinel PRIMARY (35% weight)** — hoạt động tốt ở VN |
| OKX Public | 20 req/min | Giá, OHLCV | ✅ Sentinel FALLBACK (35% weight) — hoạt động ở VN |
| DexScreener | ~60 req/min | DEX-only coins, giá | ✅ Cho coins chỉ có trên DEX |
| CoinPaprika | 25K/month free | Social + GitHub, ATH data | Top 100 coins |
| DeFiLlama | 300/5min (rất rộng rãi) | TVL, DeFi metrics, hacks | ✅ Không cần API key |
| alternative.me | Free | Fear & Greed Index | 1 call/ngày là đủ |
| NewsData.io | Free tier | Tin tức tổng hợp | |
| CoinMarketCap | Free tier | Rankings, market data | |
| Messari | Free tier | Research data | |
| CoinDesk API | Free tier | Tin tức, market data | (formerly CryptoCompare News) |
| FlowHunt | Free tier | Crypto Sentiment MCP | AI sentiment analysis tool |
| Apify | Free tier | Cointelegraph Scraper | Web scraping marketplace |

### ⚠️ BÀI HỌC TỪ CIC SENTINEL — API DATA SOURCES

> **CRITICAL**: Dựa trên kinh nghiệm thực tế xây dựng CIC Sentinel (210 assets, 10-worker pipeline):

**1. Binance API ĐÃ BỊ BLOCK IP VIỆT NAM:**
- CIC Sentinel đã phải **vô hiệu hóa Binance** (`SOURCE_AVAILABLE.BINANCE: false`)
- Binance chỉ còn weight 0.1 (10%), đánh dấu "often blocked"
- **Giải pháp Sentinel**: Chuyển sang MEXC (35%) + OKX (35%) + DexScreener (25%) + CoinLore (20%)
- **Áp dụng cho Daily Report**: Dùng **MEXC Public API** thay Binance cho OHLCV data (TA engine)
- **USDT/VND**: Cần dùng PriceDancing scrape hoặc P2P aggregator thay Binance P2P API

**2. CoinGecko THƯỜNG XUYÊN BỊ RATE LIMIT:**
- Free tier chỉ 10 RPM, ~10K calls/month → dễ bị 429 Too Many Requests
- CIC Sentinel đã **demote CoinGecko xuống fallback** từ v7.0.2
- **Giải pháp Sentinel**: CoinLore (price, no limit) + CryptoCompare (social, 100K/month)
- CoinGecko Pro: $129/month — KHÔNG phù hợp zero-cost
- **Áp dụng cho Daily Report**: Dùng **CoinLore + CryptoCompare** làm primary, CoinGecko backup

**3. Các API free đáng tin cậy đã test trong Sentinel:**
| API | Ổn định | Rate Limit | Dùng cho |
|-----|---------|-----------|----------|
| MEXC | ⭐⭐⭐⭐⭐ | 500/min | Price + OHLCV (thay Binance) |
| CoinLore | ⭐⭐⭐⭐⭐ | Không giới hạn | Market cap, giá |
| DeFiLlama | ⭐⭐⭐⭐⭐ | 300/5min | TVL, DeFi |
| CryptoCompare | ⭐⭐⭐⭐ | 100K/month | Social + Dev data |
| OKX | ⭐⭐⭐⭐ | 20/min (strict) | Price fallback |
| DexScreener | ⭐⭐⭐⭐ | ~60/min | DEX-only coins |
| CoinPaprika | ⭐⭐⭐ | 25K/month | ATH, social |
| CoinGecko | ⭐⭐ | 10 RPM | ⚠️ Fallback only |

**4. QuotaManager Pattern (từ Sentinel):**
- Pre-call quota checking → block trước khi gọi API
- Daily limits config per API
- Circuit breaker: 3 consecutive 429 → open circuit → auto-recover sau 30 min
- Alert thresholds: 70% warning → 90% critical → 100% block
- **Áp dụng**: Implement tương tự cho Daily Report pipeline

### ⚡ FULL ARTICLE EXTRACTION — RSS & Web Scraping (Research 04/03/2026)

> **INSIGHT**: Bài viết đầy đủ trên web chứa insight sâu hơn rất nhiều so với TG summaries. Ví dụ: Upside (@Coin98Insights) post TG tóm tắt 3 dòng về Kevin Warsh, nhưng bài gốc trên coin98.net dài 5,000+ từ với phân tích chuyên sâu về CBDC, Bitcoin regulation, FED policy.

#### Tier 1 — RSS Full Content (KHÔNG cần scraping, parse trực tiếp)

| Site | RSS URL | Ngôn ngữ | Content | robots.txt |
|------|---------|----------|---------|------------|
| **cryptoslate.com** | `/feed/` | EN | Full HTML articles | Permissive |
| **blockonomi.com** | `/feed/` | EN | Full HTML articles | Very permissive |
| **bitcoinmagazine.com** | `/feed` | EN | Full HTML articles | Moderate |
| **beincrypto.com** | `/feed/` | EN | Full HTML articles | Restrictive web, OK RSS |
| **newsbtc.com** | `/feed/` | EN | Full HTML articles | Moderate |
| **5phutcrypto.io** | `/feed` | **VN** | Full HTML (2K-5K+ từ) | Moderate |
| **hulkcrypto.com** | `/feed` | **VN** | Full HTML articles | Minimal |

#### Tier 2 — RSS Discovery + Page Scraping (RSS cho links, scrape full text)

| Site | RSS URL | Scraping Tool | Khó khăn |
|------|---------|---------------|----------|
| **coin98.net** | `/rss/tin-moi-nhat.rss` | trafilatura / newspaper4k | Next.js rendered |
| **coin68.com** | `/rss/tin-tong-hop.rss` | trafilatura | WordPress-based |
| **decrypt.co** | `/feed` | trafilatura | Very permissive robots.txt |
| **cryptobriefing.com** | `/feed/` | trafilatura | Very permissive + có `llms.txt` |
| **cointelegraph.com** | `/rss` | trafilatura | Restrictive nhưng vẫn scrapable |
| **u.today** | `/rss` | trafilatura | Drupal-based |

#### Tier 3 — Khó truy cập (paywall/restrictions)

| Site | Vấn đề |
|------|--------|
| **theblock.co** | Partial paywall, 403 on robots.txt |
| **coindesk.com** | Empty `content:encoded`, blocks AI bots |
| **ambcrypto.com** | Explicitly blocks `/feed/` in robots.txt |

#### Python Stack cho Article Extraction

```python
# 1. RSS full-content feeds (7 sites)
import feedparser  # Parse RSS → full articles

# 2. Page scraping (accuracy ranking)
import trafilatura      # F1=0.958 — BEST accuracy, 50+ languages
from newspaper import Article  # newspaper4k — F1=0.949, NLP summary
from readability import Document  # readability-lxml — F1=0.922, fastest

# 3. External service (fallback)
# Jina AI Reader: r.jina.ai/{URL} → Markdown output
# Free: 20 req/min (no key), 200 req/min (free key)
```

#### News Aggregator APIs

| API | Free Tier | Full Text? | Crypto Filter? | Ghi chú |
|-----|-----------|------------|---------------|---------|
| **CryptoPanic** | ~100 req/day | No (có `original_url` để follow) | Yes (currencies) | Đã có account, sentiment data |
| **Event Registry** | 2K tokens/month | **YES (all plans!)** | Keyword search | Best free full-text API |
| **NewsData.io** | 200/day, 12h delay | Paid only ($45/m) | Yes (`/crypto`) | Dedicated crypto endpoint |
| **CryptoNews API** | 5-day trial only | No (copyright) | Yes (600+ tickers) | Sentiment + whale data |
| **GNews.io** | 100 req/day | Paid only | No (keyword) | General news |

#### Chiến lược Hybrid cho CIC Daily Report

```
┌─ LAYER 1: RSS Full Content (7 sites, ~50-100 bài/ngày)
│  feedparser → parse trực tiếp → full articles
│
├─ LAYER 2: TG Link Following (27 channels)
│  Telethon fetch → extract URLs from TG messages
│  → trafilatura/newspaper4k scrape full article
│  → Ví dụ: @Coin98Insights post TG summary + link coin98.net
│    → follow link → scrape 5,000 từ full article
│
├─ LAYER 3: CryptoPanic API (100+ nguồn)
│  API call → get original_url → trafilatura scrape
│  + sentiment/votes metadata
│
├─ LAYER 4: Event Registry (2K tokens/month)
│  Full text search → full article body
│  Dùng cho important stories cần cross-reference
│
└─ LAYER 5: Structured Data APIs
   CoinLore + MEXC + alternative.me + DeFiLlama
   → Giá, market cap, Fear&Greed, TVL
```

> **Tham khảo quy trình research của Stacy_muur:**
> 1. Discovery → 2. Data Aggregation → 3. Validation & Normalization → 4. Pattern Detection → 5. Narrative Mapping → 6. Synthesis
> **AI giúp nhất ở:** tổng hợp dữ liệu, phát hiện pattern quy mô lớn, phân tích narrative/sentiment, soạn thảo báo cáo
> **Công cụ tham khảo:** SurfAI (crypto-specific AI research), Minara (DeFi AI agent)

### 🔬 EXPANDED SOURCE RESEARCH — Deep Dive (04/03/2026)

> **Yêu cầu**: Research sâu hơn để tìm thêm nguồn NGOÀI những gì đã có. Insights từ bài Stacy_muur về AI research workflow.

---

#### A. Nguồn Tin Tức Tiếng Việt MỚI

| # | Site | RSS URL | Posts/ngày | DA | Đặc điểm |
|---|------|---------|-----------|-----|----------|
| 1 | **blogtienao.com** | `/feed` | 13 | 42 | 147K FB, 26K Twitter — rất active, VN crypto news tổng hợp |
| 2 | **bitcoinvn.io/news** | `/news/feed` | Vừa phải | ~30 | Bitcoin + crypto + blockchain tại VN, có góc nhìn local |

> **Thực tế**: Nguồn VN chất lượng vẫn khan hiếm — hầu hết đã trong danh sách (coin98, coin68, 5phutcrypto, hulkcrypto). blogtienao là phát hiện mới đáng giá nhất.

---

#### B. Nguồn Tin Tức Quốc Tế MỚI (Chưa có trong danh sách)

| # | Site | RSS URL | Full Content? | Đặc điểm |
|---|------|---------|---------------|----------|
| 1 | **crypto.news** | `/feed` | ✅ Confirmed | Đa dạng, có tag Vietnam — lấy được VN-related EN news |
| 2 | **cryptonews.com** | `/news/feed` | Likely summary | Original coverage global blockchain/crypto |
| 3 | **protos.com** | `/feed` | ✅ Full | Critical/skeptical tone — tốt cho balanced view, chống FOMO |
| 4 | **bitcoinist.com** | `/feed` | ✅ Full | BTC-focused, high volume, permissive |
| 5 | **cryptodaily.co.uk** | `/feed` | ✅ Full | UK-based, broad coverage từ 2017 |
| 6 | **finbold.com** | `/feed` | Likely full | Finance + crypto, stock + crypto correlations |
| 7 | **cryptopotato.com** | `/feed` | ✅ Confirmed | 2014, high DA, balanced analysis |
| 8 | **watcher.guru** | `/news/feed` | Likely full | ⚠️ ĐÃ CÓ trong TG (@WatcherGuru) — dùng TG đủ rồi |

> **🏆 Top picks**: **crypto.news** (có Vietnam tag), **protos.com** (critical/balanced), **bitcoinist.com** (BTC deep), **cryptopotato.com** (long-established quality)

---

#### C. On-Chain Analytics — Free Tier Reality Check

| Tool | Free Tier | Dùng được? | Ghi chú |
|------|-----------|-----------|---------|
| **Glassnode** | Community (rất giới hạn) | ⚠️ Partial | Mostly paid ($29-299+/month). **THAY THẾ**: parse @cryptoquant_official + @whale_alert_io TG (miễn phí hoàn toàn) |
| **Arkham Intelligence** | Limited (basic wallet lookups) | ⚠️ Limited | API cần trả bằng ARKM tokens. Free: chỉ basic tagging + visualization |
| **IntoTheBlock** | ❌ Đã đổi tên → **Sentora** | ❌ No | Legacy app/API đã bị sunset. Không dùng được |
| **Messari** | 20 req/min, free reports | ✅ Partial | 170TB data, OpenAI-compatible API, credit-based. Tốt cho research reports |
| **Glassnode MCP** | Paid | ❌ | MCP Server for AI agents — 2025, nhưng cần paid account |
| **Token Terminal** | Free dashboard | ⚠️ Web only | Protocol revenue, TVL — không có free API |

> **⚡ Kết luận On-Chain**: Chiến lược TG channels (@cryptoquant_alert, @whale_alert_io, @FundingRates1, @oi_detector) = **"Free Glassnode"** — không cần trả tiền, chỉ parse TG messages có cấu trúc.

---

#### D. Social Sentiment & Twitter/X — Thực Tế

| Tool | Cost | RSS/API? | Khuyến nghị |
|------|------|---------|------------|
| **RSSHub** | Free (self-host) | ✅ RSS for X | Cần session auth từ X — phức tạp, fragile |
| **coindive.app** | Freemium | Web only | Crypto Twitter feed aggregator — không có API |
| **Flockler/Tagembed** | Paid | Limited free | Social aggregator — quá tốn kém cho zero-cost |
| **Twitter/X native RSS** | ❌ Đã bỏ | N/A | X đã loại RSS từ 2013 — không dùng trực tiếp |

> **⚡ Kết luận Social**: Tiếp tục dùng **Telegram channels làm proxy cho crypto Twitter** — @WatcherGuru, @cointelegraph, @Coin98Insights đều repost content chất lượng từ X. Không cần build X integration riêng.

---

#### E. Nguồn Vĩ Mô & Pháp Lý — RSS Feed

| Source | RSS URL | Loại content | Relevance |
|--------|---------|-------------|-----------|
| **BIS** | `bis.org/rss/index.htm` | Working Papers, Quarterly Review | ⭐⭐⭐ CBDC, stablecoin regulation |
| **IMF** | `imf.org/en/publications/rss?language=eng&series=World+Economic+Outlook` | WEO, Global Financial Stability | ⭐⭐⭐ Macro outlook |
| **FSB** | `fsb.org/rss-feeds/` | Financial stability publications | ⭐⭐ Crypto regulatory framework |
| **Fed** | `federalreserve.gov/feeds/press_all.xml` | Fed statements, minutes | ⭐⭐⭐ Rate decisions, macro |
| **SEC.gov** | `sec.gov/cgi-bin/browse-edgar?action=getcompany&type=&dateb=&owner=include&count=40&search_text=&action=getcompany` | Enforcement actions | ⭐⭐ Crypto enforcement |

> **⚡ Đề xuất**: Thêm BIS + IMF + Fed vào Layer 4 (Event Registry thay thế được, nhưng RSS trực tiếp cho breaking regulatory news thì nhanh hơn)

---

#### F. News APIs Bổ Sung — Đánh Giá

| API | Free Tier | Full Text | Có dùng không? |
|-----|-----------|-----------|---------------|
| **cryptonews-api.com** | 100 calls/month | ❌ No | ❌ Quá ít — 100 calls/month chỉ đủ vài ngày |
| **free-crypto-news (GitHub)** | Hoàn toàn miễn phí | ✅ RSS/JSON | ✅ **ĐÁNG THỬ** — open-source, MCP server, no API key, Python/JS SDK |
| **Messari AI** | 20 req/min, credit-based | ✅ Reports | ⚠️ Credits depletes — monitor usage. Tốt cho research queries |
| **CryptoPanic** | ~100 req/day | Via follow URL | ✅ **ĐÃ CÓ** — original_url + trafilatura scrape |

> **🏆 Discovery**: [free-crypto-news](https://github.com/nirholas/free-crypto-news) — open-source aggregator, có Claude MCP server, RSS/Atom/JSON, không cần API key. **Thêm vào Layer 1**.

---

#### G. AI Research Tools — Insight cho CIC Daily Report Design

| Tool | Loại | Public API? | Học được gì? |
|------|------|------------|-------------|
| **SurfAI (asksurf.ai)** | Crypto-specific AI research | ❌ Closed | $15M raised, 300K users, 4x ChatGPT on crypto benchmarks. Architecture: on-chain + social + curated X feeds. **Đây là benchmark cho chúng ta** |
| **Minara (minara.ai)** | Web3-native AI CFO | ❌ Closed | 50+ data sources unified, Deep Research mode, automated workflows. Insight: unified data layer là key |
| **Messari AI** | Institutional research | ✅ OpenAI-compat | 170TB data, OpenAI-compatible API, source-grounded (anti-hallucination). **Best reference architecture** |
| **Kaito AI** | Crypto mindshare | No free API | Tracks narrative momentum từ X — tốt cho narrative analysis |

---

#### H. Stacy_muur's Framework — Mapping vào CIC Daily Report

| Stacy_muur's Step | CIC Daily Report tương ứng | Đã có chưa? |
|-------------------|---------------------------|------------|
| **1. Discovery** — Xác định câu hỏi/giả thuyết trước | Master Prompt template (5 sections) | ✅ Đã có |
| **2. Data Aggregation** — On-chain + market + social + raw docs | Layer 1-5 pipeline (TG + RSS + APIs) | ✅ Đã có |
| **3. Validation & Normalization** — Verify source, sync timeframe | Spam Filter + Cross-Reference + Hallucination Guard | ✅ Đã có |
| **4. Pattern Detection** — Whale behavior, TVL spike, new correlations | @cryptoquant_alert + @whale_alert_io + MEXC data | ✅ Partial |
| **5. Narrative Mapping** — Số liệu + bối cảnh: incentive? product? | AI analysis (Gemini bulk) + NQ05 compliance | ✅ Đã có |
| **6. Synthesis** — Report ngắn gọn, rõ ràng, có dẫn chứng, rủi ro+cơ hội | Groq generate + 5-section structure + Disclaimer | ✅ Đã có |

> **✅ Kết luận**: CIC Daily Report architecture **đã align 100% với Stacy_muur's framework** — không cần thay đổi kiến trúc cơ bản. Chỉ cần implement đúng.

> **💡 Insight bổ sung từ Stacy_muur**: "AI phát huy giá trị ở tổng hợp dữ liệu đa chuỗi, phát hiện pattern quy mô lớn, phân tích narrative TRƯỚC KHI giá phản ứng, soạn thảo báo cáo. AI KHÔNG tạo ra alpha — chỉ KHUẾCH ĐẠI judgment của người dùng."

---

#### I. Cập Nhật Chiến Lược Hybrid — 7 Lớp (Nâng từ 5 lớp)

```
┌─ LAYER 1: RSS Full Content (11 sites, ~100-150 bài/ngày)
│  CŨ: cryptoslate, blockonomi, bitcoinmagazine, beincrypto, newsbtc, 5phutcrypto, hulkcrypto
│  MỚI: + crypto.news + protos.com + bitcoinist.com + cryptopotato.com
│
├─ LAYER 2: TG Link Following (27 channels)
│  Telethon → extract URLs → trafilatura scrape full article
│  Ví dụ: @Coin98Insights → coin98.net → 5,000+ từ full article
│
├─ LAYER 3: CryptoPanic API (100+ nguồn)
│  original_url → trafilatura scrape + sentiment metadata
│
├─ LAYER 4: Event Registry / Regulatory RSS (2K tokens/month + BIS/IMF/Fed)
│  Full text important stories + cross-reference macro/regulatory
│  MỚI: BIS/IMF/Fed RSS cho breaking regulatory news
│
├─ LAYER 5: Structured Data APIs
│  CoinLore + MEXC + alternative.me + DeFiLlama + CryptoCompare
│
├─ LAYER 6: Open-Source News Aggregator [MỚI]
│  free-crypto-news (GitHub) — RSS/JSON, no API key, MCP server
│  Có thể feed trực tiếp vào Gemini qua MCP
│
└─ LAYER 7: Macro/Regulatory Intelligence [MỚI]
   BIS RSS + IMF RSS + Fed RSS
   → Regulatory changes TRƯỚC KHI TG channels đăng lại
```

---

#### K. Followin.io & CryptoPanic — Deep Dive (04/03/2026)

##### CryptoPanic — Đánh Giá Chi Tiết API

> **Đã có account — nhưng chưa khai thác hết tiềm năng!**

| Tính năng | Thực tế |
|-----------|---------|
| Free API token | Tại `cryptopanic.com/developers/api/keys` — không cần thẻ |
| Rate limit free | ~100 req/day → đủ cho batch 5AM |
| `original_url` | **LUÔN CÓ** trong mọi post → scrape full text với trafilatura |
| `panic_score` | 0-100 fear/greed per article — sentiment layer độc đáo |
| `votes` | Bullish/Bearish/Important/Toxic community votes — tín hiệu chất lượng |
| `currencies` filter | `?currencies=BTC,ETH,SOL` → khớp 210 assets CIC |
| Nguồn VN | ❌ Coin98/Coin68 KHÔNG có trong index. Regional: en,de,nl,es,fr,it,pt,ru |
| Full text trong API | Enterprise only → workaround: `original_url` + trafilatura |
| Webhook/stream | Không có ở free tier |

```python
# CryptoPanic — Cách dùng tối ưu
def fetch_cryptopanic_hot(currencies="BTC,ETH,SOL,BNB,XRP"):
    r = requests.get("https://cryptopanic.com/api/free/v2/posts/", params={
        "auth_token": CRYPTOPANIC_TOKEN,
        "currencies": currencies,  # filter theo assets CIC đang theo dõi
        "filter": "hot",           # hot | rising | bullish | bearish | important
        "kind": "news",
        "public": True,
    })
    for post in r.json()["results"]:
        # Sentiment layer độc đáo
        print(f"Panic Score: {post.get('panic_score')}")
        print(f"Votes: {post['votes']}")  # bullish/bearish/important/toxic
        # Follow link để scrape full article
        full_text = trafilatura.fetch_url(post["original_url"])
```

> **💡 Chiến lược**: `filter=hot` + `filter=important` → top 20 tin quan trọng nhất ngày → follow `original_url` → scrape full. Dùng `votes.bullish/bearish` làm **community sentiment indicator**.

---

##### Followin.io — Đánh Giá Chi Tiết

> **Không có API nhưng có Vietnamese coverage độc đáo nhất trong tất cả các platforms đã research**

| Tính năng | Thực tế |
|-----------|---------|
| Public API | ❌ Không tồn tại |
| RSS feed | ❌ Không có |
| Vietnamese UI | ✅ Native — 1 trong 5 ngôn ngữ chính |
| VN Community | ✅ @FollowinVietnam Twitter, events Hà Nội, Vietnamese KOL list |
| Nội dung độc đáo | KOL signals (X/Twitter), Mirror, Substack, TG channels, on-chain alerts |
| AI features | F1 News (millisecond alerts), Hot Track leaderboard, sector rotation |
| Web access | ✅ `followin.io/en` + iOS/Android |
| Origin | ChainCatcher ecosystem (China) |

**Workarounds khả thi:**

| Phương pháp | Khả thi? | Ghi chú |
|------------|---------|---------|
| Monitor @FollowinVietnam (X/Twitter) | ✅ | Via nitter RSS hoặc RSSHub |
| Tìm Telegram channel Followin VN | ✅ | Phổ biến với Asian crypto platforms |
| Playwright scrape `followin.io/en` | ⚠️ | JS-rendered, fragile nhưng possible |
| **Manual review 5 phút/ngày** | ✅ Best | Anh Cường check "Hot Track" + "Alpha" trước khi approve report |

> **💡 Recommendation**: Followin.io dùng để **manually check Vietnamese crypto community sentiment** — đặc biệt phần "Hot Track" (sector rotation) và "Alpha Channel" (early signals). Không cần automate.

---

##### Aggregators Mới Phát Hiện — RSS Free

| Site | RSS URL | Format | Đặc biệt |
|------|---------|--------|----------|
| **blockworks.co** | `blockworks.co/feed/` | Full EN articles | Institutional macro + DeFi, regulatory |
| **thedefiant.io** | `thedefiant.substack.com/feed` | Full EN articles | Best DeFi deep-dive (ex-Bloomberg journalist) |
| **milkroad.com** | `milkroad.substack.com/feed` | Daily brief | **Format gần nhất với CIC Daily Report** — 5-min daily, 330K subs |
| **bankless.com** | `bankless.substack.com/feed` | Weekly deep | ETH/L2 ecosystem, 300K subs |

> **🏆 Milk Road**: Daily 5-min crypto brief — format "cái gì đang xảy ra hôm nay" giống nhất CIC Daily Report. Dùng làm **format reference** + content signal.

---

#### J. Revised Source Priority Matrix

```
TIER 1 — Full Content RSS (parse trực tiếp, zero scraping):
✅ cryptoslate.com, blockonomi.com, bitcoinmagazine.com, beincrypto.com
✅ newsbtc.com, 5phutcrypto.io, hulkcrypto.com (CŨ)
🆕 crypto.news, protos.com, bitcoinist.com, cryptopotato.com (MỚI)
🆕 blogtienao.com (VN, 13 posts/ngày) (MỚI)
🆕 blockworks.co, thedefiant.io, milkroad.com, bankless.com (MỚI)

TIER 2 — RSS Discovery + Scrape:
✅ coin98.net, coin68.com, decrypt.co, cryptobriefing.com (CŨ)
✅ cointelegraph.com, u.today (CŨ)
🆕 finbold.com (finance+crypto), cryptonews.com (MỚI)

TIER 3 — API Aggregators:
✅ CryptoPanic (sentiment + 100+ sources)
🆕 free-crypto-news (open-source, MCP)

TIER 4 — On-Chain / Structured:
✅ @whale_alert_io, @cryptoquant_alert, @FundingRates1, @oi_detector (TG)
✅ MEXC, CoinLore, DeFiLlama, CryptoCompare

TIER 5 — Regulatory/Macro:
🆕 BIS RSS (bis.org/rss/index.htm)
🆕 IMF RSS (World Economic Outlook)
🆕 Fed RSS (press_all.xml)
```

---

### 🔬 DEEP RESEARCH 2 — Macro / On-Chain / TA Chuyên Sâu (04/03/2026)

> **Mục tiêu**: Tìm nguồn chất lượng cao cho 3 mảng: Vĩ mô (Fed/CPI/DXY), On-Chain (UTXO/miners/derivatives), TA (indicators/options/market structure)

---

#### MACRO — Nguồn Dữ Liệu Kinh Tế Vĩ Mô

##### APIs Hoàn Toàn Miễn Phí (Automatable)

| Source | Python Library | Key Data Points | Priority |
|--------|---------------|----------------|----------|
| **FRED (Federal Reserve)** | `pip install fredapi` — **FREE API key** | DGS10 (10Y Treasury), DTWEXBGS (DXY proxy), CPIAUCSL (CPI), WALCL (Fed balance sheet), UNRATE (Unemployment), M2SL | 🏆 **P1** |
| **yfinance** | `pip install yfinance` — **NO KEY** | GC=F (Gold), CL=F (Oil), ^TNX (10Y yield), ^VIX, DX-Y.NYB (DXY), ^GSPC (S&P 500) — tất cả daily OHLCV | 🏆 **P1** |
| **Stooq.com** | HTTP CSV download — **NO KEY, NO AUTH** | DXY (`^dxy`), Gold (XAUUSD), Oil (CL.F), SPX (`^spx`) — URL: `stooq.com/q/d/l/?s=^dxy&i=d` | **P2** |
| **Alpha Vantage** | REST API — free key (25 calls/day) | CPI, Fed Funds Rate, Real GDP, Treasury yields time series | **P3** |

```python
# FRED API — macro ground truth
from fredapi import Fred
fred = Fred(api_key='YOUR_FREE_KEY')  # Đăng ký miễn phí tại fred.stlouisfed.org/api
us10y = fred.get_series('DGS10')        # 10Y Treasury yield
fed_bs = fred.get_series('WALCL')       # Fed balance sheet
dxy_proxy = fred.get_series('DTWEXBGS') # Dollar Index proxy
cpi = fred.get_series('CPIAUCSL')       # CPI monthly

# yfinance — macro prices (Gold, Oil, VIX, SPX, DXY)
import yfinance as yf
macro = yf.download(["GC=F","CL=F","^TNX","^VIX","DX-Y.NYB","^GSPC"], period="5d")
```

##### Macro Newsletters với RSS (Miễn Phí)

| Newsletter | RSS URL | Cadence | Nội dung | Priority |
|-----------|---------|---------|----------|----------|
| **Lyn Alden** | `lynalden.substack.com/feed` | Monthly | M2/liquidity/BTC correlation, macro cycle | 🏆 P1 |
| **The Macro Compass** | `themacrocompass.substack.com/feed` | 2-3x/week | Rates, bonds, liquidity cycles | 🏆 P1 |
| **Rekt Capital** | `rektcapital.substack.com/feed` | 3-4x/week | BTC halving cycle, key price levels | **P1** |
| **Will Clemente** | `willclemente.substack.com/feed` | Weekly | On-chain + TA hybrid BTC/ETH | **P1** |
| **Delphi Digital** | `delphidigital.io/feed/` | Daily/Weekly | Institutional TA + fundamentals | **P2** |
| **The Bitcoin Layer (Nik Bhatia)** | `thebitcoinlayer.substack.com/feed` | Weekly | BTC as monetary system, rates | **P2** |

##### Macro Telegram Channels Mới (Chưa Có)

| Channel | Handle | Nội dung | Priority |
|---------|--------|----------|----------|
| **Macro Alf** | @MacroAlf | Global macro, rates, liquidity | 🏆 P1 |
| **tedtalksmacro** | @tedtalksmacro | Fed policy, liquidity cycles + crypto | 🏆 P1 |
| **Crypto x Macro** | @crypto_macro | Crypto-macro correlation chuyên biệt | 🏆 P1 |
| **The Macro Compass** | @MacroCompassOfficial | Rates + bonds + crypto weekly | **P2** |
| **The Last Bear Standing** | @LastBearStanding | Risk-off signals, rates, credit | **P2** |

> **💡 Tổng kết Macro**: FRED + yfinance = "Free Bloomberg Terminal" — DXY, Gold, Oil, 10Y yield, S&P500 tất cả daily free. Thêm 5 TG channels macro mới + 4 Substack RSS feeds.

---

#### ON-CHAIN — Analytics Miễn Phí (Game Changer)

##### APIs Miễn Phí Có Thể Dùng Ngay

| Source | Free Tier | Key Metrics | Code |
|--------|-----------|------------|------|
| **Glassnode** | **200+ metrics FREE** (daily resolution) | SOPR, MVRV Z-Score, Exchange Reserves, STH/LTH Realized Price, Active Addresses, Miner Position Index | REST + free API key |
| **Coinglass** | Free key, 5 calls/min | Funding rates (all exchanges), OI aggregated, Liquidations 24h, Long/Short ratio, Options put/call | REST API |
| **Mempool.space** | **No key needed** — completely free | BTC fee rates, hashrate 3-day avg, difficulty adjustment, mempool backlog, mining pool distribution | REST API |
| **Blockchain.info Stats** | Free, no key | BTC hashrate, tx count, avg fees, active addresses, market price | REST API |
| **Deribit** | **No auth needed** — public API | BTC/ETH options: all strikes/expiries, IV, put/call OI, mark price → calculate Max Pain, GEX | REST API |
| **Bybit** | Free public API, no key | OI by contract, funding rate, mark vs index price spread | REST API |
| **CoinAnk** | Free, no key for most | Funding rates, OI, liquidations, Coinbase premium index | REST API |

```python
# Glassnode FREE — on-chain cycle indicators
import requests
KEY = "your_free_key"  # Đăng ký tại studio.glassnode.com
base = "https://api.glassnode.com/v1/metrics"
mvrv = requests.get(f"{base}/market/mvrv_z_score", params={"a":"BTC","api_key":KEY,"i":"24h"}).json()
sopr = requests.get(f"{base}/indicators/sopr", params={"a":"BTC","api_key":KEY,"i":"24h"}).json()
exchange_flow = requests.get(f"{base}/transactions/transfers_volume_to_exchanges_sum",
    params={"a":"BTC","api_key":KEY,"i":"24h"}).json()

# Mempool.space — BTC health (no key)
fees = requests.get("https://mempool.space/api/v1/fees/recommended").json()
hashrate = requests.get("https://mempool.space/api/v1/mining/hashrate/3d").json()
diff = requests.get("https://mempool.space/api/v1/difficulty-adjustment").json()

# Coinglass — derivatives (free key)
headers = {"coinglassSecret": "FREE_KEY"}
funding = requests.get("https://open-api.coinglass.com/public/v2/indicator/funding_rate",
    headers=headers, params={"symbol":"BTC"}).json()
liquidations = requests.get("https://open-api.coinglass.com/public/v2/indicator/liquidation_history",
    headers=headers, params={"symbol":"BTC","timeType":"0"}).json()

# Deribit — BTC options max pain (no auth)
options = requests.get("https://www.deribit.com/api/v2/public/get_book_summary_by_currency",
    params={"currency":"BTC","kind":"option"}).json()["result"]
# Group by expiry → calculate max pain
```

##### On-Chain Telegram Channels Mới Chất Lượng Cao

| Channel | Handle | Dữ liệu | Priority |
|---------|--------|---------|----------|
| **Glassnode Alerts** | @glassnodealerts | On-chain metric alerts khi vượt ngưỡng | 🏆 P1 |
| **Laevitas** | @Laevitas_CryptoDerivatives | Daily GEX + max pain + derivatives summary | 🏆 P1 |
| **Greeks.live** | @GreeksLiveTG | BTC/ETH options daily snapshot: IV, skew, max pain | 🏆 P1 |
| **Token Unlocks Alert** | @TokenUnlocksAlert | Upcoming token unlock cảnh báo sớm | 🏆 P1 |
| **Whale Freedom** | @WhaleFreedomAlert | Large BTC/ETH whale wallet movements | **P2** |
| **Coinglass Official** | @CoinglassOfficialChannel | Funding rates, liquidation heatmaps | **P2** |
| **Arkham Intel** | @ArkhamIntelligence | Labeled wallet movements, exchange flows | **P2** |
| **DeFi Llama** | @DefiLlama | TVL alerts, protocol fee updates | **P2** |

> **🚨 Game Changer**: **Glassnode free API** có 200+ metrics ở daily resolution — SOPR, MVRV Z-Score, Exchange Reserves, STH/LTH Realized Price. Đây là data on-chain mà trước đây cần $29-299/tháng. **KHÔNG phải chỉ dùng TG nữa — có thể pull trực tiếp.**

---

#### TA — Technical Analysis Sources

##### Derivatives & Options (Miễn Phí)

| Source | Free Access | Data Available | Note |
|--------|------------|----------------|------|
| **Deribit Public API** | No auth, REST | BTC/ETH options: IV surface, max pain, put/call OI, term structure | Tính Max Pain từ raw data |
| **Coinglass Options** | Free key | Put/call OI by strike, max pain price, OI by exchange | Pre-aggregated, dễ dùng hơn Deribit |
| **Bybit API** | No key | Perpetual funding, mark vs index spread, OI by contract | Derivatives tốt hơn MEXC |
| **Laevitas TG** | Free via @Laevitas_CryptoDerivatives | GEX chart + max pain daily | Visual charts |

##### TA Substack RSS Feeds

| Newsletter | RSS | Cadence | Focus |
|-----------|-----|---------|-------|
| **Rekt Capital** | `rektcapital.substack.com/feed` | 3-4x/week | BTC cycle analysis, halving, key levels |
| **Will Clemente** | `willclemente.substack.com/feed` | Weekly | On-chain + TA hybrid |
| **PlanB** | `100trillionusd.substack.com/feed` | Irregular | S2F model, BTC monthly |
| **Delphi Digital** | `delphidigital.io/feed/` | Daily | Institutional grade BTC/ETH/alts |
| **The Daily Candle** | `thedailycandle.substack.com/feed` | Daily | BTC/ETH daily TA, key levels |

##### TradingView Webhook Pattern (Automation)

```python
# TradingView Pine Script → Webhook → Your endpoint (MIỄN PHÍ!)
# 1. Tạo Pine Script alert với điều kiện: RSI < 30, EMA cross, etc.
# 2. Set alert to post JSON to your URL
# 3. Endpoint nhận → lưu SQLite → trigger report section

# Alert JSON format từ TradingView:
# {"symbol": "BTCUSDT", "signal": "RSI_OVERSOLD", "rsi": 28.5, "price": 65000}

# Ý tưởng: Tự tạo alerts cho SonicR PAC signals → feed vào daily report
```

##### TA Telegram Channels Chất Lượng

| Channel | Handle | Focus | Language | Priority |
|---------|--------|-------|----------|----------|
| **Material Indicators** | @MaterialIndicatorsOG | BTC liquidity heatmaps, order book depth | EN | 🏆 P1 |
| **Mikybull Crypto** | @MikybullCrypto | BTC market structure, SMC | EN | P1 |
| **TheKingfisher** | @TheKingfisher | BTC order book, liquidation levels | EN | P1 |
| **Titan of Crypto** | @TitanofCrypto | Elliott Wave BTC | EN | P2 |
| **Rekt Capital** | @rektcapital | BTC cycle analysis | EN | P1 |

##### Vietnamese TA/On-Chain/Macro Channels Mới

| Channel | Handle | Loại | Note |
|---------|--------|------|------|
| **Coin98 Analytics** | @coin98analytics | TA + FA tiếng Việt | High quality từ Coin98 team |
| **FOMO Sapiens VN** | @fomosapiensVN | On-chain + macro tiếng Việt | Dịch Glassnode/CryptoQuant sang VN |
| **Coin68 Research** | @coin68research | Research tổng hợp tiếng Việt | Team Coin68 |
| **AnToanCrypto** | @antoanCrypto | Risk analysis + on-chain safety | Phù hợp với triết lý CIC |

---

#### UPDATED DATA PIPELINE — 10 Nguồn Structured Data APIs

**(Thay thế cho phần "API Sources" cũ, bổ sung FRED + yfinance + Glassnode + Coinglass + Mempool + Deribit)**

| Category | API | Key | Rate Limit | Data |
|---------|-----|-----|-----------|------|
| **Macro** | FRED | Free key | Generous | DGS10, CPI, DXY proxy, Fed BS |
| **Macro** | yfinance | None | ~2000/hr | Gold, Oil, VIX, SPX, DXY, 10Y |
| **Macro** | Stooq.com | None | Moderate | CSV backup for all macro prices |
| **Price** | CoinLore | None | Unlimited | Market cap, price (Primary) |
| **Price** | MEXC | None | 500/min | OHLCV, price (Primary) |
| **Price** | OKX | None | 20/min | Price fallback |
| **On-Chain** | **Glassnode** 🆕 | Free key | 200+ metrics/day | MVRV, SOPR, Exchange flows |
| **On-Chain** | **Coinglass** 🆕 | Free key | 5/min | Funding, OI, Liquidations |
| **On-Chain** | **Mempool.space** 🆕 | None | Generous | BTC fees, hashrate, difficulty |
| **Options/TA** | **Deribit** 🆕 | None | Public | Max pain, IV, put/call ratio |
| **DeFi** | DeFiLlama | None | 300/5min | TVL, protocol fees |
| **Sentiment** | alternative.me | None | Generous | Fear & Greed Index |
| **News** | CryptoPanic | Free | ~100/day | 100+ sources aggregated |

---

#### TG CHANNELS MASTER LIST — CẬP NHẬT (Thêm 12 kênh mới)

**Thêm vào Tier 1 — Quality Insight (6 kênh mới):**

| # | Handle | Loại | Lý do thêm |
|---|--------|------|-----------|
| 28 | @MacroAlf | Macro | Global macro, rates, liquidity — TOP quality |
| 29 | @tedtalksmacro | Macro + Crypto | Fed policy + liquidity cycles, crypto impact |
| 30 | @crypto_macro | Crypto-Macro | Dedicated BTC-macro correlation analysis |
| 31 | @glassnodealerts | On-Chain | Alerts khi MVRV/SOPR/reserves vượt ngưỡng |
| 32 | @Laevitas_CryptoDerivatives | Options/TA | Daily GEX + max pain — options intelligence |
| 33 | @GreeksLiveTG | Options | BTC/ETH IV + skew + term structure daily |

**Thêm vào Tier 3 — Data Alerts (6 kênh mới):**

| # | Handle | Loại | Lý do thêm |
|---|--------|------|-----------|
| 34 | @TokenUnlocksAlert | Token Unlocks | Sắp có unlock lớn = risk alert |
| 35 | @WhaleFreedomAlert | Whale | Large wallet movements |
| 36 | @CoinglassOfficialChannel | Derivatives | Liquidation heatmaps, funding |
| 37 | @ArkhamIntelligence | On-Chain | Labeled wallet movements |
| 38 | @MaterialIndicatorsOG | TA | BTC liquidity heatmaps, order book |
| 39 | @rektcapital | TA | BTC cycle analysis |

> **Tổng TG channels: 27 (cũ) + 12 (mới) = 39 channels**

---

#### KEY METRICS TABLE CHO DAILY REPORT (Expanded)

```
📊 BẢNG CHỈ SỐ EXPANDED:

VĨ MÔ (từ FRED + yfinance):
  DXY | Gold ($/oz) | Oil ($/barrel) | S&P 500 | VIX
  US 10Y Treasury Yield | Fed Balance Sheet trend

CRYPTO MARKET (từ CoinLore + MEXC):
  Total Market Cap | BTC.D | ETH.D | TOTAL3 | Altcoin Season

SENTIMENT (từ alternative.me):
  Fear & Greed Index | USDT/VND (PriceDancing)

ON-CHAIN BTC (từ Glassnode free):
  MVRV Z-Score (cycle position) | SOPR (realized P&L)
  Exchange Net Flow (inflow/outflow) | STH Realized Price
  LTH Supply (HODLer behavior)

DERIVATIVES (từ Coinglass + Deribit):
  Funding Rate avg (8 exchanges) | Open Interest change 24h
  Liquidations 24h (L/S) | Put/Call Ratio | Max Pain (weekly exp)
  BTC IV Index (implied volatility)

BTC NETWORK HEALTH (từ Mempool.space):
  Hashrate 3-day avg | Difficulty adjustment next
  Mempool backlog | Fee rates (sat/vbyte)
```

---

## III. 114 IDEAS — ORGANIZED BY CATEGORY

### A. Data Sources & Collection (12 ideas)

| # | Idea | Mô tả |
|---|------|--------|
| 1 | Hybrid Data Pipeline | API free (giá, market cap) + Telegram (narrative) + 1-2 API trả phí cho critical data |
| 2 | Telegram-First Architecture | Dùng TG channels làm nguồn chính — human curation đã có sẵn |
| 3 | Smart API Tiering | Chia API: Free → Low-cost → Premium. Tối đa free trước |
| 4 | Noise-Filtering Layer | Phân biệt signal vs noise — kênh quality đọc hết, kênh alert chỉ filter quan trọng |
| 5 | Channel Weight System | Gán trọng số cho từng kênh — quality insight weight cao hơn |
| 6 | Telegram Userbot Monitor | Telethon (Python) với account user, truy cập mọi kênh đã join |
| 7 | Bilingual Processing Engine | 11 kênh VN + 16 kênh EN — cross-reference, report bằng tiếng Việt |
| 8 | Structured vs Unstructured Split | 6 kênh auto-alert (parse số) + 21 kênh narrative (NLP/AI) |
| 12 | Free API Ecosystem | CryptoPanic + CoinLore + MEXC + CryptoCompare + alternative.me (⚠️ CoinGecko → fallback, Binance → disabled) |
| 15 | Free On-Chain Data Research | Parse @cryptoquant_alert + @whale_alert_io thay cho Glassnode trả phí |
| 20 | Telegram-as-OnChain-Data-Source | Aggregate TG on-chain channels = "Free Glassnode" |
| 38 | CryptoPanic Shortcut | 1 API call = tin từ 100+ nguồn, thay cho 10 web scrapers |

### B. Processing & AI Analysis (11 ideas)

| # | Idea | Mô tả |
|---|------|--------|
| 9 | Hybrid Intelligence Architecture | 3 lớp: API data + TG human insights + AI cross-reference |
| 10 | AI Surpasses Human Analyst | AI đọc 37+ nguồn cùng lúc, cross-reference trong vài giây |
| 13 | Context-Aware Narrative Engine | AI nhớ context ngày trước, viết narrative liên tục có tính "series" |
| 14 | Multi-Timeframe Cross-Analysis | So sánh với hàng trăm pattern lịch sử, không chỉ "tuần trước" |
| 16 | Multi-Timeframe TA Engine | 4h/D/3D/W: S/R, Trendline, SonicR PAC, RSI, Stochastic, MACD |
| 24 | SonicR PAC Reuse from Sentinel | Tái sử dụng SonicR logic từ CIC Sentinel, không build từ đầu |
| 30 | Gemini + Groq Dual Engine | Gemini (1M context, đọc bulk) + Groq (fast generation) |
| 31 | Free AI Backup Pool | OpenRouter, Mistral, Cerebras, HuggingFace — fallback khi rate limit |
| 33 | ~~Binance~~ → MEXC Public API for TA | ⚠️ Binance block VN → MEXC 500 req/min free, pandas-ta compute indicators |
| 25 | Master Prompt Template | Prompt NotebookLM đã test — tích hợp NQ05 + cấu trúc 5 section |
| 45 | Prompt A/B Testing | 2 prompts song song, so sánh output, iterate hàng tuần |

### C. Spam Filter & Data Verification (11 ideas)

| # | Idea | Mô tả |
|---|------|--------|
| 46 | Multi-Layer Spam Detection | 3 lớp: regex blacklist → AI classify → channel-specific rules |
| 47 | Spam Keyword Blacklist (VN+EN) | Danh sách từ khóa spam song ngữ |
| 48 | Message Quality Scoring | Chấm điểm 0-100 mỗi message, ngưỡng ≥50 mới đưa vào AI |
| 49 | Forward/Repost Detection | Tin forward nhiều = quan trọng, tin 1 kênh nhỏ = cần verify |
| 50 | Time-Relevance Filter | Chỉ tin 24h + weight theo timing context |
| 51 | Multi-Source Cross-Reference | Tin ≥2 nguồn độc lập → xác thực |
| 52 | Data vs Narrative Verification | "BTC giảm 10%" → verify bằng MEXC/CoinLore API thực tế (⚠️ Binance block VN) |
| 53 | Source Credibility Tier | Tier 1 (CryptoQuant, Binance) → Tier 2 (HCCapital) → Tier 3 |
| 54 | Contradiction Detection | Phát hiện 2 nguồn nói ngược nhau → AI verify + note |
| 55 | Timestamp Freshness Check | Loại tin cũ bị repost, giữ report luôn fresh 24h |
| 56 | Hallucination Guard | Mọi con số trong report phải trace ngược lại data source |

### D. Output Format & Report Structure (15 ideas)

| # | Idea | Mô tả |
|---|------|--------|
| 11 | Professional On-Chain Report | Template CIC: Tin tức → Phái sinh → Giao ngay → ETF → Tổng kết |
| 17 | Multi-Format Content Pipeline | Text report + Slides/Infographic + Video/Audio (NotebookLM) |
| 19 | CIC Community Content Hierarchy | TL;DR → Slides/Video → Full Report trong comment |
| 23 | NotebookLM Automation Gap | Hiện manual copy-paste, cần research automation |
| 81 | Traffic Light Summary | 🟢🟡🔴 — 1 tín hiệu 3 giây trả lời "Tôi có cần lo không?" |
| 82 | "Giải Thích Cho Bạn Nghe" | Đoạn mở đầu cực đơn giản, không thuật ngữ |
| 84 | Glossary Tooltip Style | Thuật ngữ + giải thích ngắn trong ngoặc |
| 87 | Expert Deep Dive Section | TA + on-chain + derivatives cho pro traders |
| 88 | "Điểm Mù Hôm Nay" | 3 điều bạn có thể chưa biết — insights từ nguồn ít phổ biến |
| 89 | Raw Data Appendix | Bảng số liệu thô cuối report cho pro tự phân tích |
| 90 | Contrarian Signal Detector | AI phát hiện divergence sentiment vs data |
| 91 | Historical Pattern Matching | Tìm pattern lịch sử tương đồng hiện tại |
| 92 | Multi-Market Correlation | BTC vs DXY, S&P500, Gold, 10Y Treasury |
| 93 | Layered Report Architecture | Đơn giản → phức tạp từ trên xuống, mỗi persona dừng ở tầng phù hợp |
| 94 | Telegram Message Splitting | 4 messages riêng: TL;DR → Tin tức → TA/On-chain → Altcoin/Pháp lý |

### E. NQ05 Compliance & Vietnamese Language (9 ideas)

| # | Idea | Mô tả |
|---|------|--------|
| 21 | NQ05 Auto-Compliance Engine | Tự thay "Bitcoin"→"tài sản dẫn đầu", không nêu tên coin/sàn |
| 22 | Project News vs Token Analysis | Phân biệt tin dự án (cho phép) vs phân tích token (không được) |
| 57 | Full Vietnamese Pipeline | Mọi output tiếng Việt — report, errors, alerts |
| 58 | CIC Terminology Glossary | Dictionary thuật ngữ CIC chuẩn, NQ05 compliant |
| 59 | Jargon Explainer for Newbies | Giải thích thuật ngữ khó khi xuất hiện lần đầu |
| 60 | Error Message Templates (VN) | ✅⚠️❌🔄📊 — mọi trạng thái bằng tiếng Việt |
| 85 | Weekly Learning Nugget | Mỗi tuần 1 concept giáo dục, sau 1 năm = 52 concepts |
| 96 | Weekend vs Weekday Report | Cuối tuần bớt macro/ETF, thêm TA + ecosystem |
| 99 | Seasonal Content Adaptation | Adjust tone theo market cycle (bull/bear/accumulation) |

### F. Realtime Critical Alert System (20 ideas)

| # | Idea | Mô tả |
|---|------|--------|
| 61 | Dual-Mode Architecture | Daily Report (6AM batch) + Breaking Alert (24/7 realtime) |
| 62 | Critical Event Taxonomy | 🔴 LEVEL 1 (5 min) → 🟠 LEVEL 2 (15 min) → 🟡 LEVEL 3 (1h) |
| 63 | Price Crash/Pump Detector | Poll MEXC/OKX mỗi 5 min (⚠️ Binance block VN), trigger khi BTC ±5% |
| 64 | Stablecoin Depeg Monitor | USDT/USDC lệch >2% = LEVEL 1 EMERGENCY |
| 65 | TG Breaking News Detector | Monitor 5 kênh Tier 1 realtime, AI classify "breaking or not" |
| 66 | Whale Alert Mirror | Parse whale moves >$50M + exchange destination = alert |
| 67 | Liquidation Cascade Detector | Liquidation >$200M/30min = cascade alert |
| 68 | Multi-Signal Confluence | 2+ signals đồng thời → auto upgrade severity |
| 69 | VN Alert Templates by Severity | Format khác nhau theo 🔴🟠🟡, copy-paste ready |
| 70 | GitHub Actions Polling (Limit) | Free tier không đủ 24/7 → cần giải pháp khác |
| 71 | Hybrid Monitoring | External price alerts + TG listener (Koyeb) + GitHub Actions (daily) |
| 72 | Koyeb/Render Free Tier | 500-750h free/month = đủ 24/7 lightweight listener |
| 73 | Price Alert via Free Services | CoinGecko alerts, TradingView alerts thay vì tự build |
| 74 | PC as Backup Listener | Máy cá nhân chạy backup khi cloud gặp vấn đề |
| 75 | Rate Limit During Crisis | Pre-cache data, ưu tiên bandwidth cho critical checks |
| 76 | Duplicate Alert Prevention | Cooldown 1h sau alert cùng loại, chỉ alert lại nếu severity tăng |
| 77 | Alert → Action Bridge | Inline buttons: [📢 Post CIC] [✏️ Chỉnh sửa] [🚫 Bỏ qua] |
| 78 | Night Mode / DND | LEVEL 1: bất kỳ lúc nào. LEVEL 2: 7AM-11PM. LEVEL 3: gộp daily |
| 79 | Historical Alert Log | Lưu mọi alert để review + tune ngưỡng |
| 80 | False Positive vs Negative | Ưu tiên giảm false negative — "better safe than sorry" |

### G. Architecture & MVP (12 ideas)

| # | Idea | Mô tả |
|---|------|--------|
| 26 | Serverless Cron Pipeline | Không cần VPS — GitHub Actions/Cloudflare Workers free |
| 27 | Python-First Stack | Telethon + pandas-ta + LangChain + python-telegram-bot |
| 28 | Data Lake → AI → Multi-Output | SQLite lưu mọi data, AI đọc, tạo nhiều format output |
| 29 | Zero-Cost Architecture | GitHub Actions + Gemini free + Groq free + TG Bot free + SQLite |
| 32 | Day-1 MVP Pipeline | TG batch fetch → API data → AI generate → TG bot send |
| 34 | GitHub Actions as Free Cron | 2000 min/month free, pipeline ~13 min/run, dư sức |
| 35 | Telegram Userbot + Bot Combo | Userbot (collect) + Bot (deliver) |
| 36 | 24/7 Listener Problem | Free tier không hỗ trợ long-running → batch 5AM thay realtime |
| 37 | Morning Batch Approach | 5AM script 1 lần, lấy 24h history, perfect cho daily report |
| 39 | GitHub Actions + Telethon Session | Auth 1 lần local → encrypt session → GitHub Secrets |
| 40 | Self-Healing Pipeline | Retry 3 lần, skip section nếu fail, luôn gửi report |
| 41 | Execution Time Budget | ~13 min/run, GitHub free 66 min/ngày, dư cho retry |

### H. Persona-Based Design (16 ideas)

| # | Idea | Mô tả |
|---|------|--------|
| 81 | Traffic Light Summary | 🟢🟡🔴 cho Chị Lan (người bận, ít kiến thức) |
| 82 | "Giải Thích Cho Bạn Nghe" | 5 dòng không thuật ngữ, tiếng Việt đời thường |
| 83 | "Danh Mục CIC Hôm Nay" | Quick check % tăng/giảm danh mục CIC khuyến nghị |
| 84 | Glossary Tooltip Style | Thuật ngữ (giải thích ngắn) inline — giáo dục dần |
| 85 | Weekly Learning Nugget | 1 concept/tuần = 52 concepts/năm |
| 86 | Audio Summary Option | NotebookLM audio 3 phút, nghe trong xe |
| 87 | Expert Deep Dive | TA + on-chain cho Anh Minh (trader lâu năm) |
| 88 | "Điểm Mù Hôm Nay" | 3 insights expert có thể chưa biết |
| 89 | Raw Data Appendix | Số liệu thô cho pro tự phân tích |
| 90 | Contrarian Signal Detector | Divergence sentiment vs data |
| 91 | Historical Pattern Matching | Pattern lịch sử tương đồng hiện tại |
| 92 | Multi-Market Correlation | BTC vs TradFi assets |
| 95 | Engagement Tracking | Track đọc đến message nào → adjust content |
| 97 | "Sự Kiện Tuần Này" | Forward-looking: events sắp tới gây biến động |
| 98 | Community Sentiment Poll | Poll sau report → kết quả vào report ngày mai |
| 100 | Report Archive | Knowledge base tích lũy, monthly digest tự động |

### I. Tier-Based Content (CIC L1-L5) (14 ideas)

| # | Idea | Mô tả |
|---|------|--------|
| 101 | Content Pyramid | 1 master report → 5 filtered outputs per tier |
| 102 | NQ05-Compatible Tier Content | L1 strict NQ05, L2+ linh hoạt hơn trong context giáo dục |
| 103 | "1 Post L1, Link Chuyên Sâu" | Post L1 + redirect đến group tier cao hơn |
| 104 | Priority Posting | Daily L1, 2-3x/week L2+, weekly L3-L5 deep dive |
| 105 | Copy-Paste Optimized Format | Format tương thích BIC Chat, chia blocks per tier |
| 106 | TG Bot → 5 Messages Riêng | Mỗi tier 1 message copy-paste ready |
| 107 | Smart Skip | Chỉ gửi tier khi có nội dung đáng post |
| 108 | L1 Content Design | Đèn tín hiệu + TL;DR + Chỉ số + Vĩ mô + BTC/ETH TA |
| 109 | L2 Content — Bluechip Watch | Performance bảng + tin dự án + chiến lược mùa |
| 110 | L3 Content — Mid-Cap | Top 5 biến động + ecosystem update + Bot strategy |
| 111 | L4 Content — DeFi Deep Dive | TVL + protocol revenue + yield + infra upgrades |
| 112 | L5 Content — Full Spectrum | New listings + speculative + trading signals + contrarian |
| 113 | BIC Chat Web Automation | Tương lai: Playwright auto-post hoặc Beincom partnership |
| 114 | Beincom Partnership | Đề xuất API access — CIC 2,278+ members là leverage |

### J. Operational (5 ideas)

| # | Idea | Mô tả |
|---|------|--------|
| 42 | Monitoring & Alert | Pipeline fail → alert tiếng Việt qua TG |
| 43 | Account Phụ Strategy | TG account riêng cho monitoring, tách khỏi account chính |
| 44 | Progressive Enhancement MVP | MVP tối thiểu, thêm features mỗi tuần |
| 18 | NotebookLM-in-the-Loop | Pipeline → AI report → NotebookLM → slides + video |
| 86 | Audio Summary | NotebookLM audio briefing 3 phút |

---

## IV. MORPHOLOGICAL MATRIX — MVP COMBO

### MVP Combo (Ngày 04/03/2026)

| Thành phần | Lựa chọn | Lý do |
|-----------|----------|-------|
| Thu thập TG | Telethon batch 5AM (lấy 24h history) | Đơn giản, không cần listener 24/7 |
| Tin tức API | CryptoPanic (free, aggregated) | 1 call = 100+ nguồn |
| Market Data | CoinLore (primary) + CoinGecko (fallback) | ⚠️ CoinGecko hay bị rate limit → CoinLore không giới hạn, Sentinel đã validate |
| Fear & Greed | alternative.me API | Free, 1 call |
| USDT/VND | PriceDancing scrape HOẶC OKX P2P API | ⚠️ Binance bị block IP VN → dùng PriceDancing hoặc OKX thay |
| On-Chain | Parse @cryptoquant_alert TG | Free, trong pipeline |
| ETF Flow | Parse TG channels | Nhiều kênh post ETF data |
| AI Tổng hợp | Gemini 2.0 Flash (1M context) | Đọc hết bulk messages |
| AI Report | Groq (Llama 3.3 70B) | Generate nhanh nhất |
| TA | **MEXC API** + pandas-ta + SonicR | ⚠️ Binance block VN → MEXC 500 req/min, Sentinel đã validate |
| Spam Filter | Regex blacklist + AI classify | 2 lớp lọc |
| NQ05 | Prompt engineering | Tích hợp vào system prompt |
| Storage | SQLite file-based | Zero setup |
| Schedule | GitHub Actions cron 5AM | Auto, free |
| Delivery | Telegram Bot → 5 messages per tier | Copy-paste ready |
| Language | Full Vietnamese | Report + errors + alerts |
| Slides/Video | NotebookLM (manual) | Automate sau |
| Hosting | GitHub repo | Free, version controlled |
| TG Account | Account phụ riêng cho monitoring | Tách khỏi account chính |

### Full Version (Nâng cấp sau MVP)

| Nâng cấp | Thành |
|----------|-------|
| Realtime Alerts | Koyeb/Render free tier, 24/7 listener, critical event taxonomy |
| Storage | Supabase PostgreSQL (history, analytics) |
| On-Chain | + CryptoQuant free API + Dune Analytics |
| ETF | + SoSoValue scrape |
| Social Data | CryptoCompare (100K/month) thay CoinGecko |
| Slides | Gamma.app API hoặc BIC Chat automation |
| AI Backup | + Mistral + Cerebras + OpenRouter + Google Gemini Flash-Lite fallback |
| Delivery | + Engagement tracking + Community polls |
| BIC Chat | Partnership với Beincom cho API access (URL: beincom.com/bic-chat/) |
| QuotaManager | Implement circuit breaker pattern từ Sentinel |

---

## V. SYSTEM ARCHITECTURE

### Dual-Mode Architecture

```
┌──────────────────────────────────────────────────────┐
│           CIC DAILY CRYPTO SYSTEM                    │
├─────────────────────┬────────────────────────────────┤
│  MODE 1: DAILY      │  MODE 2: REALTIME ALERT        │
│  (GitHub Actions     │  (Koyeb/Render 24/7)           │
│   5AM batch)        │  [Phase 2 — sau MVP]           │
│                     │                                │
│  ┌─ Telegram Batch  │  ┌─ Price Monitor (5 min)      │
│  ├─ CryptoPanic API │  ├─ TG Tier 1 Listener         │
│  ├─ CoinLore API    │  ├─ Stablecoin Depeg Monitor   │
│  ├─ MEXC API (⚠️    │  ├─ Whale Alert Parser          │
│  │  thay Binance-   │                                │
│  │  block VN)       │                                │
│  ├─ Fear & Greed    │  ├─ Liquidation Detector        │
│  │                  │  └─ Confluence Detector         │
│  ├─ SPAM FILTER     │                                │
│  │  ├─ Regex        │  Critical? → Alert NOW (🔴🟠🟡) │
│  │  ├─ AI Classify  │  Normal? → Queue for AM report  │
│  │  └─ Quality Score│                                │
│  │                  │  Alert includes:                │
│  ├─ VERIFICATION    │  [📢 Post CIC] [✏️ Edit] [🚫] │
│  │  ├─ Cross-ref    │                                │
│  │  ├─ API verify   │  Night Mode:                    │
│  │  └─ Hallucination│  🔴 LEVEL 1 → anytime          │
│  │     guard        │  🟠 LEVEL 2 → 7AM-11PM         │
│  │                  │  🟡 LEVEL 3 → daily report      │
│  ├─ AI ANALYSIS     │                                │
│  │  ├─ Gemini (bulk)│                                │
│  │  └─ Groq (gen)   │                                │
│  │                  │                                │
│  ├─ TA ENGINE       │                                │
│  │  ├─ RSI/MACD/    │                                │
│  │  │  Stochastic   │                                │
│  │  ├─ SonicR PAC   │                                │
│  │  └─ Multi-TF     │                                │
│  │    (4h/D/3D/W)   │                                │
│  │                  │                                │
│  ├─ NQ05 COMPLIANCE │                                │
│  │                  │                                │
│  └─ REPORT GEN      │                                │
│     ├─ L1 (all)     │                                │
│     ├─ L2 (bluechip)│                                │
│     ├─ L3 (mid-cap) │                                │
│     ├─ L4 (DeFi)    │                                │
│     └─ L5 (full)    │                                │
│                     │                                │
│  → TG Bot           │  → TG Bot                      │
│    (5 messages)     │    (alert message)             │
│  → Anh Cường        │  → Anh Cường                   │
│  → BIC Chat         │  → BIC Chat                    │
│    (manual post)    │    (manual post nếu cần)       │
└─────────────────────┴────────────────────────────────┘
```

### Report Layered Architecture (L1 Report)

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🚦 ĐÈN TÍN HIỆU: 🟢 / 🟡 / 🔴
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ↑ Người bận đọc đến đây = đủ (10 giây)

📝 TÓM TẮT CHO NGƯỜI BẬN (5 dòng, không thuật ngữ)
    ↑ 1 phút đọc

📊 BẢNG CHỈ SỐ THỊ TRƯỜNG
   Market Cap | BTC.D | ETH.D | TOTAL3 |
   Fear&Greed | Altcoin Season | USDT/VND
    ↑ Ai cũng xem

📰 TIN TỨC NỔI BẬT + VĨ MÔ
💰 DÒNG TIỀN & TỔ CHỨC (ETF flows, whale, institutional)
    ↑ Trung cấp đọc kỹ từ đây

📈 PHÂN TÍCH KỸ THUẬT ĐA KHUNG (4h/D/3D/W)
   S/R | Trendline | SonicR PAC | RSI | MACD | Stochastic
🔗 ON-CHAIN INSIGHTS (LTH/STH, URPD, exchange flows)
📊 THỊ TRƯỜNG PHÁI SINH (Liquidations, OI, Funding Rates)
    ↑ Expert đọc sâu

🔥 ALTCOIN & HỆ SINH THÁI
⚖️ PHÁP LÝ & CHÍNH SÁCH (VN + quốc tế)

💡 "3 ĐIỀU BẠN CÓ THỂ CHƯA BIẾT"
📅 SỰ KIỆN TUẦN NÀY CẦN THEO DÕI
    ↑ Pro traders thích nhất

📎 PHỤ LỤC DỮ LIỆU THÔ

⚖️ DISCLAIMER (NQ05)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## VI. CIC COMMUNITY CONTEXT

### Cấu trúc ICS trên BIC Chat (Beincom)

```
EVOL Community
  ├── EVOL COMMUNITY
  ├── TRẢI NGHIỆM EVOL
  ├── UBRAND
  ├── EVOL INVESTORS & TRADERS
  │     ├── EVOL Investors & Traders
  │     ├── Bất Động Sản (MBS)
  │     └── Stock Inner Circle (SIC)
  ├── Crypto Inner Circle (CIC - L1) ← 2,278 members, ALL see this
  │     ├── CIC L2 - Strategic Investors
  │     │     └── CIC L3 - Bot Investors
  │     │           └── CIC L4 - Pro Bot Investors
  │     │                 └── CIC L5 - Master Investors
  │     ├── Crypto Trading Warriors
  │     └── CIC Legacy
  │           ├── CIC-A Legacy
  │           └── CIC-Bot Legacy
  └── EVOL EDU COURSES
```

### 5 Tier Membership

| Level | Tên | Vốn KN | Phí/năm | Trọn đời (gốc) | Giảm giá | Trọn đời (thực) | Content |
|-------|-----|--------|---------|----------------|----------|-----------------|---------|
| L1 | Holder | 10-30M | 10M | 20M | -15% | 17M | BTC, ETH only (2 tokens) |
| L2 | Strategic Investor | 30-60M | 35M | 70M | -20% | 56M | + 17 bluechips |
| L3 | Auto Investor | 60-150M | 60M | 120M | -25% | 90M | + 44 mid-caps + Bot |
| L4 | Pro Auto Investor | 150-300M | 85M | 170M | -30% | 119M | + 70 DeFi/infra |
| L5 | Master Investor | 300M+ | 110M | 220M | -35% | 143M | + 38 speculative + Trading signals |

> **Upgrade fee**: 50M VND mỗi lần nâng cấp 1 level

### Triết lý CIC (Chi tiết)

**Investor vs Trader vs Speculator:**
- **CIC đào tạo Strategic Investor** (dài hạn, ADCA) — KHÔNG phải Trader hay Speculator
- Trader: Lướt sóng ngắn, rủi ro cao, cần kỹ thuật chuyên sâu
- Speculator: Đánh bạc, không có chiến lược, thua lỗ cao
- Strategic Investor: Nghiên cứu + tích lũy + nắm giữ dài hạn

**Mô hình 4 Mùa:**
| Mùa | Đặc điểm | Chiến lược |
|------|----------|-----------|
| Mùa Đông | Thị trường buồn tẻ, giá thấp | Tích lũy (ADCA) — thời điểm tốt nhất mua |
| Mùa Xuân | Bắt đầu tăng, quanh Bitcoin Halving | BTC dẫn đầu, Free-coin (rút vốn gốc, giữ lời) |
| Mùa Hè | Hưng phấn, đỉnh thị trường | Chốt lời chính, NGUY HIỂM nếu mới vào |
| Mùa Thu | Suy giảm sau đỉnh | Chờ đợi, nhà đầu tư kinh nghiệm chờ Đông tiếp |

**ADCA (Advanced Dollar Cost Averaging):**
- Chiến lược tích lũy CHỦ ĐỘNG — KHÔNG phải sửa sai
- Giả định: nhà đầu tư sẽ LUÔN sai về hướng thị trường → ADCA bù đắp
- Dùng thay Stop-Loss

**Holding Power (Sức mạnh nắm giữ):**
- Yếu tố quyết định thành công
- 3 trụ cột: Vốn (chỉ tiền nhàn rỗi) + Tâm lý + Chiến lược (ADCA Đông/Thu, Free-coin Xuân/Hè)

**3 Nguyên tắc đầu tư:**
1. Phân tán rủi ro
2. Luôn có kế hoạch dự phòng (không bao giờ all-in)
3. Chỉ đầu tư tiền nhàn rỗi

**6 Tiêu chí chọn crypto tốt:**
1. Problem (Giải quyết vấn đề gì)
2. Market (Thị trường mục tiêu)
3. Product (Sản phẩm thực tế)
4. Team (Đội ngũ phát triển)
5. Community (Cộng đồng)
6. Economics (Tokenomics)

**4 Loại Bot giao dịch (Bitsgap platform):**
| Bot | Mùa sử dụng | Chức năng |
|-----|-------------|-----------|
| S-Bot (GRID) | Đông | Tích lũy + kiếm lời ngang (lateral profit) |
| B-Bot (DCA Buy) | Đông | All-in BTC/ETH theo ADCA |
| D-Bot (DCA Buy) | Đông | Free-coin, buy-the-dip |
| C-Bot (GRID Sell) | Xuân/Hè | Chốt lời tích lũy + tiếp tục lời ngang |

**Chiến lược "Làm bạn với Binance" (Market Maker):**
- Đông: S-Bot tích lũy + kiếm lời lateral → Xuân/Hè: chuyển sang C-Bot bán dần + vẫn kiếm lateral

**Tâm lý đầu tư:**
- Bẫy Fear/Greed/FOMO — CIC giáo dục nhận biết và tránh
- 6 bí quyết thành công Master Investor
- "Trách nhiệm lịch sử" — Tier system KHÔNG đánh giá chất lượng coin, mà kiểm soát phạm vi thông tin

**Lợi nhuận kỳ vọng theo chu kỳ:**
| Level | Lợi nhuận kỳ vọng/chu kỳ |
|-------|--------------------------|
| L1 | 100% |
| L2 | 200% |
| L3 | 300% |
| L4 | 400% |
| L5 | 500% |

### Danh sách Token chính xác theo Tier (Cumulative — tier cao = tất cả tier dưới + thêm)

**L1 — Holder (2 tokens):** BTC, ETH

**L2 — Strategic Investor (+17 bluechips):** A, ADA, BCH, BNB, DASH, DOT, IOTA, LINK, LTC, NEO, PAXG, SOL, TRX, XEM, XLM, XMR, XRP

**L3 — Auto Investor (+44 mid-caps):** 1INCH, ARB, ATOM, AVAX, BAT, BTS, DCR, DGB, ETC, FIL, FTT, GAS, GLM, HOT, HT, ICX, KCS, LSK, LUNA, NEAR, ONE, OMG, ONT, OP, POL, QNT, QTUM, RPL, RVN, S, SKY, STEEM, STRK, THETA, TIA, UNI, VET, WAVES, XNO, XTZ, ZEC, ZIL, ZRX

**L4 — Pro Auto Investor (+70 DeFi/infra):** AAVE, ALGO, ALPHA, ALT, ANKR, API3, APT, AR, AXS, BAND, BEAM, BNT, BTCST, CAKE, CELO, CHZ, COMP, COTI, CRO, CRV, CTK, CVC, DODO, DYDX, ENJ, ENS, FET, FIRO, G, GMX, GNS, GRT, HBAR, HEI, IMX, INJ, KARRAT, KMD, KNC, KSM, LDO, LOOM, LRC, MANTA, NEXO, NTRN, NULS, PENDLE, PHA, PYTH, REEF, REN, RON, SAND, SCRT, SFP, SLF, SNX, SRM, STORJ, SUSHI, TAO, TON, TRB, TWT, VIC, WAXP, XVS, YFI

**L5 — Master Investor (+38 speculative):** AERO, BAL, BEL, BICO, Bondly, BURGER, CEL, CND, CREAM, CSPR, CVX, HFT, HNT, HOOK, ICP, ILV, KAVA, LTO, MANA, MAV, MDX, MERL, MIR, NFP, PORTAL, RDNT, RUNE, SFI, STX, SUI, SUPER, TRIBE, UMA, UNFI, VRTX, WING, WOO, ZKJ

**Tổng: 171 tokens** (2 + 17 + 44 + 70 + 38)

> **Nguyên tắc Cumulative Access**: L2 thấy tokens L1 + L2. L3 thấy L1 + L2 + L3. Tương tự cho L4, L5.

### Content Distribution Strategy

| Khi nào | Post ở đâu | Nội dung |
|---------|-----------|----------|
| Hàng ngày | L1 (all see) | Tổng quan thị trường, BTC/ETH focus |
| 2-3x/tuần | L2 group | Bluechip highlights khi có biến động |
| Khi có tin | L3-L5 groups | Tier-specific updates |
| Weekly | L3-L5 | Deep dive, bot strategy |
| Breaking | L1 + relevant tier | Critical alerts |

### BIC Chat Posting Pattern (Hiện tại của Anh Cường)
- **Main post**: Video tóm tắt (NotebookLM) + text ngắn
- **Comment**: Phân tích chi tiết đầy đủ
- Quote: "Ai muốn xem tóm tắt thì bấm vào video bên dưới, còn ai muốn xem phân tích chi tiết cả nhà vào phần comment nhé"
- **Platform URLs**: beincom.com/bic-chat/ | beincom.com/about-bic/
- **Đặc điểm BIC Chat**: Thread-based (không drift), Guaranteed reach (không bị algorithm giấu), chỉ members mới thấy

---

## VII. NQ05 COMPLIANCE RULES

### Nghị quyết 05/2025/NQ-CP

| Ngữ cảnh | Quy tắc |
|-----------|---------|
| Bitcoin | → "tài sản mã hóa dẫn đầu thị trường" |
| Ethereum | → "tài sản lớn thứ hai" |
| Altcoins | → "các tài sản mã hóa khác" |
| Sàn giao dịch | Không nêu tên sàn chưa được cấp phép tại VN |
| ETF Products | ĐƯỢC PHÉP nêu tên: Spot Bitcoin ETF, Spot ETH ETF |
| Tin dự án | ĐƯỢC PHÉP nêu tên dự án trong context tin tức (không phân tích token) |
| Khuyến nghị | KHÔNG đưa ra khuyến nghị đầu tư hoặc dự đoán giá |
| Disclaimer | BẮT BUỘC ở cuối mỗi bài |

### Master Prompt Template (Đã test & validate)
- Vai trò: Nhà nghiên cứu + phân tích thị trường + nhà đầu tư chuyên nghiệp
- 5 sections: Tổng quan → Dòng tiền → Hệ sinh thái → Vĩ mô & Pháp lý → Nhận định
- Phong cách: Chuyên nghiệp, rõ ràng, gần gũi, có emoji minh họa
- Disclaimer bắt buộc cuối mỗi bài

---

## VIII. SAMPLE REPORTS & REFERENCES

### Bài mẫu CIC Research Team (On-Chain Analysis, 29/09/2025)
- **Tác giả**: Nguyễn Tấn Đạt (CIC Research Team)
- **Format**: Tin tức nổi bật → Phái sinh → Giao ngay → ETF → Tổng kết
- **Nguồn data**: Coinglass, Glassnode, CryptoQuant, SoSoValue
- **Chất lượng**: Rất cao — cross-reference nhiều chỉ báo, narrative liên tục
- **Số liệu mẫu trong bài**:
  - BTC Total Liquidations: $725M (short) + $273M (long)
  - Open Interest giảm $5B
  - Funding Rates: phân tích 28/9 vs 29/9
  - LTH/STH behavior analysis
  - URPD: 650K BTC xuống 550K BTC tại $108,207, support $104,500 và $97,000
  - ETF outflows data
- **Giá trị template**: Flow phân tích Phái sinh → Giao ngay là mẫu tốt cho AI report engine

### Bài mẫu NotebookLM (03/03/2026)
- **Tiêu đề**: "Market Overview — Toàn cảnh thị trường crypto — 03/03/2026"
- **Ngôn ngữ**: NQ05 compliant ("tài sản mã hóa dẫn đầu" thay Bitcoin)
- **Số liệu mẫu**: Total Market Cap $2.45T, BTC.D 59%, ETH.D 10.41%, TOTAL3 $704B, Fear & Greed 14 (Cực Kỳ Sợ Hãi), Altcoin Season 43/100, USDT/VND 26,793
- **Dữ liệu đặc biệt**: Iran/Nobitex (tăng 700% capital flight, ~$3M), Strategy/MicroStrategy avg cost ~$75,985, Miner Capitulation risk ~$87,000 vs giá ~$68,300, BTC ~$70,000 (short squeeze driven)
- **Đặc điểm**: Có slides infographic, có video MP4

### NotebookLM Master Prompt Template (Đã test & validate)

**Tiêu đề**: "Crypto Daily — Toàn cảnh thị trường crypto — [ngày hiện tại]"

**Vai trò AI**: Nhà nghiên cứu thị trường + phân tích + nhà đầu tư chuyên nghiệp

**5 Sections output**:
1. **Tổng quan thị trường** — bảng 7 chỉ số + phân tích ngắn
2. **Dòng tiền & tổ chức lớn** — ETF flows, whale, institutional accumulation
3. **Tin tức hệ sinh thái / dự án hợp pháp** — project news (NQ05 cho phép nêu tên dự án)
4. **Tổng quan kinh tế vĩ mô & pháp lý** — macro, regulations VN + quốc tế
5. **Nhận định tổng thể (Trung lập)** — balanced assessment, no prediction

**7 Chỉ số bắt buộc** (bảng format):
Total Market Cap | BTC.D | ETH.D | TOTAL3 | Fear & Greed | Altcoin Season Index | USDT/VND

**Phong cách**: Chuyên nghiệp, rõ ràng, gần gũi, có emoji minh họa

**Thuật ngữ NQ05**: Chỉ dùng "tài sản mã hóa" (KHÔNG "tiền điện tử", "tài sản số", "tài sản kỹ thuật số")

**Disclaimer bắt buộc cuối mỗi bài** (exact text từ template)

### Infographic Slides (Mẫu NotebookLM)
- Tóm tắt Chuyên sâu: [Vĩ Mô] [Dòng Tiền] [Pháp Lý & BUIDL]
- Khủng hoảng & Địa chính trị
- TradFi & Lạm phát
- Lifeline 24/7 (Crypto trong chiến sự)
- Lực cầu tổ chức (MicroStrategy, Bitmine)
- ETF Flows & Institutional
- Pháp lý (US vs EU: CBDC vs Stablecoin)
- Tech upgrades (Ethereum, AAVE V4)
- Altcoin & Ecosystem (Pump.fun, AI Agents, Narratives)
- Tiêu Điểm Việt Nam (SSI + Bithumb, Đà Nẵng sandbox)

---

## IX. CRITICAL EVENT TAXONOMY (Realtime Alerts)

### 🔴 LEVEL 1 — KHẨN CẤP (Alert trong 5 phút, BẤT KỲ LÚC NÀO)
- Stablecoin depeg (USDT/USDC lệch >2%)
- Sàn lớn sập/tạm dừng rút tiền
- Flash crash >10% BTC trong 1 giờ
- Hack/exploit >$50M
- Chiến tranh/khủng bố ảnh hưởng crypto
- Lệnh cấm crypto đột ngột

### 🟠 LEVEL 2 — QUAN TRỌNG (Alert trong 15 phút, 7AM-11PM)
- BTC ±5% trong 4 giờ
- Whale move >$100M + exchange destination
- Liquidation cascade >$500M/1h
- Fed/ECB thay đổi lãi suất bất ngờ
- ETF outflow >$500M/ngày

### 🟡 LEVEL 3 — CHÚ Ý (Gộp vào daily report)
- BTC ±3% trong 4 giờ
- Funding rate cực đoan
- OI thay đổi >10%
- Tin pháp lý quan trọng

---

## X. LIÊN KẾT VỚI CIC SENTINEL

### Tái sử dụng từ Sentinel
| Component | Sentinel Source | Áp dụng cho Daily Report |
|-----------|----------------|--------------------------|
| SonicR PAC | Workers/Worker_2_Technical.gs | TA engine multi-timeframe |
| MEXC API integration | Workers/Worker_1_Market_Data.gs | Price + OHLCV data (thay Binance) |
| OKX fallback | Workers/Worker_1_Market_Data.gs | Price fallback |
| CoinLore API | Workers/Worker_1_Market_Data.gs | Market cap (thay CoinGecko) |
| CryptoCompare | CryptoCompare_Client.gs | Social + Dev data |
| DeFiLlama | Workers/Worker_9_DeFi_Metrics.gs | TVL, DeFi metrics |
| QuotaManager pattern | Modules/QuotaManager.gs | Rate limit management |
| Circuit breaker | Workers/Worker_1_Market_Data.gs | API failure recovery |
| FA 8-Pillar scoring | FA_Engine_v2_3.gs | Có thể tham khảo cho FA section |

### Phân loại CIC (Sentinel V13)
- Sentinel dùng hệ thống phân loại 2 chiều: Safety (0-100) × Opportunity (0-100)
- Kết quả: TRỤ_CỘT / AN_TOÀN / TIỀM_NĂNG / CƠ_HỘI / RỦI_RO
- Hệ thống này ĐỘC LẬP với tier system L1-L5
- Daily Report có thể tham chiếu nhưng không phụ thuộc

---

## XI. NEXT STEPS — ACTION PLAN

### MVP ngày 04/03/2026
1. Setup GitHub repo + project structure
2. Telegram: tạo account phụ + auth Telethon + tạo bot
3. Implement: TG batch fetch → API data (MEXC+CoinLore+CryptoPanic, ⚠️ KHÔNG Binance) → Spam filter → AI analysis → Report gen → TG send
4. Test end-to-end pipeline
5. Setup GitHub Actions cron 5AM (UTC+7)

### Phase 2 (Tuần 2)
- Thêm TA engine (pandas-ta + SonicR)
- Thêm on-chain parsing từ TG
- Improve prompt quality
- Thêm L2-L5 tier-specific content

### Phase 3 (Tuần 3-4)
- Realtime alert system (Koyeb/Render)
- NotebookLM workflow optimization
- Engagement tracking
- Community sentiment polls

### Phase 4 (Tháng 2+)
- BIC Chat automation research
- Beincom partnership outreach
- Monthly digest auto-generation
- Historical pattern matching database

---

## XII. TỔNG HỢP CUỐI — MASTER REFERENCE (04/03/2026)

> **Đây là bản tổng hợp CHÍNH THỨC sau 2 ngày brainstorming + deep research. Dùng làm input cho PRD.**

---

### A. MASTER SOURCE LIST — Tất Cả Nguồn Đã Xác Nhận

#### 1. Telegram Channels (39 kênh)

**Tier 1 — Quality Insight (16 kênh):**

| # | Handle | Tên | Subs | Ngôn ngữ | Loại |
|---|--------|-----|------|----------|------|
| 1 | @HCCapital_Channel | HC CAPITAL | 75K | VN | Insight |
| 2 | @Fivemincryptoann | 5 Phut Crypto | 63K | VN | Insight |
| 3 | @coin369channel | Coin369 | 13K | VN | Insight |
| 4 | @vnwallstreet | VN Wall Street | 31K | VN | Macro |
| 5 | @kryptonewsresearch | Krypto News Research | 415 | VN | Research |
| 6 | @hctradecoin_channel | HC Tradecoin | 39K | VN | Insight |
| 7 | @Coin98Insights | Upside (Coin98) | 31K | VN | Insight |
| 8 | @A1Aofficial | A1Academy | 43K | VN | Insight |
| 9 | @coin68 | Coin68 | 28K | VN | News |
| 10 | @wublockchainenglish | Wu Blockchain | 324K | EN | News |
| 11 | @MacroAlf | Macro Alf | — | EN | 🆕 Macro |
| 12 | @tedtalksmacro | Ted Talks Macro | — | EN | 🆕 Macro+Crypto |
| 13 | @crypto_macro | Crypto x Macro | — | EN | 🆕 Macro-Crypto |
| 14 | @glassnodealerts | Glassnode Alerts | — | EN | 🆕 On-Chain |
| 15 | @Laevitas_CryptoDerivatives | Laevitas | — | EN | 🆕 Options/TA |
| 16 | @GreeksLiveTG | Greeks.live | — | EN | 🆕 Options |

**Tier 2 — Major News (7 kênh):**

| # | Handle | Subs | Ngôn ngữ |
|---|--------|------|----------|
| 17 | @cointelegraph | 388K | EN |
| 18 | @binance_announcements | 4.6M | EN |
| 19 | @WatcherGuru | 628K | EN |
| 20 | @CryptoRankNews | 859K | EN |
| 21 | @layergg | 21K | VN |
| 22 | @bitcoin | 216K | EN |
| 23 | @coffeecryptonews | 12K | VN |

**Tier 3 — Data & Alerts (16 kênh):**

| # | Handle | Loại data |
|---|--------|-----------|
| 24 | @whale_alert_io | Whale transactions |
| 25 | @cryptoquant_official | On-chain analytics |
| 26 | @cryptoquant_alert | On-chain alerts |
| 27 | @FundingRates1 | Funding rates |
| 28 | @oi_detector | Open Interest |
| 29 | @bitcoin_price | BTC price |
| 30 | @eth_price | ETH price |
| 31 | @Database52Hz | VN on-chain |
| 32 | @TokenUnlocksAlert | 🆕 Token vesting alerts |
| 33 | @WhaleFreedomAlert | 🆕 Whale movements |
| 34 | @CoinglassOfficialChannel | 🆕 Funding/Liquidations |
| 35 | @ArkhamIntelligence | 🆕 Labeled wallet flows |
| 36 | @MaterialIndicatorsOG | 🆕 BTC liquidity heatmaps |
| 37 | @rektcapital | 🆕 BTC cycle TA |
| 38 | @DefiLlama | 🆕 TVL/protocol fees |
| 39 | @Coinank_Community | Community data |

---

#### 2. RSS Feeds (20 sites)

**Tier 1 — Full Content (parse trực tiếp, ~150+ bài/ngày):**

| # | Site | RSS URL | Ngôn ngữ | Content |
|---|------|---------|----------|---------|
| 1 | cryptoslate.com | `/feed/` | EN | Full HTML ✅ |
| 2 | blockonomi.com | `/feed/` | EN | Full HTML ✅ |
| 3 | bitcoinmagazine.com | `/feed` | EN | Full HTML ✅ |
| 4 | beincrypto.com | `/feed/` | EN | Full HTML ✅ |
| 5 | newsbtc.com | `/feed/` | EN | Full HTML ✅ |
| 6 | 5phutcrypto.io | `/feed` | **VN** | Full 2K-5K từ ✅ |
| 7 | hulkcrypto.com | `/feed` | **VN** | Full HTML ✅ |
| 8 | crypto.news | `/feed` | EN | Full ✅, có Vietnam tag |
| 9 | protos.com | `/feed` | EN | Full ✅, critical/balanced |
| 10 | bitcoinist.com | `/feed` | EN | Full ✅, BTC-focused |
| 11 | cryptopotato.com | `/feed` | EN | Full ✅, DA cao |
| 12 | blogtienao.com | `/feed` | **VN** | Full ✅, 13 bài/ngày |
| 13 | blockworks.co | `/feed/` | EN | Full ✅, institutional |
| 14 | thedefiant.io | `thedefiant.substack.com/feed` | EN | Full ✅, DeFi |
| 15 | milkroad.com | `milkroad.substack.com/feed` | EN | Full ✅, **daily brief format** |

**Tier 2 — RSS Link + Scrape:**

| # | Site | RSS URL | Scraping |
|---|------|---------|---------|
| 16 | coin98.net | `/rss/tin-moi-nhat.rss` | trafilatura |
| 17 | coin68.com | `/rss/tin-tong-hop.rss` | trafilatura |
| 18 | decrypt.co | `/feed` | trafilatura |
| 19 | cointelegraph.com | `/rss` | trafilatura |
| 20 | finbold.com | `/feed/` | trafilatura |

**Macro/Regulatory Substack RSS:**

| # | Newsletter | RSS URL | Cadence |
|---|-----------|---------|---------|
| R1 | Lyn Alden | `lynalden.substack.com/feed` | Monthly |
| R2 | The Macro Compass | `themacrocompass.substack.com/feed` | 2-3x/week |
| R3 | Rekt Capital | `rektcapital.substack.com/feed` | 3-4x/week |
| R4 | Will Clemente | `willclemente.substack.com/feed` | Weekly |
| R5 | BIS | `bis.org/rss/index.htm` | On release |
| R6 | IMF WEO | `imf.org/en/publications/rss?...series=World+Economic+Outlook` | Quarterly |
| R7 | Fed | `federalreserve.gov/feeds/press_all.xml` | On release |

---

#### 3. APIs — Structured Data (13 APIs)

| # | API | Auth | Rate Limit | Data Category | Priority |
|---|-----|------|-----------|--------------|----------|
| 1 | **FRED** | Free key | Generous | Macro: DGS10, CPI, DXY, Fed BS | 🏆 P1 |
| 2 | **yfinance** | None | ~2K/hr | Macro: Gold, Oil, VIX, SPX, DXY | 🏆 P1 |
| 3 | **CoinLore** | None | Unlimited | Price, Market Cap | 🏆 P1 |
| 4 | **MEXC Public** | None | 500/min | OHLCV (TA engine) | 🏆 P1 |
| 5 | **Glassnode** | Free key | 200+ metrics/day | On-Chain: MVRV, SOPR, flows | 🏆 P1 |
| 6 | **Coinglass** | Free key | 5/min | Derivatives: Funding, OI, Liq | 🏆 P1 |
| 7 | **Mempool.space** | None | Generous | BTC: hashrate, fees, difficulty | 🏆 P1 |
| 8 | **CryptoPanic** | Free token | ~100/day | News sentiment + original_url | 🏆 P1 |
| 9 | **DeFiLlama** | None | 300/5min | TVL, protocol fees | P2 |
| 10 | **alternative.me** | None | Generous | Fear & Greed Index | P2 |
| 11 | **Deribit** | None | Public | Options: max pain, IV, put/call | P2 |
| 12 | **OKX Public** | None | 20/min | Price fallback | P3 |
| 13 | **CryptoCompare** | Free key | 100K/month | Social + dev data | P3 |

---

#### 4. Aggregator Platforms

| Platform | API? | RSS? | VN Content | Cách dùng |
|---------|------|------|-----------|----------|
| **CryptoPanic** | ✅ Free | ✅ 20 items | ❌ | Primary news filter + sentiment |
| **Followin.io** | ❌ | ❌ | ✅ Native | Manual 5min/ngày — Hot Track + Alpha |
| **free-crypto-news (GitHub)** | ✅ Free/MCP | ✅ | ❌ | Backup aggregator layer |
| **LunarCrush** | 💰 $240/mo | ❌ | ❌ | Skip — quá đắt |

---

### B. FINAL DATA PIPELINE — 7 Lớp

```
┌─ LAYER 1: RSS Full Content (~150+ bài/ngày)
│  15 sites → feedparser → full articles (zero scraping)
│  VN: 5phutcrypto, hulkcrypto, blogtienao, coin98 (Tier 2)
│  EN: cryptoslate, bitcoinmagazine, beincrypto, crypto.news,
│      protos, bitcoinist, blockworks, thedefiant, milkroad...
│
├─ LAYER 2: Telegram (39 channels, batch 5AM)
│  Telethon → 24h message history
│  Link detection → trafilatura scrape full article
│  Structured data parsing (whale alerts, funding rates, OI)
│
├─ LAYER 3: CryptoPanic API (~100 req/day)
│  Hot + Important filter → original_url → full text scrape
│  + panic_score + votes (bullish/bearish) = sentiment layer
│
├─ LAYER 4: Macro APIs (FRED + yfinance)
│  FRED: DGS10, CPI, Fed Balance Sheet, DXY proxy
│  yfinance: Gold, Oil, VIX, S&P500, DXY daily
│
├─ LAYER 5: Structured Data APIs
│  CoinLore (price/mcap) + MEXC (OHLCV/TA) + alternative.me
│  DeFiLlama (TVL) + CryptoCompare (social)
│
├─ LAYER 6: On-Chain APIs (Glassnode + Coinglass + Mempool)
│  Glassnode: MVRV Z-Score, SOPR, Exchange flows, LTH/STH
│  Coinglass: Funding rates, OI, Liquidations 24h
│  Mempool.space: BTC hashrate, fees, difficulty
│
└─ LAYER 7: Regulatory/Research RSS
   BIS + IMF + Fed RSS → breaking regulatory signals
   Substack: Lyn Alden, Macro Compass, Rekt Capital
```

---

### C. DASHBOARD KPI — Chỉ Số Đầy Đủ Cho Daily Report

```
━━━ VĨ MÔ (từ FRED + yfinance) ━━━
DXY | Gold ($/oz) | Oil ($/bbl) | S&P 500 | VIX
US 10Y Yield | Fed Balance Sheet trend

━━━ CRYPTO MARKET (từ CoinLore + MEXC) ━━━
Total Market Cap | BTC.D | ETH.D | TOTAL3
Altcoin Season Index | USDT/VND

━━━ SENTIMENT ━━━
Fear & Greed | CryptoPanic panic_score top stories
CryptoPanic votes aggregate (bullish% vs bearish%)

━━━ ON-CHAIN BTC (từ Glassnode free) ━━━
MVRV Z-Score | SOPR | Exchange Net Flow
STH Realized Price | LTH Supply % change

━━━ DERIVATIVES (từ Coinglass + Deribit) ━━━
Funding Rate avg (8 exchanges) | OI change 24h
Liquidations L/S | Put/Call Ratio | Max Pain

━━━ BTC NETWORK (từ Mempool.space) ━━━
Hashrate 3d avg | Difficulty adjustment ETA
Mempool backlog | Fee rates (sat/vbyte)
```

---

### D. ARCHITECTURE DECISIONS ĐÃ XÁC NHẬN

| Quyết định | Lựa chọn | Lý do |
|-----------|----------|-------|
| Infrastructure | GitHub Actions (cron 5AM) | Free 2000 min/month, zero VPS |
| Language | Python | Telethon, feedparser, trafilatura, pandas-ta, yfinance, fredapi |
| Storage | SQLite | Zero setup, file-based, đủ cho daily report |
| AI Bulk Read | Gemini 2.0 Flash (1M context) | Đọc toàn bộ 150+ articles cùng lúc |
| AI Generate | Groq (Llama 3.3 70B) | Fastest generation, Vietnamese quality |
| Price data | MEXC Primary + CoinLore fallback | Binance blocked VN; CoinGecko rate-limited |
| On-chain | Glassnode free API + TG parsing | 200+ metrics daily free; no $29/mo |
| Scraping | trafilatura (F1=0.958) | Best accuracy, 50+ languages |
| Delivery | Telegram Bot → 5 tier messages | Copy-paste ready cho Anh Cường |
| Output format | NQ05 compliant Vietnamese | Nghị quyết 05/2025/NQ-CP |

---

### E. MVP SCOPE ĐÃ XÁC NHẬN

**MVP ngày 04/03/2026 — Minimum Viable Pipeline:**

```
TG batch 5AM (24h history từ 27 channels TOP priority)
+ RSS Layer 1 (top 7 sites: 5phutcrypto, bitcoinmagazine, cryptoslate, beincrypto, newsbtc, hulkcrypto, crypto.news)
+ CryptoPanic API (filter=hot, currencies=BTC,ETH top coins)
+ CoinLore + MEXC (market data)
+ alternative.me (Fear & Greed)
+ Glassnode free (MVRV Z-Score, SOPR, Exchange flow)
+ Coinglass (Funding rates, OI, Liquidations)
→ Spam Filter (regex + AI classify)
→ Gemini 2.0 Flash bulk analysis
→ Groq generate Vietnamese report
→ TG Bot send 5 messages (L1-L5)
→ Anh Cường review + copy-paste BIC Chat
```

**Bổ sung Phase 2 (Tuần 2-3):**
- FRED + yfinance (macro layer)
- Mempool.space (BTC network health)
- Deribit options (max pain, IV)
- Full TA engine (pandas-ta + SonicR PAC reuse từ Sentinel)
- Tier-specific L2-L5 content depth

**Bổ sung Phase 3 (Tuần 4+):**
- Realtime alert system (Koyeb 24/7)
- More RSS sites (blockworks, thedefiant, milkroad)
- Macro newsletter RSS (Lyn Alden, Macro Compass, Rekt Capital)

---

### F. CONSTRAINTS & RISKS ĐÃ XÁC NHẬN

| Constraint | Chi tiết | Giải pháp |
|-----------|----------|----------|
| **Zero budget** | Tất cả free tier | Đã xác nhận 13 APIs miễn phí |
| **No VPS** | GitHub Actions only | Batch 5AM, ~13 min/run |
| **Binance blocked VN** | Không dùng được | MEXC + OKX thay thế |
| **CoinGecko rate limit** | 10 RPM free | CoinLore primary (unlimited) |
| **NQ05 compliance** | Không nêu tên coin/sàn | Prompt engineering + NQ05 engine |
| **BIC Chat no API** | Manual post thủ công | TG Bot format copy-paste ready |
| **GitHub Actions 2000 min/month** | ~66 min/ngày | Pipeline ~13 min → dư sức |
| **CryptoPanic 100 req/day** | Giới hạn calls | Batch once daily, cache results |
| **TG Telethon session** | Auth 1 lần local | Encrypt session → GitHub Secrets |

---

### G. BRAINSTORMING SESSION — KẾT LUẬN

**Tổng số ý tưởng**: 152 ideas
**Thời gian**: 2 ngày (03-04/03/2026)
**Techniques**: Mind Mapping + Morphological Analysis + Six Thinking Hats + What-If Persona Analysis + Deep Research
**Nguồn xác nhận**: 39 TG channels + 20+ RSS sites + 13 APIs + 2 aggregator platforms
**Quyết định MVP**: GitHub Actions + Python + Gemini + Groq + Telegram Bot + SQLite
**Trạng thái**: ✅ **SẴN SÀNG → PRD**
