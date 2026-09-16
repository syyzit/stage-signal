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

# Compatibility fix: pytest 9 capture teardown can cause pytest-timeout to hit
# AssertionError in read_global_capture if capture is inactive when timeout fires.
try:
    from _pytest.capture import CaptureManager

    _orig_read = CaptureManager.read_global_capture

    def _safe_read_global_capture(self):  # type: ignore[no-untyped-def]
        if getattr(self, "_global_capturing", None) is None:
            return ("", "")
        try:
            return _orig_read(self)
        except Exception:
            return ("", "")

    CaptureManager.read_global_capture = _safe_read_global_capture  # type: ignore[method-assign]
except Exception:
    pass

# When a thread-method timeout fires, ensure the offending test nodeid is explicitly printed.
try:
    import pytest_timeout

    _orig_timeout_timer = pytest_timeout.timeout_timer

    def _safe_timeout_timer(item, settings):  # type: ignore[no-untyped-def]
        try:
            terminal = item.config.get_terminal_writer()
            terminal.sep(
                "!",
                title=f"PYTEST TIMEOUT EXCEEDED (> {settings.timeout}s): {item.nodeid}",
            )
        except Exception:
            pass
        _orig_timeout_timer(item, settings)

    pytest_timeout.timeout_timer = _safe_timeout_timer
except Exception:
    pass


