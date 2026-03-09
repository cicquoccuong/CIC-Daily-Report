"""Tests for delivery/delivery_manager.py — all mocked."""

from unittest.mock import AsyncMock, MagicMock

from cic_daily_report.core.error_handler import LLMError
from cic_daily_report.delivery.delivery_manager import DeliveryManager, DeliveryResult
from cic_daily_report.delivery.email_backup import EmailBackup
from cic_daily_report.delivery.telegram_bot import TelegramBot


def _articles() -> list[dict[str, str]]:
    return [
        {"tier": "L1", "content": "Article 1"},
        {"tier": "L2", "content": "Article 2"},
        {"tier": "Summary", "content": "Summary text"},
    ]


class TestDeliveryResult:
    def test_success(self):
        r = DeliveryResult(messages_sent=3, messages_total=3)
        assert r.success
        assert not r.partial

    def test_partial(self):
        r = DeliveryResult(messages_sent=2, messages_total=3)
        assert r.success
        assert r.partial

    def test_failure(self):
        r = DeliveryResult(messages_sent=0, messages_total=3)
        assert not r.success

    def test_status_line(self):
        r = DeliveryResult(tier_status={"L1": "sent", "L2": "failed", "Summary": "sent"})
        line = r.status_line()
        assert "L1 ✅" in line
        assert "L2 ❌" in line
        assert "Summary ✅" in line


class TestDeliveryManager:
    async def test_telegram_success(self):
        mock_tg = AsyncMock(spec=TelegramBot)
        mock_tg.deliver_all = AsyncMock(return_value=[{"ok": True}, {"ok": True}, {"ok": True}])
        mock_tg.send_message = AsyncMock()

        mgr = DeliveryManager(telegram_bot=mock_tg)
        result = await mgr.deliver(_articles())

        assert result.method == "telegram"
        assert result.messages_sent == 3

    async def test_telegram_partial(self):
        mock_tg = AsyncMock(spec=TelegramBot)
        mock_tg.deliver_all = AsyncMock(
            return_value=[{"ok": True}, {"ok": False, "error": "rate limit"}, {"ok": True}]
        )
        mock_tg.send_message = AsyncMock()

        mgr = DeliveryManager(telegram_bot=mock_tg)
        result = await mgr.deliver(_articles())

        assert result.method == "partial"
        assert result.messages_sent == 2
        assert result.partial

    async def test_telegram_fail_email_fallback(self):
        mock_tg = AsyncMock(spec=TelegramBot)
        mock_tg.deliver_all = AsyncMock(side_effect=Exception("TG down"))
        mock_tg.send_message = AsyncMock()

        mock_email = MagicMock(spec=EmailBackup)
        mock_email.available = True

        mgr = DeliveryManager(telegram_bot=mock_tg, email_backup=mock_email)
        result = await mgr.deliver(_articles())

        assert result.method == "email_backup"
        mock_email.send_daily_report.assert_called_once()

    async def test_no_content_no_errors(self):
        mgr = DeliveryManager()
        result = await mgr.deliver([])
        assert not result.success
        assert result.messages_total == 0

    async def test_sends_error_notification(self):
        mock_tg = AsyncMock(spec=TelegramBot)
        mock_tg.deliver_all = AsyncMock(return_value=[{"ok": True}])
        mock_tg.send_message = AsyncMock()

        mgr = DeliveryManager(telegram_bot=mock_tg)
        errors = [LLMError("Groq timeout")]
        await mgr.deliver(
            [{"tier": "L1", "content": "ok"}],
            pipeline_errors=errors,
        )

        # Error notification sent via send_message
        mock_tg.send_message.assert_called()

    async def test_email_not_called_when_tg_succeeds(self):
        mock_tg = AsyncMock(spec=TelegramBot)
        mock_tg.deliver_all = AsyncMock(return_value=[{"ok": True}])
        mock_tg.send_message = AsyncMock()

        mock_email = MagicMock(spec=EmailBackup)
        mock_email.available = True

        mgr = DeliveryManager(telegram_bot=mock_tg, email_backup=mock_email)
        await mgr.deliver([{"tier": "L1", "content": "ok"}])

        mock_email.send_daily_report.assert_not_called()
