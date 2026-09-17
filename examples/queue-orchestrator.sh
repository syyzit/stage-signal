#!/bin/sh
# queue-orchestrator.sh — minimal multi-stage queue consumer for stage-signal.
#
# Thesis: an external loop advances milestones using ONLY stage-signal
# (status/wait/exit codes). This script NEVER reads agent logs, chat
# transcripts, TUI state, or OpenCode DBs. It only calls:
#   stage-signal status --json
#   stage-signal wait --state terminal --timeout SEC --poll SEC
#   stage-signal wait --needs-reclaim --timeout SEC --poll SEC  (reclaim path)
# and maps the observed state to an exit code (see docs/SPEC.md §7).
#
# Queue file format (see examples/sample-queue.md):
#   - one stage id per line; blank lines and `#` comments ignored
#   - leading markdown markers (`- `, `* `, `N. `, `- [ ]`, `- [x]`) and
#     surrounding `**` / backticks are stripped, so `.md` checklists parse
#     as plain lists.
#
# Model: one stage-signal dir holds the CURRENT stage; the queue file is the
# plan. Walk order top-to-bottom:
#   - entries before the current stage: already superseded, reported as `ok`
#   - current stage `done`: advance — report `advance <cur> done -> next <n>`
#     (or `queue drained` when last) and exit 0. The caller enqueues the next
#     agent with `stage-signal start --stage <n>`; this script never starts
#     agent work itself.
#   - current stage `blocked`/`failed`: stop for human/agent fix, exit 11/12.
#   - current stage `running`/`queued`: `wait` for terminal (blocking), or
#     with `--once` exit immediately with 10/13 for cron-style re-polling.
#     Stuck running (DEAD_PID / STALE) is not this script's job: use
#     `wait --needs-reclaim` → `fail --if-needs-reclaim` (see
#     orchestrator-watchdog.sh --wait-reclaim), not a doctor sleep loop.
#   - current stage not in queue (or no stage yet): act on status alone.
#
# How a bot calls it:
#   Blocking overnight loop (one shot, waits up to 1h):
#     ./examples/queue-orchestrator.sh --queue examples/sample-queue.md
#   Cron every 5 minutes (never blocks; switch on exit code):
#     ./examples/queue-orchestrator.sh --queue examples/sample-queue.md --once
#     # 0 = advanced/drained (enqueue next or sleep), 10/13 = still working
#     # (re-poll), 11/12 = page human, 14 = wait timeout, 15 = not initialized.
#   Example crontab:
#     */5 * * * * cd /path/to/repo && ./examples/queue-orchestrator.sh --queue examples/sample-queue.md --once >>/tmp/queue-orch.log 2>&1
#   Grok Bot / watchdog (every ~15m, same contract, stage-signal only):
#     ./examples/queue-orchestrator.sh --queue examples/sample-queue.md --dir .stage-signal --once
#
# Usage:
#   ./examples/queue-orchestrator.sh --queue FILE [--dir PATH] [--timeout SEC] [--poll SEC] [--once]
#
#   --queue FILE   queue file, one stage id per line (required)
#   --dir PATH     stage dir (default: ./.stage-signal or $STAGE_SIGNAL_DIR)
#   --timeout SEC  wait timeout in seconds (default: 3600)
#   --poll SEC     poll interval in seconds (default: 5)
#   --once         single pass, never blocks (cron style)
#
# Exit code follows the observed-state contract (SPEC §7):
#   0 advanced/drained/wait-met, 10 running, 11 blocked, 12 failed,
#   13 queued (or next not started), 14 wait timeout, 15 not initialized,
#   1 generic/corrupt, 2 bad args.
#
# Requires `stage-signal` and `python3` on PATH (python3 is used only to
# parse STATUS.json and the queue file; no third-party modules).
set -u

QUEUE=""
DIR=""
TIMEOUT="3600"
POLL="5"
ONCE=0

usage() {
  sed -n '2,/^set -u/p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --queue) QUEUE="${2:?--queue needs FILE}"; shift 2 ;;
    --dir) DIR="${2:?--dir needs PATH}"; shift 2 ;;
    --timeout) TIMEOUT="${2:?--timeout needs SEC}"; shift 2 ;;
    --poll) POLL="${2:?--poll needs SEC}"; shift 2 ;;
    --once) ONCE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "queue-orchestrator: unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[ -n "$QUEUE" ] || { echo "queue-orchestrator: --queue FILE is required" >&2; usage >&2; exit 2; }
[ -r "$QUEUE" ] || { echo "queue-orchestrator: queue file not readable: $QUEUE" >&2; exit 2; }

command -v stage-signal >/dev/null 2>&1 || {
  echo "queue-orchestrator: stage-signal not on PATH (activate venv / pip install -e .)" >&2
  exit 1
}
command -v python3 >/dev/null 2>&1 || {
  echo "queue-orchestrator: python3 not on PATH (needed to read STATUS.json)" >&2
  exit 1
}

ST() {
  if [ -n "$DIR" ]; then
    stage-signal --dir "$DIR" "$@"
  else
    stage-signal "$@"
  fi
}

WORK_D=""
cleanup() { [ -z "$WORK_D" ] || rm -rf "$WORK_D"; }
trap 'cleanup' EXIT INT TERM
WORK_D="$(mktemp -d "${TMPDIR:-/tmp}/stage-signal-queue.XXXXXX")" || exit 1
QNORM="$WORK_D/queue.ids"
SNAP="$WORK_D/status.json"

# Normalize the queue file to one bare stage id per line.
python3 - "$QUEUE" >"$QNORM" <<'PY'
import re, sys
path = sys.argv[1]
out = []
with open(path, encoding="utf-8") as fh:
    for raw in fh:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = re.sub(r"^[-*+]\s+(\[[ xX]\]\s+)?", "", line)
        line = re.sub(r"^\d+[.)]\s+", "", line)
        line = re.sub(r"^\[[ xX]\]\s+", "", line)
        if not line or line.startswith("#"):
            continue
        tok = line.split()[0].strip("*_`'\"")
        tok = re.sub(r"[,.:;]+$", "", tok).strip("*_`'\"")
        if not tok or tok.startswith("#"):
            continue
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", tok):
            m = re.search(r"[A-Za-z0-9][A-Za-z0-9._-]*", line)
            if not m:
                continue
            tok = m.group(0)
        out.append(tok)
for tid in out:
    print(tid)
PY
[ $? -eq 0 ] || { echo "queue-orchestrator: failed to parse queue file: $QUEUE" >&2; exit 1; }
[ -s "$QNORM" ] || { echo "queue-orchestrator: empty queue (no stage ids in $QUEUE)" >&2; exit 2; }

TOTAL="$(wc -l <"$QNORM" | tr -d ' ')"
IDS="$(cat "$QNORM")"

# Fetch current snapshot: sets CUR_STAGE / CUR_STATE, returns status exit code.
CUR_STAGE=""
CUR_STATE=""
fetch_snapshot() {
  rm -f "$SNAP"
  ST status --json >"$SNAP" 2>/dev/null
  code=$?
  if [ "$code" -eq 15 ]; then
    echo "queue-orchestrator: stage dir not initialized (run stage-signal init)" >&2
    return 15
  fi
  if [ "$code" -ne 0 ] && [ "$code" -ne 10 ] && [ "$code" -ne 11 ] && [ "$code" -ne 12 ] && [ "$code" -ne 13 ]; then
    echo "queue-orchestrator: status failed (exit $code); see stage-signal output" >&2
    ST status --json >&2 2>/dev/null || true
    return "$code"
  fi
  parsed="$(python3 - "$SNAP" <<'PY'
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        st = json.load(fh)
except Exception as exc:
    print(f"unparseable STATUS: {exc}", file=sys.stderr)
    sys.exit(1)
stage = st.get("stage_name") or ""
state = st.get("state") or ""
print(f"{stage}\t{state}")
PY
)"
  [ $? -eq 0 ] || return 1
  CUR_STAGE="${parsed%%	*}"
  CUR_STATE="${parsed#*	}"
  return "$code"
}

fetch_snapshot
snap_code=$?
if [ "$snap_code" -ne 0 ] && [ "$snap_code" -ne 10 ] && [ "$snap_code" -ne 11 ] && [ "$snap_code" -ne 12 ] && [ "$snap_code" -ne 13 ]; then
  exit "$snap_code"
fi

# Locate current stage in queue (1-indexed; 0 = not present).
CUR_POS=0
POS=0
# shellcheck disable=SC2086
for _q in $IDS; do
  POS=$((POS + 1))
  if [ "$_q" = "$CUR_STAGE" ]; then CUR_POS=$POS; break; fi
done

nth_id() {
  want=$1
  _p=0
  # shellcheck disable=SC2086
  for _q in $IDS; do
    _p=$((_p + 1))
    if [ "$_p" -eq "$want" ]; then printf '%s' "$_q"; return 0; fi
  done
  return 1
}

# Report entries superseded by the current stage (already advanced past).
report_superseded() {
  _p=0
  # shellcheck disable=SC2086
  for _q in $IDS; do
    _p=$((_p + 1))
    if [ "$_p" -lt "$CUR_POS" ]; then
      echo "ok $_q (superseded by $CUR_STAGE)"
    else
      break
    fi
  done
}

dir_flag() {
  if [ -n "$DIR" ]; then printf ' --dir %s' "$DIR"; else printf ''; fi
}

handle_terminal_done() {
  NEXT=""
  if [ "$CUR_POS" -gt 0 ] && [ "$CUR_POS" -lt "$TOTAL" ]; then
    NEXT="$(nth_id $((CUR_POS + 1)))"
  fi
  if [ "$CUR_POS" -gt 0 ]; then
    report_superseded
  fi
  if [ -z "$NEXT" ]; then
    if [ "$CUR_POS" -gt 0 ]; then
      echo "queue drained: $CUR_STAGE done ($CUR_POS/$TOTAL)"
    else
      echo "advance $CUR_STAGE done (not in queue; nothing to enqueue)"
    fi
    exit 0
  fi
  echo "advance $CUR_STAGE done -> next $NEXT"
  # shellcheck disable=SC2059
  printf 'next action: stage-signal%s start --stage %s\n' "$(dir_flag)" "$NEXT"
  exit 0
}

handle_terminal_stop() {
  # $1 = exit code (11 blocked / 12 failed)
  code=$1
  if [ "$CUR_POS" -gt 0 ]; then
    report_superseded
  fi
  echo "stop $CUR_STAGE $CUR_STATE (needs human/agent fix; queue halts here)"
  exit "$code"
}

handle_waitable() {
  # $1 = observing code (10 running / 13 queued)
  code=$1
  if [ "$CUR_POS" -gt 0 ]; then
    report_superseded
  fi
  if [ "$ONCE" = "1" ]; then
    echo "wait $CUR_STAGE $CUR_STATE (re-poll; agent working)"
    exit "$code"
  fi
  _label="$CUR_STAGE"
  [ -n "$_label" ] || _label="-"
  echo "queue-orchestrator: waiting for $_label terminal timeout=${TIMEOUT}s poll=${POLL}s" >&2
  if ST wait --state terminal --timeout "$TIMEOUT" --poll "$POLL"; then
    fetch_snapshot
    _nc=$?
    if [ "$_nc" -ne 0 ] && [ "$_nc" -ne 10 ] && [ "$_nc" -ne 11 ] && [ "$_nc" -ne 12 ] && [ "$_nc" -ne 13 ]; then
      exit "$_nc"
    fi
    case "$CUR_STATE" in
      done) handle_terminal_done ;;
      blocked) handle_terminal_stop 11 ;;
      failed) handle_terminal_stop 12 ;;
      *) echo "wait $CUR_STAGE $CUR_STATE (re-poll)" ; exit "$_nc" ;;
    esac
  else
    _wc=$?
    ST status --json 2>/dev/null | python3 -c "import json,sys; st=json.load(sys.stdin); print('%s %s (attempt %s)' % (st.get('state'), st.get('stage_name') or '-', st.get('attempt')))" >&2 2>/dev/null || true
    exit "$_wc"
  fi
}

case "$CUR_STATE" in
  done)
    if [ "$CUR_POS" -eq 0 ]; then
      _show="$CUR_STAGE"
      [ -n "$_show" ] || _show="-"
      echo "queue-orchestrator: current stage '$_show' not in queue ($TOTAL entries); acting on status alone" >&2
    fi
    handle_terminal_done
    ;;
  blocked)
    if [ "$CUR_POS" -eq 0 ]; then
      echo "queue-orchestrator: current stage '$CUR_STAGE' not in queue ($TOTAL entries); acting on status alone" >&2
    fi
    handle_terminal_stop 11
    ;;
  failed)
    if [ "$CUR_POS" -eq 0 ]; then
      echo "queue-orchestrator: current stage '$CUR_STAGE' not in queue ($TOTAL entries); acting on status alone" >&2
    fi
    handle_terminal_stop 12
    ;;
  running)
    if [ "$CUR_POS" -eq 0 ]; then
      _show="$CUR_STAGE"
      [ -n "$_show" ] || _show="-"
      echo "queue-orchestrator: current stage '$_show' not in queue ($TOTAL entries); acting on status alone" >&2
    fi
    handle_waitable 10
    ;;
  queued)
    if [ "$CUR_POS" -eq 0 ]; then
      _show="$CUR_STAGE"
      [ -n "$_show" ] || _show="-"
      echo "queue-orchestrator: current stage '$_show' not in queue ($TOTAL entries); acting on status alone" >&2
    fi
    handle_waitable 13
    ;;
  *)
    echo "queue-orchestrator: unknown state '$CUR_STATE' for stage '$CUR_STAGE'" >&2
    exit 1
    ;;
esac
