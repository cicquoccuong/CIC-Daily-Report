# SPEC: CIC-Daily-Report Quality Overhaul v2

> **Version**: 2.0 | **Date**: 2026-04-11
> **Status**: APPROVED (B2) — Anh Cuong approved 2026-04-12
> **Supersedes**: `SPEC-v2.0-phase2-quality-overhaul.md` (v1.0, rejected 2026-04-11)
> **Namespace**: QO.xx (replaces P2.x to avoid collision with v2.0-architecture-redesign.md Phase 2)

---

## 1. Boi canh & Van de

### 1.1 Tom tat

Phan tich output thuc te 30-31/03/2026 phat hien 55 van de (VD-01 -> VD-44 + sub-items).
Old spec v1.0 de xuat 36 tasks nhung bi reject vi:
- Tiep can tu 55 trieu chung thay vi nguyen nhan goc
- 2 plan conflict (Section 5 vs Section 10B)
- Task ID trung namespace voi v2.0 architecture spec
- Wave 3 (delivery redesign: gop L2/L3/L4 vao Morning Digest) bi HUY

### 1.2 Trang thai hien tai

Phase 1 (alpha.1 -> alpha.11) da giai quyet ~22/55 van de gian tiep:
- Master Analysis architecture loai bo cross-tier contradictions
- Consensus Engine wired vao pipeline
- COOLDOWN_HOURS: 4 -> 12 (`dedup_manager.py:21`)
- MAX_EVENTS_PER_RUN: 5 -> 3 (`breaking_pipeline.py:37`)
- Cerebras model: qwen-3-32b -> gpt-oss-120b
- P1.18: Tach API key Sentinel vs DR (alpha.12)

Con lai **~33 van de CHUA FIX**, nhom theo 3 nguyen nhan goc + quick wins.

### 1.3 Phan loai 55 VD theo Root Cause

**RC1 — Breaking pipeline thieu relevance/priority filter** (~20 issues):
VD-01 (F&G lap 4-5x), VD-02 (Canada trung 2x), VD-03 (geo spam 10x/ngay),
VD-04 (BYD lot qua), VD-05 (gia khong nhat quan), VD-10 (VN news bi bo sot),
VD-11 (dao lon uu tien), VD-12 (thieu "tin lon" detector), VD-17 (breaking cham 3-6h),
VD-21 (31+ tin/ngay), VD-22 (Telethon SPOF), VD-24 (thresholds co dinh),
VD-25 (Google News proxy yeu), VD-31 (DXY lap moi tin), VD-32 (daily khong cover tin quan trong),
VD-38 (digest vs breaking format khac nhau)

**RC2 — LLM prompts thieu enforcement** (~15 issues):
VD-06 (noi dung generic), VD-09 (NQ05 borderline), VD-14 (tiers lap 70-80%),
VD-15 (Quality Gate log-only), VD-16 (Consensus chi 2-3 nguon),
VD-18 (NQ05 bo sot VN patterns), VD-19 (Master truncation risk),
VD-27 (on-chain 0.0000), VD-30 ("tien dien tu"), VD-33 (Consensus khong hien thi),
VD-34 (tu tieng Anh lot), VD-39 (L2 zero data), VD-40 (Research vs L5 overlap 70%)

**RC3 — Thresholds hardcoded in code** (~10 issues):
VD-01 (F&G threshold=10), VD-24 (BTC/ETH drop thresholds), VD-17 (CACHE_MAX_AGE=7200),
VD-21 (MAX_EVENTS_PER_RUN=3), VD-09 (COOLDOWN_HOURS),
plus macro thresholds (Oil/Gold/VIX/DXY/SPX) tai `market_trigger.py:15-26`

**Quick-win bugs** (~10 issues):
VD-07 (F&G symbol mismatch), VD-28 (error gui member), VD-29 (source name lo),
VD-35 (L5 cat ngau nhien), VD-36 (disclaimer 15-20% moi tin),
VD-37 (severity icon khong giai thich), VD-23 (2 code paths Summary)

---

## 2. Quyet dinh thiet ke

| # | Quyet dinh | Ly do | Approved by |
|---|-----------|-------|-------------|
| QD1 | GIU L2/L3/L4 la Telegram messages rieng | Cai thien chat luong, khong gop/xoa | Anh Cuong (2026-04-11) |
| QD2 | Root-cause approach (3 RC + quick wins) | Giai quyet goc thay vi 55 trieu chung rieng le | Anh Cuong (2026-04-11) |
| QD3 | Namespace QO.xx | Tranh trung P2.x cua v2.0 architecture spec | Team review |
| QD4 | Wave 3 delivery redesign tu old spec → HUY | Anh Cuong muon giu L2/L3/L4 | Anh Cuong (2026-04-11) |
| QD5 | CAU_HINH-first | Moi threshold moi doc tu Google Sheet, code chi giu fallback | Team review |
| QD6 | 48 tasks / 5 waves trong 1 spec | Roadmap day du, bao gom ca v2.0 Phase 2 enhancements | Anh Cuong (2026-04-11) |
| QD7 | SambaNova cho LLM Impact Scoring (QO.18) | 20 RPD free, tach rieng khoi main chain, Sentinel da co code mau | Anh Cuong (2026-04-11) |
| QD8 | Khong delivery lite | Giu nguyen so tin/ngay, chi cai thien chat luong | Anh Cuong (2026-04-11) |

---

## 3. Root Cause Analysis

### 3.1 RC1: Breaking Pipeline thieu filter

**Trang thai hien tai (code references)**:
- `event_detector.py:30-36` — ALWAYS_TRIGGER chi co 5 keywords crypto tieng Anh
- `event_detector.py:42-55` — GEOPOLITICAL_KEYWORDS = 12 tu, tat ca o ALWAYS_TRIGGER tier
- `severity_classifier.py:222-234` — `_is_crypto_relevant()` chi chay o classifier, KHONG o detector
- `dedup_manager.py:21` — COOLDOWN_HOURS = 12 (da fix tu 4)
- `dedup_manager.py:88-89` — SIMILARITY_THRESHOLD = 0.70, ENTITY_OVERLAP_THRESHOLD = 0.60
- `breaking_pipeline.py:37` — MAX_EVENTS_PER_RUN = 3 (da fix tu 5)
- `breaking_pipeline.py:39` — DIGEST_THRESHOLD = 3
- KHONG co MAX_EVENTS_PER_DAY (feedback.py:32 = 100, khong thuc su cap)
- KHONG co LLM-based relevance/impact scoring
- KHONG co VN regulatory keywords

**Trang thai muc tieu**:
Staged pipeline: Detect -> **Score (SambaNova Impact)** -> **Filter (relevance + daily cap)** -> Prioritize -> Format

### 3.2 RC2: LLM Prompts thieu enforcement

**Trang thai hien tai (code references)**:
- `quality_gate.py:1-4` — Comment "Phase 1a: LOG-ONLY", KHONG block bai sai
- `quality_gate.py:20` — INSIGHT_DENSITY_THRESHOLD = 0.30 (chi log, khong retry)
- `tier_extractor.py:48+` — ExtractionConfig co format_instructions nhung L2 KHONG enforce so lieu
- `content_generator.py:36-80` — BREAKING_PROMPT_TEMPLATE yeu cau "HE QUA CU THE" nhung khong validate
- `nq05_filter.py:99-123` — SEMANTIC_NQ05_PATTERNS thieu nhieu pattern VN
- `consensus_engine.py:50` — MIN_SOURCES_FOR_CONSENSUS = 2 (qua thap)
- `master_analysis.py:25` — MASTER_MAX_TOKENS = 16384 (sat gioi han)
- KHONG co cross-tier overlap checker
- KHONG co structured JSON output enforcement

**Trang thai muc tieu**:
Quality Gate BLOCK mode + cross-tier dedup + per-tier format enforcement + NQ05 expansion

### 3.3 RC3: Thresholds hardcoded

**Danh sach day du**:

| File | Line | Constant | Value |
|------|------|----------|-------|
| `market_trigger.py` | 15 | BTC_DROP_THRESHOLD | -7.0 |
| `market_trigger.py` | 16 | ETH_DROP_THRESHOLD | -10.0 |
| `market_trigger.py` | 17 | FEAR_GREED_THRESHOLD | 10 |
| `market_trigger.py` | 22 | OIL_SPIKE_THRESHOLD | 8.0 |
| `market_trigger.py` | 23 | GOLD_SPIKE_THRESHOLD | 3.0 |
| `market_trigger.py` | 24 | VIX_SPIKE_THRESHOLD | 30 |
| `market_trigger.py` | 25 | DXY_SPIKE_THRESHOLD | 2.0 |
| `market_trigger.py` | 26 | SPX_DROP_THRESHOLD | -3.0 |
| `dedup_manager.py` | 21 | COOLDOWN_HOURS | 12 |
| `dedup_manager.py` | 88 | SIMILARITY_THRESHOLD | 0.70 |
| `dedup_manager.py` | 89 | ENTITY_OVERLAP_THRESHOLD | 0.60 |
| `event_detector.py` | 25 | CACHE_MAX_AGE | 7200 |
| `event_detector.py` | 71 | DEFAULT_PANIC_THRESHOLD | 70 |
| `breaking_pipeline.py` | 37 | MAX_EVENTS_PER_RUN | 3 |
| `breaking_pipeline.py` | 39 | DIGEST_THRESHOLD | 3 |
| `breaking_pipeline.py` | 40 | INTER_EVENT_DELAY | 30 |
| `quality_gate.py` | 20 | INSIGHT_DENSITY_THRESHOLD | 0.30 |
| `master_analysis.py` | 25 | MASTER_MAX_TOKENS | 16384 |
| `research_generator.py` | 31 | RESEARCH_MAX_TOKENS | 6144 |
| `consensus_engine.py` | 73 | _LABEL_THRESHOLDS | fixed array |
| `feedback.py` | 32 | MAX_EVENTS_PER_DAY | 100 |
| `severity_classifier.py` | 20-21 | NIGHT_START/NIGHT_END | 23/7 |

**Trang thai muc tieu**: Tat ca doc tu CAU_HINH Google Sheet qua `config_loader.py`.
Code chi giu default fallback. Pattern: `get_setting_int("KEY", default_value)`.

---

## 4. Task List

### Wave 0: Quick Wins (11 tasks)

| ID | Mo ta | File(s) | Effort | AC |
|----|-------|---------|--------|----|
| QO.01 | Fix F&G symbol mismatch ("Fear_Greed" -> "Fear&Greed") | `breaking_pipeline.py:841` | 5m | Symbol hien thi dung |
| QO.02 | ADMIN_CHAT_ID cho error alerts (tach khoi member channel) | `delivery/telegram_bot.py:300-308` | 30m | Error chi gui admin |
| QO.03 | SOURCE_DISPLAY_MAP (internal name -> display name) | `breaking/content_generator.py:138` | 30m | Source name than thien |
| QO.04 | Feedback summary 200 -> 1000 chars | `breaking/feedback.py:127` | 5m | Feedback day du hon |
| QO.05 | Filter on-chain 0.0000 values truoc khi gui LLM | `collectors/research_data.py:107` | 30m | Khong co 0.0000 trong output |
| QO.06 | Grep + fix "tien dien tu" trong tat ca prompts | All prompt files | 30m | Chi dung "tai san ma hoa" |
| QO.07 | DISCLAIMER_SHORT cho breaking (1 dong) | `generators/article_generator.py:32-38`, `breaking/content_generator.py` | 30m | Disclaimer khong chiem 15-20% |
| QO.08 | MASTER_MAX_TOKENS 16384 -> 20480 | `generators/master_analysis.py:25` | 5m | Master khong bi truncate |
| QO.09 | DXY chi inject khi macro event hoac DXY change >= 0.5% | `breaking_pipeline.py:832-845` | 30m | DXY khong lap moi tin |
| QO.10 | Smart message splitting (tai `## ` headings) | `delivery/telegram_bot.py:24` | 2h | Tin khong bi cat giua section |
| QO.11 | Severity legend gui 1 lan/ngay (tin breaking dau ngay) | `breaking/severity_classifier.py:28-32` | 1h | Legend khong lap moi tin |

> **Luu y**: QO.02, QO.03, QO.04, QO.05 co the da duoc fix trong alpha.10/11.
> Amelia PHAI verify truoc khi skip.

**Wave 0 estimate**: 1-2 ngay

---

### Wave 1: RC1 — Event Pipeline Refactor (8 tasks)

| ID | Mo ta | File(s) | AC | Effort | Deps |
|----|-------|---------|-----|--------|------|
| QO.12 | Metric-type daily dedup: F&G max 1x/ngay, BTC/ETH drop chi khi delta >= 5% tu lan gui truoc | `dedup_manager.py` | F&G <= 1 msg/ngay | 4h | - |
| QO.13 | Entity pattern expansion: them quoc gia + to chuc (Canada, EU, Japan, SEC, Fed, ECB...) | `dedup_manager.py:92-103` | Trung entity bi bat | 2h | - |
| QO.14 | Geo event digest + daily cap: geo events gop digest, max 3/ngay, CRITICAL (panic>=90) gui rieng | `event_detector.py`, `breaking_pipeline.py` | Geo <= 3/ngay | 6h | - |
| QO.15 | Crypto relevance check TAI event_detector: move `_is_crypto_relevant()` tu severity_classifier | `event_detector.py`, `severity_classifier.py:222-234` | Non-crypto skip som | 4h | - |
| QO.16 | MAX_EVENTS_PER_DAY = 12 (configurable): sau 12 -> deferred_to_daily | `breaking_pipeline.py`, `feedback.py` | Daily cap enforce | 2h | - |
| QO.17 | VN regulatory keywords + auto CRITICAL severity | `event_detector.py:30-36`, `severity_classifier.py:38-45` | "thong tu", "ONUS" trigger CRITICAL | 4h | - |
| QO.18 | LLM Impact Scoring via **SambaNova** (Llama-3.3-70B, 20 RPD): "Tin nay quan trong co nao cho NDT crypto VN?" Score 1-10 | `breaking/llm_scorer.py` (new) | Score < 4 skip, 4-6 digest, >= 7 gui. SambaNova rieng, khong an quota main chain | 8h | QO.15 |
| QO.19 | Breaking enrichment: consensus snapshot + historical parallel vao prompt | `breaking/content_generator.py:36-80` | Prompt co consensus data | 8h | Wave 0 |

**Wave 1 estimate**: ~2 tuan

---

### Wave 2: RC2 — LLM Quality Enforcement (8 tasks)

| ID | Mo ta | File(s) | AC | Effort | Deps |
|----|-------|---------|-----|--------|------|
| QO.20 | Quality Gate BLOCK mode: retry 1 lan khi factual_issues > 0 hoac density < 0.30. Fail lan 2 -> log + gui | `generators/quality_gate.py` | Active retry, khong con LOG-ONLY. QUALITY_GATE_MODE config trong CAU_HINH | 6h | Wave 0 |
| QO.21 | Cross-tier overlap check: sentence overlap giua moi cap tier. Overlap > 40% -> retry voi anti-repetition instruction | `generators/quality_gate.py`, `generators/tier_extractor.py` | Overlap < 40% giua moi cap | 8h | Wave 0 |
| QO.22 | L2 force data injection: bat buoc BTC price + F&G + top 3 altcoin % change | `generators/tier_extractor.py:70-80` | L2 co >= 3 so lieu cu the | 4h | Wave 0 |
| QO.23 | Research vs L5 scope separation: Research focus on-chain deep + institutional, KHONG lap market overview | `generators/tier_extractor.py`, `generators/research_generator.py` | Research vs L5 overlap < 30% | 4h | Wave 0 |
| QO.24 | NQ05 pattern expansion: them ~10 patterns VN (gia tang ty trong, vung mua ly tuong...) | `generators/nq05_filter.py:99-123` | Patterns moi bi bat | 4h | - |
| QO.25 | Vietnamese glossary inject vao NQ05_SYSTEM_PROMPT | `generators/article_generator.py:41-59` | "Market Cap" -> "Von hoa" | 3h | - |
| QO.26 | Consensus display enforcement: Summary + L3+ bat buoc co section "CONSENSUS" noi bat | `generators/tier_extractor.py`, `consensus_engine.py` | Consensus visible | 4h | Wave 0 |
| QO.27 | PriceSnapshot: dong bang gia 1 lan per pipeline run, tat ca components dung cung snapshot | `daily_pipeline.py`, `breaking_pipeline.py`, `collectors/market_data.py` | Gia nhat quan xuyen suot | 6h | Wave 0 |

**Wave 2 estimate**: ~2 tuan (chay SONG SONG voi Wave 1)

---

### Wave 3: RC3 — Config Externalization (6 tasks)

| ID | Mo ta | File(s) | AC | Effort | Deps |
|----|-------|---------|-----|--------|------|
| QO.28 | Mo rong CAU_HINH seeds: them 22+ threshold keys vao `_DEFAULT_CONFIG_SEEDS` | `storage/sheets_client.py:20-37` | 22+ keys co default + mo ta tieng Viet | 2h | - |
| QO.29 | Market trigger thresholds doc tu CAU_HINH | `breaking/market_trigger.py:15-27`, `storage/config_loader.py` | Thay doi threshold tu Sheet | 4h | QO.28 |
| QO.30 | Dedup thresholds doc tu CAU_HINH: COOLDOWN_HOURS, SIMILARITY, ENTITY_OVERLAP | `breaking/dedup_manager.py:21,88-89` | Config external | 3h | QO.28 |
| QO.31 | Pipeline limits doc tu CAU_HINH: MAX_EVENTS_PER_RUN, MAX_EVENTS_PER_DAY, DIGEST_THRESHOLD | `breaking_pipeline.py:37-39`, `feedback.py:32` | Config external | 3h | QO.28 |
| QO.32 | Quality thresholds doc tu CAU_HINH: INSIGHT_DENSITY, MASTER_MAX_TOKENS, QUALITY_GATE_MODE | `quality_gate.py:20`, `master_analysis.py:25` | Config external, revert LOG mode tu Sheet | 3h | QO.28 |
| QO.33 | Season-aware thresholds: Sentinel Season dieu chinh market trigger defaults | `breaking/market_trigger.py`, `storage/sentinel_reader.py` | MUA_DONG = thresholds thap hon | 4h | QO.29 |

**Wave 3 estimate**: ~1 tuan (SAU Wave 1+2)

---

### Wave 4: v2.0 Phase 2 Enhancements (15 tasks)

| ID | Mo ta | Origin (v2.0 spec) | Effort | Deps |
|----|-------|---------------------|--------|------|
| QO.34 | TradingView ideas collector | P2.1 | 6h | Wave 1 |
| QO.35 | Augmento social sentiment collector | P2.2 | 4h | Wave 1 |
| QO.36 | Breaking enrichment layer (consensus + cross-asset + Polymarket shift) | P2.4 | 8h | QO.19 |
| QO.37 | Expanded news content (800 -> 2000 chars, 30 -> 50 articles) | P2.5 | 4h | - |
| QO.38 | Cross-tier consistency check (active, not log) | P2.6 | 4h | QO.21 |
| QO.39 | Crypto events calendar (CoinMarketCal/RSS) | P2.7 | 6h | - |
| QO.40 | DR_EXPORT tab + dr_exporter.py (persist data cho Sentinel) | P2.10 | 8h | Wave 2 |
| QO.41 | Price unification from Sentinel consensus | P2.12 | 4h | QO.27 |
| QO.42 | cic_action_watcher.py — detect cic_action changes -> breaking | P2.16 | 8h | - |
| QO.43 | Deribit options data (IV, max pain, put/call ratio) | P2.17 | 8h | - |
| QO.44 | TG channel expansion: Tier 2 (7 News) + Tier 3 (16 Data) | P1.5 Phase 2 | 6h | Wave 1 |
| QO.45 | Telethon monitoring + RSS fallback | P2.19 variant | 4h | QO.44 |
| QO.46 | Token unlock calendar collector | old P2.30 | 8h | - |
| QO.47 | NewsAPI.org / GDELT macro collector | old P2.28+P2.29 | 8h | - |
| QO.48 | Headline price validation | P2.22 | 4h | QO.27 |

**Wave 4 estimate**: ~2-3 tuan

---

## 5. Mapping: Old spec -> New spec

| Old Task | Mo ta | New Task | Ghi chu |
|----------|-------|----------|---------|
| P2.QW1 | F&G symbol fix | QO.01 | Giu nguyen |
| P2.QW2 | ADMIN_CHAT_ID | QO.02 | Giu nguyen |
| P2.QW3 | SOURCE_DISPLAY_MAP | QO.03 | Giu nguyen |
| P2.QW4 | Feedback 200->1000 | QO.04 | Verify (co the da fix) |
| P2.QW5 | On-chain 0.0000 | QO.05 | Verify (co the da fix) |
| P2.QW6 | "tien dien tu" fix | QO.06 | Giu nguyen |
| P2.QW7 | DISCLAIMER_SHORT | QO.07 | Giu nguyen |
| P2.QW8 | MASTER_MAX_TOKENS | QO.08 | Giu nguyen |
| P2.QW9 | DXY conditional | QO.09 | Giu nguyen |
| P2.QW10 | Deploy alpha.10 | N/A | DA DONE (alpha.11) |
| P2.1 | Metric dedup | QO.12 | Giu nguyen |
| P2.2 | Entity expansion | QO.13 | Giu nguyen |
| P2.3 | Geo digest | QO.14 | Giu nguyen |
| P2.4 | Breaking enrichment | QO.19 + QO.36 | Chia 2 phases |
| P2.5 | Crypto relevance | QO.15 | Giu nguyen |
| P2.6 | MAX_EVENTS_PER_DAY | QO.16 | Giu nguyen |
| P2.7 | VN keywords | QO.17 | Giu nguyen |
| P2.8 | LLM Impact Scoring | QO.18 | Doi tu Groq sang SambaNova |
| P2.9 | Cooldown 4->8h | N/A | DA FIX (hien tai = 12h) |
| P2.11 | Quality Gate BLOCK | QO.20 | Giu nguyen |
| P2.12 | PriceSnapshot | QO.27 | Giu nguyen |
| P2.13 | NQ05 expansion | QO.24 | Giu nguyen |
| P2.14 | Cross-tier overlap | QO.21 | Giu nguyen |
| P2.15 | L2 force data | QO.22 | Giu nguyen |
| P2.16 | Research/L5 dedup | QO.23 | Giu nguyen |
| P2.17 | VN glossary | QO.25 | Giu nguyen |
| P2.18 | Consensus display | QO.26 | Giu nguyen |
| P2.19 | Smart splitting | QO.10 | Chuyen Wave 0 |
| P2.20 | Severity legend | QO.11 | Chuyen Wave 0 |
| P2.21 | Season thresholds | QO.33 | Chuyen Wave 3 (RC3) |
| P2.22-P2.27 | **DELIVERY REDESIGN** | **HUY** | Anh Cuong: giu L2/L3/L4 |
| P2.28-P2.36 | New sources | QO.34-QO.48 | Merge Wave 4 |

---

## 6. Critical Path

```
Wave 0 (quick wins, 1-2 ngay)
    |
    v
Wave 1 (RC1 pipeline)  ----  Wave 2 (RC2 quality)    [SONG SONG, ~2 tuan]
    |                              |
    +--------- Wave 3 (RC3 config, ~1 tuan) ----------+
                        |
                        v
                Wave 4 (enhancements, ~2-3 tuan)
```

**Tong estimate**: 6-8 tuan

---

## 7. Risk Assessment

| Rui ro | Muc do | Mitigation |
|--------|--------|------------|
| SambaNova thay doi free tier (QO.18) | MEDIUM | Chi dung cho scoring (khong phai core generation). Fallback: skip scoring, gui tat ca events | 
| Quality Gate BLOCK mode gay delay (QO.20) | HIGH | Retry 1 lan, timeout 30s. QUALITY_GATE_MODE config trong CAU_HINH cho revert |
| Config externalization gay confusion (Wave 3) | LOW | Moi key co mo ta tieng Viet trong CAU_HINH |
| Cross-tier overlap check cham pipeline (QO.21) | MEDIUM | Async, timeout 10s, disable qua CAU_HINH |
| VN regulatory keywords false positives (QO.17) | LOW | Keywords cu the, LLM confirm |
| Season-aware thresholds khi Sentinel offline (QO.33) | LOW | Fallback ve default thresholds |
| TradingView khong co free API (QO.34) | MEDIUM | Verify feasibility truoc khi implement. Neu khong free -> skip |

**Rollback strategy**: Moi Wave co feature flag trong CAU_HINH Google Sheet.
Operator tat flag tu Sheet, khong can deploy code.

---

## 8. Acceptance Criteria tong the

| Metric | Hien tai | Target |
|--------|---------|--------|
| Breaking messages/ngay | 15-34 | <= 12 (cap boi MAX_EVENTS_PER_DAY) |
| F&G duplicate/ngay | 4-5 | <= 1 |
| Geo spam/ngay | 8-10 | <= 3 |
| Non-crypto events | 20-30% | < 5% |
| Cross-tier overlap | 70-80% | < 40% |
| Quality Gate mode | LOG-ONLY | BLOCK + retry |
| Hardcoded thresholds | 22+ | 0 (tat ca trong CAU_HINH) |
| L2 so lieu cu the | 0 | >= 3 per message |
| NQ05 violations | 2-3/ngay | 0 |
| Tests | 1501 | >= 1600 (100+ new tests) |

---

## 9. Anh Cuong Answers (2026-04-12)

| # | Cau hoi | Tra loi |
|---|---------|---------|
| 1 | MAX_EVENTS_PER_DAY | **12 tin/ngay** |
| 2 | Geo events | **A: Gop digest, toi da 3 lan/ngay** |
| 3 | LLM Impact Scoring | **OK** — SambaNova cham diem 1-10 |
| 4 | Quality Gate retry | **OK** — tu viet lai 1 lan, gui kem canh bao neu van loi |
| 5 | VN regulatory keywords | **Can research them** — danh sach ban dau chua du, team phai bo sung |
| 6 | Season-aware thresholds | **OK** — MUA_DONG thap hon, MUA_HE cao hon |
| 7 | Breaking schedule | **OK** — giu 4x/ngay (1h, 7h, 13h, 19h VN) |

> **Luu y QO.17**: Danh sach VN keywords can research them truoc khi implement.
> Mary phai scan them nguon phap ly VN de bo sung.

---

## 10. References

- Old spec (rejected): `docs/specs/SPEC-v2.0-phase2-quality-overhaul.md`
- v2.0 architecture: `docs/specs/v2.0-architecture-redesign.md`
- SambaNova reference implementation: `CIC-Sentinel/app/code/workers/Worker_5_FA_Scorer.gs:481-606`
- Config loader pattern: `src/cic_daily_report/storage/config_loader.py`
- LLM adapter pattern: `src/cic_daily_report/adapters/llm_adapter.py:115-200`
