"""Email backup delivery — sends via SMTP when Telegram fails (FR33b).

Plain text email, Gmail App Password compatible.
Non-blocking health check on startup.
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

from cic_daily_report.core.error_handler import DeliveryError
from cic_daily_report.core.logger import get_logger

logger = get_logger("email_backup")


def _parse_recipients(raw: str) -> list[str]:
    """Parse comma-separated recipients string into list."""
    if not raw or not raw.strip():
        return []
    return [addr.strip() for addr in raw.split(",") if addr.strip()]


class EmailBackup:
    """SMTP-based email backup delivery."""

    def __init__(
        self,
        smtp_server: str | None = None,
        smtp_port: int = 587,
        smtp_email: str | None = None,
        smtp_password: str | None = None,
        recipients: list[str] | None = None,
    ) -> None:
        self._server = smtp_server or os.getenv("SMTP_HOST", "smtp.gmail.com")
        self._port = smtp_port
        self._email = smtp_email or os.getenv("SMTP_USER", "")
        self._password = smtp_password or os.getenv("SMTP_PASSWORD", "")
        self._recipients = recipients or _parse_recipients(os.getenv("SMTP_RECIPIENTS", ""))
        self._available = bool(self._email and self._password)

    @property
    def available(self) -> bool:
        """True if SMTP credentials are configured."""
        return self._available

    def health_check(self) -> bool:
        """Test SMTP connection (non-blocking, connect + auth only).

        Returns True if connection succeeds.
        """
        if not self._available:
            logger.warning("Email backup disabled — missing SMTP config")
            return False

        try:
            with smtplib.SMTP(self._server, self._port, timeout=10) as server:
                server.starttls()
                server.login(self._email, self._password)
            logger.info("SMTP health check passed")
            return True
        except Exception as e:
            logger.warning(f"SMTP connection failed — email backup may not work: {e}")
            return False

    def send(
        self,
        subject: str,
        body: str,
        recipients: list[str] | None = None,
    ) -> None:
        """Send plain text email.

        Args:
            subject: Email subject (e.g. "[CIC Daily] 2026-03-09 - Daily Report")
            body: Plain text content.
            recipients: Override recipient list; falls back to constructor list.
        """
        if not self._available:
            logger.warning("Email backup skipped — SMTP not configured")
            return

        to_addrs = recipients or self._recipients
        if not to_addrs:
            logger.warning("Email backup skipped — no recipients configured")
            return

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self._email
        msg["To"] = ", ".join(to_addrs)
        msg.set_content(body)

        try:
            with smtplib.SMTP(self._server, self._port, timeout=30) as server:
                server.starttls()
                server.login(self._email, self._password)
                server.send_message(msg)
            logger.info(f"Email sent to {len(to_addrs)} recipients: {subject}")
        except Exception as e:
            logger.error(f"Email send failed: {e}")
            raise DeliveryError(
                f"Email backup failed: {e}",
                source="email_backup",
            ) from e

    def send_daily_report(self, date_str: str, content: str, recipients: list[str] | None = None):
        """Send daily report email with standard subject."""
        self.send(
            subject=f"[CIC Daily] {date_str} - Daily Report",
            body=content,
            recipients=recipients,
        )

    def send_breaking_news(
        self,
        date_str: str,
        severity_emoji: str,
        headline: str,
        content: str,
        recipients: list[str] | None = None,
    ):
        """Send breaking news email with standard subject."""
        self.send(
            subject=f"[CIC Breaking] {date_str} - {severity_emoji} {headline}",
            body=content,
            recipients=recipients,
        )
