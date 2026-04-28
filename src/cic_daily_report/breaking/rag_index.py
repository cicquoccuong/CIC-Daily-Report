"""RAG mini — BM25 indexer for BREAKING_LOG (Wave 0.6 Story 0.6.1).

Scaffolding ONLY: this module reads historical breaking events from Sheets,
builds a BM25 index for keyword retrieval, and persists it to a local SQLite
cache. Story 0.6.2 will wire `query_historical_events()` into the LLM prompt
to inject ground-truth historical events instead of letting the model
fabricate (audit Wave 0.5.2: 87.5% of LLM "historical references" were wrong).

Storage hybrid:
- Source of truth: Google Sheets BREAKING_LOG (persistent across runs).
- Cache: data/rag_index.sqlite (ephemeral on GitHub Actions, persistent
  on local dev). Auto-rebuild when Sheets row count != cached doc_count.

Why BM25 over vectors:
- Pure Python (rank_bm25) — no native compile on GH Actions Linux runner.
- < 100ms query time, < 30s build time at ~1000 events scale.
- Adequate for keyword matching (event titles are short + entity-rich).
- Defer vector embeddings to Wave 1.0+ if scale > 10k events.
"""

from __future__ import annotations

import json
import pickle
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rank_bm25 import BM25Okapi

from cic_daily_report.core.logger import get_logger

if TYPE_CHECKING:
    from cic_daily_report.storage.sheets_client import SheetsClient

logger = get_logger("rag_index")

# WHY: Default cache path under data/ — already gitignored (P1.10 ephemeral
# data dir). On GH Actions runner, this is recreated each run.
_DEFAULT_SQLITE_PATH = Path("data") / "rag_index.sqlite"

# WHY: cache_key bumps when index format changes (e.g., tokenizer revamp).
_CACHE_KEY = "bm25_v1"

# WHY: Minimal stopword set covering Vietnamese + English noise tokens that
# add no retrieval signal. KEEP SHORT — over-aggressive stopwords hurt recall.
_STOPWORDS: set[str] = {
    # English
    "the",
    "a",
    "an",
    "of",
    "to",
    "in",
    "on",
    "at",
    "for",
    "and",
    "or",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "by",
    "with",
    "as",
    "it",
    "this",
    "that",
    "these",
    "those",
    "from",
    "but",
    "not",
    "no",
    # Vietnamese (no diacritics + with diacritics common forms)
    "la",
    "co",
    "khong",
    "duoc",
    "cua",
    "va",
    "voi",
    "den",
    "tu",
    "thi",
    "cho",
    "ra",
    "vao",
    "len",
    "xuong",
    "nay",
    "do",
    "kia",
    "mot",
    "hai",
    "là",
    "có",
    "không",
    "được",
    "của",
    "và",
    "với",
    "đến",
    "từ",
    "thì",
    "cho",
    "ra",
    "vào",
    "lên",
    "xuống",
    "này",
    "đó",
    "kia",
    "một",
}


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    """Lowercase + split on non-alphanumeric + drop stopwords + drop tokens len<2.

    WHY simple regex over NLP pipeline: BM25 is robust to noisy tokens; full
    NLP (spaCy/underthesea) adds 50MB+ deps and seconds of init for marginal
    gain on entity-heavy news titles.
    """
    if not text:
        return []
    # WHY \w+ Unicode-aware so Vietnamese chars survive; lowercase first
    tokens = re.findall(r"\w+", text.lower(), flags=re.UNICODE)
    return [t for t in tokens if len(t) >= 2 and t not in _STOPWORDS]


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass
class RAGEvent:
    """Historical event indexed in RAG. Mirrors BREAKING_LOG row + price ctx."""

    event_id: str
    title: str
    summary: str = ""
    source: str = ""
    severity: str = ""
    timestamp: str = ""  # ISO format
    btc_price: float | None = None
    eth_price: float | None = None
    fng_index: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_doc_text(self) -> str:
        """Concatenate title + summary for BM25 indexing."""
        return f"{self.title} {self.summary}".strip()


# ---------------------------------------------------------------------------
# RAGIndex class
# ---------------------------------------------------------------------------


class RAGIndex:
    """BM25 index over BREAKING_LOG events, backed by SQLite cache."""

    def __init__(
        self,
        sheets_client: "SheetsClient | None" = None,
        sqlite_path: Path | str | None = None,
    ):
        self._sheets = sheets_client
        self._sqlite_path = Path(sqlite_path) if sqlite_path else _DEFAULT_SQLITE_PATH
        self._events: list[RAGEvent] = []
        self._bm25: BM25Okapi | None = None
        self._tokenized_corpus: list[list[str]] = []
        # WHY: ensure parent dir exists before any sqlite open
        self._sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ------------------------------------------------------------------ schema

    def _connect(self) -> sqlite3.Connection:
        """Open sqlite. Auto-recreate on corruption (DatabaseError).

        WHY explicit pre-check: opening a corrupt file then SELECT 1 sometimes
        succeeds because the read happens on the first real query. We probe
        with a header read first; on bad header we unlink (must close any
        prior handle on Windows) and recreate.
        """
        # Probe the file header — sqlite files start with magic "SQLite format 3\0"
        if self._sqlite_path.exists() and self._sqlite_path.stat().st_size > 0:
            try:
                with open(self._sqlite_path, "rb") as fh:
                    header = fh.read(16)
                if not header.startswith(b"SQLite format 3"):
                    raise sqlite3.DatabaseError("bad magic header")
            except (OSError, sqlite3.DatabaseError) as e:
                logger.warning(f"Corrupt SQLite at {self._sqlite_path} ({e}) — recreating")
                try:
                    self._sqlite_path.unlink(missing_ok=True)
                except OSError:
                    pass

        try:
            conn = sqlite3.connect(self._sqlite_path)
            conn.execute("SELECT 1")
            return conn
        except sqlite3.DatabaseError as e:
            logger.warning(f"SQLite open failed at {self._sqlite_path} ({e}) — recreating")
            try:
                self._sqlite_path.unlink(missing_ok=True)
            except OSError:
                pass
            return sqlite3.connect(self._sqlite_path)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS rag_events (
                    event_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    summary TEXT,
                    source TEXT,
                    severity TEXT,
                    timestamp TEXT NOT NULL,
                    btc_price REAL,
                    eth_price REAL,
                    fng_index INTEGER,
                    metadata_json TEXT,
                    indexed_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_timestamp ON rag_events(timestamp);
                CREATE INDEX IF NOT EXISTS idx_severity ON rag_events(severity);

                CREATE TABLE IF NOT EXISTS rag_bm25_cache (
                    cache_key TEXT PRIMARY KEY,
                    model_blob BLOB,
                    doc_count INTEGER,
                    built_at TEXT
                );
                """
            )

    # ------------------------------------------------------------------ build

    def _row_to_event(self, row: dict[str, Any]) -> RAGEvent | None:
        """Parse a BREAKING_LOG dict row → RAGEvent. Returns None on bad data.

        BREAKING_LOG schema (sheets_client.py): ID, Thời gian, Tiêu đề, Hash,
        Nguồn, Mức độ, Trạng thái gửi, URL, Thời gian gửi.
        """
        title = (row.get("Tiêu đề") or "").strip()
        timestamp = (row.get("Thời gian") or "").strip()
        if not title or not timestamp:
            return None  # skip rows lacking minimum data

        # WHY: event_id falls back to hash → timestamp+title to stay unique
        event_id = (row.get("Hash") or "").strip() or f"{timestamp}_{title[:40]}"
        # WHY: keep ALL non-canonical columns under metadata for forward compat
        canonical = {
            "ID",
            "Thời gian",
            "Tiêu đề",
            "Hash",
            "Nguồn",
            "Mức độ",
            "Trạng thái gửi",
            "URL",
            "Thời gian gửi",
        }
        metadata = {k: v for k, v in row.items() if k not in canonical}
        # Optional summary — BREAKING_LOG doesn't carry it natively; tolerate
        # both schemas (some test fixtures may include "Tóm tắt" / "summary").
        summary = row.get("summary") or row.get("Tóm tắt") or metadata.pop("summary", "") or ""

        def _to_float(val: Any) -> float | None:
            try:
                return float(val) if val not in (None, "") else None
            except (TypeError, ValueError):
                return None

        def _to_int(val: Any) -> int | None:
            try:
                return int(float(val)) if val not in (None, "") else None
            except (TypeError, ValueError):
                return None

        return RAGEvent(
            event_id=event_id,
            title=title,
            summary=summary,
            source=(row.get("Nguồn") or "").strip(),
            severity=(row.get("Mức độ") or "").strip(),
            timestamp=timestamp,
            btc_price=_to_float(row.get("btc_price") or metadata.get("btc_price")),
            eth_price=_to_float(row.get("eth_price") or metadata.get("eth_price")),
            fng_index=_to_int(row.get("fng_index") or metadata.get("fng_index")),
            metadata=metadata,
        )

    def build_from_sheets(self) -> int:
        """Read BREAKING_LOG, parse → SQLite + BM25. Returns doc_count.

        Graceful degrade: any Sheets API exception → empty index, log warning,
        return 0 (caller can decide whether to retry / surface).
        """
        if self._sheets is None:
            logger.warning("RAGIndex.build_from_sheets: no sheets_client provided")
            return 0
        try:
            rows = self._sheets.read_all("BREAKING_LOG")
        except Exception as e:
            logger.warning(f"RAGIndex: Sheets API failed ({e}); returning empty")
            self._events = []
            self._bm25 = None
            self._tokenized_corpus = []
            return 0

        events: list[RAGEvent] = []
        for row in rows:
            try:
                ev = self._row_to_event(row)
                if ev is not None:
                    events.append(ev)
            except Exception as e:  # WHY: never let one bad row poison the index
                logger.warning(f"RAGIndex: skipping malformed row ({e})")
                continue

        self._events = events
        self._tokenized_corpus = [_tokenize(e.to_doc_text()) for e in events]
        # WHY: BM25Okapi requires non-empty corpus → guard
        self._bm25 = BM25Okapi(self._tokenized_corpus) if self._tokenized_corpus else None
        self._persist()
        logger.info(f"RAGIndex built: {len(events)} events indexed")
        return len(events)

    def _persist(self) -> None:
        """Save events + BM25 model to SQLite."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute("DELETE FROM rag_events")
            conn.executemany(
                """INSERT INTO rag_events
                   (event_id, title, summary, source, severity, timestamp,
                    btc_price, eth_price, fng_index, metadata_json, indexed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        e.event_id,
                        e.title,
                        e.summary,
                        e.source,
                        e.severity,
                        e.timestamp,
                        e.btc_price,
                        e.eth_price,
                        e.fng_index,
                        json.dumps(e.metadata, ensure_ascii=False),
                        now_iso,
                    )
                    for e in self._events
                ],
            )
            blob = pickle.dumps(self._bm25) if self._bm25 is not None else b""
            conn.execute(
                """INSERT INTO rag_bm25_cache (cache_key, model_blob, doc_count, built_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(cache_key) DO UPDATE SET
                     model_blob=excluded.model_blob,
                     doc_count=excluded.doc_count,
                     built_at=excluded.built_at""",
                (_CACHE_KEY, blob, len(self._events), now_iso),
            )
            conn.commit()

    # ------------------------------------------------------------------ load

    def load_from_cache(self) -> bool:
        """Try to load BM25 + events from SQLite. Returns True on success."""
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    "SELECT model_blob, doc_count FROM rag_bm25_cache WHERE cache_key=?",
                    (_CACHE_KEY,),
                )
                row = cur.fetchone()
                if not row:
                    return False
                blob, doc_count = row
                if not blob or doc_count == 0:
                    self._events = []
                    self._bm25 = None
                    self._tokenized_corpus = []
                    return True  # empty cache is a valid state

                cur = conn.execute(
                    """SELECT event_id, title, summary, source, severity, timestamp,
                              btc_price, eth_price, fng_index, metadata_json
                       FROM rag_events"""
                )
                events: list[RAGEvent] = []
                for r in cur.fetchall():
                    (eid, title, summary, source, severity, ts, btc, eth, fng, meta_json) = r
                    try:
                        meta = json.loads(meta_json) if meta_json else {}
                    except json.JSONDecodeError:
                        meta = {}
                    events.append(
                        RAGEvent(
                            event_id=eid,
                            title=title,
                            summary=summary or "",
                            source=source or "",
                            severity=severity or "",
                            timestamp=ts,
                            btc_price=btc,
                            eth_price=eth,
                            fng_index=fng,
                            metadata=meta,
                        )
                    )
                self._events = events
                self._tokenized_corpus = [_tokenize(e.to_doc_text()) for e in events]
                try:
                    self._bm25 = pickle.loads(blob)
                except (pickle.UnpicklingError, EOFError, AttributeError) as e:
                    logger.warning(f"RAGIndex: cache pickle corrupt ({e}); rebuilding")
                    return False
                logger.info(f"RAGIndex loaded from cache: {len(events)} events")
                return True
        except sqlite3.Error as e:
            logger.warning(f"RAGIndex: cache load failed ({e})")
            return False

    # ------------------------------------------------------------------ query

    def query(
        self,
        query: str,
        top_k: int = 3,
        min_score: float = 0.5,
        exclude_recent_hours: float = 1.0,
        severity: str | None = None,
    ) -> list[dict[str, Any]]:
        """BM25 search with score + recency + severity filters.

        Args:
            query: search keywords (Vietnamese or English).
            top_k: max results.
            min_score: BM25 score threshold (events below are dropped).
            exclude_recent_hours: events with timestamp newer than (now - N
                hours) are excluded — prevents the LLM citing the very event
                it is currently writing about (Wave 0.5.2 self-reference fix).
            severity: optional exact match filter on severity column.

        Returns:
            List of dicts sorted by score desc, capped at top_k.
        """
        if self._bm25 is None or not self._events:
            return []
        tokens = _tokenize(query)
        if not tokens:
            return []  # query was empty / all stopwords

        raw_scores = self._bm25.get_scores(tokens)
        # WHY clip: BM25 IDF goes negative when a term appears in every doc
        # (df == N). For small/uniform corpora this drops legitimate matches.
        # Clipping to 0 preserves "term-found" signal; relative ranking among
        # non-negative scores is unchanged.
        scores = [max(0.0, float(s)) for s in raw_scores]
        # WHY: with negative IDF clipping, the "min_score" semantic is
        # ambiguous for low-info corpora. Treat any document that shares at
        # least one query token as a candidate when min_score == 0.0;
        # otherwise apply the score threshold strictly.
        token_set = set(tokens)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=exclude_recent_hours)

        ranked: list[tuple[float, RAGEvent]] = []
        for i, (score, ev) in enumerate(zip(scores, self._events)):
            if min_score > 0.0:
                if score < min_score:
                    continue
            else:
                # min_score==0 → require at least one query token to occur
                if not token_set.intersection(self._tokenized_corpus[i]):
                    continue
            if severity and ev.severity != severity:
                continue
            # WHY: tolerate any ISO format that fromisoformat parses;
            # malformed/empty timestamps are kept (treated as "old enough")
            if exclude_recent_hours > 0 and ev.timestamp:
                try:
                    ts = datetime.fromisoformat(ev.timestamp.replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts > cutoff:
                        continue
                except ValueError:
                    pass  # unparseable → keep, BM25 score still gates
            ranked.append((float(score), ev))

        ranked.sort(key=lambda x: x[0], reverse=True)
        results: list[dict[str, Any]] = []
        for score, ev in ranked[:top_k]:
            results.append(
                {
                    "event_id": ev.event_id,
                    "title": ev.title,
                    "summary": ev.summary,
                    "source": ev.source,
                    "severity": ev.severity,
                    "timestamp": ev.timestamp,
                    "btc_price": ev.btc_price,
                    "eth_price": ev.eth_price,
                    "fng_index": ev.fng_index,
                    "score": score,
                    "metadata": ev.metadata,
                }
            )
        return results

    # ------------------------------------------------------------------ misc

    @property
    def doc_count(self) -> int:
        return len(self._events)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def get_or_build_index(
    sheets_client: "SheetsClient | None" = None,
    sqlite_path: Path | str | None = None,
    force_rebuild: bool = False,
) -> RAGIndex:
    """Return a RAGIndex, using cache if doc_count matches Sheets row count.

    Logic:
      1. force_rebuild=True → build from Sheets unconditionally.
      2. Try load_from_cache. If miss → build from Sheets.
      3. If cache hit AND sheets_client provided → compare row counts.
         Mismatch (Sheets grew/shrank) → rebuild.

    Trade-off: GH Actions runner has no persistent disk → step 2 always
    misses → ~5-10s rebuild on first run. Acceptable vs. 30+s if querying
    Sheets per LLM call.
    """
    idx = RAGIndex(sheets_client=sheets_client, sqlite_path=sqlite_path)
    if force_rebuild:
        idx.build_from_sheets()
        return idx

    cache_ok = idx.load_from_cache()
    if not cache_ok:
        idx.build_from_sheets()
        return idx

    # Compare cached doc_count vs current Sheets size
    if sheets_client is not None:
        try:
            current = sheets_client.get_row_count("BREAKING_LOG")
            if current != idx.doc_count:
                logger.info(
                    f"RAGIndex: cache stale ({idx.doc_count} cached vs "
                    f"{current} in Sheets) — rebuilding"
                )
                idx.build_from_sheets()
        except Exception as e:
            logger.warning(f"RAGIndex: row count check failed ({e}); using cache")
    return idx


def query_historical_events(
    query: str,
    top_k: int = 3,
    min_score: float = 0.5,
    exclude_recent_hours: float = 1.0,
    sheets_client: "SheetsClient | None" = None,
    sqlite_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """One-shot helper — build/load index then query.

    For Story 0.6.2: this is the entry-point the LLM-prompt builder will
    call to fetch ground-truth historical context.
    """
    idx = get_or_build_index(sheets_client=sheets_client, sqlite_path=sqlite_path)
    return idx.query(
        query=query,
        top_k=top_k,
        min_score=min_score,
        exclude_recent_hours=exclude_recent_hours,
    )


# ---------------------------------------------------------------------------
# Tiny self-benchmark hook (for local timing only — not run in tests)
# ---------------------------------------------------------------------------


def _bench(n_docs: int = 100) -> tuple[float, float]:  # pragma: no cover
    """Build N synthetic docs, return (build_seconds, query_seconds)."""
    idx = RAGIndex(sqlite_path=Path("data") / "rag_bench.sqlite")
    fake = [
        RAGEvent(
            event_id=f"id_{i}",
            title=f"Event {i} BTC ETH halving Powell Fed crypto regulation",
            summary=f"Synthetic body {i} discussing market dynamics",
            timestamp="2024-01-01T00:00:00+00:00",
            severity="MEDIUM",
        )
        for i in range(n_docs)
    ]
    idx._events = fake
    idx._tokenized_corpus = [_tokenize(e.to_doc_text()) for e in fake]
    t0 = time.perf_counter()
    idx._bm25 = BM25Okapi(idx._tokenized_corpus)
    build_sec = time.perf_counter() - t0
    t1 = time.perf_counter()
    for _ in range(100):
        idx.query("BTC halving", top_k=3, exclude_recent_hours=0)
    query_sec = (time.perf_counter() - t1) / 100
    return build_sec, query_sec
