"""Tests for generators/template_engine.py."""

from cic_daily_report.generators.template_engine import (
    KEY_METRICS_LABELS,
    ArticleTemplate,
    SectionTemplate,
    load_templates,
    render_key_metrics_table,
    render_sections,
)


def _raw(tier: str, name: str, order: int, enabled: bool = True, prompt: str = "p") -> dict:
    return {
        "tier": tier,
        "section_name": name,
        "enabled": enabled,
        "order": order,
        "prompt_template": prompt,
        "max_words": 300,
    }


class TestLoadTemplates:
    def test_groups_by_tier(self):
        raw = [_raw("L1", "Intro", 1), _raw("L1", "Body", 2), _raw("L2", "Intro", 1)]
        result = load_templates(raw)
        assert "L1" in result
        assert "L2" in result
        assert len(result["L1"].sections) == 2
        assert len(result["L2"].sections) == 1

    def test_sorts_by_order(self):
        raw = [_raw("L1", "Body", 3), _raw("L1", "Intro", 1), _raw("L1", "Mid", 2)]
        result = load_templates(raw)
        names = [s.section_name for s in result["L1"].sections]
        assert names == ["Intro", "Mid", "Body"]

    def test_empty_input(self):
        assert load_templates([]) == {}

    def test_case_insensitive_tier(self):
        raw = [_raw("l1", "Intro", 1)]
        result = load_templates(raw)
        assert "L1" in result

    def test_skips_empty_tier(self):
        raw = [_raw("", "Intro", 1)]
        result = load_templates(raw)
        assert result == {}


class TestRenderSections:
    def test_substitutes_variables(self):
        template = ArticleTemplate(
            tier="L1",
            sections=[
                SectionTemplate("L1", "Intro", True, 1, "Coins: {coin_list}", 300),
            ],
        )
        rendered = render_sections(template, {"coin_list": "BTC, ETH"})
        assert len(rendered) == 1
        assert rendered[0].prompt == "Coins: BTC, ETH"

    def test_skips_disabled_sections(self):
        template = ArticleTemplate(
            tier="L1",
            sections=[
                SectionTemplate("L1", "Intro", True, 1, "active", 300),
                SectionTemplate("L1", "Hidden", False, 2, "disabled", 300),
            ],
        )
        rendered = render_sections(template, {})
        assert len(rendered) == 1
        assert rendered[0].section_name == "Intro"

    def test_preserves_order(self):
        template = ArticleTemplate(
            tier="L1",
            sections=[
                SectionTemplate("L1", "A", True, 1, "first", 100),
                SectionTemplate("L1", "B", True, 2, "second", 200),
            ],
        )
        rendered = render_sections(template, {})
        assert rendered[0].section_name == "A"
        assert rendered[1].section_name == "B"

    def test_multiple_variables(self):
        template = ArticleTemplate(
            tier="L1",
            sections=[
                SectionTemplate("L1", "S", True, 1, "{a} and {b}", 300),
            ],
        )
        rendered = render_sections(template, {"a": "X", "b": "Y"})
        assert rendered[0].prompt == "X and Y"

    def test_unresolved_placeholder_kept(self):
        template = ArticleTemplate(
            tier="L1",
            sections=[
                SectionTemplate("L1", "S", True, 1, "Hello {unknown}", 300),
            ],
        )
        rendered = render_sections(template, {})
        assert "{unknown}" in rendered[0].prompt


class TestRenderKeyMetricsTable:
    def test_all_metrics_present(self):
        metrics = {
            "BTC Price": "$105,000",
            "BTC Dominance": "61.2%",
            "Total Market Cap": "$3.4T",
            "Fear & Greed": "72 (Greed)",
            "DXY": "104.5",
            "Gold": "$2,650",
            "Funding Rate": "0.01%",
        }
        table = render_key_metrics_table(metrics)
        assert "BTC Price" in table
        assert "$105,000" in table
        assert "| Chỉ số |" in table

    def test_missing_metrics_show_na(self):
        table = render_key_metrics_table({})
        assert table.count("N/A") == 11

    def test_partial_metrics(self):
        table = render_key_metrics_table({"BTC Price": "$100K"})
        assert "$100K" in table
        assert table.count("N/A") == 10


class TestKeyMetricsLabels:
    """Tests for FR20 key metrics — 11 mandatory metrics (Wave E)."""

    def test_exactly_11_metrics(self):
        assert len(KEY_METRICS_LABELS) == 11

    def test_new_metrics_present(self):
        """Wave E added ETH Dominance, TOTAL3, Altcoin Season, USDT/VND."""
        assert "ETH Dominance" in KEY_METRICS_LABELS
        assert "TOTAL3" in KEY_METRICS_LABELS
        assert "Altcoin Season" in KEY_METRICS_LABELS
        assert "USDT/VND" in KEY_METRICS_LABELS

    def test_original_metrics_still_present(self):
        for label in ["BTC Price", "BTC Dominance", "Total Market Cap",
                       "Fear & Greed", "DXY", "Gold", "Funding Rate"]:
            assert label in KEY_METRICS_LABELS

    def test_new_metrics_in_rendered_table(self):
        """All 11 metrics appear as rows in the rendered table."""
        metrics = {label: f"val_{i}" for i, label in enumerate(KEY_METRICS_LABELS)}
        table = render_key_metrics_table(metrics)
        for label in KEY_METRICS_LABELS:
            assert label in table
        assert table.count("N/A") == 0
