"""Wave 0.6 Story 0.6.5 (alpha.23) — Replay breaking events for validation.

Purpose: Replay historical breaking events from BREAKING_LOG with Wave 0.6
flags ON, and compare new pipeline output against the historical content
that was actually delivered. Generates a markdown report quantifying
hallucination reduction (historical claim count, NQ05 advisory phrases).

Usage::

    # Mock mode — no API calls, validates script structure
    uv run python scripts/replay_breaking.py --mock --output reports/replay-mock.md

    # Real replay (needs CEREBRAS_API_KEY + GOOGLE_SHEETS creds)
    uv run python scripts/replay_breaking.py \\
        --from 2026-04-27 --to 2026-04-28 \\
        --output reports/replay-wave-0.6.md

WHY this script exists:
Anh Cuong (no-code operator) needs to validate Wave 0.6 BEFORE flipping flags
in production. Without this script, the only validation path is "ship it and
watch live Telegram" — which is risky (1-2 days of bad messages before
detection). Replay = offline dry-run with measurable diff vs baseline.

WHY mock mode is default-friendly:
Cerebras API has tight quota. Anh Cuong can run --mock first to verify the
script wiring works, then run the real replay only when confident.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Regex catalog — kept module-level so tests can import + verify patterns
# WHY: extracting these into a module-level constant makes the detection
# logic auditable separately from the replay flow.
HISTORICAL_PATTERNS = [
    re.compile(r"L[ầa]n cu[ốo]i", re.IGNORECASE),  # "Lần cuối ... vào năm X"
    re.compile(r"n[ăa]m\s+20\d{2}", re.IGNORECASE),  # "năm 2021"
    re.compile(r"k[ểe] t[ừu] n[ăa]m", re.IGNORECASE),  # "kể từ năm 2020"
    re.compile(r"l[ầa]n\s+(?:đầ?u|thứ?\s*\d+)", re.IGNORECASE),  # "lần đầu tiên"
]
# WHY separate numeric pattern: $/% claims are checked but not used as
# "hallucination" signal (legitimate breaking content has prices/percents).
# Tracked for delta reporting only.
NUMERIC_PATTERN = re.compile(r"[\$₫€£¥]\s*[\d.,]+|\d+(?:\.\d+)?\s*%")
# Vietnamese NQ05-violation advisory phrases — see generators/nq05_filter.py.
NQ05_PATTERNS = [
    re.compile(r"n[êe]n mua", re.IGNORECASE),
    re.compile(r"n[êe]n b[áa]n", re.IGNORECASE),
    re.compile(r"khuy[ếe]n ngh[ịi]", re.IGNORECASE),
    re.compile(r"l[ờo]i khuy[êe]n", re.IGNORECASE),
]


@dataclass
class ReplayEntry:
    """Replay outcome for a single historical event."""

    title: str
    source: str
    severity: str
    detected_at: str
    old_content: str = ""
    new_content: str = ""
    old_historical_count: int = 0
    new_historical_count: int = 0
    old_numeric_count: int = 0
    new_numeric_count: int = 0
    old_nq05_count: int = 0
    new_nq05_count: int = 0
    error: str = ""

    @property
    def status(self) -> str:
        """OK if hallucinations dropped or stayed equal; REGRESSION if increased."""
        if self.error:
            return "ERROR"
        if self.new_historical_count > self.old_historical_count:
            return "REGRESSION"
        if self.new_nq05_count > self.old_nq05_count:
            return "REGRESSION"
        return "OK"


@dataclass
class ReplayReport:
    """Full report aggregating per-event replay outcomes."""

    date_from: str = ""
    date_to: str = ""
    events: list[ReplayEntry] = field(default_factory=list)
    mock_mode: bool = False

    @property
    def total_events(self) -> int:
        return len(self.events)

    @property
    def old_hallucination_total(self) -> int:
        return sum(e.old_historical_count for e in self.events)

    @property
    def new_hallucination_total(self) -> int:
        return sum(e.new_historical_count for e in self.events)

    @property
    def reduction_percentage(self) -> float:
        """Compute hallucination reduction. 0% if old_total is 0 (no baseline)."""
        if self.old_hallucination_total == 0:
            return 0.0
        delta = self.old_hallucination_total - self.new_hallucination_total
        return (delta / self.old_hallucination_total) * 100

    @property
    def regression_count(self) -> int:
        return sum(1 for e in self.events if e.status == "REGRESSION")


def count_historical_claims(text: str) -> int:
    """Count regex matches against the historical-claim patterns.

    Each pattern that matches at least once contributes 1 to the count
    (we count distinct *types* of claims, not raw match count, to avoid
    double-counting "lần cuối vào năm 2021" as 2 hallucinations).
    """
    if not text:
        return 0
    return sum(1 for pat in HISTORICAL_PATTERNS if pat.search(text))


def count_numeric_claims(text: str) -> int:
    """Count distinct numeric claims (prices/percents) in text."""
    if not text:
        return 0
    return len(NUMERIC_PATTERN.findall(text))


def count_nq05_violations(text: str) -> int:
    """Count NQ05 advisory-phrase pattern matches."""
    if not text:
        return 0
    return sum(1 for pat in NQ05_PATTERNS if pat.search(text))


def filter_events_by_date(raw_rows: list[dict], date_from: str, date_to: str) -> list[dict]:
    """Filter sheet rows by date range (inclusive both ends).

    Date strings in BREAKING_LOG are ISO-8601 ("2026-04-27T15:30:00+00:00").
    We compare DATE portion only — time-of-day ignored.
    """
    try:
        from_d = datetime.fromisoformat(date_from).date()
        to_d = datetime.fromisoformat(date_to).date()
    except ValueError:
        return []
    out = []
    for row in raw_rows:
        ts = str(row.get("Thời gian", "") or row.get("detected_at", ""))
        if not ts:
            continue
        try:
            row_date = datetime.fromisoformat(ts).date()
        except (ValueError, TypeError):
            continue
        if from_d <= row_date <= to_d:
            out.append(row)
    return out


def compute_reduction_percentage(old_total: int, new_total: int) -> float:
    """Pure helper for tests — reduction as percent of old baseline.

    Returns 0.0 when old_total is 0 (cannot reduce from nothing).
    Returns 100.0 when new_total == 0 and old_total > 0 (full elimination).
    """
    if old_total <= 0:
        return 0.0
    delta = old_total - new_total
    return (delta / old_total) * 100


async def _replay_one_event_mock(row: dict) -> ReplayEntry:
    """Mock replay — fabricates a "new" content with FEWER hallucinations.

    WHY this exists: --mock mode lets Anh Cuong test the script wiring
    (CLI args, output format, file write) without burning Cerebras quota.
    The fake reduction (old - 1) is intentional so the report visibly shows
    a reduction — confirming the diff math + table renders correctly.
    """
    old = str(row.get("content", "") or row.get("Tiêu đề", "") or row.get("title", ""))
    # Strip first historical pattern match to simulate Wave 0.6 catching it.
    new = old
    for pat in HISTORICAL_PATTERNS:
        m = pat.search(new)
        if m:
            new = new[: m.start()] + new[m.end() :]
            break
    return ReplayEntry(
        title=str(row.get("Tiêu đề", "") or row.get("title", "")),
        source=str(row.get("Nguồn", "") or row.get("source", "")),
        severity=str(row.get("Mức độ", "") or row.get("severity", "")),
        detected_at=str(row.get("Thời gian", "") or row.get("detected_at", "")),
        old_content=old,
        new_content=new,
        old_historical_count=count_historical_claims(old),
        new_historical_count=count_historical_claims(new),
        old_numeric_count=count_numeric_claims(old),
        new_numeric_count=count_numeric_claims(new),
        old_nq05_count=count_nq05_violations(old),
        new_nq05_count=count_nq05_violations(new),
    )


def _fetch_baseline_from_url(url: str, timeout: float = 12.0) -> str:
    """Wave 0.6.6 B8: fetch original article text from URL as baseline.

    BREAKING_LOG schema does NOT have a `content` column (it stores
    title/hash/severity/url only — see storage/sheets_client.py BREAKING_LOG
    schema). Without this fallback, `old_content=""` → reduction metrics
    meaningless (always 0 baseline → 0% reduction). Use trafilatura to fetch
    the original article body so we have something real to compare against.

    Returns empty string on any failure (network, parse, missing trafilatura).
    """
    if not url:
        return ""
    try:
        import trafilatura  # lazy import — keeps mock mode lightweight
    except ImportError:
        return ""
    try:
        downloaded = trafilatura.fetch_url(url, no_ssl=True)
        if not downloaded:
            return ""
        extracted = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
        )
        return extracted or ""
    except Exception as e:
        print(f"[WARN] baseline fetch failed for {url}: {e}", file=sys.stderr)
        return ""


async def _replay_one_event_real(row: dict) -> ReplayEntry:
    """Real replay — re-runs generate_breaking_content with Wave 0.6 ON.

    NOTE: This function requires CEREBRAS_API_KEY + Google Sheets creds.
    It is NOT called in --mock mode. We import dependencies lazily so that
    --mock mode works in environments without those creds.
    """
    # Lazy imports — only loaded when real mode is used.
    from cic_daily_report.adapters.llm_adapter import LLMAdapter
    from cic_daily_report.breaking.content_generator import generate_breaking_content
    from cic_daily_report.breaking.event_detector import BreakingEvent

    title = str(row.get("Tiêu đề", "") or row.get("title", ""))
    source = str(row.get("Nguồn", "") or row.get("source", ""))
    severity = str(row.get("Mức độ", "") or row.get("severity", "important"))
    detected_at = str(row.get("Thời gian", "") or row.get("detected_at", ""))
    # Wave 0.6.6 B8: BREAKING_LOG has no `content` column — fall back to fetching
    # original article body via URL so reduction metrics use a real baseline.
    old = str(row.get("content", "") or "")
    if not old:
        url = str(row.get("URL", "") or row.get("url", ""))
        if url:
            old = await asyncio.to_thread(_fetch_baseline_from_url, url)

    entry = ReplayEntry(
        title=title,
        source=source,
        severity=severity,
        detected_at=detected_at,
        old_content=old,
        old_historical_count=count_historical_claims(old),
        old_numeric_count=count_numeric_claims(old),
        old_nq05_count=count_nq05_violations(old),
    )

    try:
        event = BreakingEvent(
            title=title,
            source=source,
            url=str(row.get("URL", "")),
            panic_score=int(row.get("panic_score", 0) or 0),
        )
        llm = LLMAdapter(prefer="cerebras")
        content = await asyncio.wait_for(
            generate_breaking_content(event, llm, severity=severity),
            timeout=90,
        )
        entry.new_content = content.formatted
        entry.new_historical_count = count_historical_claims(entry.new_content)
        entry.new_numeric_count = count_numeric_claims(entry.new_content)
        entry.new_nq05_count = count_nq05_violations(entry.new_content)
    except Exception as e:
        entry.error = str(e)
    return entry


async def run_replay(
    date_from: str,
    date_to: str,
    output_path: Path,
    mock: bool = False,
    limit: int | None = None,
) -> ReplayReport:
    """Top-level orchestrator — load events, replay each, write report."""
    report = ReplayReport(date_from=date_from, date_to=date_to, mock_mode=mock)

    # Load historical events. In mock mode, fabricate a small dataset so the
    # script is runnable even with no Sheets access.
    if mock:
        raw_rows = _mock_breaking_log_rows()
    else:
        raw_rows = await _load_breaking_log_rows()

    filtered = filter_events_by_date(raw_rows, date_from, date_to)
    if limit is not None:
        filtered = filtered[:limit]

    # Set Wave 0.6 flags ON for the duration of the replay (env override).
    # WHY env (not config import): generate_breaking_content reads the flag
    # via os.getenv at call time → setting env here propagates correctly.
    import os

    saved_flags = {
        k: os.environ.get(k)
        for k in (
            "WAVE_0_6_ENABLED",
            "WAVE_0_6_DATE_BLOCK",
            "WAVE_0_6_2SOURCE_REQUIRED",
            # Wave 0.6.6 B9: include kill switch in saved set so we restore it.
            "WAVE_0_6_KILL_SWITCH",
        )
    }
    os.environ["WAVE_0_6_ENABLED"] = "1"
    os.environ["WAVE_0_6_DATE_BLOCK"] = "1"
    os.environ["WAVE_0_6_2SOURCE_REQUIRED"] = "1"
    # Wave 0.6.6 B9: kill switch overrides ALL Wave 0.6 flags. Without unsetting
    # it, replay would silently run with Wave 0.6 OFF → metrics meaningless.
    # WHY pop (not set "0"): _wave_0_6_kill_switch_active() treats any unset
    # value as inactive; explicitly popping is unambiguous.
    os.environ.pop("WAVE_0_6_KILL_SWITCH", None)
    try:
        replay_fn = _replay_one_event_mock if mock else _replay_one_event_real
        for row in filtered:
            entry = await replay_fn(row)
            report.events.append(entry)
    finally:
        # Restore env so subsequent script invocations / tests aren't polluted.
        for k, v in saved_flags.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_render_report_markdown(report), encoding="utf-8")
    return report


def _render_report_markdown(report: ReplayReport) -> str:
    """Render report as markdown for Anh Cuong to review.

    Format follows the spec — header summary + per-event table with status.
    """
    lines = []
    lines.append("# Replay Report — Wave 0.6 vs Wave 0.5.2")
    lines.append("")
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"Date range: {report.date_from} to {report.date_to}")
    lines.append(f"Mock mode: {report.mock_mode}")
    lines.append(f"Events processed: {report.total_events}")
    lines.append(f"Pipeline old (baseline): {report.old_hallucination_total} bài có dấu hiệu bịa")
    lines.append(
        f"Pipeline new (Wave 0.6 ON): {report.new_hallucination_total} bài có dấu hiệu bịa"
    )
    lines.append(f"Reduction: {report.reduction_percentage:.1f}%")
    lines.append(f"Regressions: {report.regression_count}")
    lines.append("")
    lines.append("| Event | Old hist | New hist | Old NQ05 | New NQ05 | Status |")
    lines.append("|---|---|---|---|---|---|")
    for e in report.events:
        title = (e.title[:60] + "...") if len(e.title) > 60 else e.title
        # Escape pipe chars in title for markdown safety.
        title = title.replace("|", "\\|")
        lines.append(
            f"| {title} | {e.old_historical_count} | {e.new_historical_count} | "
            f"{e.old_nq05_count} | {e.new_nq05_count} | {e.status} |"
        )
    if any(e.error for e in report.events):
        lines.append("")
        lines.append("## Errors")
        for e in report.events:
            if e.error:
                lines.append(f"- {e.title[:80]}: {e.error}")
    return "\n".join(lines) + "\n"


def _mock_breaking_log_rows() -> list[dict]:
    """Fabricate a tiny dataset for --mock mode (no Sheets access needed)."""
    return [
        {
            "Tiêu đề": "BTC giảm 5% sau tin Fed",
            "Nguồn": "CoinDesk",
            "Mức độ": "important",
            "Thời gian": "2026-04-27T10:00:00+00:00",
            "content": "BTC giảm 5%. Lần cuối Bitcoin giảm mạnh thế này vào năm 2022.",
        },
        {
            "Tiêu đề": "ETH ETF approved",
            "Nguồn": "Reuters",
            "Mức độ": "critical",
            "Thời gian": "2026-04-28T08:00:00+00:00",
            "content": "ETH ETF được SEC phê duyệt. Đây là lần đầu tiên kể từ năm 2024.",
        },
    ]


async def _load_breaking_log_rows() -> list[dict]:
    """Read all rows from BREAKING_LOG sheet (real mode only).

    Returns empty list on failure — replay then has nothing to do, which is
    a safe outcome (operator sees "0 events" in report and investigates).
    """
    try:
        from cic_daily_report.storage.sheets_client import SheetsClient

        sheets = SheetsClient()
        return await asyncio.to_thread(sheets.read_all, "BREAKING_LOG")
    except Exception as e:
        print(f"[ERROR] BREAKING_LOG read failed: {e}", file=sys.stderr)
        return []


def _build_arg_parser() -> argparse.ArgumentParser:
    """Construct CLI arg parser. Extracted for testability."""
    parser = argparse.ArgumentParser(
        description="Replay BREAKING_LOG events with Wave 0.6 flags ON for validation."
    )
    parser.add_argument(
        "--from",
        dest="date_from",
        default="2026-04-27",
        help="ISO date — start of replay range (inclusive). Default: 2026-04-27",
    )
    parser.add_argument(
        "--to",
        dest="date_to",
        default="2026-04-28",
        help="ISO date — end of replay range (inclusive). Default: 2026-04-28",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/replay-wave-0.6.md"),
        help="Markdown output path. Default: reports/replay-wave-0.6.md",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use fabricated dataset + no LLM calls (for script wiring validation).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N events (for fast iteration).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns process exit code."""
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    report = asyncio.run(
        run_replay(
            date_from=args.date_from,
            date_to=args.date_to,
            output_path=args.output,
            mock=args.mock,
            limit=args.limit,
        )
    )
    print(
        f"Replay complete: {report.total_events} events, "
        f"{report.reduction_percentage:.1f}% reduction, "
        f"{report.regression_count} regressions. Report: {args.output}"
    )
    return 1 if report.regression_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
