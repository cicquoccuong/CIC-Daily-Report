"""Tests for delivery/error_notifier.py."""

from cic_daily_report.core.error_handler import (
    CICError,
    CollectorError,
    DeliveryError,
    LLMError,
)
from cic_daily_report.delivery.error_notifier import (
    ErrorNotification,
    build_notification,
)


class TestErrorNotification:
    def test_empty_no_message(self):
        n = ErrorNotification()
        assert n.format_message() == ""

    def test_single_error_format(self):
        n = ErrorNotification(
            errors=[
                LLMError("Groq API timeout", source="llm_adapter"),
            ]
        )
        msg = n.format_message()
        assert "Tạo nội dung" in msg
        assert "Groq API timeout" in msg
        assert "llm_adapter" in msg

    def test_critical_uses_red(self):
        n = ErrorNotification(
            errors=[
                CICError(code="QUOTA_EXCEEDED", message="Over limit", retry=False),
            ]
        )
        assert n.is_critical
        assert n.severity_emoji == "🔴"

    def test_recoverable_uses_warning(self):
        n = ErrorNotification(
            errors=[
                CollectorError("RSS timeout", source="rss"),
            ]
        )
        assert not n.is_critical
        assert n.severity_emoji == "⚠️"

    def test_multiple_errors_grouped(self):
        n = ErrorNotification(
            errors=[
                CollectorError("RSS fail"),
                LLMError("Groq down"),
                DeliveryError("TG rate limit"),
            ]
        )
        msg = n.format_message()
        assert "Tổng: 3 lỗi" in msg
        assert "Thu thập dữ liệu" in msg
        assert "Tạo nội dung" in msg
        assert "Gửi bài" in msg

    def test_action_suggestions_present(self):
        n = ErrorNotification(
            errors=[
                LLMError("API key invalid", source="llm"),
            ]
        )
        msg = n.format_message()
        assert "GROQ_API_KEY" in msg or "Kiểm tra" in msg


class TestBuildNotification:
    def test_wraps_non_cic_errors(self):
        errors = [ValueError("bad value"), LLMError("llm fail")]
        n = build_notification(errors)
        assert len(n.errors) == 2
        assert n.errors[0].code == "UNKNOWN_ERROR"
        assert n.errors[1].code == "LLM_ERROR"

    def test_empty_errors(self):
        n = build_notification([])
        assert len(n.errors) == 0


class TestSanitizeError:
    from cic_daily_report.delivery.error_notifier import _sanitize_error

    def test_url_query_param_key_redacted(self):
        from cic_daily_report.delivery.error_notifier import _sanitize_error

        msg = "Request failed: https://example.com/api?key=AIzaSyABC123"
        result = _sanitize_error(msg)
        assert "AIzaSyABC123" not in result
        assert "***REDACTED***" in result
        assert "https://example.com/api" in result

    def test_url_ampersand_api_key_redacted(self):
        from cic_daily_report.delivery.error_notifier import _sanitize_error

        msg = "Error calling https://api.example.com/data?page=1&api_key=supersecretvalue"
        result = _sanitize_error(msg)
        assert "supersecretvalue" not in result
        assert "***REDACTED***" in result
        assert "page=1" in result

    def test_google_api_key_in_text_redacted(self):
        from cic_daily_report.delivery.error_notifier import _sanitize_error

        # Google API key: AIzaSy + exactly 33 alphanumeric/dash/underscore chars
        google_key = "AIzaSy" + "A" * 33
        msg = f"Invalid credentials: {google_key} is not authorized"
        result = _sanitize_error(msg)
        assert google_key not in result
        assert "***REDACTED***" in result
        assert "Invalid credentials" in result
        assert "is not authorized" in result

    def test_groq_key_redacted(self):
        from cic_daily_report.delivery.error_notifier import _sanitize_error

        # Groq key: gsk_ + 48 alphanumeric chars
        groq_key = "gsk_" + "x" * 48
        msg = f"Groq API error with key {groq_key}: rate limit exceeded"
        result = _sanitize_error(msg)
        assert groq_key not in result
        assert "***REDACTED***" in result
        assert "rate limit exceeded" in result

    def test_message_without_keys_unchanged(self):
        from cic_daily_report.delivery.error_notifier import _sanitize_error

        msg = "Connection timed out after 30 seconds"
        result = _sanitize_error(msg)
        assert result == msg

    def test_multiple_keys_all_redacted(self):
        from cic_daily_report.delivery.error_notifier import _sanitize_error

        google_key = "AIzaSy" + "B" * 33
        groq_key = "gsk_" + "y" * 48
        openai_key = "sk-" + "z" * 32
        msg = f"Auth failed: google={google_key}, groq={groq_key}, openai={openai_key}"
        result = _sanitize_error(msg)
        assert google_key not in result
        assert groq_key not in result
        assert openai_key not in result
        assert result.count("***REDACTED***") == 3
