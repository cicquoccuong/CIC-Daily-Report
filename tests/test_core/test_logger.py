"""Tests for core/logger.py."""

import logging

from cic_daily_report.core.logger import get_logger


class TestLogger:
    def test_returns_logger(self):
        logger = get_logger("test_module")
        assert isinstance(logger, logging.Logger)

    def test_logger_name_prefixed(self):
        logger = get_logger("news_collector")
        assert logger.name == "cic.news_collector"

    def test_has_handler(self):
        logger = get_logger("handler_test")
        assert len(logger.handlers) >= 1

    def test_format_output(self, capfd):
        logger = get_logger("fmt_test")
        logger.info("hello world")
        captured = capfd.readouterr()
        assert "[INFO]" in captured.out
        assert "[cic.fmt_test]" in captured.out
        assert "hello world" in captured.out

    def test_all_levels(self, capfd):
        logger = get_logger("level_test")
        for level in ["debug", "info", "warning", "error", "critical"]:
            getattr(logger, level)(f"{level} message")
        captured = capfd.readouterr()
        assert "[DEBUG]" in captured.out
        assert "[INFO]" in captured.out
        assert "[WARNING]" in captured.out
        assert "[ERROR]" in captured.out
        assert "[CRITICAL]" in captured.out

    def test_no_duplicate_handlers(self):
        logger1 = get_logger("dup_test")
        logger2 = get_logger("dup_test")
        assert logger1 is logger2
        assert len(logger1.handlers) == 1
