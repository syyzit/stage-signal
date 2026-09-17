"""Unit tests for the stage_signal core library (M1)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from stage_signal import (
    BadArgsError,
    CorruptStatusError,
    IllegalTransition,
    NotInitialized,
    Stage,
    WaitTimeout,
    state_exit_code,
    verify_proof,
)


@pytest.fixture()
def stage_dir(tmp_path: Path) -> Path:
    return tmp_path / ".stage-signal"


@pytest.fixture()
def stage(stage_dir: Path) -> Stage:
    s = Stage(stage_dir)
    s.init(project="testproj")
    return s


def test_init_creates_queued_status(stage_dir: Path) -> None:
    s = Stage(stage_dir)
    st = s.init(project="p")
    assert st["state"] == "queued"
    assert st["schema_version"] == 1
    assert st["project"] == "p"
    assert st["stage_id"] is None
    assert (stage_dir / "STATUS.json").is_file()
    assert (stage_dir / "STATUS.md").is_file()
    assert (stage_dir / "events.jsonl").is_file()
    # idempotent: second init keeps existing status
    st2 = s.init(project="other")
    assert st2["project"] == "p"


def test_init_env_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAGE_SIGNAL_PROJECT", "envproj")
    s = Stage(tmp_path / ".stage-signal")
    assert s.init()["project"] == "envproj"


def test_not_initialized(tmp_path: Path) -> None:
    s = Stage(tmp_path / ".stage-signal")
    with pytest.raises(NotInitialized) as exc:
        s.status()
    assert exc.value.exit_code == 15


def test_start_from_any_state(stage: Stage) -> None:
    st = stage.start(stage="m1", session_id="ses_1")
    assert st["state"] == "running"
    assert st["stage_id"] == "m1"
    assert st["attempt"] == 1
    assert st["session_id"] == "ses_1"
    assert st["started_at"]
    assert st["heartbeat_at"]
    # same stage_id retry bumps attempt, keeps artifacts
    stage.artifact("a.txt")
    st2 = stage.start(stage="m1")
    assert st2["attempt"] == 2
    assert [a["path"] for a in st2["artifacts"]] == ["a.txt"]
    # new stage resets attempt + artifacts, clears terminal
    stage.done(summary="ok")
    st3 = stage.start(stage="m2")
    assert st3["state"] == "running"
    assert st3["attempt"] == 1
    assert st3["artifacts"] == []
    assert st3["result"] is None


def test_start_validates_args(stage: Stage) -> None:
    with pytest.raises(BadArgsError):
        stage.start(stage="  ")
    with pytest.raises(BadArgsError):
        stage.start(stage="m", pid=-1)


def test_heartbeat_only_running(stage: Stage) -> None:
    with pytest.raises(IllegalTransition) as exc:
        stage.heartbeat()
    assert exc.value.exit_code == 3
    stage.start(stage="m")
    st = stage.heartbeat(note="progress")
    assert st["heartbeat_note"] == "progress"
    assert st["heartbeat_at"]


def test_note_and_artifact(stage: Stage) -> None:
    with pytest.raises(IllegalTransition):
        stage.note("x")
    with pytest.raises(BadArgsError):
        stage.note("  ")
    stage.start(stage="m")
    stage.note("checkpoint-1")
    st = stage.artifact("dist/app.whl", label="wheel")
    assert st["notes"][-1]["text"] == "checkpoint-1"
    assert st["artifacts"][-1] == {
        "path": "dist/app.whl",
        "label": "wheel",
        "added_at": st["artifacts"][-1]["added_at"],
    }
    with pytest.raises(BadArgsError):
        stage.artifact("  ")


def test_done_blocked_fail(stage: Stage) -> None:
    stage.start(stage="m")
    st = stage.done(summary="merged abc", git_head="abc")
    assert st["state"] == "done"
    assert st["result"]["summary"] == "merged abc"
    assert st["git_head"] == "abc"
    assert st["error"] is None
    assert state_exit_code("done") == 0
    # idempotent repeat
    st2 = stage.done(summary="again")
    assert st2["state"] == "done"
    assert st2["result"]["summary"] == "again"
    # terminal -> different terminal is illegal
    with pytest.raises(IllegalTransition):
        stage.blocked("nope")
    with pytest.raises(IllegalTransition):
        stage.fail("nope")
    # new attempt via start, then blocked
    stage.start(stage="m")
    st3 = stage.blocked("free-tier stall")
    assert st3["state"] == "blocked"
    assert st3["error"]["reason"] == "free-tier stall"
    assert state_exit_code("blocked") == 11
    stage.start(stage="m")
    st4 = stage.fail("boom")
    assert st4["state"] == "failed"
    assert state_exit_code("failed") == 12
    # blocked/fail require reasons
    stage.start(stage="m")
    with pytest.raises(BadArgsError):
        stage.blocked(" ")
    with pytest.raises(BadArgsError):
        stage.fail("")


def test_fail_if_dead_pid(stage: Stage) -> None:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait(timeout=10)
    stage.start(stage="m", pid=process.pid)

    st = stage.fail("worker exited", if_dead_pid=True)

    assert st["state"] == "failed"
    assert st["error"]["reason"] == "worker exited"
    assert st["error"]["finished_at"]
    events = [json.loads(line) for line in (stage.dir / "events.jsonl").read_text().splitlines()]
    assert events[-1]["type"] == "failed"
    assert events[-1]["message"] == "worker exited"


def test_fail_if_dead_pid_live_no_mutation(stage: Stage) -> None:
    stage.start(stage="m", pid=os.getpid())
    before = {name: (stage.dir / name).read_bytes() for name in ("STATUS.json", "STATUS.md", "events.jsonl")}

    with pytest.raises(IllegalTransition, match="is alive") as exc:
        stage.fail("worker exited", if_dead_pid=True, write_status_mirror=True)

    assert exc.value.exit_code == 3
    assert {name: (stage.dir / name).read_bytes() for name in before} == before
    assert not (stage.dir.parent / ".orch").exists()


@pytest.mark.parametrize("pid", [None, True, False, 0, -1, "123", 1.5, [], {}])
def test_fail_if_dead_pid_invalid_no_mutation(stage: Stage, monkeypatch: pytest.MonkeyPatch, pid) -> None:
    status = stage.start(stage="m")
    status["pid"] = pid
    (stage.dir / "STATUS.json").write_text(json.dumps(status))
    before = {name: (stage.dir / name).read_bytes() for name in ("STATUS.json", "STATUS.md", "events.jsonl")}

    def unexpected_probe(pid):
        pytest.fail("invalid pid must not be probed")

    monkeypatch.setattr("stage_signal.stage._is_pid_alive", unexpected_probe)
    with pytest.raises(IllegalTransition, match="valid positive integer"):
        stage.fail("worker exited", if_dead_pid=True)

    assert {name: (stage.dir / name).read_bytes() for name in before} == before


@pytest.mark.parametrize("state", ["queued", "done", "blocked", "failed"])
def test_fail_if_dead_pid_non_running_normal_rules(stage: Stage, monkeypatch: pytest.MonkeyPatch, state: str) -> None:
    if state == "done":
        stage.done()
    elif state == "blocked":
        stage.blocked("waiting")
    elif state == "failed":
        stage.fail("previous failure")
    before = {name: (stage.dir / name).read_bytes() for name in ("STATUS.json", "STATUS.md", "events.jsonl")}

    def unexpected_probe(pid):
        pytest.fail("non-running states must not probe pid")

    monkeypatch.setattr("stage_signal.stage._is_pid_alive", unexpected_probe)
    if state in ("queued", "failed"):
        st = stage.fail("new failure", if_dead_pid=True)
        assert st["state"] == "failed"
        assert st["error"]["reason"] == "new failure"
    else:
        with pytest.raises(IllegalTransition):
            stage.fail("new failure", if_dead_pid=True)
        assert {name: (stage.dir / name).read_bytes() for name in before} == before


def test_fail_if_needs_reclaim_dead_pid(stage: Stage) -> None:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait(timeout=10)
    stage.start(stage="m", pid=process.pid)

    st = stage.fail("worker exited", if_needs_reclaim=True)

    assert st["state"] == "failed"
    assert st["error"]["reason"] == "worker exited"
    events = [json.loads(line) for line in (stage.dir / "events.jsonl").read_text().splitlines()]
    assert events[-1]["type"] == "failed"
    assert events[-1]["message"] == "worker exited"


def test_fail_if_needs_reclaim_stale_heartbeat(stage: Stage) -> None:
    stage.start(stage="m", pid=os.getpid())
    status_file = stage.dir / "STATUS.json"
    raw = json.loads(status_file.read_text(encoding="utf-8"))
    raw["heartbeat_at"] = "2000-01-01T00:00:00+00:00"
    status_file.write_text(json.dumps(raw), encoding="utf-8")

    st = stage.fail("stale runner", if_needs_reclaim=True)

    assert st["state"] == "failed"
    assert st["error"]["reason"] == "stale runner"
    events = [json.loads(line) for line in (stage.dir / "events.jsonl").read_text().splitlines()]
    assert events[-1]["type"] == "failed"
    assert events[-1]["message"] == "stale runner"


def test_fail_if_needs_reclaim_dead_pid_and_stale(stage: Stage) -> None:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait(timeout=10)
    stage.start(stage="m", pid=process.pid)
    status_file = stage.dir / "STATUS.json"
    raw = json.loads(status_file.read_text(encoding="utf-8"))
    raw["heartbeat_at"] = "2000-01-01T00:00:00+00:00"
    status_file.write_text(json.dumps(raw), encoding="utf-8")

    st = stage.fail("dead and stale", if_needs_reclaim=True)

    assert st["state"] == "failed"
    assert st["error"]["reason"] == "dead and stale"


def test_fail_if_needs_reclaim_healthy_running_no_mutation(stage: Stage) -> None:
    stage.start(stage="m", pid=os.getpid())
    before = {name: (stage.dir / name).read_bytes() for name in ("STATUS.json", "STATUS.md", "events.jsonl")}

    with pytest.raises(IllegalTransition, match="needs_reclaim is false") as exc:
        stage.fail("not reclaimable", if_needs_reclaim=True)

    assert exc.value.exit_code == 3
    assert {name: (stage.dir / name).read_bytes() for name in before} == before


@pytest.mark.parametrize("state", ["queued", "done", "blocked", "failed"])
def test_fail_if_needs_reclaim_non_running_no_mutation(
    stage: Stage, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    if state == "done":
        stage.done()
    elif state == "blocked":
        stage.blocked("waiting")
    elif state == "failed":
        stage.fail("previous failure")
    before = {name: (stage.dir / name).read_bytes() for name in ("STATUS.json", "STATUS.md", "events.jsonl")}

    def unexpected_probe(pid):
        pytest.fail("non-running --if-needs-reclaim must not probe pid")

    monkeypatch.setattr("stage_signal.stage._is_pid_alive", unexpected_probe)
    with pytest.raises(IllegalTransition, match="needs_reclaim is false") as exc:
        stage.fail("not reclaimable", if_needs_reclaim=True)

    assert exc.value.exit_code == 3
    assert {name: (stage.dir / name).read_bytes() for name in before} == before


def test_fail_if_needs_reclaim_mutually_exclusive_with_if_dead_pid(stage: Stage) -> None:
    stage.start(stage="m", pid=os.getpid())
    before = {name: (stage.dir / name).read_bytes() for name in ("STATUS.json", "STATUS.md", "events.jsonl")}

    with pytest.raises(BadArgsError, match="mutually exclusive"):
        stage.fail("x", if_dead_pid=True, if_needs_reclaim=True)

    assert {name: (stage.dir / name).read_bytes() for name in before} == before


def test_clear_terminal(stage: Stage) -> None:
    st0 = stage.clear_terminal()  # queued is allowed (abandon/reset)
    assert st0["state"] == "queued"
    assert st0["stage_name"] is None
    stage.start(stage="m")
    with pytest.raises(IllegalTransition, match="running"):
        stage.clear_terminal()  # running still illegal
    stage.done(summary="ok")
    st = stage.clear_terminal()
    assert st["state"] == "queued"
    assert st["result"] is None


def test_done_from_queued_allowed(stage: Stage) -> None:
    st = stage.done(summary="fast-path")
    assert st["state"] == "done"


def test_proof_ref_recorded(stage: Stage) -> None:
    stage.start(stage="m")
    st = stage.done(summary="ok", proof_ref="ledger/123")
    assert st["proof"] == {
        "tool": "agent-done-or-not",
        "ref": "ledger/123",
        "verified": None,
    }


def test_require_proof_file_gate(tmp_path: Path, stage: Stage) -> None:
    stage.start(stage="m")
    receipt = tmp_path / "receipt.json"
    receipt.write_text('{"ok": true}\n')
    st = stage.done(summary="ok", proof_ref=str(receipt), require_proof=True)
    assert st["state"] == "done"
    assert st["proof"]["verified"] == "file"
    # missing file + no binary on PATH -> fail closed, no mutation
    stage.start(stage="m2")
    with pytest.raises(IllegalTransition):
        stage.done(
            summary="ok", proof_ref=str(tmp_path / "nope.json"),
            require_proof=True,
        )
    assert stage.status()["state"] == "running"
    # empty file fails
    empty = tmp_path / "empty.json"
    empty.write_text("")
    with pytest.raises(IllegalTransition):
        stage.done(summary="ok", proof_ref=str(empty), require_proof=True)
    # no ref at all fails
    with pytest.raises(IllegalTransition):
        stage.done(summary="ok", require_proof=True)


def test_require_proof_delegates_to_binary(
    tmp_path: Path, stage: Stage, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("STAGE_SIGNAL_PROOF_REF", raising=False)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    fake_sh = bin_dir / "agent-done-or-not"
    fake_sh.write_text("#!/bin/sh\nexit 0\n")
    try:
        fake_sh.chmod(0o755)
    except OSError:
        pass
    fake_cmd = bin_dir / "agent-done-or-not.cmd"
    fake_cmd.write_text("@echo off\nexit /b 0\n")
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    stage.start(stage="m")
    st = stage.done(summary="ok", proof_ref="some-ref", require_proof=True)
    assert st["proof"]["verified"] == "verify"


def test_require_proof_delegates_to_binary_failure(
    tmp_path: Path, stage: Stage, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("STAGE_SIGNAL_PROOF_REF", raising=False)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    fake_sh = bin_dir / "agent-done-or-not"
    fake_sh.write_text("#!/bin/sh\necho 'rejection reason' >&2\nexit 1\n")
    try:
        fake_sh.chmod(0o755)
    except OSError:
        pass
    fake_cmd = bin_dir / "agent-done-or-not.cmd"
    fake_cmd.write_text("@echo rejection reason 1>&2\n@exit /b 1\n")
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    stage.start(stage="m")
    with pytest.raises(IllegalTransition, match="agent-done-or-not verify exited 1: rejection reason"):
        stage.done(summary="ok", proof_ref="some-ref", require_proof=True)


def test_verify_proof_windows_cmd_delegation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STAGE_SIGNAL_PROOF_REF", raising=False)
    monkeypatch.setattr("stage_signal.stage.sys.platform", "win32")
    monkeypatch.setattr(
        "shutil.which",
        lambda cmd: r"C:\tools\agent-done-or-not.cmd" if cmd == "agent-done-or-not" else None,
    )
    monkeypatch.setenv("COMSPEC", r"C:\Windows\System32\cmd.exe")
    called_cmd: list[list[str]] = []

    class FakeProc:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, capture_output, text, timeout):
        called_cmd.append(cmd)
        return FakeProc()

    monkeypatch.setattr("subprocess.run", fake_run)
    res = verify_proof("ref-123")
    assert res == {"tool": "agent-done-or-not", "ref": "ref-123", "verified": "verify"}
    assert called_cmd == [
        [r"C:\Windows\System32\cmd.exe", "/c", r"C:\tools\agent-done-or-not.cmd", "verify", "--ref", "ref-123"]
    ]


def test_verify_proof_windows_exe_delegation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STAGE_SIGNAL_PROOF_REF", raising=False)
    monkeypatch.setattr("stage_signal.stage.sys.platform", "win32")
    monkeypatch.setattr(
        "shutil.which",
        lambda cmd: r"C:\tools\agent-done-or-not.exe" if cmd == "agent-done-or-not" else None,
    )
    called_cmd: list[list[str]] = []

    class FakeProc:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, capture_output, text, timeout):
        called_cmd.append(cmd)
        return FakeProc()

    monkeypatch.setattr("subprocess.run", fake_run)
    res = verify_proof("ref-123")
    assert res == {"tool": "agent-done-or-not", "ref": "ref-123", "verified": "verify"}
    assert called_cmd == [[r"C:\tools\agent-done-or-not.exe", "verify", "--ref", "ref-123"]]


def test_events_appended(stage: Stage, stage_dir: Path) -> None:
    stage.start(stage="m")
    stage.heartbeat(note="n")
    stage.note("hello")
    stage.artifact("f.bin")
    stage.done(summary="ok")
    lines = (stage_dir / "events.jsonl").read_text().strip().splitlines()
    types = [json.loads(line)["type"] for line in lines]
    assert types == ["init", "start", "heartbeat", "note", "artifact", "done"]
    for line in lines:
        obj = json.loads(line)
        assert obj["ts"] and obj["state"] and obj["attempt"] >= 1


def test_corrupt_status(tmp_path: Path) -> None:
    d = tmp_path / ".stage-signal"
    s = Stage(d)
    s.init(project="p")
    (d / "STATUS.json").write_text("{not json")
    with pytest.raises(CorruptStatusError):
        s.status()
    (d / "STATUS.json").write_text('{"schema_version": 99}')
    with pytest.raises(CorruptStatusError):
        s.status()


def test_wait_terminal_and_specific(stage: Stage) -> None:
    import threading

    stage.start(stage="m")
    result: dict = {}

    def finish() -> None:
        import time

        time.sleep(0.3)
        Stage(stage.dir).done(summary="bg done")

    t = threading.Thread(target=finish)
    t.start()
    out = stage.wait("terminal", timeout=10, poll=0.05)
    t.join()
    assert out["state"] == "done"
    result["ok"] = True
    assert result["ok"]

    stage.start(stage="m")
    Stage(stage.dir).blocked("stalled")
    out2 = stage.wait("blocked", timeout=5, poll=0.05)
    assert out2["state"] == "blocked"


def test_wait_terminal_mismatch_returns_immediately(stage: Stage) -> None:
    import time

    stage.start(stage="m")
    stage.blocked("stalled")
    started = time.monotonic()
    out = stage.wait("done", timeout=30, poll=0.5)
    assert out["state"] == "blocked"
    assert time.monotonic() - started < 5


def test_wait_timeout(stage: Stage) -> None:
    stage.start(stage="m")
    with pytest.raises(WaitTimeout) as exc:
        stage.wait("done", timeout=0.2, poll=0.05)
    assert exc.value.exit_code == 14
    assert exc.value.last_status["state"] == "running"


def test_wait_validates(stage: Stage) -> None:
    with pytest.raises(BadArgsError):
        stage.wait("bogus", timeout=1)
    with pytest.raises(BadArgsError):
        stage.wait("terminal", timeout=0)
    with pytest.raises(BadArgsError, match="cannot be combined"):
        stage.wait("done", timeout=1, needs_reclaim=True)


def test_wait_needs_reclaim_dead_pid(stage: Stage) -> None:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait(timeout=10)
    stage.start(stage="m", pid=process.pid)
    started = time.monotonic()
    out = stage.wait(timeout=5, poll=0.05, needs_reclaim=True)
    assert time.monotonic() - started < 2
    assert out["state"] == "running"
    assert out["needs_reclaim"] is True


def test_wait_needs_reclaim_stale_heartbeat(stage: Stage) -> None:
    stage.start(stage="m", pid=os.getpid())
    status_file = stage.dir / "STATUS.json"
    raw = json.loads(status_file.read_text(encoding="utf-8"))
    raw["heartbeat_at"] = "2000-01-01T00:00:00+00:00"
    status_file.write_text(json.dumps(raw), encoding="utf-8")
    out = stage.wait(timeout=5, poll=0.05, needs_reclaim=True)
    assert out["state"] == "running"
    assert out["needs_reclaim"] is True


def test_wait_needs_reclaim_polls_until_stale(stage: Stage) -> None:
    import threading

    stage.start(stage="m", pid=os.getpid())
    assert stage.status()["needs_reclaim"] is False

    def stale() -> None:
        time.sleep(0.15)
        status_file = stage.dir / "STATUS.json"
        raw = json.loads(status_file.read_text(encoding="utf-8"))
        raw["heartbeat_at"] = "2000-01-01T00:00:00+00:00"
        status_file.write_text(json.dumps(raw), encoding="utf-8")

    t = threading.Thread(target=stale)
    t.start()
    out = stage.wait(timeout=5, poll=0.05, needs_reclaim=True)
    t.join()
    assert out["state"] == "running"
    assert out["needs_reclaim"] is True


def test_wait_needs_reclaim_healthy_running_times_out(stage: Stage) -> None:
    stage.start(stage="m", pid=os.getpid())
    with pytest.raises(WaitTimeout) as exc:
        stage.wait(timeout=0.2, poll=0.05, needs_reclaim=True)
    assert exc.value.exit_code == 14
    assert exc.value.last_status["state"] == "running"
    assert exc.value.last_status["needs_reclaim"] is False


@pytest.mark.parametrize("setup", ["done", "blocked", "failed"])
def test_wait_needs_reclaim_terminal_without_reclaim_returns(
    stage: Stage, setup: str
) -> None:
    if setup == "done":
        stage.done()
    elif setup == "blocked":
        stage.blocked("waiting")
    else:
        stage.fail("previous")
    started = time.monotonic()
    out = stage.wait(timeout=30, poll=0.5, needs_reclaim=True)
    assert time.monotonic() - started < 5
    assert out["state"] == setup
    assert out["needs_reclaim"] is False


def test_wait_needs_reclaim_not_initialized(stage_dir: Path) -> None:
    s = Stage(stage_dir)
    with pytest.raises(NotInitialized) as exc:
        s.wait(timeout=1, poll=0.05, needs_reclaim=True)
    assert exc.value.exit_code == 15


@pytest.mark.parametrize("kind", ["dead_pid", "stale", "healthy", "done", "blocked", "failed"])
def test_wait_needs_reclaim_matches_status_and_doctor(stage: Stage, kind: str) -> None:
    """wait --needs-reclaim uses the same boolean as status/doctor."""
    if kind == "dead_pid":
        process = subprocess.Popen([sys.executable, "-c", "pass"])
        process.wait(timeout=10)
        stage.start(stage="m", pid=process.pid)
    elif kind == "stale":
        stage.start(stage="m", pid=os.getpid())
        status_file = stage.dir / "STATUS.json"
        raw = json.loads(status_file.read_text(encoding="utf-8"))
        raw["heartbeat_at"] = "2000-01-01T00:00:00+00:00"
        status_file.write_text(json.dumps(raw), encoding="utf-8")
    elif kind == "healthy":
        stage.start(stage="m", pid=os.getpid())
    elif kind == "done":
        stage.done()
    elif kind == "blocked":
        stage.blocked("waiting")
    else:
        stage.fail("previous")

    status = stage.status()
    diag = stage.diagnose()
    assert status["needs_reclaim"] is diag["needs_reclaim"]
    assert status["state"] == diag["state"]

    if diag["needs_reclaim"]:
        out = stage.wait(timeout=5, poll=0.05, needs_reclaim=True)
        assert out["needs_reclaim"] is True
        assert out["state"] == "running"
        return

    if status["state"] in ("done", "blocked", "failed"):
        started = time.monotonic()
        out = stage.wait(timeout=30, poll=0.5, needs_reclaim=True)
        assert time.monotonic() - started < 5
        assert out["needs_reclaim"] is False
        assert out["state"] == status["state"]
        return

    with pytest.raises(WaitTimeout) as exc:
        stage.wait(timeout=0.2, poll=0.05, needs_reclaim=True)
    assert exc.value.last_status["needs_reclaim"] is False
    assert exc.value.last_status["state"] == "running"


def test_diagnose(stage: Stage, stage_dir: Path) -> None:
    diag = stage.diagnose()
    assert diag["ok"] and not diag["problems"]
    assert diag["summary"] == "OK: queued"
    missing = Stage(stage_dir.parent / "nope" / ".stage-signal")
    diag2 = missing.diagnose()
    assert not diag2["ok"]
    assert diag2["summary"] is None
    stage.start(stage="m")
    diag3 = stage.diagnose(stale_after=10**9)
    assert diag3["ok"] and not diag3["warnings"]
    assert diag3["summary"] == "OK: running"
    diag4 = stage.diagnose(stale_after=0)
    assert diag4["ok"] and diag4["warnings"] and diag4["warnings"][0]["code"] == "STALE_HEARTBEAT"
    assert "STALE" in diag4["warnings"][0]["message"]
    assert diag4["summary"] == "ATTENTION: running needs reclaim"


def test_state_exit_codes() -> None:
    assert state_exit_code("running") == 10
    assert state_exit_code("blocked") == 11
    assert state_exit_code("failed") == 12
    assert state_exit_code("queued") == 13
    assert state_exit_code("done") == 0


def test_meta_clear_and_replace_on_start(stage: Stage) -> None:
    stage.start(stage="m", meta={"a": "1"})
    st = stage.start(stage="m", meta={"b": "2"})
    assert st["meta"] == {"b": "2"}
    st2 = stage.start(stage="m")
    assert st2["meta"] == {}


def test_status_md_mirror(stage: Stage, stage_dir: Path) -> None:
    stage.start(stage="m")
    md = (stage_dir / "STATUS.md").read_text()
    assert "state: running" in md


def test_dogfood_meta_cleared_on_new_stage(stage: Stage) -> None:
    # Repro from dogfood (issue #15): prior loop had owner and reason in meta
    stage.start(
        stage="clear-meta",
        meta={"owner": "OpenLoop", "reason": "no_module_named_pytest"},
    )
    st = stage.status()
    assert st["meta"] == {
        "owner": "OpenLoop",
        "reason": "no_module_named_pytest",
    }

    # Next start without --meta must clear old meta entirely
    st2 = stage.start(stage="other")
    assert st2["meta"] == {}

    # Another start with new meta must replace entirely without retaining old keys
    st3 = stage.start(stage="third", meta={"owner": "NewAgent"})
    assert st3["meta"] == {"owner": "NewAgent"}


def test_git_head_and_branch_refresh_on_start(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "commit 1"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    head1 = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    s = Stage(repo / ".stage-signal")
    s.init(project="test-repo")
    st1 = s.start(stage="stage-1")
    assert st1["git_head"] == head1
    assert st1["git_branch"] == "main"

    # Advance git repo with a new commit
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "commit 2"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    head2 = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert head1 != head2

    # Next stage start must reflect current HEAD, not previous stage SHA
    st2 = s.start(stage="stage-2")
    assert st2["git_head"] == head2
    assert st2["git_head"] != head1

    # Switch branch
    subprocess.run(
        ["git", "checkout", "-b", "feat-refresh"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    st3 = s.start(stage="stage-3")
    assert st3["git_branch"] == "feat-refresh"

    # Explicit override takes precedence
    st4 = s.start(
        stage="stage-4", git_head="customhead", git_branch="custombranch"
    )
    assert st4["git_head"] == "customhead"
    assert st4["git_branch"] == "custombranch"


def test_git_head_not_stale_in_non_git_repo(stage: Stage) -> None:
    # Explicit git_head in first stage
    st1 = stage.start(stage="s1", git_head="manual-sha")
    assert st1["git_head"] == "manual-sha"

    # Subsequent stage without explicit git_head must not retain stale SHA
    st2 = stage.start(stage="s2")
    assert st2["git_head"] is None


def test_clear_terminal_clears_to_idle_by_default(stage: Stage) -> None:
    stage.start(stage="m1", session_id="ses_1", pid=9999)
    stage.artifact("foo.txt", label="f")
    stage.fail(reason="boom")
    st = stage.clear_terminal()
    assert st["state"] == "queued"
    assert st["stage_id"] is None
    assert st["stage_name"] is None
    assert st["session_id"] is None
    assert st["pid"] is None
    assert st["started_at"] is None
    assert st["heartbeat_at"] is None
    assert st["heartbeat_note"] is None
    assert st["result"] is None
    assert st["error"] is None
    assert st["proof"] is None
    assert st["artifacts"] == []
    assert st["meta"] == {}
    events = stage.events()
    assert events[-1]["type"] == "clear_terminal"
    assert events[-1]["stage_id"] is None
    assert events[-1]["message"] == "cleared to idle queued"
    assert events[-1]["detail"] == {"keep_stage": False}


def test_clear_terminal_keep_stage(stage: Stage) -> None:
    stage.start(stage="m1", session_id="ses_1", pid=9999)
    stage.fail(reason="boom")
    st = stage.clear_terminal(keep_stage=True)
    assert st["state"] == "queued"
    assert st["stage_id"] == "m1"
    assert st["stage_name"] == "m1"
    assert st["session_id"] == "ses_1"
    assert st["result"] is None
    assert st["error"] is None
    events = stage.events()
    assert events[-1]["type"] == "clear_terminal"
    assert events[-1]["stage_id"] == "m1"
    assert events[-1]["message"] == "cleared to queued"
    assert events[-1]["detail"] == {"keep_stage": True}


def test_clear_terminal_abandons_named_queued(stage: Stage) -> None:
    stage.start(stage="parked", session_id="ses_parked", pid=42)
    stage.done(summary="park then abandon")
    named = stage.clear_terminal(keep_stage=True)
    assert named["state"] == "queued"
    assert named["stage_name"] == "parked"
    events_before = len(stage.events())

    st = stage.clear_terminal()

    assert st["state"] == "queued"
    assert st["stage_id"] is None
    assert st["stage_name"] is None
    assert st["pid"] is None
    assert st["session_id"] is None
    events = stage.events()
    assert len(events) == events_before + 1
    assert events[-1]["type"] == "clear_terminal"
    assert events[-1]["stage_id"] is None
    assert events[-1]["message"] == "cleared to idle queued"


def test_clear_terminal_running_still_illegal_even_with_dead_pid(stage: Stage) -> None:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait(timeout=10)
    stage.start(stage="m", pid=process.pid)
    before = {name: (stage.dir / name).read_bytes() for name in ("STATUS.json", "STATUS.md", "events.jsonl")}

    with pytest.raises(IllegalTransition, match="running"):
        stage.clear_terminal()

    assert {name: (stage.dir / name).read_bytes() for name in before} == before


def test_done_accept_failure(stage: Stage) -> None:
    stage.start(stage="m1")
    stage.fail(reason="failed build")

    # Regular done from failed is illegal
    with pytest.raises(IllegalTransition):
        stage.done(summary="cannot done from failed directly")

    # done with accept_failure=True succeeds
    st = stage.done(summary="accepted failed build", accept_failure=True)
    assert st["state"] == "done"
    assert st["result"]["summary"] == "accepted failed build"
    assert st["result"]["accepted_failure"] is True
    assert st["error"] is None
    events = stage.events()
    assert events[-1]["type"] == "done"
    assert events[-1]["detail"]["accepted_failure"] is True


def test_done_accept_failure_illegal_states(stage: Stage) -> None:
    # accept_failure=True is only allowed from failed
    # 1. From queued
    with pytest.raises(IllegalTransition, match="only allowed from state 'failed'"):
        stage.done(accept_failure=True)

    # 2. From running
    stage.start(stage="m2")
    with pytest.raises(IllegalTransition, match="only allowed from state 'failed'"):
        stage.done(accept_failure=True)

    # 3. From blocked
    stage.blocked(reason="waiting")
    with pytest.raises(IllegalTransition, match="only allowed from state 'failed'"):
        stage.done(accept_failure=True)

    # 4. From done
    stage.start(stage="m3")
    stage.done(summary="ok")
    with pytest.raises(IllegalTransition, match="only allowed from state 'failed'"):
        stage.done(accept_failure=True)

