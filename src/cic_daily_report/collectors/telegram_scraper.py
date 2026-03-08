"""Telegram Channel Scraper (FR8) — collects from VN crypto channels.

High-risk component: session can expire, requires manual re-auth.
Falls back gracefully if credentials missing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

from cic_daily_report.core.logger import get_logger

logger = get_logger("telegram_scraper")

# Default channels to scrape
DEFAULT_CHANNELS = [
    "crypto_vn_community",
    "coin68_official",
    "tapchibitcoin",
    "vnbitcoin",
    "cryptoviet",
]


@dataclass
class TelegramMessage:
    """Message from a Telegram channel."""

    channel_name: str
    message_text: str
    date: str
    message_id: int

    def to_row(self) -> list[str]:
        collected_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        return [
            "",  # ID
            self.message_text[:200],  # title (truncated)
            "",  # URL
            f"telegram:{self.channel_name}",
            collected_at,
            "vi",
            self.message_text[:500],  # summary
            "",  # event_type
            "",  # coin_symbol
            "",  # sentiment_score
            "",  # action_category
        ]


async def collect_telegram(
    channels: list[str] | None = None,
) -> list[TelegramMessage]:
    """Collect recent messages from Telegram channels.

    Requires TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION_STRING.
    Falls back gracefully if any are missing.
    """
    api_id = os.getenv("TELEGRAM_API_ID", "")
    api_hash = os.getenv("TELEGRAM_API_HASH", "")
    session_string = os.getenv("TELEGRAM_SESSION_STRING", "")

    if not all([api_id, api_hash, session_string]):
        logger.warning(
            "TG scraping disabled — missing credentials "
            "(TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION_STRING)"
        )
        return []

    channels = channels or DEFAULT_CHANNELS
    logger.info(f"Collecting from {len(channels)} Telegram channels")

    # Telethon/Pyrogram integration would go here
    # For MVP, this is a placeholder that returns empty
    # Full implementation requires Telethon which needs session management
    try:
        messages = await _scrape_channels(api_id, api_hash, session_string, channels)
        logger.info(f"Telegram: collected {len(messages)} messages")
        return messages
    except Exception as e:
        if "auth" in str(e).lower() or "session" in str(e).lower():
            logger.error(f"TG session expired — manual re-auth needed: {e}")
        else:
            logger.error(f"Telegram scraping failed: {e}")
        return []


async def _scrape_channels(
    api_id: str,
    api_hash: str,
    session_string: str,
    channels: list[str],
) -> list[TelegramMessage]:
    """Scrape messages from channels. Placeholder for Telethon integration."""
    # TODO: Implement with Telethon when session management is ready
    # This is intentionally a no-op for MVP — TG scraping is highest-risk component
    logger.info("Telegram scraper: placeholder mode (Telethon not yet integrated)")
    return []
