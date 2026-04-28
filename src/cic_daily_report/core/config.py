"""Environment detection and base configuration."""

from __future__ import annotations

import os

IS_PRODUCTION: bool = os.getenv("GITHUB_ACTIONS") == "true"

# Version — single source of truth
VERSION = "2.0.0-alpha.21"


def _wave_0_6_enabled() -> bool:
    """Wave 0.6 feature flag — RAG inject + Cerebras Qwen3 fact-checker.

    WHY function (not module-level constant): allows runtime override via
    env var without re-importing module. Defaults to False — Wave 0.6
    Story 0.6.5 will flip to True after live monitoring confirms zero
    regression. Override via `WAVE_0_6_ENABLED=1`.
    """
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
    """
    return os.getenv("WAVE_0_6_DATE_BLOCK", "").strip().lower() in {"1", "true", "yes", "on"}


WAVE_0_6_DATE_BLOCK: bool = _wave_0_6_date_block_enabled()
