"""Shared retry logic — exponential backoff 3 attempts (2s→4s→8s)."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, TypeVar

from cic_daily_report.core.logger import get_logger

logger = get_logger("retry")

T = TypeVar("T")

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 2.0  # seconds


async def retry_async(
    fn: Callable[..., Any],
    *args: Any,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    **kwargs: Any,
) -> Any:
    """Retry an async function with exponential backoff.

    Delays: base_delay * 2^attempt (2s, 4s, 8s for defaults).
    """
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                logger.warning(
                    f"Attempt {attempt + 1}/{max_retries} failed: {e}. Retrying in {delay}s..."
                )
                await asyncio.sleep(delay)
            else:
                logger.error(f"All {max_retries} attempts failed: {e}")

    raise last_error  # type: ignore[misc]


def retry_sync(
    fn: Callable[..., T],
    *args: Any,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    **kwargs: Any,
) -> T:
    """Retry a sync function with exponential backoff."""
    import time

    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                logger.warning(
                    f"Attempt {attempt + 1}/{max_retries} failed: {e}. Retrying in {delay}s..."
                )
                time.sleep(delay)
            else:
                logger.error(f"All {max_retries} attempts failed: {e}")

    raise last_error  # type: ignore[misc]
