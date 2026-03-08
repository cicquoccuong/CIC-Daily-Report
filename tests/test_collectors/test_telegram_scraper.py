"""Tests for collectors/telegram_scraper.py — all mocked."""

from unittest.mock import patch

from cic_daily_report.collectors.telegram_scraper import (
    TelegramMessage,
    collect_telegram,
)


class TestTelegramMessage:
    def test_to_row(self):
        msg = TelegramMessage(
            channel_name="crypto_vn",
            message_text="BTC hit 100k today",
            date="2026-03-09",
            message_id=123,
        )
        row = msg.to_row()
        assert len(row) == 11
        assert "telegram:crypto_vn" in row[3]
        assert row[5] == "vi"


class TestCollectTelegram:
    async def test_skips_when_missing_credentials(self):
        with patch.dict("os.environ", {}, clear=True):
            result = await collect_telegram()
        assert result == []

    async def test_skips_when_partial_credentials(self):
        with patch.dict(
            "os.environ",
            {"TELEGRAM_API_ID": "123"},
            clear=True,
        ):
            result = await collect_telegram()
        assert result == []

    async def test_placeholder_returns_empty(self):
        """MVP placeholder mode — returns empty."""
        env = {
            "TELEGRAM_API_ID": "123",
            "TELEGRAM_API_HASH": "abc",
            "TELEGRAM_SESSION_STRING": "session",
        }
        with patch.dict("os.environ", env, clear=True):
            result = await collect_telegram()
        assert result == []
