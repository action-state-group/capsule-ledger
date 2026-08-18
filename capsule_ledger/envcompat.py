# SPDX-License-Identifier: Apache-2.0
"""Env-var read helper for the ``ASG_*`` -> ``CAPSULE_*`` rename.

Every setting that used to be read from an ``ASG_*`` environment variable is
now read from its ``CAPSULE_*`` equivalent first, falling back silently to
the old ``ASG_*`` name if the new one isn't set -- so anything already
scripted against the old names keeps working for one release.
"""
from __future__ import annotations

import os

__all__ = ["env_get"]


def env_get(new_name: str, old_name: str, default: str | None = None) -> str | None:
    """Read ``new_name``, falling back to ``old_name``, then ``default``."""
    value = os.environ.get(new_name)
    if value is not None:
        return value
    return os.environ.get(old_name, default)
