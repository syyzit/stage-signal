"""SPEC-gap regression tests: proof lifecycle, git-branch, exit codes, mirror, retry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stage_signal import CorruptStatusError, Stage
from stage_signal.cli import main


@pytest.fixture()
def sdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    monkeypatch.delenv("STAGE_SIGNAL_STATUS_MIRROR", raising=False)
    monkeypatch.delenv("STAGE_SIGNAL_PROOF_REF", raising=False)
    assert main(["init", "--project", "p"]) == 0
    return d


def test_proof_cleared_on_start(sdir: Path) -> None:
    s = Stage(str(sdir))
    s.start(stage="m1")
    s.done(summary="ok", proof_ref="ledger/123")
    assert s.status()["proof"]["ref"] == "ledger/123"
    nxt = s.start(stage="m2")
    assert nxt["proof"] is None
    assert nxt["state"] == "running"
    # same-stage retry also clears (new attempt starts clean)
    s.done(summary="ok2", proof_ref="ledger/456")
    retry = s.start(stage="m2")
    assert retry["proof"] is None
    assert retry["attempt"] == 2


def test_notes_preserved_artifacts_cleared_on_new_stage(sdir: Path) -> None:
    s = Stage(str(sdir))
    s.start(stage="m1")
    s.note("hello")
    s.artifact("a.txt")
    nxt = s.start(stage="m2")
    assert [n["text"] for n in nxt["notes"]] == ["hello"]
    assert nxt["artifacts"] == []


def test_schema_version_unsupported_is_exit_1(sdir: Path) -> None:
    (sdir / "STATUS.json").write_text('{"schema_version": 99}\n')
    with pytest.raises(CorruptStatusError) as exc:
        Stage(str(sdir)).status()
    assert exc.value.exit_code == 1


def test_cli_schema_version_exits_1(sdir: Path, capsys) -> None:
    (sdir / "STATUS.json").write_text('{"schema_version": 99}\n')
    capsys.readouterr()
    assert main(["status"]) == 1


def test_cli_start_git_branch(sdir: Path) -> None:
    assert main(["start", "--stage", "m", "--git-branch", "feat-x"]) == 0
    st = Stage(str(sdir)).status()
    assert st["git_branch"] == "feat-x"
    assert st["stage_id"] == "m"  # defaults to stage_name


def test_cli_status_exit_codes(sdir: Path, capsys) -> None:
    capsys.readouterr()
    assert main(["status"]) == 13  # queued
    assert main(["start", "--stage", "m"]) == 0
    capsys.readouterr()
    assert main(["status"]) == 10
    assert main(["status", "--json"]) == 10
    assert main(["done", "--summary", "ok"]) == 0
    capsys.readouterr()
    assert main(["status"]) == 0
    assert main(["start", "--stage", "m"]) == 0
    assert main(["blocked", "--reason", "x"]) == 0
    capsys.readouterr()
    assert main(["status"]) == 11
    assert main(["start", "--stage", "m"]) == 0
    assert main(["fail", "--reason", "boom"]) == 0
    capsys.readouterr()
    assert main(["status"]) == 12


def test_cli_wait_mismatch_timeout_not_initialized(
    sdir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert main(["start", "--stage", "m"]) == 0
    assert main(["blocked", "--reason", "stalled"]) == 0
    # wait --state done against blocked must report 11 immediately
    assert main(["wait", "--state", "done", "--timeout", "5", "--poll", "0.05"]) == 11
    # wait for the matching terminal state exits 0
    assert main(["wait", "--state", "blocked", "--timeout", "5"]) == 0
    # running with short timeout -> 14
    assert main(["start", "--stage", "m"]) == 0
    assert main(["wait", "--state", "done", "--timeout", "0.2", "--poll", "0.05"]) == 14
    # uninitialized dir -> 15
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(tmp_path / "nope" / ".stage-signal"))
    assert main(["wait", "--state", "terminal", "--timeout", "1"]) == 15
    assert main(["wait", "--json", "--state", "terminal", "--timeout", "1"]) == 15
    assert main(["status"]) == 15


def test_cli_clear_terminal_and_doctor(sdir: Path, capsys) -> None:
    assert main(["start", "--stage", "m"]) == 0
    assert main(["done", "--summary", "ok"]) == 0
    assert main(["clear-terminal"]) == 0
    assert Stage(str(sdir)).status()["state"] == "queued"
    capsys.readouterr()
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "OK" in out
    # stale warning still exits 0
    assert main(["start", "--stage", "m"]) == 0
    capsys.readouterr()
    assert main(["doctor", "--stale-after", "0"]) == 0
    out2 = capsys.readouterr().out
    assert "STALE" in out2


def test_cli_init_corrupt_fails_1(sdir: Path, capsys) -> None:
    (sdir / "STATUS.json").write_text("{not json")
    capsys.readouterr()
    assert main(["init"]) == 1


def test_cli_proof_ref_and_require_proof_gate(sdir: Path, tmp_path: Path, capsys) -> None:
    assert main(["start", "--stage", "m"]) == 0
    assert main(["done", "--summary", "ok", "--proof-ref", "ledger/123"]) == 0
    assert Stage(str(sdir)).status()["proof"] == {
        "tool": "agent-done-or-not",
        "ref": "ledger/123",
        "verified": None,
    }
    # require-proof without ref fails closed, exit 3, no mutation
    assert main(["start", "--stage", "m2"]) == 0
    capsys.readouterr()
    assert main(["done", "--summary", "ok", "--require-proof"]) == 3
    assert Stage(str(sdir)).status()["state"] == "running"
    # require-proof with real non-empty file passes
    receipt = tmp_path / "receipt.json"
    receipt.write_text('{"ok": true}\n')
    assert (
        main(["done", "--summary", "ok", "--proof-ref", str(receipt), "--require-proof"])
        == 0
    )
    assert Stage(str(sdir)).status()["proof"]["verified"] == "file"


def test_status_mirror_writes_orch_and_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    assert main(["init", "--project", "p"]) == 0
    assert main(["start", "--stage", "m", "--write-status-mirror"]) == 0
    mirror = tmp_path / ".orch" / "STATUS.md"
    assert mirror.is_file()
    assert "state: running" in mirror.read_text()
    assert main(["done", "--summary", "ok", "--write-status-mirror"]) == 0
    assert (tmp_path / ".orch" / "DONE").is_file()
    # env var enables the mirror too
    monkeypatch.setenv("STAGE_SIGNAL_STATUS_MIRROR", "1")
    assert main(["start", "--stage", "m2"]) == 0
    assert "state: running" in mirror.read_text()


def test_status_mirror_failure_warns_but_succeeds(
    sdir: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    import stage_signal.stage as stmod

    monkeypatch.setattr(stmod, "write_status_mirror", lambda *a, **k: None)
    capsys.readouterr()
    assert main(["start", "--stage", "m", "--write-status-mirror"]) == 0
    err = capsys.readouterr().err
    assert "mirror failed" in err
    assert Stage(str(sdir)).status()["state"] == "running"


def test_read_status_retries_torn_read_once(sdir: Path, monkeypatch) -> None:
    from pathlib import Path as _Path

    status_path = sdir / "STATUS.json"
    good = status_path.read_text(encoding="utf-8")
    calls = {"n": 0}
    orig = _Path.read_text

    def flaky(self, *args, **kwargs):
        if self == status_path and calls["n"] == 0:
            calls["n"] += 1
            return "{truncated"
        return orig(self, *args, **kwargs)

    monkeypatch.setattr(_Path, "read_text", flaky)
    st = Stage(str(sdir)).start(stage="m")
    assert st["state"] == "running"
    assert calls["n"] == 1
    assert json.loads(good)["project"] == "p"


def test_pytest_timeout_plugin_installed_and_aborts_hanging_test(tmp_path: Path) -> None:
    import subprocess
    import sys
    import pytest_timeout

    assert pytest_timeout is not None
    test_file = tmp_path / "test_hanging.py"
    test_file.write_text("import time\ndef test_slow():\n    time.sleep(2)\n")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--timeout=1",
            "--timeout-method=thread",
            str(test_file),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "Timeout" in proc.stdout or "Timeout" in proc.stderr

