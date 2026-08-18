# SPDX-License-Identifier: Apache-2.0
"""Shared plumbing for verbs that evaluate a fold by reference: `capsule diff --fold`
and `capsule bisect --fold` both accept the same thing `fold test` does -- a
fold_id, a definition_digest, or a path to a definition YAML file -- resolved
against the built-in catalog (or `--dir`/`$CAPSULE_FOLD_DIR`)."""
from __future__ import annotations

from pathlib import Path

from ..envcompat import env_get
from ..folds.catalog import Catalog
from ..folds.definition import FoldDefinition
from ..folds.loader import load_definition_file
from .constraints_cmd import DEFAULT_CATALOG_DIR

__all__ = ["catalog_dir", "resolve_fold"]


def catalog_dir(args) -> Path:
    explicit = getattr(args, "dir", None)
    if explicit:
        return Path(explicit)
    env = env_get("CAPSULE_FOLD_DIR", "ASG_FOLD_DIR")
    if env:
        return Path(env)
    return DEFAULT_CATALOG_DIR


def resolve_fold(fold_ref: str, directory: Path) -> FoldDefinition | None:
    """Resolve *fold_ref* to a definition: a path to a YAML file if it exists
    on disk, otherwise a fold_id/definition_digest lookup in the catalog.
    Returns ``None`` if neither resolves -- callers print their own verb-scoped
    error message. A ``FoldDefinitionError`` from a malformed on-disk file
    propagates uncaught, same as `fold test`/`fold lint`."""
    path = Path(fold_ref)
    if path.exists():
        return load_definition_file(path)
    entry = Catalog(directory).get(fold_ref)
    return entry.definition if entry is not None else None
