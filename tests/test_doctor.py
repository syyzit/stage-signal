"""Tests for Stage.diagnose() dead claiming PID check and CLI doctor --json."""

from __future__ import annotations

import ctypes
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import types
from unittest.mock import MagicMock

import pytest

from stage_signal import Stage
from stage_signal.cli import main
from stage_signal.stage import (
    _is_pid_alive,
    _is_pid_alive_posix,
    _is_pid_alive_windows,
)


@pytest.fixture()
def sdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    monkeypatch.delenv("STAGE_SIGNAL_STATUS_MIRROR", raising=False)
    monkeypatch.delenv("STAGE_SIGNAL_PROOF_REF", raising=False)
    assert main(["init", "--project", "testproj"]) == 0
    return d


def test_diagnose_running_live_pid(tmp_path: Path) -> None:
    """A running stage with the current (live) PID produces no dead-PID warning."""
    d = tmp_path / ".stage-signal"
    stage = Stage(d)
    stage.init(project="testproj")
    stage.start(stage="task1", pid=os.getpid())

    diag = stage.diagnose()
    assert diag["ok"] is True
    assert not diag["problems"]
    assert not any("DEAD PID" in w for w in diag["warnings"])


def test_diagnose_running_dead_pid(tmp_path: Path) -> None:
    """A running stage with a dead PID produces an advisory DEAD PID warning without mutating state."""
    # Spawn a child that immediately exits to obtain a genuine dead PID.
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    dead_pid = proc.pid

    d = tmp_path / ".stage-signal"
    stage = Stage(d)
    stage.init(project="testproj")
    stage.start(stage="task1", pid=dead_pid)

    diag = stage.diagnose()
    assert diag["ok"] is True  # Warning alone does not cause ok to be False
    assert not diag["problems"]
    dead_warnings = [w for w in diag["warnings"] if "DEAD PID" in w]
    assert len(dead_warnings) == 1
    assert f"DEAD PID: claiming pid {dead_pid} is not alive (state still running)" in dead_warnings[0]

    # SPEC §4: library never auto-mutates state on staleness/dead PID
    status = stage.status()
    assert status["state"] == "running"
    assert status["pid"] == dead_pid


def test_diagnose_running_null_pid(tmp_path: Path) -> None:
    """A running stage with pid=None produces no dead-PID warning and does not crash."""
    d = tmp_path / ".stage-signal"
    stage = Stage(d)
    stage.init(project="testproj")
    stage.start(stage="task1")
    # Explicitly test null pid in STATUS.json
    status_file = d / "STATUS.json"
    raw = json.loads(status_file.read_text())
    raw["pid"] = None
    status_file.write_text(json.dumps(raw))

    diag = stage.diagnose()
    assert diag["ok"] is True
    assert not diag["problems"]
    assert not any("DEAD PID" in w for w in diag["warnings"])


def test_diagnose_non_running_dead_pid(tmp_path: Path) -> None:
    """A completed (done) stage with a dead PID produces no DEAD PID warning."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    dead_pid = proc.pid

    d = tmp_path / ".stage-signal"
    stage = Stage(d)
    stage.init(project="testproj")
    stage.start(stage="task1", pid=dead_pid)
    stage.done("finished successfully")

    diag = stage.diagnose()
    assert diag["ok"] is True
    assert not any("DEAD PID" in w for w in diag["warnings"])


def test_cli_doctor_human_and_json_live_pid(sdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CLI doctor and doctor --json with live PID output cleanly and exit 0."""
    live_pid = os.getpid()
    assert main(["start", "--stage", "m", "--pid", str(live_pid)]) == 0
    capsys.readouterr()

    # Human mode
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "OK: running" in out
    assert "DEAD PID" not in out

    # JSON mode
    assert main(["doctor", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["problems"] == []
    assert not any("DEAD PID" in w for w in data["warnings"])
    assert data["status"]["state"] == "running"
    assert data["status"]["pid"] == live_pid


def test_cli_doctor_human_and_json_dead_pid(sdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CLI doctor and doctor --json with dead PID warn and exit 0."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    dead_pid = proc.pid

    assert main(["start", "--stage", "m", "--pid", str(dead_pid)]) == 0
    capsys.readouterr()

    # Human mode
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    expected_warning = f"DEAD PID: claiming pid {dead_pid} is not alive (state still running)"
    assert f"WARNING: {expected_warning}" in out
    assert "OK: running" in out

    # JSON mode
    assert main(["doctor", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["problems"] == []
    assert expected_warning in data["warnings"]
    assert data["status"]["state"] == "running"
    assert data["status"]["pid"] == dead_pid


def test_cli_doctor_json_uninitialized(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CLI doctor --json on an uninitialized dir returns exit 1 and JSON problems."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    assert main(["--dir", str(empty_dir), "doctor", "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is False
    assert len(data["problems"]) > 0
    assert data["status"] is None


def test_cli_doctor_json_missing_dir(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CLI doctor --json on a missing directory returns exit 1 and JSON problems."""
    missing_dir = tmp_path / "does_not_exist"
    assert main(["--dir", str(missing_dir), "doctor", "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is False
    assert any("missing dir" in p for p in data["problems"])


def test_posix_liveness_unit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit test POSIX liveness: EPERM treats as alive, ESRCH as dead, other errors as None."""
    # Live current PID
    assert _is_pid_alive_posix(os.getpid()) is True

    # EPERM -> alive
    def mock_kill_eperm(pid: int, sig: int) -> None:
        raise PermissionError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(os, "kill", mock_kill_eperm)
    assert _is_pid_alive_posix(12345) is True

    # ESRCH -> dead
    def mock_kill_esrch(pid: int, sig: int) -> None:
        raise ProcessLookupError(errno.ESRCH, "No such process")

    monkeypatch.setattr(os, "kill", mock_kill_esrch)
    assert _is_pid_alive_posix(12345) is False

    # Other OSError -> None
    def mock_kill_other(pid: int, sig: int) -> None:
        raise OSError(errno.EINVAL, "Invalid argument")

    monkeypatch.setattr(os, "kill", mock_kill_other)
    assert _is_pid_alive_posix(12345) is None


def test_windows_liveness_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit test Windows liveness check using mocked ctypes.windll.kernel32."""
    mock_kernel32 = types.SimpleNamespace()
    mock_windll = types.SimpleNamespace(kernel32=mock_kernel32)

    import ctypes as real_ctypes

    monkeypatch.setattr(real_ctypes, "windll", mock_windll, raising=False)

    # 1. OpenProcess fails with ERROR_ACCESS_DENIED (5) -> alive (True)
    mock_kernel32.OpenProcess = MagicMock(return_value=0)
    mock_kernel32.GetLastError = MagicMock(return_value=5)
    assert _is_pid_alive_windows(1234) is True

    # 2. OpenProcess fails with ERROR_INVALID_PARAMETER (87) -> dead (False)
    mock_kernel32.GetLastError = MagicMock(return_value=87)
    assert _is_pid_alive_windows(1234) is False

    # 3. OpenProcess succeeds, GetExitCodeProcess returns STILL_ACTIVE (259) -> alive (True)
    mock_kernel32.OpenProcess = MagicMock(return_value=42)
    mock_kernel32.CloseHandle = MagicMock()

    def fake_exit_code_active(handle: int, byref_val: Any) -> int:
        byref_val._obj.value = 259
        return 1

    mock_kernel32.GetExitCodeProcess = fake_exit_code_active
    assert _is_pid_alive_windows(1234) is True
    mock_kernel32.CloseHandle.assert_called_with(42)

    # 4. OpenProcess succeeds, GetExitCodeProcess returns 0 (exited) -> dead (False)
    def fake_exit_code_dead(handle: int, byref_val: Any) -> int:
        byref_val._obj.value = 0
        return 1

    mock_kernel32.GetExitCodeProcess = fake_exit_code_dead
    assert _is_pid_alive_windows(1234) is False

    # 5. OpenProcess raises unexpected exception -> returns None
    mock_kernel32.OpenProcess = MagicMock(side_effect=RuntimeError("ctypes boom"))
    assert _is_pid_alive_windows(1234) is None


def test_is_pid_alive_edge_cases() -> None:
    """_is_pid_alive handles invalid types and negative/zero PIDs safely."""
    assert _is_pid_alive(0) is False
    assert _is_pid_alive(-1) is False
    assert _is_pid_alive(-999) is False
    assert _is_pid_alive(None) is None  # type: ignore[arg-type]
    assert _is_pid_alive("1234") is None  # type: ignore[arg-type]
    assert _is_pid_alive(True) is None  # type: ignore[arg-type]
    assert _is_pid_alive(False) is None  # type: ignore[arg-type]
