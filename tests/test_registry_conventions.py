# SPDX-License-Identifier: Apache-2.0
"""``registry.conventions``: the action_class convention-label lookup
(design principle item 2) -- the local, vendored stand-in for the
not-yet-existing ``capsule-registry`` "Action-type conventions" table."""
from __future__ import annotations

from capsule_ledger.registry import conventions_digest, describe_action_class


def test_no_action_class_is_a_distinct_state_from_unregistered():
    convention = describe_action_class(None)
    assert convention.action_class is None
    assert convention.registered is False
    assert "no action class" in convention.label


def test_registered_action_class_resolves_a_real_label():
    convention = describe_action_class("money.transfer")
    assert convention.registered is True
    assert convention.label == "Money transfer"
    assert convention.description


def test_unregistered_action_class_renders_as_is_never_an_error():
    convention = describe_action_class("hold.reserve")
    assert convention.registered is False
    assert convention.action_class == "hold.reserve"
    assert convention.label == "hold.reserve"  # renders as-is, not hidden


def test_conventions_digest_is_a_stable_real_digest():
    d1 = conventions_digest()
    d2 = conventions_digest()
    assert d1 == d2
    assert len(d1) == 64
    int(d1, 16)  # hex
