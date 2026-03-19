"""Tests for inter-tier context passing (v0.21.0, updated v0.23.0)."""

from cic_daily_report.generators.article_generator import _summarize_tier_output


class TestSummarizeTierOutput:
    def test_includes_tier_and_focus(self):
        content = "BTC tăng 2% trong 24h qua. ETH giảm nhẹ 1.5%."
        summary = _summarize_tier_output("L1", content)
        assert "[L1]" in summary

    def test_extracts_coins(self):
        content = (
            "BTC tăng 2% lên $75,000. ETH giảm nhẹ 1.5%. "
            "SOL đang ổn định quanh $140. Thị trường crypto sôi động."
        )
        summary = _summarize_tier_output("L2", content)
        assert "BTC" in summary
        assert "ETH" in summary

    def test_extracts_numbers(self):
        content = "BTC tăng 2% lên $75,000 với volume $2.1B."
        summary = _summarize_tier_output("L1", content)
        # Should extract numbers
        assert "Số liệu đã dùng" in summary

    def test_extracts_key_sentences(self):
        content = (
            "Thị trường crypto đang trong trạng thái phục hồi sau đợt giảm mạnh tuần trước. "
            "BTC tăng 5% lên $75,000 với volume giao dịch tăng 30%."
        )
        summary = _summarize_tier_output("L1", content)
        # Should have at least one key sentence
        assert len(summary.split("\n")) >= 2

    def test_fallback_for_empty_content(self):
        summary = _summarize_tier_output("L3", "")
        assert "[L3]" in summary
