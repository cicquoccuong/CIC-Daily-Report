"""Tests for P1.23 (strip think tags) and P1.24 (truncate on length) in llm_adapter.py."""

from unittest.mock import AsyncMock, MagicMock, patch

from cic_daily_report.adapters.llm_adapter import (
    LLMAdapter,
    LLMProvider,
    LLMResponse,
    _call_gemini,
    _call_groq,
    _strip_think_tags,
    _truncate_to_complete_sentence,
)

# ---------------------------------------------------------------------------
# Helpers — reuse provider factories from existing tests
# ---------------------------------------------------------------------------


def _groq_qwen_provider() -> LLMProvider:
    """Groq provider with Qwen3 model (has 'qwen' in model name)."""
    return LLMProvider(
        name="groq",
        api_key="test-key",
        model="qwen/qwen3-32b",
        endpoint="https://api.groq.com/openai/v1/chat/completions",
        rate_limit_per_min=60,
    )


def _groq_llama_provider() -> LLMProvider:
    """Groq provider with Llama 4 model (no 'qwen' in model name)."""
    return LLMProvider(
        name="groq_llama4",
        api_key="test-key",
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        endpoint="https://api.groq.com/openai/v1/chat/completions",
        rate_limit_per_min=30,
    )


def _cerebras_provider() -> LLMProvider:
    """Cerebras provider with Qwen3 model (has 'qwen' in model name)."""
    return LLMProvider(
        name="cerebras",
        api_key="test-key",
        model="qwen-3-32b",
        endpoint="https://api.cerebras.ai/v1/chat/completions",
        rate_limit_per_min=30,
    )


def _gemini_provider() -> LLMProvider:
    return LLMProvider(
        name="gemini_flash",
        api_key="test-key",
        model="gemini-2.5-flash",
        endpoint="https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
        rate_limit_per_min=15,
    )


def _mock_httpx_client(json_response: dict) -> MagicMock:
    """Create a mocked httpx.AsyncClient that returns the given JSON."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = json_response
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


# ===========================================================================
# P1.23 — Strip <think> tags
# ===========================================================================


class TestStripThinkTags:
    def test_strip_think_tags_basic(self):
        """Removes <think>reasoning</think> from text."""
        text = "<think>reasoning here</think>Bitcoin rose 5% today."
        assert _strip_think_tags(text) == "Bitcoin rose 5% today."

    def test_strip_think_tags_multiline(self):
        """Removes multi-line think blocks."""
        text = (
            "<think>\nLet me analyze this...\n"
            "Step 1: check price\nStep 2: check volume\n</think>\n"
            "BTC is bullish."
        )
        assert _strip_think_tags(text) == "BTC is bullish."

    def test_strip_think_tags_no_tags(self):
        """Text without think tags is returned unchanged (minus leading/trailing space)."""
        text = "Clean text with no tags."
        assert _strip_think_tags(text) == "Clean text with no tags."

    def test_strip_think_tags_nested(self):
        """Handles edge case: <think> inside <think> — greedy-minimal match.

        WHY: re.DOTALL with .*? (non-greedy) will match from first <think>
        to first </think>, which is correct for nested-like content.
        """
        text = "<think>outer <think>inner</think> rest"
        # Non-greedy .*? matches from first <think> to first </think>
        result = _strip_think_tags(text)
        assert "<think>" not in result
        # "rest" remains after stripping
        assert "rest" in result

    def test_strip_think_tags_empty(self):
        """Empty think tags are removed."""
        text = "Before <think></think> After"
        assert _strip_think_tags(text) == "Before  After"

    def test_strip_think_tags_multiple(self):
        """Multiple think blocks in one response are all removed."""
        text = "<think>thought 1</think>First sentence. <think>thought 2</think>Second sentence."
        assert _strip_think_tags(text) == "First sentence. Second sentence."

    def test_strip_think_tags_unclosed(self):
        """Unclosed <think> tag: LLM ran out of tokens mid-thinking.

        WHY: If finish_reason=length while inside a <think> block, the closing
        </think> tag is missing. The regex won't match, so the fallback must
        strip everything from <think> to end of text.
        """
        text = "Before <think>reasoning without close"
        assert _strip_think_tags(text) == "Before"

    def test_strip_think_tags_unclosed_no_content_before(self):
        """Unclosed <think> with nothing before it returns empty string."""
        text = "<think>all reasoning no output"
        assert _strip_think_tags(text) == ""

    def test_strip_think_tags_unclosed_preserves_complete_blocks(self):
        """Closed block is stripped, then unclosed block at end is also stripped."""
        text = "<think>first thought</think>Good content. <think>second thought without close"
        result = _strip_think_tags(text)
        assert result == "Good content."


class TestGroqQwenThinkingParam:
    async def test_groq_qwen_disables_thinking(self):
        """Verify payload includes thinking disabled for qwen models."""
        provider = _groq_qwen_provider()

        json_resp = {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 10},
        }
        mock_client = _mock_httpx_client(json_resp)

        with patch(
            "cic_daily_report.adapters.llm_adapter.httpx.AsyncClient",
            return_value=mock_client,
        ):
            await _call_groq(provider, "prompt", 1024, 0.7, "")

        # Inspect the payload sent to httpx
        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert "thinking" in payload
        assert payload["thinking"] == {"type": "disabled"}

    async def test_groq_non_qwen_no_thinking_param(self):
        """Non-qwen models (Llama 4) don't get thinking param in payload."""
        provider = _groq_llama_provider()

        json_resp = {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 10},
        }
        mock_client = _mock_httpx_client(json_resp)

        with patch(
            "cic_daily_report.adapters.llm_adapter.httpx.AsyncClient",
            return_value=mock_client,
        ):
            await _call_groq(provider, "prompt", 1024, 0.7, "")

        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert "thinking" not in payload

    async def test_cerebras_qwen_disables_thinking(self):
        """Cerebras also uses qwen model — should also disable thinking."""
        provider = _cerebras_provider()

        json_resp = {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 10},
        }
        mock_client = _mock_httpx_client(json_resp)

        with patch(
            "cic_daily_report.adapters.llm_adapter.httpx.AsyncClient",
            return_value=mock_client,
        ):
            await _call_groq(provider, "prompt", 1024, 0.7, "")

        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert "thinking" in payload
        assert payload["thinking"] == {"type": "disabled"}


class TestGenerateStripsThinkTags:
    async def test_generate_strips_think_tags(self):
        """End-to-end: generate() returns clean text with think tags stripped."""
        provider = _groq_qwen_provider()
        adapter = LLMAdapter(providers=[provider])

        raw_text = "<think>internal reasoning</think>BTC analysis: price up 5%."
        groq_resp = LLMResponse(
            text=raw_text, tokens_used=50, model="qwen/qwen3-32b", finish_reason="stop"
        )
        with patch(
            "cic_daily_report.adapters.llm_adapter._call_groq",
            new_callable=AsyncMock,
            return_value=groq_resp,
        ):
            resp = await adapter.generate("test prompt")

        assert "<think>" not in resp.text
        assert resp.text == "BTC analysis: price up 5%."


# ===========================================================================
# P1.24 — Finish reason parsing & sentence truncation
# ===========================================================================


class TestFinishReasonParsed:
    async def test_finish_reason_parsed_groq(self):
        """LLMResponse has correct finish_reason from Groq response."""
        provider = _groq_qwen_provider()

        json_resp = {
            "choices": [{"message": {"content": "hello"}, "finish_reason": "length"}],
            "usage": {"total_tokens": 42},
        }
        mock_client = _mock_httpx_client(json_resp)

        with patch(
            "cic_daily_report.adapters.llm_adapter.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await _call_groq(provider, "prompt", 1024, 0.7, "")

        assert result.finish_reason == "length"

    async def test_finish_reason_parsed_gemini(self):
        """LLMResponse has correct finish_reason from Gemini (mapped to normalized)."""
        provider = _gemini_provider()

        json_resp = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "gemini text"}]},
                    "finishReason": "MAX_TOKENS",
                }
            ],
            "usageMetadata": {"totalTokenCount": 30},
        }
        mock_client = _mock_httpx_client(json_resp)

        with patch(
            "cic_daily_report.adapters.llm_adapter.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await _call_gemini(provider, "prompt", 1024, 0.7, "")

        # MAX_TOKENS mapped to "length"
        assert result.finish_reason == "length"

    async def test_finish_reason_gemini_stop(self):
        """Gemini STOP maps to 'stop'."""
        provider = _gemini_provider()

        json_resp = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "done"}]},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {"totalTokenCount": 10},
        }
        mock_client = _mock_httpx_client(json_resp)

        with patch(
            "cic_daily_report.adapters.llm_adapter.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await _call_gemini(provider, "prompt", 1024, 0.7, "")

        assert result.finish_reason == "stop"


class TestTruncateToCompleteSentence:
    def test_truncate_to_complete_sentence_basic(self):
        """Truncates at last period before incomplete fragment."""
        text = "First sentence. Second sentence. Incomplete frag"
        result = _truncate_to_complete_sentence(text)
        assert result == "First sentence. Second sentence."

    def test_truncate_to_complete_sentence_question_mark(self):
        """Truncates at question mark boundary."""
        text = "Is BTC going up? Probably because of ETF infl"
        result = _truncate_to_complete_sentence(text)
        assert result == "Is BTC going up?"

    def test_truncate_to_complete_sentence_exclamation(self):
        """Truncates at exclamation mark boundary."""
        text = "BTC hit $100K! The market is cele"
        result = _truncate_to_complete_sentence(text)
        assert result == "BTC hit $100K!"

    def test_truncate_to_complete_sentence_no_boundary(self):
        """Returns text as-is if no sentence boundary found."""
        text = "no punctuation here just words"
        result = _truncate_to_complete_sentence(text)
        assert result == "no punctuation here just words"

    def test_truncate_to_complete_sentence_multiple_sentences(self):
        """Keeps all complete sentences, drops only the incomplete tail."""
        text = "Sentence one. Sentence two. Sentence three. Incompl"
        result = _truncate_to_complete_sentence(text)
        assert result == "Sentence one. Sentence two. Sentence three."

    def test_truncate_preserves_newline_boundary(self):
        """Sentence ending at newline is also a valid boundary."""
        text = "First line.\nSecond line.\nIncomplete thi"
        result = _truncate_to_complete_sentence(text)
        assert result == "First line.\nSecond line."

    def test_truncate_sentence_at_end_of_string(self):
        """Text ending with punctuation at EOF is already complete."""
        text = "This is complete."
        result = _truncate_to_complete_sentence(text)
        assert result == "This is complete."


class TestGenerateTruncation:
    async def test_generate_truncates_on_length(self):
        """generate() auto-truncates when finish_reason=length."""
        provider = _groq_qwen_provider()
        adapter = LLMAdapter(providers=[provider])

        truncated_text = "Complete sentence. Incomplete frag"
        groq_resp = LLMResponse(
            text=truncated_text,
            tokens_used=100,
            model="qwen/qwen3-32b",
            finish_reason="length",
        )
        with patch(
            "cic_daily_report.adapters.llm_adapter._call_groq",
            new_callable=AsyncMock,
            return_value=groq_resp,
        ):
            resp = await adapter.generate("test prompt")

        assert resp.text == "Complete sentence."

    async def test_generate_no_truncation_on_stop(self):
        """generate() doesn't truncate when finish_reason=stop."""
        provider = _groq_qwen_provider()
        adapter = LLMAdapter(providers=[provider])

        full_text = "Complete sentence. Another sentence."
        groq_resp = LLMResponse(
            text=full_text,
            tokens_used=50,
            model="qwen/qwen3-32b",
            finish_reason="stop",
        )
        with patch(
            "cic_daily_report.adapters.llm_adapter._call_groq",
            new_callable=AsyncMock,
            return_value=groq_resp,
        ):
            resp = await adapter.generate("test prompt")

        assert resp.text == "Complete sentence. Another sentence."

    async def test_truncation_logs_warning(self):
        """Verify warning is logged when truncation happens."""
        provider = _groq_qwen_provider()
        adapter = LLMAdapter(providers=[provider])

        truncated_text = "Good sentence. Bad frag"
        groq_resp = LLMResponse(
            text=truncated_text,
            tokens_used=80,
            model="qwen/qwen3-32b",
            finish_reason="length",
        )
        with (
            patch(
                "cic_daily_report.adapters.llm_adapter._call_groq",
                new_callable=AsyncMock,
                return_value=groq_resp,
            ),
            patch(
                "cic_daily_report.adapters.llm_adapter.logger.warning",
            ) as mock_warn,
        ):
            await adapter.generate("test prompt")

        # WHY: logger.propagate=False, so caplog can't capture. Mock directly.
        mock_warn.assert_called_once()
        assert "finish_reason=length" in mock_warn.call_args[0][0]


class TestThinkTagsBeforeTruncation:
    async def test_think_tags_stripped_before_truncation(self):
        """P1.23 runs before P1.24: think tags stripped, THEN truncation applied.

        WHY: If think tags are not stripped first, the sentence boundary detection
        could be affected by text inside <think> blocks.
        """
        provider = _groq_qwen_provider()
        adapter = LLMAdapter(providers=[provider])

        # Think tags + truncated text
        raw_text = (
            "<think>I need to analyze the market trends carefully.</think>"
            "Bitcoin is strong. The market shows incompl"
        )
        groq_resp = LLMResponse(
            text=raw_text,
            tokens_used=100,
            model="qwen/qwen3-32b",
            finish_reason="length",
        )
        with patch(
            "cic_daily_report.adapters.llm_adapter._call_groq",
            new_callable=AsyncMock,
            return_value=groq_resp,
        ):
            resp = await adapter.generate("test prompt")

        # Think tags stripped AND text truncated to last complete sentence
        assert "<think>" not in resp.text
        assert resp.text == "Bitcoin is strong."
