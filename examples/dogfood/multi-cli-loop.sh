#!/bin/sh
# multi-cli-loop.sh — thin orchestrator loop driving agy, opencode, or mock agents.
#
# Thesis: stage-signal is the boring contract so an external loop can drive
# coding agents without scraping TUIs or chat transcripts. This script
# reuses examples/dogfood/queue-orchestrator.sh to inspect queue state and wait for
# terminal transitions.
#
# The ONLY difference between agents is the invocation command line:
#   agy:      agy -p "$PROMPT" --dangerously-skip-permissions --print-timeout "${TIMEOUT}s"
#   opencode: opencode run --dir "$REPO_ROOT" --auto -m "$MODEL" "$PROMPT"
#   mock:     (simulated agent for testing and verification)
# Everything else (working directory, stage signals, exit codes) is identical.
#
# Usage:
#   ./examples/dogfood/multi-cli-loop.sh [--agent agy|opencode|mock] [--queue FILE] [--dir PATH]
#                                [--prompts-dir DIR] [--timeout SEC] [--model MODEL] [--once]
#
# Exit codes follow the stage-signal contract:
#   0 queue drained / all done, 10 running, 11 blocked, 12 failed,
#   13 queued, 14 timeout, 15 not initialized, 2 bad args.
set -u

AGENT="agy"
QUEUE="examples/dogfood/sample-queue.md"
DIR=""
PROMPTS_DIR="prompts"
TIMEOUT="3600"
MODEL="google/gemini-2.5-pro"
ONCE=0

usage() {
  sed -n '2,/^set -u/p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --agent) AGENT="${2:?--agent needs agy|opencode|mock}"; shift 2 ;;
    --queue) QUEUE="${2:?--queue needs FILE}"; shift 2 ;;
    --dir) DIR="${2:?--dir needs PATH}"; shift 2 ;;
    --prompts-dir) PROMPTS_DIR="${2:?--prompts-dir needs DIR}"; shift 2 ;;
    --timeout) TIMEOUT="${2:?--timeout needs SEC}"; shift 2 ;;
    --model) MODEL="${2:?--model needs MODEL}"; shift 2 ;;
    --once) ONCE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "multi-cli-loop: unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QORCH="$SCRIPT_DIR/queue-orchestrator.sh"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
[ -f "$QUEUE" ] || [ ! -f "$SCRIPT_DIR/sample-queue.md" ] || QUEUE="$SCRIPT_DIR/sample-queue.md"

[ -x "$QORCH" ] || {
  echo "multi-cli-loop: queue-orchestrator.sh not found or not executable at $QORCH" >&2
  exit 1
}

command -v stage-signal >/dev/null 2>&1 || {
  echo "multi-cli-loop: stage-signal not on PATH (activate venv / pip install -e .)" >&2
  exit 1
}

command -v python3 >/dev/null 2>&1 || {
  echo "multi-cli-loop: python3 not on PATH" >&2
  exit 1
}

[ -r "$QUEUE" ] || {
  echo "multi-cli-loop: queue file not readable: $QUEUE" >&2
  exit 2
}

ST() {
  if [ -n "$DIR" ]; then
    stage-signal --dir "$DIR" "$@"
  else
    stage-signal "$@"
  fi
}

QO() {
  if [ -n "$DIR" ]; then
    "$QORCH" --queue "$QUEUE" --dir "$DIR" "$@"
  else
    "$QORCH" --queue "$QUEUE" "$@"
  fi
}

# Auto-initialize stage directory if not yet initialized
ST status --json >/dev/null 2>&1
st_init_code=$?
if [ "$st_init_code" -eq 15 ]; then
  ST init >/dev/null || { echo "multi-cli-loop: failed to initialize stage dir" >&2; exit 15; }
fi

# Helper to find prompt content for a given stage
get_prompt() {
  stage_name="$1"
  pfile1="$PROMPTS_DIR/prompt-$stage_name.md"
  pfile2="$PROMPTS_DIR/$stage_name.md"
  if [ -f "$pfile1" ]; then
    cat "$pfile1"
  elif [ -f "$pfile2" ]; then
    cat "$pfile2"
  else
    cat <<EOF
You are working ONE milestone in this repository: $stage_name.

Please complete the tasks for $stage_name.
When finished:
  stage-signal done --summary "completed $stage_name" --git-head \$(git rev-parse HEAD 2>/dev/null || echo "none")
If you encounter an external blocker:
  stage-signal blocked --reason "description of blocker"
If invariants or tests fail:
  stage-signal fail --reason "description of failure"
EOF
  fi
}

# Extract first stage from queue file
first_queue_stage() {
  python3 - "$QUEUE" <<'PY'
import re, sys
with open(sys.argv[1], encoding="utf-8") as fh:
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
        if tok and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", tok):
            print(tok)
            sys.exit(0)
sys.exit(1)
PY
}

# Main loop
while true; do
  q_out="$(QO --once 2>&1)"
  q_code=$?

  case "$q_code" in
    0)
      if echo "$q_out" | grep -q "queue drained"; then
        echo "multi-cli-loop: queue drained: all milestones complete"
        exit 0
      fi
      NEXT_STAGE="$(echo "$q_out" | sed -n 's/.*-> next //p')"
      if [ -z "$NEXT_STAGE" ]; then
        NEXT_STAGE="$(first_queue_stage)" || {
          echo "multi-cli-loop: could not determine next stage from queue" >&2
          exit 1
        }
      fi
      ;;
    10)
      # Currently running: wait for it
      if [ "$ONCE" = "1" ]; then
        echo "multi-cli-loop: stage running (once mode, exiting 10)"
        exit 10
      fi
      echo "multi-cli-loop: stage already running; waiting for terminal..."
      QO --timeout "$TIMEOUT"
      w_code=$?
      if [ "$w_code" -ne 0 ]; then exit "$w_code"; fi
      continue
      ;;
    13)
      # Fresh / queued dir without stage started: pick first stage
      NEXT_STAGE="$(first_queue_stage)" || {
        echo "multi-cli-loop: could not determine first stage from queue" >&2
        exit 1
      }
      ;;
    11)
      echo "multi-cli-loop: queue stopped: stage is BLOCKED (exit 11)" >&2
      exit 11
      ;;
    12)
      echo "multi-cli-loop: queue stopped: stage FAILED (exit 12)" >&2
      exit 12
      ;;
    *)
      echo "multi-cli-loop: unexpected queue state (exit $q_code): $q_out" >&2
      exit "$q_code"
      ;;
  esac

  echo "multi-cli-loop: starting milestone '$NEXT_STAGE' with agent '$AGENT'"
  ST start --stage "$NEXT_STAGE" --meta "cli=$AGENT" >/dev/null

  PROMPT_CONTENT="$(get_prompt "$NEXT_STAGE")"

  case "$AGENT" in
    agy)
      command -v agy >/dev/null 2>&1 || {
        echo "multi-cli-loop: 'agy' CLI not found on PATH" >&2
        exit 1
      }
      timeout_min="$((TIMEOUT / 60))"
      [ "$timeout_min" -gt 0 ] || timeout_min=1
      agy -p "$PROMPT_CONTENT" --dangerously-skip-permissions --print-timeout "${timeout_min}m"
      ;;
    opencode)
      command -v opencode >/dev/null 2>&1 || {
        echo "multi-cli-loop: 'opencode' CLI not found on PATH" >&2
        exit 1
      }
      opencode run --dir "$REPO_ROOT" --auto -m "$MODEL" "$PROMPT_CONTENT"
      ;;
    mock)
      # Mock agent: simulate work, issue heartbeat, and complete
      # NOTE: mock never commits, so omit --git-head inherits the start SHA (§13.30.3).
      ST heartbeat >/dev/null
      ST done --summary "mock completed $NEXT_STAGE" >/dev/null
      ;;
    *)
      echo "multi-cli-loop: unsupported agent '$AGENT'. Use agy, opencode, or mock." >&2
      exit 2
      ;;
  esac

  # Wait for terminal state through the queue orchestrator
  QO --timeout "$TIMEOUT"
  wait_code=$?
  if [ "$wait_code" -ne 0 ]; then
    echo "multi-cli-loop: milestone '$NEXT_STAGE' finished with non-zero exit code: $wait_code" >&2
    exit "$wait_code"
  fi

  if [ "$ONCE" = "1" ]; then
    echo "multi-cli-loop: single milestone pass completed (--once)"
    exit 0
  fi
done
