# SPDX-License-Identifier: Apache-2.0
from capsule_ledger.cli import main as cli_main


def test_import_subpackages():
    import capsule_ledger.cli
    import capsule_ledger.folds
    import capsule_ledger.guards
    import capsule_ledger.ledger
    import capsule_ledger.mcp
    import capsule_ledger.vectors

    assert capsule_ledger.ledger and capsule_ledger.folds and capsule_ledger.guards
    assert capsule_ledger.cli and capsule_ledger.mcp and capsule_ledger.vectors


def test_cli_version(capsys):
    assert cli_main(["--version"]) == 0
    out = capsys.readouterr().out.strip()
    assert out
