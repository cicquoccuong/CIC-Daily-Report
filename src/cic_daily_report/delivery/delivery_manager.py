"""Delivery Manager — orchestrates TG → retry → email backup (Story 4.5).

Single entry point for all delivery logic. Handles partial delivery,
error notifications, and fallback to email.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

from cic_daily_report.core.logger import get_logger
from cic_daily_report.delivery.email_backup import EmailBackup
from cic_daily_report.delivery.error_notifier import build_notification
from cic_daily_report.delivery.telegram_bot import (
    TelegramBot,
    prepare_messages,
)

logger = get_logger("delivery_manager")


@dataclass
class DeliveryResult:
    """Result of the delivery process."""

    method: str = "none"  # "telegram", "email_backup", "partial"
    messages_sent: int = 0
    messages_total: int = 0
    errors: list[str] = field(default_factory=list)
    tier_status: dict[str, str] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.messages_sent > 0

    @property
    def partial(self) -> bool:
        return 0 < self.messages_sent < self.messages_total

    def status_line(self) -> str:
        """FR32: Human-readable status line showing per-tier status."""
        if not self.tier_status:
            return "Không có nội dung để gửi"
        parts = []
        for tier, status in self.tier_status.items():
            emoji = "✅" if status == "sent" else "❌"
            parts.append(f"{tier} {emoji}")
        return " ".join(parts)


class DeliveryManager:
    """Orchestrates delivery: Telegram → retry → email backup."""

    def __init__(
        self,
        telegram_bot: TelegramBot | None = None,
        email_backup: EmailBackup | None = None,
    ) -> None:
        self._tg = telegram_bot
        self._email = email_backup

    async def deliver(
        self,
        articles: list[dict[str, str]],
        pipeline_errors: list[Exception] | None = None,
    ) -> DeliveryResult:
        """Deliver content via Telegram, fallback to email.

        Args:
            articles: list of dicts with keys:
                - tier (str): "L1"/"L2"/..."L5"/"Summary"
                - content (str): Article text
                - source_urls (list[dict], optional): [{"title":..., "url":...}]
                - image_urls (list[str], optional): URLs of research images
            pipeline_errors: any errors from earlier pipeline stages.

        Returns:
            DeliveryResult with delivery method and status.
        """
        result = DeliveryResult()

        # Prepare messages
        messages = prepare_messages(articles)
        result.messages_total = len(messages)

        if not messages and not pipeline_errors:
            logger.warning("No content and no errors to deliver")
            return result

        # Track tier status
        for article in articles:
            result.tier_status[article.get("tier", "?")] = "pending"

        # Try Telegram delivery
        tg_success = False
        tg_error_msg: str | None = None
        if self._tg and messages:
            try:
                tg_results = await self._tg.deliver_all(messages)
                sent_count = sum(1 for r in tg_results if r.get("ok"))
                result.messages_sent = sent_count
                result.method = "telegram"
                tg_success = sent_count > 0

                # Update tier status
                for msg, tg_result in zip(messages, tg_results):
                    status = "sent" if tg_result.get("ok") else "failed"
                    result.tier_status[msg.tier_label] = status

                # Send partial delivery status if not all sent
                if result.partial:
                    result.method = "partial"
                    tg_error_msg = (
                        f"Gửi được {result.messages_sent}/{result.messages_total} tin — "
                        f"{result.status_line()}"
                    )
                    status_msg = f"⚠️ Partial delivery: {result.status_line()}"
                    try:
                        await self._tg.send_message(status_msg)
                    except Exception:
                        pass  # Best effort

                logger.info(f"Telegram delivery: {sent_count}/{len(messages)} messages sent")

            except Exception as e:
                logger.error(f"Telegram delivery failed completely: {e}")
                tg_error_msg = str(e)
                result.errors.append(str(e))

        # Send research images (max 3 per run)
        if tg_success and self._tg:
            await self._send_images(articles)

        # Send error notifications via Telegram
        if pipeline_errors and self._tg:
            try:
                notification = build_notification(pipeline_errors)
                await self._tg.send_message(notification.format_message())
            except Exception as e:
                logger.error(f"Error notification failed: {e}")

        # Fallback to email if Telegram failed completely or partially
        tg_has_failures = result.messages_sent < result.messages_total
        if (not tg_success or tg_has_failures) and self._email and self._email.available:
            try:
                date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                body = _combine_content(articles)

                if pipeline_errors:
                    notification = build_notification(pipeline_errors)
                    body += f"\n\n--- ERRORS ---\n{notification.format_message()}"

                await asyncio.to_thread(
                    self._email.send_daily_report, date_str, body, telegram_error=tg_error_msg
                )
                result.method = "email_backup"
                result.messages_sent = 1
                logger.info("Fallback to email backup successful")

            except Exception as e:
                logger.error(f"Email backup also failed: {e}")
                result.errors.append(f"Email: {e}")

        return result

    async def _send_images(self, articles: list[dict[str, str]]) -> None:
        """Send research images via Telegram sendPhoto (max 3/run)."""
        image_urls: list[tuple[str, str]] = []  # (url, caption)
        for article in articles:
            for img_url in article.get("image_urls", []):
                if img_url and len(image_urls) < 3:
                    caption = article.get("tier", "")
                    image_urls.append((img_url, caption))

        if not image_urls:
            return

        for url, caption in image_urls:
            try:
                await self._tg.send_photo(url, caption=caption)
                await asyncio.sleep(1.0)
            except Exception as e:
                logger.debug(f"Image send failed (non-critical): {e}")

        logger.info(f"Sent {len(image_urls)} research images")


def _combine_content(articles: list[dict[str, str]]) -> str:
    """Combine all articles into a single plain text body for email."""
    parts = []
    for article in articles:
        tier = article.get("tier", "")
        content = article.get("content", "")
        parts.append(f"[{tier}]\n{content}")
    return f"\n\n{'=' * 50}\n\n".join(parts)
