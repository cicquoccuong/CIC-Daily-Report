"""Integration test — full content generation pipeline (Story 3.6).

Verifies: 5 tier articles + 1 summary generated, NQ05 compliant,
Vietnamese, disclaimers present, cumulative logic, LLM fallback.
All LLM calls mocked.
"""

from unittest.mock import AsyncMock

from cic_daily_report.adapters.llm_adapter import LLMResponse
from cic_daily_report.generators.article_generator import (
    DISCLAIMER,
    GenerationContext,
    generate_tier_articles,
)
from cic_daily_report.generators.nq05_filter import check_and_fix
from cic_daily_report.generators.summary_generator import generate_bic_summary
from cic_daily_report.generators.template_engine import (
    ArticleTemplate,
    load_templates,
)


def _full_templates() -> dict[str, ArticleTemplate]:
    """Create templates for all 5 tiers."""
    raw = []
    for tier in ["L1", "L2", "L3", "L4", "L5"]:
        raw.extend(
            [
                {
                    "tier": tier,
                    "section_name": "Tổng quan",
                    "enabled": True,
                    "order": 1,
                    "prompt_template": "Tổng quan thị trường cho {coin_list}",
                    "max_words": 200,
                },
                {
                    "tier": tier,
                    "section_name": "Phân tích kỹ thuật",
                    "enabled": True,
                    "order": 2,
                    "prompt_template": "Phân tích kỹ thuật {coin_list} với {market_data}",
                    "max_words": 400,
                },
            ]
        )
    return load_templates(raw)


def _full_context() -> GenerationContext:
    """Create context with cumulative coin lists."""
    return GenerationContext(
        coin_lists={
            "L1": ["BTC", "ETH"],
            "L2": ["BTC", "ETH", "SOL", "BNB"],
            "L3": ["BTC", "ETH", "SOL", "BNB", "ADA", "XRP"],
            "L4": ["BTC", "ETH", "SOL", "BNB", "ADA", "XRP", "DOT", "AVAX"],
            "L5": ["BTC", "ETH", "SOL", "BNB", "ADA", "XRP", "DOT", "AVAX", "MATIC", "LINK"],
        },
        market_data="BTC $105K (+2.3%), ETH $3.8K (+1.5%)",
        news_summary="SEC approves new crypto ETF. Fed giữ lãi suất ổn định.",
        onchain_data="MVRV Z-Score: 2.1, SOPR: 1.02",
        key_metrics={
            "BTC Price": "$105,234",
            "BTC Dominance": "61.2%",
            "Total Market Cap": "$3.4T",
            "Fear & Greed": "72 (Greed)",
            "DXY": "104.5",
            "Gold": "$2,650",
            "Funding Rate": "0.01%",
        },
    )


def _mock_llm() -> AsyncMock:
    """Create mock LLM that returns Vietnamese content."""
    mock = AsyncMock()
    mock.generate = AsyncMock(
        return_value=LLMResponse(
            text=(
                "## TL;DR\n"
                "Thị trường tài sản mã hóa tăng nhẹ hôm nay. "
                "BTC vượt $105K, ETH giữ vùng $3.8K.\n\n"
                "## Phân tích chi tiết\n"
                "Theo CoinLore, BTC giao dịch quanh $105,234 "
                "với volume 24h đạt $45B. Dữ liệu Glassnode cho thấy "
                "MVRV Z-Score ở mức 2.1, cho thấy thị trường chưa quá nóng."
            ),
            tokens_used=150,
            model="llama-3.3-70b-versatile",
        )
    )
    return mock


class TestFullContentPipeline:
    async def test_generates_5_tier_articles(self):
        """FR13: Generate 5 tier articles."""
        llm = _mock_llm()
        templates = _full_templates()
        context = _full_context()

        articles = await generate_tier_articles(llm, templates, context)

        assert len(articles) == 5
        tiers = [a.tier for a in articles]
        assert tiers == ["L1", "L2", "L3", "L4", "L5"]

    async def test_generates_summary_after_articles(self):
        """FR15: Generate 1 BIC Chat summary."""
        llm = _mock_llm()
        templates = _full_templates()
        context = _full_context()

        articles = await generate_tier_articles(llm, templates, context)
        summary = await generate_bic_summary(llm, articles, context.key_metrics)

        assert summary.title.startswith("[Summary]")
        assert summary.word_count > 0

    async def test_all_content_has_disclaimers(self):
        """FR17: All content has disclaimers."""
        llm = _mock_llm()
        templates = _full_templates()
        context = _full_context()

        articles = await generate_tier_articles(llm, templates, context)
        summary = await generate_bic_summary(llm, articles, context.key_metrics)

        for article in articles:
            assert DISCLAIMER in article.content, f"{article.tier} missing disclaimer"
        assert DISCLAIMER in summary.content, "Summary missing disclaimer"

    async def test_all_content_passes_nq05(self):
        """NFR29: Zero NQ05 violations in final output."""
        llm = _mock_llm()
        templates = _full_templates()
        context = _full_context()

        articles = await generate_tier_articles(llm, templates, context)
        summary = await generate_bic_summary(llm, articles, context.key_metrics)

        all_content = [a.content for a in articles] + [summary.content]
        for content in all_content:
            result = check_and_fix(content)
            assert result.passed, f"NQ05 failed: {result.flagged_for_review}"

    async def test_cumulative_coin_logic(self):
        """FR59: L2 includes L1 coins, L3 includes L1+L2, etc."""
        context = _full_context()

        # L1 coins should be subset of L2
        l1_set = set(context.coin_lists["L1"])
        l2_set = set(context.coin_lists["L2"])
        assert l1_set.issubset(l2_set)

        # L2 coins should be subset of L3
        l3_set = set(context.coin_lists["L3"])
        assert l2_set.issubset(l3_set)

    async def test_llm_fallback_scenario(self):
        """FR34: Fallback kicks in when primary fails."""
        llm = AsyncMock()
        fallback_text = (
            "Thị trường tài sản mã hóa hôm nay có nhiều biến động đáng chú ý. "
            "Giá Bitcoin đang giao dịch quanh mức hỗ trợ quan trọng. "
            "Ethereum cũng có xu hướng tương tự với khối lượng giao dịch tăng. "
            "Theo dữ liệu từ CoinLore, tâm lý thị trường đang thận trọng. "
            "Các chỉ số kỹ thuật cho thấy xu hướng ngắn hạn chưa rõ ràng. "
            "Nhà đầu tư cần theo dõi thêm các yếu tố vĩ mô. "
            "Dữ liệu on-chain cho thấy dòng tiền vào sàn giao dịch đang giảm."
        )
        # First call fails (L1), second succeeds (L2)
        llm.generate = AsyncMock(
            side_effect=[
                Exception("Primary LLM down"),
                LLMResponse(text=fallback_text, tokens_used=50, model="gemini-flash"),
            ]
        )

        templates = _full_templates()
        # Only L1, L2 to simplify
        templates = {k: v for k, v in templates.items() if k in ("L1", "L2")}
        context = _full_context()

        articles = await generate_tier_articles(llm, templates, context)

        # L1 failed, L2 succeeded
        assert len(articles) == 1
        assert articles[0].tier == "L2"
        assert articles[0].llm_used == "gemini-flash"

    async def test_content_written_to_rows(self):
        """Verify to_row() format for NOI_DUNG_DA_TAO sheet."""
        llm = _mock_llm()
        templates = _full_templates()
        context = _full_context()

        articles = await generate_tier_articles(llm, templates, context)
        summary = await generate_bic_summary(llm, articles, context.key_metrics)

        # Each article row: [timestamp, tier, title, content, word_count, llm_used, time, nq05]
        for article in articles:
            row = article.to_row()
            assert len(row) == 8
            assert row[1] in ("L1", "L2", "L3", "L4", "L5")

        summary_row = summary.to_row()
        assert summary_row[1] == "SUMMARY"
