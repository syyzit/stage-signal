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

ST clear-terminal >/dev/null || fail "clear-terminal"
[ "$(STATE_OF)" = "queued" ] || fail "expected queued after clear-terminal"
pass "clear-terminal -> queued"

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

echo "ALL SMOKE CHECKS PASSED"
