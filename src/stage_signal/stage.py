"""stage-signal core library: the Stage lifecycle API (SPEC §§3-5, 8-11)."""

from __future__ import annotations

import copy
import errno
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional
import time

from .constants import (
    DEFAULT_MIRROR_DIRNAME,
    ENV_STATUS_MIRROR,
    ENV_PROJECT,
    ENV_PROOF_REF,
    MAX_NOTES,
    SCHEMA_VERSION,
    STATE_BLOCKED,
    STATE_DONE,
    STATE_FAILED,
    STATE_QUEUED,
    STATE_RUNNING,
    TERMINAL_STATES,
    state_exit_code,
)
from .errors import (
    BadArgsError,
    IllegalTransition,
    NotInitialized,
    WaitTimeout,
)
from .store import StageStore, now_iso

__all__ = [
    "Stage",
    "state_exit_code",
    "want_matches",
    "verify_proof",
    "write_status_mirror",
]

WAIT_CHOICES = ("done", "blocked", "failed", "terminal")


def want_matches(want: str, state: str) -> bool:
    """True when *state* satisfies a `wait --state` want value."""
    if want == "terminal":
        return state in TERMINAL_STATES
    return state == want


def verify_proof(ref: Optional[str] = None) -> dict[str, Any]:
    """Verify a proof reference for `done --require-proof` (SPEC §9).

    Gate order: existing non-empty file wins; else delegate to
    `agent-done-or-not verify --ref R` when that binary is on PATH;
    otherwise fail closed with IllegalTransition (exit 3).
    """
    ref = ref or os.environ.get(ENV_PROOF_REF)
    if not ref:
        raise IllegalTransition(
            "--require-proof needs --proof-ref REF or "
            f"${ENV_PROOF_REF} (no proof reference given)"
        )
    candidate = Path(ref).expanduser()
    if candidate.is_file():
        try:
            if candidate.stat().st_size > 0:
                return {"tool": "agent-done-or-not", "ref": ref, "verified": "file"}
        except OSError:
            pass
        raise IllegalTransition(f"proof gate failed: file {ref!r} is empty/unreadable")
    binary = shutil.which("agent-done-or-not")
    if binary is not None:
        try:
            proc = subprocess.run(
                [binary, "verify", "--ref", ref],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise IllegalTransition(
                f"proof gate failed: agent-done-or-not error: {exc}"
            ) from exc
        if proc.returncode == 0:
            return {"tool": "agent-done-or-not", "ref": ref, "verified": "verify"}
        raise IllegalTransition(
            f"proof gate failed: agent-done-or-not verify exited "
            f"{proc.returncode}: {(proc.stderr or proc.stdout or '').strip()}"
        )
    raise IllegalTransition(
        f"proof gate failed: {ref!r} is not an existing file and "
        "agent-done-or-not is not on PATH (fail closed)"
    )


def write_status_mirror(
    stage_dir: Path, status: dict[str, Any], *, repo_root: Optional[Path] = None
) -> Optional[Path]:
    """Best-effort status mirror into `<repo>/.orch/` (SPEC §10). Never raises.

    Returns the mirrored STATUS.md path, or None when skipped/failed.
    """
    try:
        root = repo_root
        if root is None:
            # <repo>/.stage-signal -> <repo>
            if stage_dir.name == ".stage-signal" and stage_dir.parent.is_dir():
                root = stage_dir.parent
            else:
                root = Path.cwd()
        mirror = root / DEFAULT_MIRROR_DIRNAME
        mirror.mkdir(parents=True, exist_ok=True)
        lines = [
            "# stage-signal status mirror",
            f"state: {status.get('state')}",
            f"stage: {status.get('stage_name')}",
            f"stage_id: {status.get('stage_id')}",
            f"project: {status.get('project')}",
            f"updated: {status.get('updated_at')}",
            f"source: stage-signal {stage_dir}",
            "",
        ]
        (mirror / "STATUS.md").write_text("\n".join(lines), encoding="utf-8")
        if status.get("state") == STATE_DONE:
            (mirror / "DONE").write_text(
                f"done: {status.get('stage_name')} "
                f"{status.get('updated_at')}\n",
                encoding="utf-8",
            )
        return mirror / "STATUS.md"
    except Exception:
        return None


def _status_mirror_enabled(explicit: Optional[bool]) -> bool:
    if explicit is not None:
        return explicit
    return os.environ.get(ENV_STATUS_MIRROR, "").strip().lower() in (
        "1", "true", "yes", "on",
    )


class Stage:
    """One stage lifecycle bound to a stage dir.

    Usage::

        with Stage.open(".stage-signal") as s:
            s.init(project="myproj")
            s.start(stage="m1", session_id="ses_1")
            s.heartbeat(note="tests green")
            s.done(summary="merged abc123")

    All mutations are internally locked; the context-manager form only
    provides scoped usage (no persistent lock is held between calls).
    """

    def __init__(self, dir: Optional[str | os.PathLike] = None) -> None:
        self._store = StageStore(dir)

    # -- construction --------------------------------------------------

    @classmethod
    def open(cls, dir: Optional[str | os.PathLike] = None) -> "Stage":
        """Create a Stage bound to *dir* (usable as a context manager)."""
        return cls(dir)

    def __enter__(self) -> "Stage":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    @property
    def dir(self) -> Path:
        return self._store.dir

    # -- internal mutation helper --------------------------------------

    def _mutate(
        self,
        event_type: str,
        transform,
        *,
        message: Optional[str] = None,
        detail: Optional[dict[str, Any]] = None,
        do_mirror: Optional[bool] = None,
    ) -> dict[str, Any]:
        store = self._store
        with store.locked(exclusive=True):
            status = store.read_status()
            new_status = transform(copy.deepcopy(status))
            new_status["updated_at"] = now_iso()
            store.write_status(new_status)
            store.append_event(
                {
                    "ts": new_status["updated_at"],
                    "type": event_type,
                    "stage_id": new_status.get("stage_id"),
                    "stage_name": new_status.get("stage_name"),
                    "state": new_status.get("state"),
                    "attempt": new_status.get("attempt"),
                    "message": message,
                    "detail": detail or {},
                }
            )
            store.write_status_md(new_status)
            if _status_mirror_enabled(do_mirror) and event_type in (
                "start", "done", "blocked", "failed",
            ):
                mirrored = write_status_mirror(store.dir, new_status)
                if mirrored is None:
                    print(
                        "stage-signal: warning: status mirror failed",
                        file=sys.stderr,
                    )
            return copy.deepcopy(new_status)

    # -- lifecycle ------------------------------------------------------

    def init(self, project: Optional[str] = None) -> dict[str, Any]:
        """Create the stage dir + queued STATUS (idempotent, SPEC §4.1)."""
        store = self._store
        with store.locked(exclusive=True):
            if store.is_initialized:
                # Validate: fail loudly on corruption rather than masking it.
                return copy.deepcopy(store.read_status())
            project_name = (
                project
                or os.environ.get(ENV_PROJECT)
                or _default_project(store.dir)
            )
            ts = now_iso()
            status: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "project": project_name,
                "stage_id": None,
                "stage_name": None,
                "state": STATE_QUEUED,
                "attempt": 1,
                "session_id": None,
                "pid": None,
                "model": None,
                "variant": None,
                "repo_path": _repo_path(store.dir),
                "git_branch": None,
                "git_head": None,
                "started_at": None,
                "updated_at": ts,
                "heartbeat_at": None,
                "heartbeat_note": None,
                "result": None,
                "error": None,
                "artifacts": [],
                "proof": None,
                "notes": [],
                "meta": {},
            }
            store.write_status(status)
            store.append_event(
                {
                    "ts": ts,
                    "type": "init",
                    "stage_id": None,
                    "stage_name": None,
                    "state": STATE_QUEUED,
                    "attempt": 1,
                    "message": project_name,
                    "detail": {},
                }
            )
            store.write_status_md(status)
            return copy.deepcopy(status)

    def start(
        self,
        stage: str,
        *,
        stage_id: Optional[str] = None,
        session_id: Optional[str] = None,
        pid: Optional[int] = None,
        model: Optional[str] = None,
        variant: Optional[str] = None,
        git_head: Optional[str] = None,
        git_branch: Optional[str] = None,
        meta: Optional[dict[str, Any]] = None,
        write_status_mirror: Optional[bool] = None,
    ) -> dict[str, Any]:
        """Claim/start a stage. Allowed from any state (SPEC §4.2)."""
        if not stage or not stage.strip():
            raise BadArgsError("start requires a non-empty --stage NAME")
        new_id = stage_id or stage.strip()
        if pid is not None and (not isinstance(pid, int) or pid < 0):
            raise BadArgsError(f"invalid pid: {pid!r}")

        def _apply(current: dict[str, Any]) -> dict[str, Any]:
            ts = now_iso()
            same_series = current.get("stage_id") == new_id
            detected_head, detected_branch = _detect_git(self._store.dir)
            resolved_head = git_head if git_head is not None else detected_head
            resolved_branch = git_branch if git_branch is not None else detected_branch
            current.update(
                {
                    "stage_id": new_id,
                    "stage_name": stage.strip(),
                    "state": STATE_RUNNING,
                    "attempt": current.get("attempt", 0) + 1 if same_series else 1,
                    "session_id": session_id,
                    "pid": pid if pid is not None else os.getpid(),
                    "model": model,
                    "variant": variant,
                    "repo_path": _repo_path(self._store.dir),
                    "git_branch": resolved_branch,
                    "git_head": resolved_head,
                    "started_at": ts,
                    "heartbeat_at": ts,
                    "heartbeat_note": None,
                    "result": None,
                    "error": None,
                    "proof": None,
                    "meta": dict(meta) if meta else {},
                }
            )
            if not same_series:
                current["artifacts"] = []
            return current

        return self._mutate(
            "start",
            _apply,
            message=stage.strip(),
            detail={
                "stage_id": new_id,
                "session_id": session_id,
                "pid": pid,
                "model": model,
                "variant": variant,
            },
            do_mirror=write_status_mirror,
        )

    def heartbeat(self, note: Optional[str] = None) -> dict[str, Any]:
        """Bump heartbeat. Only from `running` (SPEC §4.3)."""
        def _apply(current: dict[str, Any]) -> dict[str, Any]:
            _require_state(current, (STATE_RUNNING,), "heartbeat")
            ts = now_iso()
            current["heartbeat_at"] = ts
            if note is not None:
                current["heartbeat_note"] = note
            return current

        return self._mutate("heartbeat", _apply, message=note)

    def note(self, text: str) -> dict[str, Any]:
        """Append a free-form note. Only from `running`."""
        if not text or not text.strip():
            raise BadArgsError("note requires non-empty TEXT")

        def _apply(current: dict[str, Any]) -> dict[str, Any]:
            _require_state(current, (STATE_RUNNING,), "note")
            notes = list(current.get("notes") or [])
            notes.append({"text": text, "added_at": now_iso()})
            current["notes"] = notes[-MAX_NOTES:]
            return current

        return self._mutate("note", _apply, message=text)

    def artifact(
        self, path: str, *, label: Optional[str] = None
    ) -> dict[str, Any]:
        """Record an artifact path. Only from `running`."""
        if not path or not path.strip():
            raise BadArgsError("artifact requires non-empty PATH")

        def _apply(current: dict[str, Any]) -> dict[str, Any]:
            _require_state(current, (STATE_RUNNING,), "artifact")
            artifacts = list(current.get("artifacts") or [])
            artifacts.append(
                {"path": path, "label": label, "added_at": now_iso()}
            )
            current["artifacts"] = artifacts
            return current

        return self._mutate(
            "artifact", _apply, message=path,
            detail={"path": path, "label": label},
        )

    def done(
        self,
        summary: Optional[str] = None,
        *,
        git_head: Optional[str] = None,
        proof_ref: Optional[str] = None,
        require_proof: bool = False,
        write_status_mirror: Optional[bool] = None,
    ) -> dict[str, Any]:
        """Mark success. From queued/running, or idempotent repeat (SPEC §4 rule 5)."""
        proof: Optional[dict[str, Any]] = None
        ref = proof_ref or os.environ.get(ENV_PROOF_REF)
        if require_proof:
            proof = verify_proof(ref)  # before any mutation
        elif ref:
            proof = {"tool": "agent-done-or-not", "ref": ref, "verified": None}

        def _apply(current: dict[str, Any]) -> dict[str, Any]:
            _require_terminal_source(current, STATE_DONE, "done")
            ts = now_iso()
            current["state"] = STATE_DONE
            current["result"] = {
                "summary": summary,
                "git_head": git_head if git_head is not None else current.get("git_head"),
                "finished_at": ts,
            }
            if git_head is not None:
                current["git_head"] = git_head
            if proof is not None:
                current["proof"] = proof
            current["error"] = None
            return current

        return self._mutate(
            "done", _apply, message=summary,
            detail={"proof": proof, "git_head": git_head},
            do_mirror=write_status_mirror,
        )

    def blocked(
        self,
        reason: str,
        *,
        write_status_mirror: Optional[bool] = None,
    ) -> dict[str, Any]:
        """Mark externally blocked. Same transition rule as done."""
        if not reason or not reason.strip():
            raise BadArgsError("blocked requires non-empty --reason TEXT")

        def _apply(current: dict[str, Any]) -> dict[str, Any]:
            _require_terminal_source(current, STATE_BLOCKED, "blocked")
            current["state"] = STATE_BLOCKED
            current["error"] = {
                "reason": reason,
                "kind": STATE_BLOCKED,
                "finished_at": now_iso(),
            }
            current["result"] = None
            return current

        return self._mutate(
            "blocked", _apply, message=reason,
            do_mirror=write_status_mirror,
        )

    def fail(
        self,
        reason: str,
        *,
        write_status_mirror: Optional[bool] = None,
    ) -> dict[str, Any]:
        """Mark hard failure. Same transition rule as done."""
        if not reason or not reason.strip():
            raise BadArgsError("fail requires non-empty --reason TEXT")

        def _apply(current: dict[str, Any]) -> dict[str, Any]:
            _require_terminal_source(current, STATE_FAILED, "fail")
            current["state"] = STATE_FAILED
            current["error"] = {
                "reason": reason,
                "kind": STATE_FAILED,
                "finished_at": now_iso(),
            }
            current["result"] = None
            return current

        return self._mutate(
            "failed", _apply, message=reason,
            do_mirror=write_status_mirror,
        )

    def clear_terminal(self) -> dict[str, Any]:
        """Reset done/blocked/failed back to queued (SPEC §4.7)."""

        def _apply(current: dict[str, Any]) -> dict[str, Any]:
            _require_state(
                current, TERMINAL_STATES, "clear-terminal",
                message="only terminal states (done/blocked/failed) "
                        "can be cleared",
            )
            current["state"] = STATE_QUEUED
            current["result"] = None
            current["error"] = None
            return current

        return self._mutate("clear_terminal", _apply, message="cleared to queued")

    # -- observers --------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Read current STATUS (shared lock)."""
        with self._store.locked(exclusive=False):
            return copy.deepcopy(self._store.read_status())

    def events(self) -> list[dict[str, Any]]:
        """Read all events."""
        with self._store.locked(exclusive=False):
            return self._store.read_events()

    def wait(
        self,
        want: str = "terminal",
        *,
        timeout: float = 3600,
        poll: float = 5,
    ) -> dict[str, Any]:
        """Poll until *want* matches. Raises WaitTimeout (exit 14) on timeout."""
        if want not in WAIT_CHOICES:
            raise BadArgsError(
                f"invalid wait state {want!r} "
                f"(choose from {', '.join(WAIT_CHOICES)})"
            )
        if timeout <= 0:
            raise BadArgsError("wait --timeout must be > 0")
        if poll <= 0:
            raise BadArgsError("wait --poll must be > 0")
        deadline = time.monotonic() + timeout
        last: dict[str, Any] = self.status()  # raises NotInitialized early
        while True:
            state = str(last.get("state"))
            if want_matches(want, state):
                return last
            if state in TERMINAL_STATES:
                # A different terminal state already won (before or during
                # the wait): report it now instead of hanging until timeout.
                # The caller maps it to its exit code (SPEC §6).
                return last
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WaitTimeout(
                    f"wait timed out after {timeout:g}s "
                    f"(state={last.get('state')})",
                    last_status=copy.deepcopy(last),
                )
            time.sleep(min(poll, remaining))
            with self._store.locked(exclusive=False):
                last = copy.deepcopy(self._store.read_status())

    def diagnose(self, *, stale_after: Optional[float] = 300.0) -> dict[str, Any]:
        """Check dir health. Returns {"ok", "problems", "warnings", "status"}."""
        problems: list[str] = []
        warnings: list[str] = []
        status: Optional[dict[str, Any]] = None
        store = self._store
        if not store.dir.is_dir():
            problems.append(f"missing dir: {store.dir}")
            return {"ok": False, "problems": problems,
                    "warnings": warnings, "status": None}
        if not store.is_initialized:
            problems.append(f"missing STATUS: {store.status_path}")
        else:
            try:
                status = store.read_status()
            except NotInitialized as exc:
                problems.append(str(exc))
            except Exception as exc:  # CorruptStatusError etc.
                problems.append(str(exc))
        if store.is_initialized:
            try:
                store.read_events()
            except Exception as exc:
                problems.append(str(exc))
        try:
            store.ensure_layout()
            with open(store.lock_path, "a"):
                pass
        except OSError as exc:
            problems.append(f"lock file not writable: {exc}")
        if stale_after is not None and status is not None:
            if status.get("state") == STATE_RUNNING and status.get("heartbeat_at"):
                try:
                    from datetime import datetime as _dt
                    hb = _dt.fromisoformat(str(status["heartbeat_at"]))
                    age = (_dt.now().astimezone() - hb).total_seconds()
                    if age > stale_after:
                        warnings.append(
                            f"STALE: running with heartbeat {age:.0f}s ago "
                            f"(threshold {stale_after:g}s)"
                        )
                except ValueError:
                    warnings.append("unparseable heartbeat_at")
            elif status.get("state") == STATE_RUNNING:
                warnings.append("STALE: running with no heartbeat recorded")
        if status is not None and status.get("state") == STATE_RUNNING:
            pid = status.get("pid")
            if isinstance(pid, int) and not isinstance(pid, bool):
                try:
                    alive = _is_pid_alive(pid)
                    if alive is False:
                        warnings.append(
                            f"DEAD PID: claiming pid {pid} is not alive (state still running)"
                        )
                except Exception:
                    pass
        return {
            "ok": not problems,
            "problems": problems,
            "warnings": warnings,
            "status": status,
        }


# -- helpers ------------------------------------------------------------


def _is_pid_alive_posix(pid: int) -> Optional[bool]:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        if exc.errno == errno.EPERM:
            return True
        return None
    except Exception:
        return None


def _is_pid_alive_windows(pid: int) -> Optional[bool]:
    try:
        import ctypes

        kernel32 = getattr(getattr(ctypes, "windll", None), "kernel32", None)
        if kernel32 is None:
            return None
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            err = kernel32.GetLastError()
            if err == 5:  # ERROR_ACCESS_DENIED: process exists, treat as alive
                return True
            return False
        try:
            exit_code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return bool(exit_code.value == STILL_ACTIVE)
            return True
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return None


def _is_pid_alive(pid: int) -> Optional[bool]:
    """Best-effort check whether a process is alive.

    Returns True if alive, False if dead, or None if indeterminate.
    Never raises.
    - POSIX: os.kill(pid, 0) (ESRCH -> dead, EPERM -> alive).
    - Windows: kernel32.OpenProcess / GetExitCodeProcess via ctypes.
    """
    if not isinstance(pid, int) or isinstance(pid, bool):
        return None
    if pid <= 0:
        return False

    if sys.platform == "win32":
        return _is_pid_alive_windows(pid)
    return _is_pid_alive_posix(pid)


def _require_state(
    status: dict[str, Any],
    allowed: tuple[str, ...],
    op: str,
    *,
    message: Optional[str] = None,
) -> None:
    state = status.get("state")
    if state not in allowed:
        raise IllegalTransition(
            message or f"{op} not allowed from state {state!r} "
                       f"(allowed: {', '.join(allowed)})"
        )


def _require_terminal_source(
    current: dict[str, Any], target: str, op: str
) -> None:
    """Enforce SPEC §4 rules 5-6: queued/running, or idempotent same-stage repeat."""
    state = current.get("state")
    if state in (STATE_QUEUED, STATE_RUNNING):
        return
    if state == target:
        return  # idempotent repeat (same series by construction)
    raise IllegalTransition(
        f"{op} not allowed from terminal state {state!r}: "
        "run 'start' for a new attempt or 'clear-terminal' first"
    )


def _default_project(stage_dir: Path) -> str:
    if stage_dir.name == ".stage-signal":
        return stage_dir.parent.name
    return Path.cwd().name


def _repo_path(stage_dir: Path) -> Optional[str]:
    try:
        if stage_dir.name == ".stage-signal":
            return str(stage_dir.parent.resolve())
        return str(Path.cwd().resolve())
    except OSError:
        return None


def _detect_git(stage_dir: Path) -> tuple[Optional[str], Optional[str]]:
    """Return (git_head, git_branch) best-effort for the repository containing stage_dir."""
    head: Optional[str] = None
    branch: Optional[str] = None
    try:
        candidate = (
            stage_dir
            if (stage_dir / ".git").exists()
            else stage_dir.parent
        )
    except OSError:
        candidate = stage_dir.parent

    try:
        proc = subprocess.run(
            ["git", "-C", str(candidate), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            val = proc.stdout.strip()
            if val:
                head = val
    except (subprocess.SubprocessError, OSError):
        pass

    try:
        proc = subprocess.run(
            ["git", "-C", str(candidate), "symbolic-ref", "--short", "-q", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            val = proc.stdout.strip()
            if val:
                branch = val
    except (subprocess.SubprocessError, OSError):
        pass

    return head, branch
