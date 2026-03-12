"""Tests for generators/article_generator.py — all mocked."""

from unittest.mock import AsyncMock

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
        assert "KHÔNG BAO GIỜ" in sys_prompt
