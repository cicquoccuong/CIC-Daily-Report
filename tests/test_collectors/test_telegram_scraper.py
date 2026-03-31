"""Tests for collectors/telegram_scraper.py — P1.5 Telethon integration.

All Telethon and LLM calls are mocked — no real TG API in CI.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from cic_daily_report.collectors.telegram_scraper import (
    TIER1_CHANNELS,
    TelegramChannelConfig,
    TelegramMessage,
    _build_classification_prompt,
    _classify_messages_batch,
    _extract_url,
    _parse_classification_response,
    _scrape_single_channel,
    collect_telegram,
)

# --- TelegramChannelConfig ---


class TestTelegramChannelConfig:
    def test_tier1_channels_count(self):
        """TIER1_CHANNELS must contain exactly 16 channels per spec."""
        assert len(TIER1_CHANNELS) == 16

    def test_tier1_all_tier_1(self):
        """Every channel in TIER1_CHANNELS must have tier=1."""
        for ch in TIER1_CHANNELS:
            assert ch.tier == 1, f"{ch.handle} has tier={ch.tier}"

    def test_tier1_valid_languages(self):
        """All channels must have language VN or EN."""
        for ch in TIER1_CHANNELS:
            assert ch.language in ("VN", "EN"), f"{ch.handle}: {ch.language}"

    def test_tier1_valid_categories(self):
        """All channels must have valid category."""
        valid = {"Insight", "News", "Data", "Macro"}
        for ch in TIER1_CHANNELS:
            assert ch.category in valid, f"{ch.handle}: {ch.category}"

    def test_tier1_all_llm_full(self):
        """All Tier 1 channels use llm_full processing."""
        for ch in TIER1_CHANNELS:
            assert ch.processing == "llm_full", f"{ch.handle}: {ch.processing}"

    def test_tier1_handles_start_with_at(self):
        """All handles must start with @."""
        for ch in TIER1_CHANNELS:
            assert ch.handle.startswith("@"), f"{ch.handle} missing @"

    def test_tier1_unique_handles(self):
        """No duplicate handles."""
        handles = [ch.handle for ch in TIER1_CHANNELS]
        assert len(handles) == len(set(handles))

    def test_tier1_specific_channels_present(self):
        """Verify specific channels from spec are present."""
        handles = {ch.handle for ch in TIER1_CHANNELS}
        expected = {
            "@HCCapital_Channel",
            "@Fivemincryptoann",
            "@coin369channel",
            "@vnwallstreet",
            "@kryptonewsresearch",
            "@hctradecoin_channel",
            "@Coin98Insights",
            "@A1Aofficial",
            "@coin68",
            "@wublockchainenglish",
            "@MacroAlf",
            "@tedtalksmacro",
            "@crypto_macro",
            "@glassnodealerts",
            "@Laevitas_CryptoDerivatives",
            "@GreeksLiveTG",
        }
        assert handles == expected


# --- TelegramMessage ---


class TestTelegramMessage:
    def test_to_row_basic(self):
        msg = TelegramMessage(
            channel_name="crypto_vn",
            message_text="BTC hit 100k today",
            date="2026-03-09",
            message_id=123,
        )
        row = msg.to_row()
        assert len(row) == 11
        assert "telegram:crypto_vn" in row[3]
        assert row[5] == "vi"  # default language when empty

    def test_to_row_with_p15_fields(self):
        """P1.5 fields populate the row correctly."""
        msg = TelegramMessage(
            channel_name="HC Capital",
            message_text="BTC 67000 support holding strong",
            date="2026-03-30",
            message_id=456,
            sentiment="BULLISH",
            key_levels="BTC 67000-68000",
            thesis="Strong support level",
            language="VN",
            category="Insight",
            url="https://example.com/article",
        )
        row = msg.to_row()
        assert len(row) == 11
        assert row[2] == "https://example.com/article"  # URL field
        assert row[5] == "VN"  # language from channel config
        assert row[9] == "BULLISH"  # sentiment

    def test_to_row_language_defaults_to_vi(self):
        """Empty language defaults to 'vi'."""
        msg = TelegramMessage(channel_name="ch", message_text="msg", date="", message_id=1)
        assert msg.to_row()[5] == "vi"

    def test_to_row_language_en(self):
        """EN language is preserved."""
        msg = TelegramMessage(
            channel_name="ch",
            message_text="msg",
            date="",
            message_id=1,
            language="EN",
        )
        assert msg.to_row()[5] == "EN"


# --- Classification Prompt ---


class TestBuildClassificationPrompt:
    def test_basic_prompt(self):
        messages = [(1, "BTC going up"), (2, "ETH dumping")]
        prompt = _build_classification_prompt(messages)
        assert "MSG_1: BTC going up" in prompt
        assert "MSG_2: ETH dumping" in prompt
        assert "BULLISH" in prompt
        assert "NEUTRAL" in prompt
        assert "BEARISH" in prompt

    def test_single_message(self):
        prompt = _build_classification_prompt([(1, "test")])
        assert "MSG_1: test" in prompt


# --- Classification Parsing ---


class TestParseClassificationResponse:
    def test_standard_response(self):
        response = (
            "MSG_1: BULLISH | BTC 67000-68000 | Funding rate positive\n"
            "MSG_2: NEUTRAL | - | General news\n"
            "MSG_3: BEARISH | ETH 3200 | Volume declining"
        )
        results = _parse_classification_response(response, 3)
        assert len(results) == 3
        assert results[0]["sentiment"] == "BULLISH"
        assert results[0]["key_levels"] == "BTC 67000-68000"
        assert results[0]["thesis"] == "Funding rate positive"
        assert results[1]["sentiment"] == "NEUTRAL"
        assert results[2]["sentiment"] == "BEARISH"

    def test_pads_short_response(self):
        """If LLM returns fewer lines than expected, pad with empty."""
        response = "MSG_1: BULLISH | BTC 100k | Moon"
        results = _parse_classification_response(response, 3)
        assert len(results) == 3
        assert results[0]["sentiment"] == "BULLISH"
        assert results[1]["sentiment"] == ""
        assert results[2]["sentiment"] == ""

    def test_truncates_extra_lines(self):
        """If LLM returns more lines than expected, truncate."""
        response = "MSG_1: BULLISH | - | yes\nMSG_2: NEUTRAL | - | no\nMSG_3: BEARISH | - | maybe"
        results = _parse_classification_response(response, 2)
        assert len(results) == 2

    def test_invalid_sentiment_normalized(self):
        """Unknown sentiment values become empty string."""
        response = "MSG_1: UNKNOWN_SENTIMENT | - | test"
        results = _parse_classification_response(response, 1)
        assert results[0]["sentiment"] == ""

    def test_empty_response(self):
        results = _parse_classification_response("", 3)
        assert len(results) == 3
        assert all(r["sentiment"] == "" for r in results)

    def test_noise_lines_skipped(self):
        """Non-MSG lines (explanations, blank lines) are skipped."""
        response = (
            "Here's my analysis:\n"
            "\n"
            "MSG_1: BULLISH | BTC 100k | Strong momentum\n"
            "Overall the market looks good.\n"
        )
        results = _parse_classification_response(response, 1)
        assert results[0]["sentiment"] == "BULLISH"


# --- URL Extraction ---


class TestExtractUrl:
    def test_extracts_https(self):
        assert _extract_url("Check https://example.com/article") == "https://example.com/article"

    def test_extracts_http(self):
        assert _extract_url("Visit http://coin68.com") == "http://coin68.com"

    def test_no_url(self):
        assert _extract_url("BTC going up today") == ""

    def test_first_url_only(self):
        text = "See https://first.com and https://second.com"
        assert _extract_url(text) == "https://first.com"


# --- collect_telegram ---


class TestCollectTelegram:
    async def test_skips_when_missing_credentials(self):
        """No TG credentials → returns empty list."""
        with patch.dict("os.environ", {}, clear=True):
            result = await collect_telegram()
        assert result == []

    async def test_skips_when_partial_credentials(self):
        """Only API_ID set → returns empty list."""
        with patch.dict(
            "os.environ",
            {"TELEGRAM_API_ID": "123"},
            clear=True,
        ):
            result = await collect_telegram()
        assert result == []

    async def test_collect_with_mock_telethon(self):
        """Full flow: _scrape_channels returns messages → LLM classifies them."""
        env = {
            "TELEGRAM_API_ID": "123",
            "TELEGRAM_API_HASH": "abc",
            "TELEGRAM_SESSION_STRING": "session123",
            "GROQ_API_KEY": "groq_test_key",
        }

        # WHY mock _scrape_channels: TelegramClient is imported inside the
        # function, so it can't be patched at module level. We test scraping
        # separately in TestScrapeSingleChannel.
        scraped_messages = [
            TelegramMessage(
                channel_name="Test",
                message_text="BTC breaking 100k resistance, very bullish setup",
                date="2026-03-30 10:00:00",
                message_id=1001,
                language="VN",
                category="Insight",
            ),
            TelegramMessage(
                channel_name="Test",
                message_text="Check this https://example.com/analysis",
                date="2026-03-30 07:00:00",
                message_id=1002,
                language="VN",
                category="Insight",
                url="https://example.com/analysis",
            ),
        ]

        # Mock LLM response for classification
        mock_llm_response = MagicMock()
        mock_llm_response.text = (
            "MSG_1: BULLISH | BTC 100000 | Breaking resistance\n"
            "MSG_2: NEUTRAL | - | Article link, no clear direction"
        )

        with (
            patch.dict("os.environ", env, clear=True),
            patch(
                "cic_daily_report.collectors.telegram_scraper._scrape_channels",
                new_callable=AsyncMock,
                return_value=scraped_messages,
            ),
            patch(
                "cic_daily_report.adapters.llm_adapter._build_providers",
            ) as mock_providers,
            patch(
                "cic_daily_report.adapters.llm_adapter.LLMAdapter.generate",
                new_callable=AsyncMock,
                return_value=mock_llm_response,
            ),
        ):
            from cic_daily_report.adapters.llm_adapter import LLMProvider

            mock_providers.return_value = [LLMProvider("groq", "k", "m", "https://e", 60)]

            test_channel = [
                TelegramChannelConfig("@test_channel", "Test", 1, "VN", "Insight", "llm_full")
            ]
            result = await collect_telegram(channels=test_channel)

        assert len(result) == 2
        assert result[0].channel_name == "Test"
        assert result[0].message_text == "BTC breaking 100k resistance, very bullish setup"
        assert result[0].sentiment == "BULLISH"
        assert result[0].language == "VN"
        assert result[1].url == "https://example.com/analysis"

    async def test_collect_session_expired(self):
        """_scrape_channels raises auth error → returns empty list."""
        env = {
            "TELEGRAM_API_ID": "123",
            "TELEGRAM_API_HASH": "abc",
            "TELEGRAM_SESSION_STRING": "expired_session",
        }

        with (
            patch.dict("os.environ", env, clear=True),
            patch(
                "cic_daily_report.collectors.telegram_scraper._scrape_channels",
                new_callable=AsyncMock,
                side_effect=Exception("session expired"),
            ),
        ):
            result = await collect_telegram()

        assert result == []


# --- Channel error handling ---


class TestChannelErrorHandling:
    async def test_channel_not_found_skipped(self):
        """Channel not found → _scrape_single_channel raises, others continue."""
        # WHY: test _scrape_channels directly by mocking telethon import.
        # Approach: mock the entire telethon module at import time.
        mock_client = AsyncMock()
        mock_client.is_user_authorized = AsyncMock(return_value=True)
        mock_client.connect = AsyncMock()
        mock_client.disconnect = AsyncMock()

        async def mock_iter_messages(channel, limit=50):
            if channel == "@bad_channel":
                raise ValueError("Could not find the input entity for 'not found'")
            now = datetime.now(timezone.utc)
            msg = MagicMock()
            msg.text = "Good message"
            msg.date = now - timedelta(hours=1)
            msg.id = 2001
            yield msg

        mock_client.iter_messages = mock_iter_messages

        # WHY: patch telethon.TelegramClient at the telethon module level
        # because _scrape_channels imports it inside the function body.
        mock_tg_client_cls = MagicMock(return_value=mock_client)
        mock_string_session = MagicMock()

        channels = [
            TelegramChannelConfig("@bad_channel", "Bad", 1, "VN", "News", "llm_full"),
            TelegramChannelConfig("@good_channel", "Good", 1, "VN", "News", "llm_full"),
        ]

        with (
            patch("telethon.TelegramClient", mock_tg_client_cls),
            patch("telethon.sessions.StringSession", mock_string_session),
        ):
            from cic_daily_report.collectors.telegram_scraper import _scrape_channels

            result = await _scrape_channels("123", "abc", "session", channels)

        # Only good channel messages should be returned
        assert len(result) == 1
        assert result[0].channel_name == "Good"

    async def test_channel_timeout_skipped(self):
        """Channel that hangs → timeout, skipped, continues."""
        mock_client = AsyncMock()
        mock_client.is_user_authorized = AsyncMock(return_value=True)
        mock_client.connect = AsyncMock()
        mock_client.disconnect = AsyncMock()

        async def mock_iter_slow(channel, limit=50):
            await asyncio.sleep(100)
            yield  # pragma: no cover — never reached

        mock_client.iter_messages = mock_iter_slow

        mock_tg_client_cls = MagicMock(return_value=mock_client)
        mock_string_session = MagicMock()

        channels = [
            TelegramChannelConfig("@slow_channel", "Slow", 1, "VN", "News", "llm_full"),
        ]

        # WHY: patch _CHANNEL_TIMEOUT_SEC to tiny value so test runs fast
        with (
            patch("telethon.TelegramClient", mock_tg_client_cls),
            patch("telethon.sessions.StringSession", mock_string_session),
            patch(
                "cic_daily_report.collectors.telegram_scraper._CHANNEL_TIMEOUT_SEC",
                0.1,
            ),
        ):
            from cic_daily_report.collectors.telegram_scraper import _scrape_channels

            result = await _scrape_channels("123", "abc", "session", channels)

        assert result == []


# --- Classify batch ---


class TestClassifyBatch:
    async def test_classify_batch_success(self):
        """Messages get classified by LLM."""
        messages = [
            TelegramMessage(
                channel_name="Test",
                message_text="BTC breaking out above 100k",
                date="2026-03-30",
                message_id=1,
                language="VN",
                category="Insight",
            ),
            TelegramMessage(
                channel_name="Test",
                message_text="Market update: sideways movement",
                date="2026-03-30",
                message_id=2,
                language="VN",
                category="News",
            ),
        ]

        mock_response = MagicMock()
        mock_response.text = (
            "MSG_1: BULLISH | BTC 100000 | Breakout confirmed\n"
            "MSG_2: NEUTRAL | - | No clear direction"
        )

        with (
            patch.dict(
                "os.environ",
                {"GROQ_API_KEY": "test_key", "GEMINI_API_KEY": ""},
                clear=True,
            ),
            patch(
                "cic_daily_report.adapters.llm_adapter._build_providers",
            ) as mock_bp,
            patch(
                "cic_daily_report.adapters.llm_adapter.LLMAdapter.generate",
                new_callable=AsyncMock,
                return_value=mock_response,
            ),
        ):
            from cic_daily_report.adapters.llm_adapter import LLMProvider

            mock_bp.return_value = [LLMProvider("groq", "k", "m", "https://e", 60)]
            result = await _classify_messages_batch(messages)

        assert result[0].sentiment == "BULLISH"
        assert result[0].key_levels == "BTC 100000"
        assert result[0].thesis == "Breakout confirmed"
        assert result[1].sentiment == "NEUTRAL"

    async def test_classify_batch_no_groq_key(self):
        """No GROQ_API_KEY → messages returned unclassified."""
        messages = [
            TelegramMessage(channel_name="T", message_text="test", date="", message_id=1),
        ]
        with patch.dict("os.environ", {}, clear=True):
            result = await _classify_messages_batch(messages)
        assert len(result) == 1
        assert result[0].sentiment == ""

    async def test_classify_batch_llm_failure(self):
        """LLM call fails → messages returned without sentiment."""
        messages = [
            TelegramMessage(
                channel_name="T",
                message_text="BTC update",
                date="",
                message_id=1,
            ),
        ]

        with (
            patch.dict(
                "os.environ",
                {"GROQ_API_KEY": "test_key", "GEMINI_API_KEY": ""},
                clear=True,
            ),
            patch(
                "cic_daily_report.adapters.llm_adapter._build_providers",
            ) as mock_bp,
            patch(
                "cic_daily_report.adapters.llm_adapter.LLMAdapter.generate",
                new_callable=AsyncMock,
                side_effect=Exception("API error"),
            ),
        ):
            from cic_daily_report.adapters.llm_adapter import LLMProvider

            mock_bp.return_value = [LLMProvider("groq", "k", "m", "https://e", 60)]
            result = await _classify_messages_batch(messages)

        assert len(result) == 1
        assert result[0].sentiment == ""  # unclassified, not crashed

    async def test_classify_empty_list(self):
        """Empty message list → returns empty."""
        result = await _classify_messages_batch([])
        assert result == []


# --- _scrape_single_channel ---


class TestScrapeSingleChannel:
    async def test_filters_old_messages(self):
        """Messages older than cutoff are excluded."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=24)

        new_msg = MagicMock()
        new_msg.text = "Fresh news"
        new_msg.date = now - timedelta(hours=2)
        new_msg.id = 100

        old_msg = MagicMock()
        old_msg.text = "Old news"
        old_msg.date = now - timedelta(hours=48)
        old_msg.id = 99

        mock_client = AsyncMock()

        async def mock_iter(channel, limit=50):
            for m in [new_msg, old_msg]:
                yield m

        mock_client.iter_messages = mock_iter

        ch = TelegramChannelConfig("@test", "Test", 1, "VN", "News", "llm_full")
        result = await _scrape_single_channel(mock_client, ch, cutoff)

        assert len(result) == 1
        assert result[0].message_text == "Fresh news"

    async def test_skips_non_text_messages(self):
        """Messages without text (photos, stickers) are skipped."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=24)

        text_msg = MagicMock()
        text_msg.text = "Actual text"
        text_msg.date = now - timedelta(hours=1)
        text_msg.id = 200

        photo_msg = MagicMock()
        photo_msg.text = None
        photo_msg.date = now - timedelta(hours=2)
        photo_msg.id = 201

        empty_msg = MagicMock()
        empty_msg.text = ""
        empty_msg.date = now - timedelta(hours=3)
        empty_msg.id = 202

        mock_client = AsyncMock()

        async def mock_iter(channel, limit=50):
            for m in [text_msg, photo_msg, empty_msg]:
                yield m

        mock_client.iter_messages = mock_iter

        ch = TelegramChannelConfig("@test", "Test", 1, "EN", "Data", "llm_full")
        result = await _scrape_single_channel(mock_client, ch, cutoff)

        assert len(result) == 1
        assert result[0].message_text == "Actual text"
        assert result[0].language == "EN"
        assert result[0].category == "Data"
