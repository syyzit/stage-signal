"""stage-signal error hierarchy. Each error carries its CLI exit code."""

from __future__ import annotations

from typing import Any, Optional

from .constants import (
    EXIT_BAD_ARGS,
    EXIT_ERROR,
    EXIT_ILLEGAL_TRANSITION,
    EXIT_NOT_INITIALIZED,
    EXIT_WAIT_TIMEOUT,
)

__all__ = [
    "StageError",
    "BadArgsError",
    "IllegalTransition",
    "NotInitialized",
    "CorruptStatusError",
    "WaitTimeout",
]


class StageError(Exception):
    """Base error for stage-signal. Carries a stable ``exit_code``."""

    exit_code = EXIT_ERROR

    def __init__(self, message: str, *, detail: Optional[Any] = None) -> None:
        super().__init__(message)
        self.detail = detail


class BadArgsError(StageError):
    """Bad arguments or bad schema usage. Exit 2."""

    exit_code = EXIT_BAD_ARGS


class IllegalTransition(StageError):
    """Illegal state transition (incl. failed --require-proof gate). Exit 3."""

    exit_code = EXIT_ILLEGAL_TRANSITION


class NotInitialized(StageError):
    """Stage dir / STATUS.json missing. Exit 15."""

    exit_code = EXIT_NOT_INITIALIZED


class CorruptStatusError(StageError):
    """STATUS.json unreadable or failing validation. Exit 1."""

    exit_code = EXIT_ERROR


class WaitTimeout(StageError):
    """wait(1) timed out without the wanted condition. Exit 14."""

    exit_code = EXIT_WAIT_TIMEOUT

    def __init__(self, message: str, *, last_status: Optional[dict] = None) -> None:
        super().__init__(message)
        self.last_status = last_status
