# CIC-Daily-Report — System State

> Snapshot tai: 2026-05-02
> File nay BAT BUOC doc dau session. Cap nhat moi wave.

## Version
- Current: `2.0.0-alpha.34`
- Latest wave: 0.8.6.1 (chua merge — working tree dirty)
- Next planned: Wave C+ (NQ05 centralize, prompts/*.txt, heterogeneous verifier)

## Pipeline Status
- **Daily**: WARNING DISABLED (anh Cuong disabled 02/05 de fix root cause)
- **Breaking**: WARNING DISABLED
- **Test**: Active

## Active Feature Flags (GitHub Secrets)
| Flag | Default | Purpose |
|------|---------|---------|
| WAVE_0_6_ENABLED | false | RAG + Cerebras judge |
| WAVE_0_6_DATE_BLOCK | false | Block future date hallucination |
| WAVE_0_6_2SOURCE_REQUIRED | false | 2-source verifier |
| WAVE_0_6_KILL_SWITCH | false | Force OFF all Wave 0.6 |

## Known Critical Bugs (chua fix)
- Bug 1: Total Market Cap mismatch ($1.5T L1 vs $2.65T Research) — ROOT: NQ05 disclaimer phan tan
- Bug 9: Coinbase 1 doan — Wave 0.8.6.1 da patch (universal gate)
- Bug 10: Canada self-ref bia — Wave 0.8.6.1 da patch (entity overlap=1)
- Bug 11: Alex Lab 6/6/2026 future date — can bat WAVE_0_6_DATE_BLOCK=true

## Active Sprint (Wave C+)
1. NQ05 disclaimer centralize → LLMAdapter wrapper
2. Tach prompts ra `prompts/*.txt` + linter
3. Heterogeneous verifier (OpenRouter GPT-4o)
4. Update docs (CLAUDE.md, SYSTEM_STATE, prompts/CHANGELOG)

## Tech Debt Log
- Test 94/2/2 unit/integration/e2e ratio (e2e all mocked)
- Coverage 60% line only, NO branch coverage
- 0 Sheets backup, 0 Telegram recall, 0 hotfix runbook
- 6 doc file MISSING (cdr-known-bugs, cdr-wave-history, cdr-nq05-incidents, prompts/CHANGELOG, cdr-operator-guide)

## Quick Commands
- Disable cron: `gh workflow disable daily-pipeline.yml && gh workflow disable breaking-news.yml`
- Re-enable: `gh workflow enable daily-pipeline.yml && gh workflow enable breaking-news.yml`
- Run preflight: `uv run python scripts/preflight_check.py`
- Replay breaking: `uv run python scripts/replay_breaking.py`
