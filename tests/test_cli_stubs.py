"""`asg diff`/`blame`/`bisect` are explicitly out of scope for this task
(batch 2) -- they should say so clearly and fail loudly, never silently
succeed as if implemented."""
from __future__ import annotations

import pytest

from asg_ledger.cli.main import main


@pytest.mark.parametrize("verb", ["diff", "blame", "bisect"])
def test_stub_reports_not_implemented(verb, capsys):
    rc = main([verb])
    assert rc == 1
    err = capsys.readouterr().err
    assert f"asg {verb}: not yet implemented" in err
    assert "batch 2" in err


@pytest.mark.parametrize("verb", ["diff", "blame", "bisect"])
def test_stub_help_text_explains_scope(verb, capsys):
    with pytest.raises(SystemExit) as exc_info:
        main([verb, "--help"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "not yet implemented" in out
    assert "batch 2" in out
