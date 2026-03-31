"""Sentinel Spreadsheet Cross-Reader (P1.12).

Reads SonicR zones, FA scores, Season, Registry, and NQ05 blacklist
from the CIC-Sentinel spreadsheet. Uses same service account as DR
but targets a DIFFERENT spreadsheet_id (SENTINEL_SPREADSHEET_ID).

Design: Each read method is independent — if one tab fails, others
still work. Pipeline wraps sync gspread calls with asyncio.to_thread().
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials

from cic_daily_report.core.logger import get_logger

logger = get_logger("sentinel_reader")

# WHY: 1 hour threshold — Sentinel updates season data at least hourly.
# If stale > 1h, downstream should treat season data as potentially outdated.
STALE_THRESHOLD_SEC = 3600


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SentinelSeason:
    """Official season phase from Sentinel CONFIG tab."""

    phase: str  # MUA_DONG / MUA_XUAN / MUA_HE / MUA_THU
    heat_score: float  # 0-100
    confidence: float  # 0.0-1.0
    detail: str
    last_update: str


@dataclass
class SonicRZones:
    """SonicR technical zones for a single asset."""

    symbol: str
    ema34: float
    ema89: float
    ema200: float
    ema610: float
    sonicr_trend: str  # BULLISH / NEUTRAL / BEARISH
    fib_adca_zone: str
    rsi_d1: float


@dataclass
class SentinelFAScore:
    """Fundamental Analysis score from Sentinel 06_FA_SCORES tab."""

    symbol: str
    total_score: float  # 0-80
    classification: str  # TRU_COT / AN_TOAN / TIEM_NANG / CO_HOI / RUI_RO
    category: str
    suggested_level: str  # L1-L5


@dataclass
class SentinelCoin:
    """Asset identity from Sentinel 01_ASSET_IDENTITY tab."""

    cic_id: str
    symbol: str
    name: str
    tier: str
    fa_status: str
    cic_action: str


@dataclass
class NQ05Term:
    """NQ05 compliance term from Sentinel blacklist."""

    term: str
    language: str  # VI / EN
    category: str
    severity: str  # BLOCK / WARN
    safe_alternative: str
    source_system: str  # sentinel / daily_report / shared


@dataclass
class SentinelData:
    """Aggregated data from all Sentinel tabs."""

    season: SentinelSeason | None = None
    sonicr_btc: SonicRZones | None = None
    sonicr_eth: SonicRZones | None = None
    fa_top_movers: list[SentinelFAScore] = field(default_factory=list)
    registry: list[SentinelCoin] = field(default_factory=list)
    nq05_blacklist: list[NQ05Term] = field(default_factory=list)
    read_timestamp: str = ""
    stale_flags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# SentinelReader
# ---------------------------------------------------------------------------


class SentinelReader:
    """Cross-read client for the CIC-Sentinel spreadsheet.

    WHY separate from SheetsClient: Sentinel is a DIFFERENT spreadsheet
    (SENTINEL_SPREADSHEET_ID) with a different tab schema. Reusing
    SheetsClient would couple the two systems and complicate error handling.
    """

    def __init__(self, credentials_b64: str = "", sentinel_spreadsheet_id: str = ""):
        self._credentials_b64 = credentials_b64 or os.getenv("GOOGLE_SHEETS_CREDENTIALS", "")
        self._spreadsheet_id = sentinel_spreadsheet_id or os.getenv("SENTINEL_SPREADSHEET_ID", "")
        self._spreadsheet: gspread.Spreadsheet | None = None

    def _connect(self) -> gspread.Spreadsheet:
        """Lazy connection to Sentinel spreadsheet."""
        if self._spreadsheet is not None:
            return self._spreadsheet

        if not self._credentials_b64 or not self._spreadsheet_id:
            raise ConnectionError("Missing GOOGLE_SHEETS_CREDENTIALS or SENTINEL_SPREADSHEET_ID")

        creds_json = json.loads(base64.b64decode(self._credentials_b64))
        creds = Credentials.from_service_account_info(
            creds_json,
            scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
        )
        client = gspread.authorize(creds)
        self._spreadsheet = client.open_by_key(self._spreadsheet_id)
        logger.info(f"Connected to Sentinel spreadsheet: {self._spreadsheet_id}")
        return self._spreadsheet

    def read_all(self) -> SentinelData:
        """Batch-read all Sentinel tabs. Each read is independent.

        If Sentinel is unreachable, returns empty SentinelData with
        stale_flags=["sentinel_unreachable"]. Pipeline continues without.
        """
        now = datetime.now(timezone.utc).isoformat()
        stale_flags: list[str] = []

        try:
            self._connect()
        except Exception as e:
            logger.warning(f"Sentinel unreachable: {e}")
            return SentinelData(
                read_timestamp=now,
                stale_flags=["sentinel_unreachable"],
            )

        # WHY: Each read wrapped independently — partial success is better than total failure
        season = None
        try:
            season = self.read_season()
            if season and _is_season_stale(season.last_update):
                stale_flags.append("season_stale")
        except Exception as e:
            logger.warning(f"Sentinel season read failed: {e}")
            stale_flags.append("season_read_error")

        sonicr_btc = None
        try:
            sonicr_btc = self.read_sonicr("BTC")
        except Exception as e:
            logger.warning(f"Sentinel SonicR BTC read failed: {e}")
            stale_flags.append("sonicr_btc_error")

        sonicr_eth = None
        try:
            sonicr_eth = self.read_sonicr("ETH")
        except Exception as e:
            logger.warning(f"Sentinel SonicR ETH read failed: {e}")
            stale_flags.append("sonicr_eth_error")

        fa_top = []
        try:
            fa_top = self.read_fa_scores()
        except Exception as e:
            logger.warning(f"Sentinel FA scores read failed: {e}")
            stale_flags.append("fa_scores_error")

        registry = []
        try:
            registry = self.read_registry()
        except Exception as e:
            logger.warning(f"Sentinel registry read failed: {e}")
            stale_flags.append("registry_error")

        nq05 = []
        try:
            nq05 = self.read_nq05_blacklist()
        except Exception as e:
            logger.warning(f"Sentinel NQ05 read failed: {e}")
            stale_flags.append("nq05_error")

        return SentinelData(
            season=season,
            sonicr_btc=sonicr_btc,
            sonicr_eth=sonicr_eth,
            fa_top_movers=fa_top,
            registry=registry,
            nq05_blacklist=nq05,
            read_timestamp=now,
            stale_flags=stale_flags,
        )

    def read_season(self) -> SentinelSeason | None:
        """Read season data from Sentinel CONFIG tab.

        Looks for rows keyed by: OFFICIAL_SEASON, SEASON_HEAT_SCORE,
        SEASON_CONFIDENCE, SEASON_DETAIL, SEASON_LAST_UPDATE.
        """
        ss = self._connect()
        ws = ss.worksheet("CONFIG")
        rows = ws.get_all_values()

        # Build key→value map from CONFIG rows (col A = key, col B = value)
        config_map: dict[str, str] = {}
        for row in rows:
            if len(row) >= 2 and row[0]:
                config_map[row[0].strip()] = row[1].strip()

        phase = config_map.get("OFFICIAL_SEASON", "")
        if not phase:
            return None

        return SentinelSeason(
            phase=phase,
            heat_score=_safe_float(config_map.get("SEASON_HEAT_SCORE", "0")),
            confidence=_safe_float(config_map.get("SEASON_CONFIDENCE", "0")),
            detail=config_map.get("SEASON_DETAIL", ""),
            last_update=config_map.get("SEASON_LAST_UPDATE", ""),
        )

    def read_sonicr(self, symbol: str) -> SonicRZones | None:
        """Read SonicR zones from 03_SCORING_ENGINE tab for a given symbol."""
        ss = self._connect()
        ws = ss.worksheet("03_SCORING_ENGINE")
        rows = ws.get_all_values()

        if not rows:
            return None

        # WHY: Find header row first, then locate symbol row.
        # Sentinel tab structure may vary — use header-based column lookup.
        header = [h.strip().upper() for h in rows[0]]
        symbol_col = _find_col(header, ("SYMBOL", "MA_COIN"))
        if symbol_col is None:
            return None

        for row in rows[1:]:
            if len(row) <= symbol_col:
                continue
            if row[symbol_col].strip().upper() == symbol.upper():
                return SonicRZones(
                    symbol=symbol.upper(),
                    ema34=_safe_float(_get_col(row, header, ("EMA34", "EMA_34"))),
                    ema89=_safe_float(_get_col(row, header, ("EMA89", "EMA_89"))),
                    ema200=_safe_float(_get_col(row, header, ("EMA200", "EMA_200"))),
                    ema610=_safe_float(_get_col(row, header, ("EMA610", "EMA_610"))),
                    sonicr_trend=_get_col(row, header, ("SONICR_TREND", "TREND")),
                    fib_adca_zone=_get_col(row, header, ("FIB_ADCA_ZONE", "ADCA_ZONE")),
                    rsi_d1=_safe_float(_get_col(row, header, ("RSI_D1", "RSI"))),
                )

        return None

    def read_fa_scores(self, top_n: int = 20) -> list[SentinelFAScore]:
        """Read FA scores from 06_FA_SCORES tab, sorted by total_score desc."""
        ss = self._connect()
        ws = ss.worksheet("06_FA_SCORES")
        rows = ws.get_all_values()

        if len(rows) < 2:
            return []

        header = [h.strip().upper() for h in rows[0]]
        results: list[SentinelFAScore] = []

        for row in rows[1:]:
            symbol = _get_col(row, header, ("SYMBOL", "MA_COIN"))
            if not symbol:
                continue
            total = _safe_float(_get_col(row, header, ("TOTAL_SCORE", "DIEM_TONG")))
            results.append(
                SentinelFAScore(
                    symbol=symbol,
                    total_score=total,
                    classification=_get_col(row, header, ("CLASSIFICATION", "PHAN_LOAI")),
                    category=_get_col(row, header, ("CATEGORY", "DANH_MUC")),
                    suggested_level=_get_col(row, header, ("SUGGESTED_LEVEL", "MUC_DE_XUAT")),
                )
            )

        # WHY: Sort descending so top movers are first
        results.sort(key=lambda x: x.total_score, reverse=True)
        return results[:top_n]

    def read_registry(self) -> list[SentinelCoin]:
        """Read all coins from 01_ASSET_IDENTITY tab."""
        ss = self._connect()
        ws = ss.worksheet("01_ASSET_IDENTITY")
        rows = ws.get_all_values()

        if len(rows) < 2:
            return []

        header = [h.strip().upper() for h in rows[0]]
        results: list[SentinelCoin] = []

        for row in rows[1:]:
            cic_id = _get_col(row, header, ("CIC_ID", "ID"))
            symbol = _get_col(row, header, ("SYMBOL", "MA_COIN"))
            if not symbol:
                continue
            results.append(
                SentinelCoin(
                    cic_id=cic_id,
                    symbol=symbol,
                    name=_get_col(row, header, ("NAME", "TEN")),
                    tier=_get_col(row, header, ("TIER", "CAP")),
                    fa_status=_get_col(row, header, ("FA_STATUS", "TRANG_THAI_FA")),
                    cic_action=_get_col(row, header, ("CIC_ACTION", "HANH_DONG")),
                )
            )

        return results

    def read_nq05_blacklist(self) -> list[NQ05Term]:
        """Read NQ05 blacklist from NQ05_BLACKLIST tab.

        WHY graceful: This tab may not exist yet in all Sentinel versions.
        Returns empty list if tab is missing.
        """
        ss = self._connect()
        try:
            ws = ss.worksheet("NQ05_BLACKLIST")
        except gspread.exceptions.WorksheetNotFound:
            logger.info("NQ05_BLACKLIST tab not found in Sentinel — returning empty")
            return []

        rows = ws.get_all_values()
        if len(rows) < 2:
            return []

        header = [h.strip().upper() for h in rows[0]]
        results: list[NQ05Term] = []

        for row in rows[1:]:
            term = _get_col(row, header, ("TERM", "TU_KHOA"))
            if not term:
                continue
            results.append(
                NQ05Term(
                    term=term,
                    language=_get_col(row, header, ("LANGUAGE", "NGON_NGU")) or "VI",
                    category=_get_col(row, header, ("CATEGORY", "DANH_MUC")),
                    severity=_get_col(row, header, ("SEVERITY", "MUC_DO")) or "BLOCK",
                    safe_alternative=_get_col(
                        row, header, ("SAFE_ALTERNATIVE", "THAY_THE_AN_TOAN")
                    ),
                    source_system=_get_col(row, header, ("SOURCE_SYSTEM", "HE_THONG_NGUON"))
                    or "sentinel",
                )
            )

        return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_float(val: str) -> float:
    """Parse string to float, returning 0.0 on failure."""
    try:
        return float(val.replace(",", "").strip()) if val else 0.0
    except (ValueError, AttributeError):
        return 0.0


def _find_col(header: list[str], candidates: tuple[str, ...]) -> int | None:
    """Find column index matching any candidate name."""
    for i, h in enumerate(header):
        if h in candidates:
            return i
    return None


def _get_col(row: list[str], header: list[str], candidates: tuple[str, ...]) -> str:
    """Get cell value by column name candidates. Returns '' if not found."""
    idx = _find_col(header, candidates)
    if idx is not None and idx < len(row):
        return row[idx].strip()
    return ""


def _is_season_stale(last_update: str) -> bool:
    """Check if season last_update is older than STALE_THRESHOLD_SEC."""
    if not last_update:
        return True
    try:
        # Try ISO format first
        dt = datetime.fromisoformat(last_update.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - dt).total_seconds()
        return age > STALE_THRESHOLD_SEC
    except (ValueError, TypeError):
        return True


def format_sentinel_for_llm(data: SentinelData) -> str:
    """Format SentinelData for LLM context injection.

    Used by build_master_context() to add Sentinel data to the Master prompt.
    """
    if not data or data.stale_flags == ["sentinel_unreachable"]:
        return ""

    parts: list[str] = ["=== DU LIEU TU CIC SENTINEL ==="]

    # Season
    if data.season:
        s = data.season
        stale_note = " (DU LIEU CU)" if "season_stale" in data.stale_flags else ""
        parts.append(
            f"Mua vu: {s.phase} | Heat Score: {s.heat_score}/100 | "
            f"Confidence: {s.confidence:.0%}{stale_note}"
        )
        if s.detail:
            parts.append(f"  Chi tiet: {s.detail}")

    # SonicR zones
    for label, zones in [("BTC", data.sonicr_btc), ("ETH", data.sonicr_eth)]:
        if zones:
            parts.append(
                f"SonicR {label}: Trend={zones.sonicr_trend} | "
                f"EMA34={zones.ema34:,.0f} | EMA89={zones.ema89:,.0f} | "
                f"EMA200={zones.ema200:,.0f} | RSI_D1={zones.rsi_d1:.1f}"
            )

    # FA top movers
    if data.fa_top_movers:
        top5 = data.fa_top_movers[:5]
        fa_lines = [f"  {fa.symbol}: {fa.total_score}/80 ({fa.classification})" for fa in top5]
        parts.append("FA Top:\n" + "\n".join(fa_lines))

    return "\n".join(parts)
