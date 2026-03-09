"""Breaking news pipeline entry point — hourly event detection and alerting.

Orchestrates: Detect (5.1) → Dedup (5.4) → Generate (5.2) → Classify (5.3) → Deliver
Total time target: ≤20 minutes from pipeline start.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from cic_daily_report.breaking.content_generator import (
    BreakingContent,
    generate_breaking_content,
)
from cic_daily_report.breaking.dedup_manager import DedupEntry, DedupManager, compute_hash
from cic_daily_report.breaking.event_detector import (
    detect_breaking_events,
)
from cic_daily_report.breaking.severity_classifier import (
    ClassifiedEvent,
    classify_batch,
)
from cic_daily_report.core.logger import get_logger

logger = get_logger("breaking_pipeline")

BREAKING_TIMEOUT_SECONDS = 20 * 60  # 20 minutes


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

    return result


async def _execute_pipeline(run_log: BreakingRunLog) -> BreakingPipelineResult:
    """Core pipeline: detect → dedup → generate → classify → deliver.

    This function is called with external dependencies injected in production.
    For testability, the steps are also available as individual functions.
    """
    result = BreakingPipelineResult(run_log=run_log)

    # Stage 1: Detect (inner timeout 60s)
    try:
        events = await asyncio.wait_for(detect_breaking_events(), timeout=60)
        run_log.events_detected = len(events)
    except asyncio.TimeoutError:
        logger.error("Detection timed out after 60s")
        run_log.errors.append("Detection: timeout 60s")
        run_log.status = "error"
        return result
    except Exception as e:
        logger.error(f"Detection failed: {e}")
        run_log.errors.append(f"Detection: {e}")
        run_log.status = "error"
        return result

    if not events:
        run_log.status = "no_events"
        return result

    # Stage 2: Dedup
    dedup_mgr = DedupManager()  # In production, load from BREAKING_LOG sheet
    dedup_result = dedup_mgr.check_and_filter(events)
    run_log.events_new = len(dedup_result.new_events)
    result.dedup_entries = dedup_result.entries_written

    if not dedup_result.new_events:
        run_log.status = "no_events"
        return result

    # Stage 3: Classify
    classified = classify_batch(dedup_result.new_events)

    # Stage 4: Generate content + deliver based on classification
    from cic_daily_report.adapters.llm_adapter import LLMAdapter

    try:
        llm = LLMAdapter()
    except Exception as e:
        logger.warning(f"LLM init failed, will use raw data fallback: {e}")
        llm = None

    for classified_event in classified:
        if classified_event.is_deferred:
            run_log.events_deferred += 1
            result.deferred_events.append(classified_event)
            # Update dedup entry status
            h = compute_hash(
                classified_event.event.title, classified_event.event.source
            )
            dedup_mgr.update_entry_status(h, classified_event.delivery_action)
            continue

        # Generate content for events to send now
        try:
            content = await generate_breaking_content(
                classified_event.event,
                llm,
                severity=classified_event.severity,
            )
            result.contents.append(content)
            result.sent_events.append(classified_event)
            run_log.events_sent += 1

            # Update dedup entry
            h = compute_hash(
                classified_event.event.title, classified_event.event.source
            )
            dedup_mgr.update_entry_status(
                h,
                "sent",
                delivered_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as e:
            logger.error(f"Content generation failed for '{classified_event.event.title}': {e}")
            run_log.errors.append(f"Generate: {e}")

    # Deliver generated content via Telegram
    if result.contents:
        await _deliver_breaking(result)

    # Cleanup old entries
    dedup_mgr.cleanup_old_entries()

    run_log.status = "success" if run_log.events_sent > 0 else "partial"
    return result


async def _deliver_breaking(result: BreakingPipelineResult) -> None:
    """Deliver breaking news content via Telegram Bot."""
    from cic_daily_report.delivery.telegram_bot import TelegramBot

    severity_map = {"critical": "\U0001f534", "important": "\U0001f7e0",
                    "notable": "\U0001f7e1"}
    try:
        bot = TelegramBot()
        for content in result.contents:
            emoji = "\U0001f7e1"
            for evt in result.sent_events:
                if evt.event.title == content.event.title:
                    emoji = severity_map.get(evt.severity, "\U0001f7e1")
                    break

            message = f"{emoji} BREAKING NEWS\n\n{content.formatted}"
            await bot.send_message(message)
            logger.info(f"Breaking delivered: {content.event.title[:50]}...")
            # Rate limit delay between messages (same as daily pipeline)
            await asyncio.sleep(1.5)
    except Exception as e:
        logger.error(f"Breaking delivery failed: {e}")
        result.run_log.errors.append(f"Delivery: {e}")


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
