"""Daily pipeline entry point — orchestrates full daily report generation.

Execution order: Data Collection → Content Generation → NQ05 Filter → Delivery.
Timeout: 40 minutes (NFR1). Partial delivery on timeout/error (NFR7).
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone

from cic_daily_report.core.logger import get_logger

logger = get_logger("daily_pipeline")

PIPELINE_TIMEOUT_SEC = 40 * 60  # 40 minutes (NFR1)


def main() -> None:
    """Run the daily pipeline."""
    is_production = os.getenv("GITHUB_ACTIONS") == "true"

    if not is_production:
        logger.info("Development mode — skipping real API calls")
        return

    asyncio.run(_run_pipeline())


async def _run_pipeline() -> None:
    """Execute the daily pipeline with timeout and error handling."""
    start = time.monotonic()
    run_log = _new_run_log()
    errors: list[Exception] = []
    articles: list[dict[str, str]] = []

    try:
        # Apply pipeline-level timeout
        articles, errors = await asyncio.wait_for(
            _execute_stages(),
            timeout=PIPELINE_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        logger.error("Pipeline timeout — delivering partial content")
        run_log["status"] = "timeout"
        errors.append(Exception("Pipeline timeout after 40 minutes"))
    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        run_log["status"] = "error"
        errors.append(e)

    # Deliver whatever we have (NFR7: always send something)
    try:
        await _deliver(articles, errors)
    except Exception as e:
        logger.error(f"Delivery failed: {e}")

    # Log pipeline run
    elapsed = time.monotonic() - start
    run_log["duration_sec"] = round(elapsed, 1)
    if run_log["status"] == "running":
        run_log["status"] = "success" if not errors else "partial"
    run_log["errors"] = [str(e) for e in errors]
    run_log["tiers_delivered"] = len(articles)

    logger.info(
        f"Pipeline complete: {run_log['status']} in {elapsed:.0f}s, "
        f"{len(articles)} articles, {len(errors)} errors"
    )

    # Write log to Sheets (best effort)
    try:
        await _write_run_log(run_log)
    except Exception as e:
        logger.error(f"Failed to write pipeline log: {e}")


async def _execute_stages() -> tuple[list[dict[str, str]], list[Exception]]:
    """Run all pipeline stages in order.

    Returns (articles, errors) — articles may be partial.
    """
    # Placeholder — each stage will be wired in as modules are integrated
    # Stage 1: Data Collection (Epic 2)
    # Stage 2: Content Generation (Epic 3)
    # Stage 3: NQ05 Filter (Epic 3)
    # Returns articles + any non-fatal errors
    return [], []


async def _deliver(
    articles: list[dict[str, str]],
    errors: list[Exception],
) -> None:
    """Deliver content via DeliveryManager.

    Placeholder — will be wired to delivery_manager.deliver() when integrated.
    """
    pass


async def _write_run_log(run_log: dict) -> None:
    """Write run log entry to NHAT_KY_PIPELINE sheet.

    Placeholder — will use SheetsClient.batch_append() when integrated.
    """
    pass


def _new_run_log() -> dict:
    """Create a new pipeline run log entry template."""
    return {
        "start_time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "end_time": "",
        "duration_sec": 0,
        "status": "running",
        "tiers_delivered": 0,
        "llm_used": "",
        "errors": [],
        "delivery_method": "",
    }


if __name__ == "__main__":
    main()
