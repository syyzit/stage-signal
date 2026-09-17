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
  "pid_token": null,
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
| `pid_token` | str\|null | no (optional) | Opaque process-start identity captured best effort by `Stage.start`; missing/null means unavailable (including legacy statuses). Replaced on every start, cleared with `pid` on idle reset, preserved with `clear-terminal --keep-stage` or `reclaim --keep-failed`. |
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
   `notes`, clears stale `meta` (replacing entirely with new `--meta` if
   supplied), refreshes `git_head` and `git_branch` from current repo (unless
   overridden), and bumps `heartbeat_at` and `updated_at`.
   `Stage.start` captures an opaque process-start identity in `pid_token` for
   the claiming PID: Linux `/proc/<pid>/stat` field 22 (start time), macOS
   `ps` `lstart` with stable locale and timezone, or Windows `GetProcessTimes`
   (best effort). Unavailable capture never prevents start. Every start
   replaces the previous token with the newly captured value or `null`,
   including retries of the same stage.
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
6. `blocked --reason`, `fail --reason [--if-dead-pid|--if-needs-reclaim]` — same rule as `done` with `error`
   payload instead of `result`.
   With `--if-dead-pid`, a `running` stage transitions to `failed` (exit 0)
   only when its claiming `pid` is a positive integer (not a boolean) confirmed
   dead. A live, null/invalid PID or unknown liveness causes exit 3 without
   changing status, events, or mirrors; an absent required `pid` key is corrupt
   status (exit 1, also no mutation). The guard is checked under the mutation lock.
   Outside `running`, normal fail rules apply: `queued` and `failed` allow fail,
   while `done` and `blocked` reject it (exit 3).
   With `--if-needs-reclaim`, the transition to `failed` (exit 0) succeeds
   **only** when `needs_reclaim` would be true under the same detection as
   `Stage.diagnose()` / `doctor` / `status` (default 300-second heartbeat
   threshold): `state == running` and a `DEAD_PID` or `STALE_HEARTBEAT`
   warning applies. When `needs_reclaim` is false (healthy running,
   non-running states, or only `UNPARSEABLE_HEARTBEAT`), exit 3 with a clear
   message and no mutation of status, events, or mirrors. The guard is
   checked under the mutation lock. `--if-dead-pid` and `--if-needs-reclaim`
   are mutually exclusive (exit 2). `doctor` remains advisory-only.
7. `reclaim --reason TEXT [--keep-failed] [--kill]` — one-shot reclaim for a `running` stage
   when `needs_reclaim` is true (same detection as `doctor` / `status` / `fail --if-needs-reclaim`:
   `state == running` and a `DEAD_PID` or `STALE_HEARTBEAT` warning applies).
   Under a single exclusive lock, transitions the stage to `failed` with `--reason`
   (emitting a `failed` event with `detail: {"reclaim": True, "keep_failed": ...}`),
   and — unless `--keep-failed` is passed — immediately resets the stage via `clear-terminal`
   to idle `queued` with stage identity cleared (emitting a `clear_terminal` event with
   `detail: {"keep_stage": False, "reclaim": True}`). When `needs_reclaim` is false
   (healthy running, non-running states), exit 3 with a clear message and no mutation of
   status, events, or mirrors. `--keep-failed` stops after the `failed` transition without
   clearing, allowing watchdog audit before manual `clear-terminal`.
   `--kill` defaults to false. When enabled, **after** the `needs_reclaim` guard
   passes and **before** fail+clear, best-effort terminate the recorded PID only
   if it is a valid positive integer (not a boolean) and the shared
   `_is_pid_alive` helper confirms it is alive. Send `SIGTERM`, wait up to
   1 second polling liveness every 50ms, then send `SIGKILL` only if still alive.
   Dead, null, invalid, or unknown-liveness PIDs receive no termination signal;
   reclaim still proceeds if the guard passed (for example, on a stale heartbeat).
   When a non-null `pid_token` is recorded, re-read the process-start identity
   and compare it with that token before **each** termination signal: both
   the initial `SIGTERM` and any escalation. A mismatch or unreadable current
   identity warns on stderr and skips the signal; fail+clear (or `failed`
   without clearing with `--keep-failed`) still proceeds. Missing or null
   tokens, including legacy statuses, preserve existing best-effort kill
   behavior without identity verification.
   Permission/OS errors warn on stderr and do not prevent fail+clear. On Windows,
   `SIGTERM` terminates the process; when `SIGKILL` is unavailable, escalation
   falls back to `SIGTERM` with the same identity check. Guard, liveness and
   identity checks, signals, wait, and fail+clear all remain under the same
   exclusive lock. A rejected guard exits 3 without
   signals or mutation, even with `--kill`. `--kill --keep-failed` performs the
   same termination attempt but stops after `failed`.
   Without `--kill`, no termination signals are sent and existing event shapes
   remain unchanged (no added kill-related fields). Liveness probes may still run.
   This targets only the recorded PID, not a process group or descendants.
   Identity verification reduces PID reuse risk but cannot eliminate the race
   between checking identity and sending a signal, or low-resolution identity
   collisions. Successful reclaim does not guarantee the worker has stopped,
   particularly after skipped signals or permission errors. Orchestrators needing
   that guarantee must verify termination before relaunching.
8. `clear-terminal [--keep-stage]` — allowed from `done`/`blocked`/`failed`
   **and** from `queued` (abandon a parked or idle queued stage). Resets to
   `queued`. By default, clears stage identity (`stage_id` and
   `stage_name` set to `null`, clearing claim/heartbeat/session/pid/pid_token/proof/
   artifacts/meta and resetting to true idle queued). If `--keep-stage` is given,
   preserves previous `stage_id` and `stage_name` to re-queue the same stage,
   retaining `pid` and `pid_token`. `reclaim --keep-failed` also preserves both;
   an idle reset clears them together.
   From `running` it is exit 3 (reclaim a stuck running stage with
   `reclaim`, `fail --if-needs-reclaim`, or `fail --if-dead-pid` first). Each call
   appends a `clear_terminal` event (audit).
9. Every mutation appends exactly one event to `events.jsonl` and rewrites
   `STATUS.md` best-effort (`reclaim` appends two events: `failed` then `clear_terminal`,
   or only `failed` when `--keep-failed`).

### Idle vs. Queued (orchestrator contract)

A stage dir in `state: queued` with `stage_name: null` and `stage_id: null` represents
a clean **idle** worktree (created by `init` or reset via `clear-terminal`). An
orchestrator or watchdog observing `status` sees `queued - (attempt 1)` and knows no
stage work is currently pending or abandoned. In contrast, `state: queued` with a
non-null `stage_name` represents an actively queued stage awaiting execution.
`clear-terminal` from `queued` (named or idle) is the supported abandon path:
it resets to idle queued and appends a `clear_terminal` event, without requiring
a terminal state first and without hand-editing STATUS files. From `running`,
`clear-terminal` stays illegal; use `reclaim --reason TEXT` (or `fail --if-needs-reclaim`
/ `fail --if-dead-pid`) to move a stuck running stage to `failed` (or idle queued) first.

After a stage failure, orchestrators can choose between two clean end states:
- **Return to idle:** `stage-signal clear-terminal` clears stage identity to null,
  signaling that the failure was handled and the runner is idle.
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

Orchestrators **must not scrape** `events.jsonl` with `tail`/`jq`. The first-class
read path is:

- CLI: `stage-signal events [--tail N] [--type TYPE] [--json]`
- Library: `Stage.events(*, tail=None, type=None) -> list[dict]`

Human CLI output is chronological (**newest last**, matching file order).
`--tail N` keeps the last N matching events (default 20; `0` = all).
`--type` filters to one SPEC event type **before** `--tail` (so
`--type failed --tail 5` is the last 5 `failed` events). `--json` prints a
JSON array (pretty-printed, one array — not NDJSON), matching other
`--json` commands that emit JSON values rather than line-oriented records.
Both paths take a shared lock like `status`. Missing/uninitialized STATUS
is exit 15 / `NotInitialized`. A totally unreadable file, or any single
unparseable JSON line, is fail-closed (`CorruptStatusError`, exit 1).
Blank lines are skipped. After `fail --if-needs-reclaim` or
`clear-terminal`, use `events` to audit the reclaim/abandon trail.

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
stage-signal fail --reason TEXT [--if-dead-pid|--if-needs-reclaim] [--write-status-mirror]
stage-signal reclaim --reason TEXT [--keep-failed] [--kill] [--write-status-mirror]
stage-signal status [--json]
stage-signal events [--tail N] [--type TYPE] [--json]
stage-signal wait [--state done|blocked|failed|terminal] [--needs-reclaim]
             [--timeout SEC] [--poll SEC] [--json]
stage-signal clear-terminal [--keep-stage]
stage-signal doctor [--stale-after SEC] [--json] [--format human|json]
stage-signal supervise [--every SEC] [--dir DIR] [--summary SUMMARY] [--reason REASON]
             [--write-status-mirror] -- CMD [ARGS...]
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
  `--needs-reclaim` is an alternate wait target (cannot be combined with
  `--state` other than the default `terminal`). It polls until
  `needs_reclaim` is true under the same detection as `status --json` /
  `doctor` / `Stage.diagnose()` (default 300s stale threshold): `running`
  plus `DEAD_PID` or `STALE_HEARTBEAT`. Exit 0 when that boolean becomes
  true. Healthy `running` keeps polling — never treat `status` / `doctor
  --exit-reclaim` exit 10 as wait success. `queued` also keeps polling
  (reclaim can only become true after `start`). Terminal
  `done`/`blocked`/`failed` without reclaim **fails closed** immediately:
  reuse the existing mismatch codes (`blocked` → 11, `failed` → 12);
  `done` cannot reuse 0, so it exits **1**. Library:
  `Stage.wait(..., needs_reclaim=True)` (keyword-only) shares this poll
  loop; a terminal-without-reclaim snapshot is returned (not raised) so
  the caller maps the non-zero mismatch. The reclaim loop for
  orchestrators is `wait --needs-reclaim` → `reclaim --reason ... --kill` → `start`
  (or `reclaim --reason ... --kill --keep-failed` → optional `events` audit → `clear-terminal` / restart,
  or the explicit two-step `fail --if-needs-reclaim` → `clear-terminal`) — not a hand-rolled
  `doctor` sleep.
  `--json` prints one JSON object on stdout across all outcomes (`outcome`:
  `"met"` | `"mismatch"` | `"timeout"`, `wanted`, `observed_state` / `state`,
  `exit_code`, `timeout`, `stage_id`, `dir`, `reason`, `needs_reclaim`, and
  the `status` snapshot) with human output omitted, preserving the
  exit-code contract. `wanted` is the `--state` value, or `"needs_reclaim"`
  when `--needs-reclaim` is set. Top-level `needs_reclaim` is the same
  boolean as `status --json` / `doctor --json` (also nested on `status`
  when a snapshot is present). `reason` is a short string when the observed
  state is `blocked` or `failed` (from `status.error.reason`) or when the
  wait timed out (the timeout message); otherwise `null`. Human default
  output is unchanged without `--json`.
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
- `events` prints recent `events.jsonl` records for orchestrator audit
  (do not scrape the file). Human default is chronological, newest last.
  `--tail N` is the last N matching events (default 20; `0` = all).
  `--type` is one of `init|start|heartbeat|note|artifact|done|blocked|failed|clear_terminal`,
  applied before `--tail`. `--json` prints a JSON array (not NDJSON),
  consistent with other `--json` commands emitting JSON values.
  Exit 0 on success, 15 if not initialized, 1 if the log is unreadable or a
  line is corrupt (fail-closed; blank lines skipped), 2 on bad args.
  Library: `Stage.events(*, tail=None, type=None) -> list[dict]` with
  `tail=None` or `0` meaning all (CLI default 20 is a CLI-only convenience).
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
  Orchestrators that need to **wait** until `needs_reclaim` is true should
  use `wait --needs-reclaim` (not a `doctor` sleep loop), then reclaim with
  `reclaim --reason TEXT --kill` (or `fail --reason TEXT --if-needs-reclaim`
  when only a state transition, without termination, is wanted).
  For snapshot checks, orchestrators can branch on `doctor --exit-reclaim` (exits 10 on needs_reclaim)
  or use `orchestrator-watchdog.sh --once --doctor-reclaim` (reclaims via `reclaim --keep-failed`
  and exits 12). `fail --if-dead-pid` remains the narrower DEAD_PID-only gate. `doctor` itself never mutates.
  Passing `stale_after=None` to `Stage.diagnose()` disables heartbeat checks.
- `reclaim --reason TEXT [--keep-failed] [--kill]` is the one-shot pairing for `wait --needs-reclaim`.
  When `needs_reclaim` is true (`running` + `DEAD_PID` or `STALE_HEARTBEAT`, same detection
  as `doctor` / `status` / `fail --if-needs-reclaim`), it transitions to `failed` with `--reason`
  and immediately clears to idle `queued` (stage identity reset to null) under a single
  exclusive lock. Two events are appended to `events.jsonl`: `failed` followed by
  `clear_terminal`. When `needs_reclaim` is false, it exits 3 with no mutation. Passing
  `--keep-failed` stops after the `failed` transition without clearing, leaving the state as
  `failed` for watchdog inspection before manual `clear-terminal`. `--kill` (default false)
  opts into best-effort termination of a valid, alive recorded PID before mutation,
  only after the guard passes; see §4 rule 7 for timing, platform behavior, and limits.
  It is compatible with `--keep-failed`. Mutators do not support `--json`.
- `supervise [--every SEC] [--dir DIR] [--summary SUMMARY] [--reason REASON] [--write-status-mirror] -- CMD [ARGS...]`:
  Runs and supervises a child process `CMD`, automatically bumping stage `heartbeat` every `--every`
  seconds (default 60; validated `1 <= every <= stale_threshold - 1`, default stale threshold 300)
  while the child process is alive. The stage must already be in state `running` (refuses with exit 3 /
  `IllegalTransition` otherwise; exit 15 / `NotInitialized` if not initialized).
  After `Popen` successfully spawns the child, `supervise` updates STATUS under exclusive lock:
  sets `pid` to the child's `proc.pid`, refreshes `pid_token` via the existing identity capture
  (or `null` if capture fails, same as `start`), and bumps `updated_at` and `heartbeat_at`.
  `stage_id`, `stage_name`, `attempt`, and `session_id` are preserved unchanged. This ensures
  `doctor` liveness checks and `reclaim --kill` target the active child worker rather than the supervisor
  wrapper. When the child process exits 0, transitions to `done` with `--summary` (default:
  `'command succeeded (exit 0): CMD'`). When the child process exits non-zero, transitions to `failed`
  with `--reason` (default: `'command failed with exit code N: CMD'` or `'command terminated by SIGNUM: CMD'`).
  Signals (`SIGINT`, `SIGTERM`) are forwarded to the child process; the supervisor waits for child
  exit and records the terminal transition before returning (pid lifecycle unchanged after that).
  Exit code matches the child process exit code (or `128 + SIGNUM` if terminated by signal, 2 on bad args,
  3 on illegal transition, 15 if not initialized, 127 if command not found, 126 if permission denied).
  Library: `Stage.supervise(cmd, *, every=60.0, stale_threshold=300.0, summary=None, reason=None, write_status_mirror=None, cwd=None, env=None) -> int`.

## 7. Exit codes (part of the contract)

| Code | Meaning |
|------|---------|
| 0 | OK / wait condition met (including `wait --needs-reclaim` when `needs_reclaim` is true) |
| 1 | Generic error (IO, corrupt file incl. unsupported schema version, doctor problems); also `wait --needs-reclaim` when the stage reached `done` without reclaim (fail closed; cannot reuse 0) |
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
`supervise` returns the child process exit code (or `128 + SIGNUM` on signal termination, 127 when not found, 126 on permission denied; standard error exit codes 2, 3, 15 apply on setup/precondition failures).

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
    print(s.events(tail=20, type="failed"))  # newest last; type filter then tail
```

- `Stage.open(dir)` → context-managed `Stage`. Plain `Stage(dir)` also works;
  mutations are one-shot locked internally in both cases.
- `s.reclaim(reason, *, keep_failed=False, kill=False) -> dict` fails a `needs_reclaim`
  running stage and clears to idle queued under one exclusive lock; raises
  `IllegalTransition` (exit 3) without signals or mutation when `needs_reclaim` is false.
  `kill=True` uses the shared `_is_pid_alive` helper used by doctor/status and follows
  the same guarded, best-effort termination contract as CLI `--kill` (§4 rule 7).
  `keep_failed=True` skips clearing, independently of `kill`.
- `s.events(*, tail=None, type=None) -> list[dict]` reads `events.jsonl`
  (shared lock; chronological, newest last). `type` filters first; `tail`
  `None` or `0` means all (CLI default 20 is CLI-only). Same corrupt-line
  policy as §5 (fail-closed).
- Errors: `StageError` (code 1) → `BadArgsError` (2), `IllegalTransition` (3),
  `NotInitialized` (15), `CorruptStatusError` (1), `WaitTimeout` (14). Each carries `.exit_code`.
- `state_exit_code(state) -> int` maps state → 10/11/12/13 (and `done` → 0).

## 12. Testing strategy

- Unit: transitions, idempotency, exit-code map, atomic IO, corrupt/lock tests.
- Concurrency: N threads × M heartbeats → valid STATUS, exact event count.
- CLI integration: subprocess per command incl. `wait` (background `done`),
  timeout path, proof gate paths (missing/empty/existing file).
- Chaos note: `kill -9` ⇒ stale `running`; `doctor --stale-after` or dead-PID check must flag it.

## 13. Appendix: schema_version 1 compatibility (normative)

This appendix formally locks the read contract for all tools and orchestrators interacting with `stage-signal` under `schema_version: 1`.

### 13.1 Additive-only policy
- Under `schema_version: 1`, all schema and API evolution is strictly **additive-only** until `schema_version: 2`.
- Keys in existing JSON payloads and contract tables MUST NOT be removed, renamed, or change their semantic meaning.
- Orchestrators and consumers written against `schema_version: 1` can safely branch on these frozen keys and exit codes without risk of silent breaking changes.
- Readers MUST tolerate unknown additional keys (forward compatibility).

### 13.2 STATUS.json required keys (freeze)
The following 23 keys are strictly required on disk in `STATUS.json` (`STATUS_REQUIRED_KEYS`). Writers must emit all of them; readers reject payloads missing any of these keys with `CorruptStatusError` / exit 1:

| Key | Type | Description |
|-----|------|-------------|
| `schema_version` | int | Must equal `1`. Readers reject any other value. |
| `project` | str | Project identifier. |
| `stage_id` | str\|null | Stable identifier for an attempt-series. |
| `stage_name` | str\|null | Human stage name. |
| `state` | enum | One of `queued`, `running`, `done`, `blocked`, `failed`. |
| `attempt` | int ≥ 1 | Attempt counter (1-based). |
| `session_id` | str\|null | Claiming agent session identifier. |
| `pid` | int\|null | Claiming process PID. |
| `model` | str\|null | Informational agent model name. |
| `variant` | str\|null | Informational model variant or reasoning effort. |
| `repo_path` | str\|null | Absolute repository path. |
| `git_branch` | str\|null | Git branch name. |
| `git_head` | str\|null | Git commit SHA. |
| `started_at` | ISO8601\|null | Timestamp of current attempt start. |
| `updated_at` | ISO8601 | Timestamp of latest mutation. |
| `heartbeat_at` | ISO8601\|null | Timestamp of latest heartbeat. |
| `heartbeat_note` | str\|null | Note text from latest heartbeat. |
| `result` | object\|null | Succeeded stage result summary. |
| `error` | object\|null | Blocked/failed stage error information. |
| `artifacts` | list | List of artifact entries (`path`, `label`, `added_at`). |
| `proof` | object\|null | Optional verification proof reference. |
| `notes` | list | Chronological notes appended to stage (`text`, `added_at`). |
| `meta` | object | Free-form key-value metadata object. |

*(Note: `pid_token` is an additive optional `str|null` field captured best-effort on process start; legacy 0.1.x files without `pid_token` remain valid on disk).*

### 13.3 JSON contract keys (freeze)
The machine-readable JSON objects emitted by CLI commands and library queries guarantee the following key sets:

#### 13.3.1 `status --json` / `Stage.status()` (`STATUS_JSON_KEYS`)
Always includes all 23 required `STATUS.json` keys plus the following dynamic observability fields:
- `needs_reclaim` (bool): `true` when `state == "running"` and `DEAD_PID` or `STALE_HEARTBEAT` applies; `false` otherwise.
- `heartbeat_age_seconds` (float | null): elapsed seconds since `heartbeat_at` when `state == "running"` and parseable; `null` otherwise.

Frozen guaranteed key set (`STATUS_JSON_KEYS`):
`schema_version`, `project`, `stage_id`, `stage_name`, `state`, `attempt`, `session_id`, `pid`, `model`, `variant`, `repo_path`, `git_branch`, `git_head`, `started_at`, `updated_at`, `heartbeat_at`, `heartbeat_note`, `result`, `error`, `artifacts`, `proof`, `notes`, `meta`, `needs_reclaim`, `heartbeat_age_seconds`.

#### 13.3.2 `doctor --json` / `Stage.diagnose()` (`DOCTOR_JSON_KEYS`)
Guaranteed key set across all conditions (healthy, warnings, problems, uninitialized):
- `ok` (bool): `true` when no problems exist.
- `needs_reclaim` (bool): `true` when `state == "running"` and `DEAD_PID` or `STALE_HEARTBEAT` applies; `false` otherwise.
- `state` (str | null): stage state if readable; `null` otherwise.
- `problems` (list[str]): list of error strings preventing healthy operation.
- `warnings` (list[object]): list of warning objects (`code`, `message`, `detail`).
- `status` (object | null): status snapshot including `heartbeat_age_seconds` if initialized; `null` otherwise.
- `summary` (str | null): human summary string (`OK: <state>`, `ATTENTION: running needs reclaim`, or `null`).

Frozen guaranteed key set (`DOCTOR_JSON_KEYS`):
`ok`, `needs_reclaim`, `state`, `problems`, `warnings`, `status`, `summary`.

#### 13.3.3 `wait --json` (`WAIT_JSON_KEYS`)
Guaranteed key set across all outcomes (`outcome`: `"met"`, `"mismatch"`, `"timeout"`):
- `outcome` (str): `"met"` | `"mismatch"` | `"timeout"`.
- `wanted` (str): wanted state target or `"needs_reclaim"`.
- `observed_state` (str | null): state observed when wait finished.
- `state` (str | null): alias of `observed_state`.
- `exit_code` (int): process exit code.
- `timeout` (bool): `true` if wait timed out; `false` otherwise.
- `stage_id` (str | null): stage identifier at exit.
- `dir` (str): path to stage directory.
- `reason` (str | null): failure reason (`status.error.reason`), timeout message, or `null`.
- `needs_reclaim` (bool): whether reclaim was required at exit.
- `status` (object | null): status snapshot at exit.

Frozen guaranteed key set (`WAIT_JSON_KEYS`):
`outcome`, `wanted`, `observed_state`, `state`, `exit_code`, `timeout`, `stage_id`, `dir`, `reason`, `needs_reclaim`, `status`.

### 13.4 Exit-code table freeze (`EXIT_CODES`)
The CLI exit codes are locked as part of the observer and runner contract:

| Exit code | Constant | Meaning |
|-----------|----------|---------|
| 0 | `EXIT_OK` | Success / wait condition met |
| 1 | `EXIT_ERROR` | Generic error (corrupt status, IO error, doctor problems; also `wait --needs-reclaim` mismatch on `done`) |
| 2 | `EXIT_BAD_ARGS` | Bad or conflicting CLI arguments |
| 3 | `EXIT_ILLEGAL_TRANSITION` | Illegal stage transition / failed `--require-proof` gate |
| 10 | `EXIT_RUNNING` | Observing state `running` (`status` / `wait` mismatch); or `doctor --exit-reclaim` when `needs_reclaim` is true |
| 11 | `EXIT_BLOCKED` | Observing state `blocked` |
| 12 | `EXIT_FAILED` | Observing state `failed` |
| 13 | `EXIT_QUEUED` | Observing state `queued` |
| 14 | `EXIT_WAIT_TIMEOUT` | Wait timeout elapsed |
| 15 | `EXIT_NOT_INITIALIZED` | Stage directory or STATUS.json missing |

### 13.5 Event types freeze (`EVENT_TYPES`)
The canonical event types recorded in `events.jsonl` are frozen:
- `init`
- `start`
- `heartbeat`
- `note`
- `artifact`
- `done`
- `blocked`
- `failed`
- `clear_terminal`

