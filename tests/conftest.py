"""Ensure src layout is importable without an install (dev/test convenience)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Default per-test timeout on Windows to fail hangs clearly if not explicitly configured
if sys.platform == "win32" and "PYTEST_TIMEOUT" not in os.environ:
    os.environ["PYTEST_TIMEOUT"] = "60"

