"""Whale Alert — Large Transaction Tracker (v0.24.0).

Monitors whale transactions (≥$1M) across 20+ blockchains.
API: api.whale-alert.io/v1/ (paid plans only — min $29.95/mo)
Optional: pipeline works without key (returns empty summary).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import httpx

from cic_daily_report.core.logger import get_logger

logger = get_logger("whale_alert")

BASE_URL = "https://api.whale-alert.io/v1"
REQUEST_TIMEOUT = 20
MIN_VALUE_USD = 1_000_000  # $1M minimum
# Free plan allows ~1 hour lookback max (3600s). Use 3500s for safety margin.
LOOKBACK_SECONDS = 3500

# Currencies we track
TRACKED_CURRENCIES = {"btc", "eth", "usdt", "usdc"}


@dataclass
class WhaleTransaction:
    """A single whale transaction."""

    blockchain: str
    symbol: str
    amount: float
    amount_usd: float
    from_owner: str  # "exchange", "unknown"
    to_owner: str  # "exchange", "unknown"
    from_name: str  # exchange name or ""
    to_name: str  # exchange name or ""
    timestamp: int

    @property
    def flow_type(self) -> str:
        """Classify transaction flow direction."""
        from_ex = self.from_owner == "exchange"
        to_ex = self.to_owner == "exchange"
        if from_ex and not to_ex:
            return "exchange_outflow"  # withdrawal from exchange
        if not from_ex and to_ex:
            return "exchange_inflow"  # deposit to exchange
        if from_ex and to_ex:
            return "exchange_to_exchange"
        return "unknown_transfer"


@dataclass
class WhaleAlertSummary:
    """Aggregated whale activity for LLM context."""

    transactions: list[WhaleTransaction] = field(default_factory=list)
    total_count: int = 0
    btc_inflow_usd: float = 0.0
    btc_outflow_usd: float = 0.0
    eth_inflow_usd: float = 0.0
    eth_outflow_usd: float = 0.0
    stablecoin_inflow_usd: float = 0.0
    stablecoin_outflow_usd: float = 0.0

    @property
    def btc_net_flow(self) -> float:
        """Positive = net inflow to exchanges, negative = net outflow."""
        return self.btc_inflow_usd - self.btc_outflow_usd

    @property
    def eth_net_flow(self) -> float:
        return self.eth_inflow_usd - self.eth_outflow_usd

    @property
    def stablecoin_net_flow(self) -> float:
        return self.stablecoin_inflow_usd - self.stablecoin_outflow_usd

    def format_for_llm(self) -> str:
        """Format whale data as LLM context string."""
        if not self.transactions:
            return "WHALE ACTIVITY (1h): Không có dữ liệu whale alert."

        lines = [f"WHALE ACTIVITY (1h): {self.total_count} giao dịch lớn (≥$1M)"]

        # BTC flow
        if self.btc_inflow_usd > 0 or self.btc_outflow_usd > 0:
            direction = "VÀO sàn" if self.btc_net_flow > 0 else "RA khỏi sàn"
            lines.append(
                f"  BTC: ${abs(self.btc_net_flow) / 1e6:,.1f}M net {direction} "
                f"(in=${self.btc_inflow_usd / 1e6:,.1f}M, "
                f"out=${self.btc_outflow_usd / 1e6:,.1f}M)"
            )

        # ETH flow
        if self.eth_inflow_usd > 0 or self.eth_outflow_usd > 0:
            direction = "VÀO sàn" if self.eth_net_flow > 0 else "RA khỏi sàn"
            lines.append(
                f"  ETH: ${abs(self.eth_net_flow) / 1e6:,.1f}M net {direction} "
                f"(in=${self.eth_inflow_usd / 1e6:,.1f}M, "
                f"out=${self.eth_outflow_usd / 1e6:,.1f}M)"
            )

        # Stablecoin flow
        if self.stablecoin_inflow_usd > 0 or self.stablecoin_outflow_usd > 0:
            direction = "VÀO sàn" if self.stablecoin_net_flow > 0 else "RA khỏi sàn"
            lines.append(
                f"  Stablecoin: ${abs(self.stablecoin_net_flow) / 1e6:,.1f}M net {direction}"
            )

        # Top 3 largest transactions
        top3 = sorted(self.transactions, key=lambda t: t.amount_usd, reverse=True)[:3]
        if top3:
            lines.append("  Top 3 lớn nhất:")
            for tx in top3:
                src = tx.from_name or tx.from_owner
                dst = tx.to_name or tx.to_owner
                lines.append(
                    f"    - {tx.symbol.upper()} ${tx.amount_usd / 1e6:,.1f}M ({src} → {dst})"
                )

        # Signal interpretation
        if self.btc_net_flow < -10_000_000:
            lines.append("  → Tín hiệu: BTC rút ròng khỏi sàn — whale có thể đang tích lũy")
        elif self.btc_net_flow > 10_000_000:
            lines.append("  → Tín hiệu: BTC nạp ròng vào sàn — có thể chuẩn bị bán")
        if self.stablecoin_net_flow > 50_000_000:
            lines.append("  → Tín hiệu: Stablecoin nạp ròng vào sàn — có thể chuẩn bị mua")

        return "\n".join(lines)


async def collect_whale_alerts() -> WhaleAlertSummary:
    """Collect and summarize whale transactions from last 1h.

    Returns WhaleAlertSummary with aggregated flow data.
    Graceful degradation: returns empty summary on failure.
    """
    api_key = os.getenv("WHALE_ALERT_API_KEY", "")
    if not api_key:
        logger.warning("WHALE_ALERT_API_KEY not set — skipping Whale Alert")
        return WhaleAlertSummary()

    try:
        start_ts = int(time.time()) - LOOKBACK_SECONDS
        transactions = await _fetch_transactions(api_key, start_ts)
        summary = _aggregate_transactions(transactions)
        logger.info(
            f"Whale Alert: {summary.total_count} transactions "
            f"(BTC net={summary.btc_net_flow / 1e6:+,.1f}M, "
            f"stablecoin net={summary.stablecoin_net_flow / 1e6:+,.1f}M)"
        )
        return summary
    except Exception as e:
        logger.warning(f"Whale Alert collection failed: {e}")
        return WhaleAlertSummary()


async def _fetch_transactions(api_key: str, start_ts: int) -> list[WhaleTransaction]:
    """Fetch whale transactions from API."""
    transactions: list[WhaleTransaction] = []

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            # Note: `currency` param is single-valued in Whale Alert API.
            # Omit it and filter client-side by TRACKED_CURRENCIES instead.
            resp = await client.get(
                f"{BASE_URL}/transactions",
                params={
                    "api_key": api_key,
                    "min_value": MIN_VALUE_USD,
                    "start": start_ts,
                    "limit": 100,
                },
            )
            resp.raise_for_status()

        data = resp.json()
        if data.get("result") != "success":
            logger.warning(f"Whale Alert API error: {data.get('message', 'unknown')}")
            return []

        for tx in data.get("transactions", []):
            symbol = tx.get("symbol", "").lower()
            if symbol not in TRACKED_CURRENCIES:
                continue

            amount_usd = float(tx.get("amount_usd", 0))
            if amount_usd < MIN_VALUE_USD:
                continue

            from_info = tx.get("from", {})
            to_info = tx.get("to", {})

            transactions.append(
                WhaleTransaction(
                    blockchain=tx.get("blockchain", ""),
                    symbol=symbol,
                    amount=float(tx.get("amount", 0)),
                    amount_usd=amount_usd,
                    from_owner=from_info.get("owner_type", "unknown"),
                    to_owner=to_info.get("owner_type", "unknown"),
                    from_name=from_info.get("owner", ""),
                    to_name=to_info.get("owner", ""),
                    timestamp=int(tx.get("timestamp", 0)),
                )
            )

    except httpx.HTTPStatusError as e:
        logger.warning(f"Whale Alert HTTP {e.response.status_code}")
    except Exception as e:
        logger.warning(f"Whale Alert fetch: {e}")

    return transactions


def _aggregate_transactions(transactions: list[WhaleTransaction]) -> WhaleAlertSummary:
    """Aggregate transactions into flow summary."""
    summary = WhaleAlertSummary(
        transactions=transactions,
        total_count=len(transactions),
    )

    for tx in transactions:
        is_inflow = tx.flow_type == "exchange_inflow"
        is_outflow = tx.flow_type == "exchange_outflow"

        if tx.symbol == "btc":
            if is_inflow:
                summary.btc_inflow_usd += tx.amount_usd
            elif is_outflow:
                summary.btc_outflow_usd += tx.amount_usd
        elif tx.symbol == "eth":
            if is_inflow:
                summary.eth_inflow_usd += tx.amount_usd
            elif is_outflow:
                summary.eth_outflow_usd += tx.amount_usd
        elif tx.symbol in ("usdt", "usdc"):
            if is_inflow:
                summary.stablecoin_inflow_usd += tx.amount_usd
            elif is_outflow:
                summary.stablecoin_outflow_usd += tx.amount_usd

    return summary
