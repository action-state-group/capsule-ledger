"""env_get: plain environment read with a default."""
from capsule_ledger.envcompat import env_get


def test_value_used_when_set(monkeypatch):
    monkeypatch.setenv("CAPSULE_PROBE", "value")
    assert env_get("CAPSULE_PROBE") == "value"


def test_default_when_unset(monkeypatch):
    monkeypatch.delenv("CAPSULE_PROBE", raising=False)
    assert env_get("CAPSULE_PROBE", "fallback") == "fallback"
    assert env_get("CAPSULE_PROBE") is None
