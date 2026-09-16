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
| `stage_id` | str\|null | yes (key present) | Stable id for one attempt-series; defaults to `stage_name` when not given. `null` only before first `start`. |
| `stage_name` | str\|null | yes (key present) | Human stage name (`start --stage`). `null` only before first `start`. |
| `state` | enum | yes | One of `queued\|running\|done\|blocked\|failed`. |
| `attempt` | int ≥1 | yes | Incremented on each `start` for the **same** `stage_id`; reset to 1 on new `stage_id`. Starts at 1. |
| `session_id` | str\|null | yes | Agent session claim. |
| `pid` | int\|null | yes | Claiming process pid. |
| `model`, `variant` | str\|null | yes | Informational (e.g. model id). |
| `repo_path` | str\|null | yes | Absolute path of repo at `start`/`init` time. |
| `git_branch`, `git_head` | str\|null | yes | Best-effort VCS info; `--git-head` overrides. |
| `started_at` | ISO8601\|null | yes | Set on `start`; preserved until next `start`. |
| `updated_at` | ISO8601 | yes | Bumped on every mutation. |
| `heartbeat_at` | ISO8601\|null | yes | Bumped on `start` + `heartbeat`. |
| `heartbeat_note` | str\|null | yes | Last `--note`. |
| `result` | object\|null | yes | Set by `done`: `{"summary": str, "git_head": str\|null, "finished_at": ISO8601}`. Cleared on `start`/`clear-terminal`. |
| `error` | object\|null | yes | Set by `blocked`/`fail`: `{"reason": str, "kind": "blocked"\|"failed", "finished_at": ISO8601}`. Cleared on `start`/`clear-terminal`. |
| `artifacts` | list | yes | Items `{"path": str, "label": str\|null, "added_at": ISO8601}`. Preserved across heartbeats; cleared on `start` with a new `stage_id`, kept on retry of same `stage_id`. |
| `proof` | object\|null | yes | Optional composition pointer, e.g. `{"tool": "agent-done-or-not", "ref": "<ledger path/label>", "verified": null\|"file"\|"verify"}`. Set by `done --proof-ref` / `--require-proof` (see §9 and `docs/COMPOSE.md`); cleared on every `start`. `verified` is `null` when recorded without checking, `"file"` when the `--require-proof` file gate passed, `"verify"` when the external verifier passed. |
| `notes` | list | yes | Items `{"text": str, "added_at": ISO8601}`; appended by `note`, capped at 200 entries (oldest dropped). Preserved across `start` (both same and new `stage_id`). |
| `meta` | object | yes | Free-form; `start` merges repeatable `--meta K=V` (value kept as string) and/or raw JSON object strings (e.g. `'{"ticket": 42}'`, JSON types preserved). Entries merge in order, later wins. Invalid entries (bare word, malformed JSON, non-object JSON) are exit 2 with no mutation. |

Timestamps are ISO-8601 with timezone (UTC if none determinable, suffix `+00:00`).
`init` creates a STATUS with `state: "queued"` and null stage fields.

## 4. States & transitions

```
            ┌──────────────────────────────┐
            │           queued             │◄─────────────┐
            └──────────────┬───────────────┘              │
           start           │ start              clear-terminal
                           ▼                              │
            ┌──────────────────────────────┐   done/blocked/fail (same
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
   `notes`/`meta` (merges new `--meta`), and bumps `heartbeat_at` and
   `updated_at`.
   Emits `start` event. This is how a previous terminal (`blocked`/`failed`/
   `done`) is cleared for a new attempt — no separate unlock needed.
3. `heartbeat [--note]` — allowed only from `running`. Bumps `heartbeat_at`,
   `updated_at`. Else exit 3.
4. `note TEXT`, `artifact PATH [--label]` — allowed only from `running`.
   Else exit 3.
5. `done [--summary] [--git-head] [--proof-ref R] [--require-proof]` —
   allowed from `queued`/`running`, plus idempotent repeat when already
   `done` **with the same `stage_id`** (updates summary, exit 0).
   Terminal→different-terminal without an intervening `start` is exit 3.
   `--require-proof` verifies proof *before* mutating (see §9); on failure
   exit 3 and no mutation.
6. `blocked --reason`, `fail --reason` — same rule as `done` with `error`
   payload instead of `result`.
7. `clear-terminal` — allowed only from `done`/`blocked`/`failed`; sets
   `queued` (keeps stage identity, clears `result`/`error`). From
   `queued`/`running` it is exit 3.
8. Every mutation appends exactly one event to `events.jsonl` and rewrites
   `STATUS.md` best-effort.

### Staleness (v1 policy)

The library **never auto-mutates** on staleness. A `running` stage with an old
`heartbeat_at` (e.g. after `kill -9`) stays `running`. Orchestrators decide via
`doctor --stale-after SEC` / `status --json` (`heartbeat_at`) what "stale"
means. `doctor` reports staleness; it does not change state.

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
             [--write-status-mirror]
stage-signal blocked --reason TEXT [--write-status-mirror]
stage-signal fail --reason TEXT [--write-status-mirror]
stage-signal status [--json]
stage-signal wait [--state done|blocked|failed|terminal] [--timeout SEC] [--poll SEC]
stage-signal clear-terminal
stage-signal doctor [--stale-after SEC]
```

- `--dir` / `STAGE_SIGNAL_DIR`: stage dir (default `.stage-signal`).
- `start --meta` is repeatable and accepts two forms, merged in order
  (later wins): `K=V` (value kept as a string; value may contain `=`;
  `K=` means empty string) or a single raw JSON object string per entry
  (e.g. `'{"ticket": 42, "flag": true}'`; JSON types — numbers, bools,
  null, nested objects/arrays — are preserved). Bare words, malformed
  JSON, and non-object JSON are bad args (exit 2) with no mutation.
  Implemented stdlib-only (`json`), no new dependencies.
- `wait` defaults: `--state terminal --timeout 3600 --poll 5`.
  Exit 0 when the wanted condition is met. If a *different* terminal state is
  reached first, exit with that state's code (11/12) — not 0, not 14.
  Exit 14 only on true timeout. `wait` on a non-initialized dir is exit 15.
- `status` prints human text by default, raw `STATUS.json` with `--json`.
  Its exit code always reflects state (§7), so orchestrators can
  `stage-signal status` / `wait` in shell `if` directly.
- `doctor` checks: dir exists, STATUS parses + schema ok, events.jsonl
  readable, lock writable. Prints `OK` lines / problems; exit 0 when healthy,
  1 otherwise. `--stale-after SEC` adds a `STALE` warning when `running` and
  `now - heartbeat_at > SEC` (still exit 0 unless other problems; stale alone
  is a warning, reported as `STALE ...` line).

## 7. Exit codes (part of the contract)

| Code | Meaning |
|------|---------|
| 0 | OK / wait condition met |
| 1 | Generic error (IO, corrupt file incl. unsupported schema version, doctor problems) |
| 2 | Bad args |
| 3 | Illegal transition / failed `--require-proof` gate |
| 10 | State is `running` (`status`/`wait` mismatch reporting) |
| 11 | State is `blocked` |
| 12 | State is `failed` |
| 13 | State is `queued` |
| 14 | `wait` timeout |
| 15 | Not initialized (missing dir/STATUS) |

`done`/`blocked`/`failed` terminal commands exit 0 on success (they *perform*
the transition); the 10–13 codes are for *observing* (`status`/`wait`) only.

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
- Chaos note: `kill -9` ⇒ stale `running`; `doctor --stale-after` must flag it.
