"""Tests for breaking/rag_index.py — Wave 0.6 Story 0.6.1.

Covers: init, build, query (top_k/min_score/recency/severity), cache
save/load, cache invalidation, corrupt sqlite recreate, Sheets API failure,
unicode VN, metadata preservation, concurrency, and edge cases.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cic_daily_report.breaking.rag_index import (
    RAGEvent,
    RAGIndex,
    _tokenize,
    get_or_build_index,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso_hours_ago(hours: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _make_row(
    title: str,
    timestamp: str,
    *,
    summary: str = "",
    source: str = "TestSource",
    severity: str = "MEDIUM",
    hash_val: str | None = None,
    extra: dict | None = None,
) -> dict:
    """Build a fake BREAKING_LOG row in the dict form sheets returns."""
    row = {
        "ID": "",
        "Thời gian": timestamp,
        "Tiêu đề": title,
        "Hash": hash_val or f"h_{abs(hash(title)) % 10000:04d}",
        "Nguồn": source,
        "Mức độ": severity,
        "Trạng thái gửi": "sent",
        "URL": "",
        "Thời gian gửi": "",
    }
    if summary:
        row["summary"] = summary
    if extra:
        row.update(extra)
    return row


def _mock_sheets(rows: list[dict] | Exception):
    sc = MagicMock()
    if isinstance(rows, Exception):
        sc.read_all.side_effect = rows
    else:
        sc.read_all.return_value = rows
    sc.get_row_count.return_value = len(rows) if isinstance(rows, list) else 0
    return sc


@pytest.fixture
def tmp_sqlite(tmp_path: Path) -> Path:
    return tmp_path / "rag.sqlite"


# ---------------------------------------------------------------------------
# 1. Init / empty
# ---------------------------------------------------------------------------


def test_init_with_empty_sheets(tmp_sqlite: Path):
    sc = _mock_sheets([])
    idx = RAGIndex(sheets_client=sc, sqlite_path=tmp_sqlite)
    n = idx.build_from_sheets()
    assert n == 0
    assert idx.doc_count == 0
    assert idx.query("anything") == []


# ---------------------------------------------------------------------------
# 2. Build basic
# ---------------------------------------------------------------------------


def test_build_from_mock_sheets(tmp_sqlite: Path):
    rows = [
        _make_row("Poly Network hack stolen $611M", _iso_hours_ago(48)),
        _make_row("Bitcoin halving April 2024", _iso_hours_ago(72)),
        _make_row("Wormhole bridge exploit 2022", _iso_hours_ago(96)),
        _make_row("Powell Fed rate decision", _iso_hours_ago(50)),
        _make_row("Ethereum Shanghai upgrade", _iso_hours_ago(60)),
    ]
    sc = _mock_sheets(rows)
    idx = RAGIndex(sheets_client=sc, sqlite_path=tmp_sqlite)
    assert idx.build_from_sheets() == 5
    assert idx.doc_count == 5


# ---------------------------------------------------------------------------
# 3. Query — exact match
# ---------------------------------------------------------------------------


def test_query_exact_match(tmp_sqlite: Path):
    rows = [
        _make_row("Poly Network hack stolen funds", _iso_hours_ago(48)),
        _make_row("Bitcoin halving event", _iso_hours_ago(72)),
        _make_row("Random unrelated topic", _iso_hours_ago(96)),
    ]
    sc = _mock_sheets(rows)
    idx = RAGIndex(sheets_client=sc, sqlite_path=tmp_sqlite)
    idx.build_from_sheets()
    res = idx.query("Poly Network hack", top_k=3, min_score=0.0)
    assert res
    assert "Poly Network" in res[0]["title"]


# ---------------------------------------------------------------------------
# 4. Query — partial match
# ---------------------------------------------------------------------------


def test_query_partial_match(tmp_sqlite: Path):
    rows = [
        _make_row("Bitcoin halving April 2024", _iso_hours_ago(48)),
        _make_row("Ethereum upgrade Shanghai", _iso_hours_ago(72)),
        _make_row("Federal Reserve announcement", _iso_hours_ago(96)),
    ]
    sc = _mock_sheets(rows)
    idx = RAGIndex(sheets_client=sc, sqlite_path=tmp_sqlite)
    idx.build_from_sheets()
    res = idx.query("Bitcoin halving", top_k=3, min_score=0.0)
    assert res
    assert "halving" in res[0]["title"].lower()


# ---------------------------------------------------------------------------
# 5. Query — no match
# ---------------------------------------------------------------------------


def test_query_no_match(tmp_sqlite: Path):
    rows = [
        _make_row("Bitcoin halving event", _iso_hours_ago(48)),
        _make_row("Ethereum upgrade", _iso_hours_ago(72)),
    ]
    sc = _mock_sheets(rows)
    idx = RAGIndex(sheets_client=sc, sqlite_path=tmp_sqlite)
    idx.build_from_sheets()
    res = idx.query("xyz123 quokka zebra", top_k=3, min_score=0.5)
    assert res == []


# ---------------------------------------------------------------------------
# 6. Query — min_score filter drops weak matches
# ---------------------------------------------------------------------------


def test_query_min_score_filter(tmp_sqlite: Path):
    rows = [
        _make_row("Poly Network hack stolen $611M crypto bridge", _iso_hours_ago(48)),
        _make_row("Some random article about cooking", _iso_hours_ago(72)),
    ]
    sc = _mock_sheets(rows)
    idx = RAGIndex(sheets_client=sc, sqlite_path=tmp_sqlite)
    idx.build_from_sheets()
    # very high threshold → likely 0 results
    res_high = idx.query("Poly Network", top_k=5, min_score=999.0)
    assert res_high == []
    # threshold 0 → at least 1
    res_low = idx.query("Poly Network", top_k=5, min_score=0.0)
    assert len(res_low) >= 1


# ---------------------------------------------------------------------------
# 7. Query — exclude recent (anti-self-reference)
# ---------------------------------------------------------------------------


def test_query_exclude_recent(tmp_sqlite: Path):
    rows = [
        # 30 minutes ago — must be excluded with default exclude_recent_hours=1.0
        _make_row("Fresh Bitcoin price news", _iso_hours_ago(0.5)),
        # 48h ago — kept
        _make_row("Old Bitcoin halving article", _iso_hours_ago(48)),
    ]
    sc = _mock_sheets(rows)
    idx = RAGIndex(sheets_client=sc, sqlite_path=tmp_sqlite)
    idx.build_from_sheets()
    res = idx.query("Bitcoin", top_k=5, min_score=0.0, exclude_recent_hours=1.0)
    titles = [r["title"] for r in res]
    assert "Fresh Bitcoin price news" not in titles
    assert "Old Bitcoin halving article" in titles


# ---------------------------------------------------------------------------
# 8. Query — top_k limit
# ---------------------------------------------------------------------------


def test_query_top_k_limit(tmp_sqlite: Path):
    rows = [_make_row(f"Bitcoin event number {i}", _iso_hours_ago(48 + i)) for i in range(10)]
    sc = _mock_sheets(rows)
    idx = RAGIndex(sheets_client=sc, sqlite_path=tmp_sqlite)
    idx.build_from_sheets()
    res = idx.query("Bitcoin event", top_k=2, min_score=0.0)
    assert len(res) == 2


# ---------------------------------------------------------------------------
# 9. Cache save → load round-trip
# ---------------------------------------------------------------------------


def test_cache_save_load(tmp_sqlite: Path):
    rows = [
        _make_row("Poly Network hack", _iso_hours_ago(48)),
        _make_row("Bitcoin halving", _iso_hours_ago(72)),
    ]
    sc = _mock_sheets(rows)
    idx1 = RAGIndex(sheets_client=sc, sqlite_path=tmp_sqlite)
    idx1.build_from_sheets()

    # Reload from cache only
    idx2 = RAGIndex(sheets_client=None, sqlite_path=tmp_sqlite)
    assert idx2.load_from_cache() is True
    assert idx2.doc_count == 2
    res = idx2.query("Poly", top_k=3, min_score=0.0)
    assert res
    assert "Poly" in res[0]["title"]


# ---------------------------------------------------------------------------
# 10. Cache invalidation when Sheets row count changes
# ---------------------------------------------------------------------------


def test_cache_invalidation_on_doc_count_change(tmp_sqlite: Path):
    rows1 = [_make_row("Event A", _iso_hours_ago(48))]
    sc1 = _mock_sheets(rows1)
    idx1 = RAGIndex(sheets_client=sc1, sqlite_path=tmp_sqlite)
    idx1.build_from_sheets()
    assert idx1.doc_count == 1

    # Now Sheets has 3 rows → get_or_build_index should rebuild
    rows2 = [
        _make_row("Event A", _iso_hours_ago(48)),
        _make_row("Event B", _iso_hours_ago(72)),
        _make_row("Event C", _iso_hours_ago(96)),
    ]
    sc2 = _mock_sheets(rows2)
    idx2 = get_or_build_index(sheets_client=sc2, sqlite_path=tmp_sqlite)
    assert idx2.doc_count == 3


# ---------------------------------------------------------------------------
# 11. Corrupt SQLite — auto recreate
# ---------------------------------------------------------------------------


def test_corrupt_sqlite_recreate(tmp_sqlite: Path):
    # Write garbage bytes that aren't a valid sqlite file
    tmp_sqlite.write_bytes(b"this is not a sqlite file" * 100)
    rows = [_make_row("Event after corruption", _iso_hours_ago(48))]
    sc = _mock_sheets(rows)
    # Should not raise — just recreate
    idx = RAGIndex(sheets_client=sc, sqlite_path=tmp_sqlite)
    n = idx.build_from_sheets()
    assert n == 1


# ---------------------------------------------------------------------------
# 12. Graceful Sheets API fail
# ---------------------------------------------------------------------------


def test_graceful_sheets_api_fail(tmp_sqlite: Path):
    sc = _mock_sheets(RuntimeError("network down"))
    idx = RAGIndex(sheets_client=sc, sqlite_path=tmp_sqlite)
    n = idx.build_from_sheets()
    assert n == 0
    assert idx.doc_count == 0
    assert idx.query("anything") == []


# ---------------------------------------------------------------------------
# 13. Unicode Vietnamese query
# ---------------------------------------------------------------------------


def test_unicode_vietnamese_query(tmp_sqlite: Path):
    rows = [
        _make_row("Tài sản mã hóa giảm mạnh sau quyết định Fed", _iso_hours_ago(48)),
        _make_row("Bitcoin halving sự kiện quan trọng", _iso_hours_ago(72)),
    ]
    sc = _mock_sheets(rows)
    idx = RAGIndex(sheets_client=sc, sqlite_path=tmp_sqlite)
    idx.build_from_sheets()
    res = idx.query("tài sản mã hóa", top_k=3, min_score=0.0)
    assert res
    assert "Tài sản" in res[0]["title"] or "tài sản" in res[0]["title"].lower()


# ---------------------------------------------------------------------------
# 14. Metadata round-trip preservation
# ---------------------------------------------------------------------------


def test_metadata_preservation(tmp_sqlite: Path):
    rows = [
        _make_row(
            "Event with extras",
            _iso_hours_ago(48),
            extra={"custom_field": "custom_value", "btc_price": "63000.5"},
        )
    ]
    sc = _mock_sheets(rows)
    idx1 = RAGIndex(sheets_client=sc, sqlite_path=tmp_sqlite)
    idx1.build_from_sheets()

    idx2 = RAGIndex(sheets_client=None, sqlite_path=tmp_sqlite)
    assert idx2.load_from_cache()
    res = idx2.query("Event with extras", top_k=1, min_score=0.0)
    assert res
    assert res[0]["btc_price"] == 63000.5
    assert res[0]["metadata"].get("custom_field") == "custom_value"


# ---------------------------------------------------------------------------
# 15. Concurrent query — no race
# ---------------------------------------------------------------------------


def test_concurrent_query(tmp_sqlite: Path):
    rows = [_make_row(f"Bitcoin event {i}", _iso_hours_ago(48 + i)) for i in range(20)]
    sc = _mock_sheets(rows)
    idx = RAGIndex(sheets_client=sc, sqlite_path=tmp_sqlite)
    idx.build_from_sheets()

    results: list[list[dict]] = []
    errors: list[BaseException] = []

    def _worker():
        try:
            r = idx.query("Bitcoin event", top_k=3, min_score=0.0)
            results.append(r)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=_worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(results) == 10
    # All workers should yield the same top-K (order-stable for identical input)
    assert all(len(r) == 3 for r in results)


# ---------------------------------------------------------------------------
# 16. Empty query string
# ---------------------------------------------------------------------------


def test_empty_query_string(tmp_sqlite: Path):
    rows = [_make_row("Some event", _iso_hours_ago(48))]
    sc = _mock_sheets(rows)
    idx = RAGIndex(sheets_client=sc, sqlite_path=tmp_sqlite)
    idx.build_from_sheets()
    assert idx.query("", top_k=3, min_score=0.0) == []
    assert idx.query("   ", top_k=3, min_score=0.0) == []


# ---------------------------------------------------------------------------
# 17. Stopwords-only query → no signal
# ---------------------------------------------------------------------------


def test_stopwords_only_query(tmp_sqlite: Path):
    rows = [_make_row("Bitcoin event", _iso_hours_ago(48))]
    sc = _mock_sheets(rows)
    idx = RAGIndex(sheets_client=sc, sqlite_path=tmp_sqlite)
    idx.build_from_sheets()
    # All stopwords → tokens become []
    assert idx.query("the a an of to", top_k=3, min_score=0.0) == []


# ---------------------------------------------------------------------------
# 18. Special chars in query don't crash
# ---------------------------------------------------------------------------


def test_special_chars_in_query(tmp_sqlite: Path):
    rows = [_make_row("Bitcoin price hits $100,000", _iso_hours_ago(48))]
    sc = _mock_sheets(rows)
    idx = RAGIndex(sheets_client=sc, sqlite_path=tmp_sqlite)
    idx.build_from_sheets()
    # Exotic punctuation must not raise
    res = idx.query("$$$ !@# Bitcoin ???", top_k=3, min_score=0.0)
    assert isinstance(res, list)


# ---------------------------------------------------------------------------
# 19. Very long query is tolerated
# ---------------------------------------------------------------------------


def test_very_long_query(tmp_sqlite: Path):
    rows = [_make_row("Bitcoin halving event", _iso_hours_ago(48))]
    sc = _mock_sheets(rows)
    idx = RAGIndex(sheets_client=sc, sqlite_path=tmp_sqlite)
    idx.build_from_sheets()
    long_query = ("Bitcoin halving " * 500).strip()
    res = idx.query(long_query, top_k=3, min_score=0.0)
    assert isinstance(res, list)


# ---------------------------------------------------------------------------
# 20. Severity filter + tokenize unit + skip malformed row
# ---------------------------------------------------------------------------


def test_severity_filter_and_skip_malformed(tmp_sqlite: Path):
    rows = [
        _make_row("High severity event", _iso_hours_ago(48), severity="HIGH"),
        _make_row("Medium severity event", _iso_hours_ago(50), severity="MEDIUM"),
        # Malformed: missing title — should be skipped silently
        {
            "Thời gian": _iso_hours_ago(60),
            "Tiêu đề": "",
            "Hash": "h_x",
            "Nguồn": "X",
            "Mức độ": "LOW",
        },
    ]
    sc = _mock_sheets(rows)
    idx = RAGIndex(sheets_client=sc, sqlite_path=tmp_sqlite)
    n = idx.build_from_sheets()
    assert n == 2  # malformed dropped

    res_high = idx.query("severity event", top_k=5, min_score=0.0, severity="HIGH")
    assert all(r["severity"] == "HIGH" for r in res_high)
    assert len(res_high) == 1

    # Tokenizer unit assertions
    assert "the" not in _tokenize("the bitcoin halving")
    assert "bitcoin" in _tokenize("Bitcoin Halving")


# ---------------------------------------------------------------------------
# Bonus: dataclass + force rebuild
# ---------------------------------------------------------------------------


def test_force_rebuild(tmp_sqlite: Path):
    rows1 = [_make_row("First", _iso_hours_ago(48))]
    sc1 = _mock_sheets(rows1)
    RAGIndex(sheets_client=sc1, sqlite_path=tmp_sqlite).build_from_sheets()

    rows2 = [
        _make_row("First", _iso_hours_ago(48)),
        _make_row("Second", _iso_hours_ago(72)),
    ]
    sc2 = _mock_sheets(rows2)
    idx = get_or_build_index(sheets_client=sc2, sqlite_path=tmp_sqlite, force_rebuild=True)
    assert idx.doc_count == 2


def test_ragevent_to_doc_text():
    ev = RAGEvent(event_id="x", title="Hello", summary="World")
    assert ev.to_doc_text() == "Hello World"
    ev2 = RAGEvent(event_id="x", title="Hello")
    assert ev2.to_doc_text() == "Hello"
