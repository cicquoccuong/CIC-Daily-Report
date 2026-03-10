"""Template Engine — configurable article sections from MAU_BAI_VIET (QĐ8).

Loads templates per tier from Google Sheets, substitutes variables,
renders Key Metrics Table (FR20), and respects enabled/disabled sections.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from cic_daily_report.core.logger import get_logger

logger = get_logger("template_engine")

# FR20: 7 mandatory key metrics
KEY_METRICS_LABELS = [
    "BTC Price",
    "BTC Dominance",
    "Total Market Cap",
    "Fear & Greed",
    "DXY",
    "Gold",
    "Funding Rate",
]


@dataclass
class SectionTemplate:
    """A single content section within a tier article."""

    tier: str
    section_name: str
    enabled: bool
    order: int
    prompt_template: str
    max_words: int


@dataclass
class RenderedSection:
    """A section after variable substitution, ready for LLM."""

    section_name: str
    prompt: str
    max_words: int


@dataclass
class ArticleTemplate:
    """All sections for a single tier, sorted by order."""

    tier: str
    sections: list[SectionTemplate] = field(default_factory=list)


def load_templates(raw_templates: list[dict[str, Any]]) -> dict[str, ArticleTemplate]:
    """Group raw template rows (from ConfigLoader) into per-tier ArticleTemplates.

    Returns dict keyed by tier (e.g. "L1", "L2", ...).
    """
    by_tier: dict[str, list[SectionTemplate]] = {}

    for row in raw_templates:
        section = SectionTemplate(
            tier=str(row.get("tier", "")).strip().upper(),
            section_name=str(row.get("section_name", "")).strip(),
            enabled=bool(row.get("enabled", True)),
            order=int(row.get("order", 0) or 0),
            prompt_template=str(row.get("prompt_template", "")).strip(),
            max_words=int(row.get("max_words", 500) or 500),
        )
        if section.tier:
            by_tier.setdefault(section.tier, []).append(section)

    result: dict[str, ArticleTemplate] = {}
    for tier, sections in by_tier.items():
        sorted_sections = sorted(sections, key=lambda s: s.order)
        result[tier] = ArticleTemplate(tier=tier, sections=sorted_sections)

    logger.info(
        "Templates loaded: "
        + ", ".join(f"{t}={len(at.sections)} sections" for t, at in result.items())
    )
    return result


def render_sections(
    template: ArticleTemplate,
    variables: dict[str, str],
) -> list[RenderedSection]:
    """Substitute variables into enabled sections, return rendered prompts.

    Variables dict maps placeholder names to values, e.g.:
      {"coin_list": "BTC, ETH", "market_data": "...", "news_summary": "..."}
    """
    rendered: list[RenderedSection] = []

    for section in template.sections:
        if not section.enabled:
            logger.debug(f"Skipping disabled section: {section.section_name}")
            continue

        prompt = section.prompt_template
        for key, value in variables.items():
            prompt = prompt.replace(f"{{{key}}}", value)

        # Warn about unreplaced placeholders
        unreplaced = re.findall(r"\{(\w+)\}", prompt)
        if unreplaced:
            logger.warning(f"Unreplaced placeholders in '{section.section_name}': {unreplaced}")

        rendered.append(
            RenderedSection(
                section_name=section.section_name,
                prompt=prompt,
                max_words=section.max_words,
            )
        )

    return rendered


def render_key_metrics_table(metrics: dict[str, str | float]) -> str:
    """Render FR20 Key Metrics Table as Markdown.

    Args:
        metrics: dict with keys matching KEY_METRICS_LABELS values.
    """
    lines = ["| Chỉ số | Giá trị |", "|--------|---------|"]
    for label in KEY_METRICS_LABELS:
        value = metrics.get(label, "N/A")
        lines.append(f"| {label} | {value} |")
    return "\n".join(lines)
