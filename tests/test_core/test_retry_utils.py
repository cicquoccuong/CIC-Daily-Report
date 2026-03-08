"""Tests for core/retry_utils.py."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from cic_daily_report.core.retry_utils import retry_async, retry_sync


class TestRetryAsync:
    async def test_succeeds_first_try(self):
        fn = AsyncMock(return_value="ok")
        result = await retry_async(fn, max_retries=3, base_delay=0.01)
        assert result == "ok"
        assert fn.call_count == 1

    async def test_retries_on_failure(self):
        fn = AsyncMock(side_effect=[ValueError("fail"), "ok"])
        result = await retry_async(fn, max_retries=3, base_delay=0.01)
        assert result == "ok"
        assert fn.call_count == 2

    async def test_raises_after_max_retries(self):
        fn = AsyncMock(side_effect=ValueError("always fails"))
        with pytest.raises(ValueError, match="always fails"):
            await retry_async(fn, max_retries=3, base_delay=0.01)
        assert fn.call_count == 3

    async def test_passes_args_and_kwargs(self):
        fn = AsyncMock(return_value="done")
        await retry_async(fn, "arg1", key="val", max_retries=1, base_delay=0.01)
        fn.assert_called_once_with("arg1", key="val")


class TestRetrySync:
    def test_succeeds_first_try(self):
        fn = MagicMock(return_value="ok")
        result = retry_sync(fn, max_retries=3, base_delay=0.01)
        assert result == "ok"

    def test_retries_on_failure(self):
        fn = MagicMock(side_effect=[ValueError("fail"), "ok"])
        result = retry_sync(fn, max_retries=3, base_delay=0.01)
        assert result == "ok"
        assert fn.call_count == 2

    def test_raises_after_max_retries(self):
        fn = MagicMock(side_effect=ValueError("nope"))
        with pytest.raises(ValueError, match="nope"):
            retry_sync(fn, max_retries=2, base_delay=0.01)
        assert fn.call_count == 2
