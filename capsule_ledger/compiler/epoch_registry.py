# SPDX-License-Identifier: Apache-2.0
"""Judge epochs as ``epoch_opens`` records (terms-to-report design §4 / §8
build item 3: "Epoch registry -- judge epochs as ``epoch_opens`` records:
pin set, opened-at, terms version, judge family (for the §2 independence
caveat).")

**Additive on an existing primitive, not a second epoch mechanism.**
``chain.relation == "epoch_opens"`` is already a registered chain-start
relation (``agent_action_capsule.history``'s registry -- see
``policy/activation.py``'s own docstring and ``cli/blame_cmd.py``/
``cli/diff_cmd.py``, which already treat it as "a legal chain-start, never
a gap"). A judge epoch is the same shape of fact as a policy-manifest
epoch -- "a new evaluative regime begins here, chained to the one it
supersedes" -- so this module reuses that relation rather than inventing a
parallel one. The two ``epoch_opens`` lineages (policy-manifest, judge) are
independent chains that happen to share a relation label, distinguished by
``asg_payload.event`` (``EVENT_EPOCH_OPEN`` here vs
``policy.activation.EVENT_MANIFEST_ACTIVATED``) -- exactly how
``policy/activation.py``'s own docstring anticipates "any future
epoch_opens producer."

**What a judge epoch's registry entry is for.** Design §4: "Open epoch B,
run J_i under model B over the same committed subject range, seal a second
satellite chain with epoch: B." The registry entry is what makes epoch B
identifiable and auditable *before* any verdict cites it: a declared
``pin_set`` (design §8: which judge/rule each term is pinned to for this
epoch -- so a later report can check a verdict's own ``judge_pin`` against
what the epoch actually declared, not merely trust it), the ``t_digest`` in
force when the epoch opened (design §3 [rev]: "the rule you're grading
against existed" -- extended one level, to the judging regime itself), and
the ``judge_family`` design §2/§4 need for the same-family caveat (`report`
computes it from the registry alone -- see ``same_family_epoch_pairs``).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from agent_action_capsule.canonical import json_digest
from agent_action_capsule.contracts import is_hex64

from ..guards.capsule import build_event_capsule
from ..guards.signing import Signer
from ..ledger.api import LedgerAPI, ScanQuery
from .compile import CompilerError
from .terms_desk import CompiledTerm

__all__ = [
    "EVENT_EPOCH_OPEN",
    "GENESIS_PARENT",
    "EpochPin",
    "EpochOpen",
    "pin_set_for_terms",
    "build_epoch_open_capsule",
    "epoch_open_from_record",
    "epoch_opens_from_records",
    "find_epoch_opens",
    "latest_epoch_open",
    "same_family_epoch_pairs",
    "all_pins_deterministic_rule",
    "verify_same_family_caveat_integrity",
]

EVENT_EPOCH_OPEN = "compiler.epoch_open"
# Same sentinel convention as policy/activation.py's own GENESIS_PARENT --
# a deliberately-never-real capsule_id so the first epoch in a ledger still
# has a legal chain-start parent to cite.
GENESIS_PARENT = "0" * 64


@dataclass(frozen=True)
class EpochPin:
    """One term's judging configuration as declared at epoch-open time --
    the "pin set" (design §8 item 3). Mirrors ``terms_desk.JudgeOrRuleSpec``'s
    own kind split: ``model_id``/``prompt_digest`` for a term pinned to a
    judge, ``rule_digest`` for a term pinned to a deterministic rule --
    never both, matching whichever the compiled term actually carries."""

    term_id: str
    model_id: str | None = None
    prompt_digest: str | None = None
    rule_digest: str | None = None

    def __post_init__(self) -> None:
        judge_fields_set = self.model_id is not None or self.prompt_digest is not None
        if judge_fields_set and self.rule_digest is not None:
            raise CompilerError(
                f"epoch pin for term {self.term_id!r} carries both judge fields and rule_digest -- "
                "exactly one of judge/rule must be set, mirroring JudgeOrRuleSpec's own kind split"
            )
        if not judge_fields_set and self.rule_digest is None:
            raise CompilerError(f"epoch pin for term {self.term_id!r} carries neither a judge pin nor a rule_digest")

    def canonical_dict(self) -> dict:
        out: dict = {"term_id": self.term_id}
        if self.model_id is not None:
            out["model_id"] = self.model_id
        if self.prompt_digest is not None:
            out["prompt_digest"] = self.prompt_digest
        if self.rule_digest is not None:
            out["rule_digest"] = self.rule_digest
        return out


def pin_set_for_terms(compiled_terms: Sequence[CompiledTerm]) -> tuple[EpochPin, ...]:
    """Derive the pin set straight from the compiled terms -- never a second,
    hand-typed description of what each term is pinned to (the P/F lesson,
    applied to pins: a pin re-described independently of the compiled
    ``JudgeOrRuleSpec`` could silently drift from what actually compiled).
    A REFUSED term (``judge_or_rule is None``) has nothing to pin and is
    skipped -- it already renders as a refusal row, not a judged line."""
    pins = []
    for ct in compiled_terms:
        if ct.judge_or_rule is None:
            continue
        if ct.judge_or_rule.kind == "judge":
            pins.append(
                EpochPin(
                    term_id=ct.term_id,
                    model_id=ct.judge_or_rule.model_id,
                    prompt_digest=ct.judge_or_rule.prompt_digest,
                )
            )
        else:
            pins.append(EpochPin(term_id=ct.term_id, rule_digest=ct.judge_or_rule.rule_digest))
    return tuple(sorted(pins, key=lambda p: p.term_id))


@dataclass(frozen=True)
class EpochOpen:
    """One ``epoch_opens`` registry entry (design §8 item 3): "pin set,
    opened-at, terms version, judge family." ``t_digest`` is the terms
    version (``TermsDocument.digest()``) in force when this epoch opened --
    the same temporal-binding discipline design §1 applies to terms,
    extended to the judging regime itself."""

    epoch_id: str
    opened_at: str
    t_digest: str
    judge_family: str
    pins: tuple[EpochPin, ...] = ()

    def __post_init__(self) -> None:
        if not self.epoch_id:
            raise CompilerError("epoch_id must be non-empty")
        if not is_hex64(self.t_digest):
            raise CompilerError(f"t_digest must be a 64-hex SHA-256 digest; got {self.t_digest!r}")
        if not self.judge_family:
            raise CompilerError(
                f"epoch {self.epoch_id!r} must declare a non-empty judge_family (design §2's "
                "independence caveat is computed from this field)"
            )

    def canonical_dict(self) -> dict:
        return {
            "epoch_id": self.epoch_id,
            "opened_at": self.opened_at,
            "t_digest": self.t_digest,
            "judge_family": self.judge_family,
            "pins": [p.canonical_dict() for p in sorted(self.pins, key=lambda p: p.term_id)],
        }

    def digest(self) -> str:
        return json_digest(self.canonical_dict())


def build_epoch_open_capsule(
    epoch: EpochOpen,
    *,
    operator: str,
    developer: str,
    signer: Signer,
    previous_epoch_open_capsule_id: str | None = None,
    timestamp: str | None = None,
    action_id: str | None = None,
) -> dict:
    """Seal one judge epoch's opening -- design §4: "Open epoch B
    (epoch_opens), run J_i under model B over the same committed subject
    range." Every field design §8 item 3 names lives in ``detail``, never
    inferred from the wrapping capsule -- an epoch's "opened at" moment is a
    fact about the judging regime, not about when this particular capsule
    happened to be sealed (the two coincide in the ordinary case, but a
    replayed/backfilled seal must never silently overwrite the true open
    time by reading the capsule's own ``timestamp`` instead)."""
    return build_event_capsule(
        operator=operator,
        developer=developer,
        signer=signer,
        event=EVENT_EPOCH_OPEN,
        detail=epoch.canonical_dict(),
        timestamp=timestamp,
        action_id=action_id or f"compiler.epoch_open/{epoch.epoch_id}",
        chain_parent=previous_epoch_open_capsule_id or GENESIS_PARENT,
        chain_relation="epoch_opens",
    )


def epoch_open_from_record(capsule: dict) -> EpochOpen | None:
    """Parse one sealed capsule dict back into an ``EpochOpen``, or ``None``
    if it isn't a judge-epoch-open record (the event-name check is what
    disambiguates this chain from any other ``epoch_opens``-relation
    lineage sharing the same chain vocabulary, e.g. a policy-manifest
    activation)."""
    payload = capsule.get("asg_payload") or {}
    if payload.get("event") != EVENT_EPOCH_OPEN:
        return None
    detail = payload.get("detail") or {}
    pins = tuple(
        EpochPin(
            term_id=p["term_id"],
            model_id=p.get("model_id"),
            prompt_digest=p.get("prompt_digest"),
            rule_digest=p.get("rule_digest"),
        )
        for p in detail.get("pins", [])
    )
    return EpochOpen(
        epoch_id=detail["epoch_id"],
        opened_at=detail["opened_at"],
        t_digest=detail["t_digest"],
        judge_family=detail["judge_family"],
        pins=pins,
    )


def epoch_opens_from_records(records: Sequence[dict]) -> tuple[EpochOpen, ...]:
    """Every judge-epoch-open in append order, read straight off a plain
    records slice -- the same "records: list[dict]" convention
    ``terms_desk.evaluate_term_fold`` already uses, so a report can be built
    from a slice of the ledger without a live ``LedgerAPI`` in hand."""
    out = []
    for record in records:
        parsed = epoch_open_from_record(record)
        if parsed is not None:
            out.append(parsed)
    return tuple(out)


def find_epoch_opens(ledger: LedgerAPI) -> tuple[EpochOpen, ...]:
    """The live-ledger counterpart of ``epoch_opens_from_records`` -- same
    scan-and-filter shape as ``policy.activation.find_latest_activation``."""
    matches = []
    for record in ledger.scan(ScanQuery(action_type="fyi")):
        parsed = epoch_open_from_record(record.capsule)
        if parsed is not None:
            matches.append(parsed)
    return tuple(matches)


def latest_epoch_open(ledger: LedgerAPI) -> EpochOpen | None:
    opens = find_epoch_opens(ledger)
    return opens[-1] if opens else None


def same_family_epoch_pairs(epoch_opens: Sequence[EpochOpen]) -> frozenset[frozenset[str]]:
    """design §4: "Inter-epoch disagreement between same-family epochs is
    correlated opinion, not independent check ... the report must not
    present it as the latter." Every unordered pair of distinct epoch ids
    that share a ``judge_family`` -- computable from the registry alone, no
    verdict rows needed, which is what lets the report render this caveat
    even for a term that hasn't been judged yet in the newer epoch."""
    pairs: set[frozenset[str]] = set()
    for i, a in enumerate(epoch_opens):
        for b in epoch_opens[i + 1 :]:
            if a.epoch_id != b.epoch_id and a.judge_family == b.judge_family:
                pairs.add(frozenset((a.epoch_id, b.epoch_id)))
    return frozenset(pairs)


def all_pins_deterministic_rule(pins: Sequence[EpochPin]) -> bool:
    """True iff every pin in ``pins`` is a deterministic-rule pin (``EpochPin
    .__post_init__`` already enforces that a pin carries exactly a rule pin
    XOR a judge pin, so "no ``model_id``" and "has ``rule_digest``" are the
    same fact). An epoch with an EMPTY pin set is not "all deterministic" --
    there is nothing to derive a family from, so callers should treat it as
    unknown provenance, not mechanically same-family with another empty-pin
    epoch."""
    return bool(pins) and all(p.model_id is None for p in pins)


def verify_same_family_caveat_integrity(epoch_opens: Sequence[EpochOpen]) -> None:
    """The oracle cross-check design §2's same-family caveat needs (adversarial
    review finding, [pack-harden-tau2-oracle] -- see ``adv-tau2-demo.md`` Area
    3): ``same_family_epoch_pairs`` trusts ``EpochOpen.judge_family`` as a
    free-typed string with nothing cross-checking it against what the epoch's
    OWN pin set proves. A coder could dodge the caveat by typing two
    different ``judge_family`` labels for two epochs that are, in fact,
    equally uninformative about model-provider independence.

    This closes the one slice of that gap that is mechanically, unambiguously
    derivable without a provider registry: every epoch that is ENTIRELY
    deterministic-rule (``all_pins_deterministic_rule`` -- zero live-model
    pins anywhere in it) cannot possibly have model-family independence from
    another such epoch, no matter what free-text label either declares
    (design §2's independence claim is specifically about model-provider
    diversity; an epoch with no live model call has none to be independent
    with). So every fully-deterministic-rule epoch in ``epoch_opens`` MUST
    declare the SAME ``judge_family`` as every other one -- if two disagree,
    that is either a labelling bug or a live-model call the pin set doesn't
    reflect, and this raises rather than let the caveat silently not fire for
    a pair that is, in truth, exactly as correlated as any other
    deterministic-rule pair.

    Deliberately does NOT attempt to derive/validate a family label for
    epochs that DO carry live-model pins -- cross-model-family diversity
    (e.g. "gpt-4-turbo" vs "gpt-4-mini" both being OpenAI) has no registry in
    this codebase to derive from, and inventing one is out of scope here;
    design's own worked example (a real model-provider string) is already
    harder to fudge than a hand-typed research label for a rule-based judge
    (see Area 3's severity note)."""
    deterministic = [e for e in epoch_opens if all_pins_deterministic_rule(e.pins)]
    families = {e.judge_family for e in deterministic}
    if len(families) > 1:
        raise CompilerError(
            f"epochs {[e.epoch_id for e in deterministic]} are all fully deterministic-rule (zero live-model "
            f"pins) but declare different judge_family labels {sorted(families)} -- two epochs with no live "
            "model call cannot have independent judge families; declaring different labels would silently "
            "suppress the same-family caveat design §2 requires. Use the identical judge_family string for "
            "every fully deterministic-rule epoch."
        )
