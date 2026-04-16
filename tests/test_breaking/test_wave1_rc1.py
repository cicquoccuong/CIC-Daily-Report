"""Tests for Wave 1 RC1 tasks: QO.12, QO.13, QO.15, QO.16, QO.17.

QO.12 — Metric-type daily dedup (F&G max 1/day, BTC/ETH delta >= 5%)
QO.13 — Entity pattern expansion (countries + organizations)
QO.15 — Crypto relevance check at event_detector level
QO.16 — MAX_EVENTS_PER_DAY = 12
QO.17 — VN regulatory keywords + auto CRITICAL severity
"""

from datetime import datetime, timedelta, timezone

from cic_daily_report.breaking.dedup_manager import (
    METRIC_DEDUP_PRICE_DELTA,
    DedupEntry,
    DedupManager,
    _extract_entities,
    _extract_percentage,
    compute_hash,
)
from cic_daily_report.breaking.event_detector import (
    VN_REGULATORY_KEYWORDS,
    BreakingEvent,
    DetectionConfig,
    _evaluate_items,
    _match_keywords,
    is_crypto_relevant,
    is_vn_regulatory,
)
from cic_daily_report.breaking.feedback import MAX_EVENTS_PER_DAY as FEEDBACK_MAX_EVENTS
from cic_daily_report.breaking.severity_classifier import (
    CRITICAL,
    ClassificationConfig,
    _determine_severity,
    classify_event,
)


def _event(title="BTC hack", source="CoinDesk", url="https://x.com", panic_score=80):
    return BreakingEvent(title=title, source=source, url=url, panic_score=panic_score)


def _make_item(title="BTC news", panic_votes=None, source_title="CoinDesk"):
    votes = panic_votes or {}
    return {
        "title": title,
        "source": {"title": source_title},
        "url": f"https://example.com/{title.replace(' ', '-')}",
        "votes": votes,
    }


# ============================================================================
# QO.15 — Crypto relevance check at event_detector
# ============================================================================


class TestQO15CryptoRelevanceAtDetector:
    """QO.15: is_crypto_relevant() in event_detector filters non-crypto early."""

    def test_bitcoin_relevant(self):
        assert is_crypto_relevant("Bitcoin ETF approved by SEC") is True

    def test_ethereum_relevant(self):
        assert is_crypto_relevant("Ethereum gas fees spike") is True

    def test_exchange_relevant(self):
        assert is_crypto_relevant("Binance faces regulatory issues") is True

    def test_geopolitical_relevant(self):
        """Geopolitical events bypass crypto requirement."""
        assert is_crypto_relevant("Iran launches missile attack") is True

    def test_sports_not_relevant(self):
        """Pure sports news filtered out."""
        assert is_crypto_relevant("NBA draft picks announced today") is False

    def test_tech_company_not_relevant(self):
        """Generic tech news without crypto context."""
        assert is_crypto_relevant("Apple releases new iPhone model") is False

    def test_vn_regulatory_relevant(self):
        """QO.17: VN regulatory keywords are always crypto-relevant."""
        assert is_crypto_relevant("Nghị định mới về quản lý crypto tại VN") is True

    def test_fear_greed_relevant(self):
        assert is_crypto_relevant("Fear & Greed Index drops to 10") is True

    def test_hack_relevant(self):
        assert is_crypto_relevant("Major hack discovered in DeFi protocol") is True

    def test_empty_title_not_relevant(self):
        assert is_crypto_relevant("") is False


class TestQO15EarlyFilterInEvaluateItems:
    """QO.15: _evaluate_items skips non-crypto items before keyword/score checks."""

    def test_non_crypto_item_filtered_even_with_high_panic(self):
        """Non-crypto item with high panic score should be filtered at detector level.
        WHY 'World Cup soccer final': avoids substring false positives (e.g. 'ton' in 'tonight').
        """
        items = [_make_item("World Cup soccer final scores", {"negative": 90, "toxic": 10})]
        cfg = DetectionConfig(panic_threshold=50)
        events = _evaluate_items(items, cfg)
        assert len(events) == 0

    def test_crypto_item_passes_through(self):
        """Crypto item should pass through relevance check."""
        items = [_make_item("Bitcoin crashes 10% overnight", {"negative": 50})]
        cfg = DetectionConfig(panic_threshold=50)
        events = _evaluate_items(items, cfg)
        assert len(events) == 1

    def test_geo_item_passes_through(self):
        """Geopolitical item passes relevance check (war impacts crypto)."""
        items = [_make_item("War erupts in Middle East")]
        cfg = DetectionConfig(panic_threshold=99)
        events = _evaluate_items(items, cfg)
        assert len(events) == 1

    def test_vn_regulatory_passes_through(self):
        """VN regulatory item passes relevance check."""
        items = [_make_item("Nghị định mới cấm giao dịch crypto")]
        cfg = DetectionConfig(panic_threshold=99)
        events = _evaluate_items(items, cfg)
        # WHY: VN regulatory keywords are in VN_REGULATORY_KEYWORDS, matched
        # by _match_keywords QO.17 addition
        assert len(events) == 1


# ============================================================================
# QO.12 — Metric-type daily dedup
# ============================================================================


class TestQO12FearGreedDedup:
    """QO.12: F&G events max 1 per calendar day."""

    def test_first_fg_event_passes(self):
        """First F&G event of the day should pass."""
        mgr = DedupManager()
        event = _event("Fear & Greed Index drops to 10 — Extreme Fear", "Alt.me", "https://a.com")
        result = mgr.check_and_filter([event])
        assert len(result.new_events) == 1

    def test_second_fg_event_blocked(self):
        """Second F&G event same day should be blocked."""
        now = datetime.now(timezone.utc)
        existing = DedupEntry(
            hash=compute_hash("Fear & Greed drops to 15", "Alt.me"),
            title="Fear & Greed drops to 15",
            source="Alt.me",
            detected_at=now.isoformat(),
            status="sent",
        )
        mgr = DedupManager(existing_entries=[existing])
        event = _event("Extreme Fear: F&G at 12 today", "CoinDesk", "https://b.com", panic_score=50)
        result = mgr.check_and_filter([event])
        assert len(result.new_events) == 0
        assert result.duplicates_skipped == 1

    def test_fg_from_yesterday_allows_new(self):
        """F&G from yesterday should NOT block today's F&G."""
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        existing = DedupEntry(
            hash=compute_hash("Fear & Greed at 20", "Alt.me"),
            title="Fear & Greed at 20",
            source="Alt.me",
            detected_at=yesterday.isoformat(),
            status="sent",
        )
        mgr = DedupManager(existing_entries=[existing])
        event = _event("Fear & Greed Index drops to 10", "Alt.me", "https://c.com")
        result = mgr.check_and_filter([event])
        assert len(result.new_events) == 1

    def test_fg_abbreviation_detected(self):
        """F&G abbreviation also triggers metric dedup."""
        now = datetime.now(timezone.utc)
        existing = DedupEntry(
            hash="some_hash",
            title="F&G drops to extreme fear level",
            source="S",
            detected_at=now.isoformat(),
            status="pending",
        )
        mgr = DedupManager(existing_entries=[existing])
        event = _event("F&G index at 8 — worst in months", "CoinDesk", "https://d.com")
        result = mgr.check_and_filter([event])
        assert len(result.new_events) == 0

    def test_extreme_greed_also_capped(self):
        """Extreme Greed events also capped at 1/day."""
        now = datetime.now(timezone.utc)
        existing = DedupEntry(
            hash="h1",
            title="Extreme Greed reaches 90",
            source="S",
            detected_at=now.isoformat(),
        )
        mgr = DedupManager(existing_entries=[existing])
        event = _event("Extreme Greed at 92 today", "Alt.me", "https://e.com")
        result = mgr.check_and_filter([event])
        assert len(result.new_events) == 0


class TestQO12BtcEthDropDedup:
    """QO.12: BTC/ETH price drops only sent when delta >= 5%."""

    def test_first_btc_drop_passes(self):
        """First BTC drop event of the day should pass."""
        mgr = DedupManager()
        event = _event("Bitcoin drops 7% in flash crash", "CoinDesk", "https://f.com")
        result = mgr.check_and_filter([event])
        assert len(result.new_events) == 1

    def test_small_delta_btc_drop_blocked(self):
        """BTC drop with < 5% delta from previous → blocked."""
        now = datetime.now(timezone.utc)
        existing = DedupEntry(
            hash="h1",
            title="BTC crashes 7% overnight",
            source="S",
            detected_at=now.isoformat(),
        )
        mgr = DedupManager(existing_entries=[existing])
        # 8% vs 7% = 1% delta < 5%
        event = _event("Bitcoin drops 8% as selloff continues", "Reuters", "https://g.com")
        result = mgr.check_and_filter([event])
        assert len(result.new_events) == 0

    def test_large_delta_btc_drop_passes(self):
        """BTC drop with >= 5% delta from previous → passes."""
        now = datetime.now(timezone.utc)
        existing = DedupEntry(
            hash="h1",
            title="BTC drops 3% today",
            source="S",
            detected_at=now.isoformat(),
        )
        mgr = DedupManager(existing_entries=[existing])
        # 10% vs 3% = 7% delta >= 5%
        event = _event("Bitcoin crash 10% in major selloff", "Reuters", "https://h.com")
        result = mgr.check_and_filter([event])
        assert len(result.new_events) == 1

    def test_eth_drop_also_checked(self):
        """ETH drops also subject to metric dedup."""
        now = datetime.now(timezone.utc)
        existing = DedupEntry(
            hash="h1",
            title="Ethereum plunges 5%",
            source="S",
            detected_at=now.isoformat(),
        )
        mgr = DedupManager(existing_entries=[existing])
        # 6% vs 5% = 1% delta < 5%
        event = _event("ETH drops 6% following BTC", "CoinDesk", "https://i.com")
        result = mgr.check_and_filter([event])
        assert len(result.new_events) == 0

    def test_yesterday_drop_allows_new(self):
        """Drop from yesterday should NOT block today's drop."""
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        existing = DedupEntry(
            hash="h1",
            title="BTC crashes 7%",
            source="S",
            detected_at=yesterday.isoformat(),
        )
        mgr = DedupManager(existing_entries=[existing])
        event = _event("Bitcoin drops 8% today", "Reuters", "https://j.com")
        result = mgr.check_and_filter([event])
        assert len(result.new_events) == 1

    def test_non_drop_btc_event_not_affected(self):
        """BTC events without drop indicators are not affected by metric dedup."""
        now = datetime.now(timezone.utc)
        existing = DedupEntry(
            hash="h1",
            title="BTC drops 7%",
            source="S",
            detected_at=now.isoformat(),
        )
        mgr = DedupManager(existing_entries=[existing])
        # "surges" is not a drop indicator
        event = _event("Bitcoin surges 5% on ETF news", "Reuters", "https://k.com")
        result = mgr.check_and_filter([event])
        assert len(result.new_events) == 1


class TestExtractPercentage:
    """QO.12: _extract_percentage helper."""

    def test_integer_percentage(self):
        assert _extract_percentage("BTC drops 7% today") == 7.0

    def test_decimal_percentage(self):
        assert _extract_percentage("ETH plunges 3.5% overnight") == 3.5

    def test_no_percentage(self):
        assert _extract_percentage("Bitcoin reaches new high") is None

    def test_first_percentage_extracted(self):
        """When multiple %, return the first one."""
        assert _extract_percentage("BTC drops 7% and ETH falls 5%") == 7.0

    def test_metric_dedup_price_delta_value(self):
        """Verify the delta threshold constant."""
        assert METRIC_DEDUP_PRICE_DELTA == 5.0


# ============================================================================
# QO.13 — Entity pattern expansion
# ============================================================================


class TestQO13EntityExpansion:
    """QO.13: Countries and organizations detected as entities for dedup."""

    # --- Countries ---

    def test_eu_extracted(self):
        result = _extract_entities("EU passes MiCA regulation")
        assert "eu" in result

    def test_turkey_extracted(self):
        result = _extract_entities("Turkey bans crypto payments")
        assert "turkey" in result

    def test_japan_extracted(self):
        result = _extract_entities("Japan approves stablecoin framework")
        assert "japan" in result

    def test_korea_extracted(self):
        result = _extract_entities("Korea launches crypto tax")
        assert "korea" in result

    def test_india_extracted(self):
        result = _extract_entities("India considers crypto ban")
        assert "india" in result

    def test_brazil_extracted(self):
        result = _extract_entities("Brazil legalizes crypto payments")
        assert "brazil" in result

    def test_russia_extracted(self):
        result = _extract_entities("Russia restricts crypto mining")
        assert "russia" in result

    def test_switzerland_extracted(self):
        result = _extract_entities("Switzerland crypto valley growth")
        assert "switzerland" in result

    def test_germany_extracted(self):
        result = _extract_entities("Germany institutional crypto adoption")
        assert "germany" in result

    def test_france_extracted(self):
        result = _extract_entities("France crypto regulation update")
        assert "france" in result

    def test_uae_extracted(self):
        result = _extract_entities("UAE becomes crypto hub")
        assert "uae" in result

    def test_argentina_extracted(self):
        result = _extract_entities("Argentina dollar crisis crypto")
        assert "argentina" in result

    def test_nigeria_extracted(self):
        result = _extract_entities("Nigeria bans P2P crypto trading")
        assert "nigeria" in result

    # --- Organizations ---

    def test_boj_extracted(self):
        """Bank of Japan (BOJ) extracted as entity."""
        result = _extract_entities("BOJ rate decision impacts crypto")
        assert "boj" in result

    def test_pboc_extracted(self):
        """People's Bank of China (PBOC) extracted."""
        result = _extract_entities("PBOC issues digital yuan update")
        assert "pboc" in result

    def test_imf_extracted(self):
        result = _extract_entities("IMF warns about crypto risks")
        assert "imf" in result

    def test_fatf_extracted(self):
        result = _extract_entities("FATF updates crypto travel rule")
        assert "fatf" in result

    def test_onus_extracted(self):
        """VN exchange ONUS extracted."""
        result = _extract_entities("ONUS exchange launches new feature")
        assert "onus" in result

    def test_vasp_extracted(self):
        result = _extract_entities("VASP registration requirements")
        assert "vasp" in result

    def test_sbv_extracted(self):
        """State Bank of Vietnam (SBV)."""
        result = _extract_entities("SBV issues warning about crypto")
        assert "sbv" in result

    # --- Entity overlap dedup for same country ---

    def test_same_country_events_deduped(self):
        """Two events about EU regulation → entity overlap detected."""
        entries = [DedupEntry(hash="h1", title="EU passes MiCA crypto regulation", source="S")]
        assert _extract_entities("EU MiCA regulation takes effect today") != set()
        # Both have EU + MiCA → Jaccard should be high
        from cic_daily_report.breaking.dedup_manager import _is_entity_overlap

        assert _is_entity_overlap("EU MiCA regulation takes effect today", entries) is True


# ============================================================================
# QO.16 — MAX_EVENTS_PER_DAY = 12
# ============================================================================


class TestQO16MaxEventsPerDay:
    """QO.16: Daily event cap enforcement."""

    def test_feedback_max_events_is_12(self):
        """feedback.py MAX_EVENTS_PER_DAY = 12 (was 100)."""
        assert FEEDBACK_MAX_EVENTS == 12

    def test_pipeline_max_events_per_day_is_12(self):
        """breaking_pipeline.py MAX_EVENTS_PER_DAY = 12."""
        from cic_daily_report.breaking_pipeline import MAX_EVENTS_PER_DAY

        assert MAX_EVENTS_PER_DAY == 12

    def test_count_today_sent_events_empty(self):
        """No sent events → count = 0."""
        from cic_daily_report.breaking_pipeline import _count_today_sent_events

        mgr = DedupManager()
        assert _count_today_sent_events(mgr) == 0

    def test_count_today_sent_events_counts_sent(self):
        """Counts 'sent' status entries from today."""
        from cic_daily_report.breaking_pipeline import _count_today_sent_events

        now = datetime.now(timezone.utc)
        entries = [
            DedupEntry(
                hash=f"h{i}",
                title=f"Event {i}",
                source="S",
                status="sent",
                detected_at=now.isoformat(),
            )
            for i in range(5)
        ]
        mgr = DedupManager(existing_entries=entries)
        assert _count_today_sent_events(mgr) == 5

    def test_count_today_excludes_yesterday(self):
        """Events from yesterday are not counted."""
        from cic_daily_report.breaking_pipeline import _count_today_sent_events

        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        entries = [
            DedupEntry(
                hash="h1",
                title="Old event",
                source="S",
                status="sent",
                detected_at=yesterday.isoformat(),
            )
        ]
        mgr = DedupManager(existing_entries=entries)
        assert _count_today_sent_events(mgr) == 0

    def test_count_today_excludes_pending(self):
        """Pending events are not counted as sent."""
        from cic_daily_report.breaking_pipeline import _count_today_sent_events

        now = datetime.now(timezone.utc)
        entries = [
            DedupEntry(
                hash="h1",
                title="Pending event",
                source="S",
                status="pending",
                detected_at=now.isoformat(),
            )
        ]
        mgr = DedupManager(existing_entries=entries)
        assert _count_today_sent_events(mgr) == 0

    def test_count_today_includes_sent_digest(self):
        """'sent_digest' status also counted."""
        from cic_daily_report.breaking_pipeline import _count_today_sent_events

        now = datetime.now(timezone.utc)
        entries = [
            DedupEntry(
                hash="h1",
                title="Digest event",
                source="S",
                status="sent_digest",
                detected_at=now.isoformat(),
            )
        ]
        mgr = DedupManager(existing_entries=entries)
        assert _count_today_sent_events(mgr) == 1


# ============================================================================
# QO.17 — VN regulatory keywords + auto CRITICAL severity
# ============================================================================


class TestQO17VNRegulatoryKeywords:
    """QO.17: VN regulatory keywords trigger event detection."""

    def test_thong_tu_triggers(self):
        result = _match_keywords(
            "Thông tư mới về quản lý tài sản mã hóa",
            [],  # No base keywords — VN regulatory checked separately
        )
        assert "thông tư" in result

    def test_nghi_dinh_triggers(self):
        result = _match_keywords("Nghị định về crypto sắp ban hành", [])
        assert "nghị định" in result

    def test_onus_triggers(self):
        result = _match_keywords("ONUS exchange bị điều tra", [])
        assert "onus" in result

    def test_vasp_triggers(self):
        result = _match_keywords("VASP registration required in Vietnam", [])
        assert "vasp" in result

    def test_sbv_triggers(self):
        result = _match_keywords("SBV issues crypto warning", [])
        assert "sbv" in result

    def test_bo_tai_chinh_triggers(self):
        result = _match_keywords("Bộ Tài chính ban hành quy định mới", [])
        assert "bộ tài chính" in result

    def test_cam_giao_dich_triggers(self):
        result = _match_keywords("Cấm giao dịch crypto tại Việt Nam", [])
        assert "cấm giao dịch" in result

    def test_vietnam_crypto_ban_triggers(self):
        result = _match_keywords("Vietnam crypto ban takes effect", [])
        assert "vietnam crypto ban" in result

    def test_state_bank_of_vietnam_triggers(self):
        result = _match_keywords("State Bank of Vietnam restricts crypto", [])
        assert "state bank of vietnam" in result

    def test_normal_text_no_vn_trigger(self):
        """Normal text without VN keywords → no VN regulatory match."""
        result = _match_keywords("Bitcoin reaches new all-time high", [])
        assert result == []


class TestQO17VNRegulatoryBoolCheck:
    """QO.17: is_vn_regulatory() boolean check."""

    def test_thong_tu_is_vn_regulatory(self):
        assert is_vn_regulatory("Thông tư mới về crypto") is True

    def test_nghi_dinh_is_vn_regulatory(self):
        assert is_vn_regulatory("Nghị định quản lý tài sản số") is True

    def test_sbv_is_vn_regulatory(self):
        assert is_vn_regulatory("SBV warns about crypto risks") is True

    def test_normal_crypto_not_vn_regulatory(self):
        assert is_vn_regulatory("Bitcoin surges 5%") is False

    def test_us_sec_not_vn_regulatory(self):
        assert is_vn_regulatory("SEC sues Binance") is False

    def test_vn_keywords_list_not_empty(self):
        """Verify VN regulatory keywords list has sufficient entries."""
        assert len(VN_REGULATORY_KEYWORDS) >= 10


class TestQO17AutoCriticalSeverity:
    """QO.17: VN regulatory events → auto CRITICAL severity."""

    def test_thong_tu_auto_critical(self):
        event = _event("Thông tư mới cấm giao dịch crypto", panic_score=10)
        result = _determine_severity(event, ClassificationConfig())
        assert result == CRITICAL

    def test_nghi_dinh_auto_critical(self):
        event = _event("Nghị định về VASP sắp ban hành", panic_score=10)
        result = _determine_severity(event, ClassificationConfig())
        assert result == CRITICAL

    def test_sbv_auto_critical(self):
        event = _event("SBV bans crypto trading accounts", panic_score=10)
        result = _determine_severity(event, ClassificationConfig())
        assert result == CRITICAL

    def test_onus_auto_critical(self):
        event = _event("ONUS exchange under investigation", panic_score=10)
        result = _determine_severity(event, ClassificationConfig())
        assert result == CRITICAL

    def test_vn_regulatory_overrides_analysis_downgrade(self):
        """VN regulatory should NOT be downgraded by analysis keywords.
        WHY: VN regulation is checked BEFORE analysis-downgrade logic.
        """
        event = _event("Phân tích nghị định mới về crypto tại VN", panic_score=10)
        result = _determine_severity(event, ClassificationConfig())
        assert result == CRITICAL

    def test_classify_event_vn_regulatory_send_now(self):
        """VN regulatory event: CRITICAL + send_now even during night."""
        from cic_daily_report.breaking.severity_classifier import VN_TZ

        event = _event("Thông tư mới về tài sản mã hóa", panic_score=10)
        night = datetime(2026, 4, 12, 2, 0, tzinfo=VN_TZ)  # 2 AM VN = night
        result = classify_event(event, now=night)
        assert result.severity == CRITICAL
        assert result.delivery_action == "send_now"

    def test_non_vn_event_not_auto_critical(self):
        """Regular low-panic event should NOT be auto-critical."""
        event = _event("Market update today", panic_score=10)
        result = _determine_severity(event, ClassificationConfig())
        assert result != CRITICAL


# ============================================================================
# Integration: VN regulatory in evaluate_items
# ============================================================================


class TestQO17InEvaluateItems:
    """QO.17: VN regulatory keywords trigger event creation in _evaluate_items."""

    def test_vn_regulatory_creates_event_via_keyword_match(self):
        """VN regulatory title creates a BreakingEvent even with low panic score."""
        items = [_make_item("Nghị định mới cấm giao dịch crypto tại Việt Nam")]
        cfg = DetectionConfig(panic_threshold=99)  # High — only keyword triggers
        events = _evaluate_items(items, cfg)
        assert len(events) == 1
        # Should have matched VN regulatory keyword
        assert any(
            "nghị định" in kw.lower() or "cấm giao dịch" in kw.lower()
            for kw in events[0].matched_keywords
        )

    def test_sbv_creates_event(self):
        items = [_make_item("SBV issues stern warning about cryptocurrency")]
        cfg = DetectionConfig(panic_threshold=99)
        events = _evaluate_items(items, cfg)
        assert len(events) == 1
        assert any("sbv" in kw.lower() for kw in events[0].matched_keywords)


# ============================================================================
# Regression: existing behavior preserved
# ============================================================================


class TestRegressionExistingBehavior:
    """Ensure QO.12/13/15/16/17 changes don't break existing functionality."""

    def test_hack_still_always_triggers(self):
        result = _match_keywords("Exchange hack discovered", ["hack"])
        assert "hack" in result

    def test_similarity_dedup_still_works(self):
        """Similarity dedup unaffected by metric dedup addition."""
        from cic_daily_report.breaking.dedup_manager import _is_similar_to_recent

        entries = [DedupEntry(hash="h1", title="BTC drops 10% in flash crash", source="S")]
        assert _is_similar_to_recent("BTC drops 10% in major flash crash", entries) is True

    def test_url_dedup_still_works(self):
        """URL-based dedup unaffected."""
        mgr = DedupManager()
        e1 = _event("BTC hack A", "S1", url="https://same.com/article")
        e2 = _event("BTC hack B", "S2", url="https://same.com/article")
        result = mgr.check_and_filter([e1, e2])
        assert len(result.new_events) == 1

    def test_entity_dedup_existing_patterns_work(self):
        """Existing entity patterns (SEC, Binance) still extracted."""
        result = _extract_entities("SEC sues Binance")
        assert "sec" in result
        assert "binance" in result

    def test_cooldown_still_12h(self):
        """Hash-based cooldown still 12h."""
        from cic_daily_report.breaking.dedup_manager import COOLDOWN_HOURS

        assert COOLDOWN_HOURS == 12

    def test_max_events_per_run_still_3(self):
        """Per-run cap unchanged."""
        from cic_daily_report.breaking_pipeline import MAX_EVENTS_PER_RUN

        assert MAX_EVENTS_PER_RUN == 3
