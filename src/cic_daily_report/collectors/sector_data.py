"""Sector & DeFi Data Collector (Phase 2) — CoinGecko categories + DefiLlama TVL.

Free APIs, no keys required. Adds sector-level context for L2-L5 analysis:
- CoinGecko /categories: market cap + 24h change per sector
- DefiLlama /protocols: total TVL + top protocols by chain
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

from cic_daily_report.core.logger import get_logger

logger = get_logger("sector_data")

_TIMEOUT = 20  # seconds


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class SectorData:
    """Market data for a crypto sector/category."""

    name: str  # e.g. "DeFi", "Layer 2", "AI"
    market_cap: float  # USD
    market_cap_change_24h: float  # percentage
    volume_24h: float  # USD
    top_coins: list[str]  # top 3 coin names


@dataclass
class DefiProtocol:
    """TVL data for a DeFi protocol."""

    name: str
    tvl: float  # USD
    chain: str
    change_1d: float  # percentage
    category: str  # "Lending", "DEX", etc.


@dataclass
class SectorSnapshot:
    """Complete sector data snapshot."""

    sectors: list[SectorData]
    defi_total_tvl: float
    defi_protocols: list[DefiProtocol]

    def format_for_llm(self) -> str:
        """Format sector data as LLM context text."""
        parts: list[str] = []

        if self.sectors:
            parts.append("=== PHÂN TÍCH THEO SECTOR (nguồn: CoinGecko) ===")
            for s in self.sectors[:10]:  # top 10 sectors
                mcap_b = (s.market_cap or 0) / 1e9 if (s.market_cap or 0) > 0 else 0
                vol_b = (s.volume_24h or 0) / 1e9 if (s.volume_24h or 0) > 0 else 0
                change = s.market_cap_change_24h or 0
                coins = ", ".join(s.top_coins[:3]) if s.top_coins else "N/A"
                parts.append(
                    f"  • {s.name}: MCap ${mcap_b:.1f}B ({change:+.1f}%) "
                    f"| Vol ${vol_b:.1f}B | Top: {coins}"
                )

        if (self.defi_total_tvl or 0) > 0:
            tvl_b = self.defi_total_tvl / 1e9
            parts.append(f"\nDeFi TỔNG TVL: ${tvl_b:.1f}B (nguồn: DefiLlama)")

        if self.defi_protocols:
            parts.append("Top DeFi protocols:")
            for p in self.defi_protocols[:8]:
                p_tvl = p.tvl or 0
                tvl_b = p_tvl / 1e9 if p_tvl > 1e9 else p_tvl / 1e6
                unit = "B" if p_tvl > 1e9 else "M"
                change = p.change_1d or 0
                parts.append(
                    f"  • {p.name} ({p.category}): TVL ${tvl_b:.1f}{unit} "
                    f"({change:+.1f}%) — {p.chain}"
                )

        return "\n".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# CoinGecko Categories
# ---------------------------------------------------------------------------

# Sectors we care about (CoinGecko category IDs → display name)
_TARGET_CATEGORIES: dict[str, str] = {
    "decentralized-finance-defi": "DeFi",
    "layer-1": "Layer 1",
    "layer-2": "Layer 2",
    "artificial-intelligence": "AI & Big Data",
    "gaming": "Gaming (GameFi)",
    "meme-token": "Meme",
    "real-world-assets-rwa": "RWA",
    "decentralized-exchange": "DEX",
    "lending-borrowing": "Lending",
    "non-fungible-tokens-nft": "NFT",
    "zero-knowledge-zk": "Zero Knowledge",
    "infrastructure": "Infrastructure",
}


async def _collect_coingecko_categories() -> list[SectorData]:
    """Fetch sector data from CoinGecko /categories (free, 30 req/min)."""
    url = "https://api.coingecko.com/api/v3/coins/categories"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        categories = resp.json()
        if not isinstance(categories, list):
            logger.warning("CoinGecko categories: unexpected response format")
            return []

        sectors: list[SectorData] = []
        # Build a lookup by ID
        cat_by_id = {c.get("id", ""): c for c in categories}

        for cat_id, display_name in _TARGET_CATEGORIES.items():
            cat = cat_by_id.get(cat_id)
            if not cat:
                continue
            top_coins = cat.get("top_3_coins_id", []) or []
            # CoinGecko returns coin IDs, use them as-is (close enough to names)
            top_coin_names = [c.replace("-", " ").title() for c in top_coins[:3] if c]
            sectors.append(
                SectorData(
                    name=display_name,
                    market_cap=float(cat.get("market_cap", 0) or 0),
                    market_cap_change_24h=float(cat.get("market_cap_change_24h", 0) or 0),
                    volume_24h=float(cat.get("volume_24h", 0) or 0),
                    top_coins=top_coin_names,
                )
            )

        # Sort by market cap descending
        sectors.sort(key=lambda s: s.market_cap, reverse=True)
        logger.info(f"CoinGecko sectors: {len(sectors)} categories collected")
        return sectors

    except httpx.HTTPStatusError as e:
        logger.warning(f"CoinGecko categories HTTP {e.response.status_code}")
        return []
    except Exception as e:
        logger.warning(f"CoinGecko categories failed: {e}")
        return []


# ---------------------------------------------------------------------------
# DefiLlama TVL
# ---------------------------------------------------------------------------


async def _collect_defillama() -> tuple[float, list[DefiProtocol]]:
    """Fetch DeFi TVL from DefiLlama (free, no key, no rate limit).

    Returns (total_tvl, top_protocols).
    """
    total_tvl = 0.0
    protocols: list[DefiProtocol] = []

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        # Total TVL
        try:
            resp = await client.get("https://api.llama.fi/v2/historicalChainTvl")
            resp.raise_for_status()
            data = resp.json()
            if data and isinstance(data, list):
                total_tvl = float(data[-1].get("tvl") or 0)
        except Exception as e:
            logger.warning(f"DefiLlama total TVL failed: {e}")

        # Top protocols
        try:
            resp = await client.get("https://api.llama.fi/protocols")
            resp.raise_for_status()
            data = resp.json()
            if data and isinstance(data, list):
                # Sort by TVL, take top 15. Guard against None values from API.
                sorted_protos = sorted(
                    [p for p in data if (p.get("tvl") or 0) > 0],
                    key=lambda p: p.get("tvl") or 0,
                    reverse=True,
                )[:15]

                for p in sorted_protos:
                    change_1d = float(p.get("change_1d") or 0)
                    chains = p.get("chains", [])
                    chain = chains[0] if chains else "Multi-chain"
                    protocols.append(
                        DefiProtocol(
                            name=p.get("name", "Unknown"),
                            tvl=float(p.get("tvl", 0)),
                            chain=chain,
                            change_1d=change_1d,
                            category=p.get("category", "Other"),
                        )
                    )
        except Exception as e:
            logger.warning(f"DefiLlama protocols failed: {e}")

    logger.info(f"DefiLlama: TVL=${total_tvl / 1e9:.1f}B, {len(protocols)} top protocols")
    return total_tvl, protocols


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def collect_sector_data() -> SectorSnapshot:
    """Collect all sector data in parallel.

    Returns SectorSnapshot with CoinGecko categories + DefiLlama TVL.
    Both sources are free with no API key required.
    """
    logger.info("Collecting sector & DeFi data")

    sectors_task = _collect_coingecko_categories()
    defi_task = _collect_defillama()

    results = await asyncio.gather(sectors_task, defi_task, return_exceptions=True)

    sectors = results[0] if not isinstance(results[0], Exception) else []
    if isinstance(results[1], Exception):
        defi_tvl, defi_protocols = 0.0, []
    else:
        defi_tvl, defi_protocols = results[1]

    snapshot = SectorSnapshot(
        sectors=sectors,
        defi_total_tvl=defi_tvl,
        defi_protocols=defi_protocols,
    )
    logger.info(
        f"Sector data done: {len(sectors)} sectors, "
        f"TVL=${defi_tvl / 1e9:.1f}B, {len(defi_protocols)} protocols"
    )
    return snapshot
