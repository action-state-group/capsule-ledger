# SPDX-License-Identifier: Apache-2.0
import pytest

from capsule_ledger.setup.candidates import AttainmentCandidate, RefusedCandidate
from capsule_ledger.setup.declarations import (
    DeclarationCorrupt,
    DeclarationNotFound,
    DeclarationStore,
    candidate_digest,
)


def test_save_and_load_round_trips_the_candidate(tmp_path):
    store = DeclarationStore(tmp_path)
    c = AttainmentCandidate(outcome_id="outcome.x", statement="x happened", action_class="verb_x")
    store.save(c, acceptance_state="proposed", forward_verdict="DETERMINISTIC", backward_verdict="DETERMINISTIC")

    stored = store.load("outcome.x")
    assert stored.candidate == c
    assert stored.acceptance_state == "proposed"
    assert stored.forward_verdict == "DETERMINISTIC"
    assert stored.d_digest == candidate_digest(c)


def test_load_missing_outcome_raises():
    store = DeclarationStore("/tmp/does-not-matter")
    with pytest.raises(DeclarationNotFound):
        store.load("outcome.nope")


def test_set_acceptance_state_preserves_verdict_fields(tmp_path):
    store = DeclarationStore(tmp_path)
    c = RefusedCandidate(outcome_id="outcome.r", statement="r", reason_code="unbounded_goal_unmonitorable")
    store.save(c, acceptance_state="proposed", forward_verdict="REFUSED", backward_verdict="REFUSED", refusal_reason_code="unbounded_goal_unmonitorable")

    updated = store.set_acceptance_state("outcome.r", "refused")
    assert updated.acceptance_state == "refused"
    assert updated.forward_verdict == "REFUSED"
    assert updated.refusal_reason_code == "unbounded_goal_unmonitorable"


def test_save_rejects_unknown_acceptance_state(tmp_path):
    store = DeclarationStore(tmp_path)
    c = AttainmentCandidate(outcome_id="outcome.x", statement="x", action_class="v")
    with pytest.raises(ValueError):
        store.save(c, acceptance_state="bogus")


def test_list_ids_and_exists(tmp_path):
    store = DeclarationStore(tmp_path)
    assert store.list_ids() == []
    assert not store.exists("outcome.x")
    store.save(AttainmentCandidate(outcome_id="outcome.x", statement="x", action_class="v"))
    assert store.list_ids() == ["outcome.x"]
    assert store.exists("outcome.x")


def test_candidate_digest_is_stable_across_save_load(tmp_path):
    store = DeclarationStore(tmp_path)
    c = AttainmentCandidate(outcome_id="outcome.x", statement="x happened", action_class="verb_x")
    d1 = candidate_digest(c)
    store.save(c)
    stored = store.load("outcome.x")
    assert candidate_digest(stored.candidate) == d1


def test_load_raises_declaration_corrupt_on_invalid_json(tmp_path):
    """A directory we own must fail loudly on garbage, by name, rather
    than a bare ``json.JSONDecodeError`` traceback the caller has to
    recognize as "one of my files is broken" on its own."""
    store = DeclarationStore(tmp_path)
    store.directory.mkdir(parents=True, exist_ok=True)
    bad_path = store.directory / "outcome.garbage.json"
    bad_path.write_text("THIS IS NOT JSON {{{")

    with pytest.raises(DeclarationCorrupt) as exc_info:
        store.load("outcome.garbage")
    assert exc_info.value.path == bad_path
    assert "not valid JSON" in exc_info.value.reason


def test_load_raises_declaration_corrupt_on_missing_required_keys(tmp_path):
    """Valid JSON that isn't shaped like a stored candidate (a hand-typed
    file that skipped ``acceptance_state``/``declaration``) must be named
    as broken too, not crash on a ``KeyError`` deep inside candidate
    reconstruction."""
    store = DeclarationStore(tmp_path)
    store.directory.mkdir(parents=True, exist_ok=True)
    bad_path = store.directory / "outcome.half_written.json"
    bad_path.write_text('{"outcome_id": "outcome.half_written", "statement": "not the real shape"}')

    with pytest.raises(DeclarationCorrupt) as exc_info:
        store.load("outcome.half_written")
    assert exc_info.value.path == bad_path


def test_load_raises_declaration_corrupt_on_unknown_candidate_kind(tmp_path):
    """A ``declaration.kind`` outside the closed set must name the file
    and fail loudly rather than raising an undecorated ``KeyError`` from
    the internal kind->class lookup table."""
    store = DeclarationStore(tmp_path)
    store.directory.mkdir(parents=True, exist_ok=True)
    bad_path = store.directory / "outcome.bad_kind.json"
    bad_path.write_text(
        '{"acceptance_state": "proposed", "d_digest": "x", '
        '"declaration": {"kind": "not_a_real_kind", "outcome_id": "outcome.bad_kind", "statement": "s"}, '
        '"forward_verdict": null, "backward_verdict": null, "refusal_reason_code": null, "missing_instrument": null}'
    )

    with pytest.raises(DeclarationCorrupt) as exc_info:
        store.load("outcome.bad_kind")
    assert exc_info.value.path == bad_path


def test_a_hand_written_declaration_matching_the_written_shape_is_not_ignored(tmp_path):
    """The declarations directory is a real input, not write-only output:
    a file placed there by hand -- not by ``propose`` -- must be picked
    up by ``list_ids``/``load`` exactly like one ``propose`` wrote."""
    store = DeclarationStore(tmp_path)
    c = AttainmentCandidate(outcome_id="outcome.hand_written", statement="hand-authored", action_class="v")
    # Write it the same way `save()` would, but never call `save()` itself
    # -- this stands in for a human copying the on-disk shape by hand.
    store.directory.mkdir(parents=True, exist_ok=True)
    import json

    (store.directory / "outcome.hand_written.json").write_text(
        json.dumps(
            {
                "acceptance_state": "proposed",
                "d_digest": candidate_digest(c),
                "declaration": {"kind": "attainment", "outcome_id": c.outcome_id, "statement": c.statement, "params": {"action_class": "v"}},
                "forward_verdict": "DETERMINISTIC",
                "backward_verdict": "DETERMINISTIC",
                "refusal_reason_code": None,
                "missing_instrument": None,
            }
        )
    )
    assert "outcome.hand_written" in store.list_ids()
    assert store.load("outcome.hand_written").candidate == c


def test_outcome_id_with_slash_does_not_collide_with_underscore_form(tmp_path):
    """A naive ``outcome_id.replace('/', '__')`` filename scheme collides
    ``"a/b"`` with a literal ``"a__b"`` -- both would map to the same file.
    The store must keep them as two distinct, independently loadable
    entries."""
    store = DeclarationStore(tmp_path)
    store.save(AttainmentCandidate(outcome_id="a/b", statement="s1", action_class="v1"))
    store.save(AttainmentCandidate(outcome_id="a__b", statement="s2", action_class="v2"))
    assert sorted(store.list_ids()) == ["a/b", "a__b"]
    assert store.load("a/b").candidate.statement == "s1"
    assert store.load("a__b").candidate.statement == "s2"
