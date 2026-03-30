"""Tests for generators/article_generator.py — all mocked."""

from unittest.mock import AsyncMock, patch

from cic_daily_report.adapters.llm_adapter import LLMResponse
from cic_daily_report.generators.article_generator import (
    DISCLAIMER,
    GenerationContext,
    _filter_data_for_tier,
    _get_tier_data_sources,
    _validate_and_clean_output,
    generate_tier_articles,
)
from cic_daily_report.generators.template_engine import (
    ArticleTemplate,
    SectionTemplate,
)


def _make_templates(*tiers: str) -> dict[str, ArticleTemplate]:
    result = {}
    for tier in tiers:
        result[tier] = ArticleTemplate(
            tier=tier,
            sections=[
                SectionTemplate(tier, "Intro", True, 1, "Intro for {tier}", 200),
                SectionTemplate(tier, "Analysis", True, 2, "Analyze {coin_list}", 500),
            ],
        )
    return result


def _make_context() -> GenerationContext:
    return GenerationContext(
        coin_lists={"L1": ["BTC", "ETH"], "L2": ["BTC", "ETH", "SOL"]},
        market_data="BTC at $105K",
        news_summary="SEC news today",
        key_metrics={"BTC Price": "$105,000"},
    )


_MOCK_ARTICLE = (
    "Thị trường tài sản mã hóa hôm nay có nhiều biến động đáng chú ý. "
    "Giá Bitcoin đang giao dịch quanh mức hỗ trợ quan trọng. "
    "Ethereum cũng có xu hướng tương tự với khối lượng giao dịch tăng. "
    "Theo dữ liệu từ CoinLore, tâm lý thị trường đang thận trọng. "
    "Các chỉ số kỹ thuật cho thấy xu hướng ngắn hạn chưa rõ ràng. "
    "Nhà đầu tư cần theo dõi thêm các yếu tố vĩ mô. "
    "Dữ liệu on-chain cho thấy dòng tiền vào sàn giao dịch đang giảm. "
    "Điều này có thể ảnh hưởng đến giá trong thời gian tới."
)


class TestGenerateTierArticles:
    async def test_generates_articles_for_available_tiers(self):
        templates = _make_templates("L1", "L2")
        context = _make_context()

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(text=_MOCK_ARTICLE, tokens_used=100, model="test-model")
        )

        articles = await generate_tier_articles(mock_llm, templates, context)

        assert len(articles) == 2
        assert articles[0].tier == "L1"
        assert articles[1].tier == "L2"

    async def test_articles_have_disclaimer(self):
        templates = _make_templates("L1")
        context = _make_context()

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(text=_MOCK_ARTICLE, tokens_used=50, model="m")
        )

        articles = await generate_tier_articles(mock_llm, templates, context)

        assert len(articles) == 1
        assert DISCLAIMER in articles[0].content

    async def test_skips_tiers_without_templates(self):
        templates = _make_templates("L1")  # Only L1
        context = _make_context()

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(text=_MOCK_ARTICLE, tokens_used=10, model="m")
        )

        articles = await generate_tier_articles(mock_llm, templates, context)

        # Only L1 generated, L2-L5 skipped
        assert len(articles) == 1
        assert articles[0].tier == "L1"

    async def test_continues_on_llm_failure(self):
        templates = _make_templates("L1", "L2")
        context = _make_context()

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            side_effect=[
                Exception("LLM down"),
                LLMResponse(text=_MOCK_ARTICLE, tokens_used=10, model="m"),
            ]
        )

        articles = await generate_tier_articles(mock_llm, templates, context)

        # L1 failed, L2 succeeded
        assert len(articles) == 1
        assert articles[0].tier == "L2"

    async def test_coin_list_substituted(self):
        templates = _make_templates("L1")
        context = _make_context()

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(text="ok", tokens_used=10, model="m")
        )

        await generate_tier_articles(mock_llm, templates, context)

        # Verify the prompt sent to LLM contains coin list
        call_args = mock_llm.generate.call_args
        prompt = call_args.kwargs.get("prompt", call_args[1].get("prompt", ""))
        assert "BTC, ETH" in prompt

    @patch("cic_daily_report.generators.article_generator.asyncio.sleep", new_callable=AsyncMock)
    async def test_retries_once_on_429_then_succeeds(self, mock_sleep):
        """Q1: 429 rate limit → wait → retry → success."""
        templates = _make_templates("L1")
        context = _make_context()

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            side_effect=[
                Exception("429 Too Many Requests"),
                LLMResponse(text=_MOCK_ARTICLE, tokens_used=100, model="m"),
            ]
        )

        articles = await generate_tier_articles(mock_llm, templates, context)

        assert len(articles) == 1
        assert articles[0].tier == "L1"
        assert mock_llm.generate.call_count == 2  # called twice (1 fail + 1 success)
        mock_sleep.assert_called_with(120)  # _TIER_RETRY_WAIT = 120s

    @patch("cic_daily_report.generators.article_generator.asyncio.sleep", new_callable=AsyncMock)
    async def test_gives_up_after_two_429_failures(self, mock_sleep):
        """Q1: 429 → retry → 429 again → skip tier."""
        templates = _make_templates("L1")
        context = _make_context()

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            side_effect=[
                Exception("429 Too Many Requests"),
                Exception("429 Too Many Requests"),
            ]
        )

        articles = await generate_tier_articles(mock_llm, templates, context)

        assert len(articles) == 0  # tier skipped after 2 failures
        assert mock_llm.generate.call_count == 2

    @patch("cic_daily_report.generators.article_generator.asyncio.sleep", new_callable=AsyncMock)
    async def test_non_429_error_skips_without_retry(self, mock_sleep):
        """Non-429 errors should NOT retry — skip immediately."""
        templates = _make_templates("L1", "L2")
        context = _make_context()

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            side_effect=[
                Exception("Connection timeout"),
                LLMResponse(text=_MOCK_ARTICLE, tokens_used=100, model="m"),
            ]
        )

        articles = await generate_tier_articles(mock_llm, templates, context)

        # L1 failed (no retry), L2 succeeded
        assert len(articles) == 1
        assert articles[0].tier == "L2"
        assert mock_llm.generate.call_count == 2  # 1 fail (L1) + 1 success (L2)

    async def test_prompt_contains_analysis_requirements(self):
        """Q2+Q4: Prompt must include comparison, meaning, and causation requirements."""
        templates = _make_templates("L1")
        context = _make_context()

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(text=_MOCK_ARTICLE, tokens_used=10, model="m")
        )

        await generate_tier_articles(mock_llm, templates, context)

        call_args = mock_llm.generate.call_args
        prompt = call_args.kwargs.get("prompt", call_args[1].get("prompt", ""))
        assert "SO SÁNH" in prompt
        assert "NHÂN QUẢ" in prompt  # v0.30.1: restructured quality rules
        # v0.30.1: format simplified — check emoji guidance + mobile-friendly
        assert "emoji" in prompt.lower() or "📈" in prompt

    async def test_nq05_system_prompt_used(self):
        """v0.30.1: NQ05 slimmed in system prompt — only 1-line reminder, post-filter enforces."""
        templates = _make_templates("L1")
        context = _make_context()

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(text="ok", tokens_used=10, model="m")
        )

        await generate_tier_articles(mock_llm, templates, context)

        call_args = mock_llm.generate.call_args
        sys_prompt = call_args.kwargs.get("system_prompt", "")
        assert "tài sản mã hóa" in sys_prompt
        assert "CHỐNG BỊA" in sys_prompt


class TestPhase1QuickWins:
    """Phase 1 tests: D1 (no hardcoded numbers), E2 (temperature=0.3)."""

    def test_tier_context_no_hardcoded_numbers(self):
        """D1: Tier context L3-L5 must not contain hardcoded data that conflicts with API."""
        import inspect

        import cic_daily_report.daily_pipeline as dp

        source = inspect.getsource(dp)
        # Old hardcoded values must be gone
        assert "3.75%" not in source, "Hardcoded Fed rate 3.75% still in tier context"
        assert "sideway $73K-$77K" not in source, "Hardcoded BTC range still in tier context"
        assert "Fed meeting 19/03" not in source, "Hardcoded Fed date still in tier context"
        assert "Fed dovish 19/03" not in source, "Hardcoded Fed scenario still in tier context"
        assert "DXY <99" not in source, "Hardcoded DXY threshold still in tier context"

    async def test_temperature_daily_is_0_3(self):
        """E2: article_generator must use temperature=0.3."""
        templates = _make_templates("L1")
        context = _make_context()

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(text=_MOCK_ARTICLE, tokens_used=100, model="m")
        )

        await generate_tier_articles(mock_llm, templates, context)

        call_kwargs = mock_llm.generate.call_args
        temperature = call_kwargs.kwargs.get("temperature")
        assert temperature == 0.3, f"Expected temperature=0.3, got {temperature}"


class TestAntiHallucinationGuardrails:
    """v0.19.0: NQ05_SYSTEM_PROMPT anti-hallucination changes."""

    def test_nq05_prompt_no_glassnode_example(self):
        """NQ05_SYSTEM_PROMPT should NOT contain old 'Theo CoinLore' example."""
        from cic_daily_report.generators.article_generator import NQ05_SYSTEM_PROMPT

        assert "Theo CoinLore" not in NQ05_SYSTEM_PROMPT

    def test_prompt_has_anti_hallucination_guardrail(self):
        from cic_daily_report.generators.article_generator import NQ05_SYSTEM_PROMPT

        assert "CHỐNG BỊA" in NQ05_SYSTEM_PROMPT

    async def test_guardrail_bans_fabrication_sources(self):
        """v0.22.0: System prompt bans known fabrication sources."""
        from cic_daily_report.generators.article_generator import NQ05_SYSTEM_PROMPT

        # These sources must be explicitly banned to prevent LLM fabrication
        assert "Bloomberg" in NQ05_SYSTEM_PROMPT
        assert "CryptoQuant" in NQ05_SYSTEM_PROMPT
        assert "TradingView" in NQ05_SYSTEM_PROMPT


class TestTierDataSources:
    """v0.28.0: Tests for _get_tier_data_sources()."""

    def test_l1_sources_no_coingecko(self):
        """L1 must NOT include CoinGecko — it only receives CoinLore + alternative.me data."""
        from cic_daily_report.generators.article_generator import _get_tier_data_sources

        result = _get_tier_data_sources("L1")
        assert "CoinLore" in result
        assert "alternative.me" in result
        assert "CoinGecko" not in result

    def test_l3_l4_l5_include_faireconomy_and_whale_alert(self):
        """L3, L4, L5 all receive FairEconomy calendar and Whale Alert data."""
        from cic_daily_report.generators.article_generator import _get_tier_data_sources

        for tier in ("L3", "L4", "L5"):
            result = _get_tier_data_sources(tier)
            assert "FairEconomy" in result, f"{tier} missing FairEconomy"
            assert "Whale Alert" in result, f"{tier} missing Whale Alert"

    def test_unknown_tier_returns_fallback(self):
        """An unrecognised tier string falls back to 'CoinLore, CoinGecko'."""
        from cic_daily_report.generators.article_generator import _get_tier_data_sources

        assert _get_tier_data_sources("L99") == "CoinLore, CoinGecko"
        assert _get_tier_data_sources("") == "CoinLore, CoinGecko"


class TestValidateAndClean:
    """v0.28.0: Tests for _validate_and_clean_output()."""

    def test_clean_content_returned_unchanged_no_warnings(self):
        """Content with no fabricated metrics or banned sources passes through clean."""
        from cic_daily_report.generators.article_generator import _validate_and_clean_output

        content = (
            "BTC đang giao dịch ở mức $105,000. "
            "Fear & Greed Index ở mức 45 (Neutral). "
            "Tâm lý thị trường đang thận trọng trước các sự kiện vĩ mô."
        )
        cleaned, warnings = _validate_and_clean_output(content, "L3", "")
        assert cleaned == content
        assert warnings == []

    def test_mvrv_without_onchain_data_removes_line(self):
        """A line containing MVRV is removed when MVRV is absent from the onchain input."""
        from cic_daily_report.generators.article_generator import _validate_and_clean_output

        content = (
            "BTC đang giao dịch tốt.\n"
            "MVRV ratio hiện tại cho thấy thị trường đang overvalued.\n"
            "Nhà đầu tư nên theo dõi thêm."
        )
        cleaned, warnings = _validate_and_clean_output(content, "L3", onchain_data="")
        assert "MVRV" not in cleaned
        assert any("MVRV" in w for w in warnings)
        # Lines without MVRV must be preserved
        assert "BTC đang giao dịch tốt." in cleaned

    def test_bloomberg_citation_line_removed(self):
        """A line citing Bloomberg is removed and a warning is recorded."""
        from cic_daily_report.generators.article_generator import _validate_and_clean_output

        content = (
            "Thị trường phục hồi mạnh.\n"
            "Theo Bloomberg, dòng tiền ETF vào BTC đạt $500M trong tuần qua.\n"
            "Điều này phản ánh sức mua tích cực."
        )
        cleaned, warnings = _validate_and_clean_output(content, "L3", onchain_data="")
        assert "Bloomberg" not in cleaned
        assert any("Bloomberg" in w for w in warnings)
        assert "Thị trường phục hồi mạnh." in cleaned
        assert "Điều này phản ánh sức mua tích cực." in cleaned

    def test_l2_too_few_coins_triggers_warning(self):
        """L2 content mentioning fewer than 10 coin symbols produces a coin-count warning."""
        from cic_daily_report.generators.article_generator import _validate_and_clean_output

        # Mention only 2 coins — well below the ≥10 threshold
        content = "BTC và ETH đang dẫn dắt thị trường hôm nay với diễn biến tích cực."
        _cleaned, warnings = _validate_and_clean_output(content, "L2", onchain_data="")
        assert any("coin" in w.lower() for w in warnings), (
            f"Expected coin-count warning, got: {warnings}"
        )

    def test_l2_project_names_counted_as_coins(self):
        """v0.28.0: Project names (Ripple, Cardano) count toward L2 coin threshold."""
        from cic_daily_report.generators.article_generator import _validate_and_clean_output

        # Mix of tickers and project names — should count as 5 unique coins
        content = (
            "BTC đang tăng mạnh. Ethereum cũng phục hồi theo. "
            "Ripple có tin hợp tác mới. Cardano ra mắt bản nâng cấp. "
            "SOL giao dịch tích cực."
        )
        _cleaned, warnings = _validate_and_clean_output(content, "L2", onchain_data="")
        # Should count: BTC, ETH (Ethereum), XRP (Ripple), ADA (Cardano), SOL = 5
        coin_warnings = [w for w in warnings if "coin" in w.lower()]
        if coin_warnings:
            # Extract the number from warning like "L2 only mentions 5 coins..."
            import re

            match = re.search(r"(\d+) coins", coin_warnings[0])
            assert match and int(match.group(1)) >= 5, (
                f"Expected ≥5 coins counted, got: {coin_warnings[0]}"
            )


class TestResearchDataInContext:
    """v2.0 P1.1: research_data_text flows into GenerationContext and tier articles."""

    _SAMPLE_RESEARCH = (
        "=== ON-CHAIN NANG CAO (nguon: BGeometrics) ===\n"
        "  MVRV_Z_Score: 2.1500 (BGeometrics, 2026-03-27)\n"
        "  NUPL: 0.5800 (BGeometrics, 2026-03-27)\n"
        "  SOPR: 1.0200 (BGeometrics, 2026-03-27)\n"
        "  Puell_Multiple: 1.3000 (BGeometrics, 2026-03-27)\n\n"
        "=== SPOT BITCOIN ETF FLOW (nguon: btcetffundflow.com) ===\n"
        "  Tong dong tien: $150,000,000\n"
    )

    def test_generation_context_accepts_research_data_text(self):
        """GenerationContext dataclass can be instantiated with research_data_text."""
        ctx = GenerationContext(research_data_text=self._SAMPLE_RESEARCH)
        assert ctx.research_data_text == self._SAMPLE_RESEARCH

    def test_generation_context_defaults_empty_research_data(self):
        """research_data_text defaults to empty string when not provided."""
        ctx = GenerationContext()
        assert ctx.research_data_text == ""

    def test_filter_l1_excludes_research_data(self):
        """L1 (beginners) must NOT receive research data."""
        ctx = GenerationContext(
            market_data="BTC: $105,000",
            research_data_text=self._SAMPLE_RESEARCH,
        )
        filtered = _filter_data_for_tier("L1", ctx, "")
        assert filtered["research_data"] == ""

    def test_filter_l2_excludes_research_data(self):
        """L2 (altcoin overview) must NOT receive research data."""
        ctx = GenerationContext(
            market_data="BTC: $105,000",
            research_data_text=self._SAMPLE_RESEARCH,
        )
        filtered = _filter_data_for_tier("L2", ctx, "")
        assert filtered["research_data"] == ""

    def test_filter_l3_includes_research_data(self):
        """L3 (deep analysis) MUST receive full research data."""
        ctx = GenerationContext(
            market_data="BTC: $105,000",
            news_summary="Some news\n" * 15,
            research_data_text=self._SAMPLE_RESEARCH,
        )
        filtered = _filter_data_for_tier("L3", ctx, "")
        assert filtered["research_data"] == self._SAMPLE_RESEARCH

    def test_filter_l4_includes_research_data(self):
        """L4 (risk analysis) MUST receive full research data."""
        ctx = GenerationContext(
            market_data="BTC: $105,000",
            news_summary="Some news\n" * 10,
            research_data_text=self._SAMPLE_RESEARCH,
        )
        filtered = _filter_data_for_tier("L4", ctx, "")
        assert filtered["research_data"] == self._SAMPLE_RESEARCH

    def test_filter_l5_includes_research_data(self):
        """L5 (master investor) MUST receive full research data."""
        ctx = GenerationContext(
            market_data="BTC: $105,000",
            news_summary="Some news\n" * 25,
            research_data_text=self._SAMPLE_RESEARCH,
        )
        filtered = _filter_data_for_tier("L5", ctx, "")
        assert filtered["research_data"] == self._SAMPLE_RESEARCH

    async def test_prompt_contains_research_data_for_l3(self):
        """L3 prompt sent to LLM must contain research data section header + content."""
        templates = _make_templates("L3")
        ctx = GenerationContext(
            coin_lists={"L3": ["BTC", "ETH"]},
            market_data="BTC: $105,000",
            news_summary="Some news\n" * 15,
            research_data_text=self._SAMPLE_RESEARCH,
        )

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(text=_MOCK_ARTICLE, tokens_used=100, model="test")
        )

        await generate_tier_articles(mock_llm, templates, ctx)

        call_args = mock_llm.generate.call_args
        prompt = call_args.kwargs.get("prompt", call_args[1].get("prompt", ""))
        assert "DU LIEU NGHIEN CUU NANG CAO" in prompt or "NGHIÊN CỨU NÂNG CAO" in prompt
        assert "BGeometrics" in prompt
        assert "MVRV_Z_Score" in prompt

    async def test_prompt_excludes_research_data_for_l1(self):
        """L1 prompt must NOT contain research data section."""
        templates = _make_templates("L1")
        ctx = GenerationContext(
            coin_lists={"L1": ["BTC", "ETH"]},
            market_data="BTC: $105,000",
            news_summary="Some news",
            research_data_text=self._SAMPLE_RESEARCH,
        )

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(text=_MOCK_ARTICLE, tokens_used=100, model="test")
        )

        await generate_tier_articles(mock_llm, templates, ctx)

        call_args = mock_llm.generate.call_args
        prompt = call_args.kwargs.get("prompt", call_args[1].get("prompt", ""))
        assert "MVRV_Z_Score" not in prompt
        assert "NGHIÊN CỨU NÂNG CAO" not in prompt

    async def test_prompt_no_research_block_when_empty(self):
        """When research_data_text is empty, no research block appears in prompt."""
        templates = _make_templates("L3")
        ctx = GenerationContext(
            coin_lists={"L3": ["BTC", "ETH"]},
            market_data="BTC: $105,000",
            news_summary="Some news\n" * 15,
            research_data_text="",  # empty
        )

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(text=_MOCK_ARTICLE, tokens_used=100, model="test")
        )

        await generate_tier_articles(mock_llm, templates, ctx)

        call_args = mock_llm.generate.call_args
        prompt = call_args.kwargs.get("prompt", call_args[1].get("prompt", ""))
        assert "NGHIÊN CỨU NÂNG CAO" not in prompt

    def test_l3_sources_include_research_providers(self):
        """L3 source attribution must include BGeometrics, btcetffundflow.com, DefiLlama."""
        result = _get_tier_data_sources("L3")
        assert "BGeometrics" in result
        assert "btcetffundflow.com" in result
        assert "DefiLlama" in result

    def test_l5_sources_include_research_providers(self):
        """L5 source attribution must include BGeometrics, btcetffundflow.com, DefiLlama."""
        result = _get_tier_data_sources("L5")
        assert "BGeometrics" in result
        assert "btcetffundflow.com" in result
        assert "DefiLlama" in result

    def test_l1_sources_exclude_research_providers(self):
        """L1 source attribution must NOT include research providers."""
        result = _get_tier_data_sources("L1")
        assert "BGeometrics" not in result
        assert "btcetffundflow.com" not in result
        assert "DefiLlama" not in result

    def test_l2_sources_exclude_research_providers(self):
        """L2 source attribution must NOT include research providers."""
        result = _get_tier_data_sources("L2")
        assert "BGeometrics" not in result
        assert "btcetffundflow.com" not in result
        assert "DefiLlama" not in result


class TestContextAwareFabricationFilter:
    """v2.0 P1.2: Fabrication filter must be context-aware.

    When research_data contains a metric (e.g. MVRV_Z_Score), the LLM mentioning
    that metric should NOT be flagged as fabrication. Only strip metrics that
    were truly NOT provided in input data.
    """

    _RESEARCH_DATA = (
        "=== ON-CHAIN NANG CAO (nguon: BGeometrics) ===\n"
        "  MVRV_Z_Score: 2.1500 (BGeometrics, 2026-03-27)\n"
        "  NUPL: 0.5800 (BGeometrics, 2026-03-27)\n"
        "  SOPR: 1.0200 (BGeometrics, 2026-03-27)\n"
        "  Puell_Multiple: 1.3000 (BGeometrics, 2026-03-27)\n"
    )

    def test_mvrv_preserved_when_in_research_data(self):
        """MVRV in output + MVRV_Z_Score in research_data => NOT stripped."""
        content = (
            "BTC tiep tuc tang.\n"
            "MVRV Z-Score hien tai la 2.15, cho thay thi truong chua qua nong.\n"
            "Nha dau tu nen tiep tuc theo doi."
        )
        cleaned, warnings = _validate_and_clean_output(
            content, "L3", onchain_data="", research_data=self._RESEARCH_DATA
        )
        assert "MVRV" in cleaned, "MVRV should be preserved when research_data contains it"
        assert not any("MVRV" in w for w in warnings), (
            f"MVRV should NOT trigger warning when in research_data, got: {warnings}"
        )

    def test_mvrv_stripped_when_no_research_data(self):
        """MVRV in output + empty research_data => SHOULD strip (fabricated)."""
        content = (
            "BTC tiep tuc tang.\n"
            "MVRV Z-Score hien tai la 2.15, cho thay thi truong chua qua nong.\n"
            "Nha dau tu nen tiep tuc theo doi."
        )
        cleaned, warnings = _validate_and_clean_output(
            content, "L3", onchain_data="", research_data=""
        )
        assert "MVRV" not in cleaned, "MVRV should be stripped when not in any input data"
        assert any("MVRV" in w for w in warnings)

    def test_nupl_preserved_when_in_research_data(self):
        """NUPL in output + NUPL in research_data => NOT stripped."""
        content = (
            "Chi so NUPL dang o muc 0.58, phan anh tam ly lac quan.\n"
            "Dieu nay dong nhat voi xu huong tich luy dai han."
        )
        cleaned, warnings = _validate_and_clean_output(
            content, "L3", onchain_data="", research_data=self._RESEARCH_DATA
        )
        assert "NUPL" in cleaned, "NUPL should be preserved when research_data contains it"
        assert not any("NUPL" in w for w in warnings)

    def test_sopr_preserved_when_in_research_data(self):
        """SOPR in output + SOPR in research_data => NOT stripped."""
        content = (
            "SOPR = 1.02, cho thay loi nhuan cua nguoi ban dang duong.\n"
            "Day la tin hieu tich cuc cho nha dau tu dai han."
        )
        cleaned, warnings = _validate_and_clean_output(
            content, "L3", onchain_data="", research_data=self._RESEARCH_DATA
        )
        assert "SOPR" in cleaned
        assert not any("SOPR" in w for w in warnings)

    def test_puell_preserved_when_in_research_data(self):
        """Puell Multiple in output + Puell_Multiple in research_data => NOT stripped."""
        content = (
            "Puell Multiple hien tai la 1.30, cho thay doanh thu mining on dinh.\n"
            "Khong co ap luc ban tu phia tho dao."
        )
        cleaned, warnings = _validate_and_clean_output(
            content, "L3", onchain_data="", research_data=self._RESEARCH_DATA
        )
        assert "Puell Multiple" in cleaned
        assert not any("Puell" in w for w in warnings)

    def test_bloomberg_still_stripped_even_with_research_data(self):
        """Bloomberg is a banned SOURCE, not a metric — always stripped regardless."""
        content = "Theo Bloomberg, dong tien ETF vao BTC dat $500M.\nDay la tin hieu tich cuc."
        cleaned, warnings = _validate_and_clean_output(
            content, "L3", onchain_data="", research_data=self._RESEARCH_DATA
        )
        assert "Bloomberg" not in cleaned, "Bloomberg must always be stripped (banned source)"
        assert any("Bloomberg" in w for w in warnings)

    def test_exchange_reserves_stripped_when_not_in_data(self):
        """Exchange Reserves not in research_data => still stripped."""
        content = "Exchange Reserve giam manh, cho thay nha dau tu rut coin.\nBTC tiep tuc on dinh."
        cleaned, warnings = _validate_and_clean_output(
            content, "L3", onchain_data="", research_data=self._RESEARCH_DATA
        )
        assert "Exchange Reserve" not in cleaned
        assert any("Exchange Reserves" in w for w in warnings)

    def test_multiple_metrics_mixed_preserved_and_stripped(self):
        """When some metrics are in research_data and some are not, handle both correctly."""
        content = (
            "MVRV Z-Score la 2.15 — thi truong chua qua nong.\n"
            "NUPL = 0.58, tam ly lac quan.\n"
            "Exchange Reserve giam manh, rut coin khoi san.\n"
            "BTC on dinh quanh $105K."
        )
        cleaned, warnings = _validate_and_clean_output(
            content, "L3", onchain_data="", research_data=self._RESEARCH_DATA
        )
        # MVRV, NUPL in research_data => preserved
        assert "MVRV" in cleaned
        assert "NUPL" in cleaned
        # Exchange Reserve NOT in research_data => stripped
        assert "Exchange Reserve" not in cleaned
        # BTC line always preserved
        assert "BTC on dinh" in cleaned

    def test_onchain_data_still_works_without_research(self):
        """Backward compat: metrics in onchain_data are preserved (regression test)."""
        content = "BTC tiep tuc tang.\nMVRV hien tai cho thay gia tri hop ly.\nKet luan: on dinh."
        # MVRV present in onchain_data (old behavior) => NOT stripped
        cleaned, warnings = _validate_and_clean_output(
            content, "L3", onchain_data="MVRV: 2.1", research_data=""
        )
        assert "MVRV" in cleaned
        assert not any("MVRV" in w for w in warnings)

    async def test_prompt_fabrication_examples_context_aware_with_research(self):
        """When research_data is present, prompt should NOT list MVRV/SOPR as banned examples."""
        templates = _make_templates("L3")
        ctx = GenerationContext(
            coin_lists={"L3": ["BTC", "ETH"]},
            market_data="BTC: $105,000",
            news_summary="Some news\n" * 15,
            research_data_text=self._RESEARCH_DATA,
        )

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(text=_MOCK_ARTICLE, tokens_used=100, model="test")
        )

        await generate_tier_articles(mock_llm, templates, ctx)

        call_args = mock_llm.generate.call_args
        prompt = call_args.kwargs.get("prompt", call_args[1].get("prompt", ""))
        # When research data IS provided, MVRV/SOPR should NOT be in banned examples
        # (they're legitimate data now, not fabrication)
        # The prompt should list Bloomberg/TradingView instead
        assert "Bloomberg" in prompt
        assert "TradingView" in prompt

    async def test_prompt_fabrication_examples_include_mvrv_without_research(self):
        """When research_data is empty, prompt should list MVRV/SOPR as banned examples."""
        templates = _make_templates("L3")
        ctx = GenerationContext(
            coin_lists={"L3": ["BTC", "ETH"]},
            market_data="BTC: $105,000",
            news_summary="Some news\n" * 15,
            research_data_text="",  # no research data
        )

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(text=_MOCK_ARTICLE, tokens_used=100, model="test")
        )

        await generate_tier_articles(mock_llm, templates, ctx)

        call_args = mock_llm.generate.call_args
        prompt = call_args.kwargs.get("prompt", call_args[1].get("prompt", ""))
        # When research data is NOT provided, MVRV/SOPR should be in banned examples
        assert "MVRV" in prompt
        assert "SOPR" in prompt


class TestConsensusDataInTierArticles:
    """v2.0 P1.6: consensus_text flows into GenerationContext and tier articles."""

    _SAMPLE_CONSENSUS = (
        "=== EXPERT CONSENSUS ===\n"
        "BTC: BULLISH (+0.45) — 5 sources, 60% bullish\n"
        "  Polymarket: BULLISH (conf: 80%, weight: 3.0) — Avg YES 72%\n"
        "  Fear&Greed: BEARISH (conf: 60%, weight: 1.0) — F&G Index = 25\n"
    )

    def test_generation_context_accepts_consensus_text(self):
        """GenerationContext dataclass can be instantiated with consensus_text."""
        ctx = GenerationContext(consensus_text=self._SAMPLE_CONSENSUS)
        assert ctx.consensus_text == self._SAMPLE_CONSENSUS

    def test_generation_context_defaults_empty_consensus(self):
        """consensus_text defaults to empty string when not provided."""
        ctx = GenerationContext()
        assert ctx.consensus_text == ""

    def test_filter_l1_excludes_consensus(self):
        """L1 (beginners) must NOT receive consensus data."""
        ctx = GenerationContext(
            market_data="BTC: $105,000",
            consensus_text=self._SAMPLE_CONSENSUS,
        )
        filtered = _filter_data_for_tier("L1", ctx, "")
        assert filtered["consensus_data"] == ""

    def test_filter_l2_excludes_consensus(self):
        """L2 (altcoin overview) must NOT receive consensus data."""
        ctx = GenerationContext(
            market_data="BTC: $105,000",
            consensus_text=self._SAMPLE_CONSENSUS,
        )
        filtered = _filter_data_for_tier("L2", ctx, "")
        assert filtered["consensus_data"] == ""

    def test_filter_l3_includes_consensus(self):
        """L3 (deep analysis) MUST receive full consensus data."""
        ctx = GenerationContext(
            market_data="BTC: $105,000",
            news_summary="Some news\n" * 15,
            consensus_text=self._SAMPLE_CONSENSUS,
        )
        filtered = _filter_data_for_tier("L3", ctx, "")
        assert filtered["consensus_data"] == self._SAMPLE_CONSENSUS

    def test_filter_l5_includes_consensus(self):
        """L5 (master investor) MUST receive full consensus data."""
        ctx = GenerationContext(
            market_data="BTC: $105,000",
            news_summary="Some news\n" * 25,
            consensus_text=self._SAMPLE_CONSENSUS,
        )
        filtered = _filter_data_for_tier("L5", ctx, "")
        assert filtered["consensus_data"] == self._SAMPLE_CONSENSUS

    async def test_prompt_contains_consensus_for_l3(self):
        """L3 prompt sent to LLM must contain consensus data."""
        templates = _make_templates("L3")
        ctx = GenerationContext(
            coin_lists={"L3": ["BTC", "ETH"]},
            market_data="BTC: $105,000",
            news_summary="Some news\n" * 15,
            consensus_text=self._SAMPLE_CONSENSUS,
        )

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(text=_MOCK_ARTICLE, tokens_used=100, model="test")
        )

        await generate_tier_articles(mock_llm, templates, ctx)

        call_args = mock_llm.generate.call_args
        prompt = call_args.kwargs.get("prompt", call_args[1].get("prompt", ""))
        assert "EXPERT CONSENSUS" in prompt
        assert "Polymarket" in prompt

    async def test_prompt_excludes_consensus_for_l1(self):
        """L1 prompt must NOT contain consensus data."""
        templates = _make_templates("L1")
        ctx = GenerationContext(
            coin_lists={"L1": ["BTC", "ETH"]},
            market_data="BTC: $105,000",
            news_summary="Some news",
            consensus_text=self._SAMPLE_CONSENSUS,
        )

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(text=_MOCK_ARTICLE, tokens_used=100, model="test")
        )

        await generate_tier_articles(mock_llm, templates, ctx)

        call_args = mock_llm.generate.call_args
        prompt = call_args.kwargs.get("prompt", call_args[1].get("prompt", ""))
        assert "EXPERT CONSENSUS" not in prompt

    async def test_prompt_no_consensus_block_when_empty(self):
        """When consensus_text is empty, no consensus block appears in prompt."""
        templates = _make_templates("L3")
        ctx = GenerationContext(
            coin_lists={"L3": ["BTC", "ETH"]},
            market_data="BTC: $105,000",
            news_summary="Some news\n" * 15,
            consensus_text="",  # empty
        )

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(text=_MOCK_ARTICLE, tokens_used=100, model="test")
        )

        await generate_tier_articles(mock_llm, templates, ctx)

        call_args = mock_llm.generate.call_args
        prompt = call_args.kwargs.get("prompt", call_args[1].get("prompt", ""))
        assert "EXPERT CONSENSUS" not in prompt
