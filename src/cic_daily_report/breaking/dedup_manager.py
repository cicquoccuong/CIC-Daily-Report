"""Alert Dedup & Cooldown Manager (Story 5.4) — prevents duplicate breaking alerts.

Uses hash(title + source) checked against BREAKING_LOG sheet.
4h TTL cooldown, 7-day auto-cleanup.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

from cic_daily_report.breaking.event_detector import BreakingEvent
from cic_daily_report.core.logger import get_logger

logger = get_logger("dedup_manager")

COOLDOWN_HOURS = 4
CLEANUP_DAYS = 7


@dataclass
class DedupEntry:
    """A single entry in BREAKING_LOG."""

    hash: str
    title: str
    source: str
    severity: str = ""
    detected_at: str = ""
    status: str = "pending"  # sent / deferred / skipped / deferred_to_morning / deferred_to_daily
    delivered_at: str = ""
    url: str = ""  # v0.19.0: store URL for deferred event reprocessing

    def to_row(self) -> list[str]:
        """Convert to sheet row.

        Schema: ID, Thời gian, Tiêu đề, Hash, Nguồn, Mức độ, Trạng thái gửi, URL, Thời gian gửi
        """
        return [
            "",  # ID
            self.detected_at,
            self.title,
            self.hash,
            self.source,
            self.severity,
            self.status,
            self.url,
            self.delivered_at,
        ]

    @staticmethod
    def from_row(row: list[str]) -> DedupEntry:
        """Create from sheet row.

        Schema: ID, Thời gian, Tiêu đề, Hash, Nguồn, Mức độ, Trạng thái gửi, URL, Thời gian gửi
        """
        return DedupEntry(
            hash=row[3] if len(row) > 3 else "",
            title=row[2] if len(row) > 2 else "",
            source=row[4] if len(row) > 4 else "",
            severity=row[5] if len(row) > 5 else "",
            detected_at=row[1] if len(row) > 1 else "",
            status=row[6] if len(row) > 6 else "",
            url=row[7] if len(row) > 7 else "",
            delivered_at=row[8] if len(row) > 8 else "",
        )


@dataclass
class DedupResult:
    """Result of dedup check on a batch of events."""

    new_events: list[BreakingEvent] = field(default_factory=list)
    duplicates_skipped: int = 0
    entries_written: list[DedupEntry] = field(default_factory=list)


def compute_hash(title: str, source: str) -> str:
    """Generate dedup hash from title + source."""
    raw = f"{title.strip().lower()}|{source.strip().lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


SIMILARITY_THRESHOLD = 0.70


def _is_similar_to_recent(
    title: str,
    recent_entries: list[DedupEntry],
    threshold: float = SIMILARITY_THRESHOLD,
) -> bool:
    """Check if title is similar to any recent entry (beyond hash match)."""
    title_lower = title.strip().lower()
    for entry in recent_entries:
        existing_lower = entry.title.strip().lower()
        ratio = SequenceMatcher(None, title_lower, existing_lower).ratio()
        if ratio >= threshold:
            logger.info(f"Similarity dedup: '{title[:50]}' ~ '{entry.title[:50]}' ({ratio:.2f})")
            return True
    return False


class DedupManager:
    """Manages dedup state via BREAKING_LOG entries."""

    # Status priority — higher = more progressed (used for dedup on load)
    _STATUS_PRIORITY = {
        "sent": 5,
        "permanently_failed": 4,
        "generation_failed": 3,
        "deferred_to_morning": 2,
        "deferred_to_daily": 2,
        "skipped": 1,
        "pending": 0,
    }

    def __init__(self, existing_entries: list[DedupEntry] | None = None) -> None:
        raw = existing_entries or []
        # Dedup by hash — keep entry with most-progressed status (B1)
        best: dict[str, DedupEntry] = {}
        for entry in raw:
            existing = best.get(entry.hash)
            if existing is None:
                best[entry.hash] = entry
            else:
                new_pri = self._STATUS_PRIORITY.get(entry.status, 0)
                old_pri = self._STATUS_PRIORITY.get(existing.status, 0)
                if new_pri > old_pri:
                    best[entry.hash] = entry
        self._entries = list(best.values())
        self._hash_map = best

    @property
    def entries(self) -> list[DedupEntry]:
        return self._entries

    def check_and_filter(
        self,
        events: list[BreakingEvent],
    ) -> DedupResult:
        """Filter out duplicate events based on hash + 4h cooldown.

        Args:
            events: Detected breaking events to check.

        Returns:
            DedupResult with new (non-duplicate) events and stats.
        """
        result = DedupResult()
        now = datetime.now(timezone.utc)

        for event in events:
            h = compute_hash(event.title, event.source)

            if self._is_duplicate(h, now):
                result.duplicates_skipped += 1
                logger.info(f"Dedup: skipped duplicate event '{event.title}'")
                continue

            # Similarity check — catch near-duplicates with different wording
            # Only check against entries within cooldown window
            recent_entries = [e for e in self._entries if not self._is_cooldown_expired(e, now)]
            if _is_similar_to_recent(event.title, recent_entries):
                result.duplicates_skipped += 1
                logger.info(f"Dedup: skipped similar event '{event.title}'")
                continue

            # New event — add to entries
            entry = DedupEntry(
                hash=h,
                title=event.title,
                source=event.source,
                detected_at=now.isoformat(),
                status="pending",
                url=event.url,
            )
            self._entries.append(entry)
            self._hash_map[h] = entry
            result.new_events.append(event)
            result.entries_written.append(entry)

        logger.info(
            f"Dedup: {len(result.new_events)} new, {result.duplicates_skipped} duplicates skipped"
        )
        return result

    def _is_duplicate(self, hash_value: str, now: datetime) -> bool:
        """Check if hash exists within the cooldown window."""
        existing = self._hash_map.get(hash_value)
        if not existing:
            return False
        return not self._is_cooldown_expired(existing, now)

    def _is_cooldown_expired(self, entry: DedupEntry, now: datetime) -> bool:
        """Check if an entry's cooldown has expired."""
        if not entry.detected_at:
            return False  # No timestamp — treat as within cooldown

        try:
            detected = datetime.fromisoformat(entry.detected_at)
            # Ensure timezone-aware to avoid TypeError on subtraction
            if detected.tzinfo is None:
                detected = detected.replace(tzinfo=timezone.utc)
            age = now - detected
            return age >= timedelta(hours=COOLDOWN_HOURS)
        except (ValueError, TypeError):
            return False  # Can't parse timestamp — treat as within cooldown

    def cleanup_old_entries(self) -> int:
        """Remove entries older than CLEANUP_DAYS. Returns count removed."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=CLEANUP_DAYS)
        original_count = len(self._entries)

        kept: list[DedupEntry] = []
        for entry in self._entries:
            if not entry.detected_at:
                continue  # Remove entries without timestamp
            try:
                detected = datetime.fromisoformat(entry.detected_at)
                if detected.tzinfo is None:
                    detected = detected.replace(tzinfo=timezone.utc)
                if detected >= cutoff:
                    kept.append(entry)
            except (ValueError, TypeError):
                continue  # Remove malformed entries

        self._entries = kept
        self._hash_map = {e.hash: e for e in self._entries}
        removed = original_count - len(self._entries)

        if removed > 0:
            logger.info(f"Cleanup: removed {removed} old entries from BREAKING_LOG")
        return removed

    def update_entry_status(
        self,
        hash_value: str,
        status: str,
        delivered_at: str = "",
        severity: str = "",
    ) -> bool:
        """Update status (and optionally severity) of an entry by hash."""
        entry = self._hash_map.get(hash_value)
        if not entry:
            return False
        entry.status = status
        if delivered_at:
            entry.delivered_at = delivered_at
        if severity:
            entry.severity = severity
        return True

    def get_deferred_events(self, status_filter: str = "deferred_to_morning") -> list[DedupEntry]:
        """Get entries with a specific deferred status."""
        return [e for e in self._entries if e.status == status_filter]

    def all_rows(self) -> list[list[str]]:
        """Get all entries as sheet rows (for batch_update)."""
        return [e.to_row() for e in self._entries]
