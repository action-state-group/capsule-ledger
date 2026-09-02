# SPDX-License-Identifier: Apache-2.0
# Submodule-qualified import deliberately, not `from capsule_ledger.cli
# import main` -- see test_cli_lazy_main_import.py's
# test_cli_main_resolves_to_the_function_not_the_submodule for why the
# package-level accessor is order-sensitive across a shared test process.
from capsule_ledger.cli.main import main as cli_main


def test_import_subpackages():
    import capsule_ledger.cli
    import capsule_ledger.ledger
    import capsule_ledger.vectors

    assert capsule_ledger.ledger
    assert capsule_ledger.cli and capsule_ledger.vectors


def test_cli_version(capsys):
    assert cli_main(["--version"]) == 0
    out = capsys.readouterr().out.strip()
    assert out
