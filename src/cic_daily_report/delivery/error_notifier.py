"""Error notification system — actionable Vietnamese messages (FR33, NFR10).

Maps CICError codes to Vietnamese action suggestions.
Groups multiple errors into a single notification.
Sanitizes error messages to prevent API key leakage (v0.28.0).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from cic_daily_report.core.error_handler import CICError
from cic_daily_report.core.logger import get_logger

logger = get_logger("error_notifier")

# Regex patterns to strip API keys/tokens from error messages.
# Matches: key=..., api_key=..., token=..., apikey=... in URLs or text.
_URL_KEY_RE = re.compile(
    r"([\?&](?:key|api_key|apikey|token|access_token|secret)=)"
    r"[^&\s\"']+",
    re.IGNORECASE,
)
_API_KEY_PATTERNS = [
    _URL_KEY_RE,
    re.compile(r"(AIzaSy[A-Za-z0-9_-]{33})"),  # Google API key
    re.compile(r"(gsk_[A-Za-z0-9]{48,})"),  # Groq API key
    re.compile(r"(sk-[A-Za-z0-9]{32,})"),  # OpenAI-style key
]


def _sanitize_error(message: str) -> str:
    """Strip API keys/tokens from error messages.

    httpx exceptions include full URLs with query params (API keys).
    Redacts known key patterns before sending to users.
    """
    sanitized = message
    for pattern in _API_KEY_PATTERNS:
        sanitized = pattern.sub("***REDACTED***", sanitized)
    return sanitized


# Error code → Vietnamese action suggestion mapping
ERROR_ACTION_MAP: dict[str, str] = {
    "COLLECTOR_ERROR": "Kiểm tra kết nối internet và trạng thái API nguồn dữ liệu.",
    "LLM_ERROR": (
        "Kiểm tra API key (GROQ_API_KEY / GEMINI_API_KEY) trong GitHub → Settings → Secrets."
    ),
    "DELIVERY_ERROR": "Kiểm tra TELEGRAM_BOT_TOKEN và TELEGRAM_CHAT_ID trong GitHub Secrets.",
    "STORAGE_ERROR": "Kiểm tra Google Service Account credentials và quyền truy cập Sheets.",
    "CONFIG_ERROR": "Kiểm tra các tab CAU_HINH, MAU_BAI_VIET, DANH_SACH_COIN trên Google Sheets.",
    "QUOTA_EXCEEDED": (
        "API đã hết quota. Chờ reset (thường 24h) hoặc kiểm tra usage trên dashboard."
    ),
    "TG_CONFIG_MISSING": "Thiếu TELEGRAM_BOT_TOKEN hoặc TELEGRAM_CHAT_ID trong GitHub Secrets.",
    "GROQ_API_ERROR": "Kiểm tra GROQ_API_KEY trong GitHub → Settings → Secrets → Actions.",
    "SMTP_ERROR": "Kiểm tra SMTP_SERVER, SMTP_EMAIL, SMTP_PASSWORD trong GitHub Secrets.",
    "PIPELINE_TIMEOUT": "Pipeline chạy quá 40 phút. Kiểm tra log để tìm bước bị chậm.",
}

# Error type labels in Vietnamese
ERROR_TYPE_MAP: dict[str, str] = {
    "COLLECTOR_ERROR": "Thu thập dữ liệu",
    "LLM_ERROR": "Tạo nội dung (AI)",
    "DELIVERY_ERROR": "Gửi bài",
    "STORAGE_ERROR": "Lưu trữ (Google Sheets)",
    "CONFIG_ERROR": "Cấu hình hệ thống",
    "QUOTA_EXCEEDED": "Hết quota API",
    "PIPELINE_TIMEOUT": "Pipeline timeout",
}


@dataclass
class ErrorNotification:
    """A grouped error notification ready for delivery."""

    errors: list[CICError] = field(default_factory=list)
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    @property
    def is_critical(self) -> bool:
        """True if any error is non-retryable (critical)."""
        return any(not e.retry for e in self.errors)

    @property
    def severity_emoji(self) -> str:
        return "🔴" if self.is_critical else "⚠️"

    def format_message(self) -> str:
        """Format grouped errors into a single Vietnamese notification."""
        if not self.errors:
            return ""

        prefix = self.severity_emoji
        lines = [f"{prefix} *Thông báo lỗi Pipeline* — {self.timestamp}\n"]

        for i, error in enumerate(self.errors, 1):
            error_type = ERROR_TYPE_MAP.get(error.code, error.code)
            action = ERROR_ACTION_MAP.get(error.code, "Kiểm tra log để biết thêm chi tiết.")

            lines.append(f"{i}. *{error_type}*")
            lines.append(f"   Lỗi: {error.message}")
            if error.source:
                lines.append(f"   Module: {error.source}")
            lines.append(f"   → {action}")
            lines.append("")

        lines.append(
            f"Tổng: {len(self.errors)} lỗi | Mức độ: "
            f"{'Nghiêm trọng' if self.is_critical else 'Có thể phục hồi'}"
        )
        return "\n".join(lines)


def build_notification(errors: list[Exception]) -> ErrorNotification:
    """Build a grouped ErrorNotification from a list of exceptions.

    Non-CICError exceptions are wrapped.
    """
    cic_errors: list[CICError] = []
    for e in errors:
        if isinstance(e, CICError):
            # Sanitize the message in-place to prevent API key leakage
            e.message = _sanitize_error(e.message)
            cic_errors.append(e)
        else:
            cic_errors.append(
                CICError(
                    code="UNKNOWN_ERROR",
                    message=_sanitize_error(str(e)),
                    source="unknown",
                    retry=False,
                )
            )

    notification = ErrorNotification(errors=cic_errors)
    logger.info(
        f"Error notification built: {len(cic_errors)} errors, "
        f"severity={'critical' if notification.is_critical else 'warning'}"
    )
    return notification
