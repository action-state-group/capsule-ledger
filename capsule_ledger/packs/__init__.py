# SPDX-License-Identifier: Apache-2.0
"""Starter packs: installable obligation -> deterministic-check -> capsule
recipes, layered on top of the existing guard/fold/manifest primitives.

See the module docstrings in ``schema.py`` (the parsed pack shape),
``loader.py`` (``pack.yaml`` -> ``PackDefinition``), and ``engine_factory.py``
(``PackDefinition`` -> an installed, manifest-governed ``GuardEngine``) for
the pieces. ``catalog/`` holds the packs this repo ships (``payments-safety``
today).
"""
from .errors import PackDefinitionError
from .install import InstalledPack, build_engine, install_pack, record_pack_activation
from .loader import load_pack_dir
from .schema import ActionSemantic, Obligation, PackDefinition, PackFixtures, ProposerStub

__all__ = [
    "PackDefinition",
    "Obligation",
    "ActionSemantic",
    "ProposerStub",
    "PackFixtures",
    "load_pack_dir",
    "PackDefinitionError",
    "InstalledPack",
    "install_pack",
    "build_engine",
    "record_pack_activation",
]
