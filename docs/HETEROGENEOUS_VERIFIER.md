# Heterogeneous Verifier — Wave C+ Cross-Check Gate

> **Purpose**: Phá echo chamber Claude monoculture trong cross-check process.
> Gọi 1 model khác family (GPT-4o-mini, Gemini Pro) làm verifier độc lập.

---

## Background

Round 5 root cause analysis (2026-05-01) phát hiện:

> **Cross-check 3 lớp = 1 model nói chuyện với chính mình 3 lần.**
>
> Quinn, Winston, Devil đều là Claude. Cùng base model, cùng RLHF bias, cùng training data. "Independent verification" thực ra là echo chamber có cấu trúc.

**Bằng chứng**: Wave 0.8.6.1 patch của Amelia pass:
- Quinn QA: 2502/2502 tests, coverage 78.3%
- Winston Architecture: APPROVED
- Devil challenge: ACCEPTED

→ GPT-4o-mini gọi qua OpenRouter caught **2 edge case** (sentinel partial detection) trong 30 giây.

## Architecture

```
Amelia code → Quinn QA (Claude) → Winston review (Claude) → Devil challenge (Claude)
                                                                ↓
                                                    Heterogeneous Verifier
                                                    (GPT-4o-mini / Gemini Pro)
                                                                ↓
                                                            Merge gate
```

## Usage

### Manual (dev workflow)

```bash
# Verify a single file
uv run python scripts/heterogeneous_verify.py src/cic_daily_report/adapters/llm_adapter.py

# Verify diff
git diff main...HEAD | uv run python scripts/heterogeneous_verify.py -

# Use a different model
HETEROGENEOUS_VERIFIER_MODEL=google/gemini-2.5-pro \
  uv run python scripts/heterogeneous_verify.py <file>
```

### Required env

```bash
export OPENROUTER_API_KEY=sk-or-v1-...
```

## When to use

**MANDATORY**:
- Wave có P0 fix (Bug 1 macro mismatch class, NQ05 leak)
- Wave touch `adapters/llm_adapter.py`, `generators/nq05_filter.py`, `breaking/content_generator.py`
- Wave thay đổi prompt template

**RECOMMENDED**:
- Mỗi wave có cross-check Quinn + Winston pass

**SKIP**:
- Doc-only changes
- Test-only changes
- Refactor không touch business logic

## Cost

OpenRouter pricing (2026-05):
- `openai/gpt-4o-mini`: ~$0.0001/review (~500 tokens)
- `google/gemini-2.5-pro`: ~$0.001/review

**Budget**: $1/month đủ cho 1000 reviews. Free OpenRouter credits cover initial use.

## Limitations

- Model có thể flag false positive (vd: security concern khi text là LLM output đã trust)
- Operator phải filter finding theo context CDR-specific
- KHÔNG auto-block merge — chỉ là input cho operator decision

## Migration plan

| Phase | When | Action |
|-------|------|--------|
| Phase 1 (now) | Wave C+ | Manual call cho NQ05 helper, prompt changes |
| Phase 2 (1-2 weeks) | Wave 1.0 | Tích hợp vào pre-commit hook (optional, không block) |
| Phase 3 (1 month) | Stable | GitHub Action job — comment finding lên PR |

## Related

- Source: `scripts/heterogeneous_verify.py`
- Root cause analysis: `Wiki/decisions/cdr-root-cause-2026-05-01.md` (TODO)
- Wave C+ summary: `Wiki/decisions/cdr-wave-c-plus.md` (TODO)
