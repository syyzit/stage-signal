#!/bin/sh
# orchestrator-smoke.sh — product-owner acceptance for stage-signal.
#
# Runs the acceptance sequence from the public README in an isolated temp dir and
# exits 0 only if every step behaves per contract. Requires the
# `stage-signal` entry point on PATH (see README: install via venv,
# then `pip install -e .`).
#
#   source .venv/bin/activate
#   ./examples/orchestrator-smoke.sh
set -u

fail() { echo "SMOKE FAIL: $1" >&2; exit 1; }
pass() { echo "SMOKE OK: $1"; }

command -v stage-signal >/dev/null 2>&1 || fail "stage-signal not on PATH (activate venv / pip install -e .)"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/stage-signal-smoke.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM
cd "$WORK" || fail "cd temp dir"

ST() { stage-signal --dir "$WORK/.stage-signal" "$@"; }
STATE_OF() { ST status --json | python3 -c "import json,sys; print(json.load(sys.stdin)['state'])"; }

ST init >/dev/null || fail "init"
pass "init"

ST start --stage demo --session test --pid $$ >/dev/null || fail "start demo"
[ "$(STATE_OF)" = "running" ] || fail "expected running after start"
pass "start --stage demo -> running"

ST heartbeat >/dev/null || fail "heartbeat"
[ "$(STATE_OF)" = "running" ] || fail "expected running after heartbeat"
pass "heartbeat"

ST done --summary "ok" >/dev/null || fail "done"
[ "$(STATE_OF)" = "done" ] || fail "expected done after done"
pass "done -> done"

ST wait --state done --timeout 1 >/dev/null || fail "wait done should exit 0"
pass "wait --state done -> exit 0"

ST wait --needs-reclaim --timeout 1 >/dev/null 2>&1
code=$?
[ "$code" -eq 1 ] || fail "wait --needs-reclaim on done should exit 1, got $code"
pass "wait --needs-reclaim on done -> exit 1"

ST clear-terminal >/dev/null || fail "clear-terminal"
[ "$(STATE_OF)" = "queued" ] || fail "expected queued after clear-terminal"
pass "clear-terminal -> queued"

ST events --json --type clear_terminal --tail 1 >/dev/null || fail "events after clear-terminal"
pass "events --json --type clear_terminal"

ST start --stage demo2 --session test --pid $$ >/dev/null || fail "start demo2"
ST blocked --reason "external dependency unavailable" >/dev/null || fail "blocked"
[ "$(STATE_OF)" = "blocked" ] || fail "expected blocked after blocked"
pass "blocked -> blocked"

ST wait --state terminal --timeout 1 >/dev/null
# wait for a *specific* state that will never come must report the
# terminal state that actually won: run wait --state done against blocked.
ST wait --state done --timeout 1 >/dev/null 2>&1
code=$?
[ "$code" -eq 11 ] || fail "wait --state done on blocked should exit 11, got $code"
pass "wait mismatch reports blocked -> exit 11"

ST status --json >/dev/null 2>&1
code=$?
[ "$code" -eq 11 ] || fail "status on blocked should exit 11, got $code"
pass "status on blocked -> exit 11"

ST doctor >/dev/null || fail "doctor should exit 0 on healthy dir"
pass "doctor -> exit 0"

ST start --stage reclaim --pid 999999999 >/dev/null || fail "start reclaim dead pid"
ST wait --needs-reclaim --timeout 2 --poll 0.1 >/dev/null || fail "wait --needs-reclaim on DEAD_PID should exit 0"
pass "wait --needs-reclaim on DEAD_PID -> exit 0"

ST reclaim --reason "smoke reclaim dead pid" >/dev/null || fail "reclaim on DEAD_PID"
[ "$(STATE_OF)" = "queued" ] || fail "expected queued after reclaim"
NAME="$(ST status --json | python3 -c "import json,sys; print(json.load(sys.stdin).get('stage_name'))")"
[ "$NAME" = "None" ] || fail "expected idle queued (stage_name null) after reclaim, got $NAME"
pass "reclaim --reason -> idle queued"

ST events --json --type failed --tail 1 >/dev/null || fail "events after reclaim (failed)"
ST events --json --type clear_terminal --tail 1 >/dev/null || fail "events after reclaim (clear_terminal)"
pass "events after reclaim"

ST start --stage reclaim2 --pid $$ >/dev/null || fail "start reclaim2 healthy"
ST reclaim --reason "should refuse" >/dev/null 2>&1
code=$?
[ "$code" -eq 3 ] || fail "reclaim on healthy running should exit 3, got $code"
[ "$(STATE_OF)" = "running" ] || fail "healthy reclaim must not mutate"
pass "reclaim on healthy running -> exit 3, no mutation"

echo "ALL SMOKE CHECKS PASSED"
