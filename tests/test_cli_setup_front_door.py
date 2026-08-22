# SPDX-License-Identifier: Apache-2.0
"""``[ldg-compiler-front-door]``: a fresh-eyes evaluation of ``capsule
setup`` found real, reproduced stops -- ``propose`` silently standing up an
instance nobody asked for, a corrupt file under ``declarations/`` crashing
the whole ``status`` command with a bare traceback, and no ``python -m``
entry point. Each is fixed and covered here independently of the module-
level tests in ``test_setup_declarations.py``/``test_setup_propose.py``.
"""
from __future__ import annotations

import runpy
import subprocess
import sys

from capsule_ledger.cli.main import main


def test_propose_before_init_refuses_instead_of_silently_creating_one(tmp_path, capsys):
    rc = main(["setup", "propose", "--project-dir", str(tmp_path)])
    assert rc == 2
    assert "run `capsule setup init` first" in capsys.readouterr().err
    # The whole point: nothing gets created just from asking.
    assert not (tmp_path / ".capsule-setup").exists()


def test_status_reports_a_corrupt_declaration_loudly_and_lists_the_rest(tmp_path, capsys):
    rc = main(["setup", "init", "--project-dir", str(tmp_path), "--key-id", "k", "--secret", "s"])
    assert rc == 0

    declarations_dir = tmp_path / ".capsule-setup" / "declarations"
    declarations_dir.mkdir(parents=True, exist_ok=True)
    (declarations_dir / "outcome.garbage.json").write_text("THIS IS NOT JSON {{{")

    rc = main(["setup", "status", "--project-dir", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "garbage" in captured.err
    assert "UNREADABLE" in captured.err


def test_python_dash_m_capsule_ledger_cli_is_a_real_entry_point():
    """``python -m capsule_ledger.cli --version`` must work even when the
    installed ``capsule`` console script isn't on PATH -- a container, a
    CI step, or an unactivated venv."""
    result = subprocess.run(
        [sys.executable, "-m", "capsule_ledger.cli", "--version"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert result.stdout.strip()


def test_main_module_calls_sys_exit_with_mains_return_code(monkeypatch):
    """Exercise ``__main__.py`` itself (not just the subprocess above) so
    coverage sees the module run, and pin that it forwards ``main()``'s
    return code to ``sys.exit`` rather than swallowing it."""
    monkeypatch.setattr(sys, "argv", ["capsule", "--version"])
    try:
        runpy.run_module("capsule_ledger.cli.__main__", run_name="__main__")
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("capsule_ledger.cli.__main__ did not call sys.exit")
