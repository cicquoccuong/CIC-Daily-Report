"""Tests for generators/text_utils.py — truncate_to_limit function."""

from cic_daily_report.generators.text_utils import truncate_to_limit


class TestTruncateNoTruncationNeeded:
    def test_text_under_limit_returns_unchanged(self):
        text = "Short text that fits."
        result, was_truncated = truncate_to_limit(text, 100)
        assert result == text
        assert was_truncated is False


class TestTruncateParagraphBoundary:
    def test_cuts_at_last_paragraph_break(self):
        text = "First paragraph here.\n\nSecond paragraph here.\n\nThird paragraph is long."
        # Limit should cut before third paragraph
        limit = len("First paragraph here.\n\nSecond paragraph here.") + 5
        result, was_truncated = truncate_to_limit(text, limit)
        assert was_truncated is True
        assert result == "First paragraph here.\n\nSecond paragraph here."
        assert len(result) <= limit

    def test_prefers_paragraph_over_sentence(self):
        """When both paragraph and sentence boundaries exist, paragraph wins."""
        text = "Sentence one. Sentence two.\n\nParagraph two. More text here that goes on."
        limit = len("Sentence one. Sentence two.\n\nParagraph two.") + 3
        result, was_truncated = truncate_to_limit(text, limit)
        assert was_truncated is True
        # Should cut at \n\n, not at `. `
        assert result == "Sentence one. Sentence two."


class TestTruncateSentenceBoundary:
    def test_cuts_at_sentence_when_no_paragraph_boundary(self):
        """No \\n\\n in text → falls back to sentence boundary."""
        text = "First sentence here. Second sentence here. Third sentence is very long."
        limit = len("First sentence here. Second sentence here.") + 3
        result, was_truncated = truncate_to_limit(text, limit)
        assert was_truncated is True
        assert result == "First sentence here. Second sentence here."
        assert len(result) <= limit

    def test_cuts_at_dot_newline(self):
        """Sentence ending with .\\n (not \\n\\n) is a valid boundary."""
        text = "Line one.\nLine two.\nLine three is very long and exceeds."
        limit = len("Line one.\nLine two.") + 3
        result, was_truncated = truncate_to_limit(text, limit)
        assert was_truncated is True
        assert result.endswith(".")
        assert len(result) <= limit


class TestTruncateHardCut:
    def test_hard_cuts_when_no_boundary(self):
        """No paragraph or sentence boundary → hard cut at max_chars."""
        text = "a" * 200  # No periods, no newlines
        result, was_truncated = truncate_to_limit(text, 100)
        assert was_truncated is True
        assert len(result) == 100

    def test_hard_cut_single_long_word(self):
        text = "x" * 500
        result, was_truncated = truncate_to_limit(text, 50)
        assert was_truncated is True
        assert len(result) == 50


class TestTruncatePreservesSentenceMode:
    def test_sentence_mode_skips_paragraph_search(self):
        """preserve='sentence' goes straight to sentence boundary."""
        text = "Before para.\n\nAfter para. More words that push past limit."
        # With paragraph mode, would cut at \n\n
        # With sentence mode, should cut at last `. ` before limit
        limit = len(text) - 5
        result_para, _ = truncate_to_limit(text, limit, preserve="paragraph")
        result_sent, _ = truncate_to_limit(text, limit, preserve="sentence")
        # Paragraph mode cuts at \n\n (shorter)
        assert result_para == "Before para."
        # Sentence mode finds last `. ` before limit (longer, past the \n\n)
        assert "After para." in result_sent


class TestTruncateEmptyText:
    def test_empty_string_returns_unchanged(self):
        result, was_truncated = truncate_to_limit("", 100)
        assert result == ""
        assert was_truncated is False


class TestTruncateExactLimit:
    def test_text_exactly_at_limit_returns_unchanged(self):
        text = "Exact length."
        result, was_truncated = truncate_to_limit(text, len(text))
        assert result == text
        assert was_truncated is False


class TestTruncateExclamationBoundary:
    def test_truncate_at_exclamation_space(self):
        """Exclamation mark followed by space is a valid sentence boundary."""
        text = "Breaking news! BTC surged past resistance. More text here that overflows."
        limit = len("Breaking news! BTC surged past resistance.") + 5
        result, was_truncated = truncate_to_limit(text, limit, preserve="sentence")
        assert was_truncated is True
        assert result == "Breaking news! BTC surged past resistance."

    def test_truncate_at_exclamation_newline(self):
        """Exclamation mark followed by newline is a valid sentence boundary."""
        text = "Amazing!\nNext line. More overflow text here."
        limit = len("Amazing!\nNext line.") + 3
        result, was_truncated = truncate_to_limit(text, limit, preserve="sentence")
        assert was_truncated is True
        assert result.endswith(".")
        assert len(result) <= limit


class TestTruncateQuestionBoundary:
    def test_truncate_at_question_space(self):
        """Question mark followed by space is a valid sentence boundary."""
        text = "Is BTC bullish? Analysts say yes. Extra overflow content here."
        limit = len("Is BTC bullish? Analysts say yes.") + 5
        result, was_truncated = truncate_to_limit(text, limit, preserve="sentence")
        assert was_truncated is True
        assert result == "Is BTC bullish? Analysts say yes."

    def test_truncate_at_question_newline(self):
        """Question mark followed by newline is a valid sentence boundary."""
        text = "Will ETH flip?\nSome say soon. More overflow content."
        limit = len("Will ETH flip?\nSome say soon.") + 3
        result, was_truncated = truncate_to_limit(text, limit, preserve="sentence")
        assert was_truncated is True
        assert result.endswith(".")
        assert len(result) <= limit

    def test_question_preferred_over_earlier_period(self):
        """If `? ` is later than `. `, the question mark is the boundary."""
        text = "First. Is this right? Overflow here."
        # Limit just past the question mark
        limit = len("First. Is this right?") + 3
        result, was_truncated = truncate_to_limit(text, limit, preserve="sentence")
        assert was_truncated is True
        assert result == "First. Is this right?"


class TestTruncateStripsTrailingWhitespace:
    def test_no_trailing_spaces_after_truncation(self):
        """Truncation should strip trailing whitespace."""
        text = "First paragraph.   \n\nSecond paragraph with trailing spaces.   "
        limit = len("First paragraph.   \n\n") + 5
        result, was_truncated = truncate_to_limit(text, limit)
        assert was_truncated is True
        assert not result.endswith(" ")
        assert not result.endswith("\n")

    def test_hard_cut_strips_trailing_whitespace(self):
        text = "word " * 100  # Lots of trailing spaces at cut points
        result, was_truncated = truncate_to_limit(text, 50)
        assert was_truncated is True
        assert not result.endswith(" ")
