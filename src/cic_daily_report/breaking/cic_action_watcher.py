"""CIC Action Watcher (QO.42).

Detects changes in CIC Sentinel's cic_action column and creates
BreakingEvent objects for the breaking pipeline. Compares current
Sentinel registry state with a previous snapshot stored in BREAKING_LOG.

Example: BTC's cic_action changes from "theo-doi" to "mua" →
generates a breaking event: "CIC cap nhat: BTC chuyen tu 'theo-doi' sang 'mua'"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from cic_daily_report.breaking.event_detector import BreakingEvent
from cic_daily_report.core.logger import get_logger

logger = get_logger("cic_action_watcher")

# WHY: cic_action values used by Sentinel scoring engine.
# Changes between these values are meaningful signals for CIC members.
KNOWN_ACTIONS = {"mua", "theo-doi", "giam", "ban", "ngung"}

# WHY prefix: Breaking events from this source are tagged for dedup manager.
# Using a distinct source prevents collision with CryptoPanic/RSS events.
EVENT_SOURCE = "cic_sentinel_action"


@dataclass
class ActionChange:
    """Represents a single cic_action change for one coin."""

    symbol: str
    old_action: str
    new_action: str
    timestamp: str = ""

    def to_event_title(self) -> str:
        """Format as user-friendly Vietnamese event title.

        WHY Vietnamese: All user-facing text in CIC Daily Report is Vietnamese.
        """
        return f"CIC cap nhat: {self.symbol} chuyen tu '{self.old_action}' sang '{self.new_action}'"


@dataclass
class ActionSnapshot:
    """Snapshot of all cic_action values at a point in time.

    WHY dataclass: easy to serialize/compare. The snapshot is stored
    as a dict[symbol, action] for O(1) lookup during comparison.
    """

    actions: dict[str, str] = field(default_factory=dict)
    timestamp: str = ""


def detect_action_changes(
    current_registry: list,
    previous_snapshot: ActionSnapshot | None = None,
) -> tuple[list[BreakingEvent], ActionSnapshot]:
    """Compare current Sentinel registry with previous snapshot.

    Args:
        current_registry: List of SentinelCoin objects from sentinel_reader.read_registry().
        previous_snapshot: Previous action snapshot. If None, creates initial snapshot
            (no changes detected on first run — this is intentional to avoid
            flooding on first deployment).

    Returns:
        Tuple of (list of BreakingEvent for changed actions, new snapshot).
        The new snapshot should be stored for the next comparison.

    WHY return tuple: Caller needs both the events AND the updated snapshot
    to persist for the next pipeline run.
    """
    now = datetime.now(timezone.utc).isoformat()
    events: list[BreakingEvent] = []

    # Build current snapshot from registry
    current = ActionSnapshot(timestamp=now)
    for coin in current_registry:
        symbol = getattr(coin, "symbol", "")
        action = getattr(coin, "cic_action", "")
        if symbol and action:
            current.actions[symbol] = action.lower().strip()

    if not current.actions:
        logger.info("Action watcher: no coins with cic_action in registry")
        return [], current

    if previous_snapshot is None:
        # First run — establish baseline, no events
        logger.info(f"Action watcher: initial snapshot created ({len(current.actions)} coins)")
        return [], current

    # Compare current vs previous
    changes: list[ActionChange] = []
    for symbol, new_action in current.actions.items():
        old_action = previous_snapshot.actions.get(symbol, "")
        if old_action and old_action != new_action:
            change = ActionChange(
                symbol=symbol,
                old_action=old_action,
                new_action=new_action,
                timestamp=now,
            )
            changes.append(change)
            logger.info(f"Action change detected: {symbol} '{old_action}' → '{new_action}'")

    # Convert changes to BreakingEvent objects
    for change in changes:
        event = BreakingEvent(
            title=change.to_event_title(),
            source=EVENT_SOURCE,
            url="",  # WHY empty: internal signal, no external URL
            panic_score=75,  # WHY 75: above default threshold (70) to ensure detection
            detected_at=datetime.now(timezone.utc),
            raw_data={
                "symbol": change.symbol,
                "old_action": change.old_action,
                "new_action": change.new_action,
                "change_type": "cic_action",
            },
        )
        events.append(event)

    if changes:
        logger.info(f"Action watcher: {len(changes)} changes → {len(events)} events")
    else:
        logger.debug("Action watcher: no changes detected")

    return events, current


def load_previous_snapshot(dedup_entries: list) -> ActionSnapshot | None:
    """Reconstruct previous action snapshot from BREAKING_LOG entries.

    WHY from dedup: We don't want a separate storage mechanism for snapshots.
    The BREAKING_LOG already has sent cic_action events with old/new values
    in the title. We parse these to reconstruct the last known state.

    Args:
        dedup_entries: List of DedupEntry objects from dedup_manager.

    Returns:
        ActionSnapshot or None if no previous cic_action events found.
    """
    # WHY: Look for entries from our source to find the most recent actions
    latest_actions: dict[str, str] = {}
    found_any = False

    for entry in dedup_entries:
        source = getattr(entry, "source", "")
        if source != EVENT_SOURCE:
            continue

        found_any = True
        title = getattr(entry, "title", "")
        # Parse title format: "CIC cap nhat: BTC chuyen tu 'theo-doi' sang 'mua'"
        # Extract symbol and new_action
        parsed = _parse_action_title(title)
        if parsed:
            symbol, new_action = parsed
            latest_actions[symbol] = new_action

    if not found_any:
        return None

    return ActionSnapshot(actions=latest_actions)


def _parse_action_title(title: str) -> tuple[str, str] | None:
    """Parse an action change title to extract symbol and new action.

    Expected format: "CIC cap nhat: SYMBOL chuyen tu 'old' sang 'new'"
    Returns (symbol, new_action) or None if parsing fails.
    """
    # WHY simple parsing: title format is controlled by us (to_event_title),
    # so we can rely on the structure.
    try:
        if "chuyen tu" not in title or "sang" not in title:
            return None

        # Extract symbol after "CIC cap nhat: "
        prefix = "CIC cap nhat: "
        if not title.startswith(prefix):
            return None

        rest = title[len(prefix) :]
        parts = rest.split(" chuyen tu ")
        if len(parts) != 2:
            return None

        symbol = parts[0].strip()

        # Extract new_action from "sang 'new_action'"
        sang_parts = parts[1].split(" sang ")
        if len(sang_parts) != 2:
            return None

        new_action = sang_parts[1].strip().strip("'")
        return symbol, new_action
    except Exception:
        return None
