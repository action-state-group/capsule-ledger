# SPDX-License-Identifier: Apache-2.0
"""``python -m capsule_ledger.cli`` -- the same entry point as the installed
``capsule`` console script, for anywhere a `pip install -e .` hasn't put the
script on ``$PATH`` (a container, a CI step, an unactivated venv)."""
import sys

from .main import main

if __name__ == "__main__":
    sys.exit(main())
