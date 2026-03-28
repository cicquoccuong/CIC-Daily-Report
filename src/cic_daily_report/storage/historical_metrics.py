"""Historical Metrics Storage — daily snapshot save/read for LICH_SU_METRICS tab.

Saves key metrics after each pipeline run so LLM can reference 7d/30d history
for richer analysis (e.g. "F&G=13 -- last time below 15 was day X, BTC rose Y%").

v2.0 P1.3: New module for Historical Context System (spec Section 2.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from cic_daily_report.core.logger import get_logger

logger = get_logger("historical_metrics")

# Tab name matches Vietnamese no-diacritics UPPER_SNAKE_CASE convention (QD1)
TAB_NAME = "LICH_SU_METRICS"

# Column headers — Vietnamese WITH diacritics per project rules
LICH_SU_METRICS_HEADERS = [
    "Ngay",
    "BTC_Gia",
    "ETH_Gia",
    "F_and_G",
    "DXY",
    "Vang",
    "Dau",
    "VIX",
    "Funding_Rate",
    "BTC_Dominance",
    "Altcoin_Season",
    "Consensus_Score",
    "Consensus_Label",
    "RSI_BTC",
    "MA50_BTC",
    "MA200_BTC",
    "MVRV_Z",
    "NUPL",
    "SOPR",
    "Puell_Multiple",
    "Pi_Cycle_Gap_Pct",
    "ETF_Net_Flow",
    "Stablecoin_Total_Chg_7d",
]

# WHY: 90-day retention matches spec Section 9 and data_retention.py pattern
MAX_RETENTION_DAYS = 90


@dataclass
class HistoricalSnapshot:
    """One day's key metrics — maps 1:1 to LICH_SU_METRICS row (spec Section 3.3)."""

    date: str  # YYYY-MM-DD
    btc_price: float
    eth_price: float
    f_and_g: int
    dxy: float
    gold: float
    oil: float
    vix: float
    funding_rate: float
    btc_dominance: float
    altcoin_season: float
    consensus_score: float  # 0.0 for Phase 1a (consensus engine not built yet)
    consensus_label: str  # "N/A" for Phase 1a
    rsi_btc: float
    ma50_btc: float
    ma200_btc: float
    mvrv_z: float
    nupl: float
    sopr: float
    puell_multiple: float
    pi_cycle_gap_pct: float
    etf_net_flow: float
    stablecoin_total_chg_7d: float

    def to_row(self) -> list:
        """Convert to list matching LICH_SU_METRICS_HEADERS order."""
        return [
            self.date,
            self.btc_price,
            self.eth_price,
            self.f_and_g,
            self.dxy,
            self.gold,
            self.oil,
            self.vix,
            self.funding_rate,
            self.btc_dominance,
            self.altcoin_season,
            self.consensus_score,
            self.consensus_label,
            self.rsi_btc,
            self.ma50_btc,
            self.ma200_btc,
            self.mvrv_z,
            self.nupl,
            self.sopr,
            self.puell_multiple,
            self.pi_cycle_gap_pct,
            self.etf_net_flow,
            self.stablecoin_total_chg_7d,
        ]

    @classmethod
    def from_row(cls, row: list) -> HistoricalSnapshot:
        """Parse a sheet row back into a HistoricalSnapshot.

        WHY: Defensive parsing — sheet values may be strings or empty.
        """

        def _float(val, default: float = 0.0) -> float:
            try:
                return float(val) if val != "" else default
            except (ValueError, TypeError):
                return default

        def _int(val, default: int = 0) -> int:
            try:
                return int(float(val)) if val != "" else default
            except (ValueError, TypeError):
                return default

        return cls(
            date=str(row[0]) if len(row) > 0 else "",
            btc_price=_float(row[1]) if len(row) > 1 else 0.0,
            eth_price=_float(row[2]) if len(row) > 2 else 0.0,
            f_and_g=_int(row[3]) if len(row) > 3 else 0,
            dxy=_float(row[4]) if len(row) > 4 else 0.0,
            gold=_float(row[5]) if len(row) > 5 else 0.0,
            oil=_float(row[6]) if len(row) > 6 else 0.0,
            vix=_float(row[7]) if len(row) > 7 else 0.0,
            funding_rate=_float(row[8]) if len(row) > 8 else 0.0,
            btc_dominance=_float(row[9]) if len(row) > 9 else 0.0,
            altcoin_season=_float(row[10]) if len(row) > 10 else 0.0,
            consensus_score=_float(row[11]) if len(row) > 11 else 0.0,
            consensus_label=str(row[12]) if len(row) > 12 else "N/A",
            rsi_btc=_float(row[13]) if len(row) > 13 else 0.0,
            ma50_btc=_float(row[14]) if len(row) > 14 else 0.0,
            ma200_btc=_float(row[15]) if len(row) > 15 else 0.0,
            mvrv_z=_float(row[16]) if len(row) > 16 else 0.0,
            nupl=_float(row[17]) if len(row) > 17 else 0.0,
            sopr=_float(row[18]) if len(row) > 18 else 0.0,
            puell_multiple=_float(row[19]) if len(row) > 19 else 0.0,
            pi_cycle_gap_pct=_float(row[20]) if len(row) > 20 else 0.0,
            etf_net_flow=_float(row[21]) if len(row) > 21 else 0.0,
            stablecoin_total_chg_7d=_float(row[22]) if len(row) > 22 else 0.0,
        )


def _ensure_tab_exists(sheets_client) -> None:
    """Create LICH_SU_METRICS tab with headers if it doesn't exist.

    WHY: First pipeline run won't have the tab yet. Creating it here keeps
    historical_metrics self-contained instead of coupling to create_schema().
    """
    ss = sheets_client._connect()
    existing = {ws.title for ws in ss.worksheets()}
    if TAB_NAME not in existing:
        ws = ss.add_worksheet(title=TAB_NAME, rows=100, cols=len(LICH_SU_METRICS_HEADERS))
        ws.update([LICH_SU_METRICS_HEADERS], value_input_option="RAW")
        logger.info(f"Created tab '{TAB_NAME}' with {len(LICH_SU_METRICS_HEADERS)} columns")


def save_daily_snapshot(sheets_client, snapshot: HistoricalSnapshot) -> bool:
    """Save today's metrics to LICH_SU_METRICS. Returns True if saved, False if duplicate.

    WHY: Prevents double-run duplication by checking if today's date already exists.
    Uses batch append (gspread append_rows) per project rules — never cell-by-cell.
    """
    try:
        _ensure_tab_exists(sheets_client)

        # Check for duplicate: read existing dates to prevent double-run
        ss = sheets_client._connect()
        ws = ss.worksheet(TAB_NAME)
        all_values = ws.get_all_values()

        # all_values[0] = header row; rest = data rows
        for row in all_values[1:]:
            if row and row[0] == snapshot.date:
                logger.info(f"Snapshot for {snapshot.date} already exists, skipping")
                return False

        # Append new row
        ws.append_rows([snapshot.to_row()], value_input_option="RAW")
        logger.info(f"Saved historical snapshot for {snapshot.date}")

        # Auto-cleanup rows older than MAX_RETENTION_DAYS (spec: 90 days)
        _cleanup_old_rows(ws, all_values)

        return True
    except Exception as e:
        logger.error(f"Failed to save historical snapshot: {e}")
        return False


def _cleanup_old_rows(ws, all_values: list[list]) -> None:
    """Remove rows older than MAX_RETENTION_DAYS.

    WHY: Spec Section 9 says "Retention: Keep 90 days of data (auto-cleanup oldest rows)".
    Runs after each save to keep tab size bounded.

    WHY batch delete: Stale rows are always contiguous from the top (data is
    sorted by date ascending, oldest first). Using a single ws.delete_rows(start, end)
    call instead of N individual calls avoids gspread rate limits when many rows
    accumulate (e.g., after a long outage).
    """
    if len(all_values) <= 1:
        return

    cutoff = (datetime.now(timezone.utc) - timedelta(days=MAX_RETENTION_DAYS)).strftime("%Y-%m-%d")

    # Find the last stale row index (contiguous from top, skip header at row 1)
    last_stale_idx = 0
    for i, row in enumerate(all_values[1:], start=2):  # 1-based, header=row 1
        if row and row[0] < cutoff:
            last_stale_idx = i
        else:
            # Rows are date-sorted ascending — first non-stale means rest are fresh
            break

    if last_stale_idx > 0:
        # Single batch delete: rows 2 through last_stale_idx (inclusive)
        count = last_stale_idx - 1  # number of rows (row 2 to last_stale_idx)
        ws.delete_rows(2, last_stale_idx)
        logger.info(f"Cleaned up {count} old historical rows (>{MAX_RETENTION_DAYS}d)")


def read_historical(sheets_client, lookback_days: int = 30) -> list[HistoricalSnapshot]:
    """Read historical snapshots from LICH_SU_METRICS tab.

    Returns sorted by date ascending, filtered to last `lookback_days`.
    Returns empty list if tab doesn't exist or is empty.

    WHY: Graceful handling for first run (no tab yet) or empty tab.
    """
    try:
        ss = sheets_client._connect()
        existing = {ws.title for ws in ss.worksheets()}
        if TAB_NAME not in existing:
            logger.info(f"Tab '{TAB_NAME}' not found, returning empty history")
            return []

        ws = ss.worksheet(TAB_NAME)
        all_values = ws.get_all_values()

        if len(all_values) <= 1:  # Only header or empty
            return []

        cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

        snapshots = []
        for row in all_values[1:]:  # Skip header
            if row and row[0] >= cutoff:
                try:
                    snapshots.append(HistoricalSnapshot.from_row(row))
                except Exception as e:
                    logger.warning(f"Skipping malformed row: {e}")

        # Sort by date ascending
        snapshots.sort(key=lambda s: s.date)
        logger.info(f"Read {len(snapshots)} historical snapshots (lookback={lookback_days}d)")
        return snapshots
    except Exception as e:
        logger.error(f"Failed to read historical data: {e}")
        return []


def format_historical_for_llm(history: list[HistoricalSnapshot]) -> str:
    """Format historical snapshots as structured text for LLM prompt.

    WHY: Two sections — 7-day detail (daily breakdown) + 30-day comparison
    (trend delta). This gives LLM enough context to write comparative analysis
    without overwhelming the prompt with raw numbers.
    """
    if not history:
        return ""

    parts: list[str] = []

    # Section 1: 7-day detail (most recent 7 days)
    recent_7d = history[-7:]  # Last 7 entries (already sorted ascending)
    lines_7d = []
    for snap in reversed(recent_7d):  # Most recent first for readability
        # Format date as DD/MM for Vietnamese style
        try:
            dt = datetime.strptime(snap.date, "%Y-%m-%d")
            date_str = dt.strftime("%d/%m")
        except ValueError:
            date_str = snap.date

        line = (
            f"{date_str}: BTC ${snap.btc_price:,.0f} | F&G: {snap.f_and_g} "
            f"| RSI: {snap.rsi_btc:.1f} | MVRV: {snap.mvrv_z:.2f}"
        )
        lines_7d.append(line)

    parts.append("=== LICH SU 7 NGAY GAN NHAT ===\n" + "\n".join(lines_7d))

    # Section 2: 30-day comparison (only if we have >= 7 days of data)
    # WHY: 30d comparison only makes sense with enough history to show a trend
    if len(history) >= 7:
        current = history[-1]  # Most recent
        oldest = history[0]  # Oldest in range

        days_span = len(history)

        def _pct_change(current_val: float, old_val: float) -> str:
            if old_val == 0:
                return "N/A"
            change = ((current_val - old_val) / abs(old_val)) * 100
            return f"{change:+.1f}%"

        def _fg_label(value: int) -> str:
            if value <= 20:
                return "Extreme Fear"
            elif value <= 40:
                return "Fear"
            elif value <= 60:
                return "Neutral"
            elif value <= 80:
                return "Greed"
            return "Extreme Greed"

        comparison_lines = [
            f"BTC: ${current.btc_price:,.0f} vs ${oldest.btc_price:,.0f} "
            f"{days_span} ngay truoc ({_pct_change(current.btc_price, oldest.btc_price)})",
            f"F&G: {current.f_and_g} vs {oldest.f_and_g} "
            f"({_fg_label(current.f_and_g)} vs {_fg_label(oldest.f_and_g)})",
            f"RSI: {current.rsi_btc:.1f} vs {oldest.rsi_btc:.1f}",
            f"MVRV-Z: {current.mvrv_z:.2f} vs {oldest.mvrv_z:.2f}",
        ]

        parts.append(f"\n=== SO SANH {days_span} NGAY ===\n" + "\n".join(comparison_lines))

    return "\n".join(parts)


def build_snapshot_from_pipeline(
    market_data_points: list,
    onchain_text: str,
    key_metrics: dict,
    research_data,
    technical_indicators: list,
) -> HistoricalSnapshot:
    """Build a HistoricalSnapshot from pipeline data structures.

    WHY: Centralizes the extraction logic so daily_pipeline.py stays clean.
    Handles missing values gracefully (defaults to 0.0) since not all data
    sources may be available on every run.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Extract from market_data_points (list of MarketDataPoint)
    btc_price = 0.0
    eth_price = 0.0
    f_and_g = 0
    dxy = 0.0
    gold = 0.0
    oil = 0.0
    vix = 0.0
    btc_dominance = 0.0
    altcoin_season = 0.0

    for p in market_data_points:
        sym = getattr(p, "symbol", "")
        price = getattr(p, "price", 0.0)
        dtype = getattr(p, "data_type", "")

        if sym == "BTC" and dtype == "crypto":
            btc_price = price
        elif sym == "ETH" and dtype == "crypto":
            eth_price = price
        elif sym == "Fear&Greed":
            f_and_g = int(price)
        elif sym == "DXY":
            dxy = price
        elif sym == "Gold":
            gold = price
        elif sym == "Oil":
            oil = price
        elif sym == "VIX":
            vix = price
        elif sym == "BTC_Dominance":
            btc_dominance = price
        elif sym == "Altcoin_Season":
            altcoin_season = price

    # Extract funding rate from onchain_text (parsed string)
    # WHY: Funding rate is in onchain_data as text, not a separate structure
    funding_rate = 0.0
    if onchain_text:
        for line in onchain_text.split("\n"):
            if "BTC_Funding_Rate" in line or "funding" in line.lower():
                # Try to extract the numeric value
                try:
                    parts = line.split(":")
                    if len(parts) >= 2:
                        val_str = parts[-1].strip().rstrip("%").strip("() ")
                        # Remove source attribution like "(Coinalyze)"
                        for sep in ["(", " "]:
                            if sep in val_str:
                                val_str = val_str.split(sep)[0].strip()
                        funding_rate = float(val_str)
                except (ValueError, IndexError):
                    pass

    # Extract from technical_indicators (list of TechnicalIndicators)
    rsi_btc = 0.0
    ma50_btc = 0.0
    ma200_btc = 0.0
    for ind in technical_indicators:
        if getattr(ind, "symbol", "") == "BTC":
            rsi_btc = getattr(ind, "rsi_14d", 0.0)
            ma50_btc = getattr(ind, "ma_50", 0.0)
            ma200_btc = getattr(ind, "ma_200", 0.0)
            break

    # Extract from research_data (ResearchData dataclass)
    mvrv_z = 0.0
    nupl = 0.0
    sopr = 0.0
    puell_multiple = 0.0
    pi_cycle_gap_pct = 0.0
    etf_net_flow = 0.0
    stablecoin_total_chg_7d = 0.0

    if research_data is not None:
        # On-chain advanced metrics (MVRV, NUPL, SOPR, Puell)
        for m in getattr(research_data, "onchain_advanced", []):
            name = getattr(m, "name", "").upper()
            value = getattr(m, "value", 0.0)
            if "MVRV" in name:
                mvrv_z = value
            elif "NUPL" in name:
                nupl = value
            elif "SOPR" in name:
                sopr = value
            elif "PUELL" in name:
                puell_multiple = value

        # Pi Cycle
        pi_cycle = getattr(research_data, "pi_cycle", None)
        if pi_cycle is not None:
            pi_cycle_gap_pct = getattr(pi_cycle, "distance_pct", 0.0)

        # ETF net flow
        etf_flows = getattr(research_data, "etf_flows", None)
        if etf_flows is not None:
            etf_net_flow = getattr(etf_flows, "total_flow_usd", 0.0)

        # Stablecoin 7d change (sum of all tracked stablecoins)
        stablecoins = getattr(research_data, "stablecoins", [])
        if stablecoins:
            stablecoin_total_chg_7d = sum(getattr(s, "change_7d", 0.0) for s in stablecoins)

    return HistoricalSnapshot(
        date=today,
        btc_price=btc_price,
        eth_price=eth_price,
        f_and_g=f_and_g,
        dxy=dxy,
        gold=gold,
        oil=oil,
        vix=vix,
        funding_rate=funding_rate,
        btc_dominance=btc_dominance,
        altcoin_season=altcoin_season,
        consensus_score=0.0,  # Phase 1a: consensus engine not built yet
        consensus_label="N/A",  # Phase 1a: consensus engine not built yet
        rsi_btc=rsi_btc,
        ma50_btc=ma50_btc,
        ma200_btc=ma200_btc,
        mvrv_z=mvrv_z,
        nupl=nupl,
        sopr=sopr,
        puell_multiple=puell_multiple,
        pi_cycle_gap_pct=pi_cycle_gap_pct,
        etf_net_flow=etf_net_flow,
        stablecoin_total_chg_7d=stablecoin_total_chg_7d,
    )
