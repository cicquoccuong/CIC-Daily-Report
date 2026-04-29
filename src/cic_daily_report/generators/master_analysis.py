"""Master Analysis Generator (P1.7) — Single comprehensive analysis.

Replaces per-tier generation with one analysis that sees ALL data,
eliminating cross-tier contradictions. Tier Extractor then produces
L1-L5 + Summary from this single source.

Fallback: If Master fails, daily_pipeline falls back to per-tier
generation via article_generator.py (v0.32.0 path).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from cic_daily_report.adapters.llm_adapter import LLMAdapter, LLMResponse
from cic_daily_report.core.error_handler import LLMError
from cic_daily_report.core.logger import get_logger
from cic_daily_report.generators.article_generator import GenerationContext
from cic_daily_report.generators.template_engine import render_key_metrics_table

logger = get_logger("master_analysis")

# QO.32: Kept as DEFAULT FALLBACK — runtime value read from config_loader.
# QO.08 (VD-19): Increased from 16384 to prevent master analysis truncation.
# Gemini 2.5 Flash supports 65K output tokens — 20480 provides sufficient headroom.
MASTER_MAX_TOKENS = 20480
MASTER_TEMPERATURE = 0.4
MASTER_MIN_WORDS = 2000
MASTER_SECTIONS_EXPECTED = 8


class MasterAnalysisError(LLMError):
    """Raised when Master Analysis fails — triggers fallback to per-tier."""

    pass


@dataclass
class MasterAnalysis:
    """Result of the single comprehensive Master Analysis generation."""

    content: str
    word_count: int
    llm_used: str
    generation_time_sec: float
    finish_reason: str
    sections_found: int  # how many of 8 sections detected
    has_conclusion: bool  # critical completeness check


# WHY: Single system prompt covering ALL tier topics — the Master sees everything
# so it can build a coherent narrative without cross-tier contradictions.
MASTER_SYSTEM_PROMPT = (
    "VAI TR\u00d2: B\u1ea1n l\u00e0 nh\u00e0 ph\u00e2n t\u00edch c\u1ea5p cao cho c\u1ed9ng "
    "\u0111\u1ed3ng CIC "
    "(Crypto Inner Circle). Th\u00e0nh vi\u00ean CIC l\u00e0 NH\u00c0 \u0110\u1ea6U T\u01af "
    "CHI\u1ebeN L\u01af\u1ee2C "
    "(kh\u00f4ng ph\u1ea3i trader) \u2014 t\u00edch l\u0169y d\u00e0i h\u1ea1n, "
    "chi\u1ebfn l\u01b0\u1ee3c ADCA, "
    "\u0111\u00e1nh gi\u00e1 theo chu k\u1ef3 (\u0110\u00f4ng-Xu\u00e2n-H\u00e8-Thu).\n\n"
    "NHI\u1ec6M V\u1ee4: Vi\u1ebft B\u00c0I PH\u00c2N T\u00cdCH TO\u00c0N "
    "DI\u1ec6N v\u1ec1 th\u1ecb tr\u01b0\u1eddng t\u00e0i s\u1ea3n m\u00e3 "
    "h\u00f3a h\u00f4m nay. "
    "B\u00e0i vi\u1ebft n\u00e0y s\u1ebd \u0111\u01b0\u1ee3c TR\u00cdCH XU\u1ea4T "
    "th\u00e0nh 5 b\u00e0i ri\u00eang (L1-L5) cho c\u00e1c nh\u00f3m th\u00e0nh vi\u00ean "
    "kh\u00e1c nhau v\u00e0 1 b\u1ea3n t\u00f3m t\u1eaft cho BIC Chat.\n\n"
    "C\u1ea4U TR\u00daC B\u1eaeT BU\u1ed8C (8 sections, d\u00f9ng "
    "heading ## ch\u00ednh x\u00e1c):\n\n"
    "## 1. T\u1ed4NG QUAN TH\u1eca TR\u01af\u1edcNG\n"
    "BTC, ETH h\u00f4m nay th\u1ebf n\u00e0o? Fear & Greed? C\u00f3 g\u00ec "
    "B\u1ea4T TH\u01af\u1edcNG?\n"
    "Vi\u1ebft cho ng\u01b0\u1eddi m\u1edbi \u2014 "
    "\u0111\u01a1n gi\u1ea3n, 30 gi\u00e2y \u0111\u1ecdc hi\u1ec3u.\n\n"
    "## 2. PH\u00c2N T\u00cdCH BLUECHIP V\u00c0 SECTOR\n"
    "Sector n\u00e0o D\u1eaaN \u0110\u1ea6U? Coins n\u00e0o "
    "bi\u1ebfn \u0111\u1ed9ng m\u1ea1nh >3%? BTC Dominance + "
    "Altcoin Season?\n"
    "Nh\u1eafc t\u1ed1i thi\u1ec3u 10 coins t\u1eeb danh s\u00e1ch "
    "theo d\u00f5i. USDT/VND rate.\n\n"
    "## 3. CHU\u1ed6I NH\u00c2N-QU\u1ea2 MACRO\n"
    "DXY \u2192 USD \u2192 Gold \u2192 Crypto: m\u1ed1i li\u00ean h\u1ec7 "
    "h\u00f4m nay? "
    "Derivatives (Funding Rate, OI) k\u1ec3 c\u00e2u chuy\u1ec7n g\u00ec? "
    "D\u00e2n chuy\u00ean nghi\u1ec7p ngh\u0129 KH\u00c1C hay "
    "GI\u1ed0NG retail?\n\n"
    "## 4. DERIVATIVES V\u00c0 ON-CHAIN\n"
    "Ch\u1ec9 s\u1ed1 n\u00e0o M\u00c2U THU\u1eaaN nhau? Red flags? "
    "Funding Rate c\u1ef1c \u0111oan + F&G c\u1ef1c \u0111oan c\u00f9ng l\u00fac "
    "= t\u00edn hi\u1ec7u g\u00ec?\n\n"
    "## 5. R\u1ee6I RO V\u00c0 M\u00c2U THU\u1eaaN\n"
    "Ch\u1ec9 s\u1ed1 n\u00e0o \u0111ang M\u00c2U THU\u1eaaN? "
    "R\u1ee7i ro C\u1ee4 TH\u1ec2 cho DeFi/h\u1ea1 t\u1ea7ng? "
    "S\u1ef1 ki\u1ec7n v\u0129 m\u00f4 n\u00e0o S\u1eaeP "
    "T\u1edaI g\u00e2y volatility?\n\n"
    "## 6. K\u1ecaCH B\u1ea2N V\u00c0 TRI\u1ec2N V\u1eccNG\n"
    "Base case + Bullish trigger + Bearish trigger. "
    "D\u00f2ng ti\u1ec1n \u0111ang ROTATE \u0111i \u0111\u00e2u? "
    "Ph\u00f9 h\u1ee3p giai \u0111o\u1ea1n n\u00e0o trong chu k\u1ef3?\n\n"
    "## 7. D\u00d2NG TI\u1ec0N V\u00c0 XU H\u01af\u1edaNG\n"
    "CoinGecko sectors + DefiLlama TVL + narratives: sector n\u00e0o h\u00fat "
    "ti\u1ec1n? "
    "Xu h\u01b0\u1edbng ph\u00f9 h\u1ee3p giai \u0111o\u1ea1n n\u00e0o "
    "trong chu k\u1ef3 th\u1ecb tr\u01b0\u1eddng?\n\n"
    "## 8. K\u1ebeT LU\u1ea0N\n"
    "T\u1ed5ng h\u1ee3p: t\u1ea5t c\u1ea3 ch\u1ec9 s\u1ed1 "
    "\u0110\u1ed2NG THU\u1ea0N hay M\u00c2U THU\u1eaaN? "
    "S\u1ef1 ki\u1ec7n n\u00e0o 7 ng\u00e0y t\u1edbi c\u00f3 "
    "th\u1ec3 THAY \u0110\u1ed4I b\u1ee9c tranh?\n\n"
    "QUY T\u1eaeC:\n"
    "- M\u1ed7i section >= 3 data points C\u1ee4 TH\u1ec2 t\u1eeb input\n"
    "- T\u00ecm M\u00c2U THU\u1eaaN gi\u1eefa c\u00e1c ch\u1ec9 "
    "s\u1ed1 \u2192 insight c\u00f3 gi\u00e1 tr\u1ecb\n"
    "- N\u1ed0I c\u00e1c s\u1ef1 ki\u1ec7n th\u00e0nh chu\u1ed7i "
    "NH\u00c2N-QU\u1ea2 logic\n"
    "- CH\u1ec8 d\u00f9ng data \u0111\u01b0\u1ee3c cung c\u1ea5p. "
    "KH\u00d4NG b\u1ecba ngu\u1ed3n/con s\u1ed1.\n"
    "- Vi\u1ebft ti\u1ebfng Vi\u1ec7t chuy\u00ean nghi\u1ec7p, "
    "thu\u1eadt ng\u1eef ch\u00ednh x\u00e1c\n"
    "- \u0110\u1ed9 d\u00e0i: 4000-6000 t\u1eeb\n\n"
    # Wave 0.7.1 \u2014 Anti-fabrication guards (Mary fact-check 29/04 found 8/20 errors)
    "QUY T\u1eaeC CH\u1ed0NG B\u1ecaA \u0110\u1eb6T (B\u1eaeT BU\u1ed8C):\n"
    "- KH\u00d4NG t\u1ef1 \u0111o\u00e1n NG\u00c0Y c\u1ee7a s\u1ef1 ki\u1ec7n FOMC, CPI, "
    "PPI, Fed meetings. CH\u1ec8 d\u00f9ng ng\u00e0y c\u00f3 trong "
    '"LICH SU KIEN KINH TE" \u1edf input. N\u1ebfu kh\u00f4ng '
    "c\u00f3, vi\u1ebft 'theo l\u1ecbch Fed s\u1eafp t\u1edbi' kh\u00f4ng k\u00e8m "
    "ng\u00e0y c\u1ee5 th\u1ec3.\n"
    "- KH\u00d4NG t\u1ef1 b\u1ecba T\u00caN reporter/journalist/correspondent. "
    "N\u1ebfu tin tr\u00edch d\u1eabn kh\u00f4ng c\u00f3 t\u00ean ng\u01b0\u1eddi vi\u1ebft "
    "trong input, ghi 'theo {t\u00ean publication}' (vd: 'theo Reuters', 'theo Al "
    "Jazeera') \u2014 KH\u00d4NG ghi t\u00ean ng\u01b0\u1eddi gi\u1ea3 \u0111\u1ecbnh.\n"
    "- KH\u00d4NG t\u1ef1 \u0111o\u00e1n s\u1ed1 li\u1ec7u Hash Rate, Difficulty, F&G, "
    "USDT/VND, market cap. CH\u1ec8 d\u00f9ng s\u1ed1 c\u00f3 trong input. N\u1ebfu "
    "input thi\u1ebfu m\u1ed9t ch\u1ec9 s\u1ed1, b\u1ecf qua, KH\u00d4NG b\u1ecba.\n\n"
    "NQ05: Ch\u1ec9 ph\u00e2n t\u00edch v\u00e0 th\u00f4ng tin \u2014 "
    "d\u00f9ng 't\u00e0i s\u1ea3n m\u00e3 h\u00f3a' (kh\u00f4ng "
    "'ti\u1ec1n \u0111i\u1ec7n t\u1eed').\n"
)


def build_master_context(context: GenerationContext, sentinel_text: str = "") -> str:
    """Assemble ALL data sources into structured LLM context for Master Analysis.

    WHY: Master sees EVERYTHING — no per-tier filtering. This eliminates
    the cross-tier contradiction problem (e.g., L3 says bearish, L5 says bullish).

    Args:
        context: Standard GenerationContext with all collected data.
        sentinel_text: P1.12 — Pre-formatted Sentinel data (season, SonicR, FA).
            Passed separately because SentinelData is not part of GenerationContext
            to keep article_generator.py stable during Phase 1c.
    """
    parts: list[str] = []

    metrics_table = render_key_metrics_table(context.key_metrics)

    # Market data
    if context.market_data:
        parts.append(f"=== DU LIEU THI TRUONG ===\n{context.market_data}")

    # Key metrics table
    if metrics_table:
        parts.append(f"=== BANG CHI SO CHINH ===\n{metrics_table}")

    # News
    if context.news_summary:
        parts.append(f"=== TIN TUC ===\n{context.news_summary}")

    # On-chain
    if context.onchain_data:
        parts.append(f"=== DU LIEU ON-CHAIN & DERIVATIVES ===\n{context.onchain_data}")

    # Whale data
    if context.whale_data and "Khong co" not in context.whale_data:
        parts.append(f"=== WHALE ALERT ===\n{context.whale_data}")

    # Research data (MVRV, NUPL, ETF, stablecoins, Pi Cycle)
    if context.research_data_text:
        parts.append(f"=== DU LIEU NGHIEN CUU NANG CAO ===\n{context.research_data_text}")

    # Historical
    if context.historical_context:
        parts.append(f"=== LICH SU THI TRUONG ===\n{context.historical_context}")

    # Consensus
    if context.consensus_text:
        parts.append(context.consensus_text)

    # Sector
    if context.sector_data:
        parts.append(context.sector_data)

    # Economic events
    if context.economic_events:
        parts.append(f"=== LICH SU KIEN KINH TE ===\n{context.economic_events}")

    # Breaking
    if context.recent_breaking:
        parts.append(f"=== SU KIEN BREAKING 24H ===\n{context.recent_breaking}")

    # Narratives
    if context.narratives_text:
        parts.append(context.narratives_text)

    # Metrics Engine (L5 level = most comprehensive)
    if context.metrics_interpretation is not None:
        try:
            interp = context.metrics_interpretation.format_for_tier("L5")
            parts.append(f"=== PHAN TICH TU DONG ===\n{interp}")
        except Exception:
            pass

    # Data quality
    if context.data_quality_notes:
        parts.append(context.data_quality_notes)

    # P1.12: Sentinel cross-system data (season, SonicR, FA scores)
    if sentinel_text:
        parts.append(sentinel_text)

    # Coin lists (all tiers merged — Master sees everything)
    all_coins: set[str] = set()
    for coins in context.coin_lists.values():
        all_coins.update(coins)
    if all_coins:
        parts.append(f"=== DANH SACH COINS THEO DOI ===\n{', '.join(sorted(all_coins))}")

    return "\n\n".join(parts)


def _get_master_max_tokens(config_loader: object | None = None) -> int:
    """QO.32: Read MASTER_MAX_TOKENS from CAU_HINH config at runtime.

    Falls back to module-level constant if config unavailable.
    """
    if config_loader is None:
        return MASTER_MAX_TOKENS
    try:
        return config_loader.get_setting_int("MASTER_MAX_TOKENS", MASTER_MAX_TOKENS)
    except Exception:
        return MASTER_MAX_TOKENS


async def generate_master_analysis(
    llm: LLMAdapter,
    context: GenerationContext,
    sentinel_text: str = "",
    config_loader: object | None = None,
) -> MasterAnalysis:
    """Generate a single comprehensive Master Analysis.

    QO.32: MASTER_MAX_TOKENS read from CAU_HINH via config_loader.
    Raises MasterAnalysisError if response is too short (<MASTER_MIN_WORDS).
    """
    start = time.monotonic()

    # QO.32: Read max_tokens from config at runtime
    max_tokens = _get_master_max_tokens(config_loader)

    master_context = build_master_context(context, sentinel_text=sentinel_text)
    prompt = (
        f"{master_context}\n\n"
        "=== NHIEM VU ===\n"
        "Viet bai phan tich toan dien theo cau truc 8 sections o tren."
    )

    response: LLMResponse = await llm.generate(
        prompt=prompt,
        system_prompt=MASTER_SYSTEM_PROMPT,
        max_tokens=max_tokens,
        temperature=MASTER_TEMPERATURE,
    )

    content = response.text.strip()
    word_count = len(content.split())
    elapsed = time.monotonic() - start

    # Parse section markers (fuzzy: allow ## N. or ## N  or **N.** etc.)
    sections_found = 0
    for i in range(1, MASTER_SECTIONS_EXPECTED + 1):
        if re.search(rf"##\s*{i}[\.\s]", content):
            sections_found += 1

    # Fuzzy conclusion detection: ## 8 heading OR Vietnamese/ASCII keyword
    has_conclusion = bool(
        re.search(r"##\s*8[\.\s]|K\u1ebeT LU\u1eacN|KET LUAN", content, re.IGNORECASE)
    )

    master = MasterAnalysis(
        content=content,
        word_count=word_count,
        llm_used=response.model,
        generation_time_sec=elapsed,
        finish_reason=response.finish_reason,
        sections_found=sections_found,
        has_conclusion=has_conclusion,
    )

    logger.info(
        f"Master Analysis: {word_count} words, {sections_found}/{MASTER_SECTIONS_EXPECTED} "
        f"sections, conclusion={'yes' if has_conclusion else 'NO'}, "
        f"{elapsed:.1f}s via {response.model}"
    )

    if word_count < MASTER_MIN_WORDS:
        raise MasterAnalysisError(
            f"Master Analysis too short: {word_count} words (min {MASTER_MIN_WORDS})",
            source="master_analysis",
        )

    return master


def validate_master(master: MasterAnalysis) -> bool:
    """Check Master Analysis structural completeness.

    WHY: Even if word count passes, a truncated or malformed response
    (missing conclusion, too few sections) should trigger fallback.
    """
    if not master.has_conclusion:
        logger.warning("Master validation FAIL: missing conclusion (## 8)")
        return False
    if master.sections_found < 6:
        logger.warning(f"Master validation FAIL: only {master.sections_found}/8 sections")
        return False
    # Truncated by token limit = risky even if conclusion keyword found
    # (LLM may have been cut mid-section, conclusion keyword matched earlier text)
    if master.finish_reason == "length":
        logger.warning("Master validation FAIL: truncated (finish_reason=length)")
        return False
    return True
