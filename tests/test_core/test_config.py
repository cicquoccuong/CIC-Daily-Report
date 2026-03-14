"""Tests for core/config.py."""

import importlib
import os


class TestConfig:
    def test_is_production_false_by_default(self):
        # Ensure GITHUB_ACTIONS is not set
        env_backup = os.environ.pop("GITHUB_ACTIONS", None)
        try:
            import cic_daily_report.core.config as cfg

            importlib.reload(cfg)
            assert cfg.IS_PRODUCTION is False
        finally:
            if env_backup is not None:
                os.environ["GITHUB_ACTIONS"] = env_backup

    def test_is_production_true_on_github_actions(self):
        os.environ["GITHUB_ACTIONS"] = "true"
        try:
            import cic_daily_report.core.config as cfg

            importlib.reload(cfg)
            assert cfg.IS_PRODUCTION is True
        finally:
            os.environ.pop("GITHUB_ACTIONS", None)

    def test_version_exists(self):
        from cic_daily_report.core.config import VERSION

        assert VERSION == "0.19.0"
