"""Metrics Engine (Phase 1a/1b/1d) — pre-computed data interpretation.

Replaces LLM guessing with deterministic rules. Three components:
  1a. Metrics Interpreter — structured interpretation of raw metrics
  1b. Market Regime — classify Bull/Bear/Recovery/Distribution
  1d. Narrative Detection — keyword clustering from RSS news titles

Output is structured text that the LLM uses as pre-analyzed context,
so AI writes insights instead of guessing what numbers mean.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cic_daily_report.collectors.market_data import MarketDataPoint
from cic_daily_report.collectors.onchain_data import OnChainMetric
from cic_daily_report.core.logger import get_logger

logger = get_logger("metrics_engine")


# ---------------------------------------------------------------------------
# 1b. Market Regime
# ---------------------------------------------------------------------------

REGIME_BULL = "Bull"
REGIME_BEAR = "Bear"
REGIME_RECOVERY = "Recovery"
REGIME_DISTRIBUTION = "Distribution"
REGIME_NEUTRAL = "Neutral"


@dataclass
class MarketRegime:
    """Classified market state with reasoning."""

    regime: str  # Bull / Bear / Recovery / Distribution / Neutral
    confidence: str  # "high" / "medium" / "low"
    signals: list[str] = field(default_factory=list)

    def format_vi(self) -> str:
        """Format for Vietnamese LLM context."""
        regime_vi = {
            REGIME_BULL: "TĂNG TRƯỞNG (Bull Market)",
            REGIME_BEAR: "SUY GIẢM (Bear Market)",
            REGIME_RECOVERY: "PHỤC HỒI (Recovery)",
            REGIME_DISTRIBUTION: "PHÂN PHỐI (Distribution)",
            REGIME_NEUTRAL: "ĐI NGANG (Neutral/Sideways)",
        }
        conf_vi = {"high": "cao", "medium": "trung bình", "low": "thấp"}
        lines = [
            f"TRẠNG THÁI THỊ TRƯỜNG: {regime_vi.get(self.regime, self.regime)} "
            f"(độ tin cậy: {conf_vi.get(self.confidence, self.confidence)})",
        ]
        for s in self.signals:
            lines.append(f"  → {s}")
        return "\n".join(lines)


def classify_market_regime(
    market_data: list[MarketDataPoint],
    onchain_data: list[OnChainMetric],
    key_metrics: dict[str, object],
) -> MarketRegime:
    """Classify current market regime from available data.

    Uses a simple scoring system:
      bullish signals: +1 each, bearish signals: -1 each
      Score >= 2 → Bull, <= -2 → Bear, etc.
    """
    score = 0
    signals: list[str] = []

    # --- BTC price action ---
    btc_change_24h = None
    for p in market_data:
        if p.symbol == "BTC" and p.data_type == "crypto":
            btc_change_24h = p.change_24h
            break

    if btc_change_24h is not None:
        if btc_change_24h >= 5:
            score += 2
            signals.append(f"BTC tăng mạnh {btc_change_24h:+.1f}% trong 24h")
        elif btc_change_24h >= 2:
            score += 1
            signals.append(f"BTC tăng {btc_change_24h:+.1f}% trong 24h")
        elif btc_change_24h <= -5:
            score -= 2
            signals.append(f"BTC giảm mạnh {btc_change_24h:+.1f}% trong 24h")
        elif btc_change_24h <= -2:
            score -= 1
            signals.append(f"BTC giảm {btc_change_24h:+.1f}% trong 24h")
        else:
            signals.append(f"BTC đi ngang ({btc_change_24h:+.1f}% trong 24h)")

    # --- Fear & Greed ---
    fg_raw = key_metrics.get("Fear & Greed")
    if isinstance(fg_raw, int):
        if fg_raw >= 75:
            score += 1
            signals.append(
                f"Fear & Greed = {fg_raw} (Extreme Greed) — tâm lý tham lam cực độ, "
                "lịch sử cho thấy rủi ro điều chỉnh cao"
            )
        elif fg_raw >= 55:
            score += 1
            signals.append(f"Fear & Greed = {fg_raw} (Greed) — sentiment tích cực")
        elif fg_raw <= 20:
            score -= 1
            signals.append(
                f"Fear & Greed = {fg_raw} (Extreme Fear) — hoảng loạn, "
                "thường là vùng đáy ngắn hạn trong lịch sử"
            )
        elif fg_raw <= 40:
            score -= 1
            signals.append(f"Fear & Greed = {fg_raw} (Fear) — thận trọng")
        else:
            signals.append(f"Fear & Greed = {fg_raw} (Neutral)")

    # --- Altcoin Season ---
    alt_season = key_metrics.get("Altcoin Season")
    if isinstance(alt_season, int):
        if alt_season >= 75:
            score += 1
            signals.append(
                f"Altcoin Season Index = {alt_season} — dòng tiền đang chảy mạnh vào altcoin"
            )
        elif alt_season <= 25:
            score -= 1 if score < 0 else 0  # only bearish signal if already bearish
            signals.append(f"Altcoin Season Index = {alt_season} — BTC dominance, altcoin yếu")

    # --- DXY ---
    dxy_val = key_metrics.get("DXY")
    if isinstance(dxy_val, (int, float)):
        if dxy_val >= 105:
            score -= 1
            signals.append(f"DXY = {dxy_val:.1f} (USD mạnh) — thường gây áp lực giảm lên crypto")
        elif dxy_val <= 100:
            score += 1
            signals.append(f"DXY = {dxy_val:.1f} (USD yếu) — thường hỗ trợ crypto")

    # --- Funding Rate ---
    for m in onchain_data:
        if m.metric_name == "BTC_Funding_Rate":
            fr_pct = m.value * 100
            if fr_pct > 0.05:
                # Extreme positive = overheated, distribution risk
                signals.append(
                    f"Funding Rate = {fr_pct:.4f}% (cao bất thường) — "
                    "long trả phí cao, rủi ro squeeze nếu giá giảm"
                )
            elif fr_pct < -0.01:
                signals.append(
                    f"Funding Rate = {fr_pct:.4f}% (âm) — "
                    "short trả phí, thường báo hiệu bán quá mức"
                )

    # --- Determine regime ---
    if score >= 3:
        regime, confidence = REGIME_BULL, "high"
    elif score == 2:
        regime, confidence = REGIME_BULL, "medium"
    elif score <= -3:
        regime, confidence = REGIME_BEAR, "high"
    elif score == -2:
        regime, confidence = REGIME_BEAR, "medium"
    elif score == 1:
        # Mild positive: if coming from fear, it's recovery
        if isinstance(fg_raw, int) and fg_raw <= 40:
            regime, confidence = REGIME_RECOVERY, "medium"
        else:
            regime, confidence = REGIME_BULL, "low"
    elif score == -1:
        # Mild negative: if coming from greed, it's distribution
        if isinstance(fg_raw, int) and fg_raw >= 60:
            regime, confidence = REGIME_DISTRIBUTION, "medium"
        else:
            regime, confidence = REGIME_BEAR, "low"
    else:
        regime, confidence = REGIME_NEUTRAL, "medium"

    logger.info(f"Market regime: {regime} (score={score}, confidence={confidence})")
    return MarketRegime(regime=regime, confidence=confidence, signals=signals)


# ---------------------------------------------------------------------------
# 1a. Metrics Interpreter
# ---------------------------------------------------------------------------


@dataclass
class MetricsInterpretation:
    """Structured interpretation of all available metrics."""

    regime: MarketRegime
    derivatives_analysis: str  # Funding Rate + OI + Long/Short
    macro_analysis: str  # DXY, Gold, correlation
    sentiment_analysis: str  # F&G, Altcoin Season
    volume_analysis: str  # Volume patterns
    cross_signal_summary: str  # Signals agree or conflict?

    def format_for_tier(self, tier: str) -> str:
        """Return tier-appropriate interpretation text.

        L1-L2: regime + sentiment only
        L3: + derivatives + macro
        L4: + cross-signal conflicts
        L5: all analysis
        """
        parts = [self.regime.format_vi()]

        if tier in ("L1", "L2"):
            parts.append(f"\nSENTIMENT:\n{self.sentiment_analysis}")
        elif tier == "L3":
            parts.append(f"\nSENTIMENT:\n{self.sentiment_analysis}")
            parts.append(f"\nDERIVATIVES:\n{self.derivatives_analysis}")
            parts.append(f"\nMACRO:\n{self.macro_analysis}")
        elif tier == "L4":
            parts.append(f"\nDERIVATIVES:\n{self.derivatives_analysis}")
            parts.append(f"\nMACRO:\n{self.macro_analysis}")
            parts.append(f"\nTÍN HIỆU MÂU THUẪN:\n{self.cross_signal_summary}")
        else:  # L5
            parts.append(f"\nSENTIMENT:\n{self.sentiment_analysis}")
            parts.append(f"\nDERIVATIVES:\n{self.derivatives_analysis}")
            parts.append(f"\nMACRO:\n{self.macro_analysis}")
            parts.append(f"\nVOLUME:\n{self.volume_analysis}")
            parts.append(f"\nTỔNG HỢP TÍN HIỆU:\n{self.cross_signal_summary}")

        return "\n".join(parts)


def interpret_metrics(
    market_data: list[MarketDataPoint],
    onchain_data: list[OnChainMetric],
    key_metrics: dict[str, object],
) -> MetricsInterpretation:
    """Pre-compute structured interpretation of all available metrics."""
    regime = classify_market_regime(market_data, onchain_data, key_metrics)

    derivatives = _analyze_derivatives(onchain_data)
    macro = _analyze_macro(market_data, key_metrics)
    sentiment = _analyze_sentiment(key_metrics)
    volume = _analyze_volume(market_data)
    cross = _analyze_cross_signals(market_data, onchain_data, key_metrics)

    return MetricsInterpretation(
        regime=regime,
        derivatives_analysis=derivatives,
        macro_analysis=macro,
        sentiment_analysis=sentiment,
        volume_analysis=volume,
        cross_signal_summary=cross,
    )


def _analyze_derivatives(onchain_data: list[OnChainMetric]) -> str:
    """Interpret derivatives metrics with pre-computed conclusions."""
    parts: list[str] = []
    funding_rate = None
    oi_value = None
    long_short = None

    for m in onchain_data:
        if m.metric_name == "BTC_Funding_Rate":
            funding_rate = m.value
        elif m.metric_name == "BTC_Open_Interest":
            oi_value = m.value
        elif m.metric_name == "BTC_Long_Short_Ratio":
            long_short = m.value

    if funding_rate is not None:
        fr_pct = funding_rate * 100
        if fr_pct > 0.05:
            parts.append(
                f"• Funding Rate = {fr_pct:.4f}% → CẢNH BÁO: Long đang trả phí rất cao. "
                "Thị trường quá lạc quan, rủi ro long squeeze tăng nếu giá giảm đột ngột. "
                "Lịch sử: funding rate > 0.05% thường dẫn đến điều chỉnh ngắn hạn."
            )
        elif fr_pct > 0.01:
            parts.append(
                f"• Funding Rate = {fr_pct:.4f}% → Dương nhẹ: long chiếm ưu thế, "
                "thị trường thiên về lạc quan. Mức bình thường, chưa có tín hiệu cực đoan."
            )
        elif fr_pct < -0.01:
            parts.append(
                f"• Funding Rate = {fr_pct:.4f}% → Âm: Short đang trả phí cho long. "
                "Thị trường bị bán quá mức, thường là dấu hiệu đáy ngắn hạn."
            )
        else:
            parts.append(
                f"• Funding Rate = {fr_pct:.4f}% → Trung tính: không có áp lực rõ ràng "
                "từ thị trường derivatives."
            )
    else:
        parts.append("• Funding Rate: Không có dữ liệu")

    if oi_value is not None:
        oi_b = oi_value / 1e9 if oi_value > 1e6 else oi_value
        if oi_b > 1:
            parts.append(f"• Open Interest = {oi_b:.2f}B contracts")
        else:
            parts.append(f"• Open Interest = {oi_value:,.0f} contracts")
    else:
        parts.append("• Open Interest: Không có dữ liệu")

    if long_short is not None:
        if long_short > 1.5:
            parts.append(
                f"• Long/Short Ratio = {long_short:.2f} → Rất thiên long. "
                "Nhiều trader đang đặt cược tăng giá. Rủi ro: nếu giá giảm, "
                "cascade liquidation có thể xảy ra."
            )
        elif long_short > 1.0:
            parts.append(
                f"• Long/Short Ratio = {long_short:.2f} → Thiên long nhẹ. "
                "Đa số trader kỳ vọng tăng giá."
            )
        elif long_short < 0.7:
            parts.append(
                f"• Long/Short Ratio = {long_short:.2f} → Thiên short mạnh. "
                "Nhiều trader đặt cược giảm giá. Nếu giá bật lên, short squeeze có thể xảy ra."
            )
        elif long_short < 1.0:
            parts.append(
                f"• Long/Short Ratio = {long_short:.2f} → Thiên short nhẹ. Đa số trader thận trọng."
            )
    else:
        parts.append("• Long/Short Ratio: Không có dữ liệu")

    return "\n".join(parts) if parts else "Không có dữ liệu derivatives."


def _analyze_macro(
    market_data: list[MarketDataPoint],
    key_metrics: dict[str, object],
) -> str:
    """Interpret macro indicators."""
    parts: list[str] = []

    dxy = key_metrics.get("DXY")
    if isinstance(dxy, (int, float)):
        if dxy >= 105:
            parts.append(
                f"• DXY = {dxy:.1f} (USD mạnh) → Áp lực GIẢM lên crypto. "
                "USD mạnh khiến tài sản rủi ro kém hấp dẫn hơn."
            )
        elif dxy <= 100:
            parts.append(
                f"• DXY = {dxy:.1f} (USD yếu) → HỖ TRỢ crypto. "
                "USD yếu thường khiến dòng tiền tìm tài sản thay thế."
            )
        else:
            parts.append(f"• DXY = {dxy:.1f} → Vùng trung tính, chưa tạo áp lực rõ ràng.")

    gold = key_metrics.get("Gold")
    if gold:
        parts.append(f"• Gold = {gold} — tài sản trú ẩn an toàn truyền thống.")

    # BTC dominance
    btc_dom = key_metrics.get("BTC Dominance")
    if btc_dom:
        parts.append(f"• BTC Dominance = {btc_dom}")

    return "\n".join(parts) if parts else "Không có dữ liệu macro."


def _analyze_sentiment(key_metrics: dict[str, object]) -> str:
    """Interpret sentiment indicators."""
    parts: list[str] = []

    fg = key_metrics.get("Fear & Greed")
    if isinstance(fg, int):
        labels = {
            range(0, 21): "Extreme Fear — hoảng loạn, bán tháo",
            range(21, 41): "Fear — thận trọng, thiên về bán",
            range(41, 56): "Neutral — chờ đợi, không rõ hướng",
            range(56, 76): "Greed — lạc quan, thiên về mua",
            range(76, 101): "Extreme Greed — tham lam cực độ, rủi ro điều chỉnh cao",
        }
        label = "N/A"
        for r, desc in labels.items():
            if fg in r:
                label = desc
                break
        parts.append(f"• Fear & Greed Index = {fg} → {label}")

    alt_season = key_metrics.get("Altcoin Season")
    if isinstance(alt_season, int):
        if alt_season >= 75:
            parts.append(
                f"• Altcoin Season = {alt_season} → MÙA ALTCOIN: dòng tiền chảy mạnh vào altcoin, "
                "altcoin outperform BTC"
            )
        elif alt_season <= 25:
            parts.append(
                f"• Altcoin Season = {alt_season} → MÙA BTC: BTC outperform altcoin, "
                "vốn tập trung vào BTC"
            )
        else:
            parts.append(f"• Altcoin Season = {alt_season} → Không rõ ràng mùa BTC hay altcoin")

    return "\n".join(parts) if parts else "Không có dữ liệu sentiment."


def _analyze_volume(market_data: list[MarketDataPoint]) -> str:
    """Analyze volume patterns across top coins."""
    crypto_coins = [p for p in market_data if p.data_type == "crypto" and p.volume_24h > 0]

    if not crypto_coins:
        return "Không có dữ liệu volume."

    # Sort by volume
    by_vol = sorted(crypto_coins, key=lambda p: p.volume_24h, reverse=True)[:5]
    parts = ["Top 5 volume 24h:"]
    for p in by_vol:
        vol_m = p.volume_24h / 1e6
        parts.append(f"  • {p.symbol}: ${vol_m:,.0f}M (giá {p.change_24h:+.1f}%)")

    # Check for volume-price divergence on BTC
    for p in market_data:
        if p.symbol == "BTC" and p.data_type == "crypto":
            if p.change_24h < -2 and p.volume_24h > 0:
                parts.append(
                    f"→ BTC giảm {p.change_24h:.1f}% — kiểm tra volume: "
                    "nếu volume cao = bán chủ động, nếu volume thấp = thiếu lực mua"
                )
            elif p.change_24h > 2 and p.volume_24h > 0:
                parts.append(
                    f"→ BTC tăng {p.change_24h:.1f}% — volume cao xác nhận xu hướng, "
                    "volume thấp = bẫy tăng tiềm năng"
                )

    return "\n".join(parts)


def _analyze_cross_signals(
    market_data: list[MarketDataPoint],
    onchain_data: list[OnChainMetric],
    key_metrics: dict[str, object],
) -> str:
    """Identify agreement or conflict between signal types."""
    bullish: list[str] = []
    bearish: list[str] = []

    # Price action
    for p in market_data:
        if p.symbol == "BTC" and p.data_type == "crypto":
            if p.change_24h >= 2:
                bullish.append(f"BTC tăng {p.change_24h:+.1f}%")
            elif p.change_24h <= -2:
                bearish.append(f"BTC giảm {p.change_24h:+.1f}%")

    # Sentiment
    fg = key_metrics.get("Fear & Greed")
    if isinstance(fg, int):
        if fg >= 55:
            bullish.append(f"Sentiment tích cực (F&G={fg})")
        elif fg <= 40:
            bearish.append(f"Sentiment tiêu cực (F&G={fg})")

    # Derivatives
    for m in onchain_data:
        if m.metric_name == "BTC_Funding_Rate":
            fr = m.value * 100
            if fr > 0.01:
                bullish.append(f"Funding Rate dương ({fr:.4f}%)")
            elif fr < -0.01:
                bearish.append(f"Funding Rate âm ({fr:.4f}%)")

    # DXY (inverse)
    dxy = key_metrics.get("DXY")
    if isinstance(dxy, (int, float)):
        if dxy <= 100:
            bullish.append(f"USD yếu (DXY={dxy:.1f})")
        elif dxy >= 105:
            bearish.append(f"USD mạnh (DXY={dxy:.1f})")

    # Build summary
    if bullish and bearish:
        return (
            f"⚠️ TÍN HIỆU MÂU THUẪN:\n"
            f"  Tín hiệu tăng: {', '.join(bullish)}\n"
            f"  Tín hiệu giảm: {', '.join(bearish)}\n"
            f"  → Thị trường đang trong trạng thái KHÔNG RÕ RÀNG. "
            f"Cần thận trọng và theo dõi thêm."
        )
    elif bullish:
        return (
            f"✅ TÍN HIỆU ĐỒNG THUẬN TĂNG:\n"
            f"  {', '.join(bullish)}\n"
            f"  → Các chỉ số đang hướng cùng chiều tích cực."
        )
    elif bearish:
        return (
            f"🔻 TÍN HIỆU ĐỒNG THUẬN GIẢM:\n"
            f"  {', '.join(bearish)}\n"
            f"  → Các chỉ số đang hướng cùng chiều tiêu cực."
        )
    return "Không đủ dữ liệu để đánh giá tương quan tín hiệu."


# ---------------------------------------------------------------------------
# 1d. Narrative Detection
# ---------------------------------------------------------------------------

# Keyword groups for narrative clustering
_NARRATIVE_KEYWORDS: dict[str, list[str]] = {
    "ETF": ["etf", "spot etf", "bitcoin etf", "ethereum etf", "etf approval", "etf flow"],
    "Regulation": ["regulation", "sec", "cftc", "ban", "legal", "lawsuit", "compliance", "mica"],
    "DeFi": ["defi", "dex", "lending", "yield", "tvl", "liquidity", "aave", "uniswap"],
    "AI & Crypto": ["ai", "artificial intelligence", "machine learning", "gpu", "compute"],
    "Exchange": ["exchange", "binance", "coinbase", "kraken", "okx", "bybit", "listing"],
    "Hack/Security": ["hack", "exploit", "vulnerability", "stolen", "breach", "rug pull"],
    "Stablecoin": ["stablecoin", "usdt", "usdc", "dai", "peg", "depeg"],
    "Layer 2": ["layer 2", "l2", "rollup", "optimism", "arbitrum", "base", "zk"],
    "Bitcoin": ["bitcoin", "btc", "halving", "mining", "miner", "ordinals", "inscription"],
    "Ethereum": ["ethereum", "eth", "merge", "shanghai", "dencun", "blob"],
    "Meme/Social": ["meme", "memecoin", "doge", "shib", "pepe", "social"],
    "Macro": ["fed", "interest rate", "inflation", "cpi", "fomc", "treasury", "bond"],
    "Institutional": ["institutional", "blackrock", "fidelity", "grayscale", "custody", "whale"],
    "RWA": ["rwa", "real world asset", "tokenization", "tokenize"],
    "Gaming/NFT": ["nft", "gaming", "metaverse", "play to earn", "gamefi"],
}


@dataclass
class Narrative:
    """A detected market narrative/theme."""

    name: str
    mention_count: int
    sample_titles: list[str]  # up to 3 example headlines


def detect_narratives(
    news_items: list[dict[str, str]],
    min_mentions: int = 3,
) -> list[Narrative]:
    """Detect dominant narratives from news titles via keyword clustering.

    Args:
        news_items: List of dicts with at least "title" key.
        min_mentions: Minimum keyword hits to qualify as a narrative.

    Returns:
        List of Narrative objects sorted by mention count (descending).
    """
    counts: dict[str, int] = {}
    samples: dict[str, list[str]] = {}

    for item in news_items:
        title = item.get("title", "").lower()
        if not title:
            continue
        for narrative_name, keywords in _NARRATIVE_KEYWORDS.items():
            if any(kw in title for kw in keywords):
                counts[narrative_name] = counts.get(narrative_name, 0) + 1
                if narrative_name not in samples:
                    samples[narrative_name] = []
                if len(samples[narrative_name]) < 3:
                    samples[narrative_name].append(item.get("title", ""))

    narratives = [
        Narrative(name=name, mention_count=count, sample_titles=samples.get(name, []))
        for name, count in counts.items()
        if count >= min_mentions
    ]
    narratives.sort(key=lambda n: n.mention_count, reverse=True)

    logger.info(
        f"Narrative detection: {len(narratives)} themes found from {len(news_items)} articles"
    )
    return narratives


def format_narratives_for_llm(narratives: list[Narrative]) -> str:
    """Format detected narratives as LLM context."""
    if not narratives:
        return ""

    lines = ["CHỦ ĐỀ NÓNG HÔM NAY (phát hiện tự động từ tin tức):"]
    for n in narratives[:6]:  # top 6 narratives
        lines.append(f"• {n.name} ({n.mention_count} tin nhắc đến)")
        for title in n.sample_titles[:2]:
            lines.append(f'    - "{title}"')

    return "\n".join(lines)
