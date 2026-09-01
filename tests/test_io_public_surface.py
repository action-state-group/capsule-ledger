# SPDX-License-Identifier: Apache-2.0
"""``capsule_ledger.io`` is the sanctioned cross-repo entry point for ledger
I/O -- other repos (compiler, judge, engine) must not reach into
``capsule_ledger.cli.ledger_io``/``capsule_ledger.envcompat`` directly, since
``cli/__init__.py`` restricts its own ``__all__`` to ``main``."""
from __future__ import annotations

from capsule_ledger.cli import ledger_io
from capsule_ledger.envcompat import env_get as internal_env_get
from capsule_ledger.io import env_get, open_ledger, require_ledger_path


def test_reexports_are_the_same_objects_as_the_internal_implementation():
    assert open_ledger is ledger_io.open_ledger
    assert require_ledger_path is ledger_io.require_ledger_path
    assert env_get is internal_env_get


def test_env_get_reexport_behaves_like_the_original(monkeypatch):
    monkeypatch.setenv("CAPSULE_PROBE_PUBLIC", "value")
    assert env_get("CAPSULE_PROBE_PUBLIC") == "value"
    monkeypatch.delenv("CAPSULE_PROBE_PUBLIC", raising=False)
    assert env_get("CAPSULE_PROBE_PUBLIC", "fallback") == "fallback"
