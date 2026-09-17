# stage-signal

**A tiny, harness-agnostic stage lifecycle CLI for agent orchestrators.**

Coding agents run for a long time. Something else usually has to notice when a *stage* of work finished, failed, or got stuck waiting on the outside world — then start the next stage, pause, or alert a human.

`stage-signal` is that boring contract: a small CLI + on-disk status file that the **agent writes** and an **orchestrator reads**. No TUI scraping. No “it said done in the chat.” Just files, exit codes, and a few commands.

---

## The job

Typical loop:

1. An orchestrator (cron job, bot, CI step, shell watchdog) starts a coding agent on one milestone.
2. The agent calls `stage-signal start` when it begins that milestone.
3. While working, it may `heartbeat`.
4. When finished it calls `stage-signal done` (or `blocked` / `fail` if it cannot finish cleanly).
5. The orchestrator polls `stage-signal status` or `wait` on a timer — then enqueues the next milestone or stops.

So: **agents produce machine-readable stage signals; orchestrators consume them.**

This is intentionally *not* a full multi-agent cockpit, not a test proof system, and not tied to one coding product. It is a filesystem API with a thin CLI.

---

## States

| State | Meaning |
|-------|---------|
| `queued` | Stage reserved, process not started |
| `running` | Agent claimed the stage |
| `done` | Stage completed successfully |
| `blocked` | Cannot proceed without an external fix (auth, quota, human decision, missing secret, …) |
| `failed` | Hard failure (crash, red tests, broken invariant) |

Terminal states for a given attempt: `done`, `blocked`, `failed`.

---

## Install

From PyPI:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install stage-signal
stage-signal --help
```

On Windows Command Prompt, activate the virtual environment with
`.venv\Scripts\activate` instead of the `source` command above.

System Python on macOS refuses bare `pip install` (PEP 668, "externally
managed") — always use a venv as above.

From source (contributors):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"   # installs the `stage-signal` entry point + tests
stage-signal --help
.venv/bin/pytest          # all green (use .venv with .[dev]; not bare system pytest)
```

`python3.11+` with stdlib only — no third-party runtime dependencies.
`python -m stage_signal …` works as an alias for the `stage-signal` command.

---

## Quick start

```bash
# in your project
stage-signal init

# agent side
stage-signal start --stage impact-clarity --session "$SESSION_ID" --pid $$
stage-signal heartbeat
stage-signal done --summary "merged abc123" --git-head abc123
# or: stage-signal blocked --reason "..." / stage-signal fail --reason "..."
# or if accepting a known failure: stage-signal done --accept-failure --summary "accepted: ..."

# orchestrator side
stage-signal status --json
stage-signal wait --state terminal --timeout 900
# or wait --json for a structured outcome payload on stdout:
stage-signal wait --json --state terminal --timeout 900
# reclaim loop (no cron+doctor sleep): poll until DEAD_PID/STALE, then reclaim in one shot:
stage-signal wait --needs-reclaim --timeout 900 --poll 5
stage-signal reclaim --reason "worker timed out or crashed"
# or stop after fail without clearing (audit then clear):
# stage-signal reclaim --reason "audit then clear" --keep-failed
# audit the reclaim (do not scrape events.jsonl with tail/jq):
stage-signal events --tail 20 --type failed
stage-signal events --tail 5 --type clear_terminal
# snapshot health / structured warnings (STALE_HEARTBEAT, DEAD_PID):
stage-signal doctor --json
# or a one-shot exit 10 when reclaim is already needed (without requiring jq):
stage-signal doctor --exit-reclaim
```

The `--pid $$` example uses the POSIX shell process ID. On Windows, pass the
agent process ID instead (for example, `os.getpid()` from Python).

On-disk layout (default):

```
.stage-signal/
  STATUS.json     # current snapshot (normative)
  STATUS.md       # human mirror (best-effort, never normative)
  events.jsonl    # append-only history
  locks/stage.lock  # inter-process lock (POSIX fcntl.flock; Windows msvcrt.locking)
```

> **Platform locking note:** POSIX platforms use `fcntl.flock` (exclusive for mutations, shared for reads). Windows uses Python stdlib `msvcrt.locking` on the lock file (exclusive byte lock on byte 0; shared locks fall back to exclusive; no third-party dependencies). On environments lacking OS locking primitives, locking is a best-effort no-op. Do not assume Windows has POSIX `flock`. Atomic `os.replace` protects `STATUS.json` writes across all platforms.

Exact schema and exit codes: see `docs/SPEC.md` (normative) and
`docs/PRIOR_ART.md` (background).

`status` / `wait` exit codes are part of the contract: `0` done/OK (also `wait --needs-reclaim` when reclaim is needed),
`1` generic/corrupt (also `wait --needs-reclaim` ending in `done` without reclaim), `10` running, `11` blocked, `12` failed, `13` queued,
`14` wait timeout, `15` not initialized, `2` bad args, `3` illegal transition.
`wait --json` prints a structured JSON object (`outcome`, `wanted`, `observed_state` / `state`, `exit_code`, `timeout`, `stage_id`, `dir`, `reason`, `needs_reclaim`, `status`) to stdout while preserving these exit codes. `wanted` is the `--state` value, or `"needs_reclaim"` when `--needs-reclaim` is set. Top-level `needs_reclaim` is the same boolean as `status --json` / `doctor --json` (also nested on `status`). `reason` is the blocked/failed error text, or a short timeout message; `null` otherwise.
`wait --needs-reclaim` polls until that boolean is true (running + `DEAD_PID` or `STALE_HEARTBEAT`, same detection as `doctor` / `status --json`). Healthy running keeps polling — do not treat `status` / `doctor --exit-reclaim` exit 10 as wait success. Terminal without reclaim fails closed (`done` → 1, `blocked` → 11, `failed` → 12). Library: `Stage.wait(..., needs_reclaim=True)`.
`status` prints human text by default (including heartbeat age, e.g. `heartbeat: <ISO> (age 42s)`, only while `running` with a valid heartbeat). `status --json` includes dynamic `heartbeat_age_seconds` (number while running with a valid heartbeat; otherwise `null`) and the always-present boolean `needs_reclaim` with the same semantics as in `doctor --json` (`true` exactly when `running` and a `DEAD_PID` or `STALE_HEARTBEAT` warning applies, computed by the same detection logic as `doctor`; otherwise `false`).
`doctor --json` (or `--format json`) and `Stage.diagnose()` provide machine-readable health diagnostics (`ok`, `needs_reclaim`, `state`, `problems`, `warnings`: `[{code, message, detail}]`, `status`, `summary`). The always-present boolean `needs_reclaim` is `true` exactly when the state is `running` and a `DEAD_PID` or `STALE_HEARTBEAT` warning applies; otherwise it is `false`, including healthy running, non-running states, and missing/unreadable status without reclaim warnings. Orchestrators should branch on `needs_reclaim` instead of string-matching `summary` or treating `ok` as a liveness signal. The summary still reports `ATTENTION: running needs reclaim` for reclaim warnings when there are no problems. `ok` means no problems: reclaim warnings alone preserve `ok: true` and exit 0 (exit 1 on problems), and `needs_reclaim` remains independent of any problems.
To enable thin shell or watchdog scripts to branch on exit codes without requiring `jq`, `doctor --exit-reclaim` exits 10 when `needs_reclaim` is true (while still printing human or JSON output as requested). When `needs_reclaim` is false, it preserves existing exit codes (0 healthy/warnings, 1 problems, 2 bad args). Without `--exit-reclaim`, doctor retains its default advisory exit 0 on warnings.

To act on a `DEAD_PID` warning (which includes an explicit recovery hint naming `fail --reason TEXT --if-dead-pid`), `fail --reason TEXT --if-dead-pid` hard-fails a
`running` stage only after confirming the claiming PID is a valid positive
integer that is actually dead; a live, invalid, or undeterminable PID aborts
with exit 3 and no mutation (outside `running`, normal fail rules apply). Doctor remains advisory-only.

To reclaim whenever `needs_reclaim` would be true (DEAD_PID **or** STALE_HEARTBEAT, same detection as `doctor` / `status` / `Stage.diagnose()`), wait with `wait --needs-reclaim` then `reclaim --reason TEXT`. That one-shot command writes `failed` + reason and immediately clears to idle `queued` (clearing stage identity) under a single exclusive lock, emitting both `failed` and `clear_terminal` events; healthy running and non-running states exit 3 with no mutation. Use `--keep-failed` to stop after `failed` without clearing (for watchdog audit before manual `clear-terminal`). The two-step `fail --reason TEXT --if-needs-reclaim` → `clear-terminal` remains available if separate mutation steps are desired.

`clear-terminal` resets `done`/`blocked`/`failed` **and** stuck `queued` (named or idle) back to idle queued, appending a `clear_terminal` event. From `running` it stays illegal — reclaim with `reclaim`, `fail --if-needs-reclaim`, or `fail --if-dead-pid` first. After either mutation, `stage-signal events [--tail N] [--type TYPE] [--json]` is the first-class audit path (human default newest-last, last 20; `--tail 0` = all; `--json` is a JSON array). Do not scrape `events.jsonl` with `tail`/`jq`.

`start --meta` is repeatable and accepts two forms per entry (merged in
order, later wins):

```bash
stage-signal start --stage demo --meta owner=OpenLoop --meta '{"ticket": 42, "flag": true}'
```

- `K=V` — value kept as a string (value may contain `=`; `K=` is empty).
- A raw JSON object string — JSON types (numbers, bools, null, nested
  objects/arrays) are preserved.
- Bare words, malformed JSON, and non-object JSON exit `2` with no mutation.

Minimal orchestrator loop (cron, bot, CI step, shell): see
`examples/orchestrator-watchdog.sh` — it only calls
`stage-signal status --json` / `stage-signal wait` (including
`wait --needs-reclaim` for the reclaim path) and exits with the
observed-state code above. Acceptance sequence: `examples/orchestrator-smoke.sh`.

The `examples/*.sh` scripts require a POSIX shell, such as Git Bash, WSL, or
the default shell on macOS and Linux.

Multi-stage queues (same contract, one dir walked against a queue file):
`examples/queue-orchestrator.sh --queue examples/sample-queue.md [--dir PATH] [--once]`
— `done` advances (exit 0), `blocked`/`failed` stop with 11/12,
`running`/`queued` wait (or exit 10/13 with `--once` for cron).
Smoke: `examples/queue-orchestrator-smoke.sh`.

### Driving coding agents (agy, OpenCode, etc.)

An external orchestrator loop can drive coding agents across multi-stage milestones without scraping TUIs or transcripts. The orchestrator owns the **queue** (often in gitignored folders like `.agloop/` or `.museloop/` with prompt templates and run logs), while `.stage-signal/` owns the **stage signal** (`start`, `wait`, `done`, exit codes).

The agent CLI invocation line is pluggable — everything else stays identical:

| Agent CLI | Invocation Line |
| :--- | :--- |
| **agy** (Antigravity CLI) | `agy -p "$PROMPT" --dangerously-skip-permissions --print-timeout 45m` |
| **OpenCode** | `opencode run --dir "$REPO" --auto -m "$MODEL" "$PROMPT"` |

See [`docs/examples/orchestrator.md`](docs/examples/orchestrator.md) for the dual-CLI peer orchestrator guide with parallel worktrees and watchdog health checks, [`examples/cli-orchestrator-loop.md`](examples/cli-orchestrator-loop.md) for the end-to-end loop guide, and [`examples/multi-cli-loop.sh`](examples/multi-cli-loop.sh) for a thin runner reusing `examples/queue-orchestrator.sh`.

#### Idle vs. Queued in Orchestrators

Orchestrator loops need to differentiate between an active pending stage and an idle runner:
- **Idle state:** `state: queued` with no stage claimed (`stage_name: null`, displayed as `queued -`) indicates the worktree is idle and awaiting instructions (created by `init` or reset via `clear-terminal`).
- **Queued stage:** `state: queued` with a stage name (`stage_name: "feature-x"`) indicates a specific stage is queued to be picked up. Abandon it with `stage-signal clear-terminal` (now allowed from queued) to return to idle without hand-editing STATUS.
- **Handling failures:** When an agent reports `fail`, orchestrators have two clean SPEC-compatible choices:
  - `stage-signal clear-terminal` to clear stage identity back to a true idle `queued -` state.
  - `stage-signal done --accept-failure --summary "accepted: ..."` to transition a failed stage to `done` with `"accepted_failure": true` recorded in `result`, without inventing a fake success.
- **Stuck running:** Do not cron-poll `doctor`. Block with `stage-signal wait --needs-reclaim`, then `reclaim --reason "..."` (one-shot fail+clear to idle queued for relaunch; or `--keep-failed` / `fail --if-needs-reclaim`). Use `--if-dead-pid` only when the PID is confirmed dead. Audit with `stage-signal events --tail 20`. Snapshot `doctor --json` / `status --json` remains available; `doctor --exit-reclaim` is the one-shot exit-10 check (and `examples/orchestrator-watchdog.sh --once --doctor-reclaim` reclaims snapshot `needs_reclaim` via `reclaim --keep-failed`).


### GitHub Action: wait without a venv

No preinstalled venv needed — the composite action installs `stage-signal`
from PyPI then runs `stage-signal wait`:

```yaml
- uses: syyzit/stage-signal@v0.1.6
  with:
    dir: .stage-signal   # default
    state: terminal      # done | blocked | failed | terminal (default)
    # needs-reclaim: true # alternate wait target: poll until DEAD_PID or STALE_HEARTBEAT
    timeout: 3600        # seconds (default)
    # poll: 5.0          # poll interval in seconds (default: CLI default 5.0)
    # python-version: "3.12"  # default
    # version: "0.1.6"        # optional version pin (default: unpinned/latest)
    # pip-cache: true         # optional boolean for pip caching (default: false)
    # cache: "pip"            # optional setup-python cache (default: "")
```

The action exposes step outputs so downstream steps can branch without log scraping:
- `state` / `observed-state`: observed state (`done`, `blocked`, `failed`, `running`, etc.)
- `outcome`: `met`, `mismatch`, `timeout`, or `error`
- `exit-code` / `exit_code`: numeric wait exit code (`0`, `1` done-without-reclaim, `11`, `12`, `14`, `15`)
- `timed-out` / `timed_out`: `"true"` or `"false"`
- `stage-id` / `stage_id`: stage identifier if present in status
- `reason`: short blocked/failed reason or timeout message (empty otherwise)
- `needs-reclaim` / `needs_reclaim`: `"true"` or `"false"` (whether `needs_reclaim` was observed)
- `json`: raw machine-readable JSON emitted by `wait --json`

#### Branching without scraping logs

Because non-zero exit codes (11 blocked, 12 failed, 14 timeout, 1 done-without-reclaim) fail the step by default, use `continue-on-error: true` to inspect outputs in subsequent steps:

```yaml
- name: Wait for milestone
  id: wait
  uses: syyzit/stage-signal@v0.1.6
  continue-on-error: true
  with:
    state: terminal
    timeout: 600

- name: Done
  if: steps.wait.outputs.state == 'done'
  run: echo "Stage done: ${{ steps.wait.outputs.stage-id }}"

- name: Blocked
  if: steps.wait.outputs.state == 'blocked'
  run: echo "Stage blocked: ${{ steps.wait.outputs.reason }}"

- name: Failed
  if: steps.wait.outputs.state == 'failed'
  run: echo "Stage failed: ${{ steps.wait.outputs.reason }}"

- name: Timed out
  if: steps.wait.outputs.timed-out == 'true'
  run: echo "Wait timed out: ${{ steps.wait.outputs.reason }}"

# Optionally enforce job failure unless the stage is done:
- name: Fail unless done
  if: steps.wait.outputs.state != 'done'
  run: |
    echo "not done: state=${{ steps.wait.outputs.state }} reason=${{ steps.wait.outputs.reason }}"
    exit 1
```

#### CI reclaim gate: wait --needs-reclaim

In CI watchdogs, gate on the reclaim condition without writing cron/sleep loops by setting `needs-reclaim: true`. This runs `stage-signal wait --needs-reclaim --json`, polling until `needs_reclaim` is true (`DEAD_PID` or `STALE_HEARTBEAT`). Terminal states without reclaim fail closed (`done` → 1, `blocked` → 11, `failed` → 12) so downstream `if:` branches can distinguish reclaim needed from timeout or clean task completion:

```yaml
- name: Wait for reclaim signal
  id: wait
  uses: syyzit/stage-signal@v0.1.6
  continue-on-error: true
  with:
    needs-reclaim: true
    timeout: 900
    poll: 5

# Branch 1: Reclaim needed (outcome == 'met', needs-reclaim == 'true', exit-code 0)
- name: Reclaim needed
  if: steps.wait.outputs.needs-reclaim == 'true'
  run: |
    echo "Reclaim needed: stage_id=${{ steps.wait.outputs.stage-id }}"
    # Fail the stage under the mutation lock, then trigger alerts or restart:
    # stage-signal --dir .stage-signal fail --reason "CI watchdog reclaim" --if-needs-reclaim

# Branch 2: Watchdog wait timed out (exit-code 14)
- name: Timed out
  if: steps.wait.outputs.timed-out == 'true'
  run: echo "Watchdog timed out without reclaim: ${{ steps.wait.outputs.reason }}"

# Branch 3: Terminal reached without reclaim (outcome == 'mismatch': done -> 1, blocked -> 11, failed -> 12)
- name: Terminal without reclaim
  if: steps.wait.outputs.outcome == 'mismatch'
  run: |
    echo "Stage reached terminal state without reclaim: state=${{ steps.wait.outputs.state }} exit_code=${{ steps.wait.outputs.exit-code }}"
```

See [`examples/github-action-wait.yml`](examples/github-action-wait.yml) and [`examples/github-action-wait-reclaim.yml`](examples/github-action-wait-reclaim.yml) for complete copyable workflows that wait on an existing `.stage-signal/` directory and branch on `done` / `blocked` / `failed` / `timeout` / `reclaim-needed`. The composite action's steps use `shell: bash` (available on GitHub-hosted Ubuntu, macOS, and Windows runners). Pin the action ref (`@v0.1.6`) independently from the optional `version` input (PyPI package pin). Waiting for `terminal` or `--needs-reclaim` with `continue-on-error: true` keeps 11/12/14/1 from collapsing into a generic failed step so later `if:` branches can read `state` / `timed-out` / `needs-reclaim` / `reason`.

For distinguishable blocked/failed/timeout/reclaim in CI without log scraping, use the action `outputs` (see above) with `continue-on-error` on the wait step when you need downstream `if:` branches.

Exit codes are the `wait` contract: `0` condition met, `1` done-without-reclaim (fail closed), `11` blocked,
`12` failed, `14` timeout, `15` not initialized (`10` running,
`13` queued, `1`/`2`/`3` errors). See `action.yml`.

> **Action runtime note:** The composite action uses `actions/setup-python@v7`
> (Node 24 runner runtime, compatible with runner v2.327.1+), avoiding
> Node 20 runner deprecation warnings. Release packages published from GitHub
> Actions include build provenance attestations (`actions/attest-build-provenance@v4`).


---

## What this is / isn’t

**Is**

- A clear stage lifecycle for overnight or unattended agent loops
- Readable by any language that can open a JSON file
- Usable from cron, bots, CI, or a human shell

**Is not**

- A replacement for git, CI, or issue trackers
- A multi-agent worktree / DAG orchestrator (use tools like ruah / similar if you need that)
- A proof-of-test gate (compose with something like [agent-done-or-not](https://github.com/mohamedzhioua/agent-done-or-not) if you need tamper-evident receipts before declaring success)

---

## Why not scrape the agent UI?

Agent UIs and chat transcripts are for humans. Orchestrators need a stable, boring interface:

- Did this stage end?
- How did it end?
- Is the process still alive (heartbeat)?
- What git head / artifacts should the next stage assume?

`stage-signal` answers those without depending on one vendor’s session format.

---

## Status

0.1.6: library (`src/stage_signal/`), full CLI (`init`, `start`,
`heartbeat`, `note`, `artifact`, `done`, `blocked`, `fail`, `status`,
`wait`, `clear-terminal`, `doctor`), unit + concurrency tests,
`examples/orchestrator-watchdog.sh` (+ `examples/orchestrator-smoke.sh`),
`examples/queue-orchestrator.sh` (+ `examples/sample-queue.md`,
`examples/queue-orchestrator-smoke.sh`, `examples/cli-orchestrator-loop.md`,
`examples/multi-cli-loop.sh`), CI (`.github/workflows/ci.yml`:
pytest + both smokes + packaging check via `python -m build` /
`twine check`, no upload). Contract: SPEC v1.

---

## Docs

- `docs/SPEC.md` — normative contract (schema, CLI, exit codes)
- `docs/COMPOSE.md` — proof interop (`--proof-ref` / `--require-proof`)
- `docs/examples/orchestrator.md` — dual-CLI orchestrator example (agy + OpenCode as peers)
- `docs/RELEASE.md` — release procedure (manual; no upload from agent loops)
- `docs/PRIOR_ART.md` — background research
- `CHANGELOG.md` — release notes

---

## Prior art

We researched existing tools before writing this. Short version: several systems solve adjacent problems (verification receipts, process presence, full multi-agent orchestration). The niche here is a **small stage lifecycle aimed at external watchdogs**. Details: `docs/PRIOR_ART.md`.

---

## License

MIT — see `LICENSE`.

---

## Contributing

Issues and PRs welcome. Keep the scope small: lifecycle signals, not a platform.
See [`CONTRIBUTING.md`](CONTRIBUTING.md) for local setup, `.venv` test requirements, and release
boundaries.
