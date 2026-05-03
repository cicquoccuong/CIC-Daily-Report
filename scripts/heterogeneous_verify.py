"""Heterogeneous verifier — independent-model gate for Wave C+ cross-check.

WHY (Wave C+, 2026-05-01): Claude monoculture (Quinn + Winston + Devil are all
Claude variants) creates echo chamber. Round 5 root cause analysis found 22/27
verified bugs, but cross-check missed 2 edge cases (sentinel partial detection)
that GPT-4o-mini caught immediately. This script runs an independent model from
a DIFFERENT family as gate before merge.

WHY rewrite (Wave C+.1, Fix #4+#5):
    - Removed "CLEAN" shortcut from prompt — model could escape via 1-word reply.
      Now FORCE list >=3 concerns (CRITICAL, MAJOR, or MINOR).
    - Auto-inject CLAUDE.md context if present so reviewer understands codebase
      conventions (NQ05, async, gspread.batch_update, etc.).
    - Cost guard: track call count in `.claude/heterogeneous_verify_count.txt`,
      block when --max-cost reached (default 50/session — typical Wave round
      uses 5-15 calls; deep cross-check rounds (Wave C+ root-cause analysis)
      use 30-50 calls; cost-safe ceiling at 50). Operator can override with
      HETEROGENEOUS_VERIFY_RESET=1 or pass --max-cost N to raise.
    - argparse --help, type hints, better error message on missing API key.

USAGE:
    # Verify a file or diff
    uv run python scripts/heterogeneous_verify.py path/to/file.py

    # Multiple files
    uv run python scripts/heterogeneous_verify.py file1.py file2.py

    # Stdin (diff piped in)
    git diff HEAD~1 | uv run python scripts/heterogeneous_verify.py -

    # Override max calls / model
    uv run python scripts/heterogeneous_verify.py --max-cost 200 file.py
    HETEROGENEOUS_VERIFIER_MODEL=anthropic/claude-haiku-4 \\
        uv run python scripts/heterogeneous_verify.py file.py

REQUIREMENTS:
    - OPENROUTER_API_KEY env var set
    - Network access to openrouter.ai

OUTPUT:
    - Stdout: review report from heterogeneous model (Vietnamese)
    - Exit 0: review complete (does NOT auto-block — operator reads + decides)
    - Exit 1: API error, no input, or cost guard tripped
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx

OPENROUTER_URL: str = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL: str = "openai/gpt-4o-mini"  # khác family Claude — cheap + fast
TIMEOUT_SEC: int = 60
DEFAULT_MAX_COST: int = 50  # bumped from 30 — deep cross-check rounds use 30+ calls
COST_FILE: Path = Path(".claude/heterogeneous_verify_count.txt")
MAX_CONTENT_CHARS: int = 30000
CI_OUTPUT_CAP: int = 8000  # WHY (Wave 0.9): cap output for PR comment readability

SYSTEM_PROMPT: str = (
    "You are an independent code reviewer for the CIC-Daily-Report Python project. "
    "You are NOT Claude — you reason independently from a different model family. "
    "Review code with skeptical, adversarial eye. "
    "Reply in Vietnamese. Avoid praise. Focus on REAL problems only.\n\n"
    "BẮT BUỘC: Liệt kê >=3 concerns. Nếu thật sự không tìm được vấn đề critical "
    "hoặc major nào, vẫn phải nêu 3 hypothesis về risk tiềm năng (cụ thể, không "
    "general).\n\n"
    "Conventions của project (BẮT BUỘC tôn trọng):\n"
    "- NQ05: cấm khuyến nghị buy/sell, dùng 'tài sản mã hóa' không 'tiền điện tử',\n"
    "  disclaimer mandatory ở mọi user-facing content.\n"
    "- Absolute imports only: from cic_daily_report.<pkg> import ...\n"
    "- Async pattern: asyncio + httpx, retry với exponential backoff (2s/4s/8s).\n"
    "- gspread.batch_update() cho mọi Sheet write — never cell-by-cell.\n"
    "- Mock all external APIs trong tests."
)

USER_PROMPT_TEMPLATE: str = (
    "Review code change sau đây. Tìm: bugs, edge cases, security risks, race "
    "conditions, false positive/negative patterns, NQ05 violations, circular "
    "imports, idempotency bugs, type errors. KHÔNG khen — chỉ flag vấn đề.\n\n"
    "{claude_md_context}"
    "```\n{content}\n```\n\n"
    "Output format BẮT BUỘC:\n"
    "1. CRITICAL (block merge): ... (hoặc 'Không có' nếu thật sự sạch)\n"
    "2. MAJOR (fix before merge): ...\n"
    "3. MINOR (defer OK): ...\n\n"
    "BẮT BUỘC list >=3 concerns tổng cộng (CRITICAL + MAJOR + MINOR). "
    "Nếu không tìm được issue thật, phải explicit nói 'KHÔNG TÌM ĐƯỢC ISSUE NÀO' "
    "kèm 3 hypothesis về risk tiềm năng anh chưa đủ context để verify.\n\n"
    "TUYỆT ĐỐI KHÔNG được trả lời chỉ 'CLEAN' hoặc 'OK' — phải có nội dung."
)


def read_input(args: list[str]) -> str:
    """Read code content from files or stdin."""
    if not args or args == ["-"]:
        return sys.stdin.read()
    parts: list[str] = []
    for arg in args:
        path = Path(arg)
        if not path.exists():
            print(f"ERROR: file not found: {arg}", file=sys.stderr)
            sys.exit(1)
        parts.append(f"# === {path} ===\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


def load_claude_md_context() -> str:
    """Load project CLAUDE.md (truncated) so reviewer knows codebase conventions.

    WHY: External model (gpt-4o-mini) has zero context about CIC-Daily-Report
    until we inject it. Without context, the reviewer's "false positive" rate
    on flag suggestions skyrockets (e.g. flags absolute imports as bug).

    Returns empty string if CLAUDE.md absent (script still works).
    """
    candidates = [Path("CLAUDE.md"), Path("../CLAUDE.md")]
    for p in candidates:
        if p.exists():
            try:
                content = p.read_text(encoding="utf-8")[:4000]  # cap injection
                return f"## Project CLAUDE.md (excerpt — for context only)\n\n{content}\n\n---\n\n"
            except OSError:
                return ""
    return ""


def check_cost_guard(max_cost: int) -> int:
    """Read + bump call count. Block if exceeded.

    WHY: Heterogeneous verifier is paid (~$0.0001/call gpt-4o-mini, but bursts).
    Default 30 calls/session is cost-safe (typical Wave uses 5-15; raise with
    --max-cost N if needed). Operator can reset by deleting
    `.claude/heterogeneous_verify_count.txt` or setting HETEROGENEOUS_VERIFY_RESET=1.
    """
    if os.environ.get("HETEROGENEOUS_VERIFY_RESET") == "1":
        if COST_FILE.exists():
            COST_FILE.unlink()

    current = 0
    if COST_FILE.exists():
        try:
            current = int(COST_FILE.read_text(encoding="utf-8").strip() or "0")
        except (ValueError, OSError):
            current = 0

    if current >= max_cost:
        print(
            f"ERROR: cost guard tripped — {current} calls in this session "
            f"(max {max_cost}).\n"
            f"Reset: rm {COST_FILE} OR HETEROGENEOUS_VERIFY_RESET=1 "
            f"uv run python scripts/heterogeneous_verify.py ...",
            file=sys.stderr,
        )
        sys.exit(1)

    next_count = current + 1
    try:
        COST_FILE.parent.mkdir(parents=True, exist_ok=True)
        COST_FILE.write_text(str(next_count), encoding="utf-8")
    except OSError as e:
        print(f"WARNING: could not persist cost count: {e}", file=sys.stderr)

    return next_count


def call_openrouter(content: str, model: str) -> str:
    """Call OpenRouter chat completion API."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print(
            "ERROR: OPENROUTER_API_KEY env var not set.\n"
            "Get a key at https://openrouter.ai/keys then:\n"
            "  PowerShell: $env:OPENROUTER_API_KEY = 'sk-or-...'\n"
            "  Bash:       export OPENROUTER_API_KEY='sk-or-...'",
            file=sys.stderr,
        )
        sys.exit(1)

    claude_md = load_claude_md_context()
    user_msg = USER_PROMPT_TEMPLATE.format(claude_md_context=claude_md, content=content)

    payload = {
        "model": model,
        "temperature": 0.2,
        "max_tokens": 1500,  # bumped from 1000 — forced-list output is longer
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/cicquoccuong/CIC-Daily-Report",
        "X-Title": "CDR Heterogeneous Verifier",
    }
    try:
        resp = httpx.post(OPENROUTER_URL, json=payload, headers=headers, timeout=TIMEOUT_SEC)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except httpx.HTTPStatusError as e:
        # WHY (Wave 0.9.1): graceful degradation cho quota/payment errors.
        # Wave 0.9 INTENT: advisory only, KHÔNG block merge. Nếu OpenRouter
        # trả 402 (free credit cạn) hoặc 429 (rate limit), trả advisory message
        # thay vì raise — workflow vẫn exit 0 để PR không bị block.
        if e.response.status_code in (402, 429):
            print(
                f"WARNING: OpenRouter quota/payment issue ({e.response.status_code}). "
                f"Heterogeneous review SKIPPED — operator review required manually.",
                file=sys.stderr,
            )
            return (
                f"## ⚠️ Heterogeneous verifier unavailable\n\n"
                f"OpenRouter trả HTTP {e.response.status_code}. Nguyên nhân khả dĩ: "
                f"free credit cạn, API key invalid, hoặc model `{model}` không available.\n\n"
                f"**Khuyến nghị**: Operator review manual hoặc top-up OpenRouter credit "
                f"(https://openrouter.ai/credits).\n\n"
                f"PR vẫn có thể merge — heterogeneous verifier là advisory."
            )
        # Other HTTP errors (5xx, 4xx khác) vẫn raise để dev local biết bất thường
        raise
    except httpx.HTTPError as e:
        # WHY (Wave 0.9.1): network errors (timeout, DNS) cũng degrade gracefully.
        # Không thể phân biệt transient vs permanent — luôn advisory để PR merge được.
        print(f"WARNING: OpenRouter network error: {e}. Skipping review.", file=sys.stderr)
        return (
            f"## ⚠️ Heterogeneous verifier network error\n\n"
            f"`{e}`\n\nPR vẫn có thể merge — heterogeneous verifier là advisory."
        )
    except (KeyError, IndexError) as e:
        print(f"ERROR: malformed OpenRouter response: {e}", file=sys.stderr)
        sys.exit(1)


def build_argparser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    p = argparse.ArgumentParser(
        prog="heterogeneous_verify",
        description=(
            "Independent-model code review gate for Wave C+ cross-check. "
            "Reviewer is GPT-4o-mini (different family from Claude) — catches "
            "blindspots from Claude monoculture."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  uv run python scripts/heterogeneous_verify.py src/foo.py\n"
            "  git diff HEAD~1 | uv run python scripts/heterogeneous_verify.py -\n"
            "  uv run python scripts/heterogeneous_verify.py --max-cost 200 a.py b.py\n"
        ),
    )
    p.add_argument(
        "files",
        nargs="*",
        help="One or more files to review. Use '-' to read from stdin.",
    )
    p.add_argument(
        "--max-cost",
        type=int,
        default=DEFAULT_MAX_COST,
        help=f"Max API calls per session (default {DEFAULT_MAX_COST}). Tracked in {COST_FILE}.",
    )
    p.add_argument(
        "--model",
        default=None,
        help=f"Override model (default {DEFAULT_MODEL} or $HETEROGENEOUS_VERIFIER_MODEL).",
    )
    p.add_argument(
        "--ci",
        action="store_true",
        help=(
            "CI mode (Wave 0.9): suppress stderr status header, cap output to "
            f"{CI_OUTPUT_CAP} chars, always exit 0 (advisory — never auto-block)."
        ),
    )
    return p


def main() -> int:
    parser = build_argparser()
    ns = parser.parse_args()

    model = ns.model or os.environ.get("HETEROGENEOUS_VERIFIER_MODEL", DEFAULT_MODEL)

    content = read_input(ns.files)
    if not content.strip():
        print("ERROR: empty input (no files + no stdin)", file=sys.stderr)
        # WHY (Wave 0.9): CI mode never blocks — empty diff is not an error from CI POV
        return 0 if ns.ci else 1

    if len(content) > MAX_CONTENT_CHARS:
        print(
            f"WARNING: input {len(content)} chars exceeds {MAX_CONTENT_CHARS} — truncating tail",
            file=sys.stderr,
        )
        content = content[:MAX_CONTENT_CHARS] + "\n\n[TRUNCATED]"

    call_n = check_cost_guard(ns.max_cost)
    # WHY (Wave 0.9): suppress status header in CI mode — keeps PR comment clean
    if not ns.ci:
        print(
            f"=== Heterogeneous Verifier ({model}) — call {call_n}/{ns.max_cost} ===\n",
            file=sys.stderr,
        )
    try:
        review = call_openrouter(content, model)
    except Exception as e:
        # WHY (Wave 0.9.1): defense-in-depth. call_openrouter handles 402/429 +
        # network errors gracefully, nhưng 5xx + bugs chưa biết vẫn raise.
        # CI mode TUYỆT ĐỐI không được block merge — convert mọi exception thành
        # advisory message + exit 0. Dev local (no --ci) vẫn surface error.
        if ns.ci:
            print(
                f"## ⚠️ Heterogeneous verifier error\n\n`{type(e).__name__}: {e}`\n\n"
                f"PR vẫn có thể merge — heterogeneous verifier là advisory."
            )
            return 0
        raise
    # WHY (Wave 0.9): cap output for PR comment readability (GitHub UI degrades >10k)
    if ns.ci and len(review) > CI_OUTPUT_CAP:
        review = review[:CI_OUTPUT_CAP] + "\n\n[TRUNCATED — see full review by running locally]"
    print(review)
    # WHY (Wave 0.9): CI mode is advisory only — never block merge on heterogeneous review
    return 0


if __name__ == "__main__":
    sys.exit(main())
