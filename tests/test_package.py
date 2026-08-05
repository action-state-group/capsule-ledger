from asg_ledger.cli import main as cli_main


def test_import_subpackages():
    import asg_ledger.cli
    import asg_ledger.folds
    import asg_ledger.guards
    import asg_ledger.ledger
    import asg_ledger.mcp
    import asg_ledger.vectors

    assert asg_ledger.ledger and asg_ledger.folds and asg_ledger.guards
    assert asg_ledger.cli and asg_ledger.mcp and asg_ledger.vectors


def test_cli_version(capsys):
    assert cli_main(["--version"]) == 0
    out = capsys.readouterr().out.strip()
    assert out
