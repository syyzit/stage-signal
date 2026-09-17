# Multi-CLI Orchestrator Loop: agy & OpenCode

This guide demonstrates how an **external orchestrator loop** drives coding agents through a sequence of milestones using `stage-signal` as the contract.

The core thesis of `stage-signal` is simple:
> **Agents produce machine-readable stage signals; orchestrators consume them.**

The orchestrator never scrapes terminal UIs, never parses markdown chat logs for "I am done", and never inspects internal agent databases. It relies solely on `stage-signal` CLI commands, on-disk status files, and normalized exit codes.

Because the stage contract is completely decoupled from the agent implementation, the exact same orchestrator pattern works interchangeably with **Google Antigravity CLI (`agy`)** and **OpenCode (`opencode`)**. For multi-lane parallel execution in isolated worktrees with watchdog health monitoring (`doctor --json`), see [`docs/examples/orchestrator.md`](../docs/examples/orchestrator.md#branching-on-needs_reclaim-with-jq). Branch on `.needs_reclaim`, not `.summary` or `.ok`; inspect warning codes only to choose the response. The [watchdog](orchestrator-watchdog.sh) uses `--once --doctor-reclaim` to reclaim `DEAD_PID` via guarded fail, but logs ATTENTION without failing a live runner with only a stale heartbeat (the reclaim check returns `0`; `--once` still reports running as `10`).

---

## Architecture: Queue State vs Stage Signal

A clean agent automation setup separates two distinct concerns:

```
+-------------------------------------------------------------------+
|  Private Orchestrator State (.agloop/ or .museloop/)              |
|  - QUEUE.md                 (Milestone backlog / plan)            |
|  - prompt-<stage>.md        (Milestone-specific instructions)     |
|  - run.pid, run.log         (Runner process ID & raw transcripts) |
|  - STATUS.md, DONE          (Runner audit trail)                  |
|  (Gitignored: local to the machine / orchestrator session)        |
+---------------------------------+---------------------------------+
                                  |
            +---------------------+---------------------+
            |                                           |
            v                                           v
    [ Antigravity: agy ]                        [ OpenCode ]
    agy -p "$PROMPT" ...                        opencode run "$PROMPT" ...
            |                                           |
            +---------------------+---------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
|  Universal Stage Contract (.stage-signal/)                        |
|  - STATUS.json              (Normative machine snapshot)          |
|  - events.jsonl             (Append-only lifecycle event log)     |
|  - locks/stage.lock         (Atomic file lock for concurrency)    |
|                                                                   |
|  Agent updates:  start, heartbeat, note, artifact, done, blocked  |
|  Orchestrator:   wait, status, doctor                             |
|  Exit codes:     0 (ok/done), 11 (blocked), 12 (failed), 14 (tout)|
+-------------------------------------------------------------------+
```

### 1. The Queue Folder owns the *Plan* (`.agloop/`, `.museloop/`, or `.orch/`)
- Contains the task queue (e.g. `QUEUE.md`), prompt markdown files for each milestone, launcher scripts, PID files, and runner logs.
- Kept in `.gitignore` so local orchestrator state is never committed to upstream repositories.
- Each agent tool or bot can have its own private harness folder (for example, `.agloop/` for `agy`, `.museloop/` for OpenCode).

### 2. `.stage-signal/` owns the *Stage Signal*
- Contains `STATUS.json` (normative snapshot), `STATUS.md` (human mirror), `events.jsonl`, and `locks/stage.lock`.
- Tool-agnostic: whether a milestone was tackled by `agy`, `opencode`, Claude Code, or a human engineer, the state schema and exit codes are identical.
- Any external watcher (a shell script, cron job, GitHub Action, or remote bot) can read and wait on `.stage-signal/` without knowing which agent CLI is running.

---

## Side-by-Side: Agent Invocation

When the orchestrator decides to start a milestone, the invocation line is the **only piece that differs** between agent CLIs. Everything else—directory, environment, prompts, exit codes, and `stage-signal` lifecycle—stays identical.

```bash
# ==============================================================================
# 1. Antigravity CLI (agy)
# ==============================================================================
agy -p "$PROMPT" \
  --dangerously-skip-permissions \
  --print-timeout "${TIMEOUT:-45m}"

# ==============================================================================
# 2. OpenCode (opencode)
# ==============================================================================
opencode run \
  --dir "$REPO_ROOT" \
  --auto \
  -m "${MODEL:-google/gemini-2.5-pro}" \
  "$PROMPT"
```

### Comparison Matrix

| Aspect | `agy` (Antigravity CLI) | `opencode` |
| :--- | :--- | :--- |
| **Command** | `agy` | `opencode run` |
| **Execution mode** | `-p` / `--print` (single prompt non-interactive) | `opencode run` (command mode) |
| **Auto-approval** | `--dangerously-skip-permissions` | `--auto` |
| **Working directory** | Working directory of invocation | `--dir "$REPO_ROOT"` or working dir |
| **Timeout flag** | `--print-timeout 45m` (built-in) | External watchdog / `timeout` command |
| **Model selection** | `--model <name>` (or config default) | `-m <provider/model>` |
| **Stage directory** | `.stage-signal` | `.stage-signal` |
| **Start command** | `stage-signal start --stage <id>` | `stage-signal start --stage <id>` |
| **Wait command** | `stage-signal wait --state terminal` | `stage-signal wait --state terminal` |
| **Exit code contract** | `0` done, `11` blocked, `12` failed, `14` timeout | `0` done, `11` blocked, `12` failed, `14` timeout |

---

## The Agent Prompt Contract

In both cases, the prompt provided to the agent explicitly specifies the `stage-signal` contract. Here is a standard prompt template:

```markdown
You are working ONE milestone in this repository: <STAGE_NAME>.

## Workflow & Stage Contract
1. Announce start:
   stage-signal start --stage <STAGE_NAME> --pid $$
2. While working, send heartbeats if running long tasks:
   stage-signal heartbeat
   stage-signal note "Finished refactor, running test suite"
3. Run verification tests:
   .venv/bin/pytest
4. If completed cleanly:
   git commit -m "feat: complete <STAGE_NAME>"
   stage-signal done --summary "completed <STAGE_NAME>" --git-head $(git rev-parse HEAD)
5. If blocked on external human action / quota / credentials:
   stage-signal blocked --reason "Description of blocker"
6. If tests fail or code invariants break:
   stage-signal fail --reason "Description of failure"
```

> **Virtual environment note:** Prompt templates should instruct agents to prefer the worktree or main checkout `.venv` (e.g. `.venv/bin/pytest` installed with `.[dev]`) rather than bare system `pytest`, ensuring test dependencies like `pytest-timeout` are active.

---

## Reusing `examples/queue-orchestrator.sh`

Rather than writing custom queue-walking logic from scratch, external loops reuse `examples/queue-orchestrator.sh`.

`queue-orchestrator.sh` accepts a queue markdown file (like `examples/sample-queue.md` or `.agloop/QUEUE.md`):

```markdown
# Queue
- stage-schema
- stage-implementation
- stage-docs
```

When run:
- **If current stage is `done`**: advances to next stage, reports `advance <cur> done -> next <next>`, and exits `0`. If all stages are finished, reports `queue drained: <cur> done (N/N)` and exits `0`.
- **If current stage is `running` / `queued`**: waits for terminal state (or exits `10` / `13` with `--once`).
- **If current stage is `blocked`**: stops and exits `11`.
- **If current stage is `failed`**: stops and exits `12`.
- **If wait times out**: exits `14`.

---

## End-to-End Orchestrator Script

Here is an end-to-end shell orchestrator loop that drives a queue using either `agy` or `opencode`:

```bash
#!/bin/sh
set -u

AGENT="${AGENT:-agy}"                    # "agy" or "opencode"
QUEUE_FILE="${1:-examples/sample-queue.md}"
STAGE_DIR="${STAGE_SIGNAL_DIR:-.stage-signal}"
REPO_ROOT="$(pwd)"

# 1. Ensure stage-signal is initialized
stage-signal --dir "$STAGE_DIR" init >/dev/null 2>&1 || true

while true; do
  # 2. Check queue state using queue-orchestrator in single-pass mode
  status_out="$(./examples/queue-orchestrator.sh --queue "$QUEUE_FILE" --dir "$STAGE_DIR" --once 2>&1)"
  code=$?

  case "$code" in
    0)
      if echo "$status_out" | grep -q "queue drained"; then
        echo "=== Queue drained! All milestones completed successfully. ==="
        exit 0
      fi
      # Extract next stage name from "advance <cur> done -> next <next>"
      NEXT_STAGE="$(echo "$status_out" | sed -n 's/.*-> next //p')"
      if [ -z "$NEXT_STAGE" ]; then
        # Initial run: pick first entry from queue
        NEXT_STAGE="$(grep -E '^[*-] ' "$QUEUE_FILE" | head -n 1 | sed -E 's/^[*-] (\[[ xX]\] )?//' | awk '{print $1}')"
      fi
      ;;
    10|13)
      echo "Stage currently working or queued; awaiting terminal state..."
      ./examples/queue-orchestrator.sh --queue "$QUEUE_FILE" --dir "$STAGE_DIR" --timeout 3600
      wait_code=$?
      if [ "$wait_code" -ne 0 ]; then
        echo "Stage finished with non-zero status: $wait_code"
        exit "$wait_code"
      fi
      continue
      ;;
    11)
      echo "Queue halted: current stage is BLOCKED (exit 11). Human action needed." >&2
      exit 11
      ;;
    12)
      echo "Queue halted: current stage FAILED (exit 12)." >&2
      exit 12
      ;;
    *)
      echo "Unexpected status code $code: $status_out" >&2
      exit "$code"
      ;;
  esac

  echo "=== Dispatching milestone: $NEXT_STAGE (agent: $AGENT) ==="
  stage-signal --dir "$STAGE_DIR" start --stage "$NEXT_STAGE" --meta "cli=$AGENT"

  # 3. Formulate prompt
  PROMPT="You are working milestone '$NEXT_STAGE'. When done: stage-signal done --summary 'done'. If blocked: stage-signal blocked --reason '...'. If failed: stage-signal fail --reason '...'."

  # 4. Invoke the agent CLI (the only branch point!)
  case "$AGENT" in
    agy)
      agy -p "$PROMPT" --dangerously-skip-permissions --print-timeout 45m
      ;;
    opencode)
      opencode run --dir "$REPO_ROOT" --auto -m "google/gemini-2.5-pro" "$PROMPT"
      ;;
    *)
      echo "Unknown agent: $AGENT (use agy or opencode)" >&2
      exit 2
      ;;
  esac

  # 5. Wait for stage completion via stage-signal contract
  ./examples/queue-orchestrator.sh --queue "$QUEUE_FILE" --dir "$STAGE_DIR" --timeout 3600
  cycle_code=$?
  if [ "$cycle_code" -ne 0 ]; then
    echo "Milestone $NEXT_STAGE ended with exit code $cycle_code" >&2
    exit "$cycle_code"
  fi
done
```

---

## Daemonized Background Execution

When running overnight or on remote hosts, the orchestrator should survive terminal disconnects. Both `agy` and `opencode` can be double-forked into detached daemons:

### `launch-agy.py` (double-forked agy)
```python
#!/usr/bin/env python3
import os, sys, time
from pathlib import Path

root = Path(sys.argv[1]).resolve()
prompt = Path(sys.argv[2]).read_text()
timeout = sys.argv[3] if len(sys.argv) > 3 else "45m"

cmd = ["agy", "-p", prompt, "--dangerously-skip-permissions", "--print-timeout", timeout]

if os.fork() > 0:
    time.sleep(0.3)
    sys.exit(0)
os.setsid()
if os.fork() > 0:
    os._exit(0)

os.chdir(root)
log = root / ".agloop" / "run.log"
with open(log, "ab", buffering=0) as lf:
    os.dup2(lf.fileno(), 1)
    os.dup2(lf.fileno(), 2)
    os.execv(cmd[0], cmd)
```

### `launch-daemon.py` (double-forked OpenCode)
```python
#!/usr/bin/env python3
import os, sys, time
from pathlib import Path

root = Path(sys.argv[1]).resolve()
prompt = Path(sys.argv[2]).read_text()
model = sys.argv[3]

cmd = ["opencode", "run", "--dir", str(root), "-m", model, "--auto", prompt]

if os.fork() > 0:
    time.sleep(0.3)
    sys.exit(0)
os.setsid()
if os.fork() > 0:
    os._exit(0)

os.chdir(root)
log = root / ".museloop" / "run.log"
with open(log, "ab", buffering=0) as lf:
    os.dup2(lf.fileno(), 1)
    os.dup2(lf.fileno(), 2)
    os.execv(cmd[0], cmd)
```

In both setups:
- The daemon redirects stdout and stderr to a private log file (`.agloop/run.log` or `.museloop/run.log`).
- The external loop polls `queue-orchestrator.sh --queue QUEUE.md --once` via cron or a lightweight watchdog script.

---

## Handling Failures: Idle vs Accepted Failure

When an agent fails (`stage-signal fail --reason "..."`), the orchestrator receives exit code `12`. Depending on orchestrator policy, there are two clean paths forward:

1. **Reset to idle worktree:**
   Run `stage-signal clear-terminal`.
   This resets the stage directory to a clean `state: queued` with `stage_name: null`, reported as `queued - (attempt 1)`. Because `stage_name` is null, watchers and queue processors know the worktree is idle rather than awaiting an unfinished task.

2. **Accept failure:**
   Run `stage-signal done --accept-failure --summary "accepted: reason"`.
   This marks the lifecycle stage `done` (exit code `0`) while explicitly recording `"accepted_failure": true` in the `result` payload. This allows pipelines that tolerate optional failure to close out the stage without faking a successful test run.

---

## Cron Polling Pattern

For completely serverless or cron-driven setups, schedule a single-pass check every 5 minutes:

```cron
*/5 * * * * cd /path/to/repo && ./examples/queue-orchestrator.sh --queue .agloop/QUEUE.md --once >>/tmp/orch.log 2>&1
```

Orchestrator behavior maps directly to exit codes:
- `0`: Milestone finished cleanly; next milestone can be triggered or queue is complete.
- `10` / `13`: Agent is still running or queued; no action needed, re-poll on next tick.
- `11`: Milestone is **blocked**; send alert / notification to human reviewer.
- `12`: Milestone **failed**; stop queue and page engineer.
- `14`: Wait timed out (agent hung / died without updating signal).
- `15`: Uninitialized `.stage-signal` directory.

No terminal scraping. No guesswork. Just boring files and exit codes.
