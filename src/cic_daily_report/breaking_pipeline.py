"""Breaking news pipeline entry point — event detection and alerting.

Orchestrates: Detect (5.1) → Dedup (5.4) → Generate (5.2) → Classify (5.3) → Deliver
Fallback chain: CryptoPanic → RSS + LLM scoring → Market triggers (always-on).
Total time target: ≤20 minutes from pipeline start.
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from cic_daily_report.breaking.content_generator import (
    BreakingContent,
    generate_breaking_content,
    generate_digest_content,
)
from cic_daily_report.breaking.dedup_manager import DedupEntry, DedupManager, compute_hash
from cic_daily_report.breaking.event_detector import (
    BreakingEvent,
    detect_breaking_events,
    is_geo_event,
)
from cic_daily_report.breaking.severity_classifier import (
    SEVERITY_LEGEND,
    ClassifiedEvent,
    classify_batch,
    mark_legend_sent,
    should_send_legend,
)
from cic_daily_report.breaking.wave06_metrics import Wave06Metrics
from cic_daily_report.core.config import _wave_0_6_kill_switch_active
from cic_daily_report.core.error_handler import LLMError
from cic_daily_report.core.logger import get_logger

logger = get_logger("breaking_pipeline")

BREAKING_TIMEOUT_SECONDS = 20 * 60  # 20 minutes

# QO.31: Constants kept as DEFAULT FALLBACK — actual values read from CAU_HINH
# at runtime via _get_pipeline_limits(). DO NOT call config_loader at module level.
#
# Wave 0.5.2 (alpha.19) Fix 6 — TRUE spam cap (Devil finding):
# Before: MAX_EVENTS_PER_RUN=3 + MAX_DEFERRED_PER_RUN=5 = 8 actual messages/run.
# That was a "fake" cap because deferred reprocessing happened on top of the 3.
# Now: MAX_EVENTS_PER_RUN=5 covers TOTAL messages sent in a run (crypto + geo
# digest + deferred reprocess + overflow). Hard cap enforced before each
# telegram_bot send. MAX_DEFERRED_PER_RUN deprecated but kept for backwards
# compat — its value is now bounded by MAX_EVENTS_PER_RUN at runtime.
# B1: hard cap on TOTAL messages/run (was 3, Wave 0.5.2 raised to 5 + expanded scope)
MAX_EVENTS_PER_RUN = 5
MAX_DEFERRED_PER_RUN = 5  # A8: deprecated upper bound, runtime cap is MAX_EVENTS_PER_RUN
DIGEST_THRESHOLD = 3  # B5: when >=N send_now events, switch to digest mode (reduced from 5)
INTER_EVENT_DELAY = 30  # B2: seconds between events sent to TG

# QO.16: Daily event cap — after 12 events/day, remaining events deferred to daily digest.
# WHY at pipeline level: feedback.py caps the FEEDBACK file, but the pipeline must
# also stop SENDING events after the cap is reached.
MAX_EVENTS_PER_DAY = 12


def _get_pipeline_limits(config_loader: object | None = None) -> dict[str, int]:
    """QO.31: Read pipeline limits from CAU_HINH config at runtime.

    Returns dict of limit_name -> value, using defaults on failure.
    WHY function (not module-level): config_loader needs sheets_client
    which is not ready at import time.
    """
    defaults = {
        "MAX_EVENTS_PER_RUN": MAX_EVENTS_PER_RUN,
        "MAX_EVENTS_PER_DAY": MAX_EVENTS_PER_DAY,
        "DIGEST_THRESHOLD": DIGEST_THRESHOLD,
        "INTER_EVENT_DELAY": INTER_EVENT_DELAY,
    }
    if config_loader is None:
        return defaults

    try:
        result = {}
        for key, default in defaults.items():
            result[key] = config_loader.get_setting_int(key, default)
        return result
    except Exception as e:
        # WHY: Never break pipeline if config read fails — use defaults silently
        logger.warning(f"Config read failed for pipeline limits, using defaults: {e}")
        return defaults


# QO.14: Geo event daily cap — max 3 geo digest messages per day.
# WHY separate cap: geopolitical events (war, sanctions, Fed, inflation) are
# relevant but noisy. Grouping into digest + capping at 3/day reduces spam
# while still covering major macro events.
MAX_GEO_DIGESTS_PER_DAY = 3
# QO.14: Geo events with panic_score >= this threshold are CRITICAL and bypass
# the geo digest — sent individually like crypto events.
GEO_CRITICAL_PANIC_THRESHOLD = 90

# A6: severity sort order (lower = higher priority)
_SEVERITY_ORDER = {"critical": 0, "important": 1, "notable": 2, "": 3}


@dataclass
class BreakingRunLog:
    """Log entry for a breaking pipeline run."""

    pipeline_type: str = "breaking"
    started_at: str = ""
    finished_at: str = ""
    duration_seconds: float = 0
    events_detected: int = 0
    events_new: int = 0
    events_sent: int = 0
    events_deferred: int = 0
    errors: list[str] = field(default_factory=list)
    status: str = "pending"  # "success" / "partial" / "error" / "no_events"

    def to_row(self) -> list[str]:
        """Convert to sheet row for NHAT_KY_PIPELINE.

        Schema: ID, Thời gian bắt đầu, Thời gian kết thúc, Thời lượng (giây),
                Trạng thái, LLM sử dụng, Lỗi, Ghi chú
        """
        note = (
            f"breaking | detected={self.events_detected}"
            f" new={self.events_new}"
            f" sent={self.events_sent}"
            f" deferred={self.events_deferred}"
        )
        return [
            "",  # ID
            self.started_at,
            self.finished_at,
            str(self.duration_seconds),
            self.status,
            "",  # LLM sử dụng
            "; ".join(self.errors) if self.errors else "",
            note,
        ]


@dataclass
class BreakingPipelineResult:
    """Result of the breaking pipeline run."""

    run_log: BreakingRunLog
    sent_events: list[ClassifiedEvent] = field(default_factory=list)
    deferred_events: list[ClassifiedEvent] = field(default_factory=list)
    contents: list[BreakingContent] = field(default_factory=list)
    dedup_entries: list[DedupEntry] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.run_log.status in ("success", "no_events")


def main() -> None:
    """Run the breaking news pipeline."""
    is_production = os.getenv("GITHUB_ACTIONS") == "true"

    if not is_production:
        print("[DEV] Development mode — skipping real API calls")
        return

    asyncio.run(_run_breaking_pipeline())


async def _run_breaking_pipeline() -> BreakingPipelineResult:
    """Execute the full breaking news pipeline with timeout."""
    run_log = BreakingRunLog(
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    try:
        result = await asyncio.wait_for(
            _execute_pipeline(run_log),
            timeout=BREAKING_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.error("Breaking pipeline timed out after 20 minutes")
        run_log.errors.append("Pipeline timeout (20 min)")
        run_log.status = "error"
        result = BreakingPipelineResult(run_log=run_log)
    except Exception as e:
        logger.error(f"Breaking pipeline failed: {e}")
        run_log.errors.append(str(e))
        run_log.status = "error"
        result = BreakingPipelineResult(run_log=run_log)

    run_log.finished_at = datetime.now(timezone.utc).isoformat()
    run_log.duration_seconds = _calc_duration(run_log.started_at, run_log.finished_at)

    logger.info(
        f"Breaking pipeline finished: {run_log.status} "
        f"({run_log.events_sent} sent, {run_log.events_deferred} deferred, "
        f"{run_log.duration_seconds:.1f}s)"
    )

    # v0.30.0: Admin alert on pipeline failure
    if run_log.status == "error":
        from cic_daily_report.delivery.telegram_bot import send_admin_alert

        errors_text = "\n".join(f"- {e}" for e in run_log.errors[:5])
        await send_admin_alert(
            f"\u26a0\ufe0f Breaking pipeline THẤT BẠI\n"
            f"Thời gian: {run_log.duration_seconds:.0f}s\n"
            f"Lỗi:\n{errors_text}"
        )

    # A6: Write run log to NHAT_KY_PIPELINE
    try:
        await _write_breaking_run_log(run_log)
    except Exception as e:
        logger.warning(f"Run log write failed (non-critical): {e}")

    return result


async def _execute_pipeline(run_log: BreakingRunLog) -> BreakingPipelineResult:
    """Core pipeline: detect → dedup → classify → generate → deliver.

    v0.29.0 restructure:
    - A3: Single shared LLMAdapter for entire run
    - C1: Health check before batch processing
    - B3/A6: Priority-based event ordering (critical → important → notable)
    - B1/A8: Capped event processing to prevent spam
    - B5: Digest mode for high-volume runs
    - A4: LLM errors propagate (generation_failed, not raw fallback)
    - A5: Incremental dedup persist after each send
    - B2: 30s delay between events
    """
    result = BreakingPipelineResult(run_log=run_log)

    # Story 0.6.5 (alpha.23): per-run Wave 0.6 metrics + kill-switch warning.
    # WHY init early: passed to downstream gates so they can increment counters.
    wave06_metrics = Wave06Metrics()
    if _wave_0_6_kill_switch_active():
        logger.warning(
            "WAVE_0_6_KILL_SWITCH active — ALL Wave 0.6 flags forced OFF "
            "(RAG/judge/date-block/2-source). Story 0.6.5 rollback in effect."
        )

    # QO.31: Load config from CAU_HINH ONCE for entire pipeline run.
    # WHY here: config_loader needs SheetsClient which is expensive —
    # create once and pass to all downstream consumers.
    config_loader = None
    sheets = None  # Wave 0.8.2: ensure defined for downstream RAG wire even if
    # SheetsClient() construction fails (auth/network issue → fall back to None,
    # _get_historical_context will skip RAG silently).
    try:
        from cic_daily_report.storage.config_loader import ConfigLoader
        from cic_daily_report.storage.sheets_client import SheetsClient

        sheets = SheetsClient()
        config_loader = ConfigLoader(sheets)
    except Exception as e:
        logger.warning(f"QO.31: Config load failed, using defaults: {e}")

    # QO.31: Read pipeline limits from config (or use module-level defaults)
    limits = _get_pipeline_limits(config_loader)
    max_per_run = limits["MAX_EVENTS_PER_RUN"]
    max_per_day = limits["MAX_EVENTS_PER_DAY"]
    # WHY prefixed: extracted for future digest grouping logic
    _digest_threshold = limits["DIGEST_THRESHOLD"]
    inter_event_delay = limits["INTER_EVENT_DELAY"]

    # Load dedup state ONCE for the entire pipeline run
    dedup_mgr = await _load_dedup_from_sheets()

    # A3: Create single shared LLMAdapter for entire pipeline
    from cic_daily_report.adapters.llm_adapter import LLMAdapter

    llm = None
    try:
        # v0.31.0: Prefer Groq for breaking — shorter content, faster response.
        # Daily pipeline prefers Gemini, avoiding quota competition.
        llm = LLMAdapter(prefer="groq")
    except Exception as e:
        logger.warning(f"LLM init failed: {e}")

    # C1: Health check — verify at least one LLM provider responds
    if llm is not None:
        try:
            await llm.generate(prompt="ping", max_tokens=10, temperature=0)
            logger.info("LLM health check passed")
        except Exception:
            logger.warning("LLM health check failed — circuit breaker will engage")

    # Stage 0: Reprocess deferred events from previous night (FR28)
    # Wave 0.5.2 Fix 6: deferred bounded by remaining run budget (was MAX_DEFERRED_PER_RUN).
    # Wave 0.8.2: pass sheets so deferred-retry path also wires RAG
    # (otherwise overflow re-sends miss historical context).
    await _reprocess_deferred_events(
        run_log, result, dedup_mgr, llm, max_per_run=max_per_run, sheets_client=sheets
    )

    # Stage 1: Detect events — RSS first, CryptoPanic only if needed (v0.32.0)
    # WHY: CryptoPanic has tight daily quota. RSS is free and unlimited.
    # Try RSS first; only burn a CryptoPanic API call if RSS found < 3 events.
    events: list = []
    rss_events = await _rss_fallback_detection(run_log, llm)
    events.extend(rss_events)

    if len(events) < 3:
        # RSS insufficient — use CryptoPanic to supplement
        logger.info(f"RSS found {len(events)} events (< 3) — querying CryptoPanic for more")
        try:
            cp_events = await asyncio.wait_for(detect_breaking_events(), timeout=60)
            events.extend(cp_events)
        except asyncio.TimeoutError:
            logger.warning("CryptoPanic detection timed out")
        except Exception as e:
            logger.warning(f"CryptoPanic detection failed: {e}")
    else:
        logger.info(f"Skipping CryptoPanic — RSS found {len(events)} events (>= 3 sufficient)")

    # Stage 1c: Market triggers (always-on, additive)
    market_events = await _market_trigger_detection(run_log)
    events.extend(market_events)

    # QO.42: Stage 1d-watcher — detect cic_action changes from Sentinel registry.
    # WHY here (additive to events): action changes are internal CIC signals that
    # should be treated as breaking events for member notification.
    try:
        from cic_daily_report.breaking.cic_action_watcher import (
            detect_action_changes,
            load_previous_snapshot,
        )
        from cic_daily_report.storage.sentinel_reader import SentinelReader

        sentinel_reader = SentinelReader()
        sentinel_data = await asyncio.to_thread(sentinel_reader.read_all)
        if sentinel_data.registry:
            prev_snapshot = load_previous_snapshot(dedup_mgr.entries)
            action_events, _new_snapshot = detect_action_changes(
                sentinel_data.registry, prev_snapshot
            )
            if action_events:
                events.extend(action_events)
                logger.info(f"QO.42: {len(action_events)} cic_action changes detected")
    except Exception as e:
        logger.warning(f"QO.42: cic_action watcher failed (non-critical): {e}")

    run_log.events_detected = len(events)

    if not events:
        # v0.29.1 (BUG 2): Persist dedup before early return — deferred reprocess
        # at Stage 0 may have updated statuses that need saving.
        if run_log.events_sent > 0:
            await _persist_dedup_to_sheets(dedup_mgr)
        run_log.status = "no_events"
        return result

    # Stage 1d: Filter non-CIC coins (keep tracked coins + non-coin events)
    try:
        tracked_coins = await _load_tracked_coins()
        if tracked_coins:
            before = len(events)
            events = _filter_non_cic_coins(events, tracked_coins)
            if len(events) < before:
                logger.info(f"Coin filter: {before - len(events)} non-CIC events removed")
    except Exception as e:
        logger.debug(f"Coin filter skipped: {e}")

    # QO.18: Stage 1e — LLM Impact Scoring via SambaNova.
    # Score each event 1-10 for VN crypto investor relevance.
    # Runs BEFORE dedup so we don't waste dedup entries on skipped events.
    # WHY separate from main LLM: SambaNova has its own free quota (20 RPD),
    # doesn't compete with Gemini/Groq used for content generation.
    events = await _score_events_impact(events)

    # Stage 2: Dedup — using pre-loaded dedup_mgr from BREAKING_LOG (A5)
    dedup_result = dedup_mgr.check_and_filter(events)
    run_log.events_new = len(dedup_result.new_events)
    result.dedup_entries = dedup_result.entries_written

    if not dedup_result.new_events:
        # v0.29.1 (BUG 2): Persist dedup before early return.
        if run_log.events_sent > 0:
            await _persist_dedup_to_sheets(dedup_mgr)
        run_log.status = "no_events"
        return result

    # Stage 3: Classify
    classified = classify_batch(dedup_result.new_events)

    # A6/B3: Sort by severity — critical events processed first
    classified.sort(key=lambda c: _SEVERITY_ORDER.get(c.severity, 3))

    # Separate send_now vs deferred
    send_now = [c for c in classified if not c.is_deferred]
    deferred = [c for c in classified if c.is_deferred]

    # Record deferred events in dedup
    for classified_event in deferred:
        run_log.events_deferred += 1
        result.deferred_events.append(classified_event)
        h = compute_hash(classified_event.event.title, classified_event.event.source)
        dedup_mgr.update_entry_status(
            h, classified_event.delivery_action, severity=classified_event.severity
        )

    # Wave 0.6 Story 0.6.4 (alpha.22): 2-source verification gate.
    # Audit Round 2 found CoinDesk + CoinTelegraph publishing the same Canada
    # Bill C-25 event within minutes — both sent (duplicate). Conversely,
    # single-source critical claims have higher hallucination risk.
    # Flag default OFF — safe deploy. ON: critical single-source → defer,
    # important/notable single-source → ship + log warning, conflict → defer.
    from cic_daily_report.core.config import _wave_0_6_2source_required

    if _wave_0_6_2source_required() and send_now:
        from cic_daily_report.breaking.dedup_manager import _extract_entities
        from cic_daily_report.breaking.two_source_verifier import verify_two_sources

        send_now_after_gate: list = []
        # Wave 0.6.6 B7: track verified events by entity-key within the SAME run.
        # WHY: when 2 outlets report the same event in this very batch, each
        # verifies against the other (verdict=verified for both) → without
        # this guard we'd ship 2 alerts for 1 event. Use the entity set hash
        # as the dedup key (identical algorithm dedup_manager uses).
        verified_event_keys: set[frozenset[str]] = set()
        for c in send_now:
            verdict = verify_two_sources(c.event, dedup_mgr.entries)
            # Story 0.6.5: track verifier outcomes for monitoring rollout.
            if verdict.verdict == "verified":
                wave06_metrics.increment("two_source_verified")
            elif verdict.verdict == "conflict":
                wave06_metrics.increment("two_source_conflict")
            else:
                wave06_metrics.increment("two_source_single")
            if verdict.verdict == "verified":
                # Wave 0.6.6 B7: same-run duplicate guard.
                event_key = frozenset(_extract_entities(c.event.title))
                if event_key and event_key in verified_event_keys:
                    logger.info(
                        f"Story 0.6.6 B7: skipping duplicate verified event "
                        f"'{c.event.title[:60]}' (entity key already shipped this run)"
                    )
                    wave06_metrics.increment("two_source_duplicate_skipped")
                    continue
                if event_key:
                    verified_event_keys.add(event_key)
                send_now_after_gate.append(c)
            elif verdict.verdict == "conflict":
                # WHY defer (not skip): operator review needed; surface in
                # deferred_2source_conflict status so daily digest can flag.
                logger.error(
                    f"Story 0.6.4: Source conflict — defer '{c.event.title[:60]}' "
                    f"vs second source '{verdict.second_source}'"
                )
                run_log.events_deferred += 1
                result.deferred_events.append(c)
                h = compute_hash(c.event.title, c.event.source)
                dedup_mgr.update_entry_status(h, "deferred_2source_conflict", severity=c.severity)
            else:  # single_source
                if c.severity == "critical":
                    logger.warning(
                        f"Story 0.6.4: Critical event single-source — defer '{c.event.title[:60]}'"
                    )
                    run_log.events_deferred += 1
                    result.deferred_events.append(c)
                    h = compute_hash(c.event.title, c.event.source)
                    dedup_mgr.update_entry_status(h, "deferred_single_source", severity=c.severity)
                else:
                    # important/notable: ship + log only.
                    logger.info(
                        f"Story 0.6.4: Single-source non-critical event "
                        f"'{c.event.title[:60]}' — ship with warning log"
                    )
                    send_now_after_gate.append(c)
        send_now = send_now_after_gate

    # B1: Cap events per run to prevent spam (QO.31: uses config value)
    # Wave 0.5.2 Fix 6: cap on REMAINING budget (max_per_run - already sent in
    # deferred reprocessing). Old behavior allowed +MAX_DEFERRED_PER_RUN above
    # this cap → 8 actual messages. New: TOTAL <= max_per_run.
    remaining_run_budget = max(0, max_per_run - run_log.events_sent)
    if len(send_now) > remaining_run_budget:
        overflow = send_now[remaining_run_budget:]
        send_now = send_now[:remaining_run_budget]
        for classified_event in overflow:
            run_log.events_deferred += 1
            result.deferred_events.append(classified_event)
            h = compute_hash(classified_event.event.title, classified_event.event.source)
            dedup_mgr.update_entry_status(
                h, "deferred_overflow", severity=classified_event.severity
            )
        logger.info(
            f"B1+Fix6: Capped at remaining_budget={remaining_run_budget} "
            f"(MAX_EVENTS_PER_RUN={max_per_run}, already_sent={run_log.events_sent}), "
            f"deferred {len(overflow)} overflow events"
        )

    # QO.14: Separate geo events from crypto events.
    # Geo events go to digest (grouped), crypto events go individually.
    # Exception: CRITICAL geo events (panic >= 90) bypass → sent individually.
    geo_events: list[ClassifiedEvent] = []
    crypto_events: list[ClassifiedEvent] = []
    for c in send_now:
        if is_geo_event(c.event.title) and c.event.panic_score < GEO_CRITICAL_PANIC_THRESHOLD:
            geo_events.append(c)
        else:
            crypto_events.append(c)

    # QO.14: Cap geo digests at MAX_GEO_DIGESTS_PER_DAY
    geo_sent_today = _count_today_geo_digests(dedup_mgr)
    geo_remaining = max(0, MAX_GEO_DIGESTS_PER_DAY - geo_sent_today)
    if geo_events and geo_remaining == 0:
        logger.info(
            f"QO.14: Geo digest cap reached ({geo_sent_today}/{MAX_GEO_DIGESTS_PER_DAY}), "
            f"deferring {len(geo_events)} geo events"
        )
        for c in geo_events:
            run_log.events_deferred += 1
            result.deferred_events.append(c)
            h = compute_hash(c.event.title, c.event.source)
            dedup_mgr.update_entry_status(h, "deferred_geo_cap", severity=c.severity)
        geo_events = []

    # Replace send_now with crypto-only events (geo handled separately below)
    send_now = crypto_events

    # QO.16: Daily cap — defer remaining events after max_per_day reached (QO.31: config)
    daily_sent = _count_today_sent_events(dedup_mgr)
    remaining_quota = max(0, max_per_day - daily_sent)
    if remaining_quota == 0:
        logger.info(
            f"QO.16: Daily cap reached ({daily_sent}/{max_per_day}), "
            f"deferring all {len(send_now)} events to daily digest"
        )
        for classified_event in send_now:
            run_log.events_deferred += 1
            result.deferred_events.append(classified_event)
            h = compute_hash(classified_event.event.title, classified_event.event.source)
            dedup_mgr.update_entry_status(
                h, "deferred_to_daily", severity=classified_event.severity
            )
        send_now = []
    elif len(send_now) > remaining_quota:
        overflow = send_now[remaining_quota:]
        send_now = send_now[:remaining_quota]
        for classified_event in overflow:
            run_log.events_deferred += 1
            result.deferred_events.append(classified_event)
            h = compute_hash(classified_event.event.title, classified_event.event.source)
            dedup_mgr.update_entry_status(
                h, "deferred_to_daily", severity=classified_event.severity
            )
        logger.info(
            f"QO.16: Daily cap {daily_sent + len(send_now)}/{max_per_day}, "
            f"deferred {len(overflow)} events to daily digest"
        )

    if not send_now:
        dedup_mgr.cleanup_old_entries()
        await _persist_dedup_to_sheets(dedup_mgr, new_entries=dedup_result.entries_written)
        run_log.status = "partial" if run_log.events_deferred > 0 else "no_events"
        return result

    # Stage 3b: Build enrichment context for content generation
    market_snapshot = ""
    market_data = None  # WHY init: used by QO.19 consensus snapshot below
    # Wave 0.6 Story 0.6.4 (alpha.22): PriceSnapshot for breaking — same pattern as
    # daily_pipeline.py:440. Audit Round 2 found 3 breaking msg in 4 min reporting
    # BTC at $76k / $74k / $77k because each call to LLM produced a different price
    # in narrative. Freezing once per pipeline run + injecting explicit lock note
    # into prompt + post-process replace prevents this.
    price_snapshot = None
    try:
        from cic_daily_report.collectors.market_data import PriceSnapshot, collect_market_data

        market_data = await asyncio.wait_for(collect_market_data(), timeout=30)
        if market_data:
            price_snapshot = PriceSnapshot(market_data=market_data)
            logger.info(
                f"Story 0.6.4: PriceSnapshot frozen "
                f"({len(market_data)} data points, BTC=${price_snapshot.btc_price})"
            )
        # QO.09: Detect if any event in this run is macro-type (geopolitical/economic)
        # so _format_market_snapshot knows whether to include DXY.
        # WHY "market_data" only: market_trigger.py sets source="market_data" for all
        # generated events. "market_trigger" was a bug — no events use that source.
        _macro_sources = {"market_data"}
        # QO.09 fix: Expanded keywords to cover employment data, central banks,
        # economic indicators, and government fiscal events. Aligned with
        # cryptopanic_client._MACRO_KEYWORDS and event_detector.GEOPOLITICAL_KEYWORDS.
        _macro_keywords = {
            # Original
            "war",
            "sanctions",
            "fed",
            "interest rate",
            "inflation",
            "tariff",
            "oil",
            "gold",
            "dxy",
            "treasury",
            "gdp",
            "cpi",
            "fomc",
            # Employment data — high-impact macro indicators
            "employment",
            "jobs",
            "payroll",
            "nonfarm",
            "unemployment",
            "jobless",
            # Central banks — rate decisions move all risk assets
            "ecb",
            "boj",
            "pboc",
            "rba",
            "boe",
            "rate cut",
            "rate hike",
            # Economic indicators — PMI/ISM/PPI drive sentiment
            "ppi",
            "ism",
            "pmi",
            "retail sales",
            "housing",
            # Government fiscal events
            "debt ceiling",
            "shutdown",
        }
        has_macro = any(
            c.event.source in _macro_sources
            or any(kw in c.event.title.lower() for kw in _macro_keywords)
            for c in send_now
        )
        market_snapshot = _format_market_snapshot(market_data, has_macro_event=has_macro)
    except Exception as e:
        logger.debug(f"Market context for breaking skipped: {e}")

    # QO.19: Collect consensus snapshot for breaking enrichment.
    # WHY here: consensus data gives LLM context for writing more relevant
    # "TẠI SAO QUAN TRỌNG" sections. Non-critical — skip if unavailable.
    consensus_text = ""
    try:
        consensus_text = await _collect_consensus_snapshot(market_data)
    except Exception as e:
        logger.debug(f"Consensus snapshot for breaking skipped: {e}")

    # Wave 0.5.2 (alpha.19) Fix 3: recent_events_text built per-event inside
    # the loop below (anchored on each event's detected_at) so events from the
    # same batch never appear as "lịch sử" of a sibling. Digest path doesn't
    # consume recent_events.

    # v0.30.0 (Decision 1C): Critical → individual articles, Important → themed digest
    critical_now = [c for c in send_now if c.severity == "critical"]
    important_now = [c for c in send_now if c.severity != "critical"]

    # Stage 4a: Critical events — generate + deliver individually
    all_individual = critical_now[:]
    # Important events with only 1 item — also send individually (digest needs ≥2)
    if len(important_now) == 1:
        all_individual.extend(important_now)
        important_now = []

    for i, classified_event in enumerate(all_individual):
        # Wave 0.5.2 Fix 6: hard stop if TOTAL run cap reached mid-loop.
        if run_log.events_sent >= max_per_run:
            logger.info(
                f"Fix 6: Stopping individual sends mid-loop — TOTAL run cap reached "
                f"({run_log.events_sent}/{max_per_run})"
            )
            for remaining in all_individual[i:]:
                run_log.events_deferred += 1
                result.deferred_events.append(remaining)
                h = compute_hash(remaining.event.title, remaining.event.source)
                dedup_mgr.update_entry_status(h, "deferred_overflow", severity=remaining.severity)
            break
        content = None  # v0.29.1 (BUG 5): track generation vs delivery failure
        try:
            if llm is None or llm.circuit_open:
                raise RuntimeError("LLM unavailable — circuit open")

            # Wave 0.5.2 (alpha.19) Fix 3: rebuild recent_events filtered to
            # entries >=1h older than this event — prevents self-reference
            # (LLM citing tin từ cùng batch as "lịch sử").
            recent_events_text = _format_recent_events(
                dedup_mgr.entries,
                current_event_time=classified_event.event.detected_at,
                min_age_hours=1.0,
            )
            content = await asyncio.wait_for(
                generate_breaking_content(
                    classified_event.event,
                    llm,
                    severity=classified_event.severity,
                    market_context=market_snapshot,
                    recent_events=recent_events_text,
                    consensus_snapshot=consensus_text,
                    price_snapshot=price_snapshot,  # Story 0.6.4 (alpha.22)
                    # Wave 0.8.2: wire SheetsClient down so RAG (BREAKING_LOG)
                    # can build its index. Missing wire was the root cause of
                    # production warning "RAGIndex.build_from_sheets: no
                    # sheets_client provided" — RAG returned empty list →
                    # judge had no historical context → fact-check fail-open.
                    sheets_client=sheets,
                ),
                timeout=60,
            )

            # Wave 0.8.4 F5: bump judge_unavailable metric + WARNING log so
            # ops can spot Cerebras outages mid-run instead of finding out
            # the next morning when hallucinations slip through. Bug 5
            # (01/05): judge fail-open silently → 0 rejections all run.
            if getattr(content, "judge_unavailable", False):
                wave06_metrics.increment("judge_unavailable")
                logger.warning(
                    "Wave 0.8.4 F5: judge unavailable for "
                    f"'{classified_event.event.title[:60]}' (Cerebras "
                    f"fail-open). Total this run: "
                    f"{wave06_metrics.judge_unavailable}"
                )

            # Deliver immediately (not batched)
            await _deliver_single_breaking(content, classified_event, dedup_mgr=dedup_mgr)

            # v0.29.1 (BUG 4): Count AFTER successful delivery, not before.
            result.contents.append(content)
            result.sent_events.append(classified_event)
            run_log.events_sent += 1

            # A5: Incremental dedup persist after each successful send
            h = compute_hash(classified_event.event.title, classified_event.event.source)
            dedup_mgr.update_entry_status(
                h,
                "sent",
                delivered_at=datetime.now(timezone.utc).isoformat(),
                severity=classified_event.severity,
            )
            await _persist_dedup_to_sheets(dedup_mgr, new_entries=dedup_result.entries_written)

            # B2: Delay between events (skip after last) (QO.31: config)
            if i < len(all_individual) - 1 or important_now:
                logger.info(f"B2: Waiting {inter_event_delay}s before next event")
                await asyncio.sleep(inter_event_delay)

        except LLMError as e:
            # Wave 0.8.6.1 (alpha.34) Fix #2 — short-content gate is EXPECTED
            # behavior (Wave 0.8.7 Bug 9 universal F1). Skip event silently +
            # bump telemetry instead of raising to broad-except (which would
            # mark generation_failed → trigger deferred-retry that re-incurs
            # the same gate). WHY: short-content tin is unrecoverable without
            # source-side change; retry won't extend LLM output magically.
            if "breaking_content_word_gate" in (e.source or ""):
                logger.warning(
                    "breaking_skip_short_content event_title=%r source=%s reason=%s",
                    classified_event.event.title[:80],
                    e.source,
                    str(e),
                )
                wave06_metrics.increment("breaking_skipped_short_content")
                h = compute_hash(classified_event.event.title, classified_event.event.source)
                dedup_mgr.update_entry_status(
                    h, "skipped_short_content", severity=classified_event.severity
                )
                continue
            # Other LLMErrors fall through to general handling
            logger.error(f"Event failed (LLMError) for '{classified_event.event.title}': {e}")
            h = compute_hash(classified_event.event.title, classified_event.event.source)
            status = "delivery_failed" if content is not None else "generation_failed"
            dedup_mgr.update_entry_status(h, status, severity=classified_event.severity)
            run_log.errors.append(f"{'Deliver' if content else 'Generate'}: {e}")
        except Exception as e:
            logger.error(f"Event failed for '{classified_event.event.title}': {e}")
            # v0.29.1 (BUG 5): Distinguish generation vs delivery failure
            h = compute_hash(classified_event.event.title, classified_event.event.source)
            status = "delivery_failed" if content is not None else "generation_failed"
            dedup_mgr.update_entry_status(h, status, severity=classified_event.severity)
            run_log.errors.append(f"{'Deliver' if content else 'Generate'}: {e}")

    # Stage 4b: Important events (≥2) — batch into themed digest
    # Wave 0.5.2 Fix 6: digest counts as 1 message — only run if budget allows.
    if (
        important_now
        and llm is not None
        and not llm.circuit_open
        and run_log.events_sent < max_per_run
    ):
        await _generate_and_deliver_digest(
            important_now,
            llm,
            dedup_mgr,
            result,
            run_log,
            market_snapshot,
            dedup_result.entries_written,
        )
    elif important_now and run_log.events_sent >= max_per_run:
        logger.info(
            f"Fix 6: Skipping important digest — TOTAL run cap reached "
            f"({run_log.events_sent}/{max_per_run})"
        )
        for classified_event in important_now:
            run_log.events_deferred += 1
            result.deferred_events.append(classified_event)
            h = compute_hash(classified_event.event.title, classified_event.event.source)
            dedup_mgr.update_entry_status(
                h, "deferred_overflow", severity=classified_event.severity
            )
    elif important_now:
        # LLM unavailable — mark as generation_failed for retry
        for classified_event in important_now:
            h = compute_hash(classified_event.event.title, classified_event.event.source)
            dedup_mgr.update_entry_status(
                h, "generation_failed", severity=classified_event.severity
            )
            run_log.errors.append(f"LLM unavailable for digest: {classified_event.event.title}")

    # Wave 0.8.7.1: 1 geo event → ship dạng individual breaking thay vì digest.
    # WHY: digest format ("TỔNG HỢP TIN QUAN TRỌNG" + "1️⃣ ...") trông lố khi
    # chỉ có 1 mục — bug 02/05/2026 14:18 VN: 1 tin Trump-Iran lọt vào digest path.
    # Mirror guard giống important_now (line 658-660) nhưng đặt ở đây vì geo path
    # nằm SAU all_individual loop — không thể merge ngược lên.
    if (
        len(geo_events) == 1
        and llm is not None
        and not llm.circuit_open
        and run_log.events_sent < max_per_run
    ):
        single_geo = geo_events[0]
        content = None
        try:
            recent_events_text = _format_recent_events(
                dedup_mgr.entries,
                current_event_time=single_geo.event.detected_at,
                min_age_hours=1.0,
            )
            content = await asyncio.wait_for(
                generate_breaking_content(
                    single_geo.event,
                    llm,
                    severity=single_geo.severity,
                    market_context=market_snapshot,
                    recent_events=recent_events_text,
                    consensus_snapshot=consensus_text,
                    price_snapshot=price_snapshot,
                    sheets_client=sheets,
                ),
                timeout=60,
            )
            if getattr(content, "judge_unavailable", False):
                wave06_metrics.increment("judge_unavailable")
                logger.warning(
                    "Wave 0.8.4 F5: judge unavailable for "
                    f"'{single_geo.event.title[:60]}' (Cerebras "
                    f"fail-open). Total this run: "
                    f"{wave06_metrics.judge_unavailable}"
                )
            await _deliver_single_breaking(content, single_geo, dedup_mgr=dedup_mgr)
            result.contents.append(content)
            result.sent_events.append(single_geo)
            run_log.events_sent += 1
            h = compute_hash(single_geo.event.title, single_geo.event.source)
            # Status "sent" (giống individual flow) thay vì "sent_geo_digest" —
            # đây không còn là digest message nữa. Daily cap vẫn count qua _count_today_sent_events.
            dedup_mgr.update_entry_status(
                h,
                "sent",
                delivered_at=datetime.now(timezone.utc).isoformat(),
                severity=single_geo.severity,
            )
            await _persist_dedup_to_sheets(dedup_mgr, new_entries=dedup_result.entries_written)
        except Exception as e:
            logger.error(f"Single-geo event failed for '{single_geo.event.title}': {e}")
            h = compute_hash(single_geo.event.title, single_geo.event.source)
            status = "delivery_failed" if content is not None else "generation_failed"
            dedup_mgr.update_entry_status(h, status, severity=single_geo.severity)
            run_log.errors.append(f"{'Deliver' if content else 'Generate'} single-geo: {e}")
        geo_events = []  # đã xử lý — vô hiệu hóa digest path bên dưới

    # QO.14: Stage 4c — Geo events → digest (grouped message)
    # WHY separate stage: geo events are noisy individually but valuable as a digest.
    # Capping at MAX_GEO_DIGESTS_PER_DAY prevents geo spam while keeping coverage.
    # Wave 0.5.2 Fix 6: also enforce TOTAL run cap (1 digest = 1 message).
    if (
        geo_events
        and llm is not None
        and not llm.circuit_open
        and run_log.events_sent < max_per_run
    ):
        await _generate_and_deliver_digest(
            geo_events,
            llm,
            dedup_mgr,
            result,
            run_log,
            market_snapshot,
            dedup_result.entries_written,
            digest_status="sent_geo_digest",
        )
    elif geo_events and run_log.events_sent >= max_per_run:
        logger.info(
            f"Fix 6: Skipping geo digest — TOTAL run cap reached "
            f"({run_log.events_sent}/{max_per_run})"
        )
        for classified_event in geo_events:
            run_log.events_deferred += 1
            result.deferred_events.append(classified_event)
            h = compute_hash(classified_event.event.title, classified_event.event.source)
            dedup_mgr.update_entry_status(h, "deferred_geo_cap", severity=classified_event.severity)
    elif geo_events:
        for classified_event in geo_events:
            h = compute_hash(classified_event.event.title, classified_event.event.source)
            dedup_mgr.update_entry_status(
                h, "generation_failed", severity=classified_event.severity
            )
            run_log.errors.append(f"LLM unavailable for geo digest: {classified_event.event.title}")

    # Cleanup old entries
    dedup_mgr.cleanup_old_entries()

    # Final persist (covers overflow deferrals, cleanup, any remaining updates)
    await _persist_dedup_to_sheets(dedup_mgr, new_entries=dedup_result.entries_written)

    # P1.10: Save breaking feedback for daily pipeline context injection.
    # WHY here (after all sends): captures both individual + digest events in one save.
    # Non-critical — pipeline succeeds even if feedback save fails.
    if result.sent_events:
        try:
            from cic_daily_report.breaking.feedback import save_breaking_summary

            feedback_events = []
            for classified_event in result.sent_events:
                feedback_events.append(
                    {
                        "title": classified_event.event.title,
                        "source": classified_event.event.source,
                        "severity": classified_event.severity,
                        "timestamp": classified_event.event.detected_at.isoformat(),
                        "summary": classified_event.event.raw_data.get("summary", "")[:200],
                    }
                )
            save_breaking_summary(feedback_events, config_loader=config_loader)
        except Exception as e:
            logger.warning(f"Breaking feedback save failed (non-critical): {e}")

    # Story 0.6.5 (alpha.23): emit Wave 0.6 metrics summary line for grep-friendly
    # post-run monitoring. Only logs if any counter > 0 (avoids noise when flags OFF).
    if not wave06_metrics.is_empty():
        logger.info(wave06_metrics.to_log_line())

    run_log.status = "success" if run_log.events_sent > 0 else "partial"
    return result


async def _load_tracked_coins() -> set[str]:
    """Load CIC tracked coin symbols from DANH_SACH_COIN sheet."""
    try:
        from cic_daily_report.storage.sheets_client import SheetsClient

        sheets = SheetsClient()
        rows = await asyncio.to_thread(sheets.read_all, "DANH_SACH_COIN")
        coins = set()
        name_map: dict[str, str] = {}
        for row in rows:
            symbol = (
                str(row.get("Mã coin", "") or row.get("Symbol", "") or row.get("Coin", ""))
                .strip()
                .upper()
            )
            if symbol:
                coins.add(symbol)
            # v0.28.0: Also read project name mapping from existing column
            project_name = str(row.get("Tên đầy đủ", "") or row.get("Tên dự án", "")).strip()
            if symbol and project_name:
                name_map[project_name.lower()] = symbol

        # Load config-driven name mapping into shared coin_mapping
        if name_map:
            from cic_daily_report.core.coin_mapping import load_from_config

            added = load_from_config(name_map)
            logger.info(f"Coin mapping: {added} names from DANH_SACH_COIN")

        logger.info(f"Loaded {len(coins)} tracked coins from DANH_SACH_COIN")
        return coins
    except Exception as e:
        logger.warning(f"Failed to load tracked coins: {e}")
        return set()


async def _load_dedup_from_sheets() -> DedupManager:
    """Load existing dedup entries from BREAKING_LOG sheet (A5).

    v0.30.0: CRITICAL — if loading fails after retries, pipeline MUST NOT
    continue with empty dedup state (that would re-send all events).
    Retries 3 times with exponential backoff before raising fatal error.
    """
    from cic_daily_report.storage.sheets_client import SheetsClient

    max_retries = 3
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            sheets = SheetsClient()
            rows = await asyncio.to_thread(sheets.read_all, "BREAKING_LOG")
            entries = []
            for row in rows:
                entry = DedupEntry(
                    hash=str(row.get("Hash", "")),
                    title=str(row.get("Tiêu đề", "")),
                    source=str(row.get("Nguồn", "")),
                    severity=str(row.get("Mức độ", "")),
                    detected_at=str(row.get("Thời gian", "")),
                    status=str(row.get("Trạng thái gửi", "")),
                    url=str(row.get("URL", "")),
                    delivered_at=str(row.get("Thời gian gửi", "")),
                )
                if entry.hash:
                    entries.append(entry)
            logger.info(f"Loaded {len(entries)} dedup entries from BREAKING_LOG")
            return DedupManager(existing_entries=entries)
        except Exception as e:
            last_error = e
            logger.warning(f"BREAKING_LOG load attempt {attempt}/{max_retries} failed: {e}")
            if attempt < max_retries:
                await asyncio.sleep(2**attempt)  # 2s, 4s backoff

    # All retries exhausted — fail fatally to prevent duplicate sends
    raise RuntimeError(
        f"CRITICAL: Cannot load BREAKING_LOG after {max_retries} attempts "
        f"(last error: {last_error}). Pipeline halted to prevent duplicate sends."
    )


async def _persist_dedup_to_sheets(
    dedup_mgr: DedupManager, new_entries: list | None = None
) -> None:
    """Persist dedup entries back to BREAKING_LOG sheet (A5).

    v0.30.0: Uses atomic_rewrite (single API call) as primary strategy.
    If write fails, old data remains intact. Falls back to append-only
    for new entries if atomic rewrite fails.
    """
    try:
        from cic_daily_report.storage.sheets_client import SheetsClient

        sheets = SheetsClient()
        rows = dedup_mgr.all_rows()
        if not rows:
            return

        # Primary: atomic rewrite — writes header + data in ONE API call
        try:
            await asyncio.to_thread(sheets.atomic_rewrite, "BREAKING_LOG", rows)
            logger.info(f"Persisted {len(rows)} dedup entries to BREAKING_LOG (atomic rewrite)")
            return
        except Exception as e:
            logger.error(f"BREAKING_LOG atomic_rewrite failed: {e}")

        # Fallback: only append NEW entries to prevent duplicates
        if new_entries:
            new_rows = [e.to_row() for e in new_entries]
            await asyncio.to_thread(sheets.batch_append, "BREAKING_LOG", new_rows)
            logger.info(
                f"Appended {len(new_rows)} new entries to BREAKING_LOG (fallback, "
                f"skipped {len(rows) - len(new_rows)} existing)"
            )
        else:
            logger.error(
                "BREAKING_LOG: atomic_rewrite failed and no new entries to append. "
                "Dedup state may be stale — next run should recover."
            )
    except Exception as e:
        logger.error(f"Failed to persist BREAKING_LOG: {e}")


async def _write_breaking_run_log(run_log: BreakingRunLog) -> None:
    """Write breaking pipeline run log to NHAT_KY_PIPELINE (A6)."""
    try:
        from cic_daily_report.storage.sheets_client import SheetsClient

        sheets = SheetsClient()
        await asyncio.to_thread(sheets.batch_append, "NHAT_KY_PIPELINE", [run_log.to_row()])
        logger.info("Breaking run log written to NHAT_KY_PIPELINE")
    except Exception as e:
        logger.warning(f"Breaking run log write failed: {e}")


async def _rss_fallback_detection(run_log: BreakingRunLog, llm=None) -> list:
    """Fallback: collect RSS feeds and score via LLM for breaking events.

    A3: Uses shared LLM instance when available, creates fallback only if needed.
    """
    try:
        from cic_daily_report.breaking.llm_scorer import score_rss_articles
        from cic_daily_report.collectors.rss_collector import collect_rss

        rss_articles = await asyncio.wait_for(collect_rss(), timeout=60)

        # A3: Use shared LLM, create fallback only if needed
        rss_llm = llm
        if rss_llm is None:
            from cic_daily_report.adapters.llm_adapter import LLMAdapter

            rss_llm = LLMAdapter(prefer="groq")

        events = await asyncio.wait_for(score_rss_articles(rss_articles, rss_llm), timeout=60)
        logger.info(f"RSS fallback: {len(events)} breaking events from RSS+LLM")
        return events
    except Exception as e:
        logger.warning(f"RSS fallback also failed: {e}")
        run_log.errors.append(f"RSS fallback: {e}")
        return []


async def _collect_consensus_snapshot(market_data: list | None = None) -> str:
    """QO.19: Build consensus snapshot text for breaking prompt enrichment.

    Collects BTC/ETH consensus from consensus_engine if available.
    Returns formatted text or empty string if consensus unavailable.

    WHY not fail: consensus is enrichment, not required. Breaking news
    should still be generated even without consensus data.
    """
    try:
        from cic_daily_report.generators.consensus_engine import (
            MarketConsensus,
            build_consensus,
        )

        # Build consensus from market data + other available sources
        # WHY async: build_consensus is async (fetches prediction markets etc.)
        consensus_results: list[MarketConsensus] = await asyncio.wait_for(
            build_consensus(market_data=market_data),
            timeout=10,
        )

        if not consensus_results:
            return ""

        lines = []
        for mc in consensus_results:
            if mc.asset in ("BTC", "ETH"):
                lines.append(
                    f"{mc.asset}: {mc.label} (score {mc.score:+.2f}, "
                    f"{mc.source_count} nguồn, bullish {mc.bullish_pct:.0f}%)"
                )
        return " | ".join(lines) if lines else ""
    except Exception as e:
        logger.debug(f"Consensus snapshot collection failed: {e}")
        return ""


async def _score_events_impact(events: list[BreakingEvent]) -> list[BreakingEvent]:
    """QO.18: Score events via SambaNova and filter by impact.

    Score < 4 → removed (not important enough).
    Score 4-6 → kept (will be routed to digest by pipeline).
    Score >= 7 → kept (will be sent individually).

    Graceful: if SambaNova unavailable, all events pass through unchanged.
    """
    if not events:
        return events

    try:
        from cic_daily_report.breaking.llm_scorer import classify_by_impact, score_event_impact

        filtered: list[BreakingEvent] = []
        for event in events:
            try:
                score = await score_event_impact(event)
                action = classify_by_impact(score)
                if action == "skip":
                    logger.info(
                        f"QO.18: Skipping low-impact event (score={score}): '{event.title[:50]}'"
                    )
                    continue
                # Store impact score in raw_data for downstream use
                # WHY raw_data: BreakingEvent doesn't have an impact_score field,
                # and adding one would require changing the dataclass + all tests.
                if event.raw_data is None:
                    event.raw_data = {}
                event.raw_data["impact_score"] = score
                event.raw_data["impact_action"] = action
                filtered.append(event)
            except Exception as e:
                logger.debug(f"Impact scoring failed for '{event.title[:50]}': {e}")
                filtered.append(event)  # WHY: failure = pass through

        skipped = len(events) - len(filtered)
        if skipped > 0:
            logger.info(f"QO.18: Removed {skipped}/{len(events)} low-impact events")
        return filtered
    except ImportError:
        logger.debug("llm_scorer not available — skipping impact scoring")
        return events


async def _market_trigger_detection(run_log: BreakingRunLog) -> list:
    """Always-on: check market data for extreme conditions."""
    try:
        from cic_daily_report.breaking.market_trigger import detect_market_triggers
        from cic_daily_report.collectors.market_data import collect_market_data

        market_data = await asyncio.wait_for(collect_market_data(), timeout=60)
        events = detect_market_triggers(market_data)
        if events:
            logger.info(f"Market triggers: {len(events)} events detected")
        return events
    except Exception as e:
        logger.warning(f"Market trigger check failed (non-critical): {e}")
        run_log.errors.append(f"Market trigger: {e}")
        return []


async def _reprocess_deferred_events(
    run_log: BreakingRunLog,
    result: BreakingPipelineResult,
    dedup_mgr: DedupManager,
    llm=None,
    max_per_run: int = MAX_EVENTS_PER_RUN,
    sheets_client: object | None = None,
) -> None:
    """FR28: Reprocess deferred events when we're past the night window.

    v0.29.0 changes:
    - A3: Uses shared LLM instance (no separate init)
    - A6: Sorts by severity (critical first)
    - A8: Limits to MAX_DEFERRED_PER_RUN events
    - B2: 30s delay between events
    Also retries generation_failed + delivery_failed + deferred_overflow events (C3, max 1 retry).

    Wave 0.5.2 (alpha.19) Fix 6 — TOTAL run cap:
    Deferred reprocessing now bounded by ``max_per_run`` minus messages already
    sent in this run (always 0 for deferred since this is the first send stage).
    Old behavior ran up to MAX_DEFERRED_PER_RUN(5) on top of MAX_EVENTS_PER_RUN(3) =
    8 actual messages/run. New: deferred + crypto + digest + geo digest <=
    max_per_run total.
    """
    from cic_daily_report.breaking.severity_classifier import _is_night_mode

    now = datetime.now(timezone.utc)
    if _is_night_mode(now):
        return  # Still night — don't reprocess yet

    # Collect deferred_to_morning + generation_failed (C3) + delivery_failed + overflow (B1)
    morning_events = dedup_mgr.get_deferred_events("deferred_to_morning")
    retry_events = dedup_mgr.get_deferred_events("generation_failed")
    delivery_retry_events = dedup_mgr.get_deferred_events("delivery_failed")  # v0.29.1 (BUG 5)
    overflow_events = dedup_mgr.get_deferred_events("deferred_overflow")
    all_events = morning_events + retry_events + delivery_retry_events + overflow_events

    if not all_events:
        return

    # A6: Sort by severity (critical first)
    all_events.sort(key=lambda e: _SEVERITY_ORDER.get(e.severity or "", 3))

    # Wave 0.5.2 Fix 6: cap deferred to remaining budget of TOTAL run (not separate
    # MAX_DEFERRED). Reserve room for fresh events expected after this stage.
    # Heuristic: leave 50% of budget for fresh events; deferred gets 50% (rounded up).
    # WHY: deferred is opportunistic, fresh news of the day is the priority.
    deferred_budget = max(1, (max_per_run + 1) // 2)
    if len(all_events) > deferred_budget:
        logger.info(
            f"Fix 6: Capping deferred from {len(all_events)} to {deferred_budget} "
            f"(50%% of MAX_EVENTS_PER_RUN={max_per_run})"
        )
        all_events = all_events[:deferred_budget]

    logger.info(
        f"FR28: Reprocessing {len(morning_events)} deferred + "
        f"{len(retry_events)} gen_failed + {len(delivery_retry_events)} del_failed + "
        f"{len(overflow_events)} overflow events"
    )

    from cic_daily_report.delivery.telegram_bot import TelegramBot, split_message

    bot = TelegramBot()
    severity_map = {
        "critical": "\U0001f534",
        "important": "\U0001f7e0",
        "notable": "\U0001f7e1",
    }
    sent_count = 0

    for i, entry in enumerate(all_events):
        try:
            # Reconstruct BreakingEvent from DedupEntry metadata
            event = BreakingEvent(
                title=entry.title,
                source=entry.source,
                url=entry.url,
                panic_score=0,
            )

            emoji = severity_map.get(entry.severity, "\U0001f7e1")

            # A3: Use shared LLM instance
            if llm is not None and not llm.circuit_open:
                content = await asyncio.wait_for(
                    generate_breaking_content(
                        event,
                        llm,
                        severity=entry.severity or "important",
                        # Wave 0.8.2: deferred reprocess also wires RAG so
                        # judge sees historical context.
                        sheets_client=sheets_client,
                    ),
                    timeout=60,
                )
                message = f"{emoji} BREAKING NEWS\n\n{content.formatted}"
            else:
                # Fallback: raw data with hyperlink if LLM unavailable
                from cic_daily_report.breaking.content_generator import _raw_data_fallback

                fallback = _raw_data_fallback(event)
                message = f"{emoji} BREAKING NEWS\n\n{fallback.formatted}"

            # QO.11 fix: Deferred reprocessing also needs legend check.
            # WHY: Users seeing deferred events may not have seen the legend
            # from the original run (they were deferred precisely because
            # delivery didn't happen earlier).
            if should_send_legend(dedup_mgr=dedup_mgr):
                message += SEVERITY_LEGEND
                mark_legend_sent(dedup_mgr)

            # Split for TG safety
            parts = split_message("BREAKING", message)
            for part in parts:
                await bot.send_message(part.formatted)
                await asyncio.sleep(1.0)

            # Update status per event
            dedup_mgr.update_entry_status(entry.hash, "sent", delivered_at=now.isoformat())
            sent_count += 1

            # B2: Delay between events (skip after last)
            if i < len(all_events) - 1:
                await asyncio.sleep(INTER_EVENT_DELAY)

        except LLMError as e:
            # Wave 0.8.6.1 (alpha.34) Fix #2 — short-content gate also fires
            # on deferred reprocess path. Same rationale as primary path: gate
            # is unrecoverable, mark a distinct status to avoid re-retrying.
            if "breaking_content_word_gate" in (e.source or ""):
                logger.warning(
                    "breaking_skip_short_content_deferred event_title=%r reason=%s",
                    entry.title[:80],
                    str(e),
                )
                dedup_mgr.update_entry_status(entry.hash, "skipped_short_content")
                continue
            logger.warning(f"Deferred reprocess failed (LLMError) for '{entry.title[:50]}': {e}")
            if entry.status in ("generation_failed", "delivery_failed"):
                dedup_mgr.update_entry_status(entry.hash, "permanently_failed")
            else:
                dedup_mgr.update_entry_status(entry.hash, "generation_failed")
        except Exception as e:
            logger.warning(f"Deferred reprocess failed for '{entry.title[:50]}': {e}")
            if entry.status in ("generation_failed", "delivery_failed"):
                # C3: second failure → permanently_failed
                dedup_mgr.update_entry_status(entry.hash, "permanently_failed")
            else:
                dedup_mgr.update_entry_status(entry.hash, "generation_failed")

    run_log.events_sent += sent_count
    if sent_count > 0:
        logger.info(f"FR28: Delivered {sent_count}/{len(all_events)} deferred events")

    # v0.29.1 (BUG 1): Persist dedup status after deferred reprocessing.
    # Without this, status changes (sent/failed) are lost if pipeline exits
    # before the final persist — causing deferred events to be re-sent next run.
    if all_events:
        await _persist_dedup_to_sheets(dedup_mgr)


# Match only fully-uppercase words 2-6 chars in ORIGINAL title (not uppercased)
# Real coin tickers are written in uppercase in news titles (BTC, ETH, PIPPIN)
_COIN_PATTERN = re.compile(r"\b([A-Z]{2,6})\b")


def _extract_coins_from_title(title: str, known_coins: set[str]) -> set[str]:
    """Extract known coin symbols from title.

    v0.28.0: Now also recognizes project names (Ripple → XRP, Cardano → ADA)
    via shared coin_mapping module, not just uppercase tickers.
    """
    from cic_daily_report.core.coin_mapping import extract_coins_from_text

    return extract_coins_from_text(title, known_coins)


_FALSE_POSITIVE_SYMBOLS = {
    "SEC",
    "ETF",
    "CEO",
    "CFO",
    "CTO",
    "IPO",
    "FBI",
    "DOJ",
    "NFT",
    "API",
    "THE",
    "FOR",
    "AND",
    "NOT",
    "HAS",
    "NEW",
    "ALL",
    "USD",
    "EUR",
    "GBP",
    "JPY",
    "VND",
    "VN",
    "US",
    "UK",
    "EU",
    "AI",
}


def _filter_non_cic_coins(events: list, tracked_coins: set[str]) -> list:
    """Filter out events about coins not tracked by CIC.

    v0.26.0: Enhanced with parenthetical coin detection (e.g., "River (RIVER)")
    and macro-event keyword whitelist. Small unknown coins are now consistently
    filtered even when their symbols aren't uppercase in the title.

    Keeps: events about tracked coins + non-coin-specific events (regulatory, macro).
    Filters: events mentioning coin-like symbols not in tracked_coins.
    """
    if not tracked_coins:
        return events  # No whitelist available — keep all

    # v0.26.0: Keywords indicating macro/regulatory events (always keep)
    macro_keywords = {
        "fed",
        "sec",
        "regulation",
        "ban",
        "law",
        "legal",
        "court",
        "congress",
        "senate",
        "etf",
        "policy",
        "inflation",
        "rate",
        "treasury",
        "sanctions",
        "compliance",
        "framework",
        "bill",
    }

    filtered = []
    for event in events:
        title = event.title
        tracked_in_title = _extract_coins_from_title(title, tracked_coins)
        # Check for any coin-like symbols in ORIGINAL case (not uppercased)
        all_candidates = set(_COIN_PATTERN.findall(title)) - _FALSE_POSITIVE_SYMBOLS

        # v0.26.0: Also detect "Name (SYMBOL)" pattern for mixed-case titles
        # e.g., "River (RIVER) Soars 50%" — RIVER is detected by regex,
        # but also detect patterns like "Solana (SOL)" where name is mixed-case
        paren_coins = set(re.findall(r"\(([A-Z]{2,10})\)", title)) - _FALSE_POSITIVE_SYMBOLS
        all_candidates = all_candidates | paren_coins

        untracked_coins = all_candidates - tracked_coins

        if tracked_in_title:
            # Has tracked coins → keep
            filtered.append(event)
        elif untracked_coins:
            # Has coin-like symbols but NONE tracked → check if macro event
            title_lower = title.lower()
            is_macro = any(kw in title_lower for kw in macro_keywords)
            if is_macro:
                filtered.append(event)
                logger.info(f"Kept macro event with untracked coins: {title}")
            else:
                logger.info(f"Filtered non-CIC coin event: {title} (untracked: {untracked_coins})")
        else:
            # No coin symbols at all → macro/regulatory → keep
            filtered.append(event)
    return filtered


def _format_market_snapshot(market_data: list | None, has_macro_event: bool = False) -> str:
    """Format brief market context for breaking news prompt.

    QO.09 (VD-31): DXY is only injected when relevant — either the current
    run contains a macro-type event, or DXY itself moved significantly
    (abs(change_24h) >= 0.5%). This prevents DXY from appearing in every
    breaking message regardless of context.
    """
    if not market_data:
        return ""
    lines = []
    for dp in market_data:
        if dp.symbol in ("BTC", "ETH"):
            lines.append(f"{dp.symbol}: ${dp.price:,.0f} ({dp.change_24h:+.1f}%)")
    for dp in market_data:
        if dp.symbol == "Fear&Greed":  # WHY: match symbol created in market_data.py:509 (VD-07 fix)
            lines.append(f"Fear & Greed: {int(dp.price)}")
        elif dp.symbol == "DXY":
            # QO.09: Only include DXY when macro event present or DXY moved >= 0.5%
            if has_macro_event or abs(dp.change_24h) >= 0.5:
                lines.append(f"DXY: {dp.price:.1f}")
    return "Bối cảnh thị trường hiện tại: " + " | ".join(lines) if lines else ""


def _format_recent_events(
    dedup_entries: list[DedupEntry],
    max_events: int = 5,
    current_event_time: datetime | None = None,
    min_age_hours: float = 1.0,
) -> str:
    """Format recent breaking events for context injection.

    Wave 0.5.2 (alpha.19) Fix 3 (Devil CRITICAL — self-reference bug):
    When ``current_event_time`` is provided, filter entries to only include
    those detected at least ``min_age_hours`` (default 1h) BEFORE the current
    event. This prevents LLM from referencing a tin VỪA TẠO trong cùng pipeline
    run (e.g., Scallop tin 15:01 referencing ZetaChain tin 15:00 as "lịch sử").

    The filter splits the context window by timestamp, not batch position —
    so two unrelated events from the same run don't cross-pollute.
    """
    if current_event_time is not None:
        from datetime import timedelta

        cutoff = current_event_time - timedelta(hours=min_age_hours)
        filtered: list[DedupEntry] = []
        for entry in dedup_entries:
            if not entry.detected_at:
                continue
            try:
                entry_time = datetime.fromisoformat(entry.detected_at)
            except (ValueError, TypeError):
                continue
            if entry_time <= cutoff:
                filtered.append(entry)
        dedup_entries = filtered
    recent = sorted(dedup_entries, key=lambda e: e.detected_at, reverse=True)[:max_events]
    if not recent:
        return ""
    lines = ["Tin Breaking gần đây (để liên kết nếu liên quan):"]
    for entry in recent:
        lines.append(f"- {entry.title} ({entry.source}, {entry.severity})")
    return "\n".join(lines)


async def _deliver_single_breaking(
    content: BreakingContent,
    classified_event: ClassifiedEvent,
    dedup_mgr: DedupManager | None = None,
) -> None:
    """Deliver a single breaking news content via Telegram.

    v0.29.0: Extracted from batch delivery for incremental send + A5 persist.
    FR25: If image_url available, send photo first, then full text.
    """
    from cic_daily_report.delivery.telegram_bot import TelegramBot, split_message

    severity_map = {"critical": "\U0001f534", "important": "\U0001f7e0", "notable": "\U0001f7e1"}
    bot = TelegramBot()
    emoji = severity_map.get(classified_event.severity, "\U0001f7e1")

    # FR25: Send illustration image if available
    if content.image_url:
        try:
            caption = f"{emoji} BREAKING: {content.event.title[:200]}"
            await bot.send_photo(content.image_url, caption=caption)
            await asyncio.sleep(1.0)
        except Exception as img_err:
            logger.warning(f"FR25 image failed (text-only fallback): {img_err}")

    message = f"{emoji} BREAKING NEWS\n\n{content.formatted}"
    # QO.11 (VD-37): Append severity legend to the first breaking message of the day.
    # WHY dedup_mgr: Persistent tracking across process restarts (GitHub Actions
    # runs pipeline ~4x/day as separate processes, module state resets each time).
    if should_send_legend(dedup_mgr=dedup_mgr):
        message += SEVERITY_LEGEND
        if dedup_mgr is not None:
            mark_legend_sent(dedup_mgr)
    parts = split_message("BREAKING", message)
    for part in parts:
        await bot.send_message(part.formatted)
        await asyncio.sleep(0.5)

    logger.info(f"Breaking delivered: {content.event.title[:50]}...")


async def _generate_and_deliver_digest(
    send_now: list[ClassifiedEvent],
    llm,
    dedup_mgr: DedupManager,
    result: BreakingPipelineResult,
    run_log: BreakingRunLog,
    market_snapshot: str,
    new_entries: list,
    digest_status: str = "sent_digest",
) -> None:
    """B5/QO.14: Generate and deliver a single digest for multiple events.

    When >=DIGEST_THRESHOLD events need sending, combine into one summary
    to avoid spamming the Telegram channel.

    Args:
        digest_status: Dedup status to record. Default "sent_digest" for crypto,
            "sent_geo_digest" for geo events (QO.14).
    """
    from cic_daily_report.delivery.telegram_bot import TelegramBot, split_message

    logger.info(f"Digest mode — {len(send_now)} events in themed summary")

    events_for_digest = [c.event for c in send_now]
    digest_content = None  # v0.29.1 (BUG 5): track generation vs delivery failure
    try:
        digest_content = await asyncio.wait_for(
            generate_digest_content(events_for_digest, llm, market_context=market_snapshot),
            timeout=90,
        )

        # v0.30.0: Use severity-appropriate emoji for digest header
        has_critical = any(c.severity == "critical" for c in send_now)
        digest_emoji = "\U0001f534" if has_critical else "\U0001f7e0"
        digest_label = "BREAKING NEWS DIGEST" if has_critical else "TỔNG HỢP TIN QUAN TRỌNG"
        bot = TelegramBot()
        message = f"{digest_emoji} {digest_label}\n\n{digest_content.formatted}"
        # QO.11 (VD-37): Append severity legend to the first breaking message of the day.
        # WHY dedup_mgr: Persistent tracking across process restarts.
        if should_send_legend(dedup_mgr=dedup_mgr):
            message += SEVERITY_LEGEND
            mark_legend_sent(dedup_mgr)
        parts = split_message("BREAKING", message)
        for part in parts:
            await bot.send_message(part.formatted)
            await asyncio.sleep(0.5)

        # v0.29.1 (BUG 6): Count AFTER successful delivery, not before.
        result.contents.append(digest_content)
        run_log.events_sent += len(send_now)

        # Mark all events as sent (QO.14: uses digest_status param for geo vs crypto)
        for classified_event in send_now:
            result.sent_events.append(classified_event)
            h = compute_hash(classified_event.event.title, classified_event.event.source)
            dedup_mgr.update_entry_status(
                h,
                digest_status,
                delivered_at=datetime.now(timezone.utc).isoformat(),
                severity=classified_event.severity,
            )

        # A5: Persist after digest delivery
        await _persist_dedup_to_sheets(dedup_mgr, new_entries=new_entries)
        logger.info(f"B5: Digest delivered for {len(send_now)} events")

    except Exception as e:
        logger.error(f"Digest failed: {e}")
        run_log.errors.append(f"Digest: {e}")
        # v0.29.1 (BUG 5): Distinguish generation vs delivery failure
        status = "delivery_failed" if digest_content is not None else "generation_failed"
        for classified_event in send_now:
            h = compute_hash(classified_event.event.title, classified_event.event.source)
            dedup_mgr.update_entry_status(h, status, severity=classified_event.severity)


def _count_today_sent_events(dedup_mgr: DedupManager) -> int:
    """QO.16: Count events sent/sent_digest/sent_geo_digest today (UTC calendar day).

    Used to enforce MAX_EVENTS_PER_DAY cap. Counts all delivery statuses
    (sent, sent_digest, sent_geo_digest) from today's date.
    """
    # WHY include sent_geo_digest: geo digests also consume the daily event cap
    _sent_statuses = {"sent", "sent_digest", "sent_geo_digest"}
    today = datetime.now(timezone.utc).date()
    count = 0
    for entry in dedup_mgr.entries:
        if entry.status not in _sent_statuses:
            continue
        if not entry.detected_at:
            continue
        try:
            detected = datetime.fromisoformat(entry.detected_at)
            if detected.tzinfo is None:
                detected = detected.replace(tzinfo=timezone.utc)
            if detected.date() == today:
                count += 1
        except (ValueError, TypeError):
            continue
    return count


def _count_today_geo_digests(dedup_mgr: DedupManager) -> int:
    """QO.14: Count geo digest messages sent today (UTC calendar day).

    Each geo event in a digest counts as 1 toward the geo cap.
    Used to enforce MAX_GEO_DIGESTS_PER_DAY.
    """
    today = datetime.now(timezone.utc).date()
    count = 0
    for entry in dedup_mgr.entries:
        if entry.status != "sent_geo_digest":
            continue
        if not entry.detected_at:
            continue
        try:
            detected = datetime.fromisoformat(entry.detected_at)
            if detected.tzinfo is None:
                detected = detected.replace(tzinfo=timezone.utc)
            if detected.date() == today:
                count += 1
        except (ValueError, TypeError):
            continue
    return count


def _calc_duration(start_iso: str, end_iso: str) -> float:
    """Calculate duration in seconds between two ISO timestamps."""
    try:
        start = datetime.fromisoformat(start_iso)
        end = datetime.fromisoformat(end_iso)
        return (end - start).total_seconds()
    except (ValueError, TypeError):
        return 0.0


if __name__ == "__main__":
    main()
