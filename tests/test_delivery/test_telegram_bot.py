"""Tests for delivery/telegram_bot.py — all mocked."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cic_daily_report.core.error_handler import DeliveryError
from cic_daily_report.delivery.telegram_bot import (
    TelegramBot,
    TelegramMessage,
    prepare_messages,
    split_message,
)


class TestTelegramMessage:
    def test_formatted_single_part(self):
        msg = TelegramMessage(tier_label="L1", content="Hello")
        assert msg.formatted == "[L1]\n\nHello"

    def test_formatted_multi_part(self):
        msg = TelegramMessage(tier_label="L3", content="Part 2", part=2, total_parts=3)
        assert "[L3 - Phần 2/3]" in msg.formatted
        assert "Part 2" in msg.formatted


class TestSplitMessage:
    def test_short_message_no_split(self):
        msgs = split_message("L1", "Short content")
        assert len(msgs) == 1
        assert msgs[0].total_parts == 1

    def test_long_message_splits(self):
        long_content = "A" * 5000
        msgs = split_message("L2", long_content)
        assert len(msgs) >= 2
        assert msgs[0].part == 1
        assert msgs[1].part == 2

    def test_split_by_sections(self):
        # Each section must exceed max to force split
        content = "Intro text\n\n## Section 1\n" + "x" * 3000 + "\n\n## Section 2\n" + "y" * 3000
        msgs = split_message("L1", content)
        assert len(msgs) >= 2


class TestPrepareMessages:
    def test_prepares_from_articles(self):
        articles = [
            {"tier": "L1", "content": "Article 1"},
            {"tier": "Summary", "content": "Summary text"},
        ]
        msgs = prepare_messages(articles)
        assert len(msgs) == 2
        assert msgs[0].tier_label == "L1"
        assert msgs[1].tier_label == "Summary"

    def test_empty_articles(self):
        assert prepare_messages([]) == []


class TestTelegramBot:
    def test_missing_config_raises(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(DeliveryError, match="config missing"):
                TelegramBot(bot_token="", chat_id="")

    async def test_send_message_success(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True, "result": {"message_id": 1}}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        bot = TelegramBot(bot_token="test-token", chat_id="12345")

        with patch(
            "cic_daily_report.delivery.telegram_bot.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await bot.send_message("Hello")

        assert result["ok"] is True

    async def test_deliver_all_multiple_messages(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        bot = TelegramBot(bot_token="test", chat_id="123")
        messages = [
            TelegramMessage(tier_label="L1", content="Art 1"),
            TelegramMessage(tier_label="L2", content="Art 2"),
        ]

        with (
            patch(
                "cic_daily_report.delivery.telegram_bot.httpx.AsyncClient",
                return_value=mock_client,
            ),
            patch("cic_daily_report.delivery.telegram_bot.asyncio.sleep", new_callable=AsyncMock),
        ):
            results = await bot.deliver_all(messages)

        assert len(results) == 2
        assert all(r.get("ok") for r in results)

    async def test_deliver_all_handles_failure(self):
        mock_resp_ok = MagicMock()
        mock_resp_ok.json.return_value = {"ok": True}
        mock_resp_ok.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[mock_resp_ok, Exception("network error")])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        bot = TelegramBot(bot_token="test", chat_id="123")
        messages = [
            TelegramMessage(tier_label="L1", content="ok"),
            TelegramMessage(tier_label="L2", content="fail"),
        ]

        with (
            patch(
                "cic_daily_report.delivery.telegram_bot.httpx.AsyncClient",
                return_value=mock_client,
            ),
            patch("cic_daily_report.delivery.telegram_bot.asyncio.sleep", new_callable=AsyncMock),
        ):
            results = await bot.deliver_all(messages)

        assert results[0].get("ok") is True
        assert results[1].get("ok") is False
