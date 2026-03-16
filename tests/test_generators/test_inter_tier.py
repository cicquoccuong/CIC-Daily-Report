"""Tests for inter-tier context passing (v0.21.0)."""

from cic_daily_report.generators.article_generator import _summarize_tier_output


class TestSummarizeTierOutput:
    def test_extracts_section_headers(self):
        content = (
            "## Tổng quan thị trường\n"
            "BTC tăng 2% trong 24h qua.\n\n"
            "## Tin tức nổi bật\n"
            "SEC phê duyệt Bitcoin ETF.\n"
        )
        summary = _summarize_tier_output("L1", content)
        assert "[L1]" in summary
        assert "Tổng quan thị trường" in summary
        assert "Tin tức nổi bật" in summary

    def test_includes_tier_focus(self):
        summary = _summarize_tier_output("L3", "## Analysis\nDeep analysis here.\n")
        assert "Nguyên nhân" in summary or "L3" in summary

    def test_fallback_for_no_headers(self):
        content = "Plain text without any markdown headers at all."
        summary = _summarize_tier_output("L2", content)
        assert "[L2]" in summary
        assert "Plain text" in summary

    def test_limits_sections(self):
        # Create content with 10 sections
        sections = [f"## Section {i}\nContent {i}\n" for i in range(10)]
        content = "\n".join(sections)
        summary = _summarize_tier_output("L1", content)
        # Should have at most 6 sections
        assert summary.count("Section") <= 6

    def test_truncates_long_snippets(self):
        long_line = "x" * 200
        content = f"## Title\n{long_line}\n"
        summary = _summarize_tier_output("L1", content)
        assert "..." in summary
