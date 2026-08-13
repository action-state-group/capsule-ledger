# SPDX-License-Identifier: Apache-2.0
"""AARM R8 acceptance tests for ``capsule_ledger.otel_export``.

Covers, in order: (1) the receipt-reference-never-copy rule at the type
level and against real ``GuardEngine`` decisions, (2) the no-payload-leak
guarantee, (3) graceful degradation (exporter failure never touches the
decision), (4) mapping-module isolation (``gen_ai.*`` never threaded outside
``mapping_genai.py``), (5) the OCSF and JSONL mapping targets.

Every negative/must-fail check here is written to demonstrably flip on its
own mutant (workspace rule: verification code must fail its mutants) --
see each test's own comment for what the mutant would be.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from capsule_ledger.guards import Action, GuardEngine
from capsule_ledger.otel_export import (
    ALLOW,
    DECISION_VALUES,
    DEFER,
    DENY,
    MODIFY,
    STEP_UP,
    DecisionEvent,
    DecisionExporter,
    ExporterConfig,
    JSONLDecisionExporter,
    decision_event_from_guard_decision,
)
from capsule_ledger.otel_export.mapping_genai import to_genai_attributes
from capsule_ledger.otel_export.mapping_jsonl import to_jsonl_line, to_jsonl_record
from capsule_ledger.otel_export.mapping_ocsf import to_ocsf_finding

OTEL_EXPORT_DIR = Path(__file__).parent.parent / "capsule_ledger" / "otel_export"


# -- 1. receipt REFERENCE, never a COPY: required at the type level --------


def test_decision_event_requires_a_receipt_digest():
    """Mutant this catches: dropping the ``__post_init__`` guard (or giving
    ``receipt_digest`` a default) would let a pointerless event through."""
    with pytest.raises(ValueError, match="receipt_digest"):
        DecisionEvent(action_verb="transfer_funds", decision=ALLOW, receipt_digest="")


def test_decision_event_rejects_unknown_decision_value():
    """Mutant this catches: removing the vocabulary check would let a typo
    (or a raw GuardEngine outcome string) leak into exported telemetry."""
    with pytest.raises(ValueError, match="decision must be one of"):
        DecisionEvent(action_verb="transfer_funds", decision="approved", receipt_digest="a" * 64)


def test_decision_event_rejects_bad_containment_result():
    with pytest.raises(ValueError, match="containment_result"):
        DecisionEvent(
            action_verb="x", decision=ALLOW, receipt_digest="a" * 64, containment_result="maybe"
        )


@pytest.mark.parametrize("outcome,expected_decision", [("allow", ALLOW), ("deny", DENY), ("escalate", STEP_UP)])
def test_receipt_digest_matches_the_real_capsule_id_for_every_outcome(
    store, caps_fold, signer, outcome, expected_decision
):
    """Real ``GuardEngine.check()`` calls, real capsules -- not a schema
    field that's never populated (same bar as test_guard_manifest_digest.py)."""
    engine = GuardEngine(ledger=store, caps_fold=caps_fold, signer_provider=lambda: signer, caps_minor={"money.transfer": 1})
    if outcome == "allow":
        action = Action(verb="info_lookup", operator="acme", developer="dev1", action_class="info.query")
    elif outcome == "deny":
        action = Action(
            verb="transfer_funds", operator="acme", developer="dev1", action_class="money.transfer",
            amount_minor=999_999_999, currency="EUR",
        )
        # money.transfer has an approver_role, so a pure cap breach escalates
        # (D2). Force a hard deny instead via a second, colliding action so
        # the dedupe constraint also fails -- dedupe+caps both failing is an
        # unconditional deny per `_decide`. No ``equivalence_key`` override
        # here: the ledger-side match recomputes the default formula from
        # the *stored* capsule fields (operator/developer/action_type/verb/
        # target), which never sees an action-side override, so an override
        # would silently defeat the repeat-match this test relies on.
        engine.check(action)
    else:
        action = Action(
            verb="transfer_funds", operator="acme", developer="dev2", action_class="money.transfer",
            amount_minor=500_000, currency="EUR",
        )

    decision = engine.check(action)
    assert decision.outcome == outcome
    assert decision.capsule is not None

    event = decision_event_from_guard_decision(decision, action)
    assert event is not None
    assert event.receipt_digest == decision.capsule["capsule_id"]
    assert event.decision == expected_decision


def test_receipt_digest_uses_the_json_digest_representation(store, caps_fold, signer):
    """AARM R8 review item 1: `receipt.digest` MUST carry `capsule_id` in the
    exact representation pinned by the core spec (§5.1) -- lowercase-hex
    SHA-256, 64 characters -- not some other encoding (base64url, a
    `sha256:`-prefixed string, etc). Mutant this catches: swapping
    ``receipt_digest`` for any re-encoded form of ``capsule_id`` (e.g.
    ``.encode().hex()`` double-encoding, uppercasing, or a prefixed variant)
    would still equal the digest under a loose comparison but fail this
    regex."""
    from agent_action_capsule import compute_capsule_id

    engine = GuardEngine(ledger=store, caps_fold=caps_fold, signer_provider=lambda: signer)
    action = Action(verb="info_lookup", operator="acme", developer="dev1", action_class="info.query")
    decision = engine.check(action)
    event = decision_event_from_guard_decision(decision, action)

    assert re.fullmatch(r"[0-9a-f]{64}", event.receipt_digest)
    assert event.receipt_digest == compute_capsule_id(decision.capsule)


def test_different_decisions_carry_different_receipt_digests(store, caps_fold, signer):
    """The mutant: hardcoding ``receipt_digest`` (or reusing one action's
    digest for another) would make this pass trivially -- it doesn't."""
    engine = GuardEngine(ledger=store, caps_fold=caps_fold, signer_provider=lambda: signer)
    action_a = Action(verb="info_lookup", operator="acme", developer="dev1", action_class="info.query")
    action_b = Action(verb="info_lookup", operator="acme", developer="dev2", action_class="info.query")

    event_a = decision_event_from_guard_decision(engine.check(action_a), action_a)
    event_b = decision_event_from_guard_decision(engine.check(action_b), action_b)

    assert event_a.receipt_digest != event_b.receipt_digest


def test_no_capsule_minted_yields_no_event(store, caps_fold):
    """The guard's fail-closed no-capsule paths (signing key unavailable)
    have no receipt to reference -- the builder must not fabricate one."""
    engine = GuardEngine(ledger=store, caps_fold=caps_fold, signer_provider=lambda: None)
    action = Action(verb="info_lookup", operator="acme", developer="dev1", action_class="info.query")
    decision = engine.check(action)

    assert decision.capsule is None
    assert decision_event_from_guard_decision(decision, action) is None


def test_optional_fields_absent_when_not_supplied(store, caps_fold, signer):
    """Same optionality pattern as ``guards/capsule.py``'s ``manifest_digest``:
    plan.digest/containment.result/identity.* come from a separate,
    in-progress branch (ldg-plan-containment) not yet on main -- omitted,
    not null, when the caller doesn't supply them."""
    engine = GuardEngine(ledger=store, caps_fold=caps_fold, signer_provider=lambda: signer)
    action = Action(verb="info_lookup", operator="acme", developer="dev1", action_class="info.query")
    event = decision_event_from_guard_decision(engine.check(action), action)

    attrs = event.to_attributes()
    for key in ("plan.digest", "outcome.id", "plan.step_index", "containment.result",
                "identity.human", "identity.service", "identity.agent", "identity.session"):
        assert key not in attrs


def test_plan_digest_and_containment_result_included_when_supplied(store, caps_fold, signer):
    engine = GuardEngine(ledger=store, caps_fold=caps_fold, signer_provider=lambda: signer)
    action = Action(verb="info_lookup", operator="acme", developer="dev1", action_class="info.query")
    event = decision_event_from_guard_decision(
        engine.check(action), action, plan_digest="p" * 64, containment_result="pass"
    )

    attrs = event.to_attributes()
    assert attrs["plan.digest"] == "p" * 64
    assert attrs["containment.result"] == "pass"


# -- 2. no receipt PAYLOAD ever emitted -------------------------------------


def test_to_attributes_never_carries_a_nested_structure():
    """Mutant this catches: threading a raw capsule dict (or any of its
    nested objects -- ``asg_signature``, ``constraints``, ``disposition``)
    into the event would show up here as a non-scalar value."""
    event = DecisionEvent(
        action_verb="transfer_funds", decision=DENY, receipt_digest="a" * 64,
        manifest_digest="b" * 64, plan_digest="c" * 64, outcome_id="o1", plan_step_index=2,
        containment_result="fail", identity_human="h", identity_service="s",
        identity_agent="ag", identity_session="sess", action_target="t",
    )
    for key, value in event.to_attributes().items():
        assert isinstance(value, (str, int)) and not isinstance(value, bool), f"{key} is not a scalar: {value!r}"


def test_receipt_payload_fields_never_appear_in_exported_attributes(store, caps_fold, signer):
    """The capsule this decision minted really does carry payload-shaped
    fields (``asg_signature``, ``constraints``, ``disposition``,
    ``asg_payload``) -- confirm none of their *names* leak into what gets
    exported, only the digest that points at them."""
    engine = GuardEngine(ledger=store, caps_fold=caps_fold, signer_provider=lambda: signer)
    action = Action(verb="info_lookup", operator="acme", developer="dev1", action_class="info.query")
    decision = engine.check(action)
    assert "asg_signature" in decision.capsule  # sanity: the capsule really has a payload to leak

    event = decision_event_from_guard_decision(decision, action)
    exported_keys = set(event.to_attributes())
    forbidden = {"asg_signature", "constraints", "disposition", "asg_payload", "capsule_id", "action_id"}
    assert exported_keys.isdisjoint(forbidden)
    exported_values = [str(v) for v in event.to_attributes().values()]
    assert not any("sig" in v.lower() and len(v) > 40 for v in exported_values if v != event.receipt_digest)


def test_emit_never_writes_a_receipt_payload_to_the_jsonl_sink(tmp_path, store, caps_fold, signer):
    """Automated test (acceptance item) asserting no receipt payload is
    ever emitted, exercised through the actual sink a caller would use."""
    engine = GuardEngine(ledger=store, caps_fold=caps_fold, signer_provider=lambda: signer)
    action = Action(verb="info_lookup", operator="acme", developer="dev1", action_class="info.query")
    decision = engine.check(action)
    event = decision_event_from_guard_decision(decision, action)

    sink_path = tmp_path / "decisions.jsonl"
    exporter = JSONLDecisionExporter(sink_path)
    assert exporter.export(event) is True

    line = sink_path.read_text().strip()
    record = json.loads(line)
    assert record["receipt.digest"] == decision.capsule["capsule_id"]
    assert set(record).isdisjoint({"asg_signature", "constraints", "disposition", "asg_payload"})


# -- 3. graceful degradation: exporter failure never touches the decision --
#
# Note on what these mutate: a ``SpanExporter`` whose own ``.export()``
# raises never actually reaches our code -- OpenTelemetry's own
# ``SimpleSpanProcessor`` already catches and logs that internally (verified
# by hand: mutating away *our* try/except around a raising span exporter did
# not make any test here fail, because the SDK's own safety net was still
# doing the catching). So the tests below force the failure at the points
# that are actually ours: tracer construction in ``__init__``, and attribute
# mapping inside ``export()`` -- removing either try/except flips these.


def test_exporter_setup_failure_never_raises(monkeypatch):
    """Mutant this catches: removing the try/except around tracer setup in
    ``__init__`` would raise out of construction when it fails."""
    import capsule_ledger.otel_export.exporter as exporter_mod

    def _boom(self, span_exporter):
        raise RuntimeError("tracer setup exploded")

    monkeypatch.setattr(exporter_mod.DecisionExporter, "_build_tracer", _boom)

    exporter = DecisionExporter(ExporterConfig(endpoint="http://localhost:4318"))  # must not raise
    assert exporter._tracer is None

    event = DecisionEvent(action_verb="transfer_funds", decision=DENY, receipt_digest="a" * 64)
    assert exporter.export(event) is False  # degraded to a silent no-op, not an error


def test_export_never_raises_when_attribute_mapping_itself_fails(monkeypatch):
    """Mutant this catches: removing the try/except in ``export()`` would
    raise out of it when mapping (or span creation) fails -- the one
    failure mode the SDK's own resilience does *not* cover, since it
    happens before any span exporter is ever invoked."""
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    import capsule_ledger.otel_export.exporter as exporter_mod

    def _boom(event):
        raise RuntimeError("attribute mapping exploded")

    monkeypatch.setattr(exporter_mod, "to_genai_attributes", _boom)
    exporter = DecisionExporter(ExporterConfig(endpoint="http://localhost:4318"), span_exporter=InMemorySpanExporter())
    event = DecisionEvent(action_verb="transfer_funds", decision=DENY, receipt_digest="a" * 64)

    assert exporter.export(event) is False  # did not raise, despite the mapping blowing up


def test_decision_outcome_is_identical_whether_or_not_export_is_attempted(monkeypatch, store, caps_fold, signer):
    """The property under test: a telemetry outage must not become an
    availability incident and must never change an enforcement outcome.
    Compute the same decision twice; only one call attempts a (broken)
    export in between."""
    engine = GuardEngine(ledger=store, caps_fold=caps_fold, signer_provider=lambda: signer)
    action_control = Action(verb="info_lookup", operator="acme", developer="dev-control", action_class="info.query")
    action_exported = Action(verb="info_lookup", operator="acme", developer="dev-exported", action_class="info.query")

    control_decision = engine.check(action_control)
    exported_decision = engine.check(action_exported)

    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    import capsule_ledger.otel_export.exporter as exporter_mod

    monkeypatch.setattr(exporter_mod, "to_genai_attributes", lambda event: (_ for _ in ()).throw(RuntimeError("boom")))
    exporter = DecisionExporter(ExporterConfig(endpoint="http://localhost:4318"), span_exporter=InMemorySpanExporter())
    event = decision_event_from_guard_decision(exported_decision, action_exported)
    exporter.export(event)  # would raise, if graceful degradation were broken

    assert control_decision.outcome == exported_decision.outcome == "allow"
    assert exported_decision.capsule is not None  # ledger append + signing happened, unaffected by export


def test_jsonl_exporter_never_raises_on_an_unwritable_path():
    """Mutant this catches: removing the try/except OSError around the write
    in ``JSONLDecisionExporter.export()`` would raise ``FileNotFoundError``
    out of it when the parent directory can't be created."""
    unwritable = Path("/nonexistent-root-dir-for-otel-export-test/decisions.jsonl")
    exporter = JSONLDecisionExporter(unwritable)
    event = DecisionEvent(action_verb="transfer_funds", decision=DENY, receipt_digest="a" * 64)

    assert exporter.export(event) is False  # failed, but did not raise


def test_export_of_none_event_is_a_silent_noop(tmp_path):
    assert DecisionExporter(ExporterConfig(enabled=False)).export(None) is False
    assert JSONLDecisionExporter(tmp_path / "x.jsonl").export(None) is False


# -- 4. mapping module isolation --------------------------------------------


def test_genai_attribute_names_are_isolated_to_one_file():
    """Mutant this catches: spelling a ``gen_ai.*`` attribute name directly
    in ``exporter.py``, ``event.py``, or any call site outside
    ``mapping_genai.py`` would make this fail."""
    offenders = []
    for path in OTEL_EXPORT_DIR.glob("*.py"):
        if path.name == "mapping_genai.py":
            continue
        text = path.read_text()
        if re.search(r"""["']gen_ai\.""", text):
            offenders.append(path.name)
    assert offenders == [], f"gen_ai.* attribute names leaked outside mapping_genai.py: {offenders}"


def test_ocsf_identifiers_are_isolated_to_one_file():
    offenders = []
    for path in OTEL_EXPORT_DIR.glob("*.py"):
        if path.name == "mapping_ocsf.py":
            continue
        text = path.read_text()
        if "class_uid" in text or "disposition_id" in text:
            offenders.append(path.name)
    assert offenders == [], f"OCSF identifiers leaked outside mapping_ocsf.py: {offenders}"


def test_one_mapping_module_per_target_format():
    for name in ("mapping_genai.py", "mapping_ocsf.py", "mapping_jsonl.py"):
        assert (OTEL_EXPORT_DIR / name).is_file()


# -- 5. mapping content -------------------------------------------------


def test_genai_mapping_carries_the_full_attribute_set_plus_genai_names():
    event = DecisionEvent(
        action_verb="transfer_funds", decision=ALLOW, receipt_digest="a" * 64,
        identity_agent="agent-1", identity_session="sess-1",
    )
    attrs = to_genai_attributes(event)
    assert attrs["receipt.digest"] == "a" * 64  # own namespace survives the gen_ai overlay
    assert attrs["gen_ai.tool.name"] == "transfer_funds"
    assert attrs["gen_ai.agent.id"] == "agent-1"
    assert attrs["gen_ai.conversation.id"] == "sess-1"


@pytest.mark.parametrize("decision,disposition", [(ALLOW, "Allowed"), (DENY, "Blocked")])
def test_ocsf_mapping_uses_real_disposition_values_for_allow_deny(decision, disposition):
    event = DecisionEvent(action_verb="x", decision=decision, receipt_digest="a" * 64)
    finding = to_ocsf_finding(event)
    assert finding["class_uid"] == 2004
    assert finding["disposition"] == disposition


@pytest.mark.parametrize("decision", [STEP_UP, DEFER, MODIFY])
def test_ocsf_mapping_falls_back_to_other_for_values_ocsf_has_no_disposition_for(decision):
    """Documents the honest mismatch (module docstring): OCSF's disposition
    enum has no counterpart for these three, so they fall back to Other
    rather than silently mis-mapping to Allowed/Blocked."""
    event = DecisionEvent(action_verb="x", decision=decision, receipt_digest="a" * 64)
    finding = to_ocsf_finding(event)
    assert finding["disposition"] == "Other"
    assert finding["disposition_id"] == 99


def test_ocsf_unmapped_bag_preserves_the_full_attribute_set():
    event = DecisionEvent(action_verb="x", decision=DENY, receipt_digest="a" * 64, manifest_digest="b" * 64)
    finding = to_ocsf_finding(event)
    assert finding["unmapped"]["asg_ext.receipt.digest"] == "a" * 64
    assert finding["unmapped"]["asg_ext.manifest.digest"] == "b" * 64


def test_jsonl_mapping_always_works_with_no_external_config():
    event = DecisionEvent(action_verb="x", decision=ALLOW, receipt_digest="a" * 64)
    line = to_jsonl_line(event)
    assert json.loads(line) == to_jsonl_record(event) == event.to_attributes()


def test_decision_values_cover_the_full_aarm_vocabulary():
    assert DECISION_VALUES == {ALLOW, DENY, MODIFY, STEP_UP, DEFER}


# -- 6. real OTLP collector round-trip (opt-in integration test) -----------
#
# AARM R8 review item 8: the original "OTLP export working against a local
# collector" evidence was a hand-run Docker session, pasted into a log and
# torn down after -- reproducible only by re-arguing it, not by re-running
# it. This test reproduces that verification for real: spins up
# `otel/opentelemetry-collector-contrib` with a `file` exporter, sends one
# real DecisionEvent through DecisionExporter's OTLP/http path, and asserts
# the collector actually received `receipt.digest`. Skipped by default --
# needs Docker and a network pull of the collector image -- opt in with
# CAPSULE_LEDGER_OTEL_INTEGRATION_TEST=1.

_INTEGRATION_ENV_VAR = "CAPSULE_LEDGER_OTEL_INTEGRATION_TEST"


def _iter_otlp_json_spans(record):
    for resource_spans in record.get("resourceSpans", []):
        for scope_spans in resource_spans.get("scopeSpans", []):
            yield from scope_spans.get("spans", [])


@pytest.mark.skipif(
    os.environ.get(_INTEGRATION_ENV_VAR) != "1",
    reason=f"opt-in only (needs Docker) -- set {_INTEGRATION_ENV_VAR}=1 to run",
)
def test_decision_event_round_trips_through_a_real_otlp_collector(store, caps_fold, signer):
    """Mutant this catches: anything that silently drops `receipt.digest` (or
    any other required attribute) between `DecisionExporter.export()` and the
    wire -- a mapping bug an in-memory exporter test can't see, because it
    never serializes the OTLP protobuf/JSON payload at all."""
    import shutil
    import socket
    import subprocess
    import tempfile
    import time

    if shutil.which("docker") is None:
        pytest.skip("docker not available")

    def _free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    http_port = _free_port()
    # Bind-mounted files must live under $HOME: Docker Desktop/colima on
    # macOS only shares $HOME into the VM by default, not the system tmp dir
    # pytest's own `tmp_path` fixture uses -- a mount rooted there fails
    # opaquely ("not a directory") rather than a clear "no such path" error.
    cache_dir = Path.home() / ".cache"
    cache_dir.mkdir(exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="capsule_ledger_otel_it_", dir=cache_dir))
    output_file = work_dir / "collector-output.jsonl"
    output_file.write_text("")
    config_path = work_dir / "collector-config.yaml"
    config_path.write_text(
        "receivers:\n"
        "  otlp:\n"
        "    protocols:\n"
        "      http:\n"
        "        endpoint: 0.0.0.0:4318\n"
        "exporters:\n"
        "  file:\n"
        "    path: /output/collector-output.jsonl\n"
        "service:\n"
        "  pipelines:\n"
        "    traces:\n"
        "      receivers: [otlp]\n"
        "      exporters: [file]\n"
    )

    container_name = f"capsule-ledger-otel-it-{os.getpid()}"
    subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
    run = subprocess.run(
        [
            "docker", "run", "-d", "--name", container_name,
            "-p", f"{http_port}:4318",
            "-v", f"{config_path}:/etc/otelcol-contrib/config.yaml",
            "-v", f"{work_dir}:/output",
            "otel/opentelemetry-collector-contrib:latest",
        ],
        capture_output=True, text=True,
    )
    if run.returncode != 0:
        pytest.skip(f"could not start otel-collector-contrib: {run.stderr.strip()}")

    try:
        import requests

        traces_url = f"http://127.0.0.1:{http_port}/v1/traces"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                # A bare TCP accept can succeed slightly before the HTTP
                # handler is actually installed -- a real POST is the only
                # readiness signal that isn't racy.
                resp = requests.post(traces_url, json={"resourceSpans": []}, timeout=1)
                if resp.status_code == 200:
                    break
            except requests.exceptions.RequestException:
                pass
            time.sleep(0.5)
        else:
            pytest.fail("collector did not become ready to accept traces within 30s")

        engine = GuardEngine(ledger=store, caps_fold=caps_fold, signer_provider=lambda: signer)
        action = Action(verb="transfer_funds", operator="acme", developer="dev1", action_class="info.query")
        decision = engine.check(action)
        event = decision_event_from_guard_decision(decision, action)
        assert event is not None

        exporter = DecisionExporter(ExporterConfig(endpoint=f"http://127.0.0.1:{http_port}/v1/traces"))
        assert exporter.export(event) is True

        deadline = time.monotonic() + 15
        content = ""
        while time.monotonic() < deadline:
            content = output_file.read_text()
            if content.strip():
                break
            time.sleep(0.5)
        assert content.strip(), "collector never wrote any output -- the span was not received"

        attrs = {}
        for line in content.strip().splitlines():
            record = json.loads(line)
            for span in _iter_otlp_json_spans(record):
                for attr in span.get("attributes", []):
                    attrs[attr["key"]] = attr["value"].get("stringValue")

        assert attrs.get("receipt.digest") == event.receipt_digest
        assert attrs.get("decision") == event.decision
        assert attrs.get("gen_ai.tool.name") == event.action_verb
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
        shutil.rmtree(work_dir, ignore_errors=True)
