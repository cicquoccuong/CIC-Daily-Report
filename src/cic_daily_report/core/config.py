"""Environment detection and base configuration."""

from __future__ import annotations

import os

IS_PRODUCTION: bool = os.getenv("GITHUB_ACTIONS") == "true"

# Version — single source of truth
VERSION = "2.0.0-alpha.30"


def _wave_0_6_kill_switch_active() -> bool:
    """Wave 0.6 Story 0.6.5 (alpha.23) — Master kill switch for entire Wave 0.6.

    WHY separate flag overriding all 3 sub-flags: production rollback must be
    1-click. If any Wave 0.6 feature (RAG inject, Cerebras judge, date block,
    2-source verify) misbehaves, operator sets WAVE_0_6_KILL_SWITCH=1 and ALL
    Wave 0.6 flags become OFF immediately — without requiring operator to
    individually unset each one. Defaults to False.
    Override via `WAVE_0_6_KILL_SWITCH=1`.
    """
    return os.getenv("WAVE_0_6_KILL_SWITCH", "").strip().lower() in {"1", "true", "yes", "on"}


def _wave_0_6_enabled() -> bool:
    """Wave 0.6 feature flag — RAG inject + Cerebras Qwen3 fact-checker.

    WHY function (not module-level constant): allows runtime override via
    env var without re-importing module. Defaults to False — Wave 0.6
    Story 0.6.5 will flip to True after live monitoring confirms zero
    regression. Override via `WAVE_0_6_ENABLED=1`.

    Story 0.6.5 (alpha.23): kill switch overrides this flag — when active,
    returns False unconditionally regardless of WAVE_0_6_ENABLED env value.
    """
    if _wave_0_6_kill_switch_active():
        return False
    return os.getenv("WAVE_0_6_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


# Module-level alias for read-once callers (e.g., logging at import time).
# Hot-path callers should call _wave_0_6_enabled() to honor runtime overrides.
WAVE_0_6_ENABLED: bool = _wave_0_6_enabled()


def _wave_0_6_date_block_enabled() -> bool:
    """Wave 0.6 Story 0.6.3 (alpha.21) — Hard-block stale dates feature flag.

    WHY separate flag from WAVE_0_6_ENABLED: date-block enforcement is more
    aggressive than RAG inject (it can drop sentences / fail delivery).
    Operator may want RAG ON but date-block OFF during initial rollout to
    measure false-positive rate before enforcing. Defaults to False — safe.
    Override via `WAVE_0_6_DATE_BLOCK=1`.

    Story 0.6.5 (alpha.23): kill switch overrides this flag.
    """
    if _wave_0_6_kill_switch_active():
        return False
    return os.getenv("WAVE_0_6_DATE_BLOCK", "").strip().lower() in {"1", "true", "yes", "on"}


WAVE_0_6_DATE_BLOCK: bool = _wave_0_6_date_block_enabled()


def _wave_0_6_2source_required() -> bool:
    """Wave 0.6 Story 0.6.4 (alpha.22) — Require 2nd source for breaking events.

    WHY: Audit Round 2 found CoinDesk + CoinTelegraph publishing the same event
    (Canada Bill C-25) within minutes — both passed dedup as separate sources
    and got sent twice. Conversely, single-source critical claims have higher
    hallucination risk. With this flag ON, critical events without a 2nd source
    are deferred; important/notable single-source events ship but get logged.

    Defaults to False — safe deploy. Override via `WAVE_0_6_2SOURCE_REQUIRED=1`.

    Story 0.6.5 (alpha.23): kill switch overrides this flag.
    """
    if _wave_0_6_kill_switch_active():
        return False
    return os.getenv("WAVE_0_6_2SOURCE_REQUIRED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


WAVE_0_6_2SOURCE_REQUIRED: bool = _wave_0_6_2source_required()
