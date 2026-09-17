"""Tests for Stage.diagnose() dead claiming PID check and CLI doctor --json."""

from __future__ import annotations

import ctypes
from datetime import datetime, timedelta, timezone
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
    assert diag["state"] == "running"
    assert diag["summary"] == "OK: running"
    assert not diag["problems"]
    assert not any(w["code"] == "DEAD_PID" for w in diag["warnings"])


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
    assert diag["state"] == "running"
    assert diag["summary"] == "ATTENTION: running needs reclaim"
    assert not diag["problems"]
    dead_warnings = [w for w in diag["warnings"] if w["code"] == "DEAD_PID"]
    assert len(dead_warnings) == 1
    assert f"DEAD PID: claiming pid {dead_pid} is not alive (state still running)" in dead_warnings[0]["message"]
    assert "fail --reason TEXT --if-dead-pid" in dead_warnings[0]["message"]
    assert dead_warnings[0]["detail"] == {
        "pid": dead_pid,
        "recovery_hint": "fail --reason TEXT --if-dead-pid",
    }

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
    assert diag["state"] == "running"
    assert not diag["problems"]
    assert not any(w["code"] == "DEAD_PID" for w in diag["warnings"])


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
    assert diag["state"] == "done"
    assert diag["summary"] == "OK: done"
    assert not any(w["code"] == "DEAD_PID" for w in diag["warnings"])


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
    assert "ATTENTION" not in out

    # JSON mode
    assert main(["doctor", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["state"] == "running"
    assert data["summary"] == "OK: running"
    assert data["problems"] == []
    assert not any(w["code"] == "DEAD_PID" for w in data["warnings"])
    assert data["status"]["state"] == "running"
    assert data["status"]["pid"] == live_pid


def test_cli_doctor_human_and_json_dead_pid(sdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CLI doctor and doctor --json with dead PID warn, report non-OK summary, and exit 0."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    dead_pid = proc.pid

    assert main(["start", "--stage", "m", "--pid", str(dead_pid)]) == 0
    capsys.readouterr()

    # Human mode
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    expected_warning = (
        f"DEAD PID: claiming pid {dead_pid} is not alive (state still running); "
        "reclaim with 'fail --reason TEXT --if-dead-pid'"
    )
    assert f"WARNING: {expected_warning}" in out
    assert "OK: running" not in out
    assert "ATTENTION: running needs reclaim" in out

    # JSON mode
    assert main(["doctor", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["state"] == "running"
    assert data["summary"] == "ATTENTION: running needs reclaim"
    assert data["problems"] == []
    assert len(data["warnings"]) == 1
    w = data["warnings"][0]
    assert w["code"] == "DEAD_PID"
    assert w["message"] == expected_warning
    assert "fail --reason TEXT --if-dead-pid" in w["message"]
    assert w["detail"] == {
        "pid": dead_pid,
        "recovery_hint": "fail --reason TEXT --if-dead-pid",
    }
    assert data["status"]["state"] == "running"
    assert data["status"]["pid"] == dead_pid


@pytest.mark.parametrize("state,age,stale", [("running", 600, True), ("running", 30, False), ("done", 600, False)])
def test_doctor_default_heartbeat_threshold(
    sdir: Path, capsys: pytest.CaptureFixture[str], state: str, age: int, stale: bool,
) -> None:
    stage = Stage(sdir)
    stage.start(stage="task1", pid=os.getpid())
    if state == "done":
        stage.done("finished")
    status_file = sdir / "STATUS.json"
    raw = json.loads(status_file.read_text())
    raw["pid"] = None
    raw["heartbeat_at"] = (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat()
    status_file.write_text(json.dumps(raw))
    before = status_file.read_bytes()
    capsys.readouterr()

    diag = stage.diagnose()
    assert diag["ok"] is True
    assert diag["state"] == state
    assert diag["problems"] == []
    assert (any(w["code"] == "STALE_HEARTBEAT" for w in diag["warnings"])) is stale
    if stale and state == "running":
        assert diag["summary"] == "ATTENTION: running needs reclaim"
    else:
        assert diag["summary"] == f"OK: {state}"
    assert stage.diagnose(stale_after=3600)["warnings"] == []
    assert stage.diagnose(stale_after=None)["warnings"] == []

    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert ("WARNING: STALE" in out) is stale
    if stale and state == "running":
        assert "OK: running" not in out
        assert "ATTENTION: running needs reclaim" in out
    else:
        assert f"OK: {state}" in out
    assert main(["doctor", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["state"] == state
    assert data["problems"] == []
    assert (any(w["code"] == "STALE_HEARTBEAT" for w in data["warnings"])) is stale
    if stale and state == "running":
        assert data["summary"] == "ATTENTION: running needs reclaim"
    else:
        assert data["summary"] == f"OK: {state}"
    if stale:
        assert data["warnings"][0]["code"] == "STALE_HEARTBEAT"
        assert "threshold 300s" in data["warnings"][0]["message"]
        assert data["warnings"][0]["detail"]["threshold"] == 300.0
        assert data["warnings"][0]["detail"]["heartbeat_at"] == raw["heartbeat_at"]
        assert data["warnings"][0]["detail"]["age"] >= 590
    if state == "running":
        assert data["status"]["heartbeat_age_seconds"] is not None
    else:
        assert data["status"]["heartbeat_age_seconds"] is None
    if stale:
        assert data["status"]["heartbeat_age_seconds"] >= 590
    assert {k: v for k, v in data["status"].items() if k != "heartbeat_age_seconds"} == raw
    assert main(["doctor", "--stale-after", "3600", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["warnings"] == []
    assert status_file.read_bytes() == before


def test_cli_doctor_json_uninitialized(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CLI doctor --json on an uninitialized dir returns exit 1 and JSON problems."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    assert main(["--dir", str(empty_dir), "doctor", "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is False
    assert data["state"] is None
    assert len(data["problems"]) > 0
    assert data["warnings"] == []
    assert data["status"] is None


def test_cli_doctor_json_missing_dir(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CLI doctor --json on a missing directory returns exit 1 and JSON problems."""
    missing_dir = tmp_path / "does_not_exist"
    assert main(["--dir", str(missing_dir), "doctor", "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is False
    assert data["state"] is None
    assert any("missing dir" in p for p in data["problems"])
    assert data["warnings"] == []
    assert data["status"] is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal-zero probe is unsafe on Windows")
def test_posix_liveness_live_pid() -> None:
    assert _is_pid_alive_posix(os.getpid()) is True


def test_posix_liveness_unit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit test POSIX liveness: EPERM treats as alive, ESRCH as dead, other errors as None."""
    mock_kill = MagicMock(return_value=None)
    monkeypatch.setattr(os, "kill", mock_kill)
    assert _is_pid_alive_posix(12345) is True
    mock_kill.assert_called_once_with(12345, 0)

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

    mock_kernel32.GetLastError = MagicMock(return_value=6)
    assert _is_pid_alive_windows(1234) is None

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

    mock_kernel32.GetExitCodeProcess = MagicMock(return_value=0)
    assert _is_pid_alive_windows(1234) is None
    mock_kernel32.CloseHandle.assert_called_with(42)

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


def test_doctor_json_clean_ok_shapes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify clean OK JSON shapes across queued, running, done, blocked, and failed states."""
    d = tmp_path / ".stage-signal"
    stage = Stage(d)
    stage.init(project="clean-proj")

    # 1. Queued
    assert main(["--dir", str(d), "doctor", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["state"] == "queued"
    assert data["summary"] == "OK: queued"
    assert data["problems"] == []
    assert data["warnings"] == []
    assert data["status"]["state"] == "queued"
    assert data["status"]["project"] == "clean-proj"

    # 2. Running (live PID)
    stage.start(stage="step-1", pid=os.getpid())
    assert main(["--dir", str(d), "doctor", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["state"] == "running"
    assert data["summary"] == "OK: running"
    assert data["problems"] == []
    assert data["warnings"] == []
    assert data["status"]["state"] == "running"

    # 3. Done
    stage.done(summary="all good")
    assert main(["--dir", str(d), "doctor", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["state"] == "done"
    assert data["summary"] == "OK: done"
    assert data["problems"] == []
    assert data["warnings"] == []
    assert data["status"]["state"] == "done"

    # 4. Blocked
    stage.start(stage="step-2", pid=os.getpid())
    stage.blocked(reason="waiting for auth")
    assert main(["--dir", str(d), "doctor", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["state"] == "blocked"
    assert data["summary"] == "OK: blocked"
    assert data["problems"] == []
    assert data["warnings"] == []
    assert data["status"]["state"] == "blocked"

    # 5. Failed
    stage.start(stage="step-3", pid=os.getpid())
    stage.fail(reason="crash")
    assert main(["--dir", str(d), "doctor", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["state"] == "failed"
    assert data["summary"] == "OK: failed"
    assert data["problems"] == []
    assert data["warnings"] == []
    assert data["status"]["state"] == "failed"


def test_doctor_running_no_heartbeat(sdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Running stage with no heartbeat produces structured STALE_HEARTBEAT warning and attention summary."""
    assert main(["start", "--stage", "m", "--pid", str(os.getpid())]) == 0
    status_file = sdir / "STATUS.json"
    raw = json.loads(status_file.read_text())
    raw["heartbeat_at"] = None
    status_file.write_text(json.dumps(raw))
    capsys.readouterr()

    # Human output
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "WARNING: STALE: running with no heartbeat recorded" in out
    assert "OK: running" not in out
    assert "ATTENTION: running needs reclaim" in out

    # JSON output
    assert main(["doctor", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["state"] == "running"
    assert data["summary"] == "ATTENTION: running needs reclaim"
    assert data["problems"] == []
    assert len(data["warnings"]) == 1
    w = data["warnings"][0]
    assert w["code"] == "STALE_HEARTBEAT"
    assert w["message"] == "STALE: running with no heartbeat recorded"
    assert w["detail"]["age"] is None
    assert w["detail"]["threshold"] == 300.0
    assert w["detail"]["heartbeat_at"] is None


def test_doctor_running_unparseable_heartbeat(sdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Running stage with unparseable heartbeat produces structured UNPARSEABLE_HEARTBEAT warning."""
    assert main(["start", "--stage", "m", "--pid", str(os.getpid())]) == 0
    status_file = sdir / "STATUS.json"
    raw = json.loads(status_file.read_text())
    raw["heartbeat_at"] = "garbage-date"
    status_file.write_text(json.dumps(raw))
    capsys.readouterr()

    # Human output
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "WARNING: unparseable heartbeat_at" in out
    assert "OK: running" in out

    # JSON output
    assert main(["doctor", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["state"] == "running"
    assert data["summary"] == "OK: running"
    assert data["problems"] == []
    assert len(data["warnings"]) == 1
    w = data["warnings"][0]
    assert w["code"] == "UNPARSEABLE_HEARTBEAT"
    assert w["message"] == "unparseable heartbeat_at"
    assert w["detail"] == {"heartbeat_at": "garbage-date"}


def test_doctor_multiple_warnings_simultaneously(sdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A running stage with both dead PID and stale heartbeat yields both structured warnings and reclaim summary."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    dead_pid = proc.pid

    assert main(["start", "--stage", "multi", "--pid", str(dead_pid)]) == 0
    status_file = sdir / "STATUS.json"
    raw = json.loads(status_file.read_text())
    raw["heartbeat_at"] = (datetime.now(timezone.utc) - timedelta(seconds=700)).isoformat()
    status_file.write_text(json.dumps(raw))
    capsys.readouterr()

    # Human output has both warnings
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "WARNING: STALE: running with heartbeat" in out
    assert f"WARNING: DEAD PID: claiming pid {dead_pid} is not alive" in out
    assert "OK: running" not in out
    assert "ATTENTION: running needs reclaim" in out

    # JSON output has both structured warnings
    assert main(["doctor", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["state"] == "running"
    assert data["summary"] == "ATTENTION: running needs reclaim"
    assert data["problems"] == []
    assert len(data["warnings"]) == 2

    codes = {w["code"] for w in data["warnings"]}
    assert codes == {"STALE_HEARTBEAT", "DEAD_PID"}

    hb_w = next(w for w in data["warnings"] if w["code"] == "STALE_HEARTBEAT")
    assert "threshold 300s" in hb_w["message"]
    assert hb_w["detail"]["threshold"] == 300.0
    assert hb_w["detail"]["age"] >= 690

    pid_w = next(w for w in data["warnings"] if w["code"] == "DEAD_PID")
    assert f"claiming pid {dead_pid}" in pid_w["message"]
    assert "fail --reason TEXT --if-dead-pid" in pid_w["message"]
    assert pid_w["detail"] == {
        "pid": dead_pid,
        "recovery_hint": "fail --reason TEXT --if-dead-pid",
    }


def test_doctor_format_flag_support(sdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify --format json matches --json and --format human works as default."""
    capsys.readouterr()
    assert main(["doctor", "--format", "json"]) == 0
    data_format = json.loads(capsys.readouterr().out)

    assert main(["doctor", "--json"]) == 0
    data_json = json.loads(capsys.readouterr().out)

    assert data_format == data_json

    assert main(["doctor", "--format", "human"]) == 0
    out = capsys.readouterr().out
    assert "OK: queued" in out


def test_doctor_exit_codes_semantics(tmp_path: Path) -> None:
    """Verify doctor exit codes: 0 for healthy/warnings, 1 for problems, 2 for bad args, 10 for --exit-reclaim."""
    # 1. Healthy dir -> exit 0 (with or without --exit-reclaim)
    d = tmp_path / "healthy"
    stage = Stage(d)
    stage.init(project="healthy-proj")
    assert main(["--dir", str(d), "doctor"]) == 0
    assert main(["--dir", str(d), "doctor", "--json"]) == 0
    assert main(["--dir", str(d), "doctor", "--exit-reclaim"]) == 0
    assert main(["--dir", str(d), "doctor", "--exit-reclaim", "--json"]) == 0

    # 2. Healthy dir with warning (dead PID) -> exit 0 without flag, exit 10 with --exit-reclaim
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    stage.start(stage="task", pid=proc.pid)
    assert main(["--dir", str(d), "doctor"]) == 0
    assert main(["--dir", str(d), "doctor", "--json"]) == 0
    assert main(["--dir", str(d), "doctor", "--exit-reclaim"]) == 10
    assert main(["--dir", str(d), "doctor", "--exit-reclaim", "--json"]) == 10

    # 3. Problem: corrupt STATUS.json -> exit 1 (with or without --exit-reclaim)
    (d / "STATUS.json").write_text("{corrupt json")
    assert main(["--dir", str(d), "doctor"]) == 1
    assert main(["--dir", str(d), "doctor", "--json"]) == 1
    assert main(["--dir", str(d), "doctor", "--exit-reclaim"]) == 1
    assert main(["--dir", str(d), "doctor", "--exit-reclaim", "--json"]) == 1

    # 4. Problem: missing directory -> exit 1 (with or without --exit-reclaim)
    missing = tmp_path / "nonexistent"
    assert main(["--dir", str(missing), "doctor"]) == 1
    assert main(["--dir", str(missing), "doctor", "--json"]) == 1
    assert main(["--dir", str(missing), "doctor", "--exit-reclaim"]) == 1
    assert main(["--dir", str(missing), "doctor", "--exit-reclaim", "--json"]) == 1

    # 5. Bad CLI args -> exit 2 (with or without --exit-reclaim)
    with pytest.raises(SystemExit) as exc:
        main(["--dir", str(d), "doctor", "--stale-after", "not_a_number"])
    assert exc.value.code == 2
    with pytest.raises(SystemExit) as exc:
        main(["--dir", str(d), "doctor", "--exit-reclaim", "--stale-after", "not_a_number"])
    assert exc.value.code == 2


def test_doctor_healthy_running_vs_stale_vs_dead_pid(sdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Explicitly verify healthy running vs STALE vs DEAD_PID in human and JSON modes."""
    # 1. Healthy running (live PID, fresh heartbeat) -> OK: running
    assert main(["start", "--stage", "task-healthy", "--pid", str(os.getpid())]) == 0
    capsys.readouterr()

    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "OK: running" in out
    assert "ATTENTION" not in out

    assert main(["doctor", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["state"] == "running"
    assert data["summary"] == "OK: running"
    assert not data["warnings"]

    # 2. STALE running (stale heartbeat, live PID) -> ATTENTION: running needs reclaim
    status_file = sdir / "STATUS.json"
    raw = json.loads(status_file.read_text())
    raw["heartbeat_at"] = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
    status_file.write_text(json.dumps(raw))
    capsys.readouterr()

    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "OK: running" not in out
    assert "ATTENTION: running needs reclaim" in out
    assert "WARNING: STALE: running with heartbeat" in out

    assert main(["doctor", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["state"] == "running"
    assert data["summary"] == "ATTENTION: running needs reclaim"
    assert any(w["code"] == "STALE_HEARTBEAT" for w in data["warnings"])

    # 3. DEAD_PID running (fresh heartbeat, dead PID) -> ATTENTION: running needs reclaim
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    dead_pid = proc.pid
    raw["pid"] = dead_pid
    raw["heartbeat_at"] = datetime.now(timezone.utc).isoformat()
    status_file.write_text(json.dumps(raw))
    capsys.readouterr()

    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "OK: running" not in out
    assert "ATTENTION: running needs reclaim" in out
    assert f"WARNING: DEAD PID: claiming pid {dead_pid}" in out

    assert main(["doctor", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["state"] == "running"
    assert data["summary"] == "ATTENTION: running needs reclaim"
    assert any(w["code"] == "DEAD_PID" for w in data["warnings"])


@pytest.mark.parametrize("state", ["running", "done", "failed", "queued", "blocked"])
@pytest.mark.parametrize(
    "heartbeat,pid_alive,codes",
    [
        ("fresh", True, set()),
        ("stale", True, {"STALE_HEARTBEAT"}),
        ("fresh", False, {"DEAD_PID"}),
        ("stale", False, {"STALE_HEARTBEAT", "DEAD_PID"}),
        (None, True, {"STALE_HEARTBEAT"}),
        ("invalid", True, {"UNPARSEABLE_HEARTBEAT"}),
        ("fresh", None, set()),
    ],
)
def test_needs_reclaim_state_matrix(
    sdir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
    state: str, heartbeat: str | None, pid_alive: bool | None, codes: set[str],
) -> None:
    stage = Stage(sdir)
    stage.start(stage="reclaim", pid=os.getpid())
    monkeypatch.setattr("stage_signal.stage._is_pid_alive", lambda pid: pid_alive)
    status_file = sdir / "STATUS.json"
    raw = json.loads(status_file.read_text())
    raw["state"] = state
    if heartbeat == "stale":
        raw["heartbeat_at"] = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
    elif heartbeat != "fresh":
        raw["heartbeat_at"] = heartbeat
    status_file.write_text(json.dumps(raw))
    before = status_file.read_bytes()
    capsys.readouterr()
    expected_codes = codes if state == "running" else set()
    expected_reclaim = bool(expected_codes & {"STALE_HEARTBEAT", "DEAD_PID"})

    diag = stage.diagnose()
    assert main(["doctor", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    for result in (diag, data):
        assert result["needs_reclaim"] is expected_reclaim
        assert result["ok"] is True
        assert result["state"] == state
        assert {w["code"] for w in result["warnings"]} == expected_codes
    assert main(["status", "--json"]) == {
        "running": 10, "done": 0, "failed": 12, "queued": 13, "blocked": 11,
    }[state]
    status = json.loads(capsys.readouterr().out)
    assert status["needs_reclaim"] is expected_reclaim
    assert status_file.read_bytes() == before
    assert stage.diagnose(stale_after=None)["needs_reclaim"] is (
        state == "running" and pid_alive is False
    )
    assert stage.diagnose(stale_after=3600)["needs_reclaim"] is (
        state == "running" and (pid_alive is False or heartbeat is None)
    )


@pytest.mark.parametrize("problem", ["missing_dir", "missing_status", "corrupt_status"])
def test_needs_reclaim_without_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], problem: str,
) -> None:
    d = tmp_path / "unhealthy"
    if problem != "missing_dir":
        d.mkdir()
    if problem == "corrupt_status":
        (d / "STATUS.json").write_text("{corrupt json")
    diag = Stage(d).diagnose()
    assert main(["--dir", str(d), "doctor", "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    for result in (diag, data):
        assert result["needs_reclaim"] is False
        assert result["ok"] is False
        assert result["problems"]
        assert result["warnings"] == []
        assert result["status"] is None


@pytest.mark.parametrize("pid_alive", [True, False])
def test_needs_reclaim_independent_of_problems(
    sdir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
    pid_alive: bool,
) -> None:
    stage = Stage(sdir)
    stage.start(stage="reclaim", pid=os.getpid())
    monkeypatch.setattr("stage_signal.stage._is_pid_alive", lambda pid: pid_alive)
    (sdir / "events.jsonl").write_text("{corrupt json\n")
    capsys.readouterr()

    diag = stage.diagnose()
    assert main(["doctor", "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    for result in (diag, data):
        assert result["needs_reclaim"] is (not pid_alive)
        assert result["ok"] is False
        assert result["problems"]
        assert result["summary"] is None


@pytest.mark.parametrize(
    "case",
    ["healthy", "DEAD_PID", "STALE", "problems"],
)
@pytest.mark.parametrize("with_flag", [False, True])
@pytest.mark.parametrize("as_json", [False, True])
def test_doctor_exit_reclaim_matrix(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    case: str,
    with_flag: bool,
    as_json: bool,
) -> None:
    d = tmp_path / f"test-{case}-{with_flag}-{as_json}"
    stage = Stage(d)

    if case == "healthy":
        stage.init(project="testproj")
        stage.start(stage="healthy-task", pid=os.getpid())
        expected_exit = 0
        expected_needs_reclaim = False
    elif case == "DEAD_PID":
        stage.init(project="testproj")
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        stage.start(stage="dead-pid-task", pid=proc.pid)
        expected_exit = 10 if with_flag else 0
        expected_needs_reclaim = True
    elif case == "STALE":
        stage.init(project="testproj")
        stage.start(stage="stale-task", pid=os.getpid())
        stale_time = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
        status_file = d / "STATUS.json"
        raw = json.loads(status_file.read_text())
        raw["heartbeat_at"] = stale_time
        status_file.write_text(json.dumps(raw))
        expected_exit = 10 if with_flag else 0
        expected_needs_reclaim = True
    elif case == "problems":
        d.mkdir(parents=True, exist_ok=True)
        (d / "STATUS.json").write_text("{corrupt json")
        expected_exit = 1
        expected_needs_reclaim = False

    cmd = ["--dir", str(d), "doctor"]
    if with_flag:
        cmd.append("--exit-reclaim")
    if as_json:
        cmd.append("--json")

    capsys.readouterr()
    exit_code = main(cmd)
    out = capsys.readouterr().out

    assert exit_code == expected_exit

    if as_json:
        data = json.loads(out)
        assert data["needs_reclaim"] is expected_needs_reclaim
        if expected_exit == 10:
            assert data["needs_reclaim"] is True
            assert data["state"] == "running"
    else:
        if expected_exit == 10:
            assert "ATTENTION: running needs reclaim" in out
        elif case == "healthy":
            assert "OK: running" in out
        elif case == "problems":
            assert "PROBLEM:" in out


@pytest.mark.parametrize("with_flag", [False, True])
@pytest.mark.parametrize("pid_alive", [True, False])
def test_doctor_exit_reclaim_problems_coexisting(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    with_flag: bool,
    pid_alive: bool,
) -> None:
    d = tmp_path / f"test-prob-reclaim-{with_flag}-{pid_alive}"
    stage = Stage(d)
    stage.init(project="testproj")
    stage.start(stage="reclaim-problems", pid=os.getpid())
    monkeypatch.setattr("stage_signal.stage._is_pid_alive", lambda pid: pid_alive)
    (d / "events.jsonl").write_text("{corrupt json\n")
    capsys.readouterr()

    cmd = ["--dir", str(d), "doctor"]
    if with_flag:
        cmd.append("--exit-reclaim")

    # If pid is dead, needs_reclaim is True.
    # With --exit-reclaim: exits 10.
    # Without --exit-reclaim: exits 1 (problems present).
    # If pid is alive, needs_reclaim is False -> exits 1 either way.
    if not pid_alive and with_flag:
        expected_exit = 10
    else:
        expected_exit = 1

    exit_code = main(cmd)
    out = capsys.readouterr().out
    assert exit_code == expected_exit
    assert "PROBLEM:" in out
    if not pid_alive:
        assert "DEAD PID:" in out
