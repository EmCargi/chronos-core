"""Project-root conftest: make both dev/ (shared core.ollama) and the
chronos-core project root importable from every test file, so individual
tests don't need per-file sys.path bootstrap gymnastics.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DEV_ROOT = PROJECT_ROOT.parent.parent

for p in (str(DEV_ROOT), str(PROJECT_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)