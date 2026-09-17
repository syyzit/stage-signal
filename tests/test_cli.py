"""CLI contract tests for `start --meta` (K=V + raw JSON object)."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from stage_signal.cli import _parse_meta, build_parser, main
from stage_signal.errors import BadArgsError
from stage_signal import Stage


def test_cli_fail_if_dead_pid(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    stage = Stage(tmp_path / ".stage-signal")
    stage.init()
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait(timeout=10)
    stage.start(stage="m", pid=process.pid)

    assert main(["--dir", str(stage.dir), "fail", "--reason", "worker exited", "--if-dead-pid"]) == 0
    assert "failed" in capsys.readouterr().out
    assert stage.status()["state"] == "failed"
    assert stage.status()["error"]["reason"] == "worker exited"


@pytest.mark.parametrize("condition", ["live", "missing", "unknown"])
def test_cli_fail_if_dead_pid_refuses_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], condition: str
) -> None:
    stage = Stage(tmp_path / ".stage-signal")
    stage.init()
    status = stage.start(stage="m", pid=os.getpid())
    if condition == "missing":
        del status["pid"]
        (stage.dir / "STATUS.json").write_text(json.dumps(status))
    elif condition == "unknown":
        monkeypatch.setattr("stage_signal.stage._is_pid_alive", lambda pid: None)
    before = {name: (stage.dir / name).read_bytes() for name in ("STATUS.json", "STATUS.md", "events.jsonl")}

    expected_code = 1 if condition == "missing" else 3
    assert main(["--dir", str(stage.dir), "fail", "--reason", "worker exited", "--if-dead-pid"]) == expected_code
    expected_error = "missing keys: pid" if condition == "missing" else "fail --if-dead-pid"
    assert expected_error in capsys.readouterr().err
    assert {name: (stage.dir / name).read_bytes() for name in before} == before


def test_parse_meta_kv_basic() -> None:
    assert _parse_meta(["a=1", "b=2"]) == {"a": "1", "b": "2"}


def test_parse_meta_kv_value_may_contain_equals() -> None:
    assert _parse_meta(["url=a=b=c"]) == {"url": "a=b=c"}


def test_parse_meta_kv_empty_value_ok() -> None:
    assert _parse_meta(["k="]) == {"k": ""}


def test_parse_meta_json_object() -> None:
    assert _parse_meta(['{"ticket": 42, "flag": true}']) == {
        "ticket": 42,
        "flag": True,
    }


def test_parse_meta_json_types_preserved() -> None:
    meta = _parse_meta(['{"n": 1, "f": 1.5, "b": false, "z": null, "o": {"x": [1, 2]}}'])
    assert meta == {"n": 1, "f": 1.5, "b": False, "z": None, "o": {"x": [1, 2]}}


def test_parse_meta_mixed_and_later_wins() -> None:
    meta = _parse_meta(['{"a": 1, "b": 2}', "b=override", '{"a": 99}'])
    assert meta == {"a": 99, "b": "override"}


def test_parse_meta_empty_json_object_is_noop() -> None:
    assert _parse_meta(["{}"]) == {}


def test_parse_meta_rejects_bare_word() -> None:
    with pytest.raises(BadArgsError):
        _parse_meta(["justakey"])


def test_parse_meta_rejects_empty_key() -> None:
    with pytest.raises(BadArgsError):
        _parse_meta(["=v"])


def test_parse_meta_rejects_malformed_json() -> None:
    with pytest.raises(BadArgsError):
        _parse_meta(['{"a": 1'])


def test_parse_meta_rejects_non_object_json() -> None:
    for bad in ('[1, 2]', '"str"', "123", "true", "null"):
        with pytest.raises(BadArgsError):
            _parse_meta([bad])
    # JSON-looking array with leading whitespace still rejected as non-K=V.
    with pytest.raises(BadArgsError):
        _parse_meta(['  [1]'])


def test_start_help_documents_json() -> None:
    parser = build_parser()
    # --meta lives on the `start` subcommand, not top-level: inspect that parser.
    start_parser = None
    for action in parser._actions:
        if hasattr(action, "_name_parser_map") and "start" in action._name_parser_map:
            start_parser = action._name_parser_map["start"]
            break
    assert start_parser is not None
    help_text = start_parser.format_help()
    assert "--meta" in help_text
    assert "JSON" in help_text
    assert "K=V" in help_text


def test_cli_start_meta_end_to_end(tmp_path, monkeypatch) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    assert main(["init", "--project", "p"]) == 0
    assert main(["start", "--stage", "m", "--meta", "a=1",
                 "--meta", '{"b": 2, "flag": true}']) == 0
    st = Stage(str(d)).status()
    assert st["meta"] == {"a": "1", "b": 2, "flag": True}
    # new start replaces meta entirely with the new meta set (issue #15)
    assert main(["start", "--stage", "m", "--meta", "c=3"]) == 0
    st2 = Stage(str(d)).status()
    assert st2["meta"] == {"c": "3"}
    # start without --meta clears meta entirely
    assert main(["start", "--stage", "m"]) == 0
    st3 = Stage(str(d)).status()
    assert st3["meta"] == {}


def test_cli_start_meta_bad_exits_2(tmp_path, monkeypatch, capsys) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    assert main(["init"]) == 0
    capsys.readouterr()
    assert main(["start", "--stage", "m", "--meta", "no-equals"]) == 2
    assert main(["start", "--stage", "m", "--meta", '{"a":']) == 2
    assert main(["start", "--stage", "m", "--meta", "[1,2]"]) == 2
    # failed starts must not clobber meta
    assert Stage(str(d)).status()["meta"] == {}


def test_cli_status_json_roundtrips_meta_types(tmp_path, monkeypatch, capsys) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    assert main(["init"]) == 0
    assert main(["start", "--stage", "m", "--meta", '{"n": 1}']) == 0
    capsys.readouterr()
    assert main(["status", "--json"]) == 10  # running
    out = capsys.readouterr().out
    assert json.loads(out)["meta"] == {"n": 1}


def test_wait_help_documents_json() -> None:
    parser = build_parser()
    wait_parser = None
    for action in parser._actions:
        if hasattr(action, "_name_parser_map") and "wait" in action._name_parser_map:
            wait_parser = action._name_parser_map["wait"]
            break
    assert wait_parser is not None
    help_text = wait_parser.format_help()
    assert "--json" in help_text


def test_cli_wait_json_met_done(tmp_path, monkeypatch, capsys) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    assert main(["init", "--project", "demo"]) == 0
    assert main(["start", "--stage", "m1", "--stage-id", "m1-id"]) == 0
    assert main(["done", "--summary", "all good"]) == 0
    capsys.readouterr()

    # wait --json with default --state terminal
    assert main(["wait", "--json"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["outcome"] == "met"
    assert data["wanted"] == "terminal"
    assert data["observed_state"] == "done"
    assert data["state"] == "done"
    assert data["exit_code"] == 0
    assert data["timeout"] is False
    assert data["stage_id"] == "m1-id"
    assert data["dir"] == str(d)
    assert data["status"]["state"] == "done"
    assert data["status"]["result"]["summary"] == "all good"

    # wait --json with explicit --state done
    assert main(["wait", "--json", "--state", "done"]) == 0
    data2 = json.loads(capsys.readouterr().out)
    assert data2["outcome"] == "met"
    assert data2["wanted"] == "done"
    assert data2["observed_state"] == "done"
    assert data2["exit_code"] == 0


def test_cli_wait_json_timeout(tmp_path, monkeypatch, capsys) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    assert main(["init"]) == 0
    assert main(["start", "--stage", "m-running"]) == 0
    capsys.readouterr()

    # timeout exits 14 and includes last known status in JSON
    assert main(["wait", "--json", "--state", "terminal", "--timeout", "0.2", "--poll", "0.05"]) == 14
    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["outcome"] == "timeout"
    assert data["wanted"] == "terminal"
    assert data["observed_state"] == "running"
    assert data["state"] == "running"
    assert data["exit_code"] == 14
    assert data["timeout"] is True
    assert data["stage_id"] == "m-running"
    assert data["dir"] == str(d)
    assert data["status"]["state"] == "running"
    assert data["status"]["stage_name"] == "m-running"


def test_cli_wait_json_mismatch_blocked(tmp_path, monkeypatch, capsys) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    assert main(["init"]) == 0
    assert main(["start", "--stage", "m-block", "--stage-id", "id-block"]) == 0
    assert main(["blocked", "--reason", "waiting on api key"]) == 0
    capsys.readouterr()

    # Mismatch: wanted done, observed blocked -> exit 11
    assert main(["wait", "--json", "--state", "done", "--timeout", "5", "--poll", "0.05"]) == 11
    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["outcome"] == "mismatch"
    assert data["wanted"] == "done"
    assert data["observed_state"] == "blocked"
    assert data["state"] == "blocked"
    assert data["exit_code"] == 11
    assert data["timeout"] is False
    assert data["stage_id"] == "id-block"
    assert data["dir"] == str(d)
    assert data["status"]["state"] == "blocked"
    assert data["status"]["error"]["reason"] == "waiting on api key"


def test_cli_wait_json_mismatch_failed(tmp_path, monkeypatch, capsys) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    assert main(["init"]) == 0
    assert main(["start", "--stage", "m-fail", "--stage-id", "id-fail"]) == 0
    assert main(["fail", "--reason", "syntax error"]) == 0
    capsys.readouterr()

    # Mismatch: wanted done, observed failed -> exit 12
    assert main(["wait", "--json", "--state", "done", "--timeout", "5", "--poll", "0.05"]) == 12
    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["outcome"] == "mismatch"
    assert data["wanted"] == "done"
    assert data["observed_state"] == "failed"
    assert data["state"] == "failed"
    assert data["exit_code"] == 12
    assert data["timeout"] is False
    assert data["stage_id"] == "id-fail"
    assert data["dir"] == str(d)
    assert data["status"]["state"] == "failed"
    assert data["status"]["error"]["reason"] == "syntax error"


def test_cli_wait_json_matching_non_done_terminal(tmp_path, monkeypatch, capsys) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    assert main(["init"]) == 0
    assert main(["start", "--stage", "m-non-done"]) == 0
    assert main(["blocked", "--reason", "blocked on external dep"]) == 0
    capsys.readouterr()

    # Waiting specifically for blocked matches -> exit 0
    assert main(["wait", "--json", "--state", "blocked"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["outcome"] == "met"
    assert data["wanted"] == "blocked"
    assert data["observed_state"] == "blocked"
    assert data["state"] == "blocked"
    assert data["exit_code"] == 0
    assert data["timeout"] is False


def test_cli_wait_human_default_preserved(tmp_path, monkeypatch, capsys) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    assert main(["init"]) == 0
    assert main(["start", "--stage", "m-human"]) == 0
    assert main(["done", "--summary", "finished"]) == 0
    capsys.readouterr()

    # Human met
    assert main(["wait"]) == 0
    out = capsys.readouterr().out
    assert "wait met: done" in out

    # Human mismatch
    assert main(["start", "--stage", "m-human"]) == 0
    assert main(["blocked", "--reason", "blocked"]) == 0
    capsys.readouterr()
    assert main(["wait", "--state", "done", "--timeout", "5", "--poll", "0.05"]) == 11
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "wait ended in blocked (wanted done)" in captured.err

    # Human timeout
    assert main(["start", "--stage", "m-human"]) == 0
    capsys.readouterr()
    assert main(["wait", "--state", "done", "--timeout", "0.2", "--poll", "0.05"]) == 14
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "stage-signal: error: wait timed out after 0.2s" in captured.err


def test_cli_dogfood_meta_and_git_refresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
        ["git", "commit", "--allow-empty", "-m", "first"],
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

    sdir = repo / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(sdir))

    assert main(["init", "--project", "dogfood"]) == 0
    assert (
        main(
            [
                "start",
                "--stage",
                "s1",
                "--meta",
                "owner=OpenLoop",
                "--meta",
                "reason=no_module_named_pytest",
            ]
        )
        == 0
    )
    st1 = Stage(str(sdir)).status()
    assert st1["meta"] == {
        "owner": "OpenLoop",
        "reason": "no_module_named_pytest",
    }
    assert st1["git_head"] == head1
    assert st1["git_branch"] == "main"

    # Advance git repo with new commit
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "second"],
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

    # Start stage 2 without --meta: meta must be cleared, git_head must reflect head2
    assert main(["start", "--stage", "s2"]) == 0
    st2 = Stage(str(sdir)).status()
    assert st2["meta"] == {}
    assert st2["git_head"] == head2
    assert st2["git_branch"] == "main"


def test_cli_clear_terminal_clears_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    assert main(["init", "--project", "testproj"]) == 0
    assert main(["start", "--stage", "feat-1"]) == 0
    assert main(["fail", "--reason", "compile error"]) == 0
    capsys.readouterr()

    # clear-terminal prints 'cleared queued - (attempt 1)'
    assert main(["clear-terminal"]) == 0
    out = capsys.readouterr().out
    assert "cleared queued - (attempt 1)" in out

    # Status shows true idle queued
    assert main(["status", "--json"]) == 13
    st = json.loads(capsys.readouterr().out)
    assert st["state"] == "queued"
    assert st["stage_name"] is None
    assert st["stage_id"] is None
    assert st["pid"] is None

    # Doctor reports OK: queued
    assert main(["doctor"]) == 0
    doc_out = capsys.readouterr().out
    assert "OK: queued" in doc_out


def test_cli_clear_terminal_keep_stage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    assert main(["init", "--project", "testproj"]) == 0
    assert main(["start", "--stage", "feat-2"]) == 0
    assert main(["fail", "--reason", "tests failed"]) == 0
    capsys.readouterr()

    # clear-terminal --keep-stage preserves stage name
    assert main(["clear-terminal", "--keep-stage"]) == 0
    out = capsys.readouterr().out
    assert "cleared queued feat-2 (attempt 1)" in out

    assert main(["status", "--json"]) == 13
    st = json.loads(capsys.readouterr().out)
    assert st["state"] == "queued"
    assert st["stage_name"] == "feat-2"
    assert st["stage_id"] == "feat-2"


def test_cli_done_accept_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    assert main(["init", "--project", "testproj"]) == 0
    assert main(["start", "--stage", "feat-3"]) == 0
    assert main(["fail", "--reason", "budget exhausted"]) == 0

    # Direct done fails with exit 3
    capsys.readouterr()
    assert main(["done", "--summary", "done anyway"]) == 3
    err = capsys.readouterr().err
    assert "not allowed from terminal state 'failed'" in err

    # done with --accept-failure succeeds with exit 0
    assert main(["done", "--accept-failure", "--summary", "accepted budget exhaustion"]) == 0
    out = capsys.readouterr().out
    assert "done done feat-3 (attempt 1)" in out

    # Status reflects done and records accepted_failure
    assert main(["status", "--json"]) == 0
    st = json.loads(capsys.readouterr().out)
    assert st["state"] == "done"
    assert st["result"]["summary"] == "accepted budget exhaustion"
    assert st["result"]["accepted_failure"] is True
    assert st["error"] is None


def test_cli_done_accept_failure_illegal_on_running(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    assert main(["init", "--project", "testproj"]) == 0
    assert main(["start", "--stage", "feat-4"]) == 0
    capsys.readouterr()

    # --accept-failure from running is illegal, exit 3
    assert main(["done", "--accept-failure", "--summary", "not failed"]) == 3
    err = capsys.readouterr().err
    assert "done --accept-failure only allowed from state 'failed'" in err


def test_cli_status_json_heartbeat_age_seconds_null_when_no_heartbeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    assert main(["init", "--project", "testproj"]) == 0
    capsys.readouterr()

    # In queued state without heartbeat, heartbeat_age_seconds must be null
    assert main(["status", "--json"]) == 13  # queued
    data = json.loads(capsys.readouterr().out)
    assert data["state"] == "queued"
    assert data["heartbeat_at"] is None
    assert data["heartbeat_age_seconds"] is None

    st = Stage(d).status()
    assert st["heartbeat_age_seconds"] is None


def test_cli_status_json_heartbeat_age_seconds_non_negative_after_heartbeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    assert main(["init", "--project", "testproj"]) == 0
    assert main(["start", "--stage", "task1"]) == 0
    capsys.readouterr()

    # After start, heartbeat_age_seconds must be a non-negative number
    assert main(["status", "--json"]) == 10  # running
    data = json.loads(capsys.readouterr().out)
    assert data["state"] == "running"
    assert isinstance(data["heartbeat_age_seconds"], (int, float))
    assert data["heartbeat_age_seconds"] >= 0.0

    st = Stage(d).status()
    assert isinstance(st["heartbeat_age_seconds"], (int, float))
    assert st["heartbeat_age_seconds"] >= 0.0


def test_status_heartbeat_age_seconds_frozen_time_progression(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    stage = Stage(d)
    stage.init(project="testproj")

    current_time = datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc)

    def fake_now_dt() -> datetime:
        return current_time

    monkeypatch.setattr("stage_signal.stage._now_dt", fake_now_dt)
    monkeypatch.setattr("stage_signal.store.now_iso", lambda: current_time.isoformat())

    stage.start(stage="frozen-test")
    st0 = stage.status()
    assert st0["heartbeat_age_seconds"] == pytest.approx(0.0)

    # Advance time by 45.5 seconds
    current_time = datetime(2026, 9, 17, 12, 0, 45, 500000, tzinfo=timezone.utc)
    st1 = stage.status()
    assert st1["heartbeat_age_seconds"] == pytest.approx(45.5)

    # Also verify in CLI status --json
    capsys.readouterr()
    assert main(["status", "--json"]) == 10
    cli_data = json.loads(capsys.readouterr().out)
    assert cli_data["heartbeat_age_seconds"] == pytest.approx(45.5)

    # Advance time by another 100 seconds
    current_time = datetime(2026, 9, 17, 12, 2, 25, 500000, tzinfo=timezone.utc)
    st2 = stage.status()
    assert st2["heartbeat_age_seconds"] == pytest.approx(145.5)

    # Explicit heartbeat resets age back to 0.0
    stage.heartbeat(note="tick")
    st3 = stage.status()
    assert st3["heartbeat_age_seconds"] == pytest.approx(0.0)

    # Advance time by 10 seconds
    current_time = datetime(2026, 9, 17, 12, 2, 35, 500000, tzinfo=timezone.utc)
    st4 = stage.status()
    assert st4["heartbeat_age_seconds"] == pytest.approx(10.0)

    # Verify doctor --json status payload also reflects heartbeat_age_seconds
    capsys.readouterr()
    assert main(["doctor", "--json"]) == 0
    doc_data = json.loads(capsys.readouterr().out)
    assert doc_data["status"]["heartbeat_age_seconds"] == pytest.approx(10.0)


def test_status_heartbeat_age_seconds_unparseable_heartbeat(tmp_path: Path) -> None:
    d = tmp_path / ".stage-signal"
    stage = Stage(d)
    stage.init(project="testproj")
    stage.start(stage="unparseable")

    # Corrupt heartbeat_at timestamp in STATUS.json
    status_file = d / "STATUS.json"
    raw = json.loads(status_file.read_text(encoding="utf-8"))
    raw["heartbeat_at"] = "not-a-valid-timestamp"
    status_file.write_text(json.dumps(raw), encoding="utf-8")

    st = stage.status()
    assert st["heartbeat_age_seconds"] is None


def test_status_heartbeat_age_seconds_sleep_based_increase(tmp_path: Path) -> None:
    import time

    d = tmp_path / ".stage-signal"
    stage = Stage(d)
    stage.init(project="testproj")
    stage.start(stage="sleep-test")

    age1 = stage.status()["heartbeat_age_seconds"]
    assert isinstance(age1, (int, float))
    assert age1 >= 0.0

    time.sleep(0.05)
    age2 = stage.status()["heartbeat_age_seconds"]
    assert isinstance(age2, (int, float))
    assert age2 > age1


def test_cli_status_human_no_heartbeat_absent_age(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    assert main(["init", "--project", "testproj"]) == 0
    capsys.readouterr()

    # In queued state without heartbeat, human status must not have age fragment
    assert main(["status"]) == 13
    out = capsys.readouterr().out
    assert "queued" in out
    assert "heartbeat: None" in out
    assert "(age " not in out


def test_cli_status_human_after_start_has_age(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    assert main(["init", "--project", "testproj"]) == 0
    assert main(["start", "--stage", "task1"]) == 0
    capsys.readouterr()

    # After start, human status must include heartbeat age
    assert main(["status"]) == 10
    out = capsys.readouterr().out
    assert "running task1" in out
    assert "heartbeat: " in out
    assert "(age " in out


def test_cli_status_human_frozen_time_progression(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    stage = Stage(d)
    stage.init(project="testproj")

    current_time = datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc)

    def fake_now_dt() -> datetime:
        return current_time

    monkeypatch.setattr("stage_signal.stage._now_dt", fake_now_dt)
    monkeypatch.setattr("stage_signal.store.now_iso", lambda: current_time.isoformat())

    stage.start(stage="frozen-human-test")
    capsys.readouterr()

    # Initial status has 0s age
    assert main(["status"]) == 10
    out0 = capsys.readouterr().out
    assert "(age 0s)" in out0

    # Advance time by 42 seconds
    current_time = datetime(2026, 9, 17, 12, 0, 42, tzinfo=timezone.utc)
    assert main(["status"]) == 10
    out1 = capsys.readouterr().out
    assert "(age 42s)" in out1

    # Advance time by 102 seconds (1 min 42 s from start)
    current_time = datetime(2026, 9, 17, 12, 1, 42, tzinfo=timezone.utc)
    assert main(["status"]) == 10
    out2 = capsys.readouterr().out
    assert "(age 102s)" in out2

    # Heartbeat resets age back to 0s
    assert main(["heartbeat", "--note", "tick"]) == 0
    capsys.readouterr()
    assert main(["status"]) == 10
    out3 = capsys.readouterr().out
    assert "(age 0s)" in out3


def test_cli_status_human_unparseable_heartbeat_absent_age(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    stage = Stage(d)
    stage.init(project="testproj")
    stage.start(stage="unparseable")

    # Corrupt heartbeat_at timestamp in STATUS.json
    status_file = d / "STATUS.json"
    raw = json.loads(status_file.read_text(encoding="utf-8"))
    raw["heartbeat_at"] = "not-a-valid-timestamp"
    status_file.write_text(json.dumps(raw), encoding="utf-8")

    capsys.readouterr()
    assert main(["status"]) == 10
    out = capsys.readouterr().out
    assert "heartbeat: not-a-valid-timestamp" in out
    assert "(age " not in out


@pytest.mark.parametrize(
    ("state", "exit_code"),
    [("running", 10), ("done", 0), ("failed", 12), ("blocked", 11), ("queued", 13)],
)
def test_cli_status_heartbeat_age_only_while_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    state: str,
    exit_code: int,
) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    stage = Stage(d)
    stage.init(project="testproj")
    stage.start(stage="age-state")
    status_file = d / "STATUS.json"
    raw = json.loads(status_file.read_text(encoding="utf-8"))
    raw["state"] = state
    status_file.write_text(json.dumps(raw), encoding="utf-8")

    assert main(["status"]) == exit_code
    human = capsys.readouterr().out
    assert f"heartbeat: {raw['heartbeat_at']}" in human
    assert ("(age " in human) == (state == "running")

    assert main(["status", "--json"]) == exit_code
    data = json.loads(capsys.readouterr().out)
    assert data["state"] == state
    assert data["heartbeat_at"] == raw["heartbeat_at"]
    if state == "running":
        assert isinstance(data["heartbeat_age_seconds"], (int, float))
        assert data["heartbeat_age_seconds"] >= 0
    else:
        assert data["heartbeat_age_seconds"] is None
        assert stage.status()["heartbeat_age_seconds"] is None
