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
# Block until the stage reaches any terminal state (done, blocked, or failed):
stage-signal wait --state terminal --timeout 3600 --poll 5
EXIT_CODE=$?

case "$EXIT_CODE" in
  0)
    echo "Stage completed successfully (done)"
    ;;
  11)
    echo "Stage paused: external blocker encountered (blocked)"
    stage-signal status --json
    ;;
  12)
    echo "Stage failed (failed)"
    stage-signal events --tail 10
    ;;
  14)
    echo "Timed out waiting for stage completion"
    ;;
  *)
    echo "Unexpected wait exit code: $EXIT_CODE"
    ;;
esac
```

### Key Semantics

- **Normalized exit codes:** `wait --state terminal` exits `0` on `done`, `11` on `blocked`, `12` on `failed`, and `14` on timeout (SPEC §13.4, §13.38).
- **Targeting specific states:** Calling `stage-signal wait --state done` waits specifically for `done`. If the stage instead terminates in `failed` or `blocked`, `wait` reports the mismatch and exits with that terminal state's code (`12` or `11`).
- **Reading snapshots:** Call `stage-signal status --json` or `stage-signal events --json --tail 20` to inspect outcome details without parsing unstructured logs.

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
stage-signal artifact --kind patch --path "changes.diff"

# Long-running commands can be wrapped with supervise for automatic heartbeats:
stage-signal supervise --every 30 -- pytest -q

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

### Key Semantics

- **PID recording:** Always pass `--pid $$` (POSIX) or the active process ID (e.g. `os.getpid()`) on `start` so watchdog diagnostics track the correct process.
- **Git head inheritance:** `done` without `--git-head` inherits the commit SHA captured at `start` (SPEC §13.30.3). Any worker that commits changes **must** pass `--git-head $(git rev-parse HEAD)` on `done` so `result.git_head` reflects the finished commit.
- **Heartbeats & `supervise`:** Long commands without output can trigger false `STALE_HEARTBEAT` warnings. Wrapping commands with `stage-signal supervise --every SEC -- <command>` automatically refreshes heartbeats and adopts the child process PID.
- **Abandoning parked stages:** If a stage was queued but never started (or needs to be canceled), run `stage-signal clear-terminal` to reset it back to idle `queued` without editing files manually.

---

## Summary Reference

| Operation | Command | Primary Exit Codes |
|---|---|---|
| **Wait for completion** | `stage-signal wait --state terminal` | `0` (done), `11` (blocked), `12` (failed), `14` (timeout) |
| **Wait for health failure** | `stage-signal wait --needs-reclaim` | `0` (reclaim needed), `1` (clean done), `14` (timeout) |
| **Reclaim dead worker** | `stage-signal reclaim --reason "..." --kill` | `0` (reclaimed to queued), `12` (--keep-failed), `3` (guard refused) |
| **Claim stage** | `stage-signal start --stage <name> --pid $$` | `0` (running), `2` (bad args) |
| **Record completion** | `stage-signal done --summary "..." --git-head $(git rev-parse HEAD)` | `0` (done), `3` (illegal transition) |
| **Check snapshot** | `stage-signal status --json` | `0` (done), `10` (running), `11` (blocked), `12` (failed), `13` (queued) |
| **Inspect health** | `stage-signal doctor --json` | `0` (healthy), `10` (`--exit-reclaim` needed), `1` (problem) |
