# SPDX-License-Identifier: Apache-2.0
"""Local, vendored registry-convention snapshots -- see ``conventions.py``."""
from __future__ import annotations

from .conventions import ActionConvention, conventions_digest, describe_action_class

__all__ = ["ActionConvention", "conventions_digest", "describe_action_class"]
