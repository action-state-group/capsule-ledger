# SPDX-License-Identifier: Apache-2.0
"""``capsule_ledger/cli/__init__.py`` must resolve ``main`` lazily (PEP 562
module ``__getattr__``) rather than importing it eagerly at package-init
time: ``main.py`` pulls in every verb submodule, some of which need
subpackages that moved to capsule-engine (W3.2). A leaf submodule consumer
-- capsule-engine's own CLI imports ``capsule_ledger.cli.ledger_io`` for its
``open_ledger``/``require_ledger_path`` helpers -- must not be forced to
import the whole verb set (and by extension the moved subpackages) just to
get one leaf module.

This file intentionally never imports ``capsule_ledger.cli.main`` (or
anything that transitively does) at module scope, so it stays collectible
in this repo's post-W3.2 state where ``folds.catalog`` no longer exists.
"""
import subprocess
import sys


def test_leaf_cli_submodule_import_does_not_pull_in_main():
    """Run in a clean subprocess interpreter: importing the leaf submodule
    must not, as a side effect, import ``.main`` (and by extension
    ``agents_cmd`` -> the deleted ``folds.catalog``).
    """
    script = (
        "import sys\n"
        "import capsule_ledger.cli.ledger_io\n"
        "assert 'capsule_ledger.cli.main' not in sys.modules, "
        "'importing a leaf cli submodule pulled in .main'\n"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_leaf_cli_submodule_import_works_without_folds_catalog():
    """The concrete regression: capsule-engine's own cli/bundle_cmd.py (and
    console_cmd.py, verify_cmd.py, mcp/config.py, tenant_cmds.py) import
    this exact module. It must succeed even though ``folds.catalog`` --
    needed only by ``agents_cmd.py``, one of many verb submodules ``main.py``
    eagerly imported -- no longer exists in this repo.
    """
    import capsule_ledger.cli.ledger_io as ledger_io

    assert hasattr(ledger_io, "open_ledger")
    assert hasattr(ledger_io, "require_ledger_path")


def test_cli_main_resolves_to_the_function_not_the_submodule():
    """Guards the ``__getattr__`` implementation itself: importing the
    ``.main`` submodule has a side effect Python's import system performs
    unconditionally -- binding it onto the ``cli`` package under the name
    ``main`` (true for any ``pkg.submodule`` import). A naive lazy
    ``__getattr__`` would let that submodule object shadow the ``main``
    function on every subsequent lookup once the submodule has been
    imported once. Skipped here because ``main.py`` itself cannot import in
    this repo's post-W3.2 state (it needs ``agents_cmd`` -> the deleted
    ``folds.catalog``) -- exercised for real against the companion
    capsule-engine branch instead, where the dependency chain is intact.
    """
    import capsule_ledger.cli as cli_pkg

    try:
        main = cli_pkg.main
    except ModuleNotFoundError:
        import pytest

        pytest.skip("capsule_ledger.cli.main needs folds.catalog, moved to capsule-engine (W3.2)")
    assert callable(main)
