"""Configuration loader — reads config from Google Sheets (hot-reload, QĐ8)."""

from __future__ import annotations

import os
from typing import Any

from cic_daily_report.core.error_handler import ConfigError
from cic_daily_report.core.logger import get_logger
from cic_daily_report.storage.sheets_client import SheetsClient

logger = get_logger("config_loader")

# Default config values (used when Sheets key is missing)
DEFAULTS = {
    "retention_raw_days": 90,
    "retention_generated_days": 30,
    "max_rows_per_tab": 5000,
    "breaking_panic_threshold": 70,
    "breaking_night_start_hour": 23,
    "breaking_night_end_hour": 7,
    "email_backup_enabled": True,
}


class ConfigLoader:
    """Loads configuration from Google Sheets tabs (hot-reload per run)."""

    def __init__(self, sheets_client: SheetsClient) -> None:
        self._sheets = sheets_client
        self._config_cache: dict[str, str] | None = None
        self._templates_cache: list[dict[str, Any]] | None = None
        self._coins_cache: dict[str, list[str]] | None = None

    def reload(self) -> None:
        """Clear cache — forces fresh read from Sheets on next access."""
        self._config_cache = None
        self._templates_cache = None
        self._coins_cache = None
        logger.info("Config cache cleared — will reload from Sheets on next access")

    def get_settings(self) -> dict[str, str]:
        """Read CAU_HINH tab → dict of key-value settings."""
        if self._config_cache is not None:
            return self._config_cache

        try:
            rows = self._sheets.read_all("CAU_HINH")
            self._config_cache = {}
            for row in rows:
                key = str(row.get("Khóa", "")).strip()
                value = str(row.get("Giá trị", "")).strip()
                if key:
                    self._config_cache[key] = value
            logger.info(f"Loaded {len(self._config_cache)} settings from CAU_HINH")
            return self._config_cache
        except Exception as e:
            raise ConfigError(f"Failed to load CAU_HINH: {e}", source="config_loader") from e

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a single setting value with optional default."""
        settings = self.get_settings()
        value = settings.get(key)
        if value is None or value == "":
            fallback = DEFAULTS.get(key, default)
            return fallback
        return value

    def get_setting_bool(self, key: str, default: bool = False) -> bool:
        """Get a setting as boolean.

        Handles Sheets string values like "TRUE", "FALSE", "1", "0", "BẬT", "TẮT".
        """
        value = self.get_setting(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().upper() in ("TRUE", "1", "BẬT", "CÓ", "YES")
        return bool(value)

    def get_setting_int(self, key: str, default: int = 0) -> int:
        """Get a setting as integer."""
        value = self.get_setting(key, default)
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    def get_email_recipients(self) -> list[str]:
        """Read email_recipients from CAU_HINH. Falls back to SMTP_RECIPIENTS env var.

        CAU_HINH row: Khóa = "email_recipients", Giá trị = "a@b.com, c@d.com"
        This allows operators to update the recipient list via Google Sheets without
        changing GitHub Secrets.
        """
        sheet_value = self.get_setting("email_recipients", "")
        if sheet_value:
            return [e.strip() for e in str(sheet_value).split(",") if e.strip()]
        env_value = os.getenv("SMTP_RECIPIENTS", "")
        return [e.strip() for e in env_value.split(",") if e.strip()]

    def set_email_recipients(self, emails: list[str]) -> None:
        """Write email_recipients to CAU_HINH tab (upsert) and clear cache.

        Args:
            emails: list of email addresses to save.

        Raises:
            StorageError: if write to Sheets fails.
        """
        value = ", ".join(emails)
        description = (
            "Danh sach email nhan bao cao hang ngay. "
            "Cach nhau bang dau phay. Vi du: a@b.com, c@d.com"
        )
        self._sheets.upsert_setting("email_recipients", value, description)
        self._config_cache = None  # invalidate cache so next read reflects new value
        logger.info(f"Saved {len(emails)} email recipients to CAU_HINH")

    def get_templates(self) -> list[dict[str, Any]]:
        """Read MAU_BAI_VIET tab → list of template sections."""
        if self._templates_cache is not None:
            return self._templates_cache

        try:
            rows = self._sheets.read_all("MAU_BAI_VIET")
            self._templates_cache = []
            for row in rows:
                template = {
                    "tier": str(row.get("Cấp tier", "")).strip(),
                    "section_name": str(row.get("Tên phần", "")).strip(),
                    "enabled": str(row.get("Bật/Tắt", "")).strip().upper() in ("TRUE", "1", "BẬT"),
                    "order": int(row.get("Thứ tự", 0) or 0),
                    "prompt_template": str(row.get("Prompt mẫu", "")).strip(),
                    "max_words": int(row.get("Số từ tối đa", 500) or 500),
                }
                self._templates_cache.append(template)
            logger.info(f"Loaded {len(self._templates_cache)} templates from MAU_BAI_VIET")
            return self._templates_cache
        except Exception as e:
            raise ConfigError(f"Failed to load MAU_BAI_VIET: {e}", source="config_loader") from e

    def get_coin_list(self, tier: str | None = None) -> dict[str, list[str]]:
        """Read DANH_SACH_COIN tab → dict of tier → coin symbols.

        Cumulative logic: L2 = L1 + L2, L3 = L1 + L2 + L3, etc.
        """
        if self._coins_cache is not None:
            if tier:
                return {tier: self._coins_cache.get(tier, [])}
            return self._coins_cache

        try:
            rows = self._sheets.read_all("DANH_SACH_COIN")
            raw_tiers: dict[str, list[str]] = {}

            for row in rows:
                coin = str(row.get("Mã coin", "")).strip().upper()
                t = str(row.get("Cấp tier", "")).strip().upper()
                enabled = str(row.get("Bật/Tắt", "")).strip().upper() in (
                    "TRUE",
                    "1",
                    "BẬT",
                )
                if coin and t and enabled:
                    raw_tiers.setdefault(t, []).append(coin)

            # Build cumulative tiers
            tier_order = ["L1", "L2", "L3", "L4", "L5"]
            cumulative: dict[str, list[str]] = {}
            accumulated: list[str] = []

            for t in tier_order:
                accumulated = accumulated + raw_tiers.get(t, [])
                # Deduplicate while preserving order
                seen: set[str] = set()
                unique: list[str] = []
                for c in accumulated:
                    if c not in seen:
                        seen.add(c)
                        unique.append(c)
                cumulative[t] = unique

            self._coins_cache = cumulative
            logger.info(
                "Loaded coin lists: "
                + ", ".join(f"{t}={len(coins)}" for t, coins in cumulative.items())
            )

            if tier:
                return {tier: self._coins_cache.get(tier, [])}
            return self._coins_cache

        except Exception as e:
            raise ConfigError(f"Failed to load DANH_SACH_COIN: {e}", source="config_loader") from e
