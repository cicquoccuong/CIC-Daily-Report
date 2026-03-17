"""Data Quality Monitor (Phase 3b) — scores data completeness before generation.

Detects degraded data conditions and produces a quality report that:
1. Warns the pipeline when data is too thin for meaningful analysis
2. Provides quality notes to the LLM so it adjusts expectations
3. Logs actionable warnings for debugging API failures
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cic_daily_report.collectors.market_data import MarketDataPoint
from cic_daily_report.collectors.onchain_data import OnChainMetric
from cic_daily_report.core.logger import get_logger

logger = get_logger("data_quality")

# Expected minimum counts for each data category
_EXPECTED_NEWS = 10
_EXPECTED_MARKET = 5
_EXPECTED_ONCHAIN = 2


@dataclass
class DataQualityReport:
    """Quality assessment of collected data before generation."""

    score: int  # 0-100
    grade: str  # "A" (≥80), "B" (≥60), "C" (≥40), "D" (≥20), "F" (<20)
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_degraded(self) -> bool:
        """True if data quality is below acceptable threshold (C or worse)."""
        return self.score < 40

    def format_for_llm(self) -> str:
        """Format quality notes for LLM context (warns about missing data)."""
        if not self.warnings:
            return ""
        lines = [
            f"⚠️ CHẤT LƯỢNG DỮ LIỆU: {self.grade} ({self.score}/100)",
            "Lưu ý khi viết bài:",
        ]
        for w in self.warnings:
            lines.append(f"  • {w}")
        return "\n".join(lines)

    def format_for_log(self) -> str:
        """Format for pipeline log entry."""
        parts = [f"Data Quality: {self.grade} ({self.score}/100)"]
        if self.issues:
            parts.append(f"Issues: {'; '.join(self.issues)}")
        return " | ".join(parts)


def assess_data_quality(
    news_count: int,
    market_data: list[MarketDataPoint],
    onchain_data: list[OnChainMetric],
    has_sector_data: bool = False,
    has_econ_calendar: bool = False,
) -> DataQualityReport:
    """Score the quality/completeness of collected data.

    Scoring breakdown (100 total):
      - News: 25 pts (proportional to count vs expected)
      - Market data: 25 pts (BTC price required, more coins = more points)
      - On-chain/derivatives: 20 pts (Funding Rate, OI, Long/Short)
      - Sector data: 15 pts (CoinGecko categories + DefiLlama TVL)
      - Economic calendar: 15 pts
    """
    score = 0
    issues: list[str] = []
    warnings: list[str] = []

    # --- News (25 pts) ---
    if news_count >= _EXPECTED_NEWS:
        score += 25
    elif news_count > 0:
        score += int(25 * news_count / _EXPECTED_NEWS)
        issues.append(f"Only {news_count} news (expected ≥{_EXPECTED_NEWS})")
        warnings.append(
            f"Chỉ có {news_count} tin tức (ít hơn bình thường) — phân tích tin có thể chưa đầy đủ"
        )
    else:
        issues.append("No news collected")
        warnings.append("KHÔNG CÓ tin tức — chỉ phân tích từ dữ liệu giá và on-chain")

    # --- Market data (25 pts) ---
    crypto_coins = [p for p in market_data if p.data_type == "crypto"]
    has_btc = any(p.symbol == "BTC" for p in crypto_coins)

    if has_btc:
        score += 10  # BTC is critical
    else:
        issues.append("BTC price missing")
        warnings.append("KHÔNG CÓ giá BTC — dữ liệu thị trường không đáng tin cậy")

    if len(crypto_coins) >= _EXPECTED_MARKET:
        score += 15
    elif len(crypto_coins) > 0:
        score += int(15 * len(crypto_coins) / _EXPECTED_MARKET)
        issues.append(f"Only {len(crypto_coins)} crypto prices")
    else:
        issues.append("No crypto prices")
        warnings.append("KHÔNG CÓ dữ liệu giá — bài viết sẽ rất hạn chế")

    # --- On-chain (20 pts) ---
    has_funding = any(m.metric_name == "BTC_Funding_Rate" for m in onchain_data)
    has_oi = any(m.metric_name == "BTC_Open_Interest" for m in onchain_data)
    has_ls = any(m.metric_name == "BTC_Long_Short_Ratio" for m in onchain_data)

    onchain_score = 0
    if has_funding:
        onchain_score += 8
    if has_oi:
        onchain_score += 6
    if has_ls:
        onchain_score += 6
    score += onchain_score

    if onchain_score == 0:
        issues.append("No derivatives data (all providers failed)")
        warnings.append(
            "KHÔNG CÓ dữ liệu derivatives (Funding Rate, OI) — "
            "L3-L5 BỎ QUA phần on-chain, KHÔNG bịa số liệu"
        )
    elif onchain_score < 14:
        missing = []
        if not has_funding:
            missing.append("Funding Rate")
        if not has_oi:
            missing.append("OI")
        if not has_ls:
            missing.append("Long/Short")
        issues.append(f"Partial derivatives: missing {', '.join(missing)}")

    # --- Sector data (15 pts) ---
    if has_sector_data:
        score += 15
    else:
        issues.append("No sector data (CoinGecko/DefiLlama)")
        warnings.append("KHÔNG CÓ dữ liệu sector — không phân tích được dòng tiền theo nhóm")

    # --- Economic calendar (15 pts) ---
    if has_econ_calendar:
        score += 15
    else:
        issues.append("No economic calendar")

    # --- Determine grade ---
    if score >= 80:
        grade = "A"
    elif score >= 60:
        grade = "B"
    elif score >= 40:
        grade = "C"
    elif score >= 20:
        grade = "D"
    else:
        grade = "F"

    report = DataQualityReport(
        score=score,
        grade=grade,
        issues=issues,
        warnings=warnings,
    )

    log_level = "info" if score >= 60 else "warning"
    getattr(logger, log_level)(report.format_for_log())

    return report
