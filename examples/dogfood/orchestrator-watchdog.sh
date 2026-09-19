#!/bin/sh
# orchestrator-watchdog.sh — minimal external poll loop for stage-signal.
#
# The orchestrator never scrapes agent output. It only reads:
#   stage-signal status --json
#   stage-signal wait --state WANT --timeout SEC
#   stage-signal wait --needs-reclaim [--timeout SEC] [--poll SEC]
#   stage-signal events [--tail N] [--type TYPE] [--json]
# then decides what to do next (enqueue the next stage, alert, stop).
# Reclaim loop (no doctor sleep):
#   wait --needs-reclaim → reclaim --kill (or fail --if-needs-reclaim) → events
# After reclaim / clear-terminal, audit via `events`
# (do not scrape events.jsonl with tail/jq).
#
# Usage:
#   ./examples/dogfood/orchestrator-watchdog.sh [--dir PATH] [--state WANT] [--timeout SEC] [--poll SEC] [--once]
#   ./examples/dogfood/orchestrator-watchdog.sh [--dir PATH] --wait-reclaim [--timeout SEC] [--poll SEC]
#
#   --dir PATH       stage dir (default: ./.stage-signal or $STAGE_SIGNAL_DIR)
#   --state WANT     done|blocked|failed|terminal (default: terminal)
#   --timeout SEC    wait timeout in seconds (default: 3600)
#   --poll SEC       poll interval in seconds (default: 5)
#   --once           single status check, no blocking wait (cron style)
#   --doctor-reclaim, --needs-reclaim
#                    snapshot reclaim on needs_reclaim (DEAD_PID or STALE_HEARTBEAT)
#                    via reclaim --keep-failed (use with --once)
#   --wait-reclaim   block on wait --needs-reclaim, then reclaim --kill
#                    --keep-failed (terminate the alive recorded PID, then
#                    fail without clear-terminal; cannot combine with --once;
#                    use --once --doctor-reclaim for a snapshot; without
#                    --kill on reclaim no signal is sent)
#
# Exit code follows the observed-state contract (see README / docs/SPEC.md):
#   0 condition met, 10 running, 11 blocked, 12 failed,
#   13 queued, 14 wait timeout, 15 not initialized, 1 wait --needs-reclaim
#   ended in done without reclaim, 2 bad args.
#
# Reclaim termination (`--kill`) notes:
#   - Kill fires only after the needs_reclaim guard passes; a rejected guard
#     (exit 3) never signals.
#   - Only a valid positive alive recorded PID is signalled; dead, null,
#     invalid, or unknown-liveness PIDs are never signalled.
#   - Best effort: SIGTERM, wait up to 1 second polling liveness every 50ms,
#     then SIGKILL if still alive. On Windows SIGTERM terminates; SIGKILL
#     falls back to SIGTERM when unavailable.
#   - Permission/OS errors warn on stderr and reclaim continues (fail+clear
#     still happens). No guarantee the worker stopped; verify before relaunch.
#
# Requires the `stage-signal` entry point on PATH (see README: create a venv,
# then `pip install -e .`).
set -u

DIR=""
WANT="terminal"
TIMEOUT="3600"
POLL="5"
ONCE=0
DOCTOR_RECLAIM=0
WAIT_RECLAIM=0

usage() {
  sed -n '2,/^set -u/p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dir) DIR="${2:?--dir needs PATH}"; shift 2 ;;
    --state) WANT="${2:?--state needs WANT}"; shift 2 ;;
    --timeout) TIMEOUT="${2:?--timeout needs SEC}"; shift 2 ;;
    --poll) POLL="${2:?--poll needs SEC}"; shift 2 ;;
    --once) ONCE=1; shift ;;
    --doctor-reclaim|--needs-reclaim) DOCTOR_RECLAIM=1; shift ;;
    --wait-reclaim) WAIT_RECLAIM=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "orchestrator-watchdog: unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

command -v stage-signal >/dev/null 2>&1 || {
  echo "orchestrator-watchdog: stage-signal not on PATH (activate venv / pip install -e .)" >&2
  exit 1
}

ST() {
  if [ -n "$DIR" ]; then
    stage-signal --dir "$DIR" "$@"
  else
    stage-signal "$@"
  fi
}

# Print one human line: "<state> <stage> (attempt N)".
# Exit code propagates `status`' observing code (0/10/11/12/13/15),
# so --once can be used directly in shell `if` / cron checks.
# Note: non-zero observing codes (10/11/12/13) still carry a valid
# snapshot, so the line is printed before returning the code.
describe() {
  local tmp st_code pcode
  tmp="$(mktemp "${TMPDIR:-/tmp}/stage-signal-watchdog.XXXXXX")" || return 1
  ST status --json >"$tmp"
  st_code=$?
  if [ -s "$tmp" ]; then
    python3 -c "
import json, sys
try:
    with open(sys.argv[1], encoding='utf-8') as fh:
        st = json.load(fh)
except Exception as exc:
    print(f'unparseable STATUS: {exc}', file=sys.stderr)
    sys.exit(1)
print('%s %s (attempt %s)' % (st.get('state'), st.get('stage_name') or '-', st.get('attempt')))
" "$tmp"
    pcode=$?
    rm -f "$tmp"
    if [ "$pcode" -ne 0 ]; then
      return 1
    fi
    return "$st_code"
  fi
  rm -f "$tmp"
  return "$st_code"
}

# Opt-in reclaim for needs_reclaim (default off): run `doctor --json` and,
# when `needs_reclaim` is true (DEAD_PID or STALE_HEARTBEAT while still
# `running`), call `reclaim --reason TEXT --keep-failed` (guarded reclaim,
# SPEC §Terminal). The guard refuses (exit 3, no mutation) if needs_reclaim
# is false under the lock, and never mutates outside `running`; `doctor` itself
# stays advisory-only. Aligns `--once --doctor-reclaim` (and `--once --needs-reclaim`)
# with full `needs_reclaim` semantics (matching `--wait-reclaim`).
# Exit codes:
#   0 no reclaim needed
#   1 doctor failed to produce JSON (no reclaim attempted)
#   12 reclaim performed; stage is now `failed`
#   3 guard refused (needs_reclaim false under lock) — no mutation
#
# Manual check (reclaim path):
#   stage-signal --dir .stage-signal init
#   stage-signal --dir .stage-signal start --stage t1 --pid 999999999
#   ./examples/dogfood/orchestrator-watchdog.sh --dir .stage-signal --once --doctor-reclaim
#   # -> exit 12, STATUS.json state=failed, one `failed` event appended
#   # Repeat: exit 12 (no reclaim needed; --once observes failed), no new event
doctor_reclaim() {
  local tmp rc reason
  tmp="$(mktemp "${TMPDIR:-/tmp}/stage-signal-watchdog.XXXXXX")" || return 1
  if ! ST doctor --json >"$tmp" || [ ! -s "$tmp" ]; then
    rm -f "$tmp"
    echo "orchestrator-watchdog: doctor --json failed; refusing to reclaim" >&2
    return 1
  fi
  reason="$(python3 -c "
import json, sys
try:
    with open(sys.argv[1], encoding='utf-8') as fh:
        diag = json.load(fh)
except Exception as exc:
    print(f'unparseable doctor output: {exc}', file=sys.stderr)
    sys.exit(1)
if diag.get('needs_reclaim') is not True:
    sys.exit(0)
codes = []
for w in diag.get('warnings', []):
    c = w.get('code')
    if c == 'DEAD_PID':
        pid = w.get('detail', {}).get('pid')
        codes.append(f'DEAD_PID pid={pid}' if pid else 'DEAD_PID')
    elif c == 'STALE_HEARTBEAT':
        codes.append('STALE_HEARTBEAT')
print(' or '.join(codes) if codes else 'DEAD_PID or STALE_HEARTBEAT')
" "$tmp")"
  rc=$?
  rm -f "$tmp"
  [ "$rc" -eq 0 ] || return 1
  if [ -z "$reason" ]; then
    return 0
  fi
  echo "orchestrator-watchdog: needs_reclaim ($reason); reclaiming via reclaim --keep-failed" >&2
  if ST reclaim --reason "reclaimed by orchestrator-watchdog: needs_reclaim ($reason)" --keep-failed; then
    echo "orchestrator-watchdog: stage reclaimed as failed" >&2
    # First-class audit (newest last). Do not scrape events.jsonl.
    ST events --tail 20 --type failed >&2 || true
    return 12
  else
    rc=$?
  fi
  echo "orchestrator-watchdog: reclaim refused or failed (exit $rc); no mutation" >&2
  return "$rc"
}

if [ "$WAIT_RECLAIM" = "1" ] && [ "$ONCE" = "1" ]; then
  echo "orchestrator-watchdog: --wait-reclaim cannot be combined with --once (use --once --doctor-reclaim for a snapshot)" >&2
  exit 2
fi

if [ "$WAIT_RECLAIM" = "1" ]; then
  # First-class reclaim loop: no doctor sleep.
  #   wait --needs-reclaim → reclaim --kill --keep-failed → events
  # --kill best-effort terminates the alive recorded PID first (SIGTERM, wait
  # up to 1s polling 50ms, SIGKILL if needed) after the guard passes; dead,
  # null, invalid, or unknown-liveness PIDs are never signalled; permission/
  # OS errors warn on stderr and fail+clear still proceeds. Only the recorded
  # PID is targeted (not a process group or descendants); PID reuse cannot be
  # excluded and termination is not guaranteed, so verify the worker is gone
  # before relaunching. clear-terminal / restart is left to the caller (or run
  # after this exits 12).
  echo "orchestrator-watchdog: waiting for needs_reclaim timeout=${TIMEOUT}s poll=${POLL}s" >&2
  if ST wait --needs-reclaim --timeout "$TIMEOUT" --poll "$POLL"; then
    echo "orchestrator-watchdog: needs_reclaim; reclaiming via reclaim --kill --keep-failed" >&2
    if ST reclaim --reason "reclaimed by orchestrator-watchdog: needs_reclaim (DEAD_PID or STALE_HEARTBEAT)" --kill --keep-failed; then
      echo "orchestrator-watchdog: stage reclaimed as failed" >&2
      ST events --tail 20 --type failed >&2 || true
      describe || true
      exit 12
    else
      rc=$?
      echo "orchestrator-watchdog: reclaim refused or failed (exit $rc); no mutation" >&2
      exit "$rc"
    fi
  else
    wait_code=$?
    describe >&2 2>/dev/null || true
    exit "$wait_code"
  fi
fi

if [ "$ONCE" = "1" ]; then
  # Single poll for cron/timer use: never blocks.
  describe
  once_code=$?
  if [ "$DOCTOR_RECLAIM" = "1" ]; then
    doctor_reclaim
    reclaim_code=$?
    [ "$reclaim_code" -eq 0 ] || exit "$reclaim_code"
  fi
  exit "$once_code"
fi

echo "orchestrator-watchdog: waiting for state=$WANT timeout=${TIMEOUT}s poll=${POLL}s" >&2
if ST wait --state "$WANT" --timeout "$TIMEOUT" --poll "$POLL"; then
  # Condition met (wait exit 0): report the winning snapshot, keep exit 0
  # even when the terminal state itself observes as non-zero (e.g. failed).
  describe || true
  exit 0
else
  wait_code=$?
  # wait already printed the mismatch/timeout reason to stderr;
  # show the latest snapshot (best-effort) so logs carry stage identity.
  describe >&2 2>/dev/null || true
  exit "$wait_code"
fi
