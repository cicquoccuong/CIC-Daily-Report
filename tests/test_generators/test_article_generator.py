"""Tests for generators/article_generator.py — all mocked."""

from unittest.mock import AsyncMock, patch

from cic_daily_report.adapters.llm_adapter import LLMResponse
from cic_daily_report.generators.article_generator import (
    DISCLAIMER,
    GenerationContext,
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
        assert "Ý NGHĨA" in prompt  # v0.22.0: shortened from "GIẢI THÍCH Ý NGHĨA"
        assert "NHÂN QUẢ" in prompt
        assert "**Tóm lược:**" in prompt

    async def test_nq05_system_prompt_used(self):
        templates = _make_templates("L1")
        context = _make_context()

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(text="ok", tokens_used=10, model="m")
        )

        await generate_tier_articles(mock_llm, templates, context)

        call_args = mock_llm.generate.call_args
        sys_prompt = call_args.kwargs.get("system_prompt", "")
        assert "NQ05" in sys_prompt
        assert "KHÔNG khuyến nghị" in sys_prompt  # v0.22.0: rewritten system prompt


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
