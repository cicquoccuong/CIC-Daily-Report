"""Tests for generators/research_generator.py — LLM calls mocked."""

from unittest.mock import AsyncMock

from cic_daily_report.adapters.llm_adapter import LLMResponse
from cic_daily_report.collectors.research_data import (
    ETFFlowData,
    ETFFlowEntry,
    OnChainAdvanced,
    PiCycleData,
    ResearchData,
    StablecoinData,
)
from cic_daily_report.generators.article_generator import GenerationContext
from cic_daily_report.generators.research_generator import (
    RESEARCH_MAX_TOKENS,
    RESEARCH_SYSTEM_PROMPT,
    _build_research_context,
    _build_research_prompt,
    generate_research_article,
)


def _make_research_data() -> ResearchData:
    """Build sample research data for tests."""
    return ResearchData(
        onchain_advanced=[
            OnChainAdvanced("MVRV_Z_Score", 1.45, "BGeometrics", "2026-03-20"),
            OnChainAdvanced("NUPL", 0.35, "BGeometrics", "2026-03-20"),
            OnChainAdvanced("SOPR", 1.02, "BGeometrics", "2026-03-20"),
            OnChainAdvanced("Puell_Multiple", 0.89, "BGeometrics", "2026-03-20"),
        ],
        etf_flows=ETFFlowData(
            entries=[
                ETFFlowEntry("IBIT", 700e6, date="2026-03-19"),
                ETFFlowEntry("FBTC", 120e6, date="2026-03-19"),
                ETFFlowEntry("GBTC", -20e6, date="2026-03-19"),
            ],
            total_flow_usd=800e6,
            date="2026-03-19",
        ),
        stablecoins=[
            StablecoinData("Tether (USDT)", 184e9, 500e6, 1e9, 4e9),
            StablecoinData("USDC", 79e9, -200e6, 250e6, 5e9),
        ],
        blockchain_stats={"Miner_Revenue_USD": 31.2e6, "Difficulty": 145e12},
        pi_cycle=PiCycleData(sma_111=72000, sma_350x2=85000, distance_pct=-15.3),
        collected_at="2026-03-20 08:00:00",
    )


def _make_context() -> GenerationContext:
    """Build sample pipeline context for tests."""
    return GenerationContext(
        market_data="- BTC: $70,810 (+1.2%) | Vol: $25.3B | MCap: $1.4T\n"
        "- ETH: $1,850 (-0.5%) | Vol: $10.1B",
        onchain_data="- BTC_Funding_Rate: 0.0008 (Binance)\n"
        "- BTC_Open_Interest: 87,500 (Binance)\n"
        "- BTC_MVRV_Ratio: 1.287 (CoinMetrics)",
        key_metrics={
            "BTC Price": "$70,810",
            "Fear & Greed": 28,
            "BTC Dominance": "56.5%",
            "Funding Rate": "0.0800%",
        },
        economic_events="- Fed decision 2026-03-26\n- CPI release 2026-03-28",
        sector_data="=== SECTOR DATA ===\nDeFi TVL: $120B (-2.1%)",
        news_summary="- BTC breaks 70K resistance (CoinDesk)\n- ETH upgrade timeline (TheBlock)",
        recent_breaking="- [important] SEC approves new Bitcoin ETF",
        whale_data="- BTC transfer: 5,000 BTC ($355M) from unknown to Coinbase",
    )


# Reusable long content (>800 words) for tests that need to pass quality gate
_LONG_MOCK_CONTENT = (
    "# [CIC Market Insight] Phân tích chuyên sâu — Ngày 20/03/2026\n\n"
    "## 1. Tổng quan thị trường\n"
    "BTC đang giao dịch quanh mức **$70,810**, tăng nhẹ 1.2% trong 24h qua. "
    "Fear & Greed Index ở mức **28** (Fear), cho thấy tâm lý thị trường vẫn "
    "trong vùng sợ hãi. BTC Dominance **56.5%** tiếp tục xu hướng tăng.\n\n"
    "## 2. Cảnh báo sớm\n"
    "Không có tín hiệu cảnh báo bất thường trong 24h qua.\n\n"
    "## 3. Phân tích On-chain chuyên sâu\n"
    "MVRV Z-Score hiện tại là **1.45**, nằm trong vùng trung tính. "
    "NUPL ở mức **0.35** thuộc phase Optimism. "
    "SOPR = **1.02** cho thấy người bán đang chốt lời nhẹ. "
    "Puell Multiple **0.89** ở mức bình thường.\n\n"
    "## 4. Stablecoin & Dòng tiền\n"
    "USDT supply tăng $500M trong 24h, tín hiệu dòng tiền mới vào thị trường. "
    "ETF flow ngày 19/03: tổng +$800M, IBIT dẫn đầu +$700M.\n\n"
    "## 5. Phân tích Derivatives\n"
    "Funding Rate **0.08%** (dương) cho thấy đa số đang long. "
    "Open Interest **87,500 BTC** ổn định.\n\n"
    "## 6. Macro & Sự kiện\n"
    "Fed decision scheduled for 2026-03-26.\n\n"
    "## 7. Bảng tổng hợp chỉ số chính\n"
    "| Chỉ số | Giá trị | Đánh giá |\n"
    "| BTC | $70,810 | Tăng nhẹ |\n\n"
    "## 8. Tổng kết & Nhận định\n"
    "Tổng hợp tín hiệu cho thấy thị trường đang trong giai đoạn tích lũy. "
    + "Phân tích thêm chi tiết về thị trường tài sản mã hóa hôm nay. "
    * 200
)


# ---------------------------------------------------------------------------
# Context building
# ---------------------------------------------------------------------------


class TestBuildResearchContext:
    def test_includes_all_data_sections(self):
        """Context includes all available data sources."""
        context = _make_context()
        research = _make_research_data()

        result = _build_research_context(context, research)

        assert "CHỈ SỐ CHÍNH" in result
        assert "DỮ LIỆU THỊ TRƯỜNG" in result
        assert "ON-CHAIN NÂNG CAO" in result
        assert "MVRV_Z_Score" in result
        assert "ETF FLOW" in result
        assert "IBIT" in result
        assert "STABLECOIN" in result
        assert "Tether" in result
        assert "PI CYCLE" in result
        assert "ON-CHAIN & DERIVATIVES CƠ BẢN" in result
        assert "LỊCH SỰ KIỆN" in result
        assert "WHALE ALERT" in result
        assert "BREAKING" in result
        assert "TIN TỨC" in result

    def test_handles_empty_research_data(self):
        """Context still works with empty research data."""
        context = _make_context()
        research = ResearchData()

        result = _build_research_context(context, research)

        # Should still have pipeline data
        assert "BTC" in result
        assert "ON-CHAIN NÂNG CAO" not in result  # No BGeometrics data


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


class TestBuildResearchPrompt:
    def test_prompt_structure(self):
        """Prompt has 8-section structure and required elements."""
        prompt = _build_research_prompt("20/03/2026", "test data context")

        assert "CIC Market Insight" in prompt
        assert "20/03/2026" in prompt
        assert "2500" in prompt
        assert "Tổng quan thị trường" in prompt
        assert "Cảnh báo sớm" in prompt
        assert "On-chain chuyên sâu" in prompt
        assert "Stablecoin & Dòng tiền" in prompt
        assert "Derivatives" in prompt
        assert "Macro & Sự kiện" in prompt
        assert "Bảng tổng hợp chỉ số chính" in prompt
        assert "Tổng kết & Nhận định" in prompt
        assert "test data context" in prompt

    def test_missing_data_handling_instructions(self):
        """Prompt includes instructions for handling missing data."""
        prompt = _build_research_prompt("20/03/2026", "test data context")

        assert "XỬ LÝ THIẾU DỮ LIỆU" in prompt
        assert "BỎ QUA phần đó" in prompt
        assert "KHÔNG bịa số liệu thay thế" in prompt


# ---------------------------------------------------------------------------
# System prompt compliance
# ---------------------------------------------------------------------------


class TestSystemPrompt:
    def test_nq05_compliance_in_system_prompt(self):
        """System prompt includes NQ05 requirements."""
        assert "NQ05" in RESEARCH_SYSTEM_PROMPT
        assert "tài sản mã hóa" in RESEARCH_SYSTEM_PROMPT  # v0.30.1: slimmed — post-filter enforces

    def test_anti_fabrication_in_system_prompt(self):
        """System prompt includes anti-fabrication rules."""
        assert "CHỐNG BỊA DỮ LIỆU" in RESEARCH_SYSTEM_PROMPT
        assert "Bloomberg" in RESEARCH_SYSTEM_PROMPT
        assert "CryptoQuant" in RESEARCH_SYSTEM_PROMPT

    def test_research_depth_requirement(self):
        """System prompt requires >2500 words."""
        assert "2500" in RESEARCH_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Full generation (mocked LLM)
# ---------------------------------------------------------------------------


class TestGenerateResearchArticle:
    async def test_generates_article_with_mocked_llm(self):
        """Generate research article with mocked LLM response."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                text=_LONG_MOCK_CONTENT,
                tokens_used=5000,
                model="gemini_flash",
            )
        )

        context = _make_context()
        research = _make_research_data()

        article = await generate_research_article(mock_llm, context, research)

        assert article is not None
        assert "CIC Market Insight" in article.title
        assert article.word_count > 800
        assert article.llm_used == "gemini_flash"
        assert article.generation_time_sec > 0

        # Verify LLM was called with research system prompt
        call_kwargs = mock_llm.generate.call_args
        assert call_kwargs.kwargs["system_prompt"] == RESEARCH_SYSTEM_PROMPT
        assert call_kwargs.kwargs["max_tokens"] == RESEARCH_MAX_TOKENS
        assert call_kwargs.kwargs["temperature"] == 0.4

    async def test_includes_disclaimer(self):
        """Generated article includes NQ05 disclaimer."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                text=_LONG_MOCK_CONTENT,
                tokens_used=5000,
                model="gemini_flash",
            )
        )

        article = await generate_research_article(mock_llm, _make_context(), _make_research_data())

        assert article is not None
        assert "Tuyên bố miễn trừ trách nhiệm" in article.content

    async def test_returns_none_when_too_short(self):
        """Returns None when LLM produces critically short content."""
        short_content = "Bài viết quá ngắn chỉ có vài từ. " * 10  # ~80 words

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                text=short_content,
                tokens_used=200,
                model="gemini_flash_lite",
            )
        )

        article = await generate_research_article(mock_llm, _make_context(), _make_research_data())

        assert article is None  # Quality gate: <800 words → skip

    async def test_warns_when_below_target(self):
        """Returns article but warns when between 800-1500 words."""
        # ~1000 words (above 800 gate, below 1500 warning)
        medium_content = "Phân tích chi tiết thị trường tài sản mã hóa hôm nay. " * 120

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                text=medium_content,
                tokens_used=2000,
                model="gemini_flash",
            )
        )

        article = await generate_research_article(mock_llm, _make_context(), _make_research_data())

        assert article is not None  # Above 800, should return
        assert article.word_count > 800
        assert article.word_count < 1500
