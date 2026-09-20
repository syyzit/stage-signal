"""Release hygiene: the version a caller sees must be the version they installed.

`docs/RELEASE.md`'s fail-closed rules open with this check; until now nothing
enforced it, so `__init__.__version__`, `pyproject.toml` and the installed
distribution metadata could drift apart silently across a release.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from importlib import metadata
from pathlib import Path

import stage_signal


ROOT = Path(__file__).resolve().parent.parent


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_dunder_version_matches_pyproject() -> None:
    assert stage_signal.__version__ == _pyproject()["project"]["version"]


def test_dunder_version_matches_installed_metadata() -> None:
    assert stage_signal.__version__ == metadata.version("stage-signal")


def test_cli_version_flag_matches() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "stage_signal", "--version"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert stage_signal.__version__ in (proc.stdout + proc.stderr)


def test_classifiers_are_not_alpha() -> None:
    """Shipping 1.0 as `Development Status :: 3 - Alpha` contradicts the release."""
    classifiers = _pyproject()["project"]["classifiers"]
    status = [c for c in classifiers if c.startswith("Development Status ::")]
    assert status == ["Development Status :: 5 - Production/Stable"], status
