"""stage-signal CLI: init/start/heartbeat/note/artifact/done/blocked/fail/status/wait/events/clear-terminal/doctor."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable, Optional, Sequence

from . import __version__
from .constants import (
    ENV_DIR,
    EVENT_TYPES,
    EVENTS_DEFAULT_TAIL,
    EXIT_ERROR,
    EXIT_OK,
    EXIT_RUNNING,
    WAIT_DEFAULT_POLL,
    WAIT_DEFAULT_TIMEOUT,
    state_exit_code,
)
from .errors import BadArgsError, StageError, WaitTimeout
from .stage import (
    WAIT_CHOICES,
    WAIT_WANT_NEEDS_RECLAIM,
    Stage,
    wait_condition_met,
)

# Re-exported for tests / embedding.
__all__ = ["build_parser", "main"]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="stage-signal",
        description="Harness-agnostic stage lifecycle for external orchestrators.",
    )
    p.add_argument(
        "--dir",
        default=None,
        help=f"stage dir (default: ${ENV_DIR} or .stage-signal)",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True, metavar="<command>")

    c = sub.add_parser("init", help="create stage dir + queued STATUS (idempotent)")
    c.add_argument("--project", default=None)
    c.set_defaults(func=cmd_init)

    c = sub.add_parser("start", help="claim/start a stage (allowed from any state)")
    c.add_argument("--stage", required=True)
    c.add_argument("--stage-id", default=None)
    c.add_argument("--session", default=None)
    c.add_argument("--pid", type=int, default=None)
    c.add_argument("--model", default=None)
    c.add_argument("--variant", default=None)
    c.add_argument("--git-head", default=None)
    c.add_argument("--git-branch", default=None)
    c.add_argument("--meta", action="append", default=[], metavar="K=V|JSON",
                     help="free-form meta: repeatable K=V or a JSON object "
                          "string (e.g. '{\"ticket\": 42}'); merged, later wins")
    c.add_argument("--write-status-mirror", action="store_true", default=None)
    c.set_defaults(func=cmd_start)

    c = sub.add_parser("heartbeat", help="bump heartbeat (running only)")
    c.add_argument("--note", default=None)
    c.set_defaults(func=cmd_heartbeat)

    c = sub.add_parser("note", help="append a free-form note (running only)")
    c.add_argument("text")
    c.set_defaults(func=cmd_note)

    c = sub.add_parser("artifact", help="record an artifact path (running only)")
    c.add_argument("path")
    c.add_argument("--label", default=None)
    c.set_defaults(func=cmd_artifact)

    c = sub.add_parser("done", help="mark stage succeeded")
    c.add_argument("--summary", default=None)
    c.add_argument("--git-head", default=None)
    c.add_argument("--proof-ref", default=None)
    c.add_argument("--require-proof", action="store_true", default=False)
    c.add_argument(
        "--accept-failure",
        action="store_true",
        default=False,
        help="allow done transition from failed only (records accepted_failure: true)",
    )
    c.add_argument("--write-status-mirror", action="store_true", default=None)
    c.set_defaults(func=cmd_done)

    c = sub.add_parser("blocked", help="mark stage externally blocked")
    c.add_argument("--reason", required=True)
    c.add_argument("--write-status-mirror", action="store_true", default=None)
    c.set_defaults(func=cmd_blocked)

    c = sub.add_parser("fail", help="mark stage hard-failed")
    c.add_argument("--reason", required=True)
    c.add_argument(
        "--if-dead-pid",
        action="store_true",
        default=False,
        help="when running, require a confirmed dead claiming pid; otherwise use normal fail rules",
    )
    c.add_argument(
        "--if-needs-reclaim",
        action="store_true",
        default=False,
        help=(
            "succeed only when needs_reclaim is true (DEAD_PID or "
            "STALE_HEARTBEAT, same as diagnose/doctor/status); otherwise "
            "exit 3 with no mutation"
        ),
    )
    c.add_argument("--write-status-mirror", action="store_true", default=None)
    c.set_defaults(func=cmd_fail)

    c = sub.add_parser("status", help="show current STATUS (exit code reflects state)")
    c.add_argument("--json", action="store_true", default=False)
    c.set_defaults(func=cmd_status)

    c = sub.add_parser(
        "events",
        help="show recent events.jsonl (newest last; default last 20)",
        description=(
            "Read events.jsonl under a shared lock. Human output is "
            "chronological, newest last. Default --tail 20; --tail 0 shows "
            "all. --type filters to one SPEC event type before --tail. "
            "--json prints a JSON array (not NDJSON)."
        ),
    )
    c.add_argument(
        "--tail",
        type=_nonneg_int,
        default=EVENTS_DEFAULT_TAIL,
        metavar="N",
        help=(
            "last N matching events (default: "
            f"{EVENTS_DEFAULT_TAIL}; 0 = all)"
        ),
    )
    c.add_argument(
        "--type",
        choices=list(EVENT_TYPES),
        default=None,
        metavar="TYPE",
        help=(
            "filter to one SPEC event type ("
            + "|".join(EVENT_TYPES)
            + "); applied before --tail"
        ),
    )
    c.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="print a JSON array (not NDJSON); omit human text",
    )
    c.set_defaults(func=cmd_events)

    c = sub.add_parser(
        "wait",
        help="poll until a state is reached, or until needs_reclaim",
        description=(
            "Poll until --state matches, or until --needs-reclaim. "
            "Healthy running is never success for --needs-reclaim "
            "(keep polling; do not treat status/doctor exit 10 as met). "
            "Terminal done/blocked/failed without reclaim fails closed "
            "(exit 1/11/12). Timeout 14; not initialized 15."
        ),
    )
    c.add_argument("--state", default="terminal", choices=list(WAIT_CHOICES))
    c.add_argument(
        "--needs-reclaim",
        action="store_true",
        default=False,
        help=(
            "poll until needs_reclaim is true (running + DEAD_PID or "
            "STALE_HEARTBEAT, same as doctor/status --json). Cannot be "
            "combined with --state other than the default. Exit 0 when "
            "reclaim is needed; keep polling healthy running; terminal "
            "without reclaim fails closed (done=1, blocked=11, failed=12)"
        ),
    )
    c.add_argument("--timeout", type=float, default=WAIT_DEFAULT_TIMEOUT)
    c.add_argument("--poll", type=float, default=WAIT_DEFAULT_POLL)
    c.add_argument(
        "--json",
        action="store_true",
        default=False,
        help=(
            "print one JSON object on stdout (outcome, wanted, observed_state / "
            "state, exit_code, timeout, stage_id, dir, reason, needs_reclaim, "
            "status); omit human text"
        ),
    )
    c.set_defaults(func=cmd_wait)

    c = sub.add_parser(
        "clear-terminal",
        help="reset a terminal or queued state back to idle queued",
    )
    c.add_argument(
        "--keep-stage",
        action="store_true",
        default=False,
        help="preserve stage name and id (default: clear to idle queued)",
    )
    c.set_defaults(func=cmd_clear_terminal)

    c = sub.add_parser("doctor", help="check stage dir health")
    c.add_argument("--stale-after", type=float, default=300.0, metavar="SEC",
                   help="warn on running heartbeat older than SEC (default: 300)")
    c.add_argument("--json", action="store_true", default=False,
                   help="output machine-readable JSON")
    c.add_argument("--format", choices=["human", "json"], default=None,
                   help="output format (default: human)")
    c.add_argument("--exit-reclaim", action="store_true", default=False,
                   help="exit 10 when needs_reclaim is true (default: exit 0 on warnings)")
    c.set_defaults(func=cmd_doctor)

    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    func: Callable[[argparse.Namespace], int] = args.func
    try:
        return func(args)
    except StageError as exc:
        print(f"stage-signal: error: {exc}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("stage-signal: interrupted", file=sys.stderr)
        return 130


# -- helpers ------------------------------------------------------------


def _stage(args: argparse.Namespace) -> Stage:
    return Stage(args.dir)


def _parse_meta(entries: Sequence[str]) -> dict[str, Any]:
    """Parse repeatable --meta entries (SPEC §6).

    Each entry is either ``K=V`` (value kept as a string) or a single
    raw JSON object string (e.g. ``'{"ticket": 42}'``). Entries merge in
    order; later entries win on key conflicts. JSON values keep their
    JSON types (numbers, bools, null, nested objects/arrays).
    """
    meta: dict[str, Any] = {}
    for entry in entries:
        stripped = entry.strip()
        if stripped.startswith("{"):
            try:
                obj = json.loads(entry)
            except json.JSONDecodeError as exc:
                raise BadArgsError(
                    f"invalid --meta {entry!r} "
                    f"(expected K=V or JSON object: {exc})"
                ) from exc
            if not isinstance(obj, dict):
                raise BadArgsError(
                    f"invalid --meta {entry!r} "
                    "(expected K=V or a JSON object, not "
                    f"{type(obj).__name__})"
                )
            meta.update(obj)
            continue
        if "=" not in entry:
            raise BadArgsError(
                f"invalid --meta {entry!r} (expected K=V or JSON object)"
            )
        key, _, value = entry.partition("=")
        if not key:
            raise BadArgsError(f"invalid --meta {entry!r} (empty key)")
        meta[key] = value
    return meta


def _nonneg_int(value: str) -> int:
    """argparse type: int >= 0 (0 = all for --tail)."""
    try:
        parsed = int(value, 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid int: {value!r}") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be >= 0 (0 = all)")
    return parsed


def _one_line(status: dict[str, Any]) -> str:
    return (
        f"{status.get('state')} "
        f"{status.get('stage_name') or '-'} "
        f"(attempt {status.get('attempt')})"
    )


def _one_line_event(event: dict[str, Any]) -> str:
    """Human one-liner: ts, type, state, stage, message (newest-last list)."""
    ts = str(event.get("ts") or "-")
    etype = str(event.get("type") or "-")
    state = str(event.get("state") or "-")
    name = str(event.get("stage_name") or "-")
    message = event.get("message")
    if message is None:
        msg = ""
    else:
        msg = str(message).replace("\n", " ").replace("\r", " ")
    line = f"{ts}  {etype:<14}  {state:<8}  {name}"
    if msg:
        line = f"{line}  {msg}"
    return line


def _status_reason(status: Optional[dict[str, Any]]) -> Optional[str]:
    """Short blocked/failed reason from a STATUS snapshot, else None."""
    if not status:
        return None
    err = status.get("error")
    if isinstance(err, dict):
        reason = err.get("reason")
        if isinstance(reason, str) and reason.strip():
            return reason
    return None


def _wait_json_payload(
    *,
    outcome: str,
    wanted: str,
    status: Optional[dict[str, Any]],
    exit_code: int,
    timed_out: bool,
    dir_path: str,
    reason: Optional[str] = None,
) -> dict[str, Any]:
    """Machine-readable wait result (SPEC §6). Human text is omitted."""
    state = None
    stage_id = None
    needs_reclaim = False
    if status:
        raw_state = status.get("state")
        state = str(raw_state) if raw_state is not None else None
        stage_id = status.get("stage_id")
        needs_reclaim = bool(status.get("needs_reclaim"))
    if reason is None:
        reason = _status_reason(status)
    return {
        "outcome": outcome,
        "wanted": wanted,
        "observed_state": state,
        "state": state,
        "exit_code": exit_code,
        "timeout": timed_out,
        "stage_id": stage_id,
        "dir": dir_path,
        "reason": reason,
        "needs_reclaim": needs_reclaim,
        "status": status,
    }


def _wait_mismatch_exit_code(state: str, *, needs_reclaim: bool) -> int:
    """Map a wait mismatch snapshot to a non-zero observing exit.

    Reuses the existing state codes (11/12/13/10). ``done`` observes as 0,
    so ``wait --needs-reclaim`` maps that case to exit 1 — never silent
    success when the reclaim condition was not met.
    """
    code = state_exit_code(state)
    if needs_reclaim and code == EXIT_OK:
        return EXIT_ERROR
    return code


# -- commands -----------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    st = _stage(args).init(project=args.project)
    print(f"initialized {st['project']} -> {_one_line(st)}")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    st = _stage(args).start(
        args.stage,
        stage_id=args.stage_id,
        session_id=args.session,
        pid=args.pid,
        model=args.model,
        variant=args.variant,
        git_head=args.git_head,
        git_branch=args.git_branch,
        meta=_parse_meta(args.meta),
        write_status_mirror=args.write_status_mirror,
    )
    print(f"started {_one_line(st)}")
    return 0


def cmd_heartbeat(args: argparse.Namespace) -> int:
    st = _stage(args).heartbeat(note=args.note)
    print(f"heartbeat {_one_line(st)} @ {st['heartbeat_at']}")
    return 0


def cmd_note(args: argparse.Namespace) -> int:
    st = _stage(args).note(args.text)
    print(f"noted {_one_line(st)}")
    return 0


def cmd_artifact(args: argparse.Namespace) -> int:
    st = _stage(args).artifact(args.path, label=args.label)
    print(f"artifact {_one_line(st)}: {args.path}")
    return 0


def cmd_done(args: argparse.Namespace) -> int:
    st = _stage(args).done(
        summary=args.summary,
        git_head=args.git_head,
        proof_ref=args.proof_ref,
        require_proof=args.require_proof,
        accept_failure=args.accept_failure,
        write_status_mirror=args.write_status_mirror,
    )
    print(f"done {_one_line(st)}")
    return 0


def cmd_blocked(args: argparse.Namespace) -> int:
    st = _stage(args).blocked(
        args.reason, write_status_mirror=args.write_status_mirror
    )
    print(f"blocked {_one_line(st)}: {args.reason}")
    return 0


def cmd_fail(args: argparse.Namespace) -> int:
    st = _stage(args).fail(
        args.reason,
        if_dead_pid=args.if_dead_pid,
        if_needs_reclaim=getattr(args, "if_needs_reclaim", False),
        write_status_mirror=args.write_status_mirror,
    )
    print(f"failed {_one_line(st)}: {args.reason}")
    return 0


def cmd_events(args: argparse.Namespace) -> int:
    tail = args.tail
    events = _stage(args).events(
        tail=None if tail == 0 else tail,
        type=args.type,
    )
    if args.json:
        print(json.dumps(events, indent=2))
    else:
        for event in events:
            print(_one_line_event(event))
    return EXIT_OK


def cmd_status(args: argparse.Namespace) -> int:
    st = _stage(args).status()
    if args.json:
        print(json.dumps(st, indent=2))
    else:
        print(_one_line(st))
        hb_at = st.get("heartbeat_at")
        hb_age = st.get("heartbeat_age_seconds")
        if st.get("state") == "running" and hb_at and hb_age is not None:
            hb_display = f"{hb_at} (age {max(0, int(round(hb_age)))}s)"
        else:
            hb_display = f"{hb_at}"
        print(f"updated: {st.get('updated_at')}  heartbeat: {hb_display}")
        if st.get("result"):
            print(f"result: {json.dumps(st['result'])}")
        if st.get("error"):
            print(f"error: {json.dumps(st['error'])}")
    return state_exit_code(str(st.get("state")))


def cmd_wait(args: argparse.Namespace) -> int:
    needs_reclaim = bool(getattr(args, "needs_reclaim", False))
    if needs_reclaim and args.state != "terminal":
        raise BadArgsError(
            "wait --needs-reclaim cannot be combined with --state"
        )
    wanted = WAIT_WANT_NEEDS_RECLAIM if needs_reclaim else args.state
    stage_obj = _stage(args)
    try:
        st = stage_obj.wait(
            args.state,
            timeout=args.timeout,
            poll=args.poll,
            needs_reclaim=needs_reclaim,
        )
        state = str(st.get("state"))
        is_met = wait_condition_met(
            st, want=args.state, needs_reclaim=needs_reclaim
        )
        exit_code = (
            EXIT_OK
            if is_met
            else _wait_mismatch_exit_code(state, needs_reclaim=needs_reclaim)
        )
        outcome = "met" if is_met else "mismatch"
        if args.json:
            print(json.dumps(
                _wait_json_payload(
                    outcome=outcome,
                    wanted=wanted,
                    status=st,
                    exit_code=exit_code,
                    timed_out=False,
                    dir_path=str(stage_obj.dir),
                ),
                indent=2,
            ))
            return exit_code
        if is_met:
            label = wanted if needs_reclaim else state
            print(f"wait met: {label} {_one_line(st)}")
            return EXIT_OK
        # A different terminal state won first, or --needs-reclaim hit
        # terminal without reclaim: report a non-zero mismatch (SPEC §6).
        print(f"wait ended in {state} (wanted {wanted})", file=sys.stderr)
        return exit_code
    except WaitTimeout as exc:
        if args.json:
            print(json.dumps(
                _wait_json_payload(
                    outcome="timeout",
                    wanted=wanted,
                    status=exc.last_status,
                    exit_code=exc.exit_code,
                    timed_out=True,
                    dir_path=str(stage_obj.dir),
                    reason=str(exc),
                ),
                indent=2,
            ))
            return exc.exit_code
        raise


def cmd_clear_terminal(args: argparse.Namespace) -> int:
    st = _stage(args).clear_terminal(keep_stage=args.keep_stage)
    print(f"cleared {_one_line(st)}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    diag = _stage(args).diagnose(stale_after=args.stale_after)
    as_json = args.json or getattr(args, "format", None) == "json"
    if as_json:
        print(json.dumps(diag, indent=2))
    else:
        for problem in diag["problems"]:
            print(f"PROBLEM: {problem}")
        for warning in diag["warnings"]:
            msg = warning.get("message", str(warning)) if isinstance(warning, dict) else str(warning)
            print(f"WARNING: {msg}")
        if diag.get("summary"):
            print(diag["summary"])
    if getattr(args, "exit_reclaim", False) and diag.get("needs_reclaim"):
        return EXIT_RUNNING
    return EXIT_OK if diag["ok"] else EXIT_ERROR
