# Caller Guide — External Integration Patterns

`stage-signal` is a **thin stage lifecycle contract**: an on-disk directory (`.stage-signal/`), normalized CLI subcommands, deterministic exit codes, and a Python client library.

It is **not** an agent orchestrator, task queue, or multi-agent coordinator. External callers (CI runners, cron jobs, supervisor daemons, agent wrappers, or queuing harnesses) drive and observe stages through three standard patterns:

1. **Synchronous wait:** Block until a stage concludes (`wait --state terminal`).
2. **Health watchdog:** Reactively wait for worker failure and recover (`wait --needs-reclaim` → `reclaim --kill`).
3. **Agent wrapper:** Manage the worker lifecycle (`init` → `start` → work → `done`).

---

## 1. Synchronous Wait (CI Runners & Step Supervisors)

External callers that launch a background worker or monitor an existing stage can block synchronously until execution finishes.

### The Loop

```bash
# Clear any terminal state left by the *previous* stage first — otherwise it
# satisfies the wait below instantly (see "Stale-terminal race"):
stage-signal clear-terminal || true

# ... launch the worker for this stage here ...

# Block until the stage reaches any terminal state (done, blocked, or failed).
# --state terminal treats all three as "met" and exits 0, so branch on the
# observed state, not on the exit code:
OBSERVED=$(stage-signal wait --json --state terminal --timeout 3600 --poll 5)
EXIT_CODE=$?

if [ "$EXIT_CODE" -eq 14 ]; then
  echo "Timed out waiting for stage completion"
  exit 14
fi

case "$(printf '%s' "$OBSERVED" | python3 -c 'import json,sys; print(json.load(sys.stdin)["state"])')" in
  done)
    echo "Stage completed successfully (done)"
    ;;
  blocked)
    echo "Stage paused: external blocker encountered (blocked)"
    stage-signal status --json
    ;;
  failed)
    echo "Stage failed (failed)"
    stage-signal events --tail 10
    ;;
esac
```

To have the **exit code alone** distinguish outcomes, wait for a specific state
instead — `wait --state done` exits `0` on `done`, `11` if `blocked` won, `12`
if `failed` won, and `14` on timeout:

```bash
stage-signal wait --state done --timeout 3600 --poll 5
case "$?" in
  0)  echo "done" ;;
  11) echo "blocked"; stage-signal status --json ;;
  12) echo "failed"; stage-signal events --tail 10 ;;
  14) echo "timed out" ;;
esac
```

### Key Semantics

- **`--state terminal` exits `0` for all three terminal states.** `done`, `blocked` and `failed` all resolve to `outcome: met` (SPEC §13.38), so a `terminal` wait cannot tell you *which* one happened from its exit code — read `state` from `wait --json` or `status --json`. Only `14` (timeout) is distinguishable this way.
- **Targeting specific states gives you distinguishable codes.** `stage-signal wait --state done` waits specifically for `done`; if the stage instead terminates in `blocked` or `failed`, `wait` reports the mismatch and exits with that terminal state's code (`11` or `12`) (SPEC §13.4, §13.38).
- **Reading snapshots:** Call `stage-signal status --json` or `stage-signal events --json --tail 20` to inspect outcome details without parsing unstructured logs.
- **Stale-terminal race — clear before you launch:** `wait` is scoped to the *directory*, not to a stage. A leftover terminal state from the **previous** stage satisfies `wait --state terminal` immediately, so an orchestrator that launches a worker and waits can be told "done" for work that never started. Before launching the next worker, run `stage-signal clear-terminal` (resets a terminal state back to idle `queued`), or read `stage_id` from `wait --json` / `status --json` and assert it matches the stage you launched. The same caveat applies to `status`.
- **`done` is legal from idle `queued`:** A wrapper that dies before `start`, or an operator running in the wrong directory, produces `state: done` with `stage_id: null` and `pid: null` at exit `0` (deliberate, SPEC §13.30). Combined with the race above, an orchestrator can observe a `done` nobody earned — so assert `stage_id` (and, where it matters, `result.git_head`) rather than trusting `state` alone.

---

## 2. Health Watchdog (Supervisor Daemon & Recovery)

Watchdogs monitor worker liveness. Instead of polling `doctor` in a busy loop or sleeping arbitrarily, watchdogs use the reactive `wait --needs-reclaim` observer.

### The Loop

```bash
# 1. Block reactively until needs_reclaim is detected (or stage finishes cleanly):
if stage-signal wait --needs-reclaim --timeout 3600 --poll 5; then
  # Exit 0 means needs_reclaim is TRUE (DEAD_PID or STALE_HEARTBEAT while running)
  echo "Worker died or went stale; executing guarded recovery..."

  # 2. Reclaim: terminate the recorded PID (if still alive) and reset to queued:
  stage-signal reclaim \
    --reason "Watchdog detected dead or stale worker" \
    --kill
else
  CODE=$?
  if [ "$CODE" -eq 1 ]; then
    # Exit 1 means stage reached done normally without needing reclaim
    echo "Stage finished cleanly; no recovery needed."
  elif [ "$CODE" -eq 14 ]; then
    echo "Watchdog wait timed out."
  fi
fi
```

### Key Semantics

- **No busy polling:** `wait --needs-reclaim` polls under shared lock and exits `0` immediately once `needs_reclaim` is true (`DEAD_PID` or `STALE_HEARTBEAT` while in `running`). If the stage terminates normally into `done`, it exits `1` (mismatch).
- **Guarded atomic reclaim:** `stage-signal reclaim` verifies `needs_reclaim` under exclusive lock before mutating. If the worker recovered or completed in a race, reclaim refuses with exit `3` (illegal transition) and does not mutate.
- **Process signaling (`--kill`):** When `--kill` is passed, `reclaim` signals the recorded PID (SIGTERM, waits up to 1s polling every 50ms, then SIGKILL if still alive). Only valid, positive, alive recorded PIDs are signaled; dead, null, or invalid PIDs are never signaled.
- **State reset:** By default, `reclaim` records a `failed` event and clears stage state back to idle `queued`, ready for immediate restart. Pass `--kill --keep-failed` to leave the stage in `failed` state if human audit is required before resetting.
- **Advisory checks:** For single-pass cron checks without blocking, use `stage-signal doctor --exit-reclaim` (exits `10` when reclaim is needed, `0` when healthy).

---

## 3. Agent Wrapper (Worker Lifecycle)

Workers or coding agent runners wrap their execution in lifecycle signals from bootstrap to completion.

### The Loop

```bash
#!/bin/sh
set -eu

# 1. Bootstrap: create .stage-signal/ if absent (idempotent, leaves existing state intact)
stage-signal init

# 2. Claim stage: record stage identity and worker PID
stage-signal start --stage "issue-42" --session "agent-run-1" --pid $$

# 3. Work loop: emit heartbeats, notes, and artifacts during execution
stage-signal note "Running test suite"
stage-signal artifact changes.diff --label patch

# 4. Terminal outcome:
# On success (always pass --git-head after committing code):
stage-signal done \
  --summary "Fixed issue #42 and passed regression tests" \
  --git-head $(git rev-parse HEAD)

# If an external blocker is encountered:
# stage-signal blocked --reason "Missing API key for external service"

# If an unrecoverable failure occurs:
# stage-signal fail --reason "Compilation failed with 5 errors"
```

### Alternative Terminal Path: `supervise`

`supervise` is **itself terminal** — it records `done` on child exit `0` and `fail`
on any non-zero exit. It therefore replaces steps 3–4 above; it is not a drop-in
for a mid-script `heartbeat`. Use it as the **last** command in the wrapper and do
not follow it with `done` / `note` / `artifact`:

```bash
#!/bin/sh
set -eu

stage-signal init
stage-signal start --stage "issue-42" --session "agent-run-1" --pid $$
stage-signal note "Running test suite"

# Terminal: heartbeats every 30s, then done (child exit 0) or fail (non-zero).
# `set -eu` aborts the script on non-zero, so put any custom error handling
# in a trap — or drop `supervise` and call `fail --reason "..."` yourself.
exec stage-signal supervise --every 30 -- pytest -q
```

### Key Semantics

- **PID recording:** Always pass `--pid $$` (POSIX) or the active process ID (e.g. `os.getpid()`) on `start` so watchdog diagnostics track the correct process.
- **Git head inheritance:** `done` without `--git-head` inherits the commit SHA captured at `start` (SPEC §13.30.3). Any worker that commits changes **must** pass `--git-head $(git rev-parse HEAD)` on `done` so `result.git_head` reflects the finished commit.
- **Heartbeats & `supervise`:** Long commands without output can trigger false `STALE_HEARTBEAT` warnings. `stage-signal supervise --every SEC -- <command>` refreshes heartbeats and adopts the child PID for the duration of the child — but it is a **terminal** command (see above), not a heartbeat helper you can call mid-script. To keep a hand-rolled loop alive instead, emit `stage-signal heartbeat` yourself.
- **Do not branch on `supervise`'s exit code:** `supervise` returns the child's exit code verbatim, so a child exiting `2` / `3` / `15` is indistinguishable from bad-args / illegal-transition / not-initialized (SPEC §13.24). Read `stage-signal status --json` to learn the outcome.
- **Abandoning parked stages:** If a stage was queued but never started (or needs to be canceled), run `stage-signal clear-terminal` to reset it back to idle `queued` without editing files manually.

---

## Summary Reference

| Operation | Command | Primary Exit Codes |
|---|---|---|
| **Wait for any terminal state** | `stage-signal wait --json --state terminal` | `0` (done, blocked *or* failed — read `state`), `14` (timeout) |
| **Wait for success specifically** | `stage-signal wait --state done` | `0` (done), `11` (blocked), `12` (failed), `14` (timeout) |
| **Wait for health failure** | `stage-signal wait --needs-reclaim` | `0` (reclaim needed), `1` (clean done), `14` (timeout) |
| **Reclaim dead worker** | `stage-signal reclaim --reason "..." --kill` | `0` (reclaimed to queued), `12` (--keep-failed), `3` (guard refused) |
| **Claim stage** | `stage-signal start --stage <name> --pid $$` | `0` (running), `2` (bad args) |
| **Record completion** | `stage-signal done --summary "..." --git-head $(git rev-parse HEAD)` | `0` (done), `3` (illegal transition) |
| **Clear stale terminal before relaunch** | `stage-signal clear-terminal` | `0` (reset to queued), `3` (not terminal) |
| **Check snapshot** | `stage-signal status --json` | `0` (done), `10` (running), `11` (blocked), `12` (failed), `13` (queued) |
| **Inspect health** | `stage-signal doctor --json` | `0` (healthy), `10` (`--exit-reclaim` needed), `1` (problem) |
