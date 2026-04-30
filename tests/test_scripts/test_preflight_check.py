"""Tests for scripts/preflight_check.py — Wave 0.8 flag rollout pre-flight.

WHY tests despite this being a "scripts" file (not core pipeline):
preflight is the gatekeeper before anh Cuong flips flags in production.
A bug here = false confidence = bad flags shipped. We treat it like core.

We mock all external I/O (LLM, Sheets, Telegram, Telethon) so tests run
offline + zero quota burn. Mocks return shapes that match what the real
clients return — see _mock_llm_adapter / _mock_sheets_client below.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Make scripts/ importable as a package — same trick test_replay_breaking
# (if it existed) would use. We import the file directly via its path.
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

import preflight_check as pc  # noqa: E402

# ---------------------------------------------------------------------------
# Test 1 — secrets present
# ---------------------------------------------------------------------------


def test_preflight_all_secrets_present(monkeypatch):
    """All required env vars set → check returns passed=True."""
    for k in (
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "CEREBRAS_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "ADMIN_CHAT_ID",
        "GOOGLE_SHEETS_CREDENTIALS",
        "GOOGLE_SHEETS_SPREADSHEET_ID",
    ):
        monkeypatch.setenv(k, "x")
    result = pc._check_secrets()
    assert result.passed is True
    assert "all" in result.message.lower()


# ---------------------------------------------------------------------------
# Test 2 — missing groq fails
# ---------------------------------------------------------------------------


def test_preflight_missing_groq_fails(monkeypatch):
    """Missing GROQ_API_KEY → check fails + names Groq in details."""
    # Only set Gemini + Cerebras — Groq deliberately absent.
    for k in (
        "GEMINI_API_KEY",
        "CEREBRAS_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "ADMIN_CHAT_ID",
        "GOOGLE_SHEETS_CREDENTIALS",
        "GOOGLE_SHEETS_SPREADSHEET_ID",
    ):
        monkeypatch.setenv(k, "x")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    result = pc._check_secrets()
    assert result.passed is False
    assert "Groq" in result.details


# ---------------------------------------------------------------------------
# Test 3 — LLM providers smoke (mock 4 providers)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preflight_llm_providers_smoke():
    """Mock LLMAdapter so generate() returns 'ok' for all 4 providers."""
    mock_adapter = MagicMock()
    mock_adapter.generate = AsyncMock(return_value="ok")
    # Patch at the module that _check_llm_providers imports from.
    with patch(
        "cic_daily_report.adapters.llm_adapter.LLMAdapter",
        return_value=mock_adapter,
    ):
        result = await pc._check_llm_providers()
    assert result.passed is True
    assert "4/4" in result.message


@pytest.mark.asyncio
async def test_preflight_llm_one_provider_fails():
    """If 1 of 4 providers fails, overall check fails + lists offender."""
    call_count = {"n": 0}

    def _factory(prefer):
        call_count["n"] += 1
        m = MagicMock()
        if prefer == "groq-qwen3":
            m.generate = AsyncMock(side_effect=RuntimeError("rate limit"))
        else:
            m.generate = AsyncMock(return_value="ok")
        return m

    with patch(
        "cic_daily_report.adapters.llm_adapter.LLMAdapter",
        side_effect=_factory,
    ):
        result = await pc._check_llm_providers()
    assert result.passed is False
    assert "groq-qwen3" in result.details


# ---------------------------------------------------------------------------
# Test 4 — Sheets read smoke
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preflight_sheets_read_smoke():
    """Mock SheetsClient so read_all returns sample rows."""
    mock_client = MagicMock()
    mock_client.read_all = MagicMock(return_value=[{"id": 1}, {"id": 2}])
    with patch(
        "cic_daily_report.storage.sheets_client.SheetsClient",
        return_value=mock_client,
    ):
        result = await pc._check_sheets_read()
    assert result.passed is True
    assert "2 rows" in result.message


@pytest.mark.asyncio
async def test_preflight_sheets_read_fails_on_creds():
    """Sheets client raises (e.g., bad creds) → check fails with type name."""
    with patch(
        "cic_daily_report.storage.sheets_client.SheetsClient",
        side_effect=ValueError("bad creds"),
    ):
        result = await pc._check_sheets_read()
    assert result.passed is False
    assert "ValueError" in result.message


# ---------------------------------------------------------------------------
# Test 5 — Telegram bot smoke
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preflight_telegram_smoke(monkeypatch):
    """Mock httpx response so getMe returns ok=True."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")

    mock_resp = MagicMock()
    mock_resp.json = MagicMock(return_value={"ok": True, "result": {"username": "test_bot"}})

    class _MockClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def get(self, url):
            return mock_resp

    with patch("httpx.AsyncClient", return_value=_MockClient()):
        result = await pc._check_telegram_bot()
    assert result.passed is True
    assert "test_bot" in result.message


@pytest.mark.asyncio
async def test_preflight_telegram_missing_token(monkeypatch):
    """Token absent → check fails immediately, no HTTP call."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    result = await pc._check_telegram_bot()
    assert result.passed is False
    assert "missing" in result.message.lower()


# ---------------------------------------------------------------------------
# Test 6 — RAG build smoke
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preflight_rag_build_smoke():
    """RagIndex instantiates → check passes. We don't mock — real ctor."""
    result = await pc._check_rag_build()
    # If RagIndex import fails for any reason in the env, we still want
    # informative output (not a test crash).
    if not result.passed:
        pytest.fail(f"RAG build smoke unexpectedly failed: {result.message}")
    assert result.passed is True


# ---------------------------------------------------------------------------
# Test 7 — exit code 0 when all required pass
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preflight_exit_code_0_all_pass():
    """run_preflight with all stub checks passing → exit_code == 0."""

    def stub_pass():
        return pc.CheckResult(name="stub", passed=True, message="ok")

    report = await pc.run_preflight(checks=[stub_pass, stub_pass])
    assert report.exit_code == 0
    assert report.required_failed == 0


# ---------------------------------------------------------------------------
# Test 8 — exit code 1 when any required fails
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preflight_exit_code_1_any_fail():
    """One required check fails → exit_code == 1.

    Optional-failed should NOT bump exit code — verify with mixed report.
    """

    def stub_pass():
        return pc.CheckResult(name="ok", passed=True, message="ok")

    def stub_required_fail():
        return pc.CheckResult(name="bad", passed=False, message="x", required=True)

    def stub_optional_fail():
        return pc.CheckResult(name="opt", passed=False, message="x", required=False)

    report = await pc.run_preflight(checks=[stub_pass, stub_required_fail, stub_optional_fail])
    assert report.exit_code == 1
    assert report.required_failed == 1
    assert report.optional_failed == 1


# ---------------------------------------------------------------------------
# Test 9 — verbose mode adds details
# ---------------------------------------------------------------------------


def test_preflight_verbose_mode():
    """Verbose=True renders details lines under failed checks."""
    report = pc.PreflightReport()
    report.add(
        pc.CheckResult(
            name="failed-check",
            passed=False,
            message="bad",
            details="line1\nline2",
        )
    )
    out_default = pc.render_report(report, verbose=False)
    out_verbose = pc.render_report(report, verbose=True)
    assert "line1" not in out_default
    assert "line1" in out_verbose
    assert "line2" in out_verbose


# ---------------------------------------------------------------------------
# Test 10 — output format basics
# ---------------------------------------------------------------------------


def test_preflight_output_format():
    """Verify report has expected sections: header, rows, summary, verdict."""
    report = pc.PreflightReport()
    report.add(pc.CheckResult(name="alpha", passed=True, message="ok"))
    report.add(pc.CheckResult(name="beta", passed=False, message="bad"))
    out = pc.render_report(report, verbose=False)
    # Header
    assert "Pre-flight" in out
    # Both rows present (name field anchored — no fuzzy match needed).
    assert "alpha" in out and "beta" in out
    # Summary line
    assert "Summary:" in out
    # Verdict (NOT READY because beta is required+failed by default)
    assert "NOT READY" in out


def test_preflight_output_verdict_ready():
    """All checks pass → verdict says READY."""
    report = pc.PreflightReport()
    report.add(pc.CheckResult(name="x", passed=True, message="ok"))
    out = pc.render_report(report, verbose=False)
    assert "READY" in out
    assert "NOT READY" not in out


# ---------------------------------------------------------------------------
# Bonus — main() smoke
# ---------------------------------------------------------------------------


def test_preflight_main_returns_exit_code(monkeypatch):
    """main() should call run_preflight + return its exit_code."""

    fake_report = pc.PreflightReport()
    fake_report.add(pc.CheckResult(name="x", passed=True, message="ok"))

    async def _fake_run(checks=None):
        return fake_report

    with patch.object(pc, "run_preflight", side_effect=_fake_run):
        rc = pc.main([])
    assert rc == 0


def test_preflight_main_verbose_flag():
    """main(['--verbose']) should not crash + still return exit code."""
    fake_report = pc.PreflightReport()
    fake_report.add(pc.CheckResult(name="x", passed=True, message="ok"))

    async def _fake_run(checks=None):
        return fake_report

    with patch.object(pc, "run_preflight", side_effect=_fake_run):
        rc = pc.main(["--verbose"])
    assert rc == 0
