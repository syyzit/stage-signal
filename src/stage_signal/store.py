"""Locked atomic storage for stage-signal: STATUS.json, events.jsonl, STATUS.md."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional

try:
    import fcntl  # POSIX
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None  # type: ignore[assignment]

from .constants import (
    DEFAULT_DIR_NAME,
    ENV_DIR,
    EVENTS_FILENAME,
    LOCKS_DIRNAME,
    LOCK_FILENAME,
    STATUS_FILENAME,
    STATUS_MD_FILENAME,
)
from .errors import CorruptStatusError, NotInitialized


def resolve_dir(explicit: Optional[str | os.PathLike] = None) -> Path:
    """Resolve the stage dir: explicit > $STAGE_SIGNAL_DIR > .stage-signal.

    Always returns an absolute path so project inference and mirrors
    behave identically for relative and absolute inputs.
    """
    if explicit is not None:
        raw = Path(explicit).expanduser()
    else:
        env = os.environ.get(ENV_DIR)
        raw = Path(env).expanduser() if env else Path(DEFAULT_DIR_NAME)
    return raw if raw.is_absolute() else Path.cwd() / raw


def now_iso() -> str:
    """Current local time as ISO-8601 with timezone offset."""
    return datetime.now().astimezone().isoformat()


class StageStore:
    """Filesystem paths + locking + atomic IO for one stage dir."""

    def __init__(self, dir: Optional[str | os.PathLike] = None) -> None:
        self.dir = resolve_dir(dir)
        self.status_path = self.dir / STATUS_FILENAME
        self.status_md_path = self.dir / STATUS_MD_FILENAME
        self.events_path = self.dir / EVENTS_FILENAME
        self.locks_dir = self.dir / LOCKS_DIRNAME
        self.lock_path = self.locks_dir / LOCK_FILENAME

    # -- setup ----------------------------------------------------------

    def ensure_layout(self) -> None:
        """Create dir tree (idempotent). Does not touch STATUS.json."""
        self.locks_dir.mkdir(parents=True, exist_ok=True)
        self.lock_path.touch(exist_ok=True)
        if not self.events_path.exists():
            self.events_path.touch()

    @property
    def is_initialized(self) -> bool:
        return self.status_path.is_file()

    def require_initialized(self) -> None:
        if not self.is_initialized:
            raise NotInitialized(
                f"not initialized: {self.status_path} missing "
                f"(run 'stage-signal init --dir {self.dir}')"
            )

    # -- locking --------------------------------------------------------

    @contextlib.contextmanager
    def locked(self, exclusive: bool = True) -> Iterator[None]:
        """Hold a lock on locks/stage.lock for the duration of the block."""
        self.ensure_layout()
        with open(self.lock_path, "a+b") as fh:
            if fcntl is not None:
                op = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
                fcntl.flock(fh.fileno(), op)
                try:
                    yield
                finally:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            else:  # pragma: no cover - non-POSIX: no inter-process lock
                yield

    # -- STATUS.json IO -------------------------------------------------

    def read_status(self) -> dict[str, Any]:
        """Read + validate STATUS.json. Raises NotInitialized/CorruptStatusError."""
        self.require_initialized()
        try:
            raw = self.status_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise CorruptStatusError(f"cannot read {self.status_path}: {exc}") from exc
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CorruptStatusError(
                f"corrupt STATUS.json ({self.status_path}): {exc}"
            ) from exc
        validate_status(data, source=str(self.status_path))
        return data

    def write_status(self, data: dict[str, Any]) -> None:
        """Atomically rewrite STATUS.json (temp file + os.replace)."""
        validate_status(data, source=str(self.status_path))
        self.dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(self.dir), prefix=".STATUS.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.status_path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    # -- events ---------------------------------------------------------

    def append_event(self, event: dict[str, Any]) -> None:
        """Append one JSON object line to events.jsonl (fsync'd)."""
        self.ensure_layout()
        line = json.dumps(event, ensure_ascii=False) + "\n"
        with open(self.events_path, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            with contextlib.suppress(OSError):
                os.fsync(fh.fileno())

    def read_events(self) -> list[dict[str, Any]]:
        """Read all events (skips blank lines; corrupt lines raise)."""
        self.require_initialized()
        events: list[dict[str, Any]] = []
        try:
            text = self.events_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise CorruptStatusError(f"cannot read {self.events_path}: {exc}") from exc
        for lineno, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise CorruptStatusError(
                    f"corrupt {self.events_path} line {lineno}: {exc}"
                ) from exc
        return events

    # -- human mirror ---------------------------------------------------

    def write_status_md(self, status: dict[str, Any]) -> None:
        """Best-effort human mirror. Never raises (SPEC: never normative)."""
        try:
            body = render_status_md(status)
            self.dir.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                dir=str(self.dir), prefix=".STATUS-md.", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(body)
                    fh.flush()
                    with contextlib.suppress(OSError):
                        os.fsync(fh.fileno())
                os.replace(tmp, self.status_md_path)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
                raise
        except Exception:
            contextlib.suppress(Exception)


def validate_status(data: Any, *, source: str = "STATUS.json") -> None:
    """Validate a STATUS object. Raises CorruptStatusError on any problem."""
    if not isinstance(data, dict):
        raise CorruptStatusError(f"{source}: top level must be an object")
    # schema_version is normative; unknown versions are rejected, exit 1.
    if data.get("schema_version") != 1:
        raise CorruptStatusError(
            f"{source}: unsupported schema_version "
            f"{data.get('schema_version')!r} (expected 1)"
        )
    from .constants import STATES  # local import: avoid cycle at module load

    required = (
        "schema_version", "project", "stage_id", "stage_name", "state",
        "attempt", "session_id", "pid", "model", "variant", "repo_path",
        "git_branch", "git_head", "started_at", "updated_at", "heartbeat_at",
        "heartbeat_note", "result", "error", "artifacts", "proof",
        "notes", "meta",
    )
    missing = [k for k in required if k not in data]
    if missing:
        raise CorruptStatusError(f"{source}: missing keys: {', '.join(missing)}")
    if data["state"] not in STATES:
        raise CorruptStatusError(f"{source}: unknown state {data['state']!r}")
    if not isinstance(data["attempt"], int) or data["attempt"] < 1:
        raise CorruptStatusError(f"{source}: attempt must be int >= 1")
    if not isinstance(data["artifacts"], list):
        raise CorruptStatusError(f"{source}: artifacts must be a list")
    if not isinstance(data["notes"], list):
        raise CorruptStatusError(f"{source}: notes must be a list")
    if not isinstance(data["meta"], dict):
        raise CorruptStatusError(f"{source}: meta must be an object")


def render_status_md(status: dict[str, Any]) -> str:
    """Render the human-readable STATUS.md mirror."""
    lines = [
        "# stage-signal STATUS",
        "",
        f"state: {status.get('state')}",
        f"stage: {status.get('stage_name')}",
        f"stage_id: {status.get('stage_id')}",
        f"attempt: {status.get('attempt')}",
        f"project: {status.get('project')}",
        f"updated: {status.get('updated_at')}",
        f"heartbeat: {status.get('heartbeat_at')}",
    ]
    if status.get("heartbeat_note"):
        lines.append(f"heartbeat_note: {status['heartbeat_note']}")
    if status.get("result"):
        lines.append(f"result: {json.dumps(status['result'], ensure_ascii=False)}")
    if status.get("error"):
        lines.append(f"error: {json.dumps(status['error'], ensure_ascii=False)}")
    lines.append("")
    return "\n".join(lines)
