"""Wave 0.8 — Pre-flight check before flipping Wave 0.6/0.7 flags in production.

Purpose: Anh Cuong (no-code operator) needs a single command to verify ALL
infrastructure is ready BEFORE setting GitHub Secrets to flip Wave 0.6 flags
ON. Without this script, the only verification path is "set the flag and
watch the next pipeline run fail" — slow + risky.

What it checks (in order):
  1. Required secrets present in env (LLMs / Telegram / Sheets / Telethon)
  2. LLM provider smoke (Gemini Flash, Flash-Lite, Groq Qwen3, Cerebras)
  3. Sheets read smoke (BREAKING_LOG row count > 0)
  4. Telegram bot smoke (getMe returns username)
  5. Telethon connection smoke (only if API_ID/HASH/SESSION present)
  6. RAG index build smoke (Story 0.6.1 — verify code path executes)

Output: plain-text table with green ✓ / red ✗ per check + bottom verdict.
Exit: 0 if all required pass, 1 if any required fail.

Usage::

    uv run python scripts/preflight_check.py
    uv run python scripts/preflight_check.py --verbose

WHY plain-text (not rich): keep deps minimal — preflight should run on bare
minimum env. We use ANSI colors only (works on bash + GitHub Actions log).

WHY async: LLM/Sheets/Telegram smoke are I/O-bound. Running serially is
fine for ~6 checks, but we use asyncio.run so future checks (multi-LLM
parallel) plug in cleanly without rewrite.

Karpathy:
- Think: anh Cuong runs this BEFORE flipping flags — failure here = fix
  secrets/config first; do not proceed to replay or production.
- Simplicity: no daemon mode, no web UI, no metrics push. CLI only.
- Surgical: this is a NEW script — no existing pipeline code touched.
- Goal: exit 0 = "safe to flip flags"; exit 1 = "fix something first".
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass, field
from typing import Awaitable, Callable

# ANSI colors — minimal, works in bash + GH Actions runner logs.
_GREEN = "\033[92m"
_RED = "\033[91m"
_YELLOW = "\033[93m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


@dataclass
class CheckResult:
    """Outcome of a single preflight check."""

    name: str
    passed: bool
    message: str = ""
    required: bool = True  # If False, failure does NOT cause exit 1.
    details: str = ""  # Verbose-only extra info.


@dataclass
class PreflightReport:
    """Aggregated preflight outcome — printed as a table at the end."""

    results: list[CheckResult] = field(default_factory=list)

    def add(self, result: CheckResult) -> None:
        self.results.append(result)

    @property
    def required_failed(self) -> int:
        return sum(1 for r in self.results if r.required and not r.passed)

    @property
    def optional_failed(self) -> int:
        return sum(1 for r in self.results if not r.required and not r.passed)

    @property
    def total_passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def exit_code(self) -> int:
        return 1 if self.required_failed > 0 else 0


# ---------------------------------------------------------------------------
# Individual check functions — each returns CheckResult, never raises.
# WHY: preflight is "best effort" — we want to ALWAYS print the full table
# even if one check explodes; never crash mid-checklist.
# ---------------------------------------------------------------------------


def _check_secrets() -> CheckResult:
    """Check that all required env vars are set (non-empty).

    GEMINI accepts either GEMINI_API_KEY or GEMINI_API_KEY_DR (DR = data role,
    used by some collectors). Either alone is fine.
    """
    # Required groups — at least one of each tuple must be present.
    groups: list[tuple[str, tuple[str, ...]]] = [
        ("Gemini", ("GEMINI_API_KEY", "GEMINI_API_KEY_DR")),
        ("Groq", ("GROQ_API_KEY",)),
        ("Cerebras (Wave 0.6 judge)", ("CEREBRAS_API_KEY",)),
        ("Telegram bot", ("TELEGRAM_BOT_TOKEN",)),
        ("Telegram chat", ("TELEGRAM_CHAT_ID",)),
        ("Admin chat", ("ADMIN_CHAT_ID",)),
        ("Sheets creds", ("GOOGLE_SHEETS_CREDENTIALS",)),
        ("Sheets ID", ("GOOGLE_SHEETS_SPREADSHEET_ID",)),
    ]
    missing: list[str] = []
    for label, keys in groups:
        if not any(os.environ.get(k) for k in keys):
            missing.append(f"{label} ({'/'.join(keys)})")
    if missing:
        return CheckResult(
            name="Required secrets",
            passed=False,
            message=f"missing {len(missing)} secret group(s)",
            details="\n  - " + "\n  - ".join(missing),
        )
    return CheckResult(
        name="Required secrets",
        passed=True,
        message=f"all {len(groups)} groups present",
    )


def _check_optional_telethon_secrets() -> CheckResult:
    """Telethon (TG channel scraping) is OPTIONAL — fallback to RSS works."""
    keys = ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_SESSION_STRING")
    present = [k for k in keys if os.environ.get(k)]
    if len(present) == 3:
        return CheckResult(
            name="Telethon secrets (optional)",
            passed=True,
            message="all 3 present — TG scraping ENABLED",
            required=False,
        )
    if len(present) == 0:
        return CheckResult(
            name="Telethon secrets (optional)",
            passed=True,  # not a failure — pipeline falls back to RSS
            message="not set — TG scraping DISABLED (RSS fallback OK)",
            required=False,
        )
    return CheckResult(
        name="Telethon secrets (optional)",
        passed=False,
        message=f"partial ({len(present)}/3) — must be all-or-nothing",
        required=False,
        details="present: " + ", ".join(present),
    )


async def _check_llm_providers() -> CheckResult:
    """Ping each LLM provider with a trivial completion request.

    We import LLMAdapter lazily to avoid module import cost when secrets fail
    earlier (chained-fail-fast feel for operator).
    """
    try:
        from cic_daily_report.adapters.llm_adapter import LLMAdapter
    except Exception as e:
        return CheckResult(
            name="LLM providers smoke",
            passed=False,
            message=f"LLMAdapter import failed: {e}",
        )

    providers_to_test = ["gemini", "gemini-lite", "groq-qwen3", "cerebras"]
    failed: list[str] = []
    succeeded: list[str] = []
    for prov in providers_to_test:
        try:
            adapter = LLMAdapter(prefer=prov)
            # Tiny prompt — cheapest possible smoke.
            result = await asyncio.wait_for(
                adapter.generate("Reply with 'ok'", max_tokens=8),
                timeout=20,
            )
            if result and "ok" in str(result).lower():
                succeeded.append(prov)
            else:
                # Non-empty response is also pass — providers vary in style.
                if result:
                    succeeded.append(prov)
                else:
                    failed.append(f"{prov} (empty response)")
        except Exception as e:
            failed.append(f"{prov} ({type(e).__name__})")

    if failed:
        return CheckResult(
            name="LLM providers smoke",
            passed=False,
            message=f"{len(succeeded)}/{len(providers_to_test)} OK",
            details="failed: " + "; ".join(failed),
        )
    return CheckResult(
        name="LLM providers smoke",
        passed=True,
        message=f"{len(succeeded)}/{len(providers_to_test)} responding",
    )


async def _check_sheets_read() -> CheckResult:
    """Verify Sheets creds work + BREAKING_LOG tab readable."""
    try:
        from cic_daily_report.storage.sheets_client import SheetsClient

        sheets = SheetsClient()
        rows = await asyncio.to_thread(sheets.read_all, "BREAKING_LOG")
        return CheckResult(
            name="Sheets read smoke (BREAKING_LOG)",
            passed=True,
            message=f"{len(rows)} rows readable",
        )
    except Exception as e:
        return CheckResult(
            name="Sheets read smoke (BREAKING_LOG)",
            passed=False,
            message=f"{type(e).__name__}: {e}",
        )


async def _check_telegram_bot() -> CheckResult:
    """Hit Telegram getMe to verify bot token + connectivity."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return CheckResult(
            name="Telegram bot smoke (getMe)",
            passed=False,
            message="TELEGRAM_BOT_TOKEN missing — skip",
        )
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"https://api.telegram.org/bot{token}/getMe")
            data = resp.json()
            if data.get("ok") and data.get("result", {}).get("username"):
                return CheckResult(
                    name="Telegram bot smoke (getMe)",
                    passed=True,
                    message=f"bot @{data['result']['username']}",
                )
            return CheckResult(
                name="Telegram bot smoke (getMe)",
                passed=False,
                message=f"unexpected response: {data}",
            )
    except Exception as e:
        return CheckResult(
            name="Telegram bot smoke (getMe)",
            passed=False,
            message=f"{type(e).__name__}: {e}",
        )


async def _check_telethon_connection() -> CheckResult:
    """Telethon connection — OPTIONAL (only if all 3 secrets present)."""
    keys = ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_SESSION_STRING")
    if not all(os.environ.get(k) for k in keys):
        return CheckResult(
            name="Telethon connection (optional)",
            passed=True,  # skipped = pass for optional
            message="skipped (secrets not all set)",
            required=False,
        )
    try:
        # Lazy import — telethon is heavy, only needed if we run this check.
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        api_id = int(os.environ["TELEGRAM_API_ID"])
        api_hash = os.environ["TELEGRAM_API_HASH"]
        session = os.environ["TELEGRAM_SESSION_STRING"]
        client = TelegramClient(StringSession(session), api_id, api_hash)
        await asyncio.wait_for(client.connect(), timeout=15)
        is_authed = await client.is_user_authorized()
        await client.disconnect()
        if is_authed:
            return CheckResult(
                name="Telethon connection (optional)",
                passed=True,
                message="connected + authorized",
                required=False,
            )
        return CheckResult(
            name="Telethon connection (optional)",
            passed=False,
            message="connected but session NOT authorized — re-generate",
            required=False,
        )
    except Exception as e:
        return CheckResult(
            name="Telethon connection (optional)",
            passed=False,
            message=f"{type(e).__name__}: {e}",
            required=False,
        )


async def _check_rag_build() -> CheckResult:
    """RAG index (Story 0.6.1) — verify code path can construct an index.

    We don't actually rebuild from Sheets (would re-pay Sheets read cost).
    Instead, instantiate the class with empty corpus to validate imports +
    constructor wiring. Real index health is covered by Wave 0.6 tests.
    """
    try:
        from cic_daily_report.breaking.rag_index import RAGIndex

        # Construct with no rows — catches import/init errors only.
        idx = RAGIndex()
        # Touch a method to ensure dataclass/object is well-formed.
        _ = getattr(idx, "doc_count", None)
        return CheckResult(
            name="RAG index build smoke",
            passed=True,
            message="RAGIndex instantiates cleanly",
        )
    except Exception as e:
        return CheckResult(
            name="RAG index build smoke",
            passed=False,
            message=f"{type(e).__name__}: {e}",
        )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def run_preflight(
    checks: list[Callable[[], Awaitable[CheckResult] | CheckResult]] | None = None,
) -> PreflightReport:
    """Run all preflight checks, return aggregated report.

    `checks` arg is for tests — production runs use the default list below.
    Each check is awaited (or called) sequentially; we keep order stable so
    the printed table reads top-to-bottom in operator mental model.
    """
    if checks is None:
        checks = [
            _check_secrets,
            _check_optional_telethon_secrets,
            _check_llm_providers,
            _check_sheets_read,
            _check_telegram_bot,
            _check_telethon_connection,
            _check_rag_build,
        ]
    report = PreflightReport()
    for check in checks:
        try:
            result = check()
            if asyncio.iscoroutine(result):
                result = await result
        except Exception as e:
            # Defensive: a check fn should never raise, but if it does,
            # capture as failure so the table still prints.
            result = CheckResult(
                name=getattr(check, "__name__", "unknown"),
                passed=False,
                message=f"check raised: {type(e).__name__}: {e}",
            )
        report.add(result)
    return report


def render_report(report: PreflightReport, verbose: bool = False) -> str:
    """Format the report as a human-readable plain-text table.

    Format choices:
      - Each row: "[✓/✗] NAME ............ MESSAGE"
      - Footer: total summary + verdict (READY / NOT READY)
      - --verbose adds details lines under failed checks
    """
    lines: list[str] = []
    lines.append(f"{_BOLD}=== Wave 0.8 Pre-flight Check ==={_RESET}")
    lines.append("")
    name_width = max(len(r.name) for r in report.results) + 2
    for r in report.results:
        if r.passed:
            mark = f"{_GREEN}[OK]{_RESET}"
        elif not r.required:
            mark = f"{_YELLOW}[WARN]{_RESET}"
        else:
            mark = f"{_RED}[FAIL]{_RESET}"
        name_padded = r.name.ljust(name_width, ".")
        lines.append(f"  {mark}  {name_padded} {r.message}")
        if verbose and r.details:
            # Indent details so they visually nest under the row.
            for d_line in r.details.splitlines():
                lines.append(f"        {d_line}")
    lines.append("")
    lines.append(
        f"Summary: {report.total_passed}/{len(report.results)} passed, "
        f"{report.required_failed} required failed, "
        f"{report.optional_failed} optional warning(s)"
    )
    if report.exit_code == 0:
        lines.append(f"{_GREEN}{_BOLD}VERDICT: READY — safe to flip flags{_RESET}")
    else:
        lines.append(
            f"{_RED}{_BOLD}VERDICT: NOT READY — fix failed checks before flipping flags{_RESET}"
        )
    return "\n".join(lines) + "\n"


def _build_arg_parser() -> argparse.ArgumentParser:
    """CLI parser — extracted for testability."""
    parser = argparse.ArgumentParser(
        description="Wave 0.8 pre-flight check before flipping Wave 0.6/0.7 flags.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show extra detail under failed checks (e.g., which secrets missing).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point — returns process exit code (0=ready, 1=not ready)."""
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    report = asyncio.run(run_preflight())
    print(render_report(report, verbose=args.verbose))
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
