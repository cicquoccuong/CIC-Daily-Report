"""Tests for delivery/email_backup.py — all mocked."""

from unittest.mock import MagicMock, patch

import pytest

from cic_daily_report.core.error_handler import DeliveryError
from cic_daily_report.delivery.email_backup import EmailBackup


class TestEmailBackup:
    def test_not_available_without_creds(self):
        backup = EmailBackup(smtp_email="", smtp_password="")
        assert not backup.available

    def test_available_with_creds(self):
        backup = EmailBackup(smtp_email="test@gmail.com", smtp_password="pass123")
        assert backup.available

    def test_health_check_disabled(self):
        backup = EmailBackup(smtp_email="", smtp_password="")
        assert not backup.health_check()

    def test_health_check_success(self):
        backup = EmailBackup(smtp_email="test@gmail.com", smtp_password="pass")

        mock_smtp = MagicMock()
        with patch("cic_daily_report.delivery.email_backup.smtplib.SMTP", return_value=mock_smtp):
            mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp.__exit__ = MagicMock(return_value=False)
            result = backup.health_check()

        assert result is True

    def test_health_check_failure(self):
        backup = EmailBackup(smtp_email="test@gmail.com", smtp_password="pass")

        with patch(
            "cic_daily_report.delivery.email_backup.smtplib.SMTP",
            side_effect=Exception("Connection refused"),
        ):
            result = backup.health_check()

        assert result is False

    def test_send_skips_when_disabled(self):
        backup = EmailBackup(smtp_email="", smtp_password="")
        # Should not raise
        backup.send("Subject", "Body", recipients=["a@b.com"])

    def test_send_skips_no_recipients(self):
        backup = EmailBackup(smtp_email="test@gmail.com", smtp_password="pass")
        # Should not raise
        backup.send("Subject", "Body")

    def test_send_success(self):
        backup = EmailBackup(
            smtp_email="test@gmail.com",
            smtp_password="pass",
            recipients=["user@example.com"],
        )

        mock_smtp = MagicMock()
        with patch("cic_daily_report.delivery.email_backup.smtplib.SMTP", return_value=mock_smtp):
            mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp.__exit__ = MagicMock(return_value=False)
            backup.send("Test Subject", "Test Body")

        mock_smtp.send_message.assert_called_once()

    def test_send_failure_raises(self):
        backup = EmailBackup(
            smtp_email="test@gmail.com",
            smtp_password="pass",
            recipients=["user@example.com"],
        )

        with patch(
            "cic_daily_report.delivery.email_backup.smtplib.SMTP",
            side_effect=Exception("SMTP error"),
        ):
            with pytest.raises(DeliveryError, match="Email backup failed"):
                backup.send("Subject", "Body")

    def test_send_daily_report(self):
        backup = EmailBackup(
            smtp_email="test@gmail.com",
            smtp_password="pass",
            recipients=["user@example.com"],
        )

        mock_smtp = MagicMock()
        with patch("cic_daily_report.delivery.email_backup.smtplib.SMTP", return_value=mock_smtp):
            mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp.__exit__ = MagicMock(return_value=False)
            backup.send_daily_report("2026-03-09", "Report content")

        mock_smtp.send_message.assert_called_once()

    def test_send_daily_report_with_telegram_error(self):
        """telegram_error appended to body."""
        backup = EmailBackup(
            smtp_email="test@gmail.com",
            smtp_password="pass",
            recipients=["user@example.com"],
        )

        sent_body: list[str] = []

        mock_smtp = MagicMock()
        with patch("cic_daily_report.delivery.email_backup.smtplib.SMTP", return_value=mock_smtp):
            mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp.__exit__ = MagicMock(return_value=False)

            def capture_send_message(msg):
                sent_body.append(msg.get_content())

            mock_smtp.send_message.side_effect = capture_send_message
            backup.send_daily_report(
                "2026-03-12", "Report content", telegram_error="Connection refused"
            )

        assert mock_smtp.send_message.called
        body = sent_body[0]
        assert "EMAIL NÀY ĐƯỢC GỬI DO TELEGRAM THẤT BẠI" in body
        assert "Connection refused" in body

    def test_send_breaking_news(self):
        backup = EmailBackup(
            smtp_email="test@gmail.com",
            smtp_password="pass",
            recipients=["user@example.com"],
        )

        mock_smtp = MagicMock()
        with patch("cic_daily_report.delivery.email_backup.smtplib.SMTP", return_value=mock_smtp):
            mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp.__exit__ = MagicMock(return_value=False)
            backup.send_breaking_news("2026-03-09", "🔴", "BTC crash", "Details here")

        mock_smtp.send_message.assert_called_once()
