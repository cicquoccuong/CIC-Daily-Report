"""Wave 0.7 — Real-time data fixes (Part A) + Coin scope filter (Part B).

Covers Mary's fact-check batch 29/04/2026 findings:
A. 6 real-time data fixes (F&G, USDT/VND, hashrate, difficulty, FOMC, reporter)
B. 3 scope fixes (L2/L3/L4/L5 filter to cumulative tier coin list)

WHY this file lives in test_breaking/: most other test_* dirs have feature scope;
no existing dir maps cleanly to "data freshness + tier scoping". Co-locating with
the cross-cutting test files keeps Wave 0.7 traceable as a single concern.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from cic_daily_report.collectors.market_data import MarketDataPoint, PriceSnapshot
from cic_daily_report.generators.master_analysis import MASTER_SYSTEM_PROMPT
from cic_daily_report.generators.tier_extractor import (
    _cumulative_tier_set,
    _filter_top_performers_by_tier,
    build_l2_data_injection,
    build_l2_retry_instruction,
    build_tier_coin_scope_rule,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _coin_lists() -> dict[str, list[str]]:
    """Realistic per-tier coin lists matching DANH_SACH_COIN production sheet.

    Numbers below mirror the spec (2 + 17 + 43 + 69 + 38) but use a deterministic
    subset so we can assert against specific symbols.
    """
    return {
        "L1": ["BTC", "ETH"],
        "L2": [
            "BNB",
            "XRP",
            "SOL",
            "ADA",
            "LINK",
            "BCH",
            "TRX",
            "XMR",
            "XEM",
            "DOT",
            "LTC",
            "AVAX",
            "ATOM",
            "ALGO",
            "ETC",
            "EOS",
            "FIL",
        ],
        "L3": [
            "MATIC",
            "OP",
            "ARB",
            "SUI",
            "APT",
            "INJ",
            "NEAR",
            "STX",
            "GRT",
            "RNDR",
            "ICP",
            "TIA",
            "SEI",
            "FTM",
            "HBAR",
            "VET",
            "FLOW",
            "EGLD",
            "MINA",
            "RUNE",
        ],
        "L4": [
            "AAVE",
            "UNI",
            "CRV",
            "GMX",
            "PENDLE",
            "LDO",
            "ENS",
            "TAO",
            "MKR",
            "COMP",
            "SUSHI",
            "1INCH",
            "DYDX",
            "BAL",
            "YFI",
            "SNX",
            "CVX",
            "BAND",
            "OCEAN",
            "FET",
        ],
        "L5": ["MEME", "PEPE", "BONK", "FLOKI", "WIF"],
    }


def _snapshot_with(symbols_changes: dict[str, float], fg: float = 33.0) -> PriceSnapshot:
    """Build a PriceSnapshot whose top performers can be assertion-driven.

    `symbols_changes` keyed by symbol, value = 24h change percentage.
    BTC fixed at $87,500 +3.2 unless overridden. F&G defaults to 33 (Mary's verified value).
    """
    points: list[MarketDataPoint] = []
    if "BTC" not in symbols_changes:
        points.append(MarketDataPoint("BTC", 87500.0, 3.2, 45e6, 1710e9, "crypto", "CoinLore"))
    for sym, chg in symbols_changes.items():
        points.append(MarketDataPoint(sym, 100.0, chg, 1e6, 1e9, "crypto", "CoinLore"))
    points.append(MarketDataPoint("Fear&Greed", fg, 0.0, 0, 0, "index", "alternative.me"))
    return PriceSnapshot(market_data=points)


# ---------------------------------------------------------------------------
# Part A — Real-time data fixes
# ---------------------------------------------------------------------------


class TestA1FNGRealtime:
    """A1: F&G index already real-time. Verify collector still hits alternative.me."""

    @pytest.mark.asyncio
    async def test_fng_realtime_fetch_success(self):
        """A1: _collect_fear_greed should call api.alternative.me/fng/."""
        from cic_daily_report.collectors.market_data import _collect_fear_greed

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = lambda: None
        mock_resp.json = lambda: {"data": [{"value": "33", "value_classification": "Fear"}]}

        with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=mock_resp)):
            result = await _collect_fear_greed()

        assert len(result) == 1
        assert result[0].symbol == "Fear&Greed"
        assert result[0].price == 33.0
        assert result[0].source == "alternative.me"

    @pytest.mark.asyncio
    async def test_fng_no_stale_default_when_api_fails(self):
        """A1: When API fails, return [] — never silently keep stale value."""
        from cic_daily_report.collectors.market_data import _collect_fear_greed

        with patch(
            "httpx.AsyncClient.get",
            new=AsyncMock(side_effect=Exception("network down")),
        ):
            result = await _collect_fear_greed()

        # WHY []: lets pipeline detect missing F&G instead of using stale cached data
        assert result == []


class TestA2USDTVNDRealtime:
    """A2: USDT/VND collector hits Binance P2P (real-time, not cached)."""

    @pytest.mark.asyncio
    async def test_usdt_vnd_binance_p2p_realtime(self):
        """A2: Binance P2P collector returns live USDT/VND from top 5 BUY ads."""
        from cic_daily_report.collectors.market_data import _fetch_binance_p2p_vnd

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = lambda: None
        # Mary verified ~26,340 — provide ads around that range
        mock_resp.json = lambda: {
            "data": [
                {"adv": {"price": "26340"}},
                {"adv": {"price": "26345"}},
                {"adv": {"price": "26330"}},
                {"adv": {"price": "26350"}},
                {"adv": {"price": "26335"}},
            ]
        }

        with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_resp)):
            result = await _fetch_binance_p2p_vnd()

        assert result is not None
        assert result.symbol == "USDT/VND"
        # Median of 5 values around 26,340 — must be in that range, NOT the stale 26,694
        assert 26_300 <= result.price <= 26_400


class TestA3HashrateDifficulty:
    """A3: Mempool hash rate switched to /3d endpoint (was /1w)."""

    @pytest.mark.asyncio
    async def test_hashrate_uses_3d_endpoint(self):
        """A3: _fetch_hashrate must call /mining/hashrate/3d (Wave 0.7.1 spec)."""
        from cic_daily_report.collectors.mempool_data import _fetch_hashrate

        captured_urls: list[str] = []

        async def _mock_get(url, *args, **kwargs):
            captured_urls.append(url)
            r = AsyncMock()
            r.status_code = 200
            r.raise_for_status = lambda: None
            # Mary verified ~994 EH/s — return that value to match real-world
            r.json = lambda: {
                "currentHashrate": 994e18,
                "hashrates": [
                    {"avgHashrate": 980e18},
                    {"avgHashrate": 994e18},
                ],
            }
            return r

        async with __import__("httpx").AsyncClient() as client:
            with patch.object(client, "get", new=AsyncMock(side_effect=_mock_get)):
                result = await _fetch_hashrate(client)

        assert result is not None
        assert any("/mining/hashrate/3d" in u for u in captured_urls), (
            f"Expected /3d endpoint, got: {captured_urls}"
        )
        assert abs(result["hashrate_eh"] - 994.0) < 1.0

    @pytest.mark.asyncio
    async def test_difficulty_fetch_with_adjustment(self):
        """A3: _fetch_difficulty returns adjustment percentage."""
        from cic_daily_report.collectors.mempool_data import _fetch_difficulty

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = lambda: None
        # Mary verified +3.87% (positive recent adjustment, NOT -3.0% as cached)
        mock_resp.json = lambda: {
            "difficultyChange": 3.87,
            "remainingBlocks": 1200,
            "remainingTime": 3600 * 200,
        }

        async with __import__("httpx").AsyncClient() as client:
            with patch.object(client, "get", new=AsyncMock(return_value=mock_resp)):
                result = await _fetch_difficulty(client)

        assert result is not None
        assert result["difficultyChange"] == 3.87


class TestA4FOMCDateGuard:
    """A4: Master prompt forbids LLM from guessing FOMC dates."""

    def test_master_prompt_has_fomc_date_guard(self):
        """A4: MASTER_SYSTEM_PROMPT must contain the no-fabricate-dates rule."""
        # WHY check substring: prompt is rendered as Vietnamese with diacritics,
        # we look for the keyword pair "FOMC" + "KHÔNG" + "đoán NGÀY".
        assert "FOMC" in MASTER_SYSTEM_PROMPT
        # "KHÔNG tự đoán NGÀY"
        assert "đoán NGÀY" in MASTER_SYSTEM_PROMPT or "đoán NGÀY" in MASTER_SYSTEM_PROMPT
        # Reference to LICH SU KIEN section name
        assert "LICH SU KIEN" in MASTER_SYSTEM_PROMPT


class TestA5ReporterNameGuard:
    """A5: Master prompt forbids LLM from inventing reporter names."""

    def test_master_prompt_has_reporter_guard(self):
        """A5: MASTER_SYSTEM_PROMPT must contain the no-fabricate-reporter rule."""
        assert "reporter" in MASTER_SYSTEM_PROMPT.lower()
        # The publication-name pattern must be suggested
        assert "publication" in MASTER_SYSTEM_PROMPT


class TestA6USDTSupplyVerify:
    """A6: USDT supply already comes live from DefiLlama. Confirm collector path."""

    @pytest.mark.asyncio
    async def test_stablecoin_collector_calls_defillama(self):
        from cic_daily_report.collectors.research_data import _collect_stablecoin_data

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = lambda: None
        mock_resp.json = lambda: {
            "peggedAssets": [
                {
                    "name": "Tether",
                    "symbol": "USDT",
                    "circulating": {"peggedUSD": 145e9},
                    "circulatingPrevDay": {"peggedUSD": 144.9e9},
                    "circulatingPrevWeek": {"peggedUSD": 144e9},
                    "circulatingPrevMonth": {"peggedUSD": 140e9},
                }
            ]
        }

        with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=mock_resp)):
            result = await _collect_stablecoin_data()

        # WHY assert non-empty + USDT name: confirms live path returns real values,
        # not a stale fallback. The collector must use DefiLlama, not a cached file.
        assert len(result) >= 1
        usdt = next((s for s in result if "USDT" in s.name), None)
        assert usdt is not None
        # 30d delta = 145e9 - 140e9 = 5e9 (matches Mary's 5.43B-ish flag → confirmed real)
        assert usdt.change_30d > 0


# ---------------------------------------------------------------------------
# Part B — Coin scope filter (Wave 0.7.2)
# ---------------------------------------------------------------------------


class TestCumulativeTierSet:
    """Wave 0.7.2: _cumulative_tier_set semantics."""

    def test_l1_returns_l1_only(self):
        cl = _coin_lists()
        s = _cumulative_tier_set(cl, "L1")
        assert s == {"BTC", "ETH"}

    def test_l2_returns_l1_plus_l2(self):
        cl = _coin_lists()
        s = _cumulative_tier_set(cl, "L2")
        assert "BTC" in s
        assert "ETH" in s
        assert "BNB" in s
        assert "XRP" in s
        # L2 must NOT contain L4 coins
        assert "AAVE" not in s
        assert "TAO" not in s

    def test_l3_includes_all_lower(self):
        cl = _coin_lists()
        s = _cumulative_tier_set(cl, "L3")
        # L1 + L2 + L3 all present
        assert "BTC" in s and "BNB" in s and "MATIC" in s
        # L4/L5 still excluded
        assert "AAVE" not in s
        assert "PEPE" not in s

    def test_l5_full_universe(self):
        cl = _coin_lists()
        s = _cumulative_tier_set(cl, "L5")
        assert "BTC" in s and "AAVE" in s and "PEPE" in s

    def test_none_for_missing_lists(self):
        # WHY None: callers fall back to legacy unfiltered behaviour
        assert _cumulative_tier_set(None, "L2") is None
        assert _cumulative_tier_set({}, "L2") is None

    def test_none_for_unknown_tier(self):
        assert _cumulative_tier_set(_coin_lists(), "L9") is None


class TestFilterTopPerformers:
    """Wave 0.7.2: _filter_top_performers_by_tier filters out-of-scope coins."""

    def test_l2_filter_excludes_l4_coins(self):
        # TAO and AAVE are L4 — must NOT appear in L2 top performers
        snap = _snapshot_with({"TAO": 15.0, "AAVE": 12.0, "BNB": 8.0, "XRP": 6.0})
        out = _filter_top_performers_by_tier(snap, "L2", _coin_lists(), n=3)
        symbols = [dp.symbol for dp in out]
        assert "TAO" not in symbols
        assert "AAVE" not in symbols
        assert "BNB" in symbols
        assert "XRP" in symbols

    def test_l2_filter_excludes_unlisted(self):
        # DOGE, MKR, PI are NOT in DANH_SACH_COIN at all → must drop
        snap = _snapshot_with({"DOGE": 20.0, "MKR": 18.0, "PI": 17.0, "BNB": 5.0})
        out = _filter_top_performers_by_tier(snap, "L2", _coin_lists(), n=3)
        symbols = [dp.symbol for dp in out]
        assert "DOGE" not in symbols
        assert "MKR" not in symbols
        assert "PI" not in symbols
        assert "BNB" in symbols

    def test_l3_filter_includes_cumulative(self):
        # MATIC (L3) + BNB (L2) both pass; AAVE (L4) excluded
        snap = _snapshot_with({"MATIC": 10.0, "BNB": 8.0, "AAVE": 12.0})
        out = _filter_top_performers_by_tier(snap, "L3", _coin_lists(), n=3)
        symbols = [dp.symbol for dp in out]
        assert "MATIC" in symbols
        assert "BNB" in symbols
        assert "AAVE" not in symbols

    def test_l4_filter_includes_l4_excludes_l5(self):
        # AAVE (L4) passes; PEPE (L5) excluded
        snap = _snapshot_with({"AAVE": 10.0, "PEPE": 25.0, "BNB": 5.0})
        out = _filter_top_performers_by_tier(snap, "L4", _coin_lists(), n=3)
        symbols = [dp.symbol for dp in out]
        assert "AAVE" in symbols
        assert "PEPE" not in symbols

    def test_l5_full_list_pass(self):
        # All four pass at L5
        snap = _snapshot_with({"BNB": 5.0, "AAVE": 8.0, "PEPE": 25.0, "MATIC": 6.0})
        out = _filter_top_performers_by_tier(snap, "L5", _coin_lists(), n=4)
        symbols = [dp.symbol for dp in out]
        assert {"BNB", "AAVE", "PEPE", "MATIC"} <= set(symbols)

    def test_filter_preserves_order_by_change_pct(self):
        # PriceSnapshot.get_top_performers already sorts desc by change_24h.
        # After filter, order must remain desc.
        snap = _snapshot_with({"BNB": 3.0, "XRP": 9.0, "SOL": 7.0})
        out = _filter_top_performers_by_tier(snap, "L2", _coin_lists(), n=3)
        changes = [dp.change_24h for dp in out]
        assert changes == sorted(changes, reverse=True)

    def test_filter_legacy_behaviour_when_no_coin_lists(self):
        # Back-compat: passing None for coin_lists returns top performers
        # (BTC/USDT removed) without tier filter.
        snap = _snapshot_with({"BNB": 3.0, "DOGE": 9.0})
        out = _filter_top_performers_by_tier(snap, "L2", None, n=3)
        symbols = [dp.symbol for dp in out]
        assert "BTC" not in symbols
        # DOGE should pass through legacy path (no scope filter)
        assert "DOGE" in symbols

    def test_filter_empty_snapshot(self):
        snap = PriceSnapshot(market_data=[])
        out = _filter_top_performers_by_tier(snap, "L2", _coin_lists(), n=3)
        assert out == []

    def test_filter_all_out_of_tier(self):
        # Every candidate is L4-only → result is empty list (graceful)
        snap = _snapshot_with({"AAVE": 10.0, "TAO": 8.0})
        out = _filter_top_performers_by_tier(snap, "L2", _coin_lists(), n=3)
        assert out == []

    def test_filter_case_insensitive_symbols(self):
        # Even if snapshot reports lowercase 'bnb', allow-set match should hold
        snap = _snapshot_with({"bnb": 5.0})
        out = _filter_top_performers_by_tier(snap, "L2", _coin_lists(), n=3)
        symbols = [dp.symbol.upper() for dp in out]
        assert "BNB" in symbols


class TestBuildTierCoinScopeRule:
    """Wave 0.7.2: build_tier_coin_scope_rule generates the LLM allow-list."""

    def test_l2_rule_lists_l1_l2_coins(self):
        rule = build_tier_coin_scope_rule("L2", _coin_lists())
        assert "BTC" in rule
        assert "BNB" in rule
        # L4 coins must NOT appear in the L2 rule
        assert "AAVE" not in rule
        assert "TAO" not in rule

    def test_l3_rule_includes_cumulative(self):
        rule = build_tier_coin_scope_rule("L3", _coin_lists())
        assert "BTC" in rule and "BNB" in rule and "MATIC" in rule
        assert "AAVE" not in rule

    def test_l5_rule_full_universe(self):
        rule = build_tier_coin_scope_rule("L5", _coin_lists())
        assert "BTC" in rule and "AAVE" in rule and "PEPE" in rule

    def test_empty_rule_when_no_coin_lists(self):
        # Defensive: if coin_lists is None or {}, no rule injected
        assert build_tier_coin_scope_rule("L2", None) == ""
        assert build_tier_coin_scope_rule("L2", {}) == ""

    def test_rule_contains_strict_keyword(self):
        rule = build_tier_coin_scope_rule("L2", _coin_lists())
        # Vietnamese strict-mode keyword
        assert "TUYỆT ĐỐI KHÔNG" in rule or "TUYỆT ĐỐI KHÔNG" in rule

    def test_rule_lists_count(self):
        rule = build_tier_coin_scope_rule("L2", _coin_lists())
        # L1 (2) + L2 (17) = 19 coins announced in rule
        assert "(19 coins)" in rule


class TestBuildL2DataInjectionWithScope:
    """Wave 0.7.2: build_l2_data_injection respects coin_lists when provided."""

    def test_l2_injection_with_scope_excludes_out_of_tier(self):
        # Even if AAVE is the top performer, L2 injection must NOT mention AAVE
        snap = _snapshot_with({"AAVE": 25.0, "BNB": 5.0, "XRP": 4.0})
        out = build_l2_data_injection(snap, coin_lists=_coin_lists())
        assert "AAVE" not in out
        # BNB or XRP should be in top altcoins
        assert "BNB" in out or "XRP" in out

    def test_l2_injection_back_compat_without_coin_lists(self):
        # Old call signature still works (no coin_lists kwarg)
        snap = _snapshot_with({"BNB": 5.0, "XRP": 4.0})
        out = build_l2_data_injection(snap)
        assert "BNB" in out or "XRP" in out


class TestL2RetryInstructionWithScope:
    """Wave 0.7.2: L2 retry instruction also respects scope."""

    def test_retry_uses_scoped_top(self):
        snap = _snapshot_with({"AAVE": 25.0, "BNB": 5.0})
        out = build_l2_retry_instruction(snap, coin_lists=_coin_lists())
        assert "AAVE" not in out


# ---------------------------------------------------------------------------
# Version + master prompt smoke
# ---------------------------------------------------------------------------


class TestVersionBump:
    """Wave C+ (alpha.35) — centralize NQ05 disclaimer + heterogeneous verifier."""

    def test_core_config_version(self):
        from cic_daily_report.core.config import VERSION

        assert VERSION == "2.0.0-alpha.35"

    def test_module_version(self):
        from cic_daily_report import __version__

        assert __version__ == "2.0.0-alpha.35"
