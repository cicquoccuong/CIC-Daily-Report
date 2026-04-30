# Wave 0.6 + 0.7 — Rollout Guide

> **Audience**: Anh Cường (operator) — no-code, copy-paste workflow.
> **Goal**: Flip Wave 0.6 + 0.7 flags ON in production safely, with replay
> validation + phased rollout + 1-click rollback.
> **Scope**: This guide is for production cutover ONLY. Code shipped in
> alpha.26 (Wave 0.7) + alpha.23–25 (Wave 0.6) — flags default OFF.

---

## 1. Overview

### What Wave 0.6 fixes

Wave 0.6 (alpha.20–25) ships 4 anti-hallucination layers for breaking news:

- **0.6.1 — Cerebras Qwen3 fact-checker**: Judge each LLM-generated breaking
  message; reject "needs revision" or "rejected" verdicts before delivery.
- **0.6.2 — RAG historical inject**: Pull 3–5 past similar events from
  BREAKING_LOG and inject into prompt context → reduces "lần cuối vào năm
  2021" style hallucinations.
- **0.6.3 — Date HARD BLOCK + numeric guard**: Strip stale dates ("01/01"
  rendered after Apr) and unverified numeric claims from output.
- **0.6.4 — 2-source verification**: For critical-severity events, require
  ≥2 independent sources before delivery.

### What Wave 0.7 fixes

Wave 0.7 (alpha.26) ships real-time data + coin scope:

- **0.7.1 — Real-time data**: F&G, USDT/VND, hash rate, FOMC date,
  reporter name, USDT supply now pull live or refuse to fabricate.
- **0.7.2 — Coin scope filter**: L2/L3/L4 articles can only mention coins
  in their cumulative tier list (no DOGE in L2 article).

> Wave 0.7 fixes are **always-on** — no feature flag (they're just bug
> fixes / prompt updates). Only Wave 0.6 has flags.

### The 4 flags

| Env var | Controls | Default |
|---|---|---|
| `WAVE_0_6_ENABLED` | RAG inject + Cerebras judge (0.6.1 + 0.6.2) | OFF |
| `WAVE_0_6_DATE_BLOCK` | Stale-date HARD BLOCK + numeric guard (0.6.3) | OFF |
| `WAVE_0_6_2SOURCE_REQUIRED` | 2-source verification for critical (0.6.4) | OFF |
| `WAVE_0_6_KILL_SWITCH` | Master OFF — overrides all 3 above | OFF |

Set via **GitHub repo → Settings → Secrets and variables → Actions →
Repository secrets**.

---

## 2. Pre-flight check (BEFORE rollout)

Run the pre-flight script. It verifies all secrets + smoke-tests every
external service. Exit 0 = ready, exit 1 = fix something first.

```bash
cd CIC-Daily-Report
uv run python scripts/preflight_check.py
# verbose mode for detailed failure breakdown
uv run python scripts/preflight_check.py --verbose
```

Expected output (when ready):

```
=== Wave 0.8 Pre-flight Check ===

  [OK]   Required secrets............... all 8 groups present
  [OK]   Telethon secrets (optional).... all 3 present — TG scraping ENABLED
  [OK]   LLM providers smoke............ 4/4 responding
  [OK]   Sheets read smoke (BREAKING_LOG)... 142 rows readable
  [OK]   Telegram bot smoke (getMe)..... bot @cic_alert_bot
  [OK]   Telethon connection (optional). connected + authorized
  [OK]   RAG index build smoke.......... RagIndex instantiates cleanly

Summary: 7/7 passed, 0 required failed, 0 optional warning(s)
VERDICT: READY — safe to flip flags
```

If any **[FAIL]** appears → fix that first. Common causes:

- Missing secret → add it in GitHub Secrets
- LLM 401 → API key expired → regenerate at provider dashboard
- Sheets 403 → service account lost access to spreadsheet → re-share
- Telegram 401 → bot token revoked → BotFather → /token

---

## 3. Replay validation test (BEFORE flipping flags)

Replay simulates Wave 0.6 ON against historical events from
BREAKING_LOG → measures hallucination reduction without touching live
delivery.

```bash
# Pick a date range with ≥5 historical events (last 7 days is good)
uv run python scripts/replay_breaking.py \
    --from 2026-04-20 --to 2026-04-27 \
    --output reports/replay-wave-0.6.md
```

Open `reports/replay-wave-0.6.md` and verify:

- **Reduction** ≥ 70% (hallucination signals dropped vs baseline)
- **Regressions: 0** (no event got WORSE under Wave 0.6)
- **Errors: 0** (or only network errors, not logic bugs)

If reduction < 70% or any regression → DO NOT FLIP FLAGS. Investigate
the regression rows in the report; report findings to Mary/Winston.

---

## 4. Rollout phases (gradual flag flip)

We flip 1 flag at a time, with 2-day soak in between. This isolates
which sub-feature (if any) causes problems in production.

### Phase 1 — Day 1: enable RAG + judge

Set in GitHub Secrets:

```
WAVE_0_6_ENABLED = 1
```

(Leave `WAVE_0_6_DATE_BLOCK` and `WAVE_0_6_2SOURCE_REQUIRED` unset.)

Wait for next breaking-news pipeline run (every 3h, schedule
`0 6,9,12,15,18,21 * * *`). Watch:

- Telegram: messages still arriving on schedule
- Sheets `NHAT_KY_PIPELINE`: `wave06 | factcheck=P/R/V | rag=I/N | ...`
  log lines appear, no errors
- Sheets `BREAKING_LOG`: deliveries continue, no `delivery_failed`
  spike

If 2 days clean → proceed Phase 2.

### Phase 2 — Day 3: enable date HARD BLOCK + numeric guard

Add:

```
WAVE_0_6_DATE_BLOCK = 1
```

Watch `wave06 | dateblock=N | numguard=N` counters. If date strips
exceed ~10/day or empty body strips appear (`delivery_failed` reason
`date_block_too_many_strip`), pause + investigate.

If 2 days clean → proceed Phase 3.

### Phase 3 — Day 5: enable 2-source verification

Add:

```
WAVE_0_6_2SOURCE_REQUIRED = 1
```

Watch `wave06 | 2src=V/S/C` counters. Most events should land in
`single` (1 source) — that's expected. `verified` count rising = 2+
sources confirmed (good). `conflict` rising = 2 sources disagree —
those events deferred (verify content_generator catches conflicts).

If 2 days clean → proceed Phase 4.

### Phase 4 — Day 7: full activation + 7-day soak

All 3 flags ON. No new flags to flip. Now monitor for 7 consecutive
days with all of:

- < 5% historical-claim hallucination (per replay weekly)
- < 2% NQ05-violation leak (per ad-hoc spot check)
- F&G / USDT/VND / hash rate / FOMC date accuracy ≥ 95% (Mary
  fact-check sample)

If any criterion misses → use rollback procedure (Section 6).

---

## 5. Monitor metrics

After each pipeline run, check the `wave06` summary line:

**Sheets → NHAT_KY_PIPELINE tab → most recent run row → "Notes" column**

Format:

```
wave06 | factcheck=12/0/1 | rag=8/2 | dateblock=3 | numguard=1 | 2src=2/8/0
```

Reading:

- `factcheck=12/0/1` → 12 passed, 0 rejected, 1 needed revision
- `rag=8/2` → 8 events got historical context injected, 2 had no match
- `dateblock=3` → 3 stale-date sentences stripped this run
- `numguard=1` → 1 unverified numeric claim removed
- `2src=2/8/0` → 2 verified by 2+ sources, 8 had only 1 source, 0 conflicts

**Healthy ranges (rough):**

- `factcheck` rejected count ≤ 20% of total
- `rag` no_match ≤ 50% (low corpus = expected early on)
- `dateblock` strips ≤ 5/run
- `2src` conflict count ≤ 10% of total

If any range is consistently exceeded → investigate.

---

## 6. Rollback (if anything goes wrong)

**1-click rollback**: set in GitHub Secrets:

```
WAVE_0_6_KILL_SWITCH = 1
```

This **overrides all 3 sub-flags** instantly — next pipeline run
reverts to pre-Wave-0.6 behavior. No code change, no redeploy.

After rollback:

1. Note the symptom that triggered rollback (Telegram screenshot,
   Sheets row, error log)
2. Run `scripts/replay_breaking.py` covering the failure window
3. Report to Amelia/Winston with replay output for diagnosis
4. Once fixed in code (new alpha) → unset `WAVE_0_6_KILL_SWITCH` and
   restart from Phase 1

---

## 7. Success criteria

Wave 0.6 + 0.7 are considered **successfully deployed** when:

| Metric | Target | Measured by |
|---|---|---|
| Historical-claim hallucination | < 5% | Weekly replay report |
| NQ05 advisory leak | < 2% | Ad-hoc spot check (Mary) |
| F&G / data accuracy | ≥ 95% | Mary fact-check sample (Wave 0.7) |
| Coin-scope leak (L2/L3/L4) | 0 | Winston code audit per article |
| Pipeline uptime | ≥ 99% | GitHub Actions success rate |
| Telegram delivery rate | ≥ 95% of intended | BREAKING_LOG `delivered` count |

7 consecutive days meeting all 6 → flags stay ON permanently.
Less than that → rollback + iterate.

---

## 8. References

- `scripts/preflight_check.py` — pre-flight infrastructure verification
- `scripts/replay_breaking.py` — historical replay validation
- `src/cic_daily_report/breaking/wave06_metrics.py` — metrics definition
- `src/cic_daily_report/core/config.py` — flag implementation
- `CHANGELOG.md` — Wave 0.6.x and 0.7.x detailed change list
