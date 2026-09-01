# SPDX-License-Identifier: Apache-2.0
"""``registry.conventions``: the minimal, self-contained action_class
convention-label lookup this repo's own core read/verify display surface
(``cli/format.py``, ``console/api.py``) uses. The full vendored CPB +
provisional-field-value registry moved to capsule-engine
([ldg-ledger-scope-re-extraction] RESIDUALS pass §3.1) -- see that repo's
own (larger) ``test_registry_conventions.py`` for ``describe_field_value``/
``conventions_digest`` coverage."""
from __future__ import annotations

from capsule_ledger.registry import describe_action_class


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
