"""stage-signal core library: the Stage lifecycle API (SPEC §§3-5, 8-11)."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import errno
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional, Sequence

from .constants import (
    DEFAULT_MIRROR_DIRNAME,
    DEFAULT_STALE_THRESHOLD,
    SUPERVISE_DEFAULT_EVERY,
    ENV_STATUS_MIRROR,
    ENV_PROJECT,
    ENV_PROOF_REF,
    EVENT_TYPES,
    MAX_NOTES,
    SCHEMA_VERSION,
    STATE_BLOCKED,
    STATE_DONE,
    STATE_FAILED,
    STATE_QUEUED,
    STATE_RUNNING,
    TERMINAL_STATES,
    DOCTOR_SUMMARY_RECLAIM_NEEDED,
    WARNING_CODE_DEAD_PID,
    WARNING_CODE_STALE_HEARTBEAT,
    WARNING_CODE_UNPARSEABLE_HEARTBEAT,
    state_exit_code,
)
from .errors import (
    BadArgsError,
    IllegalTransition,
    NotInitialized,
    WaitTimeout,
)
from .store import StageStore

__all__ = [
    "Stage",
    "state_exit_code",
    "want_matches",
    "wait_condition_met",
    "verify_proof",
    "write_status_mirror",
]

WAIT_CHOICES = ("done", "blocked", "failed", "terminal")
WAIT_WANT_NEEDS_RECLAIM = "needs_reclaim"


def want_matches(want: str, state: str) -> bool:
    """True when *state* satisfies a `wait --state` want value."""
    if want == "terminal":
        return state in TERMINAL_STATES
    return state == want


def wait_condition_met(
    status: dict[str, Any],
    *,
    want: str,
    needs_reclaim: bool = False,
) -> bool:
    """True when a wait snapshot satisfies the requested condition."""
    if needs_reclaim:
        return bool(status.get("needs_reclaim"))
    return want_matches(want, str(status.get("state")))


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
        cmd = [binary, "verify", "--ref", ref]
        if sys.platform == "win32" and binary.lower().endswith((".cmd", ".bat")):
            comspec = os.environ.get("COMSPEC") or os.environ.get("ComSpec") or "cmd.exe"
            cmd = [comspec, "/c"] + cmd
        try:
            proc = subprocess.run(
                cmd,
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
            return _attach_heartbeat_age(copy.deepcopy(new_status))

    # -- lifecycle ------------------------------------------------------

    def init(self, project: Optional[str] = None) -> dict[str, Any]:
        """Create the stage dir + queued STATUS (idempotent, SPEC §4.1)."""
        store = self._store
        with store.locked(exclusive=True):
            if store.is_initialized:
                # Validate: fail loudly on corruption rather than masking it.
                return _attach_heartbeat_age(copy.deepcopy(store.read_status()))
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
                "pid_token": None,
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
            return _attach_heartbeat_age(copy.deepcopy(status))

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

        # Detect git outside the store lock — subprocess + lock is a Windows hang risk.
        detected_head, detected_branch = _detect_git(self._store.dir)
        resolved_head = git_head if git_head is not None else detected_head
        resolved_branch = git_branch if git_branch is not None else detected_branch
        resolved_pid = pid if pid is not None else os.getpid()
        pid_token = _pid_token(resolved_pid)

        def _apply(current: dict[str, Any]) -> dict[str, Any]:
            ts = now_iso()
            same_series = current.get("stage_id") == new_id
            current.update(
                {
                    "stage_id": new_id,
                    "stage_name": stage.strip(),
                    "state": STATE_RUNNING,
                    "attempt": current.get("attempt", 0) + 1 if same_series else 1,
                    "session_id": session_id,
                    "pid": resolved_pid,
                    "pid_token": pid_token,
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
        accept_failure: bool = False,
        write_status_mirror: Optional[bool] = None,
    ) -> dict[str, Any]:
        """Mark success. From queued/running, or idempotent repeat (SPEC §4 rule 5).

        When accept_failure=True, allowed ONLY from failed, recording
        accepted_failure: true in result.
        """
        proof: Optional[dict[str, Any]] = None
        ref = proof_ref or os.environ.get(ENV_PROOF_REF)
        if require_proof:
            proof = verify_proof(ref)  # before any mutation
        elif ref:
            proof = {"tool": "agent-done-or-not", "ref": ref, "verified": None}

        def _apply(current: dict[str, Any]) -> dict[str, Any]:
            state = current.get("state")
            if accept_failure:
                if state != STATE_FAILED:
                    raise IllegalTransition(
                        f"done --accept-failure only allowed from state 'failed' "
                        f"(current state: {state!r})"
                    )
            else:
                _require_terminal_source(current, STATE_DONE, "done")
            ts = now_iso()
            current["state"] = STATE_DONE
            result_payload: dict[str, Any] = {
                "summary": summary,
                "git_head": git_head if git_head is not None else current.get("git_head"),
                "finished_at": ts,
            }
            if accept_failure:
                result_payload["accepted_failure"] = True
            current["result"] = result_payload
            if git_head is not None:
                current["git_head"] = git_head
            if proof is not None:
                current["proof"] = proof
            current["error"] = None
            return current

        detail: dict[str, Any] = {"proof": proof, "git_head": git_head}
        if accept_failure:
            detail["accepted_failure"] = True

        return self._mutate(
            "done", _apply, message=summary,
            detail=detail,
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
        if_dead_pid: bool = False,
        if_needs_reclaim: bool = False,
        write_status_mirror: Optional[bool] = None,
    ) -> dict[str, Any]:
        """Mark hard failure. Same transition rule as done."""
        if not reason or not reason.strip():
            raise BadArgsError("fail requires non-empty --reason TEXT")
        if if_dead_pid and if_needs_reclaim:
            raise BadArgsError(
                "fail --if-dead-pid and --if-needs-reclaim are mutually exclusive"
            )

        def _apply(current: dict[str, Any]) -> dict[str, Any]:
            if if_needs_reclaim:
                _, needs_reclaim = _reclaim_diagnostics(current)
                if not needs_reclaim:
                    raise IllegalTransition(
                        "fail --if-needs-reclaim refused: needs_reclaim is false "
                        f"(state={current.get('state')!r}; no DEAD_PID or "
                        "STALE_HEARTBEAT)"
                    )
            else:
                _require_terminal_source(current, STATE_FAILED, "fail")
                if if_dead_pid and current.get("state") == STATE_RUNNING:
                    pid = current.get("pid")
                    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
                        raise IllegalTransition(
                            "fail --if-dead-pid requires a valid positive integer claiming pid"
                        )
                    alive = _is_pid_alive(pid)
                    if alive is not False:
                        condition = "is alive" if alive is True else "has unknown liveness"
                        raise IllegalTransition(
                            f"fail --if-dead-pid refused: claiming pid {pid} {condition}"
                        )
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

    def reclaim(
        self,
        reason: str,
        *,
        keep_failed: bool = False,
        kill: bool = False,
        write_status_mirror: Optional[bool] = None,
    ) -> dict[str, Any]:
        """Fail a needs_reclaim running stage, then clear to idle queued.

        When ``needs_reclaim`` is true (same detection as doctor/status/
        ``fail --if-needs-reclaim``), writes ``failed`` + reason and — unless
        ``keep_failed`` — immediately ``clear-terminal`` to idle queued, under
        one exclusive lock (two events: ``failed`` then ``clear_terminal``).

        With ``kill=True``, after the guard passes, a valid positive recorded
        pid that probes alive is signalled best-effort: SIGTERM, a brief
        bounded wait (1s), then SIGKILL if it is still alive. Dead, missing,
        or unknown-liveness pids skip the kill path and reclaim proceeds.
        Signal errors warn on stderr and never abort the reclaim. Without
        ``kill``, no process signal is sent.

        When ``needs_reclaim`` is false: raise IllegalTransition (exit 3) with
        no mutation.
        """
        if not reason or not reason.strip():
            raise BadArgsError("reclaim requires non-empty --reason TEXT")

        store = self._store
        with store.locked(exclusive=True):
            status = store.read_status()
            _, needs_reclaim = _reclaim_diagnostics(status)
            if not needs_reclaim:
                raise IllegalTransition(
                    "reclaim refused: needs_reclaim is false "
                    f"(state={status.get('state')!r}; no DEAD_PID or "
                    "STALE_HEARTBEAT)"
                )

            if kill:
                _terminate_pid(
                    status.get("pid"), token=status.get("pid_token")
                )

            failed = copy.deepcopy(status)
            failed["state"] = STATE_FAILED
            failed["error"] = {
                "reason": reason,
                "kind": STATE_FAILED,
                "finished_at": now_iso(),
            }
            failed["result"] = None
            failed["updated_at"] = now_iso()
            store.write_status(failed)
            store.append_event(
                {
                    "ts": failed["updated_at"],
                    "type": "failed",
                    "stage_id": failed.get("stage_id"),
                    "stage_name": failed.get("stage_name"),
                    "state": failed.get("state"),
                    "attempt": failed.get("attempt"),
                    "message": reason,
                    "detail": {"reclaim": True, "keep_failed": keep_failed},
                }
            )
            store.write_status_md(failed)
            if _status_mirror_enabled(write_status_mirror):
                mirrored = sys.modules[__name__].write_status_mirror(store.dir, failed)
                if mirrored is None:
                    print(
                        "stage-signal: warning: status mirror failed",
                        file=sys.stderr,
                    )

            if keep_failed:
                return _attach_heartbeat_age(copy.deepcopy(failed))

            cleared = copy.deepcopy(failed)
            cleared["state"] = STATE_QUEUED
            cleared["result"] = None
            cleared["error"] = None
            cleared["proof"] = None
            cleared["stage_id"] = None
            cleared["stage_name"] = None
            cleared["session_id"] = None
            cleared["pid"] = None
            cleared["pid_token"] = None
            cleared["started_at"] = None
            cleared["heartbeat_at"] = None
            cleared["heartbeat_note"] = None
            cleared["artifacts"] = []
            cleared["meta"] = {}
            cleared["updated_at"] = now_iso()
            store.write_status(cleared)
            store.append_event(
                {
                    "ts": cleared["updated_at"],
                    "type": "clear_terminal",
                    "stage_id": cleared.get("stage_id"),
                    "stage_name": cleared.get("stage_name"),
                    "state": cleared.get("state"),
                    "attempt": cleared.get("attempt"),
                    "message": "cleared to idle queued",
                    "detail": {"keep_stage": False, "reclaim": True},
                }
            )
            store.write_status_md(cleared)
            return _attach_heartbeat_age(copy.deepcopy(cleared))

    def clear_terminal(self, *, keep_stage: bool = False) -> dict[str, Any]:
        """Reset done/blocked/failed or queued back to queued (SPEC §4.7).

        Allowed from terminal states and from queued (abandon a parked or idle
        queued stage). Running remains illegal — reclaim with ``reclaim``,
        ``fail --if-needs-reclaim``, or ``fail --if-dead-pid`` first.

        By default, clears stage identity (stage_id and stage_name set to None,
        plus claim/session/heartbeat fields), transitioning to a true idle queued
        state. Pass keep_stage=True to preserve the previous stage identity.
        """

        def _apply(current: dict[str, Any]) -> dict[str, Any]:
            _require_state(
                current, TERMINAL_STATES + (STATE_QUEUED,), "clear-terminal",
                message="only terminal states (done/blocked/failed) or queued "
                        "can be cleared (running requires reclaim, "
                        "fail --if-needs-reclaim, or fail --if-dead-pid first)",
            )
            current["state"] = STATE_QUEUED
            current["result"] = None
            current["error"] = None
            current["proof"] = None
            if not keep_stage:
                current["stage_id"] = None
                current["stage_name"] = None
                current["session_id"] = None
                current["pid"] = None
                current["pid_token"] = None
                current["started_at"] = None
                current["heartbeat_at"] = None
                current["heartbeat_note"] = None
                current["artifacts"] = []
                current["meta"] = {}
            return current

        msg = "cleared to queued" if keep_stage else "cleared to idle queued"
        return self._mutate(
            "clear_terminal",
            _apply,
            message=msg,
            detail={"keep_stage": keep_stage},
        )

    # -- supervisor -------------------------------------------------------

    def supervise(
        self,
        cmd: Sequence[str] | str,
        *,
        every: float = SUPERVISE_DEFAULT_EVERY,
        stale_threshold: float = DEFAULT_STALE_THRESHOLD,
        summary: Optional[str] = None,
        reason: Optional[str] = None,
        write_status_mirror: Optional[bool] = None,
        cwd: Optional[Path | str] = None,
        env: Optional[dict[str, str]] = None,
    ) -> int:
        """Supervise a child command, auto-heartbeating while running (SPEC §6).

        The stage must already be in state ``running`` (SPEC §4.2/§6).
        Refuses with ``IllegalTransition`` (exit 3) if not running.

        While child process is alive, bumps ``heartbeat`` every *every*
        seconds (default 60; validated 1 <= every <= stale_threshold - 1).

        When child exits 0, transitions to ``done`` with *summary*.
        When child exits non-zero, transitions to ``failed`` with *reason*.
        Signals (SIGINT, SIGTERM) are forwarded to the child process,
        and the terminal transition is recorded before returning.

        Returns the exit code of the child process (or 128 + sig on signal).
        """
        if (
            not isinstance(every, (int, float))
            or isinstance(every, bool)
            or every < 1.0
            or every > (stale_threshold - 1.0)
        ):
            raise BadArgsError(
                f"--every must be between 1 and {int(stale_threshold - 1)} seconds (got {every})"
            )

        if isinstance(cmd, str):
            cmd_list = shlex.split(cmd) if cmd.strip() else []
        elif isinstance(cmd, (list, tuple)):
            cmd_list = [str(arg) for arg in cmd]
        else:
            raise BadArgsError(
                f"cmd must be a sequence of strings or a string (got {type(cmd).__name__})"
            )

        if not cmd_list:
            raise BadArgsError("supervise requires a non-empty command")

        st = self.status()
        current_state = st.get("state")
        if current_state != STATE_RUNNING:
            raise IllegalTransition(
                f"supervise requires state 'running' (current state: {current_state!r})"
            )

        cmd_display = " ".join(shlex.quote(str(arg)) for arg in cmd_list)
        try:
            proc = subprocess.Popen(
                cmd_list,
                cwd=cwd,
                env=env,
            )
        except FileNotFoundError as exc:
            self.fail(
                reason=f"command not found: {cmd_list[0]}",
                write_status_mirror=write_status_mirror,
            )
            return 127
        except PermissionError as exc:
            self.fail(
                reason=f"permission denied: {cmd_list[0]}",
                write_status_mirror=write_status_mirror,
            )
            return 126
        except OSError as exc:
            self.fail(
                reason=f"failed to execute command {cmd_list[0]}: {exc}",
                write_status_mirror=write_status_mirror,
            )
            return 1

        is_main_thread = (
            threading.current_thread() is threading.main_thread()
            and hasattr(signal, "signal")
        )
        old_handlers: dict[int, Any] = {}

        def _forward_signal(signum: int, _frame: Any) -> None:
            try:
                proc.send_signal(signum)
            except (ProcessLookupError, OSError):
                pass
            except ValueError:
                try:
                    proc.terminate()
                except (ProcessLookupError, OSError):
                    pass

        if is_main_thread:
            for sig_name in ("SIGINT", "SIGTERM"):
                if hasattr(signal, sig_name):
                    sig = getattr(signal, sig_name)
                    try:
                        old_handlers[sig] = signal.signal(sig, _forward_signal)
                    except (ValueError, OSError):
                        pass

        try:
            next_heartbeat = time.monotonic() + every
            while True:
                now = time.monotonic()
                time_left = next_heartbeat - now
                if time_left <= 0:
                    if proc.poll() is not None:
                        break
                    try:
                        self.heartbeat()
                    except StageError:
                        pass
                    next_heartbeat = time.monotonic() + every
                    time_left = every

                wait_slice = max(0.01, min(time_left, 1.0))
                try:
                    proc.wait(timeout=wait_slice)
                    break
                except subprocess.TimeoutExpired:
                    pass
        finally:
            if is_main_thread:
                for sig, old_h in old_handlers.items():
                    try:
                        signal.signal(sig, old_h)
                    except (ValueError, OSError):
                        pass

        rc = proc.returncode
        if rc is None:
            rc = proc.wait()

        if rc < 0:
            sig_num = -rc
            try:
                sig_name = signal.Signals(sig_num).name
            except (ValueError, AttributeError):
                sig_name = f"SIG{sig_num}"
            exit_code = 128 + sig_num
            default_fail_reason = f"command terminated by {sig_name}: {cmd_display}"
        else:
            exit_code = rc
            default_fail_reason = f"command failed with exit code {exit_code}: {cmd_display}"

        if exit_code == 0:
            self.done(
                summary=summary or f"command succeeded (exit 0): {cmd_display}",
                write_status_mirror=write_status_mirror,
            )
        else:
            self.fail(
                reason=reason or default_fail_reason,
                write_status_mirror=write_status_mirror,
            )

        return exit_code

    # -- observers --------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Read current STATUS (shared lock)."""
        with self._store.locked(exclusive=False):
            status = copy.deepcopy(self._store.read_status())
            _, status["needs_reclaim"] = _reclaim_diagnostics(status)
            return _attach_heartbeat_age(status)

    def events(
        self,
        *,
        tail: Optional[int] = None,
        type: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Read events.jsonl (shared lock). Chronological, newest last.

        *type* filters to one SPEC event type. *tail* keeps the last N
        matching events (``None`` or ``0`` = all). Filter is applied
        before tail, so ``type="failed", tail=5`` is the last 5 failed
        events.
        """
        if type is not None and type not in EVENT_TYPES:
            raise BadArgsError(
                f"invalid event type {type!r} "
                f"(choose from {'|'.join(EVENT_TYPES)})"
            )
        if tail is not None and (
            not isinstance(tail, int) or isinstance(tail, bool) or tail < 0
        ):
            raise BadArgsError("events tail must be an int >= 0 (0 = all)")
        with self._store.locked(exclusive=False):
            events = self._store.read_events()
        if type is not None:
            events = [event for event in events if event.get("type") == type]
        if tail:
            events = events[-tail:]
        return copy.deepcopy(events)

    def wait(
        self,
        want: str = "terminal",
        *,
        timeout: float = 3600,
        poll: float = 5,
        needs_reclaim: bool = False,
    ) -> dict[str, Any]:
        """Poll until *want* matches, or until ``needs_reclaim`` if that flag is set.

        Raises WaitTimeout (exit 14) on timeout. When *needs_reclaim* is
        true, a terminal ``done``/``blocked``/``failed`` snapshot without
        reclaim is returned immediately so the caller can fail closed
        (never treated as success). Healthy ``running`` keeps polling.
        """
        if needs_reclaim:
            if want != "terminal":
                raise BadArgsError(
                    "wait needs_reclaim=True cannot be combined with a --state want"
                )
        elif want not in WAIT_CHOICES:
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
            if wait_condition_met(last, want=want, needs_reclaim=needs_reclaim):
                return last
            state = str(last.get("state"))
            if state in TERMINAL_STATES:
                # A different terminal state already won (before or during
                # the wait), or --needs-reclaim hit terminal without reclaim:
                # report it now instead of hanging until timeout. The caller
                # maps it to a non-zero mismatch exit (SPEC §6).
                return last
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                extra = ""
                if needs_reclaim:
                    extra = f", needs_reclaim={last.get('needs_reclaim')}"
                raise WaitTimeout(
                    f"wait timed out after {timeout:g}s "
                    f"(state={last.get('state')}{extra})",
                    last_status=copy.deepcopy(last),
                )
            time.sleep(min(poll, remaining))
            last = self.status()

    def diagnose(
        self, *, stale_after: Optional[float] = DEFAULT_STALE_THRESHOLD
    ) -> dict[str, Any]:
        """Check dir health. Returns {"ok", "needs_reclaim", "state", "problems", "warnings", "status", "summary"}."""
        problems: list[str] = []
        warnings: list[dict[str, Any]] = []
        status: Optional[dict[str, Any]] = None
        store = self._store
        if not store.dir.is_dir():
            problems.append(f"missing dir: {store.dir}")
            return {
                "ok": False,
                "needs_reclaim": False,
                "state": None,
                "problems": problems,
                "warnings": warnings,
                "status": None,
                "summary": None,
            }
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
        warnings, needs_reclaim = _reclaim_diagnostics(status, stale_after=stale_after)
        summary: Optional[str] = None
        if not problems:
            if needs_reclaim:
                summary = DOCTOR_SUMMARY_RECLAIM_NEEDED
            else:
                state_str = status.get("state") if isinstance(status, dict) else "uninitialized dir exists"
                summary = f"OK: {state_str}"

        return {
            "ok": not problems,
            "needs_reclaim": needs_reclaim,
            "state": status.get("state") if isinstance(status, dict) else None,
            "problems": problems,
            "warnings": warnings,
            "status": _attach_heartbeat_age(copy.deepcopy(status)) if status is not None else None,
            "summary": summary,
        }


# -- helpers ------------------------------------------------------------


def _terminate_pid(
    pid: Any,
    *,
    token: Optional[str] = None,
    timeout: float = 1.0,
    poll: float = 0.05,
) -> bool:
    """Best-effort SIGTERM -> bounded wait -> SIGKILL for a recorded pid.

    Reuses the doctor/status liveness probe. Invalid or dead pids (and
    unknown liveness) are a no-op returning False. Never raises.

    When a non-None *token* is given, the process-start identity is
    re-verified before each termination signal; mismatch or unreadable
    identity skips the kill (possible pid reuse). Legacy statuses without
    a recorded token keep the previous best-effort behavior.
    """
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if _is_pid_alive(pid) is not True:
        return False
    if not _pid_token_matches(pid, token):
        return False
    try:
        if sys.platform == "win32":
            if not _pid_token_matches(pid, token):
                return False
            _signal_pid_best_effort(pid, signal.SIGTERM)
        else:
            _signal_pid_best_effort(pid, signal.SIGTERM)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if _is_pid_alive(pid) is False:
                    return True
                time.sleep(poll)
    except Exception:
        pass
    if _is_pid_alive(pid) is True:
        if not _pid_token_matches(pid, token):
            return False
        _signal_pid_best_effort(pid, signal.SIGKILL)
    return True


def _signal_pid_best_effort(pid: int, sig: int) -> None:
    try:
        os.kill(pid, sig)
    except Exception as exc:
        print(
            f"stage-signal: warning: kill pid {pid} "
            f"signal {sig} failed: {exc}",
            file=sys.stderr,
        )


def _reclaim_diagnostics(
    status: Optional[dict[str, Any]],
    *,
    stale_after: Optional[float] = DEFAULT_STALE_THRESHOLD,
) -> tuple[list[dict[str, Any]], bool]:
    warnings: list[dict[str, Any]] = []
    if status is None or status.get("state") != STATE_RUNNING:
        return warnings, False
    if stale_after is not None:
        if status.get("heartbeat_at"):
            try:
                hb = datetime.fromisoformat(str(status["heartbeat_at"]))
                if hb.tzinfo is None:
                    hb = hb.replace(tzinfo=timezone.utc)
                age = max(0.0, (_now_dt() - hb).total_seconds())
                if age > stale_after:
                    warnings.append({
                        "code": WARNING_CODE_STALE_HEARTBEAT,
                        "message": (
                            f"STALE: running with heartbeat {age:.0f}s ago "
                            f"(threshold {stale_after:g}s)"
                        ),
                        "detail": {
                            "age": age,
                            "threshold": stale_after,
                            "heartbeat_at": status.get("heartbeat_at"),
                        },
                    })
            except ValueError:
                warnings.append({
                    "code": WARNING_CODE_UNPARSEABLE_HEARTBEAT,
                    "message": "unparseable heartbeat_at",
                    "detail": {
                        "heartbeat_at": status.get("heartbeat_at"),
                    },
                })
        else:
            warnings.append({
                "code": WARNING_CODE_STALE_HEARTBEAT,
                "message": "STALE: running with no heartbeat recorded",
                "detail": {
                    "age": None,
                    "threshold": stale_after,
                    "heartbeat_at": None,
                },
            })
    pid = status.get("pid")
    if isinstance(pid, int) and not isinstance(pid, bool):
        try:
            alive = _is_pid_alive(pid)
            if alive is False:
                recovery_hint = "fail --reason TEXT --if-dead-pid"
                warnings.append({
                    "code": WARNING_CODE_DEAD_PID,
                    "message": (
                        f"DEAD PID: claiming pid {pid} is not alive (state still running); "
                        f"reclaim with '{recovery_hint}'"
                    ),
                    "detail": {
                        "pid": pid,
                        "recovery_hint": recovery_hint,
                    },
                })
        except Exception:
            pass
    needs_reclaim = any(
        w.get("code") in {WARNING_CODE_STALE_HEARTBEAT, WARNING_CODE_DEAD_PID}
        for w in warnings
    )
    return warnings, needs_reclaim


def _now_dt() -> datetime:
    return datetime.now().astimezone()


def now_iso() -> str:
    """Current local time as ISO-8601 with timezone offset."""
    return _now_dt().isoformat()


def _compute_heartbeat_age_seconds(
    heartbeat_at: Any,
    *,
    now: Optional[datetime] = None,
) -> Optional[float]:
    if not heartbeat_at:
        return None
    try:
        dt = datetime.fromisoformat(str(heartbeat_at))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        current = now if now is not None else _now_dt()
        return max(0.0, (current - dt).total_seconds())
    except Exception:
        return None


def _attach_heartbeat_age(
    status: Optional[dict[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> Optional[dict[str, Any]]:
    if status is None:
        return None
    if status.get("state") != "running":
        status["heartbeat_age_seconds"] = None
        return status
    status["heartbeat_age_seconds"] = _compute_heartbeat_age_seconds(
        status.get("heartbeat_at"), now=now
    )
    return status


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
            return False if err == 87 else None
        try:
            exit_code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return bool(exit_code.value == STILL_ACTIVE)
            return None
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


def _pid_token(pid: int) -> Optional[str]:
    """Best-effort opaque process-start identity for a pid.

    Prefers the process start time: Linux `/proc/<pid>/stat` field 22
    (clock ticks since boot), macOS `ps -o lstart=` (wall-clock start).
    Windows falls back to `wmic`-free kernel32 `GetProcessTimes` via
    ctypes (best effort). Any failure yields None: capture problems
    never prevent `start` from recording the pid.
    """
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return None
    if sys.platform == "win32":
        return _pid_token_windows(pid)
    if sys.platform == "linux":
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        # comm may contain spaces/parens: parse after the final ')'.
        rparen = stat.rfind(")")
        if rparen == -1:
            return None
        fields = stat[rparen + 2:].split()
        if len(fields) < 20:
            return None
        return fields[19]  # field 22 overall: starttime in clock ticks
    try:
        proc = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    if proc.returncode != 0:
        return None
    started = proc.stdout.strip()
    return started or None


def _pid_token_windows(pid: int) -> Optional[str]:
    """Process-start identity on Windows via kernel32 GetProcessTimes (best effort)."""
    try:
        import ctypes
        import ctypes.wintypes

        kernel32 = getattr(getattr(ctypes, "windll", None), "kernel32", None)
        if kernel32 is None:
            return None
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None

        class _Filetime(ctypes.Structure):
            _fields_ = [("dw_low", ctypes.wintypes.DWORD),
                        ("dw_high", ctypes.wintypes.DWORD)]

        def _to_int(ft: "_Filetime") -> int:
            return (ft.dw_high << 32) | ft.dw_low

        try:
            creation = _Filetime()
            exit_time = _Filetime()
            kernel_time = _Filetime()
            user_time = _Filetime()
            if not kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel_time),
                ctypes.byref(user_time),
            ):
                return None
            created = _to_int(creation)
            return str(created) if created else None
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return None


def _read_pid_token(pid: int) -> Optional[str]:
    """Read the current process-start identity for a live pid (best effort).

    Returns None when identity cannot be read (process gone, platform
    unsupported, or probe failure) — callers treat None as "unreadable".
    """
    return _pid_token(pid)


def _pid_token_matches(pid: int, token: Optional[str]) -> bool:
    """True when the recorded identity still matches the live process.

    Legacy statuses without a recorded token (None) always match, preserving
    the pre-identity best-effort kill behavior. A recorded token fails closed
    on mismatch or when the live identity is unreadable.
    """
    if token is None:
        return True
    current = _read_pid_token(pid)
    if current is None:
        _warn_pid_identity_unreadable(pid)
        return False
    if current != token:
        print(
            f"stage-signal: warning: pid {pid} identity mismatch "
            f"(recorded {token!r}, current {current!r}); "
            "skipping kill (possible pid reuse)",
            file=sys.stderr,
        )
        return False
    return True


def _warn_pid_identity_unreadable(pid: int) -> None:
    print(
        f"stage-signal: warning: pid {pid} identity unreadable; "
        "skipping kill (recorded pid_token could not be confirmed)",
        file=sys.stderr,
    )


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
