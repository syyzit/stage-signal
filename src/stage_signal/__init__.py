"""stage-signal public API."""

from .constants import (
    DEFAULT_STALE_THRESHOLD,
    SCHEMA_VERSION,
    STATES,
    SUPERVISE_DEFAULT_EVERY,
    TERMINAL_STATES,
    WARNING_CODE_DEAD_PID,
    WARNING_CODE_STALE_HEARTBEAT,
    WARNING_CODE_UNPARSEABLE_HEARTBEAT,
    state_exit_code,
)
from .errors import (
    BadArgsError,
    CorruptStatusError,
    IllegalTransition,
    NotInitialized,
    StageError,
    WaitTimeout,
)
from .stage import (
    Stage,
    verify_proof,
    wait_condition_met,
    want_matches,
    write_status_mirror,
)
from .store import StageStore, resolve_dir

__version__ = "0.1.6"

__all__ = [
    "__version__",
    "Stage",
    "StageError",
    "BadArgsError",
    "CorruptStatusError",
    "IllegalTransition",
    "NotInitialized",
    "WaitTimeout",
    "StageStore",
    "resolve_dir",
    "state_exit_code",
    "verify_proof",
    "wait_condition_met",
    "want_matches",
    "write_status_mirror",
    "SCHEMA_VERSION",
    "STATES",
    "TERMINAL_STATES",
    "DEFAULT_STALE_THRESHOLD",
    "SUPERVISE_DEFAULT_EVERY",
    "WARNING_CODE_DEAD_PID",
    "WARNING_CODE_STALE_HEARTBEAT",
    "WARNING_CODE_UNPARSEABLE_HEARTBEAT",
]
