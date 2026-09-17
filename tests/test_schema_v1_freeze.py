"""schema_version 1 contract freeze regression tests (SPEC §13, issue #102).

Locks JSON keys, exit codes, and event types so orchestrators do not
lose keys or branch targets silently.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from stage_signal import (
    ARTIFACT_ENTRY_KEYS,
    DOCTOR_JSON_KEYS,
    DOCTOR_WARNING_KEYS,
    EVENT_RECORD_KEYS,
    EVENT_TYPES,
    EXIT_BAD_ARGS,
    EXIT_BLOCKED,
    EXIT_CODES,
    EXIT_ERROR,
    EXIT_FAILED,
    EXIT_ILLEGAL_TRANSITION,
    EXIT_NOT_INITIALIZED,
    EXIT_OK,
    EXIT_QUEUED,
    EXIT_RUNNING,
    EXIT_WAIT_TIMEOUT,
    NOTE_ENTRY_KEYS,
    SCHEMA_VERSION,
    STATES,
    STATUS_JSON_KEYS,
    STATUS_REQUIRED_KEYS,
    TERMINAL_STATES,
    WAIT_JSON_KEYS,
    WARNING_CODE_DEAD_PID,
    WARNING_CODE_STALE_HEARTBEAT,
    WARNING_CODE_UNPARSEABLE_HEARTBEAT,
    WARNING_CODES,
    WARNING_KEYS,
    WARNING_REQUIRED_KEYS,
    CorruptStatusError,
    Stage,
    state_exit_code,
)
from stage_signal.cli import main
from stage_signal.constants import STATE_EXIT_CODES
from stage_signal.store import validate_status


# ============================================================================
# 1. Event types & Schema Version freeze
# ============================================================================


def test_schema_version_is_one() -> None:
    """schema_version must be exactly 1 under the v1 contract."""
    assert SCHEMA_VERSION == 1


def test_event_record_keys_freeze() -> None:
    assert EVENT_RECORD_KEYS == (
        "ts",
        "type",
        "stage_id",
        "stage_name",
        "state",
        "attempt",
        "message",
        "detail",
    )


def test_artifact_entry_keys_freeze() -> None:
    assert ARTIFACT_ENTRY_KEYS == ("path", "label", "added_at")


def test_note_entry_keys_freeze() -> None:
    assert NOTE_ENTRY_KEYS == ("text", "added_at")


@pytest.mark.parametrize("extra_keys", [False, True])
def test_artifact_note_entry_keys_on_disk_and_status_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], extra_keys: bool
) -> None:
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="entry-freeze")
    stage.start(stage="build", pid=os.getpid())
    status_file = stage_dir / "STATUS.json"
    prefix = ["--dir", str(stage_dir)]
    expected_counts = {"artifacts": 0, "notes": 0}
    commands = [
        ("artifacts", ["artifact", "dist/out.bin", "--label", "binary"]),
        ("notes", ["note", "checkpoint 1"]),
        ("artifacts", ["artifact", "dist/report.json"]),
        ("notes", ["note", "checkpoint 2"]),
    ]

    for collection, command in commands:
        assert main(prefix + command) == EXIT_OK
        capsys.readouterr()
        expected_counts[collection] += 1
        disk_data = json.loads(status_file.read_text(encoding="utf-8"))
        if extra_keys:
            disk_data[collection][-1]["future_field"] = {"value": 1}
            status_file.write_text(json.dumps(disk_data), encoding="utf-8")
        assert main(prefix + ["status", "--json"]) == EXIT_RUNNING
        cli_data = json.loads(capsys.readouterr().out)
        for data in (disk_data, cli_data):
            for name, required_keys in (
                ("artifacts", ARTIFACT_ENTRY_KEYS),
                ("notes", NOTE_ENTRY_KEYS),
            ):
                assert len(data[name]) == expected_counts[name]
                for entry in data[name]:
                    assert set(required_keys) <= entry.keys()
                    assert isinstance(entry["added_at"], str)
                    assert entry["added_at"]
                    if extra_keys:
                        assert entry["future_field"] == {"value": 1}
            assert data["artifacts"][0]["path"] == "dist/out.bin"
            assert data["artifacts"][0]["label"] == "binary"
            if expected_counts["artifacts"] == 2:
                assert data["artifacts"][1]["path"] == "dist/report.json"
                assert data["artifacts"][1]["label"] is None
            assert [entry["text"] for entry in data["notes"]] == [
                f"checkpoint {index + 1}" for index in range(expected_counts["notes"])
            ]
        assert cli_data["artifacts"] == disk_data["artifacts"]
        assert cli_data["notes"] == disk_data["notes"]


def test_event_types_freeze() -> None:
    """EVENT_TYPES must match SPEC §5 / §13 canonical tuple exactly."""
    expected = (
        "init",
        "start",
        "heartbeat",
        "note",
        "artifact",
        "done",
        "blocked",
        "failed",
        "clear_terminal",
    )
    assert EVENT_TYPES == expected
    assert len(EVENT_TYPES) == 9
    assert all(isinstance(t, str) for t in EVENT_TYPES)


# ============================================================================
# 2. Exit codes freeze
# ============================================================================


def test_exit_codes_freeze() -> None:
    """All exit codes must match their SPEC §7 / §13 defined integer values."""
    assert EXIT_OK == 0
    assert EXIT_ERROR == 1
    assert EXIT_BAD_ARGS == 2
    assert EXIT_ILLEGAL_TRANSITION == 3
    assert EXIT_RUNNING == 10
    assert EXIT_BLOCKED == 11
    assert EXIT_FAILED == 12
    assert EXIT_QUEUED == 13
    assert EXIT_WAIT_TIMEOUT == 14
    assert EXIT_NOT_INITIALIZED == 15

    assert set(EXIT_CODES) == {0, 1, 2, 3, 10, 11, 12, 13, 14, 15}

    expected_state_exit_codes = {
        "running": 10,
        "blocked": 11,
        "failed": 12,
        "queued": 13,
        "done": 0,
    }
    assert STATE_EXIT_CODES == expected_state_exit_codes

    for state, code in expected_state_exit_codes.items():
        assert state_exit_code(state) == code

    with pytest.raises(ValueError, match="unknown state"):
        state_exit_code("unknown_state")


# ============================================================================
# 3. STATUS.json required keys freeze
# ============================================================================


def test_status_required_keys_freeze() -> None:
    """STATUS_REQUIRED_KEYS must match the exact 23 frozen keys (SPEC §13.2)."""
    expected = (
        "schema_version",
        "project",
        "stage_id",
        "stage_name",
        "state",
        "attempt",
        "session_id",
        "pid",
        "model",
        "variant",
        "repo_path",
        "git_branch",
        "git_head",
        "started_at",
        "updated_at",
        "heartbeat_at",
        "heartbeat_note",
        "result",
        "error",
        "artifacts",
        "proof",
        "notes",
        "meta",
    )
    assert STATUS_REQUIRED_KEYS == expected
    assert len(STATUS_REQUIRED_KEYS) == 23


def test_status_required_keys_validation_rejects_missing_keys() -> None:
    """Omitting any single key from STATUS_REQUIRED_KEYS must fail validation."""
    valid_payload: dict[str, Any] = {
        "schema_version": 1,
        "project": "proj",
        "stage_id": "stg-1",
        "stage_name": "stg",
        "state": "running",
        "attempt": 1,
        "session_id": "ses-1",
        "pid": 1234,
        "model": "gpt-4",
        "variant": "high",
        "repo_path": "/path/to/repo",
        "git_branch": "main",
        "git_head": "abc1234",
        "started_at": "2026-09-17T12:00:00+00:00",
        "updated_at": "2026-09-17T12:00:00+00:00",
        "heartbeat_at": "2026-09-17T12:00:00+00:00",
        "heartbeat_note": "working",
        "result": None,
        "error": None,
        "artifacts": [],
        "proof": None,
        "notes": [],
        "meta": {},
    }
    # Base payload must pass validation
    validate_status(valid_payload)

    # Missing any required key must raise CorruptStatusError
    for key in STATUS_REQUIRED_KEYS:
        mutated = dict(valid_payload)
        del mutated[key]
        pattern = (
            "unsupported schema_version"
            if key == "schema_version"
            else f"missing keys:.*{key}"
        )
        with pytest.raises(CorruptStatusError, match=pattern):
            validate_status(mutated)


def test_on_disk_status_json_always_contains_all_required_keys(tmp_path: Path) -> None:
    """Every lifecycle mutation must write all 23 required keys to STATUS.json."""
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))

    def assert_disk_keys() -> None:
        status_file = stage_dir / "STATUS.json"
        assert status_file.is_file()
        data = json.loads(status_file.read_text(encoding="utf-8"))
        for key in STATUS_REQUIRED_KEYS:
            assert key in data, f"Key {key!r} missing from STATUS.json on disk"

    # 1. init
    stage.init(project="test-freeze")
    assert_disk_keys()

    # 2. start
    stage.start(stage="build", pid=os.getpid())
    assert_disk_keys()

    # 3. heartbeat
    stage.heartbeat(note="running build")
    assert_disk_keys()

    # 4. note
    stage.note("checkpoint 1")
    assert_disk_keys()

    # 5. artifact
    stage.artifact("dist/out.bin", label="binary")
    assert_disk_keys()

    # 6. done
    stage.done(summary="build complete")
    assert_disk_keys()

    # 7. clear-terminal
    stage.clear_terminal()
    assert_disk_keys()

    # 8. restart and blocked
    stage.start(stage="test", pid=os.getpid())
    stage.blocked(reason="missing dependency")
    assert_disk_keys()

    # 9. restart and fail
    stage.start(stage="test", pid=os.getpid())
    stage.fail(reason="compilation failed")
    assert_disk_keys()


# ============================================================================
# 4. status --json & Stage.status() contract keys freeze
# ============================================================================


def test_status_json_contract_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """status --json and Stage.status() must always include STATUS_JSON_KEYS across all states."""
    stage_dir = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(stage_dir))
    stage = Stage(str(stage_dir))

    def check_status_keys(expected_state: str) -> None:
        # Library read
        lib_data = stage.status()
        for k in STATUS_JSON_KEYS:
            assert k in lib_data, f"Key {k!r} missing in Stage.status() [{expected_state}]"
        assert isinstance(lib_data["needs_reclaim"], bool)
        if expected_state == "running":
            assert lib_data["heartbeat_age_seconds"] is not None
            assert isinstance(lib_data["heartbeat_age_seconds"], (int, float))
        else:
            assert lib_data["heartbeat_age_seconds"] is None

        # CLI read
        capsys.readouterr()
        code = main(["status", "--json"])
        assert code == state_exit_code(expected_state)
        cli_data = json.loads(capsys.readouterr().out)
        for k in STATUS_JSON_KEYS:
            assert k in cli_data, f"Key {k!r} missing in status --json [{expected_state}]"
        assert isinstance(cli_data["needs_reclaim"], bool)
        if expected_state == "running":
            assert cli_data["heartbeat_age_seconds"] is not None
            assert isinstance(cli_data["heartbeat_age_seconds"], (int, float))
        else:
            assert cli_data["heartbeat_age_seconds"] is None

    # State: queued (after init)
    stage.init(project="test-proj")
    check_status_keys("queued")

    # State: running (after start)
    stage.start(stage="step-1", pid=os.getpid())
    check_status_keys("running")

    # State: done
    stage.done(summary="done step-1")
    check_status_keys("done")

    # State: blocked
    stage.start(stage="step-2", pid=os.getpid())
    stage.blocked(reason="wait for approval")
    check_status_keys("blocked")

    # State: failed
    stage.start(stage="step-3", pid=os.getpid())
    stage.fail(reason="fatal crash")
    check_status_keys("failed")


# ============================================================================
# 5. doctor --json & Stage.diagnose() contract keys freeze
# ============================================================================


def test_doctor_json_contract_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """doctor --json and Stage.diagnose() must include DOCTOR_JSON_KEYS across all health conditions."""
    stage_dir = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(stage_dir))

    def check_doctor_keys(expected_exit: int, expected_ok: bool) -> None:
        stage = Stage(str(stage_dir))
        # Library read
        lib_data = stage.diagnose()
        for k in DOCTOR_JSON_KEYS:
            assert k in lib_data, f"Key {k!r} missing in Stage.diagnose()"
        assert lib_data["ok"] is expected_ok
        assert isinstance(lib_data["needs_reclaim"], bool)
        assert isinstance(lib_data["problems"], list)
        assert isinstance(lib_data["warnings"], list)

        # CLI read
        capsys.readouterr()
        code = main(["doctor", "--json"])
        assert code == expected_exit
        cli_data = json.loads(capsys.readouterr().out)
        for k in DOCTOR_JSON_KEYS:
            assert k in cli_data, f"Key {k!r} missing in doctor --json"
        assert cli_data["ok"] is expected_ok
        assert isinstance(cli_data["needs_reclaim"], bool)
        assert isinstance(cli_data["problems"], list)
        assert isinstance(cli_data["warnings"], list)

    # 1. Uninitialized directory
    check_doctor_keys(expected_exit=1, expected_ok=False)

    # 2. Healthy queued
    stage = Stage(str(stage_dir))
    stage.init(project="doc-test")
    check_doctor_keys(expected_exit=0, expected_ok=True)

    # 3. Healthy running
    stage.start(stage="task", pid=os.getpid())
    check_doctor_keys(expected_exit=0, expected_ok=True)

    # 4. Running with DEAD_PID warning (needs_reclaim == True)
    dead_proc = subprocess.Popen([sys.executable, "-c", "pass"])
    dead_proc.wait(timeout=5)
    stage.start(stage="dead-task", pid=dead_proc.pid)
    check_doctor_keys(expected_exit=0, expected_ok=True)

    # Verify needs_reclaim is True
    diag = stage.diagnose()
    assert diag["needs_reclaim"] is True
    assert any(w["code"] == "DEAD_PID" for w in diag["warnings"])

    # 5. Corrupt STATUS.json (problem present)
    (stage_dir / "STATUS.json").write_text("{not-json\n", encoding="utf-8")
    check_doctor_keys(expected_exit=1, expected_ok=False)


# ============================================================================
# 6. wait --json contract keys freeze (including timeout path)
# ============================================================================


def test_wait_json_contract_keys_met(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """wait --json output must include all WAIT_JSON_KEYS on outcome == 'met'."""
    stage_dir = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(stage_dir))
    stage = Stage(str(stage_dir))
    stage.init(project="wait-proj")
    stage.start(stage="step-met", pid=os.getpid())
    stage.done(summary="finished")

    capsys.readouterr()
    code = main(["wait", "--json", "--state", "done"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)

    for k in WAIT_JSON_KEYS:
        assert k in data, f"Key {k!r} missing in wait --json [outcome=met]"

    assert data["outcome"] == "met"
    assert data["wanted"] == "done"
    assert data["observed_state"] == "done"
    assert data["state"] == "done"
    assert data["exit_code"] == 0
    assert data["timeout"] is False
    assert data["needs_reclaim"] is False
    assert data["status"] is not None
    assert data["status"]["state"] == "done"


def test_wait_json_contract_keys_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """wait --json output must include all WAIT_JSON_KEYS on outcome == 'mismatch'."""
    stage_dir = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(stage_dir))
    stage = Stage(str(stage_dir))
    stage.init(project="wait-proj")
    stage.start(stage="step-mismatch", pid=os.getpid())
    stage.blocked(reason="rate limited")

    capsys.readouterr()
    # Waiting for done against blocked reports exit 11 mismatch
    code = main(["wait", "--json", "--state", "done", "--timeout", "2", "--poll", "0.05"])
    assert code == 11
    data = json.loads(capsys.readouterr().out)

    for k in WAIT_JSON_KEYS:
        assert k in data, f"Key {k!r} missing in wait --json [outcome=mismatch]"

    assert data["outcome"] == "mismatch"
    assert data["wanted"] == "done"
    assert data["observed_state"] == "blocked"
    assert data["state"] == "blocked"
    assert data["exit_code"] == 11
    assert data["timeout"] is False
    assert data["reason"] == "rate limited"
    assert data["needs_reclaim"] is False
    assert data["status"] is not None
    assert data["status"]["state"] == "blocked"


def test_wait_json_contract_keys_timeout_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """wait --json output must include all WAIT_JSON_KEYS on outcome == 'timeout'."""
    stage_dir = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(stage_dir))
    stage = Stage(str(stage_dir))
    stage.init(project="wait-proj")
    stage.start(stage="step-running", pid=os.getpid())

    capsys.readouterr()
    # Waiting for terminal on a running stage with tiny timeout -> exit 14
    code = main(["wait", "--json", "--state", "terminal", "--timeout", "0.1", "--poll", "0.05"])
    assert code == 14
    captured = capsys.readouterr()
    data = json.loads(captured.out)

    for k in WAIT_JSON_KEYS:
        assert k in data, f"Key {k!r} missing in wait --json [outcome=timeout]"

    assert data["outcome"] == "timeout"
    assert data["wanted"] == "terminal"
    assert data["observed_state"] == "running"
    assert data["state"] == "running"
    assert data["exit_code"] == 14
    assert data["timeout"] is True
    assert data["stage_id"] == "step-running"
    assert data["dir"] == str(stage_dir)
    assert isinstance(data["reason"], str)
    assert "wait timed out after" in data["reason"]
    assert isinstance(data["needs_reclaim"], bool)
    assert data["status"] is not None
    assert data["status"]["state"] == "running"


def test_wait_json_needs_reclaim_timeout_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """wait --json --needs-reclaim timeout must include all WAIT_JSON_KEYS."""
    stage_dir = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(stage_dir))
    stage = Stage(str(stage_dir))
    stage.init(project="wait-reclaim-proj")
    # Healthy running stage: reclaim condition is not met -> times out
    stage.start(stage="healthy-running", pid=os.getpid())

    capsys.readouterr()
    code = main(["wait", "--json", "--needs-reclaim", "--timeout", "0.1", "--poll", "0.05"])
    assert code == 14
    data = json.loads(capsys.readouterr().out)

    for k in WAIT_JSON_KEYS:
        assert k in data, f"Key {k!r} missing in wait --json --needs-reclaim [timeout]"

    assert data["outcome"] == "timeout"
    assert data["wanted"] == "needs_reclaim"
    assert data["observed_state"] == "running"
    assert data["exit_code"] == 14
    assert data["timeout"] is True
    assert isinstance(data["reason"], str)
    assert data["needs_reclaim"] is False


# ============================================================================
# 7. Doctor warning codes and warning object keys freeze (SPEC §13.8, issue #110)
# ============================================================================


def test_warning_codes_freeze() -> None:
    """WARNING_CODES must match the exact 3 frozen codes in canonical order (SPEC §13.8)."""
    expected = (
        "STALE_HEARTBEAT",
        "DEAD_PID",
        "UNPARSEABLE_HEARTBEAT",
    )
    assert WARNING_CODES == expected
    assert len(WARNING_CODES) == 3
    assert WARNING_CODE_STALE_HEARTBEAT == "STALE_HEARTBEAT"
    assert WARNING_CODE_DEAD_PID == "DEAD_PID"
    assert WARNING_CODE_UNPARSEABLE_HEARTBEAT == "UNPARSEABLE_HEARTBEAT"
    assert set(WARNING_CODES) == {
        WARNING_CODE_STALE_HEARTBEAT,
        WARNING_CODE_DEAD_PID,
        WARNING_CODE_UNPARSEABLE_HEARTBEAT,
    }
    assert all(isinstance(c, str) for c in WARNING_CODES)


def test_warning_keys_freeze() -> None:
    """WARNING_KEYS must match the exact 3 frozen required keys (SPEC §13.8)."""
    expected = (
        "code",
        "message",
        "detail",
    )
    assert WARNING_KEYS == expected
    assert len(WARNING_KEYS) == 3
    assert WARNING_REQUIRED_KEYS == expected
    assert DOCTOR_WARNING_KEYS == expected


def _assert_warning_contract(warning: dict[str, Any], expected_code: str | None = None) -> None:
    """Validate that a warning object satisfies the SPEC §13.8 contract."""
    assert isinstance(warning, dict)
    for k in WARNING_KEYS:
        assert k in warning, f"Key {k!r} missing in warning: {warning!r}"
    assert warning["code"] in WARNING_CODES, f"Code {warning['code']!r} not in WARNING_CODES"
    if expected_code is not None:
        assert warning["code"] == expected_code
    assert isinstance(warning["message"], str)
    assert len(warning["message"]) > 0
    assert isinstance(warning["detail"], dict)


def test_doctor_warning_stale_heartbeat_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Doctor emits STALE_HEARTBEAT warning with all frozen keys when heartbeat exceeds threshold."""
    stage_dir = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(stage_dir))
    stage = Stage(str(stage_dir))
    stage.init(project="stale-test")
    stage.start(stage="running-task", pid=os.getpid())

    # Set heartbeat to 600s in the past
    status_file = stage_dir / "STATUS.json"
    raw = json.loads(status_file.read_text(encoding="utf-8"))
    raw["heartbeat_at"] = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
    status_file.write_text(json.dumps(raw), encoding="utf-8")

    # Library call
    diag = stage.diagnose(stale_after=300)
    assert diag["ok"] is True
    assert diag["needs_reclaim"] is True
    stale_warnings = [w for w in diag["warnings"] if w["code"] == WARNING_CODE_STALE_HEARTBEAT]
    assert len(stale_warnings) == 1
    _assert_warning_contract(stale_warnings[0], WARNING_CODE_STALE_HEARTBEAT)
    assert "age" in stale_warnings[0]["detail"]
    assert "threshold" in stale_warnings[0]["detail"]
    assert "heartbeat_at" in stale_warnings[0]["detail"]

    # CLI call
    capsys.readouterr()
    code = main(["doctor", "--json"])
    assert code == 0
    cli_data = json.loads(capsys.readouterr().out)
    cli_stale = [w for w in cli_data["warnings"] if w["code"] == WARNING_CODE_STALE_HEARTBEAT]
    assert len(cli_stale) == 1
    _assert_warning_contract(cli_stale[0], WARNING_CODE_STALE_HEARTBEAT)


def test_doctor_warning_stale_heartbeat_null_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Doctor emits STALE_HEARTBEAT warning with all frozen keys when heartbeat_at is null."""
    stage_dir = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(stage_dir))
    stage = Stage(str(stage_dir))
    stage.init(project="stale-null-test")
    stage.start(stage="running-task", pid=os.getpid())

    status_file = stage_dir / "STATUS.json"
    raw = json.loads(status_file.read_text(encoding="utf-8"))
    raw["heartbeat_at"] = None
    status_file.write_text(json.dumps(raw), encoding="utf-8")

    # Library call
    diag = stage.diagnose(stale_after=300)
    assert diag["ok"] is True
    assert diag["needs_reclaim"] is True
    stale_warnings = [w for w in diag["warnings"] if w["code"] == WARNING_CODE_STALE_HEARTBEAT]
    assert len(stale_warnings) == 1
    _assert_warning_contract(stale_warnings[0], WARNING_CODE_STALE_HEARTBEAT)
    assert stale_warnings[0]["detail"]["age"] is None
    assert stale_warnings[0]["detail"]["threshold"] == 300.0
    assert stale_warnings[0]["detail"]["heartbeat_at"] is None

    # CLI call
    capsys.readouterr()
    code = main(["doctor", "--json"])
    assert code == 0
    cli_data = json.loads(capsys.readouterr().out)
    cli_stale = [w for w in cli_data["warnings"] if w["code"] == WARNING_CODE_STALE_HEARTBEAT]
    assert len(cli_stale) == 1
    _assert_warning_contract(cli_stale[0], WARNING_CODE_STALE_HEARTBEAT)


def test_doctor_warning_unparseable_heartbeat_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Doctor emits UNPARSEABLE_HEARTBEAT warning with all frozen keys when heartbeat_at is invalid."""
    stage_dir = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(stage_dir))
    stage = Stage(str(stage_dir))
    stage.init(project="unparseable-test")
    stage.start(stage="running-task", pid=os.getpid())

    status_file = stage_dir / "STATUS.json"
    raw = json.loads(status_file.read_text(encoding="utf-8"))
    raw["heartbeat_at"] = "invalid-iso-date"
    status_file.write_text(json.dumps(raw), encoding="utf-8")

    # Library call
    diag = stage.diagnose(stale_after=300)
    assert diag["ok"] is True
    unp_warnings = [w for w in diag["warnings"] if w["code"] == WARNING_CODE_UNPARSEABLE_HEARTBEAT]
    assert len(unp_warnings) == 1
    _assert_warning_contract(unp_warnings[0], WARNING_CODE_UNPARSEABLE_HEARTBEAT)
    assert unp_warnings[0]["detail"]["heartbeat_at"] == "invalid-iso-date"

    # CLI call
    capsys.readouterr()
    code = main(["doctor", "--json"])
    assert code == 0
    cli_data = json.loads(capsys.readouterr().out)
    cli_unp = [w for w in cli_data["warnings"] if w["code"] == WARNING_CODE_UNPARSEABLE_HEARTBEAT]
    assert len(cli_unp) == 1
    _assert_warning_contract(cli_unp[0], WARNING_CODE_UNPARSEABLE_HEARTBEAT)


def test_doctor_warning_dead_pid_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Doctor emits DEAD_PID warning with all frozen keys when recorded pid is not alive."""
    stage_dir = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(stage_dir))
    stage = Stage(str(stage_dir))
    stage.init(project="dead-pid-test")

    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=5)
    dead_pid = proc.pid
    stage.start(stage="running-task", pid=dead_pid)

    # Library call
    diag = stage.diagnose()
    assert diag["ok"] is True
    assert diag["needs_reclaim"] is True
    dead_warnings = [w for w in diag["warnings"] if w["code"] == WARNING_CODE_DEAD_PID]
    assert len(dead_warnings) == 1
    _assert_warning_contract(dead_warnings[0], WARNING_CODE_DEAD_PID)
    assert dead_warnings[0]["detail"]["pid"] == dead_pid
    assert "recovery_hint" in dead_warnings[0]["detail"]

    # CLI call
    capsys.readouterr()
    code = main(["doctor", "--json"])
    assert code == 0
    cli_data = json.loads(capsys.readouterr().out)
    cli_dead = [w for w in cli_data["warnings"] if w["code"] == WARNING_CODE_DEAD_PID]
    assert len(cli_dead) == 1
    _assert_warning_contract(cli_dead[0], WARNING_CODE_DEAD_PID)


def test_doctor_warning_multiple_simultaneous_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Doctor emitting multiple warnings includes all frozen keys and only known codes for all warnings."""
    stage_dir = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(stage_dir))
    stage = Stage(str(stage_dir))
    stage.init(project="multi-warn-test")

    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=5)
    dead_pid = proc.pid
    stage.start(stage="multi-task", pid=dead_pid)

    status_file = stage_dir / "STATUS.json"
    raw = json.loads(status_file.read_text(encoding="utf-8"))
    raw["heartbeat_at"] = (datetime.now(timezone.utc) - timedelta(seconds=700)).isoformat()
    status_file.write_text(json.dumps(raw), encoding="utf-8")

    # Library call
    diag = stage.diagnose(stale_after=300)
    assert diag["ok"] is True
    assert diag["needs_reclaim"] is True
    assert len(diag["warnings"]) == 2
    for w in diag["warnings"]:
        _assert_warning_contract(w)
    codes = {w["code"] for w in diag["warnings"]}
    assert codes == {WARNING_CODE_STALE_HEARTBEAT, WARNING_CODE_DEAD_PID}
    assert codes.issubset(set(WARNING_CODES))

    # CLI call
    capsys.readouterr()
    code = main(["doctor", "--json"])
    assert code == 0
    cli_data = json.loads(capsys.readouterr().out)
    assert len(cli_data["warnings"]) == 2
    for w in cli_data["warnings"]:
        _assert_warning_contract(w)
    cli_codes = {w["code"] for w in cli_data["warnings"]}
    assert cli_codes == {WARNING_CODE_STALE_HEARTBEAT, WARNING_CODE_DEAD_PID}
    assert cli_codes.issubset(set(WARNING_CODES))


def test_doctor_warning_tolerates_additive_keys() -> None:
    """Warning consumers/readers must tolerate additive unknown keys (SPEC §13.1, §13.8)."""
    warning_with_extras = {
        "code": WARNING_CODE_DEAD_PID,
        "message": "DEAD PID: claiming pid 99999 is not alive",
        "detail": {"pid": 99999, "recovery_hint": "fail --reason TEXT --if-dead-pid"},
        "future_field": "some_extra_metadata",
        "severity": "warning",
    }
    # Required keys present and detail is an object
    _assert_warning_contract(warning_with_extras, WARNING_CODE_DEAD_PID)
    # Readers tolerate extra keys without raising
    assert warning_with_extras.get("future_field") == "some_extra_metadata"
    assert warning_with_extras.get("severity") == "warning"

