#!/bin/sh
# queue-orchestrator-smoke.sh — acceptance for examples/queue-orchestrator.sh.
#
# Exercises the queue consumer against an isolated temp --dir (never the real
# repo state) and exits 0 only if every step matches the contract. Requires
# `stage-signal` on PATH:
#   source .venv/bin/activate
#   ./examples/queue-orchestrator-smoke.sh
set -u

# NOTE: this smoke never commits, so bare `done` omits --git-head and inherits the start SHA (§13.30.3).
fail() { echo "QUEUE SMOKE FAIL: $1" >&2; exit 1; }
pass() { echo "QUEUE SMOKE OK: $1"; }

command -v stage-signal >/dev/null 2>&1 || fail "stage-signal not on PATH (activate venv / pip install -e .)"
command -v python3 >/dev/null 2>&1 || fail "python3 not on PATH"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/stage-signal-queue-smoke.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM

Q="$WORK/queue.md"
cat >"$Q" <<'EOF'
# smoke queue (markdown markers must parse as plain ids)
- [ ] s1
- [ ] s2
- [ ] s3
EOF

D="$WORK/.stage-signal"
QO="$PWD/examples/queue-orchestrator.sh"
[ -x "$QO" ] || fail "examples/queue-orchestrator.sh missing or not executable"

ST() { stage-signal --dir "$D" "$@"; }

ST init >/dev/null || fail "init"
pass "init"

# 1. s1 done with s2 next -> advance, exit 0.
ST start --stage s1 --session test --pid $$ >/dev/null || fail "start s1"
ST done --summary "s1 ok" >/dev/null || fail "done s1"
out="$("$QO" --queue "$Q" --dir "$D" --once 2>&1)" || fail "queue advance s1 should exit 0, got $?"
echo "$out" | grep -q "advance s1 done -> next s2" || fail "expected advance s1->s2, got: $out"
pass "done s1 advances to s2"

# 2. s2 running --once -> exit 10, never blocks.
ST start --stage s2 --session test --pid $$ >/dev/null || fail "start s2"
"$QO" --queue "$Q" --dir "$D" --once >/dev/null 2>&1
code=$?
[ "$code" -eq 10 ] || fail "running s2 --once should exit 10, got $code"
pass "running s2 --once -> exit 10"

# 3. s2 done -> advance to s3, earlier s1 reported superseded.
ST done --summary "s2 ok" >/dev/null || fail "done s2"
out="$("$QO" --queue "$Q" --dir "$D" --once 2>&1)" || fail "queue advance s2 should exit 0, got $?"
echo "$out" | grep -q "advance s2 done -> next s3" || fail "expected advance s2->s3, got: $out"
echo "$out" | grep -q "ok s1 (superseded by s2)" || fail "expected superseded s1, got: $out"
pass "done s2 advances to s3 with superseded s1"

# 4. s3 blocked --once -> exit 11.
ST start --stage s3 --session test --pid $$ >/dev/null || fail "start s3"
ST blocked --reason "need human" >/dev/null || fail "blocked s3"
"$QO" --queue "$Q" --dir "$D" --once >/dev/null 2>&1
code=$?
[ "$code" -eq 11 ] || fail "blocked s3 should exit 11, got $code"
pass "blocked s3 -> exit 11"

# 5. s3 failed (new attempt) -> exit 12.
ST start --stage s3 --session test --pid $$ >/dev/null || fail "restart s3"
ST fail --reason "boom" >/dev/null || fail "fail s3"
"$QO" --queue "$Q" --dir "$D" --once >/dev/null 2>&1
code=$?
[ "$code" -eq 12 ] || fail "failed s3 should exit 12, got $code"
pass "failed s3 -> exit 12"

# 6. s3 done (last) -> queue drained, exit 0.
ST start --stage s3 --session test --pid $$ >/dev/null || fail "restart s3 again"
ST done --summary "s3 ok" >/dev/null || fail "done s3"
out="$("$QO" --queue "$Q" --dir "$D" --once 2>&1)" || fail "drained queue should exit 0, got $?"
echo "$out" | grep -q "queue drained: s3 done (3/3)" || fail "expected drained, got: $out"
pass "done s3 drains queue"

# 7. Blocking wait: s2 running, background done -> advance, exit 0.
ST start --stage s2 --session test --pid $$ >/dev/null || fail "restart s2"
( sleep 1; ST done --summary "late ok" >/dev/null 2>&1 ) &
out="$("$QO" --queue "$Q" --dir "$D" --timeout 10 --poll 1 2>&1)" || fail "blocking wait should exit 0, got $?"
echo "$out" | grep -q "advance s2 done -> next s3" || fail "expected advance after wait, got: $out"
pass "blocking wait follows running s2 to done"

# 8. Queued --once -> exit 13 (fresh dir, before first start).
D2="$WORK/fresh/.stage-signal"
stage-signal --dir "$D2" init >/dev/null || fail "init fresh dir"
"$QO" --queue "$Q" --dir "$D2" --once >/dev/null 2>&1
code=$?
[ "$code" -eq 13 ] || fail "queued fresh dir should exit 13, got $code"
pass "queued fresh dir --once -> exit 13"

# 9. multi-cli-loop runner with --agent mock drains a fresh queue
Q_MOCK="$WORK/mock-queue.md"
cat >"$Q_MOCK" <<'EOF'
- m1
- m2
EOF
D_MOCK="$WORK/mock-stage/.stage-signal"
MCLO="$PWD/examples/multi-cli-loop.sh"
if [ -x "$MCLO" ]; then
  out="$("$MCLO" --agent mock --queue "$Q_MOCK" --dir "$D_MOCK" --timeout 5 2>&1)" || fail "multi-cli-loop mock should exit 0, got $?"
  echo "$out" | grep -q "queue drained: all milestones complete" || fail "expected drained in multi-cli-loop, got: $out"
  pass "multi-cli-loop runner with mock agent drains queue"
fi

echo "ALL QUEUE SMOKE CHECKS PASSED"
