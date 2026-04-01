"""Breaking news feedback loop -- save today's events for daily pipeline.

P1.10: Breaking events detected during the day are saved to a lightweight
JSON file. When the daily pipeline runs (08:05 VN), it reads this file to
include breaking context in the Master Analysis / tier articles.

The JSON file is ephemeral -- it resets daily and is never committed to git.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cic_daily_report.core.logger import get_logger

logger = get_logger("breaking_feedback")

# WHY parent.parent.parent.parent: feedback.py lives at
#   src/cic_daily_report/breaking/feedback.py
# so 4 parents up = project root, then into data/
_FEEDBACK_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"
_FEEDBACK_FILE = _FEEDBACK_DIR / "breaking_today.json"

# SEC-02: Reject feedback files larger than 1MB to prevent memory issues.
MAX_FEEDBACK_FILE_SIZE = 1_000_000

# SEC-06: Cap events per day to prevent unbounded list growth.
MAX_EVENTS_PER_DAY = 100


def save_breaking_summary(events: list[dict]) -> None:
    """Save today's breaking events summary to JSON file.

    Each event dict should have: title, source, severity, timestamp, summary.

    Appends to existing file (multiple breaking runs per day).
    Resets at start of each new day (UTC).
    """
    _FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)

    existing: list[dict] = []
    if _FEEDBACK_FILE.exists():
        try:
            data = json.loads(_FEEDBACK_FILE.read_text(encoding="utf-8"))
            # WHY date check: Reset if stale data from yesterday
            if data.get("date") == datetime.now(timezone.utc).strftime("%Y-%m-%d"):
                existing = data.get("events", [])
        except (json.JSONDecodeError, KeyError):
            pass

    existing.extend(events)

    # SEC-06: Cap events per day to prevent unbounded list growth.
    if len(existing) > MAX_EVENTS_PER_DAY:
        existing = existing[-MAX_EVENTS_PER_DAY:]

    payload = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "events": existing,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }

    # BUG-10: Atomic write — write to temp file then rename.
    # WHY: Direct write_text() can corrupt JSON if process crashes mid-write.
    # os.replace() is atomic on most OS (POSIX guaranteed, Windows best-effort).
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(_FEEDBACK_DIR), suffix=".tmp")
    try:
        os.write(tmp_fd, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
        os.close(tmp_fd)
        os.replace(tmp_path, str(_FEEDBACK_FILE))
    except Exception:
        os.close(tmp_fd) if not _is_fd_closed(tmp_fd) else None
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    logger.info(f"Breaking feedback saved: {len(events)} new events ({len(existing)} total today)")


def _is_fd_closed(fd: int) -> bool:
    """Check if a file descriptor is already closed."""
    try:
        os.fstat(fd)
        return False
    except OSError:
        return True


def read_breaking_summary() -> str:
    """Read today's breaking events for daily pipeline context.

    Returns formatted text for LLM context injection, or empty string.
    Only returns events from TODAY (UTC).
    """
    if not _FEEDBACK_FILE.exists():
        return ""

    # SEC-02: Reject oversized feedback files to prevent memory issues.
    file_size = _FEEDBACK_FILE.stat().st_size
    if file_size > MAX_FEEDBACK_FILE_SIZE:
        logger.warning(f"Feedback file too large ({file_size} bytes), skipping")
        return ""

    try:
        data = json.loads(_FEEDBACK_FILE.read_text(encoding="utf-8"))
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        file_date = data.get("date", "")
        # R5-06: Include yesterday's events to catch late UTC breaking news.
        # WHY: Breaking uses UTC dates but daily pipeline runs at 01:05 UTC (08:05 VN).
        # Events detected at e.g. 23:00 UTC would be dated yesterday but still relevant.
        if file_date != today and file_date != yesterday:
            return ""  # WHY: Stale data from >1 day ago — don't inject outdated context

        events = data.get("events", [])
        if not events:
            return ""

        lines = [f"=== BREAKING NEWS HOM NAY ({len(events)} tin) ==="]
        for e in events:
            severity = e.get("severity", "")
            title = e.get("title", "")
            # WHY: 200 chars too short for LLM context (VD-20)
            summary = e.get("summary", "")[:1000]
            lines.append(f"- [{severity.upper()}] {title}")
            if summary:
                lines.append(f"  {summary}")

        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Breaking feedback read failed: {e}")
        return ""
