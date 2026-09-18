"""schema_version 1 contract freeze regression tests (SPEC §13, issue #102).

Locks JSON keys, exit codes, and event types so orchestrators do not
lose keys or branch targets silently.
"""

from __future__ import annotations

import argparse
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
    ARTIFACT_ALLOWED_SOURCES,
    ARTIFACT_DETAIL_KEYS,
    ARTIFACT_ENTRY_KEYS,
    BLOCKED_ALLOWED_SOURCES,
    BLOCKED_DETAIL_KEYS,
    CLEAR_TERMINAL_ALLOWED_SOURCES,
    CLEAR_TERMINAL_ALWAYS_CLEARED_FIELDS,
    CLEAR_TERMINAL_DETAIL_KEYS,
    CLEAR_TERMINAL_IDLE_RESET_FIELDS,
    CLEAR_TERMINAL_KEEP_STAGE_PRESERVED_FIELDS,
    CLEAR_TERMINAL_MESSAGE_IDLE,
    CLEAR_TERMINAL_MESSAGE_KEEP_STAGE,
    CLI_SUBCOMMANDS,
    DEFAULT_DIR_NAME,
    DEFAULT_MIRROR_DIRNAME,
    DOCTOR_JSON_KEYS,
    DOCTOR_SUMMARY_OK_FORMAT,
    DOCTOR_SUMMARY_RECLAIM_NEEDED,
    DOCTOR_WARNING_KEYS,
    DONE_ACCEPT_FAILURE_ALLOWED_SOURCES,
    DONE_ALLOWED_SOURCES,
    DONE_DETAIL_KEYS,
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
    FAIL_ALLOWED_SOURCES,
    FAIL_DETAIL_KEYS,
    FAIL_IF_DEAD_PID_ALLOWED_SOURCES,
    FAIL_IF_NEEDS_RECLAIM_ALLOWED_SOURCES,
    HEARTBEAT_ALLOWED_SOURCES,
    HEARTBEAT_DETAIL_KEYS,
    INIT_DETAIL_KEYS,
    INIT_IDLE_STATUS_FIELDS,
    LOCK_FILENAME,
    LOCKS_DIRNAME,
    NOTE_ALLOWED_SOURCES,
    NOTE_DETAIL_KEYS,
    NOTE_ENTRY_KEYS,
    PROOF_KEYS,
    PROOF_VERIFIED_VALUES,
    PUBLIC_EXPORTS,
    RECLAIM_ALLOWED_SOURCES,
    RECLAIM_CLEAR_TERMINAL_DETAIL_KEYS,
    RECLAIM_FAILED_DETAIL_KEYS,
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
    START_ALLOWED_SOURCES,
    START_DETAIL_KEYS,
    SUPERVISE_ADOPT_DETAIL_KEYS,
    SUPERVISE_ADOPT_MESSAGE_FORMAT,
    SUPERVISE_DEFAULT_EVERY,
    SUPERVISE_DONE_SUMMARY_FORMAT,
    SUPERVISE_EXIT_NOT_FOUND,
    SUPERVISE_EXIT_PERMISSION_DENIED,
    SUPERVISE_FAIL_REASON_FORMAT,
    SUPERVISE_SIGNAL_EXIT_BASE,
    SUPERVISE_SIGNAL_REASON_FORMAT,
    TERMINAL_STATES,
    WAIT_CHOICES,
    WAIT_JSON_KEYS,
    WAIT_OUTCOME_MET,
    WAIT_OUTCOME_MISMATCH,
    WAIT_OUTCOME_TIMEOUT,
    WAIT_OUTCOMES,
    WAIT_WANT_NEEDS_RECLAIM,
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
    supervise_adopt_message,
    supervise_signal_exit,
    transition_target,
    wait_condition_met,
    want_matches,
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
    """PUBLIC_EXPORTS matches the frozen 132-element tuple in SPEC §13.21."""
    expected = (
        "ALLOWED_TRANSITIONS",
        "ARTIFACT_ALLOWED_SOURCES",
        "ARTIFACT_DETAIL_KEYS",
        "ARTIFACT_ENTRY_KEYS",
        "BLOCKED_ALLOWED_SOURCES",
        "BLOCKED_DETAIL_KEYS",
        "BadArgsError",
        "CLEAR_TERMINAL_ALLOWED_SOURCES",
        "CLEAR_TERMINAL_ALWAYS_CLEARED_FIELDS",
        "CLEAR_TERMINAL_DETAIL_KEYS",
        "CLEAR_TERMINAL_IDLE_RESET_FIELDS",
        "CLEAR_TERMINAL_KEEP_STAGE_PRESERVED_FIELDS",
        "CLEAR_TERMINAL_MESSAGE_IDLE",
        "CLEAR_TERMINAL_MESSAGE_KEEP_STAGE",
        "CLI_SUBCOMMANDS",
        "CorruptStatusError",
        "DEFAULT_DIR_NAME",
        "DEFAULT_MIRROR_DIRNAME",
        "DEFAULT_STALE_THRESHOLD",
        "DOCTOR_JSON_KEYS",
        "DOCTOR_SUMMARY_OK_FORMAT",
        "DOCTOR_SUMMARY_RECLAIM_NEEDED",
        "DOCTOR_WARNING_KEYS",
        "DONE_ACCEPT_FAILURE_ALLOWED_SOURCES",
        "DONE_ALLOWED_SOURCES",
        "DONE_DETAIL_KEYS",
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
        "FAIL_ALLOWED_SOURCES",
        "FAIL_DETAIL_KEYS",
        "FAIL_IF_DEAD_PID_ALLOWED_SOURCES",
        "FAIL_IF_NEEDS_RECLAIM_ALLOWED_SOURCES",
        "HEARTBEAT_ALLOWED_SOURCES",
        "HEARTBEAT_DETAIL_KEYS",
        "INIT_DETAIL_KEYS",
        "INIT_IDLE_STATUS_FIELDS",
        "IllegalTransition",
        "LOCKS_DIRNAME",
        "LOCK_FILENAME",
        "MAX_NOTES",
        "NOTE_ALLOWED_SOURCES",
        "NOTE_DETAIL_KEYS",
        "NOTE_ENTRY_KEYS",
        "NotInitialized",
        "PROOF_KEYS",
        "PROOF_REQUIRED_KEYS",
        "PROOF_VERIFIED_VALUES",
        "PUBLIC_EXPORTS",
        "RECLAIM_ALLOWED_SOURCES",
        "RECLAIM_CLEAR_TERMINAL_DETAIL_KEYS",
        "RECLAIM_FAILED_DETAIL_KEYS",
        "RESULT_KEYS",
        "SCHEMA_VERSION",
        "STAGE_PUBLIC_METHODS",
        "START_ALLOWED_SOURCES",
        "START_DETAIL_KEYS",
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
        "SUPERVISE_ADOPT_DETAIL_KEYS",
        "SUPERVISE_ADOPT_MESSAGE_FORMAT",
        "SUPERVISE_DEFAULT_EVERY",
        "SUPERVISE_DONE_SUMMARY_FORMAT",
        "SUPERVISE_EXIT_NOT_FOUND",
        "SUPERVISE_EXIT_PERMISSION_DENIED",
        "SUPERVISE_FAIL_REASON_FORMAT",
        "SUPERVISE_SIGNAL_EXIT_BASE",
        "SUPERVISE_SIGNAL_REASON_FORMAT",
        "Stage",
        "StageError",
        "StageStore",
        "TERMINAL_STATES",
        "WAIT_CHOICES",
        "WAIT_DEFAULT_POLL",
        "WAIT_DEFAULT_TIMEOUT",
        "WAIT_JSON_KEYS",
        "WAIT_OUTCOMES",
        "WAIT_OUTCOME_MET",
        "WAIT_OUTCOME_MISMATCH",
        "WAIT_OUTCOME_TIMEOUT",
        "WAIT_WANT_NEEDS_RECLAIM",
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
        "supervise_adopt_message",
        "supervise_signal_exit",
        "transition_target",
        "verify_proof",
        "wait_condition_met",
        "want_matches",
        "write_status_mirror",
    )
    assert PUBLIC_EXPORTS == expected
    assert isinstance(PUBLIC_EXPORTS, tuple)
    assert len(PUBLIC_EXPORTS) == 134
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
        "doctor_summary_ok",
        "supervise_adopt_message",
        "supervise_signal_exit",
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
        "WAIT_CHOICES",
        "WAIT_WANT_NEEDS_RECLAIM",
        "STATUS_MD_REQUIRED_HEADINGS",
        "STATUS_MD_HEADINGS",
        "PUBLIC_EXPORTS",
        "RECLAIM_ALLOWED_SOURCES",
        "RECLAIM_CLEAR_TERMINAL_DETAIL_KEYS",
        "RECLAIM_FAILED_DETAIL_KEYS",
        "SUPERVISE_ADOPT_MESSAGE_FORMAT",
        "SUPERVISE_ADOPT_DETAIL_KEYS",
        "SUPERVISE_DONE_SUMMARY_FORMAT",
        "SUPERVISE_FAIL_REASON_FORMAT",
        "SUPERVISE_SIGNAL_REASON_FORMAT",
        "SUPERVISE_SIGNAL_EXIT_BASE",
        "SUPERVISE_EXIT_NOT_FOUND",
        "SUPERVISE_EXIT_PERMISSION_DENIED",
        "HEARTBEAT_ALLOWED_SOURCES",
        "HEARTBEAT_DETAIL_KEYS",
        "INIT_DETAIL_KEYS",
        "INIT_IDLE_STATUS_FIELDS",
        "ARTIFACT_ALLOWED_SOURCES",
        "ARTIFACT_DETAIL_KEYS",
        "BLOCKED_ALLOWED_SOURCES",
        "BLOCKED_DETAIL_KEYS",
        "DONE_ALLOWED_SOURCES",
        "DONE_ACCEPT_FAILURE_ALLOWED_SOURCES",
        "DONE_DETAIL_KEYS",
        "START_ALLOWED_SOURCES",
        "START_DETAIL_KEYS",
        "FAIL_ALLOWED_SOURCES",
        "FAIL_DETAIL_KEYS",
        "FAIL_IF_DEAD_PID_ALLOWED_SOURCES",
        "FAIL_IF_NEEDS_RECLAIM_ALLOWED_SOURCES",
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


# 20. Wait want vocabulary and predicate freeze (SPEC §13.23, issue #141)
# =============================================================================


def test_wait_want_constants_freeze() -> None:
    """WAIT_CHOICES and WAIT_WANT_NEEDS_RECLAIM match SPEC §13.23 exactly."""
    assert WAIT_CHOICES == ("done", "blocked", "failed", "terminal")
    assert isinstance(WAIT_CHOICES, tuple)
    assert len(WAIT_CHOICES) == 4
    assert all(isinstance(c, str) for c in WAIT_CHOICES)
    assert len(set(WAIT_CHOICES)) == 4

    assert WAIT_CHOICES[0] == STATE_DONE == "done"
    assert WAIT_CHOICES[1] == STATE_BLOCKED == "blocked"
    assert WAIT_CHOICES[2] == STATE_FAILED == "failed"
    assert WAIT_CHOICES[3] == "terminal"

    # Terminal states partition: all 3 TERMINAL_STATES are choices in WAIT_CHOICES
    for s in TERMINAL_STATES:
        assert s in WAIT_CHOICES

    assert WAIT_WANT_NEEDS_RECLAIM == "needs_reclaim"
    assert isinstance(WAIT_WANT_NEEDS_RECLAIM, str)


def test_wait_want_exported_from_top_level() -> None:
    """WAIT_CHOICES, WAIT_WANT_NEEDS_RECLAIM, want_matches, and wait_condition_met are exported (SPEC §13.23)."""
    import stage_signal

    for name, expected in (
        ("WAIT_CHOICES", WAIT_CHOICES),
        ("WAIT_WANT_NEEDS_RECLAIM", WAIT_WANT_NEEDS_RECLAIM),
        ("want_matches", want_matches),
        ("wait_condition_met", wait_condition_met),
    ):
        assert hasattr(stage_signal, name), f"stage_signal missing export {name!r}"
        assert name in stage_signal.__all__, f"{name!r} missing from __all__"
        assert getattr(stage_signal, name) is expected


def test_want_matches_predicate_matrix() -> None:
    """want_matches(want, state) evaluates exact truth table across all states (SPEC §13.23)."""
    # 1. want == "terminal": True iff state in TERMINAL_STATES ("done", "blocked", "failed")
    for state in (STATE_DONE, STATE_BLOCKED, STATE_FAILED):
        assert want_matches("terminal", state) is True

    for non_term in (STATE_QUEUED, STATE_RUNNING, "unknown_state", "", "none"):
        assert want_matches("terminal", non_term) is False

    # 2. Exact state wants ("done", "blocked", "failed"): True iff state == want
    for target in ("done", "blocked", "failed"):
        for state in STATES:
            if state == target:
                assert want_matches(target, state) is True
            else:
                assert want_matches(target, state) is False

        # Non-lifecycle strings never match
        assert want_matches(target, "other") is False
        assert want_matches(target, "") is False

    # 3. Arbitrary wants (e.g. "running", "queued"): fallback is state == want
    assert want_matches("running", "running") is True
    assert want_matches("running", "done") is False
    assert want_matches("queued", "queued") is True
    assert want_matches("queued", "running") is False


def test_wait_condition_met_predicate_matrix() -> None:
    """wait_condition_met evaluates status snapshots across want and needs_reclaim (SPEC §13.23)."""
    # 1. needs_reclaim=False: delegates to want_matches(want, str(status.get("state")))
    for want in WAIT_CHOICES:
        for state in STATES:
            status = {"state": state, "needs_reclaim": False}
            expected = want_matches(want, state)
            assert wait_condition_met(status, want=want, needs_reclaim=False) is expected

    # When state is None or missing
    assert wait_condition_met({}, want="terminal", needs_reclaim=False) is False
    assert wait_condition_met({"state": None}, want="done", needs_reclaim=False) is False

    # 2. needs_reclaim=True: condition is bool(status.get("needs_reclaim")), ignoring want
    for want in WAIT_CHOICES:
        # Reclaim true -> condition met regardless of want
        assert wait_condition_met(
            {"state": "running", "needs_reclaim": True},
            want=want,
            needs_reclaim=True,
        ) is True

        # Reclaim false -> condition NOT met regardless of want or state
        for state in STATES:
            assert wait_condition_met(
                {"state": state, "needs_reclaim": False},
                want=want,
                needs_reclaim=True,
            ) is False

        # Missing needs_reclaim key -> False
        assert wait_condition_met(
            {"state": "running"},
            want=want,
            needs_reclaim=True,
        ) is False

    # Truthy non-bool values in needs_reclaim evaluate via bool()
    assert wait_condition_met({"needs_reclaim": 1}, want="terminal", needs_reclaim=True) is True
    assert wait_condition_met({"needs_reclaim": 0}, want="terminal", needs_reclaim=True) is False
    assert wait_condition_met({"needs_reclaim": ""}, want="terminal", needs_reclaim=True) is False


def test_wait_needs_reclaim_mutual_exclusivity(tmp_path: Path) -> None:
    """wait --needs-reclaim cannot be combined with non-default --state (SPEC §6, §13.23)."""
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="wait-mutual-excl")

    # 1. Library API: Stage.wait with needs_reclaim=True and want != "terminal" raises BadArgsError (exit 2)
    for bad_want in ("done", "blocked", "failed", "running", "queued", "custom"):
        with pytest.raises(BadArgsError, match="wait needs_reclaim=True cannot be combined with a --state want") as exc_info:
            stage.wait(want=bad_want, needs_reclaim=True)
        assert exc_info.value.exit_code == EXIT_BAD_ARGS == 2

    # 2. Library API: Invalid want without needs_reclaim raises BadArgsError
    for invalid_want in ("running", "queued", "bogus", "TERMINAL"):
        with pytest.raises(BadArgsError, match="invalid wait state") as exc_info:
            stage.wait(want=invalid_want, needs_reclaim=False)
        assert exc_info.value.exit_code == EXIT_BAD_ARGS == 2

    # 3. CLI: stage-signal wait --state <non-terminal> --needs-reclaim exits with EXIT_BAD_ARGS (2)
    for bad_choice in ("done", "blocked", "failed"):
        code = main(["--dir", str(stage_dir), "wait", "--state", bad_choice, "--needs-reclaim"])
        assert code == EXIT_BAD_ARGS == 2


def test_wait_choices_cli_parser_contract() -> None:
    """CLI parser wait subcommand choices and defaults match frozen WAIT_CHOICES (SPEC §6, §13.23)."""
    parser = build_parser()
    subparsers = [action for action in parser._actions if isinstance(action, argparse._SubParsersAction)]
    assert len(subparsers) == 1
    wait_parser = subparsers[0].choices["wait"]

    # Locate --state argument action
    state_action = [a for a in wait_parser._actions if "--state" in a.option_strings][0]
    assert state_action.choices == list(WAIT_CHOICES)
    assert state_action.default == "terminal"

    # Locate --needs-reclaim argument action
    nr_action = [a for a in wait_parser._actions if "--needs-reclaim" in a.option_strings][0]
    assert nr_action.default is False


def test_wait_json_wanted_token_reporting(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """wait --json emits wanted field matching choice or WAIT_WANT_NEEDS_RECLAIM (SPEC §6, §13.3.3, §13.23)."""
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="wait-token-test")
    stage.start(stage="step-1")
    stage.done()

    # 1. State targets emit the requested choice in wanted
    for choice in ("terminal", "done"):
        capsys.readouterr()
        rc = main(["--dir", str(stage_dir), "wait", "--state", choice, "--json"])
        assert rc == EXIT_OK == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["wanted"] == choice
        assert payload["outcome"] == WAIT_OUTCOME_MET
        assert payload["state"] == "done"

    # 2. Reclaim wait on a healthy done stage exits with mismatch (1) and emits WAIT_WANT_NEEDS_RECLAIM in wanted
    capsys.readouterr()
    rc = main(["--dir", str(stage_dir), "wait", "--needs-reclaim", "--json"])
    assert rc == 1  # terminal without reclaim fails closed (done=1 per SPEC §6)
    payload = json.loads(capsys.readouterr().out)
    assert payload["wanted"] == WAIT_WANT_NEEDS_RECLAIM == "needs_reclaim"
    assert payload["outcome"] == WAIT_OUTCOME_MISMATCH


def test_wait_want_cross_links() -> None:
    """Verify wait want vocabulary cross-links to §6, §13.11, §13.12, and §13.16."""
    # Cross-link §13.12: All terminal states are in WAIT_CHOICES
    for term_state in TERMINAL_STATES:
        assert term_state in WAIT_CHOICES

    # Cross-link §13.16: All state targets have frozen observer exit codes
    for choice in WAIT_CHOICES:
        if choice != "terminal":
            assert choice in STATE_EXIT_CODES

    # Cross-link §13.11: Wait outcomes are met, mismatch, timeout
    assert len(WAIT_OUTCOMES) == 3
    assert set(WAIT_OUTCOMES) == {"met", "mismatch", "timeout"}

    # Cross-link §6 & §13.21: WAIT_CHOICES and WAIT_WANT_NEEDS_RECLAIM in PUBLIC_EXPORTS
    assert "WAIT_CHOICES" in PUBLIC_EXPORTS
    assert "WAIT_WANT_NEEDS_RECLAIM" in PUBLIC_EXPORTS
    assert "want_matches" in PUBLIC_EXPORTS
    assert "wait_condition_met" in PUBLIC_EXPORTS

# =============================================================================
# 21. Supervise child-PID adoption + supervisor exit contract freeze (SPEC §13.24, issue #142)
# =============================================================================


def test_supervise_adopt_constants_freeze() -> None:
    """Supervise adoption/exit constants match the frozen values in SPEC §13.24.1."""
    assert SUPERVISE_ADOPT_MESSAGE_FORMAT == "adopted child pid {pid}"
    assert isinstance(SUPERVISE_ADOPT_MESSAGE_FORMAT, str)

    assert SUPERVISE_ADOPT_DETAIL_KEYS == ("previous_pid", "pid", "pid_token")
    assert isinstance(SUPERVISE_ADOPT_DETAIL_KEYS, tuple)
    assert len(SUPERVISE_ADOPT_DETAIL_KEYS) == 3

    assert SUPERVISE_DONE_SUMMARY_FORMAT == "command succeeded (exit 0): {cmd}"
    assert SUPERVISE_FAIL_REASON_FORMAT == "command failed with exit code {code}: {cmd}"
    assert SUPERVISE_SIGNAL_REASON_FORMAT == "command terminated by {signame}: {cmd}"
    for template in (
        SUPERVISE_DONE_SUMMARY_FORMAT,
        SUPERVISE_FAIL_REASON_FORMAT,
        SUPERVISE_SIGNAL_REASON_FORMAT,
    ):
        assert isinstance(template, str)

    assert SUPERVISE_SIGNAL_EXIT_BASE == 128
    assert isinstance(SUPERVISE_SIGNAL_EXIT_BASE, int)
    assert SUPERVISE_EXIT_NOT_FOUND == 127
    assert SUPERVISE_EXIT_PERMISSION_DENIED == 126

    # Helpers render exactly the frozen formats (SPEC §13.24.1)
    assert supervise_adopt_message(1234) == "adopted child pid 1234"
    assert (
        supervise_adopt_message(1234)
        == SUPERVISE_ADOPT_MESSAGE_FORMAT.format(pid=1234)
    )
    assert callable(supervise_adopt_message)
    assert supervise_signal_exit(15) == 143
    assert supervise_signal_exit(9) == 137
    assert (
        supervise_signal_exit(2) == SUPERVISE_SIGNAL_EXIT_BASE + 2
    )
    assert callable(supervise_signal_exit)


def test_supervise_adopt_constants_exported_from_top_level() -> None:
    """Supervise freeze constants/helpers are exported from top-level stage_signal (SPEC §13.24)."""
    import stage_signal

    for name, expected in (
        ("SUPERVISE_ADOPT_MESSAGE_FORMAT", SUPERVISE_ADOPT_MESSAGE_FORMAT),
        ("SUPERVISE_ADOPT_DETAIL_KEYS", SUPERVISE_ADOPT_DETAIL_KEYS),
        ("SUPERVISE_DONE_SUMMARY_FORMAT", SUPERVISE_DONE_SUMMARY_FORMAT),
        ("SUPERVISE_FAIL_REASON_FORMAT", SUPERVISE_FAIL_REASON_FORMAT),
        ("SUPERVISE_SIGNAL_REASON_FORMAT", SUPERVISE_SIGNAL_REASON_FORMAT),
        ("SUPERVISE_SIGNAL_EXIT_BASE", SUPERVISE_SIGNAL_EXIT_BASE),
        ("SUPERVISE_EXIT_NOT_FOUND", SUPERVISE_EXIT_NOT_FOUND),
        ("SUPERVISE_EXIT_PERMISSION_DENIED", SUPERVISE_EXIT_PERMISSION_DENIED),
        ("supervise_adopt_message", supervise_adopt_message),
        ("supervise_signal_exit", supervise_signal_exit),
    ):
        assert hasattr(stage_signal, name), f"stage_signal missing {name!r}"
        assert name in stage_signal.__all__, f"{name!r} not in stage_signal.__all__"
        assert getattr(stage_signal, name) is expected


def test_supervise_precondition_freeze(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Supervise precondition failures map to frozen exits with no mutation (SPEC §13.24.2)."""
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="supervise-precondition-freeze")
    status_file = stage_dir / "STATUS.json"

    def assert_no_mutation(snapshot: str, event_count: int) -> None:
        assert status_file.read_text(encoding="utf-8") == snapshot
        assert len(stage.events()) == event_count

    # 1. Queued (not running) -> IllegalTransition / exit 3, no child spawned
    before = status_file.read_text(encoding="utf-8")
    with pytest.raises(IllegalTransition, match="requires state 'running'"):
        stage.supervise([sys.executable, "-c", "pass"])
    assert_no_mutation(before, 1)

    capsys.readouterr()
    assert (
        main(["--dir", str(stage_dir), "supervise", "--", sys.executable, "-c", "pass"])
        == EXIT_ILLEGAL_TRANSITION
    )
    assert "requires state 'running'" in capsys.readouterr().err
    assert_no_mutation(before, 1)

    # 2. Terminal state (done) -> IllegalTransition / exit 3
    stage.start(stage="precondition-step", pid=os.getpid())
    stage.done(summary="finished")
    before = status_file.read_text(encoding="utf-8")
    events_before = len(stage.events())
    with pytest.raises(IllegalTransition, match="requires state 'running'"):
        stage.supervise([sys.executable, "-c", "pass"])
    assert_no_mutation(before, events_before)

    # 3. Not initialized -> NotInitialized / exit 15
    missing = tmp_path / "does-not-exist"
    uninit = Stage(missing)
    with pytest.raises(NotInitialized):
        uninit.supervise([sys.executable, "-c", "pass"])

    capsys.readouterr()
    assert (
        main(["--dir", str(missing), "supervise", "--", sys.executable, "-c", "pass"])
        == EXIT_NOT_INITIALIZED
    )


def test_supervise_adopt_heartbeat_shape_freeze(tmp_path: Path) -> None:
    """Adoption records STATUS pid/pid_token + exact heartbeat shape (SPEC §13.24.3).

    Synchronous smoke using an instant child process (no sleeps/threads).
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="supervise-adopt-freeze")
    previous_pid = 999999
    stage.start(stage="adopt-step", pid=previous_pid, session_id="sess-adopt-freeze")

    rc = stage.supervise([sys.executable, "-c", "pass"])
    assert rc == 0

    status = stage.status()
    child_pid = status["pid"]
    assert isinstance(child_pid, int)
    assert child_pid != previous_pid
    # Identity preserved across adoption (SPEC §13.24.3)
    assert status["stage_id"] == "adopt-step"
    assert status["stage_name"] == "adopt-step"
    assert status["session_id"] == "sess-adopt-freeze"
    assert status["attempt"] == 1

    # Exactly one adoption heartbeat with the frozen message + detail keys
    adopt_events = [
        e
        for e in stage.events(type="heartbeat")
        if e.get("message", "").startswith("adopted child pid ")
    ]
    assert len(adopt_events) == 1
    adopt = adopt_events[0]
    # No new event type introduced (SPEC §13.5, §13.24.5)
    assert adopt["type"] == "heartbeat"
    assert adopt["type"] in EVENT_TYPES
    assert adopt["message"] == supervise_adopt_message(child_pid)
    assert adopt["message"] == f"adopted child pid {child_pid}"
    assert set(adopt["detail"].keys()) == set(SUPERVISE_ADOPT_DETAIL_KEYS)
    assert adopt["detail"] == {
        "previous_pid": previous_pid,
        "pid": child_pid,
        "pid_token": status["pid_token"],
    }

    # Exit 0 resolves to done with the frozen default summary template
    assert status["state"] == STATE_DONE
    import shlex as _shlex

    expected_cmd = " ".join(
        _shlex.quote(arg) for arg in (sys.executable, "-c", "pass")
    )
    assert status["result"]["summary"] == SUPERVISE_DONE_SUMMARY_FORMAT.format(
        cmd=expected_cmd
    )
    assert status["error"] is None


def test_supervise_exit_mapping_freeze(tmp_path: Path) -> None:
    """Supervisor return codes match the frozen exit mapping (SPEC §13.24.4).

    Synchronous smoke using instant child processes (no sleeps/threads/signals).
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="supervise-exits-freeze")

    # 1. Non-zero child exit -> failed + frozen default reason, return N
    stage.start(stage="exit-code-step", pid=os.getpid())
    rc = stage.supervise([sys.executable, "-c", "import sys; sys.exit(42)"])
    assert rc == 42
    status = stage.status()
    assert status["state"] == STATE_FAILED
    assert status["result"] is None
    assert status["error"]["reason"].startswith("command failed with exit code 42: ")
    assert SUPERVISE_FAIL_REASON_FORMAT.format(code=42, cmd="x").startswith(
        "command failed with exit code 42: "
    )

    # 2. Command not found -> failed, return 127 (frozen)
    stage.start(stage="not-found-step", pid=os.getpid())
    rc = stage.supervise(["__nonexistent_binary_xyz_12345__"])
    assert rc == SUPERVISE_EXIT_NOT_FOUND == 127
    status = stage.status()
    assert status["state"] == STATE_FAILED
    assert "command not found" in status["error"]["reason"]

    # 3. Signal mapping helper is frozen (no live signal delivery; non-flaky)
    import signal as _signal

    assert supervise_signal_exit(_signal.SIGTERM) == 128 + _signal.SIGTERM
    assert supervise_signal_exit(_signal.SIGINT) == 128 + _signal.SIGINT
    assert SUPERVISE_SIGNAL_REASON_FORMAT.format(
        signame="SIGTERM", cmd="sleep 60"
    ) == "command terminated by SIGTERM: sleep 60"


# =============================================================================
# 22. Clear-terminal reset + audit contract freeze (SPEC §13.26, issue #146)
# =============================================================================


def test_clear_terminal_constants_freeze() -> None:
    """Clear-terminal frozen constants match the exact values in SPEC §13.26.1."""
    assert CLEAR_TERMINAL_ALLOWED_SOURCES == ("done", "blocked", "failed", "queued")
    assert isinstance(CLEAR_TERMINAL_ALLOWED_SOURCES, tuple)
    assert set(CLEAR_TERMINAL_ALLOWED_SOURCES) == set(TERMINAL_STATES) | {STATE_QUEUED}
    assert STATE_RUNNING not in CLEAR_TERMINAL_ALLOWED_SOURCES

    assert CLEAR_TERMINAL_IDLE_RESET_FIELDS == (
        "stage_id",
        "stage_name",
        "session_id",
        "pid",
        "pid_token",
        "started_at",
        "heartbeat_at",
        "heartbeat_note",
        "artifacts",
        "meta",
    )
    assert isinstance(CLEAR_TERMINAL_IDLE_RESET_FIELDS, tuple)

    # --keep-stage preserves exactly the ten idle-reset fields (SPEC §13.26.1)
    assert CLEAR_TERMINAL_KEEP_STAGE_PRESERVED_FIELDS == CLEAR_TERMINAL_IDLE_RESET_FIELDS
    assert isinstance(CLEAR_TERMINAL_KEEP_STAGE_PRESERVED_FIELDS, tuple)

    assert CLEAR_TERMINAL_ALWAYS_CLEARED_FIELDS == ("result", "error", "proof")
    assert isinstance(CLEAR_TERMINAL_ALWAYS_CLEARED_FIELDS, tuple)
    # Preserved and always-cleared sets are disjoint
    assert not (
        set(CLEAR_TERMINAL_KEEP_STAGE_PRESERVED_FIELDS)
        & set(CLEAR_TERMINAL_ALWAYS_CLEARED_FIELDS)
    )

    assert CLEAR_TERMINAL_DETAIL_KEYS == ("keep_stage",)
    assert isinstance(CLEAR_TERMINAL_DETAIL_KEYS, tuple)

    assert CLEAR_TERMINAL_MESSAGE_IDLE == "cleared to idle queued"
    assert CLEAR_TERMINAL_MESSAGE_KEEP_STAGE == "cleared to queued"
    assert isinstance(CLEAR_TERMINAL_MESSAGE_IDLE, str)
    assert isinstance(CLEAR_TERMINAL_MESSAGE_KEEP_STAGE, str)

    # Allowed sources agree with the frozen transition matrix (SPEC §13.19)
    assert set(allowed_source_states("clear-terminal")) == set(
        CLEAR_TERMINAL_ALLOWED_SOURCES
    )
    assert set(allowed_source_states("clear_terminal")) == set(
        CLEAR_TERMINAL_ALLOWED_SOURCES
    )


def test_clear_terminal_constants_exported_from_top_level() -> None:
    """Clear-terminal freeze constants are exported from top-level stage_signal (SPEC §13.26)."""
    import stage_signal

    for name, expected in (
        ("CLEAR_TERMINAL_ALLOWED_SOURCES", CLEAR_TERMINAL_ALLOWED_SOURCES),
        ("CLEAR_TERMINAL_ALWAYS_CLEARED_FIELDS", CLEAR_TERMINAL_ALWAYS_CLEARED_FIELDS),
        ("CLEAR_TERMINAL_DETAIL_KEYS", CLEAR_TERMINAL_DETAIL_KEYS),
        ("CLEAR_TERMINAL_IDLE_RESET_FIELDS", CLEAR_TERMINAL_IDLE_RESET_FIELDS),
        (
            "CLEAR_TERMINAL_KEEP_STAGE_PRESERVED_FIELDS",
            CLEAR_TERMINAL_KEEP_STAGE_PRESERVED_FIELDS,
        ),
        ("CLEAR_TERMINAL_MESSAGE_IDLE", CLEAR_TERMINAL_MESSAGE_IDLE),
        ("CLEAR_TERMINAL_MESSAGE_KEEP_STAGE", CLEAR_TERMINAL_MESSAGE_KEEP_STAGE),
    ):
        assert hasattr(stage_signal, name), f"stage_signal missing {name!r}"
        assert name in stage_signal.__all__, f"{name!r} not in stage_signal.__all__"
        assert getattr(stage_signal, name) is expected


def test_clear_terminal_allowed_sources_semantics(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Clear-terminal succeeds from terminal + queued, refuses running (SPEC §13.26.2).

    Synchronous state-machine smoke with no sleeps/threads.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="clear-terminal-sources-freeze")
    status_file = stage_dir / "STATUS.json"

    # queued abandon path succeeds (SPEC §4 idle vs queued, §13.26.2)
    status = stage.clear_terminal()
    assert status["state"] == STATE_QUEUED
    assert status["stage_id"] is None
    assert status["stage_name"] is None
    assert stage.events()[-1]["type"] == "clear_terminal"

    # each terminal source succeeds and lands on queued
    for terminal_state, finisher in (
        (STATE_DONE, lambda: stage.done(summary="finished")),
        (STATE_BLOCKED, lambda: stage.blocked(reason="waiting")),
        (STATE_FAILED, lambda: stage.fail(reason="broken")),
    ):
        stage.start(stage=f"source-{terminal_state}", pid=os.getpid())
        finisher()
        assert stage.status()["state"] == terminal_state
        cleared = stage.clear_terminal()
        assert cleared["state"] == STATE_QUEUED
        assert cleared["stage_id"] is None
        assert cleared["stage_name"] is None

    # running is illegal: library raises, CLI exits 3, no mutation (SPEC §13.26.2)
    stage.start(stage="running-guard", pid=os.getpid())
    before = status_file.read_text(encoding="utf-8")
    events_before = len(stage.events())
    with pytest.raises(IllegalTransition):
        stage.clear_terminal()
    assert status_file.read_text(encoding="utf-8") == before
    assert len(stage.events()) == events_before

    capsys.readouterr()
    assert main(["--dir", str(stage_dir), "clear-terminal"]) == EXIT_ILLEGAL_TRANSITION
    assert "reclaim" in capsys.readouterr().err
    assert status_file.read_text(encoding="utf-8") == before
    assert len(stage.events()) == events_before

    # queued abandon via CLI succeeds with exit 0 (covers the CLI path)
    stage.done(summary="wrap up")
    capsys.readouterr()
    assert main(["--dir", str(stage_dir), "clear-terminal"]) == EXIT_OK
    assert stage.status()["state"] == STATE_QUEUED


def test_clear_terminal_idle_reset_field_set_freeze(tmp_path: Path) -> None:
    """Default clear resets the frozen idle field set, preserves the rest (SPEC §13.26.3)."""
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="clear-terminal-idle-freeze")
    stage.start(
        stage="idle-step",
        session_id="sess-idle-freeze",
        pid=os.getpid(),
        model="probe-model",
        variant="probe-variant",
    )
    stage.note("sticky note")
    stage.done(summary="idle probe finished")

    cleared = stage.clear_terminal()
    assert cleared["state"] == STATE_QUEUED
    # Frozen idle-reset fields reach idle values
    assert cleared["stage_id"] is None
    assert cleared["stage_name"] is None
    assert cleared["session_id"] is None
    assert cleared["pid"] is None
    assert cleared["pid_token"] is None
    assert cleared["started_at"] is None
    assert cleared["heartbeat_at"] is None
    assert cleared["heartbeat_note"] is None
    assert cleared["artifacts"] == []
    assert cleared["meta"] == {}
    # Always-cleared terminal payloads
    for field in CLEAR_TERMINAL_ALWAYS_CLEARED_FIELDS:
        assert cleared[field] is None, f"{field!r} not cleared on idle reset"
    # Preserved-in-both-modes fields survive the reset
    assert cleared["attempt"] == 1
    assert [n["text"] for n in cleared["notes"]] == ["sticky note"]
    assert cleared["model"] == "probe-model"
    assert cleared["variant"] == "probe-variant"
    assert cleared["repo_path"] is not None
    assert "git_head" in cleared and "git_branch" in cleared


def test_clear_terminal_keep_stage_preserved_vs_cleared_freeze(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--keep-stage preserves identity fields, still clears payloads (SPEC §13.26.4)."""
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="clear-terminal-keep-freeze")
    stage.start(stage="keep-step", session_id="sess-keep-freeze", pid=os.getpid())
    stage.done(summary="keep probe finished")
    before = stage.status()

    kept = stage.clear_terminal(keep_stage=True)
    assert kept["state"] == STATE_QUEUED
    # Frozen preserved fields keep their pre-clear values
    for field in CLEAR_TERMINAL_KEEP_STAGE_PRESERVED_FIELDS:
        assert kept[field] == before[field], f"{field!r} not preserved with keep_stage"
    assert kept["stage_id"] == "keep-step"
    assert kept["stage_name"] == "keep-step"
    assert kept["session_id"] == "sess-keep-freeze"
    assert kept["pid"] == before["pid"]
    assert kept["pid_token"] == before["pid_token"]
    # Always-cleared terminal payloads are still cleared
    for field in CLEAR_TERMINAL_ALWAYS_CLEARED_FIELDS:
        assert kept[field] is None, f"{field!r} not cleared with keep_stage"

    # CLI --keep-stage path preserves identity too
    stage.start(stage="keep-cli-step", pid=os.getpid())
    stage.blocked(reason="keep cli probe")
    capsys.readouterr()
    assert main(["--dir", str(stage_dir), "clear-terminal", "--keep-stage"]) == EXIT_OK
    kept_cli = stage.status()
    assert kept_cli["state"] == STATE_QUEUED
    assert kept_cli["stage_id"] == "keep-cli-step"
    assert kept_cli["stage_name"] == "keep-cli-step"
    assert kept_cli["error"] is None


def test_clear_terminal_audit_event_shape_freeze(tmp_path: Path) -> None:
    """Each clear appends one clear_terminal event with frozen message + detail (SPEC §13.26.5)."""
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="clear-terminal-audit-freeze")

    # Default idle clear
    stage.start(stage="audit-step", pid=os.getpid())
    stage.done(summary="audit probe")
    events_before = len(stage.events())
    stage.clear_terminal()
    events = stage.events()
    assert len(events) == events_before + 1
    last = events[-1]
    assert last["type"] == "clear_terminal"
    assert last["type"] in EVENT_TYPES
    assert last["state"] == STATE_QUEUED
    assert last["message"] == CLEAR_TERMINAL_MESSAGE_IDLE == "cleared to idle queued"
    assert set(last["detail"].keys()) == set(CLEAR_TERMINAL_DETAIL_KEYS)
    assert last["detail"] == {"keep_stage": False}

    # Keep-stage clear
    stage.start(stage="audit-keep-step", pid=os.getpid())
    stage.fail(reason="audit keep probe")
    events_before = len(stage.events())
    stage.clear_terminal(keep_stage=True)
    events = stage.events()
    assert len(events) == events_before + 1
    last = events[-1]
    assert last["type"] == "clear_terminal"
    assert last["message"] == CLEAR_TERMINAL_MESSAGE_KEEP_STAGE == "cleared to queued"
    assert set(last["detail"].keys()) == set(CLEAR_TERMINAL_DETAIL_KEYS)
    assert last["detail"] == {"keep_stage": True}

    # Queued abandon also audits exactly one event
    events_before = len(stage.events())
    stage.clear_terminal()
    events = stage.events()
    assert len(events) == events_before + 1
    assert events[-1]["type"] == "clear_terminal"
    assert events[-1]["detail"] == {"keep_stage": False}


# =============================================================================
# =============================================================================
# 23. Reclaim fail-and-clear contract freeze (SPEC §13.25, issue #145)
# =============================================================================


def test_reclaim_constants_freeze() -> None:
    """Reclaim frozen constants match the exact values in SPEC §13.25.1."""
    assert RECLAIM_ALLOWED_SOURCES == ("running",)
    assert isinstance(RECLAIM_ALLOWED_SOURCES, tuple)
    assert set(RECLAIM_ALLOWED_SOURCES) == {STATE_RUNNING}

    # Matches transition matrix query helpers (SPEC §13.19)
    assert set(allowed_source_states("reclaim")) == set(RECLAIM_ALLOWED_SOURCES)
    assert set(allowed_source_states("reclaim --keep-failed")) == set(
        RECLAIM_ALLOWED_SOURCES
    )
    assert set(allowed_source_states("reclaim_keep_failed")) == set(
        RECLAIM_ALLOWED_SOURCES
    )

    assert RECLAIM_FAILED_DETAIL_KEYS == ("reclaim", "keep_failed")
    assert isinstance(RECLAIM_FAILED_DETAIL_KEYS, tuple)

    assert RECLAIM_CLEAR_TERMINAL_DETAIL_KEYS == ("keep_stage", "reclaim")
    assert isinstance(RECLAIM_CLEAR_TERMINAL_DETAIL_KEYS, tuple)


def test_reclaim_constants_exported_from_top_level() -> None:
    """Reclaim freeze constants are exported from top-level stage_signal (SPEC §13.25)."""
    import stage_signal

    for name, expected in (
        ("RECLAIM_ALLOWED_SOURCES", RECLAIM_ALLOWED_SOURCES),
        ("RECLAIM_FAILED_DETAIL_KEYS", RECLAIM_FAILED_DETAIL_KEYS),
        ("RECLAIM_CLEAR_TERMINAL_DETAIL_KEYS", RECLAIM_CLEAR_TERMINAL_DETAIL_KEYS),
    ):
        assert hasattr(stage_signal, name), f"stage_signal missing {name!r}"
        assert name in stage_signal.__all__, f"{name!r} not in stage_signal.__all__"
        assert getattr(stage_signal, name) is expected


# =============================================================================
# 24. Heartbeat liveness contract freeze (SPEC §13.27, issue #148)
# =============================================================================


def test_heartbeat_constants_freeze() -> None:
    """Heartbeat frozen constants match the exact values in SPEC §13.27.1."""
    assert HEARTBEAT_ALLOWED_SOURCES == ("running",)
    assert isinstance(HEARTBEAT_ALLOWED_SOURCES, tuple)
    assert len(HEARTBEAT_ALLOWED_SOURCES) == 1
    assert STATE_RUNNING in HEARTBEAT_ALLOWED_SOURCES
    for terminal in TERMINAL_STATES:
        assert terminal not in HEARTBEAT_ALLOWED_SOURCES
    assert STATE_QUEUED not in HEARTBEAT_ALLOWED_SOURCES

    assert HEARTBEAT_DETAIL_KEYS == ()
    assert isinstance(HEARTBEAT_DETAIL_KEYS, tuple)
    assert len(HEARTBEAT_DETAIL_KEYS) == 0

    # Allowed sources agree with the frozen transition matrix (SPEC §13.19)
    assert tuple(allowed_source_states("heartbeat")) == HEARTBEAT_ALLOWED_SOURCES
    assert is_transition_allowed(STATE_RUNNING, "heartbeat") is True
    assert transition_target(STATE_RUNNING, "heartbeat") == STATE_RUNNING


def test_heartbeat_constants_exported_from_top_level() -> None:
    """Heartbeat freeze constants are exported from top-level stage_signal (SPEC §13.27)."""
    import stage_signal

    for name, expected in (
        ("HEARTBEAT_ALLOWED_SOURCES", HEARTBEAT_ALLOWED_SOURCES),
        ("HEARTBEAT_DETAIL_KEYS", HEARTBEAT_DETAIL_KEYS),
    ):
        assert hasattr(stage_signal, name), f"stage_signal missing {name!r}"
        assert name in stage_signal.__all__, f"{name!r} not in stage_signal.__all__"
        assert getattr(stage_signal, name) is expected


def test_reclaim_guard_semantics(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Reclaim enforces needs_reclaim guard; rejects uninit/badargs/healthy/non-running (SPEC §13.25.2).

    Synchronous state-machine tests with zero sleeps/threads.
    """
    from stage_signal.cli import main

    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))

    # 1. Uninitialized: exit 15 / NotInitialized
    with pytest.raises(NotInitialized):
        stage.reclaim(reason="not init")
    assert main(["--dir", str(stage_dir), "reclaim", "--reason", "not init"]) == EXIT_NOT_INITIALIZED
    capsys.readouterr()

    # Initialize
    stage.init(project="reclaim-guard-freeze")

    # 2. Empty reason: exit 2 / BadArgsError
    with pytest.raises(BadArgsError, match="non-empty"):
        stage.reclaim(reason="")
    with pytest.raises(BadArgsError, match="non-empty"):
        stage.reclaim(reason="   ")
    assert main(["--dir", str(stage_dir), "reclaim", "--reason", "  "]) == EXIT_BAD_ARGS
    capsys.readouterr()

    # 3. Non-running states: queued, done, blocked, failed -> IllegalTransition (exit 3)
    # 3a. From queued (initial idle queued)
    status_before = (stage_dir / "STATUS.json").read_bytes()
    with pytest.raises(IllegalTransition, match="needs_reclaim is false"):
        stage.reclaim(reason="cannot reclaim queued")
    assert (stage_dir / "STATUS.json").read_bytes() == status_before
    assert main(["--dir", str(stage_dir), "reclaim", "--reason", "cannot reclaim queued"]) == EXIT_ILLEGAL_TRANSITION
    capsys.readouterr()

    # 3b. From done
    stage.start(stage="done-step", pid=os.getpid())
    stage.done(summary="all good")
    status_before = (stage_dir / "STATUS.json").read_bytes()
    with pytest.raises(IllegalTransition, match="needs_reclaim is false"):
        stage.reclaim(reason="cannot reclaim done")
    assert (stage_dir / "STATUS.json").read_bytes() == status_before
    assert main(["--dir", str(stage_dir), "reclaim", "--reason", "cannot reclaim done"]) == EXIT_ILLEGAL_TRANSITION
    capsys.readouterr()

    # 3c. From blocked
    stage.start(stage="blocked-step", pid=os.getpid())
    stage.blocked(reason="waiting for gate")
    status_before = (stage_dir / "STATUS.json").read_bytes()
    with pytest.raises(IllegalTransition, match="needs_reclaim is false"):
        stage.reclaim(reason="cannot reclaim blocked")
    assert (stage_dir / "STATUS.json").read_bytes() == status_before
    assert main(["--dir", str(stage_dir), "reclaim", "--reason", "cannot reclaim blocked"]) == EXIT_ILLEGAL_TRANSITION
    capsys.readouterr()

    # 3d. From failed
    stage.start(stage="failed-step", pid=os.getpid())
    stage.fail(reason="normal failure")
    status_before = (stage_dir / "STATUS.json").read_bytes()
    with pytest.raises(IllegalTransition, match="needs_reclaim is false"):
        stage.reclaim(reason="cannot reclaim failed")
    assert (stage_dir / "STATUS.json").read_bytes() == status_before
    assert main(["--dir", str(stage_dir), "reclaim", "--reason", "cannot reclaim failed"]) == EXIT_ILLEGAL_TRANSITION
    capsys.readouterr()

    # 4. From running but healthy: live PID, fresh heartbeat -> IllegalTransition (exit 3)
    stage.start(stage="healthy-running", pid=os.getpid())
    status_before = (stage_dir / "STATUS.json").read_bytes()
    events_before = len(stage.events())
    with pytest.raises(IllegalTransition, match="needs_reclaim is false"):
        stage.reclaim(reason="healthy cannot be reclaimed")
    assert (stage_dir / "STATUS.json").read_bytes() == status_before
    assert len(stage.events()) == events_before
    assert main(["--dir", str(stage_dir), "reclaim", "--reason", "healthy cannot be reclaimed"]) == EXIT_ILLEGAL_TRANSITION
    capsys.readouterr()


def test_reclaim_default_sequence_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default reclaim fails then immediately clears to idle queued under single lock (SPEC §13.25.3, §13.25.6)."""
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="reclaim-default-freeze")

    stage.start(stage="work-step", pid=99999)
    # Simulate dead PID -> needs_reclaim becomes True
    monkeypatch.setattr("stage_signal.stage._is_pid_alive", lambda pid: False)

    events_before = len(stage.events())
    cleared = stage.reclaim("worker terminated unexpectedly")

    # Final returned state is idle queued
    assert cleared["state"] == STATE_QUEUED
    assert cleared["stage_id"] is None
    assert cleared["stage_name"] is None
    assert cleared["pid"] is None
    assert cleared["pid_token"] is None
    assert cleared["result"] is None
    assert cleared["error"] is None
    assert cleared["proof"] is None
    assert cleared["artifacts"] == []
    assert cleared["meta"] == {}

    # Exactly two events appended in sequence: failed then clear_terminal
    events = stage.events()
    assert len(events) == events_before + 2

    # Step 1 event: failed
    ev_failed = events[-2]
    assert ev_failed["type"] == "failed"
    assert ev_failed["state"] == STATE_FAILED
    assert ev_failed["stage_name"] == "work-step"
    assert ev_failed["message"] == "worker terminated unexpectedly"
    assert tuple(ev_failed["detail"].keys()) == RECLAIM_FAILED_DETAIL_KEYS
    assert ev_failed["detail"] == {"reclaim": True, "keep_failed": False}

    # Step 2 event: clear_terminal
    ev_clear = events[-1]
    assert ev_clear["type"] == "clear_terminal"
    assert ev_clear["state"] == STATE_QUEUED
    assert ev_clear["stage_id"] is None
    assert ev_clear["stage_name"] is None
    assert ev_clear["message"] == CLEAR_TERMINAL_MESSAGE_IDLE == "cleared to idle queued"
    assert tuple(ev_clear["detail"].keys()) == RECLAIM_CLEAR_TERMINAL_DETAIL_KEYS
    assert ev_clear["detail"] == {"keep_stage": False, "reclaim": True}


def test_reclaim_keep_failed_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """reclaim --keep-failed stops after failed, preserving stage identity (SPEC §13.25.4, §13.25.6)."""
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="reclaim-keep-failed-freeze")

    stage.start(stage="audit-step", pid=99999, meta={"k": "v"})
    monkeypatch.setattr("stage_signal.stage._is_pid_alive", lambda pid: False)

    events_before = len(stage.events())
    failed_st = stage.reclaim("preserve for audit", keep_failed=True)

    # State is failed and identity is preserved
    assert failed_st["state"] == STATE_FAILED
    assert failed_st["stage_name"] == "audit-step"
    assert failed_st["pid"] == 99999
    assert failed_st["meta"] == {"k": "v"}
    assert failed_st["error"] is not None
    assert failed_st["error"]["reason"] == "preserve for audit"
    assert failed_st["error"]["kind"] == STATE_FAILED

    # Exactly ONE event appended: failed
    events = stage.events()
    assert len(events) == events_before + 1
    ev_failed = events[-1]
    assert ev_failed["type"] == "failed"
    assert ev_failed["state"] == STATE_FAILED
    assert ev_failed["stage_name"] == "audit-step"
    assert ev_failed["message"] == "preserve for audit"
    assert tuple(ev_failed["detail"].keys()) == RECLAIM_FAILED_DETAIL_KEYS
    assert ev_failed["detail"] == {"reclaim": True, "keep_failed": True}


def test_reclaim_kill_best_effort_semantics_no_sleep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--kill executes after guard, continues on signal failure, verifies token (SPEC §13.25.5).

    Pure synchronous unit test: mocks process termination without sleeps or forks.
    """
    from stage_signal.stage import _terminate_pid

    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="reclaim-kill-freeze")

    # 1. When guard fails, terminate_pid is NEVER called
    stage.start(stage="live-step", pid=os.getpid())
    kill_called = []
    monkeypatch.setattr(
        "stage_signal.stage._terminate_pid",
        lambda pid, **kw: kill_called.append((pid, kw)),
    )
    with pytest.raises(IllegalTransition, match="needs_reclaim is false"):
        stage.reclaim("should fail guard", kill=True)
    assert len(kill_called) == 0

    # 2. When guard passes, terminate_pid is called after guard; reclaim succeeds even if terminate fails
    monkeypatch.setattr("stage_signal.stage._is_pid_alive", lambda pid: False)
    def failing_terminate(pid: Any, **kw: Any) -> bool:
        kill_called.append((pid, kw))
        return False

    monkeypatch.setattr("stage_signal.stage._terminate_pid", failing_terminate)
    cleared = stage.reclaim("worker dead", kill=True)
    assert len(kill_called) == 1
    assert kill_called[0][0] == os.getpid()
    assert cleared["state"] == STATE_QUEUED

    # 3. _terminate_pid token mismatch skips signaling
    # Verify the token mismatch branch in _terminate_pid directly
    monkeypatch.setattr("stage_signal.stage._is_pid_alive", lambda pid: True)
    monkeypatch.setattr("stage_signal.stage._pid_token_matches", lambda pid, tok: False)
    signals_sent = []
    monkeypatch.setattr("stage_signal.stage._signal_pid_best_effort", lambda pid, sig: signals_sent.append((pid, sig)))
    result = _terminate_pid(pid=12345, token="expected_token")
    assert result is False
    assert len(signals_sent) == 0


def test_reclaim_cli_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """CLI reclaim outputs expected human lines and exit codes (SPEC §13.25.2, §13.25.3, §13.25.4)."""
    from stage_signal.cli import main

    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="reclaim-cli-freeze")

    stage.start(stage="cli-reclaim-step", pid=99999)
    monkeypatch.setattr("stage_signal.stage._is_pid_alive", lambda pid: False)

    # CLI default reclaim
    code = main(["--dir", str(stage_dir), "reclaim", "--reason", "cli dead runner"])
    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert "reclaimed" in out
    assert "cli dead runner" in out
    assert stage.status()["state"] == STATE_QUEUED

    # Re-start and CLI keep-failed reclaim
    stage.start(stage="cli-keep-step", pid=99999)
    code = main(["--dir", str(stage_dir), "reclaim", "--reason", "audit later", "--keep-failed"])
    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert "reclaimed (kept failed)" in out
    assert "audit later" in out
    assert stage.status()["state"] == STATE_FAILED


def test_heartbeat_allowed_source_semantics(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Heartbeat succeeds only from running; queued/terminal refuse exit 3 (SPEC §13.27.2).

    Synchronous state-machine smoke with no sleeps/threads.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="heartbeat-sources-freeze")
    status_file = stage_dir / "STATUS.json"

    def assert_no_mutation(snapshot: str, event_count: int) -> None:
        assert status_file.read_text(encoding="utf-8") == snapshot
        assert len(stage.events()) == event_count

    # queued is illegal: library raises, CLI exits 3, no mutation
    before = status_file.read_text(encoding="utf-8")
    with pytest.raises(IllegalTransition):
        stage.heartbeat()
    assert_no_mutation(before, 1)

    capsys.readouterr()
    assert main(["--dir", str(stage_dir), "heartbeat"]) == EXIT_ILLEGAL_TRANSITION
    assert_no_mutation(before, 1)

    # running succeeds via library and CLI (covers both paths)
    stage.start(stage="hb-step", pid=os.getpid())
    running_status = stage.heartbeat(note="probe")
    assert running_status["state"] == STATE_RUNNING
    capsys.readouterr()
    assert main(["--dir", str(stage_dir), "heartbeat", "--note", "cli probe"]) == EXIT_OK
    assert stage.status()["state"] == STATE_RUNNING
    assert stage.status()["heartbeat_note"] == "cli probe"

    # each terminal source refuses with no mutation
    for terminal_state, finisher in (
        (STATE_DONE, lambda: stage.done(summary="finished")),
        (STATE_BLOCKED, lambda: stage.blocked(reason="waiting")),
        (STATE_FAILED, lambda: stage.fail(reason="broken")),
    ):
        # Re-enter running first when coming from a terminal state
        if stage.status()["state"] != STATE_RUNNING:
            stage.start(stage=f"hb-{terminal_state}", pid=os.getpid())
        finisher()
        assert stage.status()["state"] == terminal_state
        before = status_file.read_text(encoding="utf-8")
        events_before = len(stage.events())
        with pytest.raises(IllegalTransition):
            stage.heartbeat(note="should not land")
        assert_no_mutation(before, events_before)

        capsys.readouterr()
        assert main(["--dir", str(stage_dir), "heartbeat"]) == EXIT_ILLEGAL_TRANSITION
        assert_no_mutation(before, events_before)


def test_heartbeat_bump_and_note_omit_vs_set_freeze(tmp_path: Path) -> None:
    """heartbeat_at always bumps; note=None preserves, note=<str> overwrites (SPEC §13.27.3).

    Compares timestamps already recorded (no sleeps/threads).
    """
    from datetime import datetime as _datetime

    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="heartbeat-note-freeze")
    stage.start(stage="hb-note-step", pid=os.getpid())

    # start leaves heartbeat_note null with a recorded heartbeat_at
    started = stage.status()
    assert started["heartbeat_note"] is None
    assert isinstance(started["heartbeat_at"], str) and started["heartbeat_at"]
    first_ts = _datetime.fromisoformat(str(started["heartbeat_at"]))

    # Omit (note=None) bumps heartbeat_at and preserves note (still null)
    omitted = stage.heartbeat()
    assert omitted["state"] == STATE_RUNNING
    assert omitted["stage_id"] == "hb-note-step"
    assert omitted["attempt"] == started["attempt"]
    assert omitted["heartbeat_note"] is None
    assert _datetime.fromisoformat(str(omitted["heartbeat_at"])) >= first_ts

    # Set overwrites, including preserving other identity fields
    noted = stage.heartbeat(note="first progress")
    assert noted["heartbeat_note"] == "first progress"
    assert _datetime.fromisoformat(str(noted["heartbeat_at"])) >= _datetime.fromisoformat(
        str(omitted["heartbeat_at"])
    )

    # Omit again preserves the previous string byte-for-byte
    preserved = stage.heartbeat()
    assert preserved["heartbeat_note"] == "first progress"
    assert _datetime.fromisoformat(str(preserved["heartbeat_at"])) >= _datetime.fromisoformat(
        str(noted["heartbeat_at"])
    )

    # Explicit empty string overwrites (only None preserves)
    cleared = stage.heartbeat(note="")
    assert cleared["heartbeat_note"] == ""


def test_heartbeat_audit_event_shape_freeze(tmp_path: Path) -> None:
    """Each heartbeat appends one heartbeat event with passthrough message + empty detail (SPEC §13.27.4)."""
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="heartbeat-audit-freeze")
    stage.start(stage="hb-audit-step", pid=os.getpid())

    # Omit path: message None, detail {}
    events_before = len(stage.events())
    stage.heartbeat()
    events = stage.events()
    assert len(events) == events_before + 1
    last = events[-1]
    assert last["type"] == "heartbeat"
    assert last["type"] in EVENT_TYPES
    assert last["state"] == STATE_RUNNING
    assert last["stage_id"] == "hb-audit-step"
    assert last["message"] is None
    assert set(last["detail"].keys()) == set(HEARTBEAT_DETAIL_KEYS)
    assert last["detail"] == {}
    for key in EVENT_RECORD_KEYS:
        assert key in last

    # Set path: message echoes the note exactly, detail stays {}
    events_before = len(stage.events())
    stage.heartbeat(note="audit note")
    events = stage.events()
    assert len(events) == events_before + 1
    last = events[-1]
    assert last["type"] == "heartbeat"
    assert last["message"] == "audit note"
    assert set(last["detail"].keys()) == set(HEARTBEAT_DETAIL_KEYS)
    assert last["detail"] == {}


def test_heartbeat_age_only_while_running_freeze(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """heartbeat_age_seconds is a float>=0 only while running, else null (SPEC §13.27.5).

    No sleeps: asserts on timestamps already recorded by start/heartbeat.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="heartbeat-age-freeze")

    # queued: null age even with no heartbeat recorded
    assert stage.status()["heartbeat_age_seconds"] is None

    # running: float age >= 0 via library and CLI
    stage.start(stage="hb-age-step", pid=os.getpid())
    running = stage.status()
    assert running["state"] == STATE_RUNNING
    assert isinstance(running["heartbeat_age_seconds"], float)
    assert running["heartbeat_age_seconds"] >= 0.0

    stage.heartbeat(note="fresh")
    bumped = stage.status()
    assert isinstance(bumped["heartbeat_age_seconds"], float)
    assert bumped["heartbeat_age_seconds"] >= 0.0

    capsys.readouterr()
    assert main(["--dir", str(stage_dir), "status", "--json"]) == EXIT_RUNNING
    cli_running = json.loads(capsys.readouterr().out)
    assert isinstance(cli_running["heartbeat_age_seconds"], float)
    assert cli_running["heartbeat_age_seconds"] >= 0.0

    # terminal states: null age even though heartbeat_at remains recorded
    stage.done(summary="age probe done")
    assert stage.status()["heartbeat_at"] is not None
    assert stage.status()["heartbeat_age_seconds"] is None

    stage.start(stage="hb-age-blocked", pid=os.getpid())
    stage.blocked(reason="age probe blocked")
    assert stage.status()["heartbeat_at"] is not None
    assert stage.status()["heartbeat_age_seconds"] is None

    stage.start(stage="hb-age-failed", pid=os.getpid())
    stage.fail(reason="age probe failed")
    assert stage.status()["heartbeat_at"] is not None
    assert stage.status()["heartbeat_age_seconds"] is None

    # idle queued after clear-terminal: null age
    stage.clear_terminal()
    assert stage.status()["state"] == STATE_QUEUED
    assert stage.status()["heartbeat_age_seconds"] is None


# 21. Artifact add contract freeze (SPEC §13.29, issue #152)
# =============================================================================


def test_artifact_constants_freeze() -> None:
    """Artifact frozen constants match the exact values in SPEC §13.29.1."""
    assert ARTIFACT_ALLOWED_SOURCES == ("running",)
    assert isinstance(ARTIFACT_ALLOWED_SOURCES, tuple)
    assert len(ARTIFACT_ALLOWED_SOURCES) == 1
    assert STATE_RUNNING in ARTIFACT_ALLOWED_SOURCES
    for terminal in TERMINAL_STATES:
        assert terminal not in ARTIFACT_ALLOWED_SOURCES
    assert STATE_QUEUED not in ARTIFACT_ALLOWED_SOURCES

    assert ARTIFACT_DETAIL_KEYS == ("path", "label")
    assert isinstance(ARTIFACT_DETAIL_KEYS, tuple)
    assert len(ARTIFACT_DETAIL_KEYS) == 2

    # Allowed sources agree with the frozen transition matrix (SPEC §13.19)
    assert tuple(allowed_source_states("artifact")) == ARTIFACT_ALLOWED_SOURCES
    assert is_transition_allowed(STATE_RUNNING, "artifact") is True
    assert transition_target(STATE_RUNNING, "artifact") == STATE_RUNNING


def test_artifact_constants_exported_from_top_level() -> None:
    """Artifact freeze constants are exported from top-level stage_signal (SPEC §13.29)."""
    import stage_signal

    for name, expected in (
        ("ARTIFACT_ALLOWED_SOURCES", ARTIFACT_ALLOWED_SOURCES),
        ("ARTIFACT_DETAIL_KEYS", ARTIFACT_DETAIL_KEYS),
    ):
        assert hasattr(stage_signal, name), f"stage_signal missing {name!r}"
        assert name in stage_signal.__all__, f"{name!r} not in stage_signal.__all__"
        assert getattr(stage_signal, name) is expected


def test_artifact_allowed_source_semantics(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Artifact succeeds only from running; queued/terminal refuse exit 3 (SPEC §13.29.2).

    Synchronous state-machine smoke with no sleeps/threads.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="artifact-sources-freeze")
    status_file = stage_dir / "STATUS.json"

    def assert_no_mutation(snapshot: str, event_count: int) -> None:
        assert status_file.read_text(encoding="utf-8") == snapshot
        assert len(stage.events()) == event_count

    # Empty/whitespace-only PATH is BadArgs (exit 2) even from queued
    with pytest.raises(BadArgsError):
        stage.artifact("")
    with pytest.raises(BadArgsError):
        stage.artifact("   ")
    capsys.readouterr()
    assert main(["--dir", str(stage_dir), "artifact", "  "]) == EXIT_BAD_ARGS
    assert_no_mutation(status_file.read_text(encoding="utf-8"), 1)

    # queued is illegal: library raises, CLI exits 3, no mutation
    before = status_file.read_text(encoding="utf-8")
    with pytest.raises(IllegalTransition):
        stage.artifact("dist/out.bin")
    assert_no_mutation(before, 1)

    capsys.readouterr()
    assert main(["--dir", str(stage_dir), "artifact", "dist/out.bin"]) == EXIT_ILLEGAL_TRANSITION
    assert_no_mutation(before, 1)

    # running succeeds via library and CLI (covers both paths)
    stage.start(stage="artifact-step", pid=os.getpid())
    running_status = stage.artifact("dist/out.bin", label="binary")
    assert running_status["state"] == STATE_RUNNING
    assert running_status["artifacts"][-1]["path"] == "dist/out.bin"
    capsys.readouterr()
    assert main(["--dir", str(stage_dir), "artifact", "dist/cli.bin"]) == EXIT_OK
    assert stage.status()["state"] == STATE_RUNNING
    assert stage.status()["artifacts"][-1]["path"] == "dist/cli.bin"

    # each terminal source refuses with no mutation
    for terminal_state, finisher in (
        (STATE_DONE, lambda: stage.done(summary="finished")),
        (STATE_BLOCKED, lambda: stage.blocked(reason="waiting")),
        (STATE_FAILED, lambda: stage.fail(reason="broken")),
    ):
        # Re-enter running first when coming from a terminal state
        if stage.status()["state"] != STATE_RUNNING:
            stage.start(stage=f"artifact-{terminal_state}", pid=os.getpid())
        finisher()
        assert stage.status()["state"] == terminal_state
        before = status_file.read_text(encoding="utf-8")
        events_before = len(stage.events())
        with pytest.raises(IllegalTransition):
            stage.artifact("dist/should-not-land.bin")
        assert_no_mutation(before, events_before)

        capsys.readouterr()
        assert main(["--dir", str(stage_dir), "artifact", "dist/should-not-land.bin"]) == EXIT_ILLEGAL_TRANSITION
        assert_no_mutation(before, events_before)


def test_artifact_entry_append_and_label_omit_vs_set_freeze(tmp_path: Path) -> None:
    """Artifact appends {path, label, added_at} per ARTIFACT_ENTRY_KEYS; label None->null (SPEC §13.29.3).

    Compares entries already recorded (no sleeps/threads).
    """
    from datetime import datetime as _datetime

    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="artifact-entry-freeze")
    stage.start(stage="artifact-entry-step", pid=os.getpid())

    # Omitted label records null with all ARTIFACT_ENTRY_KEYS present
    first = stage.artifact("dist/out.bin")
    assert first["state"] == STATE_RUNNING
    assert first["stage_id"] == "artifact-entry-step"
    entry = first["artifacts"][-1]
    assert set(entry.keys()) == set(ARTIFACT_ENTRY_KEYS)
    assert entry["path"] == "dist/out.bin"
    assert entry["label"] is None
    assert isinstance(entry["added_at"], str) and entry["added_at"]
    first_ts = _datetime.fromisoformat(str(entry["added_at"]))

    # Set label records exactly, including preserving other identity fields
    second = stage.artifact("dist/report.json", label="report")
    entry2 = second["artifacts"][-1]
    assert set(entry2.keys()) == set(ARTIFACT_ENTRY_KEYS)
    assert entry2["path"] == "dist/report.json"
    assert entry2["label"] == "report"
    assert _datetime.fromisoformat(str(entry2["added_at"])) >= first_ts
    assert len(second["artifacts"]) == 2
    # Earlier entry unchanged (append-only)
    assert second["artifacts"][0] == entry
    assert second["stage_id"] == "artifact-entry-step"

    # Explicit empty string label is stored exactly (only None produces null)
    third = stage.artifact("dist/empty-label.bin", label="")
    assert third["artifacts"][-1]["label"] == ""
    assert set(third["artifacts"][-1].keys()) == set(ARTIFACT_ENTRY_KEYS)


def test_artifact_audit_event_shape_freeze(tmp_path: Path) -> None:
    """Each artifact appends one artifact event with path message + path/label detail (SPEC §13.29.4)."""
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="artifact-audit-freeze")
    stage.start(stage="artifact-audit-step", pid=os.getpid())

    # Omitted label: message is path, detail carries null label
    events_before = len(stage.events())
    stage.artifact("dist/out.bin")
    events = stage.events()
    assert len(events) == events_before + 1
    last = events[-1]
    assert last["type"] == "artifact"
    assert last["type"] in EVENT_TYPES
    assert last["state"] == STATE_RUNNING
    assert last["stage_id"] == "artifact-audit-step"
    assert last["message"] == "dist/out.bin"
    assert tuple(last["detail"].keys()) == ARTIFACT_DETAIL_KEYS
    assert last["detail"] == {"path": "dist/out.bin", "label": None}
    for key in EVENT_RECORD_KEYS:
        assert key in last

    # Set label: message stays path-only, detail echoes path+label exactly
    events_before = len(stage.events())
    stage.artifact("dist/report.json", label="report")
    events = stage.events()
    assert len(events) == events_before + 1
    last = events[-1]
    assert last["type"] == "artifact"
    assert last["message"] == "dist/report.json"
    assert tuple(last["detail"].keys()) == ARTIFACT_DETAIL_KEYS
    assert last["detail"] == {"path": "dist/report.json", "label": "report"}


def test_artifact_preserved_across_heartbeat_freeze(tmp_path: Path) -> None:
    """Artifacts survive heartbeats unchanged (SPEC §13.29.5 cross-links §13.27).

    No sleeps: asserts on entries already recorded.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="artifact-preserve-freeze")
    stage.start(stage="artifact-preserve-step", pid=os.getpid())
    stage.artifact("dist/keep.bin", label="keep")
    before = list(stage.status()["artifacts"])
    assert len(before) == 1

    after = stage.heartbeat(note="still alive")
    assert after["artifacts"] == before
    assert after["state"] == STATE_RUNNING



# =============================================================================
# 25. Note progress appending and MAX_NOTES cap contract freeze (SPEC §13.28, issue #151)
# =============================================================================


def test_note_constants_freeze() -> None:
    """Note frozen constants match the exact values in SPEC §13.28.1."""
    assert NOTE_ALLOWED_SOURCES == ("running",)
    assert isinstance(NOTE_ALLOWED_SOURCES, tuple)
    assert len(NOTE_ALLOWED_SOURCES) == 1
    assert STATE_RUNNING in NOTE_ALLOWED_SOURCES
    for terminal in TERMINAL_STATES:
        assert terminal not in NOTE_ALLOWED_SOURCES
    assert STATE_QUEUED not in NOTE_ALLOWED_SOURCES

    assert NOTE_DETAIL_KEYS == ()
    assert isinstance(NOTE_DETAIL_KEYS, tuple)
    assert len(NOTE_DETAIL_KEYS) == 0

    assert NOTE_ENTRY_KEYS == ("text", "added_at")
    assert MAX_NOTES == 200

    # Allowed sources agree with the frozen transition matrix (SPEC §13.19)
    assert tuple(allowed_source_states("note")) == NOTE_ALLOWED_SOURCES
    assert is_transition_allowed(STATE_RUNNING, "note") is True
    assert transition_target(STATE_RUNNING, "note") == STATE_RUNNING

    for disallowed in (STATE_QUEUED, STATE_DONE, STATE_BLOCKED, STATE_FAILED):
        assert is_transition_allowed(disallowed, "note") is False
        with pytest.raises(ValueError):
            transition_target(disallowed, "note")


def test_note_constants_exported_from_top_level() -> None:
    """Note freeze constants are exported from top-level stage_signal (SPEC §13.28)."""
    import stage_signal

    for name, expected in (
        ("NOTE_ALLOWED_SOURCES", NOTE_ALLOWED_SOURCES),
        ("NOTE_DETAIL_KEYS", NOTE_DETAIL_KEYS),
        ("NOTE_ENTRY_KEYS", NOTE_ENTRY_KEYS),
        ("MAX_NOTES", MAX_NOTES),
    ):
        assert hasattr(stage_signal, name), f"stage_signal missing {name!r}"
        assert name in stage_signal.__all__, f"{name!r} not in stage_signal.__all__"
        assert getattr(stage_signal, name) is expected


def test_note_non_running_guard_semantics(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Note succeeds only from running; uninitialized and non-running refuse (SPEC §13.28.2).

    Synchronous state-machine tests with zero sleeps/threads.
    """
    from stage_signal.cli import main

    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))

    # 1. Uninitialized: exit 15 / NotInitialized
    with pytest.raises(NotInitialized):
        stage.note("uninit probe")
    assert main(["--dir", str(stage_dir), "note", "uninit probe"]) == EXIT_NOT_INITIALIZED
    capsys.readouterr()

    # 2. Queued: exit 3 / IllegalTransition
    stage.init(project="note-guard-test")
    with pytest.raises(IllegalTransition):
        stage.note("queued probe")
    assert main(["--dir", str(stage_dir), "note", "queued probe"]) == EXIT_ILLEGAL_TRANSITION
    capsys.readouterr()
    assert stage.status()["notes"] == []

    # 3. Running: succeeds
    stage.start(stage="guard-running", pid=os.getpid())
    st = stage.note("valid running note")
    assert len(st["notes"]) == 1
    assert st["notes"][0]["text"] == "valid running note"

    # 4. Terminal done: exit 3 / IllegalTransition
    stage.done(summary="finished step")
    with pytest.raises(IllegalTransition):
        stage.note("done probe")
    assert main(["--dir", str(stage_dir), "note", "done probe"]) == EXIT_ILLEGAL_TRANSITION
    capsys.readouterr()
    assert len(stage.status()["notes"]) == 1

    # 5. Terminal blocked: exit 3 / IllegalTransition
    stage.start(stage="guard-blocked", pid=os.getpid())
    stage.blocked(reason="wait for external")
    with pytest.raises(IllegalTransition):
        stage.note("blocked probe")
    assert main(["--dir", str(stage_dir), "note", "blocked probe"]) == EXIT_ILLEGAL_TRANSITION
    capsys.readouterr()

    # 6. Terminal failed: exit 3 / IllegalTransition
    stage.start(stage="guard-failed", pid=os.getpid())
    stage.fail(reason="process crashed")
    with pytest.raises(IllegalTransition):
        stage.note("failed probe")
    assert main(["--dir", str(stage_dir), "note", "failed probe"]) == EXIT_ILLEGAL_TRANSITION
    capsys.readouterr()

    # Verify on-disk status notes count remains 1 from the single successful call
    raw = json.loads((stage_dir / STATUS_FILENAME).read_text())
    assert len(raw["notes"]) == 1
    assert raw["notes"][0]["text"] == "valid running note"


def test_note_input_validation_and_whitespace_semantics(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Note validates non-empty text (exit 2) and preserves valid whitespace verbatim (SPEC §13.28.3).

    Synchronous tests with zero sleeps/threads.
    """
    from stage_signal.cli import main

    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="note-validation-test")
    stage.start(stage="val-stage", pid=os.getpid())

    # Empty text raises BadArgsError (CLI exit 2)
    with pytest.raises(BadArgsError, match="note requires non-empty TEXT"):
        stage.note("")
    assert main(["--dir", str(stage_dir), "note", ""]) == EXIT_BAD_ARGS
    capsys.readouterr()

    # Whitespace-only strings raise BadArgsError (CLI exit 2)
    with pytest.raises(BadArgsError, match="note requires non-empty TEXT"):
        stage.note("   ")
    assert main(["--dir", str(stage_dir), "note", "   "]) == EXIT_BAD_ARGS
    capsys.readouterr()

    with pytest.raises(BadArgsError, match="note requires non-empty TEXT"):
        stage.note("\t \n \r")
    assert main(["--dir", str(stage_dir), "note", "\t \n \r"]) == EXIT_BAD_ARGS
    capsys.readouterr()

    # Missing positional argument in CLI raises SystemExit 2 (argparse)
    with pytest.raises(SystemExit) as exc_info:
        main(["--dir", str(stage_dir), "note"])
    assert exc_info.value.code == EXIT_BAD_ARGS
    capsys.readouterr()

    # Non-empty string with leading/trailing spaces preserves whitespace verbatim
    spaced_text = "   leading and trailing spaces kept   "
    st = stage.note(spaced_text)
    assert st["notes"][-1]["text"] == spaced_text
    events = stage.events()
    assert events[-1]["message"] == spaced_text

    # Multi-line text preserves embedded newlines unchanged
    multiline_text = "first line\nsecond line\nthird line"
    st = stage.note(multiline_text)
    assert st["notes"][-1]["text"] == multiline_text
    events = stage.events()
    assert events[-1]["message"] == multiline_text

    # Successful CLI execution prints standard "noted <one_line>" and exits 0
    capsys.readouterr()
    assert main(["--dir", str(stage_dir), "note", "cli execution success"]) == EXIT_OK
    cli_out = capsys.readouterr().out
    assert cli_out.strip() == "noted running val-stage (attempt 1)"


def test_note_append_and_max_notes_fifo_cap(tmp_path: Path) -> None:
    """Notes append {"text","added_at"} per NOTE_ENTRY_KEYS and FIFO-truncate at MAX_NOTES (SPEC §13.28.4).

    Synchronous tests with zero sleeps/threads.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="note-cap-test")
    stage.start(stage="cap-stage", pid=os.getpid())

    # Check empty initial notes list
    assert stage.status()["notes"] == []

    # 1. Append first note: exactly NOTE_ENTRY_KEYS
    st = stage.note("entry-000")
    assert len(st["notes"]) == 1
    assert tuple(st["notes"][0].keys()) == NOTE_ENTRY_KEYS
    assert st["notes"][0]["text"] == "entry-000"
    # ISO-8601 validation
    ts = datetime.fromisoformat(st["notes"][0]["added_at"])
    assert ts.tzinfo is not None


    # 2. Append up to MAX_NOTES (200 items)
    for i in range(1, MAX_NOTES):
        stage.note(f"entry-{i:03d}")

    st = stage.status()
    assert len(st["notes"]) == MAX_NOTES
    assert st["notes"][0]["text"] == "entry-000"
    assert st["notes"][-1]["text"] == f"entry-{MAX_NOTES - 1:03d}"

    # 3. Append 201st note: oldest entry (entry-000) dropped in FIFO order
    st = stage.note("overflow-200")
    assert len(st["notes"]) == MAX_NOTES
    assert st["notes"][0]["text"] == "entry-001"
    assert st["notes"][-1]["text"] == "overflow-200"

    # 4. Append 50 more notes: verify continuous FIFO ring-buffer truncation
    for i in range(201, 251):
        stage.note(f"overflow-{i:03d}")

    st = stage.status()
    assert len(st["notes"]) == MAX_NOTES
    # 51 total overflows added; entries 0 to 50 were dropped; entry-051 is now first
    assert st["notes"][0]["text"] == "entry-051"
    assert st["notes"][-1]["text"] == "overflow-250"

    # 5. Verify on-disk STATUS.json matches in-memory status exactly
    raw = json.loads((stage_dir / STATUS_FILENAME).read_text())
    assert len(raw["notes"]) == MAX_NOTES
    assert raw["notes"][0]["text"] == "entry-051"
    assert raw["notes"][-1]["text"] == "overflow-250"
    for item in raw["notes"]:
        assert tuple(item.keys()) == NOTE_ENTRY_KEYS
        assert isinstance(item["text"], str)
        assert isinstance(item["added_at"], str)


def test_note_audit_event_shape(tmp_path: Path) -> None:
    """Each note appends one note event with verbatim message + empty detail (SPEC §13.28.5).

    Synchronous tests with zero sleeps/threads.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="note-audit-test")
    stage.start(stage="audit-stage", pid=os.getpid())

    initial_event_count = len(stage.events())

    note_text = "checkpoint reached: data parsed"
    st = stage.note(note_text)
    events = stage.events()
    assert len(events) == initial_event_count + 1

    last_event = events[-1]
    assert last_event["type"] == "note"
    assert last_event["stage_id"] == "audit-stage"
    assert last_event["stage_name"] == "audit-stage"
    assert last_event["state"] == STATE_RUNNING
    assert last_event["attempt"] == 1
    assert last_event["message"] == note_text
    assert last_event["detail"] == {}
    assert tuple(last_event["detail"].keys()) == NOTE_DETAIL_KEYS
    assert last_event["ts"] == st["updated_at"]
    for required_key in EVENT_RECORD_KEYS:
        assert required_key in last_event


def test_note_lifecycle_preservation(tmp_path: Path) -> None:
    """Notes are preserved across clear-terminal (idle & keep-stage) and start (SPEC §13.28.4).

    Synchronous tests with zero sleeps/threads.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="note-lifecycle-test")
    stage.start(stage="step-1", pid=os.getpid())
    stage.note("step-1 note 1")
    stage.note("step-1 note 2")
    stage.done(summary="step-1 complete")

    assert len(stage.status()["notes"]) == 2

    # 1. Clear-terminal default (idle reset): notes array is preserved
    stage.clear_terminal()
    st_idle = stage.status()
    assert st_idle["state"] == STATE_QUEUED
    assert st_idle["stage_id"] is None
    assert len(st_idle["notes"]) == 2
    assert st_idle["notes"][0]["text"] == "step-1 note 1"
    assert st_idle["notes"][1]["text"] == "step-1 note 2"

    # 2. Start new stage: notes array is preserved across start
    stage.start(stage="step-2", pid=os.getpid())
    st_start = stage.status()
    assert st_start["state"] == STATE_RUNNING
    assert st_start["stage_id"] == "step-2"
    assert len(st_start["notes"]) == 2

    stage.note("step-2 note 1")
    assert len(stage.status()["notes"]) == 3
    stage.fail(reason="step-2 failure")

    # 3. Clear-terminal with --keep-stage: notes array is preserved
    stage.clear_terminal(keep_stage=True)
    st_keep = stage.status()
    assert st_keep["state"] == STATE_QUEUED
    assert st_keep["stage_id"] == "step-2"
    assert len(st_keep["notes"]) == 3
    assert [n["text"] for n in st_keep["notes"]] == [
        "step-1 note 1",
        "step-1 note 2",
        "step-2 note 1",
    ]


# =============================================================================
# 28. Done terminal contract freeze (SPEC §13.30, issue #155)
# =============================================================================


def test_done_constants_freeze() -> None:
    """DONE_* constants match SPEC §13.30 and agree with transition matrix."""
    assert DONE_ALLOWED_SOURCES == ("queued", "running", "done")
    assert isinstance(DONE_ALLOWED_SOURCES, tuple)
    assert len(DONE_ALLOWED_SOURCES) == 3

    assert DONE_ACCEPT_FAILURE_ALLOWED_SOURCES == ("failed",)
    assert isinstance(DONE_ACCEPT_FAILURE_ALLOWED_SOURCES, tuple)
    assert len(DONE_ACCEPT_FAILURE_ALLOWED_SOURCES) == 1

    assert DONE_DETAIL_KEYS == ("proof", "git_head", "accepted_failure")
    assert isinstance(DONE_DETAIL_KEYS, tuple)
    assert len(DONE_DETAIL_KEYS) == 3

    # Allowed sources agree with the frozen transition matrix (SPEC §13.19)
    assert tuple(allowed_source_states("done")) == DONE_ALLOWED_SOURCES
    assert tuple(allowed_source_states("done --accept-failure")) == DONE_ACCEPT_FAILURE_ALLOWED_SOURCES

    for src in DONE_ALLOWED_SOURCES:
        assert is_transition_allowed(src, "done") is True
        assert transition_target(src, "done") == STATE_DONE

    assert is_transition_allowed(STATE_BLOCKED, "done") is False
    assert is_transition_allowed(STATE_FAILED, "done") is False

    assert is_transition_allowed(STATE_FAILED, "done --accept-failure") is True
    assert is_transition_allowed(STATE_FAILED, "done_accept_failure") is True
    assert transition_target(STATE_FAILED, "done --accept-failure") == STATE_DONE
    assert transition_target(STATE_FAILED, "done_accept_failure") == STATE_DONE

    for non_failed in (STATE_QUEUED, STATE_RUNNING, STATE_DONE, STATE_BLOCKED):
        assert is_transition_allowed(non_failed, "done --accept-failure") is False


def test_done_constants_exported_from_top_level() -> None:
    """Done freeze constants are exported from top-level stage_signal (SPEC §13.30)."""
    import stage_signal

    for name, expected in (
        ("DONE_ALLOWED_SOURCES", DONE_ALLOWED_SOURCES),
        ("DONE_ACCEPT_FAILURE_ALLOWED_SOURCES", DONE_ACCEPT_FAILURE_ALLOWED_SOURCES),
        ("DONE_DETAIL_KEYS", DONE_DETAIL_KEYS),
    ):
        assert hasattr(stage_signal, name), f"stage_signal missing {name!r}"
        assert name in stage_signal.__all__, f"{name!r} not in stage_signal.__all__"
        assert getattr(stage_signal, name) is expected


# =============================================================================
# 26. Fail terminal contract freeze (SPEC §13.31, issue #156)
# =============================================================================


def test_fail_constants_freeze() -> None:
    """Fail frozen constants match the exact values in SPEC §13.31.1."""
    assert FAIL_ALLOWED_SOURCES == ("queued", "running", "failed")
    assert isinstance(FAIL_ALLOWED_SOURCES, tuple)
    assert len(FAIL_ALLOWED_SOURCES) == 3
    assert STATE_QUEUED in FAIL_ALLOWED_SOURCES
    assert STATE_RUNNING in FAIL_ALLOWED_SOURCES
    assert STATE_FAILED in FAIL_ALLOWED_SOURCES
    for terminal in (STATE_DONE, STATE_BLOCKED):
        assert terminal not in FAIL_ALLOWED_SOURCES

    assert FAIL_IF_DEAD_PID_ALLOWED_SOURCES == ("queued", "running", "failed")
    assert isinstance(FAIL_IF_DEAD_PID_ALLOWED_SOURCES, tuple)
    assert len(FAIL_IF_DEAD_PID_ALLOWED_SOURCES) == 3

    assert FAIL_IF_NEEDS_RECLAIM_ALLOWED_SOURCES == ("running",)
    assert isinstance(FAIL_IF_NEEDS_RECLAIM_ALLOWED_SOURCES, tuple)
    assert len(FAIL_IF_NEEDS_RECLAIM_ALLOWED_SOURCES) == 1
    assert STATE_RUNNING in FAIL_IF_NEEDS_RECLAIM_ALLOWED_SOURCES

    assert FAIL_DETAIL_KEYS == ()
    assert isinstance(FAIL_DETAIL_KEYS, tuple)
    assert len(FAIL_DETAIL_KEYS) == 0

    # Allowed sources agree with the frozen transition matrix (SPEC §13.19)
    assert tuple(allowed_source_states("fail")) == FAIL_ALLOWED_SOURCES
    assert (
        tuple(allowed_source_states("fail --if-dead-pid"))
        == FAIL_IF_DEAD_PID_ALLOWED_SOURCES
    )
    assert (
        tuple(allowed_source_states("fail --if-needs-reclaim"))
        == FAIL_IF_NEEDS_RECLAIM_ALLOWED_SOURCES
    )
    assert is_transition_allowed(STATE_QUEUED, "fail") is True
    assert is_transition_allowed(STATE_RUNNING, "fail") is True
    assert is_transition_allowed(STATE_FAILED, "fail") is True
    assert transition_target(STATE_RUNNING, "fail") == STATE_FAILED
    assert transition_target(STATE_RUNNING, "fail --if-dead-pid") == STATE_FAILED
    assert transition_target(STATE_RUNNING, "fail --if-needs-reclaim") == STATE_FAILED

    for disallowed in (STATE_DONE, STATE_BLOCKED):
        assert is_transition_allowed(disallowed, "fail") is False
        with pytest.raises(ValueError):
            transition_target(disallowed, "fail")
    for disallowed in (STATE_QUEUED, STATE_DONE, STATE_BLOCKED, STATE_FAILED):
        assert is_transition_allowed(disallowed, "fail --if-needs-reclaim") is False
        with pytest.raises(ValueError):
            transition_target(disallowed, "fail --if-needs-reclaim")


def test_fail_constants_exported_from_top_level() -> None:
    """Fail freeze constants are exported from top-level stage_signal (SPEC §13.31)."""
    import stage_signal

    for name, expected in (
        ("FAIL_ALLOWED_SOURCES", FAIL_ALLOWED_SOURCES),
        ("FAIL_DETAIL_KEYS", FAIL_DETAIL_KEYS),
        ("FAIL_IF_DEAD_PID_ALLOWED_SOURCES", FAIL_IF_DEAD_PID_ALLOWED_SOURCES),
        ("FAIL_IF_NEEDS_RECLAIM_ALLOWED_SOURCES", FAIL_IF_NEEDS_RECLAIM_ALLOWED_SOURCES),
    ):
        assert hasattr(stage_signal, name), f"stage_signal missing {name!r}"
        assert name in stage_signal.__all__, f"{name!r} not in stage_signal.__all__"
        assert getattr(stage_signal, name) is expected


def test_done_plain_allowed_sources_and_idempotence(tmp_path: Path) -> None:
    """Plain done succeeds from queued, running, and idempotent done (SPEC §4 rule 5, §13.30).

    Synchronous tests with zero sleeps/threads.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="done-sources-test")

    # 1. Plain done from queued
    assert stage.status()["state"] == STATE_QUEUED
    st_q = stage.done(summary="direct success from queued")
    assert st_q["state"] == STATE_DONE
    assert st_q["result"]["summary"] == "direct success from queued"
    assert "accepted_failure" not in st_q["result"]
    assert st_q["error"] is None

    # 2. Plain done from running
    stage.start(stage="run-1", pid=os.getpid(), git_head="head-run-1")
    assert stage.status()["state"] == STATE_RUNNING
    st_r = stage.done(summary="success from running")
    assert st_r["state"] == STATE_DONE
    assert st_r["result"]["summary"] == "success from running"
    assert st_r["result"]["git_head"] == "head-run-1"
    assert "accepted_failure" not in st_r["result"]
    assert st_r["error"] is None

    # 3. Idempotent repeat from done (same stage)
    st_repeat = stage.done(summary="updated summary on repeat", git_head="head-updated")
    assert st_repeat["state"] == STATE_DONE
    assert st_repeat["result"]["summary"] == "updated summary on repeat"
    assert st_repeat["result"]["git_head"] == "head-updated"
    assert st_repeat["git_head"] == "head-updated"
    assert "accepted_failure" not in st_repeat["result"]
    assert st_repeat["error"] is None


def test_done_plain_illegal_sources(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Plain done is rejected from blocked and failed states (SPEC §4 rule 5, §13.30).

    Synchronous tests with zero sleeps/threads.
    """
    from stage_signal import cli

    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="done-illegal-test")

    # 1. Blocked -> plain done is illegal
    stage.start(stage="stage-blk", pid=os.getpid())
    stage.blocked(reason="waiting on reviewer")
    assert stage.status()["state"] == STATE_BLOCKED

    before_blk_status = (stage_dir / "STATUS.json").read_bytes()
    before_blk_events = (stage_dir / "events.jsonl").read_bytes()

    with pytest.raises(IllegalTransition, match="not allowed from terminal state 'blocked'"):
        stage.done(summary="should fail")

    assert (stage_dir / "STATUS.json").read_bytes() == before_blk_status
    assert (stage_dir / "events.jsonl").read_bytes() == before_blk_events

    # CLI check from blocked
    rc_blk = cli.main(["--dir", str(stage_dir), "done", "--summary", "cli fail"])
    assert rc_blk == EXIT_ILLEGAL_TRANSITION

    # 2. Failed -> plain done is illegal (requires --accept-failure or start)
    stage.start(stage="stage-fail", pid=os.getpid())
    stage.fail(reason="build broke")
    assert stage.status()["state"] == STATE_FAILED

    before_fail_status = (stage_dir / "STATUS.json").read_bytes()
    before_fail_events = (stage_dir / "events.jsonl").read_bytes()

    with pytest.raises(IllegalTransition, match="not allowed from terminal state 'failed'"):
        stage.done(summary="cannot plain done from failed")

    assert (stage_dir / "STATUS.json").read_bytes() == before_fail_status
    assert (stage_dir / "events.jsonl").read_bytes() == before_fail_events

    # CLI check from failed without --accept-failure
    rc_fail = cli.main(["--dir", str(stage_dir), "done", "--summary", "cli fail"])
    assert rc_fail == EXIT_ILLEGAL_TRANSITION


def test_done_accept_failure_semantics(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """done --accept-failure succeeds ONLY from failed and records accepted_failure (SPEC §13.30).

    Synchronous tests with zero sleeps/threads.
    """
    from stage_signal import cli

    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="accept-failure-test")
    stage.start(stage="af-stage", pid=os.getpid(), git_head="head-init")
    stage.fail(reason="flaky test failure")

    assert stage.status()["state"] == STATE_FAILED
    assert stage.status()["error"]["reason"] == "flaky test failure"

    # Library call
    st = stage.done(summary="accepted test failure", accept_failure=True)
    assert st["state"] == STATE_DONE
    assert st["result"]["summary"] == "accepted test failure"
    assert st["result"]["git_head"] == "head-init"
    assert st["result"]["accepted_failure"] is True
    assert set(st["result"].keys()) == set(RESULT_KEYS) | {"accepted_failure"}
    assert st["error"] is None  # Error is cleared!

    # Audit event check
    events = stage.events()
    last_event = events[-1]
    assert last_event["type"] == "done"
    assert last_event["state"] == STATE_DONE
    assert last_event["message"] == "accepted test failure"
    assert last_event["detail"]["accepted_failure"] is True
    assert set(last_event["detail"].keys()) == set(DONE_DETAIL_KEYS)
    assert tuple(last_event["detail"].keys()) == DONE_DETAIL_KEYS

    # CLI check: fail again then call CLI with --accept-failure
    stage.start(stage="af-stage-cli", pid=os.getpid())
    stage.fail(reason="cli test failure")
    rc = cli.main([
        "--dir", str(stage_dir), "done",
        "--accept-failure",
        "--summary", "accepted via cli",
    ])
    assert rc == EXIT_OK
    st_cli = stage.status()
    assert st_cli["state"] == STATE_DONE
    assert st_cli["result"]["summary"] == "accepted via cli"
    assert st_cli["result"]["accepted_failure"] is True
    assert st_cli["error"] is None


def test_done_accept_failure_illegal_sources(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """done --accept-failure is rejected from queued, running, blocked, done (SPEC §13.30).

    Synchronous tests with zero sleeps/threads.
    """
    from stage_signal import cli

    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="af-illegal-test")

    # 1. From queued
    assert stage.status()["state"] == STATE_QUEUED
    with pytest.raises(IllegalTransition, match="only allowed from state 'failed'"):
        stage.done(accept_failure=True)
    rc = cli.main(["--dir", str(stage_dir), "done", "--accept-failure"])
    assert rc == EXIT_ILLEGAL_TRANSITION

    # 2. From running
    stage.start(stage="af-running", pid=os.getpid())
    assert stage.status()["state"] == STATE_RUNNING
    with pytest.raises(IllegalTransition, match="only allowed from state 'failed'"):
        stage.done(accept_failure=True)
    rc = cli.main(["--dir", str(stage_dir), "done", "--accept-failure"])
    assert rc == EXIT_ILLEGAL_TRANSITION

    # 3. From blocked
    stage.blocked(reason="paused")
    assert stage.status()["state"] == STATE_BLOCKED
    with pytest.raises(IllegalTransition, match="only allowed from state 'failed'"):
        stage.done(accept_failure=True)
    rc = cli.main(["--dir", str(stage_dir), "done", "--accept-failure"])
    assert rc == EXIT_ILLEGAL_TRANSITION

    # 4. From done
    stage.start(stage="af-done", pid=os.getpid())
    stage.done(summary="success")
    assert stage.status()["state"] == STATE_DONE
    with pytest.raises(IllegalTransition, match="only allowed from state 'failed'"):
        stage.done(accept_failure=True)
    rc = cli.main(["--dir", str(stage_dir), "done", "--accept-failure"])
    assert rc == EXIT_ILLEGAL_TRANSITION


def test_done_result_payload_and_error_clearing(tmp_path: Path) -> None:
    """Result payload conforms to RESULT_KEYS and error is cleared to null (SPEC §13.9, §13.30).

    Synchronous tests with zero sleeps/threads.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="result-shape-test")
    stage.start(stage="res-stage", pid=os.getpid(), git_head="head-start")

    st = stage.done(summary="clean finish", git_head="head-done-override")
    assert st["state"] == STATE_DONE
    assert st["error"] is None

    result = st["result"]
    assert isinstance(result, dict)
    assert set(result.keys()) == set(RESULT_KEYS)
    assert result["summary"] == "clean finish"
    assert result["git_head"] == "head-done-override"
    assert st["git_head"] == "head-done-override"
    assert isinstance(result["finished_at"], str)

    # finished_at parses as valid ISO-8601
    dt = datetime.fromisoformat(result["finished_at"])
    assert dt.tzinfo is not None

    # updated_at parses as valid ISO-8601
    dt_up = datetime.fromisoformat(st["updated_at"])
    assert dt_up.tzinfo is not None


def test_done_proof_and_require_proof_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proof recording and --require-proof verification gate semantics (SPEC §9, §13.10, §13.30).

    Synchronous tests with zero sleeps/threads.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="proof-test")
    stage.start(stage="proof-stage", pid=os.getpid())

    # 1. Unverified proof_ref alone
    st_unverified = stage.done(summary="unverified proof", proof_ref="ledger:proof-123")
    proof = st_unverified["proof"]
    assert proof is not None
    assert proof["tool"] == "agent-done-or-not"
    assert proof["ref"] == "ledger:proof-123"
    assert proof["verified"] is None
    assert set(proof.keys()) == set(PROOF_KEYS)

    # 2. Valid file proof with require_proof=True
    receipt_file = tmp_path / "valid-receipt.json"
    receipt_file.write_text('{"status": "ok", "receipt": "abc"}')

    stage.start(stage="proof-stage-2", pid=os.getpid())
    st_verified = stage.done(
        summary="verified proof",
        proof_ref=str(receipt_file),
        require_proof=True,
    )
    proof_v = st_verified["proof"]
    assert proof_v is not None
    assert proof_v["tool"] == "agent-done-or-not"
    assert proof_v["ref"] == str(receipt_file)
    assert proof_v["verified"] == "file"
    assert proof_v["verified"] in PROOF_VERIFIED_VALUES
    assert set(proof_v.keys()) == set(PROOF_KEYS)

    # 3. require_proof=True with non-existent file fails BEFORE mutation
    stage.start(stage="proof-fail-stage", pid=os.getpid())
    before_status = (stage_dir / "STATUS.json").read_bytes()
    before_events = (stage_dir / "events.jsonl").read_bytes()

    with pytest.raises(IllegalTransition, match="proof gate failed"):
        stage.done(
            summary="should fail",
            proof_ref=str(tmp_path / "missing-receipt.json"),
            require_proof=True,
        )

    assert (stage_dir / "STATUS.json").read_bytes() == before_status
    assert (stage_dir / "events.jsonl").read_bytes() == before_events
    assert stage.status()["state"] == STATE_RUNNING

    # 4. require_proof=True with missing proof_ref fails BEFORE mutation
    with pytest.raises(IllegalTransition, match="needs --proof-ref REF"):
        stage.done(summary="missing ref", require_proof=True)

    assert stage.status()["state"] == STATE_RUNNING

    # 5. Fallback to ENV_PROOF_REF environment variable
    monkeypatch.setenv("STAGE_SIGNAL_PROOF_REF", str(receipt_file))
    st_env = stage.done(summary="env verified", require_proof=True)
    assert st_env["state"] == STATE_DONE
    assert st_env["proof"]["ref"] == str(receipt_file)
    assert st_env["proof"]["verified"] == "file"


def test_done_audit_event_shape(tmp_path: Path) -> None:
    """Each done appends one done event with summary message + detail keys (SPEC §13.30.5).

    Synchronous tests with zero sleeps/threads.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="done-audit-test")
    stage.start(stage="audit-stage", pid=os.getpid(), git_head="head-audit")

    initial_event_count = len(stage.events())

    summary_text = "all requirements verified"
    st = stage.done(summary=summary_text, git_head="head-audit")
    events = stage.events()
    assert len(events) == initial_event_count + 1

    last_event = events[-1]
    assert last_event["type"] == "done"
    assert last_event["stage_id"] == "audit-stage"
    assert last_event["stage_name"] == "audit-stage"
    assert last_event["state"] == STATE_DONE
    assert last_event["attempt"] == 1
    assert last_event["message"] == summary_text
    assert last_event["ts"] == st["updated_at"]

    for required_key in EVENT_RECORD_KEYS:
        assert required_key in last_event

    # Plain done detail keys: ("proof", "git_head")
    detail = last_event["detail"]
    assert isinstance(detail, dict)
    assert tuple(detail.keys()) == ("proof", "git_head")
    assert detail["git_head"] == "head-audit"
    assert detail["proof"] is None
    assert "accepted_failure" not in detail
    assert set(detail.keys()).issubset(set(DONE_DETAIL_KEYS))

    # done with summary=None passes message=None
    stage.start(stage="audit-none-summary", pid=os.getpid())
    st_none = stage.done(summary=None)
    ev_none = stage.events()[-1]
    assert ev_none["message"] is None


def test_done_uninitialized(tmp_path: Path) -> None:
    """done raises NotInitialized (exit 15) when stage dir is uninitialized (SPEC §13.17, §13.30).

    Synchronous tests with zero sleeps/threads.
    """
    from stage_signal import cli

    missing_dir = tmp_path / "nonexistent" / ".stage-signal"
    stage = Stage(str(missing_dir))

    with pytest.raises(NotInitialized):
        stage.done(summary="cannot done")

    rc = cli.main(["--dir", str(missing_dir), "done"])
    assert rc == EXIT_NOT_INITIALIZED


def test_done_status_md_rendering(tmp_path: Path) -> None:
    """STATUS.md human mirror renders state: done, result:, and omits error: (SPEC §13.18, §13.30).

    Synchronous tests with zero sleeps/threads.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="status-md-test")
    stage.start(stage="md-stage", pid=os.getpid(), git_head="head-md")
    stage.done(summary="finished task successfully")

    status_md_path = stage_dir / "STATUS.md"
    assert status_md_path.is_file()
    content = status_md_path.read_text()

    assert "# stage-signal STATUS" in content
    assert "state: done" in content
    assert "stage: md-stage" in content
    assert "result:" in content
    assert "finished task successfully" in content
    assert "error:" not in content


def test_fail_plain_sources_and_reason_validation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Plain fail succeeds from queued/running/failed; done/blocked refuse exit 3 (SPEC §13.31.2).

    Empty/whitespace-only reasons are BadArgs (exit 2) regardless of state (SPEC §13.31.3).
    Synchronous state-machine smoke with no sleeps/threads.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="fail-sources-freeze")
    status_file = stage_dir / "STATUS.json"

    def assert_no_mutation(snapshot: str, event_count: int) -> None:
        assert status_file.read_text(encoding="utf-8") == snapshot
        assert len(stage.events()) == event_count

    # Empty/whitespace-only reason is BadArgs (exit 2) even from queued
    for bad_reason in ("", "   ", "\t \n"):
        with pytest.raises(BadArgsError, match="fail requires non-empty --reason TEXT"):
            stage.fail(bad_reason)
    capsys.readouterr()
    assert main(["--dir", str(stage_dir), "fail", "--reason", "  "]) == EXIT_BAD_ARGS
    assert_no_mutation(status_file.read_text(encoding="utf-8"), 1)

    # Missing --reason flag is argparse exit 2
    with pytest.raises(SystemExit) as exc_info:
        main(["--dir", str(stage_dir), "fail"])
    assert exc_info.value.code == EXIT_BAD_ARGS
    capsys.readouterr()
    assert_no_mutation(status_file.read_text(encoding="utf-8"), 1)

    # queued succeeds via library
    st = stage.fail("queued failure")
    assert st["state"] == STATE_FAILED
    assert st["error"]["reason"] == "queued failure"

    # idempotent repeat from failed succeeds and overwrites the reason
    st = stage.fail("failed again")
    assert st["state"] == STATE_FAILED
    assert st["error"]["reason"] == "failed again"

    # done refuses with no mutation
    stage.start(stage="fail-done-step", pid=os.getpid())
    stage.done(summary="finished")
    assert stage.status()["state"] == STATE_DONE
    before = status_file.read_text(encoding="utf-8")
    events_before = len(stage.events())
    with pytest.raises(IllegalTransition):
        stage.fail("should not land")
    assert_no_mutation(before, events_before)
    capsys.readouterr()
    assert (
        main(["--dir", str(stage_dir), "fail", "--reason", "should not land"])
        == EXIT_ILLEGAL_TRANSITION
    )
    assert_no_mutation(before, events_before)

    # blocked refuses with no mutation
    stage.start(stage="fail-blocked-step", pid=os.getpid())
    stage.blocked(reason="waiting")
    assert stage.status()["state"] == STATE_BLOCKED
    before = status_file.read_text(encoding="utf-8")
    events_before = len(stage.events())
    with pytest.raises(IllegalTransition):
        stage.fail("should not land")
    assert_no_mutation(before, events_before)
    capsys.readouterr()
    assert (
        main(["--dir", str(stage_dir), "fail", "--reason", "should not land"])
        == EXIT_ILLEGAL_TRANSITION
    )
    assert_no_mutation(before, events_before)

    # running succeeds via CLI
    stage.start(stage="fail-running-step", pid=os.getpid())
    capsys.readouterr()
    assert main(["--dir", str(stage_dir), "fail", "--reason", "cli failure"]) == EXIT_OK
    out = capsys.readouterr().out
    assert out.startswith("failed failed fail-running-step (attempt 1): cli failure")
    assert stage.status()["state"] == STATE_FAILED


def test_fail_reason_stored_verbatim(tmp_path: Path) -> None:
    """A valid reason is stored byte-for-byte (validation strips only for the check) (SPEC §13.31.3)."""
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="fail-verbatim-freeze")
    stage.start(stage="fail-verbatim-step", pid=os.getpid())

    reason = "  disk full: /tmp kept  "
    st = stage.fail(reason)
    assert st["error"]["reason"] == reason
    events = stage.events()
    assert events[-1]["type"] == "failed"
    assert events[-1]["message"] == reason


def test_fail_flag_mutual_exclusion(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--if-dead-pid + --if-needs-reclaim together are BadArgs (exit 2), no mutation (SPEC §13.31.3)."""
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="fail-mutex-freeze")
    stage.start(stage="fail-mutex-step", pid=os.getpid())
    status_file = stage_dir / "STATUS.json"
    before = status_file.read_text(encoding="utf-8")
    events_before = len(stage.events())

    with pytest.raises(BadArgsError, match="mutually exclusive"):
        stage.fail("both flags", if_dead_pid=True, if_needs_reclaim=True)
    assert status_file.read_text(encoding="utf-8") == before
    assert len(stage.events()) == events_before

    capsys.readouterr()
    assert (
        main(
            [
                "--dir", str(stage_dir), "fail",
                "--reason", "both flags",
                "--if-dead-pid", "--if-needs-reclaim",
            ]
        )
        == EXIT_BAD_ARGS
    )
    assert status_file.read_text(encoding="utf-8") == before
    assert len(stage.events()) == events_before
    # Stage is still running and unfailing afterwards
    assert stage.status()["state"] == STATE_RUNNING


def test_fail_if_needs_reclaim_guard(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """fail --if-needs-reclaim succeeds only when needs_reclaim is true (SPEC §13.31.4).

    Synchronous: DEAD_PID is produced with a reaped child pid (no sleeps/threads).
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="fail-reclaim-guard-freeze")
    status_file = stage_dir / "STATUS.json"

    def assert_no_mutation(snapshot: str, event_count: int) -> None:
        assert status_file.read_text(encoding="utf-8") == snapshot
        assert len(stage.events()) == event_count

    # queued refuses: needs_reclaim is false outside running
    before = status_file.read_text(encoding="utf-8")
    with pytest.raises(IllegalTransition, match="needs_reclaim is false"):
        stage.fail("queued reclaim probe", if_needs_reclaim=True)
    assert_no_mutation(before, 1)
    capsys.readouterr()
    assert (
        main(["--dir", str(stage_dir), "fail", "--reason", "queued reclaim probe",
              "--if-needs-reclaim"])
        == EXIT_ILLEGAL_TRANSITION
    )
    assert_no_mutation(before, 1)

    # healthy running (alive pid, fresh heartbeat) refuses with no mutation
    stage.start(stage="fail-healthy-step", pid=os.getpid())
    assert stage.diagnose()["needs_reclaim"] is False
    before = status_file.read_text(encoding="utf-8")
    events_before = len(stage.events())
    with pytest.raises(IllegalTransition, match="needs_reclaim is false"):
        stage.fail("healthy probe", if_needs_reclaim=True)
    assert_no_mutation(before, events_before)
    capsys.readouterr()
    assert (
        main(["--dir", str(stage_dir), "fail", "--reason", "healthy probe",
              "--if-needs-reclaim"])
        == EXIT_ILLEGAL_TRANSITION
    )
    assert_no_mutation(before, events_before)
    assert stage.status()["state"] == STATE_RUNNING

    # running with a confirmed-dead claiming pid: needs_reclaim true, guard passes
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    dead_pid = proc.pid
    stage.start(stage="fail-stuck-step", pid=dead_pid)
    assert stage.diagnose()["needs_reclaim"] is True
    events_before = len(stage.events())
    st = stage.fail("stuck worker", if_needs_reclaim=True)
    assert st["state"] == STATE_FAILED
    assert st["error"] == {
        "reason": "stuck worker",
        "kind": STATE_FAILED,
        "finished_at": st["error"]["finished_at"],
    }
    assert len(stage.events()) == events_before + 1
    assert stage.events()[-1]["type"] == "failed"
    assert stage.events()[-1]["detail"] == {}

    # non-running failed refuses again (needs_reclaim false outside running)
    before = status_file.read_text(encoding="utf-8")
    events_before = len(stage.events())
    with pytest.raises(IllegalTransition, match="needs_reclaim is false"):
        stage.fail("failed-state probe", if_needs_reclaim=True)
    assert_no_mutation(before, events_before)

    # done refuses as well
    stage.start(stage="fail-done-reclaim-step", pid=os.getpid())
    stage.done(summary="finished")
    before = status_file.read_text(encoding="utf-8")
    events_before = len(stage.events())
    with pytest.raises(IllegalTransition, match="needs_reclaim is false"):
        stage.fail("done-state probe", if_needs_reclaim=True)
    assert_no_mutation(before, events_before)


def test_fail_if_dead_pid_guard(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """fail --if-dead-pid enforces the dead-pid liveness gate only from running (SPEC §13.31.5).

    Synchronous: dead pid from a reaped child; no sleeps/threads.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="fail-dead-pid-freeze")
    status_file = stage_dir / "STATUS.json"

    def assert_no_mutation(snapshot: str, event_count: int) -> None:
        assert status_file.read_text(encoding="utf-8") == snapshot
        assert len(stage.events()) == event_count

    # queued: guard skipped, plain-fail rules apply (exit 0)
    st = stage.fail("queued dead-pid probe", if_dead_pid=True)
    assert st["state"] == STATE_FAILED
    assert st["error"]["reason"] == "queued dead-pid probe"

    # running with a live claiming pid refuses with no mutation
    stage.start(stage="fail-live-step", pid=os.getpid())
    before = status_file.read_text(encoding="utf-8")
    events_before = len(stage.events())
    with pytest.raises(IllegalTransition, match="is alive"):
        stage.fail("live pid probe", if_dead_pid=True)
    assert_no_mutation(before, events_before)
    capsys.readouterr()
    assert (
        main(["--dir", str(stage_dir), "fail", "--reason", "live pid probe",
              "--if-dead-pid"])
        == EXIT_ILLEGAL_TRANSITION
    )
    assert_no_mutation(before, events_before)
    assert stage.status()["state"] == STATE_RUNNING

    # running with a null claiming pid refuses with no mutation
    raw = json.loads(status_file.read_text(encoding="utf-8"))
    raw["pid"] = None
    status_file.write_text(json.dumps(raw), encoding="utf-8")
    before = status_file.read_text(encoding="utf-8")
    events_before = len(stage.events())
    with pytest.raises(IllegalTransition, match="valid positive integer"):
        stage.fail("null pid probe", if_dead_pid=True)
    assert_no_mutation(before, events_before)

    # running with a confirmed-dead claiming pid succeeds
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    stage.start(stage="fail-dead-step", pid=proc.pid)
    events_before = len(stage.events())
    st = stage.fail("dead worker", if_dead_pid=True)
    assert st["state"] == STATE_FAILED
    assert st["error"]["reason"] == "dead worker"
    assert st["error"]["kind"] == STATE_FAILED
    assert len(stage.events()) == events_before + 1

    # failed: guard skipped, idempotent repeat succeeds
    st = stage.fail("failed repeat", if_dead_pid=True)
    assert st["state"] == STATE_FAILED
    assert st["error"]["reason"] == "failed repeat"

    # done refuses with no mutation (plain-fail terminal guard)
    stage.start(stage="fail-dead-done-step", pid=os.getpid())
    stage.done(summary="finished")
    before = status_file.read_text(encoding="utf-8")
    events_before = len(stage.events())
    with pytest.raises(IllegalTransition):
        stage.fail("done dead-pid probe", if_dead_pid=True)
    assert_no_mutation(before, events_before)
    capsys.readouterr()
    assert (
        main(["--dir", str(stage_dir), "fail", "--reason", "done dead-pid probe",
              "--if-dead-pid"])
        == EXIT_ILLEGAL_TRANSITION
    )
    assert_no_mutation(before, events_before)


def test_fail_success_payload_and_audit_freeze(tmp_path: Path) -> None:
    """Successful fail writes the ERROR_KEYS error object, result null, one failed event (SPEC §13.31.6/13.31.7)."""
    from datetime import datetime as _datetime

    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="fail-payload-freeze")
    stage.start(stage="fail-payload-step", pid=os.getpid())
    stage_id_before = stage.status()["stage_id"]
    events_before = len(stage.events())

    st = stage.fail("disk full")

    # State + error object cross-linked to ERROR_KEYS / ERROR_KINDS (§13.9, not redefined)
    assert st["state"] == STATE_FAILED
    assert set(st["error"].keys()) == set(ERROR_KEYS)
    assert tuple(st["error"].keys()) == ERROR_KEYS
    assert st["error"]["reason"] == "disk full"
    assert st["error"]["kind"] == STATE_FAILED
    assert st["error"]["kind"] in ERROR_KINDS
    finished = _datetime.fromisoformat(str(st["error"]["finished_at"]))
    assert finished.tzinfo is not None
    # result is null; identity fields preserved; updated_at bumped
    assert st["result"] is None
    assert st["stage_id"] == stage_id_before

    # Exactly one failed event: reason passthrough message, empty detail
    events = stage.events()
    assert len(events) == events_before + 1
    last = events[-1]
    assert last["type"] == "failed"
    assert last["type"] in EVENT_TYPES
    assert last["state"] == STATE_FAILED
    assert last["stage_id"] == stage_id_before
    assert last["message"] == "disk full"
    assert last["detail"] == {}
    assert tuple(last["detail"].keys()) == FAIL_DETAIL_KEYS
    assert last["ts"] == st["updated_at"]
    for key in EVENT_RECORD_KEYS:
        assert key in last

    # On-disk STATUS.json matches the returned snapshot payload
    raw = json.loads((stage_dir / STATUS_FILENAME).read_text(encoding="utf-8"))
    assert raw["state"] == STATE_FAILED
    assert raw["error"] == st["error"]
    assert raw["result"] is None


# =============================================================================
# 29. Start claim-running contract freeze (SPEC §13.33, issue #160)
# =============================================================================


def test_start_constants_freeze() -> None:
    """START_* constants match SPEC §13.33 and agree with transition matrix."""
    assert START_ALLOWED_SOURCES == ("queued", "running", "done", "blocked", "failed")
    assert isinstance(START_ALLOWED_SOURCES, tuple)
    assert len(START_ALLOWED_SOURCES) == 5
    assert set(START_ALLOWED_SOURCES) == set(STATES)
    for terminal in TERMINAL_STATES:
        assert terminal in START_ALLOWED_SOURCES

    assert START_DETAIL_KEYS == ("stage_id", "session_id", "pid", "model", "variant")
    assert isinstance(START_DETAIL_KEYS, tuple)
    assert len(START_DETAIL_KEYS) == 5
    assert len(set(START_DETAIL_KEYS)) == 5

    # Allowed sources agree with the frozen transition matrix (SPEC §13.19)
    assert tuple(allowed_source_states("start")) == START_ALLOWED_SOURCES
    for src in START_ALLOWED_SOURCES:
        assert is_transition_allowed(src, "start") is True
        assert transition_target(src, "start") == STATE_RUNNING


def test_start_constants_exported_from_top_level() -> None:
    """Start freeze constants are exported from top-level stage_signal (SPEC §13.33)."""
    import stage_signal

    for name, expected in (
        ("START_ALLOWED_SOURCES", START_ALLOWED_SOURCES),
        ("START_DETAIL_KEYS", START_DETAIL_KEYS),
    ):
        assert hasattr(stage_signal, name), f"stage_signal missing {name!r}"
        assert name in stage_signal.__all__, f"{name!r} not in stage_signal.__all__"
        assert getattr(stage_signal, name) is expected


def test_start_allowed_from_any_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Start succeeds from queued, running, done, blocked, and failed (SPEC §4 rule 2, §13.33).

    Synchronous tests with zero sleeps/threads.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="start-sources-test")

    # 1. queued -> running (fresh claim, attempt starts at 1)
    assert stage.status()["state"] == STATE_QUEUED
    st = stage.start(stage="step-a", pid=os.getpid())
    assert st["state"] == STATE_RUNNING
    assert st["stage_id"] == "step-a"
    assert st["stage_name"] == "step-a"
    assert st["attempt"] == 1

    # 2. running -> running (same-stage retry bumps attempt)
    st = stage.start(stage="step-a", pid=os.getpid())
    assert st["state"] == STATE_RUNNING
    assert st["attempt"] == 2

    # 3. done -> running (terminal cleared for a new attempt)
    stage.done(summary="finished step-a")
    assert stage.status()["state"] == STATE_DONE
    st = stage.start(stage="step-b", pid=os.getpid())
    assert st["state"] == STATE_RUNNING
    assert st["stage_id"] == "step-b"
    assert st["attempt"] == 1

    # 4. blocked -> running
    stage.blocked(reason="waiting on reviewer")
    assert stage.status()["state"] == STATE_BLOCKED
    st = stage.start(stage="step-c", pid=os.getpid())
    assert st["state"] == STATE_RUNNING
    assert st["attempt"] == 1

    # 5. failed -> running via CLI (exit 0, `started` summary line)
    stage.fail(reason="crashed")
    assert stage.status()["state"] == STATE_FAILED
    capsys.readouterr()
    assert main(["--dir", str(stage_dir), "start", "--stage", "step-d"]) == EXIT_OK
    out = capsys.readouterr().out
    assert out.startswith("started running step-d (attempt 1)")
    assert stage.status()["state"] == STATE_RUNNING
    assert stage.status()["attempt"] == 1


def test_start_stage_and_stage_id_validation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Empty stage names are BadArgs; strip/default/verbatim id rules (SPEC §13.33.3).

    Synchronous tests with zero sleeps/threads.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="start-validation-test")
    status_file = stage_dir / "STATUS.json"

    def assert_no_mutation(snapshot: str, event_count: int) -> None:
        assert status_file.read_text(encoding="utf-8") == snapshot
        assert len(stage.events()) == event_count

    # Empty / whitespace-only / None stage is BadArgs (exit 2) with no mutation
    for bad_stage in ("", "   ", "\t \n", None):
        with pytest.raises(BadArgsError, match="start requires a non-empty --stage NAME"):
            stage.start(stage=bad_stage)  # type: ignore[arg-type]
    assert_no_mutation(status_file.read_text(encoding="utf-8"), 1)

    capsys.readouterr()
    assert main(["--dir", str(stage_dir), "start", "--stage", "  "]) == EXIT_BAD_ARGS
    assert_no_mutation(status_file.read_text(encoding="utf-8"), 1)

    # Missing --stage flag is argparse exit 2
    with pytest.raises(SystemExit) as exc_info:
        main(["--dir", str(stage_dir), "start"])
    assert exc_info.value.code == EXIT_BAD_ARGS
    capsys.readouterr()
    assert_no_mutation(status_file.read_text(encoding="utf-8"), 1)

    # Stored stage_name is stripped; default stage_id derives from the stripped name
    st = stage.start(stage="  spaced  ", pid=os.getpid())
    assert st["stage_name"] == "spaced"
    assert st["stage_id"] == "spaced"

    # Empty-string stage_id falls back to the stripped stage name
    st = stage.start(stage="fallback", stage_id="", pid=os.getpid())
    assert st["stage_id"] == "fallback"

    # Explicit truthy stage_id wins verbatim (no stripping) and defines the series
    st = stage.start(stage="label", stage_id="  custom-id  ", pid=os.getpid())
    assert st["stage_name"] == "label"
    assert st["stage_id"] == "  custom-id  "
    assert st["attempt"] == 1
    st = stage.start(stage="label", stage_id="  custom-id  ", pid=os.getpid())
    assert st["attempt"] == 2


def test_start_pid_validation_and_default(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Non-integer/negative pids are BadArgs; omitted pid claims self (SPEC §13.33.3/13.33.4).

    Synchronous tests with zero sleeps/threads.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="start-pid-test")
    status_file = stage_dir / "STATUS.json"

    def assert_no_mutation(snapshot: str, event_count: int) -> None:
        assert status_file.read_text(encoding="utf-8") == snapshot
        assert len(stage.events()) == event_count

    # Negative or non-integer pid is BadArgs with no mutation
    with pytest.raises(BadArgsError, match="invalid pid"):
        stage.start(stage="x", pid=-1)
    assert_no_mutation(status_file.read_text(encoding="utf-8"), 1)
    with pytest.raises(BadArgsError, match="invalid pid"):
        stage.start(stage="x", pid="123")  # type: ignore[arg-type]
    assert_no_mutation(status_file.read_text(encoding="utf-8"), 1)

    # CLI --pid with a non-numeric value fails in argparse with exit 2
    with pytest.raises(SystemExit) as exc_info:
        main(["--dir", str(stage_dir), "start", "--stage", "x", "--pid", "abc"])
    assert exc_info.value.code == EXIT_BAD_ARGS
    capsys.readouterr()
    assert_no_mutation(status_file.read_text(encoding="utf-8"), 1)

    # Omitted pid resolves to the calling process; start never probes liveness
    st = stage.start(stage="self-claim")
    assert st["pid"] == os.getpid()

    # An explicit pid is stored as-is even when that pid is not alive
    st = stage.start(stage="explicit-claim", pid=424242)
    assert st["pid"] == 424242


def test_start_claim_fields_pid_token(tmp_path: Path) -> None:
    """Session/pid/pid_token/model/variant recorded and replaced each start (SPEC §13.33.4).

    Synchronous tests with zero sleeps/threads.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="start-claim-test")

    st = stage.start(
        stage="claim-a",
        session_id="ses-1",
        pid=os.getpid(),
        model="muse-spark",
        variant="free",
    )
    assert st["session_id"] == "ses-1"
    assert st["pid"] == os.getpid()
    assert st["model"] == "muse-spark"
    assert st["variant"] == "free"
    token = st["pid_token"]
    assert token is None or (isinstance(token, str) and len(token) > 0)

    # Omitted annotations stay null
    st = stage.start(stage="claim-b", pid=os.getpid())
    assert st["session_id"] is None
    assert st["model"] is None
    assert st["variant"] is None
    token2 = st["pid_token"]
    assert token2 is None or (isinstance(token2, str) and len(token2) > 0)

    # Claim fields are replaced (not merged) on every start
    assert st["session_id"] != "ses-1"
    assert st["model"] != "muse-spark"


def test_start_attempt_and_field_lifecycle(tmp_path: Path) -> None:
    """Attempt series, conditional artifact clear, notes/meta/result lifecycle (SPEC §13.33.5).

    Synchronous tests with zero sleeps/threads.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="start-lifecycle-test")

    # Same stage_id retries bump attempt and keep artifacts
    stage.start(stage="series-a", pid=os.getpid(), meta={"ticket": "1"})
    stage.artifact("dist/out.bin", label="binary")
    stage.note("progress note")
    st = stage.start(stage="series-a", pid=os.getpid(), meta={"ticket": "2"})
    assert st["attempt"] == 2
    assert [a["path"] for a in st["artifacts"]] == ["dist/out.bin"]
    # Meta is replaced entirely, notes are preserved
    assert st["meta"] == {"ticket": "2"}
    assert [n["text"] for n in st["notes"]] == ["progress note"]
    # Fresh-claim heartbeat reset
    assert st["heartbeat_note"] is None
    assert isinstance(st["started_at"], str) and st["started_at"]
    assert isinstance(st["heartbeat_at"], str) and st["heartbeat_at"]

    # New stage_id resets attempt to 1 and clears artifacts but keeps notes
    st = stage.start(stage="series-b", pid=os.getpid())
    assert st["attempt"] == 1
    assert st["artifacts"] == []
    assert [n["text"] for n in st["notes"]] == ["progress note"]
    assert st["meta"] == {}

    # Terminal payloads and proof receipts are cleared by the next claim
    stage.done(summary="series-b done", proof_ref="ledger:proof-1")
    assert stage.status()["result"] is not None
    assert stage.status()["proof"] is not None
    st = stage.start(stage="series-c", pid=os.getpid())
    assert st["result"] is None
    assert st["error"] is None
    assert st["proof"] is None

    # Error payloads are cleared the same way
    stage.fail(reason="series-c broke")
    assert stage.status()["error"] is not None
    st = stage.start(stage="series-d", pid=os.getpid())
    assert st["state"] == STATE_RUNNING
    assert st["error"] is None
    assert st["result"] is None
    # All on-disk required keys remain present after every start
    raw = json.loads((stage_dir / STATUS_FILENAME).read_text(encoding="utf-8"))
    for key in STATUS_REQUIRED_KEYS:
        assert key in raw


def test_start_meta_validation_and_cli_merge(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--meta K=V/JSON merge (later wins); invalid entries are exit 2 (SPEC §6, §13.33.5).

    Synchronous tests with zero sleeps/threads.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="start-meta-test")
    status_file = stage_dir / "STATUS.json"

    # Library dict meta is stored as-is
    st = stage.start(stage="meta-lib", pid=os.getpid(), meta={"k": "v", "n": 1})
    assert st["meta"] == {"k": "v", "n": 1}

    # CLI repeatable --meta merges in order, later wins, JSON types preserved
    capsys.readouterr()
    assert main([
        "--dir", str(stage_dir), "start", "--stage", "meta-cli",
        "--meta", "ticket=42",
        "--meta", '{"flag": true, "n": 3}',
        "--meta", "ticket=43",
    ]) == EXIT_OK
    capsys.readouterr()
    assert stage.status()["meta"] == {"ticket": "43", "flag": True, "n": 3}

    # Invalid --meta entries are BadArgs (exit 2) with no mutation
    before = status_file.read_text(encoding="utf-8")
    events_before = len(stage.events())
    capsys.readouterr()
    assert main([
        "--dir", str(stage_dir), "start", "--stage", "meta-bad",
        "--meta", "bareword",
    ]) == EXIT_BAD_ARGS
    assert status_file.read_text(encoding="utf-8") == before
    assert len(stage.events()) == events_before
    assert stage.status()["meta"] == {"ticket": "43", "flag": True, "n": 3}


def test_start_audit_event_shape(tmp_path: Path) -> None:
    """Each start appends one start event: stripped message + raw-args detail (SPEC §13.33.6)."""
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="start-audit-test")

    events_before = len(stage.events())
    st = stage.start(
        stage="  audit-stage  ",
        session_id="ses-audit",
        pid=424243,
        model="model-a",
        variant="variant-a",
    )
    events = stage.events()
    assert len(events) == events_before + 1
    last = events[-1]
    assert last["type"] == "start"
    assert last["type"] in EVENT_TYPES
    assert last["state"] == STATE_RUNNING
    assert last["stage_id"] == "audit-stage"
    assert last["stage_name"] == "audit-stage"
    assert last["attempt"] == st["attempt"]
    assert last["message"] == "audit-stage"
    assert last["ts"] == st["updated_at"]
    for key in EVENT_RECORD_KEYS:
        assert key in last

    # Detail carries the raw call arguments in START_DETAIL_KEYS order
    detail = last["detail"]
    assert tuple(detail.keys()) == START_DETAIL_KEYS
    assert set(detail.keys()) == set(START_DETAIL_KEYS)
    assert detail == {
        "stage_id": "audit-stage",
        "session_id": "ses-audit",
        "pid": 424243,
        "model": "model-a",
        "variant": "variant-a",
    }

    # Omitted pid: detail records null while STATUS records the resolved claimant
    st = stage.start(stage="audit-self")
    last = stage.events()[-1]
    assert last["detail"]["pid"] is None
    assert last["detail"]["stage_id"] == "audit-self"
    assert tuple(last["detail"].keys()) == START_DETAIL_KEYS
    assert st["pid"] == os.getpid()


def test_start_git_override_and_uninitialized(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Explicit git overrides stored verbatim; uninitialized start is exit 15 (SPEC §13.33.5).

    Synchronous tests with zero sleeps/threads.
    """
    from stage_signal import cli

    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="start-git-test")

    st = stage.start(
        stage="git-stage",
        pid=os.getpid(),
        git_head="head-explicit",
        git_branch="branch-explicit",
    )
    assert st["git_head"] == "head-explicit"
    assert st["git_branch"] == "branch-explicit"

    missing_dir = tmp_path / "nonexistent" / ".stage-signal"
    missing_stage = Stage(str(missing_dir))
    with pytest.raises(NotInitialized):
        missing_stage.start(stage="cannot start")

    capsys.readouterr()
    rc = cli.main(["--dir", str(missing_dir), "start", "--stage", "cannot start"])
    assert rc == EXIT_NOT_INITIALIZED


# =============================================================================
# 30. Blocked terminal contract freeze (SPEC §13.32, issue #159)
# =============================================================================


def test_blocked_constants_freeze() -> None:
    """BLOCKED_* constants match SPEC §13.32 and agree with transition matrix."""
    assert BLOCKED_ALLOWED_SOURCES == ("queued", "running", "blocked")
    assert isinstance(BLOCKED_ALLOWED_SOURCES, tuple)
    assert len(BLOCKED_ALLOWED_SOURCES) == 3
    assert STATE_QUEUED in BLOCKED_ALLOWED_SOURCES
    assert STATE_RUNNING in BLOCKED_ALLOWED_SOURCES
    assert STATE_BLOCKED in BLOCKED_ALLOWED_SOURCES
    for terminal in (STATE_DONE, STATE_FAILED):
        assert terminal not in BLOCKED_ALLOWED_SOURCES

    assert BLOCKED_DETAIL_KEYS == ()
    assert isinstance(BLOCKED_DETAIL_KEYS, tuple)
    assert len(BLOCKED_DETAIL_KEYS) == 0

    # Allowed sources agree with the frozen transition matrix (SPEC §13.19)
    assert tuple(allowed_source_states("blocked")) == BLOCKED_ALLOWED_SOURCES
    assert is_transition_allowed(STATE_QUEUED, "blocked") is True
    assert is_transition_allowed(STATE_RUNNING, "blocked") is True
    assert is_transition_allowed(STATE_BLOCKED, "blocked") is True
    assert transition_target(STATE_QUEUED, "blocked") == STATE_BLOCKED
    assert transition_target(STATE_RUNNING, "blocked") == STATE_BLOCKED
    assert transition_target(STATE_BLOCKED, "blocked") == STATE_BLOCKED

    for disallowed in (STATE_DONE, STATE_FAILED):
        assert is_transition_allowed(disallowed, "blocked") is False
        with pytest.raises(ValueError):
            transition_target(disallowed, "blocked")


def test_blocked_constants_exported_from_top_level() -> None:
    """Blocked freeze constants are exported from top-level stage_signal (SPEC §13.32)."""
    import stage_signal

    for name, expected in (
        ("BLOCKED_ALLOWED_SOURCES", BLOCKED_ALLOWED_SOURCES),
        ("BLOCKED_DETAIL_KEYS", BLOCKED_DETAIL_KEYS),
    ):
        assert hasattr(stage_signal, name), f"stage_signal missing {name!r}"
        assert name in stage_signal.__all__, f"{name!r} not in stage_signal.__all__"
        assert getattr(stage_signal, name) is expected


def test_blocked_allowed_sources_and_idempotence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Blocked succeeds from queued/running/blocked; done/failed refuse exit 3 (SPEC §13.32.2).

    Empty/whitespace-only reasons are BadArgs (exit 2) regardless of state (SPEC §13.32.3).
    Synchronous state-machine smoke with no sleeps/threads.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="blocked-sources-freeze")
    status_file = stage_dir / "STATUS.json"

    def assert_no_mutation(snapshot: str, event_count: int) -> None:
        assert status_file.read_text(encoding="utf-8") == snapshot
        assert len(stage.events()) == event_count

    # Empty/whitespace-only reason is BadArgs (exit 2) even from queued
    for bad_reason in ("", "   ", "\t \n"):
        with pytest.raises(BadArgsError, match="blocked requires non-empty --reason TEXT"):
            stage.blocked(bad_reason)
    capsys.readouterr()
    assert main(["--dir", str(stage_dir), "blocked", "--reason", "  "]) == EXIT_BAD_ARGS
    assert_no_mutation(status_file.read_text(encoding="utf-8"), 1)

    # Missing --reason flag is argparse exit 2
    with pytest.raises(SystemExit) as exc_info:
        main(["--dir", str(stage_dir), "blocked"])
    assert exc_info.value.code == EXIT_BAD_ARGS
    capsys.readouterr()
    assert_no_mutation(status_file.read_text(encoding="utf-8"), 1)

    # queued succeeds via library
    st = stage.blocked("queued blockage")
    assert st["state"] == STATE_BLOCKED
    assert st["error"]["reason"] == "queued blockage"

    # idempotent repeat from blocked succeeds and overwrites the reason
    st = stage.blocked("blocked again")
    assert st["state"] == STATE_BLOCKED
    assert st["error"]["reason"] == "blocked again"

    # done refuses with no mutation
    stage.start(stage="blocked-done-step", pid=os.getpid())
    stage.done(summary="finished")
    assert stage.status()["state"] == STATE_DONE
    before = status_file.read_text(encoding="utf-8")
    events_before = len(stage.events())
    with pytest.raises(IllegalTransition):
        stage.blocked("should not land")
    assert_no_mutation(before, events_before)
    capsys.readouterr()
    assert (
        main(["--dir", str(stage_dir), "blocked", "--reason", "should not land"])
        == EXIT_ILLEGAL_TRANSITION
    )
    assert_no_mutation(before, events_before)

    # failed refuses with no mutation
    stage.start(stage="blocked-failed-step", pid=os.getpid())
    stage.fail(reason="crashed")
    assert stage.status()["state"] == STATE_FAILED
    before = status_file.read_text(encoding="utf-8")
    events_before = len(stage.events())
    with pytest.raises(IllegalTransition):
        stage.blocked("should not land")
    assert_no_mutation(before, events_before)
    capsys.readouterr()
    assert (
        main(["--dir", str(stage_dir), "blocked", "--reason", "should not land"])
        == EXIT_ILLEGAL_TRANSITION
    )
    assert_no_mutation(before, events_before)

    # running succeeds via CLI
    stage.start(stage="blocked-running-step", pid=os.getpid())
    capsys.readouterr()
    assert main(["--dir", str(stage_dir), "blocked", "--reason", "cli blockage"]) == EXIT_OK
    out = capsys.readouterr().out
    assert out.startswith("blocked blocked blocked-running-step (attempt 1): cli blockage")
    assert stage.status()["state"] == STATE_BLOCKED


def test_blocked_reason_stored_verbatim(tmp_path: Path) -> None:
    """A valid reason is stored byte-for-byte (validation strips only for the check) (SPEC §13.32.3)."""
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="blocked-verbatim-freeze")
    stage.start(stage="blocked-verbatim-step", pid=os.getpid())

    reason = "  waiting on reviewer: docs kept  "
    st = stage.blocked(reason)
    assert st["error"]["reason"] == reason
    events = stage.events()
    assert events[-1]["type"] == "blocked"
    assert events[-1]["message"] == reason


def test_blocked_success_payload_and_audit_freeze(tmp_path: Path) -> None:
    """Successful blocked writes the ERROR_KEYS error object, result null, one blocked event (SPEC §13.32.4/13.32.5)."""
    from datetime import datetime as _datetime

    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="blocked-payload-freeze")
    stage.start(stage="blocked-payload-step", pid=os.getpid())
    stage_id_before = stage.status()["stage_id"]
    events_before = len(stage.events())

    st = stage.blocked("waiting on external dep")

    # State + error object cross-linked to ERROR_KEYS / ERROR_KINDS (§13.9, not redefined)
    assert st["state"] == STATE_BLOCKED
    assert set(st["error"].keys()) == set(ERROR_KEYS)
    assert tuple(st["error"].keys()) == ERROR_KEYS
    assert st["error"]["reason"] == "waiting on external dep"
    assert st["error"]["kind"] == STATE_BLOCKED
    assert st["error"]["kind"] in ERROR_KINDS
    finished = _datetime.fromisoformat(str(st["error"]["finished_at"]))
    assert finished.tzinfo is not None
    # result is null; identity fields preserved; updated_at bumped
    assert st["result"] is None
    assert st["stage_id"] == stage_id_before

    # Exactly one blocked event: reason passthrough message, empty detail
    events = stage.events()
    assert len(events) == events_before + 1
    last = events[-1]
    assert last["type"] == "blocked"
    assert last["type"] in EVENT_TYPES
    assert last["state"] == STATE_BLOCKED
    assert last["stage_id"] == stage_id_before
    assert last["message"] == "waiting on external dep"
    assert last["detail"] == {}
    assert tuple(last["detail"].keys()) == BLOCKED_DETAIL_KEYS
    assert last["ts"] == st["updated_at"]
    for key in EVENT_RECORD_KEYS:
        assert key in last

    # On-disk STATUS.json matches the returned snapshot payload
    raw = json.loads((stage_dir / STATUS_FILENAME).read_text(encoding="utf-8"))
    assert raw["state"] == STATE_BLOCKED
    assert raw["error"] == st["error"]
    assert raw["result"] is None


def test_blocked_uninitialized_library_and_cli_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Blocked raises NotInitialized (exit 15) when stage dir is uninitialized (SPEC §13.17, §13.32)."""
    missing_dir = tmp_path / "nonexistent" / ".stage-signal"
    missing_stage = Stage(str(missing_dir))
    with pytest.raises(NotInitialized) as exc_info:
        missing_stage.blocked("cannot block")
    assert exc_info.value.exit_code == EXIT_NOT_INITIALIZED == 15

    capsys.readouterr()
    rc = main(["--dir", str(missing_dir), "blocked", "--reason", "cannot block"])
    assert rc == EXIT_NOT_INITIALIZED == 15
    err_out = capsys.readouterr().err
    assert "stage-signal: error:" in err_out


# ---------------------------------------------------------------------------
# §13.34: Init bootstrap and idempotent setup contract freeze
# ---------------------------------------------------------------------------


def test_init_constants_exact_values() -> None:
    """INIT_* constants match SPEC §13.34 and contain the frozen canonical initial fields."""
    assert INIT_DETAIL_KEYS == ()
    assert isinstance(INIT_DETAIL_KEYS, tuple)
    assert len(INIT_DETAIL_KEYS) == 0

    assert isinstance(INIT_IDLE_STATUS_FIELDS, tuple)
    assert len(INIT_IDLE_STATUS_FIELDS) == 24
    assert len(set(INIT_IDLE_STATUS_FIELDS)) == 24

    # All 23 STATUS_REQUIRED_KEYS (§13.2) must be in INIT_IDLE_STATUS_FIELDS
    for key in STATUS_REQUIRED_KEYS:
        assert key in INIT_IDLE_STATUS_FIELDS

    # Plus pid_token (SPEC §13.34)
    assert "pid_token" in INIT_IDLE_STATUS_FIELDS

    expected_fields = (
        "schema_version",
        "project",
        "stage_id",
        "stage_name",
        "state",
        "attempt",
        "session_id",
        "pid",
        "pid_token",
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
    assert INIT_IDLE_STATUS_FIELDS == expected_fields


def test_init_constants_exported_from_top_level() -> None:
    """Init freeze constants are exported from top-level stage_signal (SPEC §13.34)."""
    import stage_signal

    for name, expected in (
        ("INIT_DETAIL_KEYS", INIT_DETAIL_KEYS),
        ("INIT_IDLE_STATUS_FIELDS", INIT_IDLE_STATUS_FIELDS),
    ):
        assert hasattr(stage_signal, name), f"stage_signal missing {name!r}"
        assert name in stage_signal.__all__, f"{name!r} not in stage_signal.__all__"
        assert getattr(stage_signal, name) is expected


def test_init_fresh_initialization_fields_and_event(tmp_path: Path) -> None:
    """Fresh init writes all 24 fields, creates directory layout, and appends init event (SPEC §13.34).

    Synchronous test with zero sleeps/threads.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))

    # Before init: directory does not exist, status raises NotInitialized
    assert not stage_dir.exists()
    with pytest.raises(NotInitialized):
        stage.status()

    # Fresh init
    status = stage.init(project="fresh-proj")

    # Directory and layout files created
    assert stage_dir.is_dir()
    assert (stage_dir / "STATUS.json").is_file()
    assert (stage_dir / "STATUS.md").is_file()
    assert (stage_dir / "events.jsonl").is_file()
    assert (stage_dir / "locks" / "stage.lock").is_file()

    # Exact field structure matches INIT_IDLE_STATUS_FIELDS
    assert tuple(status.keys()) == INIT_IDLE_STATUS_FIELDS + ("heartbeat_age_seconds",)
    raw_status = json.loads((stage_dir / "STATUS.json").read_text(encoding="utf-8"))
    assert tuple(raw_status.keys()) == INIT_IDLE_STATUS_FIELDS
    assert set(raw_status.keys()) == set(INIT_IDLE_STATUS_FIELDS)

    # Initial values match SPEC §13.34.4
    assert raw_status["schema_version"] == SCHEMA_VERSION
    assert raw_status["project"] == "fresh-proj"
    assert raw_status["stage_id"] is None
    assert raw_status["stage_name"] is None
    assert raw_status["state"] == STATE_QUEUED
    assert raw_status["attempt"] == 1
    assert raw_status["session_id"] is None
    assert raw_status["pid"] is None
    assert raw_status["pid_token"] is None
    assert raw_status["model"] is None
    assert raw_status["variant"] is None
    assert raw_status["repo_path"] == str(stage_dir.parent.resolve())
    assert raw_status["git_branch"] is None
    assert raw_status["git_head"] is None
    assert raw_status["started_at"] is None
    assert raw_status["updated_at"] is not None
    assert raw_status["heartbeat_at"] is None
    assert raw_status["heartbeat_note"] is None
    assert raw_status["result"] is None
    assert raw_status["error"] is None
    assert raw_status["artifacts"] == []
    assert raw_status["proof"] is None
    assert raw_status["notes"] == []
    assert raw_status["meta"] == {}

    # Audit event appended: exactly one 'init' event
    events = stage.events()
    assert len(events) == 1
    ev = events[0]
    assert ev["type"] == "init"
    assert ev["type"] in EVENT_TYPES
    assert ev["stage_id"] is None
    assert ev["stage_name"] is None
    assert ev["state"] == STATE_QUEUED
    assert ev["attempt"] == 1
    assert ev["message"] == "fresh-proj"
    assert ev["ts"] == raw_status["updated_at"]
    for key in EVENT_RECORD_KEYS:
        assert key in ev
    assert tuple(ev["detail"].keys()) == INIT_DETAIL_KEYS
    assert ev["detail"] == {}


def test_init_idempotent_preserve_all_states(tmp_path: Path) -> None:
    """Calling init on an already-initialized stage preserves state and never duplicates events (SPEC §13.34.2).

    Synchronous test with zero sleeps/threads.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))

    # 1. Queued state: init once, then init again
    st1 = stage.init(project="idempotent-test")
    raw1 = (stage_dir / "STATUS.json").read_text(encoding="utf-8")
    events1 = stage.events()
    assert len(events1) == 1

    # Second init on queued: must be a no-op preserve
    st2 = stage.init(project="different-ignored-project")
    raw2 = (stage_dir / "STATUS.json").read_text(encoding="utf-8")
    assert raw2 == raw1
    assert st2["project"] == "idempotent-test"  # preserved, not overwritten
    assert len(stage.events()) == 1  # no new event appended

    # 2. Running state: start a stage, then call init
    st_run = stage.start(stage="live-work", session_id="ses-123", pid=os.getpid())
    assert st_run["state"] == STATE_RUNNING
    events_run = stage.events()
    assert len(events_run) == 2  # init + start

    st_after_init = stage.init(project="another-ignored")
    assert st_after_init["state"] == STATE_RUNNING
    assert st_after_init["stage_name"] == "live-work"
    assert st_after_init["session_id"] == "ses-123"
    assert st_after_init["pid"] == os.getpid()
    assert len(stage.events()) == 2  # no new event

    # 3. Done state: mark done, then call init
    stage.done(summary="all completed")
    assert stage.status()["state"] == STATE_DONE
    events_done = stage.events()
    assert len(events_done) == 3

    st_done_init = stage.init()
    assert st_done_init["state"] == STATE_DONE
    assert st_done_init["result"]["summary"] == "all completed"
    assert len(stage.events()) == 3

    # 4. Blocked state
    stage.start(stage="retry-blocked")
    stage.blocked(reason="dependency missing")
    assert stage.status()["state"] == STATE_BLOCKED
    events_blocked = stage.events()

    st_blocked_init = stage.init()
    assert st_blocked_init["state"] == STATE_BLOCKED
    assert st_blocked_init["error"]["reason"] == "dependency missing"
    assert len(stage.events()) == len(events_blocked)

    # 5. Failed state
    stage.start(stage="retry-failed")
    stage.fail(reason="fatal crash")
    assert stage.status()["state"] == STATE_FAILED
    events_failed = stage.events()

    st_failed_init = stage.init()
    assert st_failed_init["state"] == STATE_FAILED
    assert st_failed_init["error"]["reason"] == "fatal crash"
    assert len(stage.events()) == len(events_failed)


def test_init_project_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Project resolution follows: explicit > STAGE_SIGNAL_PROJECT > dir inference (SPEC §13.34.3).

    Synchronous test with zero sleeps/threads.
    """
    # Precedence 1: Explicit project wins over env var and dir name
    dir1 = tmp_path / "workspace-a" / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_PROJECT", "env-project")
    st1 = Stage(str(dir1)).init(project="explicit-project")
    assert st1["project"] == "explicit-project"

    # Precedence 2: Environment variable wins over dir inference when explicit is omitted
    dir2 = tmp_path / "workspace-b" / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_PROJECT", "env-project")
    st2 = Stage(str(dir2)).init()
    assert st2["project"] == "env-project"

    # Precedence 3a: Directory inference (.stage-signal parent directory name) when env unset
    monkeypatch.delenv("STAGE_SIGNAL_PROJECT", raising=False)
    workspace_dir = tmp_path / "my-awesome-repo"
    dir3 = workspace_dir / ".stage-signal"
    dir3.mkdir(parents=True)
    st3 = Stage(str(dir3)).init()
    assert st3["project"] == "my-awesome-repo"

    # Precedence 3b: Directory inference (custom dir name outside .stage-signal uses cwd name)
    custom_dir = tmp_path / "custom-stage-dir"
    st4 = Stage(str(custom_dir)).init()
    assert st4["project"] == Path.cwd().name


def test_init_corrupt_status_fails_loudly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Corrupt STATUS.json raises CorruptStatusError and CLI exits 1 without clobbering (SPEC §13.34.2).

    Synchronous test with zero sleeps/threads.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="corrupt-test")

    # Corrupt STATUS.json
    status_file = stage_dir / "STATUS.json"
    status_file.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(CorruptStatusError):
        stage.init(project="rescue-attempt")

    # Ensure corruption was NOT clobbered
    assert status_file.read_text(encoding="utf-8") == "{not valid json"

    # CLI test: exits EXIT_ERROR (1) on corrupt status
    capsys.readouterr()
    rc = main(["--dir", str(stage_dir), "init"])
    assert rc == EXIT_ERROR


def test_init_cli_behavior(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """CLI init prints initialized message and exits 0 (SPEC §13.34.6).

    Synchronous test with zero sleeps/threads.
    """
    stage_dir = tmp_path / ".stage-signal"

    capsys.readouterr()
    rc = main(["--dir", str(stage_dir), "init", "--project", "cli-proj"])
    assert rc == EXIT_OK
    out = capsys.readouterr().out
    assert out.startswith("initialized cli-proj -> queued - (attempt 1)")

    # Subsequent CLI init call succeeds with exit 0 (idempotent)
    rc = main(["--dir", str(stage_dir), "init", "--project", "ignored"])
    assert rc == EXIT_OK
    out = capsys.readouterr().out
    assert out.startswith("initialized cli-proj -> queued - (attempt 1)")


# ---------------------------------------------------------------------------
# §13.35: Status read snapshot contract freeze
# ---------------------------------------------------------------------------


def test_status_snapshot_keys_exact_freeze() -> None:
    """STATUS_JSON_KEYS is exactly the 23 required keys + 2 derived read fields (SPEC §13.35.1)."""
    assert STATUS_JSON_KEYS == STATUS_REQUIRED_KEYS + (
        "needs_reclaim",
        "heartbeat_age_seconds",
    )
    assert isinstance(STATUS_JSON_KEYS, tuple)
    assert len(STATUS_JSON_KEYS) == 25
    assert len(set(STATUS_JSON_KEYS)) == 25
    assert STATUS_JSON_KEYS[-2:] == ("needs_reclaim", "heartbeat_age_seconds")


def test_status_read_pure_shared_lock_no_mutation(tmp_path: Path) -> None:
    """Stage.status() is a non-mutating shared-lock read returning a detached snapshot (SPEC §13.35.2).

    Synchronous test with zero sleeps/threads.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="status-pure-read-freeze")
    stage.start(stage="pure-step", pid=os.getpid())
    status_file = stage_dir / STATUS_FILENAME

    raw_before = status_file.read_text(encoding="utf-8")
    events_before = len(stage.events())

    first = stage.status()
    second = stage.status()

    # Derived keys live only on the snapshot, never on disk.
    assert "needs_reclaim" not in json.loads(raw_before)
    assert "heartbeat_age_seconds" not in json.loads(raw_before)
    for key in STATUS_JSON_KEYS:
        assert key in first, f"guaranteed key {key!r} missing from Stage.status()"

    # Reads mutate nothing: identical file bytes, identical event count.
    assert status_file.read_text(encoding="utf-8") == raw_before
    assert len(stage.events()) == events_before

    # Consecutive snapshots agree on every persisted field (age may tick between reads).
    for key in STATUS_REQUIRED_KEYS:
        assert second[key] == first[key]
    assert second["needs_reclaim"] == first["needs_reclaim"]
    assert isinstance(first["heartbeat_age_seconds"], float)

    # The returned snapshot is detached: caller mutation never reaches disk.
    first["state"] = "HACKED"
    first["needs_reclaim"] = "HACKED"
    assert status_file.read_text(encoding="utf-8") == raw_before
    assert stage.status()["state"] == STATE_RUNNING


def test_status_derived_fields_freeze(tmp_path: Path) -> None:
    """needs_reclaim + heartbeat_age_seconds semantics across states (SPEC §13.35.3).

    Synchronous test with zero sleeps/threads (staleness is crafted on disk, not waited out).
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="status-derived-freeze")

    # queued: no reclaim, null age.
    queued = stage.status()
    assert queued["needs_reclaim"] is False
    assert queued["heartbeat_age_seconds"] is None

    # healthy running (live claimant, fresh heartbeat): no reclaim, float age >= 0.
    stage.start(stage="derived-step", pid=os.getpid())
    healthy = stage.status()
    assert healthy["state"] == STATE_RUNNING
    assert healthy["needs_reclaim"] is False
    assert isinstance(healthy["heartbeat_age_seconds"], float)
    assert healthy["heartbeat_age_seconds"] >= 0.0

    # running with a confirmed-dead claimant: needs_reclaim True, age still a float.
    dead_proc = subprocess.Popen([sys.executable, "-c", "pass"])
    dead_proc.wait(timeout=5)
    stage.start(stage="derived-dead", pid=dead_proc.pid)
    dead = stage.status()
    assert dead["needs_reclaim"] is True
    assert isinstance(dead["heartbeat_age_seconds"], float)

    # running with a stale heartbeat (crafted on disk): STALE -> needs_reclaim True, age > threshold.
    status_file = stage_dir / STATUS_FILENAME
    raw = json.loads(status_file.read_text(encoding="utf-8"))
    raw["heartbeat_at"] = "2000-01-01T00:00:00+00:00"
    raw["pid"] = os.getpid()
    status_file.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    stale = stage.status()
    assert stale["state"] == STATE_RUNNING
    assert stale["needs_reclaim"] is True
    assert isinstance(stale["heartbeat_age_seconds"], float)
    assert stale["heartbeat_age_seconds"] > DEFAULT_STALE_THRESHOLD

    # running with an unparseable heartbeat: null age, UNPARSEABLE alone is not reclaim.
    raw["heartbeat_at"] = "not-a-timestamp"
    status_file.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    garbled = stage.status()
    assert garbled["heartbeat_age_seconds"] is None
    assert garbled["needs_reclaim"] is False

    # terminal states: null age even though heartbeat_at stays recorded; no reclaim.
    stage.start(stage="derived-terminal", pid=os.getpid())
    stage.done(summary="derived done")
    done = stage.status()
    assert done["heartbeat_at"] is not None
    assert done["heartbeat_age_seconds"] is None
    assert done["needs_reclaim"] is False

    stage.start(stage="derived-blocked", pid=os.getpid())
    stage.blocked(reason="derived blocked")
    assert stage.status()["heartbeat_at"] is not None
    assert stage.status()["heartbeat_age_seconds"] is None
    assert stage.status()["needs_reclaim"] is False

    stage.start(stage="derived-failed", pid=os.getpid())
    stage.fail(reason="derived failed")
    assert stage.status()["heartbeat_at"] is not None
    assert stage.status()["heartbeat_age_seconds"] is None
    assert stage.status()["needs_reclaim"] is False

    # idle queued after clear-terminal: null age, no reclaim.
    stage.clear_terminal()
    idle = stage.status()
    assert idle["state"] == STATE_QUEUED
    assert idle["heartbeat_age_seconds"] is None
    assert idle["needs_reclaim"] is False


def test_status_cli_human_and_json_shapes_freeze(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Human one-liner + updated/heartbeat/result/error lines vs --json object (SPEC §13.35.5).

    Synchronous test with zero sleeps/threads.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="status-shapes-freeze")

    def human() -> tuple[int, str]:
        capsys.readouterr()
        rc = main(["--dir", str(stage_dir), "status"])
        return rc, capsys.readouterr().out

    def as_json() -> tuple[int, dict[str, Any]]:
        capsys.readouterr()
        rc = main(["--dir", str(stage_dir), "status", "--json"])
        return rc, json.loads(capsys.readouterr().out)

    # queued: '-' stage slot, bare null heartbeat, no age suffix, no result/error.
    rc, out = human()
    assert rc == EXIT_QUEUED == state_exit_code("queued")
    lines = out.splitlines()
    assert lines[0] == "queued - (attempt 1)"
    assert lines[1].startswith("updated: ")
    assert "heartbeat: None" in lines[1]
    assert "(age " not in out
    assert "result:" not in out
    assert "error:" not in out
    rc, payload = as_json()
    assert rc == EXIT_QUEUED
    for key in STATUS_JSON_KEYS:
        assert key in payload, f"guaranteed key {key!r} missing from status --json [queued]"
    assert payload["state"] == "queued"

    # running: named slot, heartbeat with (age Ns) suffix, no result/error.
    stage.start(stage="shaped-step", pid=os.getpid())
    rc, out = human()
    assert rc == EXIT_RUNNING == state_exit_code("running")
    lines = out.splitlines()
    assert lines[0] == "running shaped-step (attempt 1)"
    assert "(age " in lines[1] and lines[1].rstrip().endswith(")")
    assert "result:" not in out
    assert "error:" not in out
    rc, payload = as_json()
    assert rc == EXIT_RUNNING
    for key in STATUS_JSON_KEYS:
        assert key in payload, f"guaranteed key {key!r} missing from status --json [running]"
    assert isinstance(payload["heartbeat_age_seconds"], float)
    assert payload["needs_reclaim"] is False

    # done: result line, bare heartbeat (no age suffix despite recorded timestamp).
    stage.done(summary="shaped done")
    rc, out = human()
    assert rc == EXIT_OK == state_exit_code("done")
    assert out.splitlines()[0] == "done shaped-step (attempt 1)"
    assert "(age " not in out
    assert '"summary": "shaped done"' in out
    assert "error:" not in out
    rc, payload = as_json()
    assert rc == EXIT_OK
    assert payload["heartbeat_age_seconds"] is None

    # blocked: error line with kind blocked.
    stage.start(stage="shaped-blocked", pid=os.getpid())
    stage.blocked(reason="shaped wait")
    rc, out = human()
    assert rc == EXIT_BLOCKED == state_exit_code("blocked")
    assert out.splitlines()[0].startswith("blocked shaped-blocked (attempt 1)")
    assert '"reason": "shaped wait"' in out
    assert '"kind": "blocked"' in out
    assert "result:" not in out

    # failed: error line with kind failed.
    stage.start(stage="shaped-failed", pid=os.getpid())
    stage.fail(reason="shaped crash")
    rc, out = human()
    assert rc == EXIT_FAILED == state_exit_code("failed")
    assert out.splitlines()[0].startswith("failed shaped-failed (attempt 1)")
    assert '"kind": "failed"' in out


def test_status_uninitialized_and_corrupt_freeze(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Status reads raise NotInitialized (exit 15) / CorruptStatusError (exit 1) (SPEC §13.35.4).

    Synchronous test with zero sleeps/threads.
    """
    missing_dir = tmp_path / "nonexistent" / ".stage-signal"
    missing_stage = Stage(str(missing_dir))
    with pytest.raises(NotInitialized) as exc_info:
        missing_stage.status()
    assert exc_info.value.exit_code == EXIT_NOT_INITIALIZED == 15

    for argv in (["status"], ["status", "--json"]):
        capsys.readouterr()
        rc = main(["--dir", str(missing_dir)] + argv)
        assert rc == EXIT_NOT_INITIALIZED == 15
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "stage-signal: error:" in captured.err
        assert "not initialized" in captured.err

    # Corrupt STATUS.json surfaces CorruptStatusError (exit 1) on both shapes.
    stage_dir = tmp_path / ".stage-signal"
    Stage(str(stage_dir)).init(project="status-corrupt-freeze")
    (stage_dir / STATUS_FILENAME).write_text("{not valid json", encoding="utf-8")
    with pytest.raises(CorruptStatusError) as exc_info:
        Stage(str(stage_dir)).status()
    assert exc_info.value.exit_code == EXIT_ERROR == 1
    for argv in (["status"], ["status", "--json"]):
        capsys.readouterr()
        assert main(["--dir", str(stage_dir)] + argv) == EXIT_ERROR
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "stage-signal: error:" in captured.err


def test_status_read_cross_links_freeze() -> None:
    """Status read reuses frozen exit, method-surface, and export symbols (SPEC §13.35.6)."""
    import stage_signal

    for state, code in (
        ("queued", EXIT_QUEUED),
        ("running", EXIT_RUNNING),
        ("done", EXIT_OK),
        ("blocked", EXIT_BLOCKED),
        ("failed", EXIT_FAILED),
    ):
        assert state_exit_code(state) == code
        assert STATE_EXIT_CODES[state] == code

    assert "status" in STAGE_PUBLIC_METHODS
    assert callable(Stage.status)

    for name in (
        "STATUS_JSON_KEYS",
        "STATE_EXIT_CODES",
        "state_exit_code",
        "NotInitialized",
        "DEFAULT_STALE_THRESHOLD",
    ):
        assert hasattr(stage_signal, name), f"stage_signal missing {name!r}"
        assert name in stage_signal.__all__, f"{name!r} not in stage_signal.__all__"
        assert name in PUBLIC_EXPORTS, f"{name!r} not in PUBLIC_EXPORTS"

    # §13.35 adds no export: the inventory stays at the 134 frozen symbols.
    assert len(PUBLIC_EXPORTS) == 134


# ---------------------------------------------------------------------------
# §13.36: Events read snapshot and tail contract freeze
# ---------------------------------------------------------------------------


def test_events_frozen_constants_and_symbols() -> None:
    """EVENT_RECORD_KEYS, EVENT_TYPES, EVENTS_DEFAULT_TAIL, EVENTS_FILENAME exact freeze (SPEC §13.36.1)."""
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
    assert isinstance(EVENT_RECORD_KEYS, tuple)
    assert len(EVENT_RECORD_KEYS) == 8
    assert len(set(EVENT_RECORD_KEYS)) == 8

    assert EVENT_TYPES == (
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
    assert isinstance(EVENT_TYPES, tuple)
    assert len(EVENT_TYPES) == 9
    assert len(set(EVENT_TYPES)) == 9

    assert EVENTS_DEFAULT_TAIL == 20
    assert isinstance(EVENTS_DEFAULT_TAIL, int)
    assert not isinstance(EVENTS_DEFAULT_TAIL, bool)

    assert EVENTS_FILENAME == "events.jsonl"


def test_events_pure_shared_lock_no_mutation(tmp_path: Path) -> None:
    """Stage.events() is a pure non-mutating read with detached deep-copy records (SPEC §13.36.2).

    Synchronous test with zero sleeps/threads.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="events-pure-read-freeze")
    stage.start(stage="step-events", pid=os.getpid())
    stage.heartbeat(note="first heartbeat")
    stage.note("intermediate note")

    events_file = stage_dir / EVENTS_FILENAME
    status_file = stage_dir / STATUS_FILENAME
    raw_events_before = events_file.read_text(encoding="utf-8")
    raw_status_before = status_file.read_text(encoding="utf-8")

    first = stage.events()
    second = stage.events(tail=2)
    third = stage.events(type="note")

    # Reads mutate nothing: file bytes are identical, event counts identical
    assert events_file.read_text(encoding="utf-8") == raw_events_before
    assert status_file.read_text(encoding="utf-8") == raw_status_before
    assert len(stage.events()) == 4

    # Returned snapshot is a detached deep copy
    first[0]["message"] = "TAMPERED_IN_MEMORY"
    first[0]["detail"]["hack"] = True
    assert stage.events()[0]["message"] != "TAMPERED_IN_MEMORY"
    assert "hack" not in stage.events()[0]["detail"]

    # Empty log returns empty list without raising
    empty_dir = tmp_path / "empty-events" / ".stage-signal"
    empty_stage = Stage(str(empty_dir))
    empty_stage.init(project="empty-log")
    (empty_dir / EVENTS_FILENAME).write_text("", encoding="utf-8")
    assert empty_stage.events() == []
    assert empty_stage.events(tail=10) == []
    assert empty_stage.events(type="init") == []
    (empty_dir / EVENTS_FILENAME).write_text("   \n\n  \t  \n", encoding="utf-8")
    assert empty_stage.events() == []


def test_events_return_shape_and_record_keys_freeze(tmp_path: Path) -> None:
    """Every event dictionary guarantees all 8 EVENT_RECORD_KEYS and tolerates unknown keys (SPEC §13.36.4).

    Synchronous test with zero sleeps/threads.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="events-shape-freeze")
    stage.start(stage="shape-step", pid=os.getpid(), session_id="ses-123")
    stage.heartbeat(note="tick")
    stage.note("checkpoint")
    stage.artifact("build/app.whl", label="wheel")
    stage.fail(reason="shape test fail")
    stage.clear_terminal()

    events = stage.events()
    assert len(events) == 7
    for ev in events:
        for key in EVENT_RECORD_KEYS:
            assert key in ev, f"required key {key!r} missing from event {ev!r}"
        assert ev["type"] in EVENT_TYPES
        assert isinstance(ev["ts"], str)
        assert isinstance(ev["state"], str)
        assert ev["state"] in STATES
        assert isinstance(ev["attempt"], int) and ev["attempt"] >= 1
        assert ev["message"] is None or isinstance(ev["message"], str)
        assert isinstance(ev["detail"], dict)
        assert ev["stage_id"] is None or isinstance(ev["stage_id"], str)
        assert ev["stage_name"] is None or isinstance(ev["stage_name"], str)

    # Tolerates unknown future keys per additive-only policy
    events_file = stage_dir / EVENTS_FILENAME
    line = json.dumps({
        "ts": "2026-09-18T12:00:00+00:00",
        "type": "note",
        "stage_id": "shape-step",
        "stage_name": "shape-step",
        "state": "running",
        "attempt": 1,
        "message": "future event",
        "detail": {},
        "unknown_future_field": "preserved",
    }) + "\n"
    with open(events_file, "a", encoding="utf-8") as fh:
        fh.write(line)

    tail_events = stage.events(tail=1)
    assert len(tail_events) == 1
    assert tail_events[0]["unknown_future_field"] == "preserved"


def test_events_ordering_and_filter_before_tail_freeze(tmp_path: Path) -> None:
    """Chronological oldest->newest order, filter-before-tail, and tail argument semantics (SPEC §13.36.3).

    Synchronous test with zero sleeps/threads.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="events-ordering-freeze")
    stage.start(stage="order-step", pid=os.getpid())

    # Seed an early failed event, followed by many heartbeats
    stage.fail(reason="early failure")
    stage.start(stage="order-retry", pid=os.getpid())
    for i in range(25):
        stage.heartbeat(note=f"beat-{i}")

    all_events = stage.events()
    assert len(all_events) == 29  # 1 init + 1 start + 1 fail + 1 start + 25 heartbeats

    # Chronological ordering (oldest -> newest): newest event is the last element
    assert all_events[-1]["type"] == "heartbeat"
    assert all_events[-1]["message"] == "beat-24"
    assert all_events[0]["type"] == "init"

    # Selected tail is also oldest -> newest of the selected slice
    tail5 = stage.events(tail=5)
    assert len(tail5) == 5
    assert [e["message"] for e in tail5] == ["beat-20", "beat-21", "beat-22", "beat-23", "beat-24"]

    # Filter-before-tail: early failed event is returned even when overall tail=1 would miss it
    tail1_overall = stage.events(tail=1)
    assert tail1_overall[0]["type"] == "heartbeat"

    failed_tail = stage.events(type="failed", tail=1)
    assert len(failed_tail) == 1
    assert failed_tail[0]["type"] == "failed"
    assert failed_tail[0]["message"] == "early failure"

    # Library tail=None and tail=0 return all events
    assert stage.events(tail=None) == all_events
    assert stage.events(tail=0) == all_events


def test_events_cli_human_and_json_shapes_freeze(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """CLI human one-liner vs --json array shape and default tail 20 (SPEC §13.36.6).

    Synchronous test with zero sleeps/threads.
    """
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="events-cli-freeze")
    stage.start(stage="cli-step", pid=os.getpid())
    for i in range(25):
        stage.note(f"line {i}\nmultiline note")

    # CLI default tail is EVENTS_DEFAULT_TAIL (20)
    capsys.readouterr()
    rc = main(["--dir", str(stage_dir), "events"])
    assert rc == EXIT_OK == 0
    human_lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(human_lines) == EVENTS_DEFAULT_TAIL == 20

    # Human one-liner format check: newlines replaced with spaces, ts/type/state/name columns
    last_human = human_lines[-1]
    assert "multiline note" in last_human
    assert "\n" not in last_human
    assert "note" in last_human
    assert "running" in last_human
    assert "cli-step" in last_human

    # CLI --tail 0 outputs all events
    capsys.readouterr()
    rc = main(["--dir", str(stage_dir), "events", "--tail", "0"])
    assert rc == EXIT_OK == 0
    all_human_lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(all_human_lines) == 27  # 1 init + 1 start + 25 notes

    # CLI --json outputs a single JSON array (not NDJSON)
    capsys.readouterr()
    rc = main(["--dir", str(stage_dir), "events", "--json", "--tail", "3"])
    assert rc == EXIT_OK == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert isinstance(payload, list)
    assert len(payload) == 3
    for ev in payload:
        assert set(EVENT_RECORD_KEYS).issubset(ev.keys())
    assert payload == stage.events(tail=3)

    # Empty match in --json produces [] (empty array)
    capsys.readouterr()
    rc = main(["--dir", str(stage_dir), "events", "--json", "--type", "blocked"])
    assert rc == EXIT_OK == 0
    assert json.loads(capsys.readouterr().out) == []

    # Empty log in human mode produces empty stdout
    empty_dir = tmp_path / "empty-cli" / ".stage-signal"
    Stage(str(empty_dir)).init(project="empty-cli-proj")
    (empty_dir / EVENTS_FILENAME).write_text("", encoding="utf-8")
    capsys.readouterr()
    rc = main(["--dir", str(empty_dir), "events"])
    assert rc == EXIT_OK == 0
    assert capsys.readouterr().out == ""


def test_events_uninitialized_corrupt_bad_args_freeze(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Preconditions: NotInitialized (exit 15), CorruptStatusError (exit 1), BadArgsError (exit 2) (SPEC §13.36.5).

    Synchronous test with zero sleeps/threads.
    """
    missing_dir = tmp_path / "missing" / ".stage-signal"
    missing_stage = Stage(str(missing_dir))

    # NotInitialized
    with pytest.raises(NotInitialized) as exc_info:
        missing_stage.events()
    assert exc_info.value.exit_code == EXIT_NOT_INITIALIZED == 15

    for argv in (["events"], ["events", "--json"]):
        capsys.readouterr()
        rc = main(["--dir", str(missing_dir)] + argv)
        assert rc == EXIT_NOT_INITIALIZED == 15
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "not initialized" in captured.err.lower() or "missing" in captured.err.lower()

    # CorruptStatusError: corrupt JSON line fail-closed
    stage_dir = tmp_path / ".stage-signal"
    stage = Stage(str(stage_dir))
    stage.init(project="corrupt-events-freeze")
    events_file = stage_dir / EVENTS_FILENAME
    events_file.write_text("{\"valid\": true}\n{bad json line\n", encoding="utf-8")

    with pytest.raises(CorruptStatusError) as exc_info:
        stage.events()
    assert exc_info.value.exit_code == EXIT_ERROR == 1
    assert "line 2" in str(exc_info.value)

    for argv in (["events"], ["events", "--json"]):
        capsys.readouterr()
        rc = main(["--dir", str(stage_dir)] + argv)
        assert rc == EXIT_ERROR == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "corrupt" in captured.err.lower()

    # BadArgsError: invalid type
    with pytest.raises(BadArgsError) as exc_info:
        stage.events(type="invalid_event_type")
    assert exc_info.value.exit_code == EXIT_BAD_ARGS == 2

    # BadArgsError: negative tail, boolean tail, non-int tail
    with pytest.raises(BadArgsError) as exc_info:
        stage.events(tail=-1)
    assert exc_info.value.exit_code == EXIT_BAD_ARGS == 2

    with pytest.raises(BadArgsError) as exc_info:
        stage.events(tail=True)  # type: ignore[arg-type]
    assert exc_info.value.exit_code == EXIT_BAD_ARGS == 2

    with pytest.raises(BadArgsError) as exc_info:
        stage.events(tail="5")  # type: ignore[arg-type]
    assert exc_info.value.exit_code == EXIT_BAD_ARGS == 2

    # CLI rejects bad args with exit code 2
    with pytest.raises(SystemExit) as exc_info_sys:
        main(["--dir", str(stage_dir), "events", "--type", "invalid_type"])
    assert exc_info_sys.value.code == EXIT_BAD_ARGS == 2

    with pytest.raises(SystemExit) as exc_info_sys:
        main(["--dir", str(stage_dir), "events", "--tail", "-5"])
    assert exc_info_sys.value.code == EXIT_BAD_ARGS == 2


def test_events_cross_links_freeze() -> None:
    """Events read reuses frozen exit, method-surface, and export symbols (SPEC §13.36.7)."""
    import stage_signal

    # Method in STAGE_PUBLIC_METHODS
    assert "events" in STAGE_PUBLIC_METHODS
    assert callable(Stage.events)

    # Symbols in stage_signal.__all__ and PUBLIC_EXPORTS
    for name in (
        "EVENT_RECORD_KEYS",
        "EVENT_TYPES",
        "EVENTS_DEFAULT_TAIL",
        "EVENTS_FILENAME",
        "EXIT_OK",
        "EXIT_ERROR",
        "EXIT_BAD_ARGS",
        "EXIT_NOT_INITIALIZED",
        "NotInitialized",
        "CorruptStatusError",
        "BadArgsError",
    ):
        assert hasattr(stage_signal, name), f"stage_signal missing {name!r}"
        assert name in stage_signal.__all__, f"{name!r} not in stage_signal.__all__"
        assert name in PUBLIC_EXPORTS, f"{name!r} not in PUBLIC_EXPORTS"

    # §13.36 adds no new export: the inventory stays at 134 frozen symbols
    assert len(PUBLIC_EXPORTS) == 134


