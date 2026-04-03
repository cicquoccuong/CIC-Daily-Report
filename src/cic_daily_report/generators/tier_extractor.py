"""Tier Extractor (P1.7) — Extract L1-L5 + Summary from Master Analysis.

Each tier gets a focused extraction from the single Master Analysis,
maintaining consistency while adapting content to the target audience.

Sequential extraction with cooldowns to respect 7 RPM rate limits.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass

from cic_daily_report.adapters.llm_adapter import LLMAdapter, LLMResponse
from cic_daily_report.core.logger import get_logger
from cic_daily_report.generators.article_generator import (
    DISCLAIMER,
    NQ05_SYSTEM_PROMPT,
    GeneratedArticle,
)
from cic_daily_report.generators.master_analysis import MasterAnalysis

logger = get_logger("tier_extractor")

# WHY 120s: Gemini 2.5 Flash has 7 RPM limit — if we hit 429, wait 2 full minutes
# to let the per-minute window reset before retrying.
_TIER_RETRY_WAIT = 120  # seconds to wait on 429


@dataclass
class ExtractionConfig:
    """Configuration for extracting a single tier from Master Analysis."""

    tier: str
    max_tokens: int
    temperature: float
    target_words: tuple[int, int]
    sections_focus: str  # which Master sections to emphasize
    audience: str
    focus: str
    format_instructions: str = ""  # extra format rules (e.g., story-based for Summary)


# WHY per-tier configs: Each audience needs different depth, focus, and word count.
# sections_focus tells the LLM which Master sections are most relevant for extraction.
EXTRACTION_CONFIGS: dict[str, ExtractionConfig] = {
    # WHY x1.5 increase: Vietnamese text uses ~1.5x more tokens than English
    # for equivalent content, causing frequent finish_reason=length truncation.
    "L1": ExtractionConfig(
        tier="L1",
        max_tokens=3072,
        temperature=0.3,
        target_words=(600, 800),  # VD-13: reduced from (800, 1200) to fit 1-2 TG messages
        sections_focus="1, 2",
        audience=(
            "Ng\u01b0\u1eddi m\u1edbi b\u1eaft \u0111\u1ea7u t\u00ecm hi\u1ec3u "
            "t\u00e0i s\u1ea3n m\u00e3 h\u00f3a. "
            "Ch\u1ec9 c\u1ea7n bi\u1ebft BTC/ETH h\u00f4m nay th\u1ebf n\u00e0o, "
            "c\u00f3 g\u00ec \u0111\u00e1ng ch\u00fa \u00fd."
        ),
        focus=(
            "T\u1ed5ng quan \u0111\u01a1n gi\u1ea3n: gi\u00e1 BTC/ETH, "
            "Fear & Greed, tin ch\u00ednh. "
            "Ng\u00f4n ng\u1eef d\u1ec5 hi\u1ec3u, kh\u00f4ng thu\u1eadt ng\u1eef "
            "chuy\u00ean s\u00e2u."
        ),
    ),
    "L2": ExtractionConfig(
        tier="L2",
        max_tokens=4608,
        temperature=0.3,
        target_words=(800, 1000),  # VD-13: reduced from (1200, 1500) to fit 1-2 TG messages
        sections_focus="2, 7",
        audience=(
            "Nh\u00e0 \u0111\u1ea7u t\u01b0 quan t\u00e2m altcoin v\u00e0 sector. "
            "\u0110\u00e3 \u0111\u1ecdc L1."
        ),
        focus=(
            "Bluechip + sector rotation. BTC Dominance, Altcoin Season. "
            "Nh\u1eafc t\u1ed1i thi\u1ec3u 10 coins. USDT/VND rate. "
            "KH\u00d4NG l\u1eb7p l\u1ea1i n\u1ed9i dung L1."
        ),
    ),
    "L3": ExtractionConfig(
        tier="L3",
        max_tokens=6144,
        temperature=0.4,
        target_words=(900, 1100),  # VD-13: reduced from (1800, 2000) to fit 1-2 TG messages
        sections_focus="3, 4",
        audience=(
            "Nh\u00e0 \u0111\u1ea7u t\u01b0 mu\u1ed1n hi\u1ec3u nguy\u00ean nh\u00e2n "
            "s\u00e2u. \u0110\u00e3 \u0111\u1ecdc L1-L2."
        ),
        focus=(
            "Chu\u1ed7i nh\u00e2n-qu\u1ea3 macro: DXY \u2192 USD \u2192 Gold \u2192 Crypto. "
            "Derivatives (Funding Rate, OI). On-chain signals. "
            "KH\u00d4NG l\u1eb7p l\u1ea1i n\u1ed9i dung L1-L2."
        ),
    ),
    "L4": ExtractionConfig(
        tier="L4",
        max_tokens=6144,
        temperature=0.4,
        target_words=(900, 1100),  # VD-13: reduced from (2000, 2200) to fit 1-2 TG messages
        sections_focus="4, 5",
        audience=(
            "Nh\u00e0 \u0111\u1ea7u t\u01b0 t\u1eadp trung qu\u1ea3n l\u00fd r\u1ee7i ro. "
            "\u0110\u00e3 \u0111\u1ecdc L1-L3."
        ),
        focus=(
            "R\u1ee7i ro v\u00e0 m\u00e2u thu\u1eabn gi\u1eefa c\u00e1c ch\u1ec9 s\u1ed1. "
            "Red flags. S\u1ef1 ki\u1ec7n v\u0129 m\u00f4 s\u1eafp t\u1edbi. "
            "DeFi/h\u1ea1 t\u1ea7ng risks. "
            "KH\u00d4NG l\u1eb7p l\u1ea1i n\u1ed9i dung L1-L3."
        ),
    ),
    "L5": ExtractionConfig(
        tier="L5",
        max_tokens=8192,
        temperature=0.45,
        target_words=(1200, 1500),  # VD-13: reduced from (2500, 3000) to fit 1-2 TG messages
        sections_focus="5, 6, 7, 8",
        audience=(
            "Master Investor — chi\u1ebfn l\u01b0\u1ee3c d\u00e0i h\u1ea1n, "
            "ADCA, \u0111\u00e1nh gi\u00e1 theo chu k\u1ef3. "
            "\u0110\u00e3 \u0111\u1ecdc L1-L4."
        ),
        focus=(
            "T\u1ed5ng h\u1ee3p chi\u1ebfn l\u01b0\u1ee3c: k\u1ecbch b\u1ea3n "
            "(base/bull/bear), d\u00f2ng ti\u1ec1n rotate, tri\u1ec3n v\u1ecdng. "
            "Giai \u0111o\u1ea1n trong chu k\u1ef3 th\u1ecb tr\u01b0\u1eddng. "
            "K\u1ebft lu\u1eadn: \u0111\u1ed3ng thu\u1eadn hay m\u00e2u thu\u1eabn. "
            "KH\u00d4NG l\u1eb7p l\u1ea1i n\u1ed9i dung L1-L4."
        ),
    ),
    "Summary": ExtractionConfig(
        tier="Summary",
        max_tokens=4096,
        temperature=0.3,
        target_words=(500, 700),  # VD-13: reduced from (600, 900) to fit 1-2 TG messages
        sections_focus="1, 2, 5, 6",
        audience=(
            "BIC Chat members — \u0111\u1ecdc nhanh tr\u00ean \u0111i\u1ec7n tho\u1ea1i, "
            "c\u1ea7n b\u1ea3n tin copy-paste ready cho Telegram."
        ),
        focus=(
            "B\u1ea3n t\u00f3m t\u1eaft d\u1ea1ng story-based digest. "
            "Kh\u00f4ng li\u1ec7t k\u00ea kh\u00f4, k\u1ec3 c\u00e2u chuy\u1ec7n."
        ),
        # WHY full format spec: Summary has unique story-based format different
        # from tier articles — Hook + Market Overview + Stories + Forward Look.
        format_instructions=(
            "C\u1ea4U TR\u00daC B\u1eaeT BU\u1ed8C:\n\n"
            "HOOK (1-2 c\u00e2u): M\u1edf \u0111\u1ea7u b\u1eb1ng 1 PH\u00c1T HI\u1ec6N "
            "TH\u00da V\u1eca t\u1eeb d\u1eef li\u1ec7u. \u01afu ti\u00ean:\n"
            "- M\u00e2u thu\u1eabn gi\u1eefa c\u00e1c t\u00edn hi\u1ec7u\n"
            "- S\u1ed1 li\u1ec7u b\u1ea5t ng\u1edd\n"
            "- B\u1ed1i c\u1ea3nh l\u1ecbch s\u1eed\n"
            "KH\u00d4NG m\u1edf \u0111\u1ea7u b\u1eb1ng "
            "'H\u00f4m nay th\u1ecb tr\u01b0\u1eddng...'\n\n"
            "C\u1eacP NH\u1eacT TH\u1eca TR\u01af\u1edcNG (1 \u0111o\u1ea1n):\n"
            "**C\u1eadp nh\u1eadt Th\u1ecb tr\u01b0\u1eddng** l\u00e0m ti\u00eau "
            "\u0111\u1ec1 \u0111\u1eadm.\n"
            "1 \u0111o\u1ea1n v\u0103n xu\u00f4i l\u1ed3ng s\u1ed1 li\u1ec7u: "
            "t\u1ed5ng v\u1ed1n h\u00f3a, BTC, ETH, sector n\u1ed5i b\u1eadt.\n\n"
            "TIN T\u1ee8C (5-8 tin, s\u1eafp theo m\u1ee9c quan tr\u1ecdng):\n"
            "M\u1ed7i tin = 1 section ri\u00eang:\n"
            "- Ti\u00eau \u0111\u1ec1: **[Ti\u00eau \u0111\u1ec1 ti\u1ebfng Vi\u1ec7t]**\n"
            "- 2-3 tin quan tr\u1ecdng nh\u1ea5t: 1-2 \u0111o\u1ea1n ph\u00e2n t\u00edch\n"
            "- 3-5 tin ph\u1ee5: 1 \u0111o\u1ea1n ng\u1eafn\n"
            "C\u00e2u cu\u1ed1i = H\u1ec6 QU\u1ea2 C\u1ee4 TH\u1ec2\n\n"
            "S\u1eaeP T\u1edaI (1-2 d\u00f2ng cu\u1ed1i):\n"
            "S\u1ef1 ki\u1ec7n 3-7 ng\u00e0y t\u1edbi.\n\n"
            "QUY T\u1eaeC:\n"
            "- Ti\u1ebfng Vi\u1ec7t c\u00f3 d\u1ea5u\n"
            "- D\u00f9ng 't\u00e0i s\u1ea3n m\u00e3 h\u00f3a'\n"
            "- M\u1ed7i \u0111o\u1ea1n T\u1ed0I \u0110A 3 c\u00e2u\n"
            "- **bold** CH\u1ec8 cho ti\u00eau \u0111\u1ec1 tin v\u00e0 s\u1ed1 li\u1ec7u\n"
            "- Copy-paste ready cho Telegram\n"
            "- KH\u00d4NG b\u1ecba s\u1ed1 li\u1ec7u\n"
        ),
    ),
}


async def extract_tier(
    llm: LLMAdapter,
    master: MasterAnalysis,
    config: ExtractionConfig,
    tier_context_str: str = "",
) -> GeneratedArticle:
    """Extract a single tier article from the Master Analysis.

    WHY: Each tier gets its own LLM call with focused instructions so the
    extraction adapts depth/language to the target audience while staying
    consistent with the single Master source.
    """
    start = time.monotonic()

    # Build extraction prompt — Master content + tier-specific instructions
    prompt = (
        f"=== B\u00c0I PH\u00c2N T\u00cdCH G\u1ed0C ===\n"
        f"{master.content}\n\n"
        f"=== NHI\u1ec6M V\u1ee4: Tr\u00edch xu\u1ea5t cho {config.tier} ===\n"
        f"\u0110\u1ed0I T\u01af\u1ee2NG: {config.audience}\n"
        f"TR\u1eccNG T\u00c2M: {config.focus}\n"
        f"SECTIONS LI\u00caN QUAN: {config.sections_focus}\n"
        f"\u0110\u1ed8 D\u00c0I: {config.target_words[0]}-{config.target_words[1]} "
        f"t\u1eeb\n"
    )

    if tier_context_str:
        prompt += f"\n{tier_context_str}\n"

    if config.format_instructions:
        prompt += f"\n{config.format_instructions}\n"

    # WHY: LLM sometimes adds meta-commentary before actual content (VD-16).
    prompt += (
        "\n\u0110\u1ecaNH D\u1ea0NG: Vi\u1ebft b\u00e0i ph\u00e2n t\u00edch "
        "TR\u1ef0C TI\u1ebeP. "
        "D\u00f2ng \u0111\u1ea7u ti\u00ean PH\u1ea2I l\u00e0 n\u1ed9i dung "
        "ph\u00e2n t\u00edch. "
        "TUY\u1ec6T \u0110\u1ed0I KH\u00d4NG vi\u1ebft l\u1eddi ch\u00e0o, "
        "l\u1eddi d\u1eabn, gi\u1edbi thi\u1ec7u "
        "('Tuy\u1ec7t v\u1eddi!', 'D\u01b0\u1edbi \u0111\u00e2y l\u00e0...', "
        "'Ch\u1eafc ch\u1eafn!').\n"
    )

    prompt += (
        "\nQUY T\u1eaeC:\n"
        "- KH\u00d4NG th\u00eam data kh\u00f4ng c\u00f3 trong b\u00e0i g\u1ed1c\n"
        "- KH\u00d4NG thay \u0111\u1ed5i s\u1ed1 li\u1ec7u, "
        "ch\u1ec9 \u0110\u01a0N GI\u1ea2N H\u00d3A ng\u00f4n ng\u1eef theo level\n"
        "- Member \u0111\u00e3 \u0111\u1ecdc c\u00e1c tier tr\u01b0\u1edbc \u2014 "
        "KH\u00d4NG l\u1eb7p l\u1ea1i\n"
    )

    response: LLMResponse = await llm.generate(
        prompt=prompt,
        system_prompt=NQ05_SYSTEM_PROMPT,
        max_tokens=config.max_tokens,
        temperature=config.temperature,
    )

    # WHY retry: Vietnamese text uses ~1.5x more tokens than English.
    # If LLM ran out of tokens (finish_reason=length), retry once with 2x
    # max_tokens to get complete output. Pattern mirrors master_analysis.py:280-297.
    if response.finish_reason == "length":
        logger.warning(
            f"Tier {config.tier} truncated (finish_reason=length), retrying with 2x tokens"
        )
        response2: LLMResponse = await llm.generate(
            prompt=prompt,
            system_prompt=NQ05_SYSTEM_PROMPT,
            max_tokens=config.max_tokens * 2,
            temperature=config.temperature,
        )
        if response2.finish_reason == "length":
            logger.error(f"Tier {config.tier} still truncated after retry")
        else:
            response = response2

    content = response.text.strip()

    # WHY: LLM sometimes prefixes meta-commentary ("Tuyệt vời!", "Dưới đây là...")
    # despite prompt instructions. Regex strip as safety net (VD-16).
    content = re.sub(
        r"^(?:Tuyệt vời!?\s*|Chắc chắn!?\s*|Dưới đây là\s*|Sure!?\s*|Certainly!?\s*).*?\n+",
        "",
        content,
        count=1,
        flags=re.IGNORECASE,
    )

    # Summary does NOT get DISCLAIMER appended — it uses NQ05 post-filter in pipeline
    # Tier articles DO get DISCLAIMER for NQ05 compliance
    if config.tier != "Summary":
        content = content + DISCLAIMER

    word_count = len(content.split())
    elapsed = time.monotonic() - start

    return GeneratedArticle(
        tier=config.tier,
        title=f"[{config.tier}] Ph\u00e2n t\u00edch th\u1ecb tr\u01b0\u1eddng "
        f"t\u00e0i s\u1ea3n m\u00e3 h\u00f3a",
        content=content,
        word_count=word_count,
        llm_used=response.model,
        generation_time_sec=elapsed,
    )


async def extract_all(
    llm: LLMAdapter,
    master: MasterAnalysis,
    tier_contexts: dict[str, str],
) -> list[GeneratedArticle]:
    """Extract all tiers + summary from Master Analysis sequentially.

    WHY sequential: 7 RPM rate limit on Gemini 2.5 Flash means we cannot
    fire all 6 extractions in parallel — we'd hit 429 immediately.
    Sequential + adaptive cooldown keeps us within limits.
    """
    articles: list[GeneratedArticle] = []

    for config in EXTRACTION_CONFIGS.values():
        tier_ctx = tier_contexts.get(config.tier, "")

        for attempt in range(2):
            try:
                article = await extract_tier(llm, master, config, tier_ctx)
                articles.append(article)
                logger.info(f"Extracted {config.tier}: {article.word_count} words")

                # Adaptive cooldown between extractions to avoid 429
                cooldown = llm.suggest_cooldown()
                if cooldown > 0:
                    await asyncio.sleep(cooldown)
                break
            except Exception as e:
                if attempt == 0 and "429" in str(e):
                    logger.warning(f"{config.tier} rate limited, waiting {_TIER_RETRY_WAIT}s")
                    await asyncio.sleep(_TIER_RETRY_WAIT)
                    continue
                logger.error(f"Extraction failed for {config.tier}: {e}")
                break

    logger.info(f"Extracted {len(articles)}/{len(EXTRACTION_CONFIGS)} articles from Master")
    return articles
