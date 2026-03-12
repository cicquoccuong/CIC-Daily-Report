"""Environment detection and base configuration."""

from __future__ import annotations

import os

IS_PRODUCTION: bool = os.getenv("GITHUB_ACTIONS") == "true"

# Version — single source of truth
VERSION = "0.14.3"
