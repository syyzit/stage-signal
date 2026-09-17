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

DOCTOR_SUMMARY_RECLAIM_NEEDED = "ATTENTION: running needs reclaim"


def state_exit_code(state: str) -> int:
    """Map a stage state to its observer exit code (SPEC §7)."""
    try:
        return STATE_EXIT_CODES[state]
    except KeyError:
        raise ValueError(f"unknown state: {state!r}") from None
