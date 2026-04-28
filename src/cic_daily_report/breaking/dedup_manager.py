"""Alert Dedup & Cooldown Manager (Story 5.4) — prevents duplicate breaking alerts.

Uses hash(title + source) checked against BREAKING_LOG sheet.
12h TTL cooldown, 7-day auto-cleanup.

QO.30 (Wave 3): COOLDOWN_HOURS, SIMILARITY_THRESHOLD, ENTITY_OVERLAP_THRESHOLD
now configurable from CAU_HINH via config_loader. Module-level constants kept
as DEFAULT FALLBACK.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

from cic_daily_report.breaking.event_detector import BreakingEvent
from cic_daily_report.core.coin_mapping import NAME_TO_TICKER
from cic_daily_report.core.logger import get_logger

logger = get_logger("dedup_manager")

# QO.30: Constants kept as DEFAULT FALLBACK — actual values read from
# CAU_HINH at runtime via DedupManager constructor.
COOLDOWN_HOURS = 12  # WHY: 4h too short with 3h interval → duplicates (VD-02)
CLEANUP_DAYS = 7

# QO.12: Metric-type dedup keywords for pattern-matching
# WHY separate: F&G and BTC/ETH price drops repeat frequently in CryptoPanic,
# causing VD-01 (F&G 4-5x/day) and noisy price updates.
_FG_KEYWORDS = {"fear & greed", "fear and greed", "f&g", "extreme fear", "extreme greed"}
_BTC_ETH_DROP_KEYWORDS = {"btc", "bitcoin", "eth", "ethereum"}
_PRICE_DROP_INDICATORS = {"drop", "crash", "fall", "plunge", "dump", "decline", "tumble", "sink"}

# QO.12: Minimum price delta (%) to re-send BTC/ETH drop alerts
METRIC_DEDUP_PRICE_DELTA = 5.0


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


def _extract_percentage(title: str) -> float | None:
    """Extract first percentage value from a title (e.g., '7.5%' → 7.5).

    QO.12: Used for BTC/ETH price drop delta comparison.
    Returns None if no percentage found.
    """
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", title)
    if match:
        return float(match.group(1))
    return None


# QO.30: Module-level defaults — runtime values read from CAU_HINH in DedupManager.
# Wave 0.5 (alpha.18): SIMILARITY_THRESHOLD lowered 0.70 → 0.55 after audit found
# regulatory-bill near-duplicates passing through (e.g., "Canada Bill C-25 crypto"
# vs "Canada cấm crypto donate" both about same bill but worded differently).
SIMILARITY_THRESHOLD = 0.55
ENTITY_OVERLAP_THRESHOLD = 0.60  # v0.28.0: entity-based dedup

# Wave 0.5 (alpha.18): Regulatory bill ID detector — when two titles reference the
# same bill ID (e.g., "Bill C-25", "MiCA", "FIT21", "GENIUS Act"), they describe
# the same regulatory event and should be auto-flagged as duplicates regardless
# of wording similarity. Bypasses the SequenceMatcher threshold entirely.
_REG_BILL_PATTERNS = [
    re.compile(r"\bBill\s+[A-Z]-\d+\b", re.IGNORECASE),
    re.compile(r"\b(?:MiCA|FIT21|GENIUS\s+Act|CLARITY\s+Act)\b", re.IGNORECASE),
]


def _extract_reg_bill_ids(title: str) -> set[str]:
    """Wave 0.5: Extract regulatory bill identifiers from a title.

    WHY: Two articles about the same bill (different wording, different angles)
    must be flagged as duplicates. Returns lowercased canonical IDs for set
    intersection with another title's IDs.
    """
    ids: set[str] = set()
    for pat in _REG_BILL_PATTERNS:
        for m in pat.findall(title):
            ids.add(m.lower().strip())
    return ids


# Named entities: crypto projects, companies, regulatory bodies, key figures
_ENTITY_PATTERN = re.compile(
    r"\b("
    r"BTC|ETH|SOL|BNB|XRP|ADA|DOGE|AVAX|DOT|MATIC|LINK|UNI|ATOM|LTC|NEAR|APT|ARB|OP|SUI"
    r"|Bitcoin|Ethereum|Solana|Ripple|Cardano|Dogecoin"
    r"|Binance|Coinbase|Kraken|OKX|Bybit|MEXC|Bitget|Kalshi|Robinhood"
    # QO.13: Expanded regulatory bodies — international + VN-specific
    r"|SEC|CFTC|DOJ|FBI|Fed|ECB|MiCA|FATF"
    r"|BOJ|PBOC|IMF|ONUS|VASP|SBV|RBI"
    r"|BlackRock|Fidelity|Grayscale|MicroStrategy|Tesla|Tether|Circle"
    r"|Trump|Gensler|Powell|CZ|SBF|Vitalik"
    r"|Nevada|California|Wyoming|Congress|Senate|House"
    # WHY: Expand entity coverage to reduce false negatives in dedup
    # for DeFi, stablecoin, geopolitical, security, and institutional news
    r"|Drift|Aave|Compound|Maker|MakerDAO|Lido|Uniswap|Curve|dYdX|GMX|Pendle|Ethena|Morpho|Balancer|Yearn|Frax"
    r"|USDC|USDT|DAI|USDS|USDe|FDUSD|TUSD|BUSD"
    # QO.13: Expanded country list — key crypto-regulatory jurisdictions
    r"|Canada|China|Japan|Korea|India|Russia|Iran|Israel|UK|Australia|Singapore|Brazil|Vietnam"
    r"|EU|Turkey|Thailand|Indonesia|Philippines|Argentina|Nigeria|UAE|Switzerland|Germany|France"
    r"|hack|exploit|hacker|attack|bridge|oracle|vulnerability|breach|stolen|drain"
    r"|VanEck|ARK|Franklin|JPMorgan"
    r")\b",
    re.IGNORECASE,
)


# Build dedup synonym dict from shared coin_mapping (lowercase → lowercase ticker).
# Also includes people/org aliases not in coin_mapping.
_ENTITY_SYNONYMS: dict[str, str] = {k: v.lower() for k, v in NAME_TO_TICKER.items()}
_ENTITY_SYNONYMS.update(
    {
        "changpeng zhao": "cz",
        "sam bankman-fried": "sbf",
        "vitalik buterin": "vitalik",
        "strategy": "microstrategy",  # rebranded 2025
    }
)


def _extract_entities(title: str) -> set[str]:
    """Extract named entities from a title for entity-based dedup.

    Applies synonym normalization so "Ripple" and "XRP" map to the same
    canonical entity, improving Jaccard overlap for duplicate detection.
    """
    raw = {m.lower() for m in _ENTITY_PATTERN.findall(title)}
    return {_ENTITY_SYNONYMS.get(e, e) for e in raw}


def _is_entity_overlap(
    title: str,
    recent_entries: list[DedupEntry],
    threshold: float = ENTITY_OVERLAP_THRESHOLD,
) -> bool:
    """Check if a new title shares too many entities with a recent entry.

    v0.28.0: Catches cases where different English titles describe the same event
    (e.g., "Kalshi launches crypto prediction market" and "Nevada licenses Kalshi for crypto").

    v0.32.0: When only 1 entity extracted, require BOTH entity match AND title
    similarity >= 0.50. Previously required >= 2 entities which missed single-entity
    duplicate stories (e.g., two different articles both about "Binance").
    """
    new_entities = _extract_entities(title)
    if len(new_entities) == 0:
        return False  # No entities to compare

    title_lower = title.strip().lower()

    for entry in recent_entries:
        existing_entities = _extract_entities(entry.title)
        if not existing_entities:
            continue
        overlap = new_entities & existing_entities

        if len(new_entities) == 1:
            # WHY: Single entity match alone is too aggressive (many articles mention "BTC").
            # Require entity match + title similarity >= 0.50 as dual confirmation.
            if overlap:
                existing_lower = entry.title.strip().lower()
                ratio = SequenceMatcher(None, title_lower, existing_lower).ratio()
                if ratio >= 0.50:
                    logger.info(
                        f"Entity dedup (1-entity+sim): '{title[:50]}' overlaps "
                        f"'{entry.title[:50]}' (entity: {overlap}, sim: {ratio:.2f})"
                    )
                    return True
        else:
            # Jaccard similarity on entities (original logic for >= 2 entities)
            union = new_entities | existing_entities
            if union and len(overlap) / len(union) >= threshold:
                logger.info(
                    f"Entity dedup: '{title[:50]}' overlaps "
                    f"'{entry.title[:50]}' (entities: {overlap})"
                )
                return True
    return False


def _is_similar_to_recent(
    title: str,
    recent_entries: list[DedupEntry],
    threshold: float = SIMILARITY_THRESHOLD,
) -> bool:
    """Check if title is similar to any recent entry (beyond hash match).

    Wave 0.5 (alpha.18): Bill ID auto-dedup added — same regulatory bill ID
    (Bill C-XX, MiCA, FIT21, GENIUS Act) in both titles → flagged as duplicate
    regardless of similarity ratio.
    """
    title_lower = title.strip().lower()
    new_bill_ids = _extract_reg_bill_ids(title)
    for entry in recent_entries:
        existing_lower = entry.title.strip().lower()

        # Wave 0.5: Regulatory bill ID match → instant duplicate (bypass ratio).
        if new_bill_ids:
            existing_bill_ids = _extract_reg_bill_ids(entry.title)
            shared = new_bill_ids & existing_bill_ids
            if shared:
                logger.info(
                    f"Bill ID dedup: '{title[:50]}' shares bill {shared} with '{entry.title[:50]}'"
                )
                return True

        ratio = SequenceMatcher(None, title_lower, existing_lower).ratio()
        if ratio >= threshold:
            logger.info(f"Similarity dedup: '{title[:50]}' ~ '{entry.title[:50]}' ({ratio:.2f})")
            return True
    return False


class DedupManager:
    """Manages dedup state via BREAKING_LOG entries."""

    # Status priority — higher = more progressed (used for dedup on load)
    # v0.29.1 (BUG 3): Added sent_digest, delivery_failed, deferred_overflow
    _STATUS_PRIORITY = {
        "sent": 5,
        "sent_digest": 5,
        "permanently_failed": 4,
        "delivery_failed": 4,
        "generation_failed": 3,
        "deferred_overflow": 2,
        "deferred_to_morning": 2,
        "deferred_to_daily": 2,
        "skipped": 1,
        "pending": 0,
    }

    def __init__(
        self,
        existing_entries: list[DedupEntry] | None = None,
        config_loader: object | None = None,
    ) -> None:
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

        # QO.30: Read dedup thresholds from CAU_HINH at runtime.
        # WHY in __init__: DedupManager is created once per pipeline run, so
        # config is read once and cached for the entire run (no repeated API calls).
        self._cooldown_hours = COOLDOWN_HOURS
        self._similarity_threshold = SIMILARITY_THRESHOLD
        self._entity_overlap_threshold = ENTITY_OVERLAP_THRESHOLD
        if config_loader is not None:
            try:
                self._cooldown_hours = config_loader.get_setting_int(
                    "COOLDOWN_HOURS", COOLDOWN_HOURS
                )
                self._similarity_threshold = config_loader.get_setting_float(
                    "SIMILARITY_THRESHOLD", SIMILARITY_THRESHOLD
                )
                self._entity_overlap_threshold = config_loader.get_setting_float(
                    "ENTITY_OVERLAP_THRESHOLD", ENTITY_OVERLAP_THRESHOLD
                )
            except Exception as e:
                # WHY: Never break dedup if config read fails — use module defaults
                logger.warning(f"Config read failed for dedup thresholds, using defaults: {e}")

    @property
    def entries(self) -> list[DedupEntry]:
        return self._entries

    def check_and_filter(
        self,
        events: list[BreakingEvent],
    ) -> DedupResult:
        """Filter out duplicate events based on URL + hash + similarity + entity overlap.

        v0.30.0: Added URL-based dedup as first check — same URL = same article,
        regardless of title/source differences across runs.

        QO.12: Added metric-type dedup — F&G max 1/day, BTC/ETH drops only on
        significant delta (>= 5% from last sent value).

        Args:
            events: Detected breaking events to check.

        Returns:
            DedupResult with new (non-duplicate) events and stats.
        """
        result = DedupResult()
        now = datetime.now(timezone.utc)

        for event in events:
            # v0.30.0: URL-based dedup — same URL = same article, guaranteed
            if event.url and self._is_url_duplicate(event.url, now):
                result.duplicates_skipped += 1
                logger.info(f"Dedup: skipped URL-match event '{event.title}'")
                continue

            h = compute_hash(event.title, event.source)

            if self._is_duplicate(h, now):
                result.duplicates_skipped += 1
                logger.info(f"Dedup: skipped duplicate event '{event.title}'")
                continue

            # QO.12: Metric-type dedup — F&G max 1/day, BTC/ETH price drops
            # only when delta >= 5% from last sent value
            if self._is_metric_duplicate(event, now):
                result.duplicates_skipped += 1
                continue

            # Similarity check — catch near-duplicates with different wording
            # Only check against entries within cooldown window
            recent_entries = [e for e in self._entries if not self._is_cooldown_expired(e, now)]
            # QO.30: Use instance thresholds from config (not module-level constants)
            if _is_similar_to_recent(
                event.title, recent_entries, threshold=self._similarity_threshold
            ):
                result.duplicates_skipped += 1
                logger.info(f"Dedup: skipped similar event '{event.title}'")
                continue

            # v0.28.0: Entity-based dedup — catch same-event with different wording
            # QO.30: Use instance threshold from config
            if _is_entity_overlap(
                event.title, recent_entries, threshold=self._entity_overlap_threshold
            ):
                result.duplicates_skipped += 1
                logger.info(f"Dedup: skipped entity-overlap event '{event.title}'")
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

    def _is_metric_duplicate(self, event: BreakingEvent, now: datetime) -> bool:
        """QO.12: Metric-type dedup for recurring data-driven events.

        Rules:
        - F&G (Fear & Greed): Max 1 message per calendar day (UTC).
          If any F&G event was already sent/pending today, skip.
        - BTC/ETH price drops: Only send if the percentage in the title
          differs by >= METRIC_DEDUP_PRICE_DELTA from the last sent value.

        WHY: F&G and BTC/ETH price drops are the noisiest event types
        (VD-01: F&G repeated 4-5x/day). Normal dedup misses them because
        each instance has a slightly different title/score.
        """
        title_lower = event.title.lower()
        today = now.date()

        # --- F&G dedup: max 1 per calendar day ---
        if any(kw in title_lower for kw in _FG_KEYWORDS):
            for entry in self._entries:
                if not entry.detected_at:
                    continue
                try:
                    entry_time = datetime.fromisoformat(entry.detected_at)
                    if entry_time.tzinfo is None:
                        entry_time = entry_time.replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    continue
                if entry_time.date() != today:
                    continue
                entry_lower = entry.title.lower()
                if any(kw in entry_lower for kw in _FG_KEYWORDS):
                    logger.info(
                        f"QO.12: F&G dedup — already sent today, skipping '{event.title[:50]}'"
                    )
                    return True
            return False

        # --- BTC/ETH price drop dedup: only on significant delta ---
        has_asset = any(kw in title_lower for kw in _BTC_ETH_DROP_KEYWORDS)
        has_drop = any(kw in title_lower for kw in _PRICE_DROP_INDICATORS)
        if has_asset and has_drop:
            new_pct = _extract_percentage(event.title)
            if new_pct is None:
                return False  # No percentage found — let normal dedup handle it

            for entry in self._entries:
                if not entry.detected_at:
                    continue
                try:
                    entry_time = datetime.fromisoformat(entry.detected_at)
                    if entry_time.tzinfo is None:
                        entry_time = entry_time.replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    continue
                if entry_time.date() != today:
                    continue
                entry_lower = entry.title.lower()
                entry_has_asset = any(kw in entry_lower for kw in _BTC_ETH_DROP_KEYWORDS)
                entry_has_drop = any(kw in entry_lower for kw in _PRICE_DROP_INDICATORS)
                if not (entry_has_asset and entry_has_drop):
                    continue
                old_pct = _extract_percentage(entry.title)
                if old_pct is not None and abs(new_pct - old_pct) < METRIC_DEDUP_PRICE_DELTA:
                    logger.info(
                        f"QO.12: BTC/ETH drop dedup — delta {abs(new_pct - old_pct):.1f}% "
                        f"< {METRIC_DEDUP_PRICE_DELTA}%, skipping '{event.title[:50]}'"
                    )
                    return True
            return False

        return False

    def _is_url_duplicate(self, url: str, now: datetime) -> bool:
        """Check if URL matches any entry within 7-day window.

        v0.30.0: URL-based dedup catches the same article across runs even when
        the AI-generated title differs (which changes the hash). Same URL = same
        underlying article, so this is the most reliable dedup signal.

        v0.32.0: Uses 7-day window (CLEANUP_DAYS) instead of 4h cooldown.
        WHY: Same URL = same article regardless of time. Only expire when
        the entry would be cleaned up anyway.
        """
        url_lower = url.strip().lower()
        for entry in self._entries:
            if entry.url and entry.url.strip().lower() == url_lower:
                if not self._is_url_cooldown_expired(entry, now):
                    return True
        return False

    def _is_url_cooldown_expired(self, entry: DedupEntry, now: datetime) -> bool:
        """URL-based dedup uses 7-day window (same as cleanup cycle).

        Same URL = same article regardless of time. Only expire when
        the entry would be cleaned up anyway.
        """
        if not entry.detected_at:
            return False
        try:
            detected = datetime.fromisoformat(entry.detected_at)
            if detected.tzinfo is None:
                detected = detected.replace(tzinfo=timezone.utc)
            age = now - detected
            return age >= timedelta(days=CLEANUP_DAYS)
        except (ValueError, TypeError):
            return False

    def _is_duplicate(self, hash_value: str, now: datetime) -> bool:
        """Check if hash exists within the cooldown window."""
        existing = self._hash_map.get(hash_value)
        if not existing:
            return False
        return not self._is_cooldown_expired(existing, now)

    def _is_cooldown_expired(self, entry: DedupEntry, now: datetime) -> bool:
        """Check if an entry's cooldown has expired.

        QO.30: Uses self._cooldown_hours (from config) instead of module constant.
        """
        if not entry.detected_at:
            return False  # No timestamp — treat as within cooldown

        try:
            detected = datetime.fromisoformat(entry.detected_at)
            # Ensure timezone-aware to avoid TypeError on subtraction
            if detected.tzinfo is None:
                detected = detected.replace(tzinfo=timezone.utc)
            age = now - detected
            return age >= timedelta(hours=self._cooldown_hours)
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
