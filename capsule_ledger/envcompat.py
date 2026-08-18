# SPDX-License-Identifier: Apache-2.0
"""Env-var read helper."""
from __future__ import annotations

import os

__all__ = ["env_get"]


def env_get(name: str, default: str | None = None) -> str | None:
    """Read ``name`` from the environment, else ``default``."""
    return os.environ.get(name, default)
