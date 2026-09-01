# SPDX-License-Identifier: Apache-2.0
"""``[ldg-compiler-front-door]``: pins that the ``capsule`` CLI has a real
``python -m`` entry point, and that ``__main__.py`` forwards ``main()``'s
return code to ``sys.exit`` rather than swallowing it."""
from __future__ import annotations

import runpy
import subprocess
import sys


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
