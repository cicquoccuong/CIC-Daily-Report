"""Linter: forbid raw `+ DISCLAIMER` / `+ DISCLAIMER_SHORT` outside helper.

WHY (Wave C+ NQ05 centralization): All NQ05 disclaimer appends MUST flow through
`adapters.llm_adapter.append_nq05_disclaimer`. A raw `+ DISCLAIMER` in any caller
re-introduces the leak that motivated centralization (caller forgets variant,
truncation logic drifts, etc.).

USAGE:
    uv run python scripts/lint_nq05_pattern.py
    # Exit 0 = clean. Exit 1 = violations printed to stderr.

NOT installed as pre-commit hook (per spec); standalone CI / manual gate.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Pattern: any `+ DISCLAIMER` or `+ DISCLAIMER_SHORT` token (with optional spaces).
# Negative-lookahead prevents matching `+ DISCLAIMER_RE`, `+ DISCLAIMER_RX`, etc.
_PATTERN = re.compile(r"\+\s*DISCLAIMER(?:_SHORT)?\b(?!_)")

# Files allowed to contain the raw pattern (helper definition + constants).
_ALLOWLIST = {
    # llm_adapter.py — defines append_nq05_disclaimer; uses constants internally.
    "src/cic_daily_report/adapters/llm_adapter.py",
    # nq05_constants.py — SINGLE SOURCE OF TRUTH for DISCLAIMER + DISCLAIMER_SHORT.
    # WHY allowlist (Wave C+.2 fix #5): module docstring + WHY comments cite
    # the literal token `+ DISCLAIMER` / `+ DISCLAIMER_SHORT` when explaining
    # the historical anti-pattern this module replaces. Linter regex matches
    # those mentions inside docstrings/comments → false positive. The module
    # itself never USES `+ DISCLAIMER` (it only DEFINES the constants).
    "src/cic_daily_report/generators/nq05_constants.py",
    # article_generator.py — defines DISCLAIMER constant + has its OWN call site
    # post-migration (uses helper now), but the regex `+ DISCLAIMER` will not
    # match the helper-call form. Listed for safety in case future docstring
    # references the historical pattern.
}

# Source root to scan.
_SRC_ROOT = Path(__file__).resolve().parent.parent / "src"


def main() -> int:
    if not _SRC_ROOT.exists():
        print(f"ERROR: src root not found: {_SRC_ROOT}", file=sys.stderr)
        return 2

    violations: list[tuple[Path, int, str]] = []
    for py_file in _SRC_ROOT.rglob("*.py"):
        rel = py_file.relative_to(_SRC_ROOT.parent).as_posix()
        if rel in _ALLOWLIST:
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except OSError as e:
            print(f"WARN: cannot read {rel}: {e}", file=sys.stderr)
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            # Skip comment-only lines (false positives in WHY/historical notes).
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if _PATTERN.search(line):
                violations.append((py_file, lineno, line.rstrip()))

    if violations:
        print(
            f"NQ05 lint FAIL: {len(violations)} raw `+ DISCLAIMER[_SHORT]` "
            "occurrence(s) — must use append_nq05_disclaimer() helper.",
            file=sys.stderr,
        )
        for path, lineno, line in violations:
            print(f"  {path.as_posix()}:{lineno}: {line}", file=sys.stderr)
        return 1

    print("NQ05 lint OK: all disclaimer appends route through append_nq05_disclaimer().")
    return 0


if __name__ == "__main__":
    sys.exit(main())
