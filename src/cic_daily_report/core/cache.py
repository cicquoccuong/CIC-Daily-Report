"""Simple file-based cache for API responses — reduces redundant API calls."""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any

from cic_daily_report.core.logger import get_logger

logger = get_logger("cache")

# Default cache directory: system temp / cic_cache
CACHE_DIR = os.path.join(tempfile.gettempdir(), "cic_cache")


def _ensure_cache_dir() -> None:
    """Create cache directory if it doesn't exist."""
    os.makedirs(CACHE_DIR, exist_ok=True)


def get_cached(key: str, max_age_seconds: int = 3600) -> Any | None:
    """Return cached data if fresh, else None.

    Args:
        key: Cache key (used as filename).
        max_age_seconds: Maximum age in seconds before cache is stale.
    """
    path = os.path.join(CACHE_DIR, f"{key}.json")
    try:
        if not os.path.exists(path):
            return None

        age = time.time() - os.path.getmtime(path)
        if age > max_age_seconds:
            logger.debug(f"Cache stale for '{key}' ({age:.0f}s > {max_age_seconds}s)")
            return None

        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        logger.info(f"Cache hit for '{key}' (age={age:.0f}s)")
        return data
    except Exception as e:
        logger.debug(f"Cache read failed for '{key}': {e}")
        return None


def set_cached(key: str, data: Any) -> None:
    """Write data to cache.

    Args:
        key: Cache key (used as filename).
        data: JSON-serializable data.
    """
    _ensure_cache_dir()
    path = os.path.join(CACHE_DIR, f"{key}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        logger.debug(f"Cache written for '{key}'")
    except Exception as e:
        logger.debug(f"Cache write failed for '{key}': {e}")
