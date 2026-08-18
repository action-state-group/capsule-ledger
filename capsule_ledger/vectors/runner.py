# SPDX-License-Identifier: Apache-2.0
"""Fixture-driven vector discovery for the fold engine (spec §6, shipping gate).

Each vector class is a directory of pinned files under ``fixtures/``:

- ``kat/<name>/``: definition.yaml, records.jsonl, expected.json
  (``{key_value: expected_result}``) — per-reducer known-answer tests.
- ``determinism/<name>/``: definition.yaml, base.jsonl, mutant.jsonl,
  expected.json — the mutant (permuted/injected-unknown fields) MUST produce
  the same result as the base stream.
- ``must_fail/<name>/``: definition.yaml, reason.txt, and optionally
  records.jsonl + key.txt — evaluating (or even just loading) the definition
  MUST raise with the named reason.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def read_jsonl(path: Path) -> list[dict]:
    records = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def _subdirs(base: Path) -> list[Path]:
    if not base.is_dir():
        return []
    return sorted(p for p in base.iterdir() if p.is_dir())


@dataclass(frozen=True)
class KATCase:
    name: str
    directory: Path


def kat_cases() -> list[KATCase]:
    return [KATCase(name=p.name, directory=p) for p in _subdirs(FIXTURES_DIR / "kat")]


@dataclass(frozen=True)
class DeterminismCase:
    name: str
    directory: Path


def determinism_cases() -> list[DeterminismCase]:
    return [DeterminismCase(name=p.name, directory=p) for p in _subdirs(FIXTURES_DIR / "determinism")]


@dataclass(frozen=True)
class MustFailCase:
    name: str
    directory: Path


def must_fail_cases() -> list[MustFailCase]:
    return [MustFailCase(name=p.name, directory=p) for p in _subdirs(FIXTURES_DIR / "must_fail")]
