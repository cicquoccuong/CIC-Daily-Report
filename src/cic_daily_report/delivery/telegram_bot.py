"""Telegram Bot delivery — send tier articles + summary (FR29, QĐ6).

Handles: message formatting, smart splitting (4096 char limit),
tier labels, MarkdownV2 escaping, rate limiting delay.
"""

from __future__ import annotations

import asyncio
import html as html_lib
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

from cic_daily_report.core.error_handler import DeliveryError
from cic_daily_report.core.logger import get_logger
from cic_daily_report.core.retry_utils import retry_async

logger = get_logger("telegram_bot")

TG_MAX_LENGTH = 4000  # Telegram limit is 4096 but use 4000 for UTF-8 safety margin
SEND_DELAY = 1.5  # seconds between messages to avoid rate limiting


@dataclass
class TelegramMessage:
    """A message ready to send via Telegram Bot API."""

    tier_label: str
    content: str
    part: int = 1
    total_parts: int = 1

    @property
    def formatted(self) -> str:
        """Full message text with tier label and part indicator."""
        if self.total_parts > 1:
            header = f"[{self.tier_label} - Phần {self.part}/{self.total_parts}]"
        else:
            header = f"[{self.tier_label}]"
        return f"{header}\n\n{self.content}"


def split_message(tier_label: str, content: str) -> list[TelegramMessage]:
    """Split content into TG-safe messages (QĐ6: split by section, not mid-sentence).

    Splits on section headers (## or **) when possible, falls back to newlines.
    """
    header_len = len(f"[{tier_label} - Phần 99/99]\n\n")
    max_content = TG_MAX_LENGTH - header_len

    if len(content) <= max_content:
        return [TelegramMessage(tier_label=tier_label, content=content)]

    # Split by sections (## headers or bold headers)
    sections = re.split(r"(?=\n##\s|\n\*\*[^*]+\*\*\n)", content)
    if len(sections) <= 1:
        # Fallback: split by double newlines
        sections = content.split("\n\n")

    parts: list[str] = []
    current = ""

    for section in sections:
        if len(current) + len(section) > max_content and current:
            parts.append(current.strip())
            current = section
        else:
            current += section

    if current.strip():
        parts.append(current.strip())

    # Hard fallback: if any part still exceeds max, chunk it
    final_parts: list[str] = []
    for part in parts:
        while len(part) > max_content:
            final_parts.append(part[:max_content])
            part = part[max_content:]
        if part.strip():
            final_parts.append(part.strip())
    parts = final_parts if final_parts else parts

    total = len(parts)
    return [
        TelegramMessage(tier_label=tier_label, content=p, part=i + 1, total_parts=total)
        for i, p in enumerate(parts)
    ]


def prepare_messages(
    articles: list[dict[str, str]],
) -> list[TelegramMessage]:
    """Prepare TelegramMessages from article dicts.

    Args:
        articles: list of {"tier": "L1", "content": "..."} or
                  {"tier": "Summary", "content": "..."}
    """
    messages: list[TelegramMessage] = []
    for article in articles:
        tier = article.get("tier", "")
        content = article.get("content", "")
        messages.extend(split_message(tier, content))
    return messages


class TelegramBot:
    """Telegram Bot API client for message delivery."""

    def __init__(
        self,
        bot_token: str | None = None,
        chat_id: str | None = None,
    ) -> None:
        self._token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self._chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")

        if not self._token or not self._chat_id:
            raise DeliveryError(
                "Telegram config missing — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID",
                source="telegram_bot",
            )

    async def send_message(self, text: str, parse_mode: str = "HTML") -> dict[str, Any]:
        """Send a single message via Telegram Bot API with retry."""
        return await retry_async(
            self._send_raw,
            text=text,
            parse_mode=parse_mode,
        )

    async def _send_raw(self, text: str, parse_mode: str = "HTML") -> dict[str, Any]:
        """Raw send — called by retry wrapper.

        Note: All text is HTML-escaped at this level to prevent parsing errors.
        If HTML formatting tags are needed in future, move escaping to caller level.
        """
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        # Escape HTML entities to prevent TG parsing errors (M1 fix)
        text = html_lib.escape(text)
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()

        data = resp.json()
        if not data.get("ok"):
            raise DeliveryError(
                f"Telegram API error: {data.get('description', 'unknown')}",
                source="telegram_bot",
            )
        return data

    async def deliver_all(
        self,
        messages: list[TelegramMessage],
    ) -> list[dict[str, Any]]:
        """Send all messages in order with delay between each (NFR18).

        Returns list of Telegram API responses.
        """
        results: list[dict[str, Any]] = []

        for i, msg in enumerate(messages):
            try:
                result = await self.send_message(msg.formatted)
                results.append(result)
                logger.info(f"Sent [{msg.tier_label}] part {msg.part}/{msg.total_parts}")

                # Delay between messages (except after last)
                if i < len(messages) - 1:
                    await asyncio.sleep(SEND_DELAY)

            except Exception as e:
                logger.error(f"Failed to send [{msg.tier_label}]: {e}")
                results.append({"ok": False, "error": str(e), "tier": msg.tier_label})

        sent = sum(1 for r in results if r.get("ok"))
        logger.info(f"Delivery complete: {sent}/{len(messages)} messages sent")
        return results
