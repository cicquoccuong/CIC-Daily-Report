# Changelog

## [Unreleased] - 2026-04-02

### Docs — Fix stale LLM chain references across 4 doc files

- **CLAUDE.md**: Added `gpt-oss-120b` to Cerebras entry (line 17); QĐ2 table row updated to full chain
- **README.md**: Fixed Multi-LLM Fallback bullet (was `Groq Llama 3.3 → Gemini Flash → Gemini Flash Lite`, now Gemini-first); updated Tech Stack + Zero Cost bullets
- **docs/architecture.md**: QĐ2 fallback chain corrected to Gemini-primary; `adapters/` file tree updated to reflect actual `llm_adapter.py` single-file structure
- **docs/epics.md**: Added update notes (not rewrites) on FR34, QĐ2 entry, and Story 3.1 — preserving planning history

## [2.0.0-alpha.11] - 2026-04-01

### LLM API Migration Đợt 1+2 — Cerebras model upgrade + Gemini quota fixes + Centralization

- **Cerebras model**: `qwen-3-32b` → `gpt-oss-120b` + `reasoning_effort` disabled (VĐ11, VĐ14 — qwen-3-32b deprecated)
- **Gemini thinking parts filter**: defense-in-depth filter for `thought` parts in Gemini responses (VĐ2)
- **Gemini quota fix**: 1500 → 250 RPD, 15 → 10 RPM in quota_manager.py (VĐ15 — actual free tier limit)
- **Shared rate group "gemini"**: quota 1500 → 250 RPD synced (B5 review fix)
- **Đợt 2**: Extracted `GEMINI_API_BASE` constant for DRY endpoint construction (was full hardcoded URL in each provider)
- **Đợt 2**: Model names in `_build_providers()` use local variables — no duplication between `model=` and `endpoint=`
- **Đợt 2**: Updated GAS display text: `AutoSetup.gs` + `Menu.gs` reflect current LLM chain

## [2.0.0-alpha.10] - 2026-03-31

### Fixed — 5 deferred items from Phase 1 audit (zero remaining)

- **R5-05** Kalshi fallback: if Polymarket returns 0 BTC/ETH markets, auto-fallback to Kalshi API
  (`api.elections.kalshi.com`). Consensus engine now has dual prediction market sources.
- **R5-10** Sheets timeout: ALL `asyncio.to_thread()` gspread calls wrapped with `wait_for(timeout=60s)`.
  Individual Sheets operations can no longer hang the pipeline indefinitely.
- **G7** Integration tests: 8 new E2E tests — master path flow, fallback trigger, consensus→run_log,
  cross-tier repetition check. (`tests/test_integration/test_pipeline_e2e.py`)
- **G9** Consensus monitoring: per-asset logging (label, score, source count, divergence alerts) +
  `consensus_summary` dict in pipeline run_log → visible in NHAT_KY_PIPELINE sheet notes.
- **BUG-17** CNBC RSS: updated from deprecated `search.cnbc.com` to current `www.cnbc.com/id/.../rss.html`.

### Stats
- Tests: 1430 → 1448 (+18 new: 6 Kalshi + 4 timeout + 8 E2E)
- All 40 audit items now resolved: 32 fixed (alpha.5) + 5 fixed (alpha.10) + 3 resolved by other tasks

## [2.0.0-alpha.9] - 2026-03-31

### Added — Phase 1c Batch 2: Sentinel Integration (P1.13-15, P1.21)

- P1.13: `classify_from_sentinel_season()` — maps 4-season cycle (MUA_DONG/XUAN/HE/THU) to
  MarketRegime. Overrides heuristic `classify_market_regime()` when Sentinel data available.
- P1.14: `merge_blacklist()` — combines hardcoded NQ05 banned keywords with Sentinel NQ05_BLACKLIST
  terms (BLOCK severity only, case-insensitive dedup). Pipeline passes merged list to all
  `check_and_fix()` calls.
- P1.15: `load_from_sentinel()` — supplements coin_mapping with Sentinel 01_ASSET_IDENTITY registry.
  Does not override existing mappings (operator config takes precedence).
- P1.21: `_follow_links()` in telegram_scraper — fetches article content from URLs in TG messages
  via httpx + trafilatura (max 2000 chars), called BEFORE LLM classification. 10s timeout per link.
- Tests: +33 (13 metrics_engine + 6 nq05 + 7 coin_mapping + 7 telegram)

## [2.0.0-alpha.8] - 2026-03-31

### Added — Phase 1c Batch 1: Sentinel Integration + New Collectors (P1.12, P1.19, P1.20)

- `storage/sentinel_reader.py` (471 lines, P1.12): Cross-read CIC Sentinel spreadsheet — Season
  (MUA_DONG/XUAN/HE/THU), SonicR zones (EMA34/89/200/610), FA scores (top 20), Registry
  (01_ASSET_IDENTITY), NQ05 blacklist. Stale detection, format_sentinel_for_llm, readonly scope.
- `collectors/fred_macro.py` (143 lines, P1.19): FRED API collector — 10Y Treasury (DGS10),
  CPI (CPIAUCSL), Fed Balance Sheet (WALCL). Requires FRED_API_KEY env var.
- `collectors/mempool_data.py` (173 lines, P1.20): Mempool.space collector — BTC hashrate,
  recommended fees (fast/medium/slow), difficulty adjustment. No API key needed.
- Pipeline: 3 new collectors in asyncio.gather (Stage 1), FRED+Mempool text in LLM context,
  Sentinel text passed to Master Analysis via build_master_context().
- Tests: +43 (29 sentinel + 7 FRED + 7 mempool), all external APIs mocked.

## [2.0.0-alpha.7] - 2026-03-31

### Added — P1.5: Telegram Scraper Upgrade (16 Tier 1 channels)

Replaces placeholder with real Telethon async scraper + Groq LLM batch classification.

- `telegram_scraper.py` (100→405 lines): Full rewrite with Telethon StringSession async client
- 16 Tier 1 "Quality Insight" channels: HCCapital, Fivemincrypto, coin369, vnwallstreet,
  kryptonews, hctradecoin, Coin98, A1A, coin68, WuBlockchain, MacroAlf, tedtalksmacro,
  crypto_macro, Glassnode, Laevitas, GreeksLive
- `TelegramChannelConfig` dataclass: handle, name, tier, language, category, processing
- `TelegramMessage` extended: sentiment, key_levels, thesis, language, category, url
- Batch LLM classification: 10 messages/call via Groq (saves Gemini quota for Master Analysis)
- Per-channel 30s timeout, 24h message window, 50 messages/channel limit
- Graceful fallback: no credentials → [], channel not found → skip, LLM fails → unclassified
- Tests: 3→36 (+33 new), all Telethon calls mocked
- `telethon>=1.42.0` added to project dependencies

## [2.0.0-alpha.6] - 2026-03-30

### Added — P1.7: Master Analysis + Tier Extractor (core v2.0 architecture change)

Replaces 7 independent LLM calls with 1 Master Analysis (ALL data → single comprehensive
analysis) + 6 sequential extractions (L1-L5 + Summary). Eliminates cross-tier contradictions.
Research article stays independent, receives Master as supplementary context.

#### New files
- `generators/master_analysis.py` (282 lines) — MasterAnalysis dataclass, 8-section Vietnamese
  system prompt, `build_master_context()` (assembles all 15 data sources), `generate_master_analysis()`
  (16K max tokens, temperature 0.4), `validate_master()` (conclusion + section completeness check)
- `generators/tier_extractor.py` (290 lines) — 6 ExtractionConfigs (L1-L5 + Summary), sequential
  extraction with adaptive cooldown, 429 retry, per-tier audience/focus/word targets. Summary
  extraction includes full story-based digest format (Hook + Overview + Stories + Forward Look)

#### Pipeline rewire (`daily_pipeline.py`)
- Stage 2: Master Analysis Generation → Stage 3: Quality Gate on Master → Stage 4: Tier Extraction
- Fallback: if Master fails (short/truncated/error) → immediate fallback to per-tier generation
  (v0.32.0 code path preserved in full — `generate_tier_articles` + `generate_bic_summary` untouched)
- Research article always independent: receives `master_analysis_text` as optional context

#### DA-driven design adjustments (B3.5 review findings)
- Research generator stays independent (NOT extracted from Master) — preserves depth
- Extractions are sequential (NOT parallel) — respects 7 RPM rate limit
- Master retry = 1 attempt max, then fallback immediately
- Section parsing uses fuzzy regex + Vietnamese diacritics detection
- Summary extraction includes full story-format spec from summary_generator.py
- validate_master: finish_reason=length ALWAYS triggers fallback (regardless of conclusion match)

### Stats
- Tests: 1284 → 1322 (+38 new tests)
- New files: 2 source + 2 test (1265 lines total)
- Modified: daily_pipeline.py (+140 lines), research_generator.py (+20 lines)
- Token budget: 1 Master (16K) + 6 extractions + 1 Research = 8 LLM calls

## [2.0.0-alpha.5] - 2026-03-30

### Fixed — 32 issues from Phase 1 comprehensive audit (5 scan rounds)

Root cause: spec defined modules not data flows; tasks assigned as "create module" without
"connect + prove"; no integration gate. Fixed by wiring consensus into pipeline, fixing 3 APIs,
correcting edge cases, and hardening security.

#### Wave 0+1: Core wiring + API fixes (15 issues)
- **G1** Wire Expert Consensus into daily pipeline (collect → build → format → pass to generators)
- **G2** Summary generator receives consensus_text for BIC Chat digest
- **G3** Research generator receives consensus_text for deep analysis
- **G4** RSS macro articles now carry `news_type="macro"` (was only `source_type`)
- **G5** Historical metrics store real consensus score/label (was hardcoded 0.0/"N/A")
- **BUG-01** Polymarket API: removed non-existent `slug_contains` param, use volume sort + single call
- **BUG-02** Groq API: `reasoning_effort: "none"` instead of wrong `thinking` param (Groq-only)
- **BUG-03** AP News RSS: switched to Google News proxy (apnews.com RSS returns 404)
- **BUG-07** Consensus weights per-category: smart_money 2.5÷N sources (was 2.5 each = 65% dominance)
- **BUG-14** Symmetric score boundaries: score ≥ −0.2 = NEUTRAL (was asymmetric)
- **SEC-01** NaN/Infinity validation in consensus weighted score calculation
- ETH proxy sources now get per-category weight (was missed by `startswith` name matching)
- Tier articles L3-L5 receive consensus data (L1-L2 excluded by design)
- Prediction markets: single API call instead of duplicate

#### Wave 2: LLM adapter + text processing (5 issues)
- **BUG-04** Gemini SAFETY/RECITATION finish_reason mapped to `content_filter` with truncation
- **BUG-05** Nested `<think>` tags: iterative `[^<]*` regex strips from inside out
- **BUG-08** `_truncate_to_complete_sentence` falls back to last whitespace + "..." when no boundary
- **BUG-09** `text_utils` sentence boundary at position 0 handled with length guard
- **BUG-15** Breaking content `body_limit` floored at 500 chars (was negative with long suffix)

#### Wave 3-5: Event detection, consensus, feedback, security (12 issues)
- **BUG-06** Quality Gate regex: numeric ≥5.0% check replaces digit-pattern `[5-9]` false positive
- **BUG-16** "nuclear" keyword skips energy context (nuclear energy ≠ geopolitical threat)
- **BUG-20** Vietnamese dollar format `$87.500` now recognized as data-backed sentence
- **BUG-23** market_overall F&G weight redistributed to BTC/ETH when F&G data missing
- **BUG-10** Atomic file write (tempfile + os.replace) for breaking feedback JSON
- **G8** Quality Gate logs "RETRY RECOMMENDED" with density + issues
- **SEC-02** Feedback file size limit (1MB) before read
- **SEC-04** Crypto-context neutralization for geopolitical keywords (prevents false positives)
- **SEC-05** RSS `_sanitize_text` strips HTML tags before entity decoding
- **SEC-06** Breaking events capped at 100/day
- **R5-06** Yesterday's events included in daily pipeline read (catches late UTC breaking news)
- **R5-09** Version synced: pyproject.toml + config.py + CLAUDE.md → 2.0.0-alpha.5

### Stats
- Tests: 1221 → 1284 (+63 new tests)
- Files changed: 24 (13 source + 11 test)
- 3 review rounds per wave (build → review → fix → verify)

### Deferred (10 items — Phase 1c / Phase 2 / P1.7)
- G6 (metrics_engine consensus expansion) → P1.7 Master Analysis
- G7 (integration tests) → B7 Phase Gate
- G9 (consensus monitoring), G10 (Telegram scraper), G11 (breaking↔daily feedback)
- BUG-17 (CNBC old URL), SEC-03 (rate limit), R5-04 (graceful degradation)
- R5-05 (Polymarket fallback), R5-10 (Sheets timeout)

## [2.0.0-alpha.4+docs] - 2026-03-29

### Docs — Spec + Workflow updated to prevent 40-issue root causes (DA findings)

Added interface contracts, DoD per task, B3.5 DA Design Review, B7 Phase Gate, and Golden Rule #22
to close the 3 structural gaps that caused 40 issues: missing data flow contracts, no pipeline
integration gate, and tasks defined as "create module" without a "connect + prove" requirement.

#### v2.0 Spec (`docs/specs/v2.0-architecture-redesign.md`)
- Section 2.2: Added explicit weight-per-category clarification and symmetric score boundaries
  (STRONG_BULLISH ≥0.6, BULLISH ≥0.2, NEUTRAL ≥-0.2, BEARISH ≥-0.6, STRONG_BEARISH <-0.6)
- Section 3.7 (NEW): Interface Contracts — Unified News Item field names, `news_type` not
  `source_type`, Consensus→Generator contract via `GenerationContext`, field naming convention
- Section 3.8 (NEW): Definition of Done per task — 5 mandatory criteria (code, tests, pipeline
  connected, data flows to output, integration test). Scaffolding status rules.

#### Workflow (`_bmad/_config/custom/optimized-team-flow/QUY-TRINH-LAM-VIEC-CHUAN.md`) — v1.8
- B3.5 (NEW): Devil's Advocate Design Review gate before B4 — required for algorithms, data flows,
  API integrations. DA must verify weights, boundaries, endpoint existence, field consistency.
- B7 Phase Gate (NEW): Integration Verification after all waves in a Phase — Pipeline Trace,
  Data Flow Test, Cross-wave Integration, Field Consistency, Spec Compliance (Winston + Quinn + DA)
- Old B7 Report → renamed B8 Report (numbering shift)
- Golden Rule #22 (NEW): Task creating new files MUST include (1) create file, (2) import into
  pipeline, (3) integration test proving data flows. Module without pipeline connection = not done.
- Section 10 NEVER list: 3 new rules for B3.5 skip, B7 Phase Gate bypass, split-task scaffolding

## [2.0.0-alpha.4] - 2026-03-28

### Added — Phase 1b Wave 3: Expert Consensus Engine (P1.6)
- Expert Consensus Engine with 3-layer weighted scoring (Polymarket=3.0, Smart Money=2.5, Expert=2.0, Social=1.0)
- 5 source extractors: Polymarket probabilities, Fear & Greed Index, Funding Rate, Whale Flows, ETF Flows
- 3 consensus assets: BTC, ETH, market_overall (composite BTC×0.6 + ETH×0.3 + F&G×0.1)
- Contrarian detection and divergence alerts (smart money vs social sentiment)
- ETH proxy transparency: BTC-specific signals tagged "(BTC proxy)" with -0.1 confidence penalty
- ETF neutral band: flows below $50M treated as noise (confidence=0.3)
- Score labels with asymmetric boundaries: STRONG_BULLISH (≥0.6) → STRONG_BEARISH (≤-0.6)
- 79 new tests (total: 1221)

## [2.0.0-alpha.3] - 2026-03-28

### Phase 1b Wave 2 — Prediction Markets + Macro RSS + Geo Keywords + Breaking Feedback Loop (4 tasks, 131 new tests)

Polymarket BTC/ETH sentiment data thu thập được, 5 nguồn RSS vĩ mô thêm vào, 12 từ khóa địa chính trị
và 5 macro trigger mới, và breaking news giờ chia sẻ context với daily pipeline qua JSON.

#### P1.4: Polymarket Prediction Markets Collector
- NEW `collectors/prediction_markets.py` — fetches BTC/ETH prediction market data from Polymarket
  Gamma API (free, no auth required).
- `PredictionMarketsData` dataclass with `format_for_llm()` and `format_for_consensus()` methods.
- Scaffolding ready for P1.6 (Consensus Engine) — not yet wired into main pipeline.

#### P1.8: Macro RSS Feeds
- Added 5 macro RSS feeds to `rss_collector.py`: Reuters (via Google News proxy), AP News, CNBC,
  OilPrice, Al Jazeera — all tagged `source_type="macro"`.
- B5 fix: Reuters original URL (dead since 2020) replaced with Google News proxy; AP replaced with
  direct feed.

#### P1.9: Geopolitical Keywords + Macro Market Triggers
- Added 12 geopolitical always-trigger keywords: war, invasion, blockade, sanctions, airstrike,
  missile, nuclear, ceasefire, oil crisis, energy crisis, embargo, hormuz — no crypto context needed.
- Added 5 macro triggers with Vietnamese titles: Oil ≥+8%, Gold ≥+3%, VIX ≥30, DXY ≥+2%,
  SPX ≤-3%.

#### P1.10: Breaking Feedback Loop
- NEW `breaking/feedback.py` — persists sent breaking events to `data/breaking_today.json` (JSON).
- `breaking_pipeline.py` saves events after send; `daily_pipeline.py` reads JSON to inject context
  into LLM prompt.
- Auto-resets on new day; graceful degrade if file missing.

### Test Coverage
- 1011 → 1142 tests (+131 new tests), 1142/1142 pass.

## [2.0.0-alpha.2] - 2026-03-28

### Phase 1b Wave 1 — LLM Output Cleanup + Hard Character Limits (3 tasks, 58 new tests)

Think tags stripped at adapter level, truncated responses cut at sentence boundaries, and hard
character limits enforce Telegram safety and article quality for all output types.

#### P1.23: Strip `<think>...</think>` Tags
- `_strip_think_tags()` added to `llm_adapter.py` — regex strips think tags from ALL LLM responses.
- `thinking: {type: disabled}` injected into Groq API payload for Qwen3 models to prevent
  reasoning tokens from appearing in output.
- Fallback handles unclosed `<think>` tags when LLM runs out of tokens mid-thinking.
- Defense-in-depth: applied at adapter level, all callers protected automatically.

#### P1.24: Sentence Boundary Truncation on `finish_reason=length`
- `finish_reason` field added to `LLMResponse` dataclass.
- `_truncate_to_complete_sentence()` finds last `. ` / `! ` / `? ` boundary to avoid cut-off sentences.
- Auto-applies when `finish_reason=length` (Groq) or `MAX_TOKENS` (Gemini).
- Warning logged when truncation occurs.

#### P1.25: Hard Character Limits
- New `generators/text_utils.py` — `truncate_to_limit()` utility with paragraph → sentence →
  hard-cut boundary strategy.
- Breaking news capped at 4000 chars (Telegram single-message safety limit).
- Research articles capped at 18000 chars (2500 VN words + formatting headroom).
- NQ05 DISCLAIMER always preserved: body truncated first, disclaimer appended after.

#### B5 Review Fixes
- Unclosed `<think>` tag fallback (strips from opening tag to end of string).
- Sentence boundary detection expanded to include `!` and `?` markers.
- `RESEARCH_MAX_CHARS` raised 12000 → 18000 to accommodate full research articles.
- DISCLAIMER truncation order enforced (body first, never disclaimer).

### Test Coverage
- 953 → 1011 tests (+58 new tests), 1011/1011 pass.

## [2.0.0-alpha.1] - 2026-03-28

### Phase 1a — Research Data Pipeline + Quality Foundation (5 tasks)

First alpha release of v2.0 architecture: on-chain research data now flows through to article
generation, fabrication filter made context-aware, historical metrics storage added, technical
indicators (RSI/MA) integrated, and quality gate scaffolding in place.

#### P1.1: Research Data → Article Generation
- `GenerationContext` dataclass added to `article_generator.py` — carries `research_data`
  (MVRV, NUPL, SOPR, Puell Multiple, ETF flows, stablecoin supply) alongside existing fields.
- L3–L5 tier article generation now receives research_data; L1–L2 remain unaffected.
- `daily_pipeline.py` passes collected research data through GenerationContext.

#### P1.2: Context-Aware Fabrication Filter
- Fabrication filter in `article_generator.py` now reads actual input data before filtering.
- Only strips metrics genuinely absent from input — previously removed valid on-chain data
  that was present but not explicitly listed in a hardcoded allowlist.

#### P1.3: Historical Metrics Storage (LICH_SU_METRICS tab)
- New `storage/historical_metrics.py` — saves daily snapshot of 23 on-chain/market columns.
- New `LICH_SU_METRICS` tab added to Google Sheets schema (10th tab).
- Provides 7-day and 30-day comparison context to LLM prompt for trend analysis.
- `sheets_client.py` updated with LICH_SU_METRICS tab schema.

#### P1.11: Technical Indicators (RSI + Moving Averages)
- `collectors/market_data.py` gains `TechnicalIndicators` dataclass: RSI 14d, MA50, MA200
  for BTC and ETH via yfinance.
- Golden cross / death cross detection (MA50 vs MA200).
- Integrated into `daily_pipeline.py` collection phase.

#### P1.22: Quality Gate (log-only)
- New `generators/quality_gate.py` — two checks: factual consistency (metrics cited vs
  metrics provided) and insight density (analyst language ratio).
- Log-only mode in Phase 1a — no articles blocked yet. Blocking enabled in Phase 1b.

## [0.32.0] - 2026-03-27

### LLM Overhaul + Data Source Fixes + Quality Fixes (3 clusters, 20+ changes)

Root cause investigation after Gemini 2.0 deprecation deadline (31/03/2026) + 429 rate limit errors
+ duplicate breaking alerts. Found cascading failures across LLM provider chain, data sources,
and dedup/NQ05 compliance layers.

#### Cụm 1: LLM Overhaul (P0 — Khẩn cấp trước 31/03)

- **Gemini 2.5 migration**: Replaced Gemini 2.0 Flash/Lite with 2.5 Flash/Lite — fixes 429 errors
  from deprecated models (deadline 31/03/2026).
- **Groq Qwen3 32B**: Replaced Groq Llama 3.3 with `qwen/qwen3-32b` (60 RPM) — fixes insufficient
  free tier quota that caused daily pipeline to fail after 3 articles.
- **Groq Llama 4 Scout**: Added as secondary Groq fallback (30 RPM).
- **Cerebras Qwen3**: Added as 5th provider in fallback chain — gracefully skipped if no API key.
- **New fallback chain**: Gemini 2.5 Flash → Flash-Lite → Groq Qwen3 32B → Groq Llama 4 Scout
  → Cerebras Qwen3 (3 independent infra: Google, Groq, Cerebras).
- **Shared rate groups**: Gemini group (Flash + Lite) and Groq group (Qwen3 + Llama 4) share
  quota correctly. Added `"gemini"` shared rate group to QuotaManager — fixes rate limiting bypass
  that caused 429 errors.
- **Reduced cooldown**: Buffer 15s→5s, max 180s→120s — total pipeline cooldown ~200s (was ~356s).

#### Cụm 2: Data Source Fixes (P1)

- **CryptoPanic v2**: Migrated API v1→v2 endpoint — fixes 404 errors in breaking news detection.
- **ETF flows defensive check**: Added type checking before accessing `__NEXT_DATA__` structure
  on btcetffundflow.com — fixes crash when site changes response format.
- **CoinMetrics 400 logging**: Added response body diagnostic logging for HTTP 400 errors.
- **Binance 451 workaround**: CoinGecko fallback for Pi Cycle indicator when Binance geo-blocks.
- **Missing env vars**: Added `CEREBRAS_API_KEY`, `GLASSNODE_API_KEY`, `WHALE_ALERT_API_KEY`,
  `COINALYZE_API_KEY` to GitHub Actions workflows.
- **Altcoin Season fallback**: Synthetic value (50 = neutral) when BlockchainCenter API unavailable.
- **F&G severity fix**: Added Fear & Greed terms to severity classifier crypto relevance keywords
  — fixes F&G events being incorrectly skipped.
- **Breaking pipeline RSS-first**: CryptoPanic only queried when RSS finds <3 events — optimizes
  quota usage.

#### Cụm 3: Quality Fixes (P1)

- **Error notification**: Truncation at 3500 chars + plain text `parse_mode` — fixes Telegram
  400 errors on long error messages.
- **URL dedup window**: Extended from 4 hours to 7 days — fixes duplicate breaking alerts
  (e.g., Cardano 3x sends).
- **Entity overlap threshold**: Lowered ≥2→≥1 entities with similarity ≥0.50 — fixes duplicate
  alerts for single-entity news (e.g., Circle 2x sends).
- **NQ05 pattern expansion**: Added "có thể/cần/nếu" prefixes + standalone "xem xét tích lũy"
  pattern — fixes compliance bypass on softened phrasing.
- **Filler phrase removal**: Top 3 patterns ("điều này cho thấy", "có thể ảnh hưởng đến",
  "trong bối cảnh") upgraded from WARN to sentence-level REMOVE.

## [0.31.0] - 2026-03-23

### BIC Chat Summary — Story-based Digest Rewrite

Replaced 4-section format (emoji table + bullet lists) with story-based digest:
- **Cross-signal hook**: Opening 1-2 sentences highlighting contradictions in data
  (e.g., F&G low but whale accumulation → unique CIC insight)
- **Narrative market overview**: Numbers woven into prose (not standalone table)
- **Prioritized stories**: Top 2-3 news get 2 paragraphs of deep analysis,
  remaining 3-5 get concise 1-paragraph treatment
- **Forward look**: Upcoming macro/crypto events in 3-7 days
- **Mobile-optimized**: Max 3 sentences per paragraph, bold only for headlines
  and key numbers, no tables, no complex markdown
- Removed: emoji metrics table (📊), numbered news list, rigid 4-section structure

### Dual-branch Fix — Provider Management + Content Quality

Root cause: Daily report produced only 3/7 outputs (2026-03-23). Investigation revealed TWO
independent root causes: (1) rate limit exhaustion — breaking pipeline consumed Gemini quota,
Groq exhausted after 3 articles; (2) content quality — filler phrases, TL;DR format, NQ05 violations.

#### Branch 1: Provider Management (quantity)

- **Provider preference**: `LLMAdapter(prefer="gemini_flash")` for daily pipeline,
  `prefer="groq"` for breaking. Best model used first per pipeline type — consistent quality,
  no quota competition.
- **Adaptive cooldown**: Replaced fixed 60s with `suggest_cooldown()` — calculates based on
  actual tokens used and provider-specific TPM limits:
  `max(15, min(tokens_used / provider_tpm * 60 + 15, 180))`.
  Gemini (32K TPM) gets ~15-25s, Groq (6K TPM) gets longer cooldowns.
- **Time-based circuit breaker**: `_provider_failed` changed from `dict[str, bool]` to
  `dict[str, float]` (failure timestamp). Provider retried after 300s recovery window.
  When ALL providers failed, oldest-failed is retried first.

#### Branch 2: Content Quality

- **Anti-filler in Layer 6**: Positive instructions — "Câu cuối = HỆ QUẢ CỤ THỂ (ai bị ảnh
  hưởng, bao nhiêu, khi nào)" replaces banned filler phrases in article prompts.
- **TL;DR ban + strip**: Added to ⛔ KHÔNG list in prompts. Post-generation regex strips any
  `TL;DR:` prefixes that still appear. Removed stale FR14 TL;DR validation from daily pipeline.
- **NQ05 advisory patterns** (3 new SEMANTIC_NQ05_PATTERNS, REMOVE mode):
  `nhà đầu tư cần theo dõi chặt chẽ`, `quyết định đầu tư thông minh/sáng suốt`,
  `giai đoạn tích lũy trước khi tăng trưởng`.

#### Bug Fixes

- **ETF flows type guard**: `research_data.py` — added `isinstance(first_query, dict)` check
  before accessing `.get()` on queries[0] (was crashing on non-dict responses).

## [0.30.1] - 2026-03-23

### Prompt Quality — NQ05 Input→Output Shift + Anti-filler + Emoji Formatting

After reviewing real pipeline output (2026-03-22 + 2026-03-23), identified that NQ05
restrictions in prompts caused LLM self-censorship → generic filler content.

#### NQ05 Prompt Slim (all content types)
- **NQ05_SYSTEM_PROMPT**: Removed verbose COMPLIANCE section (4 rules) + CỤM TỪ CẤM
  (7 banned phrases) → replaced with 1-line NQ05 reminder. NQ05 enforcement now
  exclusively via post-filter (Layer 2).
- **Tier Articles**: Removed NQ05 from ⛔ KHÔNG list, slimmed format instructions.
- **Summary**: Removed NQ05 line from QUY TẮC.
- **Research**: Removed 2 NQ05 lines (section 8 + QUY TẮC CHUNG).

#### Breaking News Prompt Rewrite
- **Positive instructions**: "CHUYỆN GÌ XẢY RA" (đoạn 1) + "TẠI SAO QUAN TRỌNG" (đoạn 2)
  — prevents paragraph duplication.
- **Anti-filler**: Explicit ban on "Điều này cho thấy...", "có thể ảnh hưởng đến...",
  "trong bối cảnh..." — replaced by "kết thúc bằng HỆ QUẢ CỤ THỂ".
- **Neutral tone**: "Tin xấu → nêu rủi ro THẬT, KHÔNG giảm nhẹ" — prevents AI from
  spinning security incidents as positive PR.
- **Emoji markers**: 📌 title, paragraphs without rigid headings.

#### Digest Prompt Rewrite
- Same anti-filler treatment: each item ends with specific consequence, not generic filler.
- **bold** for all numbers (price, %, quantity, dates).

#### NQ05 Post-filter (2 new patterns)
- `cơ hội...tích lũy/mua vào/mua thêm` — catches implicit buy recommendations.
- `nhà đầu tư/bạn nên...mua/bán/tích lũy` — catches "should buy/sell" variants.

#### Severity Classifier — Analysis Downgrade (P2)
- Added `ANALYSIS_DOWNGRADE_KEYWORDS` (19 words, VN+EN): "hậu quả", "bài học",
  "phân tích", "aftermath", "lesson", "analysis", "review", etc.
- When title matches a critical keyword (e.g. "hack") AND an analysis keyword
  (e.g. "hậu quả"), severity downgrades from CRITICAL → IMPORTANT.
- Rationale: "Hậu quả hack Bybit" is analysis, not a live hack alert.
- 7 new tests covering downgrade + live-event-stays-critical scenarios.

#### RSS Multi-topic Handling (P3)
- Added "NHIỀU CHỦ ĐỀ TRONG SOURCE" instruction to BREAKING_PROMPT_TEMPLATE.
- When source article covers multiple unrelated topics, AI focuses on the single
  most important story (priority: specific numbers > large scale > broad impact).

#### Emoji & Format
- Tier Articles: emoji guidance (📈📉⚡📊🔍💡), mobile-friendly paragraph style.
- Breaking: 📌 title marker consistent across all breaking news.

## [0.30.0] - 2026-03-22

### Major Overhaul — Pipeline Reliability, Content Quality & Architecture (6 clusters, 19 fixes)

Root cause investigation after 20+ duplicate breaking news sends on 2026-03-22. Found cascading
failures across dedup persistence, LLM fallback chain, content quality, and missing monitoring.

#### Cụm 1: Dedup & Sheets Persistence (Triple-send root cause)
- **atomic_rewrite()**: New Sheets write method — single `ws.update()` call replacing non-atomic
  delete+append pattern. If write fails, old data remains intact.
- **URL-based dedup**: First check in dedup chain — same URL = same article, regardless of
  AI-generated title differences across runs.
- **Fatal dedup load**: `_load_dedup_from_sheets()` retries 3x with exponential backoff, then
  raises `RuntimeError` instead of silently returning empty state (which would re-send everything).
- **atomic_rewrite for BREAKING_LOG**: `_persist_dedup_to_sheets()` uses atomic_rewrite as primary
  strategy with append-only fallback for new entries.

#### Cụm 2: Daily Pipeline LLM Cascade
- **Per-provider circuit breaker**: Replaced global `_all_providers_failed` boolean with
  per-provider `_provider_failed` dict. Gemini failing no longer blocks Groq.
- **Early return tuple fix**: `_execute_stages()` early returns now return 4-tuple
  `([], errors, "", 0)` matching caller's expected `articles, errors, llm_used, research_wc`.
- **60s cooldown**: Added cooldown before Summary/Research generation to let per-minute rate
  limit window reset after 5+ tier article generations.
- **Shared rate limiter**: Gemini Flash + Flash Lite share 15 RPM total via `_SHARED_RATE_GROUPS`.
  Each gets 7 RPM (14 combined, 1 RPM headroom).

#### Cụm 5: Critical vs Important Architecture (Decision 1C + 2B)
- **Separate delivery flows**: Critical (🔴) events → individual articles sent immediately.
  Important (🟠) events → batched into themed digest (reduces Telegram noise).
- **Night mode 07:00 VN run**: Added `0 0 * * *` UTC to breaking-news cron for morning
  deferred event delivery at 07:00 VN.
- **Digest emoji**: Important digest uses 🟠 header instead of 🔴.

#### Cụm 6: Monitoring & Admin Alerts
- **`send_admin_alert()`**: Fire-and-forget Telegram notification for pipeline failures.
  Silently swallows all errors — monitoring never crashes the pipeline.
- **Breaking pipeline alert**: Notifies on pipeline error/timeout with error summary.
- **Daily pipeline alert**: Notifies on error/timeout with article count and errors.
- **Research skip alert**: Notifies when research article fails quality gate.

#### Cụm 3: Breaking News Content Quality
- **CIC context in prompt**: Added community context (Crypto Investment Community, experienced
  members) so LLM writes for the right audience.
- **Higher word targets**: Critical 200-250 → 300-400, Important 100-150 → 200-300 words.
- **Deeper source content**: Article extraction increased 1500→3000 chars, timeout 8→12s.
- **Labeled context sections**: Market snapshot and recent events now have clear headers
  in the prompt to help LLM distinguish data sources.
- **Narrowed NQ05 patterns**: Removed over-aggressive semantic patterns that stripped legitimate
  analysis (support/resistance levels, "nhà đầu tư nên theo dõi", market expectations).

#### Cụm 4: Research Article
- **Decoupled from tier generation**: Research article now attempts generation whenever LLM
  is available, not gated by `if generated:`. Research uses raw pipeline data (context),
  not generated tier articles.

## [0.29.1] - 2026-03-21

### Bug Fixes — Content Quality & Pipeline Reliability (7 bugs + 1 improvement)

Post-release review of v0.29.0 found 7 bugs across content generation and pipeline flow.

#### P0: Content Quality
- **(BUG 7) NQ05 filler removal → WARN-only**: Reverted filler phrase removal (v0.28.0)
  back to warn-only. The 7 filler patterns (`có thể ảnh hưởng đến`, `trong bối cảnh`,
  `điều này cho thấy`, etc.) are structural Vietnamese grammar — removing them from prose
  destroyed sentence structure, producing unreadable breaking news. Filler reduction now
  handled via improved LLM prompt instructions instead.
- **NQ05 sentence-level removal**: `_remove_sentences_with_pattern()` now removes entire
  *sentences* containing NQ05 violations (banned keywords, allocation patterns, semantic
  patterns) instead of just the matching phrase. Prevents broken grammar when violations
  are structural parts of sentences. Multi-sentence lines keep clean sentences intact.

#### P1: Pipeline Flow
- **(BUG 1) Deferred reprocess persist**: `_reprocess_deferred_events()` now persists dedup
  status to Sheets after reprocessing. Without this, status changes were lost if pipeline
  exited before final persist — causing deferred events to be re-sent next run.
- **(BUG 2) Early return persist**: Both early-return paths (`if not events` / `if not
  dedup_result.new_events`) now persist dedup state when deferred events were sent.
- **(BUG 4) Individual path count-after-delivery**: `events_sent` and `sent_events.append()`
  moved AFTER successful `_deliver_single_breaking()`. Previously counted before delivery —
  if Telegram failed, counts were inflated and run log showed false success.
- **(BUG 6) Digest path count-after-delivery**: Same fix for digest mode — `events_sent +=
  len(send_now)` moved after all Telegram sends complete.

#### P2: Status Tracking
- **(BUG 3) `_STATUS_PRIORITY` completeness**: Added `sent_digest` (5), `delivery_failed`
  (4), and `deferred_overflow` (2) to `DedupManager._STATUS_PRIORITY`. Missing entries
  defaulted to priority 0, causing incorrect hash collision resolution.
- **(BUG 5) `delivery_failed` status**: Distinguish delivery failure from generation failure.
  If content was generated successfully but Telegram send failed, status is now
  `delivery_failed` (not `generation_failed`). `_reprocess_deferred_events()` also retries
  `delivery_failed` entries.

## [0.29.0] - 2026-03-21

### Breaking Pipeline Reliability Overhaul (12 issues / 5 root-cause layers / 15 fixes)

Root-cause investigation of "AI không khả dụng" errors and burst-sending behavior
revealed a 5-layer causal chain from false-positive detection through infinite loop.
All 12 issues resolved across 6 implementation phases.

#### Layer 1: Quota & Rate Limiting
- **(A2) track_failure()**: `QuotaManager` now updates `last_call_time` on failed API calls,
  preventing rapid-fire retries against rate-limited providers (was: only updated on success)
- **(A3) Shared LLMAdapter**: Single `LLMAdapter` instance for entire pipeline run — was
  creating 3 separate instances (main, RSS fallback, deferred), each with independent
  QuotaManagers that couldn't coordinate rate limits

#### Layer 2: Circuit Breaker
- **(A7) Circuit breaker**: After all LLM providers fail once, subsequent `generate()` calls
  fail fast without making API requests. Resets on next successful response
- **(C1) Health check**: Pipeline verifies LLM availability with a ping before batch
  processing — opens circuit breaker early if all providers are down

#### Layer 3: Error Handling
- **(A4) Error propagation**: `generate_breaking_content()` no longer silently catches LLM
  errors and sends "AI không khả dụng" raw data. Exceptions propagate to caller, which marks
  events as `generation_failed` for retry in next run
- **(B4) Skip enrichment**: When LLM is known down, skip 8-second article fetch
  (trafilatura) — saves time when content generation will fail anyway

#### Layer 4: Flow Control
- **(A6/B3) Priority ordering**: Events sorted by severity (Critical → Important → Notable)
  before processing — ensures most important events get LLM quota first
- **(B1) Event cap**: Max 5 events per run (`MAX_EVENTS_PER_RUN`). Overflow events deferred
  to next run as `deferred_overflow` instead of exhausting all quota
- **(A8) Deferred cap**: Max 5 deferred events reprocessed per run (`MAX_DEFERRED_PER_RUN`)
- **(B2) Inter-event delay**: 30-second gap between Telegram sends (`INTER_EVENT_DELAY`).
  Prevents burst-sending dozens of alerts simultaneously
- **(B5) Digest mode**: When ≥5 events need sending, generate single combined summary
  via `generate_digest_content()` instead of individual messages
- **(A5) Incremental persist**: Dedup state saved after each successful send (not just at
  end). Prevents timeout → dedup lost → re-send loop (the infinite loop root cause)

#### Layer 5: False Positive Reduction
- **(C2) Context-aware keywords**: Split keywords into ALWAYS_TRIGGER (hack, exploit,
  rug pull, delisting, bankrupt) and CONTEXT_REQUIRED (crash, collapse, SEC, ban,
  emergency). Generic keywords only fire when title also contains a crypto-related word.
  Prevents "plane crash" from triggering crypto breaking alerts

## [0.28.0] - 2026-03-21

### Quality Audit Fixes (42 issues / 8 root causes / 7 clusters)

Comprehensive QA/QC audit of pipeline output identified 42 issues across 8 root causes.
All fixes organized into 7 implementation clusters:

#### Cluster 5: Security & Delivery
- **API key sanitization**: `error_notifier.py` now strips API keys from error messages
  before sending to Telegram (regex redaction for Google, Groq, OpenAI key formats)
- **Link preview disabled**: Added `link_preview_options: {is_disabled: true}` to Telegram
  `sendMessage` payload to prevent unwanted URL previews in articles

#### Cluster 4: Data Integrity
- **Synthetic data warning**: Altcoin Season Index fallback now marked as
  `source="SYNTHETIC (BlockchainCenter unavailable)"` to prevent LLM misinterpretation
- **Narrative word boundary**: `metrics_engine.py` narrative detection upgraded from
  substring matching to `re.search(r"\b...\b")` — fixes false positives like "ADA" in "Canada"

#### Cluster 2: NQ05 Post-Filter
- **Filler removal**: Upgraded from WARN-only to REMOVE — filler phrases are now actively
  stripped from generated content (was: counted but preserved)
- **7 new semantic NQ05 patterns**: Added detection for price predictions, investor
  recommendations, price targets, support/resistance levels

#### Cluster 1: Prompt Engineering
- **Tier-specific data headers**: Each tier now cites only its actual data sources
  (L1: CoinLore+alternative.me, L5: all sources) instead of generic "CoinLore, CoinGecko, yfinance"
- **Format simplification**: Removed dual "Tóm lược/Phân tích chi tiết" structure that
  caused within-tier repetition — articles now write in continuous flow

#### Cluster 3: Output Validation
- **Fabrication blocking**: `_validate_output()` → `_validate_and_clean_output()` —
  fabricated metrics and banned source citations are now REMOVED from content (was: log warning only)

#### Cluster 6: Breaking News
- **Entity-based dedup**: New `_is_entity_overlap()` in `dedup_manager.py` — catches
  duplicate events with different wording by comparing named entity overlap (Jaccard similarity)
- **Crypto relevance filter**: New `_is_crypto_relevant()` in `severity_classifier.py` —
  non-crypto events (e.g., sports betting) are skipped instead of triggering breaking alerts

#### Cluster 7: Quota Management
- **Quota awareness**: Added `remaining()` and `has_budget()` methods to `QuotaManager`
  for pipeline to check quota before optional tasks (research, summary)

#### Unified Coin Name↔Ticker Mapping (Config-Driven)
- **New `core/coin_mapping.py`**: Config-driven name→ticker resolution. Primary source:
  DANH_SACH_COIN "Tên đầy đủ" column (operator-managed). Fallback: hardcoded 30+ entries.
  Operator adds new coin + name on Sheet → pipeline recognizes it, no code change needed.
- **`config_loader.get_coin_name_map()`**: New method reads "Tên đầy đủ" column, populates
  `coin_mapping.load_from_config()` at pipeline startup (daily + breaking)
- **Breaking pipeline**: `_extract_coins_from_title()` now recognizes project names, not just
  uppercase tickers — fixes "Ripple partners with bank" being filtered out despite XRP tracked
- **Severity classifier**: Added 20+ missing project names (ripple, dogecoin, avalanche, polkadot,
  chainlink, litecoin, etc.) — synced with data_cleaner keywords
- **Dedup manager**: `_ENTITY_SYNONYMS` now derived from shared `coin_mapping` instead of isolated dict
- **L2 validation**: Coin count now uses `extract_coins_from_text()` — "Ethereum" counts as ETH
- **CryptoPanic**: `currencies` field from API now stored in `coin_symbol` column (was: discarded)

### Tests
- 751 tests pass (+70 from v0.27.0)
- New `test_coin_mapping.py`: 13 tests for normalize/extract/consistency
- New breaking pipeline tests: project name extraction (Ripple→XRP, Cardano→ADA)
- New severity classifier tests: 6 project name recognition tests
- New CryptoPanic tests: currencies field storage
- Updated test assertions for filler removal behavior change
- Updated test for prompt format change (Tóm lược removal)

## [0.27.0] - 2026-03-20

### P2-A: CIC Market Insight Research Article (BIC Group L1)

New feature: generates a >2500-word deep analysis research article for BIC Group L1 paid members.
Series name: "CIC Market Insight — Ngày DD/MM/YYYY"

#### New Files
- **`collectors/research_data.py`**: Research-specific data collector with 5 free sources:
  - BGeometrics: MVRV Z-Score, NUPL, SOPR, Puell Multiple (15 req/day, no key)
  - btcetffundflow.com: Spot Bitcoin ETF daily flows for 13 ETFs (scraping __NEXT_DATA__)
  - DefiLlama Stablecoins: USDT/USDC supply + 1d/7d/30d flow changes (no key)
  - Blockchain.com: Miner Revenue, Difficulty, Hash Rate (no key)
  - Binance Spot: Pi Cycle Top indicator (calculated from 111SMA & 350SMA×2)
- **`generators/research_generator.py`**: Research article generator with:
  - 8-section article structure (Overview, Alerts, On-chain, Stablecoin/ETF, Derivatives, Macro, Summary Table, Conclusion)
  - Research-grade NQ05-compliant system prompt
  - 8192 max tokens for >2500 word output
  - NQ05 compliance: prompt-level + pipeline Stage 3 post-filter (consistent with tier articles)

#### Pipeline Integration (daily_pipeline.py)
- Stage 1: `collect_research_data()` added to parallel data collection
- Stage 2: `generate_research_article()` runs after BIC Chat summary
- Stage 3: Research article passes through NQ05 post-filter (same as tier articles)
- Stage 4: Delivered as tier="Research" alongside existing articles

#### Data Stack (all verified free, no credit card required)
| Source | Data | API Calls/Day |
|--------|------|---------------|
| BGeometrics | MVRV-Z, NUPL, SOPR, Puell | 4 |
| btcetffundflow.com | ETF flows (13 ETFs) | 1 |
| DefiLlama | Stablecoin supply/flow | 1 |
| Blockchain.com | Miner Revenue, Difficulty | 1 |
| Binance Spot | Pi Cycle (calculated) | 1 |
| + Existing pipeline | Market, On-chain, Derivatives, Sector, News | ~30 |

#### Tests
- `tests/test_collectors/test_research_data.py`: 15 tests covering all 5 data sources + format + edge cases
- `tests/test_generators/test_research_generator.py`: 11 tests covering context, prompt, NQ05, generation + quality gate

#### Review Fixes (post-implementation QA)
- **Quality gate**: `generate_research_article()` returns `None` when content <800 words (pipeline skips gracefully); warns when <1500 words
- **NQ05 single-layer**: Removed duplicate `check_and_fix()` from generator — NQ05 post-filter now only in pipeline Stage 3 (consistent with tier articles)
- **Stablecoin data consistency**: `circulating.peggedUSD` used as single source of truth for market cap (not mixing with `chainCirculating`)
- **ETF 5-day trend**: Added `recent_total_flows` to `ETFFlowData` — LLM receives 5-day flow trend for analysis, not just latest day
- **Section 7 rewrite**: Changed from "So sánh hôm nay vs hôm qua" (requires yesterday's data) to "Bảng tổng hợp chỉ số chính" (summary table)
- **Removed bond yield**: Prompt no longer requires US Bond 10Y/2Y yield data (no source available)
- **Missing data handling**: Added "XỬ LÝ THIẾU DỮ LIỆU" instructions to prompt — LLM skips sections without data instead of fabricating
- **Stablecoin zero change**: Fixed Python falsy bug — `change_1d=0.0` now formats as "+0" instead of showing "N/A"
- **Sheets truncation**: Increased content limit from 8,000 to 45,000 chars (research articles ~12-15K chars, Sheets cell limit 50K)
- **Run log tracking**: `_execute_stages()` returns research word count; NHAT_KY_PIPELINE notes field shows `research: Nw` for traceability
- **Source hyperlinks (PA E)**: Breaking news `🔗 <a href="url">Nguồn: Source ↗</a>` — full clickable hyperlink in Telegram, replacing plain-text URL
- **Deferred event fallback**: Reuses `_raw_data_fallback()` with HTML hyperlinks instead of separate plain-text template

## [0.26.0] - 2026-03-20

### Content Quality — Investor-Focused Insight Upgrade (Phase 1)

#### 1. Tier Context Rewrite (daily_pipeline.py)
- All 5 tier_context prompts rewritten with **investor persona** matching CIC member profiles:
  - L1: Beginner investor (BTC/ETH, 10-30M VND, ADCA strategy)
  - L2: Bluechip diversifier (19 coins, 30-60M VND, sector allocation)
  - L3: Experienced mid-cap investor (50+ coins, 60-150M VND, causal analysis)
  - L4: DeFi/infrastructure specialist (100+ coins, 150-300M VND, risk assessment)
  - L5: Master investor (full portfolio, >300M VND, strategic + seasonal cycle)
- Each tier now asks questions relevant to **long-term investors**, not traders
- Example prompts updated to demonstrate insight-driven analysis

#### 2. NQ05 System Prompt Upgrade (article_generator.py)
- Added CIC community context (ADCA strategy, 4-season cycle, busy investors)
- **Mandatory insight requirements**: each article MUST contain:
  - 1+ causal link between 2+ indicators
  - 1+ anomaly or contradiction from data
  - 0 sentences that merely restate numbers without interpretation
- Added 2 more banned filler phrases commonly seen in output
- Analysis process now includes explicit "find contradictions" step

#### 3. Metrics Engine Enhancement (metrics_engine.py)
- `_analyze_cross_signals()`: New **specific contradiction detection**:
  - Retail vs Pro: F&G extreme + Funding Rate opposite direction
  - Macro vs Sentiment: DXY direction vs F&G direction conflict
  - Price vs Volume: divergence detection (bull trap warning)
- Each contradiction includes **interpretation + risk implication**
- `format_for_tier()`: Tier-specific framing enhanced:
  - L1-L2: Added investor-relevant context for accumulation guidance
  - L3: Now receives cross-signal contradictions (not just L4)
  - L4: Risk framing specific to DeFi/infrastructure portfolios
  - L5: Added **seasonal cycle context** (Winter/Spring/Summer/Fall)

#### 4. Breaking News Filter (breaking_pipeline.py)
- `_filter_non_cic_coins()`: Added parenthetical coin detection `(SYMBOL)`
- Added macro-event keyword whitelist (regulation/legal events always kept)
- Untracked coins with macro keywords → kept; pure altcoin pumps → filtered

#### 5. Tier-Specific Temperature (article_generator.py)
- L1-L2: 0.3 (factual, concise)
- L3-L4: 0.4 (allows more creative causal reasoning)
- L5: 0.45 (strategic synthesis)

#### 6. Enhanced Inter-Tier Context (article_generator.py)
- L5 receives **richer summaries** from L1-L4 with synthesis instructions
- `_summarize_tier_output()`: Extracts 5 key sentences (up from 3) for L5

#### Tests
- 1 test updated for renamed cross-signal conflict header
- Total: 655 tests pass. Lint clean.

## [0.25.0] - 2026-03-19

### Breaking Pipeline — Deferred Mechanism Fix (8 bugs, 3 clusters)

#### Cluster A — Message Length (Bugs 1, 5, 9)
- `_deliver_breaking()`: Per-event try/except + `split_message()` for TG 4096 char safety.
  One oversized/failed message no longer kills delivery for remaining events.
- `_reprocess_deferred_events()`: Same split_message() treatment for morning alerts.

#### Cluster B — Dedup Persistence (Bugs 2, 8)
- `DedupManager.__init__()`: Dedup entries by hash on load — keeps entry with most-progressed
  status (sent > deferred > pending). Eliminates duplicate rows from BREAKING_LOG.
- `_persist_dedup_to_sheets()`: Append-only fallback now only appends NEW entries (not all rows),
  preventing duplicate row creation when clear_and_rewrite fails.

#### Cluster C — Deferred Mechanism (Bugs 3, 4, 6, 7)
- **C1**: Morning reprocessing rewritten — calls LLM to generate full Breaking News content
  (Approach B), sends each event individually with proper format instead of plain text links.
- **C2**: Removed `deferred_to_daily` (never consumed). Notable events during night → `skipped`.
- **C3**: Content generation failure → `generation_failed` status (not stuck as "pending").
  Morning reprocessing retries failed events once; second failure → `permanently_failed`.
- **C4**: Severity now persisted in dedup entry when classifier runs, enabling proper sort
  and display in morning alerts.

#### Tests
- 7 new tests (dedup on load, severity update, generation_failed retrieval, notable night skipped).
- Total: 655 tests pass. Lint clean.

## [0.24.0] - 2026-03-18

### Data Source Expansion + Summary Generator Rewrite

#### New Collectors
- **Coinalyze** (`collectors/coinalyze_data.py`): Derivatives data via Coinalyze API (OI, Funding
  Rate, Liquidations, Long/Short Ratio) for BTC + ETH. Uses Binance USDT perpetuals (most liquid).
  No geo-blocking from GitHub Actions. 40 req/min. Fallback: OKX → Binance → Bybit.
- **CoinMetrics Community** (`collectors/coinmetrics_data.py`): On-chain fundamentals (NVT, MVRV,
  Active Addresses, Hash Rate) for BTC + ETH. Replaces Glassnode (limited free tier).
  No API key needed. Community tier only (SOPR, Exchange flows are PRO-only). Fallback: Glassnode.
- **Whale Alert** (`collectors/whale_alert.py`): Large transaction tracker (≥$1M) across 20+
  blockchains. New data type — aggregates whale flow direction (exchange in/out), generates
  signal interpretation for LLM context. Paid plans only ($29.95/mo min) — optional,
  pipeline works without key (returns empty summary).

#### Pipeline Integration
- `onchain_data.py`: New fallback chains — Coinalyze → OKX → Binance → Bybit (derivatives),
  CoinMetrics → Glassnode (on-chain).
- `daily_pipeline.py`: Whale Alert added as 8th parallel collector in Stage 1.
  Whale data passed to tier articles (L3+) and summary generator.
- `article_generator.py`: GenerationContext gains `whale_data` field. Tier articles (L3-L5)
  include whale activity in LLM prompt.

#### Summary Generator Rewrite
- **Complete rewrite** of `summary_generator.py` — from 94-line bullet-point generator to
  comprehensive 4-section market overview matching BIC Chat manual format:
  - Section 1: ⭐ Tổng quan (causal analysis paragraphs)
  - Section 2: 📊 Bảng chỉ số (metrics table with emoji markers)
  - Section 3: 👉🏻 Đáng chú ý (VN news + upcoming macro events)
  - Section 4: 📰 Tin tức nổi bật (5-8 articles with analysis)
- Input: Receives full raw data (cleaned_news, market_data, onchain_data, sector_snapshot,
  econ_calendar, metrics_interp, narratives, whale_data) — not just article excerpts.
- Temperature reduced to 0.3 (data-driven), max_tokens increased to 4096.
- Backward-compatible signature (old callers still work).

#### Bug Fixes (post-research API verification)
- **Coinalyze**: Symbol `.6` (non-existent) → `BTCUSDT_PERP.A` (Binance, confirmed).
  Liquidation endpoint response parsing fixed (`history[].l/s` instead of `longLiquidations`).
  Long/Short Ratio endpoint corrected to `/long-short-ratio-history` (no snapshot endpoint).
  Interval `24h` → `daily`.
- **CoinMetrics**: Removed PRO-only metrics (SOPR, Exchange Inflow/Outflow).
  Fixed metric ID `SplyAct1d` → `AdrActCnt`.
- **Whale Alert**: Free plan ~1h lookback (was incorrectly set to 24h).
  Removed `currency` comma-join (API accepts single value only, filter client-side instead).
- **article_generator.py**: `whale_data` was missing from `variables` dict — whale data
  collected but never reached LLM prompts for tier articles. Fixed.
  Also fixed prompt formatting: whale section now uses proper `=== WHALE ALERT ===` header.

#### Tests
- 55 new tests across 6 files (coinalyze, coinmetrics, whale_alert, summary_generator,
  onchain_data, filter_data). Test patterns: graceful degradation, fallback chains,
  data aggregation, prompt structure, whale_data tier filtering, edge cases.
- Total: 648 tests pass. Lint clean.

#### Environment Variables (new)
- `COINALYZE_API_KEY` — free key from coinalyze.net (required for derivatives)
- `WHALE_ALERT_API_KEY` — paid key from whale-alert.io (optional, $29.95/mo min)
- CoinMetrics Community: no key needed

## [0.23.0] - 2026-03-18

### Pipeline Quality Overhaul (25 root causes, 5 phases)

#### Phase 1 — Quick Wins (D1, E1, E2)
- **D1**: Replace hardcoded numbers in L3/L4/L5 tier_context with placeholder templates
  forcing LLM to use real data instead of echoing stale examples.
- **E1**: Filler phrase detection — 7 regex patterns counted (not removed) by NQ05 filter,
  exposed via `filler_count` field for quality gate.
- **E2**: LLM temperature reduced 0.5→0.3 (both daily + breaking) to reduce hallucination.

#### Phase 2 — Breaking News Context Enrichment (A1-A4)
- **A1**: Trafilatura article body extraction (8s timeout, 1500 char cap) for breaking news.
- **A2**: Market snapshot context injected into breaking prompt (BTC price/change, F&G).
- **A3**: Recent events context (last 3 breaking alerts) injected for continuity.
- **A4**: Rewritten breaking prompt template with "Nội dung cốt lõi" + "Bối cảnh & tác động".

#### Phase 3 — Breaking News Classification & Dedup (B1-B4, F4)
- **B1**: Price vs volume percentage distinction in severity classifier — volume % no longer
  inflates severity (e.g., "volume up 50%" stays "normal", not "critical").
- **B2**: Coin whitelist filter — non-CIC coins filtered out of breaking news.
- **B4**: Added "crash" to DEFAULT_IMPORTANT_KEYWORDS.
- **F4**: Similarity-based dedup (SequenceMatcher ≥0.70) catches near-duplicate headlines
  with different wording within cooldown window.

#### Phase 4 — Daily Pipeline Data Quality (F1-F7)
- **F1**: Full article text passed to LLM (800 char cap) instead of 300-char summary.
- **F2**: Top 5 RSS feeds marked `enrich=True` for trafilatura enrichment.
- **F3**: 4 new RSS feeds added (CryptoNews, Bitcoinist, CryptoPotato, BlogTienAo).
- **F5**: Macro article whitelist — Fed/CPI/DXY/interest rate articles bypass crypto filter.
- **F6**: Data quality gate — pipeline aborts if <5 news AND no market data.
- **F7**: Telegram truncation warning logged when message content is split.

#### Phase 5 — Daily Report Anti-Repetition (C1-C3, E5)
- **C1**: Rewritten `_summarize_tier_output()` with structured extraction (coins, numbers,
  key sentences) for inter-tier context passing.
- **C2**: Tier-specific analytical framing in metrics engine — L3 gets "NGUYÊN NHÂN" (causal),
  L4 gets "RỦI RO" (risk/contradictions), L5 gets "KỊCH BẢN" (scenarios).
- **C3**: Cross-tier 4-gram repetition detection — warns when same phrases appear in 3+ tiers.
- **E5**: NQ05 phrase removal — removes only violating phrase (not entire sentence) for prose;
  entire bullet removed for bullet points.

### Test Coverage
- 600 tests (up from 571), all passing
- New test classes: TestFillerDetection, TestPhase5PhraseRemoval, TestPhase2ArticleEnrichment,
  TestPhase2Helpers, TestPhase3CoinFilter, TestSimilarityDedup, TestPhase3Classification,
  TestPhase4FeedEnhancements, TestCrossTierRepetition, plus updated inter-tier and metrics tests

## [0.22.0] - 2026-03-17

### Prompt Architecture Overhaul

- **Fix Gemini API**: Use `system_instruction` parameter instead of concatenating
  system+user prompt. Gemini now processes NQ05 rules with higher priority.
- **Rewrite system prompt**: Role (analyst + investor perspective), 4-step process
  (summarize→find patterns→interpret→present), filler phrase blacklist.
- **Question-driven tier prompts**: Each tier has 3-4 specific questions to answer
  instead of open-ended "write analysis". Includes few-shot example paragraphs.
- **Reduce L5 data**: Cap news at top 20 lines to prevent Groq 413 Payload Too Large.
- **Prompt restructured**: "Context first, questions last" following Gemini best practices.

### Bug Fixes

- **DefiLlama None comparison**: Guard against `tvl=None` from API causing TypeError.
- **Derivatives fallback reorder**: OKX first (only provider working on GitHub Actions),
  removed Binance Spot (also 451 geo-blocked). Binance Futures + Bybit kept as fallbacks.
- **Sector data None guards**: All format_for_llm() comparisons now handle None values.

## [0.21.0] - 2026-03-16

### Phase 1 — Data Architecture Overhaul (Metrics Engine + Inter-Tier Context)

**Root cause (3rd time)**: Previous fixes (v0.13 data enrichment, v0.19 anti-hallucination,
v0.20 tier context redesign) were all prompt engineering — addressing symptoms, not architecture.
All 5 tiers received IDENTICAL data, no inter-tier awareness, and missing pre-computed insights
caused AI to guess/repeat instead of analyze.

**1a. Metrics Engine (NEW: generators/metrics_engine.py):**
- Pre-computed data interpretation replaces LLM guessing
- Funding Rate, OI, Long/Short Ratio → structured conclusions with reasoning
- DXY, Gold, BTC Dominance → macro analysis with cause-effect
- Fear & Greed, Altcoin Season → labeled sentiment with historical context
- Cross-signal analysis: detects agreement vs conflict between indicators
- Volume pattern analysis: top coins + divergence detection
- Tier-specific output: L1-L2 get sentiment only, L3-L5 get derivatives + macro + cross-signals

**1b. Market Regime Classification (in metrics_engine.py):**
- Scoring system classifies: Bull / Bear / Recovery / Distribution / Neutral
- Inputs: BTC price action, F&G, Altcoin Season, DXY, Funding Rate
- Confidence levels: high/medium/low based on signal agreement
- Vietnamese-formatted output included in every tier's prompt

**1c. Inter-Tier Context Passing (article_generator.py):**
- After generating each tier, section headers + first lines are summarized
- Summary passed to next tier as "CÁC TIER TRƯỚC ĐÃ VIẾT" context
- L2 knows what L1 covered, L3 knows L1+L2, etc.
- Eliminates content repetition at the architectural level (not just prompt hints)

**1d. Narrative Detection (in metrics_engine.py):**
- Keyword clustering from RSS news titles (15 narrative categories)
- Categories: ETF, Regulation, DeFi, AI, Exchange, Hack, Stablecoin, L2, etc.
- Top narratives with sample headlines passed to LLM as "CHỦ ĐỀ NÓNG HÔM NAY"
- AI can now write about dominant themes instead of random news

**Pipeline integration (daily_pipeline.py):**
- Removed 80+ lines of scattered interpretation_notes code
- Replaced with 3-line Metrics Engine call: interpret + narratives + format
- GenerationContext extended with metrics_interpretation + narratives_text fields
- Backward compatible: old interpretation_notes field kept as empty fallback

**Phase 2 — Data Source Expansion:**

**2a. Sector Data Collector (NEW: collectors/sector_data.py):**
- CoinGecko `/categories` endpoint — 12 tracked sectors (DeFi, L1, L2, AI, Gaming, Meme, RWA, etc.)
- Market cap + 24h change + volume + top 3 coins per sector
- Formatted as "PHÂN TÍCH THEO SECTOR" context for LLM

**2b. DefiLlama TVL (in sector_data.py):**
- Total DeFi TVL from historical endpoint
- Top 15 protocols by TVL with chain, category, 1d change
- Free API, no key required, no rate limit

**2c. Binance Spot Fallback (onchain_data.py):**
- Added `_derivatives_binance_spot()` using `api.binance.com` (not geo-blocked)
- Provides BTC spot volume, price change as derivatives proxy
- Attempts Binance Coin-M funding rate (alternative endpoint)
- Fallback chain now: Binance Futures → Binance Spot → Bybit → OKX

**Pipeline integration:**
- `collect_sector_data()` added to parallel Stage 1 collection
- `SectorSnapshot.format_for_llm()` passed to each tier via `sector_data` field
- GenerationContext extended with `sector_data: str` field
- L2-L5 now have real sector data for analysis (previously empty)

**Phase 3 — Prompt Optimization (leveraging new data architecture):**

**3a. Tier-Specific Data Filtering (article_generator.py):**
- `_filter_data_for_tier()` reduces noise for lower tiers
- L1: BTC/ETH prices + F&G + top 5 news only (no on-chain, sector, macro events)
- L2: Full market + sector + news (no on-chain details)
- L3: Full analytical data, reduced news (already in L1/L2)
- L4: On-chain + sector + macro focus, minimal news
- L5: Everything (scenario analysis needs full context)

**3b. Data Quality Monitor (NEW: generators/data_quality.py):**
- `assess_data_quality()` scores data completeness 0-100 (A/B/C/D/F)
- Scoring: News 25pts, Market 25pts, On-chain 20pts, Sector 15pts, Econ 15pts
- Vietnamese warnings passed to LLM when data is degraded
- `is_degraded` flag (score < 40) for pipeline-level decisions
- Integrated into daily_pipeline.py with logging

**3c. Tier Prompt Refinement (daily_pipeline.py):**
- L1: Uses Market Regime from Metrics Engine (no more LLM guessing bullish/bearish)
- L2: References CoinGecko/DefiLlama sector data for grouping coins
- L3: Delegates derivatives interpretation to Metrics Engine (removed inline guide)
- L4: Uses cross-signal analysis for risk detection, sector risk from DefiLlama
- L5: Uses sector rotation data + regime confidence for scenario analysis
- Trimmed redundant "KIẾN THỨC NỀN" block in prompt (Metrics Engine handles this)

**Tests: 80 new tests total (562 total, 100% pass)**
- TestMarketRegime: 9 tests (bull, bear, neutral, recovery, distribution, edge cases)
- TestInterpretMetrics: 11 tests (tier formatting, derivatives, cross-signals)
- TestNarrativeDetection: 9 tests (detection, filtering, formatting)
- TestSummarizeTierOutput: 5 tests (header extraction, fallback, truncation)
- TestSectorSnapshot: 3 tests (formatting with/without data)
- TestCoinGeckoCategories: 4 tests (parsing, HTTP error, network error, sorting)
- TestDefiLlama: 2 tests (TVL + protocols, failure handling)
- TestCollectSectorData: 2 tests (integration, partial failure)
- TestDataQualityReport: 5 tests (grades, formatting, threshold boundaries)
- TestAssessDataQuality: 10 tests (perfect score, no data, partial, boundaries)
- TestFilterDataL1-L5: 20 tests (per-tier data filtering)
- TestFilterDataEdgeCases: 2 tests (empty context, metrics table preservation)

## [0.20.0] - 2026-03-15

### Phase 1 — Prompt Redesign & Output Quality (ICS Anti-Repetition)

**Root cause**: All 5 tiers received same data with nearly identical prompts, causing massive
content repetition visible to higher-tier members who see all lower-tier content via ICS structure.

**1A. Tier Context Redesign (daily_pipeline.py):**
- Each tier now answers a DIFFERENT question:
  L1="Hôm nay thế nào?", L2="Coins nào?", L3="Tại sao?", L4="Rủi ro?", L5="Nếu X thì sao?"
- Each tier explicitly states "MEMBER ĐÃ ĐỌC tier thấp hơn — KHÔNG lặp lại"
- Different tone per tier: L1=casual, L2=professional, L3=analytical, L4=risk-focused, L5=formal
- L2 must mention ≥10/19 coins with sector grouping
- L3-L5 have explicit "KHÔNG LÀM" lists to prevent content overlap
- Each tier has specific "NỘI DUNG BẮT BUỘC" checklist

**1B. Prompt Engineering (article_generator.py):**
- Removed bad example "vùng tích lũy trước đợt tăng mới" (NQ05 borderline prediction)
- Added domain knowledge block: Funding Rate, OI, F&G, BTC Dominance, DXY interpretation
- Added negative examples with ⚠️ SAI markers (wrong FR/OI interpretation, NQ05 violations)
- Added anti-fabrication examples (MVRV, correlation coefficient, smart money)
- URLs now passed in news_text for LLM to reference actual source links

**1C. NQ05 Filter Overhaul (nq05_filter.py):**
- Banned keywords now remove ENTIRE SENTENCE (was: replace with "[đã biên tập]" leaving broken text)
- New `_remove_sentences_with_pattern()` handles both prose and bullet points
- Added 5 semantic NQ05 patterns: "vùng tích lũy trước đợt tăng", "cơ hội tốt để tích lũy",
  "smart money đang mua", "thời điểm tốt để mua", "nên cân nhắc mua"
- Removed auto-append disclaimer (was causing double disclaimer with article_generator)

**1D. Summary Generator Fix (summary_generator.py):**
- Added `check_and_fix()` NQ05 filter call before appending disclaimer (was skipped entirely)

**1E. Breaking News Improvements (content_generator.py):**
- Prompt now receives event URL + summary from raw_data (was: title only → filler content)
- Clarified NQ05 allows naming specific assets (BTC, ETH, SOL...)
- Structured output now includes 🔗 source link

**1F. Post-Generation Validation (article_generator.py):**
- New `_validate_output()` scans LLM output for fabricated metrics
  (MVRV, SOPR, Exchange Reserves, whale data, liquidation data, correlation coefficients)
- L2 coin count check: warns if <5 coins mentioned (target: ≥10)
- Banned source citation check (Bloomberg, CryptoQuant, TradingView, etc.)
- All warnings logged for pipeline monitoring

**1G. Pipeline Stability Fixes (post-deploy):**
- `_TIER_COOLDOWN` 45→60s, `_TIER_RETRY_WAIT` 60→120s — Groq free tier TPM limit
  caused L3-L5 rate limit failures with insufficient cooldown
- Fixed NQ05 violation in interpretation note: "giai đoạn tích lũy trước breakout"
  → "volume thấp thường đi kèm biến động mạnh sau đó (hướng chưa rõ)"
- On-chain prompt header: removed "Glassnode, Binance Futures, Bybit" (geo-blocked/unavailable),
  now shows only "OKX, FRED" to prevent LLM citing unavailable sources
- Disabled 7 dead RSS feeds (BeInCrypto_VN 403, CCN 403, DLNews 404, Reuters DNS fail,
  Bankless 403, CoinMetrics 403, Galaxy_Digital 404) — `enabled=False` for easy re-enable
- `sheets_client.read_all()`: filters out empty-key dict entries from corrupt sheet headers
- `sheets_client.clear_and_rewrite()`: auto-repairs header row against schema definition
  (fixes BREAKING_LOG duplicate empty columns causing context load failure)

## [0.19.0] - 2026-03-15

### Anti-Hallucination & Output Quality

**Fix 1 — Anti-Hallucination (article_generator.py):**
- Removed "Theo CoinLore/Glassnode" example from NQ05_SYSTEM_PROMPT that was INSTRUCTING LLM to cite fabricated sources
- Added "CHỐNG BỊA DỮ LIỆU" rule: LLM can only cite sources from provided data
- Added "QUY TẮC DỮ LIỆU TUYỆT ĐỐI" block in article prompt with source whitelist/blocklist
- Added "KIỂM TRA CUỐI CÙNG" guardrail: whitelist of allowed sources at end of prompt
- Glassnode + Messari moved to ALLOWED list (they ARE real data sources in onchain_data.py + rss_collector.py)
- On-chain source label updated: "Glassnode, Binance Futures, Bybit, OKX, FRED"
- L2 tier_context: removed "support/resistance" instruction that invited LLM to fabricate price levels

**Fix 2 — Data Cleaning Before LLM (daily_pipeline.py, economic_calendar.py):**
- New `_format_onchain_value()`: Funding Rate → percentage format (e.g. -0.0056% instead of -5.55e-05), large numbers → B/M suffixes, ratios → 4 decimal places
- Key metrics Funding Rate now shows percentage format
- Economic events `recent_events`: label changed to "ĐÃ DIỄN RA" with "ĐÃ QUA" tag — prevents LLM from writing past events as "sắp tới"
- Added Funding Rate + OI correlation hints in interpretation notes (OI uses `_format_onchain_value()` instead of hardcoded "B USD")
- Economic events prompt instruction: explicit "KHÔNG viết sự kiện đã qua như 'sắp tới'"

**Fix 3 — Severity Classifier (severity_classifier.py):**
- Added 16 new important keywords: drops, falls, plunges, surges, soars, selloff, rally, war, attack, missile, sanctions, Iran, escalation, invasion, liquidated, sell-off
- Added price-movement percentage detection: X% in title where X≥3 → important, X≥10 → critical
- Word-boundary matching (`\b`) for ALL keywords — fixes "ban" matching inside "Binance" (false CRITICAL)

**Fix 4 — Breaking News Format (breaking_pipeline.py, content_generator.py, dedup_manager.py):**
- Breaking prompt rewritten: 300-400 → 100-150 words (critical: 200-250), no hedge language, structured as "Chuyện gì xảy ra" + "Tại sao quan trọng"
- AI-generated breaking content now includes NQ05 DISCLAIMER (was only on raw fallback)
- DedupEntry: added `url` field (8-column schema) — deferred events now retain URL
- BREAKING_LOG schema in sheets_client.py: 7 → 8 columns (added URL header)
- `_load_dedup_from_sheets()`: now reads URL column from sheet
- Fixed double dedup load: single `dedup_mgr` shared across pipeline stages (was loading twice, second overwriting first)
- Removed dead `url=` kwarg from content_generator `.format()` call
- Deferred morning alert: sorted by severity, includes severity emoji + URL link

**Fix 5 — Crypto Relevance Filter (data_cleaner.py):**
- New `_filter_non_crypto()` step in cleaning pipeline
- 70+ keywords: 50 crypto + 18 macro/finance (SEC, ETF, Fed, FOMC, CPI, inflation, tariff, DXY, etc.)
- Word-boundary matching for short keywords (≤3 chars) — prevents "sol" matching "solution", "eth" matching "method"
- Crypto-only sources (Coin68, TapChiBitcoin, BeInCrypto) bypass keyword check

**Fix 6 — Breaking → Daily Context Sharing (daily_pipeline.py, article_generator.py):**
- New `_load_recent_breaking_context()`: reads BREAKING_LOG for events within 24h
- New `recent_breaking` field in GenerationContext
- Injected into article prompt: "SỰ KIỆN BREAKING GẦN ĐÂY (24h qua — PHẢI nhắc đến trong bài)"
- Daily report now references breaking news from previous night

**Tests:** 471 passed (+21 new), 0 regressions
- Severity classifier: keyword tests, percentage detection, word-boundary tests (ban vs Binance)
- Data cleaner: non-crypto filter, crypto bypass, macro terms, substring false positive tests
- Article generator: anti-hallucination guardrails, Glassnode in allowed list
- Content generator: AI path DISCLAIMER, word targets
- Daily pipeline: `_format_onchain_value()` for funding rate, ratio, large/small numbers
- Dedup manager: URL field, 8-column row

## [0.18.0] - 2026-03-14

### FR60 — Economic Calendar Integration + Template Upgrade

**Economic Calendar Collector (NEW):**
- New `collectors/economic_calendar.py`: fetches macro-economic events from FairEconomy feed
- Filters High-impact USD events relevant to crypto (Fed, FOMC, CPI, PPI, NFP, GDP, etc.)
- 30+ event titles in `CRYPTO_RELEVANT_EVENTS` set (exact + prefix matching)
- Auto-splits events into today vs upcoming, formats as Vietnamese text for LLM prompt
- Graceful fallback: returns empty CalendarResult on any error (HTTP, JSON, timeout)
- Integrated as 6th parallel collector in `daily_pipeline.py` via `asyncio.gather()`
- New `economic_events` field in `GenerationContext` dataclass

**Template Upgrade (AutoSetup.gs):**
- L1: 2→3 sections (added "Kết luận & Sự kiện sắp tới")
- L2: 2→3 sections (added "Xu hướng & Sự kiện vĩ mô")
- L3: 2→4 sections (On-chain + Vĩ mô & Lịch sự kiện + Derivatives + Tổng hợp)
- L4: 2→4 sections (Sector + Sentiment & Derivatives + Sự kiện vĩ mô + Cảnh báo)
- L5: 2→6 sections (Executive Summary + Macro + On-chain + Sector + Liên thị trường + Risk)
- Each section prompt includes specific economic event analysis instructions
- L4 TIER_MAX_TOKENS: 3072→4096 (supports 4 sections)

**Article Generator:**
- `economic_events` variable injected into LLM prompt with "LỊCH SỰ KIỆN KINH TẾ VĨ MÔ" header
- Economic context only added when events are available (no empty sections)

**Tests:** 440 passed (+14 new), 0 regressions
- 14 new tests: `_is_crypto_relevant()`, `EconomicEvent`, `CalendarResult.format_for_llm()`, `collect_economic_calendar()` (5 scenarios)
- Test fixture: `economic_calendar_sample.json` (10 events)

**Version sync:** config.py, pyproject.toml, Menu.gs, test_config.py → 0.18.0

---

## [0.17.0] - 2026-03-14

### PRD Remediation — 24 findings across 5 clusters (R1→R3→R2→R4→R5)

**R1 — Config & Templates:**
- Improved all 8 template prompts in AutoSetup.gs: dual-layer (TL;DR + detail), source attribution
- Added 2 new sections: L4 "Tín hiệu cảnh báo" + L5 "Phân tích liên thị trường" (8→10 total)
- Fixed L4 NQ05 violation: removed "Nêu tỷ trọng phân bổ %" → replaced with risk analysis
- Added `resetTemplates()` GAS function + menu item for Anh Cường to apply updates
- Updated GAS version to 0.17.0

**R3 — Crash Notification & Stability:**
- Added TG failure notification step to both GitHub Actions workflows (daily + breaking)
- Fixed test mode timing bug: `_send_test_confirmation` now runs AFTER run_log finalized
- Pipeline operator gets Telegram alert when both pipeline attempts fail

**R2 — Validation Layer:**
- Pre-flight validation: checks templates exist for all 5 tiers before generating
- Pre-flight validation: warns when coin lists are empty for a tier
- Early exit when NO templates loaded (prevents silent empty report)
- Post-generation validation: checks all 5 tiers were generated, logs missing tiers
- Post-generation validation: checks FR14 dual-layer (TL;DR marker)

**R4 — Format & Delivery:**
- FR30 copy-paste fix: replaced `<a href>` HTML injection with plain-text source footer
- New `_append_source_references()`: appends "Nguồn tham khảo" section with up to 5 sources
- Content now copy-paste ready for BIC Group (Beincom) — no raw HTML tags
- FR28 deferred event reprocessing: breaking pipeline reprocesses `deferred_to_morning` events

**R5 — Bug Fixes & Sync:**
- CJK character sanitization in NQ05 filter: strips Chinese/Japanese/Korean chars from LLM output
- FR12 conflict detection: passes conflict flag to LLM context with warning marker
- FR43 data retention: `run_cleanup()` now called at end of daily pipeline (was orphaned)
- Version sync: config.py, pyproject.toml, GAS Menu.gs all at 0.17.0

**Tests:** 426 passed, 0 regressions

---

## [0.16.0] - 2026-03-13

### Added — CryptoPanic Fallback: RSS + LLM Scoring + Market Triggers

**LLM Scorer (`breaking/llm_scorer.py`) — NEW:**
- RSS-based breaking event scoring when CryptoPanic unavailable
- Batch LLM prompt: scores up to 20 articles in 1 call (efficiency)
- Keyword pre-filter: matching articles bypass LLM (faster, no quota)
- Time filter: only scores articles published within last 6 hours
- Graceful degradation: LLM failure returns keyword-only matches

**Market Trigger (`breaking/market_trigger.py`) — NEW:**
- Always-on price crash detection (not a fallback, runs every time)
- BTC drop > 7% in 24h → automatic breaking event
- ETH drop > 10% in 24h → automatic breaking event
- Fear & Greed Index < 10 → Extreme Fear breaking event
- Uses existing market data collector (no new API calls)

**Breaking Pipeline Fallback Chain:**
- 3-layer detection: CryptoPanic (primary) → RSS+LLM (fallback) → Market triggers (always-on)
- CryptoPanic failure (quota/error/timeout) triggers automatic RSS fallback
- Market triggers run alongside primary detection (additive, not exclusive)
- All sources merge before dedup — no duplicate alerts
- 50 new tests, 426 total, 0 regression

---

## [0.15.0] - 2026-03-13

### Added — Research Integration + Telegram Formatting + CryptoPanic Quota Fix

**Research Feed Integration (Cụm 1):**
- 4 research feeds: Messari, Glassnode Insights, CoinMetrics, Galaxy Digital
- `source_type` field ("news" vs "research") on FeedConfig + NewsArticle
- `og_image` extraction via trafilatura for research articles
- `full_text` enrichment for research articles (up to 2000 chars)
- `asyncio.Semaphore(25)` limits concurrent HTTP requests
- Data cleaner preserves `og_image` and `source_type` through dedup

**CryptoPanic API Quota Fix (GP1-4):**
- Breaking pipeline: hourly → every 3h, skip UTC 0-5 (750→180 calls/month)
- QuotaManager integrated into both CryptoPanic collectors
- File-based cache (2h TTL) prevents redundant API calls
- New `core/cache.py` module for simple file-based caching

**Delivery Layer Enhancements (Cụm 2):**
- Selective HTML escape: preserves safe `<a href>` hyperlinks
- `send_photo()` method for sending research chart images via Telegram
- Image delivery: up to 3 research images per daily report
- Email backup supports HTML alternative (for hyperlinks)
- Sheets truncation increased from 5000 to 8000 chars

**Hyperlink Injection (Cụm 3):**
- Source URLs collected and injected AFTER NQ05 filter (security-safe)
- First occurrence of each source name wrapped in clickable `<a href>` tag
- `source_urls` and `image_urls` passed through article dict to delivery

---

## [0.14.3] - 2026-03-12

### Changed — F2: CAU_HINH Self-Documenting Email Config

**Operator (no-code user) chỉ cần mở Google Sheet để quản lý email:**
- Tab CAU_HINH được seed sẵn row `email_recipients` khi setup lần đầu
- Cột "Mô tả" hướng dẫn đầy đủ tiếng Việt: THÊM / XÓA / Ví dụ format
- Không cần terminal, không cần tool — edit trực tiếp cell trong Sheet
- `seed_setting()`: append row nếu key chưa có, skip nếu đã có (không overwrite)
- `seed_default_config()`: seed tất cả default rows, idempotent
- `create_schema()` tự gọi `seed_default_config()` khi setup

**Xóa `scripts/manage_email_recipients.py`** — CLI tool không phù hợp no-code user.

**Thêm `scripts/setup_schema.py`** — one-time dev script khi tạo spreadsheet mới.

---

## [0.14.2] - 2026-03-12

### Added — F2 (Tiếp): Email Recipients Management via CAU_HINH

**SheetsClient.upsert_setting():**
- Tìm key trong CAU_HINH → update nếu có, append nếu chưa có
- Cột: `Khóa | Giá trị | Mô tả`

**ConfigLoader.set_email_recipients():**
- Ghi danh sách email vào CAU_HINH (upsert), tự động xóa cache sau khi lưu

**scripts/manage_email_recipients.py:**
- CLI tool để quản lý email backup từ terminal (không cần vào GitHub)
- Commands: `list`, `add <email>`, `remove <email>`, `set <email1,email2,...>`

---

## [0.14.1] - 2026-03-12

### Added — F2: Email Backup với Lý Do Telegram Thất Bại

**Email body giờ bao gồm lý do Telegram fail:**
- `send_daily_report()` nhận param mới `telegram_error: str | None`
- Khi Telegram fail hoàn toàn hoặc partial → lý do + timestamp UTC append vào body
- `delivery_manager.py` tự động capture error và truyền qua

**Email recipients cấu hình được từ Google Sheets (CAU_HINH):**
- `ConfigLoader.get_email_recipients()` đọc key `email_recipients` từ CAU_HINH
- Format: `a@gmail.com, b@gmail.com` (comma-separated, có thể thêm nhiều người)
- Fallback: `SMTP_RECIPIENTS` env var nếu chưa có trong sheet
- `_deliver()` đọc từ sheet mỗi lần chạy — không cần redeploy khi đổi email

---

## [0.14.0] - 2026-03-12

### Added — F1: Derivatives Data Migration (Binance Futures)

**Thay thế Coinglass v2 (deprecated) bằng Binance Futures public API:**
- Binance Futures làm primary source (GitHub Actions servers ở US/EU, không bị chặn)
- Bybit v5 làm first fallback, OKX v5 làm second fallback
- 4 metrics mới: `BTC_Funding_Rate`, `BTC_Open_Interest`, `BTC_Long_Short_Ratio`, `BTC_Taker_Buy_Sell_Ratio`
- Không cần API key — tất cả public endpoints
- Provider-level fallback: nếu Binance fail thì thử Bybit, rồi OKX

### Added — F3: RSS Feed Expansion (+5 sources)

**Thêm 5 nguồn tin mới (từ 12 lên 17 feeds):**
- `BeInCrypto_VN` — vn.beincrypto.com (Vietnamese)
- `CCN` — ccn.com (English crypto news)
- `Blockworks` — blockworks.co (institutional crypto)
- `DLNews` — dlnews.com (DL News)
- `Reuters` — feeds.reuters.com/reuters/businessNews (financial news)
- `Bankless` — banklesshq.substack.com (DeFi/Web3)

---

## [0.13.1] - 2026-03-12

### Fixed — Hotfix Wave E (Cleanup)

**E1: Xóa 3 RSS feed chết**
- `TNCK` (404), `BitcoinMag` (403), `BeInCrypto` (403) bị gọi mỗi ngày nhưng không bao giờ thành công
- DEFAULT_FEEDS: 15 → 12 feeds

**E2: Refactor breaking_pipeline dùng private `sheets._connect()`**
- Thêm public method `SheetsClient.clear_and_rewrite()` thay thế truy cập private
- Fix luôn bug cũ: `batch_append` luôn chạy kể cả khi delete thành công (double-write)
- Thêm 4 test cases cho `clear_and_rewrite()`

### Fixed — Hotfix Wave B (Pipeline Reliability)

**D1: Fix test version mismatch**
- Test assert `VERSION == "0.13.0"` → `"0.13.1"` (CI sẽ fail nếu không sửa)

**D2: ValueError → LLMError trong article_generator**
- `raise ValueError(...)` → `raise LLMError(...)` — đúng chuẩn QĐ3 (CICError hierarchy)

**D3: Xóa dead code escape_markdown_v2()**
- Hàm `escape_markdown_v2()` trong telegram_bot.py không được gọi ở đâu → xóa cùng tests

**D5: Bật SSL verification cho Altcoin Season Index**
- `verify=False` → `verify=True` — sửa lỗ hổng bảo mật HTTPS

**D6: Fix ErrorEntry mutation side effect**
- `_trim_error_history()` sửa trực tiếp input object → dùng `dataclasses.replace()` tạo copy

**D7+D8: Xóa dead code to_row() trong GeneratedArticle + GeneratedSummary**
- Hai hàm `to_row()` không được gọi trong pipeline (pipeline dùng dict trực tiếp) → xóa cùng tests + unused imports

**C1: Tách Concurrency Group + Offset Cron**
- Daily pipeline và Breaking News dùng chung concurrency group → block nhau khi trigger cùng lúc
- Tách thành `daily-pipeline` / `breaking-news` groups, daily cron offset 5 phút (01:05 UTC)

**C3: Pipeline Fail Khi Delivery Gửi 0 Tin**
- `_deliver()` catch exception nhưng không propagate → pipeline báo "success" dù delivery fail
- `_deliver()` giờ return `DeliveryResult`, `_run_pipeline()` check 0-sent → set status "error" + `sys.exit(1)`
- Partial delivery (ví dụ 3/6 sent) vẫn là "partial", không fail pipeline

**C5: Fix pyproject.toml Version**
- Version `0.12.0` không khớp `core/config.py` `0.13.0` → sửa đồng bộ

**H6: Validate Groq Empty Response**
- Groq thiếu validation empty text (Gemini đã có 2 lớp)
- Thêm validation trong `_call_groq()` + safety net trong `generate()` cho TẤT CẢ providers

**M1: HTML Escape cho Telegram Messages**
- `parse_mode="HTML"` nhưng không escape `<`, `>`, `&` → TG parsing error
- Thêm `html.escape()` trong `_send_raw()` — tầng thấp nhất, cover mọi message

## [0.13.0] - 2026-03-11

### Fixed — Data Context Starvation (Root Cause of Generic Output)

**Root cause**: Pipeline collected rich data but compressed it to titles+prices before passing to LLM, causing generic output lacking insight.

**Wave A — Quick Wins (LLM Context Enrichment):**
- Spam articles (`filtered=True`) now excluded from LLM context (was polluting prompt)
- News text enriched with article summaries (300 chars each) instead of titles only
- Market text enriched with volume + market cap alongside price/change
- CryptoPanic `summary` field populated from full_text when API returns empty
- LLM temperature 0.3 → 0.5 for more natural, varied analysis
- BIC Chat summary excerpt 300 → 800 chars for richer source context

**Wave B — Data Enrichment (New Metrics FR10/FR20):**
- Added **ETH Dominance** collection from CoinLore API
- Added **TOTAL3** (altcoin market cap) calculated from dominance percentages
- Added **Altcoin Season Index** from BlockchainCenter API (graceful degradation)
- KEY_METRICS_LABELS expanded 7 → 11 items (ETH Dominance, TOTAL3, Altcoin Season, USDT/VND)
- Key metrics mapping in pipeline: ETH_Dominance, TOTAL3, Altcoin_Season → dashboard
- Anomaly detection flags: Extreme Fear/Greed (≤20/≥80), significant BTC moves (≥5%)
- Gemini `_call_gemini()` now raises `LLMError` on empty candidates/text (was silently returning "")
- Improved on-chain collector logging (Glassnode warnings, Coinglass zero-value alerts)

**Wave C — Tier Differentiation:**
- Per-tier Vietnamese analysis instructions (L1=beginner, L2=technical, L3=on-chain+macro, L4=risk, L5=comprehensive)
- `TIER_MAX_TOKENS` dict: L1=2048, L2=3072, L3=4096, L4=3072, L5=6144 (was fixed 4096)
- `GenerationContext.tier_context` field added to pass tier-specific instructions to LLM
- L4 tier explicitly warns: "TUYỆT ĐỐI KHÔNG đưa ra tỷ lệ phân bổ cụ thể (%) — vi phạm NQ05"

**Wave D — NQ05 Hardening:**
- Added `ALLOCATION_PATTERNS` (3 regex patterns) detecting portfolio allocation percentages
- `check_and_fix()` Step 1b: scans and removes allocation patterns (e.g., "30% cho BTC")
- Per-violation audit trail logging with `logger.warning()`

**Wave E — Infrastructure & Breaking News:**
- gh-pages deploy: replaced git-stash-based approach with proper fetch/checkout (race condition fix)
- Dashboard `_trim_error_history()`: assigns default timestamp for errors without one
- Breaking `_calculate_panic_score()`: clarified docstring (panic score ≠ sentiment score)

### Tests
- Fixed 4 tests broken by Wave A-E changes (Gemini empty candidates, coinlore 4 points, 11 metrics)
- All tests passing: 357+ passed, 0 failed

### Stats
- Version: 0.12.0 → 0.13.0
- Metrics tracked: 7 → 11 (KEY_METRICS_LABELS)
- LLM context: ~5% of collected data → ~60% (summaries, volume, mcap, anomalies)
- NQ05 patterns: keyword-only → keywords + allocation regex + per-tier warnings

## [0.12.0] - 2026-03-09

### Added — GAS Menu & Auto Setup
- **Google Apps Script Menu** (`gas/Menu.gs`): menu "📊 CIC Daily Report" trên Google Sheets
  - ⚙️ Thiết Lập Tự Động — tạo 9 tab + header + định dạng (idempotent)
  - 🔄 Đồng Bộ Cột Thiếu — thêm cột mới mà không xóa dữ liệu
  - 🎨 Định Dạng Lại — sửa format bị lộn xộn
  - 📊 Trạng Thái Hệ Thống + 📏 Đếm Dữ Liệu
  - 🗑️ Dọn Dẹp Dữ Liệu Cũ (>30 ngày)
- **Auto Setup** (`gas/AutoSetup.gs`): 9 tab schema khớp 100% với Python `sheets_client.py`
  - Header: chữ đậm, nền xanh, chữ trắng, đóng băng hàng đầu
  - Number formats: giá, phần trăm, khối lượng tự định dạng
  - Default data: tab CAU_HINH ghi sẵn 9 cấu hình mặc định
  - Xóa "Sheet1" mặc định tự động

### Improved — GitHub Actions
- Thêm bước **Validate required secrets** vào daily-pipeline + breaking-news
  - Kiểm tra 6 secrets bắt buộc trước khi chạy → báo lỗi rõ ràng nếu thiếu
- Bật **uv cache** (`enable-cache: true`) cho tất cả 3 workflows → cài nhanh hơn
- Thêm **timeout-minutes: 10** cho test workflow
- Thêm **SMTP_**** env vars vào daily-pipeline (email backup)
- Test workflow trigger trên cả `main` và `master` branches

### Updated — Documentation
- `docs/SETUP_GUIDE.md`: thêm hướng dẫn cài GAS menu + Base64 encode + đánh dấu CRYPTOPANIC_API_KEY là bắt buộc
- `gas/README.md`: hướng dẫn cài đặt GAS từng bước

## [0.11.0] - 2026-03-09

### Fixed — Comprehensive 13-Item Fix Batch (Đợt 3 final)

**Nhóm A — Data Persistence (CRITICAL):**
- **A1**: News data (RSS + CryptoPanic) now written to `TIN_TUC_THO` Sheet tab
- **A2**: Market data (CoinLore, MEXC, CoinGecko, Fear&Greed) now written to `DU_LIEU_THI_TRUONG`
- **A3**: On-chain data (Coinglass, Glassnode, FRED) now written to `DU_LIEU_ONCHAIN`
- **A4**: Generated articles now written to `NOI_DUNG_DA_TAO` Sheet tab
- **A5**: Breaking pipeline now loads/persists dedup entries from `BREAKING_LOG` Sheet (was in-memory only)
- **A6**: Breaking pipeline now writes run logs to `NHAT_KY_PIPELINE` Sheet

**Nhóm B — Broken/Incomplete Features:**
- **B1**: Email backup now reads `SMTP_RECIPIENTS` env var (was always empty → never sent)
- **B2**: Telegram scraper placeholder kept (decided: defer implementation)
- **B4**: Breaking news cooldown changed from 24h → 4h (user-approved)

**Nhóm C — Code Quality:**
- **C1**: All `.to_row()` methods now have call sites (previously dead code)
- **C2**: Fixed 2 bare `except: pass` → added logging in `data_retention.py` and `cryptopanic_client.py`
- **C3**: Version single source of truth: `__init__.py` imports from `core/config.py`
- **C4**: 18 new integration tests for data persistence, email recipients, cooldown

### Stats
- Tests: 326 → 344 (+18)
- All 9 Sheet tabs now have write paths (was 2/9)
- Lint: 0 errors (ruff)

## [0.10.0] - 2026-03-09

### Fixed — P0 Critical Bugs (Dot 3)
- **CRASH FIX**: `clean_articles()` returns `CleanResult`, not list — was crashing daily pipeline
- **DATA FIX**: `source_name` key mismatch in news dict construction (2 places + news_text builder)
- **SCHEMA FIX**: `NHAT_KY_PIPELINE` row format — now matches 8-column Sheet schema
- **SCHEMA FIX**: `BREAKING_LOG` field order — `to_row()`/`from_row()` reordered to match Sheet columns
- **ASYNC FIX**: Wrapped `SheetsClient` + `EmailBackup` sync calls with `asyncio.to_thread()`
- **WIRING FIX**: Dashboard data write (`_write_dashboard_data()`) now called after delivery
- **DATA FIX**: Telegram messages (results[4]) no longer silently dropped
- **DELIVERY FIX**: Breaking news rate limit delay (1.5s between messages)
- Removed dead dependencies: `python-telegram-bot`, `pyyaml` (TG bot uses raw httpx)

### Added — P2 Features (Dot 3)
- **FR6**: MEXC collector — free API, no key, top 15 USDT pairs (`api.mexc.com/api/v3/ticker/24hr`)
- **FR22**: Cross-verify CoinLore vs MEXC prices — logs warning if deviation >5%
- **FR10b**: USDT/VND rate via CoinGecko (`simple/price?ids=tether&vs_currencies=vnd`)
- **FR20**: BTC Dominance + Total Market Cap via CoinLore `/api/global/`
- **FR54**: Test mode TG confirmation message (pipeline status summary)
- **T10**: Inner timeout (60s) for breaking pipeline detection stage
- **T6**: Coinglass v2 deprecation warning with v4 migration notes
- Key metrics expanded: BTC Dominance, Total MCap, USDT/VND in LLM context
- Test fixtures: `mexc_tickers.json`, `coinlore_global.json`, `coingecko_usdt_vnd.json`
- 7 new test classes (11→ tests in test_market_data.py)

### Documentation
- `docs/API_RESEARCH.md`: Full API audit — MEXC, CoinGecko, CoinLore, Coinglass v2/v4
- Updated CLAUDE.md with new collectors and data sources

## [0.9.0] - 2026-03-09

### Fixed — Comprehensive Audit (Dot 1 + Dot 2)
- **CRITICAL**: Wired `daily_pipeline.py` — was placeholder, now connects all collectors → generators → NQ05 → delivery → run log
- **CRITICAL**: Wired `breaking_pipeline.py` — added `_deliver_breaking()` to actually send alerts via Telegram
- Version alignment: `__init__.py`, `config.py`, `pyproject.toml`, `CLAUDE.md` all → 0.9.0
- SMTP env var mismatch: code now reads `SMTP_HOST` / `SMTP_USER` (matches `.env.example`)
- f-string bug in `delivery_manager.py` `_combine_content()` separator
- Added `yfinance>=0.2` to `pyproject.toml` dependencies
- Added `GLASSNODE_API_KEY` + `COINGLASS_API_KEY` to `.env.example`
- Fixed test assertion for version string (0.1.0 → 0.9.0)

## [0.8.0] - 2026-03-09

### Added — Epic 7: Onboarding & Operational Readiness
- Setup Guide: Vietnamese step-by-step, no-code friendly, 15-20 min setup (FR51-FR52)
- Operations Guide: daily workflow, coin management, config, troubleshooting FAQ (Vietnamese)
- Test mode: pipeline detects workflow_dispatch for lite mode (FR53)
- README: comprehensive project overview, architecture, quick start, dev workflow

## [0.7.0] - 2026-03-09

### Added — Epic 6: Pipeline Health Dashboard
- Dashboard Data Generator: JSON output with last_run, llm_used, tier_delivery, error_history, data_freshness (FR45-FR49)
- GitHub Pages static dashboard: dark theme, responsive, auto-refresh 5min, Vietnamese locale (QĐ7)
- CI Integration: both daily + breaking workflows auto-commit dashboard-data.json to gh-pages branch
- Error history: 7-day retention with merge/trim logic
- 18 new tests (319 total), 80.5% coverage

## [0.6.0] - 2026-03-09

### Added — Epic 5: Breaking News Intelligence
- Event Detector: CryptoPanic API, panic_score thresholds, keyword triggers (FR23)
- Alert Dedup & Cooldown: hash(title+source), BREAKING_LOG, 24h TTL, 7-day cleanup (FR56)
- Breaking Content Generator: reuses LLM adapter + NQ05 filter, 300-500 words, raw data fallback
- Severity Classification: 🔴 Critical / 🟠 Important / 🟡 Notable, configurable keywords
- Night Mode: 23:00-07:00 VN (UTC+7), 🔴 always sends, 🟠 deferred to morning, 🟡 to daily (FR28)
- Breaking Pipeline: detect → dedup → generate → classify → deliver, ≤20min timeout
- GitHub Actions workflow: hourly cron, 25min timeout, manual dispatch
- 94 new tests (301 total), 80% coverage

## [0.5.0] - 2026-03-09

### Added — Epic 4: Content Delivery & Reliability
- Telegram Bot: send 6 messages (5 tiers + summary), smart splitting (QĐ6, 4096 char limit)
- Retry & partial delivery: shared retry_utils, status line per tier, always deliver something (NFR7)
- Error notifications: Vietnamese action suggestions, error grouping, severity levels (🔴/⚠️)
- Email backup: SMTP/Gmail, plain text, health check, daily + breaking formats (FR33b)
- Delivery Manager: TG → retry → email fallback orchestration
- Daily pipeline orchestration: timeout (40 min), partial delivery, run logging (FR58)
- E2E integration test: full flow mock (6 deliverables, NQ05 pass, partial delivery)

## [0.4.0] - 2026-03-09

### Added — Epic 3: AI Content Generation & NQ05 Compliance
- LLM Adapter: Multi-provider fallback chain (Groq → Gemini Flash → Flash Lite) with quota integration
- Template Engine: configurable sections from MAU_BAI_VIET, variable substitution, FR20 Key Metrics Table
- Article Generator: 5 tier articles (L1→L5), dual-layer content (TL;DR + Full Analysis), cumulative coins
- BIC Chat Summary Generator: market overview + key highlights, copy-paste ready for Telegram
- NQ05 Filter: dual-layer compliance (prompt + post-filter), banned keywords, terminology fixes, auto-disclaimer
- Integration test: full pipeline mock test (5 articles + 1 summary, NQ05 pass, fallback scenario)

## [0.3.0] - 2026-03-09

### Added — Epic 2: Data Collection Pipeline
- RSS collector: 15+ feeds, parallel async, bilingual VN+EN
- CryptoPanic client: news + sentiment scores + full-text extraction
- Market data: CoinLore crypto prices, yfinance macro (DXY, Gold, VIX), Fear & Greed
- On-chain data: Glassnode, Coinglass, FRED API (graceful degradation)
- Telegram scraper: placeholder with graceful fallback
- Data dedup: title similarity + URL hash matching
- Spam filter: keyword blacklist (configurable from CAU_HINH)

## [0.2.0] - 2026-03-09

### Added — Epic 1: Foundation
- Core: CICError hierarchy, structured logger, config (IS_PRODUCTION)
- Storage: SheetsClient (9-tab schema, batch ops), ConfigLoader (hot-reload)
- QuotaManager: rate limits, daily limits, 6 pre-configured services
- RetryUtils: exponential backoff (2s→4s→8s)
- Data retention: auto-cleanup by age, size warnings
- Pipeline entry points: daily_pipeline.py, breaking_pipeline.py
- 3 GitHub Actions workflows (test, daily-pipeline, breaking-news)

## [0.1.0] - 2026-03-09

### Added
- Project initialization with pyproject.toml (uv + ruff + pytest)
- Planning docs: PRD, Architecture, Epics & Stories
- Sprint status tracking (sprint-status.yaml)
- CLAUDE.md project context for AI-assisted development
- Directory structure: src/cic_daily_report/ with 8 subpackages
