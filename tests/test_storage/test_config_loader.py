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
