# stage-signal — SPEC v1 (normative)

**Schema version:** `1`
**Ship name:** `stage-signal` · **Language:** Python 3.11+ stdlib-first
**Source of truth:** this file + `docs/PRIOR_ART.md`. The early
`docs/IMPLEMENTATION_PLAN.md` is background; on conflict this SPEC wins.

## 1. Overview

`stage-signal` is a boring filesystem + CLI contract. Any coding agent writes
stage lifecycle; any orchestrator (cron, cron, bot, or CI watchdog) reads it
via `status` / `wait` **without watching a TUI**. No daemon, no network.

## 2. On-disk layout

Default root: `.stage-signal/` in the repo (override: `--dir PATH` or
`STAGE_SIGNAL_DIR` env; `--dir` wins).

```
.stage-signal/
  STATUS.json        # normative current state (single JSON object)
  STATUS.md          # optional human mirror (best-effort, never normative)
  events.jsonl       # append-only, one JSON object per line
  locks/stage.lock   # lock file (POSIX fcntl.flock; Windows msvcrt.locking)
```

- All writes are **atomic**: write temp file in same directory + `os.replace`.
- All read-modify-write cycles hold an **exclusive lock** on `locks/stage.lock`
  (see §8). POSIX uses `fcntl.flock`; Windows uses stdlib `msvcrt.locking`
  (exclusive byte lock on byte 0; shared requests fall back to exclusive;
  no third-party dependencies). On platforms without locking primitives,
  the lock path is a best-effort no-op. Readers (`status` without mutation)
  take a shared lock where available (POSIX), else tolerate partial reads by
  retrying once.
- `events.jsonl` is append-only; never rewritten by the library (except file
  creation). Each line is a complete JSON object, UTF-8, `\n` terminated.

## 3. STATUS.json schema (schema_version 1)

```json
{
  "schema_version": 1,
  "project": "stage-signal",
  "stage_id": "m1-core-lib-001",
  "stage_name": "m1-core-lib",
  "state": "running",
  "attempt": 1,
  "session_id": "ses_abc123",
  "pid": 35736,
  "model": "provider/model-id",
  "variant": "high",
  "repo_path": "/Users/you/projects/foo",
  "git_branch": "main",
  "git_head": "4fad289",
  "started_at": "2026-09-16T04:42:11+02:00",
  "updated_at": "2026-09-16T04:48:00+02:00",
  "heartbeat_at": "2026-09-16T04:48:00+02:00",
  "heartbeat_note": null,
  "result": null,
  "error": null,
  "artifacts": [],
  "proof": null,
  "notes": [],
  "meta": {}
}
```

Field rules:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `schema_version` | int | yes | Must be `1`. Readers reject others (exit 1 / `CorruptStatusError`). |
| `project` | str | yes | Set by `init --project`, overridable by `STAGE_SIGNAL_PROJECT`. |
| `stage_id` | str\|null | yes (key present) | Stable id for one attempt-series; defaults to `stage_name` when not given. `null` before first `start` and when cleared to idle. |
| `stage_name` | str\|null | yes (key present) | Human stage name (`start --stage`). `null` before first `start` and when cleared to idle. |
| `state` | enum | yes | One of `queued\|running\|done\|blocked\|failed`. |
| `attempt` | int ≥1 | yes | Incremented on each `start` for the **same** `stage_id`; reset to 1 on new `stage_id`. Starts at 1. |
| `session_id` | str\|null | yes | Agent session claim. |
| `pid` | int\|null | yes | Claiming process pid. |
| `model`, `variant` | str\|null | yes | Informational (e.g. model id). |
| `repo_path` | str\|null | yes | Absolute path of repo at `start`/`init` time. |
| `git_branch`, `git_head` | str\|null | yes | Best-effort VCS info; refreshed from current repo on `start`; `--git-head`/`--git-branch` override. |
| `started_at` | ISO8601\|null | yes | Set on `start`; preserved until next `start`. |
| `updated_at` | ISO8601 | yes | Bumped on every mutation. |
| `heartbeat_at` | ISO8601\|null | yes | Bumped on `start` + `heartbeat`. |
| `heartbeat_note` | str\|null | yes | Last `--note`. |
| `result` | object\|null | yes | Set by `done`: `{"summary": str, "git_head": str\|null, "finished_at": ISO8601}` (plus `"accepted_failure": true` on accepted failure). Cleared on `start`/`clear-terminal`. |
| `error` | object\|null | yes | Set by `blocked`/`fail`: `{"reason": str, "kind": "blocked"\|"failed", "finished_at": ISO8601}`. Cleared on `start`/`clear-terminal`. |
| `artifacts` | list | yes | Items `{"path": str, "label": str\|null, "added_at": ISO8601}`. Preserved across heartbeats; cleared on `start` with a new `stage_id` and on `clear-terminal` without `--keep-stage`, kept on retry of same `stage_id`. |
| `proof` | object\|null | yes | Optional composition pointer, e.g. `{"tool": "agent-done-or-not", "ref": "<ledger path/label>", "verified": null\|"file"\|"verify"}`. Set by `done --proof-ref` / `--require-proof` (see §9 and `docs/COMPOSE.md`); cleared on every `start`. `verified` is `null` when recorded without checking, `"file"` when the `--require-proof` file gate passed, `"verify"` when the external verifier passed. |
| `notes` | list | yes | Items `{"text": str, "added_at": ISO8601}`; appended by `note`, capped at 200 entries (oldest dropped). Preserved across `start` (both same and new `stage_id`). |
| `meta` | object | yes | Free-form; cleared on each `start` unless new repeatable `--meta K=V` and/or raw JSON object strings are supplied (which replace `meta` entirely). Within a single `start`, entries merge in order, later wins. Invalid entries (bare word, malformed JSON, non-object JSON) are exit 2 with no mutation. |

Timestamps are ISO-8601 with timezone (UTC if none determinable, suffix `+00:00`).
`init` creates a STATUS with `state: "queued"` and null stage fields.

When status is queried via `status --json` or `Stage.status()` (as well as the
`status` snapshot in `doctor --json` and `wait --json`), the serialized payload
includes a dynamically computed `heartbeat_age_seconds`: number of elapsed
seconds since `heartbeat_at` (float ≥ 0), or `null` when no heartbeat timestamp
is recorded or unparseable. This dynamic field is computed on read and is not
persisted to `STATUS.json` on disk.
Heartbeat age is available only when `state == "running"`; for `done`, `failed`, `blocked`, or `queued`, human `status` omits `(age …)` and JSON `heartbeat_age_seconds` is `null`, even if `heartbeat_at` remains recorded.

## 4. States & transitions

```
            ┌──────────────────────────────┐
            │           queued             │◄─────────────┐
            └──────────────┬───────────────┘              │
           start           │ start              clear-terminal
                           ▼                              │
            ┌──────────────────────────────┐   done/blocked/fail/queued (same
            │           running            │   stage → idempotent OK)
            └──┬───────────┬───────────┬───┘
      done / blocked / fail (from queued or running)
               ▼           ▼           ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │   done   │ │ blocked  │ │  failed  │  (terminal)
        └──────────┘ └──────────┘ └──────────┘
```

Rules:

1. `init` — creates dir/files if missing (idempotent). Never overwrites an
   existing STATUS. Fails with exit 1 if `STATUS.json` is corrupt.
2. `start --stage NAME` — allowed from **any** state. Sets `running`, updates
   claim fields, bumps `attempt` (same `stage_id`) or resets to 1 (new
   `stage_id`), clears `result`/`error`/`proof`, sets `heartbeat_note` to null,
   clears `artifacts` only on a new `stage_id` (kept on retry), preserves
   `notes`, clears stale `meta` (replacing entirely with new `--meta` if
   supplied), refreshes `git_head` and `git_branch` from current repo (unless
   overridden), and bumps `heartbeat_at` and `updated_at`.
   Emits `start` event. This is how a previous terminal (`blocked`/`failed`/
   `done`) is cleared for a new attempt — no separate unlock needed.
3. `heartbeat [--note]` — allowed only from `running`. Bumps `heartbeat_at`,
   `updated_at`. Else exit 3.
4. `note TEXT`, `artifact PATH [--label]` — allowed only from `running`.
   Else exit 3.
5. `done [--summary] [--git-head] [--proof-ref R] [--require-proof] [--accept-failure]` —
   allowed from `queued`/`running`, plus idempotent repeat when already
   `done` **with the same `stage_id`** (updates summary, exit 0).
   Allowed from `failed` **only** when `--accept-failure` is passed (records
   `"accepted_failure": true` in `result`; from any non-failed state
   `--accept-failure` is exit 3).
   Terminal→different-terminal without an intervening `start` (or without
   `--accept-failure` on `failed`) is exit 3.
   `--require-proof` verifies proof *before* mutating (see §9); on failure
   exit 3 and no mutation.
6. `blocked --reason`, `fail --reason [--if-dead-pid]` — same rule as `done` with `error`
   payload instead of `result`.
   With `--if-dead-pid`, a `running` stage transitions to `failed` (exit 0)
   only when its claiming `pid` is a positive integer (not a boolean) confirmed
   dead. A live, null/invalid PID or unknown liveness causes exit 3 without
   changing status, events, or mirrors; an absent required `pid` key is corrupt
   status (exit 1, also no mutation). The guard is checked under the mutation lock.
   Outside `running`, normal fail rules apply: `queued` and `failed` allow fail,
   while `done` and `blocked` reject it (exit 3). `doctor` remains advisory-only.
7. `clear-terminal [--keep-stage]` — allowed from `done`/`blocked`/`failed`/`queued`;
   resets to `queued`. By default, clears stage identity (`stage_id` and
   `stage_name` set to `null`, clearing claim/heartbeat/session/pid/proof/
   artifacts/meta and resetting to true idle queued). If `--keep-stage` is given,
   preserves previous `stage_id` and `stage_name` to re-queue the same stage.
   From `running` it is exit 3.
8. Every mutation appends exactly one event to `events.jsonl` and rewrites
   `STATUS.md` best-effort.

### Idle vs. Queued (orchestrator contract)

A stage dir in `state: queued` with `stage_name: null` and `stage_id: null` represents
a clean **idle** worktree (created by `init` or reset via `clear-terminal`). An
orchestrator or watchdog observing `status` sees `queued - (attempt 1)` and knows no
stage work is currently pending or abandoned. In contrast, `state: queued` with a
non-null `stage_name` represents an actively queued stage awaiting execution.

After a stage failure, or when abandoning a parked or stuck queued stage, orchestrators can choose between clean end states:
- **Return to idle:** `stage-signal clear-terminal` clears stage identity to null,
  signaling that the failure or stuck queued stage was handled and the runner is idle.
- **Accept failure:** `stage-signal done --accept-failure --summary "reason"` marks
  the lifecycle `done` while recording `"accepted_failure": true`, without inventing
  a fake success.

### Staleness (v1 policy)

The library **never auto-mutates** on staleness. A `running` stage with an old
`heartbeat_at` (e.g. after `kill -9`) stays `running`. Orchestrators decide via
`doctor --stale-after SEC` / `status --json` (`heartbeat_at`) what "stale"
means. `doctor` reports staleness; it does not change state.

Similarly, when `state == running` and a claiming `pid` is recorded, `doctor`
performs an advisory best-effort liveness check (POSIX `os.kill(pid, 0)` /
Windows API). If the claiming PID is dead while the stage is still `running`,
`doctor` reports a warning (`DEAD PID: claiming pid N is not alive (state still running); reclaim with 'fail --reason TEXT --if-dead-pid'`).
The check is strictly advisory: the library never auto-transitions or mutates
state; orchestrators decide whether to clear, fail, or restart.

## 5. events.jsonl

Each event: `{"ts": ISO8601, "type": str, "stage_id": str|null,
"stage_name": str|null, "state": str, "attempt": int, "message": str|null,
"detail": object}`.

`type` ∈ `init|start|heartbeat|note|artifact|done|blocked|failed|clear_terminal`.
`message` is the human summary (note text / reason / heartbeat note).
`detail` carries extras (artifact path+label, proof ref, pid, session).

## 6. CLI contract

```
stage-signal [--dir PATH] <command> [args]
stage-signal init [--project NAME]
stage-signal start --stage NAME [--stage-id ID] [--session ID] [--pid N]
             [--model M] [--variant V] [--git-head H] [--git-branch B] [--meta K=V|JSON ...]
             [--write-status-mirror]
stage-signal heartbeat [--note TEXT]
stage-signal note TEXT
stage-signal artifact PATH [--label LABEL]
stage-signal done [--summary TEXT] [--git-head H] [--proof-ref R] [--require-proof]
             [--accept-failure] [--write-status-mirror]
stage-signal blocked --reason TEXT [--write-status-mirror]
stage-signal fail --reason TEXT [--if-dead-pid] [--write-status-mirror]
stage-signal status [--json]
stage-signal wait [--state done|blocked|failed|terminal] [--timeout SEC] [--poll SEC] [--json]
stage-signal clear-terminal [--keep-stage]
stage-signal doctor [--stale-after SEC] [--json] [--format human|json]
```

- `--dir` / `STAGE_SIGNAL_DIR`: stage dir (default `.stage-signal`).
- `start --meta` is repeatable and accepts two forms, merged in order
  (later wins): `K=V` (value kept as a string; value may contain `=`;
  `K=` means empty string) or a single raw JSON object string per entry
  (e.g. `'{"ticket": 42, "flag": true}'`; JSON types — numbers, bools,
  null, nested objects/arrays — are preserved). On each `start`, previous
  meta is cleared; any new `--meta` flags replace the previous meta entirely.
  Bare words, malformed JSON, and non-object JSON are bad args (exit 2) with
  no mutation. Implemented stdlib-only (`json`), no new dependencies.
- `wait` defaults: `--state terminal --timeout 3600 --poll 5`.
  Exit 0 when the wanted condition is met. If a *different* terminal state is
  reached first, exit with that state's code (11/12) — not 0, not 14.
  Exit 14 only on true timeout. `wait` on a non-initialized dir is exit 15.
  `--json` prints one JSON object on stdout across all outcomes (`outcome`:
  `"met"` | `"mismatch"` | `"timeout"`, `wanted`, `observed_state` / `state`,
  `exit_code`, `timeout`, `stage_id`, `dir`, `reason`, and the `status`
  snapshot) with human output omitted, preserving the exit-code contract.
  `reason` is a short string when the observed state is `blocked` or `failed`
  (from `status.error.reason`) or when the wait timed out (the timeout
  message); otherwise `null`. Human default output is unchanged without
  `--json`.
- `status` prints human text by default (including heartbeat age, e.g.
  `heartbeat: <ISO> (age 42s)`, when a heartbeat is recorded); with `--json`, it
  prints the status payload as a JSON object, including dynamic
  `heartbeat_age_seconds` (number of elapsed seconds since `heartbeat_at`, or
  `null` when no heartbeat is recorded).
  The JSON payload also always includes `needs_reclaim: bool` with the same
  semantics as the `doctor` field of the same name: `true` exactly when the
  state is `running` and a `DEAD_PID` or `STALE_HEARTBEAT` warning applies
  (computed by the same detection logic as `doctor` / `Stage.diagnose()` with
  the default 300-second threshold); `false` otherwise, including healthy
  running and non-running states. `status` warnings remain advisory only and
  the exit code always reflects state (§7).
  Its exit code always reflects state (§7), so orchestrators can
  `stage-signal status` / `wait` in shell `if` directly.
- `doctor` checks: dir exists, STATUS parses + schema ok, events.jsonl
  readable, lock writable. When `state == running` and `pid` is an int,
  best-effort checks whether the claiming process is alive (POSIX
  `os.kill(pid, 0)`, Windows API; warning on dead PID). Prints summary
  line (`OK: <state>` or `ATTENTION: running needs reclaim`) / problems;
  exit 0 when healthy or warnings present (advisory check), 1 otherwise (problems
  present). When `state == running` and either `STALE_HEARTBEAT` or `DEAD_PID`
  warning applies, the summary line does not report `OK: running`, but instead
  outputs `ATTENTION: running needs reclaim` (both in human text and the JSON
  `summary` field), alerting operators and orchestrators that reclaim is required.
  `doctor` and `Stage.diagnose()` default to a 300-second (5-minute) heartbeat threshold,
  overridable with `--stale-after SEC`.
  When `running` and `now - heartbeat_at > SEC`, human output prints
  `WARNING: STALE: ...`.
  `--json` (or `--format json`) prints a structured JSON object:
  `{"ok": bool, "needs_reclaim": bool, "state": str|null, "problems": list[str], "warnings": [{"code": str, "message": str, "detail": object}], "status": object|null, "summary": str|null}`.
  `Stage.diagnose()` returns the same fields. `needs_reclaim` is always present:
  `true` exactly when the state is `running` and a `DEAD_PID` or
  `STALE_HEARTBEAT` warning applies; `false` otherwise, including healthy running,
  non-running states, and missing/unreadable status without reclaim warnings.
  It is independent of `ok` (which means no problems) and remains `true` if
  reclaim warnings coexist with problems. Reclaim warnings alone do not change
  `ok: true` or exit 0.
  Structured warning codes include:
  - `STALE_HEARTBEAT`: heartbeat older than threshold (detail: `{"age": float|null, "threshold": float, "heartbeat_at": str|null}`) or missing entirely.
  - `DEAD_PID`: claiming process is not alive (detail: `{"pid": int, "recovery_hint": str}`).
    The warning message includes an explicit recovery hint naming `fail --reason TEXT --if-dead-pid`.
  - `UNPARSEABLE_HEARTBEAT`: invalid heartbeat timestamp format (detail: `{"heartbeat_at": str}`).
  Warnings never change stage state and do not trigger a non-zero exit code (exit 0 on healthy/warnings, 1 on problems, 2 on bad args); orchestrators should branch on the `needs_reclaim` boolean rather than string-matching `summary` or scraping human warning text.
  Passing `--exit-reclaim` causes `doctor` to exit 10 when `needs_reclaim` is true (while still printing human/JSON output as requested). When `--exit-reclaim` is set and `needs_reclaim` is false, standard exit codes are preserved (0 on healthy/warnings, 1 on problems, 2 on bad args). Without the flag, behavior is unchanged (reclaim warnings stay exit 0).
  Passing `stale_after=None` to `Stage.diagnose()` disables heartbeat checks.

## 7. Exit codes (part of the contract)

| Code | Meaning |
|------|---------|
| 0 | OK / wait condition met |
| 1 | Generic error (IO, corrupt file incl. unsupported schema version, doctor problems) |
| 2 | Bad args |
| 3 | Illegal transition / failed `--require-proof` gate |
| 10 | State is `running` (`status`/`wait` mismatch reporting); or `doctor --exit-reclaim` when `needs_reclaim` is true |
| 11 | State is `blocked` |
| 12 | State is `failed` |
| 13 | State is `queued` |
| 14 | `wait` timeout |
| 15 | Not initialized (missing dir/STATUS) |

`done`/`blocked`/`failed` terminal commands exit 0 on success (they *perform*
the transition); the 10–13 codes are for *observing* (`status`/`wait`) only (and exit 10 for `doctor --exit-reclaim` when reclaim is needed).

## 8. Concurrency & atomicity

- **Inter-process locking on `locks/stage.lock`:**
  - **POSIX (Linux, macOS):** Exclusive `fcntl.flock(LOCK_EX)` on `locks/stage.lock`
    for every mutation; shared `LOCK_SH` (fallback: exclusive) for reads.
  - **Windows:** Standard library `msvcrt.locking` provides an exclusive byte lock
    on byte 0 of `locks/stage.lock` with non-blocking retry polling (up to 10s).
    Shared lock requests fall back to exclusive byte locking (msvcrt lacks shared locks).
    No third-party packages (e.g. portalocker, pywin32) are required.
  - **Non-locking environments:** If neither `fcntl` nor `msvcrt` is available,
    `StageStore.locked()` is a best-effort no-op (`yield`). Do not assume Windows
    or other platforms have POSIX `flock`.
- **Atomic writes & event durability:**
  - All platforms: temp-file in the stage directory + atomic `os.replace` for `STATUS.json` writes.
  - `open(..., "a")` + flush + `os.fsync` for `events.jsonl` appends while holding the lock.
  - Readers tolerate partial/torn reads by retrying once before reporting corruption (SPEC §2).
- Concurrent heartbeats are safe: last writer wins on `heartbeat_at`, no event
  loss (append under lock), schema stays valid. Covered by a threads test.

## 9. Proof composition (`--require-proof`)

- `done --proof-ref R` records `proof={"tool":"agent-done-or-not","ref":R}`
  without verification.
- `done --require-proof [--proof-ref R]` additionally verifies *before*
  mutating: if `R` (or `STAGE_SIGNAL_PROOF_REF` env) names an existing file,
  it must exist and be non-empty; otherwise the tool runs
  `agent-done-or-not verify --ref R` (if that binary exists on PATH) and treats
  non-zero exit as gate failure. If neither a file nor the binary exists, the
  gate fails closed (exit 3). Rationale: never silently claim proof.
- The library never shells out except for this explicitly requested gate.

## 10. Optional `.orch` status mirror

`--write-status-mirror` (or `STAGE_SIGNAL_STATUS_MIRROR=1`) on
`start`/`done`/`blocked`/`fail` best-effort writes `<repo>/.orch/STATUS.md`
(`state: <state>` + stage + updated) and touches `<repo>/.orch/DONE` when
the new state is `done`. Mirror failures warn on stderr but never fail the
command. Repo root = parent of the stage dir when the dir is named
`.stage-signal`, else `cwd`. See `docs/COMPOSE.md`.

## 11. Library API (Python)

```python
from stage_signal import Stage, StageError, IllegalTransition, NotInitialized, state_exit_code

with Stage.open(".stage-signal") as s:   # scoped use; use Stage(dir) + context manager the same way
    s.init(project="myproj")
    s.start(stage="impact-clarity", session_id="ses_...", pid=123)
    s.heartbeat(note="tests green")
    s.note("checkpoint")
    s.artifact("dist/app.whl", label="wheel")
    s.done(summary="merge 9f38343", git_head="9f38343")
    print(s.status())
```

- `Stage.open(dir)` → context-managed `Stage`. Plain `Stage(dir)` also works;
  mutations are one-shot locked internally in both cases.
- Errors: `StageError` (code 1) → `BadArgsError` (2), `IllegalTransition` (3),
  `NotInitialized` (15), `CorruptStatusError` (1), `WaitTimeout` (14). Each carries `.exit_code`.
- `state_exit_code(state) -> int` maps state → 10/11/12/13 (and `done` → 0).

## 12. Testing strategy

- Unit: transitions, idempotency, exit-code map, atomic IO, corrupt/lock tests.
- Concurrency: N threads × M heartbeats → valid STATUS, exact event count.
- CLI integration: subprocess per command incl. `wait` (background `done`),
  timeout path, proof gate paths (missing/empty/existing file).
- Chaos note: `kill -9` ⇒ stale `running`; `doctor --stale-after` or dead-PID check must flag it.
