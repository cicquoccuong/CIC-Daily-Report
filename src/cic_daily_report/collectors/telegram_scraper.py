"""Telegram Channel Scraper (FR8) — collects from VN/EN crypto channels.

P1.5: Real Telethon integration with LLM classification (Groq).
High-risk component: session can expire, requires manual re-auth.
Falls back gracefully if credentials missing.
"""

from __future__ import annotations

import asyncio
import os
import re as _re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

# WHY try/except: trafilatura is in project dependencies but we want graceful
# fallback if it's somehow missing (e.g., minimal install).
try:
    import trafilatura
except ImportError:
    trafilatura = None  # type: ignore[assignment]

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

# QO.44: Tier 2 — Major News (7 channels).
# WHY "keyword" processing: these channels post short factual news that
# can be classified by keyword extraction, saving LLM quota for Tier 1.
TIER2_CHANNELS: list[TelegramChannelConfig] = [
    TelegramChannelConfig("@cointelegraph", "CoinTelegraph", 2, "EN", "News", "keyword"),
    TelegramChannelConfig(
        "@binance_announcements", "Binance Announcements", 2, "EN", "News", "keyword"
    ),
    TelegramChannelConfig("@WatcherGuru", "Watcher Guru", 2, "EN", "News", "keyword"),
    TelegramChannelConfig("@CryptoRankNews", "CryptoRank News", 2, "EN", "News", "keyword"),
    TelegramChannelConfig("@layergg", "Layer.gg", 2, "VN", "News", "keyword"),
    TelegramChannelConfig("@bitcoin", "Bitcoin", 2, "EN", "News", "keyword"),
    TelegramChannelConfig("@coffeecryptonews", "Coffee Crypto News", 2, "VN", "News", "keyword"),
]

# QO.44: Tier 3 — Data & Alerts (16 channels).
# WHY "regex" processing: these channels post structured data (whale alerts,
# funding rates, OI changes) that can be parsed with regex patterns.
TIER3_CHANNELS: list[TelegramChannelConfig] = [
    TelegramChannelConfig("@whale_alert_io", "Whale Alert", 3, "EN", "Data", "regex"),
    TelegramChannelConfig(
        "@cryptoquant_official", "CryptoQuant Official", 3, "EN", "Data", "regex"
    ),
    TelegramChannelConfig("@cryptoquant_alert", "CryptoQuant Alert", 3, "EN", "Data", "regex"),
    TelegramChannelConfig("@FundingRates1", "Funding Rates", 3, "EN", "Data", "regex"),
    TelegramChannelConfig("@oi_detector", "OI Detector", 3, "EN", "Data", "regex"),
    TelegramChannelConfig("@bitcoin_price", "Bitcoin Price", 3, "EN", "Data", "regex"),
    TelegramChannelConfig("@eth_price", "ETH Price", 3, "EN", "Data", "regex"),
    TelegramChannelConfig("@Database52Hz", "Database 52Hz", 3, "VN", "Data", "regex"),
    TelegramChannelConfig("@TokenUnlocksAlert", "Token Unlocks Alert", 3, "EN", "Data", "regex"),
    TelegramChannelConfig("@WhaleFreedomAlert", "Whale Freedom Alert", 3, "EN", "Data", "regex"),
    TelegramChannelConfig(
        "@CoinglassOfficialChannel", "Coinglass Official", 3, "EN", "Data", "regex"
    ),
    TelegramChannelConfig("@ArkhamIntelligence", "Arkham Intelligence", 3, "EN", "Data", "regex"),
    TelegramChannelConfig("@MaterialIndicatorsOG", "Material Indicators", 3, "EN", "Data", "regex"),
    TelegramChannelConfig("@rektcapital", "Rekt Capital", 3, "EN", "Insight", "regex"),
    TelegramChannelConfig("@DefiLlama", "DefiLlama", 3, "EN", "Data", "regex"),
    TelegramChannelConfig("@Coinank_Community", "Coinank Community", 3, "EN", "Data", "regex"),
]

# QO.44: Convenience list of all channels across all tiers (39 total).
ALL_CHANNELS: list[TelegramChannelConfig] = TIER1_CHANNELS + TIER2_CHANNELS + TIER3_CHANNELS

# Legacy default channels kept for backward compat (unused in P1.5+)
DEFAULT_CHANNELS = [
    "crypto_vn_community",
    "coin68_official",
    "tapchibitcoin",
    "vnbitcoin",
    "cryptoviet",
]

# --- Constants ---

_MESSAGES_PER_CHANNEL = 20  # max messages to read per channel (was 50, reduced to cut LLM calls)
_LOOKBACK_HOURS = 12  # only messages from last 12h (was 24h, fresher content)
_BATCH_SIZE = 20  # messages per LLM classification call (was 10, fewer API calls)
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


# --- QO.44: Tier 2 Keyword Classification ---

# WHY keyword-based: Tier 2 channels post factual news. Keyword extraction
# is cheaper than LLM calls and sufficient for sentiment + topic detection.

_BULLISH_KEYWORDS = {
    "surge",
    "soar",
    "rally",
    "breakout",
    "bullish",
    "pump",
    "ath",
    "all-time high",
    "accumulation",
    "buy",
    "long",
    "upgrade",
    "tang",
    "bung no",
    "pha dinh",
    "tich luy",
}
_BEARISH_KEYWORDS = {
    "crash",
    "dump",
    "plunge",
    "bearish",
    "liquidation",
    "hack",
    "exploit",
    "rug",
    "sell",
    "short",
    "downgrade",
    "ban",
    "giam",
    "sap",
    "thanh ly",
    "tan cong",
}


def _classify_by_keywords(messages: list[TelegramMessage]) -> list[TelegramMessage]:
    """QO.44: Classify Tier 2 messages using keyword matching.

    WHY not LLM: saves Groq quota for Tier 1 classification.
    Simple positive/negative word count ratio gives adequate sentiment
    for news-type messages.

    Returns messages with sentiment field populated.
    """
    for msg in messages:
        text_lower = msg.message_text.lower()
        bull_count = sum(1 for kw in _BULLISH_KEYWORDS if kw in text_lower)
        bear_count = sum(1 for kw in _BEARISH_KEYWORDS if kw in text_lower)

        if bull_count > bear_count:
            msg.sentiment = "BULLISH"
        elif bear_count > bull_count:
            msg.sentiment = "BEARISH"
        else:
            msg.sentiment = "NEUTRAL"

        msg.thesis = f"keyword: bull={bull_count} bear={bear_count}"

    classified = sum(1 for m in messages if m.sentiment)
    logger.info(f"Tier 2 keyword classification: {classified}/{len(messages)} classified")
    return messages


# --- QO.44: Tier 3 Regex Parsing ---

# WHY regex patterns: Tier 3 channels post structured data (whale transfers,
# funding rates, OI changes). Regex extracts the data directly without LLM.
_WHALE_PATTERN = _re.compile(
    r"(\d[\d,]*)\s+(BTC|ETH|USDT|USDC|XRP)\b.*?(transferred|moved|sent)",
    _re.IGNORECASE,
)
_FUNDING_PATTERN = _re.compile(
    r"(BTC|ETH)\s+funding.*?([+-]?\d+\.?\d*)%",
    _re.IGNORECASE,
)
_PRICE_PATTERN = _re.compile(
    r"(BTC|ETH|Bitcoin|Ethereum)\s*[:\s]+\$?([\d,]+\.?\d*)",
    _re.IGNORECASE,
)
_LIQUIDATION_PATTERN = _re.compile(
    r"\$?([\d,.]+[MBK]?)\s+(liquidat|liq\.)",
    _re.IGNORECASE,
)


def _parse_structured_data(messages: list[TelegramMessage]) -> list[TelegramMessage]:
    """QO.44: Parse Tier 3 messages using regex patterns.

    Extracts structured data (amounts, coins, directions) from
    data/alert channels. Results stored in key_levels and thesis fields.

    WHY not LLM: structured data has predictable formats. Regex is faster,
    cheaper, and more reliable than LLM for pattern extraction.
    """
    for msg in messages:
        text = msg.message_text
        parts = []

        # Whale transfers
        whale_match = _WHALE_PATTERN.search(text)
        if whale_match:
            amount = whale_match.group(1)
            coin = whale_match.group(2).upper()
            parts.append(f"whale:{coin} {amount}")

        # Funding rates
        funding_match = _FUNDING_PATTERN.search(text)
        if funding_match:
            coin = funding_match.group(1).upper()
            rate = funding_match.group(2)
            parts.append(f"funding:{coin} {rate}%")
            # WHY: extreme funding rates signal sentiment
            try:
                rate_val = float(rate)
                if rate_val > 0.05:
                    msg.sentiment = "BULLISH"
                elif rate_val < -0.05:
                    msg.sentiment = "BEARISH"
                else:
                    msg.sentiment = "NEUTRAL"
            except ValueError:
                pass

        # Price data
        price_match = _PRICE_PATTERN.search(text)
        if price_match:
            coin = price_match.group(1).upper()
            if coin in ("BITCOIN",):
                coin = "BTC"
            elif coin in ("ETHEREUM",):
                coin = "ETH"
            price = price_match.group(2)
            msg.key_levels = f"{coin} ${price}"

        # Liquidations
        liq_match = _LIQUIDATION_PATTERN.search(text)
        if liq_match:
            amount = liq_match.group(1)
            parts.append(f"liquidation:${amount}")

        if parts:
            msg.thesis = "regex:" + " | ".join(parts)
        if not msg.sentiment:
            msg.sentiment = "NEUTRAL"

    parsed = sum(1 for m in messages if m.thesis)
    logger.info(f"Tier 3 regex parsing: {parsed}/{len(messages)} with extracted data")
    return messages


# --- QO.45: Telethon Health Monitoring ---


@dataclass
class ChannelHealthStatus:
    """QO.45: Health status for a single Telegram channel.

    Tracks consecutive failures and message counts to detect
    channels that are down or no longer posting.
    """

    handle: str
    consecutive_failures: int = 0
    last_success: str = ""
    last_failure: str = ""
    last_message_count: int = 0
    is_healthy: bool = True

    # WHY threshold 3: transient network errors are common with Telegram.
    # 3 consecutive failures = ~9h at 3h intervals, strong signal of real issue.
    FAILURE_THRESHOLD: int = 3


class TelethonHealthMonitor:
    """QO.45: Monitors Telethon channel health and triggers RSS fallback.

    Tracks per-channel scrape results. If a channel fails N consecutive
    times (default 3), marks it unhealthy and returns it in the
    unhealthy list for RSS fallback consideration.

    WHY in-memory: Health state resets on pipeline restart, which is
    acceptable since GitHub Actions runs are ephemeral. For persistent
    tracking, we'd need to store in Sheets (future enhancement).
    """

    def __init__(self, failure_threshold: int = 3) -> None:
        self._statuses: dict[str, ChannelHealthStatus] = {}
        self._failure_threshold = failure_threshold

    def record_success(self, handle: str, message_count: int) -> None:
        """Record a successful channel scrape."""
        status = self._get_or_create(handle)
        status.consecutive_failures = 0
        status.last_success = datetime.now(timezone.utc).isoformat()
        status.last_message_count = message_count
        status.is_healthy = True

    def record_failure(self, handle: str, reason: str = "") -> None:
        """Record a failed channel scrape."""
        status = self._get_or_create(handle)
        status.consecutive_failures += 1
        status.last_failure = datetime.now(timezone.utc).isoformat()

        if status.consecutive_failures >= self._failure_threshold:
            status.is_healthy = False
            logger.warning(
                f"Channel {handle} marked UNHEALTHY after "
                f"{status.consecutive_failures} consecutive failures"
                f"{f': {reason}' if reason else ''}"
            )

    def get_unhealthy_channels(self) -> list[ChannelHealthStatus]:
        """Get list of unhealthy channels (for RSS fallback)."""
        return [s for s in self._statuses.values() if not s.is_healthy]

    def get_status(self, handle: str) -> ChannelHealthStatus | None:
        """Get health status for a specific channel."""
        return self._statuses.get(handle)

    def get_all_statuses(self) -> list[ChannelHealthStatus]:
        """Get health statuses for all tracked channels."""
        return list(self._statuses.values())

    def _get_or_create(self, handle: str) -> ChannelHealthStatus:
        """Get or create a health status entry."""
        if handle not in self._statuses:
            self._statuses[handle] = ChannelHealthStatus(handle=handle)
        return self._statuses[handle]


# QO.45: RSS fallback URLs for major channels.
# WHY: When Telethon scraping fails for a channel, we can try its RSS feed
# as a degraded alternative (no sentiment, but at least we get headlines).
RSS_FALLBACK_URLS: dict[str, str] = {
    "@cointelegraph": "https://cointelegraph.com/rss",
    "@bitcoin": "https://news.bitcoin.com/feed/",
    "@WatcherGuru": "https://watcher.guru/news/feed",
    "@CryptoRankNews": "https://cryptorank.io/news/feed",
    "@rektcapital": "https://rektcapital.substack.com/feed",
    "@DefiLlama": "https://defillama.com/feed",
}


async def _rss_fallback_scrape(
    unhealthy_channels: list[ChannelHealthStatus],
) -> list[TelegramMessage]:
    """QO.45: Fetch headlines from RSS feeds for unhealthy channels.

    WHY RSS: degraded but functional alternative when Telethon fails.
    Returns messages with source = "rss_fallback:{channel}" so downstream
    can distinguish them from Telethon-sourced messages.

    Only attempts RSS for channels that have a known RSS URL.
    """
    messages: list[TelegramMessage] = []

    for status in unhealthy_channels:
        rss_url = RSS_FALLBACK_URLS.get(status.handle, "")
        if not rss_url:
            continue

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(rss_url, follow_redirects=True)
                resp.raise_for_status()

            # WHY simple parsing: RSS feeds have <title> and <link> tags.
            # Full XML parsing would be better but adds dependency.
            # This regex approach handles most RSS/Atom feeds adequately.
            titles = _re.findall(
                r"<title><!\[CDATA\[(.*?)\]\]></title>|<title>(.*?)</title>",
                resp.text,
            )
            links = _re.findall(r"<link>(.*?)</link>", resp.text)

            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            # WHY skip first: first <title> is usually the feed title, not an item
            for i, title_groups in enumerate(titles[1:6]):  # Max 5 items
                title = title_groups[0] or title_groups[1]
                url = links[i + 1] if i + 1 < len(links) else ""
                messages.append(
                    TelegramMessage(
                        channel_name=f"rss_fallback:{status.handle}",
                        message_text=title,
                        date=now_str,
                        message_id=0,
                        language="EN",
                        category="News",
                        url=url,
                    )
                )

            if messages:
                logger.info(f"RSS fallback for {status.handle}: {len(messages)} items")
        except Exception as e:
            logger.debug(f"RSS fallback failed for {status.handle}: {e}")

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
    health_monitor: TelethonHealthMonitor | None = None,
) -> list[TelegramMessage]:
    """Scrape messages from Telegram channels using Telethon async client.

    WHY StringSession: avoids file-based session storage. The session string
    is stored in env var TELEGRAM_SESSION_STRING, making it CI-friendly.

    WHY async (not telethon.sync): Python 3.14 removed implicit event loop
    creation that telethon.sync relied on. Pure async is future-proof.

    QO.45: health_monitor tracks per-channel success/failure for RSS fallback.
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
                # QO.45: Record success in health monitor
                if health_monitor:
                    health_monitor.record_success(ch_config.handle, len(channel_messages))
            except asyncio.TimeoutError:
                logger.warning(
                    f"Channel {ch_config.handle} timed out after {_CHANNEL_TIMEOUT_SEC}s — skipping"
                )
                # QO.45: Record failure in health monitor
                if health_monitor:
                    health_monitor.record_failure(ch_config.handle, "timeout")
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
                # QO.45: Record failure in health monitor
                if health_monitor:
                    health_monitor.record_failure(ch_config.handle, str(e))
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


# --- Link Following (P1.21) ---

# WHY 10s: aggressive timeout per link — we'd rather skip a slow page
# than block the entire pipeline. Links are supplementary context, not critical.
_LINK_FOLLOW_TIMEOUT = 10.0

# WHY 2000 chars: LLM context window is limited; truncated article text
# gives enough context for better classification without wasting tokens.
_LINK_MAX_CHARS = 2000


async def _follow_links(messages: list[TelegramMessage]) -> list[TelegramMessage]:
    """Fetch and extract article content from URLs in Telegram messages.

    P1.21: For messages that contain a URL, fetches the page via httpx and
    extracts main content via trafilatura. Appended text gives the LLM
    richer context for classification (vs. just the short TG message).

    Errors are silently skipped per-link — one bad URL must not break others.
    """
    if trafilatura is None:
        logger.warning("trafilatura not installed — skipping TG link following")
        return messages

    msgs_with_url = [(i, m) for i, m in enumerate(messages) if m.url]
    if not msgs_with_url:
        return messages

    async def _fetch_one(idx: int, msg: TelegramMessage) -> None:
        """Fetch a single URL and append extracted text to message."""
        try:
            async with httpx.AsyncClient(timeout=_LINK_FOLLOW_TIMEOUT) as client:
                resp = await client.get(msg.url, follow_redirects=True)
            text = await asyncio.to_thread(trafilatura.extract, resp.text, include_comments=False)
            if text:
                # WHY: Append with separator so LLM can distinguish TG text from article
                truncated = text[:_LINK_MAX_CHARS]
                msg.message_text = f"{msg.message_text}\n\n--- Article content ---\n{truncated}"
        except Exception as e:
            # WHY: Skip silently — link following is best-effort enrichment
            logger.debug(f"Link follow failed for {msg.url}: {e}")

    tasks = [_fetch_one(i, m) for i, m in msgs_with_url]
    await asyncio.gather(*tasks, return_exceptions=True)

    enriched = sum(1 for _, m in msgs_with_url if "--- Article content ---" in m.message_text)
    logger.info(f"TG link following: {enriched}/{len(msgs_with_url)} URLs enriched")
    return messages


# --- Public API ---


async def collect_telegram(
    channels: list[TelegramChannelConfig] | None = None,
    health_monitor: TelethonHealthMonitor | None = None,
) -> list[TelegramMessage]:
    """Collect recent messages from Telegram channels.

    Requires TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION_STRING.
    Falls back gracefully if any are missing.

    P1.5: Uses Telethon async client + Groq LLM classification.
    QO.44: Supports Tier 1 (LLM), Tier 2 (keyword), Tier 3 (regex).
    QO.45: Health monitoring + RSS fallback for unhealthy channels.
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

    # QO.44: Default to ALL_CHANNELS (39 total: Tier 1+2+3).
    # WHY ALL_CHANNELS: Phase 2 expands to all 39 channels.
    channels = channels or ALL_CHANNELS
    logger.info(f"Collecting from {len(channels)} Telegram channels")

    # QO.45: Initialize health monitor if not provided
    if health_monitor is None:
        health_monitor = TelethonHealthMonitor()

    try:
        messages = await _scrape_channels(
            api_id, api_hash, session_string, channels, health_monitor
        )
        logger.info(f"Telegram: collected {len(messages)} messages")

        # QO.44: Split messages by tier for tier-specific processing
        tier1_msgs = [m for m in messages if _get_tier(m.channel_name, channels) == 1]
        tier2_msgs = [m for m in messages if _get_tier(m.channel_name, channels) == 2]
        tier3_msgs = [m for m in messages if _get_tier(m.channel_name, channels) == 3]

        # P1.21: Follow links BEFORE classification so LLM sees article content
        # WHY only Tier 1: Tier 2/3 don't need enriched context for their processing
        if tier1_msgs:
            tier1_msgs = await _follow_links(tier1_msgs)

        # P1.5: Classify Tier 1 messages using Groq LLM
        if tier1_msgs:
            tier1_msgs = await _classify_messages_batch(tier1_msgs)

        # QO.44: Classify Tier 2 messages using keyword matching
        if tier2_msgs:
            tier2_msgs = _classify_by_keywords(tier2_msgs)

        # QO.44: Parse Tier 3 messages using regex patterns
        if tier3_msgs:
            tier3_msgs = _parse_structured_data(tier3_msgs)

        all_processed = tier1_msgs + tier2_msgs + tier3_msgs

        # QO.45: Check for unhealthy channels and try RSS fallback
        unhealthy = health_monitor.get_unhealthy_channels()
        if unhealthy:
            logger.info(f"QO.45: {len(unhealthy)} unhealthy channels, attempting RSS fallback")
            rss_messages = await _rss_fallback_scrape(unhealthy)
            if rss_messages:
                all_processed.extend(rss_messages)
                logger.info(f"QO.45: RSS fallback added {len(rss_messages)} messages")

        return all_processed
    except Exception as e:
        if "auth" in str(e).lower() or "session" in str(e).lower():
            logger.error(f"TG session expired — manual re-auth needed: {e}")
        else:
            logger.error(f"Telegram scraping failed: {e}")
        return []


def _get_tier(channel_name: str, channels: list[TelegramChannelConfig]) -> int:
    """QO.44: Get tier for a channel by its display name.

    WHY by name not handle: TelegramMessage stores channel_name (display name),
    not the handle. We match against the config list.
    """
    for ch in channels:
        if ch.name == channel_name:
            return ch.tier
    return 1  # WHY default 1: unknown channels get full LLM processing (safest)
