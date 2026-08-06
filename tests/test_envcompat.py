# SPDX-License-Identifier: Apache-2.0
"""``ASG_*`` -> ``CAPSULE_*`` env-var rename: the shared ``env_get`` fallback
helper (unit-level) plus a couple of real call sites proving the alias
actually works end to end, not just in isolation.
"""
from __future__ import annotations

import pytest

from capsule_ledger.envcompat import env_get


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("CAPSULE_PROBE", raising=False)
    monkeypatch.delenv("ASG_PROBE", raising=False)


def test_new_name_used_when_set(monkeypatch):
    monkeypatch.setenv("CAPSULE_PROBE", "new-value")
    assert env_get("CAPSULE_PROBE", "ASG_PROBE") == "new-value"


def test_falls_back_to_old_name_when_new_unset(monkeypatch):
    monkeypatch.setenv("ASG_PROBE", "old-value")
    assert env_get("CAPSULE_PROBE", "ASG_PROBE") == "old-value"


def test_new_name_takes_precedence_over_old(monkeypatch):
    monkeypatch.setenv("CAPSULE_PROBE", "new-value")
    monkeypatch.setenv("ASG_PROBE", "old-value")
    assert env_get("CAPSULE_PROBE", "ASG_PROBE") == "new-value"


def test_default_used_when_neither_set():
    assert env_get("CAPSULE_PROBE", "ASG_PROBE", "fallback") == "fallback"
    assert env_get("CAPSULE_PROBE", "ASG_PROBE") is None


# -- real call sites, not just the helper in isolation -----------------------


def test_packaging_arm_new_name_unset_old_set_still_works(monkeypatch):
    """ASG_LEDGER_ARM unset, CAPSULE_LEDGER_ARM set -> new value used."""
    from capsule_ledger import packaging

    monkeypatch.delenv("ASG_LEDGER_ARM", raising=False)
    monkeypatch.setenv("CAPSULE_LEDGER_ARM", "guards-only")
    assert packaging.current_arm() == "guards-only"


def test_packaging_arm_new_name_unset_old_name_used_as_fallback(monkeypatch):
    """CAPSULE_LEDGER_ARM unset, ASG_LEDGER_ARM set -> old value used as fallback."""
    from capsule_ledger import packaging

    monkeypatch.delenv("CAPSULE_LEDGER_ARM", raising=False)
    monkeypatch.setenv("ASG_LEDGER_ARM", "guards-only")
    assert packaging.current_arm() == "guards-only"


def test_telemetry_opt_in_new_name_unset_old_set_still_works(monkeypatch):
    from capsule_ledger.telemetry import consent

    monkeypatch.delenv(consent.ENV_VAR, raising=False)
    monkeypatch.setenv(consent.ENV_VAR_LEGACY, "1")
    assert consent.is_opted_in() is True


def test_telemetry_opt_in_new_name_used_old_name_used_as_fallback(monkeypatch):
    from capsule_ledger.telemetry import consent

    monkeypatch.delenv(consent.ENV_VAR_LEGACY, raising=False)
    monkeypatch.setenv(consent.ENV_VAR, "1")
    assert consent.is_opted_in() is True
