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

System Python on macOS refuses bare `pip install` (PEP 668, "externally
managed") — always use a venv as above.

From source (contributors):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"   # installs the `stage-signal` entry point + tests
stage-signal --help
python -m pytest          # all green
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

# orchestrator side
stage-signal status --json
stage-signal wait --state terminal --timeout 900
```

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

`status` / `wait` exit codes are part of the contract: `0` done/OK,
`1` generic/corrupt, `10` running, `11` blocked, `12` failed, `13` queued,
`14` wait timeout, `15` not initialized, `2` bad args, `3` illegal transition.

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
`stage-signal status --json` / `stage-signal wait` and exits with the
observed-state code above. Acceptance sequence: `examples/orchestrator-smoke.sh`.

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

See [`examples/cli-orchestrator-loop.md`](examples/cli-orchestrator-loop.md) for the end-to-end loop guide and [`examples/multi-cli-loop.sh`](examples/multi-cli-loop.sh) for a thin runner reusing `examples/queue-orchestrator.sh`.

### GitHub Action: wait without a venv

No preinstalled venv needed — the composite action installs `stage-signal`
from PyPI then runs `stage-signal wait`:

```yaml
- uses: syyzit/stage-signal@v0.1.1
  with:
    dir: .stage-signal   # default
    state: terminal      # done | blocked | failed | terminal (default)
    timeout: 3600        # seconds (default)
    # python-version: "3.12"  # default
    # version: "0.1.1"        # optional version pin (default: unpinned/latest)
    # pip-cache: true         # optional boolean for pip caching (default: false)
    # cache: "pip"            # optional setup-python cache (default: "")
```

Exit codes are the `wait` contract: `0` condition met, `11` blocked,
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

0.1.0: library (`src/stage_signal/`), full CLI (`init`, `start`,
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
See [`CONTRIBUTING.md`](CONTRIBUTING.md) for local setup, tests, and release
boundaries.
