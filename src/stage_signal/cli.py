"""stage-signal CLI: init/start/heartbeat/note/artifact/done/blocked/fail/status/wait/clear-terminal/doctor."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable, Optional, Sequence

from . import __version__
from .constants import (
    ENV_DIR,
    WAIT_DEFAULT_POLL,
    WAIT_DEFAULT_TIMEOUT,
    state_exit_code,
)
from .errors import BadArgsError, StageError, WaitTimeout
from .stage import WAIT_CHOICES, Stage, want_matches

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
    c.add_argument("--write-status-mirror", action="store_true", default=None)
    c.set_defaults(func=cmd_done)

    c = sub.add_parser("blocked", help="mark stage externally blocked")
    c.add_argument("--reason", required=True)
    c.add_argument("--write-status-mirror", action="store_true", default=None)
    c.set_defaults(func=cmd_blocked)

    c = sub.add_parser("fail", help="mark stage hard-failed")
    c.add_argument("--reason", required=True)
    c.add_argument("--write-status-mirror", action="store_true", default=None)
    c.set_defaults(func=cmd_fail)

    c = sub.add_parser("status", help="show current STATUS (exit code reflects state)")
    c.add_argument("--json", action="store_true", default=False)
    c.set_defaults(func=cmd_status)

    c = sub.add_parser("wait", help="poll until a state is reached")
    c.add_argument("--state", default="terminal", choices=list(WAIT_CHOICES))
    c.add_argument("--timeout", type=float, default=WAIT_DEFAULT_TIMEOUT)
    c.add_argument("--poll", type=float, default=WAIT_DEFAULT_POLL)
    c.add_argument("--json", action="store_true", default=False)
    c.set_defaults(func=cmd_wait)

    c = sub.add_parser(
        "clear-terminal", help="reset a terminal state back to queued"
    )
    c.set_defaults(func=cmd_clear_terminal)

    c = sub.add_parser("doctor", help="check stage dir health")
    c.add_argument("--stale-after", type=float, default=300.0, metavar="SEC",
                   help="warn on running heartbeat older than SEC (default: 300)")
    c.add_argument("--json", action="store_true", default=False)
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


def _one_line(status: dict[str, Any]) -> str:
    return (
        f"{status.get('state')} "
        f"{status.get('stage_name') or '-'} "
        f"(attempt {status.get('attempt')})"
    )


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
        args.reason, write_status_mirror=args.write_status_mirror
    )
    print(f"failed {_one_line(st)}: {args.reason}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    st = _stage(args).status()
    if args.json:
        print(json.dumps(st, indent=2))
    else:
        print(_one_line(st))
        print(f"updated: {st.get('updated_at')}  heartbeat: {st.get('heartbeat_at')}")
        if st.get("result"):
            print(f"result: {json.dumps(st['result'])}")
        if st.get("error"):
            print(f"error: {json.dumps(st['error'])}")
    return state_exit_code(str(st.get("state")))


def cmd_wait(args: argparse.Namespace) -> int:
    stage_obj = _stage(args)
    try:
        st = stage_obj.wait(args.state, timeout=args.timeout, poll=args.poll)
        state = str(st.get("state"))
        is_met = want_matches(args.state, state)
        exit_code = 0 if is_met else state_exit_code(state)
        outcome = "met" if is_met else "mismatch"
        if args.json:
            result = {
                "outcome": outcome,
                "wanted": args.state,
                "observed_state": state,
                "state": state,
                "exit_code": exit_code,
                "timeout": False,
                "stage_id": st.get("stage_id"),
                "dir": str(stage_obj.dir),
                "status": st,
            }
            print(json.dumps(result, indent=2))
            return exit_code
        if is_met:
            print(f"wait met: {state} {_one_line(st)}")
            return 0
        # A different terminal state won first: report its code (SPEC §6).
        print(f"wait ended in {state} (wanted {args.state})", file=sys.stderr)
        return exit_code
    except WaitTimeout as exc:
        if args.json:
            st = exc.last_status
            state = str(st.get("state")) if st else None
            result = {
                "outcome": "timeout",
                "wanted": args.state,
                "observed_state": state,
                "state": state,
                "exit_code": exc.exit_code,
                "timeout": True,
                "stage_id": st.get("stage_id") if st else None,
                "dir": str(stage_obj.dir),
                "status": st,
            }
            print(json.dumps(result, indent=2))
            return exc.exit_code
        raise


def cmd_clear_terminal(args: argparse.Namespace) -> int:
    st = _stage(args).clear_terminal()
    print(f"cleared {_one_line(st)}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    diag = _stage(args).diagnose(stale_after=args.stale_after)
    if args.json:
        print(json.dumps(diag, indent=2))
    else:
        for problem in diag["problems"]:
            print(f"PROBLEM: {problem}")
        for warning in diag["warnings"]:
            print(f"WARNING: {warning}")
        if diag["ok"]:
            st = diag["status"]
            print(f"OK: {st['state'] if st else 'uninitialized dir exists'}")
    return 0 if diag["ok"] else 1
