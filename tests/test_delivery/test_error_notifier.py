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
