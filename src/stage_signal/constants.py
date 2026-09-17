"""stage-signal constants: schema version, states, exit codes, paths."""

from __future__ import annotations

SCHEMA_VERSION = 1

STATE_QUEUED = "queued"
STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_BLOCKED = "blocked"
STATE_FAILED = "failed"

STATES = (STATE_QUEUED, STATE_RUNNING, STATE_DONE, STATE_BLOCKED, STATE_FAILED)
TERMINAL_STATES = (STATE_DONE, STATE_BLOCKED, STATE_FAILED)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_BAD_ARGS = 2
EXIT_ILLEGAL_TRANSITION = 3
EXIT_RUNNING = 10
EXIT_BLOCKED = 11
EXIT_FAILED = 12
EXIT_QUEUED = 13
EXIT_WAIT_TIMEOUT = 14
EXIT_NOT_INITIALIZED = 15

EXIT_CODES = (
    EXIT_OK,
    EXIT_ERROR,
    EXIT_BAD_ARGS,
    EXIT_ILLEGAL_TRANSITION,
    EXIT_RUNNING,
    EXIT_BLOCKED,
    EXIT_FAILED,
    EXIT_QUEUED,
    EXIT_WAIT_TIMEOUT,
    EXIT_NOT_INITIALIZED,
)

STATE_EXIT_CODES = {
    STATE_RUNNING: EXIT_RUNNING,
    STATE_BLOCKED: EXIT_BLOCKED,
    STATE_FAILED: EXIT_FAILED,
    STATE_QUEUED: EXIT_QUEUED,
    STATE_DONE: EXIT_OK,
}

DEFAULT_DIR_NAME = ".stage-signal"
STATUS_FILENAME = "STATUS.json"
STATUS_MD_FILENAME = "STATUS.md"
EVENTS_FILENAME = "events.jsonl"
LOCKS_DIRNAME = "locks"
LOCK_FILENAME = "stage.lock"

ENV_DIR = "STAGE_SIGNAL_DIR"
ENV_PROJECT = "STAGE_SIGNAL_PROJECT"
ENV_PROOF_REF = "STAGE_SIGNAL_PROOF_REF"
ENV_STATUS_MIRROR = "STAGE_SIGNAL_STATUS_MIRROR"
DEFAULT_MIRROR_DIRNAME = ".orch"

WAIT_DEFAULT_TIMEOUT = 3600.0
WAIT_DEFAULT_POLL = 5.0
EVENTS_DEFAULT_TAIL = 20
DEFAULT_STALE_THRESHOLD = 300.0
SUPERVISE_DEFAULT_EVERY = 60.0

EVENT_TYPES = (
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

MAX_NOTES = 200

WARNING_CODE_STALE_HEARTBEAT = "STALE_HEARTBEAT"
WARNING_CODE_DEAD_PID = "DEAD_PID"
WARNING_CODE_UNPARSEABLE_HEARTBEAT = "UNPARSEABLE_HEARTBEAT"

WARNING_CODES = (
    WARNING_CODE_STALE_HEARTBEAT,
    WARNING_CODE_DEAD_PID,
    WARNING_CODE_UNPARSEABLE_HEARTBEAT,
)

WARNING_KEYS = (
    "code",
    "message",
    "detail",
)
WARNING_REQUIRED_KEYS = WARNING_KEYS
DOCTOR_WARNING_KEYS = WARNING_KEYS

DOCTOR_SUMMARY_RECLAIM_NEEDED = "ATTENTION: running needs reclaim"

# Frozen schema_version 1 key sets (SPEC §13)
STATUS_REQUIRED_KEYS = (
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

STATUS_JSON_KEYS = STATUS_REQUIRED_KEYS + (
    "needs_reclaim",
    "heartbeat_age_seconds",
)

DOCTOR_JSON_KEYS = (
    "ok",
    "needs_reclaim",
    "state",
    "problems",
    "warnings",
    "status",
    "summary",
)

EVENT_RECORD_KEYS = (
    "ts",
    "type",
    "stage_id",
    "stage_name",
    "state",
    "attempt",
    "message",
    "detail",
)

WAIT_JSON_KEYS = (
    "outcome",
    "wanted",
    "observed_state",
    "state",
    "exit_code",
    "timeout",
    "stage_id",
    "dir",
    "reason",
    "needs_reclaim",
    "status",
)


def state_exit_code(state: str) -> int:
    """Map a stage state to its observer exit code (SPEC §7)."""
    try:
        return STATE_EXIT_CODES[state]
    except KeyError:
        raise ValueError(f"unknown state: {state!r}") from None
