"""Tests for Wave 2 tasks (QO.20-QO.27) — Quality Enforcement.

Covers:
- QO.20: Quality Gate BLOCK mode + configurable modes
- QO.21: Cross-tier overlap check
- QO.22: L2 force data injection
- QO.23: Research vs L5 scope separation
- QO.26: Consensus display enforcement
- QO.27: PriceSnapshot freeze prices per pipeline run
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from cic_daily_report.adapters.llm_adapter import LLMResponse
from cic_daily_report.collectors.market_data import MarketDataPoint, PriceSnapshot
from cic_daily_report.generators.article_generator import GeneratedArticle
from cic_daily_report.generators.master_analysis import MasterAnalysis
from cic_daily_report.generators.quality_gate import (
    DEFAULT_MODE,
    OVERLAP_THRESHOLD,
    VALID_MODES,
    QualityGateResult,
    _calculate_pair_overlap,
    _normalize_sentence,
    _split_sentences,
    check_cross_tier_overlap,
    get_quality_gate_mode,
    run_quality_gate,
    run_quality_gate_with_retry,
)
from cic_daily_report.generators.tier_extractor import (
    EXTRACTION_CONFIGS,
    L2_MIN_DATA_POINTS,
    _count_numbers_in_text,
    build_consensus_section,
    build_l2_data_injection,
    build_l2_retry_instruction,
    extract_all,
    extract_tier,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

GOOD_CONTENT = (
    "BTC tăng **3.2%** lên $87,500 trong phiên giao dịch hôm nay. "
    "ETH cũng tăng 2.1% đạt $3,200. "
    "Fear & Greed Index = 45, cho thấy thị trường trung tính. "
    "BTC Dominance đạt 56.8%, giảm nhẹ 0.3% so với hôm qua. "
    "Total Market Cap đạt $2.8 nghìn tỷ USD. "
    "Funding Rate = 0.01%, cho thấy derivatives cân bằng. "
    "RSI 14 ngày = 52.3, vùng trung tính. "
    "DXY giảm 0.4% về 104.2 — hỗ trợ tài sản rủi ro. "
    "Sector dẫn đầu: AI & Big Data tăng 4.1%. "
    "Volume giao dịch đạt $45.2 tỷ trong phiên hôm nay.\n"
)

FILLER_CONTENT = (
    "Thị trường hôm nay tiếp tục xu hướng hiện tại. "
    "Các nhà đầu tư đang theo dõi diễn biến tiếp theo. "
    "Nhiều chuyên gia cho rằng cần kiên nhẫn chờ đợi. "
    "Xu hướng dài hạn vẫn chưa rõ ràng. "
    "Cần thêm thời gian để xác nhận tín hiệu.\n"
)

MARKET_DATA_TEXT = (
    "- BTC: $87,500 (+3.2%) | Vol: $45.2M | MCap: $1,710.5B\n"
    "- ETH: $3,200 (+2.1%) | Vol: $18.3M | MCap: $384.8B\n"
)

ECON_EVENTS_TEXT = "- CPI Mỹ (14:30 UTC) — dự báo 3.2%\n"


def _make_input_data(econ="", market="") -> dict:
    return {
        "economic_events": econ,
        "market_data": market,
        "key_metrics": {},
    }


def _make_market_data_points() -> list[MarketDataPoint]:
    return [
        MarketDataPoint("BTC", 87500.0, 3.2, 45e6, 1710e9, "crypto", "CoinLore"),
        MarketDataPoint("ETH", 3200.0, 2.1, 18e6, 384e9, "crypto", "CoinLore"),
        MarketDataPoint("SOL", 145.0, 5.5, 5e6, 62e9, "crypto", "CoinLore"),
        MarketDataPoint("BNB", 580.0, -1.2, 3e6, 89e9, "crypto", "CoinLore"),
        MarketDataPoint("XRP", 0.62, 8.1, 2e6, 34e9, "crypto", "CoinLore"),
        MarketDataPoint("Fear&Greed", 35.0, 0, 0, 0, "index", "alternative.me"),
        MarketDataPoint("DXY", 104.2, -0.4, 0, 0, "macro", "yfinance"),
    ]


def _make_price_snapshot() -> PriceSnapshot:
    return PriceSnapshot(market_data=_make_market_data_points())


def _make_master(content: str = "Master content " * 500) -> MasterAnalysis:
    return MasterAnalysis(
        content=content,
        word_count=len(content.split()),
        llm_used="gemini-2.5-flash",
        generation_time_sec=15.0,
        finish_reason="stop",
        sections_found=8,
        has_conclusion=True,
    )


_MOCK_EXTRACTION = (
    "Phan tich thi truong tai san ma hoa hom nay co nhieu bien dong. "
    "BTC tang 3.2% len $87,500 trong phien giao dich. "
    "Fear & Greed Index = 45 cho thay thi truong trung tinh. "
    "SOL tang 5.5%, XRP tang 8.1%. " * 20
)


# ---------------------------------------------------------------------------
# QO.20: Quality Gate BLOCK mode
# ---------------------------------------------------------------------------


class TestQualityGateModes:
    """Tests for QUALITY_GATE_MODE configuration."""

    def test_default_mode_is_block(self):
        """QO.20: Default mode should be BLOCK."""
        assert DEFAULT_MODE == "BLOCK"

    def test_valid_modes(self):
        """QO.20: Only BLOCK, LOG, OFF are valid."""
        assert VALID_MODES == {"BLOCK", "LOG", "OFF"}

    def test_get_mode_no_config_returns_default(self):
        """QO.20: No config_loader → returns DEFAULT_MODE."""
        mode = get_quality_gate_mode(None)
        assert mode == "BLOCK"

    def test_get_mode_from_config(self):
        """QO.20: Reads mode from config_loader."""
        mock_config = MagicMock()
        mock_config.get_setting.return_value = "LOG"
        mode = get_quality_gate_mode(mock_config)
        assert mode == "LOG"

    def test_get_mode_invalid_falls_back(self):
        """QO.20: Invalid value → falls back to BLOCK."""
        mock_config = MagicMock()
        mock_config.get_setting.return_value = "INVALID"
        mode = get_quality_gate_mode(mock_config)
        assert mode == "BLOCK"

    def test_get_mode_exception_falls_back(self):
        """QO.20: Exception → falls back to BLOCK."""
        mock_config = MagicMock()
        mock_config.get_setting.side_effect = Exception("Sheet error")
        mode = get_quality_gate_mode(mock_config)
        assert mode == "BLOCK"


class TestRunQualityGateWithMode:
    """Tests for run_quality_gate() mode parameter."""

    def test_off_mode_skips_all_checks(self):
        """QO.20: OFF mode returns passed=True without checking."""
        result = run_quality_gate(FILLER_CONTENT, "L1", _make_input_data(), mode="OFF")
        assert result.passed is True
        assert "OFF" in result.details

    def test_log_mode_checks_but_doesnt_block(self):
        """QO.20: LOG mode checks quality but behavior is same as before."""
        result = run_quality_gate(
            FILLER_CONTENT, "L1", _make_input_data(market=MARKET_DATA_TEXT), mode="LOG"
        )
        assert result.passed is False
        assert result.retry_recommended is True
        assert "LOG" in result.details

    def test_block_mode_checks_and_recommends_retry(self):
        """QO.20: BLOCK mode checks quality and recommends retry."""
        result = run_quality_gate(
            FILLER_CONTENT, "L1", _make_input_data(market=MARKET_DATA_TEXT), mode="BLOCK"
        )
        assert result.passed is False
        assert result.retry_recommended is True
        assert "BLOCK" in result.details

    def test_block_mode_passes_on_good_content(self):
        """QO.20: BLOCK mode passes for good content."""
        result = run_quality_gate(
            GOOD_CONTENT, "L1", _make_input_data(market=MARKET_DATA_TEXT), mode="BLOCK"
        )
        assert result.passed is True
        assert result.retry_recommended is False

    def test_default_mode_is_block(self):
        """QO.20: Default mode parameter is BLOCK."""
        result = run_quality_gate(GOOD_CONTENT, "L1", _make_input_data(market=MARKET_DATA_TEXT))
        assert "BLOCK" in result.details


class TestRunQualityGateWithRetry:
    """Tests for run_quality_gate_with_retry() — BLOCK mode retry logic."""

    async def test_passes_first_try_no_retry(self):
        """QO.20: Good content passes first check, no retry needed."""
        content, result = await run_quality_gate_with_retry(
            GOOD_CONTENT,
            "L1",
            _make_input_data(market=MARKET_DATA_TEXT),
            mode="BLOCK",
        )
        assert result.passed is True
        assert result.was_retried is False
        # Wave 0.5.2 Fix 7: warning is now log-only (QUALITY_WARNING="" empty string).
        # Use the result flag instead of substring check.
        assert result.quality_warning_appended is False

    async def test_log_mode_no_retry(self):
        """QO.20: LOG mode never retries."""
        content, result = await run_quality_gate_with_retry(
            FILLER_CONTENT,
            "L1",
            _make_input_data(market=MARKET_DATA_TEXT),
            mode="LOG",
        )
        assert result.passed is False
        assert result.was_retried is False
        assert content == FILLER_CONTENT

    async def test_block_retry_success(self):
        """QO.20: BLOCK mode retries and succeeds with better content."""

        async def regenerate():
            return MagicMock(content=GOOD_CONTENT)

        content, result = await run_quality_gate_with_retry(
            FILLER_CONTENT,
            "L1",
            _make_input_data(market=MARKET_DATA_TEXT),
            regenerate_fn=regenerate,
            mode="BLOCK",
        )
        assert result.passed is True
        assert result.was_retried is True
        # Wave 0.5.2 Fix 7: passing retry never appends warning.
        assert result.quality_warning_appended is False

    async def test_block_retry_fails_appends_warning(self):
        """QO.20: BLOCK mode retries, still fails → appends quality warning."""

        async def regenerate():
            return MagicMock(content=FILLER_CONTENT)

        content, result = await run_quality_gate_with_retry(
            FILLER_CONTENT,
            "L1",
            _make_input_data(market=MARKET_DATA_TEXT),
            regenerate_fn=regenerate,
            mode="BLOCK",
        )
        assert result.passed is False
        assert result.was_retried is True
        # Wave 0.5.2 Fix 7: flag still set for ops dashboards, but content is
        # NOT mutated with a user-visible warning string anymore.
        assert result.quality_warning_appended is True
        assert "Lưu ý: Bài viết này có thể chưa đạt tiêu chuẩn" not in content

    async def test_block_no_regenerate_fn(self):
        """QO.20: BLOCK mode without regenerate_fn sends original."""
        content, result = await run_quality_gate_with_retry(
            FILLER_CONTENT,
            "L1",
            _make_input_data(market=MARKET_DATA_TEXT),
            regenerate_fn=None,
            mode="BLOCK",
        )
        assert result.passed is False
        assert content == FILLER_CONTENT

    async def test_block_regenerate_exception_appends_warning(self):
        """QO.20: BLOCK mode regenerate_fn throws → appends warning to original."""

        async def regenerate():
            raise RuntimeError("LLM error")

        content, result = await run_quality_gate_with_retry(
            FILLER_CONTENT,
            "L1",
            _make_input_data(market=MARKET_DATA_TEXT),
            regenerate_fn=regenerate,
            mode="BLOCK",
        )
        assert result.was_retried is True
        assert result.quality_warning_appended is True
        # Wave 0.5.2 Fix 7: warning text NOT inserted into content.
        assert "Lưu ý: Bài viết này có thể chưa đạt tiêu chuẩn" not in content

    async def test_regenerate_returns_string(self):
        """QO.20: regenerate_fn can return a plain string."""

        async def regenerate():
            return GOOD_CONTENT

        content, result = await run_quality_gate_with_retry(
            FILLER_CONTENT,
            "L1",
            _make_input_data(market=MARKET_DATA_TEXT),
            regenerate_fn=regenerate,
            mode="BLOCK",
        )
        assert result.passed is True
        assert result.was_retried is True


class TestQualityGateResultFields:
    """Tests for new QualityGateResult fields."""

    def test_was_retried_default_false(self):
        result = QualityGateResult(passed=True)
        assert result.was_retried is False

    def test_quality_warning_appended_default_false(self):
        result = QualityGateResult(passed=True)
        assert result.quality_warning_appended is False


# ---------------------------------------------------------------------------
# QO.21: Cross-tier overlap check
# ---------------------------------------------------------------------------


class TestNormalizeSentence:
    """Tests for _normalize_sentence()."""

    def test_lowercase_and_strip(self):
        assert _normalize_sentence("  Hello World.  ") == "hello world"

    def test_removes_punctuation(self):
        # WHY: Vietnamese diacritics (ă) are \w chars, so they survive the regex.
        # Punctuation (%, !) is removed, but accented chars remain.
        result = _normalize_sentence("BTC tăng 3.2%!")
        assert "btc" in result
        assert "!" not in result
        assert "%" not in result

    def test_collapses_whitespace(self):
        assert _normalize_sentence("a  b   c") == "a b c"


class TestSplitSentences:
    """Tests for _split_sentences()."""

    def test_splits_on_period(self):
        text = "Sentence one. Sentence two. Sentence three is longer than ten chars."
        result = _split_sentences(text)
        assert len(result) >= 2

    def test_excludes_headers(self):
        text = "## Header\nActual sentence with enough content."
        result = _split_sentences(text)
        assert not any("header" in s for s in result)

    def test_excludes_disclaimer(self):
        text = "*Tuyên bố miễn trừ trách nhiệm: blah blah blah.*"
        result = _split_sentences(text)
        assert len(result) == 0

    def test_excludes_short_fragments(self):
        text = "OK.\nThis is a real sentence with enough content."
        result = _split_sentences(text)
        assert len(result) == 1

    def test_empty_returns_empty(self):
        assert _split_sentences("") == []
        assert _split_sentences(None) == []

    def test_excludes_warning_lines(self):
        text = "⚠️ Quality warning here.\nActual content is long enough to count."
        result = _split_sentences(text)
        assert len(result) == 1


class TestCalculatePairOverlap:
    """Tests for _calculate_pair_overlap()."""

    def test_identical_sets_return_1(self):
        sents = ["sentence one", "sentence two"]
        assert _calculate_pair_overlap(sents, sents) == 1.0

    def test_no_overlap_returns_0(self):
        a = ["alpha beta gamma"]
        b = ["delta epsilon zeta"]
        assert _calculate_pair_overlap(a, b) == 0.0

    def test_partial_overlap(self):
        a = ["s1", "s2", "s3", "s4"]
        b = ["s1", "s2", "x1", "x2"]  # 2/4 overlap
        result = _calculate_pair_overlap(a, b)
        assert abs(result - 0.5) < 0.01

    def test_empty_sets_return_0(self):
        assert _calculate_pair_overlap([], ["a"]) == 0.0
        assert _calculate_pair_overlap(["a"], []) == 0.0
        assert _calculate_pair_overlap([], []) == 0.0


class TestCheckCrossTierOverlap:
    """Tests for check_cross_tier_overlap()."""

    def test_no_overlap_passes(self):
        contents = {
            "L1": "BTC price analysis is unique content for tier one today.",
            "L2": "ETH sector rotation and bluechip performance review here.",
            "L3": "Macro analysis DXY USD gold correlation deep dive now.",
            "L4": "Risk assessment contradictions between indicators today.",
            "L5": "Strategic outlook scenarios base bull bear predictions.",
        }
        result = check_cross_tier_overlap(contents)
        assert result["passed"] is True
        assert result["exceeded"] == []
        assert result["threshold"] == OVERLAP_THRESHOLD

    def test_high_overlap_fails(self):
        """Identical content in adjacent tiers should fail."""
        shared = (
            "This exact same sentence is duplicated across tiers for testing overlap detection."
        )
        contents = {
            "L1": shared,
            "L2": shared,
        }
        result = check_cross_tier_overlap(contents)
        assert result["passed"] is False
        assert "L1↔L2" in result["exceeded"]

    def test_partial_tiers_handled(self):
        """Missing tiers should not crash."""
        contents = {"L1": "Some content here.", "L3": "Different content there."}
        result = check_cross_tier_overlap(contents)
        # L1↔L2 and L2↔L3 skipped (L2 missing)
        assert result["passed"] is True

    def test_overlap_percentage_in_pairs(self):
        """Overlap percentage should be in the pairs dict."""
        contents = {
            "L1": "BTC analysis unique to L1 with specific data points and insights.",
            "L2": "ETH analysis unique to L2 with different data points entirely.",
        }
        result = check_cross_tier_overlap(contents)
        assert "L1↔L2" in result["pairs"]
        assert isinstance(result["pairs"]["L1↔L2"], float)

    def test_threshold_value(self):
        assert OVERLAP_THRESHOLD == 0.40


# ---------------------------------------------------------------------------
# QO.22: L2 force data injection
# ---------------------------------------------------------------------------


class TestCountNumbersInText:
    """Tests for _count_numbers_in_text()."""

    def test_counts_percentages(self):
        text = "BTC tăng 3.2% và ETH tăng 2.1%."
        assert _count_numbers_in_text(text) >= 2

    def test_counts_dollar_amounts(self):
        text = "BTC đạt $87,500 và ETH đạt $3,200."
        assert _count_numbers_in_text(text) >= 2

    def test_counts_abbreviated_numbers(self):
        text = "Volume đạt 45.2B và MCap 1.7T."
        assert _count_numbers_in_text(text) >= 2

    def test_counts_metric_values(self):
        # F&G = 45 matches the metric pattern; RSI = 52.3 also matches
        text = "F&G = 45 và RSI = 52"
        assert _count_numbers_in_text(text) >= 2

    def test_zero_for_no_numbers(self):
        text = "Thị trường hôm nay tiếp tục xu hướng hiện tại."
        assert _count_numbers_in_text(text) == 0


class TestBuildL2DataInjection:
    """Tests for build_l2_data_injection()."""

    def test_returns_empty_without_snapshot(self):
        assert build_l2_data_injection(None) == ""

    def test_includes_btc_price(self):
        snapshot = _make_price_snapshot()
        result = build_l2_data_injection(snapshot)
        assert "$87,500" in result or "87500" in result

    def test_includes_fear_greed(self):
        snapshot = _make_price_snapshot()
        result = build_l2_data_injection(snapshot)
        assert "35" in result or "Fear" in result

    def test_includes_top_performers(self):
        snapshot = _make_price_snapshot()
        result = build_l2_data_injection(snapshot)
        # XRP has 8.1% change, SOL 5.5%
        assert "XRP" in result or "SOL" in result

    def test_mandatory_label(self):
        """Injection should have BẮT BUỘC label."""
        snapshot = _make_price_snapshot()
        result = build_l2_data_injection(snapshot)
        assert "BẮT BUỘC" in result or "B\u1eaeT BU\u1ed8C" in result


class TestBuildL2RetryInstruction:
    """Tests for build_l2_retry_instruction()."""

    def test_includes_specific_values(self):
        snapshot = _make_price_snapshot()
        result = build_l2_retry_instruction(snapshot)
        assert "87,500" in result or "BTC" in result

    def test_without_snapshot(self):
        result = build_l2_retry_instruction(None)
        assert "BTC price" in result

    def test_mandatory_keyword(self):
        result = build_l2_retry_instruction(_make_price_snapshot())
        assert "BẮT BUỘC" in result or "B\u1eaeT BU\u1ed8C" in result


class TestL2MinDataPoints:
    """Tests for L2_MIN_DATA_POINTS constant."""

    def test_value(self):
        assert L2_MIN_DATA_POINTS == 3


# ---------------------------------------------------------------------------
# QO.23: Research vs L5 scope separation
# ---------------------------------------------------------------------------


class TestResearchL5ScopeSeparation:
    """Tests for scope boundary prompts in Research and L5."""

    def test_research_system_prompt_has_scope_boundary(self):
        from cic_daily_report.generators.research_generator import RESEARCH_SYSTEM_PROMPT

        # Should mention what research MUST focus on
        assert "on-chain" in RESEARCH_SYSTEM_PROMPT.lower() or "PHẢI" in RESEARCH_SYSTEM_PROMPT
        # Should mention what research MUST NOT repeat
        assert "KHÔNG lặp" in RESEARCH_SYSTEM_PROMPT or "không lặp" in RESEARCH_SYSTEM_PROMPT

    async def test_l5_extraction_adds_scope_in_prompt(self):
        """L5 extraction prompt should include scope boundary via extract_tier."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                text=_MOCK_EXTRACTION, tokens_used=2000, model="mock", finish_reason="stop"
            )
        )

        master = _make_master()
        config = EXTRACTION_CONFIGS["L5"]
        await extract_tier(mock_llm, master, config)

        call_kwargs = mock_llm.generate.call_args.kwargs
        prompt = call_kwargs["prompt"]
        # Should contain L5 scope boundary instruction
        assert "Research" in prompt or "PHẠM VI L5" in prompt or "PH\u1ea0M VI L5" in prompt


# ---------------------------------------------------------------------------
# QO.26: Consensus display enforcement
# ---------------------------------------------------------------------------


class TestBuildConsensusSection:
    """Tests for build_consensus_section()."""

    def test_returns_empty_without_data(self):
        assert build_consensus_section(None) == ""
        assert build_consensus_section([]) == ""

    def test_includes_market_overall(self):
        mock_consensus = MagicMock()
        mock_consensus.asset = "market_overall"
        mock_consensus.label = "BULLISH"
        mock_consensus.score = 0.35
        mock_consensus.source_count = 5

        result = build_consensus_section([mock_consensus])
        assert "TĂNG" in result or "T\u0102NG" in result
        assert "0.35" in result or "+0.35" in result

    def test_fallback_to_btc(self):
        """If no market_overall, uses BTC."""
        mock_consensus = MagicMock()
        mock_consensus.asset = "BTC"
        mock_consensus.label = "NEUTRAL"
        mock_consensus.score = 0.05
        mock_consensus.source_count = 3

        result = build_consensus_section([mock_consensus])
        assert "BTC" in result
        assert "TRUNG" in result or "TRUNG L\u1eacP" in result

    def test_consensus_section_format(self):
        """Should have bold header."""
        mock_consensus = MagicMock()
        mock_consensus.asset = "market_overall"
        mock_consensus.label = "BEARISH"
        mock_consensus.score = -0.30
        mock_consensus.source_count = 4

        result = build_consensus_section([mock_consensus])
        assert "**" in result  # Bold formatting


class TestConsensusEnforcementInExtraction:
    """Tests for consensus section being added/checked during extraction."""

    async def test_consensus_instruction_in_l3_prompt(self):
        """L3 extraction should include consensus display instruction."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                text=_MOCK_EXTRACTION, tokens_used=2000, model="mock", finish_reason="stop"
            )
        )

        mock_consensus = MagicMock()
        mock_consensus.asset = "market_overall"
        mock_consensus.label = "BULLISH"
        mock_consensus.score = 0.35
        mock_consensus.source_count = 5

        master = _make_master()
        config = EXTRACTION_CONFIGS["L3"]
        await extract_tier(
            mock_llm,
            master,
            config,
            consensus_data=[mock_consensus],
        )

        call_kwargs = mock_llm.generate.call_args.kwargs
        prompt = call_kwargs["prompt"]
        assert "ĐỒNG THUẬN" in prompt or "\u0110\u1ed2NG THU\u1eacN" in prompt

    async def test_consensus_not_in_l1_prompt(self):
        """L1 extraction should NOT include consensus instruction."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                text=_MOCK_EXTRACTION, tokens_used=2000, model="mock", finish_reason="stop"
            )
        )

        mock_consensus = MagicMock()
        mock_consensus.asset = "market_overall"
        mock_consensus.label = "BULLISH"
        mock_consensus.score = 0.35
        mock_consensus.source_count = 5

        master = _make_master()
        config = EXTRACTION_CONFIGS["L1"]
        await extract_tier(
            mock_llm,
            master,
            config,
            consensus_data=[mock_consensus],
        )

        call_kwargs = mock_llm.generate.call_args.kwargs
        prompt = call_kwargs["prompt"]
        # L1 is NOT in the consensus enforcement list
        assert "ĐỒNG THUẬN THỊ TRƯỜNG" not in prompt
        assert "\u0110\u1ed2NG THU\u1eacN TH\u1eca TR\u01af\u1edcNG" not in prompt

    async def test_consensus_appended_when_missing(self):
        """If LLM output lacks consensus section, it should be appended."""
        # Content without any consensus keywords
        content_without_consensus = (
            "Thi truong hom nay tang 3.2% voi nhieu bien dong. "
            "BTC dat $87,500 trong phien giao dich. " * 20
        )
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                text=content_without_consensus, tokens_used=2000, model="mock", finish_reason="stop"
            )
        )

        mock_consensus = MagicMock()
        mock_consensus.asset = "market_overall"
        mock_consensus.label = "BULLISH"
        mock_consensus.score = 0.35
        mock_consensus.source_count = 5

        master = _make_master()
        config = EXTRACTION_CONFIGS["L3"]
        article = await extract_tier(
            mock_llm,
            master,
            config,
            consensus_data=[mock_consensus],
        )

        # Consensus section should have been appended
        assert "TĂNG" in article.content or "T\u0102NG" in article.content


# ---------------------------------------------------------------------------
# QO.27: PriceSnapshot
# ---------------------------------------------------------------------------


class TestPriceSnapshot:
    """Tests for PriceSnapshot dataclass."""

    def test_create_with_data(self):
        snapshot = _make_price_snapshot()
        assert len(snapshot.market_data) > 0
        assert snapshot.timestamp != ""

    def test_create_empty(self):
        snapshot = PriceSnapshot()
        assert len(snapshot.market_data) == 0
        assert snapshot.timestamp != ""

    def test_get_price(self):
        snapshot = _make_price_snapshot()
        assert snapshot.get_price("BTC") == 87500.0
        assert snapshot.get_price("ETH") == 3200.0
        assert snapshot.get_price("NONEXISTENT") is None

    def test_get_change_24h(self):
        snapshot = _make_price_snapshot()
        assert snapshot.get_change_24h("BTC") == 3.2
        assert snapshot.get_change_24h("NONEXISTENT") is None

    def test_get_data_point(self):
        snapshot = _make_price_snapshot()
        dp = snapshot.get_data_point("BTC")
        assert dp is not None
        assert dp.symbol == "BTC"
        assert dp.price == 87500.0

    def test_get_top_performers(self):
        snapshot = _make_price_snapshot()
        top = snapshot.get_top_performers(3)
        assert len(top) <= 3
        assert all(dp.data_type == "crypto" for dp in top)
        # Should be sorted by change_24h descending
        if len(top) >= 2:
            assert top[0].change_24h >= top[1].change_24h

    def test_btc_price_property(self):
        snapshot = _make_price_snapshot()
        assert snapshot.btc_price == 87500.0

    def test_fear_greed_property(self):
        snapshot = _make_price_snapshot()
        assert snapshot.fear_greed == 35.0

    def test_empty_snapshot_properties(self):
        snapshot = PriceSnapshot()
        assert snapshot.btc_price is None
        assert snapshot.fear_greed is None


class TestCreatePriceSnapshot:
    """Tests for create_price_snapshot() async function."""

    @patch("cic_daily_report.collectors.market_data.collect_market_data")
    async def test_creates_snapshot(self, mock_collect):
        from cic_daily_report.collectors.market_data import create_price_snapshot

        mock_collect.return_value = _make_market_data_points()
        snapshot = await create_price_snapshot()
        assert isinstance(snapshot, PriceSnapshot)
        assert len(snapshot.market_data) > 0
        assert snapshot.btc_price == 87500.0

    @patch("cic_daily_report.collectors.market_data.collect_market_data")
    async def test_empty_market_data(self, mock_collect):
        from cic_daily_report.collectors.market_data import create_price_snapshot

        mock_collect.return_value = []
        snapshot = await create_price_snapshot()
        assert isinstance(snapshot, PriceSnapshot)
        assert len(snapshot.market_data) == 0


# ---------------------------------------------------------------------------
# Integration: extract_all with QO.21, QO.22, QO.26
# ---------------------------------------------------------------------------


class TestExtractAllWithOverlapCheck:
    """Tests for extract_all() with cross-tier overlap check (QO.21)."""

    async def test_passes_price_snapshot_to_extract_tier(self):
        """QO.22: price_snapshot should be passed through to extract_tier."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                text=_MOCK_EXTRACTION, tokens_used=2000, model="mock", finish_reason="stop"
            )
        )
        mock_llm.suggest_cooldown = lambda: 0

        snapshot = _make_price_snapshot()
        master = _make_master()

        articles = await extract_all(
            mock_llm,
            master,
            {},
            price_snapshot=snapshot,
        )
        assert len(articles) == 6

        # L2 prompt should contain injected data
        calls = mock_llm.generate.call_args_list
        l2_prompt = calls[1].kwargs["prompt"]  # L2 is 2nd extraction
        assert "BẮT BUỘC" in l2_prompt or "B\u1eaeT BU\u1ed8C" in l2_prompt

    async def test_passes_consensus_to_extract_tier(self):
        """QO.26: consensus_data should be passed through to extract_tier."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                text=_MOCK_EXTRACTION, tokens_used=2000, model="mock", finish_reason="stop"
            )
        )
        mock_llm.suggest_cooldown = lambda: 0

        mock_consensus = MagicMock()
        mock_consensus.asset = "market_overall"
        mock_consensus.label = "BULLISH"
        mock_consensus.score = 0.35
        mock_consensus.source_count = 5

        master = _make_master()
        articles = await extract_all(
            mock_llm,
            master,
            {},
            consensus_data=[mock_consensus],
        )
        assert len(articles) == 6

    async def test_backward_compat_no_snapshot_no_consensus(self):
        """Backward compat: extract_all works without new params."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                text=_MOCK_EXTRACTION, tokens_used=2000, model="mock", finish_reason="stop"
            )
        )
        mock_llm.suggest_cooldown = lambda: 0

        master = _make_master()
        articles = await extract_all(mock_llm, master, {})
        assert len(articles) == 6


class TestExtractTierBackwardCompat:
    """Tests for extract_tier() backward compatibility."""

    async def test_works_without_new_params(self):
        """extract_tier should work without price_snapshot and consensus_data."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                text=_MOCK_EXTRACTION, tokens_used=2000, model="mock", finish_reason="stop"
            )
        )

        master = _make_master()
        config = EXTRACTION_CONFIGS["L1"]
        article = await extract_tier(mock_llm, master, config)
        assert isinstance(article, GeneratedArticle)
        assert article.tier == "L1"

    async def test_l2_without_snapshot_no_injection(self):
        """L2 without price_snapshot should not inject data."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                text=_MOCK_EXTRACTION, tokens_used=2000, model="mock", finish_reason="stop"
            )
        )

        master = _make_master()
        config = EXTRACTION_CONFIGS["L2"]
        await extract_tier(mock_llm, master, config)

        call_kwargs = mock_llm.generate.call_args.kwargs
        prompt = call_kwargs["prompt"]
        # Should NOT have mandatory data injection
        assert "BẮT BUỘC" not in prompt and "B\u1eaeT BU\u1ed8C" not in prompt
