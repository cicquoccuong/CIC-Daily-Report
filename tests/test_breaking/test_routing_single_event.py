"""Wave 0.8.7.7: Test sub-threshold routing helper.

Bug 03/05/2026: 2 important events (Buffett + XRP) lọt digest path → "TỔNG HỢP
TIN QUAN TRỌNG" với 1️⃣ heading duy nhất. Wave 0.8.7.1 chỉ guard len==1, miss
len==2 vì DIGEST_THRESHOLD=3.

Wave 0.8.7.7 fix: _route_below_threshold_to_individual() áp dụng cho TẤT CẢ
category (important_now + geo_events) — len < threshold → individual path.
"""

from cic_daily_report.breaking_pipeline import (
    DIGEST_THRESHOLD,
    _route_below_threshold_to_individual,
)


class TestRouteBelowThreshold:
    """Wave 0.8.7.7: helper routing logic."""

    def test_default_digest_threshold_is_3(self):
        """Sanity: DIGEST_THRESHOLD = 3 (1-2 events go individual)."""
        assert DIGEST_THRESHOLD == 3

    def test_empty_list_no_routing(self):
        """0 events → empty in, empty out."""
        remaining, routed = _route_below_threshold_to_individual([], 3)
        assert remaining == []
        assert routed == []

    def test_single_event_routed(self):
        """1 event < threshold(3) → routed to individual."""
        events = ["ev1"]
        remaining, routed = _route_below_threshold_to_individual(events, 3)
        assert remaining == []
        assert routed == ["ev1"]

    def test_two_events_routed(self):
        """2 events < threshold(3) → BOTH routed (regression: bug 03/05/2026
        had len==2 but Wave 0.8.7.1 only guarded len==1)."""
        events = ["buffett", "xrp"]
        remaining, routed = _route_below_threshold_to_individual(events, 3)
        assert remaining == []
        assert routed == ["buffett", "xrp"]

    def test_threshold_events_kept_for_digest(self):
        """3 events == threshold → KEEP as digest (regression check)."""
        events = ["e1", "e2", "e3"]
        remaining, routed = _route_below_threshold_to_individual(events, 3)
        assert remaining == ["e1", "e2", "e3"]
        assert routed == []

    def test_above_threshold_kept_for_digest(self):
        """4+ events > threshold → KEEP as digest."""
        events = ["e1", "e2", "e3", "e4", "e5"]
        remaining, routed = _route_below_threshold_to_individual(events, 3)
        assert remaining == events
        assert routed == []

    def test_custom_threshold_5(self):
        """Threshold=5: len 1-4 → individual, len>=5 → digest."""
        for n in range(1, 5):
            events = [f"e{i}" for i in range(n)]
            remaining, routed = _route_below_threshold_to_individual(events, 5)
            assert remaining == [], f"len={n} should route all"
            assert len(routed) == n

        events_5 = [f"e{i}" for i in range(5)]
        remaining, routed = _route_below_threshold_to_individual(events_5, 5)
        assert remaining == events_5
        assert routed == []

    def test_returned_routed_is_independent_copy(self):
        """Mutating returned list MUST NOT mutate original (defensive copy)."""
        original = ["a", "b"]
        remaining, routed = _route_below_threshold_to_individual(original, 3)
        routed.append("MUTATED")
        assert "MUTATED" not in original

    def test_zero_threshold_never_routes(self):
        """Edge case: threshold=0 → 0 < len < 0 never true → never route."""
        events = ["e1"]
        remaining, routed = _route_below_threshold_to_individual(events, 0)
        assert remaining == ["e1"]
        assert routed == []


class TestRoutingScenarios:
    """Wave 0.8.7.7: real-world bug scenarios from production."""

    def test_bug_03_05_buffett_2_important_events(self):
        """Bug 03/05/2026: Buffett (important) + XRP (important) → digest path
        rendered as "TỔNG HỢP" với 1️⃣ duy nhất. Sau fix: cả 2 → individual."""
        important_now = ["buffett_event", "xrp_event"]
        remaining, routed = _route_below_threshold_to_individual(important_now, DIGEST_THRESHOLD)
        assert remaining == [], "important_now phải clear (đã route hết)"
        assert routed == ["buffett_event", "xrp_event"], "cả 2 vào individual"

    def test_bug_02_05_trump_iran_1_geo_event(self):
        """Bug 02/05/2026 14:18 VN: 1 geo event (Trump-Iran) lọt digest. Wave
        0.8.7.1 đã fix qua inline single-geo block; Wave 0.8.7.7 thay bằng
        helper unified."""
        geo_events = ["trump_iran"]
        remaining, routed = _route_below_threshold_to_individual(geo_events, DIGEST_THRESHOLD)
        assert remaining == []
        assert routed == ["trump_iran"]

    def test_3_geo_events_form_digest(self):
        """Regression: 3 geo events vẫn form digest đúng (DIGEST_THRESHOLD=3)."""
        geo_events = ["geo1", "geo2", "geo3"]
        remaining, routed = _route_below_threshold_to_individual(geo_events, DIGEST_THRESHOLD)
        assert remaining == geo_events
        assert routed == []
