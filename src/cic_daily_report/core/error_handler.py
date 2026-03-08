"""Centralized error handling (QĐ3) — CICError hierarchy."""

from __future__ import annotations


class CICError(Exception):
    """Base error for all CIC Daily Report errors."""

    def __init__(
        self,
        code: str,
        message: str,
        source: str = "",
        retry: bool = False,
    ) -> None:
        self.code = code
        self.message = message
        self.source = source
        self.retry = retry
        super().__init__(f"[{code}] {message}")

    def __repr__(self) -> str:
        return f"CICError(code={self.code!r}, source={self.source!r}, retry={self.retry})"


class CollectorError(CICError):
    """Error during data collection."""

    def __init__(self, message: str, source: str = "", retry: bool = True) -> None:
        super().__init__(code="COLLECTOR_ERROR", message=message, source=source, retry=retry)


class LLMError(CICError):
    """Error during LLM generation."""

    def __init__(self, message: str, source: str = "", retry: bool = True) -> None:
        super().__init__(code="LLM_ERROR", message=message, source=source, retry=retry)


class DeliveryError(CICError):
    """Error during content delivery."""

    def __init__(self, message: str, source: str = "", retry: bool = True) -> None:
        super().__init__(code="DELIVERY_ERROR", message=message, source=source, retry=retry)


class StorageError(CICError):
    """Error during Google Sheets operations."""

    def __init__(self, message: str, source: str = "", retry: bool = True) -> None:
        super().__init__(code="STORAGE_ERROR", message=message, source=source, retry=retry)


class ConfigError(CICError):
    """Error in configuration loading."""

    def __init__(self, message: str, source: str = "", retry: bool = False) -> None:
        super().__init__(code="CONFIG_ERROR", message=message, source=source, retry=retry)


class QuotaExceededError(CICError):
    """API quota exceeded."""

    def __init__(self, message: str, source: str = "", retry: bool = False) -> None:
        super().__init__(code="QUOTA_EXCEEDED", message=message, source=source, retry=retry)
