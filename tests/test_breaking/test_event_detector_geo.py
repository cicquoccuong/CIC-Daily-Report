"""Tests for P1.9 — Geopolitical keywords in event_detector.py."""

from cic_daily_report.breaking.event_detector import (
    ALWAYS_TRIGGER_KEYWORDS,
    CONTEXT_REQUIRED_KEYWORDS,
    DEFAULT_KEYWORD_TRIGGERS,
    GEOPOLITICAL_KEYWORDS,
    DetectionConfig,
    _evaluate_items,
    _match_keywords,
)


def _make_item(title="BTC news", panic_votes=None, source_title="CoinDesk"):
    """Helper to create a CryptoPanic-style item dict."""
    votes = panic_votes or {}
    return {
        "title": title,
        "source": {"title": source_title},
        "url": f"https://example.com/{title.replace(' ', '-')}",
        "votes": votes,
    }


class TestGeopoliticalKeywordList:
    """Verify GEOPOLITICAL_KEYWORDS structure and integration."""

    def test_geopolitical_keywords_in_defaults(self):
        """All geo keywords must appear in DEFAULT_KEYWORD_TRIGGERS."""
        for kw in GEOPOLITICAL_KEYWORDS:
            assert kw in DEFAULT_KEYWORD_TRIGGERS, f"Missing geo keyword: {kw}"

    def test_geopolitical_keywords_not_empty(self):
        # WHY >=12: Spec 2.7 requires 12 geo keywords (including "hormuz")
        assert len(GEOPOLITICAL_KEYWORDS) >= 12

    def test_no_overlap_with_always_trigger(self):
        """Geo keywords are a separate list from ALWAYS_TRIGGER_KEYWORDS."""
        overlap = set(GEOPOLITICAL_KEYWORDS) & set(ALWAYS_TRIGGER_KEYWORDS)
        assert overlap == set(), f"Unexpected overlap: {overlap}"

    def test_no_overlap_with_context_required(self):
        overlap = set(GEOPOLITICAL_KEYWORDS) & set(CONTEXT_REQUIRED_KEYWORDS)
        assert overlap == set(), f"Unexpected overlap: {overlap}"

    def test_default_order_always_before_context(self):
        """ALWAYS_TRIGGER + GEOPOLITICAL come before CONTEXT_REQUIRED."""
        # Find first context-required keyword index in defaults
        first_ctx = None
        for i, kw in enumerate(DEFAULT_KEYWORD_TRIGGERS):
            if kw in CONTEXT_REQUIRED_KEYWORDS:
                first_ctx = i
                break
        # All geo keywords should appear before first_ctx
        for kw in GEOPOLITICAL_KEYWORDS:
            idx = DEFAULT_KEYWORD_TRIGGERS.index(kw)
            assert idx < first_ctx, f"Geo keyword '{kw}' at {idx} >= first context at {first_ctx}"


class TestGeopoliticalAlwaysTrigger:
    """Geo keywords should fire WITHOUT crypto context (always-trigger behavior)."""

    def test_war_keyword_triggers(self):
        """'war' in title triggers without crypto context."""
        result = _match_keywords(
            "Russia-Ukraine war escalates with new offensive",
            DEFAULT_KEYWORD_TRIGGERS,
        )
        assert "war" in result

    def test_sanctions_keyword_triggers(self):
        result = _match_keywords(
            "US imposes new sanctions on Iranian oil exports",
            DEFAULT_KEYWORD_TRIGGERS,
        )
        assert "sanctions" in result

    def test_invasion_keyword_triggers(self):
        result = _match_keywords(
            "Military invasion reported in Eastern Europe",
            DEFAULT_KEYWORD_TRIGGERS,
        )
        assert "invasion" in result

    def test_missile_keyword_triggers(self):
        result = _match_keywords(
            "Missile attack on energy infrastructure",
            DEFAULT_KEYWORD_TRIGGERS,
        )
        assert "missile" in result

    def test_nuclear_keyword_triggers(self):
        result = _match_keywords(
            "Nuclear threat raises global tensions",
            DEFAULT_KEYWORD_TRIGGERS,
        )
        assert "nuclear" in result

    def test_ceasefire_keyword_triggers(self):
        result = _match_keywords(
            "Ceasefire agreement reached in conflict zone",
            DEFAULT_KEYWORD_TRIGGERS,
        )
        assert "ceasefire" in result

    def test_embargo_keyword_triggers(self):
        result = _match_keywords(
            "Trade embargo imposed on major exporter",
            DEFAULT_KEYWORD_TRIGGERS,
        )
        assert "embargo" in result

    def test_multi_word_oil_crisis(self):
        """Multi-word keyword 'oil crisis' matches correctly via substring."""
        result = _match_keywords(
            "Global oil crisis deepens as OPEC cuts supply",
            DEFAULT_KEYWORD_TRIGGERS,
        )
        assert "oil crisis" in result

    def test_multi_word_energy_crisis(self):
        result = _match_keywords(
            "Europe faces energy crisis ahead of winter",
            DEFAULT_KEYWORD_TRIGGERS,
        )
        assert "energy crisis" in result

    def test_hormuz_keyword_triggers(self):
        """'hormuz' triggers without crypto context (Strait of Hormuz — oil chokepoint)."""
        result = _match_keywords(
            "Iran threatens to close Strait of Hormuz amid tensions",
            DEFAULT_KEYWORD_TRIGGERS,
        )
        assert "hormuz" in result

    def test_hormuz_keyword_uppercase(self):
        """Hormuz matches case-insensitively."""
        result = _match_keywords(
            "HORMUZ STRAIT BLOCKADE FEARS RISE",
            DEFAULT_KEYWORD_TRIGGERS,
        )
        assert "hormuz" in result

    def test_hormuz_in_evaluate_items(self):
        """End-to-end: Hormuz in title -> BreakingEvent created."""
        items = [_make_item("Tensions rise at Strait of Hormuz")]
        cfg = DetectionConfig(panic_threshold=99)  # Only keyword triggers
        events = _evaluate_items(items, cfg)
        assert len(events) == 1
        assert "hormuz" in events[0].matched_keywords


class TestGeoCaseInsensitive:
    def test_war_uppercase(self):
        result = _match_keywords("WAR BREAKS OUT", DEFAULT_KEYWORD_TRIGGERS)
        assert "war" in result

    def test_sanctions_mixed_case(self):
        result = _match_keywords("New Sanctions Announced", DEFAULT_KEYWORD_TRIGGERS)
        assert "sanctions" in result

    def test_oil_crisis_uppercase(self):
        result = _match_keywords("OIL CRISIS WORSENS", DEFAULT_KEYWORD_TRIGGERS)
        assert "oil crisis" in result


class TestExistingKeywordsStillWork:
    """Regression: existing keywords unaffected by P1.9 changes."""

    def test_hack_still_always_triggers(self):
        result = _match_keywords("Major hack discovered in system", DEFAULT_KEYWORD_TRIGGERS)
        assert "hack" in result

    def test_exploit_still_always_triggers(self):
        result = _match_keywords("New exploit targets wallets", DEFAULT_KEYWORD_TRIGGERS)
        assert "exploit" in result

    def test_rug_pull_still_always_triggers(self):
        result = _match_keywords("Suspected rug pull on DeFi protocol", DEFAULT_KEYWORD_TRIGGERS)
        assert "rug pull" in result

    def test_context_required_still_needs_context(self):
        """'crash' without crypto context should NOT trigger."""
        result = _match_keywords("Plane crash in remote area", DEFAULT_KEYWORD_TRIGGERS)
        assert result == []

    def test_context_required_with_crypto_context(self):
        """'crash' WITH crypto context should still trigger."""
        result = _match_keywords("Bitcoin crash sends prices tumbling", DEFAULT_KEYWORD_TRIGGERS)
        assert "crash" in result


class TestGeoInEvaluateItems:
    """End-to-end: geo keyword in title -> BreakingEvent created."""

    def test_war_title_creates_event(self):
        items = [_make_item("War erupts in Middle East")]
        cfg = DetectionConfig(panic_threshold=99)  # High threshold — only keyword triggers
        events = _evaluate_items(items, cfg)
        assert len(events) == 1
        assert "war" in events[0].matched_keywords

    def test_sanctions_title_creates_event(self):
        items = [_make_item("Sanctions target Russian banks")]
        cfg = DetectionConfig(panic_threshold=99)
        events = _evaluate_items(items, cfg)
        assert len(events) == 1
        assert "sanctions" in events[0].matched_keywords

    def test_geo_keyword_no_false_positive(self):
        """Title without any keyword -> no event."""
        items = [_make_item("Normal economic growth reported")]
        cfg = DetectionConfig(panic_threshold=99)
        events = _evaluate_items(items, cfg)
        assert len(events) == 0
