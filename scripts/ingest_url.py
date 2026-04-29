"""Wave 0.6.6 A2 — URL ingest CLI for one-off breaking news.

Use case: anh Cường paste 1 URL bài cũ rớt khỏi RSS / cần publish 1 lần →
script fetch, build BreakingEvent, run minimal pipeline (dedup → severity →
content gen → optional Telegram send → BREAKING_LOG append).

Usage::

    # Dry-run (default safe mode, NO Telegram send, NO log append)
    uv run python scripts/ingest_url.py https://example.com/article \\
        --severity important --source-name "Decrypt" --dry-run

    # Real send (requires TG + Sheets creds, GROQ/CEREBRAS keys for LLM)
    uv run python scripts/ingest_url.py https://example.com/article \\
        --severity important --source-name "Decrypt"

WHY this script exists:
RSS pulls only the latest N items per feed. If a noteworthy article rolls
off the feed before the breaking pipeline catches it (rare, but happens
during outages), there is currently NO way to feed it into the pipeline
without manually editing Google Sheets. This CLI gives anh Cường a single
command to ingest 1 URL on-demand.

WHY simplicity:
- No retry logic (one-shot manual command — operator can re-run).
- No batch (1 URL at a time keeps semantics clear).
- --dry-run is opt-out via flag absence in real mode (we want explicit
  confirmation before TG send to avoid accidental misfires).

Exit codes:
    0 — success (or skipped as duplicate in dry-run)
    1 — failure (URL fetch failed, LLM all-fallback failed, TG send failed)
    2 — duplicate (event already in BREAKING_LOG within dedup window)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse


def _build_arg_parser() -> argparse.ArgumentParser:
    """CLI parser — extracted so tests can call without sys.argv."""
    parser = argparse.ArgumentParser(
        description="Ingest 1 URL as a breaking news event (one-off).",
    )
    parser.add_argument(
        "url",
        help="Article URL to fetch + ingest (must be http/https).",
    )
    parser.add_argument(
        "--severity",
        choices=("notable", "important", "critical"),
        default="important",
        help="Severity tier. Default: important.",
    )
    parser.add_argument(
        "--source-name",
        default="",
        help=("Display source name (e.g., 'Decrypt'). Empty → derived from URL hostname."),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Preview only — does NOT send Telegram, does NOT append to "
            "BREAKING_LOG. Use this first to inspect output."
        ),
    )
    parser.add_argument(
        "--skip-dedup",
        action="store_true",
        help=(
            "Bypass duplicate check. Use with caution — duplicate sends will "
            "spam Telegram. Default: dedup ON."
        ),
    )
    return parser


def _validate_url(url: str) -> str:
    """Return URL on valid http/https; raise ValueError otherwise."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Invalid URL scheme: {parsed.scheme!r} (need http/https)")
    if not parsed.netloc:
        raise ValueError("URL missing host portion")
    return url


def _hostname_to_source(url: str) -> str:
    """Derive display source name from URL hostname.

    Example: 'https://www.decrypt.co/x' → 'decrypt.co'
    """
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host or "unknown"


def fetch_article(url: str, timeout: float = 12.0) -> tuple[str, str]:
    """Fetch URL with trafilatura → return (title, body).

    Returns (empty, empty) on failure — caller decides what to do.
    """
    try:
        import trafilatura
    except ImportError:
        print("[ERROR] trafilatura not installed — pip install trafilatura", file=sys.stderr)
        return "", ""

    try:
        downloaded = trafilatura.fetch_url(url, no_ssl=True)
        if not downloaded:
            return "", ""
        # Extract metadata (title) and body separately.
        meta = trafilatura.extract_metadata(downloaded)
        title = (meta.title if meta and meta.title else "") or ""
        body = (
            trafilatura.extract(
                downloaded,
                include_comments=False,
                include_tables=False,
            )
            or ""
        )
        return title.strip(), body.strip()
    except Exception as e:
        print(f"[ERROR] fetch_article failed: {e}", file=sys.stderr)
        return "", ""


async def ingest_one_url(
    url: str,
    severity: str,
    source_name: str,
    dry_run: bool,
    skip_dedup: bool,
) -> int:
    """Top-level orchestrator. Returns CLI exit code.

    Flow:
        1. Fetch URL → title + body via trafilatura.
        2. Build BreakingEvent.
        3. Dedup check (unless --skip-dedup) against BREAKING_LOG.
        4. generate_breaking_content with LLM adapter.
        5. (NOT --dry-run) → send via Telegram + append BREAKING_LOG.
    """
    try:
        url = _validate_url(url)
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    print(f"[INFO] Fetching {url}", file=sys.stderr)
    title, body = fetch_article(url)
    if not title:
        print("[ERROR] Could not extract title from URL", file=sys.stderr)
        return 1
    if not body:
        print("[WARN] Empty body — content generation may be poor", file=sys.stderr)

    display_source = source_name or _hostname_to_source(url)
    print(f"[INFO] Title: {title[:120]}", file=sys.stderr)
    print(f"[INFO] Source: {display_source} | Severity: {severity}", file=sys.stderr)

    # Lazy imports — keep --help fast and not require Sheets creds for parsing.
    from cic_daily_report.adapters.llm_adapter import LLMAdapter
    from cic_daily_report.breaking.content_generator import generate_breaking_content
    from cic_daily_report.breaking.event_detector import BreakingEvent

    event = BreakingEvent(
        title=title,
        source=display_source,
        url=url,
        panic_score=0,  # manual ingest has no panic context
        raw_data={"summary": body[:2000]},  # truncate to keep prompt sane
    )

    # Dedup check.
    if not skip_dedup:
        try:
            from cic_daily_report.breaking.dedup_manager import DedupManager
            from cic_daily_report.storage.sheets_client import SheetsClient

            sheets = SheetsClient()
            dedup_mgr = DedupManager(sheets_client=sheets)
            dedup_result = dedup_mgr.process_events([event])
            if dedup_result.duplicates_skipped > 0:
                print(
                    "[INFO] Event flagged as duplicate (already in BREAKING_LOG). "
                    "Use --skip-dedup to override.",
                    file=sys.stderr,
                )
                return 2
        except Exception as e:
            # Dedup is not fatal — warn and proceed (operator-driven action).
            print(f"[WARN] Dedup check failed ({e}); proceeding without dedup", file=sys.stderr)

    # Generate content.
    try:
        llm = LLMAdapter()
        content = await asyncio.wait_for(
            generate_breaking_content(event, llm, severity=severity),
            timeout=120,
        )
    except Exception as e:
        print(f"[ERROR] generate_breaking_content failed: {e}", file=sys.stderr)
        return 1

    formatted = content.formatted
    print("─" * 60, file=sys.stderr)
    print(formatted)
    print("─" * 60, file=sys.stderr)

    if dry_run:
        print("[INFO] --dry-run: skipping Telegram send + BREAKING_LOG append", file=sys.stderr)
        return 0

    # Real send.
    try:
        from cic_daily_report.delivery.telegram_bot import TelegramBot

        bot = TelegramBot()
        await bot.send_message(formatted)
        print("[INFO] Telegram sent", file=sys.stderr)
    except Exception as e:
        print(f"[ERROR] Telegram send failed: {e}", file=sys.stderr)
        return 1

    # Append BREAKING_LOG.
    try:
        from cic_daily_report.breaking.dedup_manager import compute_hash
        from cic_daily_report.storage.sheets_client import SheetsClient

        h = compute_hash(event.title, event.source)
        now_iso = datetime.now(timezone.utc).isoformat()
        sheets = SheetsClient()
        sheets.batch_append(
            "BREAKING_LOG",
            [
                [
                    f"manual_{int(datetime.now(timezone.utc).timestamp())}",
                    now_iso,
                    event.title,
                    h,
                    event.source,
                    severity,
                    "sent",
                    event.url,
                    now_iso,
                ]
            ],
        )
        print("[INFO] BREAKING_LOG row appended", file=sys.stderr)
    except Exception as e:
        # Non-fatal: TG already sent. Operator can fix sheet manually.
        print(f"[WARN] BREAKING_LOG append failed (TG already sent): {e}", file=sys.stderr)

    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry. Returns process exit code."""
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    return asyncio.run(
        ingest_one_url(
            url=args.url,
            severity=args.severity,
            source_name=args.source_name,
            dry_run=args.dry_run,
            skip_dedup=args.skip_dedup,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
