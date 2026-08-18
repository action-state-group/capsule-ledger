# SPDX-License-Identifier: Apache-2.0
"""`capsule payload put` + resolve-at-read wiring in `capsule show`/`capsule
log` (ldg-registry-driven-viewer item 5a): local-auto-resolve on a real
ledger directory with a payload store present, match + mismatch rendering,
and staying digest-only everywhere resolve-at-read does not apply (no store,
an imported JSONL fixture, or a bundle export)."""
from __future__ import annotations

import json

from agent_action_capsule import json_digest

from capsule_ledger.cli.main import main
from capsule_ledger.ledger import LedgerStore

EVIDENCE = {"threshold_minor": 1000000, "observed_minor": 1200000, "window": "2026-W32"}
REASON = {"policy": "weekly-cap", "note": "over by 200000 minor units"}
EVIDENCE_DIGEST = json_digest(EVIDENCE)
REASON_DIGEST = json_digest(REASON)
CAPSULE_ID = "a" * 64


def _capsule(*, action_class="money.transfer", assurance_mode="self_attested"):
    cap = {
        "capsule_id": CAPSULE_ID,
        "operator": "acme",
        "developer": "agent-1",
        "action_id": "approve_purchase/1",
        "action_type": "decide",
        "timestamp": "2026-08-11T00:00:00Z",
        "assurance": {"attestation_mode": assurance_mode, "effect_mode": "not_applicable", "ledger_mode": "standalone"},
        "disposition": {"decision": "reject", "verdict_class": "blocked", "reason_digest": REASON_DIGEST},
        "constraints": [{"id": "caps", "result": "fail", "evidence_digest": EVIDENCE_DIGEST}],
    }
    if action_class:
        cap["asg_payload"] = {"action_class": action_class}
    return cap


def _seed_ledger(root):
    store = LedgerStore(root)
    store.append(_capsule(), consequential=False)
    store.close()


def _write_payload_file(tmp_path, payload, name="payload.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# -- `capsule payload put` ---------------------------------------------------


def test_payload_put_stores_keyed_by_real_digest_and_prints_it(tmp_path, capsys):
    ledger_root = tmp_path / "ledger"
    _seed_ledger(ledger_root)
    payload_file = _write_payload_file(tmp_path, EVIDENCE)

    rc = main(["payload", "put", str(payload_file), "--ledger", str(ledger_root)])
    assert rc == 0
    out = capsys.readouterr().out
    assert EVIDENCE_DIGEST in out
    assert "never exported, never bundled" in out

    stored = ledger_root / "payloads" / f"{EVIDENCE_DIGEST}.json"
    assert stored.is_file()
    assert json.loads(stored.read_text()) == EVIDENCE


def test_payload_put_refuses_a_non_directory_ledger(tmp_path, capsys):
    """The payload store only exists for a real, local ledger DIRECTORY --
    fail closed rather than silently writing somewhere nonsensical."""
    fixture_file = tmp_path / "sample.jsonl"
    fixture_file.write_text(json.dumps(_capsule()) + "\n", encoding="utf-8")
    payload_file = _write_payload_file(tmp_path, EVIDENCE)

    rc = main(["payload", "put", str(payload_file), "--ledger", str(fixture_file)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "real ledger directory" in err


def test_bare_payload_command_prints_help(capsys):
    rc = main(["payload"])
    assert rc == 0
    assert "payload" in capsys.readouterr().out


# -- `capsule show` resolve-at-read ------------------------------------------


def test_show_does_not_resolve_when_no_payload_store_exists(tmp_path, capsys):
    ledger_root = tmp_path / "ledger"
    _seed_ledger(ledger_root)

    rc = main(["show", CAPSULE_ID, "--ledger", str(ledger_root)])
    assert rc == 0
    out = capsys.readouterr().out
    assert f"evidence_digest: {EVIDENCE_DIGEST}" in out
    assert "resolved evidence" not in out
    assert "resolved reason" not in out


def test_show_auto_resolves_matching_evidence_and_reason(tmp_path, capsys):
    ledger_root = tmp_path / "ledger"
    _seed_ledger(ledger_root)
    rc = main(["payload", "put", str(_write_payload_file(tmp_path, EVIDENCE)), "--ledger", str(ledger_root)])
    assert rc == 0
    rc = main(["payload", "put", str(_write_payload_file(tmp_path, REASON, name="reason.json")), "--ledger", str(ledger_root)])
    assert rc == 0

    rc = main(["show", CAPSULE_ID, "--ledger", str(ledger_root)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "resolved evidence (from your local payload store — not part of the record" in out
    assert "digest recomputed live: match" in out
    assert '"threshold_minor": 1000000' in out
    assert "resolved reason (from your local payload store" in out
    assert '"policy": "weekly-cap"' in out


def test_show_reports_a_tampered_local_copy_loudly(tmp_path, capsys):
    ledger_root = tmp_path / "ledger"
    _seed_ledger(ledger_root)
    main(["payload", "put", str(_write_payload_file(tmp_path, EVIDENCE)), "--ledger", str(ledger_root)])
    capsys.readouterr()

    tampered_path = ledger_root / "payloads" / f"{EVIDENCE_DIGEST}.json"
    tampered_path.write_text(json.dumps({"threshold_minor": 1}), encoding="utf-8")

    rc = main(["show", CAPSULE_ID, "--ledger", str(ledger_root)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "does NOT match" in out
    assert "may be corrupted or tampered" in out
    assert "digest recomputed live: match" not in out


def test_show_never_auto_resolves_an_imported_jsonl_fixture(tmp_path, capsys):
    """A --ledger pointing at a loose JSONL fixture (a foreign/imported
    bundle, opened into a throwaway tempdir by open_ledger()) must never
    auto-resolve -- even when the fixture file sits right next to a real,
    populated payload store (the fixture's own parent directory), which is
    the realistic near-miss: a gate that fell back to "the ledger path's
    parent directory" instead of refusing outright would leak here."""
    ledger_root = tmp_path / "ledger"
    _seed_ledger(ledger_root)
    main(["payload", "put", str(_write_payload_file(tmp_path, EVIDENCE)), "--ledger", str(ledger_root)])
    capsys.readouterr()

    # Deliberately placed INSIDE ledger_root, alongside the real payloads/
    # directory -- not off in some unrelated tmp_path location, which
    # wouldn't exercise a "fall back to the parent directory" regression.
    fixture_file = ledger_root / "sample.jsonl"
    fixture_file.write_text(json.dumps(_capsule()) + "\n", encoding="utf-8")

    rc = main(["show", CAPSULE_ID, "--ledger", str(fixture_file)])
    assert rc == 0
    out = capsys.readouterr().out
    assert f"evidence_digest: {EVIDENCE_DIGEST}" in out
    assert "resolved evidence" not in out


# -- `capsule log` resolve-at-read -------------------------------------------


def test_log_auto_resolves_reason_when_a_matching_payload_is_stored(tmp_path, capsys):
    ledger_root = tmp_path / "ledger"
    _seed_ledger(ledger_root)
    main(["payload", "put", str(_write_payload_file(tmp_path, REASON)), "--ledger", str(ledger_root)])
    capsys.readouterr()

    rc = main(["log", "--ledger", str(ledger_root)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "resolved reason (from your local payload store" in out
    assert '"policy": "weekly-cap"' in out


# -- convention labels + assurance grade (items 2/3) -------------------------


def test_show_renders_registered_action_class_label(tmp_path, capsys):
    ledger_root = tmp_path / "ledger"
    _seed_ledger(ledger_root)
    rc = main(["show", CAPSULE_ID, "--ledger", str(ledger_root)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Action class: money.transfer — Money transfer" in out


def test_show_marks_unregistered_action_class_honestly(tmp_path, capsys):
    ledger_root = tmp_path / "ledger"
    store = LedgerStore(ledger_root)
    store.append(_capsule(action_class="hold.reserve"), consequential=False)
    store.close()

    rc = main(["show", CAPSULE_ID, "--ledger", str(ledger_root)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "hold.reserve (unregistered)" in out


def test_show_omits_action_class_line_when_capsule_carries_none(tmp_path, capsys):
    ledger_root = tmp_path / "ledger"
    store = LedgerStore(ledger_root)
    store.append(_capsule(action_class=None), consequential=False)
    store.close()

    rc = main(["show", CAPSULE_ID, "--ledger", str(ledger_root)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Action class:" not in out


def test_show_assurance_grade_self_attested_is_plain(tmp_path, capsys):
    ledger_root = tmp_path / "ledger"
    _seed_ledger(ledger_root)
    rc = main(["show", CAPSULE_ID, "--ledger", str(ledger_root)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Assurance:  self-attested · ledger: standalone" in out
    assert "[" not in out.split("Assurance:")[1].splitlines()[0]


def test_show_assurance_grade_anchored_is_badged(tmp_path, capsys):
    ledger_root = tmp_path / "ledger"
    store = LedgerStore(ledger_root)
    store.append(_capsule(assurance_mode="anchored"), consequential=False)
    store.close()

    rc = main(["show", CAPSULE_ID, "--ledger", str(ledger_root)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Assurance:  [anchored · ledger: standalone]" in out


def test_show_never_prints_paid_upsell_copy():
    """No fixture needed -- this asserts the module's own text, matching
    the neutrality-grep discipline this repo already runs in CI."""
    import capsule_ledger.cli.format as format_module

    source = format_module.__file__
    text = open(source, encoding="utf-8").read().lower()
    for banned in ("upgrade to", "enterprise", "contact sales", "pro tier"):
        assert banned not in text


# -- export never leaks resolved payload content -----------------------------


def test_bundle_export_stays_digest_only_even_with_a_matching_payload_store(tmp_path, capsys):
    ledger_root = tmp_path / "ledger"
    _seed_ledger(ledger_root)
    main(["payload", "put", str(_write_payload_file(tmp_path, EVIDENCE)), "--ledger", str(ledger_root)])
    capsys.readouterr()

    out_path = tmp_path / "bundle.json"
    # This test's hand-built capsule is not a fully spec-valid record (no
    # spec_version/format_version/real capsule_id digest), so `bundle`'s
    # own verification step legitimately reports a failure (rc=1) -- fine,
    # this test only cares whether the *payload store* leaked into the
    # written file, not whether this synthetic fixture verifies.
    main(["bundle", "--ledger", str(ledger_root), "--out", str(out_path)])
    assert out_path.is_file()

    bundle_text = out_path.read_text(encoding="utf-8")
    assert "over by 200000 minor units" not in bundle_text
    assert "1200000" not in bundle_text  # EVIDENCE's own distinctive value
    assert EVIDENCE_DIGEST in bundle_text  # the commitment itself is still there
