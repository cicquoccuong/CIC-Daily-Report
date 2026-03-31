"""Unified coin name ↔ ticker mapping (v0.28.0).

Config-driven: primary source is DANH_SACH_COIN "Tên dự án" column (operator-managed).
Hardcoded fallback for common names when Sheet column is empty or missing.

Used by: dedup_manager, breaking_pipeline, severity_classifier, article_generator.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cic_daily_report.storage.sentinel_reader import SentinelCoin

# ---------------------------------------------------------------------------
# Hardcoded fallback mapping — used when DANH_SACH_COIN has no "Tên dự án".
# Keys: project name (lowercase). Values: ticker (uppercase).
# ---------------------------------------------------------------------------
_FALLBACK_NAME_TO_TICKER: dict[str, str] = {
    # Top-20 by market cap
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "solana": "SOL",
    "ripple": "XRP",
    "cardano": "ADA",
    "dogecoin": "DOGE",
    "avalanche": "AVAX",
    "polkadot": "DOT",
    "polygon": "MATIC",
    "chainlink": "LINK",
    "uniswap": "UNI",
    "cosmos": "ATOM",
    "litecoin": "LTC",
    "near protocol": "NEAR",
    "near": "NEAR",
    "aptos": "APT",
    "arbitrum": "ARB",
    "optimism": "OP",
    "sui": "SUI",
    "tron": "TRX",
    "stellar": "XLM",
    "hedera": "HBAR",
    "filecoin": "FIL",
    "internet computer": "ICP",
    "toncoin": "TON",
    "ton": "TON",
    # Rebrands / aliases
    "strategy": "MSTR",  # MicroStrategy rebranded 2025
    "microstrategy": "MSTR",
    "terra": "LUNA",
    "terra luna": "LUNA",
    "shiba inu": "SHIB",
    "shib": "SHIB",
}

# ---------------------------------------------------------------------------
# Runtime state — merged mapping (config + fallback). Initialized with fallback,
# updated when load_from_config() is called during pipeline startup.
# ---------------------------------------------------------------------------
NAME_TO_TICKER: dict[str, str] = dict(_FALLBACK_NAME_TO_TICKER)

# Reverse mapping: ticker (lowercase) → ticker (uppercase).
_TICKER_CANONICAL: dict[str, str] = {}

# All project names (lowercase) — for keyword-based relevance checks.
PROJECT_NAMES: set[str] = set()


def _rebuild_derived() -> None:
    """Rebuild derived lookups from NAME_TO_TICKER.

    Mutates existing objects in-place so imported references stay valid.
    """
    _TICKER_CANONICAL.clear()
    _TICKER_CANONICAL.update({v.lower(): v for v in set(NAME_TO_TICKER.values())})
    PROJECT_NAMES.clear()
    PROJECT_NAMES.update(NAME_TO_TICKER.keys())


# Initialize derived state from fallback
_rebuild_derived()


def load_from_config(config_name_map: dict[str, str]) -> int:
    """Merge config-driven name→ticker mapping into the active mapping.

    Called once during pipeline startup with data from ConfigLoader.get_coin_name_map().
    Config entries take precedence over hardcoded fallback (allows operator overrides).

    Args:
        config_name_map: Dict of lowercase project name → uppercase ticker
                         from DANH_SACH_COIN "Tên dự án" column.

    Returns:
        Number of new entries added (beyond fallback).
    """
    before = len(NAME_TO_TICKER)
    # Config takes precedence — operator can override fallback
    NAME_TO_TICKER.update(config_name_map)
    _rebuild_derived()
    added = len(NAME_TO_TICKER) - before
    return added


def load_from_sentinel(registry: list[SentinelCoin]) -> int:
    """Supplement coin mapping with Sentinel 01_ASSET_IDENTITY registry.

    P1.15: Adds Sentinel-tracked coins to the mapping. Does NOT override
    existing entries — config and fallback mappings take precedence because
    they are operator-curated.

    Args:
        registry: List of SentinelCoin from SentinelReader.read_registry().

    Returns:
        Number of new entries added from Sentinel registry.
    """
    before = len(NAME_TO_TICKER)
    for coin in registry:
        name_key = coin.name.strip().lower()
        symbol = coin.symbol.strip().upper()
        if not name_key or not symbol:
            continue
        # WHY: Don't override existing mappings — operator config takes precedence
        if name_key not in NAME_TO_TICKER:
            NAME_TO_TICKER[name_key] = symbol
    _rebuild_derived()
    added = len(NAME_TO_TICKER) - before
    return added


def normalize_to_ticker(name: str) -> str | None:
    """Resolve a project name or ticker to its canonical uppercase ticker.

    Returns None if name is not recognized.

    Examples:
        >>> normalize_to_ticker("Ripple")
        'XRP'
        >>> normalize_to_ticker("btc")
        'BTC'
        >>> normalize_to_ticker("unknown")
        None
    """
    key = name.strip().lower()
    # Check name → ticker first
    if key in NAME_TO_TICKER:
        return NAME_TO_TICKER[key]
    # Check if it's already a known ticker
    if key in _TICKER_CANONICAL:
        return _TICKER_CANONICAL[key]
    return None


def extract_coins_from_text(text: str, known_coins: set[str] | None = None) -> set[str]:
    """Extract all recognized coin tickers from free text.

    Scans for both uppercase tickers (BTC, ETH) and project names (Ripple, Cardano).
    If known_coins is provided, only returns tickers in that set.

    Args:
        text: Free text (news title, article content, etc.)
        known_coins: Optional whitelist of tracked tickers (uppercase).

    Returns:
        Set of canonical uppercase tickers found in text.
    """
    found: set[str] = set()

    # 1. Match uppercase tickers (2-6 chars) — real tickers in news
    for match in re.finditer(r"\b([A-Z]{2,6})\b", text):
        candidate = match.group(1)
        ticker = _TICKER_CANONICAL.get(candidate.lower())
        if ticker:
            found.add(ticker)

    # 2. Match project names (case-insensitive)
    text_lower = text.lower()
    for name, ticker in NAME_TO_TICKER.items():
        if name in text_lower:
            found.add(ticker)

    # 3. Filter by known_coins if provided
    if known_coins is not None:
        found = found & known_coins

    return found
