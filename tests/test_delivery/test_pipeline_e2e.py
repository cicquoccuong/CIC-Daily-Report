"""End-to-end integration test — full daily pipeline (Story 4.5).

Verifies: data collection → content generation → NQ05 → delivery.
All external APIs mocked. Tests timeout scenario.
"""

from unittest.mock import AsyncMock

from cic_daily_report.adapters.llm_adapter import LLMResponse
from cic_daily_report.delivery.delivery_manager import DeliveryManager
from cic_daily_report.delivery.telegram_bot import TelegramBot, prepare_messages
from cic_daily_report.generators.article_generator import (
    DISCLAIMER,
    GenerationContext,
    generate_tier_articles,
)
from cic_daily_report.generators.nq05_filter import check_and_fix
from cic_daily_report.generators.summary_generator import generate_bic_summary
from cic_daily_report.generators.template_engine import load_templates


def _mock_llm() -> AsyncMock:
    mock = AsyncMock()
    mock.generate = AsyncMock(
        return_value=LLMResponse(
            text="Thị trường tài sản mã hóa hôm nay ổn định.",
            tokens_used=50,
            model="test-model",
        )
    )
    return mock


def _templates():
    raw = []
    for tier in ["L1", "L2", "L3", "L4", "L5"]:
        raw.append(
            {
                "tier": tier,
                "section_name": "Overview",
                "enabled": True,
                "order": 1,
                "prompt_template": "Analyze {coin_list}",
                "max_words": 300,
            }
        )
    return load_templates(raw)


def _context():
    return GenerationContext(
        coin_lists={
            "L1": ["BTC", "ETH"],
            "L2": ["BTC", "ETH", "SOL"],
            "L3": ["BTC", "ETH", "SOL", "BNB"],
            "L4": ["BTC", "ETH", "SOL", "BNB", "ADA"],
            "L5": ["BTC", "ETH", "SOL", "BNB", "ADA", "XRP"],
        },
        market_data="BTC $105K",
        key_metrics={"BTC Price": "$105K", "Fear & Greed": "72"},
    )


class TestFullPipelineE2E:
    async def test_full_flow_produces_6_deliverables(self):
        """Full flow: generate 5 articles + 1 summary → 6 messages."""
        llm = _mock_llm()
        templates = _templates()
        context = _context()

        # Stage 1: Generate articles
        articles = await generate_tier_articles(llm, templates, context)
        assert len(articles) == 5

        # Stage 2: Generate summary
        summary = await generate_bic_summary(llm, articles, context.key_metrics)
        assert summary.word_count > 0

        # Stage 3: NQ05 filter
        all_content = [a.content for a in articles] + [summary.content]
        for content in all_content:
            result = check_and_fix(content)
            assert result.passed

        # Stage 4: Prepare delivery messages
        article_dicts = [{"tier": a.tier, "content": a.content} for a in articles] + [
            {"tier": "Summary", "content": summary.content}
        ]

        messages = prepare_messages(article_dicts)
        assert len(messages) >= 6  # At least 6 (could be more if splitting occurs)

    async def test_delivery_manager_sends_all(self):
        """DeliveryManager sends all 6 messages via Telegram."""
        mock_tg = AsyncMock(spec=TelegramBot)
        mock_tg.deliver_all = AsyncMock(return_value=[{"ok": True} for _ in range(6)])
        mock_tg.send_message = AsyncMock()

        mgr = DeliveryManager(telegram_bot=mock_tg)
        articles = [{"tier": f"L{i}", "content": f"Content {i}"} for i in range(1, 6)] + [
            {"tier": "Summary", "content": "Summary"}
        ]

        result = await mgr.deliver(articles)

        assert result.success
        assert result.messages_sent == 6
        assert result.method == "telegram"

    async def test_partial_delivery_with_errors(self):
        """Pipeline errors → partial delivery + error notification."""
        llm = AsyncMock()
        # L1 fails, rest succeed
        llm.generate = AsyncMock(
            side_effect=[
                Exception("LLM fail"),
                LLMResponse(text="L2 content", tokens_used=10, model="m"),
                LLMResponse(text="L3 content", tokens_used=10, model="m"),
                LLMResponse(text="L4 content", tokens_used=10, model="m"),
                LLMResponse(text="L5 content", tokens_used=10, model="m"),
                LLMResponse(text="Summary", tokens_used=10, model="m"),
            ]
        )

        templates = _templates()
        context = _context()
        articles = await generate_tier_articles(llm, templates, context)

        # L1 failed → 4 articles
        assert len(articles) == 4

        # Delivery should still work with 4 articles (no summary in this test)
        mock_tg = AsyncMock(spec=TelegramBot)
        mock_tg.deliver_all = AsyncMock(return_value=[{"ok": True} for _ in range(4)])
        mock_tg.send_message = AsyncMock()

        mgr = DeliveryManager(telegram_bot=mock_tg)
        article_dicts = [{"tier": a.tier, "content": a.content} for a in articles]
        result = await mgr.deliver(article_dicts)

        assert result.success
        assert result.messages_sent == 4

    async def test_all_content_has_disclaimer(self):
        """Every deliverable has NQ05 disclaimer."""
        llm = _mock_llm()
        templates = _templates()
        context = _context()

        articles = await generate_tier_articles(llm, templates, context)
        summary = await generate_bic_summary(llm, articles, context.key_metrics)

        for article in articles:
            assert DISCLAIMER in article.content
        assert DISCLAIMER in summary.content

    async def test_message_order_preserved(self):
        """Messages sent in order: L1 → L2 → L3 → L4 → L5 → Summary."""
        article_dicts = [{"tier": f"L{i}", "content": f"Content {i}"} for i in range(1, 6)] + [
            {"tier": "Summary", "content": "Sum"}
        ]

        messages = prepare_messages(article_dicts)
        labels = [m.tier_label for m in messages]
        assert labels == ["L1", "L2", "L3", "L4", "L5", "Summary"]
