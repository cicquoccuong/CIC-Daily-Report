"""Breaking news feedback loop -- save today's events for daily pipeline.

P1.10: Breaking events detected during the day are saved to a lightweight
JSON file. When the daily pipeline runs (08:05 VN), it reads this file to
include breaking context in the Master Analysis / tier articles.

The JSON file is ephemeral -- it resets daily and is never committed to git.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from cic_daily_report.core.logger import get_logger

logger = get_logger("breaking_feedback")

# WHY parent.parent.parent.parent: feedback.py lives at
#   src/cic_daily_report/breaking/feedback.py
# so 4 parents up = project root, then into data/
_FEEDBACK_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"
_FEEDBACK_FILE = _FEEDBACK_DIR / "breaking_today.json"


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

    payload = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "events": existing,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }

    _FEEDBACK_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Breaking feedback saved: {len(events)} new events ({len(existing)} total today)")


def read_breaking_summary() -> str:
    """Read today's breaking events for daily pipeline context.

    Returns formatted text for LLM context injection, or empty string.
    Only returns events from TODAY (UTC).
    """
    if not _FEEDBACK_FILE.exists():
        return ""

    try:
        data = json.loads(_FEEDBACK_FILE.read_text(encoding="utf-8"))
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if data.get("date") != today:
            return ""  # WHY: Stale data from yesterday — don't inject outdated context

        events = data.get("events", [])
        if not events:
            return ""

        lines = [f"=== BREAKING NEWS HOM NAY ({len(events)} tin) ==="]
        for e in events:
            severity = e.get("severity", "")
            title = e.get("title", "")
            summary = e.get("summary", "")[:200]
            lines.append(f"- [{severity.upper()}] {title}")
            if summary:
                lines.append(f"  {summary}")

        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Breaking feedback read failed: {e}")
        return ""
