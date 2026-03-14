"""Alert Dedup & Cooldown Manager (Story 5.4) — prevents duplicate breaking alerts.

Uses hash(title + source) checked against BREAKING_LOG sheet.
4h TTL cooldown, 7-day auto-cleanup.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

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

        Schema: ID, Thời gian, Tiêu đề, Hash, Nguồn, Mức độ, Trạng thái gửi, URL
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
        ]

    @staticmethod
    def from_row(row: list[str]) -> DedupEntry:
        """Create from sheet row.

        Schema: ID, Thời gian, Tiêu đề, Hash, Nguồn, Mức độ, Trạng thái gửi, URL
        """
        return DedupEntry(
            hash=row[3] if len(row) > 3 else "",
            title=row[2] if len(row) > 2 else "",
            source=row[4] if len(row) > 4 else "",
            severity=row[5] if len(row) > 5 else "",
            detected_at=row[1] if len(row) > 1 else "",
            status=row[6] if len(row) > 6 else "",
            url=row[7] if len(row) > 7 else "",
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


class DedupManager:
    """Manages dedup state via BREAKING_LOG entries."""

    def __init__(self, existing_entries: list[DedupEntry] | None = None) -> None:
        self._entries = existing_entries or []
        self._hash_map: dict[str, DedupEntry] = {e.hash: e for e in self._entries}

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

        if not existing.detected_at:
            return True  # Hash exists but no timestamp — treat as duplicate

        try:
            detected = datetime.fromisoformat(existing.detected_at)
            # Ensure timezone-aware to avoid TypeError on subtraction
            if detected.tzinfo is None:
                detected = detected.replace(tzinfo=timezone.utc)
            age = now - detected
            return age < timedelta(hours=COOLDOWN_HOURS)
        except (ValueError, TypeError):
            return True  # Can't parse timestamp — treat as duplicate

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

    def update_entry_status(self, hash_value: str, status: str, delivered_at: str = "") -> bool:
        """Update status of an entry by hash."""
        entry = self._hash_map.get(hash_value)
        if not entry:
            return False
        entry.status = status
        if delivered_at:
            entry.delivered_at = delivered_at
        return True

    def get_deferred_events(self, status_filter: str = "deferred_to_morning") -> list[DedupEntry]:
        """Get entries with a specific deferred status."""
        return [e for e in self._entries if e.status == status_filter]

    def all_rows(self) -> list[list[str]]:
        """Get all entries as sheet rows (for batch_update)."""
        return [e.to_row() for e in self._entries]
