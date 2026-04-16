"""Tests for Wave 0 Quick Wins: QO.07, QO.08, QO.09, QO.11.

QO.07: DISCLAIMER_SHORT for breaking news
QO.08: MASTER_MAX_TOKENS 16384 → 20480
QO.09: DXY conditional injection
QO.11: Severity legend once per day
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

from cic_daily_report.adapters.llm_adapter import LLMResponse
from cic_daily_report.breaking.event_detector import BreakingEvent
from cic_daily_report.collectors.market_data import MarketDataPoint


def _event(title="Major exchange hack", source="CoinDesk") -> BreakingEvent:
    return BreakingEvent(
        title=title,
        source=source,
        url="https://coindesk.com/hack",
        panic_score=85,
    )


def _mock_llm(text: str = "Tin nóng: sự kiện tài sản mã hóa quan trọng.") -> AsyncMock:
    mock = AsyncMock()
    mock.generate = AsyncMock(
        return_value=LLMResponse(text=text, tokens_used=100, model="test-model")
    )
    mock.last_provider = "groq"
    return mock


def _dxy_data(change_24h: float = -0.3) -> MarketDataPoint:
    return MarketDataPoint(
        symbol="DXY",
        price=99.8,
        change_24h=change_24h,
        volume_24h=0,
        market_cap=0,
        data_type="index",
        source="FairEconomy",
    )


def _market_data(dxy_change: float = -0.3) -> list[MarketDataPoint]:
    return [
        MarketDataPoint(
            symbol="BTC",
            price=74589,
            change_24h=0.5,
            volume_24h=1e10,
            market_cap=1e12,
            data_type="crypto",
            source="CoinLore",
        ),
        MarketDataPoint(
            symbol="ETH",
            price=2450,
            change_24h=-1.2,
            volume_24h=5e9,
            market_cap=3e11,
            data_type="crypto",
            source="CoinLore",
        ),
        MarketDataPoint(
            symbol="Fear&Greed",
            price=26,
            change_24h=0,
            volume_24h=0,
            market_cap=0,
            data_type="index",
            source="Alternative.me",
        ),
        _dxy_data(dxy_change),
    ]


# =====================================================================
# QO.07: DISCLAIMER_SHORT for breaking news
# =====================================================================
class TestQO07DisclaimerShort:
    """QO.07 (VD-36): Breaking news uses short disclaimer, daily keeps full."""

    def test_disclaimer_short_exists(self):
        """DISCLAIMER_SHORT constant is defined in article_generator."""
        from cic_daily_report.generators.article_generator import DISCLAIMER_SHORT

        assert "DYOR" in DISCLAIMER_SHORT
        assert len(DISCLAIMER_SHORT) < 100  # ~60 chars target

    def test_disclaimer_short_is_nq05_compliant(self):
        """Short disclaimer still mentions it's not investment advice."""
        from cic_daily_report.generators.article_generator import DISCLAIMER_SHORT

        assert "lời khuyên đầu tư" in DISCLAIMER_SHORT

    def test_disclaimer_short_matches_nq05_filter_check(self):
        """QO.07 fix: DISCLAIMER_SHORT contains 'trách nhiệm' for nq05_filter match."""
        from cic_daily_report.generators.article_generator import DISCLAIMER_SHORT

        # nq05_filter.py line 299 checks for this exact substring
        assert "Tuyên bố miễn trừ trách nhiệm" in DISCLAIMER_SHORT

    def test_disclaimer_short_has_risk_warning(self):
        """QO.07 fix: DISCLAIMER_SHORT includes 'Rủi ro cao' risk warning."""
        from cic_daily_report.generators.article_generator import DISCLAIMER_SHORT

        assert "Rủi ro cao" in DISCLAIMER_SHORT

    def test_nq05_filter_detects_short_disclaimer(self):
        """QO.07 fix: nq05_filter reports disclaimer_present=True for short disclaimer."""
        from cic_daily_report.generators.article_generator import DISCLAIMER_SHORT
        from cic_daily_report.generators.nq05_filter import check_and_fix

        content = "Tin tức tài sản mã hóa quan trọng." + DISCLAIMER_SHORT
        result = check_and_fix(content)
        assert result.disclaimer_present is True

    def test_full_disclaimer_still_exists(self):
        """Full DISCLAIMER is preserved for daily articles."""
        from cic_daily_report.generators.article_generator import DISCLAIMER

        assert "Tuyên bố miễn trừ trách nhiệm" in DISCLAIMER
        assert len(DISCLAIMER) > 100

    async def test_breaking_content_uses_short_disclaimer(self):
        """Generated breaking content uses short disclaimer, not full."""
        from cic_daily_report.breaking.content_generator import generate_breaking_content

        llm = _mock_llm()
        result = await generate_breaking_content(_event(), llm)

        # Short disclaimer present
        assert "DYOR" in result.content
        # Full disclaimer NOT present (check unique substring from full version)
        assert "Nội dung trên chỉ mang tính chất thông tin và phân tích" not in result.content

    async def test_breaking_content_shorter_than_full(self):
        """Breaking content with short disclaimer is shorter than it would be with full."""
        from cic_daily_report.generators.article_generator import DISCLAIMER, DISCLAIMER_SHORT

        assert len(DISCLAIMER_SHORT) < len(DISCLAIMER)

    def test_raw_data_fallback_uses_short_disclaimer(self):
        """Raw data fallback also uses short disclaimer since it's breaking."""
        from cic_daily_report.breaking.content_generator import _raw_data_fallback

        result = _raw_data_fallback(_event())
        assert "DYOR" in result.content
        assert "Nội dung trên chỉ mang tính chất thông tin và phân tích" not in result.content

    async def test_digest_uses_short_disclaimer(self):
        """Digest content also uses short disclaimer."""
        from cic_daily_report.breaking.content_generator import generate_digest_content

        events = [
            BreakingEvent(
                title=f"Event {i}",
                source=f"Src{i}",
                url=f"https://example.com/{i}",
                panic_score=80,
            )
            for i in range(3)
        ]
        llm = _mock_llm()
        result = await generate_digest_content(events, llm)
        assert "DYOR" in result.content
        assert "Nội dung trên chỉ mang tính chất thông tin và phân tích" not in result.content


# =====================================================================
# QO.08: MASTER_MAX_TOKENS = 20480
# =====================================================================
class TestQO08MasterMaxTokens:
    """QO.08 (VD-19): Master analysis max tokens increased to prevent truncation."""

    def test_master_max_tokens_is_20480(self):
        from cic_daily_report.generators.master_analysis import MASTER_MAX_TOKENS

        assert MASTER_MAX_TOKENS == 20480

    def test_master_max_tokens_used_in_generation(self):
        """Verify the constant is actually used when generating (via source inspection).

        QO.32: After config externalization, MASTER_MAX_TOKENS is read through
        _get_master_max_tokens() helper which falls back to the module constant.
        """
        import inspect

        from cic_daily_report.generators import master_analysis

        source = inspect.getsource(master_analysis)
        # QO.32: The constant is now used via _get_master_max_tokens() helper
        assert "_get_master_max_tokens" in source
        assert "MASTER_MAX_TOKENS" in source


# =====================================================================
# QO.09: DXY conditional injection
# =====================================================================
class TestQO09DXYConditional:
    """QO.09 (VD-31): DXY only injected when macro event or DXY change >= 0.5%."""

    def test_dxy_excluded_when_small_change_no_macro(self):
        """DXY change -0.3% (< 0.5) + no macro event → DXY NOT in snapshot."""
        from cic_daily_report.breaking_pipeline import _format_market_snapshot

        result = _format_market_snapshot(_market_data(dxy_change=-0.3), has_macro_event=False)
        assert "DXY" not in result
        assert "BTC" in result  # Other data still present

    def test_dxy_included_when_large_change(self):
        """DXY change -0.7% (>= 0.5) → DXY included even without macro event."""
        from cic_daily_report.breaking_pipeline import _format_market_snapshot

        result = _format_market_snapshot(_market_data(dxy_change=-0.7), has_macro_event=False)
        assert "DXY: 99.8" in result

    def test_dxy_included_when_positive_large_change(self):
        """DXY change +0.5% (>= 0.5, absolute) → DXY included."""
        from cic_daily_report.breaking_pipeline import _format_market_snapshot

        result = _format_market_snapshot(_market_data(dxy_change=0.5), has_macro_event=False)
        assert "DXY: 99.8" in result

    def test_dxy_included_when_macro_event(self):
        """Macro event present → DXY always included regardless of change."""
        from cic_daily_report.breaking_pipeline import _format_market_snapshot

        result = _format_market_snapshot(_market_data(dxy_change=-0.1), has_macro_event=True)
        assert "DXY: 99.8" in result

    def test_dxy_included_when_exactly_0_5(self):
        """DXY change exactly 0.5% → included (boundary test)."""
        from cic_daily_report.breaking_pipeline import _format_market_snapshot

        result = _format_market_snapshot(_market_data(dxy_change=0.5), has_macro_event=False)
        assert "DXY" in result

    def test_dxy_excluded_when_0_49(self):
        """DXY change 0.49% → excluded (just below threshold)."""
        from cic_daily_report.breaking_pipeline import _format_market_snapshot

        result = _format_market_snapshot(_market_data(dxy_change=0.49), has_macro_event=False)
        assert "DXY" not in result

    def test_btc_eth_fg_always_present(self):
        """BTC, ETH, Fear&Greed always present regardless of DXY condition."""
        from cic_daily_report.breaking_pipeline import _format_market_snapshot

        result = _format_market_snapshot(_market_data(dxy_change=-0.1), has_macro_event=False)
        assert "BTC: $74,589" in result
        assert "ETH: $2,450" in result
        assert "Fear & Greed: 26" in result

    def test_empty_market_data(self):
        """None/empty market data → empty string (backward compat)."""
        from cic_daily_report.breaking_pipeline import _format_market_snapshot

        assert _format_market_snapshot(None) == ""
        assert _format_market_snapshot([]) == ""

    def test_default_has_macro_event_is_false(self):
        """Default has_macro_event=False → DXY excluded for small changes."""
        from cic_daily_report.breaking_pipeline import _format_market_snapshot

        # Calling without has_macro_event should default to False
        result = _format_market_snapshot(_market_data(dxy_change=-0.2))
        assert "DXY" not in result


# =====================================================================
# QO.09 fix: Expanded macro keywords + _macro_sources fix
# =====================================================================
class TestQO09MacroKeywordsExpanded:
    """QO.09 fix: Expanded macro keyword coverage and source correction."""

    def test_macro_sources_does_not_include_market_trigger(self):
        """market_trigger.py uses source='market_data', not 'market_trigger'.
        The _macro_sources set must reflect the actual source value."""
        import inspect

        from cic_daily_report import breaking_pipeline

        source = inspect.getsource(breaking_pipeline)
        # Verify "market_trigger" is NOT in _macro_sources
        # (We can't access the local var directly, so inspect the source)
        assert '"market_trigger"' not in source.split("_macro_sources")[1].split("}")[0]

    def test_employment_keywords_present(self):
        """Employment macro keywords added: nonfarm, payroll, unemployment, etc."""
        import inspect

        from cic_daily_report import breaking_pipeline

        source = inspect.getsource(breaking_pipeline)
        macro_section = source.split("_macro_keywords")[1].split("}")[0]
        for kw in ["nonfarm", "payroll", "unemployment", "jobless", "employment", "jobs"]:
            assert f'"{kw}"' in macro_section, f"Missing macro keyword: {kw}"

    def test_central_bank_keywords_present(self):
        """Central bank keywords added: ecb, boj, pboc, rate cut/hike, etc."""
        import inspect

        from cic_daily_report import breaking_pipeline

        source = inspect.getsource(breaking_pipeline)
        macro_section = source.split("_macro_keywords")[1].split("}")[0]
        for kw in ["ecb", "boj", "pboc", "rba", "boe", "rate cut", "rate hike"]:
            assert f'"{kw}"' in macro_section, f"Missing macro keyword: {kw}"

    def test_economic_indicator_keywords_present(self):
        """Economic indicator keywords added: ppi, ism, pmi, retail sales, housing."""
        import inspect

        from cic_daily_report import breaking_pipeline

        source = inspect.getsource(breaking_pipeline)
        macro_section = source.split("_macro_keywords")[1].split("}")[0]
        for kw in ["ppi", "ism", "pmi", "retail sales", "housing"]:
            assert f'"{kw}"' in macro_section, f"Missing macro keyword: {kw}"

    def test_government_fiscal_keywords_present(self):
        """Government fiscal keywords added: debt ceiling, shutdown."""
        import inspect

        from cic_daily_report import breaking_pipeline

        source = inspect.getsource(breaking_pipeline)
        macro_section = source.split("_macro_keywords")[1].split("}")[0]
        for kw in ["debt ceiling", "shutdown"]:
            assert f'"{kw}"' in macro_section, f"Missing macro keyword: {kw}"


# =====================================================================
# QO.11: Severity legend once per day
# =====================================================================
class TestQO11SeverityLegend:
    """QO.11 (VD-37): Severity legend sent with first breaking message of the day."""

    def test_severity_legend_constant_exists(self):
        """SEVERITY_LEGEND is defined with all 3 severity levels."""
        from cic_daily_report.breaking.severity_classifier import SEVERITY_LEGEND

        assert "\U0001f534" in SEVERITY_LEGEND  # 🔴
        assert "\U0001f7e0" in SEVERITY_LEGEND  # 🟠
        assert "\U0001f7e1" in SEVERITY_LEGEND  # 🟡

    def test_severity_legend_has_vietnamese_labels(self):
        """Legend explains emoji meanings in Vietnamese."""
        from cic_daily_report.breaking.severity_classifier import SEVERITY_LEGEND

        assert "Nghiêm trọng" in SEVERITY_LEGEND
        assert "Quan trọng" in SEVERITY_LEGEND
        assert "Đáng chú ý" in SEVERITY_LEGEND

    def test_should_send_legend_first_call(self):
        """First call of the day → True."""
        from cic_daily_report.breaking.severity_classifier import (
            reset_legend_tracker,
            should_send_legend,
        )

        reset_legend_tracker()
        assert should_send_legend() is True

    def test_should_send_legend_second_call_same_day(self):
        """Second call same day → False."""
        from cic_daily_report.breaking.severity_classifier import (
            reset_legend_tracker,
            should_send_legend,
        )

        reset_legend_tracker()
        now = datetime(2026, 4, 12, 10, 0, tzinfo=timezone.utc)
        assert should_send_legend(now) is True
        assert should_send_legend(now) is False

    def test_should_send_legend_next_day(self):
        """New day → True again."""
        from cic_daily_report.breaking.severity_classifier import (
            reset_legend_tracker,
            should_send_legend,
        )

        reset_legend_tracker()
        day1 = datetime(2026, 4, 12, 10, 0, tzinfo=timezone.utc)
        day2 = datetime(2026, 4, 13, 8, 0, tzinfo=timezone.utc)
        assert should_send_legend(day1) is True
        assert should_send_legend(day1) is False  # same day
        assert should_send_legend(day2) is True  # new day

    def test_should_send_legend_multiple_calls_same_day(self):
        """Multiple calls same day → only first is True."""
        from cic_daily_report.breaking.severity_classifier import (
            reset_legend_tracker,
            should_send_legend,
        )

        reset_legend_tracker()
        now = datetime(2026, 4, 12, 10, 0, tzinfo=timezone.utc)
        assert should_send_legend(now) is True
        for _ in range(5):
            assert should_send_legend(now) is False

    def test_reset_legend_tracker(self):
        """reset_legend_tracker resets state so next call returns True."""
        from cic_daily_report.breaking.severity_classifier import (
            reset_legend_tracker,
            should_send_legend,
        )

        reset_legend_tracker()
        now = datetime(2026, 4, 12, 10, 0, tzinfo=timezone.utc)
        should_send_legend(now)  # consume first
        assert should_send_legend(now) is False
        reset_legend_tracker()
        assert should_send_legend(now) is True

    def test_legend_imported_in_breaking_pipeline(self):
        """SEVERITY_LEGEND, should_send_legend, mark_legend_sent imported in breaking_pipeline."""
        from cic_daily_report import breaking_pipeline

        assert hasattr(breaking_pipeline, "SEVERITY_LEGEND")
        assert hasattr(breaking_pipeline, "should_send_legend")
        assert hasattr(breaking_pipeline, "mark_legend_sent")

    def test_legend_persistent_via_dedup_manager(self):
        """QO.11 fix: Legend tracked across processes via dedup_manager entries."""
        from cic_daily_report.breaking.dedup_manager import DedupManager
        from cic_daily_report.breaking.severity_classifier import (
            mark_legend_sent,
            reset_legend_tracker,
            should_send_legend,
        )

        reset_legend_tracker()
        dedup_mgr = DedupManager()
        now = datetime(2026, 4, 12, 10, 0, tzinfo=timezone.utc)

        # First call with dedup_mgr → True, then mark it
        assert should_send_legend(now, dedup_mgr=dedup_mgr) is True
        mark_legend_sent(dedup_mgr, now)

        # Simulate new process: reset module state, same dedup_mgr
        reset_legend_tracker()
        assert should_send_legend(now, dedup_mgr=dedup_mgr) is False

    def test_legend_persistent_different_day(self):
        """QO.11 fix: Legend resets on a new day even with dedup_manager persistence."""
        from cic_daily_report.breaking.dedup_manager import DedupManager
        from cic_daily_report.breaking.severity_classifier import (
            mark_legend_sent,
            reset_legend_tracker,
            should_send_legend,
        )

        reset_legend_tracker()
        dedup_mgr = DedupManager()
        day1 = datetime(2026, 4, 12, 10, 0, tzinfo=timezone.utc)
        day2 = datetime(2026, 4, 13, 8, 0, tzinfo=timezone.utc)

        # Day 1: send + mark
        assert should_send_legend(day1, dedup_mgr=dedup_mgr) is True
        mark_legend_sent(dedup_mgr, day1)

        # Day 2: new day → True again
        reset_legend_tracker()
        assert should_send_legend(day2, dedup_mgr=dedup_mgr) is True

    def test_legend_without_dedup_mgr_still_works(self):
        """QO.11 fix: Without dedup_mgr, falls back to module-level tracking (backward compat)."""
        from cic_daily_report.breaking.severity_classifier import (
            reset_legend_tracker,
            should_send_legend,
        )

        reset_legend_tracker()
        now = datetime(2026, 4, 12, 10, 0, tzinfo=timezone.utc)
        # Without dedup_mgr: module-level only (original behavior)
        assert should_send_legend(now) is True
        assert should_send_legend(now) is False
