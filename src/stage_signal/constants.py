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
ENV_VARS = (ENV_DIR, ENV_PROJECT, ENV_PROOF_REF, ENV_STATUS_MIRROR)
DEFAULT_MIRROR_DIRNAME = ".orch"

WAIT_DEFAULT_TIMEOUT = 3600.0
WAIT_DEFAULT_POLL = 5.0
EVENTS_DEFAULT_TAIL = 20
DEFAULT_STALE_THRESHOLD = 300.0
SUPERVISE_DEFAULT_EVERY = 60.0

CLI_SUBCOMMANDS = (
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
DOCTOR_SUMMARY_OK_FORMAT = "OK: {state}"


def doctor_summary_ok(state: object) -> str:
    """Format the healthy doctor summary for *state* (SPEC §6, §13.22)."""
    return DOCTOR_SUMMARY_OK_FORMAT.format(state=state)


# Frozen supervise child-PID adoption + exit contract (SPEC §13.24)
SUPERVISE_ADOPT_MESSAGE_FORMAT = "adopted child pid {pid}"
SUPERVISE_ADOPT_DETAIL_KEYS = (
    "previous_pid",
    "pid",
    "pid_token",
)

SUPERVISE_DONE_SUMMARY_FORMAT = "command succeeded (exit 0): {cmd}"
SUPERVISE_FAIL_REASON_FORMAT = "command failed with exit code {code}: {cmd}"
SUPERVISE_SIGNAL_REASON_FORMAT = "command terminated by {signame}: {cmd}"

SUPERVISE_SIGNAL_EXIT_BASE = 128
SUPERVISE_EXIT_NOT_FOUND = 127
SUPERVISE_EXIT_PERMISSION_DENIED = 126


def supervise_adopt_message(pid: object) -> str:
    """Format the supervise adoption heartbeat message for child *pid* (SPEC §13.24)."""
    return SUPERVISE_ADOPT_MESSAGE_FORMAT.format(pid=pid)


def supervise_signal_exit(signum: int) -> int:
    """Map a terminating signal number to the supervise exit code 128 + SIGNUM (SPEC §13.24)."""
    return SUPERVISE_SIGNAL_EXIT_BASE + int(signum)


# Frozen reclaim fail-and-clear contract (SPEC §13.25)
RECLAIM_ALLOWED_SOURCES = (
    "running",
)

RECLAIM_FAILED_DETAIL_KEYS = (
    "reclaim",
    "keep_failed",
)

RECLAIM_CLEAR_TERMINAL_DETAIL_KEYS = (
    "keep_stage",
    "reclaim",
)

# Frozen clear-terminal reset + audit contract (SPEC §13.26)
CLEAR_TERMINAL_ALLOWED_SOURCES = (
    "done",
    "blocked",
    "failed",
    "queued",
)

CLEAR_TERMINAL_IDLE_RESET_FIELDS = (
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

CLEAR_TERMINAL_KEEP_STAGE_PRESERVED_FIELDS = (
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

CLEAR_TERMINAL_ALWAYS_CLEARED_FIELDS = (
    "result",
    "error",
    "proof",
)

CLEAR_TERMINAL_DETAIL_KEYS = (
    "keep_stage",
)

CLEAR_TERMINAL_MESSAGE_IDLE = "cleared to idle queued"
CLEAR_TERMINAL_MESSAGE_KEEP_STAGE = "cleared to queued"

# Frozen heartbeat contract (SPEC §13.27)
HEARTBEAT_ALLOWED_SOURCES = (
    "running",
)

HEARTBEAT_DETAIL_KEYS: tuple[str, ...] = ()

# Frozen artifact add contract (SPEC §13.29)
ARTIFACT_ALLOWED_SOURCES = (
    "running",
)

ARTIFACT_DETAIL_KEYS = (
    "path",
    "label",
)

# Frozen note progress contract (SPEC §13.28)
NOTE_ALLOWED_SOURCES = (
    "running",
)

NOTE_DETAIL_KEYS: tuple[str, ...] = ()

# Frozen done terminal contract (SPEC §13.30)
DONE_ALLOWED_SOURCES = (
    "queued",
    "running",
    "done",
)

DONE_ACCEPT_FAILURE_ALLOWED_SOURCES = (
    "failed",
)

DONE_DETAIL_KEYS = (
    "proof",
    "git_head",
    "accepted_failure",
)

# Frozen fail terminal contract (SPEC §13.31)
FAIL_ALLOWED_SOURCES = (
    "queued",
    "running",
    "failed",
)

FAIL_IF_DEAD_PID_ALLOWED_SOURCES = (
    "queued",
    "running",
    "failed",
)

FAIL_IF_NEEDS_RECLAIM_ALLOWED_SOURCES = (
    "running",
)

FAIL_DETAIL_KEYS: tuple[str, ...] = ()

# Frozen blocked terminal contract (SPEC §13.32)
BLOCKED_ALLOWED_SOURCES = (
    "queued",
    "running",
    "blocked",
)

BLOCKED_DETAIL_KEYS: tuple[str, ...] = ()
# Frozen start/claim-running contract (SPEC §13.33)
START_ALLOWED_SOURCES = (
    "queued",
    "running",
    "done",
    "blocked",
    "failed",
)

START_DETAIL_KEYS = (
    "stage_id",
    "session_id",
    "pid",
    "model",
    "variant",
)

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

ARTIFACT_ENTRY_KEYS = ("path", "label", "added_at")
NOTE_ENTRY_KEYS = ("text", "added_at")
RESULT_KEYS = ("summary", "git_head", "finished_at")
ERROR_KEYS = ("reason", "kind", "finished_at")
ERROR_KINDS = (STATE_BLOCKED, STATE_FAILED)

PROOF_KEYS = ("tool", "ref", "verified")
PROOF_REQUIRED_KEYS = PROOF_KEYS
PROOF_VERIFIED_VALUES = (None, "file", "verify")

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

WAIT_OUTCOME_MET = "met"
WAIT_OUTCOME_MISMATCH = "mismatch"
WAIT_OUTCOME_TIMEOUT = "timeout"
WAIT_OUTCOMES = (
    WAIT_OUTCOME_MET,
    WAIT_OUTCOME_MISMATCH,
    WAIT_OUTCOME_TIMEOUT,
)

WAIT_CHOICES = ("done", "blocked", "failed", "terminal")
WAIT_WANT_NEEDS_RECLAIM = "needs_reclaim"

STATUS_MD_TITLE = "# stage-signal STATUS"
STATUS_MD_REQUIRED_HEADINGS = (
    "# stage-signal STATUS",
    "state:",
    "stage:",
    "stage_id:",
    "attempt:",
    "project:",
    "updated:",
    "heartbeat:",
)
STATUS_MD_OPTIONAL_HEADINGS = (
    "heartbeat_note:",
    "result:",
    "error:",
)
STATUS_MD_HEADINGS = STATUS_MD_REQUIRED_HEADINGS + STATUS_MD_OPTIONAL_HEADINGS

STAGE_PUBLIC_METHODS = (
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


def state_exit_code(state: str) -> int:
    """Map a stage state to its observer exit code (SPEC §6, §7, §13.16)."""
    try:
        return STATE_EXIT_CODES[state]
    except KeyError:
        raise ValueError(f"unknown state: {state!r}") from None


# Allowed lifecycle transition matrix under schema_version 1 (SPEC §13.19)
ALLOWED_TRANSITIONS: dict[tuple[str, str], str] = {
    # start: allowed from any state -> running (SPEC §4.2, §13.19)
    (STATE_QUEUED, "start"): STATE_RUNNING,
    (STATE_RUNNING, "start"): STATE_RUNNING,
    (STATE_DONE, "start"): STATE_RUNNING,
    (STATE_BLOCKED, "start"): STATE_RUNNING,
    (STATE_FAILED, "start"): STATE_RUNNING,

    # heartbeat, note, artifact: allowed only from running -> running (SPEC §4.3, §4.4, §13.19)
    (STATE_RUNNING, "heartbeat"): STATE_RUNNING,
    (STATE_RUNNING, "note"): STATE_RUNNING,
    (STATE_RUNNING, "artifact"): STATE_RUNNING,

    # done: allowed from queued, running, or idempotent done -> done (SPEC §4.5, §13.19)
    (STATE_QUEUED, "done"): STATE_DONE,
    (STATE_RUNNING, "done"): STATE_DONE,
    (STATE_DONE, "done"): STATE_DONE,

    # done --accept-failure: allowed only from failed -> done (SPEC §4.5, §13.19)
    (STATE_FAILED, "done --accept-failure"): STATE_DONE,
    (STATE_FAILED, "done_accept_failure"): STATE_DONE,

    # blocked: allowed from queued, running, or idempotent blocked -> blocked (SPEC §4.6, §13.19)
    (STATE_QUEUED, "blocked"): STATE_BLOCKED,
    (STATE_RUNNING, "blocked"): STATE_BLOCKED,
    (STATE_BLOCKED, "blocked"): STATE_BLOCKED,

    # fail: allowed from queued, running, or idempotent failed -> failed (SPEC §4.6, §13.19)
    (STATE_QUEUED, "fail"): STATE_FAILED,
    (STATE_RUNNING, "fail"): STATE_FAILED,
    (STATE_FAILED, "fail"): STATE_FAILED,
    (STATE_QUEUED, "fail --if-dead-pid"): STATE_FAILED,
    (STATE_RUNNING, "fail --if-dead-pid"): STATE_FAILED,
    (STATE_FAILED, "fail --if-dead-pid"): STATE_FAILED,
    (STATE_RUNNING, "fail --if-needs-reclaim"): STATE_FAILED,

    # clear-terminal: allowed from terminal states or queued -> idle queued (SPEC §4.8, §13.19)
    (STATE_DONE, "clear-terminal"): STATE_QUEUED,
    (STATE_BLOCKED, "clear-terminal"): STATE_QUEUED,
    (STATE_FAILED, "clear-terminal"): STATE_QUEUED,
    (STATE_QUEUED, "clear-terminal"): STATE_QUEUED,
    (STATE_DONE, "clear_terminal"): STATE_QUEUED,
    (STATE_BLOCKED, "clear_terminal"): STATE_QUEUED,
    (STATE_FAILED, "clear_terminal"): STATE_QUEUED,
    (STATE_QUEUED, "clear_terminal"): STATE_QUEUED,

    # reclaim: running with needs_reclaim -> failed [+ optional clear_terminal] (SPEC §4.7, §13.19)
    (STATE_RUNNING, "reclaim"): STATE_QUEUED,
    (STATE_RUNNING, "reclaim --keep-failed"): STATE_FAILED,
    (STATE_RUNNING, "reclaim_keep_failed"): STATE_FAILED,
}


def is_transition_allowed(from_state: str, command: str) -> bool:
    """Check whether a (from_state, command) transition edge is legal under schema_version 1 (SPEC §13.19)."""
    return (from_state, command) in ALLOWED_TRANSITIONS


def transition_target(from_state: str, command: str) -> str:
    """Return the resulting target state for a legal transition, or raise ValueError if unknown/illegal (SPEC §13.19)."""
    try:
        return ALLOWED_TRANSITIONS[(from_state, command)]
    except KeyError:
        raise ValueError(
            f"illegal transition from state {from_state!r} via command {command!r}"
        ) from None


def allowed_source_states(command: str) -> tuple[str, ...]:
    """Return tuple of allowed source states for command from ALLOWED_TRANSITIONS (SPEC §13.19)."""
    states: list[str] = []
    for from_state, cmd in ALLOWED_TRANSITIONS:
        if cmd == command and from_state not in states:
            states.append(from_state)
    return tuple(states)


# Canonical public export inventory under schema_version 1 (SPEC §13.21)
PUBLIC_EXPORTS: tuple[str, ...] = (
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

