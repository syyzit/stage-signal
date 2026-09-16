#!/bin/sh
# orchestrator-watchdog.sh — minimal external poll loop for stage-signal.
#
# The orchestrator never scrapes agent output. It only reads:
#   stage-signal status --json
#   stage-signal wait --state WANT --timeout SEC
# then decides what to do next (enqueue the next stage, alert, stop).
#
# Usage:
#   ./examples/orchestrator-watchdog.sh [--dir PATH] [--state WANT] [--timeout SEC] [--poll SEC] [--once]
#
#   --dir PATH     stage dir (default: ./.stage-signal or $STAGE_SIGNAL_DIR)
#   --state WANT   done|blocked|failed|terminal (default: terminal)
#   --timeout SEC  wait timeout in seconds (default: 3600)
#   --poll SEC     poll interval in seconds (default: 5)
#   --once         single status check, no blocking wait (cron style)
#
# Exit code follows the observed-state contract (see README / docs/SPEC.md):
#   0 condition met, 10 running, 11 blocked, 12 failed,
#   13 queued, 14 wait timeout, 15 not initialized, 2 bad args.
#
# Requires the `stage-signal` entry point on PATH (see README: create a venv,
# then `pip install -e .`).
set -u

DIR=""
WANT="terminal"
TIMEOUT="3600"
POLL="5"
ONCE=0

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

if [ "$ONCE" = "1" ]; then
  # Single poll for cron/timer use: never blocks.
  describe
  exit $?
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
