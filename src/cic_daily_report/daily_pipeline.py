"""Daily pipeline entry point — orchestrates full daily report generation."""

import asyncio
import os


def main() -> None:
    """Run the daily pipeline."""
    is_production = os.getenv("GITHUB_ACTIONS") == "true"

    if not is_production:
        print("[DEV] Development mode — skipping real API calls")
        return

    asyncio.run(_run_pipeline())


async def _run_pipeline() -> None:
    """Execute the daily pipeline steps."""
    # Will be implemented in later stories:
    # 1. Load config from Google Sheets
    # 2. Collect data from all sources (parallel)
    # 3. Generate AI content (5 tiers + 1 summary)
    # 4. Deliver via Telegram
    # 5. Log run to NHAT_KY_PIPELINE
    pass


if __name__ == "__main__":
    main()
