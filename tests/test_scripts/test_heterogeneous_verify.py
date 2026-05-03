"""Wave 0.9.1: graceful degradation tests cho heterogeneous_verify.py.

WHY: Wave 0.9 INTENT là "advisory only, không block merge", nhưng implementation
gốc raise on httpx.HTTPError → workflow exit 1 → required check fail → PR #26 BLOCKED.
Wave 0.9.1 hotfix: catch 402/429 + network errors, return advisory string.

Tests cover:
1. 402 Payment Required → advisory message, KHÔNG raise (regression test cho PR #26)
2. 429 Rate Limit → advisory message
3. 500 Server Error → vẫn raise (not quota issue, dev cần biết)
4. Network error (ConnectError) → advisory message
5. main() trong --ci mode wrap exception → exit 0
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

# Inject scripts/ vào sys.path để import heterogeneous_verify
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import heterogeneous_verify as hv  # noqa: E402


def _make_http_status_error(status_code: int) -> httpx.HTTPStatusError:
    """Build httpx.HTTPStatusError với status code cho trước."""
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = status_code
    return httpx.HTTPStatusError(
        f"HTTP {status_code}", request=MagicMock(spec=httpx.Request), response=mock_resp
    )


def test_402_payment_required_returns_advisory_not_raise():
    """402 Payment Required → return advisory string, KHÔNG raise.

    Regression test: chính bug đã block PR #26 alpha.39.
    """
    err = _make_http_status_error(402)
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = err

    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "fake-key"}):
        with patch("heterogeneous_verify.httpx.post", return_value=mock_resp):
            result = hv.call_openrouter("test code", "openai/gpt-4o-mini")

    # Advisory message phải mention status code + cho phép merge
    assert "402" in result
    assert "unavailable" in result.lower()
    assert "PR vẫn có thể merge" in result


def test_429_rate_limit_returns_advisory():
    """429 Rate Limit → advisory, không raise."""
    err = _make_http_status_error(429)
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = err

    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "fake-key"}):
        with patch("heterogeneous_verify.httpx.post", return_value=mock_resp):
            result = hv.call_openrouter("test code", "openai/gpt-4o-mini")

    assert "429" in result
    assert "PR vẫn có thể merge" in result


def test_500_server_error_still_raises():
    """500 Server Error → raise. Không phải quota issue, dev cần biết.

    WHY: chỉ 402/429 là quota/cost-related → graceful degrade.
    5xx/4xx khác có thể là bug/config → surface để fix.
    """
    err = _make_http_status_error(500)
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = err

    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "fake-key"}):
        with patch("heterogeneous_verify.httpx.post", return_value=mock_resp):
            with pytest.raises(httpx.HTTPStatusError):
                hv.call_openrouter("test", "openai/gpt-4o-mini")


def test_network_error_returns_advisory():
    """ConnectError (network down) → advisory, không raise."""
    network_err = httpx.ConnectError("Connection refused")

    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "fake-key"}):
        with patch("heterogeneous_verify.httpx.post", side_effect=network_err):
            result = hv.call_openrouter("test", "openai/gpt-4o-mini")

    assert "network error" in result.lower()
    assert "PR vẫn có thể merge" in result


def test_main_ci_mode_wraps_unexpected_exception_returns_zero(tmp_path, monkeypatch):
    """main() với --ci flag: bất kỳ exception nào cũng convert → exit 0.

    WHY: defense-in-depth. Dù call_openrouter có bug raise unexpected exception,
    CI mode TUYỆT ĐỐI không được block merge.
    """
    # Setup tmp file
    target = tmp_path / "fake.py"
    target.write_text("def foo(): pass\n", encoding="utf-8")

    # Mock cost guard để tránh ghi file thật
    monkeypatch.setattr(hv, "check_cost_guard", lambda _max: 1)

    # Force call_openrouter raise unexpected exception (không phải 402/429)
    monkeypatch.setattr(
        hv, "call_openrouter", MagicMock(side_effect=RuntimeError("boom unexpected"))
    )

    monkeypatch.setattr(sys, "argv", ["heterogeneous_verify", "--ci", str(target)])

    rc = hv.main()
    assert rc == 0  # CI mode never blocks


def test_main_dev_mode_unexpected_exception_propagates(tmp_path, monkeypatch):
    """main() KHÔNG có --ci: exception unexpected vẫn raise (dev cần biết)."""
    target = tmp_path / "fake.py"
    target.write_text("def foo(): pass\n", encoding="utf-8")

    monkeypatch.setattr(hv, "check_cost_guard", lambda _max: 1)
    monkeypatch.setattr(hv, "call_openrouter", MagicMock(side_effect=RuntimeError("boom")))

    monkeypatch.setattr(sys, "argv", ["heterogeneous_verify", str(target)])

    with pytest.raises(RuntimeError, match="boom"):
        hv.main()
