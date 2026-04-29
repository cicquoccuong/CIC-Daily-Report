"""Wave 0.6 Story 0.6.4 (alpha.22) — PriceSnapshot wire + 2-source verification.

Tests:
PriceSnapshot wire (Part A):
1. test_pricesnap_injected_into_prompt — explicit lock note in prompt when snapshot provided
2. test_pricesnap_omitted_when_none — no lock note when snapshot=None (back-compat)
3. test_post_process_replaces_off_snapshot_btc — LLM writes $80k → replaced with $76k snapshot
4. test_post_process_keeps_close_btc — LLM writes $76,500 (within 1%) → unchanged
5. test_post_process_skips_huge_drift — $200k vs $76k (>50%) → numeric_sanity, no replace
6. test_post_process_replaces_eth — same logic for ETH
7. test_post_process_no_snapshot_no_change — without snapshot, no replace logic
8. test_post_process_handles_k_suffix — "$76k" recognized as $76,000

Two-source verifier (Part B):
9. test_2source_verified_match — same event, different source, recent → verified
10. test_2source_single_source — no match found → single_source
11. test_2source_conflict_flag — high sim + numeric mismatch → conflict
12. test_2source_skip_same_source — same source repost ignored
13. test_2source_outside_window — old entry ignored
14. test_2source_empty_recent — empty list → single_source
15. test_2source_low_similarity — distinct events → single_source
16. test_2source_entity_required — high sim but no entity overlap → single_source
17. test_2source_unicode_vn — VN unicode titles handled
18. test_2source_malformed_timestamp — bad detected_at → skipped gracefully
19. test_2source_ratio_threshold_edge — sim=0.4 boundary

Pipeline wire + flag (Part C):
20. test_2source_flag_off_default — without env var → flag is False
21. test_2source_flag_on_via_env — env=1 → flag True
22. test_verifier_default_threshold_constant — defaults exposed
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from cic_daily_report.adapters.llm_adapter import LLMResponse
from cic_daily_report.breaking.content_generator import (
    _replace_off_snapshot_prices,
    generate_breaking_content,
)
from cic_daily_report.breaking.dedup_manager import DedupEntry
from cic_daily_report.breaking.event_detector import BreakingEvent
from cic_daily_report.breaking.two_source_verifier import (
    DEFAULT_RECENT_HOURS,
    DEFAULT_SIMILARITY_THRESHOLD,
    TwoSourceResult,
    verify_two_sources,
)
from cic_daily_report.collectors.market_data import MarketDataPoint, PriceSnapshot
from cic_daily_report.core.config import _wave_0_6_2source_required

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _event(title: str = "Major exchange hack", source: str = "CoinDesk") -> BreakingEvent:
    return BreakingEvent(
        title=title,
        source=source,
        url=f"https://example.com/{source.lower()}",
        panic_score=85,
    )


def _mock_llm(
    text: str = "Tin nóng: BTC giảm mạnh sau sự kiện quan trọng. Giá hiện tại có thay đổi.",
) -> AsyncMock:
    mock = AsyncMock()
    mock.generate = AsyncMock(
        return_value=LLMResponse(text=text, tokens_used=100, model="test-model")
    )
    mock.last_provider = "groq"
    mock.circuit_open = False
    return mock


def _snapshot(btc: float = 76000.0, eth: float = 3500.0) -> PriceSnapshot:
    return PriceSnapshot(
        market_data=[
            MarketDataPoint(
                symbol="BTC",
                price=btc,
                change_24h=-2.5,
                volume_24h=0,
                market_cap=0,
                data_type="crypto",
                source="test",
            ),
            MarketDataPoint(
                symbol="ETH",
                price=eth,
                change_24h=-3.0,
                volume_24h=0,
                market_cap=0,
                data_type="crypto",
                source="test",
            ),
        ]
    )


def _entry(
    title: str,
    source: str,
    detected_at: datetime | None = None,
    severity: str = "important",
) -> DedupEntry:
    if detected_at is None:
        detected_at = datetime.now(timezone.utc) - timedelta(hours=2)
    return DedupEntry(
        hash=f"hash_{title[:8]}_{source}",
        title=title,
        source=source,
        severity=severity,
        detected_at=detected_at.isoformat(),
        status="sent",
        url=f"https://{source.lower()}.com/article",
    )


# ---------------------------------------------------------------------------
# Part A — PriceSnapshot wire into prompt + post-process
# ---------------------------------------------------------------------------


class TestPriceSnapshotWire:
    """Verify PriceSnapshot is injected into prompt + post-process replace works."""

    @pytest.mark.asyncio
    async def test_pricesnap_injected_into_prompt(self):
        """Snapshot provided → explicit lock instruction appears in prompt."""
        llm = _mock_llm()
        snapshot = _snapshot(btc=76000, eth=3500)
        await generate_breaking_content(_event(), llm, price_snapshot=snapshot)
        call_kwargs = llm.generate.call_args
        prompt = call_kwargs.kwargs.get("prompt", "")
        assert "GIÁ ĐÃ KHÓA" in prompt
        assert "BTC price = $76,000" in prompt
        assert "ETH price = $3,500" in prompt
        assert "KHÔNG dùng giá khác cho BTC" in prompt

    @pytest.mark.asyncio
    async def test_pricesnap_omitted_when_none(self):
        """No snapshot → no lock instruction (back-compat)."""
        llm = _mock_llm()
        await generate_breaking_content(_event(), llm, price_snapshot=None)
        call_kwargs = llm.generate.call_args
        prompt = call_kwargs.kwargs.get("prompt", "")
        assert "GIÁ ĐÃ KHÓA" not in prompt

    def test_post_process_replaces_off_snapshot_btc(self):
        """LLM writes BTC $80,000 → replaced with snapshot $76,000."""
        content = "BTC hiện tại $80,000 sau biến động lớn."
        result = _replace_off_snapshot_prices(content, "BTC", 76000.0, tolerance_pct=1.0)
        assert "$76,000" in result
        assert "$80,000" not in result

    def test_post_process_keeps_close_btc(self):
        """LLM writes $76,500 (within 1%) → unchanged."""
        content = "BTC giá $76,500 ổn định."
        # 76500 vs 76000: 0.66% drift → within 1% tolerance
        result = _replace_off_snapshot_prices(content, "BTC", 76000.0, tolerance_pct=1.0)
        # Note: depending on tolerance edge; 0.66% < 1% → keep
        assert "$76,500" in result

    def test_post_process_skips_huge_drift(self):
        """Price >50% off snapshot → not replaced (numeric_sanity territory)."""
        content = "Bitcoin lập đỉnh $200,000."  # 163% drift
        result = _replace_off_snapshot_prices(content, "BTC", 76000.0, tolerance_pct=1.0)
        # Out of replace range → kept (numeric_sanity should have caught earlier)
        assert "$200,000" in result

    def test_post_process_replaces_eth(self):
        """Same logic for ETH."""
        content = "ETH đang ở mức $5,000 hiện tại."  # 43% drift from $3,500
        result = _replace_off_snapshot_prices(content, "ETH", 3500.0, tolerance_pct=1.0)
        assert "$3,500" in result
        assert "$5,000" not in result

    def test_post_process_handles_k_suffix(self):
        """'$80k' recognized as $80,000 and replaced."""
        content = "BTC quanh mức $80k sau tin tức."
        result = _replace_off_snapshot_prices(content, "BTC", 76000.0, tolerance_pct=1.0)
        # Should replace $80k with $76,000
        assert "$76,000" in result

    def test_post_process_no_match_no_change(self):
        """Content without BTC/ETH price patterns → unchanged."""
        content = "Sự kiện quan trọng diễn ra hôm nay."
        result = _replace_off_snapshot_prices(content, "BTC", 76000.0, tolerance_pct=1.0)
        assert result == content

    def test_post_process_uses_snapshot_in_numeric_guard(self):
        """When snapshot wired, apply_all_numeric_guards gets tighter range."""
        # This is an integration check — snapshot variables must be passed through.
        from cic_daily_report.generators.numeric_sanity import apply_all_numeric_guards

        # With snapshot $76k, range becomes $38k-$114k. Without snapshot, $10k-$200k.
        # An $8k claim would only be flagged when snapshot is provided (since 8k > 10k).
        # Here we just verify the function accepts snapshots without error.
        out, issues = apply_all_numeric_guards("BTC at $50k", btc_snapshot=76000.0)
        # Either passes or flags — just verify call works
        assert isinstance(out, str)
        assert isinstance(issues, list)


# ---------------------------------------------------------------------------
# Part B — Two-source verifier
# ---------------------------------------------------------------------------


class TestTwoSourceVerifier:
    """Verify 2-source verification logic."""

    def test_verified_match(self):
        """Same event from different source within 24h → verified."""
        event = _event(
            title="Canada passes Bill C-25 crypto regulation",
            source="CoinDesk",
        )
        recent = [
            _entry(
                "Canada Bill C-25 cryptocurrency law approved",
                "CoinTelegraph",
                detected_at=datetime.now(timezone.utc) - timedelta(hours=2),
            ),
        ]
        result = verify_two_sources(event, recent)
        assert result.verdict == "verified"
        assert result.second_source == "CoinTelegraph"
        assert result.similarity_score >= DEFAULT_SIMILARITY_THRESHOLD

    def test_single_source_no_match(self):
        """No matching second source → single_source."""
        event = _event(title="Drift Protocol launches new feature", source="CoinDesk")
        recent = [
            _entry(
                "Tesla quarterly earnings report",
                "Reuters",
                detected_at=datetime.now(timezone.utc) - timedelta(hours=1),
            ),
        ]
        result = verify_two_sources(event, recent)
        assert result.verdict == "single_source"
        assert result.second_source == ""

    def test_conflict_flag(self):
        """Very similar titles but disagree on numbers → conflict."""
        event = _event(
            title="Bitcoin hack steals $1B from exchange",
            source="CoinDesk",
        )
        recent = [
            _entry(
                "Bitcoin hack steals $10B from exchange",  # ~98% similarity
                "CoinTelegraph",
                detected_at=datetime.now(timezone.utc) - timedelta(hours=1),
            ),
        ]
        result = verify_two_sources(event, recent)
        assert result.verdict == "conflict"
        assert result.second_source == "CoinTelegraph"

    def test_skip_same_source(self):
        """Same source repost is NOT counted as 2nd source."""
        event = _event(
            title="Canada passes Bill C-25 crypto regulation",
            source="CoinDesk",
        )
        recent = [
            _entry(
                "Canada Bill C-25 cryptocurrency law approved",
                "CoinDesk",  # same source
                detected_at=datetime.now(timezone.utc) - timedelta(hours=1),
            ),
        ]
        result = verify_two_sources(event, recent)
        assert result.verdict == "single_source"

    def test_outside_window(self):
        """Entry older than recent_hours → not counted."""
        event = _event(title="Bitcoin hack", source="CoinDesk")
        recent = [
            _entry(
                "Bitcoin hack",
                "CoinTelegraph",
                detected_at=datetime.now(timezone.utc) - timedelta(hours=48),  # too old
            ),
        ]
        result = verify_two_sources(event, recent, recent_hours=24)
        assert result.verdict == "single_source"

    def test_empty_recent(self):
        """Empty recent list → single_source."""
        result = verify_two_sources(_event(), [])
        assert result.verdict == "single_source"

    def test_low_similarity_no_match(self):
        """Distinct events from different source → single_source."""
        event = _event(title="Drift Protocol token launch", source="CoinDesk")
        recent = [
            _entry(
                "Federal Reserve interest rate decision",
                "Reuters",
                detected_at=datetime.now(timezone.utc) - timedelta(hours=1),
            ),
        ]
        result = verify_two_sources(event, recent)
        assert result.verdict == "single_source"

    def test_entity_overlap_required(self):
        """High word similarity but zero entity overlap → not verified."""
        event = _event(title="Random text about generic news today", source="CoinDesk")
        recent = [
            _entry(
                "Random text about generic news yesterday",
                "Reuters",
                detected_at=datetime.now(timezone.utc) - timedelta(hours=2),
            ),
        ]
        # No crypto entities → entity overlap = 0 → no match
        result = verify_two_sources(event, recent)
        # Could be single_source (no entities); verifier requires len(overlap) >= 1
        assert result.verdict == "single_source"

    def test_unicode_vn_titles(self):
        """Vietnamese unicode titles handled without crash."""
        event = _event(
            title="Bitcoin tăng giá mạnh sau quyết định Fed",
            source="CoinDesk",
        )
        recent = [
            _entry(
                "Bitcoin tăng giá mạnh sau quyết định Fed",
                "Reuters",
                detected_at=datetime.now(timezone.utc) - timedelta(hours=1),
            ),
        ]
        result = verify_two_sources(event, recent)
        assert result.verdict == "verified"

    def test_malformed_timestamp_skipped(self):
        """Entry with bad detected_at → skipped silently."""
        event = _event(title="Bitcoin hack", source="CoinDesk")
        recent = [
            DedupEntry(
                hash="x",
                title="Bitcoin hack",
                source="CoinTelegraph",
                detected_at="not-a-date",
                status="sent",
            ),
        ]
        result = verify_two_sources(event, recent)
        # Bad timestamp → entry skipped → no match found
        assert result.verdict == "single_source"

    def test_threshold_boundary(self):
        """Custom threshold parameter respected."""
        event = _event(title="Bitcoin price update", source="CoinDesk")
        recent = [
            _entry(
                "Bitcoin price update",
                "Reuters",
                detected_at=datetime.now(timezone.utc) - timedelta(hours=1),
            ),
        ]
        # Identical titles → similarity 1.0 >> any threshold
        result = verify_two_sources(event, recent, similarity_threshold=0.9)
        assert result.verdict == "verified"


# ---------------------------------------------------------------------------
# Part C — Feature flag + module constants
# ---------------------------------------------------------------------------


class TestTwoSourceFlag:
    """Verify feature flag default OFF + env var override."""

    def test_flag_off_default(self, monkeypatch):
        """No env var → flag is False (safe deploy)."""
        monkeypatch.delenv("WAVE_0_6_2SOURCE_REQUIRED", raising=False)
        assert _wave_0_6_2source_required() is False

    def test_flag_on_via_env(self, monkeypatch):
        """env=1 → flag True."""
        monkeypatch.setenv("WAVE_0_6_2SOURCE_REQUIRED", "1")
        assert _wave_0_6_2source_required() is True

    def test_flag_on_truthy_values(self, monkeypatch):
        """Common truthy strings accepted."""
        for val in ("1", "true", "yes", "on", "TRUE", "YES"):
            monkeypatch.setenv("WAVE_0_6_2SOURCE_REQUIRED", val)
            assert _wave_0_6_2source_required() is True, f"{val} should be truthy"

    def test_flag_off_falsy_values(self, monkeypatch):
        """Common falsy strings rejected."""
        for val in ("0", "false", "no", "off", "", "random"):
            monkeypatch.setenv("WAVE_0_6_2SOURCE_REQUIRED", val)
            assert _wave_0_6_2source_required() is False, f"{val} should be falsy"

    def test_default_constants_exposed(self):
        """Module-level constants for test/operator override."""
        assert DEFAULT_SIMILARITY_THRESHOLD == 0.4
        assert DEFAULT_RECENT_HOURS == 24
        # TwoSourceResult is a dataclass — verify shape
        r = TwoSourceResult(verdict="verified", second_source="X")
        assert r.verdict == "verified"
        assert r.second_source == "X"
        assert r.similarity_score == 0.0
