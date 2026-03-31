"""Telegram Channel Scraper (FR8) — collects from VN/EN crypto channels.

P1.5: Real Telethon integration with LLM classification (Groq).
High-risk component: session can expire, requires manual re-auth.
Falls back gracefully if credentials missing.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from cic_daily_report.core.logger import get_logger

logger = get_logger("telegram_scraper")

# --- Channel Configuration ---


@dataclass
class TelegramChannelConfig:
    """Configuration for a single Telegram channel.

    WHY dataclass: easy to extend for Tier 2/3 channels later.
    """

    handle: str  # e.g., "@HCCapital_Channel"
    name: str  # display name
    tier: int  # 1, 2, or 3
    language: str  # "VN" or "EN"
    category: str  # "Insight", "News", "Data", "Macro"
    processing: str  # "llm_full", "keyword", "regex"


# WHY constant: easy to extend with Tier 2/3 in later phases.
# 16 Tier 1 channels — curated by CIC team for crypto signal quality.
TIER1_CHANNELS: list[TelegramChannelConfig] = [
    # --- Vietnamese Insight channels ---
    TelegramChannelConfig("@HCCapital_Channel", "HC Capital", 1, "VN", "Insight", "llm_full"),
    TelegramChannelConfig("@Fivemincryptoann", "5 Min Crypto", 1, "VN", "Insight", "llm_full"),
    TelegramChannelConfig("@coin369channel", "Coin369", 1, "VN", "Insight", "llm_full"),
    TelegramChannelConfig("@vnwallstreet", "VN Wall Street", 1, "VN", "Macro", "llm_full"),
    TelegramChannelConfig("@kryptonewsresearch", "Krypto Research", 1, "VN", "Insight", "llm_full"),
    TelegramChannelConfig("@hctradecoin_channel", "HC Trade Coin", 1, "VN", "Insight", "llm_full"),
    TelegramChannelConfig("@Coin98Insights", "Coin98 Insights", 1, "VN", "News", "llm_full"),
    TelegramChannelConfig("@A1Aofficial", "A1A Official", 1, "VN", "Insight", "llm_full"),
    # --- Vietnamese News channels ---
    TelegramChannelConfig("@coin68", "Coin68", 1, "VN", "News", "llm_full"),
    # --- English channels ---
    TelegramChannelConfig("@wublockchainenglish", "Wu Blockchain", 1, "EN", "News", "llm_full"),
    TelegramChannelConfig("@MacroAlf", "Macro Alf", 1, "EN", "Macro", "llm_full"),
    TelegramChannelConfig("@tedtalksmacro", "Ted Talks Macro", 1, "EN", "Macro", "llm_full"),
    TelegramChannelConfig("@crypto_macro", "Crypto Macro", 1, "EN", "Macro", "llm_full"),
    # --- English Data/Alert channels ---
    TelegramChannelConfig("@glassnodealerts", "Glassnode Alerts", 1, "EN", "Data", "llm_full"),
    TelegramChannelConfig(
        "@Laevitas_CryptoDerivatives", "Laevitas Derivatives", 1, "EN", "Data", "llm_full"
    ),
    TelegramChannelConfig("@GreeksLiveTG", "Greeks Live", 1, "EN", "Data", "llm_full"),
]

# Legacy default channels kept for backward compat (unused in P1.5+)
DEFAULT_CHANNELS = [
    "crypto_vn_community",
    "coin68_official",
    "tapchibitcoin",
    "vnbitcoin",
    "cryptoviet",
]

# --- Constants ---

_MESSAGES_PER_CHANNEL = 50  # max messages to read per channel
_LOOKBACK_HOURS = 24  # only messages from last 24h
_BATCH_SIZE = 10  # messages per LLM classification call
_CHANNEL_TIMEOUT_SEC = 30  # timeout per channel scrape


# --- Data classes ---


@dataclass
class TelegramMessage:
    """Message from a Telegram channel."""

    channel_name: str
    message_text: str
    date: str
    message_id: int
    # P1.5 additions — classification fields
    sentiment: str = ""  # "BULLISH" / "NEUTRAL" / "BEARISH"
    key_levels: str = ""  # extracted price levels
    thesis: str = ""  # reasoning summary
    language: str = ""  # "VN" or "EN"
    category: str = ""  # "Insight", "Macro", etc.
    url: str = ""  # link in message (for link following)

    def to_row(self) -> list[str]:
        collected_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        return [
            "",  # ID
            self.message_text[:200],  # title (truncated)
            self.url,  # URL (P1.5: extracted link)
            f"telegram:{self.channel_name}",
            collected_at,
            self.language or "vi",
            self.message_text[:500],  # summary
            "",  # event_type
            "",  # coin_symbol
            self.sentiment,  # sentiment_score (P1.5: LLM classification)
            "",  # action_category
        ]


# --- LLM Classification ---


def _build_classification_prompt(messages: list[tuple[int, str]]) -> str:
    """Build the batch classification prompt for Groq.

    WHY batching: reduce LLM calls from N to N/10. Groq has generous
    rate limits but batching still saves latency and cost.

    Args:
        messages: list of (index, text[:500]) tuples.
    """
    msg_block = "\n".join(f"MSG_{idx}: {text}" for idx, text in messages)
    return (
        "Classify each crypto message below:\n"
        "- Sentiment: BULLISH / NEUTRAL / BEARISH\n"
        "- Key Levels: Important price levels (support/resistance) if any\n"
        "- Thesis: 1-sentence summary of reasoning\n\n"
        "Format output EXACTLY as:\n"
        "MSG_1: BULLISH | BTC 67000-68000 | Funding rate positive = accumulation\n"
        "MSG_2: NEUTRAL | - | General news, no clear direction\n"
        "...\n\n"
        f"Messages:\n{msg_block}"
    )


def _parse_classification_response(response_text: str, count: int) -> list[dict[str, str]]:
    """Parse LLM classification response into structured data.

    WHY lenient parsing: LLM output may not perfectly match format.
    We extract what we can and leave blanks for unparseable lines.

    Returns:
        List of dicts with keys: sentiment, key_levels, thesis.
        Length matches `count` (pads with empty dicts if LLM output is short).
    """
    results: list[dict[str, str]] = []
    lines = response_text.strip().split("\n")

    for line in lines:
        line = line.strip()
        if not line or not line.upper().startswith("MSG_"):
            continue

        # Remove "MSG_N:" prefix
        colon_pos = line.find(":")
        if colon_pos < 0:
            continue
        content = line[colon_pos + 1 :].strip()

        parts = [p.strip() for p in content.split("|")]
        sentiment = parts[0].upper() if len(parts) > 0 else ""
        # Normalize sentiment to valid values only
        if sentiment not in ("BULLISH", "NEUTRAL", "BEARISH"):
            sentiment = ""
        key_levels = parts[1] if len(parts) > 1 else ""
        thesis = parts[2] if len(parts) > 2 else ""

        results.append({"sentiment": sentiment, "key_levels": key_levels, "thesis": thesis})

    # Pad to expected count if LLM returned fewer lines
    while len(results) < count:
        results.append({"sentiment": "", "key_levels": "", "thesis": ""})

    return results[:count]


async def _classify_messages_batch(
    messages: list[TelegramMessage],
) -> list[TelegramMessage]:
    """Classify messages in batches using Groq LLM.

    WHY Groq not Gemini: save Gemini quota for Master Analysis (the
    most critical LLM call in the pipeline). Groq has 12K TPM which
    is plenty for classification batches.

    Falls back gracefully: if LLM fails, messages are returned with
    empty sentiment fields (still usable as raw news).
    """
    if not messages:
        return messages

    groq_key = os.getenv("GROQ_API_KEY", "")
    if not groq_key:
        logger.warning("GROQ_API_KEY not set — skipping TG classification")
        return messages

    try:
        from cic_daily_report.adapters.llm_adapter import LLMAdapter

        llm = LLMAdapter(prefer="groq")
    except Exception as e:
        logger.warning(f"LLM adapter init failed — skipping classification: {e}")
        return messages

    # Process in batches of _BATCH_SIZE
    for batch_start in range(0, len(messages), _BATCH_SIZE):
        batch = messages[batch_start : batch_start + _BATCH_SIZE]
        indexed_texts = [(i + 1, msg.message_text[:500]) for i, msg in enumerate(batch)]

        prompt = _build_classification_prompt(indexed_texts)
        try:
            response = await llm.generate(
                prompt=prompt,
                max_tokens=1024,
                temperature=0.3,
                system_prompt=(
                    "You are a crypto market analyst. Classify messages concisely. "
                    "Output ONLY the MSG_N: SENTIMENT | LEVELS | THESIS lines."
                ),
            )
            parsed = _parse_classification_response(response.text, len(batch))

            for i, classification in enumerate(parsed):
                batch[i].sentiment = classification["sentiment"]
                batch[i].key_levels = classification["key_levels"]
                batch[i].thesis = classification["thesis"]

            logger.debug(
                f"Classified batch {batch_start // _BATCH_SIZE + 1}: {len(batch)} messages"
            )
        except Exception as e:
            # WHY catch-all: classification failure must not break data collection.
            # Messages are still usable without sentiment.
            logger.warning(
                f"LLM classification failed for batch {batch_start // _BATCH_SIZE + 1}: {e}"
            )

    classified_count = sum(1 for m in messages if m.sentiment)
    logger.info(f"Classification complete: {classified_count}/{len(messages)} messages classified")
    return messages


# --- Telethon Scraping ---


def _extract_url(text: str) -> str:
    """Extract the first URL from message text.

    WHY simple regex: Telegram messages often contain article links.
    We extract the first one for link-following in later phases.
    """
    import re

    match = re.search(r"https?://\S+", text)
    return match.group(0) if match else ""


async def _scrape_channels(
    api_id: str,
    api_hash: str,
    session_string: str,
    channels: list[TelegramChannelConfig],
) -> list[TelegramMessage]:
    """Scrape messages from Telegram channels using Telethon async client.

    WHY StringSession: avoids file-based session storage. The session string
    is stored in env var TELEGRAM_SESSION_STRING, making it CI-friendly.

    WHY async (not telethon.sync): Python 3.14 removed implicit event loop
    creation that telethon.sync relied on. Pure async is future-proof.
    """
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    cutoff = datetime.now(timezone.utc) - timedelta(hours=_LOOKBACK_HOURS)
    all_messages: list[TelegramMessage] = []

    client = TelegramClient(StringSession(session_string), int(api_id), api_hash)
    await client.connect()

    if not await client.is_user_authorized():
        logger.error("TG session not authorized — manual re-auth needed")
        await client.disconnect()
        return []

    try:
        for ch_config in channels:
            try:
                channel_messages = await asyncio.wait_for(
                    _scrape_single_channel(client, ch_config, cutoff),
                    timeout=_CHANNEL_TIMEOUT_SEC,
                )
                all_messages.extend(channel_messages)
            except asyncio.TimeoutError:
                logger.warning(
                    f"Channel {ch_config.handle} timed out after {_CHANNEL_TIMEOUT_SEC}s — skipping"
                )
            except Exception as e:
                # WHY broad except: one channel failing must not stop others.
                # Common causes: channel not found, not joined, restricted.
                err_msg = str(e).lower()
                if "no user" in err_msg or "not found" in err_msg or "invite" in err_msg:
                    logger.warning(
                        f"Channel {ch_config.handle} not accessible — not joined or not found: {e}"
                    )
                else:
                    logger.warning(f"Channel {ch_config.handle} scrape failed: {e}")
    finally:
        await client.disconnect()

    return all_messages


async def _scrape_single_channel(
    client: object,
    ch_config: TelegramChannelConfig,
    cutoff: datetime,
) -> list[TelegramMessage]:
    """Scrape a single channel for messages after cutoff.

    WHY separate function: isolates per-channel error handling and
    makes timeout wrapping cleaner in the caller.
    """
    messages: list[TelegramMessage] = []

    # client.iter_messages returns newest first
    async for msg in client.iter_messages(  # type: ignore[attr-defined]
        ch_config.handle, limit=_MESSAGES_PER_CHANNEL
    ):
        # Skip messages older than cutoff
        if msg.date and msg.date.replace(tzinfo=timezone.utc) < cutoff:
            break

        # Skip non-text messages (photos, stickers, etc.)
        if not msg.text:
            continue

        messages.append(
            TelegramMessage(
                channel_name=ch_config.name,
                message_text=msg.text,
                date=msg.date.strftime("%Y-%m-%d %H:%M:%S") if msg.date else "",
                message_id=msg.id,
                language=ch_config.language,
                category=ch_config.category,
                url=_extract_url(msg.text),
            )
        )

    if messages:
        logger.info(f"  {ch_config.handle}: {len(messages)} messages")
    return messages


# --- Public API ---


async def collect_telegram(
    channels: list[TelegramChannelConfig] | None = None,
) -> list[TelegramMessage]:
    """Collect recent messages from Telegram channels.

    Requires TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION_STRING.
    Falls back gracefully if any are missing.

    P1.5: Uses Telethon async client + Groq LLM classification.
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

    # WHY default to TIER1_CHANNELS: Phase 1 only uses Tier 1.
    # Tier 2/3 channels will be added in later phases.
    channels = channels or TIER1_CHANNELS
    logger.info(f"Collecting from {len(channels)} Telegram channels")

    try:
        messages = await _scrape_channels(api_id, api_hash, session_string, channels)
        logger.info(f"Telegram: collected {len(messages)} messages")

        # P1.5: Classify messages using Groq LLM
        if messages:
            messages = await _classify_messages_batch(messages)

        return messages
    except Exception as e:
        if "auth" in str(e).lower() or "session" in str(e).lower():
            logger.error(f"TG session expired — manual re-auth needed: {e}")
        else:
            logger.error(f"Telegram scraping failed: {e}")
        return []
