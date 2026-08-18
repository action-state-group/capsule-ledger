# SPDX-License-Identifier: Apache-2.0
"""Deterministic two-agent capsule simulation: demo AND fixture generator.

Run as ``python -m capsule_ledger.examples.two_agents``.

Two scripted agents ("checkout-agent-alpha@v1" and "checkout-agent-beta@v1"),
each with its own capsule-emit call surface and its own guard-decision
signing key, act against **one** ledger. In a single run this exercises:

1. **Overlapping spend against a shared cap** -- both agents draw against a
   shared treasury identity (``checkout-shared-treasury@v1``); the guard's
   ``caps`` check pools spend per ``developer`` (``guards/checks/caps.py``),
   so the shared identity is what makes the second agent's spend genuinely
   overlap with the first's, in the same weekly window. Alpha's transfer
   fits under the cap and is allowed; Beta's, right after, pushes the
   pooled total over it -- ``money.transfer`` has an ``approver_role``
   configured (``guards/classes.py``), so per D2 the guard **escalates**
   (``hitl_dispatched``) rather than hard-denying (``guards/engine.py``'s
   ``_decide``).
2. **A dedupe collision** -- Alpha submits the same logical action
   (operator + developer + action_type + verb + target) twice; the second
   submission's equivalence key matches the first's, so ``check_dedupe``
   fails and the guard hard-denies, chaining the denial capsule back to the
   original via ``chain.parent_capsule_id`` (``guards/checks/dedupe.py``
   sets that chain automatically on a match).
3. **A refusal** -- Beta requests a ``data.delete`` citing a
   ``cited_mandate_capsule_id`` that was never recorded. ``data.delete`` has
   no ``approver_role`` configured, and a missing/failed mandate is an
   integrity failure regardless -- ``verify_before_dispatch`` fails and the
   guard hard-denies unconditionally (D2's "classes explicitly marked
   deny" half, and the integrity-failure row of the same table).
4. **A declared-intent -> action chain** -- Alpha first emits a plain,
   non-gated ``intent.declare`` capsule *through capsule-emit itself*
   (``capsule_emit.emit()``), then submits the actual fulfilling action
   through the guard, explicitly chained to the intent capsule's
   ``capsule_id`` via ``chain_parent``/``chain_relation="confirms"``
   (the same "did -> confirmed" relation capsule-emit's own ``confirms``
   parameter threads).

**Why both capsule-emit and the guard engine.** ``GuardEngine.check()``
builds and signs its own decision capsule -- that capsule asserts a *gate*
decision, not that anything downstream executed
(``guards/capsule.py``'s module docstring). The intent-declare capsule is a
passive, non-gated observation with no decision to gate, so it goes through
capsule-emit's own one-call ``emit()`` instead, and its returned capsule
dict is appended into the *same* ``LedgerAPI`` -- one ledger either way,
just two different callers producing capsules against it, matching how a
real deployment would split "an agent observes/declares something" from
"an agent's consequential action gets gated."

**Determinism.** Every ``Action`` gets an explicit ``action_id`` and
``timestamp`` (both otherwise default to wall-clock/``uuid4()``, see
``guards/action.py``). capsule-emit's own ``emit()`` has no such override --
it always calls the base ``agent_action_capsule.emit()`` with
``action_id=None`` and no ``timestamp``, so both get generated from
wall-clock time and ``uuid.uuid4()`` deep inside that library
(``agent_action_capsule/emit.py``). ``_pinned_capsule_emit_clock`` pins that
module's clock/uuid source for the one call that needs it -- the only way,
given capsule-emit's current public API, to get byte-identical output
across runs. Every other source of non-determinism (the two agents'
signing keys, the intent capsule's synthetic id) is derived from ``--seed``,
so the same seed reproduces the exact same ledger byte-for-byte, and a
different seed reproduces a genuinely different one.

**Purpose.** This is the repeatable demo/fixture: scripted, seeded, always
the same. It is not a substitute for a live deployment. Don't make this one "more realistic" by
adding non-determinism; that would break its actual job.

**Backend.** ``--backend local`` (default) opens an ephemeral
``LedgerStore``. ``--backend remote`` (or ``$CAPSULE_LEDGER_SIM_BACKEND``)
points the exact same scenario code at a hosted remote ledger tenant over
HTTP (``remote_ledger.RemoteLedgerAPI``) via ``--base-url``/``--api-key`` --
config, not code.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import os
import shutil
import sys
import tempfile
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import capsule_emit

from capsule_ledger.folds.loader import load_definition_file
from capsule_ledger.guards import ALLOW, DENY, ESCALATE, Action, GuardEngine, LocalSigner
from capsule_ledger.ledger import LedgerAPI, LedgerRecord, LedgerStore

from .remote_ledger import RemoteLedgerAPI

__all__ = ["SimulationResult", "run_simulation", "main"]

# `agent_action_capsule/__init__.py` does `from .emit import emit`, which
# rebinds the package attribute `agent_action_capsule.emit` to that
# function -- shadowing the submodule of the same name. `import
# agent_action_capsule.emit as X` would silently bind X to the function
# (an attribute lookup, not a sys.modules lookup), not the module we need
# to patch below. `importlib.import_module` always returns the real
# submodule regardless of that shadowing.
_aac_emit_module = importlib.import_module("agent_action_capsule.emit")

CATALOG_DIR = Path(__file__).resolve().parent.parent / "folds" / "catalog_defs"
DEFAULT_FIXTURE_PATH = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "two_agents_sim_ledger.jsonl"

DEFAULT_SEED = 20260807
BASE_TIMESTAMP = "2026-08-07T09:00:00Z"
CLOCK_STEP_SECONDS = 17

OPERATOR = "acme-checkout"
ALPHA_DEVELOPER = "checkout-agent-alpha@v1"
BETA_DEVELOPER = "checkout-agent-beta@v1"
# Shared budget identity: the caps check pools spend per `developer`
# (guards/checks/caps.py), so this is what makes Alpha's and Beta's spends
# genuinely overlap in one weekly window rather than being tracked in two
# separate per-agent buckets.
TREASURY_DEVELOPER = "checkout-shared-treasury@v1"

MONEY_TRANSFER_CAP_MINOR = 10_000_00  # EUR 10,000.00, shared weekly cap


class _DeterministicClock:
    """A fixed, non-wall-clock timestamp source -- every capsule in the run
    gets an explicit, advancing timestamp instead of ``datetime.now()``."""

    def __init__(self, start: str, step_seconds: int) -> None:
        self._current = datetime.fromisoformat(start.replace("Z", "+00:00"))
        self._step = timedelta(seconds=step_seconds)

    def next(self) -> str:
        ts = self._current
        self._current += self._step
        return ts.isoformat().replace("+00:00", "Z")


def _seeded_secret(seed: int, label: str) -> bytes:
    return hashlib.sha256(f"two-agents-demo-sim/{seed}/{label}".encode()).digest()


def _seeded_uuid(seed: int, label: str) -> uuid.UUID:
    digest = hashlib.sha256(f"two-agents-demo-sim/{seed}/{label}".encode()).digest()
    return uuid.UUID(bytes=digest[:16])


@contextmanager
def _pinned_capsule_emit_clock(timestamp: str, fixed_uuid: uuid.UUID) -> Iterator[None]:
    """Pin the clock/uuid source ``agent_action_capsule.emit()`` reads for the
    duration of one ``capsule_emit.emit()`` call. See the module docstring's
    "Determinism" section for why this is necessary rather than a style
    choice."""
    real_utc_now = _aac_emit_module._utc_now
    real_uuid4 = uuid.uuid4
    _aac_emit_module._utc_now = lambda: timestamp
    uuid.uuid4 = lambda: fixed_uuid
    try:
        yield
    finally:
        _aac_emit_module._utc_now = real_utc_now
        uuid.uuid4 = real_uuid4


@dataclass(frozen=True)
class SimulationResult:
    """Everything a caller (the CLI, or a test) needs, without re-parsing
    the exported fixture: every record in append order, plus each
    scenario's capsule_id and outcome keyed by a stable scenario name."""

    records: tuple[LedgerRecord, ...]
    capsule_ids: dict[str, str]
    outcomes: dict[str, str]


def _require_outcome(decision, expected: str, scenario: str) -> None:
    if decision.outcome != expected:
        raise RuntimeError(
            f"two-agents demo sim: scenario {scenario!r} expected outcome {expected!r}, "
            f"got {decision.outcome!r} ({decision.reason})"
        )


def _run_scenarios(ledger: LedgerAPI, *, seed: int) -> SimulationResult:
    clock = _DeterministicClock(BASE_TIMESTAMP, CLOCK_STEP_SECONDS)
    caps_fold = load_definition_file(CATALOG_DIR / "spend.weekly.yaml")

    signer_alpha = LocalSigner(key_id="checkout-agent-alpha-guard-key", secret=_seeded_secret(seed, "alpha"))
    signer_beta = LocalSigner(key_id="checkout-agent-beta-guard-key", secret=_seeded_secret(seed, "beta"))

    engine_alpha = GuardEngine(
        ledger=ledger,
        caps_fold=caps_fold,
        signer_provider=lambda: signer_alpha,
        caps_minor={"money.transfer": MONEY_TRANSFER_CAP_MINOR},
    )
    engine_beta = GuardEngine(
        ledger=ledger,
        caps_fold=caps_fold,
        signer_provider=lambda: signer_beta,
        caps_minor={"money.transfer": MONEY_TRANSFER_CAP_MINOR},
    )

    capsule_ids: dict[str, str] = {}
    outcomes: dict[str, str] = {}

    # -- Scenario 1: overlapping spend against a shared cap (D2 escalation) --
    spend_1 = Action(
        verb="transfer_funds",
        operator=OPERATOR,
        developer=TREASURY_DEVELOPER,
        action_class="money.transfer",
        amount_minor=6_500_00,
        currency="EUR",
        target="vendor-forge-supplies/invoice-1001",
        action_id="transfer_funds/sim-alpha-spend-1",
        timestamp=clock.next(),
    )
    decision_spend_1 = engine_alpha.check(spend_1)
    _require_outcome(decision_spend_1, ALLOW, "overlap_spend_alpha")
    capsule_ids["overlap_spend_alpha"] = decision_spend_1.capsule["capsule_id"]
    outcomes["overlap_spend_alpha"] = decision_spend_1.outcome

    spend_2 = Action(
        verb="transfer_funds",
        operator=OPERATOR,
        developer=TREASURY_DEVELOPER,
        action_class="money.transfer",
        amount_minor=6_000_00,
        currency="EUR",
        target="vendor-forge-supplies/invoice-1002",
        action_id="transfer_funds/sim-beta-spend-1",
        timestamp=clock.next(),
    )
    decision_spend_2 = engine_beta.check(spend_2)
    _require_outcome(decision_spend_2, ESCALATE, "overlap_spend_beta_escalated")
    capsule_ids["overlap_spend_beta_escalated"] = decision_spend_2.capsule["capsule_id"]
    outcomes["overlap_spend_beta_escalated"] = decision_spend_2.outcome

    # -- Scenario 2: dedupe collision --
    dup_1 = Action(
        verb="send_compliance_report",
        operator=OPERATOR,
        developer=ALPHA_DEVELOPER,
        action_class="comms.external",
        target="compliance@partner.example",
        action_id="send_compliance_report/sim-alpha-dup-1",
        timestamp=clock.next(),
    )
    decision_dup_1 = engine_alpha.check(dup_1)
    _require_outcome(decision_dup_1, ALLOW, "dedupe_original")
    capsule_ids["dedupe_original"] = decision_dup_1.capsule["capsule_id"]
    outcomes["dedupe_original"] = decision_dup_1.outcome

    dup_2 = Action(
        verb="send_compliance_report",
        operator=OPERATOR,
        developer=ALPHA_DEVELOPER,
        action_class="comms.external",
        target="compliance@partner.example",
        action_id="send_compliance_report/sim-alpha-dup-2",
        timestamp=clock.next(),
    )
    decision_dup_2 = engine_alpha.check(dup_2)
    _require_outcome(decision_dup_2, DENY, "dedupe_collision")
    capsule_ids["dedupe_collision"] = decision_dup_2.capsule["capsule_id"]
    outcomes["dedupe_collision"] = decision_dup_2.outcome

    # -- Scenario 3: refusal (cited mandate was never recorded -> hard deny) --
    refusal = Action(
        verb="delete_customer_record",
        operator=OPERATOR,
        developer=BETA_DEVELOPER,
        action_class="data.delete",
        target="customer-48213",
        cited_mandate_capsule_id="f" * 64,
        action_id="delete_customer_record/sim-beta-refusal-1",
        timestamp=clock.next(),
    )
    decision_refusal = engine_beta.check(refusal)
    _require_outcome(decision_refusal, DENY, "refusal")
    capsule_ids["refusal"] = decision_refusal.capsule["capsule_id"]
    outcomes["refusal"] = decision_refusal.outcome

    # -- Scenario 4: declared-intent -> action chain --
    intent_ts = clock.next()
    with _pinned_capsule_emit_clock(intent_ts, _seeded_uuid(seed, "intent-declare-alpha")):
        intent_result = capsule_emit.emit(
            action="intent.declare",
            operator=OPERATOR,
            developer=ALPHA_DEVELOPER,
            agent_input={
                "intent": "renew annual vendor contract with Forge Supplies",
                "planned_amount_minor": 2_500_00,
                "planned_currency": "EUR",
            },
            model={"provider": "anthropic", "model_id": "claude-sonnet-4-6"},
            verdict="confirmed",
            effect={"type": "intent.declare", "status": "planned"},
            decision="accept",
            action_type="fyi",
            anchor=False,  # no network I/O in a deterministic fixture generator
            ledger=os.devnull,  # capsule-emit always writes a side JSONL; the real one is `ledger`
        )
    intent_capsule = intent_result.capsule
    ledger.append(intent_capsule, consequential=False)
    capsule_ids["intent_declare"] = intent_capsule["capsule_id"]
    outcomes["intent_declare"] = "declared"

    fulfill = Action(
        verb="renew_vendor_contract",
        operator=OPERATOR,
        developer=ALPHA_DEVELOPER,
        action_class="money.transfer",
        amount_minor=2_500_00,
        currency="EUR",
        target="vendor-forge-supplies-contract-renewal",
        action_id="renew_vendor_contract/sim-alpha-fulfill-1",
        timestamp=clock.next(),
    )
    decision_fulfill = engine_alpha.check(fulfill, chain_parent=intent_capsule["capsule_id"], chain_relation="confirms")
    _require_outcome(decision_fulfill, ALLOW, "intent_fulfill")
    capsule_ids["intent_fulfill"] = decision_fulfill.capsule["capsule_id"]
    outcomes["intent_fulfill"] = decision_fulfill.outcome

    records = tuple(ledger.scan())
    return SimulationResult(records=records, capsule_ids=capsule_ids, outcomes=outcomes)


def _open_backend(
    *,
    backend: str,
    local_store_dir: str | os.PathLike | None,
    base_url: str | None,
    api_key: str | None,
) -> tuple[LedgerAPI, Callable[[], None]]:
    if backend == "local":
        cleanup_dir: Path | None = None
        if local_store_dir is None:
            local_store_dir = tempfile.mkdtemp(prefix="capsule-ledger-two-agents-sim-")
            cleanup_dir = Path(local_store_dir)
        store = LedgerStore(local_store_dir)

        def _close() -> None:
            store.close()
            if cleanup_dir is not None:
                shutil.rmtree(cleanup_dir, ignore_errors=True)

        return store, _close

    if backend == "remote":
        if not base_url or not api_key:
            raise RuntimeError(
                "backend='remote' requires a base URL and API key -- pass --base-url/--api-key "
                "or set $CAPSULE_LEDGER_SIM_BASE_URL / $CAPSULE_LEDGER_SIM_API_KEY"
            )
        return RemoteLedgerAPI(base_url, api_key), lambda: None

    raise NotImplementedError(f"backend={backend!r} is not implemented -- only 'local' and 'remote' are wired up.")


def run_simulation(
    *,
    backend: str = "local",
    local_store_dir: str | os.PathLike | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    seed: int = DEFAULT_SEED,
    fixture_out: str | os.PathLike | None = None,
) -> SimulationResult:
    """Run the full four-scenario simulation once and return the result.

    Every capsule is scanned back off ``ledger`` (not accumulated by hand)
    before the backend is closed, so the returned ``records`` are exactly
    what a fresh reader of that ledger would see -- and if ``fixture_out``
    is given, exactly what gets exported.
    """
    ledger, close = _open_backend(backend=backend, local_store_dir=local_store_dir, base_url=base_url, api_key=api_key)
    try:
        result = _run_scenarios(ledger, seed=seed)
    finally:
        close()

    if fixture_out is not None:
        _export_fixture(result.records, Path(fixture_out))

    return result


def _export_fixture(records: tuple[LedgerRecord, ...], path: Path) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record.capsule, separators=(",", ":")) + "\n")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m capsule_ledger.examples.two_agents",
        description="Deterministic two-agent capsule simulation (see module docstring for the four scenarios).",
    )
    parser.add_argument(
        "--backend",
        choices=["local", "remote"],
        default=os.environ.get("CAPSULE_LEDGER_SIM_BACKEND", "local"),
        help="Ledger backend: 'local' (ephemeral LedgerStore, default) or 'remote' (a hosted "
        "remote ledger tenant). $CAPSULE_LEDGER_SIM_BACKEND.",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("CAPSULE_LEDGER_SIM_BASE_URL"),
        help="remote ledger tenant base URL; required for --backend remote. $CAPSULE_LEDGER_SIM_BASE_URL.",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("CAPSULE_LEDGER_SIM_API_KEY"),
        help="remote ledger tenant API key (sent as X-API-Key); required for --backend remote. "
        "$CAPSULE_LEDGER_SIM_API_KEY.",
    )
    parser.add_argument(
        "--local-store-dir",
        default=os.environ.get("CAPSULE_LEDGER_SIM_STORE_DIR"),
        help="Directory for the local LedgerStore. Default: a fresh temp dir, removed after the run.",
    )
    parser.add_argument(
        "--out",
        default=os.environ.get("CAPSULE_LEDGER_SIM_OUT", str(DEFAULT_FIXTURE_PATH)),
        help=f"Path to write the flat JSONL fixture ledger. Default: {DEFAULT_FIXTURE_PATH}. Pass '' to skip writing.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=int(os.environ.get("CAPSULE_LEDGER_SIM_SEED", DEFAULT_SEED)),
        help="Deterministic seed for the two agents' signing keys and the intent capsule's synthetic "
        "id -- same seed reproduces byte-identical output; a different seed reproduces a genuinely "
        "different ledger.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    fixture_out = args.out if args.out else None
    result = run_simulation(
        backend=args.backend,
        local_store_dir=args.local_store_dir,
        base_url=args.base_url,
        api_key=args.api_key,
        seed=args.seed,
        fixture_out=fixture_out,
    )
    print(f"two-agents demo sim: {len(result.records)} capsule(s) recorded, seed={args.seed}, backend={args.backend}")
    for name, outcome in result.outcomes.items():
        print(f"  {name:<28} {outcome:<10} {result.capsule_ids[name][:16]}…")
    if fixture_out:
        print(f"fixture written to {fixture_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
