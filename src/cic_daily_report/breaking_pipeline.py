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
)
from cic_daily_report.breaking.severity_classifier import (
    ClassifiedEvent,
    classify_batch,
)
from cic_daily_report.core.logger import get_logger

logger = get_logger("breaking_pipeline")

BREAKING_TIMEOUT_SECONDS = 20 * 60  # 20 minutes

# v0.29.0: Pipeline limits to prevent spam and quota exhaustion
MAX_EVENTS_PER_RUN = 5  # B1: max events to generate+send per run
MAX_DEFERRED_PER_RUN = 5  # A8: max deferred events to reprocess per run
DIGEST_THRESHOLD = 5  # B5: when >=N send_now events, switch to digest mode
INTER_EVENT_DELAY = 30  # B2: seconds between events sent to TG

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
    # Uses shared LLM, limited by MAX_DEFERRED_PER_RUN (A8)
    await _reprocess_deferred_events(run_log, result, dedup_mgr, llm)

    # Stage 1: Detect via CryptoPanic (primary)
    events: list = []
    use_rss_fallback = False
    try:
        events = await asyncio.wait_for(detect_breaking_events(), timeout=60)
    except asyncio.TimeoutError:
        logger.warning("CryptoPanic detection timed out — will try RSS fallback")
        use_rss_fallback = True
    except Exception as e:
        logger.warning(f"CryptoPanic detection failed: {e} — will try RSS fallback")
        use_rss_fallback = True

    # Stage 1b: RSS + LLM fallback (uses shared LLM — A3)
    if use_rss_fallback:
        rss_events = await _rss_fallback_detection(run_log, llm)
        events.extend(rss_events)

    # Stage 1c: Market triggers (always-on, additive)
    market_events = await _market_trigger_detection(run_log)
    events.extend(market_events)

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

    # B1: Cap events per run to prevent spam
    if len(send_now) > MAX_EVENTS_PER_RUN:
        overflow = send_now[MAX_EVENTS_PER_RUN:]
        send_now = send_now[:MAX_EVENTS_PER_RUN]
        for classified_event in overflow:
            run_log.events_deferred += 1
            result.deferred_events.append(classified_event)
            h = compute_hash(classified_event.event.title, classified_event.event.source)
            dedup_mgr.update_entry_status(
                h, "deferred_overflow", severity=classified_event.severity
            )
        logger.info(f"B1: Capped at {MAX_EVENTS_PER_RUN}, deferred {len(overflow)} overflow events")

    if not send_now:
        dedup_mgr.cleanup_old_entries()
        await _persist_dedup_to_sheets(dedup_mgr, new_entries=dedup_result.entries_written)
        run_log.status = "partial" if run_log.events_deferred > 0 else "no_events"
        return result

    # Stage 3b: Build enrichment context for content generation
    market_snapshot = ""
    try:
        from cic_daily_report.collectors.market_data import collect_market_data

        market_data = await asyncio.wait_for(collect_market_data(), timeout=30)
        market_snapshot = _format_market_snapshot(market_data)
    except Exception as e:
        logger.debug(f"Market context for breaking skipped: {e}")

    recent_events_text = _format_recent_events(dedup_mgr.entries)

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
        content = None  # v0.29.1 (BUG 5): track generation vs delivery failure
        try:
            if llm is None or llm.circuit_open:
                raise RuntimeError("LLM unavailable — circuit open")

            content = await asyncio.wait_for(
                generate_breaking_content(
                    classified_event.event,
                    llm,
                    severity=classified_event.severity,
                    market_context=market_snapshot,
                    recent_events=recent_events_text,
                ),
                timeout=60,
            )

            # Deliver immediately (not batched)
            await _deliver_single_breaking(content, classified_event)

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

            # B2: Delay between events (skip after last)
            if i < len(all_individual) - 1 or important_now:
                logger.info(f"B2: Waiting {INTER_EVENT_DELAY}s before next event")
                await asyncio.sleep(INTER_EVENT_DELAY)

        except Exception as e:
            logger.error(f"Event failed for '{classified_event.event.title}': {e}")
            # v0.29.1 (BUG 5): Distinguish generation vs delivery failure
            h = compute_hash(classified_event.event.title, classified_event.event.source)
            status = "delivery_failed" if content is not None else "generation_failed"
            dedup_mgr.update_entry_status(h, status, severity=classified_event.severity)
            run_log.errors.append(f"{'Deliver' if content else 'Generate'}: {e}")

    # Stage 4b: Important events (≥2) — batch into themed digest
    if important_now and llm is not None and not llm.circuit_open:
        await _generate_and_deliver_digest(
            important_now,
            llm,
            dedup_mgr,
            result,
            run_log,
            market_snapshot,
            dedup_result.entries_written,
        )
    elif important_now:
        # LLM unavailable — mark as generation_failed for retry
        for classified_event in important_now:
            h = compute_hash(classified_event.event.title, classified_event.event.source)
            dedup_mgr.update_entry_status(
                h, "generation_failed", severity=classified_event.severity
            )
            run_log.errors.append(f"LLM unavailable for digest: {classified_event.event.title}")

    # Cleanup old entries
    dedup_mgr.cleanup_old_entries()

    # Final persist (covers overflow deferrals, cleanup, any remaining updates)
    await _persist_dedup_to_sheets(dedup_mgr, new_entries=dedup_result.entries_written)

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
) -> None:
    """FR28: Reprocess deferred events when we're past the night window.

    v0.29.0 changes:
    - A3: Uses shared LLM instance (no separate init)
    - A6: Sorts by severity (critical first)
    - A8: Limits to MAX_DEFERRED_PER_RUN events
    - B2: 30s delay between events
    Also retries generation_failed + delivery_failed + deferred_overflow events (C3, max 1 retry).
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

    # A8: Limit deferred reprocessing
    if len(all_events) > MAX_DEFERRED_PER_RUN:
        logger.info(f"A8: Capping deferred from {len(all_events)} to {MAX_DEFERRED_PER_RUN}")
        all_events = all_events[:MAX_DEFERRED_PER_RUN]

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
                    ),
                    timeout=60,
                )
                message = f"{emoji} BREAKING NEWS\n\n{content.formatted}"
            else:
                # Fallback: raw data with hyperlink if LLM unavailable
                from cic_daily_report.breaking.content_generator import _raw_data_fallback

                fallback = _raw_data_fallback(event)
                message = f"{emoji} BREAKING NEWS\n\n{fallback.formatted}"

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


def _format_market_snapshot(market_data: list | None) -> str:
    """Format brief market context for breaking news prompt."""
    if not market_data:
        return ""
    lines = []
    for dp in market_data:
        if dp.symbol in ("BTC", "ETH"):
            lines.append(f"{dp.symbol}: ${dp.price:,.0f} ({dp.change_24h:+.1f}%)")
    for dp in market_data:
        if dp.symbol == "Fear_Greed":
            lines.append(f"Fear & Greed: {int(dp.price)}")
        elif dp.symbol == "DXY":
            lines.append(f"DXY: {dp.price:.1f}")
    return "Bối cảnh thị trường hiện tại: " + " | ".join(lines) if lines else ""


def _format_recent_events(dedup_entries: list[DedupEntry], max_events: int = 5) -> str:
    """Format recent breaking events for context injection."""
    recent = sorted(dedup_entries, key=lambda e: e.detected_at, reverse=True)[:max_events]
    if not recent:
        return ""
    lines = ["Tin Breaking gần đây (để liên kết nếu liên quan):"]
    for entry in recent:
        lines.append(f"- {entry.title} ({entry.source}, {entry.severity})")
    return "\n".join(lines)


async def _deliver_single_breaking(
    content: BreakingContent, classified_event: ClassifiedEvent
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
) -> None:
    """B5: Generate and deliver a single digest for multiple events.

    When >=DIGEST_THRESHOLD events need sending, combine into one summary
    to avoid spamming the Telegram channel.
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
        parts = split_message("BREAKING", message)
        for part in parts:
            await bot.send_message(part.formatted)
            await asyncio.sleep(0.5)

        # v0.29.1 (BUG 6): Count AFTER successful delivery, not before.
        result.contents.append(digest_content)
        run_log.events_sent += len(send_now)

        # Mark all events as sent
        for classified_event in send_now:
            result.sent_events.append(classified_event)
            h = compute_hash(classified_event.event.title, classified_event.event.source)
            dedup_mgr.update_entry_status(
                h,
                "sent_digest",
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
