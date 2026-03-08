"""Tests for core/error_handler.py."""

import pytest

from cic_daily_report.core.error_handler import (
    CICError,
    CollectorError,
    ConfigError,
    DeliveryError,
    LLMError,
    QuotaExceededError,
    StorageError,
)


class TestCICError:
    def test_basic_attributes(self):
        err = CICError(
            code="COLLECTOR_TIMEOUT",
            message="RSS feed timeout",
            source="rss_collector",
            retry=True,
        )
        assert err.code == "COLLECTOR_TIMEOUT"
        assert err.message == "RSS feed timeout"
        assert err.source == "rss_collector"
        assert err.retry is True

    def test_string_representation(self):
        err = CICError(code="TEST", message="test msg")
        assert "[TEST] test msg" in str(err)

    def test_repr(self):
        err = CICError(code="TEST", message="msg", source="src", retry=True)
        assert "CICError" in repr(err)
        assert "TEST" in repr(err)

    def test_is_exception(self):
        err = CICError(code="X", message="y")
        assert isinstance(err, Exception)

    def test_defaults(self):
        err = CICError(code="X", message="y")
        assert err.source == ""
        assert err.retry is False


class TestSubclasses:
    @pytest.mark.parametrize(
        "cls,expected_code,default_retry",
        [
            (CollectorError, "COLLECTOR_ERROR", True),
            (LLMError, "LLM_ERROR", True),
            (DeliveryError, "DELIVERY_ERROR", True),
            (StorageError, "STORAGE_ERROR", True),
            (ConfigError, "CONFIG_ERROR", False),
            (QuotaExceededError, "QUOTA_EXCEEDED", False),
        ],
    )
    def test_subclass_code_and_retry(self, cls, expected_code, default_retry):
        err = cls(message="test")
        assert err.code == expected_code
        assert err.retry is default_retry
        assert isinstance(err, CICError)

    def test_collector_error_with_source(self):
        err = CollectorError(message="timeout", source="rss_collector")
        assert err.source == "rss_collector"
        assert err.retry is True
