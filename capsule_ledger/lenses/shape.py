# SPDX-License-Identifier: Apache-2.0
"""Shape lens: two structural sequence-pattern detectors over the ledger
query API, each run independently per agent (``developer``), in ledger
append order:

  - retry storm -- a maximal run of consecutive, same-verb records for one
                   agent whose timestamps span no more than a duration
                   threshold (pure repetition, no verb variation)
  - cycle       -- a maximal run of records for one agent that strictly
                   alternates between exactly two verbs (A -> B -> A -> B
                   -> ...), at least ``min_length`` records long

Both are counting/windowing/pattern-matching over already-recorded verbs
and timestamps -- never an inference about *why* an agent repeated or
alternated actions.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..folds.duration import parse_duration_seconds
from ..ledger.records import LedgerRecord
from ._common import parse_timestamp, record_verb

__all__ = ["RetryStorm", "Cycle", "find_retry_storms", "find_cycles"]


@dataclass(frozen=True)
class RetryStorm:
    """A run of >= ``min_repeats`` consecutive same-verb records for one agent."""

    developer: str
    verb: str
    records: tuple[LedgerRecord, ...]
    span_seconds: float | None


@dataclass(frozen=True)
class Cycle:
    """A run of >= ``min_length`` records for one agent strictly alternating
    between exactly two verbs (A -> B -> A -> B -> ...)."""

    developer: str
    verbs: tuple[str, str]
    records: tuple[LedgerRecord, ...]


def _by_developer(records: list[LedgerRecord]) -> dict[str, list[LedgerRecord]]:
    grouped: dict[str, list[LedgerRecord]] = {}
    for r in records:
        grouped.setdefault(r.capsule.get("developer") or "", []).append(r)
    return grouped


def _consecutive_verb_runs(devrecords: list[LedgerRecord]) -> list[tuple[str, list[LedgerRecord]]]:
    """Collapse *devrecords* into (verb, run) pairs of consecutive same-verb records."""
    runs: list[tuple[str, list[LedgerRecord]]] = []
    current_verb: str | None = None
    current_run: list[LedgerRecord] = []
    for r in devrecords:
        verb = record_verb(r.capsule)
        if verb == current_verb:
            current_run.append(r)
        else:
            if current_run:
                runs.append((current_verb, current_run))
            current_verb = verb
            current_run = [r]
    if current_run:
        runs.append((current_verb, current_run))
    return runs


def find_retry_storms(
    records: list[LedgerRecord], *, min_repeats: int = 3, window: str = "60s"
) -> list[RetryStorm]:
    """Flag maximal same-verb runs (per agent) of at least ``min_repeats``
    records whose first-to-last timestamp span is within ``window``
    (a duration string, e.g. "60s", "5m" -- see ``folds/duration.py``)."""
    window_seconds = parse_duration_seconds(window)
    storms: list[RetryStorm] = []

    for developer, devrecords in _by_developer(records).items():
        for verb, run in _consecutive_verb_runs(devrecords):
            if len(run) < min_repeats:
                continue
            t0 = parse_timestamp(run[0].capsule.get("timestamp"))
            t1 = parse_timestamp(run[-1].capsule.get("timestamp"))
            span = (t1 - t0).total_seconds() if t0 is not None and t1 is not None else None
            if span is not None and span > window_seconds:
                continue
            storms.append(RetryStorm(developer=developer, verb=verb, records=tuple(run), span_seconds=span))

    return storms


def find_cycles(records: list[LedgerRecord], *, min_length: int = 4) -> list[Cycle]:
    """Flag maximal runs (per agent) of >= ``min_length`` records that
    strictly alternate between exactly two verbs."""
    cycles: list[Cycle] = []

    for developer, devrecords in _by_developer(records).items():
        verbs = [record_verb(r.capsule) for r in devrecords]
        n = len(devrecords)
        i = 0
        while i < n:
            j = i + 1
            while j < n and verbs[j] != verbs[j - 1] and ((j - i) < 2 or verbs[j] == verbs[j - 2]):
                j += 1
            length = j - i
            if length >= min_length:
                cycles.append(
                    Cycle(
                        developer=developer,
                        verbs=(verbs[i], verbs[i + 1]),
                        records=tuple(devrecords[i:j]),
                    )
                )
                i = j
            else:
                i += 1

    return cycles
