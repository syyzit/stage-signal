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
    ALLOWED_TRANSITIONS,
    ARTIFACT_ENTRY_KEYS,
    CLI_SUBCOMMANDS,
    DEFAULT_DIR_NAME,
    DEFAULT_MIRROR_DIRNAME,
    DOCTOR_JSON_KEYS,
    DOCTOR_SUMMARY_OK_FORMAT,
    DOCTOR_SUMMARY_RECLAIM_NEEDED,
    DOCTOR_WARNING_KEYS,
    ERROR_KEYS,
    ERROR_KINDS,
    EVENT_RECORD_KEYS,
    EVENT_TYPES,
    EVENTS_FILENAME,
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
    LOCK_FILENAME,
    LOCKS_DIRNAME,
    NOTE_ENTRY_KEYS,
    PROOF_KEYS,
    PROOF_VERIFIED_VALUES,
    PUBLIC_EXPORTS,
    RESULT_KEYS,
    SCHEMA_VERSION,
    STATE_BLOCKED,
    STATE_DONE,
    STATE_EXIT_CODES,
    STATE_FAILED,
    STATE_QUEUED,
    STATE_RUNNING,
    STATES,
    STATUS_FILENAME,
    STATUS_JSON_KEYS,
    STATUS_MD_FILENAME,
    STATUS_MD_HEADINGS,
    STATUS_MD_OPTIONAL_HEADINGS,
    STATUS_MD_REQUIRED_HEADINGS,
    STATUS_MD_TITLE,
    STATUS_REQUIRED_KEYS,
    STAGE_PUBLIC_METHODS,
    SUPERVISE_DEFAULT_EVERY,
    TERMINAL_STATES,
    WAIT_JSON_KEYS,
    WAIT_OUTCOME_MET,
    WAIT_OUTCOME_MISMATCH,
    WAIT_OUTCOME_TIMEOUT,
    WAIT_OUTCOMES,
    WARNING_CODE_DEAD_PID,
    WARNING_CODE_STALE_HEARTBEAT,
    WARNING_CODE_UNPARSEABLE_HEARTBEAT,
    WARNING_CODES,
    WARNING_KEYS,
    WARNING_REQUIRED_KEYS,
    BadArgsError,
    CorruptStatusError,
    IllegalTransition,
    NotInitialized,
    StageError,
    WaitTimeout,
    Stage,
    StageStore,
    render_status_md,
    resolve_dir,
    state_exit_code,
    allowed_source_states,
    doctor_summary_ok,
    is_transition_allowed,
    transition_target,
    write_status_mirror,
    DEFAULT_STALE_THRESHOLD,
    ENV_DIR,
    ENV_PROJECT,
    ENV_PROOF_REF,
    ENV_STATUS_MIRROR,
    ENV_VARS,
    EVENTS_DEFAULT_TAIL,
    MAX_NOTES,
    WAIT_DEFAULT_POLL,
    WAIT_DEFAULT_TIMEOUT,
)
from stage_signal.cli import build_parser, main
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


def test_proof_keys_freeze() -> None:
    """PROOF_KEYS must match SPEC §13.10 required keys exactly."""
    assert PROOF_KEYS == ("tool", "ref", "verified")
    assert all(isinstance(k, str) for k in PROOF_KEYS)


def test_proof_verified_values_freeze() -> None:
    """PROOF_VERIFIED_VALUES must match SPEC §13.10 verified enum exactly."""
    assert PROOF_VERIFIED_VALUES == (None, "file", "verify")
    assert all(v is None or isinstance(v, str) for v in PROOF_VERIFIED_VALUES)


def _assert_proof_contract(
    proof: Any,
    *,
    expected_ref: str,
    expected_verified: str | None,
    expected_tool: str = "agent-done-or-not",
    extra_field: str | None = None,
) -> None:
    assert isinstance(proof, dict)
    assert set(PROOF_KEYS) <= proof.keys()
    assert proof["tool"] == expected_tool
    assert isinstance(proof["tool"], str)
    assert proof["ref"] == expected_ref
    assert isinstance(proof["ref"], str)
    assert proof["verified"] == expected_verified
    assert proof["verified"] in PROOF_VERIFIED_VALUES
    if extra_field is not None:
        assert extra_field in proof


@pytest.mark.parametrize("extra_keys", [False, True])
def test_proof_keys_on_disk_and_status_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    extra_keys: bool,
) -> None:
    """After proof-ref-only and --require-proof done paths, on-disk + status --json

    non-null proof objects include frozen PROOF_KEYS and only PROOF_VERIFIED_VALUES.
    Readers tolerate unknown additive keys without error.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="proof-freeze")
    status_file = stage_dir / "STATUS.json"
    prefix = ["--dir", str(stage_dir)]

    # 1. Initially (and after start), proof is null (valid under SPEC §13.10)
    assert main(prefix + ["status", "--json"]) == EXIT_QUEUED
    init_cli = json.loads(capsys.readouterr().out)
    init_disk = json.loads(status_file.read_text(encoding="utf-8"))
    assert init_cli["proof"] is None
    assert init_disk["proof"] is None
    assert stage.status()["proof"] is None

    # Plain done without proof-ref leaves proof null
    assert main(prefix + ["start", "--stage", "phase-0", "--pid", str(os.getpid())]) == EXIT_OK
    capsys.readouterr()
    assert main(prefix + ["done", "--summary", "plain done"]) == EXIT_OK
    capsys.readouterr()
    assert main(prefix + ["status", "--json"]) == EXIT_OK
    plain_cli = json.loads(capsys.readouterr().out)
    plain_disk = json.loads(status_file.read_text(encoding="utf-8"))
    assert plain_cli["proof"] is None
    assert plain_disk["proof"] is None
    assert stage.status()["proof"] is None

    # 2. Proof-ref-only done path: records pointer without verification (verified is None)
    assert main(prefix + ["start", "--stage", "phase-ref", "--pid", str(os.getpid())]) == EXIT_OK
    capsys.readouterr()
    ref_target = "ledger/tx-1001"
    assert main(prefix + ["done", "--summary", "ref only", "--proof-ref", ref_target]) == EXIT_OK
    capsys.readouterr()

    if extra_keys:
        disk_data = json.loads(status_file.read_text(encoding="utf-8"))
        disk_data["proof"]["future_checksum"] = "sha256:abc"
        status_file.write_text(json.dumps(disk_data), encoding="utf-8")

    assert main(prefix + ["status", "--json"]) == EXIT_OK
    cli_ref = json.loads(capsys.readouterr().out)
    disk_ref = json.loads(status_file.read_text(encoding="utf-8"))
    lib_ref = stage.status()
    for payload in (cli_ref, disk_ref, lib_ref):
        _assert_proof_contract(
            payload["proof"],
            expected_ref=ref_target,
            expected_verified=None,
            extra_field="future_checksum" if extra_keys else None,
        )

    # 3. --require-proof file gate done path: verified is "file"
    assert main(prefix + ["start", "--stage", "phase-file", "--pid", str(os.getpid())]) == EXIT_OK
    capsys.readouterr()
    receipt_file = tmp_path / "receipt.json"
    receipt_file.write_text('{"tests": "passed", "exit_code": 0}\n', encoding="utf-8")
    assert (
        main(
            prefix
            + [
                "done",
                "--summary",
                "file gate done",
                "--proof-ref",
                str(receipt_file),
                "--require-proof",
            ]
        )
        == EXIT_OK
    )
    capsys.readouterr()

    if extra_keys:
        disk_data = json.loads(status_file.read_text(encoding="utf-8"))
        disk_data["proof"]["future_verified_by"] = "custom-agent"
        status_file.write_text(json.dumps(disk_data), encoding="utf-8")

    assert main(prefix + ["status", "--json"]) == EXIT_OK
    cli_file = json.loads(capsys.readouterr().out)
    disk_file = json.loads(status_file.read_text(encoding="utf-8"))
    lib_file = stage.status()
    for payload in (cli_file, disk_file, lib_file):
        _assert_proof_contract(
            payload["proof"],
            expected_ref=str(receipt_file),
            expected_verified="file",
            extra_field="future_verified_by" if extra_keys else None,
        )

    # 4. --require-proof external verifier gate done path: verified is "verify"
    bin_dir = tmp_path / "mock-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    fake_sh = bin_dir / "agent-done-or-not"
    fake_sh.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    try:
        fake_sh.chmod(0o755)
    except OSError:
        pass
    fake_cmd = bin_dir / "agent-done-or-not.cmd"
    fake_cmd.write_text("@echo off\nexit /b 0\n", encoding="utf-8")
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    monkeypatch.delenv("STAGE_SIGNAL_PROOF_REF", raising=False)

    assert main(prefix + ["start", "--stage", "phase-verify", "--pid", str(os.getpid())]) == EXIT_OK
    capsys.readouterr()
    verify_ref = "external-ledger/run-888"
    assert (
        main(
            prefix
            + [
                "done",
                "--summary",
                "verify gate done",
                "--proof-ref",
                verify_ref,
                "--require-proof",
            ]
        )
        == EXIT_OK
    )
    capsys.readouterr()

    if extra_keys:
        disk_data = json.loads(status_file.read_text(encoding="utf-8"))
        disk_data["proof"]["audit_meta"] = {"passed": True}
        status_file.write_text(json.dumps(disk_data), encoding="utf-8")

    assert main(prefix + ["status", "--json"]) == EXIT_OK
    cli_verify = json.loads(capsys.readouterr().out)
    disk_verify = json.loads(status_file.read_text(encoding="utf-8"))
    lib_verify = stage.status()
    for payload in (cli_verify, disk_verify, lib_verify):
        _assert_proof_contract(
            payload["proof"],
            expected_ref=verify_ref,
            expected_verified="verify",
            extra_field="audit_meta" if extra_keys else None,
        )


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
    assert data["outcome"] in WAIT_OUTCOMES
    assert data["wanted"] == "done"
    assert data["observed_state"] == "done"
    assert data["state"] == "done"
    assert data["exit_code"] == 0
    assert data["timeout"] is False
    assert (data["outcome"] == "timeout") is data["timeout"]
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
    assert data["outcome"] in WAIT_OUTCOMES
    assert data["wanted"] == "done"
    assert data["observed_state"] == "blocked"
    assert data["state"] == "blocked"
    assert data["exit_code"] == 11
    assert data["timeout"] is False
    assert (data["outcome"] == "timeout") is data["timeout"]
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
    assert data["outcome"] in WAIT_OUTCOMES
    assert data["wanted"] == "terminal"
    assert data["observed_state"] == "running"
    assert data["state"] == "running"
    assert data["exit_code"] == 14
    assert data["timeout"] is True
    assert (data["outcome"] == "timeout") is data["timeout"]
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
    assert data["outcome"] in WAIT_OUTCOMES
    assert data["wanted"] == "needs_reclaim"
    assert data["observed_state"] == "running"
    assert data["exit_code"] == 14
    assert data["timeout"] is True
    assert (data["outcome"] == "timeout") is data["timeout"]
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


# ============================================================================
# 8. result/error object keys freeze (SPEC §13.9, issue #113)
# ============================================================================


def test_result_error_keys_freeze() -> None:
    """RESULT_KEYS / ERROR_KEYS / ERROR_KINDS must match SPEC §13.9 exactly."""
    assert RESULT_KEYS == ("summary", "git_head", "finished_at")
    assert len(RESULT_KEYS) == 3
    assert ERROR_KEYS == ("reason", "kind", "finished_at")
    assert len(ERROR_KEYS) == 3
    assert ERROR_KINDS == ("blocked", "failed")
    assert set(ERROR_KINDS) == {"blocked", "failed"}
    assert all(isinstance(k, str) for k in RESULT_KEYS + ERROR_KEYS + ERROR_KINDS)


def _assert_result_contract(
    result: dict[str, Any] | None, *, accept_failure: bool
) -> None:
    """Validate a non-null result object against the SPEC §13.9 contract."""
    assert isinstance(result, dict)
    for k in RESULT_KEYS:
        assert k in result, f"Key {k!r} missing in result: {result!r}"
    assert isinstance(result["summary"], str)
    assert result["git_head"] is None or isinstance(result["git_head"], str)
    assert isinstance(result["finished_at"], str)
    assert result["finished_at"]
    if accept_failure:
        assert result.get("accepted_failure") is True
    else:
        assert "accepted_failure" not in result


def _assert_error_contract(error: dict[str, Any] | None, kind: str) -> None:
    """Validate a non-null error object against the SPEC §13.9 contract."""
    assert isinstance(error, dict)
    for k in ERROR_KEYS:
        assert k in error, f"Key {k!r} missing in error: {error!r}"
    assert isinstance(error["reason"], str)
    assert error["reason"]
    assert error["kind"] == kind
    assert error["kind"] in ERROR_KINDS
    assert isinstance(error["finished_at"], str)
    assert error["finished_at"]


def test_result_error_keys_lifecycle_freeze(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """After done / blocked / fail / done --accept-failure, on-disk and
    status --json non-null result/error objects carry exactly the frozen
    required keys (SPEC §13.9); null result/error remain valid."""
    stage_dir = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(stage_dir))
    status_file = stage_dir / "STATUS.json"
    stage = Stage(str(stage_dir))
    stage.init(project="result-error-freeze")

    def check_contract(
        *, result_kind: str | None, error_kind: str | None
    ) -> None:
        capsys.readouterr()
        assert main(["status", "--json"]) in (EXIT_OK, EXIT_BLOCKED, EXIT_FAILED)
        cli_data = json.loads(capsys.readouterr().out)
        disk_data = json.loads(status_file.read_text(encoding="utf-8"))
        for data in (cli_data, disk_data):
            if result_kind is None:
                assert data["result"] is None
            else:
                _assert_result_contract(
                    data["result"], accept_failure=result_kind == "accepted_failure"
                )
                assert set(RESULT_KEYS) <= data["result"].keys()
            if error_kind is None:
                assert data["error"] is None
            else:
                _assert_error_contract(data["error"], error_kind)
                assert set(ERROR_KEYS) <= data["error"].keys()

    # done: result frozen, error null
    stage.start(stage="build", pid=os.getpid())
    stage.done(summary="build complete")
    check_contract(result_kind="done", error_kind=None)

    # blocked: error frozen with kind blocked, result null
    stage.start(stage="wait", pid=os.getpid())
    stage.blocked(reason="missing dependency")
    check_contract(result_kind=None, error_kind="blocked")

    # fail: error frozen with kind failed, result null
    stage.start(stage="verify", pid=os.getpid())
    stage.fail(reason="compilation failed")
    check_contract(result_kind=None, error_kind="failed")

    # done --accept-failure: result frozen + additive accepted_failure
    stage.done(summary="accepted", accept_failure=True)
    check_contract(result_kind="accepted_failure", error_kind=None)


def test_result_error_tolerates_additive_keys(tmp_path: Path) -> None:
    """Readers must tolerate additive unknown keys on result/error (SPEC §13.1, §13.9)."""
    result_with_extra = {
        "summary": "ok",
        "git_head": None,
        "finished_at": "2026-09-17T12:00:00+00:00",
        "future_metric": 42,
    }
    _assert_result_contract(result_with_extra, accept_failure=False)
    assert result_with_extra.get("future_metric") == 42

    error_with_extra = {
        "reason": "boom",
        "kind": "failed",
        "finished_at": "2026-09-17T12:00:00+00:00",
        "future_code": "E42",
    }
    _assert_error_contract(error_with_extra, "failed")
    assert error_with_extra.get("future_code") == "E42"


# ============================================================================
# 9. STATES and TERMINAL_STATES freeze (SPEC §13.12, issue #118)
# ============================================================================


def test_states_and_terminal_states_constants_freeze() -> None:
    """STATES and TERMINAL_STATES tuples must match SPEC §13.12 exactly."""
    assert STATES == ("queued", "running", "done", "blocked", "failed")
    assert isinstance(STATES, tuple)
    assert len(STATES) == 5

    assert TERMINAL_STATES == ("done", "blocked", "failed")
    assert isinstance(TERMINAL_STATES, tuple)
    assert len(TERMINAL_STATES) == 3

    # All terminal states must be in STATES
    for s in TERMINAL_STATES:
        assert s in STATES

    # Non-terminal partition must be exactly queued and running
    non_terminal = tuple(s for s in STATES if s not in TERMINAL_STATES)
    assert non_terminal == ("queued", "running")

    # Individual state constants must match exact string values
    assert STATE_QUEUED == "queued"
    assert STATE_RUNNING == "running"
    assert STATE_DONE == "done"
    assert STATE_BLOCKED == "blocked"
    assert STATE_FAILED == "failed"

    # Confirm exports from stage_signal
    import stage_signal

    assert getattr(stage_signal, "STATES") is STATES
    assert getattr(stage_signal, "TERMINAL_STATES") is TERMINAL_STATES
    assert getattr(stage_signal, "STATE_QUEUED") == "queued"
    assert getattr(stage_signal, "STATE_RUNNING") == "running"
    assert getattr(stage_signal, "STATE_DONE") == "done"
    assert getattr(stage_signal, "STATE_BLOCKED") == "blocked"
    assert getattr(stage_signal, "STATE_FAILED") == "failed"
    assert "STATES" in stage_signal.__all__
    assert "TERMINAL_STATES" in stage_signal.__all__
    assert "STATE_QUEUED" in stage_signal.__all__
    assert "STATE_RUNNING" in stage_signal.__all__
    assert "STATE_DONE" in stage_signal.__all__
    assert "STATE_BLOCKED" in stage_signal.__all__
    assert "STATE_FAILED" in stage_signal.__all__


def test_states_lifecycle_membership_and_terminal_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Lifecycle asserts every on-disk / status --json state in STATES;

    after done/blocked/fail, state in TERMINAL_STATES;
    after start, state == running and not in TERMINAL_STATES.
    """
    stage_dir = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(stage_dir))
    status_file = stage_dir / "STATUS.json"
    stage = Stage(str(stage_dir))

    expected_exit = {
        STATE_DONE: EXIT_OK,
        STATE_RUNNING: EXIT_RUNNING,
        STATE_BLOCKED: EXIT_BLOCKED,
        STATE_FAILED: EXIT_FAILED,
        STATE_QUEUED: EXIT_QUEUED,
    }

    def verify_state(expected: str, *, terminal: bool) -> None:
        assert expected in STATES
        if terminal:
            assert expected in TERMINAL_STATES
        else:
            assert expected not in TERMINAL_STATES

        capsys.readouterr()
        rc = main(["status", "--json"])
        assert rc == expected_exit[expected]
        cli_data = json.loads(capsys.readouterr().out)
        disk_data = json.loads(status_file.read_text(encoding="utf-8"))
        lib_status = stage.status()

        for data in (cli_data, disk_data, lib_status):
            observed = data["state"]
            assert observed == expected
            assert observed in STATES
            if terminal:
                assert observed in TERMINAL_STATES
            else:
                assert observed not in TERMINAL_STATES
            assert state_exit_code(observed) == expected_exit[expected]

    # 1. init: queued (non-terminal)
    stage.init(project="states-freeze-test")
    verify_state(STATE_QUEUED, terminal=False)

    # 2. start: running (non-terminal, exactly running)
    stage.start(stage="stage-a", pid=os.getpid())
    verify_state(STATE_RUNNING, terminal=False)

    # 3. heartbeat: running (non-terminal)
    stage.heartbeat(note="heartbeat check")
    verify_state(STATE_RUNNING, terminal=False)

    # 4. note: running (non-terminal)
    stage.note("noting progress")
    verify_state(STATE_RUNNING, terminal=False)

    # 5. done: done (terminal)
    stage.done(summary="stage-a finished")
    verify_state(STATE_DONE, terminal=True)

    # 6. clear_terminal: queued (non-terminal)
    stage.clear_terminal()
    verify_state(STATE_QUEUED, terminal=False)

    # 7. start again: running (non-terminal)
    stage.start(stage="stage-b", pid=os.getpid())
    verify_state(STATE_RUNNING, terminal=False)

    # 8. blocked: blocked (terminal)
    stage.blocked(reason="waiting on reviewer")
    verify_state(STATE_BLOCKED, terminal=True)

    # 9. start again: running (non-terminal)
    stage.start(stage="stage-c", pid=os.getpid())
    verify_state(STATE_RUNNING, terminal=False)

    # 10. fail: failed (terminal)
    stage.fail(reason="process crashed")
    verify_state(STATE_FAILED, terminal=True)

    # 11. done --accept-failure: done (terminal)
    stage.done(summary="failure accepted by human", accept_failure=True)
    verify_state(STATE_DONE, terminal=True)


def test_unknown_state_rejected_by_validator(tmp_path: Path) -> None:
    """validate_status and Stage.status() reject states not in STATES."""
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="invalid-state-test")

    status_file = stage_dir / "STATUS.json"
    data = json.loads(status_file.read_text(encoding="utf-8"))

    # Valid state works
    assert data["state"] in STATES
    validate_status(data)

    # State not in STATES must raise CorruptStatusError
    data["state"] = "unknown_state"
    status_file.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(CorruptStatusError, match="unknown state 'unknown_state'"):
        validate_status(data)

    with pytest.raises(CorruptStatusError, match="unknown state 'unknown_state'"):
        stage.status()

# ============================================================================
# 10. Wait outcomes enum freeze (SPEC §13.11, issue #117)
# ============================================================================


def test_wait_outcomes_freeze() -> None:
    """WAIT_OUTCOMES must match the exact 3 frozen outcomes in canonical order (SPEC §13.11)."""
    expected = ("met", "mismatch", "timeout")
    assert WAIT_OUTCOMES == expected
    assert len(WAIT_OUTCOMES) == 3
    assert WAIT_OUTCOME_MET == "met"
    assert WAIT_OUTCOME_MISMATCH == "mismatch"
    assert WAIT_OUTCOME_TIMEOUT == "timeout"
    assert set(WAIT_OUTCOMES) == {"met", "mismatch", "timeout"}
    assert all(isinstance(o, str) for o in WAIT_OUTCOMES)


def _assert_wait_payload_contract(
    payload: dict[str, Any],
    *,
    expected_outcome: str,
    expected_exit: int,
    expected_timeout: bool,
    expected_wanted: str | None = None,
) -> None:
    """Validate a wait --json payload against the SPEC §13.3.3 and §13.11 contract."""
    assert isinstance(payload, dict)
    for k in WAIT_JSON_KEYS:
        assert k in payload, f"Key {k!r} missing in wait --json: {payload!r}"
    assert payload["outcome"] in WAIT_OUTCOMES
    assert payload["outcome"] == expected_outcome
    assert payload["exit_code"] == expected_exit
    assert payload["timeout"] is expected_timeout
    # timeout bool must be strictly consistent with outcome (SPEC §13.11)
    assert (payload["outcome"] == "timeout") is payload["timeout"]
    if expected_wanted is not None:
        assert payload["wanted"] == expected_wanted


@pytest.mark.parametrize(
    "wanted,terminal_action,action_args,expected_outcome,expected_exit",
    [
        ("done", "done", {"summary": "build finished"}, "met", EXIT_OK),
        ("terminal", "done", {"summary": "finished"}, "met", EXIT_OK),
        ("terminal", "blocked", {"reason": "paused"}, "met", EXIT_OK),
        ("terminal", "fail", {"reason": "crashed"}, "met", EXIT_OK),
        ("done", "blocked", {"reason": "blocked instead"}, "mismatch", EXIT_BLOCKED),
        ("done", "fail", {"reason": "failed instead"}, "mismatch", EXIT_FAILED),
        ("blocked", "done", {"summary": "done instead"}, "mismatch", EXIT_OK),
        ("failed", "done", {"summary": "done instead"}, "mismatch", EXIT_OK),
    ],
)
def test_wait_json_outcomes_terminal_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    wanted: str,
    terminal_action: str,
    action_args: dict[str, Any],
    expected_outcome: str,
    expected_exit: int,
) -> None:
    """wait --json outcomes across terminal resolutions satisfy SPEC §13.11 contract."""
    stage_dir = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(stage_dir))
    stage = Stage(str(stage_dir))
    stage.init(project="wait-outcomes-test")
    stage.start(stage="task", pid=os.getpid())

    if terminal_action == "done":
        stage.done(**action_args)
    elif terminal_action == "blocked":
        stage.blocked(**action_args)
    elif terminal_action == "fail":
        stage.fail(**action_args)

    capsys.readouterr()
    exit_code = main(["wait", "--json", "--state", wanted, "--timeout", "1", "--poll", "0.05"])
    assert exit_code == expected_exit
    cli_data = json.loads(capsys.readouterr().out)

    _assert_wait_payload_contract(
        cli_data,
        expected_outcome=expected_outcome,
        expected_exit=expected_exit,
        expected_timeout=False,
        expected_wanted=wanted,
    )


def test_wait_json_outcome_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """wait --json on running and queued stages with expired timeout emits outcome='timeout' and timeout=True."""
    stage_dir = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(stage_dir))
    stage = Stage(str(stage_dir))
    stage.init(project="wait-timeout-test")

    # 1. Queued stage timing out waiting for done
    capsys.readouterr()
    exit_code = main(["wait", "--json", "--state", "done", "--timeout", "0.05", "--poll", "0.02"])
    assert exit_code == EXIT_WAIT_TIMEOUT
    cli_data = json.loads(capsys.readouterr().out)
    _assert_wait_payload_contract(
        cli_data,
        expected_outcome="timeout",
        expected_exit=EXIT_WAIT_TIMEOUT,
        expected_timeout=True,
        expected_wanted="done",
    )

    # 2. Running stage timing out waiting for terminal
    stage.start(stage="worker", pid=os.getpid())
    capsys.readouterr()
    exit_code = main(["wait", "--json", "--state", "terminal", "--timeout", "0.05", "--poll", "0.02"])
    assert exit_code == EXIT_WAIT_TIMEOUT
    cli_data = json.loads(capsys.readouterr().out)
    _assert_wait_payload_contract(
        cli_data,
        expected_outcome="timeout",
        expected_exit=EXIT_WAIT_TIMEOUT,
        expected_timeout=True,
        expected_wanted="terminal",
    )


def test_wait_json_needs_reclaim_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """wait --json --needs-reclaim emits met, mismatch, and timeout outcomes consistent with SPEC §13.11."""
    stage_dir = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(stage_dir))
    stage = Stage(str(stage_dir))

    # 1. Met: stage running with DEAD_PID
    stage.init(project="reclaim-met")
    dead_proc = subprocess.Popen([sys.executable, "-c", "pass"])
    dead_proc.wait(timeout=5)
    stage.start(stage="dead-worker", pid=dead_proc.pid)

    capsys.readouterr()
    exit_code = main(["wait", "--json", "--needs-reclaim", "--timeout", "1", "--poll", "0.05"])
    assert exit_code == EXIT_OK
    cli_data = json.loads(capsys.readouterr().out)
    _assert_wait_payload_contract(
        cli_data,
        expected_outcome="met",
        expected_exit=EXIT_OK,
        expected_timeout=False,
        expected_wanted="needs_reclaim",
    )
    assert cli_data["needs_reclaim"] is True

    # 2. Mismatch: stage finishes to done without reclaim -> exit 1 mismatch
    stage_dir_mismatch = tmp_path / "mismatch" / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(stage_dir_mismatch))
    stage_m = Stage(str(stage_dir_mismatch))
    stage_m.init(project="reclaim-mismatch")
    stage_m.start(stage="normal-worker", pid=os.getpid())
    stage_m.done(summary="done without needing reclaim")

    capsys.readouterr()
    exit_code = main(["wait", "--json", "--needs-reclaim", "--timeout", "1", "--poll", "0.05"])
    assert exit_code == EXIT_ERROR
    cli_data = json.loads(capsys.readouterr().out)
    _assert_wait_payload_contract(
        cli_data,
        expected_outcome="mismatch",
        expected_exit=EXIT_ERROR,
        expected_timeout=False,
        expected_wanted="needs_reclaim",
    )
    assert cli_data["needs_reclaim"] is False

    # 3. Timeout: healthy running stage does not need reclaim before timeout
    stage_dir_timeout = tmp_path / "timeout" / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(stage_dir_timeout))
    stage_t = Stage(str(stage_dir_timeout))
    stage_t.init(project="reclaim-timeout")
    stage_t.start(stage="healthy-worker", pid=os.getpid())

    capsys.readouterr()
    exit_code = main(["wait", "--json", "--needs-reclaim", "--timeout", "0.05", "--poll", "0.02"])
    assert exit_code == EXIT_WAIT_TIMEOUT
    cli_data = json.loads(capsys.readouterr().out)
    _assert_wait_payload_contract(
        cli_data,
        expected_outcome="timeout",
        expected_exit=EXIT_WAIT_TIMEOUT,
        expected_timeout=True,
        expected_wanted="needs_reclaim",
    )
    assert cli_data["needs_reclaim"] is False


def test_wait_outcome_tolerates_additive_fields() -> None:
    """Consumers and readers of wait --json tolerate unknown additive fields (SPEC §13.1, §13.11)."""
    payload_with_extras: dict[str, Any] = {
        "outcome": "met",
        "wanted": "done",
        "observed_state": "done",
        "state": "done",
        "exit_code": 0,
        "timeout": False,
        "stage_id": "step-1",
        "dir": "/tmp/.stage-signal",
        "reason": None,
        "needs_reclaim": False,
        "status": {"state": "done"},
        "future_duration_seconds": 1.23,
        "future_trace_id": "trace-456",
    }
    _assert_wait_payload_contract(
        payload_with_extras,
        expected_outcome="met",
        expected_exit=0,
        expected_timeout=False,
        expected_wanted="done",
    )
    assert payload_with_extras.get("future_duration_seconds") == 1.23
    assert payload_with_extras.get("future_trace_id") == "trace-456"


# ============================================================================
# 11. On-disk layout path constants freeze (SPEC §13.13, issue #121)
# ============================================================================


def test_layout_path_constants_freeze() -> None:
    """Canonical on-disk layout path constants must match SPEC §13.13 exactly."""
    assert DEFAULT_DIR_NAME == ".stage-signal"
    assert STATUS_FILENAME == "STATUS.json"
    assert STATUS_MD_FILENAME == "STATUS.md"
    assert EVENTS_FILENAME == "events.jsonl"
    assert LOCKS_DIRNAME == "locks"
    assert LOCK_FILENAME == "stage.lock"
    assert DEFAULT_MIRROR_DIRNAME == ".orch"

    assert isinstance(DEFAULT_DIR_NAME, str)
    assert isinstance(STATUS_FILENAME, str)
    assert isinstance(STATUS_MD_FILENAME, str)
    assert isinstance(EVENTS_FILENAME, str)
    assert isinstance(LOCKS_DIRNAME, str)
    assert isinstance(LOCK_FILENAME, str)
    assert isinstance(DEFAULT_MIRROR_DIRNAME, str)

    # Confirm exports from stage_signal
    import stage_signal

    assert getattr(stage_signal, "DEFAULT_DIR_NAME") == ".stage-signal"
    assert getattr(stage_signal, "STATUS_FILENAME") == "STATUS.json"
    assert getattr(stage_signal, "STATUS_MD_FILENAME") == "STATUS.md"
    assert getattr(stage_signal, "EVENTS_FILENAME") == "events.jsonl"
    assert getattr(stage_signal, "LOCKS_DIRNAME") == "locks"
    assert getattr(stage_signal, "LOCK_FILENAME") == "stage.lock"
    assert getattr(stage_signal, "DEFAULT_MIRROR_DIRNAME") == ".orch"

    assert "DEFAULT_DIR_NAME" in stage_signal.__all__
    assert "STATUS_FILENAME" in stage_signal.__all__
    assert "STATUS_MD_FILENAME" in stage_signal.__all__
    assert "EVENTS_FILENAME" in stage_signal.__all__
    assert "LOCKS_DIRNAME" in stage_signal.__all__
    assert "LOCK_FILENAME" in stage_signal.__all__
    assert "DEFAULT_MIRROR_DIRNAME" in stage_signal.__all__


def test_init_creates_canonical_layout_paths(tmp_path: Path) -> None:
    """Stage.init creates all relative layout paths specified in SPEC §13.13."""
    stage_dir = tmp_path / "custom_stage_dir"
    stage = Stage(str(stage_dir))
    stage.init(project="layout-freeze-test")

    status_file = stage_dir / STATUS_FILENAME
    status_md_file = stage_dir / STATUS_MD_FILENAME
    events_file = stage_dir / EVENTS_FILENAME
    locks_dir = stage_dir / LOCKS_DIRNAME
    lock_file = locks_dir / LOCK_FILENAME

    assert status_file.is_file()
    assert status_md_file.is_file()
    assert events_file.is_file()
    assert locks_dir.is_dir()
    assert lock_file.is_file()

    # Assert relative paths match frozen constants
    assert status_file.relative_to(stage_dir) == Path(STATUS_FILENAME)
    assert status_md_file.relative_to(stage_dir) == Path(STATUS_MD_FILENAME)
    assert events_file.relative_to(stage_dir) == Path(EVENTS_FILENAME)
    assert locks_dir.relative_to(stage_dir) == Path(LOCKS_DIRNAME)
    assert lock_file.relative_to(stage_dir) == Path(LOCKS_DIRNAME) / LOCK_FILENAME


def test_cli_init_with_default_dir_creates_canonical_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """stage-signal init without --dir creates DEFAULT_DIR_NAME with canonical layout."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("STAGE_SIGNAL_DIR", raising=False)

    rc = main(["init", "--project", "default-dir-test"])
    assert rc == EXIT_OK

    default_dir = tmp_path / DEFAULT_DIR_NAME
    assert default_dir.is_dir()

    assert (default_dir / STATUS_FILENAME).is_file()
    assert (default_dir / STATUS_MD_FILENAME).is_file()
    assert (default_dir / EVENTS_FILENAME).is_file()
    assert (default_dir / LOCKS_DIRNAME).is_dir()
    assert (default_dir / LOCKS_DIRNAME / LOCK_FILENAME).is_file()


def test_status_mirror_uses_default_mirror_dirname(tmp_path: Path) -> None:
    """write_status_mirror places mirror files under DEFAULT_MIRROR_DIRNAME."""
    stage_dir = tmp_path / DEFAULT_DIR_NAME
    stage = Stage(str(stage_dir))
    stage.init(project="mirror-layout-test")
    status = stage.status()

    mirror_path = write_status_mirror(stage_dir, status, repo_root=tmp_path)
    assert mirror_path is not None
    assert mirror_path == tmp_path / DEFAULT_MIRROR_DIRNAME / STATUS_MD_FILENAME
    assert mirror_path.is_file()
    assert mirror_path.relative_to(tmp_path) == Path(DEFAULT_MIRROR_DIRNAME) / STATUS_MD_FILENAME


def test_layout_readers_tolerate_unknown_extra_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Readers and observers tolerate unknown extra files and directories under stage dir (SPEC §13.13)."""
    stage_dir = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(stage_dir))
    stage = Stage(str(stage_dir))
    stage.init(project="extra-files-test")

    # Introduce unknown extra files and directories
    (stage_dir / "custom_extra.json").write_text('{"extra": true}', encoding="utf-8")
    (stage_dir / "notes.txt").write_text("random note", encoding="utf-8")
    unknown_dir = stage_dir / "unknown_cache"
    unknown_dir.mkdir()
    (unknown_dir / "data.bin").write_bytes(b"\x00\x01\x02\x03")
    (stage_dir / LOCKS_DIRNAME / "extra.lock").write_bytes(b"\x00")

    # Verify status (library and CLI)
    status = stage.status()
    assert status["state"] == "queued"

    capsys.readouterr()
    rc = main(["status", "--json"])
    assert rc == EXIT_QUEUED
    data = json.loads(capsys.readouterr().out)
    assert data["state"] == "queued"

    # Verify doctor (library and CLI)
    diag = stage.diagnose()
    assert diag["ok"] is True
    assert diag["problems"] == []

    capsys.readouterr()
    rc = main(["doctor", "--json"])
    assert rc == EXIT_OK
    diag_cli = json.loads(capsys.readouterr().out)
    assert diag_cli["ok"] is True

    # Verify events
    events = stage.events()
    assert len(events) >= 1


# =============================================================================
# 12. Environment variables and timing defaults freeze (SPEC §13.14, issue #122)
# ============================================================================


def test_env_vars_freeze() -> None:
    """Environment variable names are frozen under SPEC §13.14."""
    assert ENV_DIR == "STAGE_SIGNAL_DIR"
    assert ENV_PROJECT == "STAGE_SIGNAL_PROJECT"
    assert ENV_PROOF_REF == "STAGE_SIGNAL_PROOF_REF"
    assert ENV_STATUS_MIRROR == "STAGE_SIGNAL_STATUS_MIRROR"
    expected_vars = (
        "STAGE_SIGNAL_DIR",
        "STAGE_SIGNAL_PROJECT",
        "STAGE_SIGNAL_PROOF_REF",
        "STAGE_SIGNAL_STATUS_MIRROR",
    )
    assert ENV_VARS == expected_vars
    assert len(ENV_VARS) == 4
    assert all(var.startswith("STAGE_SIGNAL_") for var in ENV_VARS)


def test_timing_and_capacity_defaults_freeze() -> None:
    """Timing defaults and capacity limits are pinned under SPEC §13.14."""
    assert WAIT_DEFAULT_TIMEOUT == 3600.0
    assert isinstance(WAIT_DEFAULT_TIMEOUT, float)

    assert WAIT_DEFAULT_POLL == 5.0
    assert isinstance(WAIT_DEFAULT_POLL, float)

    assert EVENTS_DEFAULT_TAIL == 20
    assert isinstance(EVENTS_DEFAULT_TAIL, int)

    assert DEFAULT_STALE_THRESHOLD == 300.0
    assert isinstance(DEFAULT_STALE_THRESHOLD, float)

    assert SUPERVISE_DEFAULT_EVERY == 60.0
    assert isinstance(SUPERVISE_DEFAULT_EVERY, float)

    assert MAX_NOTES == 200
    assert isinstance(MAX_NOTES, int)


def test_env_and_timing_constants_exported_from_top_level() -> None:
    """All frozen constants in SPEC §13.14 are exported from stage_signal."""
    import stage_signal

    expected_exports = [
        "ENV_DIR",
        "ENV_PROJECT",
        "ENV_PROOF_REF",
        "ENV_STATUS_MIRROR",
        "ENV_VARS",
        "WAIT_DEFAULT_TIMEOUT",
        "WAIT_DEFAULT_POLL",
        "EVENTS_DEFAULT_TAIL",
        "DEFAULT_STALE_THRESHOLD",
        "SUPERVISE_DEFAULT_EVERY",
        "MAX_NOTES",
    ]
    for name in expected_exports:
        assert hasattr(stage_signal, name), f"{name} not exported from stage_signal"
        assert name in stage_signal.__all__, f"{name} not in stage_signal.__all__"


def test_stage_signal_dir_honored_when_dir_omitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """STAGE_SIGNAL_DIR is honored when --dir is omitted (SPEC §2, §13.14)."""
    env_dir = tmp_path / "custom-env-dir"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(env_dir))

    # 1. Python API resolve_dir() honors STAGE_SIGNAL_DIR
    resolved = resolve_dir(None)
    assert resolved == env_dir.resolve()

    # 2. StageStore without explicit dir honors STAGE_SIGNAL_DIR
    stage = Stage()
    assert stage._store.dir == env_dir.resolve()

    # 3. CLI init without --dir honors STAGE_SIGNAL_DIR
    capsys.readouterr()
    exit_code = main(["init", "--project", "env-init-test"])
    assert exit_code == EXIT_OK
    assert (env_dir / "STATUS.json").exists()

    # 4. CLI status --json without --dir reads from STAGE_SIGNAL_DIR
    capsys.readouterr()
    exit_code = main(["status", "--json"])
    assert exit_code == EXIT_QUEUED
    status_data = json.loads(capsys.readouterr().out)
    assert status_data["project"] == "env-init-test"
    assert status_data["state"] == STATE_QUEUED


def test_cli_dir_wins_over_stage_signal_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--dir explicitly takes precedence over STAGE_SIGNAL_DIR (SPEC §2, §13.14)."""
    env_dir = tmp_path / "env-ignored-dir"
    explicit_dir = tmp_path / "explicit-dir"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(env_dir))

    # 1. resolve_dir(explicit) returns explicit even when env is set
    assert resolve_dir(explicit_dir) == explicit_dir.resolve()

    # 2. CLI --dir targets explicit_dir, leaves env_dir untouched
    capsys.readouterr()
    exit_code = main(["--dir", str(explicit_dir), "init", "--project", "explicit-wins"])
    assert exit_code == EXIT_OK
    assert (explicit_dir / "STATUS.json").exists()
    assert not (env_dir / "STATUS.json").exists()

    # 3. CLI status --dir reads explicit_dir
    capsys.readouterr()
    exit_code = main(["--dir", str(explicit_dir), "status", "--json"])
    assert exit_code == EXIT_QUEUED
    status_data = json.loads(capsys.readouterr().out)
    assert status_data["project"] == "explicit-wins"


def test_stage_signal_project_env_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """STAGE_SIGNAL_PROJECT provides fallback project name when --project is omitted (SPEC §13.14)."""
    stage_dir = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_PROJECT", "env-project-fallback")

    stage = Stage(str(stage_dir))
    stage.init()
    assert stage.status()["project"] == "env-project-fallback"


def test_stage_signal_proof_ref_env_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """STAGE_SIGNAL_PROOF_REF provides fallback receipt reference for proof gate (SPEC §9, §13.14)."""
    stage_dir = tmp_path / ".stage-signal"
    receipt_file = tmp_path / "receipt.txt"
    receipt_file.write_text("proof receipt content\n", encoding="utf-8")

    monkeypatch.setenv("STAGE_SIGNAL_PROOF_REF", str(receipt_file))
    stage = Stage(str(stage_dir))
    stage.init(project="proof-env-test")
    stage.start(stage="verify-step", pid=os.getpid())

    # done with require_proof=True but proof_ref=None should pick up STAGE_SIGNAL_PROOF_REF
    stage.done(summary="verified with env proof", require_proof=True)
    status = stage.status()
    assert status["proof"] == {
        "tool": "agent-done-or-not",
        "ref": str(receipt_file),
        "verified": "file",
    }


def test_stage_signal_status_mirror_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """STAGE_SIGNAL_STATUS_MIRROR=1 enables .orch mirror writes (SPEC §10, §13.14)."""
    stage_dir = tmp_path / ".stage-signal"
    orch_dir = tmp_path / ".orch"
    monkeypatch.setenv("STAGE_SIGNAL_STATUS_MIRROR", "1")

    stage = Stage(str(stage_dir))
    stage.init(project="mirror-env-test")
    stage.start(stage="mirror-step", pid=os.getpid())

    assert (orch_dir / "STATUS.md").exists()
    assert "mirror-step" in (orch_dir / "STATUS.md").read_text(encoding="utf-8")

    stage.done(summary="mirror finished")
    assert (orch_dir / "DONE").exists()


def test_stale_threshold_matches_doctor_and_supervise_defaults() -> None:
    """DEFAULT_STALE_THRESHOLD matches doctor and supervise defaults across API and CLI (SPEC §13.14)."""
    import inspect

    # 1. Stage.diagnose stale_after default
    diag_sig = inspect.signature(Stage.diagnose)
    assert diag_sig.parameters["stale_after"].default == DEFAULT_STALE_THRESHOLD

    # 2. Stage.supervise stale_threshold default
    sup_sig = inspect.signature(Stage.supervise)
    assert sup_sig.parameters["stale_threshold"].default == DEFAULT_STALE_THRESHOLD
    assert sup_sig.parameters["every"].default == SUPERVISE_DEFAULT_EVERY

    # 3. CLI parser defaults
    parser = build_parser()
    doc_args = parser.parse_args(["doctor"])
    assert doc_args.stale_after == DEFAULT_STALE_THRESHOLD

    sup_args = parser.parse_args(["supervise", "--", "echo", "hi"])
    assert sup_args.every == SUPERVISE_DEFAULT_EVERY


def test_wait_cli_timing_defaults() -> None:
    """WAIT_DEFAULT_TIMEOUT and WAIT_DEFAULT_POLL match CLI wait parser defaults (SPEC §6, §13.14)."""
    parser = build_parser()
    wait_args = parser.parse_args(["wait"])
    assert wait_args.timeout == WAIT_DEFAULT_TIMEOUT
    assert wait_args.poll == WAIT_DEFAULT_POLL


def test_events_cli_default_tail() -> None:
    """EVENTS_DEFAULT_TAIL matches CLI events parser default and filters events (SPEC §5, §13.14)."""
    parser = build_parser()
    events_args = parser.parse_args(["events"])
    assert events_args.tail == EVENTS_DEFAULT_TAIL


def test_max_notes_capacity_limit(tmp_path: Path) -> None:
    """MAX_NOTES pins the maximum retained notes in STATUS.json (SPEC §3, §13.14)."""
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="max-notes-test")
    stage.start(stage="notes-capacity", pid=os.getpid())

    # Append MAX_NOTES + 15 notes
    total_notes = MAX_NOTES + 15
    for i in range(total_notes):
        stage.note(f"note-{i}")

    status = stage.status()
    notes = status["notes"]
    assert len(notes) == MAX_NOTES
    # FIFO truncation: first note retained should be note-15, last note-214
    assert notes[0]["text"] == "note-15"
    assert notes[-1]["text"] == f"note-{total_notes - 1}"


# =============================================================================
# 13. CLI subcommand inventory freeze (SPEC §13.15, issue #125)
# =============================================================================


def test_cli_subcommands_constant_freeze() -> None:
    """CLI subcommands inventory is frozen under SPEC §13.15."""
    expected_subcommands = (
        "artifact",
        "blocked",
        "clear-terminal",
        "doctor",
        "done",
        "events",
        "fail",
        "heartbeat",
        "init",
        "note",
        "reclaim",
        "start",
        "status",
        "supervise",
        "wait",
    )
    assert CLI_SUBCOMMANDS == expected_subcommands
    assert isinstance(CLI_SUBCOMMANDS, tuple)
    assert len(CLI_SUBCOMMANDS) == 15
    # Must be sorted alphabetically
    assert CLI_SUBCOMMANDS == tuple(sorted(CLI_SUBCOMMANDS))
    # All items must be non-empty strings without whitespace
    assert all(isinstance(cmd, str) and cmd.strip() == cmd and len(cmd) > 0 for cmd in CLI_SUBCOMMANDS)
    # No duplicates
    assert len(set(CLI_SUBCOMMANDS)) == len(CLI_SUBCOMMANDS)


def test_cli_subcommands_exported_from_top_level_and_cli() -> None:
    """CLI_SUBCOMMANDS is exported from stage_signal, stage_signal.constants, and stage_signal.cli."""
    import stage_signal
    import stage_signal.cli
    import stage_signal.constants

    assert hasattr(stage_signal, "CLI_SUBCOMMANDS")
    assert "CLI_SUBCOMMANDS" in stage_signal.__all__
    assert stage_signal.CLI_SUBCOMMANDS == CLI_SUBCOMMANDS

    assert hasattr(stage_signal.constants, "CLI_SUBCOMMANDS")
    assert stage_signal.constants.CLI_SUBCOMMANDS == CLI_SUBCOMMANDS

    assert hasattr(stage_signal.cli, "CLI_SUBCOMMANDS")
    assert "CLI_SUBCOMMANDS" in stage_signal.cli.__all__
    assert stage_signal.cli.CLI_SUBCOMMANDS == CLI_SUBCOMMANDS


def test_build_parser_choices_exactly_equal_cli_subcommands() -> None:
    """CLI parser subcommands exactly match the frozen CLI_SUBCOMMANDS (SPEC §13.15)."""
    parser = build_parser()
    subparser_action = next(a for a in parser._actions if a.dest == "command")
    choices = subparser_action.choices

    assert set(choices.keys()) == set(CLI_SUBCOMMANDS)
    assert tuple(sorted(choices.keys())) == CLI_SUBCOMMANDS
    assert len(choices) == len(CLI_SUBCOMMANDS)


def test_every_subcommand_has_callable_func_and_help() -> None:
    """Every frozen subcommand in build_parser() has a valid implementation handler and help text."""
    parser = build_parser()
    subparser_action = next(a for a in parser._actions if a.dest == "command")
    choices = subparser_action.choices

    for cmd in CLI_SUBCOMMANDS:
        cmd_parser = choices[cmd]
        func = cmd_parser.get_default("func")
        assert callable(func), f"subcommand {cmd} does not have a callable func set_default"
        assert (cmd_parser.description or cmd_parser.format_help()), f"subcommand {cmd} missing help"


def test_cli_entry_points_equivalence() -> None:
    """python -m stage_signal and stage-signal CLI entry point are equivalent (SPEC §13.15.1)."""
    # 1. python -m stage_signal --version exits 0 and prints version
    proc = subprocess.run(
        [sys.executable, "-m", "stage_signal", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "stage-signal" in proc.stdout

    # 2. Invalid subcommand exits 2 (EXIT_BAD_ARGS)
    proc_bad = subprocess.run(
        [sys.executable, "-m", "stage_signal", "nonexistent-command-xyz"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_bad.returncode == EXIT_BAD_ARGS
    assert "invalid choice" in proc_bad.stderr or "error:" in proc_bad.stderr


def test_cli_subcommands_rejects_unknown_command_in_process(capsys: pytest.CaptureFixture[str]) -> None:
    """CLI parser rejects unknown subcommands with exit code 2 (EXIT_BAD_ARGS)."""
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["unknown-subcommand"])
    assert exc_info.value.code == EXIT_BAD_ARGS


# =============================================================================
# 14. State-to-exit-code mapping freeze (SPEC §13.16, issue #126)
# =============================================================================


def test_state_exit_codes_mapping_freeze() -> None:
    """STATE_EXIT_CODES matches the frozen mapping in SPEC §13.16."""
    expected_state_exit_codes = {
        "running": 10,
        "blocked": 11,
        "failed": 12,
        "queued": 13,
        "done": 0,
    }
    assert STATE_EXIT_CODES == expected_state_exit_codes
    assert set(STATE_EXIT_CODES.keys()) == set(STATES)

    # Verify individual mapped constants and state values
    assert STATE_EXIT_CODES[STATE_QUEUED] == EXIT_QUEUED == 13
    assert STATE_EXIT_CODES[STATE_RUNNING] == EXIT_RUNNING == 10
    assert STATE_EXIT_CODES[STATE_DONE] == EXIT_OK == 0
    assert STATE_EXIT_CODES[STATE_BLOCKED] == EXIT_BLOCKED == 11
    assert STATE_EXIT_CODES[STATE_FAILED] == EXIT_FAILED == 12

    for state, code in expected_state_exit_codes.items():
        assert isinstance(state, str)
        assert isinstance(code, int)
        assert state_exit_code(state) == code


def test_state_exit_codes_exported_from_top_level() -> None:
    """STATE_EXIT_CODES is exported from top-level stage_signal package (SPEC §13.16)."""
    import stage_signal

    assert hasattr(stage_signal, "STATE_EXIT_CODES")
    assert "STATE_EXIT_CODES" in stage_signal.__all__
    assert stage_signal.STATE_EXIT_CODES is STATE_EXIT_CODES


def test_state_exit_code_unknown_state_error() -> None:
    """Unknown state passed to state_exit_code raises ValueError without crashing (SPEC §13.16)."""
    with pytest.raises(ValueError, match="unknown state"):
        state_exit_code("unknown_state")

    with pytest.raises(ValueError, match="unknown state"):
        state_exit_code("")

    with pytest.raises(ValueError, match="unknown state"):
        state_exit_code("TERMINAL")


def test_status_cli_exit_codes_smoke(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Smoke test: status CLI exits with STATE_EXIT_CODES for each state (SPEC §6, §7, §13.16)."""
    stage_dir = tmp_path / ".stage-signal"
    pid = os.getpid()

    # 1. State: queued (after init) -> EXIT_QUEUED (13)
    capsys.readouterr()
    init_rc = main(["--dir", str(stage_dir), "init", "--project", "exit-smoke-test"])
    assert init_rc == EXIT_OK

    capsys.readouterr()
    rc_human = main(["--dir", str(stage_dir), "status"])
    assert rc_human == EXIT_QUEUED
    assert rc_human == STATE_EXIT_CODES["queued"]

    capsys.readouterr()
    rc_json = main(["--dir", str(stage_dir), "status", "--json"])
    assert rc_json == EXIT_QUEUED
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "queued"

    # 2. State: running (after start) -> EXIT_RUNNING (10)
    capsys.readouterr()
    start_rc = main(["--dir", str(stage_dir), "start", "--stage", "step1", "--pid", str(pid)])
    assert start_rc == EXIT_OK

    capsys.readouterr()
    rc_human = main(["--dir", str(stage_dir), "status"])
    assert rc_human == EXIT_RUNNING
    assert rc_human == STATE_EXIT_CODES["running"]

    capsys.readouterr()
    rc_json = main(["--dir", str(stage_dir), "status", "--json"])
    assert rc_json == EXIT_RUNNING
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "running"

    # 3. State: blocked (after blocked) -> EXIT_BLOCKED (11)
    capsys.readouterr()
    block_rc = main(["--dir", str(stage_dir), "blocked", "--reason", "waiting on external dep"])
    assert block_rc == EXIT_OK

    capsys.readouterr()
    rc_human = main(["--dir", str(stage_dir), "status"])
    assert rc_human == EXIT_BLOCKED
    assert rc_human == STATE_EXIT_CODES["blocked"]

    capsys.readouterr()
    rc_json = main(["--dir", str(stage_dir), "status", "--json"])
    assert rc_json == EXIT_BLOCKED
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "blocked"

    # 4. State: done (after start -> done) -> EXIT_OK (0)
    capsys.readouterr()
    start_rc = main(["--dir", str(stage_dir), "start", "--stage", "step2", "--pid", str(pid)])
    assert start_rc == EXIT_OK

    capsys.readouterr()
    done_rc = main(["--dir", str(stage_dir), "done", "--summary", "step completed"])
    assert done_rc == EXIT_OK

    capsys.readouterr()
    rc_human = main(["--dir", str(stage_dir), "status"])
    assert rc_human == EXIT_OK
    assert rc_human == STATE_EXIT_CODES["done"]

    capsys.readouterr()
    rc_json = main(["--dir", str(stage_dir), "status", "--json"])
    assert rc_json == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "done"

    # 5. State: failed (after clear-terminal -> start -> fail) -> EXIT_FAILED (12)
    capsys.readouterr()
    clear_rc = main(["--dir", str(stage_dir), "clear-terminal"])
    assert clear_rc == EXIT_OK

    capsys.readouterr()
    start_rc = main(["--dir", str(stage_dir), "start", "--stage", "step3", "--pid", str(pid)])
    assert start_rc == EXIT_OK

    capsys.readouterr()
    fail_rc = main(["--dir", str(stage_dir), "fail", "--reason", "fatal test failure"])
    assert fail_rc == EXIT_OK

    capsys.readouterr()
    rc_human = main(["--dir", str(stage_dir), "status"])
    assert rc_human == EXIT_FAILED
    assert rc_human == STATE_EXIT_CODES["failed"]

    capsys.readouterr()
    rc_json = main(["--dir", str(stage_dir), "status", "--json"])
    assert rc_json == EXIT_FAILED
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "failed"


def test_mutation_commands_exit_zero_distinct_from_status_observer(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Mutation commands exit 0 on success, distinct from observer status exits (SPEC §6, §7, §13.16)."""
    stage_dir = tmp_path / ".stage-signal"
    pid = os.getpid()

    # init mutates to queued -> mutation exits 0, status exits 13
    assert main(["--dir", str(stage_dir), "init", "--project", "distinct-test"]) == EXIT_OK
    assert main(["--dir", str(stage_dir), "status"]) == STATE_EXIT_CODES["queued"]

    # start mutates to running -> mutation exits 0, status exits 10
    assert main(["--dir", str(stage_dir), "start", "--stage", "s1", "--pid", str(pid)]) == EXIT_OK
    assert main(["--dir", str(stage_dir), "status"]) == STATE_EXIT_CODES["running"]

    # heartbeat mutates heartbeat_at -> mutation exits 0
    assert main(["--dir", str(stage_dir), "heartbeat"]) == EXIT_OK

    # note mutates notes -> mutation exits 0
    assert main(["--dir", str(stage_dir), "note", "working on task"]) == EXIT_OK

    # blocked mutates to blocked -> mutation exits 0, status exits 11
    assert main(["--dir", str(stage_dir), "blocked", "--reason", "blocked on external"]) == EXIT_OK
    assert main(["--dir", str(stage_dir), "status"]) == STATE_EXIT_CODES["blocked"]

    # restart and done -> done exits 0, status exits 0
    assert main(["--dir", str(stage_dir), "start", "--stage", "s2", "--pid", str(pid)]) == EXIT_OK
    assert main(["--dir", str(stage_dir), "done", "--summary", "all good"]) == EXIT_OK
    assert main(["--dir", str(stage_dir), "status"]) == STATE_EXIT_CODES["done"]

    # clear-terminal mutates to queued -> clear-terminal exits 0, status exits 13
    assert main(["--dir", str(stage_dir), "clear-terminal"]) == EXIT_OK
    assert main(["--dir", str(stage_dir), "status"]) == STATE_EXIT_CODES["queued"]

    # restart and fail -> fail exits 0, status exits 12
    assert main(["--dir", str(stage_dir), "start", "--stage", "s3", "--pid", str(pid)]) == EXIT_OK
    assert main(["--dir", str(stage_dir), "fail", "--reason", "bad state"]) == EXIT_OK
    assert main(["--dir", str(stage_dir), "status"]) == STATE_EXIT_CODES["failed"]


# =============================================================================
# 15. Public exception hierarchy and exit mapping freeze (SPEC §13.17, issue #129)
# =============================================================================


def test_exception_hierarchy_issubclass() -> None:
    """Exception classes follow the frozen inheritance hierarchy in SPEC §13.17."""
    assert issubclass(StageError, Exception)
    assert issubclass(BadArgsError, StageError)
    assert issubclass(IllegalTransition, StageError)
    assert issubclass(NotInitialized, StageError)
    assert issubclass(CorruptStatusError, StageError)
    assert issubclass(WaitTimeout, StageError)

    # Base class directly inherits from Exception
    assert StageError.__bases__ == (Exception,)

    # Subclasses directly inherit from StageError
    subclasses = [
        BadArgsError,
        IllegalTransition,
        NotInitialized,
        CorruptStatusError,
        WaitTimeout,
    ]
    for sub in subclasses:
        assert StageError in sub.__mro__
        assert sub.__bases__ == (StageError,)

    # Subclasses are mutually distinct branches (none inherits from another)
    for i, a in enumerate(subclasses):
        for j, b in enumerate(subclasses):
            if i != j:
                assert not issubclass(a, b), f"{a.__name__} must not inherit from {b.__name__}"


def test_exception_exports_from_top_level() -> None:
    """All exception types are exported from stage_signal top-level / __all__ (SPEC §13.17)."""
    import stage_signal

    frozen_exceptions = {
        "StageError": StageError,
        "BadArgsError": BadArgsError,
        "IllegalTransition": IllegalTransition,
        "NotInitialized": NotInitialized,
        "CorruptStatusError": CorruptStatusError,
        "WaitTimeout": WaitTimeout,
    }

    for name, exc_cls in frozen_exceptions.items():
        assert hasattr(stage_signal, name), f"{name} must be an attribute of stage_signal"
        assert name in stage_signal.__all__, f"{name} must be listed in stage_signal.__all__"
        assert getattr(stage_signal, name) is exc_cls, f"stage_signal.{name} must be {exc_cls}"


def test_exception_exit_code_constants_and_instances() -> None:
    """Exception class- and instance-level exit_code attributes match SPEC §13.17."""
    expected_exit_codes = {
        StageError: (EXIT_ERROR, 1),
        BadArgsError: (EXIT_BAD_ARGS, 2),
        IllegalTransition: (EXIT_ILLEGAL_TRANSITION, 3),
        NotInitialized: (EXIT_NOT_INITIALIZED, 15),
        CorruptStatusError: (EXIT_ERROR, 1),
        WaitTimeout: (EXIT_WAIT_TIMEOUT, 14),
    }

    for exc_cls, (const_val, numeric_val) in expected_exit_codes.items():
        assert const_val == numeric_val
        # Class-level attribute
        assert exc_cls.exit_code == numeric_val
        # Instance-level attribute
        instance = exc_cls(f"test error message for {exc_cls.__name__}")
        assert instance.exit_code == numeric_val
        assert str(instance) == f"test error message for {exc_cls.__name__}"


def test_exception_instance_attributes_preserved() -> None:
    """Specific exception attributes (detail, last_status) are preserved (SPEC §13.17)."""
    # StageError detail kwarg
    err_with_detail = StageError("something broke", detail={"extra": 42})
    assert err_with_detail.detail == {"extra": 42}

    err_no_detail = StageError("no detail")
    assert err_no_detail.detail is None

    # WaitTimeout last_status kwarg
    status_dict = {"state": "running", "stage_id": "step1"}
    timeout_err = WaitTimeout("timed out waiting", last_status=status_dict)
    assert timeout_err.last_status == status_dict

    timeout_no_status = WaitTimeout("timed out")
    assert timeout_no_status.last_status is None


def test_not_initialized_library_and_cli_exit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """NotInitialized raised by library maps to EXIT_NOT_INITIALIZED (15) in CLI (SPEC §7, §13.4, §13.17)."""
    nonexistent = tmp_path / "does_not_exist"
    stage = Stage(nonexistent)

    # Library call raises NotInitialized with exit_code 15
    with pytest.raises(NotInitialized) as exc_info:
        stage.status()
    assert exc_info.value.exit_code == EXIT_NOT_INITIALIZED == 15

    with pytest.raises(NotInitialized) as exc_info:
        stage.heartbeat()
    assert exc_info.value.exit_code == EXIT_NOT_INITIALIZED == 15

    # CLI catches NotInitialized and exits with 15
    capsys.readouterr()
    rc_status = main(["--dir", str(nonexistent), "status"])
    assert rc_status == EXIT_NOT_INITIALIZED == 15
    err_out = capsys.readouterr().err
    assert "stage-signal: error:" in err_out

    capsys.readouterr()
    rc_hb = main(["--dir", str(nonexistent), "heartbeat"])
    assert rc_hb == EXIT_NOT_INITIALIZED == 15
    err_out = capsys.readouterr().err
    assert "stage-signal: error:" in err_out


def test_bad_args_error_library_and_cli_exit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """BadArgsError raised by library/CLI maps to EXIT_BAD_ARGS (2) in CLI (SPEC §7, §13.4, §13.17)."""
    stage_dir = tmp_path / ".stage-signal"
    assert main(["--dir", str(stage_dir), "init", "--project", "bad-args-test"]) == EXIT_OK
    stage = Stage(stage_dir)

    # Library call raises BadArgsError with exit_code 2
    with pytest.raises(BadArgsError) as exc_info:
        stage.start(stage="")
    assert exc_info.value.exit_code == EXIT_BAD_ARGS == 2

    with pytest.raises(BadArgsError) as exc_info:
        stage.start(stage="step1", pid=-99)
    assert exc_info.value.exit_code == EXIT_BAD_ARGS == 2

    with pytest.raises(BadArgsError) as exc_info:
        stage.note("")
    assert exc_info.value.exit_code == EXIT_BAD_ARGS == 2

    # CLI catches BadArgsError and exits with 2
    capsys.readouterr()
    rc_empty_note = main(["--dir", str(stage_dir), "note", ""])
    assert rc_empty_note == EXIT_BAD_ARGS == 2
    err_out = capsys.readouterr().err
    assert "stage-signal: error: note requires non-empty TEXT" in err_out

    capsys.readouterr()
    rc_bad_start = main(["--dir", str(stage_dir), "start", "--stage", "", "--pid", str(os.getpid())])
    assert rc_bad_start == EXIT_BAD_ARGS == 2
    err_out = capsys.readouterr().err
    assert "stage-signal: error: start requires a non-empty --stage NAME" in err_out

    capsys.readouterr()
    rc_bad_meta = main(["--dir", str(stage_dir), "start", "--stage", "ok", "--pid", str(os.getpid()), "--meta", "badjson{"])
    assert rc_bad_meta == EXIT_BAD_ARGS == 2
    err_out = capsys.readouterr().err
    assert "stage-signal: error:" in err_out


def test_illegal_transition_library_and_cli_exit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """IllegalTransition raised by library maps to EXIT_ILLEGAL_TRANSITION (3) in CLI (SPEC §7, §13.4, §13.17)."""
    stage_dir = tmp_path / ".stage-signal"
    pid = os.getpid()
    assert main(["--dir", str(stage_dir), "init", "--project", "illegal-trans-test"]) == EXIT_OK
    assert main(["--dir", str(stage_dir), "start", "--stage", "phase1", "--pid", str(pid)]) == EXIT_OK
    stage = Stage(stage_dir)

    # 1. Illegal transition: done --accept-failure from running (only allowed from failed)
    with pytest.raises(IllegalTransition) as exc_info:
        stage.done(summary="premature accept failure", accept_failure=True)
    assert exc_info.value.exit_code == EXIT_ILLEGAL_TRANSITION == 3

    capsys.readouterr()
    rc_acc_fail = main(["--dir", str(stage_dir), "done", "--summary", "premature accept failure", "--accept-failure"])
    assert rc_acc_fail == EXIT_ILLEGAL_TRANSITION == 3
    err_out = capsys.readouterr().err
    assert "stage-signal: error:" in err_out
    assert "done --accept-failure only allowed from state 'failed'" in err_out

    # 2. Failed --require-proof gate
    missing_proof = str(tmp_path / "missing_proof.json")
    with pytest.raises(IllegalTransition) as exc_info:
        stage.done(summary="done with proof", require_proof=missing_proof)
    assert exc_info.value.exit_code == EXIT_ILLEGAL_TRANSITION == 3

    capsys.readouterr()
    rc_proof = main([
        "--dir",
        str(stage_dir),
        "done",
        "--summary",
        "done with proof",
        "--require-proof",
        "--proof-ref",
        missing_proof,
    ])
    assert rc_proof == EXIT_ILLEGAL_TRANSITION == 3
    err_out = capsys.readouterr().err
    assert "stage-signal: error: proof gate failed:" in err_out

    # 3. Illegal reclaim when needs_reclaim is false
    with pytest.raises(IllegalTransition) as exc_info:
        stage.reclaim(reason="premature reclaim")
    assert exc_info.value.exit_code == EXIT_ILLEGAL_TRANSITION == 3

    capsys.readouterr()
    rc_reclaim = main(["--dir", str(stage_dir), "reclaim", "--reason", "premature reclaim"])
    assert rc_reclaim == EXIT_ILLEGAL_TRANSITION == 3
    err_out = capsys.readouterr().err
    assert "stage-signal: error:" in err_out

    # 4. Transition not allowed from terminal state: complete to done, then attempt blocked
    assert main(["--dir", str(stage_dir), "done", "--summary", "completed"]) == EXIT_OK
    with pytest.raises(IllegalTransition) as exc_info:
        stage.blocked(reason="cannot block after done")
    assert exc_info.value.exit_code == EXIT_ILLEGAL_TRANSITION == 3

    capsys.readouterr()
    rc_term = main(["--dir", str(stage_dir), "blocked", "--reason", "cannot block after done"])
    assert rc_term == EXIT_ILLEGAL_TRANSITION == 3
    err_out = capsys.readouterr().err
    assert "stage-signal: error: blocked not allowed from terminal state 'done'" in err_out


def test_corrupt_status_error_library_and_cli_exit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CorruptStatusError raised by library maps to EXIT_ERROR (1) in CLI (SPEC §7, §13.4, §13.17)."""
    stage_dir = tmp_path / ".stage-signal"
    assert main(["--dir", str(stage_dir), "init", "--project", "corrupt-test"]) == EXIT_OK
    stage = Stage(stage_dir)
    status_file = stage_dir / "STATUS.json"

    # Malformed JSON in STATUS.json
    status_file.write_text("{malformed: json")

    with pytest.raises(CorruptStatusError) as exc_info:
        stage.status()
    assert exc_info.value.exit_code == EXIT_ERROR == 1

    capsys.readouterr()
    rc_corrupt = main(["--dir", str(stage_dir), "status"])
    assert rc_corrupt == EXIT_ERROR == 1
    err_out = capsys.readouterr().err
    assert "stage-signal: error: corrupt STATUS.json" in err_out

    # Invalid schema (missing required keys)
    status_file.write_text(json.dumps({"schema_version": 1, "state": "running"}))

    with pytest.raises(CorruptStatusError) as exc_info:
        stage.status()
    assert exc_info.value.exit_code == EXIT_ERROR == 1

    capsys.readouterr()
    rc_invalid_schema = main(["--dir", str(stage_dir), "status"])
    assert rc_invalid_schema == EXIT_ERROR == 1
    err_out = capsys.readouterr().err
    assert "stage-signal: error:" in err_out
    assert "missing keys:" in err_out


def test_wait_timeout_library_and_cli_exit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """WaitTimeout raised by library maps to EXIT_WAIT_TIMEOUT (14) in CLI (SPEC §7, §13.4, §13.17)."""
    stage_dir = tmp_path / ".stage-signal"
    pid = os.getpid()
    assert main(["--dir", str(stage_dir), "init", "--project", "wait-test"]) == EXIT_OK
    assert main(["--dir", str(stage_dir), "start", "--stage", "step1", "--pid", str(pid)]) == EXIT_OK
    stage = Stage(stage_dir)

    # Library call raises WaitTimeout with exit_code 14 and populates last_status
    with pytest.raises(WaitTimeout) as exc_info:
        stage.wait(want="done", timeout=0.05, poll=0.01)
    assert exc_info.value.exit_code == EXIT_WAIT_TIMEOUT == 14
    assert exc_info.value.last_status is not None
    assert exc_info.value.last_status["state"] == "running"

    # CLI human output
    capsys.readouterr()
    rc_human = main(["--dir", str(stage_dir), "wait", "--state", "done", "--timeout", "0.05", "--poll", "0.01"])
    assert rc_human == EXIT_WAIT_TIMEOUT == 14
    err_human = capsys.readouterr().err
    assert "stage-signal: error: wait timed out after" in err_human

    # CLI JSON output
    capsys.readouterr()
    rc_json = main(["--dir", str(stage_dir), "wait", "--state", "done", "--timeout", "0.05", "--poll", "0.01", "--json"])
    assert rc_json == EXIT_WAIT_TIMEOUT == 14
    payload = json.loads(capsys.readouterr().out)
    assert payload["outcome"] == "timeout"
    assert payload["exit_code"] == EXIT_WAIT_TIMEOUT == 14
    assert payload["timeout"] is True


def test_stage_error_base_cli_exit(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Direct or generic StageError caught by CLI exits with EXIT_ERROR (1) (SPEC §7, §13.4, §13.17)."""
    # Verify base StageError instance
    err = StageError("generic stage failure", detail="details")
    assert err.exit_code == EXIT_ERROR == 1
    assert err.detail == "details"
    assert str(err) == "generic stage failure"

    # Monkeypatch a Stage method to raise raw StageError
    monkeypatch.setattr(
        "stage_signal.cli.Stage.status",
        lambda self: (_ for _ in ()).throw(StageError("simulated unhandled stage error")),
    )
    capsys.readouterr()
    rc = main(["status"])
    assert rc == EXIT_ERROR == 1
    err_out = capsys.readouterr().err
    assert "stage-signal: error: simulated unhandled stage error" in err_out

# =============================================================================
# 16. STATUS.md human-mirror required sections freeze (SPEC §13.18, issue #130)
# =============================================================================


def test_status_md_constants_freeze() -> None:
    """STATUS_MD constants match the frozen tuple in SPEC §13.18."""
    assert STATUS_MD_TITLE == "# stage-signal STATUS"
    assert isinstance(STATUS_MD_TITLE, str)

    expected_required_headings = (
        "# stage-signal STATUS",
        "state:",
        "stage:",
        "stage_id:",
        "attempt:",
        "project:",
        "updated:",
        "heartbeat:",
    )
    assert STATUS_MD_REQUIRED_HEADINGS == expected_required_headings
    assert isinstance(STATUS_MD_REQUIRED_HEADINGS, tuple)
    for heading in STATUS_MD_REQUIRED_HEADINGS:
        assert isinstance(heading, str)

    expected_optional_headings = (
        "heartbeat_note:",
        "result:",
        "error:",
    )
    assert STATUS_MD_OPTIONAL_HEADINGS == expected_optional_headings
    assert isinstance(STATUS_MD_OPTIONAL_HEADINGS, tuple)
    for heading in STATUS_MD_OPTIONAL_HEADINGS:
        assert isinstance(heading, str)

    assert STATUS_MD_HEADINGS == STATUS_MD_REQUIRED_HEADINGS + STATUS_MD_OPTIONAL_HEADINGS


def test_status_md_constants_exported_from_top_level() -> None:
    """STATUS_MD constants and renderer are exported from top-level stage_signal (SPEC §13.18)."""
    import stage_signal

    for symbol in (
        "STATUS_MD_TITLE",
        "STATUS_MD_REQUIRED_HEADINGS",
        "STATUS_MD_OPTIONAL_HEADINGS",
        "STATUS_MD_HEADINGS",
        "render_status_md",
    ):
        assert hasattr(stage_signal, symbol), f"missing {symbol} attribute"
        assert symbol in stage_signal.__all__, f"{symbol} not in __all__"

    assert stage_signal.STATUS_MD_REQUIRED_HEADINGS is STATUS_MD_REQUIRED_HEADINGS
    assert stage_signal.STATUS_MD_TITLE is STATUS_MD_TITLE
    assert stage_signal.render_status_md is render_status_md


def test_status_md_render_each_lifecycle_state() -> None:
    """render_status_md emits all required headings for each lifecycle state (SPEC §13.18)."""
    # 1. State: queued (initial state after init)
    queued_status: dict[str, Any] = {
        "schema_version": 1,
        "project": "test-project",
        "stage_id": None,
        "stage_name": None,
        "state": "queued",
        "attempt": 1,
        "session_id": None,
        "pid": None,
        "model": None,
        "variant": None,
        "repo_path": "/path/to/repo",
        "git_branch": "main",
        "git_head": "abc1234",
        "started_at": None,
        "updated_at": "2026-09-18T10:00:00+00:00",
        "heartbeat_at": None,
        "heartbeat_note": None,
        "result": None,
        "error": None,
        "artifacts": [],
        "proof": None,
        "notes": [],
        "meta": {},
    }
    md_queued = render_status_md(queued_status)
    assert md_queued.startswith(STATUS_MD_TITLE)
    for heading in STATUS_MD_REQUIRED_HEADINGS:
        assert heading in md_queued
    assert "state: queued" in md_queued
    assert "stage: None" in md_queued
    assert "heartbeat: None" in md_queued
    assert "heartbeat_note:" not in md_queued
    assert "result:" not in md_queued
    assert "error:" not in md_queued

    # 2. State: running
    running_status: dict[str, Any] = {
        **queued_status,
        "state": "running",
        "stage_name": "build-step",
        "stage_id": "build-step-001",
        "pid": 12345,
        "started_at": "2026-09-18T10:01:00+00:00",
        "updated_at": "2026-09-18T10:02:00+00:00",
        "heartbeat_at": "2026-09-18T10:02:00+00:00",
    }
    md_running = render_status_md(running_status)
    assert md_running.startswith(STATUS_MD_TITLE)
    for heading in STATUS_MD_REQUIRED_HEADINGS:
        assert heading in md_running
    assert "state: running" in md_running
    assert "stage: build-step" in md_running
    assert "stage_id: build-step-001" in md_running
    assert "heartbeat: 2026-09-18T10:02:00+00:00" in md_running
    assert "result:" not in md_running
    assert "error:" not in md_running

    # 3. State: running with heartbeat_note
    running_note_status: dict[str, Any] = {
        **running_status,
        "heartbeat_note": "compiling assets",
    }
    md_running_note = render_status_md(running_note_status)
    for heading in STATUS_MD_REQUIRED_HEADINGS:
        assert heading in md_running_note
    assert "heartbeat_note: compiling assets" in md_running_note

    # 4. State: done (terminal)
    done_status: dict[str, Any] = {
        **running_status,
        "state": "done",
        "updated_at": "2026-09-18T10:05:00+00:00",
        "result": {
            "summary": "build passed successfully",
            "git_head": "def5678",
            "finished_at": "2026-09-18T10:05:00+00:00",
        },
    }
    md_done = render_status_md(done_status)
    assert md_done.startswith(STATUS_MD_TITLE)
    for heading in STATUS_MD_REQUIRED_HEADINGS:
        assert heading in md_done
    assert "state: done" in md_done
    assert "result:" in md_done
    assert '"summary": "build passed successfully"' in md_done
    assert "error:" not in md_done

    # 5. State: blocked (terminal)
    blocked_status: dict[str, Any] = {
        **running_status,
        "state": "blocked",
        "updated_at": "2026-09-18T10:03:00+00:00",
        "error": {
            "reason": "waiting for external credential",
            "kind": "blocked",
            "finished_at": "2026-09-18T10:03:00+00:00",
        },
    }
    md_blocked = render_status_md(blocked_status)
    assert md_blocked.startswith(STATUS_MD_TITLE)
    for heading in STATUS_MD_REQUIRED_HEADINGS:
        assert heading in md_blocked
    assert "state: blocked" in md_blocked
    assert "error:" in md_blocked
    assert '"reason": "waiting for external credential"' in md_blocked
    assert '"kind": "blocked"' in md_blocked
    assert "result:" not in md_blocked

    # 6. State: failed (terminal)
    failed_status: dict[str, Any] = {
        **running_status,
        "state": "failed",
        "updated_at": "2026-09-18T10:04:00+00:00",
        "error": {
            "reason": "test failure in test_foo",
            "kind": "failed",
            "finished_at": "2026-09-18T10:04:00+00:00",
        },
    }
    md_failed = render_status_md(failed_status)
    assert md_failed.startswith(STATUS_MD_TITLE)
    for heading in STATUS_MD_REQUIRED_HEADINGS:
        assert heading in md_failed
    assert "state: failed" in md_failed
    assert "error:" in md_failed
    assert '"reason": "test failure in test_foo"' in md_failed
    assert '"kind": "failed"' in md_failed
    assert "result:" not in md_failed


def test_status_md_readers_tolerate_extra_sections() -> None:
    """Readers and parsers MUST tolerate unknown extra sections and fields (SPEC §13.1, §13.18)."""
    # 1. Extra fields in status dict passed to renderer
    status_with_extras = {
        "schema_version": 1,
        "project": "extra-test",
        "stage_id": "s1",
        "stage_name": "s1",
        "state": "running",
        "attempt": 1,
        "updated_at": "2026-09-18T10:00:00+00:00",
        "heartbeat_at": "2026-09-18T10:00:00+00:00",
        "unknown_future_field": "future_value",
        "nested_metadata": {"foo": "bar", "count": 42},
    }
    rendered = render_status_md(status_with_extras)
    for heading in STATUS_MD_REQUIRED_HEADINGS:
        assert heading in rendered

    # 2. STATUS.md containing extra sections appended by future schema/writers
    augmented_md = rendered + "\n## Future Extensions\nfuture_field: 42\ncustom_note: hello\n"
    # An observer looking for required headings must find all of them intact
    for heading in STATUS_MD_REQUIRED_HEADINGS:
        assert heading in augmented_md

    # Line-by-line parsing extracts required headings despite extra content
    parsed: dict[str, str] = {}
    for line in augmented_md.splitlines():
        if ": " in line:
            k, v = line.split(": ", 1)
            parsed[k.strip()] = v.strip()

    assert parsed.get("state") == "running"
    assert parsed.get("stage") == "s1"
    assert parsed.get("project") == "extra-test"
    assert parsed.get("future_field") == "42"


def test_write_status_md_best_effort_never_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """StageStore.write_status_md is best-effort and never raises on error (SPEC §2, §13.18)."""
    stage_dir = tmp_path / ".stage-signal"
    store = StageStore(stage_dir)
    status = {
        "state": "running",
        "stage_name": "test",
        "stage_id": "test-1",
        "attempt": 1,
        "project": "test",
        "updated_at": "2026-09-18T10:00:00+00:00",
        "heartbeat_at": "2026-09-18T10:00:00+00:00",
    }

    # 1. Normal write works
    store.write_status_md(status)
    assert (stage_dir / "STATUS.md").is_file()
    content = (stage_dir / "STATUS.md").read_text(encoding="utf-8")
    for heading in STATUS_MD_REQUIRED_HEADINGS:
        assert heading in content

    # 2. Mock mkstemp raising OSError (e.g. disk full / readonly)
    def broken_mkstemp(*args: Any, **kwargs: Any) -> Any:
        raise OSError("Disk quota exceeded")

    monkeypatch.setattr("tempfile.mkstemp", broken_mkstemp)
    # Must NOT raise
    store.write_status_md(status)

    # 3. Mock os.replace raising PermissionError
    monkeypatch.undo()

    def broken_replace(src: Any, dst: Any) -> None:
        raise PermissionError("Access denied")

    monkeypatch.setattr("os.replace", broken_replace)
    # Must NOT raise
    store.write_status_md(status)

    # 4. Non-dict input passed to write_status_md
    monkeypatch.undo()
    # Must NOT raise even if bad input causes render failure
    store.write_status_md(None)  # type: ignore[arg-type]
    store.write_status_md("invalid-string")  # type: ignore[arg-type]


def test_status_md_on_disk_lifecycle_smoke(tmp_path: Path) -> None:
    """On-disk STATUS.md mirror is updated with required headings across lifecycle (SPEC §2, §13.18)."""
    stage_dir = tmp_path / ".stage-signal"
    st = Stage(str(stage_dir))

    # 1. init -> queued
    st.init(project="lifecycle-mirror-test")
    md_path = stage_dir / "STATUS.md"
    assert md_path.is_file()
    content_queued = md_path.read_text(encoding="utf-8")
    for heading in STATUS_MD_REQUIRED_HEADINGS:
        assert heading in content_queued
    assert "state: queued" in content_queued

    # 2. start -> running
    st.start(stage="task-1", pid=os.getpid())
    content_running = md_path.read_text(encoding="utf-8")
    for heading in STATUS_MD_REQUIRED_HEADINGS:
        assert heading in content_running
    assert "state: running" in content_running
    assert "stage: task-1" in content_running

    # 3. heartbeat with note
    st.heartbeat(note="in progress")
    content_note = md_path.read_text(encoding="utf-8")
    for heading in STATUS_MD_REQUIRED_HEADINGS:
        assert heading in content_note
    assert "heartbeat_note: in progress" in content_note

    # 4. done -> terminal done
    st.done(summary="task finished successfully")
    content_done = md_path.read_text(encoding="utf-8")
    for heading in STATUS_MD_REQUIRED_HEADINGS:
        assert heading in content_done
    assert "state: done" in content_done
    assert "result:" in content_done
    assert '"summary": "task finished successfully"' in content_done

    # 5. start new stage and fail -> terminal failed
    st.start(stage="task-2", pid=os.getpid())
    st.fail(reason="fatal failure encountered")
    content_failed = md_path.read_text(encoding="utf-8")
    for heading in STATUS_MD_REQUIRED_HEADINGS:
        assert heading in content_failed
    assert "state: failed" in content_failed
    assert "error:" in content_failed
    assert '"reason": "fatal failure encountered"' in content_failed


# ============================================================================
# 19. Allowed transition matrix freeze (SPEC §13.19, issue #133)
# ============================================================================


def test_allowed_transitions_constant_freeze() -> None:
    """ALLOWED_TRANSITIONS dict and helpers match SPEC §13.19 exactly."""
    expected_transitions = {
        # start: allowed from any state -> running (SPEC §4.2, §13.19)
        ("queued", "start"): "running",
        ("running", "start"): "running",
        ("done", "start"): "running",
        ("blocked", "start"): "running",
        ("failed", "start"): "running",

        # heartbeat, note, artifact: stay running (SPEC §4.3, §4.4, §13.19)
        ("running", "heartbeat"): "running",
        ("running", "note"): "running",
        ("running", "artifact"): "running",

        # done: allowed from queued, running, or idempotent done -> done (SPEC §4.5, §13.19)
        ("queued", "done"): "done",
        ("running", "done"): "done",
        ("done", "done"): "done",

        # done --accept-failure: allowed only from failed -> done (SPEC §4.5, §13.19)
        ("failed", "done --accept-failure"): "done",
        ("failed", "done_accept_failure"): "done",

        # blocked: allowed from queued, running, or idempotent blocked -> blocked (SPEC §4.6, §13.19)
        ("queued", "blocked"): "blocked",
        ("running", "blocked"): "blocked",
        ("blocked", "blocked"): "blocked",

        # fail: allowed from queued, running, or idempotent failed -> failed (SPEC §4.6, §13.19)
        ("queued", "fail"): "failed",
        ("running", "fail"): "failed",
        ("failed", "fail"): "failed",
        ("queued", "fail --if-dead-pid"): "failed",
        ("running", "fail --if-dead-pid"): "failed",
        ("failed", "fail --if-dead-pid"): "failed",
        ("running", "fail --if-needs-reclaim"): "failed",

        # clear-terminal: allowed from terminal states or queued -> idle queued (SPEC §4.8, §13.19)
        ("done", "clear-terminal"): "queued",
        ("blocked", "clear-terminal"): "queued",
        ("failed", "clear-terminal"): "queued",
        ("queued", "clear-terminal"): "queued",
        ("done", "clear_terminal"): "queued",
        ("blocked", "clear_terminal"): "queued",
        ("failed", "clear_terminal"): "queued",
        ("queued", "clear_terminal"): "queued",

        # reclaim: running with needs_reclaim -> failed [+ optional clear_terminal] (SPEC §4.7, §13.19)
        ("running", "reclaim"): "queued",
        ("running", "reclaim --keep-failed"): "failed",
        ("running", "reclaim_keep_failed"): "failed",
    }

    assert isinstance(ALLOWED_TRANSITIONS, dict)
    assert ALLOWED_TRANSITIONS == expected_transitions

    # Every from_state and to_state must be a valid state in STATES
    for (from_state, cmd), to_state in ALLOWED_TRANSITIONS.items():
        assert from_state in STATES, f"Unknown from_state: {from_state!r}"
        assert to_state in STATES, f"Unknown to_state: {to_state!r}"
        assert isinstance(cmd, str) and len(cmd) > 0

    # Top-level exports from stage_signal
    import stage_signal

    assert getattr(stage_signal, "ALLOWED_TRANSITIONS") is ALLOWED_TRANSITIONS
    assert "ALLOWED_TRANSITIONS" in stage_signal.__all__
    assert "is_transition_allowed" in stage_signal.__all__
    assert "transition_target" in stage_signal.__all__
    assert "allowed_source_states" in stage_signal.__all__

    # Test helper functions
    assert allowed_source_states("heartbeat") == ("running",)
    assert allowed_source_states("note") == ("running",)
    assert allowed_source_states("artifact") == ("running",)
    assert set(allowed_source_states("start")) == set(STATES)
    assert set(allowed_source_states("done")) == {"queued", "running", "done"}
    assert allowed_source_states("done --accept-failure") == ("failed",)
    assert set(allowed_source_states("blocked")) == {"queued", "running", "blocked"}
    assert set(allowed_source_states("fail")) == {"queued", "running", "failed"}
    assert set(allowed_source_states("clear-terminal")) == {"done", "blocked", "failed", "queued"}
    assert set(allowed_source_states("clear_terminal")) == {"done", "blocked", "failed", "queued"}
    assert allowed_source_states("reclaim") == ("running",)

    assert is_transition_allowed("queued", "start") is True
    assert is_transition_allowed("running", "heartbeat") is True
    assert is_transition_allowed("done", "clear-terminal") is True
    assert is_transition_allowed("failed", "done --accept-failure") is True
    assert is_transition_allowed("running", "reclaim") is True

    assert transition_target("queued", "start") == "running"
    assert transition_target("running", "done") == "done"
    assert transition_target("running", "heartbeat") == "running"
    assert transition_target("failed", "done --accept-failure") == "done"
    assert transition_target("done", "clear-terminal") == "queued"
    assert transition_target("running", "reclaim") == "queued"
    assert transition_target("running", "reclaim --keep-failed") == "failed"

    with pytest.raises(ValueError, match="illegal transition"):
        transition_target("done", "blocked")
    with pytest.raises(ValueError, match="illegal transition"):
        transition_target("running", "clear-terminal")


def test_allowed_transitions_matrix_exhaustive_checks() -> None:
    """Exhaustive check across all (state, command) pairs matches ALLOWED_TRANSITIONS (SPEC §13.19)."""
    core_commands = (
        "start",
        "heartbeat",
        "note",
        "artifact",
        "done",
        "done --accept-failure",
        "blocked",
        "fail",
        "clear-terminal",
        "reclaim",
    )

    for state in STATES:
        for cmd in core_commands:
            allowed = is_transition_allowed(state, cmd)
            if allowed:
                target = transition_target(state, cmd)
                assert target in STATES
                assert (state, cmd) in ALLOWED_TRANSITIONS
                assert ALLOWED_TRANSITIONS[(state, cmd)] == target
            else:
                assert (state, cmd) not in ALLOWED_TRANSITIONS
                with pytest.raises(ValueError):
                    transition_target(state, cmd)


def test_representative_legal_transitions_lifecycle(tmp_path: Path) -> None:
    """Representative legal lifecycle paths execute cleanly and match ALLOWED_TRANSITIONS (SPEC §4, §13.19)."""
    stage_dir = tmp_path / ".stage-signal"
    st = Stage(str(stage_dir))

    # 1. init -> queued
    status = st.init(project="trans-lifecycle")
    assert status["state"] == "queued"
    assert is_transition_allowed("queued", "start")

    # 2. queued -> start -> running
    status = st.start(stage="task-1", pid=os.getpid())
    assert status["state"] == "running"
    assert status["stage_name"] == "task-1"
    assert status["attempt"] == 1

    # 3. running -> heartbeat / note / artifact -> running
    st.heartbeat(note="working")
    st.note("note 1")
    st.artifact(str(tmp_path / "art.txt"), label="test-artifact")
    curr = st.status()
    assert curr["state"] == "running"
    assert curr["heartbeat_note"] == "working"
    assert len(curr["notes"]) == 1
    assert len(curr["artifacts"]) == 1

    # 4. running -> done -> done (terminal)
    status = st.done(summary="task-1 success")
    assert status["state"] == "done"
    assert status["result"]["summary"] == "task-1 success"

    # 5. done -> done (idempotent repeat)
    status = st.done(summary="task-1 success updated")
    assert status["state"] == "done"
    assert status["result"]["summary"] == "task-1 success updated"

    # 6. done -> clear-terminal -> queued (idle reset)
    status = st.clear_terminal()
    assert status["state"] == "queued"
    assert status["stage_id"] is None
    assert status["stage_name"] is None

    # 7. queued -> start -> running (new stage)
    status = st.start(stage="task-2", pid=os.getpid())
    assert status["state"] == "running"
    assert status["stage_name"] == "task-2"

    # 8. running -> blocked -> blocked (terminal)
    status = st.blocked(reason="waiting on lock")
    assert status["state"] == "blocked"
    assert status["error"]["reason"] == "waiting on lock"

    # 9. blocked -> blocked (idempotent repeat)
    status = st.blocked(reason="still waiting on lock")
    assert status["state"] == "blocked"
    assert status["error"]["reason"] == "still waiting on lock"

    # 10. blocked -> clear-terminal (keep_stage=True) -> queued
    status = st.clear_terminal(keep_stage=True)
    assert status["state"] == "queued"
    assert status["stage_name"] == "task-2"

    # 11. queued -> start -> running
    status = st.start(stage="task-3", pid=os.getpid())
    assert status["state"] == "running"

    # 12. running -> fail -> failed (terminal)
    status = st.fail(reason="compile error")
    assert status["state"] == "failed"
    assert status["error"]["reason"] == "compile error"

    # 13. failed -> fail (idempotent repeat)
    status = st.fail(reason="compile error updated")
    assert status["state"] == "failed"

    # 14. failed -> done --accept-failure -> done
    status = st.done(summary="accepted compile failure", accept_failure=True)
    assert status["state"] == "done"
    assert status["result"]["accepted_failure"] is True

    # 15. done -> start -> running, then dead PID -> reclaim --keep-failed -> failed
    dead_proc = subprocess.Popen([sys.executable, "-c", "pass"])
    dead_proc.wait(timeout=5)
    st.start(stage="task-4", pid=dead_proc.pid)
    status = st.reclaim(reason="worker died", keep_failed=True)
    assert status["state"] == "failed"
    assert status["error"]["reason"] == "worker died"

    # 16. failed -> clear-terminal -> queued
    status = st.clear_terminal()
    assert status["state"] == "queued"

    # 17. queued -> start -> running, then dead PID -> reclaim -> queued (default)
    dead_proc2 = subprocess.Popen([sys.executable, "-c", "pass"])
    dead_proc2.wait(timeout=5)
    st.start(stage="task-5", pid=dead_proc2.pid)
    status = st.reclaim(reason="worker died again")
    assert status["state"] == "queued"
    events = st.events()
    assert events[-2]["type"] == "failed"
    assert events[-1]["type"] == "clear_terminal"


def test_representative_illegal_transitions_raise_and_cli_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Representative illegal transitions raise IllegalTransition and exit 3 on CLI without mutating status (SPEC §13.17, §13.19)."""
    stage_dir = tmp_path / ".stage-signal"
    st = Stage(str(stage_dir))
    st.init(project="illegal-trans-paths")
    status_file = stage_dir / "STATUS.json"
    initial_content = status_file.read_text(encoding="utf-8")

    def assert_no_mutation() -> None:
        assert status_file.read_text(encoding="utf-8") == initial_content

    # ------------------------------------------------------------------------
    # A. From queued
    # ------------------------------------------------------------------------
    # 1. queued -> heartbeat (illegal)
    with pytest.raises(IllegalTransition):
        st.heartbeat()
    assert_no_mutation()
    assert main(["--dir", str(stage_dir), "heartbeat"]) == EXIT_ILLEGAL_TRANSITION
    capsys.readouterr()
    assert_no_mutation()

    # 2. queued -> note (illegal)
    with pytest.raises(IllegalTransition):
        st.note("note on queued")
    assert_no_mutation()
    assert main(["--dir", str(stage_dir), "note", "note on queued"]) == EXIT_ILLEGAL_TRANSITION
    capsys.readouterr()
    assert_no_mutation()

    # 3. queued -> artifact (illegal)
    with pytest.raises(IllegalTransition):
        st.artifact("art.txt")
    assert_no_mutation()
    assert main(["--dir", str(stage_dir), "artifact", "art.txt"]) == EXIT_ILLEGAL_TRANSITION
    capsys.readouterr()
    assert_no_mutation()

    # 4. queued -> done --accept-failure (illegal)
    with pytest.raises(IllegalTransition, match="only allowed from state 'failed'"):
        st.done(accept_failure=True)
    assert_no_mutation()
    assert main(["--dir", str(stage_dir), "done", "--accept-failure"]) == EXIT_ILLEGAL_TRANSITION
    capsys.readouterr()
    assert_no_mutation()

    # 5. queued -> reclaim (illegal)
    with pytest.raises(IllegalTransition, match="needs_reclaim is false"):
        st.reclaim(reason="reclaim queued")
    assert_no_mutation()
    assert main(["--dir", str(stage_dir), "reclaim", "--reason", "reclaim queued"]) == EXIT_ILLEGAL_TRANSITION
    capsys.readouterr()
    assert_no_mutation()

    # ------------------------------------------------------------------------
    # B. From running
    # ------------------------------------------------------------------------
    st.start(stage="live-run", pid=os.getpid())
    running_content = status_file.read_text(encoding="utf-8")

    # 1. running -> clear-terminal (illegal)
    with pytest.raises(IllegalTransition, match="only terminal states"):
        st.clear_terminal()
    assert status_file.read_text(encoding="utf-8") == running_content
    assert main(["--dir", str(stage_dir), "clear-terminal"]) == EXIT_ILLEGAL_TRANSITION
    capsys.readouterr()
    assert status_file.read_text(encoding="utf-8") == running_content

    # 2. running -> done --accept-failure (illegal)
    with pytest.raises(IllegalTransition, match="only allowed from state 'failed'"):
        st.done(accept_failure=True)
    assert status_file.read_text(encoding="utf-8") == running_content
    assert main(["--dir", str(stage_dir), "done", "--accept-failure"]) == EXIT_ILLEGAL_TRANSITION
    capsys.readouterr()
    assert status_file.read_text(encoding="utf-8") == running_content

    # 3. running (healthy live PID) -> reclaim (illegal)
    with pytest.raises(IllegalTransition, match="needs_reclaim is false"):
        st.reclaim(reason="premature reclaim")
    assert status_file.read_text(encoding="utf-8") == running_content
    assert main(["--dir", str(stage_dir), "reclaim", "--reason", "premature reclaim"]) == EXIT_ILLEGAL_TRANSITION
    capsys.readouterr()
    assert status_file.read_text(encoding="utf-8") == running_content

    # 4. running (healthy live PID) -> fail --if-needs-reclaim (illegal)
    with pytest.raises(IllegalTransition, match="needs_reclaim is false"):
        st.fail(reason="premature fail", if_needs_reclaim=True)
    assert status_file.read_text(encoding="utf-8") == running_content
    assert main(["--dir", str(stage_dir), "fail", "--reason", "premature fail", "--if-needs-reclaim"]) == EXIT_ILLEGAL_TRANSITION
    capsys.readouterr()
    assert status_file.read_text(encoding="utf-8") == running_content

    # 5. running (healthy live PID) -> fail --if-dead-pid (illegal)
    with pytest.raises(IllegalTransition, match="is alive"):
        st.fail(reason="alive fail", if_dead_pid=True)
    assert status_file.read_text(encoding="utf-8") == running_content
    assert main(["--dir", str(stage_dir), "fail", "--reason", "alive fail", "--if-dead-pid"]) == EXIT_ILLEGAL_TRANSITION
    capsys.readouterr()
    assert status_file.read_text(encoding="utf-8") == running_content

    # ------------------------------------------------------------------------
    # C. From terminal done
    # ------------------------------------------------------------------------
    st.done(summary="finished task")
    done_content = status_file.read_text(encoding="utf-8")

    # 1. done -> heartbeat (illegal)
    with pytest.raises(IllegalTransition):
        st.heartbeat()
    assert status_file.read_text(encoding="utf-8") == done_content
    assert main(["--dir", str(stage_dir), "heartbeat"]) == EXIT_ILLEGAL_TRANSITION
    capsys.readouterr()

    # 2. done -> blocked (illegal terminal-to-terminal)
    with pytest.raises(IllegalTransition, match="blocked not allowed from terminal state 'done'"):
        st.blocked(reason="cannot block after done")
    assert status_file.read_text(encoding="utf-8") == done_content
    assert main(["--dir", str(stage_dir), "blocked", "--reason", "cannot block"]) == EXIT_ILLEGAL_TRANSITION
    capsys.readouterr()

    # 3. done -> fail (illegal terminal-to-terminal)
    with pytest.raises(IllegalTransition, match="fail not allowed from terminal state 'done'"):
        st.fail(reason="cannot fail after done")
    assert status_file.read_text(encoding="utf-8") == done_content
    assert main(["--dir", str(stage_dir), "fail", "--reason", "cannot fail"]) == EXIT_ILLEGAL_TRANSITION
    capsys.readouterr()

    # 4. done -> done --accept-failure (illegal)
    with pytest.raises(IllegalTransition, match="only allowed from state 'failed'"):
        st.done(accept_failure=True)
    assert status_file.read_text(encoding="utf-8") == done_content
    assert main(["--dir", str(stage_dir), "done", "--accept-failure"]) == EXIT_ILLEGAL_TRANSITION
    capsys.readouterr()

    # 5. done -> reclaim (illegal)
    with pytest.raises(IllegalTransition, match="needs_reclaim is false"):
        st.reclaim(reason="cannot reclaim done")
    assert status_file.read_text(encoding="utf-8") == done_content
    assert main(["--dir", str(stage_dir), "reclaim", "--reason", "cannot reclaim done"]) == EXIT_ILLEGAL_TRANSITION
    capsys.readouterr()

    # ------------------------------------------------------------------------
    # D. From terminal blocked
    # ------------------------------------------------------------------------
    st.start(stage="blocked-task", pid=os.getpid())
    st.blocked(reason="need manual intervention")
    blocked_content = status_file.read_text(encoding="utf-8")

    # 1. blocked -> done (illegal terminal-to-terminal)
    with pytest.raises(IllegalTransition, match="done not allowed from terminal state 'blocked'"):
        st.done(summary="cannot done after blocked")
    assert status_file.read_text(encoding="utf-8") == blocked_content
    assert main(["--dir", str(stage_dir), "done", "--summary", "cannot done"]) == EXIT_ILLEGAL_TRANSITION
    capsys.readouterr()

    # 2. blocked -> fail (illegal terminal-to-terminal)
    with pytest.raises(IllegalTransition, match="fail not allowed from terminal state 'blocked'"):
        st.fail(reason="cannot fail after blocked")
    assert status_file.read_text(encoding="utf-8") == blocked_content
    assert main(["--dir", str(stage_dir), "fail", "--reason", "cannot fail"]) == EXIT_ILLEGAL_TRANSITION
    capsys.readouterr()

    # 3. blocked -> done --accept-failure (illegal)
    with pytest.raises(IllegalTransition, match="only allowed from state 'failed'"):
        st.done(accept_failure=True)
    assert status_file.read_text(encoding="utf-8") == blocked_content
    assert main(["--dir", str(stage_dir), "done", "--accept-failure"]) == EXIT_ILLEGAL_TRANSITION
    capsys.readouterr()

    # ------------------------------------------------------------------------
    # E. From terminal failed
    # ------------------------------------------------------------------------
    st.start(stage="failed-task", pid=os.getpid())
    st.fail(reason="unhandled exception")
    failed_content = status_file.read_text(encoding="utf-8")

    # 1. failed -> done without accept_failure (illegal terminal-to-terminal)
    with pytest.raises(IllegalTransition, match="done not allowed from terminal state 'failed'"):
        st.done(summary="cannot done after failed without accept_failure")
    assert status_file.read_text(encoding="utf-8") == failed_content
    assert main(["--dir", str(stage_dir), "done", "--summary", "cannot done"]) == EXIT_ILLEGAL_TRANSITION
    capsys.readouterr()

    # 2. failed -> blocked (illegal terminal-to-terminal)
    with pytest.raises(IllegalTransition, match="blocked not allowed from terminal state 'failed'"):
        st.blocked(reason="cannot block after failed")
    assert status_file.read_text(encoding="utf-8") == failed_content
    assert main(["--dir", str(stage_dir), "blocked", "--reason", "cannot block"]) == EXIT_ILLEGAL_TRANSITION
    capsys.readouterr()

    # 3. failed -> reclaim (illegal)
    with pytest.raises(IllegalTransition, match="needs_reclaim is false"):
        st.reclaim(reason="cannot reclaim failed")
    assert status_file.read_text(encoding="utf-8") == failed_content
    assert main(["--dir", str(stage_dir), "reclaim", "--reason", "cannot reclaim failed"]) == EXIT_ILLEGAL_TRANSITION
    capsys.readouterr()
    assert status_file.read_text(encoding="utf-8") == failed_content


# =============================================================================
# 17. Stage public method surface freeze (SPEC §13.20, issue #134)
# =============================================================================


def test_stage_public_methods_constant_freeze() -> None:
    """STAGE_PUBLIC_METHODS matches the frozen tuple in SPEC §13.20."""
    expected = (
        "artifact",
        "blocked",
        "clear_terminal",
        "diagnose",
        "done",
        "events",
        "fail",
        "heartbeat",
        "init",
        "note",
        "reclaim",
        "start",
        "status",
        "supervise",
        "wait",
    )
    assert STAGE_PUBLIC_METHODS == expected
    assert isinstance(STAGE_PUBLIC_METHODS, tuple)
    assert len(STAGE_PUBLIC_METHODS) == 15
    assert STAGE_PUBLIC_METHODS == tuple(sorted(STAGE_PUBLIC_METHODS))

    # All methods required by issue #134 must be present
    mandatory_minimum = (
        "init",
        "start",
        "heartbeat",
        "note",
        "done",
        "blocked",
        "fail",
        "reclaim",
        "clear_terminal",
        "supervise",
        "status",
        "wait",
    )
    for method in mandatory_minimum:
        assert method in STAGE_PUBLIC_METHODS, f"Mandatory method {method!r} missing"

    for method in STAGE_PUBLIC_METHODS:
        assert isinstance(method, str)
        assert method
        assert method == method.strip()


def test_stage_public_methods_exported_from_top_level() -> None:
    """STAGE_PUBLIC_METHODS is exported from top-level stage_signal (SPEC §13.20)."""
    import stage_signal

    assert hasattr(stage_signal, "STAGE_PUBLIC_METHODS")
    assert "STAGE_PUBLIC_METHODS" in stage_signal.__all__
    assert stage_signal.STAGE_PUBLIC_METHODS is STAGE_PUBLIC_METHODS


def test_stage_public_methods_exist_and_callable(tmp_path: Path) -> None:
    """Every method in STAGE_PUBLIC_METHODS exists and is callable on Stage (SPEC §13.20)."""
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(stage_dir)

    for method_name in STAGE_PUBLIC_METHODS:
        assert hasattr(stage, method_name), f"Stage instance missing method {method_name!r}"
        method = getattr(stage, method_name)
        assert callable(method), f"Stage.{method_name} is not callable"
        # Must have docstring
        assert getattr(Stage, method_name).__doc__, f"Stage.{method_name} missing docstring"


def test_stage_public_methods_no_accidental_private_leakage() -> None:
    """No private names in STAGE_PUBLIC_METHODS and no unlisted public methods (SPEC §13.20)."""
    # 1. No private or dunder names in STAGE_PUBLIC_METHODS
    for method_name in STAGE_PUBLIC_METHODS:
        assert not method_name.startswith("_"), f"Private name {method_name!r} leaked into freeze list"

    # 2. All public callables on Stage (excluding classmethod open) match STAGE_PUBLIC_METHODS
    public_callables = {
        name
        for name in dir(Stage)
        if not name.startswith("_") and callable(getattr(Stage, name))
    }
    # open is a classmethod constructor; all others are instance methods
    assert public_callables == set(STAGE_PUBLIC_METHODS) | {"open"}

    # 3. dir is an exposed property on Stage, not a method
    assert hasattr(Stage, "dir")
    assert isinstance(getattr(Stage, "dir"), property)


def test_top_level_helpers_exported_and_callable() -> None:
    """Top-level helper functions cross-linked in SPEC §13.20 are exported and callable."""
    import stage_signal

    helpers = (
        "resolve_dir",
        "state_exit_code",
        "render_status_md",
        "write_status_mirror",
        "verify_proof",
        "wait_condition_met",
        "want_matches",
        "StageStore",
    )
    for helper in helpers:
        assert hasattr(stage_signal, helper), f"stage_signal missing helper {helper!r}"
        assert helper in stage_signal.__all__, f"{helper!r} not in stage_signal.__all__"
        attr = getattr(stage_signal, helper)
        assert callable(attr), f"{helper!r} is not callable"


def test_stage_public_methods_lifecycle_smoke(tmp_path: Path) -> None:
    """Smoke test exercising all 15 public methods on Stage (SPEC §11, §13.20)."""
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(stage_dir)

    # 1. init
    init_res = stage.init(project="smoke-proj")
    assert init_res["state"] == "queued"
    assert init_res["project"] == "smoke-proj"

    # 2. start
    start_res = stage.start(stage="smoke-step", pid=os.getpid())
    assert start_res["state"] == "running"
    assert start_res["stage_name"] == "smoke-step"

    # 3. heartbeat
    hb_res = stage.heartbeat(note="smoke heartbeat")
    assert hb_res["state"] == "running"
    assert hb_res["heartbeat_note"] == "smoke heartbeat"

    # 4. note
    note_res = stage.note("smoke note")
    assert note_res["state"] == "running"
    assert len(note_res["notes"]) == 1
    assert note_res["notes"][0]["text"] == "smoke note"

    # 5. artifact
    art_res = stage.artifact("dist/smoke.txt", label="report")
    assert art_res["state"] == "running"
    assert len(art_res["artifacts"]) == 1
    assert art_res["artifacts"][0]["path"] == "dist/smoke.txt"

    # 6. status
    st_res = stage.status()
    assert st_res["state"] == "running"
    assert st_res["stage_name"] == "smoke-step"

    # 7. events
    ev_res = stage.events()
    assert isinstance(ev_res, list)
    assert len(ev_res) >= 5

    # 8. diagnose
    diag_res = stage.diagnose()
    assert diag_res["ok"] is True
    assert diag_res["state"] == "running"

    # 9. done
    done_res = stage.done(summary="smoke complete")
    assert done_res["state"] == "done"
    assert done_res["result"]["summary"] == "smoke complete"

    # 10. wait (already met)
    wait_res = stage.wait(want="done", timeout=1, poll=0.01)
    assert wait_res["state"] == "done"

    # 11. clear_terminal
    clear_res = stage.clear_terminal()
    assert clear_res["state"] == "queued"
    assert clear_res["stage_name"] is None

    # 12. blocked
    stage.start(stage="smoke-block", pid=os.getpid())
    block_res = stage.blocked(reason="smoke blocked reason")
    assert block_res["state"] == "blocked"
    assert block_res["error"]["reason"] == "smoke blocked reason"
    stage.clear_terminal()

    # 13. fail
    stage.start(stage="smoke-fail", pid=os.getpid())
    fail_res = stage.fail(reason="smoke failed reason")
    assert fail_res["state"] == "failed"
    assert fail_res["error"]["reason"] == "smoke failed reason"
    stage.clear_terminal()

    # 14. supervise (runs command and auto-heartbeats to done)
    stage.start(stage="smoke-supervise", pid=os.getpid())
    rc = stage.supervise([sys.executable, "-c", "import sys; sys.exit(0)"])
    assert rc == 0
    assert stage.status()["state"] == "done"
    stage.clear_terminal()

    # 15. reclaim (with dead pid)
    dead_proc = subprocess.Popen([sys.executable, "-c", "pass"])
    dead_proc.wait(timeout=5)
    stage.start(stage="smoke-dead", pid=dead_proc.pid)
    assert stage.status()["needs_reclaim"] is True
    reclaim_res = stage.reclaim(reason="dead worker reclaim")
    assert reclaim_res["state"] == "queued"
    assert stage.status()["needs_reclaim"] is False


# =============================================================================
# 18. Doctor summary strings freeze (SPEC §13.22, issue #138)
# =============================================================================


def test_doctor_summary_constants_freeze() -> None:
    """DOCTOR_SUMMARY_* constants match the frozen strings in SPEC §13.22."""
    assert DOCTOR_SUMMARY_RECLAIM_NEEDED == "ATTENTION: running needs reclaim"
    assert isinstance(DOCTOR_SUMMARY_RECLAIM_NEEDED, str)
    assert DOCTOR_SUMMARY_OK_FORMAT == "OK: {state}"
    assert isinstance(DOCTOR_SUMMARY_OK_FORMAT, str)
    # The healthy template renders exactly "OK: <state>" with one space, no affixes.
    assert DOCTOR_SUMMARY_OK_FORMAT.format(state="running") == "OK: running"
    for state in STATES:
        assert doctor_summary_ok(state) == f"OK: {state}"
        assert doctor_summary_ok(state) == DOCTOR_SUMMARY_OK_FORMAT.format(state=state)
    assert callable(doctor_summary_ok)


def test_doctor_summary_exported_from_top_level() -> None:
    """DOCTOR_SUMMARY_* constants and helper are exported from top-level stage_signal (SPEC §13.22)."""
    import stage_signal

    for name, expected in (
        ("DOCTOR_SUMMARY_RECLAIM_NEEDED", DOCTOR_SUMMARY_RECLAIM_NEEDED),
        ("DOCTOR_SUMMARY_OK_FORMAT", DOCTOR_SUMMARY_OK_FORMAT),
        ("doctor_summary_ok", doctor_summary_ok),
    ):
        assert hasattr(stage_signal, name), f"stage_signal missing {name!r}"
        assert name in stage_signal.__all__, f"{name!r} not in stage_signal.__all__"
        assert getattr(stage_signal, name) is expected


def _assert_diagnose_doctor_json_summary(
    stage_dir: Path,
    capsys: pytest.CaptureFixture[str],
    *,
    expected_summary: str | None,
    expected_needs_reclaim: bool,
    expected_ok: bool,
    expected_exit: int,
) -> None:
    """Check Stage.diagnose() and doctor --json agree on the frozen summary (SPEC §13.22)."""
    stage = Stage(str(stage_dir))
    lib_data = stage.diagnose()
    assert lib_data["summary"] == expected_summary
    assert lib_data["needs_reclaim"] is expected_needs_reclaim
    assert lib_data["ok"] is expected_ok

    capsys.readouterr()
    code = main(["--dir", str(stage_dir), "doctor", "--json"])
    assert code == expected_exit
    cli_data = json.loads(capsys.readouterr().out)
    assert cli_data["summary"] == expected_summary
    assert cli_data["needs_reclaim"] is expected_needs_reclaim
    assert cli_data["ok"] is expected_ok


def test_diagnose_doctor_json_summary_healthy_states(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Healthy diagnose/doctor JSON emits the frozen "OK: <state>" summary (SPEC §13.22)."""
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="summary-freeze")

    _assert_diagnose_doctor_json_summary(
        stage_dir,
        capsys,
        expected_summary="OK: queued",
        expected_needs_reclaim=False,
        expected_ok=True,
        expected_exit=EXIT_OK,
    )

    stage.start(stage="step-1", pid=os.getpid())
    _assert_diagnose_doctor_json_summary(
        stage_dir,
        capsys,
        expected_summary="OK: running",
        expected_needs_reclaim=False,
        expected_ok=True,
        expected_exit=EXIT_OK,
    )

    # Human doctor prints the same healthy summary line.
    capsys.readouterr()
    assert main(["--dir", str(stage_dir), "doctor"]) == EXIT_OK
    assert "OK: running" in capsys.readouterr().out

    for terminal, terminal_action in (
        ("done", lambda: stage.done(summary="finished")),
        ("blocked", lambda: stage.blocked(reason="waiting")),
        ("failed", lambda: stage.fail(reason="crashed")),
    ):
        if stage.status()["state"] != "running":
            stage.start(stage=f"step-{terminal}", pid=os.getpid())
        terminal_action()
        _assert_diagnose_doctor_json_summary(
            stage_dir,
            capsys,
            expected_summary=f"OK: {terminal}",
            expected_needs_reclaim=False,
            expected_ok=True,
            expected_exit=EXIT_OK,
        )


def test_diagnose_doctor_json_summary_reclaim_needed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """diagnose/doctor JSON emits the frozen reclaim summary when needs_reclaim (SPEC §13.22)."""
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="summary-reclaim-freeze")

    dead_proc = subprocess.Popen([sys.executable, "-c", "pass"])
    dead_proc.wait(timeout=5)
    stage.start(stage="dead-task", pid=dead_proc.pid)

    _assert_diagnose_doctor_json_summary(
        stage_dir,
        capsys,
        expected_summary=DOCTOR_SUMMARY_RECLAIM_NEEDED,
        expected_needs_reclaim=True,
        expected_ok=True,
        expected_exit=EXIT_OK,
    )
    assert DOCTOR_SUMMARY_RECLAIM_NEEDED == "ATTENTION: running needs reclaim"

    # Human doctor prints the same reclaim summary line, never the healthy one.
    capsys.readouterr()
    assert main(["--dir", str(stage_dir), "doctor"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "ATTENTION: running needs reclaim" in out
    assert "OK: running" not in out


def test_diagnose_doctor_json_summary_null_on_problems(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """diagnose/doctor JSON emits summary null exactly when problems exist (SPEC §13.22)."""
    # 1. Missing dir: problems present -> summary null.
    missing_dir = tmp_path / "does-not-exist"
    _assert_diagnose_doctor_json_summary(
        missing_dir,
        capsys,
        expected_summary=None,
        expected_needs_reclaim=False,
        expected_ok=False,
        expected_exit=EXIT_ERROR,
    )

    # 2. Corrupt STATUS.json: problems present -> summary null.
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="summary-null-freeze")
    (stage_dir / "STATUS.json").write_text("{not-json\n", encoding="utf-8")
    _assert_diagnose_doctor_json_summary(
        stage_dir,
        capsys,
        expected_summary=None,
        expected_needs_reclaim=False,
        expected_ok=False,
        expected_exit=EXIT_ERROR,
    )

    # 3. Reclaim warnings coexisting with problems: summary stays null while
    # needs_reclaim remains independently true (SPEC §6, §13.22.2).
    stage_dir2 = tmp_path / "reclaim-problems" / ".stage-signal"
    stage2 = Stage(str(stage_dir2))
    stage2.init(project="summary-null-reclaim-freeze")
    dead_proc = subprocess.Popen([sys.executable, "-c", "pass"])
    dead_proc.wait(timeout=5)
    stage2.start(stage="dead-task", pid=dead_proc.pid)
    (stage_dir2 / "events.jsonl").write_text("{corrupt json\n", encoding="utf-8")
    _assert_diagnose_doctor_json_summary(
        stage_dir2,
        capsys,
        expected_summary=None,
        expected_needs_reclaim=True,
        expected_ok=False,
        expected_exit=EXIT_ERROR,
    )

# 19. Top-level public export inventory freeze (SPEC §13.21, issue #137)
# =============================================================================


def test_public_exports_constant_freeze() -> None:
    """PUBLIC_EXPORTS matches the frozen 93-element tuple in SPEC §13.21."""
    expected = (
        "ALLOWED_TRANSITIONS",
        "ARTIFACT_ENTRY_KEYS",
        "BadArgsError",
        "CLI_SUBCOMMANDS",
        "CorruptStatusError",
        "DEFAULT_DIR_NAME",
        "DEFAULT_MIRROR_DIRNAME",
        "DEFAULT_STALE_THRESHOLD",
        "DOCTOR_JSON_KEYS",
        "DOCTOR_SUMMARY_OK_FORMAT",
        "DOCTOR_SUMMARY_RECLAIM_NEEDED",
        "DOCTOR_WARNING_KEYS",
        "ENV_DIR",
        "ENV_PROJECT",
        "ENV_PROOF_REF",
        "ENV_STATUS_MIRROR",
        "ENV_VARS",
        "ERROR_KEYS",
        "ERROR_KINDS",
        "EVENTS_DEFAULT_TAIL",
        "EVENTS_FILENAME",
        "EVENT_RECORD_KEYS",
        "EVENT_TYPES",
        "EXIT_BAD_ARGS",
        "EXIT_BLOCKED",
        "EXIT_CODES",
        "EXIT_ERROR",
        "EXIT_FAILED",
        "EXIT_ILLEGAL_TRANSITION",
        "EXIT_NOT_INITIALIZED",
        "EXIT_OK",
        "EXIT_QUEUED",
        "EXIT_RUNNING",
        "EXIT_WAIT_TIMEOUT",
        "IllegalTransition",
        "LOCKS_DIRNAME",
        "LOCK_FILENAME",
        "MAX_NOTES",
        "NOTE_ENTRY_KEYS",
        "NotInitialized",
        "PROOF_KEYS",
        "PROOF_REQUIRED_KEYS",
        "PROOF_VERIFIED_VALUES",
        "PUBLIC_EXPORTS",
        "RESULT_KEYS",
        "SCHEMA_VERSION",
        "STAGE_PUBLIC_METHODS",
        "STATES",
        "STATE_BLOCKED",
        "STATE_DONE",
        "STATE_EXIT_CODES",
        "STATE_FAILED",
        "STATE_QUEUED",
        "STATE_RUNNING",
        "STATUS_FILENAME",
        "STATUS_JSON_KEYS",
        "STATUS_MD_FILENAME",
        "STATUS_MD_HEADINGS",
        "STATUS_MD_OPTIONAL_HEADINGS",
        "STATUS_MD_REQUIRED_HEADINGS",
        "STATUS_MD_TITLE",
        "STATUS_REQUIRED_KEYS",
        "SUPERVISE_DEFAULT_EVERY",
        "Stage",
        "StageError",
        "StageStore",
        "TERMINAL_STATES",
        "WAIT_DEFAULT_POLL",
        "WAIT_DEFAULT_TIMEOUT",
        "WAIT_JSON_KEYS",
        "WAIT_OUTCOMES",
        "WAIT_OUTCOME_MET",
        "WAIT_OUTCOME_MISMATCH",
        "WAIT_OUTCOME_TIMEOUT",
        "WARNING_CODES",
        "WARNING_CODE_DEAD_PID",
        "WARNING_CODE_STALE_HEARTBEAT",
        "WARNING_CODE_UNPARSEABLE_HEARTBEAT",
        "WARNING_KEYS",
        "WARNING_REQUIRED_KEYS",
        "WaitTimeout",
        "__version__",
        "allowed_source_states",
        "doctor_summary_ok",
        "is_transition_allowed",
        "render_status_md",
        "resolve_dir",
        "state_exit_code",
        "transition_target",
        "verify_proof",
        "wait_condition_met",
        "want_matches",
        "write_status_mirror",
    )
    assert PUBLIC_EXPORTS == expected
    assert isinstance(PUBLIC_EXPORTS, tuple)
    assert len(PUBLIC_EXPORTS) == 93
    assert PUBLIC_EXPORTS == tuple(sorted(PUBLIC_EXPORTS))
    assert len(PUBLIC_EXPORTS) == len(set(PUBLIC_EXPORTS))


def test_public_exports_exported_from_top_level() -> None:
    """PUBLIC_EXPORTS is exported from top-level stage_signal (SPEC §13.21)."""
    import stage_signal

    assert hasattr(stage_signal, "PUBLIC_EXPORTS")
    assert "PUBLIC_EXPORTS" in stage_signal.__all__
    assert stage_signal.PUBLIC_EXPORTS is PUBLIC_EXPORTS


def test_public_exports_all_set_equality() -> None:
    """set(PUBLIC_EXPORTS) matches set(stage_signal.__all__) with zero divergence (SPEC §13.21)."""
    import stage_signal

    assert set(PUBLIC_EXPORTS) == set(stage_signal.__all__)
    assert len(PUBLIC_EXPORTS) == len(stage_signal.__all__)
    assert list(PUBLIC_EXPORTS) == stage_signal.__all__


def test_public_exports_importability() -> None:
    """Every name in PUBLIC_EXPORTS is importable and exists on stage_signal (SPEC §13.21)."""
    import importlib
    import stage_signal

    for name in PUBLIC_EXPORTS:
        assert hasattr(stage_signal, name), f"stage_signal missing export {name!r}"
        val = getattr(stage_signal, name)
        assert val is not None or name in ("__version__",), f"Export {name!r} resolved to None"

        # Verify dynamic import via importlib
        mod = importlib.import_module("stage_signal")
        assert getattr(mod, name) is val, f"importlib getattr failed for {name!r}"


def test_public_exports_no_accidental_private_leakage() -> None:
    """No private or internal helper names leak into PUBLIC_EXPORTS (SPEC §13.21)."""
    for name in PUBLIC_EXPORTS:
        if name.startswith("_"):
            assert name == "__version__", f"Prohibited private symbol {name!r} leaked into PUBLIC_EXPORTS"


def test_public_exports_category_coverage() -> None:
    """PUBLIC_EXPORTS contains all required classes, exceptions, helpers, and constants (SPEC §13.21)."""
    import inspect
    import stage_signal

    # 1. Classes (§11, §13.20)
    classes = {"Stage", "StageStore"}
    for cls_name in classes:
        assert cls_name in PUBLIC_EXPORTS
        cls = getattr(stage_signal, cls_name)
        assert inspect.isclass(cls)
        assert not issubclass(cls, BaseException)

    # 2. Exceptions (§13.17)
    exceptions = {
        "StageError",
        "BadArgsError",
        "IllegalTransition",
        "NotInitialized",
        "CorruptStatusError",
        "WaitTimeout",
    }
    for exc_name in exceptions:
        assert exc_name in PUBLIC_EXPORTS
        exc = getattr(stage_signal, exc_name)
        assert inspect.isclass(exc)
        assert issubclass(exc, stage_signal.StageError)

    # 3. Top-level helper functions (§11, §13.19, §13.20.4)
    helpers = {
        "resolve_dir",
        "render_status_md",
        "state_exit_code",
        "allowed_source_states",
        "is_transition_allowed",
        "transition_target",
        "verify_proof",
        "wait_condition_met",
        "want_matches",
        "write_status_mirror",
    }
    for fn_name in helpers:
        assert fn_name in PUBLIC_EXPORTS
        fn = getattr(stage_signal, fn_name)
        assert callable(fn)
        assert not inspect.isclass(fn)

    # 4. Core frozen constants (§13.1-§13.20)
    core_constants = {
        "SCHEMA_VERSION",
        "__version__",
        "STATES",
        "TERMINAL_STATES",
        "ALLOWED_TRANSITIONS",
        "CLI_SUBCOMMANDS",
        "STAGE_PUBLIC_METHODS",
        "EXIT_CODES",
        "STATE_EXIT_CODES",
        "DEFAULT_DIR_NAME",
        "STATUS_FILENAME",
        "STATUS_MD_FILENAME",
        "EVENTS_FILENAME",
        "LOCKS_DIRNAME",
        "LOCK_FILENAME",
        "DEFAULT_MIRROR_DIRNAME",
        "ENV_VARS",
        "STATUS_REQUIRED_KEYS",
        "STATUS_JSON_KEYS",
        "EVENT_RECORD_KEYS",
        "EVENT_TYPES",
        "DOCTOR_JSON_KEYS",
        "WARNING_CODES",
        "WAIT_JSON_KEYS",
        "WAIT_OUTCOMES",
        "STATUS_MD_REQUIRED_HEADINGS",
        "STATUS_MD_HEADINGS",
        "PUBLIC_EXPORTS",
    }
    for const_name in core_constants:
        assert const_name in PUBLIC_EXPORTS


def test_public_exports_cross_links() -> None:
    """Verify cross-links to §11 (Stage), §13.17 (Exceptions), and §13.20 (Stage methods) in SPEC §13.21."""
    import stage_signal

    # Cross-link §11 & §13.20: Stage methods are defined in STAGE_PUBLIC_METHODS which is in PUBLIC_EXPORTS
    assert "STAGE_PUBLIC_METHODS" in PUBLIC_EXPORTS
    for method in STAGE_PUBLIC_METHODS:
        assert hasattr(stage_signal.Stage, method)

    # Cross-link §13.17: All frozen exception hierarchy types are in PUBLIC_EXPORTS
    frozen_exceptions = (
        "StageError",
        "BadArgsError",
        "IllegalTransition",
        "NotInitialized",
        "CorruptStatusError",
        "WaitTimeout",
    )
    for exc_name in frozen_exceptions:
        assert exc_name in PUBLIC_EXPORTS
