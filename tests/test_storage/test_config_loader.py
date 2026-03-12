"""Tests for storage/config_loader.py — all mocked."""

from unittest.mock import MagicMock

import pytest

from cic_daily_report.storage.config_loader import ConfigLoader


def _coin_row(symbol, name, tier, enabled="TRUE"):
    return {
        "Mã coin": symbol,
        "Tên đầy đủ": name,
        "Cấp tier": tier,
        "Bật/Tắt": enabled,
        "Ghi chú": "",
    }


@pytest.fixture
def mock_sheets():
    return MagicMock()


@pytest.fixture
def loader(mock_sheets):
    return ConfigLoader(mock_sheets)


class TestGetSettings:
    def test_reads_cau_hinh(self, loader, mock_sheets):
        mock_sheets.read_all.return_value = [
            {"Khóa": "retention_raw_days", "Giá trị": "60", "Mô tả": ""},
            {"Khóa": "email_list", "Giá trị": "a@b.com", "Mô tả": ""},
        ]
        settings = loader.get_settings()
        assert settings["retention_raw_days"] == "60"
        assert settings["email_list"] == "a@b.com"

    def test_caches_settings(self, loader, mock_sheets):
        mock_sheets.read_all.return_value = [{"Khóa": "k", "Giá trị": "v", "Mô tả": ""}]
        loader.get_settings()
        loader.get_settings()
        mock_sheets.read_all.assert_called_once()

    def test_reload_clears_cache(self, loader, mock_sheets):
        mock_sheets.read_all.return_value = [{"Khóa": "k", "Giá trị": "v", "Mô tả": ""}]
        loader.get_settings()
        loader.reload()
        loader.get_settings()
        assert mock_sheets.read_all.call_count == 2

    def test_get_setting_with_default(self, loader, mock_sheets):
        mock_sheets.read_all.return_value = []
        val = loader.get_setting("nonexistent", "fallback")
        assert val == "fallback"

    def test_get_setting_int(self, loader, mock_sheets):
        mock_sheets.read_all.return_value = [
            {"Khóa": "retention_raw_days", "Giá trị": "60", "Mô tả": ""}
        ]
        val = loader.get_setting_int("retention_raw_days", 90)
        assert val == 60

    def test_get_setting_int_invalid(self, loader, mock_sheets):
        mock_sheets.read_all.return_value = [
            {"Khóa": "bad", "Giá trị": "not_a_number", "Mô tả": ""}
        ]
        val = loader.get_setting_int("bad", 42)
        assert val == 42


class TestGetEmailRecipients:
    def test_reads_from_cau_hinh(self, loader, mock_sheets):
        mock_sheets.read_all.return_value = [
            {"Khóa": "email_recipients", "Giá trị": "a@b.com, c@d.com", "Mô tả": ""},
        ]
        result = loader.get_email_recipients()
        assert result == ["a@b.com", "c@d.com"]

    def test_falls_back_to_env_var(self, loader, mock_sheets, monkeypatch):
        mock_sheets.read_all.return_value = []
        monkeypatch.setenv("SMTP_RECIPIENTS", "x@y.com,z@w.com")
        result = loader.get_email_recipients()
        assert result == ["x@y.com", "z@w.com"]

    def test_returns_empty_when_neither_set(self, loader, mock_sheets, monkeypatch):
        mock_sheets.read_all.return_value = []
        monkeypatch.delenv("SMTP_RECIPIENTS", raising=False)
        result = loader.get_email_recipients()
        assert result == []

    def test_sheet_overrides_env_var(self, loader, mock_sheets, monkeypatch):
        mock_sheets.read_all.return_value = [
            {"Khóa": "email_recipients", "Giá trị": "sheet@b.com", "Mô tả": ""},
        ]
        monkeypatch.setenv("SMTP_RECIPIENTS", "env@b.com")
        result = loader.get_email_recipients()
        assert result == ["sheet@b.com"]


class TestSetEmailRecipients:
    def test_calls_upsert_setting(self, loader, mock_sheets):
        loader.set_email_recipients(["a@b.com", "c@d.com"])
        mock_sheets.upsert_setting.assert_called_once()
        call_args = mock_sheets.upsert_setting.call_args[0]
        assert call_args[0] == "email_recipients"
        assert "a@b.com" in call_args[1]
        assert "c@d.com" in call_args[1]

    def test_invalidates_cache_after_set(self, loader, mock_sheets):
        mock_sheets.read_all.return_value = [
            {"Khóa": "email_recipients", "Giá trị": "old@b.com", "Mô tả": ""},
        ]
        loader.get_settings()  # populate cache
        assert loader._config_cache is not None

        loader.set_email_recipients(["new@b.com"])
        assert loader._config_cache is None  # cache cleared

    def test_empty_list_saves_empty_string(self, loader, mock_sheets):
        loader.set_email_recipients([])
        call_args = mock_sheets.upsert_setting.call_args[0]
        assert call_args[1] == ""  # empty join


class TestGetTemplates:
    def test_reads_mau_bai_viet(self, loader, mock_sheets):
        mock_sheets.read_all.return_value = [
            {
                "Cấp tier": "L1",
                "Tên phần": "Market Overview",
                "Bật/Tắt": "TRUE",
                "Thứ tự": 1,
                "Prompt mẫu": "Analyze market...",
                "Số từ tối đa": 300,
            }
        ]
        templates = loader.get_templates()
        assert len(templates) == 1
        assert templates[0]["tier"] == "L1"
        assert templates[0]["enabled"] is True
        assert templates[0]["max_words"] == 300


class TestGetCoinList:
    def test_cumulative_tiers(self, loader, mock_sheets):
        mock_sheets.read_all.return_value = [
            _coin_row("BTC", "Bitcoin", "L1"),
            _coin_row("ETH", "Ethereum", "L1"),
            _coin_row("SOL", "Solana", "L2"),
        ]
        coins = loader.get_coin_list()
        assert coins["L1"] == ["BTC", "ETH"]
        assert coins["L2"] == ["BTC", "ETH", "SOL"]  # cumulative
        assert coins["L3"] == ["BTC", "ETH", "SOL"]  # nothing added

    def test_disabled_coins_excluded(self, loader, mock_sheets):
        mock_sheets.read_all.return_value = [
            _coin_row("BTC", "Bitcoin", "L1"),
            _coin_row("SHIB", "Shiba", "L1", "FALSE"),
        ]
        coins = loader.get_coin_list()
        assert "BTC" in coins["L1"]
        assert "SHIB" not in coins["L1"]

    def test_filter_by_tier(self, loader, mock_sheets):
        mock_sheets.read_all.return_value = [
            _coin_row("BTC", "Bitcoin", "L1"),
        ]
        coins = loader.get_coin_list(tier="L1")
        assert "L1" in coins
