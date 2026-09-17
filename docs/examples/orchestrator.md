# Dual-CLI Orchestrator Guide: agy & OpenCode as Peers

This guide explains how an **outer orchestrator** coordinates coding agents across parallel tasks using `stage-signal` as the shared stage lifecycle contract.

In this architecture, **Google Antigravity (`agy`)** and **OpenCode (`opencode`)** operate as **equal peers**:
- Neither CLI has a privileged position or custom status protocol.
- Both consume the same task prompts instructing them to emit lifecycle signals.
- The outer orchestrator supervises both runners using identical commands (`status --json`, `doctor --json`, `wait`).

---

## Architecture: Orchestrator vs. Stage Contract

A multi-agent orchestrator (such as AGLoop, a custom shell watchdog, or a CI coordinator) cleanly separates scheduling from execution:

```
+--------------------------------------------------------------------------------+
|                         Outer Orchestrator / Watchdog                          |
|  - Manages queues, milestone assignment, and worktree creation                 |
|  - Supervises runner health via: stage-signal doctor --json                    |
|  - Observes lifecycle state via: stage-signal status --json / wait             |
+---------------------------------------+----------------------------------------+
                                        |
                 +----------------------+----------------------+
                 | (Lane 1: Worktree A)        | (Lane 2: Worktree B)
                 v                             v
       [ Antigravity: agy ]             [ OpenCode: opencode ]
       agy -p "$PROMPT" ...             opencode run "$PROMPT" ...
                 |                             |
                 v                             v
       +--------------------+        +--------------------+
       |   .stage-signal/   |        |   .stage-signal/   |
       |  (Lane A Contract) |        |  (Lane B Contract) |
       +--------------------+        +--------------------+
```

- **The Orchestrator owns the lanes**: assigning stages, allocating isolated git worktrees, and enforcing timeouts.
- **`.stage-signal/` owns the stage contract**: tracking the current stage attempt, PID, heartbeats, notes, and final outcome receipts (`done`, `blocked`, or `failed`).

---

## 1. The Shared Stage-Signal Contract

Every agent follows the exact same linear stage contract:

```
init  -->  start --pid  -->  [heartbeat / note]*  -->  done | fail | blocked
```

### Stage Transitions

1. **`init`**:
   The orchestrator or worktree setup script ensures the `.stage-signal/` directory exists:
   ```bash
   stage-signal --dir .stage-signal init
   ```
   Initial state is `queued` with `stage_name: null` (idle).

2. **`start --pid <PID>`**:
   When the agent commences work on a milestone, it records its active process ID and stage identifier:
   ```bash
   stage-signal --dir .stage-signal start --stage "feature-auth" --pid "$AGENT_PID"
   ```
   - State becomes `running`.
   - Initial `heartbeat_at` is set to the start time.
   - **PID Best Practice**: Pass the real process ID of the agent runner (for example, `$!` if launched into the background in Bash, or `os.getpid()` from a launcher script). Do not use a bare `$$` inside subshells where `$$` expands to the parent shell rather than the agent process.

3. **`heartbeat` and `note`**:
   During long-running compilation, test runs, or complex refactors, the agent sends periodic heartbeats:
   ```bash
   stage-signal --dir .stage-signal heartbeat
   stage-signal --dir .stage-signal note "Refactoring auth controller: tests passing"
   ```
   Heartbeats update `heartbeat_at`. Notes append timestamped diagnostic logs to `STATUS.json` (capped at 200 entries).

4. **Terminal States**:
   When the stage ends, the agent transitions to one of three terminal states:
   - **`done`**: Success.
     ```bash
     stage-signal --dir .stage-signal done --summary "Implemented JWT authentication" --git-head "$(git rev-parse HEAD)"
     ```
   - **`blocked`**: Cannot proceed without human intervention, secret provisioning, or external resolution.
     ```bash
     stage-signal --dir .stage-signal blocked --reason "Requires OAuth client secret in vault"
     ```
   - **`fail`**: Unrecoverable error, red tests, or invariant violation.
     ```bash
     stage-signal --dir .stage-signal fail --reason "Integration test suite failed: 3 tests broken"
     ```

### Standard Exit Codes

The orchestrator inspects exit codes from `status`, `wait`, or `doctor` commands to branch without string parsing:

| Exit Code | Meaning | CLI States |
| :--- | :--- | :--- |
| `0` | Success / Done | `state: done` |
| `1` | Error / Corrupt directory | Schema violation or disk error |
| `2` | Bad CLI Arguments | Flag syntax error |
| `3` | Illegal Transition / Proof Failure | Invalid lifecycle transition |
| `10` | Running / Needs Reclaim | `state: running` (or `doctor --exit-reclaim` when `needs_reclaim` is true) |
| `11` | Blocked | `state: blocked` |
| `12` | Failed | `state: failed` |
| `13` | Queued | `state: queued` |
| `14` | Wait Timeout | `stage-signal wait` deadline exceeded |
| `15` | Uninitialized | `.stage-signal` directory does not exist |

---

## 2. Parallel Lanes in Isolated Worktrees

> **CRITICAL RULE:** Never share a single git worktree between multiple agent CLIs (or concurrent runs of the same CLI).

Running agents in parallel requires **isolated git worktrees**:

```bash
# Main repository: /repos/my-project
# Lane 1: agy
git worktree add /repos/lanes/lane-agy -b agy/feature-auth

# Lane 2: OpenCode
git worktree add /repos/lanes/lane-oc -b oc/feature-billing
```

### Pin the CLI source as well as the state directory

When dogfooding stage-signal itself, isolated worktrees do not isolate a shared
`.venv` editable install: it may still import another lane's older source.
`--dir "$WORKTREE/.stage-signal"` selects state, not Python code. Prefer a
per-worktree venv, or set `PYTHONPATH="$WORKTREE/src"` (with an absolute
`WORKTREE`) separately for each lane's agent and watchdog processes:

```bash
PYTHONPATH="$WORKTREE/src" python -m stage_signal --dir "$WORKTREE/.stage-signal" doctor --json
PYTHONPATH="$WORKTREE/src" stage-signal fail -h
```

Use the intended venv's interpreter/entry point. On a post-#43 tree the help
must include `--if-dead-pid`; if recovery rejects that flag, check the imported
source before treating it as a PID-proof failure. After merging CLI-flag
changes, reinstall the editable package **from main** if sharing a `.venv`,
then check the shared command without a `PYTHONPATH` override. Do not reinstall
from a lane into that shared venv.

See [Contributing: isolated worktrees](../../CONTRIBUTING.md#dogfooding-from-isolated-worktrees)
for import-path diagnostics and the `ss()` launcher pattern using
`sys.executable -m stage_signal` with a per-call environment. Apply it to both
local `.agloop/launch-agy.py` and `.agloop/launch-opencode.py` helpers when they
are maintained outside the tracked worktree.

### Why Worktree Isolation is Mandatory

1. **Git Working Copy Conflicts**:
   Two CLIs in the same directory will clobber each other's edits, conflict on git index locks (`.git/index.lock`), and overwrite untracked files.
2. **Signal File Collisions**:
   `.stage-signal/STATUS.json` is a singleton per worktree. Two agents running in the same directory would overwrite each other's stage names, heartbeats, and terminal outcomes.
3. **Private Runner Harnesses**:
   Each agent harness maintains private gitignored state (such as `.agloop/` for `agy` and `.museloop/` for OpenCode). Running in separate worktrees keeps logs, PID files, and prompt templates completely isolated.

---

## 3. Outer Watchdog: Reading `doctor`, `doctor --json`, and `status --json`

While the agent runs, the outer orchestrator runs a non-blocking watchdog loop that polls the lane's health and status.

### Snapshot Inspection: `status --json`

To check the current state of a lane:

```bash
stage-signal --dir "$WORKTREE/.stage-signal" status --json
```

Output:
```json
{
  "schema_version": 1,
  "project": "my-project",
  "stage_id": "feature-auth",
  "stage_name": "feature-auth",
  "state": "running",
  "attempt": 1,
  "pid": 48120,
  "started_at": "2026-09-17T04:10:00.000000+00:00",
  "updated_at": "2026-09-17T04:12:30.000000+00:00",
  "heartbeat_at": "2026-09-17T04:12:30.000000+00:00",
  "notes": [
    {"at": "2026-09-17T04:11:15+00:00", "note": "Refactoring middleware"}
  ]
}
```

The exit code matches the current state (`10` for running, `0` for done, etc.).

### Health Supervision: `doctor --json`

The orchestrator should not merely rely on wall-clock timeouts. It can proactively detect crashed or hung agents using `doctor --json`:

```bash
stage-signal --dir "$WORKTREE/.stage-signal" doctor --json
```

Healthy output:
```json
{
  "ok": true,
  "needs_reclaim": false,
  "state": "running",
  "problems": [],
  "warnings": [],
  "status": { ... },
  "summary": "OK: running"
}
```

#### Structured Warning Codes

When an anomaly occurs, `doctor --json` populates the `warnings` array with machine-readable objects containing `code`, `message`, and `detail`:

1. **`DEAD_PID`**:
   The stage is marked `running`, but the OS process table indicates that the process with recorded `pid` is dead.
   ```json
   {
     "code": "DEAD_PID",
     "message": "WARNING: DEAD PID: claiming pid 48120 is not alive",
     "detail": {
       "pid": 48120
     }
   }
   ```
   *Orchestrator Action*: The agent process crashed, segfaulted, or was killed by the OS (OOM). The orchestrator can mark the stage failed or clean up the lane immediately without waiting for a 45-minute timeout.

2. **`STALE_HEARTBEAT`**:
   The stage is marked `running`, but the elapsed time since `heartbeat_at` exceeds the stale threshold (default 300 seconds, configurable via `--stale-after`).
   ```json
   {
     "code": "STALE_HEARTBEAT",
     "message": "WARNING: STALE: running with heartbeat 480.0s ago (threshold 300s)",
     "detail": {
       "age": 480.0,
       "threshold": 300.0,
       "heartbeat_at": "2026-09-17T04:00:00+00:00"
     }
   }
   ```
   *Orchestrator Action*: The agent is likely hung in an infinite loop, blocked on an interactive prompt, or deadlocked. The watchdog can log a warning, capture process thread stacks, or send a termination signal.

3. **`UNPARSEABLE_HEARTBEAT`**:
   The `heartbeat_at` field contains an invalid timestamp string.
   ```json
   {
     "code": "UNPARSEABLE_HEARTBEAT",
     "message": "WARNING: unparseable heartbeat_at",
     "detail": {
       "heartbeat_at": "invalid-timestamp"
     }
   }
   ```

#### Branching on `needs_reclaim` with `jq`

Orchestrators must branch on the always-present `.needs_reclaim` boolean, not the human-readable `.summary` or `.ok`. It is `true` exactly when a running stage has a `DEAD_PID` or `STALE_HEARTBEAT` warning. Warnings alone keep `.ok` true and doctor's exit code at `0`; `.needs_reclaim` is independent of problems.

```bash
doc_json=$(stage-signal --dir "$WORKTREE/.stage-signal" doctor --json) || {
  echo "Doctor reported problems; inspect diagnostics before reclaiming." >&2
  exit 1
}

if printf '%s\n' "$doc_json" | jq -e '.needs_reclaim == true' >/dev/null; then
  echo "ATTENTION: running needs reclaim"

  if printf '%s\n' "$doc_json" | jq -e '.warnings[] | select(.code == "DEAD_PID")' >/dev/null; then
    if stage-signal --dir "$WORKTREE/.stage-signal" fail \
      --reason "Agent process died unexpectedly (DEAD_PID)" --if-dead-pid; then
      echo "Stage reclaimed as failed."
    else
      reclaim_code=$?
      echo "Reclaim refused or failed (exit $reclaim_code); inspect the current state." >&2
    fi
  elif printf '%s\n' "$doc_json" | jq -e '.warnings[] | select(.code == "STALE_HEARTBEAT")' >/dev/null; then
    echo "ATTENTION: stale heartbeat without DEAD_PID; inspect runner, no guarded fail attempted." >&2
  fi
fi
```

Warning checks are secondary detail for choosing a response, not the primary health gate. A stale heartbeat does not prove the PID is dead: do not call `fail --if-dead-pid` for a stale-only live runner. The [watchdog example](../../examples/orchestrator-watchdog.sh) logs ATTENTION and returns `0` from its reclaim check in that case; `--once` still returns the observed running-state code `10`. Guarded fail rechecks the current PID under lock and can refuse if the snapshot has changed.

To reclaim **either** `DEAD_PID` or `STALE_HEARTBEAT` in one shot (same `needs_reclaim` semantics as `doctor` / `status` / `Stage.diagnose()`), use `fail --if-needs-reclaim` instead of `--if-dead-pid`. After reclaim (or abandon), audit with `events` — do not scrape `events.jsonl`:

```bash
# One-shot fail gate: writes failed + reason ONLY when needs_reclaim is true.
# Healthy running and non-running states: exit 3, no mutation.
if stage-signal --dir "$WORKTREE/.stage-signal" fail \
  --reason "watchdog reclaim (DEAD_PID or STALE_HEARTBEAT)" --if-needs-reclaim; then
  echo "Stage reclaimed as failed."
  # First-class audit (newest last). --json prints a JSON array, not NDJSON.
  stage-signal --dir "$WORKTREE/.stage-signal" events --tail 20 --type failed
else
  echo "Reclaim not needed or refused (exit $?); no mutation." >&2
fi
```

`--if-dead-pid` remains the narrower DEAD_PID-only gate. `--if-dead-pid` and `--if-needs-reclaim` are mutually exclusive.

A parked `queued` stage (named or idle, no PID/heartbeat) cannot be `clear-terminal`'d on older trees. Current contract: `clear-terminal` accepts `queued` as well as `done`/`blocked`/`failed` and resets to idle queued with a `clear_terminal` event. From `running` it stays illegal — reclaim with `fail --if-needs-reclaim` first:

```bash
# Abandon a stuck queued stage (never started / parked) back to idle.
stage-signal --dir "$WORKTREE/.stage-signal" clear-terminal
stage-signal --dir "$WORKTREE/.stage-signal" events --tail 5 --type clear_terminal
```

#### Branching on Exit Code: `doctor --exit-reclaim` (without `jq`)

For thin shell or watchdog snippets that avoid `jq`, pass `--exit-reclaim` to `doctor`. When `--exit-reclaim` is set, `doctor` exits **10** when `needs_reclaim` is true (while still printing human or JSON diagnostic output as requested). When `needs_reclaim` is false, it preserves existing exit codes (0 healthy/warnings, 1 problems, 2 bad args):

```bash
# Doctor exits 10 if needs_reclaim is true (DEAD_PID or STALE_HEARTBEAT)
stage-signal --dir "$WORKTREE/.stage-signal" doctor --exit-reclaim
case $? in
  0)
    # Healthy running, non-running state, or warning without reclaim
    ;;
  10)
    echo "ATTENTION: stage needs reclaim (dead PID or stale heartbeat)" >&2
    # Attempt guarded reclaim if dead PID
    stage-signal --dir "$WORKTREE/.stage-signal" fail \
      --reason "Agent process died unexpectedly (DEAD_PID)" --if-dead-pid || true
    ;;
  1)
    echo "Doctor reported problems (e.g. uninitialized, corrupt file)" >&2
    ;;
esac
```

---

## 4. Side-by-Side: Agent Invocation Snippets

The agent invocation line is the only CLI-specific part of the workflow. Both CLIs accept instructions in their prompt to use `stage-signal`.

### Common Agent Prompt Contract

Embed the stage-signal contract into the prompt sent to either agent:

```markdown
You are assigned milestone: <STAGE_ID>.

LIFECYCLE REQUIREMENTS:
1. Announce start immediately:
   .venv/bin/stage-signal --dir .stage-signal start --stage "<STAGE_ID>" --pid $$
2. Send occasional heartbeats during long steps:
   .venv/bin/stage-signal --dir .stage-signal heartbeat
3. Run verification tests:
   .venv/bin/pytest
4. On clean completion:
   git commit -m "feat: complete <STAGE_ID>"
   .venv/bin/stage-signal --dir .stage-signal done --summary "Completed <STAGE_ID>" --git-head $(git rev-parse HEAD)
5. If blocked on external secrets or credentials:
   .venv/bin/stage-signal --dir .stage-signal blocked --reason "Explanation of blocker"
6. If tests fail or code invariants break:
   .venv/bin/stage-signal --dir .stage-signal fail --reason "Explanation of failure"
```

> **Virtual environment note:** In prompt templates, instruct agents to prefer the worktree or main repository `.venv` (e.g., `.venv/bin/pytest` or symlinked `.venv`) with `pip install -e ".[dev]"` rather than unpinned system `pytest` or bare `python3 -m pytest`, ensuring dev dependencies like `pytest-timeout` are present.

### 1. Google Antigravity CLI (`agy`) Snippet

```bash
# Invoking agy in non-interactive print mode with auto-execution
agy -p "$PROMPT" \
  --dangerously-skip-permissions \
  --print-timeout 45m
```

### 2. OpenCode (`opencode`) Snippet

```bash
# Invoking OpenCode in non-interactive command mode
opencode run \
  --dir "$WORKTREE_PATH" \
  --auto \
  -m "google/gemini-2.5-pro" \
  "$PROMPT"
```

---

## 5. Minimal Dual-Lane Orchestrator Script

Below is a complete, minimal shell orchestrator demonstrating both CLIs running as peers in parallel worktrees with watchdog health checking:

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(pwd)"
LANE_DIR="/tmp/stage-signal-lanes"
mkdir -p "$LANE_DIR"

setup_lane() {
  local lane_name="$1"
  local branch="$2"
  local worktree="$LANE_DIR/$lane_name"

  if [ ! -d "$worktree" ]; then
    git worktree add -b "$branch" "$worktree" main
  fi

  # Initialize stage-signal directory in the worktree
  stage-signal --dir "$worktree/.stage-signal" init
  echo "$worktree"
}

# 1. Allocate isolated worktrees (never share worktrees between CLIs!)
WT_AGY=$(setup_lane "lane-agy" "agy/orch-auth-demo")
WT_OC=$(setup_lane "lane-oc" "oc/orch-billing-demo")

# 2. Launch agy in Lane 1
PROMPT_AGY="Complete milestone 'auth-demo'. Follow stage-signal contract."
(
  cd "$WT_AGY"
  # Record start with background subshell PID
  stage-signal --dir .stage-signal start --stage "auth-demo" --pid "$$"
  exec agy -p "$PROMPT_AGY" --dangerously-skip-permissions --print-timeout 30m
) > "$WT_AGY/run.log" 2>&1 &
PID_AGY=$!

# 3. Launch OpenCode in Lane 2
PROMPT_OC="Complete milestone 'billing-demo'. Follow stage-signal contract."
(
  cd "$WT_OC"
  # Record start with background subshell PID
  stage-signal --dir .stage-signal start --stage "billing-demo" --pid "$$"
  exec opencode run --dir "$WT_OC" --auto -m "google/gemini-2.5-pro" "$PROMPT_OC"
) > "$WT_OC/run.log" 2>&1 &
PID_OC=$!

echo "Dispatched agy (PID: $PID_AGY) in $WT_AGY"
echo "Dispatched opencode (PID: $PID_OC) in $WT_OC"

# 4. Outer Watchdog Loop: supervise health & monitor completion
check_lane() {
  local name="$1"
  local wt="$2"

  # Run doctor to check for dead PIDs or stale heartbeats
  local doc_json
  doc_json=$(stage-signal --dir "$wt/.stage-signal" doctor --json 2>/dev/null || echo '{"ok":false}')

  if printf '%s\n' "$doc_json" | jq -e '.needs_reclaim == true' >/dev/null; then
    echo "[$name] ATTENTION: running needs reclaim; inspect doctor warning details." >&2

    if printf '%s\n' "$doc_json" | jq -e '.warnings[] | select(.code == "DEAD_PID")' >/dev/null; then
      echo "[$name] WARNING: Dead PID detected by doctor! Process crashed." >&2
    fi

    if printf '%s\n' "$doc_json" | jq -e '.warnings[] | select(.code == "STALE_HEARTBEAT")' >/dev/null; then
      echo "[$name] WARNING: Stale heartbeat detected by doctor! Agent may be hung." >&2
    fi
  fi

  # Check status code
  stage-signal --dir "$wt/.stage-signal" status >/dev/null 2>&1
  local status_code=$?
  echo "$status_code"
}

echo "Monitoring lanes..."
while true; do
  STATUS_AGY=$(check_lane "agy" "$WT_AGY")
  STATUS_OC=$(check_lane "opencode" "$WT_OC")

  echo "Current status: agy=$STATUS_AGY (10=running, 0=done), opencode=$STATUS_OC"

  # If both have reached terminal states (0=done, 11=blocked, 12=failed)
  if [[ "$STATUS_AGY" != "10" && "$STATUS_AGY" != "13" ]] && \
     [[ "$STATUS_OC" != "10" && "$STATUS_OC" != "13" ]]; then
    echo "Both lanes reached terminal state!"
    break
  fi

  sleep 10
done

echo "Lane agy finished with code $STATUS_AGY"
echo "Lane opencode finished with code $STATUS_OC"
```

---

## Summary Checklist for Orchestrator Authors

- [ ] **One Worktree Per Lane**: Separate directories, separate branches, separate `.stage-signal/` folders.
- [ ] **Accurate PIDs**: Pass the live PID to `start --pid` so `doctor` can spot process deaths.
- [ ] **Automated Health Checks**: Run `doctor --json` in your poll loop and branch on `.needs_reclaim == true`, never `.summary` or `.ok`. Inspect `.warnings[]` secondarily: reclaim `DEAD_PID` with `fail --if-dead-pid`, or reclaim both `DEAD_PID` and `STALE_HEARTBEAT` with `fail --if-needs-reclaim`.
- [ ] **Clean Resets**: Use `stage-signal clear-terminal` to reset a terminal *or* parked queued worktree back to `queued -` between tasks. From `running`, reclaim first. After `fail --if-needs-reclaim` / `clear-terminal`, audit with `stage-signal events --tail 20` (optional `--type failed|clear_terminal`, `--json` for a JSON array).
