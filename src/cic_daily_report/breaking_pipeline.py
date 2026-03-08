"""Breaking news pipeline entry point — hourly event detection and alerting."""

import asyncio
import os


def main() -> None:
    """Run the breaking news pipeline."""
    is_production = os.getenv("GITHUB_ACTIONS") == "true"

    if not is_production:
        print("[DEV] Development mode — skipping real API calls")
        return

    asyncio.run(_run_breaking_check())


async def _run_breaking_check() -> None:
    """Execute the breaking news detection pipeline."""
    # Will be implemented in Epic 5:
    # 1. Load config from Google Sheets
    # 2. Check CryptoPanic for breaking events
    # 3. Classify severity (red/orange/yellow)
    # 4. Apply Night Mode filter
    # 5. Generate alert content
    # 6. Deliver via Telegram
    pass


if __name__ == "__main__":
    main()
