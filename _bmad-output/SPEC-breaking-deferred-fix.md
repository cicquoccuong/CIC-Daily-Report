# SPEC: Breaking Pipeline — Deferred Mechanism Fix (v0.25.0)

## Problem Statement

8 bugs in the breaking pipeline's deferred mechanism cause:
- Deferred news re-sent every 3 hours indefinitely (15 tin loop)
- Duplicate entries in deferred list
- Deferred news sent as plain text links instead of Breaking News format
- Content generation failures silently lose events

## Root Cause Analysis — 3 Clusters

### Cluster A — Message Length (Bug 1, 5, 9)
**Root**: Neither `_deliver_breaking()` nor `_reprocess_deferred_events()` use `split_message()`.
Messages exceeding Telegram's 4096-char limit cause API failure → status never updates → infinite re-send loop.

### Cluster B — Dedup Persistence (Bug 2, 8)
**Root**: `_persist_dedup_to_sheets()` append-only fallback creates duplicate rows.
`DedupManager.__init__()` builds `_hash_map` (deduped by last-wins) but `_entries` list keeps ALL rows including duplicates.
`get_deferred_events()` scans `_entries` → returns duplicates.

### Cluster C — Deferred Mechanism (Bug 3, 4, 6, 7)
**Root**: Deferred events skip content generation entirely (line 226-232).
- Bug 3: No LLM content for deferred events
- Bug 4: `deferred_to_daily` never consumed
- Bug 6: Failed content generation → "pending" forever, no retry
- Bug 7: `DedupEntry.severity` never set from classifier

## Solution Design

### Fix A — Message Splitting (Bugs 1, 5, 9)

**A1. `_deliver_breaking()`** (breaking_pipeline.py:557-591):
- Import and use `split_message()` from telegram_bot
- For each `content` in `result.contents`:
  - Build full message: `f"{emoji} BREAKING NEWS\n\n{content.formatted}"`
  - Call `split_message("BREAKING", message)` → iterate parts → `bot.send_message(part.formatted)`
- Move try/except INSIDE the for loop so one failure doesn't kill remaining events

**A2. `_reprocess_deferred_events()`** (breaking_pipeline.py:400-453):
- After generating content (Fix C1), use `split_message()` for each article
- Separate status update per event (not batch after all sends)

### Fix B — Dedup Persistence (Bugs 2, 8)

**B1. Dedup on load** (dedup_manager.py `__init__`):
- After building `_hash_map`, reconstruct `_entries` from `_hash_map.values()`
- This eliminates duplicate entries with same hash
- Priority: keep entry with most-progressed status: `sent > deferred_to_morning > deferred_to_daily > pending`

**B2. Safer persistence** (breaking_pipeline.py `_persist_dedup_to_sheets`):
- If `clear_and_rewrite` fails, do NOT append all rows (creates duplicates)
- Instead: only append NEW entries (entries_written from this run) via `batch_append`
- Log warning that old entries may be stale

### Fix C — Deferred Mechanism (Bugs 3, 4, 6, 7)

**C1. Morning reprocessing with LLM** (Bug 3 — Approach B):
Rewrite `_reprocess_deferred_events()`:
- Load LLMAdapter
- For each deferred event, reconstruct `BreakingEvent` from `DedupEntry` metadata
- Call `generate_breaking_content(event, llm, severity=entry.severity)`
- Send with full Breaking News format via `split_message()`
- Update status per event (not batch)
- If LLM fails for one event, continue to next (don't abort all)

**C2. Remove `deferred_to_daily`** (Bug 4):
- `deferred_to_daily` was never implemented and adds no value
- Change `_determine_action()`: notable events during night → `"skipped"` instead of `"deferred_to_daily"`
- No consumer needed — simplifies the system

**C3. Retry failed content generation** (Bug 6):
- When `generate_breaking_content()` fails, set status to `"generation_failed"` (not leave as "pending")
- In `_reprocess_deferred_events()`, also pick up `"generation_failed"` events for retry
- Max 1 retry (if fails twice → status `"permanently_failed"`)

**C4. Set severity in dedup entry** (Bug 7):
- In Stage 4 loop (breaking_pipeline.py:225-231), after classifier runs:
  - Add `severity` parameter to `update_entry_status()` OR
  - Directly set `entry.severity = classified_event.severity` on the dedup entry
- Extend `update_entry_status()` to accept optional `severity` parameter

## Files Changed

| File | Changes |
|------|---------|
| `breaking_pipeline.py` | Fix A1, A2, B2, C1, C2, C3 |
| `breaking/dedup_manager.py` | Fix B1, C4 (update_entry_status + __init__ dedup) |
| `breaking/severity_classifier.py` | Fix C2 (deferred_to_daily → skipped) |
| `delivery/telegram_bot.py` | No changes (split_message already exists) |
| `breaking/content_generator.py` | No changes (generate_breaking_content already correct) |

## Test Plan

| Test | Verifies |
|------|----------|
| `test_deliver_breaking_splits_long_message` | Fix A1 — message > 4096 chars split correctly |
| `test_deliver_breaking_one_failure_doesnt_kill_rest` | Fix A1 — per-event try/except |
| `test_dedup_manager_dedup_on_load` | Fix B1 — duplicate entries consolidated |
| `test_dedup_manager_status_priority` | Fix B1 — sent > deferred > pending |
| `test_persist_fallback_no_duplicates` | Fix B2 — append-only doesn't duplicate |
| `test_reprocess_deferred_generates_content` | Fix C1 — LLM called for deferred events |
| `test_reprocess_deferred_splits_long` | Fix A2+C1 — split after LLM generation |
| `test_notable_night_skipped_not_deferred` | Fix C2 — no more deferred_to_daily |
| `test_generation_failed_status` | Fix C3 — failed → "generation_failed" status |
| `test_generation_failed_retry` | Fix C3 — retry on next morning reprocess |
| `test_severity_set_on_dedup_entry` | Fix C4 — severity persisted |
| `test_reprocess_deferred_per_event_status` | Fix C1 — status updated per event, not batch |

## Risks

- **LLM quota**: Morning reprocessing calls LLM per deferred event (up to ~15 events × 1 call). Gemini Flash free tier: 1500 req/day — sufficient.
- **Pipeline duration**: Morning run may take longer (~60s × 15 events = ~15min worst case). Mitigated by 60s timeout per event.
- **Google Sheets**: `clear_and_rewrite` reliability — Fix B2 makes the fallback safer but doesn't fix the root Sheets issue.
