"""DR_EXPORT tab exporter (QO.40).

Persists Daily Report summary data to a new Google Sheet tab so
CIC-Sentinel can cross-read pipeline outputs. Written at the end
of each daily pipeline run (after generation, before final status).

Tab: DR_EXPORT — one row per daily run with key metrics.
WHY separate tab: Sentinel needs a clean, stable schema to read
from. Mixing with NHAT_KY_PIPELINE would couple logging with data export.
"""

from __future__ import annotations

from datetime import datetime, timezone

from cic_daily_report.core.logger import get_logger

logger = get_logger("dr_exporter")

# DR_EXPORT tab column headers (Vietnamese with diacritics per project rules)
DR_EXPORT_HEADERS = [
    "Ngày",
    "BTC Giá",
    "ETH Giá",
    "F&G Index",
    "Sentiment",
    "Consensus Labels",
    "Top News",
    "Số bài viết",
    "Quality Gate Pass Rate",
    "Breaking Events Today",
]


def export_daily_summary(
    sheets_client: object,
    date: str = "",
    btc_price: float = 0.0,
    eth_price: float = 0.0,
    fg_index: int = 0,
    market_sentiment: str = "",
    consensus_labels: str = "",
    top_news_summary: str = "",
    articles_generated: int = 0,
    quality_pass_rate: float = 0.0,
    breaking_events_today: int = 0,
) -> bool:
    """Write a summary row to DR_EXPORT tab.

    Args:
        sheets_client: SheetsClient instance (already connected).
        date: ISO date string (defaults to today UTC).
        btc_price: Current BTC price in USD.
        eth_price: Current ETH price in USD.
        fg_index: Fear & Greed index value (0-100).
        market_sentiment: Overall market sentiment label.
        consensus_labels: Pipe-separated consensus labels (e.g., "BTC:BULLISH|ETH:NEUTRAL").
        top_news_summary: Truncated top news (max 200 chars).
        articles_generated: Total articles generated in this run.
        quality_pass_rate: Quality gate pass rate (0.0-1.0).
        breaking_events_today: Number of breaking events sent today.

    Returns:
        True if export succeeded, False otherwise.

    WHY bool return: Caller (daily_pipeline) wraps in try/except and logs warning.
    Returning False lets caller log without raising.
    """
    if not date:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # WHY truncate: Google Sheets cells have 50K char limit, but Sentinel
    # reads this via API — keep it compact for reliable parsing.
    truncated_news = top_news_summary[:200] if top_news_summary else ""

    row = [
        date,
        str(round(btc_price, 2)),
        str(round(eth_price, 2)),
        str(fg_index),
        market_sentiment,
        consensus_labels,
        truncated_news,
        str(articles_generated),
        str(round(quality_pass_rate, 2)),
        str(breaking_events_today),
    ]

    try:
        _ensure_tab_exists(sheets_client)
        sheets_client.batch_append("DR_EXPORT", [row])
        logger.info(f"DR_EXPORT: written summary for {date}")
        return True
    except Exception as e:
        # WHY: Never break pipeline if export fails — this is supplementary data.
        logger.warning(f"DR_EXPORT write failed: {e}")
        return False


def _ensure_tab_exists(sheets_client: object) -> None:
    """Create DR_EXPORT tab with headers if it doesn't exist.

    WHY lazy creation: Tab may not exist on first run. Creating it
    inline avoids requiring a migration step.
    """
    try:
        ss = sheets_client._connect()  # type: ignore[attr-defined]
        existing = {ws.title for ws in ss.worksheets()}
        if "DR_EXPORT" not in existing:
            # WHY 1000 rows: 100 was too small — daily runs accumulate ~365 rows/year.
            ws = ss.add_worksheet(title="DR_EXPORT", rows=1000, cols=len(DR_EXPORT_HEADERS))
            ws.update([DR_EXPORT_HEADERS], value_input_option="RAW")
            logger.info("Created DR_EXPORT tab with headers")
    except Exception as e:
        logger.warning(f"DR_EXPORT tab creation check failed: {e}")
        # WHY: Don't raise — batch_append will fail on its own if tab missing,
        # and the caller handles that gracefully.
