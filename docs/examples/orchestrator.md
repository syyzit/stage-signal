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
| `10` | Running | `state: running` |
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
  "state": "running",
  "problems": [],
  "warnings": [],
  "status": { ... }
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

#### Branching on Warnings with `jq`

```bash
doc_json=$(stage-signal --dir "$WORKTREE/.stage-signal" doctor --json)

# Check for dead runner process
if echo "$doc_json" | jq -e '.warnings[] | select(.code == "DEAD_PID")' >/dev/null; then
  echo "Process died without completing stage! Handling crash..."
  stage-signal --dir "$WORKTREE/.stage-signal" fail --reason "Agent process died unexpectedly (DEAD_PID)"
fi

# Check for hung / stale heartbeat
if echo "$doc_json" | jq -e '.warnings[] | select(.code == "STALE_HEARTBEAT")' >/dev/null; then
  echo "Agent heartbeat is stale! Checking process status..."
fi
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
   pytest
4. On clean completion:
   git commit -m "feat: complete <STAGE_ID>"
   .venv/bin/stage-signal --dir .stage-signal done --summary "Completed <STAGE_ID>" --git-head $(git rev-parse HEAD)
5. If blocked on external secrets or credentials:
   .venv/bin/stage-signal --dir .stage-signal blocked --reason "Explanation of blocker"
6. If tests fail or code invariants break:
   .venv/bin/stage-signal --dir .stage-signal fail --reason "Explanation of failure"
```

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

  if echo "$doc_json" | grep -q '"DEAD_PID"'; then
    echo "[$name] WARNING: Dead PID detected by doctor! Process crashed."
  fi

  if echo "$doc_json" | grep -q '"STALE_HEARTBEAT"'; then
    echo "[$name] WARNING: Stale heartbeat detected by doctor! Agent may be hung."
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
- [ ] **Automated Health Checks**: Run `doctor --json` in your poll loop and inspect `.warnings[]` for `DEAD_PID` and `STALE_HEARTBEAT`.
- [ ] **Clean Resets**: Use `stage-signal clear-terminal` to reset an idle worktree back to `queued -` between tasks.
