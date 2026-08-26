# SPDX-License-Identifier: Apache-2.0
"""``[ldg-t2r-tau2-demo]`` chunk 2 -- pack-through-desk: the airline
engagement pack's rows (``examples/airline_engagement_pack.py``, A1-A8),
run through the REAL pack-first desk flow (terms-to-report design §1
[rev3]: *pick a pack -> the census grades every row against the adopter's
actual corpus -> adopt / narrow / see the refusals*) against the REAL
demo-chunk-1 tau2-airline corpus fixture (record-grounding-bench,
``data/fixtures/tau2-airline-corpus-v1/``), then compiled and sealed via
the terms-desk compile profile (``compiler/terms_desk.py``).

**Every real decision is made by existing, unmodified machinery --
Amendment E, never a fork.** ``setup.propose.propose_from_ledger`` grades
each row; ``setup.confirm.confirm_accept``/``confirm_acknowledge_refusal``
seal T1/T4; ``compiler.terms_desk`` compiles and seals the multi-term
compilation record C. This module adds none of those primitives -- it
only supplies the airline pack's own candidate roster (sourced from
``build_airline_engagement_pack()``, never re-typed) and the desk-run
orchestration script + report renderer around them.

**The honest finding this run surfaces, not a bug (design's own
philosophy: "A1-class 44/200 results are the story, not a bug"): against
the REAL corpus fixture, every row except the pack's own refusal (A8)
census-grades to WITH-INSTRUMENTATION, not the numbers
``airline_engagement_pack.py`` reports against the offline vendored
dataset.** The fixture's conversation-turn capsules are sealed
digest-only by explicit design (``conversation/capsules.py``'s H2
invariant: "the turn's own content never enters the record in any mode"),
and its ``payloads/`` disclosure store (``payload_store.PayloadStore``)
was never populated for turn content by ``conv-recorder-tau2`` -- verified
directly: zero of the fixture's 959 distinct turn ``content_digest``
values resolve in its own 1057-entry payload store. No offer/response- or
attainment-shaped capsule exists in this corpus at all (it is a
conversation-turn + generic-observe recording, not a dispatch/offer
corpus), so every one of A1-A7's ``OfferResponseCandidate`` grades find
zero matching capsules and legitimately narrow to WITH-INSTRUMENTATION
via ``propose_from_ledger``'s own designed-for zero-coverage downgrade
(``allow_zero_coverage=True``) -- this is the SAME mechanism
``setup/propose.py`` already uses for a genuinely uninstrumented negative
case, not a special case invented here. A8 (subjective, REFUSED
regardless of any corpus) is the only row that adopts cleanly. This is
reported to Steven/EM as a real desk output, not silently smoothed over:
see the outbox report for the decision this surfaces (whether A1-A7
should be re-defined as attainment/decision-shaped claims a future
recorder revision COULD instrument, or whether disclosure needs to widen
to turn content for this pack to grade as intended).
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from ..compiler.terms_desk import (
    ApplicabilitySpec,
    CompiledTerm,
    TermDeclaration,
    TermsDocument,
    build_terms_compilation_record_capsule,
    compile_terms_document,
)
from ..guards import LocalSigner
from ..guards.signing import Signer
from ..ledger import LedgerStore
from ..setup.candidates import Candidate, OfferResponseCandidate, RefusedCandidate
from ..setup.confirm import confirm_accept, confirm_acknowledge_refusal
from ..setup.declarations import DeclarationStore, StoredCandidate
from ..setup.propose import ProposalSet, persist_proposals, propose_from_ledger
from .airline_engagement_pack import AirlineClaimResult, build_airline_engagement_pack

__all__ = [
    "OPERATOR",
    "DEVELOPER",
    "AIRLINE_PACK_CLAUSE_REFS",
    "DeskReportLine",
    "AirlinePackDeskResult",
    "airline_pack_candidates",
    "copied_corpus_ledger",
    "run_airline_pack_through_desk",
    "render_report",
    "main",
]

OPERATOR = "airline-pack-desk"
DEVELOPER = "airline-pack-desk@v1"

# clause_ref (design §1 [rev4] / §3 [rev4]): the provenance column --
# "which section of the sealed source document this term answers to". For
# a standard catalog pack (as opposed to a bespoke contract), the pack's
# own row id IS that citation -- the same mechanism a regulation-section
# reference would use for an obligations pack.
_PACK_NAME = "airline-engagement-pack"


def _clause_ref(claim_id: str) -> str:
    return f"{_PACK_NAME}/{claim_id}"


AIRLINE_PACK_CLAUSE_REFS: dict[str, str] = {}  # populated below, keyed by term_id


def _missing_instrument_label(row: AirlineClaimResult) -> str:
    """What a future recorder revision would need to instrument for THIS
    row to grade as more than WITH-INSTRUMENTATION against a real
    conversation-turn corpus -- named per row so the desk's narrow reason
    is specific, not a single generic label repeated eight times."""
    lexical = {"A1", "A3b", "A7"}
    tool_identity = {"A4", "A6"}
    if row.claim_id in lexical:
        return "disclosed_turn_content"  # needs turn text resolvable via PayloadStore
    if row.claim_id in tool_identity:
        return "disclosed_tool_identity"  # needs the specific tool_name, not just a digest
    # A2/A3a/A5: already named by the pack itself as needing typed, chained
    # capsules tau2-bench's free-text transcripts never emit (a restriction-
    # reason-cited record; a structured stated-constraint field) -- the
    # pack's own missing_instrument concept, carried through unchanged.
    return "typed_structured_capsule"


def airline_pack_candidates(pack_rows: tuple[AirlineClaimResult, ...] | None = None) -> tuple[Candidate, ...]:
    """The airline pack's A1-A8, as desk candidates -- ``term_id``/
    ``statement`` sourced from ``build_airline_engagement_pack()`` (never
    re-typed), one ``RefusedCandidate`` for A8 and one
    ``OfferResponseCandidate`` each for A1-A7. Every row is graded FRESH by
    ``propose_from_ledger`` against whatever corpus is handed to it --
    this function carries no verdict, no coverage number, from the
    original pack; only which row exists and what it is called."""
    if pack_rows is None:
        pack_rows = build_airline_engagement_pack().rows

    candidates: list[Candidate] = []
    for row in pack_rows:
        term_id = f"term.airline_pack.{row.claim_id.lower()}"
        AIRLINE_PACK_CLAUSE_REFS[term_id] = _clause_ref(row.claim_id)
        if row.is_refused:
            candidates.append(
                RefusedCandidate(
                    outcome_id=term_id,
                    statement=row.statement,
                    reason_code=row.refusal_reason_code or "subjective_state_unattestable",
                )
            )
            continue
        candidates.append(
            OfferResponseCandidate(
                outcome_id=term_id,
                statement=row.statement,
                offer_namespace=f"airline.{row.claim_id.lower()}",
                missing_instrument_label=_missing_instrument_label(row),
            )
        )
    return tuple(candidates)


@contextmanager
def copied_corpus_ledger(corpus_path: str | Path) -> Iterator[LedgerStore]:
    """Opens the real, committed tau2-airline corpus fixture READ-ONLY, by
    scanning a throwaway COPY -- ``LedgerStore.__init__`` opens its
    ``index.sqlite3`` in WAL mode and writes schema, which would create
    ``-wal``/``-shm`` files inside the fixture's own directory (a sibling
    repo's committed worktree) if opened in place. Copying first keeps the
    census grade genuinely read-only against the source."""
    tmp_root = Path(tempfile.mkdtemp(prefix="airline-pack-desk-corpus-"))
    try:
        corpus_copy = tmp_root / "corpus"
        shutil.copytree(Path(corpus_path), corpus_copy)
        store = LedgerStore(corpus_copy)
        try:
            yield store
        finally:
            store.close()
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


@dataclass(frozen=True)
class DeskReportLine:
    """One report row (design §3): ``clause_ref`` + ``c_digest`` walk the
    line back to the pack row and the sealed compilation record that
    produced it -- provenance, not just a number."""

    term_id: str
    clause_ref: str
    c_digest: str
    forward_verdict: str | None
    backward_verdict: str | None
    coverage_n: int | None
    coverage_m: int | None
    missing_instrument: str | None
    refusal_reason_code: str | None
    rationale: str

    @property
    def is_refused(self) -> bool:
        return "REFUSED" in (self.forward_verdict, self.backward_verdict)


@dataclass(frozen=True)
class AirlinePackDeskResult:
    proposal_set: ProposalSet
    terms_document: TermsDocument
    compiled_terms: tuple[CompiledTerm, ...]
    c_capsule: dict
    report_lines: tuple[DeskReportLine, ...]


def run_airline_pack_through_desk(
    corpus_path: str | Path,
    *,
    desk_ledger: LedgerStore,
    declarations_root: str | Path,
    signer: Signer | None = None,
    operator: str = OPERATOR,
    developer: str = DEVELOPER,
    acknowledged_by: str = "airline-pack-desk-script",
    pack_rows: tuple[AirlineClaimResult, ...] | None = None,
) -> AirlinePackDeskResult:
    """The pack-first desk flow, end to end, T1 SCRIPTED (design §1
    [rev3]): pick the airline pack -> census-grade every row against the
    real corpus fixture at ``corpus_path`` -> adopt (T1
    ``confirm_accept``, covers both a clean adopt and a narrowed
    WITH-INSTRUMENTATION accept -- there is no separate ledger verb for
    "narrow"; it is what an accepted non-DETERMINISTIC row already is) or
    acknowledge the refusal (T4 ``confirm_acknowledge_refusal``) -> compile
    the confirmed terms document and seal C.

    ``desk_ledger`` is the OPERATOR's own control-plane ledger (T1/T4/C
    seal onto it) -- deliberately NOT the subject corpus ledger, which
    stays exactly as committed; a daily judge's satellite capsules cite a
    subject by digest, never mutate the subject's own stream."""
    signer = signer or LocalSigner(key_id="airline-pack-desk", secret=b"airline-pack-desk-demo-key")
    candidates = airline_pack_candidates(pack_rows)
    decl_store = DeclarationStore(declarations_root)

    with copied_corpus_ledger(corpus_path) as corpus_ledger:
        proposal_set = propose_from_ledger(corpus_ledger, candidates=candidates, allow_zero_coverage=True)

    persist_proposals(proposal_set, decl_store)

    for proposal in proposal_set.proposals:
        if proposal.is_refused:
            confirm_acknowledge_refusal(
                proposal.outcome_id,
                store=decl_store,
                ledger=desk_ledger,
                signer=signer,
                operator=operator,
                developer=developer,
                acknowledged_by=acknowledged_by,
            )
        else:
            confirm_accept(
                proposal.outcome_id,
                store=decl_store,
                ledger=desk_ledger,
                signer=signer,
                operator=operator,
                developer=developer,
            )

    terms: list[TermDeclaration] = []
    stored_by_id: dict[str, StoredCandidate] = {}
    for proposal in proposal_set.proposals:
        stored = decl_store.load(proposal.outcome_id)
        stored_by_id[proposal.outcome_id] = stored
        terms.append(
            TermDeclaration(
                term_id=proposal.outcome_id,
                statement=proposal.statement,
                clause_ref=AIRLINE_PACK_CLAUSE_REFS.get(proposal.outcome_id),
                applicability=ApplicabilitySpec(unit="conversation"),
                verdict_schema=("pass", "fail"),
                stored=stored,
            )
        )

    terms_document = TermsDocument(terms=tuple(terms))
    compiled_terms = compile_terms_document(terms_document)

    c_capsule = build_terms_compilation_record_capsule(
        compiled_terms,
        t_digest=terms_document.digest(),
        operator=operator,
        developer=developer,
        signer=signer,
    )
    desk_ledger.append(c_capsule, consequential=False)
    c_digest = c_capsule["capsule_id"]

    report_lines = tuple(
        DeskReportLine(
            term_id=ct.term_id,
            clause_ref=ct.clause_ref or "",
            c_digest=c_digest,
            forward_verdict=stored_by_id[ct.term_id].forward_verdict,
            backward_verdict=stored_by_id[ct.term_id].backward_verdict,
            coverage_n=next(p.coverage_n for p in proposal_set.proposals if p.outcome_id == ct.term_id),
            coverage_m=next(p.coverage_m for p in proposal_set.proposals if p.outcome_id == ct.term_id),
            missing_instrument=stored_by_id[ct.term_id].missing_instrument,
            refusal_reason_code=ct.refusal_reason_code,
            rationale=next(p.rationale for p in proposal_set.proposals if p.outcome_id == ct.term_id),
        )
        for ct in compiled_terms
    )

    return AirlinePackDeskResult(
        proposal_set=proposal_set,
        terms_document=terms_document,
        compiled_terms=compiled_terms,
        c_capsule=c_capsule,
        report_lines=report_lines,
    )


def render_report(result: AirlinePackDeskResult) -> str:
    """Terminal-render, refusal rows preserved and rendered exactly as
    prominently as every other row (pack rule, design §3: "refusal rows
    render... because the refused row is what makes the passed rows
    credible") -- never dropped, never pushed to the bottom."""
    lines = [f"airline pack -- through the desk  (C: {result.c_capsule['capsule_id'][:16]}...)", ""]
    for line in result.report_lines:
        glyph = "✗" if line.is_refused else ("⚠" if line.missing_instrument else "✓")
        coverage = f"{line.coverage_n} of {line.coverage_m}" if line.coverage_n is not None else "n/a"
        lines.append(
            f"{glyph} {line.term_id}  clause_ref={line.clause_ref}  c_digest={line.c_digest[:16]}..."
        )
        lines.append(
            f"    forward={line.forward_verdict}  backward={line.backward_verdict}  coverage={coverage}"
        )
        if line.missing_instrument:
            lines.append(f"    missing_instrument label: {line.missing_instrument}")
        if line.refusal_reason_code:
            lines.append(f"    refusal_reason_code: {line.refusal_reason_code}")
        lines.append(f"    {line.rationale}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus", required=True, help="path to the tau2-airline-corpus-v1 fixture directory"
    )
    parser.add_argument(
        "--desk-root", required=True, help="output directory for the desk's own ledger + declarations"
    )
    args = parser.parse_args(argv)

    desk_root = Path(args.desk_root)
    desk_root.mkdir(parents=True, exist_ok=True)
    desk_ledger = LedgerStore(desk_root / "desk-ledger")
    try:
        result = run_airline_pack_through_desk(
            args.corpus,
            desk_ledger=desk_ledger,
            declarations_root=desk_root / "declarations",
        )
    finally:
        desk_ledger.close()
    print(render_report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
