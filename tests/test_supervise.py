"""Unit and CLI tests for Stage.supervise and `stage-signal supervise` (#92)."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from stage_signal import (
    BadArgsError,
    IllegalTransition,
    NotInitialized,
    Stage,
)
from stage_signal.cli import main
from stage_signal.constants import (
    DEFAULT_STALE_THRESHOLD,
    EXIT_BAD_ARGS,
    EXIT_ILLEGAL_TRANSITION,
    EXIT_NOT_INITIALIZED,
    STATE_DONE,
    STATE_FAILED,
    STATE_QUEUED,
    STATE_RUNNING,
    SUPERVISE_DEFAULT_EVERY,
)


@pytest.fixture()
def stage_dir(tmp_path: Path) -> Path:
    return tmp_path / ".stage-signal"


@pytest.fixture()
def stage(stage_dir: Path) -> Stage:
    s = Stage(stage_dir)
    s.init(project="test-supervise")
    return s


# -- Stage.supervise unit tests -----------------------------------------


def test_supervise_success_exit_zero(stage: Stage) -> None:
    stage.start(stage="task-1")
    code = stage.supervise([sys.executable, "-c", "import sys; sys.exit(0)"])
    assert code == 0

    st = stage.status()
    assert st["state"] == STATE_DONE
    assert st["result"] is not None
    assert "command succeeded (exit 0)" in st["result"]["summary"]
    assert st["error"] is None

    events = stage.events()
    assert [e["type"] for e in events] == ["init", "start", "heartbeat", "done"]
    assert events[2]["message"].startswith("adopted child pid ")


def test_supervise_failure_exit_nonzero(stage: Stage) -> None:
    stage.start(stage="task-fail")
    code = stage.supervise([sys.executable, "-c", "import sys; sys.exit(42)"])
    assert code == 42

    st = stage.status()
    assert st["state"] == STATE_FAILED
    assert st["error"] is not None
    assert "command failed with exit code 42" in st["error"]["reason"]
    assert st["result"] is None

    events = stage.events()
    assert [e["type"] for e in events] == ["init", "start", "heartbeat", "failed"]
    assert events[2]["message"].startswith("adopted child pid ")


def test_supervise_custom_summary_and_reason(stage: Stage) -> None:
    # Custom summary on success
    stage.start(stage="custom-summary")
    code = stage.supervise(
        [sys.executable, "-c", "pass"],
        summary="Custom success summary",
    )
    assert code == 0
    st = stage.status()
    assert st["result"]["summary"] == "Custom success summary"

    # Custom reason on failure
    stage.start(stage="custom-reason")
    code = stage.supervise(
        [sys.executable, "-c", "import sys; sys.exit(3)"],
        reason="Custom failure reason",
    )
    assert code == 3
    st = stage.status()
    assert st["error"]["reason"] == "Custom failure reason"


def test_supervise_auto_heartbeat_advances(stage: Stage) -> None:
    stage.start(stage="task-hb")
    t0 = stage.status()["heartbeat_at"]

    # Run for ~1.5s with every=1.0s to trigger at least one periodic heartbeat
    code = stage.supervise(
        [sys.executable, "-c", "import time; time.sleep(1.5)"],
        every=1.0,
    )
    assert code == 0
    st = stage.status()
    assert st["state"] == STATE_DONE

    events = stage.events()
    event_types = [e["type"] for e in events]
    assert "heartbeat" in event_types
    # Heartbeat timestamp in events should be >= t0
    hb_events = [e for e in events if e["type"] == "heartbeat"]
    assert len(hb_events) >= 2
    assert hb_events[0]["ts"] >= t0
    assert hb_events[1]["detail"] == {}
    assert hb_events[1]["ts"] > hb_events[0]["ts"]


def test_supervise_refuses_when_not_running(stage: Stage) -> None:
    # 1. State is queued
    st = stage.status()
    assert st["state"] == STATE_QUEUED
    with pytest.raises(IllegalTransition, match="requires state 'running'"):
        stage.supervise([sys.executable, "-c", "pass"])

    # 2. State is done
    stage.start(stage="test")
    stage.done(summary="ok")
    with pytest.raises(IllegalTransition, match="requires state 'running'"):
        stage.supervise([sys.executable, "-c", "pass"])

    # 3. State is blocked
    stage.start(stage="test")
    stage.blocked(reason="blocked")
    with pytest.raises(IllegalTransition, match="requires state 'running'"):
        stage.supervise([sys.executable, "-c", "pass"])

    # 4. State is failed
    stage.start(stage="test")
    stage.fail(reason="fail")
    with pytest.raises(IllegalTransition, match="requires state 'running'"):
        stage.supervise([sys.executable, "-c", "pass"])


def test_supervise_refuses_when_not_initialized(tmp_path: Path) -> None:
    uninit = Stage(tmp_path / "nonexistent")
    with pytest.raises(NotInitialized):
        uninit.supervise([sys.executable, "-c", "pass"])


def test_supervise_every_validation(stage: Stage) -> None:
    stage.start(stage="task-val")

    # every < 1
    with pytest.raises(BadArgsError, match="--every must be between 1 and"):
        stage.supervise([sys.executable, "-c", "pass"], every=0.5)
    with pytest.raises(BadArgsError, match="--every must be between 1 and"):
        stage.supervise([sys.executable, "-c", "pass"], every=0)
    with pytest.raises(BadArgsError, match="--every must be between 1 and"):
        stage.supervise([sys.executable, "-c", "pass"], every=-10)

    # every > stale_threshold - 1
    with pytest.raises(BadArgsError, match="--every must be between 1 and"):
        stage.supervise([sys.executable, "-c", "pass"], every=300)
    with pytest.raises(BadArgsError, match="--every must be between 1 and"):
        stage.supervise([sys.executable, "-c", "pass"], every=500)

    # non-number or bool
    with pytest.raises(BadArgsError, match="--every must be between 1 and"):
        stage.supervise([sys.executable, "-c", "pass"], every=True)  # type: ignore[arg-type]


def test_supervise_cmd_validation(stage: Stage) -> None:
    stage.start(stage="task-cmd-val")

    # Empty command sequence / string
    with pytest.raises(BadArgsError, match="supervise requires a non-empty command"):
        stage.supervise([])
    with pytest.raises(BadArgsError, match="supervise requires a non-empty command"):
        stage.supervise("")
    with pytest.raises(BadArgsError, match="supervise requires a non-empty command"):
        stage.supervise("   ")

    # Invalid type
    with pytest.raises(BadArgsError, match="cmd must be a sequence of strings or a string"):
        stage.supervise(12345)  # type: ignore[arg-type]


def test_supervise_cmd_as_string(stage: Stage) -> None:
    stage.start(stage="task-cmd-str")
    code = stage.supervise(f'"{sys.executable}" -c "import sys; sys.exit(0)"')
    assert code == 0
    assert stage.status()["state"] == STATE_DONE


def test_supervise_nonexistent_command(stage: Stage) -> None:
    stage.start(stage="task-nonexistent")
    code = stage.supervise(["__nonexistent_binary_xyz_12345__"])
    assert code == 127
    st = stage.status()
    assert st["state"] == STATE_FAILED
    assert "command not found" in st["error"]["reason"]


def test_supervise_cwd_and_env(stage: Stage, tmp_path: Path) -> None:
    stage.start(stage="task-env")
    probe = tmp_path / "probe.txt"
    script = (
        "import os, pathlib; "
        "pathlib.Path('probe.txt').write_text(os.environ.get('SUPERVISE_TEST_VAR', ''))"
    )
    code = stage.supervise(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={**os.environ, "SUPERVISE_TEST_VAR": "magic_val"},
    )
    assert code == 0
    assert probe.read_text() == "magic_val"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal forwarding")
def test_supervise_signal_forwarding_sigint(stage: Stage) -> None:
    stage.start(stage="task-sig")
    # Subprocess sleeps; supervisor will receive SIGINT in a thread or process
    # Here we test signal termination exit code mapping
    script = "import os, signal, time; os.kill(os.getpid(), signal.SIGINT)"
    code = stage.supervise([sys.executable, "-c", script])
    assert code == 128 + signal.SIGINT
    st = stage.status()
    assert st["state"] == STATE_FAILED
    assert "SIGINT" in st["error"]["reason"]


# -- CLI supervise tests ------------------------------------------------


def test_cli_supervise_success(stage: Stage, capsys: pytest.CaptureFixture[str]) -> None:
    stage.start(stage="cli-task")
    ret = main(["--dir", str(stage.dir), "supervise", "--", sys.executable, "-c", "pass"])
    assert ret == 0
    st = stage.status()
    assert st["state"] == STATE_DONE
    assert "command succeeded (exit 0)" in st["result"]["summary"]


def test_cli_supervise_failure(stage: Stage) -> None:
    stage.start(stage="cli-fail")
    ret = main([
        "--dir", str(stage.dir),
        "supervise", "--",
        sys.executable, "-c", "import sys; sys.exit(7)",
    ])
    assert ret == 7
    st = stage.status()
    assert st["state"] == STATE_FAILED
    assert "command failed with exit code 7" in st["error"]["reason"]


def test_cli_supervise_without_double_dash(stage: Stage) -> None:
    stage.start(stage="cli-nodash")
    ret = main([
        "--dir", str(stage.dir),
        "supervise",
        sys.executable, "-c", "pass",
    ])
    assert ret == 0
    assert stage.status()["state"] == STATE_DONE


def test_cli_supervise_dir_after_subcommand(stage: Stage) -> None:
    stage.start(stage="cli-dir-after")
    ret = main([
        "supervise", "--dir", str(stage.dir),
        "--", sys.executable, "-c", "pass",
    ])
    assert ret == 0
    assert stage.status()["state"] == STATE_DONE


def test_cli_supervise_custom_summary_and_reason(stage: Stage) -> None:
    stage.start(stage="cli-custom-sum")
    ret = main([
        "--dir", str(stage.dir),
        "supervise",
        "--summary", "CLI success custom",
        "--", sys.executable, "-c", "pass",
    ])
    assert ret == 0
    assert stage.status()["result"]["summary"] == "CLI success custom"

    stage.start(stage="cli-custom-fail")
    ret = main([
        "--dir", str(stage.dir),
        "supervise",
        "--reason", "CLI fail custom",
        "--", sys.executable, "-c", "import sys; sys.exit(1)",
    ])
    assert ret == 1
    assert stage.status()["error"]["reason"] == "CLI fail custom"


def test_cli_supervise_refuses_when_queued(stage: Stage, capsys: pytest.CaptureFixture[str]) -> None:
    ret = main([
        "--dir", str(stage.dir),
        "supervise", "--",
        sys.executable, "-c", "pass",
    ])
    assert ret == EXIT_ILLEGAL_TRANSITION
    err = capsys.readouterr().err
    assert "requires state 'running'" in err


def test_cli_supervise_refuses_when_not_initialized(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    nonexistent = tmp_path / "no-stage"
    ret = main([
        "--dir", str(nonexistent),
        "supervise", "--",
        sys.executable, "-c", "pass",
    ])
    assert ret == EXIT_NOT_INITIALIZED
    err = capsys.readouterr().err
    assert "not initialized" in err.lower() or "missing" in err.lower()


def test_cli_supervise_bad_every(stage: Stage, capsys: pytest.CaptureFixture[str]) -> None:
    stage.start(stage="cli-bad-every")
    ret = main([
        "--dir", str(stage.dir),
        "supervise", "--every", "0",
        "--", sys.executable, "-c", "pass",
    ])
    assert ret == EXIT_BAD_ARGS

    ret = main([
        "--dir", str(stage.dir),
        "supervise", "--every", "300",
        "--", sys.executable, "-c", "pass",
    ])
    assert ret == EXIT_BAD_ARGS


def test_cli_supervise_missing_command(stage: Stage, capsys: pytest.CaptureFixture[str]) -> None:
    stage.start(stage="cli-nocmd")
    ret = main(["--dir", str(stage.dir), "supervise"])
    assert ret == EXIT_BAD_ARGS
    err = capsys.readouterr().err
    assert "requires a command to run" in err

    ret = main(["--dir", str(stage.dir), "supervise", "--"])
    assert ret == EXIT_BAD_ARGS


def test_cli_supervise_write_status_mirror(stage: Stage) -> None:
    stage.start(stage="cli-mirror")
    ret = main([
        "--dir", str(stage.dir),
        "supervise", "--write-status-mirror",
        "--", sys.executable, "-c", "pass",
    ])
    assert ret == 0
    # Check mirror file was created in parent of .stage-signal:
    repo_root = stage.dir.parent
    orch_dir = repo_root / ".orch"
    assert (orch_dir / "STATUS.md").is_file()
    assert (orch_dir / "DONE").is_file()


def test_supervise_adopts_child_pid_and_token(stage: Stage, tmp_path: Path) -> None:
    stage.start(stage="test-adopt", pid=999999, session_id="sess-adopt")
    st0 = stage.status()
    assert st0["pid"] == 999999
    assert st0["session_id"] == "sess-adopt"
    assert st0["stage_id"] == "test-adopt"
    assert st0["attempt"] == 1

    ready = tmp_path / "child_ready.txt"
    stop = tmp_path / "child_stop.txt"
    script = (
        "import os, pathlib, time\n"
        f"pathlib.Path(r'{ready}').write_text(str(os.getpid()))\n"
        f"while not pathlib.Path(r'{stop}').exists():\n"
        "    time.sleep(0.02)\n"
    )

    t = threading.Thread(
        target=stage.supervise,
        args=([sys.executable, "-c", script],),
    )
    t.start()

    try:
        deadline = time.monotonic() + 10.0
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists(), "child did not start in time"
        child_pid = int(ready.read_text().strip())

        st_running = stage.status()
        while st_running["pid"] != child_pid and time.monotonic() < deadline:
            time.sleep(0.02)
            st_running = stage.status()
        assert st_running["state"] == STATE_RUNNING
        assert st_running["pid"] == child_pid
        assert st_running["stage_id"] == "test-adopt"
        assert st_running["session_id"] == "sess-adopt"
        assert st_running["attempt"] == 1
        assert t.is_alive()

        events = stage.events(type="heartbeat")
        assert len(events) == 1
        assert events[0] == {
            "ts": st_running["heartbeat_at"],
            "type": "heartbeat",
            "stage_id": st_running["stage_id"],
            "stage_name": st_running["stage_name"],
            "state": STATE_RUNNING,
            "attempt": st_running["attempt"],
            "message": f"adopted child pid {child_pid}",
            "detail": {
                "previous_pid": st0["pid"],
                "pid": child_pid,
                "pid_token": st_running["pid_token"],
            },
        }
    finally:
        stop.touch()
        t.join(timeout=10.0)
    assert not t.is_alive()

    st_done = stage.status()
    assert st_done["state"] == STATE_DONE
    assert st_done["pid"] == child_pid


def test_supervise_child_pid_reclaim_identity_coherent(
    stage: Stage, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor_pid = os.getpid()
    stage.start(stage="test-reclaim-child", pid=supervisor_pid)

    ready = tmp_path / "reclaim_ready.txt"
    script = (
        "import os, pathlib, time\n"
        f"pathlib.Path(r'{ready}').write_text(str(os.getpid()))\n"
        "while True:\n"
        "    time.sleep(0.05)\n"
    )

    t = threading.Thread(
        target=stage.supervise,
        args=([sys.executable, "-c", script],),
        kwargs={"every": 1.0},
    )
    t.start()

    deadline = time.monotonic() + 10.0
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert ready.exists()
    child_pid = int(ready.read_text().strip())
    assert child_pid != supervisor_pid

    st = stage.status()
    while st["pid"] != child_pid and time.monotonic() < deadline:
        time.sleep(0.02)
        st = stage.status()
    assert st["pid"] == child_pid
    assert st["state"] == STATE_RUNNING

    # Adopt heartbeat event recorded with previous supervisor pid and adopted child pid
    hb_events = stage.events(type="heartbeat")
    assert any(
        e.get("message") == f"adopted child pid {child_pid}"
        and e.get("detail", {}).get("pid") == child_pid
        and e.get("detail", {}).get("previous_pid") == supervisor_pid
        for e in hb_events
    )

    # Doctor reports ok while child alive and not stale
    diag = stage.diagnose(stale_after=10.0)
    assert diag["needs_reclaim"] is False
    assert diag["ok"] is True

    # Make stage stale to trigger needs_reclaim without killing child
    with stage._store.locked(exclusive=True):
        cur = stage._store.read_status()
        cur["heartbeat_at"] = "2020-01-01T00:00:00+00:00"
        stage._store.write_status(cur)

    diag_stale = stage.diagnose(stale_after=10.0)
    assert diag_stale["needs_reclaim"] is True

    # Assert STATUS pid was adopted child before reclaim
    assert stage.status()["pid"] == child_pid

    # Intercept signal delivery to verify target PID is child_pid, not supervisor_pid
    signals_sent: list[tuple[int, int]] = []
    orig_kill = os.kill

    def tracking_kill(pid: int, sig: int) -> None:
        if sig != 0:
            signals_sent.append((pid, sig))
        orig_kill(pid, sig)

    monkeypatch.setattr(os, "kill", tracking_kill)

    # Reclaim with --kill: checks token identity and terminates the child worker process
    rec = stage.reclaim(reason="stale worker terminated", kill=True)
    assert rec["state"] == STATE_QUEUED

    # Signals targeted the adopted child, never the supervisor process
    assert len(signals_sent) >= 1
    assert all(target_pid == child_pid for target_pid, _ in signals_sent)
    assert supervisor_pid not in [target_pid for target_pid, _ in signals_sent]
    assert (child_pid, signal.SIGTERM) in signals_sent

    # Supervisor thread joins because child was terminated
    t.join(timeout=10.0)
    assert not t.is_alive()
    assert stage.status()["state"] == STATE_FAILED



def test_supervise_token_capture_failure_fallback(
    stage: Stage, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage.start(stage="test-token-fallback", pid=999999)
    monkeypatch.setattr("stage_signal.stage._pid_token", lambda pid: None)
    code = stage.supervise([sys.executable, "-c", "pass"])
    assert code == 0
    st = stage.status()
    assert st["state"] == STATE_DONE
    assert st["pid"] is not None
    assert st["pid"] != 999999
    assert st["pid_token"] is None
    events = stage.events(type="heartbeat")
    assert len(events) == 1
    assert events[0]["detail"] == {
        "previous_pid": 999999,
        "pid": st["pid"],
        "pid_token": None,
    }


def test_cli_supervise_adopts_child_pid(stage: Stage, tmp_path: Path) -> None:
    stage.start(stage="cli-adopt", pid=999999, session_id="cli-sess-456")
    ready = tmp_path / "cli_ready.txt"
    stop = tmp_path / "cli_stop.txt"
    script = (
        "import os, pathlib, time\n"
        f"pathlib.Path(r'{ready}').write_text(str(os.getpid()))\n"
        f"while not pathlib.Path(r'{stop}').exists():\n"
        "    time.sleep(0.02)\n"
    )

    t = threading.Thread(
        target=main,
        args=([
            "--dir", str(stage.dir),
            "supervise", "--",
            sys.executable, "-c", script,
        ],),
    )
    t.start()

    deadline = time.monotonic() + 10.0
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert ready.exists()
    child_pid = int(ready.read_text().strip())

    st = stage.status()
    assert st["pid"] == child_pid
    assert st["session_id"] == "cli-sess-456"
    assert st["stage_id"] == "cli-adopt"

    stop.touch()
    t.join(timeout=10.0)
    assert not t.is_alive()
    assert stage.status()["state"] == STATE_DONE


def test_cli_supervise_reclaim_kill_signals_adopted_child(
    stage: Stage, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor_pid = os.getpid()
    stage.start(stage="cli-reclaim-adopt", pid=supervisor_pid, session_id="cli-reclaim-sess")
    ready = tmp_path / "cli_reclaim_ready.txt"
    script = (
        "import os, pathlib, time\n"
        f"pathlib.Path(r'{ready}').write_text(str(os.getpid()))\n"
        "while True:\n"
        "    time.sleep(0.05)\n"
    )

    t = threading.Thread(
        target=main,
        args=([
            "--dir", str(stage.dir),
            "supervise", "--",
            sys.executable, "-c", script,
        ],),
    )
    t.start()

    deadline = time.monotonic() + 10.0
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert ready.exists()
    child_pid = int(ready.read_text().strip())
    assert child_pid != supervisor_pid

    st = stage.status()
    while st["pid"] != child_pid and time.monotonic() < deadline:
        time.sleep(0.02)
        st = stage.status()
    assert st["pid"] == child_pid
    assert st["state"] == STATE_RUNNING

    # Adopt heartbeat event recorded
    events = stage.events(type="heartbeat")
    assert any(
        e.get("message") == f"adopted child pid {child_pid}"
        and e.get("detail", {}).get("pid") == child_pid
        and e.get("detail", {}).get("previous_pid") == supervisor_pid
        for e in events
    )

    # Force needs_reclaim via stale heartbeat without killing child yet
    with stage._store.locked(exclusive=True):
        cur = stage._store.read_status()
        cur["heartbeat_at"] = "2020-01-01T00:00:00+00:00"
        stage._store.write_status(cur)

    assert stage.diagnose(stale_after=10.0)["needs_reclaim"] is True
    # Child PID preserved in STATUS right before reclaim
    assert stage.status()["pid"] == child_pid

    signals_sent: list[tuple[int, int]] = []
    orig_kill = os.kill

    def tracking_kill(pid: int, sig: int) -> None:
        if sig != 0:
            signals_sent.append((pid, sig))
        orig_kill(pid, sig)

    monkeypatch.setattr(os, "kill", tracking_kill)

    exit_code = main([
        "--dir", str(stage.dir),
        "reclaim", "--reason", "stale adopted worker via cli", "--kill",
    ])
    assert exit_code == 0

    assert len(signals_sent) >= 1
    assert all(target_pid == child_pid for target_pid, _ in signals_sent)
    assert supervisor_pid not in [target_pid for target_pid, _ in signals_sent]
    assert (child_pid, signal.SIGTERM) in signals_sent

    t.join(timeout=10.0)
    assert not t.is_alive()
    assert stage.status()["state"] == STATE_FAILED


