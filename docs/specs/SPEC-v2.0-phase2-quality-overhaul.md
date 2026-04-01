# SPEC: CIC Daily Report v2.0 Phase 2 — Quality Overhaul & Delivery Redesign

> **Version**: 1.0
> **Date**: 2026-03-31
> **Author**: Team CIC (Party Mode Research Session — Mary, Amelia, Winston, Quinn, Devil's Advocate)
> **Status**: DRAFT — Cho Anh Cuong approve
> **Prerequisite**: Phase 1 complete (alpha.10, 1448 tests, 40/40 audit items resolved)
> **Base version**: v2.0.0-alpha.10

---

## 1. TOM TAT TINH HINH

### 1.1 Boi canh

Phase 1 da hoan thanh toan bo: Master Analysis, Tier Extraction, Consensus Engine, Quality Gate,
Historical Metrics, Sentinel Reader, FRED Macro, Mempool Data.

- 10 commits (alpha.1 -> alpha.10)
- Tests: 847 -> 1448 (+601 tests moi)
- 40/40 audit items resolved (32 fixed alpha.5, 5 fixed alpha.10, 3 resolved by other tasks)
- Coverage: 76%+
- Kien truc moi: Master Analysis -> Tier Extraction (loai bo cross-tier contradictions)
- Expert Consensus Engine: 5 sources (Polymarket, F&G, Funding Rate, Whale Flows, ETF Flows)
- Sentinel Integration: Season, SonicR zones, FA scores, NQ05 blacklist
- New collectors: FRED macro, Mempool data, Kalshi fallback

### 1.2 Van de phat hien

Phan tich output thuc te ngay 30-31/03/2026:
- 25 breaking messages + 9 daily messages = 34 messages/ngay
- So sanh voi 10 kenh Telegram canh tranh (Coin68, ThuanCapital, HC Capital, 52Hz, v.v.)

**Phat hien 55+ van de** chia thanh 5 nhom goc:

| Nhom | So luong | Mo ta | Muc do |
|------|----------|-------|--------|
| G1: Delivery UX tham hoa | 12 | Spam, lap, format hong | CRITICAL |
| G2: Content khong dung priority | 8 | Tin quan trong bi bo sot, tin rac duoc gui | HIGH |
| G3: Quality control thieu | 10 | NQ05 lot, overlap 70%, data 0.0000 | HIGH |
| G4: Code v2.0 chua deploy | 5 | Output 30/03 van chay alpha.4 | MEDIUM |
| G5: Kien truc breaking yeu | 10 | Cham 3-6h, feedback ngan, threshold co dinh | MEDIUM |

### 1.3 Phuong phap nghien cuu

- **Scan 3 vong**: code -> output thuc te -> so sanh canh tranh
- **Rule of Three**: moi van de >= 3 phuong an giai quyet truoc khi chon
- **Data thuc te tu Anh Cuong**: 25 breaking messages + Coin68 market update + 10 TG channels
- **4 parallel research agents**: Content Analysis, Breaking Analysis, Competitive Analysis, UX Audit
- **First Principles**: truy tu output -> pipeline -> root cause code

---

## 2. 55 VAN DE — CHI TIET DAY DU

### Nhom G1: Delivery UX tham hoa (12 van de)

---

#### VD-01: Fear & Greed lap 4-5 lan/ngay

**Bang chung**: 30/03 — F&G gui luc 1:38, 4:29, 9:10, 2:26 (4 lan, gia tri chi doi tu 9->8)

**Nguyen nhan code**:
- `market_trigger.py:95` — Title format `f"Fear & Greed Index xuong {fgi.price:.0f} — Extreme Fear"` tao hash moi moi khi gia tri doi 1 diem
- `dedup_manager.py:21` — `COOLDOWN_HOURS = 4`, pipeline chay moi 3h nen cua so cooldown qua ngan
- `breaking-news.yml:5` — Schedule `0 0,6,9,12,15,18,21 * * *` = 7 lan/ngay

**File lien quan**: `breaking/market_trigger.py`, `breaking/dedup_manager.py`, `.github/workflows/breaking-news.yml`

**Giai phap**: Them metric-type daily dedup — moi loai market metric (F&G, BTC drop, ETH drop) chi gui MAX 1 lan/ngay, tru khi delta >= 5 diem. Implement bang dict `_metric_daily_sent` trong dedup_manager, key = metric_type + date.

---

#### VD-02: Tin Canada trung 2 lan

**Bang chung**: 1:38 SA (Bitcoinist) + 4:29 SA (TheBlock) — cung topic Canada ban crypto donations

**Nguyen nhan code**:
- `dedup_manager.py:88` — `SIMILARITY_THRESHOLD = 0.70` — title tieng Anh khac nhau > 30% la lot qua
- `dedup_manager.py:89` — `ENTITY_OVERLAP_THRESHOLD = 0.60` — entity "Canada" khong nam trong `_ENTITY_PATTERN` (line 92-103) vi chi co crypto entities va US states
- `dedup_manager.py:21` — `COOLDOWN_HOURS = 4` — 2 tin cach nhau 3h = vua qua cooldown

**File lien quan**: `breaking/dedup_manager.py`

**Giai phap**:
1. Mo rong `_ENTITY_PATTERN` them quoc gia/to chuc chinh phu: Canada, China, EU, Japan, Korea, India, UK, Russia, Brazil
2. Tang `COOLDOWN_HOURS` tu 4 -> 8 cho hash dedup (entity dedup da dung 7-day window)
3. Them topic clustering: nhom tin theo topic (VD: "Canada crypto regulation") va chi gui 1 tin/topic/12h

---

#### VD-03: Tin chien tranh/dia chinh tri tran ngap (10 tin/ngay)

**Bang chung**: 10 tin ve Iran/Lebanon/Houthi/Israel trong 1 ngay, moi tin gan "lien quan crypto" rat guong ep

**Nguyen nhan code**:
- `event_detector.py:42-55` — `GEOPOLITICAL_KEYWORDS` list 12 keywords, tat ca o `ALWAYS_TRIGGER` tier => trigger bat ke co lien quan crypto hay khong
- `event_detector.py:365-372` — SEC-04 guard chi check `_CRYPTO_CONTEXT_NEUTRALIZERS` — tin thuan geo (khong co crypto context) VAN trigger
- `severity_classifier.py:207-219` — `_GEOPOLITICAL_KEYWORDS` set bypass `_is_crypto_relevant()` check (line 233: `if any(kw in title_lower for kw in _GEOPOLITICAL_KEYWORDS): return True`)

**File lien quan**: `breaking/event_detector.py`, `breaking/severity_classifier.py`

**Giai phap** (3 phuong an, chon ket hop A+C):
- A) Geo events LUON gop digest — khong gui rieng le. Chi CRITICAL geo (nuclear, war declaration) duoc gui rieng
- B) Them geo relevance scoring 0-10 (LLM judge: "tin nay anh huong truc tiep den crypto khong?"). Chi gui >= 6
- C) Daily cap 3 geo events — uu tien theo panic_score

**Chon**: A + C — Geo events gop digest, max 3/ngay, chi CRITICAL (panic >= 90) gui rieng

---

#### VD-04: Tin khong lien quan crypto lot qua (BYD xe dien)

**Bang chung**: "BYD Dan Dau Cuoc Dua Sac Nhanh" — 2:23 CH, lien ket crypto = "gian tiep anh huong ha tang nang luong"

**Nguyen nhan code**:
- `severity_classifier.py:222-234` — `_is_crypto_relevant()` chi chay o severity_classifier (line 285), KHONG chay o event_detector
- `event_detector.py:290` — `if score_triggered or matched:` — neu panic_score cao (CryptoPanic votes) thi van trigger du khong lien quan crypto
- LLM scorer co the cho diem cao du noi dung khong lien quan

**File lien quan**: `breaking/event_detector.py`, `breaking/severity_classifier.py`, `breaking/llm_scorer.py`

**Giai phap**: Move `_is_crypto_relevant()` check vao `_evaluate_items()` trong event_detector (line 269-307), TRUOC khi append event. Hien tai check nay chi o severity_classifier — qua muon.

---

#### VD-05: Gia khong nhat quan xuyen suot

**Bang chung**: BTC $66,398 (1:38) -> $66,554 (4:29) -> $66,645 (9:10) -> $67,232 (Research) -> $67,400 (2:27)

**Nguyen nhan**: Moi pipeline run lay gia thoi diem khac nhau tu CoinGecko/CoinCap. Breaking chay 7 lan/ngay, moi lan lay gia moi.

**File lien quan**: `collectors/market_data.py`, `daily_pipeline.py`, `breaking_pipeline.py`

**Giai phap**: P2.21 PriceSnapshot — dong bang gia 1 lan per pipeline run:
1. Dau pipeline: collect market data 1 lan, luu vao `PriceSnapshot` dataclass
2. Tat ca components trong cung 1 run dung cung PriceSnapshot
3. Breaking messages hien thi "Gia tai thoi diem [HH:MM UTC]"

---

#### VD-06: (Chuyen sang G2 — Content generic)

---

#### VD-07: Bug Fear&Greed symbol mismatch

**Bang chung**:
- `market_data.py:509` tao symbol `"Fear&Greed"` (co `&`)
- `breaking_pipeline.py:841` tim `"Fear_Greed"` (co `_`)
- Ket qua: F&G KHONG BAO GIO xuat hien trong market snapshot context cua breaking news

**File lien quan**: `collectors/market_data.py:509`, `breaking_pipeline.py:841`

**Giai phap**: Dong nhat symbol thanh `"Fear&Greed"` o `breaking_pipeline.py:841`. Doi `"Fear_Greed"` thanh `"Fear&Greed"`. Day la bug 1-line fix.

---

#### VD-21: 31+ tin/ngay = SPAM

**Bang chung**: 25 breaking + 9 daily (L2+L3+L4+L5x2+Summary+Researchx3) = 34 messages

**Nguyen nhan code**:
- `breaking_pipeline.py:37` — `MAX_EVENTS_PER_RUN = 5`, pipeline chay 7 lan/ngay = max 35 breaking/ngay
- `breaking-news.yml:5` — 7 runs/ngay (0,6,9,12,15,18,21 UTC)
- Daily pipeline gui 9 messages (L2+L3+L4+L5 Part1+L5 Part2+Summary+Research Part1+Part2+Part3)
- KHONG co `MAX_EVENTS_PER_DAY` cho breaking

**File lien quan**: `breaking_pipeline.py`, `.github/workflows/breaking-news.yml`

**Giai phap** (ket hop):
1. Them `MAX_EVENTS_PER_DAY = 12` — cap tong so breaking events duoc gui trong ngay
2. Giam breaking schedule tu 7 -> 4 lan/ngay: `0 0,6,12,18 * * *`
3. Redesign delivery (xem Section 4)

---

#### VD-28: Pipeline failure gui cho member

**Bang chung**: "Warning [Breaking News] Pipeline THAT BAI" — 5:16 CH, tren channel thanh vien

**Nguyen nhan code**:
- `delivery/telegram_bot.py:300-308` — `send_admin_alert()` dung cung `TelegramBot()` constructor
- `TelegramBot.__init__()` doc `TELEGRAM_CHAT_ID` env var — cung ID cho member messages va admin alerts
- Khong co `ADMIN_CHAT_ID` rieng

**File lien quan**: `delivery/telegram_bot.py`

**Giai phap**: Tao `ADMIN_CHAT_ID` env var rieng cho admin/error alerts. `send_admin_alert()` su dung `ADMIN_CHAT_ID` thay vi `TELEGRAM_CHAT_ID`. Default fallback: neu `ADMIN_CHAT_ID` khong set, log warning va KHONG gui (thay vi gui cho member).

---

#### VD-29: Nguon "market_data" lo ten noi bo

**Bang chung**: F&G alert ghi "Lien ket Nguon: market_data"

**Nguyen nhan code**:
- `market_trigger.py:58` — `source="market_data"` (internal name)
- `content_generator.py:138` — `_format_source_link(source, url)` hien thi source tren as-is

**File lien quan**: `breaking/market_trigger.py`, `breaking/content_generator.py`

**Giai phap**: Tao `SOURCE_DISPLAY_MAP` dict trong content_generator.py:
```python
SOURCE_DISPLAY_MAP = {
    "market_data": "Alternative.me Fear & Greed Index",
    "market_trigger": "CIC Market Monitor",
    "rss_collector": None,  # use actual source name
}
```
Ap dung trong `_format_source_link()`.

---

#### VD-31: DXY 100.2 lap trong MOI tin breaking

**Bang chung**: Hau het breaking deu co "Chi so DXY dang o muc 100.2"

**Nguyen nhan code**:
- `breaking_pipeline.py:832-845` — `_format_market_snapshot()` LUON include DXY neu co data
- `content_generator.py:44` — `{market_context}` inject vao MOI breaking prompt
- LLM nhan DXY data -> tu dong viet ve DXY trong moi bai

**File lien quan**: `breaking_pipeline.py`, `breaking/content_generator.py`

**Giai phap**: Chi inject DXY khi:
1. Event la macro event (matched keyword trong `GEOPOLITICAL_KEYWORDS` hoac `_MACRO_KEYWORDS`)
2. DXY change_24h >= 0.5% (co bien dong dang ke)
Khong inject DXY vao crypto-specific events (hack, partnership, ETF, v.v.)

---

#### VD-36: Disclaimer chiem 15-20% moi tin

**Bang chung**: 25+ lan disclaimer trong ngay, moi lan 170 ky tu (line 32-38 article_generator.py)

**File lien quan**:
- `generators/article_generator.py:32-38` — `DISCLAIMER` constant (170 chars)
- `breaking/content_generator.py:248` — append DISCLAIMER vao moi breaking
- `generators/summary_generator.py` — append DISCLAIMER vao summary
- `generators/tier_extractor.py` — append DISCLAIMER vao moi tier
- `generators/research_generator.py` — append DISCLAIMER vao research

**Giai phap**:
- Breaking -> rut gon 1 dong: `"Do not DYOR — Khong phai loi khuyen dau tu."`
- Daily -> full disclaimer chi o tin CUOI CUNG (Summary hoac Research)
- Tao 2 constants: `DISCLAIMER_SHORT` va `DISCLAIMER_FULL`

---

#### VD-38: Format TONG HOP vs Breaking don le khac nhau

**Bang chung**: Digest mode (TONG HOP) format khac hoan toan Breaking don le — digest dung numbered list, breaking dung heading + paragraphs

**File lien quan**: `breaking/content_generator.py:82-105` — `DIGEST_PROMPT_TEMPLATE` vs `BREAKING_PROMPT_TEMPLATE` (line 36-80)

**Giai phap**: Thong nhat visual template:
- Ca 2 dung: Heading bam + 2 doan (CHUYEN GI XAY RA + TAI SAO QUAN TRONG)
- Digest: moi event la 1 section nho voi cung format

---

### Nhom G2: Content khong dung priority (8 van de)

---

#### VD-06: Noi dung generic — "he qua" khong cu the

**Bang chung**: Hau het tin ket thuc bang "Nha dau tu chien luoc dai han can theo doi chat che..."

**Nguyen nhan code**:
- `content_generator.py:36-80` — `BREAKING_PROMPT_TEMPLATE` yeu cau "HE QUA CU THE" (line 60) nhung LLM thuong viet generic
- Prompt KHONG cung cap du data de LLM viet cu the (khong co consensus check, khong co cross-asset impact, khong co Polymarket probability)

**File lien quan**: `breaking/content_generator.py`

**Giai phap**: P2.4 Breaking Enrichment — them data cu the vao prompt:
1. Consensus snapshot: "BTC consensus: BULLISH (3/5 sources dong thuan)"
2. Cross-asset impact: "ETH correlation: +0.92, SOL: +0.85"
3. Polymarket probability: "BTC > $70K by EOY: 68% (Polymarket)"
4. Historical parallel: "Lan truoc F&G=9 (Jan 2023), BTC phuc hoi 45% trong 3 thang"

---

#### VD-10: Nguon tin VN — pipeline co 14 nguon VN nhung KHONG DUNG DUOC

**Bang chung**: Coin68 RSS + 9 TG channels DA CO trong code, nhung tin Thong tu 32, ONUS bat KHONG xuat hien

**Nguyen nhan code**:
- `rss_collector.py:55-74` — Co Coin68, TapChiBitcoin, CafeF, VnEconomy, BlogTienAo RSS feeds
- `event_detector.py:30-36` — `ALWAYS_TRIGGER_KEYWORDS` chi co 5 tu tieng Anh (hack, exploit, rug pull, delisting, bankrupt)
- `event_detector.py:57-63` — `CONTEXT_REQUIRED_KEYWORDS` chi co 5 tu tieng Anh (crash, collapse, SEC, ban, emergency)
- KHONG co VN regulatory keywords nao
- `telegram_scraper.py` — TG scraper (Telethon) co the chua hoat dong on dinh

**File lien quan**: `collectors/rss_collector.py`, `breaking/event_detector.py`, `collectors/telegram_scraper.py`

**Giai phap**:
1. Them `VN_REGULATORY_KEYWORDS` vao `ALWAYS_TRIGGER_KEYWORDS`:
   ```python
   VN_REGULATORY_KEYWORDS = [
       "thong tu",      # circular (regulatory)
       "nghi quyet",    # resolution
       "bo tai chinh",  # Ministry of Finance
       "ngan hang nha nuoc",  # State Bank
       "ubcknn",        # Securities Commission
       "san giao dich",  # exchange (VN context)
       "ONUS", "Remitano", "VNDC",  # VN exchanges
       "luat",          # law
       "quy dinh moi",  # new regulation
   ]
   ```
2. Tin VN regulatory -> auto `CRITICAL` severity trong severity_classifier
3. Verify Telethon scraper hoat dong — them monitoring alert khi TG fail

---

#### VD-11: Dao lon uu tien — easy-to-detect over important

**Bang chung**: 14 tin it gia tri (F&Gx4 + chien tranhx10) duoc gui, 10 tin gia tri cao (thue VN, ONUS, Morgan Stanley...) bi bo qua

**Nguyen nhan goc**: Pipeline chon tin dua vao keyword matching + panic_score, KHONG danh gia "quan trong the nao cho NDT crypto VN"

**File lien quan**: `breaking/event_detector.py`, `breaking/severity_classifier.py`, `breaking/llm_scorer.py`

**Giai phap**: LLM Impact Scoring — Groq LLM prompt:
```
"Tin nay quan trong co nao cho NDT crypto VN dai han? Score 1-10.
Tieu chi: anh huong truc tiep den gia/regulation/adoption tai VN.
Chi tra loi bang 1 so."
```
- Score >= 7 -> gui ngay
- Score 4-6 -> digest
- Score <= 3 -> skip

Implement trong `llm_scorer.py` bang LLM call nhe (Groq Qwen3, max_tokens=10, temperature=0).

---

#### VD-12: Khong co co che phat hien "tin lon"

**Bang chung**: Morgan Stanley ETF, 401(k), Fannie Mae — tin thay doi cuoc choi nhung bi bo sot

**Nguyen nhan**: Chi dua CryptoPanic + RSS, bo sot tin tu Bloomberg, WSJ, Reuters. RSS Google News proxy (line 79-88 rss_collector.py) co Reuters/AP nhung chi business category, khong loc crypto chuyen biet.

**File lien quan**: `collectors/rss_collector.py:79-92`

**Giai phap**:
1. Them RSS sources: NewsAPI.org free tier (500 req/day), GDELT Project (free, unlimited)
2. TG channel Tier 2-3 implement (brainstorm doc da list 20+ channels chua implement):
   - Bloomberg Crypto, WSJ Markets, Reuters Business, FT Crypto
3. Expand Google News proxy queries: them `q=crypto+regulation`, `q=bitcoin+etf`

---

#### VD-32: Daily Report KHONG cover tin quan trong nhat ngay

**Bang chung**: So sanh voi Coin68 market update — CIC bo sot Strategy/Lido/EEZ/CLARITY/Square

**Nguyen nhan code**:
- Daily pipeline (`daily_pipeline.py`) nhan market data nhung KHONG nhan NEWS events tu breaking
- `feedback.py:127` — `summary[:200]` — breaking feedback chi luu 200 ky tu (qua ngan de LLM hieu)
- Daily pipeline co doc `read_breaking_summary()` nhung data bi cat ngan

**File lien quan**: `breaking/feedback.py`, `daily_pipeline.py`

**Giai phap**:
1. Tang `summary[:200]` -> `summary[:1000]` (da co ke hoach, xem VD-20)
2. Daily pipeline's Master Analysis PHAI doc BREAKING_LOG tu Google Sheets (khong chi feedback file)
3. Master Analysis prompt phai co section "TOP BREAKING NEWS HOM NAY" voi tieu de + severity

---

#### VD-34: Tu tieng Anh lot vao bai tieng Viet

**Bang chung**: "busiest", "sector DEX", "Market Cap giam"

**File lien quan**: `generators/article_generator.py:41-59` — `NQ05_SYSTEM_PROMPT` yeu cau tieng Viet nhung khong co glossary

**Giai phap**: Tao Vietnamese glossary inject vao system prompt:
```python
VIETNAMESE_GLOSSARY = {
    "Market Cap": "Von hoa",
    "Funding Rate": "Ty le Funding",
    "Fear & Greed Index": "Chi so So hai & Tham lam (F&G)",
    "Open Interest": "Vi the mo",
    "Liquidation": "Thanh ly",
    "Whale": "Ca voi (whale)",
    "Stablecoin": "Stablecoin",  # giu nguyen
    "DeFi": "DeFi",  # giu nguyen
    "TVL": "TVL (Tong gia tri khoa)",
    "DEX": "San phi tap trung (DEX)",
    "CEX": "San tap trung (CEX)",
}
```
Inject vao NQ05_SYSTEM_PROMPT: "BANG THUAT NGU: Khi viet tieng Viet, dung ten tieng Viet thay the: ..."

---

#### VD-35: L5 chia 2 phan cat ngau nhien

**Bang chung**: Part 1/2 ket thuc giua Scenario Analysis

**File lien quan**: `delivery/telegram_bot.py` — message splitting logic (line 24: `TG_MAX_LENGTH = 4000`)

**Giai phap**: Split tai section breaks (`## headings`), KHONG split giua section. Algorithm:
1. Tim tat ca `## ` positions trong content
2. Split tai `## ` gan nhat ma khong vuot TG_MAX_LENGTH
3. Neu khong co `## ` phu hop, split tai `\n\n` (paragraph break)
4. Fallback: split tai position TG_MAX_LENGTH (hien tai)

---

#### VD-37: Severity icon khong co giai thich

**Bang chung**: Nguoi doc thay "Do" va "Cam" nhung khong biet nghia

**File lien quan**: `breaking/severity_classifier.py:28-32`

**Giai phap**: Them legend 1 lan/ngay (tin breaking dau tien moi ngay):
```
Do = KHOAN CAP (hack, crash lon)
Cam = QUAN TRONG (regulation, partnership lon)
Vang = DANG CHU Y (tin tuc noi bat)
```
Hoac pin message voi legend tren channel.

---

### Nhom G2 (tiep): Content quality

---

#### VD-39 (NEW): L2 = ZERO so lieu, ZERO gia tri

**Bang chung**: L2 toan bo: 0 con so, 0 BTC price, 0 F&G value. Noi dung chi la van xuoi chung chung.

**Nguyen nhan code**:
- `article_generator.py:317-324` — L2 data filtering:
  ```python
  elif tier == "L2":
      full["onchain_data"] = ""
      full["economic_events"] = ""
      full["whale_data"] = ""
      full["research_data"] = ""
      full["historical_context"] = ""
      full["consensus_data"] = ""
  ```
  L2 nhan market_data + news + sector_data nhung LLM khong bat buoc dung so lieu.
- Tier Extractor L2 config (tier_extractor.py:47) khong co format_instructions bat buoc so lieu.

**File lien quan**: `generators/article_generator.py:317-324`, `generators/tier_extractor.py`

**Giai phap**: Force inject BTC price + F&G + top 3 altcoin % change vao L2 opening:
1. Tier Extractor L2 config: them `format_instructions` yeu cau mo dau bang data:
   ```
   "BAT BUOC: Dong dau tien PHAI co BTC price + % change. Dong 2 co F&G value.
   MOI altcoin duoc nhac PHAI kem % change 24h."
   ```
2. Quality Gate: check L2 co it nhat 3 so lieu cu the (density >= 0.20 cho L2)

---

#### VD-40 (NEW): Research vs L5 overlap >= 70%

**Bang chung**: F&G, Funding Rate, stablecoin flows co trong CA HAI Research va L5.

**File lien quan**: `generators/research_generator.py`, `generators/tier_extractor.py`

**Giai phap**: Research KHONG cover market overview (da co L5). Tap trung:
1. On-chain deep dive (MVRV, NUPL, SOPR, Puell — chi Research co)
2. Model analysis (Pi Cycle, Stock-to-Flow)
3. Institutional perspective (ETF flows detail, whale address analysis)
4. Macro-to-crypto causal chain (FRED data -> BTC correlation analysis)
5. Tier Extractor Research config: them `format_instructions`:
   ```
   "KHONG lap lai market overview da co trong L5 (F&G, funding rate, market summary).
   TAP TRUNG: on-chain metrics ssu, institutional flows, macro analysis."
   ```

---

### Nhom G3: Quality control thieu (10 van de)

---

#### VD-09: NQ05 borderline

**Bang chung**: "xem xet gia tang ty trong theo chien luoc DCA", "gia co the tang len 30%"

**File lien quan**: `generators/nq05_filter.py:99-123` — `SEMANTIC_NQ05_PATTERNS`

**Giai phap**: Xem VD-18 (mo rong NQ05 patterns)

---

#### VD-14: Cac tier L2->L5 lap noi dung 70-80%

**Bang chung**: L2, L3, L4 mo dau gan giong nhau ("Chao mung cac thanh vien CIC...")

**Nguyen nhan code**:
- `tier_extractor.py:47+` — moi tier chi co prompt "KHONG lap lai" nhung KHONG co enforcement code
- `quality_gate.py` — KHONG co `check_cross_tier_overlap()` function
- Master Analysis -> Tier Extraction architecture DUNG RA phai giam overlap, nhung LLM van co the extract cung cau

**File lien quan**: `generators/tier_extractor.py`, `generators/quality_gate.py`

**Giai phap**: Implement cross-tier overlap check post-extraction:
1. Sau khi extract tat ca tiers, tinh sentence-level overlap giua moi cap (L1-L2, L2-L3, L3-L4, L4-L5)
2. Neu overlap > 40% -> retry tier co overlap cao nhat voi instruction:
   ```
   "BAI TRUOC (L{N-1}) DA VIET: [first 500 chars of previous tier]
   KHONG DUOC lap lai bat ky cau nao tu bai truoc."
   ```
3. Them `check_cross_tier_overlap()` trong quality_gate.py

---

#### VD-15: Quality Gate LOG-ONLY — khong chan bai sai

**Bang chung**: `quality_gate.py:1-4` — Comment: "Phase 1a: LOG-ONLY"

**Nguyen nhan**: Phase 1a design decision — can data thuc te truoc khi bat BLOCK mode. Da co 10 alpha versions, du data.

**File lien quan**: `generators/quality_gate.py`

**Giai phap**: Chuyen sang BLOCK mode:
1. `factual_issues > 0` -> retry 1 lan voi instruction "SUA LOI: [issue description]"
2. `density < INSIGHT_DENSITY_THRESHOLD (0.30)` -> retry 1 lan voi instruction "THEM SO LIEU CU THE"
3. Retry chi 1 lan — neu fail lan 2 thi log WARNING va gui bai (khong block pipeline)
4. Them config `QUALITY_GATE_MODE = "block"` (co the revert ve "log" neu can)

---

#### VD-16: Consensus Engine chi 2-3 nguon hoat dong thuc te

**Bang chung**: Whale Alert tra phi, ETF flows co the stale, Funding Rate phu thuoc fallback chain

**Nguyen nhan code**:
- `consensus_engine.py:50` — `MIN_SOURCES_FOR_CONSENSUS = 2` — chi can 2 nguon la hien thi "Consensus"
- Thuc te: Polymarket + F&G = 2 nguon luc nao cung co. Funding Rate, Whale Flows, ETF Flows co the fail.

**File lien quan**: `generators/consensus_engine.py`

**Giai phap**:
1. Khi < 3 sources, KHONG hien thi "CONSENSUS" label — chi hien thi "SIGNALS" (individual)
2. Log ro bao nhieu sources thuc su dong gop: `logger.info(f"Consensus: {n_sources} sources active")`
3. Them transparency text trong LLM context:
   ```
   "Consensus (3/5 sources): BULLISH | Missing: Whale Flows (API down), ETF Flows (stale)"
   ```

---

#### VD-18: NQ05 filter bo sot nhieu pattern tieng Viet

**Bang chung**: "gia tang ty trong" khong bi bat, "co the tang len 30%" khong bi bat

**File lien quan**: `generators/nq05_filter.py:99-123` — `SEMANTIC_NQ05_PATTERNS`

**Giai phap**: Them patterns moi vao `SEMANTIC_NQ05_PATTERNS`:
```python
# Phase 2 additions
r"(?:gia tang|giam)\s+ty trong",
r"(?:co the|du kien)\s+tang\s+(?:len|toi)\s+\d+%",
r"chien luoc\s+(?:DCA|ADCA|tich luy)\s+(?:\w+\s+){0,3}(?:nen|xem xet|can nhac)",
r"vung\s+(?:mua|ban)\s+(?:ly tuong|tot|hap dan)",
r"(?:target|muc tieu)\s+(?:\$|price|gia)\s*[:=]?\s*\d",
r"(?:nen|hay)\s+(?:chot loi|chot lo|take profit|stop loss)",
```

---

#### VD-19: Master Analysis truncation risk

**Bang chung**: 6000 tu tieng Viet ~ 12-15K tokens, sat gioi han 16K

**File lien quan**: `generators/master_analysis.py:25` — `MASTER_MAX_TOKENS = 16384`

**Giai phap**:
1. Them word limit trong prompt: "TUYET DOI khong vuot 5000 tu"
2. Them check sau generation: `if word_count > 5500: logger.warning("Master Analysis qua dai")`
3. Tang `MASTER_MAX_TOKENS` len 20480 de co headroom (Gemini 2.5 Flash ho tro 65K output)
4. Fallback: neu finish_reason="length" (truncated), retry voi prompt "RUT GON — TOI DA 4000 tu"

---

#### VD-27: On-chain metrics = 0.0000 -> LLM dien giai sai

**Bang chung**: Research viet "buc tranh kha tram lang" khi thuc te MVRV/NUPL/SOPR = 0.0000 (API fail)

**Nguyen nhan code**:
- `collectors/research_data.py:107` — `f"  {m.name}: {m.value:.4f} ({m.source}, {m.date})"` — format 0.0000 gui cho LLM, LLM tuong data that
- Khong co check `value == 0.0` truoc khi format

**File lien quan**: `collectors/research_data.py:107`

**Giai phap**: Filter 0.0000 values TRUOC khi gui LLM:
```python
# Trong format_for_llm():
for m in self.onchain_advanced:
    if abs(m.value) < 0.0001:
        lines.append(f"  {m.name}: KHONG CO DU LIEU (API unavailable)")
    else:
        lines.append(f"  {m.name}: {m.value:.4f} ({m.source}, {m.date})")
```
Neu >= 3/4 BGeometrics metrics = 0.0000 -> flag "On-chain data KHONG KHA DUNG — bo qua phan on-chain trong phan tich hom nay"

---

#### VD-30: "tien dien tu" vi pham NQ05

**Bang chung**: Output co the co "tien dien tu" tu LLM generation

**File lien quan**: `generators/nq05_filter.py:41-47` — `TERMINOLOGY_FIXES` dict da co mapping

**Giai phap**: `TERMINOLOGY_FIXES` DA xu ly "tien dien tu" -> "tai san ma hoa" (line 42-47). Van de la prompt cua research_generator.py va content_generator.py cung can nhan manh:
1. Grep toan bo prompts cho "tien dien tu" — thay bang "tai san ma hoa"
2. Verify moi prompt co dong: `"Dung 'tai san ma hoa' thay 'tien dien tu'"`

---

#### VD-33: Consensus Engine output KHONG hien thi

**Bang chung**: 831 dong code Consensus Engine nhung KHONG CO section "Consensus" nao trong output L2-L5, Summary, Research

**Nguyen nhan code**:
- `article_generator.py:294-295` — `consensus_data` duoc truyen vao context nhung chi cho L3+ (L1/L2 set "")
- `tier_extractor.py` — extraction prompt khong yeu cau hien thi consensus section mot cach noi bat
- Master Analysis prompt co yeu cau su dung consensus nhung tier extraction co the bo qua

**File lien quan**: `generators/consensus_engine.py`, `generators/tier_extractor.py`, `generators/article_generator.py`

**Giai phap**: Them section "CONSENSUS" noi bat:
1. Summary extraction: bat buoc co section "Tin hieu Dong thuan (Expert Consensus)" ngay sau market overview
2. L3+ extraction: bat buoc co 1 doan "Consensus Engine cho thay: [label] ([score], [n] nguon)"
3. Format:
   ```
   CONSENSUS: BULLISH (+0.35, 4/5 nguon)
   - Polymarket: BTC > $70K EOY = 68%
   - Funding Rate: +0.02% (duong = long-biased)
   - F&G: 32 (Fear — retail so, institutional van mua)
   ```

---

#### VD-39: (Da liet ke o tren — L2 ZERO data)

#### VD-40: (Da liet ke o tren — Research vs L5 overlap)

---

### Nhom G4: Code v2.0 chua deploy (5 van de)

---

#### VD-41 (NEW): Output 30/03 = alpha.4, chua co Master Analysis

**Bang chung**: Pipeline chay 01:05 UTC 30/03, alpha.6 commit SAU do (06dab56). Output 30/03 van la architecture cu (per-tier parallel).

**Giai phap**: Deploy alpha.10+ va verify output thuc te. Van de nay tu resolve khi deploy.

---

#### VD-42 (NEW): Pipeline chay alpha.4 -> per-tier parallel -> cross-tier contradictions

**Bang chung**: Output 30/03 co L1 noi "khong co su kien" nhung L3 noi "Fed giu nguyen lai suat"

**Giai phap**: Tu resolve khi deploy alpha.6+ (Master Analysis architecture). Khong can code change.

---

#### VD-43 (NEW): Consensus Engine code done nhung output khong hien thi

**Bang chung**: alpha.4 co Consensus Engine nhung output khong co section Consensus

**Giai phap**: Xem VD-33. Can explicit display enforcement trong tier extraction prompts.

---

#### VD-44 (NEW): 9 Telegram messages daily = UX disaster

**Bang chung**: L2+L3+L4+L5 Part1+L5 Part2+Summary+Research Part1+Part2+Part3 = 9 messages

**File lien quan**: `daily_pipeline.py`, `delivery/telegram_bot.py`

**Giai phap**: Redesign delivery (xem Section 4). Target: 2-3 daily messages thay vi 9.

---

#### VD-23: Hai code path tao Summary

**Bang chung**: `summary_generator.py` (standalone) va `tier_extractor.py` (Summary extraction tu Master) — 2 code paths cho cung 1 output

**File lien quan**: `generators/summary_generator.py`, `generators/tier_extractor.py`

**Giai phap**: Deprecate `summary_generator.py`. Master Analysis -> Tier Extractor Summary la source of truth. Giu `summary_generator.py` lam fallback khi Master fails (da co fallback logic trong daily_pipeline.py).

---

### Nhom G5: Kien truc breaking yeu (10 van de)

---

#### VD-17: Breaking cham 3-6 gio

**Bang chung**: Pipeline 3h interval, cache 2h (event_detector.py:25 `CACHE_MAX_AGE = 7200`), RSS khong loc thoi gian

**File lien quan**: `.github/workflows/breaking-news.yml`, `breaking/event_detector.py:25`

**Giai phap**:
1. Giam interval -> 1.5h cho breaking: `0 0,2,4,6,8,10,12,14,16,18,20,22 * * *` (12 runs, KET HOP voi MAX_EVENTS_PER_DAY = 12 de khong spam)
2. Giam `CACHE_MAX_AGE` tu 7200 -> 3600 (1h)
3. Filter RSS articles: chi lay `published < 3h` (them check `published_parsed` trong rss_collector.py)

HOAC (don gian hon):
1. Giam interval -> 2h: `0 0,2,4,6,8,10,12,14,16,18,20,22 * * *`
2. Giu `CACHE_MAX_AGE = 7200` (protect API quota)
3. `MAX_EVENTS_PER_DAY = 12` cap spam

---

#### VD-20: Feedback loop chi luu 200 ky tu

**Bang chung**: `feedback.py:127` — `summary[:200]`

**File lien quan**: `breaking/feedback.py:127`

**Giai phap**: Tang `summary[:200]` -> `summary[:1000]`. Ca total event cap `MAX_EVENTS_PER_DAY = 100` (da co line 32) nen 1000 chars/event x 100 = max 100KB — an toan.

---

#### VD-22: Telethon = single point of failure

**File lien quan**: `collectors/telegram_scraper.py`

**Giai phap**:
1. Monitoring alert khi TG fail 3 lan lien tiep
2. Fallback doc + re-auth guide
3. Them RSS backup cho top TG channels (nhieu channel co RSS mirror)
4. Health check endpoint: log `telegram_scraper_status` vao NHAT_KY_PIPELINE

---

#### VD-24: Market trigger thresholds co dinh

**File lien quan**: `breaking/market_trigger.py:15-27`

**Bang chung**: `BTC_DROP_THRESHOLD = -7.0`, `ETH_DROP_THRESHOLD = -10.0`, `FEAR_GREED_THRESHOLD = 10` — co dinh bat ke mua nao

**Giai phap**: Dung Sentinel Season de adjust thresholds:
```python
SEASON_THRESHOLD_ADJUSTMENTS = {
    "MUA_HE": {"btc_drop": -10.0, "eth_drop": -12.0, "fgi": 15},  # Mua He = volatility cao -> threshold cao hon
    "MUA_THU": {"btc_drop": -7.0, "eth_drop": -10.0, "fgi": 10},   # Default
    "MUA_DONG": {"btc_drop": -5.0, "eth_drop": -7.0, "fgi": 15},   # Mua Dong = moi drop deu quan trong
    "MUA_XUAN": {"btc_drop": -7.0, "eth_drop": -10.0, "fgi": 8},   # Mua Xuan = alert early
}
```
Sentinel Season da co san tu P1.12 (`sentinel_reader.py`).

---

#### VD-25: Google News proxy khong on dinh

**File lien quan**: `collectors/rss_collector.py:79-92`

**Bang chung**: Google News RSS proxy co the bi rate limit hoac thay doi format

**Giai phap**:
1. NewsAPI.org free tier (500 req/day) lam nguon macro chinh
2. GDELT Project (free, unlimited) lam fallback
3. Giu Google News proxy lam fallback cuoi

---

#### VD-08: Pipeline failure handling

**Bang chung**: Pipeline crash -> khong co retry mechanism

**Giai phap**: Da co retry_utils.py (exponential backoff). Can them:
1. Pipeline-level retry: neu daily_pipeline crash, GitHub Actions re-run 1 lan (workflow retry)
2. Partial success handling: neu 3/5 tiers thanh cong, gui 3 tiers + log warning

---

#### VD-13: Daily report thieu whale/ETF detail

**Bang chung**: L5/Research noi "dong tien ETF" nhung khong co con so cu the

**Nguyen nhan**: Whale Alert tra phi (Glassnode cung tra phi). ETF flows data co the stale.

**Giai phap**:
1. btcetffundflow.com (free) da duoc implement trong research_data.py — verify no chay dung
2. Whale flows: CoinMetrics Community free tier co exchange flow data — da implement trong coinmetrics_data.py
3. Ensure data duoc inject vao Master Analysis prompt (khong bi filter ra)

---

#### VD-26: Spec thieu critical path analysis

**Giai phap**: Phase 2 spec nay (document hien tai) bao gom Section 6 — Dependencies & Critical Path.

---

## 3. PHAN TICH CANH TRANH

### 3.1 So sanh 10 kenh (data ngay 30-31/03/2026)

| Kenh | Tin/ngay | Do tre | Noi dung | The manh | Diem yeu |
|------|----------|--------|----------|----------|----------|
| **Coin68 Market Update** | 2-3 | 1-3h | Tin tuc + phan tich nhe | Cover rong, VN context | Generic, khong on-chain |
| **ThuanCapital** | 1-2 | 6-12h | Phan tich sau, opinion | Causal chain, original thinking | Cham, khong real-time |
| **HC Capital** | 3-5 | 1-2h | TA + on-chain | Liquidation heatmap, funding rate | Chi BTC/ETH, khong macro |
| **52Hz Crypto** | 5-10 | <15min | Wallet tracking, whale alert | Real-time, specific addresses | Qua nhieu tin, noise |
| **5PhutCrypto** | 2-3 | 1-3h | Tin tuc + token unlock | Token unlock calendar | Khong co on-chain deep |
| **Krypto News VN** | 10-15 | <15min | Aggregator, tin nhanh | Nhanh nhat | Zero analysis, copy-paste |
| **Upside Vietnam** | 1-2 | 6-24h | VN regulation specialist | VN regulatory chieu sau | Rat cham, it tin |
| **CoinVN** | 3-5 | 1-3h | Tin tuc + gia | Cover rong, tieng Viet | Generic, khong insight |
| **Crypto Station** | 2-3 | 2-6h | TA + sentiment | RSI/MACD analysis | Template-based |
| **CIC (hien tai)** | 34 | 3-6h | 5-tier + breaking | Coverage rong, auto 24/7 | SPAM, generic, priority sai |

### 3.2 CIC Unique Value vs Gaps

**The manh duy nhat CIC (khong kenh nao co)**:
1. **Expert Consensus Engine** — 5+ sources, weighted scoring, divergence detection
2. **Tiered content** — L1-L5 cho nhieu trinh do
3. **Cross-signal divergence detection** tu dong (F&G vs Funding Rate vs Whale Flows)
4. **Automated 24/7, $0/thang** — khong phu thuoc con nguoi
5. **NQ05 compliance** — phap ly an toan cho CIC
6. **Historical context** — 7d/30d comparison tu LICH_SU_METRICS

**Tat ca kenh khac co ma CIC thieu**:
1. **Specific wallet addresses** (52Hz) — CIC khong track individual wallets
2. **Liquidation heatmap zones** (HC Capital) — can Coinalyze premium hoac Coinglass
3. **Token unlock calendar** (5PhutCrypto) — chua co collector
4. **Deep macro causal chain** (ThuanCapital) — CIC co data nhung LLM chua duoc prompt de phan tich sau
5. **Real-time push < 15 phut** (Krypto News, 52Hz) — CIC chay moi 3h
6. **VN regulatory specialist** (Upside, 5PhutCrypto) — CIC co RSS nhung khong uu tien VN news
7. **Original analysis/opinion** (ThuanCapital) — CIC la AI-generated, chua co "voice"

### 3.3 Strategy: Dan trong HOA hon la theo duoi

CIC KHONG NEN canh tranh:
- Real-time speed (< 15 min) — doi hoi infra phuc tap, $$$
- Individual wallet tracking — doi hoi on-chain infra
- Manual analysis depth (ThuanCapital-style) — AI chua bang expert

CIC NEN dan trong:
- **Consensus Intelligence** — tong hop nhieu goc nhin (KHONG kenh nao co)
- **VN regulatory coverage** — Upside qua cham, CIC co the nhanh hon
- **Data-driven tiered content** — auto-personalize theo trinh do
- **Cross-signal alerts** — F&G low + Funding positive + Whale accumulating = signal manh

---

## 4. THIET KE LAI DELIVERY (Consumption-First)

### 4.1 Nguyen tac

1. Thiet ke tu goc NGUOI DOC, khong phai nguoi tao content
2. Target: <= 8 messages/ngay (tu 34 hien tai)
3. Moi message phai co gia tri rieng, khong lap
4. Format nhat quan xuyen suot
5. Breaking chi gui khi THUC SU quan trong

### 4.2 Flow moi de xuat

**SANG (08:15 VN = 01:15 UTC):**
- 1 tin **Morning Digest** = Summary + top 3 breaking dem qua + Consensus snapshot
- Gui: BIC Chat + BIC Group
- Tuong duong: hien tai L2+L3+L4+Summary = 4 messages -> 1 message

**TRUA (13:00 VN = 06:00 UTC):**
- 1 tin **L5 Deep Analysis** (tach biet, khong trung Summary)
- Gui: BIC Group only (paid members)
- Tuong duong: hien tai L5 Part1+Part2 = 2 messages -> 1 message (rut ngan)

**CHIEU (17:00 VN = 10:00 UTC):**
- 1 tin **Breaking Digest** = gop tat ca important events buoi chieu
- Gui: BIC Chat + BIC Group
- Chi gui neu co >= 2 events. Neu 0-1 event -> skip (gui rieng le neu CRITICAL)

**TOI (20:00 VN = 13:00 UTC):**
- 1 tin **Research** (3 lan/tuan thay vi daily — T2/T4/T6)
- Gui: BIC Group only (paid members)
- Tuong duong: hien tai Research Part1+Part2+Part3 = 3 messages -> 1 message (rut ngan)

**CRITICAL BREAKING (bat ky luc nao):**
- Chi khi: BTC drop > 10%, exchange hack xac nhan, regulatory shock (SEC, ban quoc gia)
- Gui rieng NGAY LAP TUC
- Gioi han: MAX 3 CRITICAL/ngay
- Criteria: `severity == "critical"` AND `panic_score >= 85`

### 4.3 Tac dong

| Metric | Hien tai | Moi |
|--------|----------|-----|
| Total messages/ngay | 34 | 3-5 |
| Daily messages | 9 | 2-3 |
| Breaking messages | 25 | 0-3 (digest + critical only) |
| Giam | - | 85-90% |

### 4.4 Implementation details

**Morning Digest**: New delivery mode trong `daily_pipeline.py`:
1. Master Analysis -> extract Summary (da co)
2. Doc `breaking_today.json` -> top 3 events
3. Format: Summary + "--- TIN NONG DEM QUA ---" + 3 breaking summaries + Consensus snapshot
4. Single Telegram message (<= 4000 chars)

**L5 Standalone**: Rut ngan L5 tu ~6000 chars (2 parts) xuong ~3500 chars (1 part):
1. Tier Extractor L5 config: giam `target_words` tu (2500, 4000) xuong (1500, 2500)
2. Skip Scenario Analysis section (chuyen vao Research)

**Breaking Digest**: New scheduled run luc 17:00 VN:
1. Doc tat ca events tu 08:00-17:00 VN (BREAKING_LOG status="sent" hoac "deferred_to_daily")
2. Generate 1 digest message
3. Neu 0 events -> skip

**Research Weekly**: Doi frequency tu daily -> 3x/week:
1. `.github/workflows/daily-pipeline.yml`: them condition `if day_of_week in [1, 3, 5]` (Mon/Wed/Fri)
2. Rut ngan tu ~9000 chars (3 parts) xuong ~4000 chars (1 part)
3. Focus: on-chain deep + institutional + macro (KHONG market overview)

### 4.5 Migration plan

1. **Wave 0**: Deploy alpha.10, verify output (khong thay doi delivery)
2. **Wave 1**: Implement Morning Digest + reduce L5 + reduce Research
3. **Wave 2**: Implement Breaking Digest + cap CRITICAL
4. **Wave 3**: Remove individual tier messages (L2/L3/L4), only send Morning Digest

---

## 5. SPEC CHI TIET TUNG TASK

### Phase 2 Wave 0: Quick Wins & Deploy (1-2 ngay)

| Task ID | Mo ta | File | Estimate |
|---------|-------|------|----------|
| P2.QW1 | Fix Fear&Greed symbol mismatch | `breaking_pipeline.py:841` — doi `"Fear_Greed"` -> `"Fear&Greed"` | 5 min |
| P2.QW2 | ADMIN_CHAT_ID cho error alerts | `delivery/telegram_bot.py:300-308` — them env var `ADMIN_CHAT_ID` | 30 min |
| P2.QW3 | SOURCE_DISPLAY_MAP cho market_data | `breaking/content_generator.py` — map internal -> display names | 30 min |
| P2.QW4 | Feedback summary tang 200 -> 1000 chars | `breaking/feedback.py:127` | 5 min |
| P2.QW5 | Filter 0.0000 on-chain values | `collectors/research_data.py:107` | 30 min |
| P2.QW6 | "tien dien tu" grep + fix trong prompts | All prompt files | 30 min |
| P2.QW7 | DISCLAIMER_SHORT cho breaking | `generators/article_generator.py:32-38` + `breaking/content_generator.py` | 30 min |
| P2.QW8 | Tang MASTER_MAX_TOKENS 16384 -> 20480 | `generators/master_analysis.py:25` | 5 min |
| P2.QW9 | DXY conditional injection | `breaking_pipeline.py:832-845` | 30 min |
| P2.QW10 | Deploy + verify alpha.10 output | CI/CD + manual check | 2h |

**AC cho Wave 0**:
- [QW1] `breaking_pipeline.py:841` dung `"Fear&Greed"` (khong phai `"Fear_Greed"`)
- [QW2] `send_admin_alert()` dung `ADMIN_CHAT_ID`. Neu khong set -> log, KHONG gui member channel
- [QW3] Breaking messages hien thi "Nguon: Alternative.me" thay vi "market_data"
- [QW4] Feedback summary 1000 chars
- [QW5] On-chain value 0.0000 -> "KHONG CO DU LIEU"
- [QW6] 0 instance "tien dien tu" trong code/prompts (grep verify)
- [QW7] Breaking disclaimer 1 dong, daily disclaimer chi tin cuoi
- [QW8] `MASTER_MAX_TOKENS = 20480`
- [QW9] DXY chi xuat hien trong macro-related breaking (khong moi tin)
- [QW10] Alpha.10 output verified — Master Analysis visible, Consensus visible

---

### Phase 2 Wave 1: Breaking Quality Overhaul (~2 tuan)

| Task ID | Mo ta | Dependencies | Estimate |
|---------|-------|-------------|----------|
| P2.1 | Metric-type daily dedup (F&G 1x/ngay) | None | 4h |
| P2.2 | Entity pattern expansion (quoc gia, to chuc) | None | 2h |
| P2.3 | Geo event digest + daily cap 3 | VD-03 | 6h |
| P2.4 | Breaking Enrichment (consensus + cross-asset vao prompt) | Wave 0 done | 8h |
| P2.5 | Crypto relevance check tai event_detector (truoc dedup) | None | 4h |
| P2.6 | MAX_EVENTS_PER_DAY = 12 | None | 2h |
| P2.7 | VN regulatory keywords + auto CRITICAL | VD-10 | 4h |
| P2.8 | LLM Impact Scoring (Groq judge 1-10) | P2.4 | 8h |
| P2.9 | Cooldown tang 4h -> 8h | None | 1h |
| P2.10 | Breaking schedule reduce 7 -> 4 runs/ngay | None | 30min |

**AC cho Wave 1**:
- [P2.1] F&G chi gui MAX 1 lan/ngay. BTC/ETH drop chi gui khi delta >= 5% tu lan gui truoc
- [P2.2] Entity dedup bat "Canada" va "EU" articles trung
- [P2.3] Geo events gop digest. Max 3 geo/ngay. CRITICAL geo (panic >= 90) gui rieng
- [P2.4] Breaking prompt co consensus snapshot + historical parallel
- [P2.5] Non-crypto events bi skip TAI event_detector (khong doi severity_classifier)
- [P2.6] Sau 12 events/ngay, them events bi deferred_to_daily
- [P2.7] "thong tu" + "ONUS" trigger ALWAYS_TRIGGER + auto CRITICAL severity
- [P2.8] LLM judge score visible trong log. Score < 4 = skip. Score 4-6 = digest. Score >= 7 = gui
- [P2.9] Hash dedup cooldown = 8h
- [P2.10] Breaking schedule: 4 runs/ngay

---

### Phase 2 Wave 2: Content Quality & Price Authority (~2 tuan)

| Task ID | Mo ta | Dependencies | Estimate |
|---------|-------|-------------|----------|
| P2.11 | Quality Gate BLOCK mode (retry 1 lan) | Wave 0 done | 6h |
| P2.12 | PriceSnapshot — gia dong bang per pipeline run | Wave 0 done | 6h |
| P2.13 | NQ05 pattern expansion (VD-18) | None | 4h |
| P2.14 | Cross-tier overlap check post-extraction | Wave 0 done | 8h |
| P2.15 | L2 force data injection | Wave 0 done | 4h |
| P2.16 | Research vs L5 dedup (khac biet noi dung) | Wave 0 done | 4h |
| P2.17 | Vietnamese glossary inject vao prompts | None | 3h |
| P2.18 | Consensus display enforcement trong tier extraction | Wave 0 done | 4h |
| P2.19 | Smart message splitting (section breaks) | None | 4h |
| P2.20 | Severity legend (1 lan/ngay) | None | 2h |
| P2.21 | Season-aware market thresholds | P1.12 (done) | 4h |

**AC cho Wave 2**:
- [P2.11] Quality Gate retry 1 lan khi factual_issues > 0 hoac density < 0.30. Fail lan 2 -> log + gui
- [P2.12] Moi pipeline run co 1 PriceSnapshot. Tat ca components dung cung snapshot
- [P2.13] "gia tang ty trong", "co the tang len 30%", "vung mua ly tuong" bi bat boi NQ05
- [P2.14] Cross-tier overlap < 40%. Overlap > 40% -> retry voi anti-repetition instruction
- [P2.15] L2 mo dau BAT BUOC co BTC price + F&G value. Quality Gate check density >= 0.20 cho L2
- [P2.16] Research KHONG co market overview. Focus: on-chain + institutional + macro
- [P2.17] "Market Cap" -> "Von hoa" trong output. Glossary in system prompt
- [P2.18] Summary va L3+ co section "Consensus" noi bat
- [P2.19] L5 split tai `## ` headings, khong cat giua section
- [P2.20] Tin breaking dau ngay co severity legend
- [P2.21] Market trigger thresholds thay doi theo Sentinel Season

---

### Phase 2 Wave 3: Delivery Redesign (~1 tuan)

| Task ID | Mo ta | Dependencies | Estimate |
|---------|-------|-------------|----------|
| P2.22 | Morning Digest format | Wave 2 done | 8h |
| P2.23 | L5 standalone (rut ngan, 1 message) | Wave 2 done | 4h |
| P2.24 | Breaking Digest (17:00 VN) | P2.3 | 6h |
| P2.25 | Research weekly (3x/tuan) | P2.16 | 4h |
| P2.26 | CRITICAL-only breaking delivery | P2.6, P2.8 | 4h |
| P2.27 | Remove individual tier messages (L2/L3/L4) | P2.22 | 4h |

**AC cho Wave 3**:
- [P2.22] Morning Digest = 1 message: Summary + top 3 breaking + Consensus. < 4000 chars
- [P2.23] L5 = 1 message (khong chia 2 phan). Max 2500 tu
- [P2.24] Breaking Digest luc 17:00 VN. Skip neu 0 events
- [P2.25] Research chi gui T2/T4/T6. < 4000 chars
- [P2.26] Chi CRITICAL (panic >= 85) duoc gui rieng le. Tong max 3 CRITICAL/ngay
- [P2.27] L2/L3/L4 khong con gui rieng. Noi dung gop vao Morning Digest

---

### Phase 2 Wave 4: New Sources & Integration (~2-3 tuan)

| Task ID | Mo ta | Dependencies | Estimate |
|---------|-------|-------------|----------|
| P2.28 | NewsAPI.org free tier collector | None | 6h |
| P2.29 | GDELT macro collector | None | 6h |
| P2.30 | Token unlock calendar collector | None | 8h |
| P2.31 | TG channel expansion (Bloomberg, WSJ RSS mirrors) | None | 6h |
| P2.32 | Telethon monitoring + fallback | None | 4h |
| P2.33 | cic_action_watcher (tu Sentinel) | Sentinel PA F done | 8h |
| P2.34 | Deribit options data (IV, max pain) | None | 8h |
| P2.35 | Augmento social sentiment | None | 4h |
| P2.36 | TradingView technical indicators | None | 6h |

**AC cho Wave 4**:
- [P2.28] NewsAPI collector tra ve articles cho macro events. 500 req/day budget
- [P2.29] GDELT collector tra ve top 10 macro articles/ngay
- [P2.30] Token unlock data hien thi trong L3+ va Research
- [P2.31] >= 5 new TG channels active
- [P2.32] Telethon health check moi run. Alert sau 3 failures
- [P2.33] cic_action changes visible trong breaking alerts
- [P2.34] BTC options IV + max pain hien thi trong L5 + Research
- [P2.35] Augmento Bull/Bear index trong Consensus Engine
- [P2.36] BTC RSI/MACD tu TradingView trong L3+ articles

---

## 6. DEPENDENCIES & CRITICAL PATH

```
Wave 0 (deploy + quick wins)
    |
    v
Wave 1 (breaking quality) --- Wave 2 (content quality) [PARALLEL]
    |                              |
    v                              v
    +--------- Wave 3 (delivery redesign) --------+
                        |
                        v
                  Wave 4 (new sources)
```

**Critical path**: Wave 0 -> (Wave 1 || Wave 2) -> Wave 3

**Dependencies chi tiet**:
- P2.4 (Breaking Enrichment) PHAI co Wave 0 done (consensus display working)
- P2.8 (LLM Impact Scoring) PHAI co P2.4 done (enrichment data for scoring)
- P2.22 (Morning Digest) PHAI co Wave 2 done (quality improvements first)
- P2.26 (CRITICAL-only) PHAI co P2.6 + P2.8 done (daily cap + impact scoring)
- P2.33 (cic_action_watcher) PHAI co Sentinel PA F done (da complete)
- Wave 4 khong block Wave 3 — co the lam song song hoac sau

**Time estimate tong**:
- Wave 0: 1-2 ngay
- Wave 1: ~2 tuan
- Wave 2: ~2 tuan (parallel voi Wave 1)
- Wave 3: ~1 tuan
- Wave 4: ~2-3 tuan (song song hoac sau Wave 3)
- **Tong: 4-6 tuan** (Waves 1+2 parallel, Wave 3 sequential, Wave 4 parallel)

---

## 7. SUCCESS METRICS

| Metric | Hien tai (30/03) | Target Phase 2 | Cach do |
|--------|:---:|:---:|---------|
| Messages/ngay | 34 | <= 8 | Count TG messages |
| F&G repeats/ngay | 4-5 | <= 1 | Grep BREAKING_LOG |
| Geo news/ngay | 10 | <= 3 (digest) | Count geo events |
| Tin VN regulatory bi bo sot | 100% | 0% | So sanh voi Coin68/Upside |
| Top-10 tin bi bo sot | 10/10 | <= 2/10 | Manual check daily |
| Quality Gate block rate | 0% (log-only) | Active (retry 1x) | Quality Gate logs |
| Consensus hien thi | Khong | Co (moi Summary + L3+) | Check output |
| MVRV/NUPL/SOPR accuracy | 0.0000 (sai) | Real data hoac "unavailable" | Check Research output |
| NQ05 violations caught | ~60% | >= 95% | NQ05 filter logs |
| Insight density (L2) | 0% (zero numbers) | >= 20% | Quality Gate density |
| Cross-tier overlap | ~70% | < 40% | Overlap checker |
| Breaking latency | 3-6h | 1.5-2h | Compare event time vs delivery |
| Feedback summary length | 200 chars | 1000 chars | Check feedback.py |
| Consensus sources active | 2/5 | >= 3/5 | Consensus logs |
| Research vs L5 overlap | >= 70% | < 30% | Manual check |

---

## 8. RUI RO & ROLLBACK

| Rui ro | Muc do | Xac suat | Mitigation | Rollback |
|--------|--------|----------|------------|----------|
| LLM Impact Scoring tang cost | MEDIUM | 30% | Groq free tier, max_tokens=10/call, cap 50 calls/day | Disable scoring, dung fixed rules |
| Quality Gate BLOCK mode gay delay | HIGH | 20% | Retry chi 1 lan, timeout 30s | Revert ve LOG mode (`QUALITY_GATE_MODE="log"`) |
| Morning Digest qua dai (> 4000 chars) | MEDIUM | 40% | Hard truncate, priority-based content selection | Revert ve individual tier messages |
| Geo digest bo sot tin CRITICAL | HIGH | 15% | CRITICAL geo van gui rieng. Panic >= 90 bypass digest | Revert geo ve ALWAYS_TRIGGER |
| VN regulatory false positives | LOW | 20% | Keywords cu the (khong generic), LLM confirm | Remove VN keywords, manual only |
| Breaking schedule change miss events | MEDIUM | 25% | Giam interval thay vi tang. Cache protect | Revert schedule |
| Cross-tier overlap check slow | LOW | 30% | Async comparison, timeout 10s | Disable overlap check |
| Telethon re-auth fail | HIGH | 40% | RSS backup, monitoring alert, re-auth guide | Use RSS-only mode |
| NewsAPI rate limit | LOW | 20% | 500 req/day budget tracking. GDELT fallback | Disable NewsAPI, dung RSS |

**Rollback strategy tong**:
- Moi Wave co feature flag (`PHASE2_WAVE1_ENABLED`, etc.)
- Rollback = tat flag, khong can revert code
- Feature flags luu trong `CAU_HINH` Google Sheet (operator co the tat tu Sheet)

---

## 9. GLOSSARY & REFERENCE

### 9.1 Vietnamese Glossary (inject vao LLM prompts)

| English | Vietnamese | Ghi chu |
|---------|-----------|---------|
| Market Cap | Von hoa | |
| Funding Rate | Ty le Funding | Giu "Funding" vi thong dung |
| Fear & Greed Index | Chi so So hai & Tham lam (F&G) | |
| Open Interest | Vi the mo | |
| Liquidation | Thanh ly | |
| Whale | Ca voi (whale) | |
| Stablecoin | Stablecoin | Giu nguyen |
| DeFi | DeFi | Giu nguyen |
| TVL | TVL (Tong gia tri khoa) | |
| DEX | San phi tap trung (DEX) | |
| CEX | San tap trung (CEX) | |
| Altcoin Season | Mua Altcoin | |
| Bull/Bear Market | Thi truong tang/giam | |
| Consensus | Dong thuan | |
| On-chain | On-chain | Giu nguyen, thong dung |
| Layer 2 | Layer 2 | Giu nguyen |
| Hashrate | Hashrate | Giu nguyen, thong dung |
| Mempool | Mempool | Giu nguyen |

### 9.2 File Reference — Tat ca files bi anh huong

| File | Lines | Van de lien quan | Thay doi |
|------|-------|-----------------|----------|
| `breaking_pipeline.py` | 37, 841 | VD-07, VD-21, VD-31 | Fix symbol, MAX_EVENTS_PER_DAY, DXY condition |
| `breaking/market_trigger.py` | 15-27, 58, 95 | VD-01, VD-24, VD-29 | Metric dedup, season thresholds, source name |
| `breaking/dedup_manager.py` | 21, 88-89, 92-103 | VD-01, VD-02, VD-09 | Cooldown, entity expansion, metric dedup |
| `breaking/event_detector.py` | 30-36, 42-55, 290 | VD-03, VD-04, VD-10 | Geo digest, crypto relevance, VN keywords |
| `breaking/severity_classifier.py` | 207-219, 222-234 | VD-03, VD-04 | Geo severity rules, crypto relevance at detector |
| `breaking/content_generator.py` | 36-80, 82-105, 138 | VD-06, VD-29, VD-31, VD-38 | Enrichment, source display, format unify |
| `breaking/llm_scorer.py` | - | VD-11 | LLM Impact Scoring |
| `breaking/feedback.py` | 127 | VD-20, VD-32 | Summary 200->1000, BREAKING_LOG read |
| `delivery/telegram_bot.py` | 24, 300-308 | VD-28, VD-35, VD-44 | Admin chat, smart split, delivery redesign |
| `generators/quality_gate.py` | 1-4, 20, 237-270 | VD-14, VD-15 | BLOCK mode, cross-tier overlap |
| `generators/nq05_filter.py` | 99-123 | VD-09, VD-18, VD-30 | New patterns, terminology |
| `generators/consensus_engine.py` | 50, 63 | VD-16, VD-33 | Display enforcement, source transparency |
| `generators/article_generator.py` | 32-38, 41-59, 317-324 | VD-36, VD-34, VD-39 | Disclaimer, glossary, L2 data |
| `generators/tier_extractor.py` | 47+ | VD-14, VD-33, VD-39, VD-40 | Overlap, consensus, L2 data, Research scope |
| `generators/master_analysis.py` | 25 | VD-19 | MAX_TOKENS 20480, word limit |
| `generators/summary_generator.py` | - | VD-23 | Deprecate (fallback only) |
| `generators/research_generator.py` | 37-50 | VD-40 | Scope narrowing, no market overview |
| `collectors/research_data.py` | 107 | VD-27 | 0.0000 filter |
| `collectors/market_data.py` | 509 | VD-05, VD-07 | PriceSnapshot, symbol |
| `collectors/rss_collector.py` | 55-74, 79-92 | VD-10, VD-12, VD-25 | VN feeds, macro expansion |
| `collectors/telegram_scraper.py` | - | VD-10, VD-22 | Monitoring, health check |
| `daily_pipeline.py` | - | VD-05, VD-22, VD-32, VD-44 | PriceSnapshot, delivery redesign |
| `.github/workflows/breaking-news.yml` | 5 | VD-17, VD-21 | Schedule change |
| `.github/workflows/daily-pipeline.yml` | - | VD-25 | Research weekly condition |

### 9.3 Test Strategy

- Moi Wave PHAI co unit tests moi >= 80% logic paths
- Integration tests cho:
  - Metric daily dedup (F&G gui 1 lan/ngay)
  - Geo event digest mode
  - LLM Impact Scoring mock
  - Quality Gate BLOCK + retry
  - Cross-tier overlap detection
  - PriceSnapshot consistency
  - Morning Digest format
  - ADMIN_CHAT_ID separation
- Regression: chay FULL 1448+ test suite sau moi Wave
- Target: 1448 -> ~1700+ tests (+250 new)

### 9.4 Conventions

- English snake_case cho code + JSON fields
- Vietnamese text trong prompts: dung literal strings (khong escape)
- Moi function moi: WHY comment giai thich quyet dinh thiet ke
- Feature flags: `CAU_HINH` Google Sheet, column "Key" / "Value"
- Version: tang alpha.11, .12, ... per Wave

---

## 10. APPENDIX: OUTPUT MAU (TRUOC va SAU)

### 10.1 Breaking hien tai (TRUOC)

```
Do [CRITICAL] Fear & Greed Index xuong 8 — Extreme Fear

(400 tu phan tich...)

Chi so DXY dang o muc 100.2...

Lien ket Nguon: market_data

---
Warning *Tuyen bo mien tru trach nhiem:* Noi dung tren chi mang tinh chat thong tin
va phan tich, KHONG phai loi khuyen dau tu. Tai san ma hoa co rui ro cao.
Hay tu nghien cuu (DYOR) truoc khi dua ra quyet dinh dau tu.
```

### 10.2 Breaking SAU Phase 2

```
Do [KHOAN CAP] Fear & Greed Index xuong 8 — Extreme Fear

Chi so F&G giam tu 15 xuong 8 trong 24h, muc thap nhat ke tu thang 1/2023.

CHUYEN GI XAY RA: Chi so So hai & Tham lam (F&G) roi xuong vung Extreme Fear
lan dau tien ke tu 19/01/2023. BTC giao dich quanh $66,400, giam 3.2% trong
24h. Vol giao dich tang 45% so voi trung binh 7 ngay.

DONG THUAN: NEUTRAL (+0.12, 4/5 nguon)
- Polymarket: BTC > $70K EOY = 62% (giam tu 68% tuan truoc)
- Funding Rate: +0.01% (duong nhe — pro traders van hold long)
- Mau thuan: Retail so (F&G=8) nhung institutional van mua (ETF +$120M hom qua)

Lich su: Lan truoc F&G=8 (01/2023), BTC phuc hoi 45% trong 3 thang sau.

Warning Do not DYOR — Khong phai loi khuyen dau tu.
Nguon: Alternative.me Fear & Greed Index
```

### 10.3 Morning Digest SAU Phase 2

```
CIC Market Digest — 31/03/2026

CAP NHAT THI TRUONG

BTC giao dich $67,232 (+1.2%), ETH $3,340 (+0.8%). Von hoa toan thi
truong dat $2.45T. Chi so So hai & Tham lam o muc 32 (Fear) — retail
van than trong nhung dong tien to chuc tiep tuc chay vao (+$120M ETF
hom qua).

TIN HIEU DONG THUAN: BULLISH (+0.35, 4/5 nguon)
Ca voi tiep tuc rut BTC khoi san (net outflow 3 ngay lien). Funding
Rate duong (+0.02%). Duy nhat F&G cho tin hieu nguoc — retail so
trong khi smart money tich luy.

--- TIN NONG DEM QUA ---

1. Morgan Stanley cho phep ETF Bitcoin trong tai khoan 401(k) — anh
huong 10 trieu tai khoan huu tri My

2. Thu tuong Canada ky sac lenh cam quyen gop bang tai san ma hoa
cho chien dich chinh tri — hieu luc tu 01/04

3. ONUS (san giao dich VN) dat chung nhan ISO 27001 — san VN dau
tien dat chuan bao mat quoc te

Warning DYOR — Khong phai loi khuyen dau tu.
```

---

## 11. OPEN QUESTIONS (Can Anh Cuong quyet dinh)

1. **Delivery schedule**: 08:15/13:00/17:00/20:00 VN co phu hop? Hay can dieu chinh gio?
2. **Research frequency**: 3 lan/tuan (T2/T4/T6) hay 2 lan/tuan (T3/T6)?
3. **L2/L3/L4 rieng le**: Bo han (gop vao Morning Digest) hay giu lai?
4. **CRITICAL threshold**: `panic_score >= 85` hay `>= 90`?
5. **Geo events cap**: Max 3/ngay hay max 5/ngay?
6. **Admin Telegram**: Anh Cuong cung cap ADMIN_CHAT_ID (chat rieng de nhan error alerts)

---

> **NEXT STEP**: Anh Cuong review + approve -> Team bat dau Wave 0 deploy + quick wins.
