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
  STATUS.md          # optional human mirror (best-effort, never normative; §13.18)
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
- Canonical layout path constants (`DEFAULT_DIR_NAME`, `STATUS_FILENAME`,
  `STATUS_MD_FILENAME`, `EVENTS_FILENAME`, `LOCKS_DIRNAME`, `LOCK_FILENAME`,
  `DEFAULT_MIRROR_DIRNAME`) are frozen in §13.13; `STATUS.md` human-mirror
  required headings and non-normative contract are frozen in §13.18.

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

The canonical stage lifecycle states and terminal partition are frozen in §13.12 (`STATES`, `TERMINAL_STATES`). The normative lifecycle allowed transition matrix is frozen in §13.19 (`ALLOWED_TRANSITIONS`).

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
   or only `failed` when `--keep-failed`; see §13.18).

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
  Its exit code always reflects state (§7, §13.16), so orchestrators can
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
  When running under `supervise`, `doctor` and `reclaim --kill` track and signal the adopted
  child PID rather than the supervisor wrapper process (see `supervise` below).
  It is compatible with `--keep-failed`. Mutators do not support `--json`.
- `supervise [--every SEC] [--dir DIR] [--summary SUMMARY] [--reason REASON] [--write-status-mirror] -- CMD [ARGS...]`:
  Runs and supervises a child process `CMD`, automatically bumping stage `heartbeat` every `--every`
  seconds (default 60; validated `1 <= every <= stale_threshold - 1`, default stale threshold 300)
  while the child process is alive. The stage must already be in state `running` (refuses with exit 3 /
  `IllegalTransition` otherwise; exit 15 / `NotInitialized` if not initialized).
  After `Popen` successfully spawns the child, `supervise` updates STATUS under exclusive lock:
  sets `pid` to the child's `proc.pid`, refreshes `pid_token` via the existing identity capture
  (or `null` if capture fails, same as `start`), and bumps `updated_at` and `heartbeat_at`.
  `stage_id`, `stage_name`, `attempt`, and `session_id` are preserved unchanged.
  PID adoption is recorded in the same locked section as a `heartbeat` event with message
  `adopted child pid <N>` and detail `{previous_pid, pid, pid_token}` (no new event type).
  This ensures
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
the transition); the 10–13 codes are for *observing* (`status`/`wait`) only (and exit 10 for `doctor --exit-reclaim` when reclaim is needed). The canonical state-to-exit-code mapping is frozen in §13.16 (`STATE_EXIT_CODES`). The public exception hierarchy and error exit mapping is frozen in §13.17.
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
`.stage-signal`, else `cwd`. See `docs/COMPOSE.md`. (This is distinct from
the standard `.stage-signal/STATUS.md` mirror whose required headings and
best-effort contract are frozen in §13.18; see also §2 and §13.13).

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
- The complete public instance method surface of `Stage` is frozen in §13.20 (`STAGE_PUBLIC_METHODS`).
- The complete top-level public export inventory of the package is frozen in §13.21 (`PUBLIC_EXPORTS`).

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
| `state` | enum | One of `queued`, `running`, `done`, `blocked`, `failed` (frozen `STATES`, §4, §13.12). |
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
- `warnings` (list[object]): list of warning objects (`code`, `message`, `detail`) conforming to §13.8 (`WARNING_KEYS`, `WARNING_CODES`).
- `status` (object | null): status snapshot including `heartbeat_age_seconds` if initialized; `null` otherwise.
- `summary` (str | null): human summary string (`OK: <state>`, `ATTENTION: running needs reclaim`, or `null`).

Frozen guaranteed key set (`DOCTOR_JSON_KEYS`):
`ok`, `needs_reclaim`, `state`, `problems`, `warnings`, `status`, `summary`.

#### 13.3.3 `wait --json` (`WAIT_JSON_KEYS`)
Guaranteed key set across all outcomes (`outcome`: `"met"`, `"mismatch"`, `"timeout"`; see §13.11 `WAIT_OUTCOMES`):
- `outcome` (str): one of the frozen `WAIT_OUTCOMES` (`"met"`, `"mismatch"`, `"timeout"`; §13.11).
- `wanted` (str): wanted state target or `"needs_reclaim"`.
- `observed_state` (str | null): state observed when wait finished.
- `state` (str | null): alias of `observed_state`.
- `exit_code` (int): process exit code.
- `timeout` (bool): `true` if wait timed out (`outcome == "timeout"`); `false` otherwise (§13.11).
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

The mapping from lifecycle states to observer exit codes (`queued` → 13, `running` → 10, `done` → 0, `blocked` → 11, `failed` → 12) is frozen in §13.16 (`STATE_EXIT_CODES`). The public exception hierarchy and CLI exit mapping is frozen in §13.17.

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

### 13.6 Event record keys and JSON array freeze (`EVENT_RECORD_KEYS`)
Every event object written to `events.jsonl` MUST include all eight required
keys, including keys whose values are `null`:

| Key | Type | Description |
|-----|------|-------------|
| `ts` | ISO8601 | Timestamp of the mutation. |
| `type` | enum | One of the frozen `EVENT_TYPES` (§13.5). |
| `stage_id` | str\|null | Stage identifier after the mutation. |
| `stage_name` | str\|null | Human stage name after the mutation. |
| `state` | enum | Stage state after the mutation. |
| `attempt` | int ≥ 1 | Attempt counter after the mutation. |
| `message` | str\|null | Human summary, note, or reason. |
| `detail` | object | Event-specific extras; `{}` when absent. |

The single source of truth for this required key set is `EVENT_RECORD_KEYS`
in `stage_signal.constants`, also exported from `stage_signal`.
Under `schema_version: 1`, event record evolution is **additive-only** (§13.1):
these keys MUST NOT be removed, renamed, or change semantic meaning.
Readers MUST tolerate unknown additional keys.

`events --json` emits one JSON **array** of event objects, not NDJSON or a
wrapper object. `Stage.events()` returns the corresponding `list[dict]`.
Both are chronological (**newest last**, matching file order), and every
returned event includes `EVENT_RECORD_KEYS`. No matches produces `[]`.
The `--type` / `type` and `--tail` / `tail` behavior, defaults, and
filter-before-tail ordering remain as specified in §5.

### 13.7 Artifact and note entry keys freeze (`ARTIFACT_ENTRY_KEYS`, `NOTE_ENTRY_KEYS`)
Every object in `STATUS.json`'s `artifacts[]` and `notes[]`, including those
returned by `status --json` / `Stage.status()`, MUST include all required keys
below. Empty arrays remain valid.

| Entry | Key | Type | Description |
|-------|-----|------|-------------|
| `artifacts[]` | `path` | str | Recorded artifact path. |
| `artifacts[]` | `label` | str\|null | Optional human label; the key MUST be present even when `null`. |
| `artifacts[]` | `added_at` | ISO8601 | Timestamp when the artifact was recorded. |
| `notes[]` | `text` | str | Recorded note text. |
| `notes[]` | `added_at` | ISO8601 | Timestamp when the note was appended. |

The single sources of truth for these required key sets are
`ARTIFACT_ENTRY_KEYS = ("path", "label", "added_at")` and
`NOTE_ENTRY_KEYS = ("text", "added_at")` in `stage_signal.constants`, also
exported from `stage_signal`.
Under `schema_version: 1`, entry evolution is **additive-only** (§13.1):
these keys MUST NOT be removed, renamed, or change semantic meaning.
Readers MUST tolerate unknown additional keys on each entry.

### 13.8 Doctor warning object and warning codes freeze (`WARNING_CODES`, `WARNING_KEYS`)
Every warning object contained in `warnings` emitted by `doctor --json` or returned by `Stage.diagnose()` MUST include all three required keys:

| Key | Type | Description |
|-----|------|-------------|
| `code` | enum | One of the frozen `WARNING_CODES`. |
| `message` | str | Human-readable explanation of the warning condition. |
| `detail` | object | Structured warning details; `{}` when absent. |

The single source of truth for the warning object required keys is `WARNING_KEYS` (aliased as `WARNING_REQUIRED_KEYS` / `DOCTOR_WARNING_KEYS`) in `stage_signal.constants`, also exported from `stage_signal`.
Under `schema_version: 1`, warning object evolution is **additive-only** (§13.1): these keys MUST NOT be removed, renamed, or change semantic meaning. Readers MUST tolerate unknown additional keys. `detail` MUST be an object (dictionary) and may be empty (`{}`).

The canonical warning code set is frozen in `WARNING_CODES`:
- `STALE_HEARTBEAT` (`WARNING_CODE_STALE_HEARTBEAT`)
- `DEAD_PID` (`WARNING_CODE_DEAD_PID`)
- `UNPARSEABLE_HEARTBEAT` (`WARNING_CODE_UNPARSEABLE_HEARTBEAT`)

The single source of truth for the warning codes is `WARNING_CODES` in `stage_signal.constants`, also exported from `stage_signal`. The individual `WARNING_CODE_*` constants remain exported as aliases. Orchestrators may stably branch on `warnings[].code` matching one of these identifiers.

### 13.9 result/error object keys freeze (`RESULT_KEYS`, `ERROR_KEYS`, `ERROR_KINDS`)
When the top-level `result` field is non-null (set by `done`), it MUST include all three required keys:

| Key | Type | Description |
|-----|------|-------------|
| `summary` | str | Human-readable completion summary. |
| `git_head` | str\|null | Git head at completion; the key MUST be present even when `null`. |
| `finished_at` | ISO8601 | Timestamp when the terminal transition was recorded. |

When `done` is invoked with `--accept-failure`, the result additionally records `"accepted_failure": true`. This key is **optional additive**: it MUST NOT appear on a plain `done`, and readers MUST tolerate it plus any other unknown additional keys.

When the top-level `error` field is non-null (set by `blocked` or `fail`), it MUST include all three required keys:

| Key | Type | Description |
|-----|------|-------------|
| `reason` | str | Human-readable blocked/failure reason. |
| `kind` | enum | One of the frozen `ERROR_KINDS`: `blocked` or `failed`. |
| `finished_at` | ISO8601 | Timestamp when the terminal transition was recorded. |

A `null` `result` and/or `error` remains valid in every state (e.g. `running`, `queued`, and `blocked`/`failed` carry `result: null`; `done` carries `error: null`).

The single sources of truth for these required key sets are
`RESULT_KEYS = ("summary", "git_head", "finished_at")`,
`ERROR_KEYS = ("reason", "kind", "finished_at")`, and
`ERROR_KINDS = ("blocked", "failed")` in `stage_signal.constants`, also
exported from `stage_signal`.
Under `schema_version: 1`, result/error object evolution is **additive-only** (§13.1): these keys MUST NOT be removed, renamed, or change semantic meaning. Readers MUST tolerate unknown additional keys on non-null `result`/`error` objects.

### 13.10 Proof object keys and verified enum freeze (`PROOF_KEYS`, `PROOF_VERIFIED_VALUES`)
When `proof` is non-null in `STATUS.json` or in the output of `status --json` / `Stage.status()`, it MUST be an object including all required keys below. `proof: null` remains valid when no proof reference was recorded.

| Key | Type | Description |
|-----|------|-------------|
| `tool` | str | Verification/receipt tool name (e.g. `"agent-done-or-not"`). |
| `ref` | str | Proof reference (receipt file path or external ledger label). |
| `verified` | null\|"file"\|"verify" | Gate verification status. |

The single source of truth for the required proof key set is
`PROOF_KEYS = ("tool", "ref", "verified")` in `stage_signal.constants`, also
exported from `stage_signal`.

The canonical set of allowed `verified` values is frozen in `PROOF_VERIFIED_VALUES`:
- `None` (`null` in JSON): pointer recorded without checking (`--proof-ref` alone)
- `"file"`: passed `--require-proof` because `ref` is an existing non-empty file
- `"verify"`: passed `--require-proof` via external verifier (`agent-done-or-not verify --ref R`)

The single source of truth for the verified enum is
`PROOF_VERIFIED_VALUES = (None, "file", "verify")` in `stage_signal.constants`, also
exported from `stage_signal`.

Under `schema_version: 1`, proof object evolution is **additive-only** (§13.1):
these keys MUST NOT be removed, renamed, or change semantic meaning.
Readers MUST tolerate unknown additional keys on the `proof` object.
Composition and verification semantics remain defined in §9 and `docs/COMPOSE.md`;
this section freezes the on-wire dictionary keys and closed verified enum under schema version 1.

### 13.11 Wait outcomes enum freeze (`WAIT_OUTCOMES`)
The machine-readable `wait --json` payload (§13.3.3, `WAIT_JSON_KEYS`) emits a required `outcome` string field indicating the resolution of the wait invocation. The canonical set of allowed values is frozen in `WAIT_OUTCOMES`:

| Outcome | Meaning |
|---------|---------|
| `"met"` | The wanted state target (or `--needs-reclaim` condition) was observed; exit code 0 (`EXIT_OK`). |
| `"mismatch"` | A terminal state other than wanted was observed before target was met, or `--needs-reclaim` encountered a terminal state without reclaim; non-zero observer exit code matching observed state (§13.4). |
| `"timeout"` | The wait deadline expired before any terminating condition was observed; exit code 14 (`EXIT_WAIT_TIMEOUT`). |

The single source of truth for the wait outcome enum is
`WAIT_OUTCOMES = ("met", "mismatch", "timeout")` in `stage_signal.constants`, also
exported from `stage_signal`. The individual constants `WAIT_OUTCOME_MET`,
`WAIT_OUTCOME_MISMATCH`, and `WAIT_OUTCOME_TIMEOUT` remain exported as aliases.

Under `schema_version: 1`, wait outcome evolution is strictly **additive-only** (§13.1):
these outcome values MUST NOT be removed, renamed, or change semantic meaning.
Readers MUST tolerate unknown additional outcome values in `outcome`.

The boolean `timeout` field in `WAIT_JSON_KEYS` remains strictly consistent with `outcome`:
- `timeout: true` if and only if `outcome == "timeout"`.
- `timeout: false` for `"met"` and `"mismatch"`.

Wait semantics, timeout handling, and observer exit codes remain defined in §6, §7, and §13.3.3;
this section freezes the closed outcome enum and its boolean consistency under schema version 1.

### 13.12 Stage states and terminal states freeze (`STATES`, `TERMINAL_STATES`)
The canonical stage lifecycle states and their terminal classification are frozen under `schema_version: 1`:

| State | Constant | Terminal | Meaning |
|-------|----------|----------|---------|
| `queued` | `STATE_QUEUED` | No | Stage initialized or reclaimed; awaiting execution. |
| `running` | `STATE_RUNNING` | No | Stage actively executing an attempt. |
| `done` | `STATE_DONE` | Yes | Stage execution succeeded. |
| `blocked` | `STATE_BLOCKED` | Yes | Stage paused awaiting external input or resolution. |
| `failed` | `STATE_FAILED` | Yes | Stage aborted or exited with unrecoverable failure. |

The single sources of truth for these sets are:
- `STATES = ("queued", "running", "done", "blocked", "failed")`
- `TERMINAL_STATES = ("done", "blocked", "failed")`

defined in `stage_signal.constants` and exported from `stage_signal`. The individual `STATE_*` constants (`STATE_QUEUED`, `STATE_RUNNING`, `STATE_DONE`, `STATE_BLOCKED`, `STATE_FAILED`) remain defined and exported.

The non-terminal states are `queued` and `running`. The terminal states are `done`, `blocked`, and `failed`. Terminal states signify completion of an attempt series; transitioning out of a terminal state requires an intervening `start` (or `clear-terminal` / `--accept-failure`) per the state machine in §4.

Under `schema_version: 1`, stage state evolution is **additive-only** (§13.1): existing states and terminal classifications MUST NOT be removed, renamed, or change semantic meaning. Any future state introduced under schema version 1 MUST specify its terminal or non-terminal classification, and observers/readers MUST tolerate unknown states without crashing.

State machine transitions and lifecycle rules remain defined in §4; the `state` field contract on `STATUS.json` is defined in §13.2.

### 13.13 On-disk layout path constants freeze (`DEFAULT_DIR_NAME`, `STATUS_FILENAME`, `STATUS_MD_FILENAME`, `EVENTS_FILENAME`, `LOCKS_DIRNAME`, `LOCK_FILENAME`, `DEFAULT_MIRROR_DIRNAME`)
The canonical on-disk layout directory and filenames defining the stage filesystem layout (§2) are frozen under `schema_version: 1`:

| Constant | Value | Purpose |
|----------|-------|---------|
| `DEFAULT_DIR_NAME` | `".stage-signal"` | Default relative root directory for stage state in repository (§2). |
| `STATUS_FILENAME` | `"STATUS.json"` | Normative current state file (§2, §3, §13.2). |
| `STATUS_MD_FILENAME` | `"STATUS.md"` | Optional human-readable Markdown mirror file (§2, §13.18). |
| `EVENTS_FILENAME` | `"events.jsonl"` | Append-only newline-delimited JSON events log (§2, §13.6). |
| `LOCKS_DIRNAME` | `"locks"` | Subdirectory under the stage dir hosting concurrency locks (§2, §8). |
| `LOCK_FILENAME` | `"stage.lock"` | File under `locks/` used for mutual exclusion / advisory locking (§2, §8). |
| `DEFAULT_MIRROR_DIRNAME` | `".orch"` | Default directory name for orchestrator status mirror files (§10, `write_status_mirror`). |

The single sources of truth for these path constants are:
- `DEFAULT_DIR_NAME = ".stage-signal"`
- `STATUS_FILENAME = "STATUS.json"`
- `STATUS_MD_FILENAME = "STATUS.md"`
- `EVENTS_FILENAME = "events.jsonl"`
- `LOCKS_DIRNAME = "locks"`
- `LOCK_FILENAME = "stage.lock"`
- `DEFAULT_MIRROR_DIRNAME = ".orch"`

defined in `stage_signal.constants` and exported from `stage_signal`.

Under `schema_version: 1`, layout path constants are **additive-only** (§13.1): existing path names and relative layout positions MUST NOT be removed, renamed, or change semantic meaning. Readers and observers MUST tolerate unknown extra files or directories present in the stage directory without crashing or failing.

Filesystem layout and concurrency locking rules remain defined in §2 and §8; the mirror directory layout remains defined in §10; human mirror section requirements remain defined in §13.18.
### 13.14 Environment variables and timing defaults freeze (`ENV_DIR`, `WAIT_DEFAULT_TIMEOUT`, etc.)

The canonical environment variable names and CLI/runtime numeric defaults and limits are frozen under `schema_version: 1`.

#### 13.14.1 Environment variables

`stage-signal` recognizes four canonical environment variables:

| Constant | Env Var Name | Description | Precedence |
|----------|--------------|-------------|------------|
| `ENV_DIR` | `"STAGE_SIGNAL_DIR"` | Stage directory path override. | Explicit `--dir PATH` (or `Stage(dir=...)` / `resolve_dir(explicit)`) takes precedence over `ENV_DIR`; if neither is set, defaults to `DEFAULT_DIR_NAME` (`.stage-signal`) per §2. |
| `ENV_PROJECT` | `"STAGE_SIGNAL_PROJECT"` | Project identifier fallback when initializing or starting a stage. | Explicit `--project` / `project=` takes precedence; if omitted, falls back to `ENV_PROJECT`, then Git/directory name inference. |
| `ENV_PROOF_REF` | `"STAGE_SIGNAL_PROOF_REF"` | Proof reference fallback for `--require-proof` / `--proof-ref`. | Explicit `--proof-ref R` takes precedence; falls back to `ENV_PROOF_REF` per §9. |
| `ENV_STATUS_MIRROR` | `"STAGE_SIGNAL_STATUS_MIRROR"` | Enables optional `.orch` status mirror (`"1"`, `"true"`, `"yes"`). | Explicit `--write-status-mirror` / `write_status_mirror=True` or `ENV_STATUS_MIRROR` enables mirroring per §10. |

Precedence rule: `--dir` strictly wins over `STAGE_SIGNAL_DIR` (`ENV_DIR`) per §2.

The single sources of truth for these environment variable names are:
- `ENV_DIR = "STAGE_SIGNAL_DIR"`
- `ENV_PROJECT = "STAGE_SIGNAL_PROJECT"`
- `ENV_PROOF_REF = "STAGE_SIGNAL_PROOF_REF"`
- `ENV_STATUS_MIRROR = "STAGE_SIGNAL_STATUS_MIRROR"`
- `ENV_VARS = (ENV_DIR, ENV_PROJECT, ENV_PROOF_REF, ENV_STATUS_MIRROR)`

defined in `stage_signal.constants` and exported from `stage_signal`.

Under `schema_version: 1`, environment variable names are strictly **additive-only** (§13.1): these variable names MUST NOT be removed, renamed, or change their semantic meaning. Future environment variables introduced under schema version 1 must follow the `STAGE_SIGNAL_*` prefix convention.

#### 13.14.2 Timing defaults and limits

The canonical CLI timing defaults, staleness thresholds, and capacity limits are frozen:

| Constant | Value | Type | Description |
|----------|-------|------|-------------|
| `WAIT_DEFAULT_TIMEOUT` | `3600.0` | float | Default timeout for `wait` in seconds (1 hour) when `--timeout` is omitted (§6). |
| `WAIT_DEFAULT_POLL` | `5.0` | float | Default polling interval for `wait` in seconds (5s) when `--poll` is omitted (§6). |
| `EVENTS_DEFAULT_TAIL` | `20` | int | Default event count for `events` CLI when `--tail` is omitted (§5, §13.6). |
| `DEFAULT_STALE_THRESHOLD` | `300.0` | float | Default heartbeat staleness threshold in seconds (5 minutes) for `doctor` and `supervise` (§4, §6). |
| `SUPERVISE_DEFAULT_EVERY` | `60.0` | float | Default heartbeat emission interval in seconds (1 minute) for `supervise` (§6). |
| `MAX_NOTES` | `200` | int | Maximum number of note objects retained in `STATUS.json`'s `notes[]` list (§3). |

The single sources of truth for these timing defaults and limits are defined in `stage_signal.constants` and exported from `stage_signal`.

Under `schema_version: 1`, current numeric defaults are pinned. Numeric defaults may be tuned only via documented SemVer-minor note if ever changed; for this freeze, orchestrators and CLI callers can rely on these exact values as standard baseline behavior.

### 13.15 CLI subcommand inventory freeze (`CLI_SUBCOMMANDS`)

The canonical CLI subcommand inventory is frozen under `schema_version: 1`.

#### 13.15.1 Entry points and equivalence

`stage-signal` provides two equivalent entry points:
- Console script: `stage-signal` (defined via `project.scripts` in `pyproject.toml`)
- Module execution: `python -m stage_signal` (supported via `__main__.py`)

Both invoke `stage_signal.cli:main` and provide identical arguments, behavior, and exit codes. Orchestrators and automation harnesses MAY invoke either form interchangeably.

#### 13.15.2 Canonical subcommand inventory

The CLI provides 15 canonical subcommands. In alphabetical order:

| Subcommand | Purpose | Primary SPEC Reference |
|------------|---------|------------------------|
| `artifact` | Record an artifact path in `STATUS.json` (`running` state only). | §6 |
| `blocked` | Transition stage to `blocked` with a reason string. | §4, §6 |
| `clear-terminal` | Reset a terminal or queued state back to idle `queued`. | §4, §6 |
| `doctor` | Check stage directory health, validate schema, inspect claiming PID liveness, detect reclaim needs. | §4, §6, §13.8 |
| `done` | Mark stage succeeded (`done`) with optional summary, proof verification, or failure acceptance. | §4, §6, §9 |
| `events` | Query and format recent audit records from `events.jsonl` (chronological or JSON). | §5, §6, §13.6 |
| `fail` | Mark stage hard-failed (`failed`) with a reason string; optional dead PID or needs-reclaim guards. | §4, §6 |
| `heartbeat` | Bump stage heartbeat timestamp and optional heartbeat note (`running` state only). | §3, §4, §6 |
| `init` | Create stage directory and write initial `queued` status idempotently. | §2, §3, §6 |
| `note` | Append a free-form progress note to `STATUS.json` (`running` state only). | §3, §6, §13.14 |
| `reclaim` | Atomic fail-and-clear transition when `needs_reclaim` is true; optional process termination (`--kill`). | §4, §6 |
| `start` | Claim and start a stage, transition to `running`, record PID, metadata, and git context. | §3, §4, §6 |
| `status` | Show current stage status in human text or structured JSON; exit code reflects state. | §6, §7, §13.2 |
| `supervise` | Supervise a child process command with automatic heartbeat emissions until process exit. | §4, §6 |
| `wait` | Poll until a target state or `needs_reclaim` condition is reached, or until timeout. | §6, §7, §13.11 |

The single source of truth for the canonical subcommand inventory is:
- `CLI_SUBCOMMANDS = ("artifact", "blocked", "clear-terminal", "doctor", "done", "events", "fail", "heartbeat", "init", "note", "reclaim", "start", "status", "supervise", "wait")`

defined in `stage_signal.constants` as a sorted tuple and exported from `stage_signal`.
The CLI argument parser (`build_parser()`) subcommand choices MUST match `CLI_SUBCOMMANDS` exactly.

#### 13.15.3 Additive-only evolution under schema version 1

Under `schema_version: 1`, the CLI subcommand inventory is strictly **additive-only** (§13.1):
- Existing subcommands MUST NOT be removed or renamed.
- Existing subcommand semantic meanings MUST NOT change.
- New subcommands MAY be added in minor or patch releases, expanding `CLI_SUBCOMMANDS`.
- Individual flag and argument additions to existing subcommands must remain backwards-compatible.
- Orchestrators and external automation may safely rely on the presence and stability of these 15 subcommands.

Detailed command syntax, argument semantics, and behavioral rules remain defined in §6; exit codes remain defined in §7.
### 13.16 State-to-exit-code mapping freeze (`STATE_EXIT_CODES`)

The canonical mapping from stage lifecycle state string to observer CLI exit code (used by `status` and wait outcome mismatches; §6, §7, §13.4) is frozen under `schema_version: 1`:

| State | Constant Name | Exit Code Constant | Exit Code | Meaning |
|-------|---------------|-------------------|-----------|---------|
| `queued` | `STATE_QUEUED` | `EXIT_QUEUED` | 13 | Stage is queued / awaiting execution (§4, §13.12). |
| `running` | `STATE_RUNNING` | `EXIT_RUNNING` | 10 | Stage is running / actively executing (§4, §13.12). |
| `done` | `STATE_DONE` | `EXIT_OK` | 0 | Stage completed successfully (§4, §13.12). |
| `blocked` | `STATE_BLOCKED` | `EXIT_BLOCKED` | 11 | Stage paused awaiting input or external resolution (§4, §13.12). |
| `failed` | `STATE_FAILED` | `EXIT_FAILED` | 12 | Stage failed or aborted (§4, §13.12). |

The single source of truth for this mapping is:

```python
STATE_EXIT_CODES = {
    STATE_RUNNING: EXIT_RUNNING,   # 10
    STATE_BLOCKED: EXIT_BLOCKED,   # 11
    STATE_FAILED: EXIT_FAILED,     # 12
    STATE_QUEUED: EXIT_QUEUED,     # 13
    STATE_DONE: EXIT_OK,           # 0
}
```

defined in `stage_signal.constants` and exported from `stage_signal`. The helper function `state_exit_code(state: str) -> int` maps any valid state string to its exit code using `STATE_EXIT_CODES`.

#### Distinction from mutation command exits

This mapping is strictly for **observer** commands (such as `stage-signal status`, and wait mismatch observation per §6 and §7). Mutation commands (`init`, `start`, `heartbeat`, `note`, `artifact`, `done`, `blocked`, `fail`, `reclaim`, `clear-terminal`) perform state transitions or state record updates; they exit `0` (`EXIT_OK`) upon successful completion of their operation, regardless of the target state reached (for instance, `stage-signal done`, `stage-signal blocked`, and `stage-signal fail` all exit `0` when their respective transitions succeed). Mutation commands exit non-zero only on operational or validation failure (such as `EXIT_ILLEGAL_TRANSITION` (3), `EXIT_BAD_ARGS` (2), or `EXIT_ERROR` (1) per §13.4).

#### Additive-only evolution policy

Under `schema_version: 1`, the `STATE_EXIT_CODES` mapping is strictly **additive-only** (§13.1):
- Existing state-to-exit-code mappings (`queued` → 13, `running` → 10, `done` → 0, `blocked` → 11, `failed` → 12) MUST NOT be removed, renamed, or assigned different exit codes.
- Any future lifecycle state introduced under schema version 1 MUST define its assigned observer exit code.
- Readers and observers MUST NOT crash on unknown future states. Behavior for unmapped or unknown states is implementation-defined (for example, raising `ValueError` in the Python lookup helper or emitting a non-zero exit in the CLI), but must never remove or mutate existing mappings.

### 13.17 Public exception hierarchy and exit mapping freeze

Python embedders and orchestrators interacting with `stage-signal` via its library API can catch stable, structured exception classes. The complete public exception hierarchy and its mapping to CLI exit codes (§7, §13.4) is frozen under `schema_version: 1`:

```
Exception (built-in)
└── StageError (exit_code = EXIT_ERROR = 1)
    ├── BadArgsError (exit_code = EXIT_BAD_ARGS = 2)
    ├── IllegalTransition (exit_code = EXIT_ILLEGAL_TRANSITION = 3)
    ├── NotInitialized (exit_code = EXIT_NOT_INITIALIZED = 15)
    ├── CorruptStatusError (exit_code = EXIT_ERROR = 1)
    └── WaitTimeout (exit_code = EXIT_WAIT_TIMEOUT = 14)
```

| Exception Class | Base Class | Exit Code Constant | Exit Code | Description & Usage |
|-----------------|------------|-------------------|-----------|---------------------|
| `StageError` | `Exception` | `EXIT_ERROR` | 1 | Base exception for all `stage-signal` operational errors. Carries class attribute `exit_code` (typically 1) and optional `detail` attribute (§7, §13.4). |
| `BadArgsError` | `StageError` | `EXIT_BAD_ARGS` | 2 | Invalid CLI arguments, schema misuse, or missing mandatory inputs (e.g. invalid `--pid`, empty `--stage`, invalid `--meta`; §6, §13.4). |
| `IllegalTransition` | `StageError` | `EXIT_ILLEGAL_TRANSITION` | 3 | Disallowed lifecycle transition attempt (e.g. `done` from `queued`, reclaiming un-reclaimable stage) or failed `--require-proof` verification gate (§4, §6, §13.4). |
| `NotInitialized` | `StageError` | `EXIT_NOT_INITIALIZED` | 15 | Stage directory does not exist or `STATUS.json` is missing when executing commands that require an initialized stage (§6, §7, §13.4). |
| `CorruptStatusError` | `StageError` | `EXIT_ERROR` | 1 | `STATUS.json` or `events.jsonl` unreadable, invalid JSON, or failing schema validation (§4, §13.3, §13.4). |
| `WaitTimeout` | `StageError` | `EXIT_WAIT_TIMEOUT` | 14 | `wait` operation timed out before target condition was satisfied (§6, §13.4, §13.11). Carries `last_status` dict when available. |

#### CLI boundary exit code mapping

When invoked via the CLI entry point (`stage-signal` or `python -m stage_signal`; §13.15), unhandled `StageError` exceptions are caught at the top-level boundary (`stage_signal.cli.main`), emitting an error message to `stderr` and returning `exc.exit_code`:

```python
try:
    return func(args)
except StageError as exc:
    print(f"stage-signal: error: {exc}", file=sys.stderr)
    return exc.exit_code
```

This guarantees an exact 1:1 correspondence between Python exceptions raised during library/command execution and the CLI exit codes documented in §7 and §13.4.

#### Top-level export guarantee

All six exception classes are exported from the top-level `stage_signal` package and enumerated in `__all__`:
- `StageError`
- `BadArgsError`
- `IllegalTransition`
- `NotInitialized`
- `CorruptStatusError`
- `WaitTimeout`

Embedders can import them directly:

```python
from stage_signal import (
    BadArgsError,
    CorruptStatusError,
    IllegalTransition,
    NotInitialized,
    StageError,
    WaitTimeout,
)
```

#### Additive-only evolution policy

Under `schema_version: 1`, the public exception hierarchy and exit mapping is strictly **additive-only** (§13.1):
- Existing exception types (`StageError`, `BadArgsError`, `IllegalTransition`, `NotInitialized`, `CorruptStatusError`, `WaitTimeout`) MUST NOT be removed, renamed, or assigned different `exit_code` values.
- Existing inheritance relationships MUST NOT be broken: each subclass MUST remain an `issubclass` of `StageError` (and `Exception`).
- New exception subclasses MAY be added in future minor or patch releases, expanding the hierarchy, provided each new class inherits from `StageError` (or an existing subclass) and carries an `exit_code` consistent with §7 and §13.4.

### 13.18 Best-effort STATUS.md human mirror required sections freeze (`STATUS_MD_REQUIRED_HEADINGS`)

The human-readable Markdown mirror written by `StageStore.write_status_md` / `render_status_md` (`.stage-signal/STATUS.md`; §2, §13.13) provides a predictable, human-inspected mirror of stage status while maintaining strict non-normative status.

#### 13.18.1 Best-effort / never normative contract

As established in §2, `STATUS.md` is **best-effort and never normative**:
- `STATUS.json` (§3) remains the sole authoritative source of truth for all stage lifecycle automation, state transitions, and tooling.
- `StageStore.write_status_md` is executed best-effort upon mutations; write errors (such as read-only filesystems, disk quota limits, or permission errors) MUST NOT abort state transitions, crash callers, or raise exceptions (§2, §10).
- External tools and orchestrators must inspect `STATUS.json` (or `stage-signal status --json`) for normative state and machine-critical gating decisions.

#### 13.18.2 Document title and required headings

`STATUS.md` begins with a document title followed by required key-value lines formatted as `<marker> <value>`. Across all five lifecycle states (`queued`, `running`, `done`, `blocked`, `failed`), the mirror is guaranteed to emit the following headings and lines:

| Marker / Heading | Description | Lifecycle Applicability |
|------------------|-------------|-------------------------|
| `# stage-signal STATUS` | Top-level Markdown H1 title (`STATUS_MD_TITLE`). | Always present across all states. |
| `state:` | Current lifecycle state (`queued`, `running`, `done`, `blocked`, `failed`; §4, §13.12). | Always present across all states. |
| `stage:` | Human-readable stage name (`stage_name`), or `None` if unset (§3). | Always present across all states. |
| `stage_id:` | Unique stage identifier (`stage_id`), or `None` if unset (§3). | Always present across all states. |
| `attempt:` | Current run attempt counter integer (`attempt`), or `None` if uninitialized (§3). | Always present across all states. |
| `project:` | Project name (`project`), or `None` if unset (§3). | Always present across all states. |
| `updated:` | ISO-8601 mutation timestamp (`updated_at`), or `None` if unset (§3). | Always present across all states. |
| `heartbeat:` | Heartbeat ISO-8601 timestamp (`heartbeat_at`), or `None` if unset (§3). | Always present across all states. |

The single source of truth for these required headings is:

```python
STATUS_MD_TITLE = "# stage-signal STATUS"
STATUS_MD_REQUIRED_HEADINGS = (
    "# stage-signal STATUS",
    "state:",
    "stage:",
    "stage_id:",
    "attempt:",
    "project:",
    "updated:",
    "heartbeat:",
)
```

defined in `stage_signal.constants` and exported from `stage_signal`.

#### 13.18.3 Conditional / optional headings

When specific status fields are present in `STATUS.json`, `render_status_md` emits corresponding conditional summary lines:

| Marker / Heading | Condition | Description |
|------------------|-----------|-------------|
| `heartbeat_note:` | Present when `heartbeat_note` is non-null. | Last recorded heartbeat note string (§3, §6). |
| `result:` | Present when `result` object is non-null (terminal `done`). | JSON serialization of result object (`{"summary": ..., "git_head": ..., "finished_at": ...}`; §3, §13.9). |
| `error:` | Present when `error` object is non-null (terminal `blocked` or `failed`). | JSON serialization of error object (`{"reason": ..., "kind": ..., "finished_at": ...}`; §3, §13.9). |

These conditional headings are tracked in:

```python
STATUS_MD_OPTIONAL_HEADINGS = (
    "heartbeat_note:",
    "result:",
    "error:",
)
STATUS_MD_HEADINGS = STATUS_MD_REQUIRED_HEADINGS + STATUS_MD_OPTIONAL_HEADINGS
```

#### 13.18.4 Tolerance of extra sections and additive evolution

Under `schema_version: 1`, the human mirror format is strictly **additive-only** (§13.1):
- Existing required headings (`STATUS_MD_REQUIRED_HEADINGS`) MUST NOT be removed, renamed, or reordered in incompatible ways.
- Readers, parsers, and light orchestrators inspecting `STATUS.md` MUST tolerate unknown extra sections, lines, or trailing content without failing or misinterpreting existing headings.
- New headings or informational sections MAY be appended in future minor or patch releases under schema version 1.
- Writers MUST continue guaranteeing that write failures never raise exceptions, preserving the best-effort nature of the mirror.

Distinction from orchestrator mirror: The optional `<repo>/.orch/STATUS.md` mirror (§10, `write_status_mirror`) is an independent repository-level convenience mirror that includes an extra `source:` line and touches `.orch/DONE` on completion; both mirrors adhere to non-normative, best-effort principles.

### 13.19 Allowed lifecycle transition matrix freeze (`ALLOWED_TRANSITIONS`)

The lifecycle state machine transitions between stage states (§4, §13.12) via CLI subcommands (§6, §13.15) and library methods are governed by a normative, frozen allowed transition matrix under `schema_version: 1`.

#### 13.19.1 Normative matrix rules and coverage

Orchestrators and embedders can rely on the exact legality of `(from_state → command → to_state)` edges:

1. **Initialization flow (`init` / idle `queued` → `start` → `running`):**
   - Uninitialized stages transition to idle `queued` via `init` (emitting an `init` event).
   - From `queued` (whether clean idle `queued` or named queued), invoking `start --stage NAME` transitions to `running` (attempt 1, emitting a `start` event).
   - `start` is permitted from **any** state (`queued`, `running`, `done`, `blocked`, `failed`), always transitioning to `running` (incrementing `attempt` on same series or resetting to 1 on new stage ID).
2. **Progress within running (`running` → `heartbeat` / `note` / `artifact`):**
   - Commands `heartbeat [--note]`, `note TEXT`, and `artifact PATH [--label]` are permitted **only** when `state == "running"`.
   - Each operation keeps the stage in `running` without resetting attempt, claims, or terminal payloads.
   - Invoking `heartbeat`, `note`, or `artifact` from any non-running state (`queued`, `done`, `blocked`, `failed`) is illegal and MUST raise `IllegalTransition` (exit 3; §13.4, §13.17).
3. **Completion to terminal (`running` / `queued` → `done` / `blocked` / `fail` → terminal):**
   - Standard `done` transitions from `queued` or `running` to `done`. Idempotent repeat from `done` is legal.
   - Standard `blocked` transitions from `queued` or `running` to `blocked`. Idempotent repeat from `blocked` is legal.
   - Standard `fail` transitions from `queued` or `running` to `failed`. Idempotent repeat from `failed` is legal.
   - Transitioning from one terminal state to a different terminal state without an intervening `start` (or without `--accept-failure` on `failed`) is strictly illegal (exit 3).
4. **Accepting failure (`failed` → `done --accept-failure`):**
   - `done --accept-failure` is permitted **only** from state `failed`, transitioning the stage to `done` and recording `"accepted_failure": true` in `result` (§4 rule 5).
   - Invoking `done --accept-failure` from any non-failed state (`queued`, `running`, `done`, `blocked`) is illegal and MUST raise `IllegalTransition` (exit 3).
5. **Reclaim edges (`running` + `needs_reclaim` → `failed` [+ optional `clear_terminal`]):**
   - `reclaim` requires `needs_reclaim` to be true (`state == "running"` and either a `DEAD_PID` or `STALE_HEARTBEAT` warning applies; §4 rule 7, §13.8).
   - When `needs_reclaim` is true:
     - With `--keep-failed`: transitions `running` → `failed` (emitting a `failed` event with `detail: {"reclaim": True, "keep_failed": True}`).
     - Default (without `--keep-failed`): atomically transitions `running` → `failed` then `failed` → `queued` (emitting a `failed` event followed by a `clear_terminal` event with stage identity reset to idle `queued`).
   - When `needs_reclaim` is false (healthy `running` or non-running states): `reclaim` and `fail --if-needs-reclaim` are illegal and MUST raise `IllegalTransition` (exit 3) with no mutation.
6. **Resetting to idle (`clear-terminal` from terminal / queued → idle `queued`):**
   - `clear-terminal` is permitted from all terminal states (`done`, `blocked`, `failed`) and from `queued` (abandoning an idle or pending queued stage).
   - It transitions the stage to `queued` (idle by default, resetting stage identity to `null`, or preserving stage identity when `--keep-stage` is given).
   - `clear-terminal` from `running` is strictly illegal and MUST raise `IllegalTransition` (exit 3); stuck running stages must be reclaimed first.
7. **Strict failure on illegal edges (`IllegalTransition` / exit 3):**
   - Any transition attempt outside the allowed matrix MUST raise `IllegalTransition` (§13.17) in Python and exit with code 3 (`EXIT_ILLEGAL_TRANSITION`; §13.4) at the CLI boundary.
   - Status, events, and mirrors MUST NOT be mutated on rejected transitions.

#### 13.19.2 Allowed transition matrix table

| From State | Command / Operation | Resulting State | Condition / Guard | Audit Event |
|---|---|---|---|---|
| `queued` | `start` | `running` | Stage name required | `start` |
| `queued` | `done` | `done` | Optional summary / proof | `done` |
| `queued` | `blocked` | `blocked` | Non-empty reason required | `blocked` |
| `queued` | `fail` | `failed` | Non-empty reason required | `failed` |
| `queued` | `clear-terminal` | `queued` | Resets to idle queued (abandon) | `clear_terminal` |
| `running` | `start` | `running` | Retries stage (bumps attempt) or new stage | `start` |
| `running` | `heartbeat` | `running` | Bumps heartbeat timestamp, optional note | `heartbeat` |
| `running` | `note` | `running` | Appends note entry | `note` |
| `running` | `artifact` | `running` | Appends artifact record | `artifact` |
| `running` | `done` | `done` | Optional summary / proof | `done` |
| `running` | `blocked` | `blocked` | Non-empty reason required | `blocked` |
| `running` | `fail` | `failed` | Non-empty reason required | `failed` |
| `running` | `fail --if-dead-pid` | `failed` | Recorded PID confirmed dead | `failed` |
| `running` | `fail --if-needs-reclaim` | `failed` | `needs_reclaim` is True | `failed` |
| `running` | `reclaim` | `queued` | `needs_reclaim` is True; clears to idle queued | `failed` + `clear_terminal` |
| `running` | `reclaim --keep-failed` | `failed` | `needs_reclaim` is True; leaves in failed | `failed` |
| `done` | `start` | `running` | Starts new attempt / stage | `start` |
| `done` | `done` | `done` | Idempotent same-stage repeat | `done` |
| `done` | `clear-terminal` | `queued` | Clears terminal stage to queued | `clear_terminal` |
| `blocked` | `start` | `running` | Starts new attempt / stage | `start` |
| `blocked` | `blocked` | `blocked` | Idempotent same-stage repeat | `blocked` |
| `blocked` | `clear-terminal` | `queued` | Clears terminal stage to queued | `clear_terminal` |
| `failed` | `start` | `running` | Starts new attempt / stage | `start` |
| `failed` | `fail` | `failed` | Idempotent same-stage repeat | `failed` |
| `failed` | `done --accept-failure` | `done` | Allowed ONLY from `failed` | `done` |
| `failed` | `clear-terminal` | `queued` | Clears terminal stage to queued | `clear_terminal` |

All other `(from_state, command)` combinations are illegal and MUST raise `IllegalTransition` (exit 3; §13.4, §13.17).

#### 13.19.3 Frozen structure export (`ALLOWED_TRANSITIONS`)

The single source of truth for the legal transition matrix is frozen in `stage_signal.constants` and exported from top-level `stage_signal` and `__all__`:

```python
ALLOWED_TRANSITIONS: dict[tuple[str, str], str] = {
    # start: allowed from any state -> running (SPEC §4.2)
    (STATE_QUEUED, "start"): STATE_RUNNING,
    (STATE_RUNNING, "start"): STATE_RUNNING,
    (STATE_DONE, "start"): STATE_RUNNING,
    (STATE_BLOCKED, "start"): STATE_RUNNING,
    (STATE_FAILED, "start"): STATE_RUNNING,

    # heartbeat, note, artifact: stay running (SPEC §4.3, §4.4)
    (STATE_RUNNING, "heartbeat"): STATE_RUNNING,
    (STATE_RUNNING, "note"): STATE_RUNNING,
    (STATE_RUNNING, "artifact"): STATE_RUNNING,

    # done: allowed from queued, running, or idempotent done -> done (SPEC §4.5)
    (STATE_QUEUED, "done"): STATE_DONE,
    (STATE_RUNNING, "done"): STATE_DONE,
    (STATE_DONE, "done"): STATE_DONE,

    # done --accept-failure: allowed only from failed -> done (SPEC §4.5)
    (STATE_FAILED, "done --accept-failure"): STATE_DONE,
    (STATE_FAILED, "done_accept_failure"): STATE_DONE,

    # blocked: allowed from queued, running, or idempotent blocked -> blocked (SPEC §4.6)
    (STATE_QUEUED, "blocked"): STATE_BLOCKED,
    (STATE_RUNNING, "blocked"): STATE_BLOCKED,
    (STATE_BLOCKED, "blocked"): STATE_BLOCKED,

    # fail: allowed from queued, running, or idempotent failed -> failed (SPEC §4.6)
    (STATE_QUEUED, "fail"): STATE_FAILED,
    (STATE_RUNNING, "fail"): STATE_FAILED,
    (STATE_FAILED, "fail"): STATE_FAILED,
    (STATE_QUEUED, "fail --if-dead-pid"): STATE_FAILED,
    (STATE_RUNNING, "fail --if-dead-pid"): STATE_FAILED,
    (STATE_FAILED, "fail --if-dead-pid"): STATE_FAILED,
    (STATE_RUNNING, "fail --if-needs-reclaim"): STATE_FAILED,

    # clear-terminal: allowed from terminal states or queued -> idle queued (SPEC §4.8)
    (STATE_DONE, "clear-terminal"): STATE_QUEUED,
    (STATE_BLOCKED, "clear-terminal"): STATE_QUEUED,
    (STATE_FAILED, "clear-terminal"): STATE_QUEUED,
    (STATE_QUEUED, "clear-terminal"): STATE_QUEUED,
    (STATE_DONE, "clear_terminal"): STATE_QUEUED,
    (STATE_BLOCKED, "clear_terminal"): STATE_QUEUED,
    (STATE_FAILED, "clear_terminal"): STATE_QUEUED,
    (STATE_QUEUED, "clear_terminal"): STATE_QUEUED,

    # reclaim: running with needs_reclaim -> failed [+ optional clear_terminal] (SPEC §4.7)
    (STATE_RUNNING, "reclaim"): STATE_QUEUED,
    (STATE_RUNNING, "reclaim --keep-failed"): STATE_FAILED,
    (STATE_RUNNING, "reclaim_keep_failed"): STATE_FAILED,
}
```

Helper functions exported alongside `ALLOWED_TRANSITIONS`:
- `is_transition_allowed(from_state: str, command: str) -> bool`: returns `True` if `(from_state, command)` is a legal transition edge.
- `transition_target(from_state: str, command: str) -> str`: returns the resulting `to_state` string for a legal transition, or raises `ValueError` if the transition is illegal.
- `allowed_source_states(command: str) -> tuple[str, ...]`: returns the tuple of legal `from_state` source states for the given command.

#### 13.19.4 Library gate alignment

The library gates in `Stage` (`_require_terminal_source`, `_require_state`, and transition methods) derive directly from `ALLOWED_TRANSITIONS` and `allowed_source_states`, guaranteeing exact alignment between the specification, exported metadata, and runtime enforcement without duplicate or divergent logic.

#### 13.19.5 Additive-only evolution policy

Under `schema_version: 1`, the allowed transition matrix is strictly **additive-only** (§13.1):
- Existing legal transitions MUST NOT be removed or made illegal in future minor/patch releases.
- Existing resulting target states for legal transitions MUST NOT change semantic meaning.
- New commands, optional transition flags, or new edges MAY be added in future releases under schema version 1, provided they remain compatible with the core lifecycle state machine (§4).


### 13.20 Stage public method surface freeze (`STAGE_PUBLIC_METHODS`)

Python embedders, workflow engines, and external orchestrators interact with `stage-signal` programmatically via the `Stage` class (§11). Under `schema_version: 1`, the public instance method surface of `Stage` is frozen to ensure embedders can rely on which methods exist, their semantics, and their error behavior.

#### 13.20.1 Canonical method inventory

`Stage` exposes 15 public instance methods, exactly corresponding to the 15 canonical CLI subcommands frozen in §13.15. In alphabetical order:

| Method | Signature Summary | Primary Purpose | CLI Equivalence (§13.15) | SPEC Reference |
|--------|-------------------|-----------------|--------------------------|----------------|
| `artifact` | `artifact(path, *, label=None) -> dict[str, Any]` | Record an artifact path in `STATUS.json` (`running` state only). | `stage-signal artifact` | §3, §6, §11, §13.7 |
| `blocked` | `blocked(reason, *, write_status_mirror=None) -> dict[str, Any]` | Transition stage to terminal `blocked` with reason string. | `stage-signal blocked` | §4, §6, §11 |
| `clear_terminal` | `clear_terminal(*, keep_stage=False) -> dict[str, Any]` | Reset terminal or queued state back to idle `queued`. | `stage-signal clear-terminal` | §4, §6, §11 |
| `diagnose` | `diagnose(*, stale_after=DEFAULT_STALE_THRESHOLD) -> dict[str, Any]` | Inspect directory health, validate schema, probe PID liveness, and detect reclaim needs. | `stage-signal doctor` | §4, §6, §11, §13.3.2, §13.8 |
| `done` | `done(summary=None, *, git_head=None, proof_ref=None, require_proof=False, accept_failure=False, write_status_mirror=None) -> dict[str, Any]` | Mark stage succeeded (`done`); supports optional proof gate and failure acceptance. | `stage-signal done` | §4, §6, §9, §11, §13.9, §13.10 |
| `events` | `events(*, tail=None, type=None) -> list[dict[str, Any]]` | Read chronological audit records from `events.jsonl` with optional type filter and tail limit. | `stage-signal events` | §5, §6, §11, §13.6 |
| `fail` | `fail(reason, *, if_dead_pid=False, if_needs_reclaim=False, write_status_mirror=None) -> dict[str, Any]` | Transition stage to terminal `failed` with reason; supports dead-PID or reclaim guards. | `stage-signal fail` | §4, §6, §11, §13.9 |
| `heartbeat` | `heartbeat(note=None) -> dict[str, Any]` | Bump heartbeat timestamp and optional progress note (`running` state only). | `stage-signal heartbeat` | §3, §4, §6, §11 |
| `init` | `init(project=None) -> dict[str, Any]` | Create stage directory and initial `queued` state idempotently. | `stage-signal init` | §2, §3, §4, §6, §11 |
| `note` | `note(text) -> dict[str, Any]` | Append a progress note to `STATUS.json` (`running` state only). | `stage-signal note` | §3, §6, §11, §13.7, §13.14 |
| `reclaim` | `reclaim(reason, *, keep_failed=False, kill=False, write_status_mirror=None) -> dict[str, Any]` | Atomic fail-and-clear transition when `needs_reclaim` is true; optional process termination (`kill=True`). | `stage-signal reclaim` | §4, §6, §11 |
| `start` | `start(stage, *, stage_id=None, session_id=None, pid=None, model=None, variant=None, git_head=None, git_branch=None, meta=None, write_status_mirror=None) -> dict[str, Any]` | Claim and start a stage, transition to `running`, capture PID, tokens, and git metadata. | `stage-signal start` | §3, §4, §6, §11 |
| `status` | `status() -> dict[str, Any]` | Read current status dictionary under shared lock, evaluating reclaim diagnostics. | `stage-signal status` | §6, §7, §11, §13.3.1 |
| `supervise` | `supervise(cmd, *, every=SUPERVISE_DEFAULT_EVERY, stale_threshold=DEFAULT_STALE_THRESHOLD, summary=None, reason=None, write_status_mirror=None, cwd=None, env=None) -> int` | Supervise a child process command, adopting child PID and auto-heartbeating until exit. | `stage-signal supervise` | §4, §6, §11 |
| `wait` | `wait(want="terminal", *, timeout=3600, poll=5, needs_reclaim=False) -> dict[str, Any]` | Poll until target state or `needs_reclaim` condition is met; raises `WaitTimeout` on deadline expiry. | `stage-signal wait` | §6, §7, §11, §13.3.3, §13.11 |

The single source of truth for the canonical method inventory is:

```python
STAGE_PUBLIC_METHODS = (
    "artifact",
    "blocked",
    "clear_terminal",
    "diagnose",
    "done",
    "events",
    "fail",
    "heartbeat",
    "init",
    "note",
    "reclaim",
    "start",
    "status",
    "supervise",
    "wait",
)
```

defined in `stage_signal.constants` as a sorted tuple and exported from `stage_signal` and `__all__`.

#### 13.20.2 Construction, scoping, and properties

In addition to the 15 instance methods, `Stage` provides standard construction and scoping mechanisms:

- **Constructor**: `Stage(dir: Optional[str | os.PathLike] = None)` binds a `Stage` instance to a stage directory path (falling back to `STAGE_SIGNAL_DIR` or `.stage-signal` per §2 and §13.14). Each mutation acquires an internal exclusive file lock, ensuring thread- and process-safe operations without manual lock management.
- **Context manager constructor**: `Stage.open(dir: Optional[str | os.PathLike] = None) -> Stage` provides classmethod construction for `with Stage.open(...) as s:` blocks. Scoping is purely lifecycle convenience; individual method invocations retain one-shot locking rather than holding persistent locks across the `with` block.
- **Directory property**: `stage.dir -> Path` exposes the resolved `Path` to the underlying stage directory.

#### 13.20.3 Exception contract

All `Stage` public methods raise structured exceptions from the frozen hierarchy defined in §13.17 (`StageError`, `BadArgsError`, `IllegalTransition`, `NotInitialized`, `CorruptStatusError`, `WaitTimeout`). Every exception carries an `.exit_code` integer attribute matching §7 and §13.4, ensuring Python library errors correlate directly with CLI exit behavior.

#### 13.20.4 Top-level helper functions cross-link

The Python library package exports top-level helper functions alongside `Stage` (§11):
- `resolve_dir(explicit: Optional[str | os.PathLike] = None) -> Path`: resolves stage directory precedence (§2, §13.14).
- `state_exit_code(state: str) -> int`: maps state strings to observer exit codes using `STATE_EXIT_CODES` (§13.16).
- `render_status_md(status: dict[str, Any]) -> str`: formats status dictionaries into `STATUS.md` Markdown (§13.18).
- `write_status_mirror(stage_dir: Path, status: dict[str, Any], *, repo_root: Optional[Path] = None) -> Optional[Path]`: best-effort `.orch/STATUS.md` and `.orch/DONE` mirror (§10).
- `verify_proof(ref: Optional[str] = None) -> dict[str, Any]`: proof verification logic for `--require-proof` (§9, §13.10).
- `wait_condition_met(status: dict[str, Any], *, want: str, needs_reclaim: bool = False) -> bool`: predicate evaluating wait satisfaction (§6, §13.11).
- `want_matches(want: str, state: str) -> bool`: predicate matching wait state wants (§6).
- `StageStore(dir: Optional[str | os.PathLike] = None)`: low-level filesystem store handling locked file I/O (§2, §8).

Constants owned by earlier sections (§13.2 through §13.18) are defined and governed by those respective sections and are not re-frozen here.

#### 13.20.5 Additive-only evolution policy

Under `schema_version: 1`, the `Stage` public method surface is strictly **additive-only** (§13.1):
- Existing methods in `STAGE_PUBLIC_METHODS` MUST NOT be removed or renamed.
- Existing method semantics and return schemas MUST NOT undergo breaking changes.
- Existing method signatures MAY only evolve by adding backward-compatible optional arguments (with default values).
- New public instance methods MAY be added in future minor or patch releases under schema version 1, expanding `STAGE_PUBLIC_METHODS`.
- Embedders and orchestrators can rely on the continuous availability of all 15 methods across the schema version 1 lifecycle.


### 13.21 Top-level public export inventory freeze (`PUBLIC_EXPORTS`)

External orchestrators, Python embedders, typing tools, and harnesses interact with `stage-signal` programmatically by importing symbols directly from the top-level package namespace (`stage_signal`). Under `schema_version: 1`, the complete top-level public export inventory is frozen to guarantee that all supported symbols exist, retain their documented roles, and remain importable without silent deprecation or breakage.

#### 13.21.1 Canonical export inventory

`stage_signal` exports exactly 117 public symbols matching `stage_signal.__all__`. These symbols are structured into four canonical categories:

##### 1. Classes (§11, §13.20)
- `Stage`: The primary high-level lifecycle orchestrator, embedding context manager, and transition driver (§11, §13.20).
- `StageStore`: The low-level atomic filesystem store managing status persistence, mirror writes, and cross-process file locks (§2, §8, §11, §13.20.4).

##### 2. Exception hierarchy (§13.17)
All six structured exceptions inherit from `StageError` and carry a normative `.exit_code` integer attribute matching §7 and §13.4:
- `StageError`: Base exception for all library errors (`exit_code = 1`; §13.4, §13.17).
- `BadArgsError`: Invalid arguments, unknown options, or malformed metadata (`exit_code = 2`; §13.4, §13.17).
- `IllegalTransition`: Lifecycle state machine transition rule violation (`exit_code = 3`; §13.4, §13.17, §13.19).
- `CorruptStatusError`: Unparseable or schema-invalid `STATUS.json` on disk (`exit_code = 1`; §13.2, §13.4, §13.17).
- `WaitTimeout`: Synchronous wait deadline expired before satisfaction (`exit_code = 14`; §13.4, §13.11, §13.17).
- `NotInitialized`: Stage directory does not exist or lacks initial state (`exit_code = 15`; §13.4, §13.17).

##### 3. Top-level helper functions (§11, §13.19, §13.20.4)
- `resolve_dir(explicit: Optional[str | os.PathLike] = None) -> Path`: Resolves stage directory path precedence (`--dir` > `STAGE_SIGNAL_DIR` > `.stage-signal`; §2, §13.14).
- `render_status_md(status: dict[str, Any]) -> str`: Formats status dictionary into standard Markdown for `STATUS.md` human mirrors (§13.18).
- `state_exit_code(state: str) -> int`: Maps lifecycle state string to observer exit code via `STATE_EXIT_CODES` (§7, §13.16).
- `allowed_source_states(command: str) -> tuple[str, ...]`: Queries legal source states for a given command from `ALLOWED_TRANSITIONS` (§13.19).
- `is_transition_allowed(from_state: str, command: str) -> bool`: Evaluates whether a `(from_state, command)` transition edge is legal (§13.19).
- `transition_target(from_state: str, command: str) -> str`: Returns the target state for a legal transition edge or raises `ValueError` (§13.19).
- `verify_proof(ref: Optional[str] = None) -> dict[str, Any]`: Verifies composition proof artifacts for `--require-proof` gates (§9, §13.10).
- `supervise_adopt_message(pid) -> str`: Renders the frozen supervise adoption heartbeat message (`SUPERVISE_ADOPT_MESSAGE_FORMAT`; §13.24).
- `supervise_signal_exit(signum: int) -> int`: Maps a terminating signal number to the frozen supervise exit code `128 + SIGNUM` (§13.24).
- `wait_condition_met(status: dict[str, Any], *, want: str, needs_reclaim: bool = False) -> bool`: Evaluates whether wait criteria are satisfied (§6, §13.11).
- `want_matches(want: str, state: str) -> bool`: Matches target state against wait condition strings (§6).
- `write_status_mirror(stage_dir: Path, status: dict[str, Any], *, repo_root: Optional[Path] = None) -> Optional[Path]`: Best-effort repository-level `.orch/STATUS.md` and `.orch/DONE` mirror writer (§10).

##### 4. Frozen constants and schema definitions (§13.2–§13.20)
- **Version and schema:**
  - `SCHEMA_VERSION`: Integer schema version (`1`; §3, §13.1).
  - `__version__`: Library release version string.
- **Lifecycle states and transitions:**
  - `STATES`: Tuple of all 5 lifecycle states (`queued`, `running`, `done`, `blocked`, `failed`; §4, §13.12).
  - Individual state strings: `STATE_QUEUED`, `STATE_RUNNING`, `STATE_DONE`, `STATE_BLOCKED`, `STATE_FAILED` (§4, §13.12).
  - `TERMINAL_STATES`: Tuple of terminal states (`done`, `blocked`, `failed`; §4, §13.12).
  - `ALLOWED_TRANSITIONS`: Normative transition matrix mapping `(from_state, command)` to target state (§13.19).
- **Inventories:**
  - `CLI_SUBCOMMANDS`: 15 frozen CLI subcommands (§13.15).
  - `STAGE_PUBLIC_METHODS`: 15 frozen `Stage` public instance methods (§13.20).
  - `PUBLIC_EXPORTS`: 117 frozen public symbols exported from top-level package namespace (§13.21).
- **Exit codes:**
  - `EXIT_CODES`: Tuple of all 10 standard exit codes (§7, §13.4).
  - Individual exit codes: `EXIT_OK` (0), `EXIT_ERROR` (1), `EXIT_BAD_ARGS` (2), `EXIT_ILLEGAL_TRANSITION` (3), `EXIT_RUNNING` (10), `EXIT_BLOCKED` (11), `EXIT_FAILED` (12), `EXIT_QUEUED` (13), `EXIT_WAIT_TIMEOUT` (14), `EXIT_NOT_INITIALIZED` (15) (§7, §13.4).
  - `STATE_EXIT_CODES`: Dictionary mapping states to observer exit codes (§7, §13.16).
- **Filesystem layout and environment:**
  - Layout paths: `DEFAULT_DIR_NAME` (`.stage-signal`), `STATUS_FILENAME` (`STATUS.json`), `STATUS_MD_FILENAME` (`STATUS.md`), `EVENTS_FILENAME` (`events.jsonl`), `LOCKS_DIRNAME` (`locks`), `LOCK_FILENAME` (`stage.lock`), `DEFAULT_MIRROR_DIRNAME` (`.orch`) (§2, §10, §13.13).
  - Environment variables: `ENV_DIR`, `ENV_PROJECT`, `ENV_PROOF_REF`, `ENV_STATUS_MIRROR`, `ENV_VARS` (§13.14).
- **STATUS.json schema keys:**
  - `STATUS_REQUIRED_KEYS`: 23 normative required on-disk keys (§3, §13.2).
  - `STATUS_JSON_KEYS`: Normative + runtime keys emitted by `status --json` (§13.3.1).
  - `ARTIFACT_ENTRY_KEYS`: Entry keys for `artifacts[]` (`path`, `label`, `added_at`; §3, §13.7).
  - `NOTE_ENTRY_KEYS`: Entry keys for `notes[]` (`text`, `added_at`; §3, §13.7).
  - `MAX_NOTES`: Maximum retained note records (200; §3, §13.7, §13.14).
  - `RESULT_KEYS`: Keys for `result` object (`summary`, `git_head`, `finished_at`; §3, §13.9).
  - `ERROR_KEYS`: Keys for `error` object (`reason`, `kind`, `finished_at`; §3, §13.9).
  - `ERROR_KINDS`: Allowed error kind strings (`blocked`, `failed`; §3, §13.9).
  - `PROOF_KEYS`: Keys for `proof` object (`tool`, `ref`, `verified`; §9, §13.10).
  - `PROOF_REQUIRED_KEYS`: Alias for `PROOF_KEYS` (§13.10).
  - `PROOF_VERIFIED_VALUES`: Allowed values for proof verification (`None`, `"file"`, `"verify"`; §9, §13.10).
- **Audit events:**
  - `EVENT_TYPES`: 9 frozen audit event type strings (§5, §13.5).
  - `EVENT_RECORD_KEYS`: Required keys on each event object in `events.jsonl` (§5, §13.6).
  - `EVENTS_DEFAULT_TAIL`: CLI default tail count (20; §5, §13.6, §13.14).
- **Diagnostics, warnings, and defaults:**
  - `DOCTOR_JSON_KEYS`: Required keys in `doctor --json` payload (§13.3.2).
  - `WARNING_CODES`: Frozen warning codes (`STALE_HEARTBEAT`, `DEAD_PID`, `UNPARSEABLE_HEARTBEAT`; §13.8).
  - Individual warning code constants: `WARNING_CODE_DEAD_PID`, `WARNING_CODE_STALE_HEARTBEAT`, `WARNING_CODE_UNPARSEABLE_HEARTBEAT` (§13.8).
  - `WARNING_KEYS`: Required keys in doctor warning objects (`code`, `message`, `detail`; §13.8).
  - `WARNING_REQUIRED_KEYS`: Alias for `WARNING_KEYS` (§13.8).
  - `DOCTOR_WARNING_KEYS`: Alias for `WARNING_KEYS` (§13.8).
  - `DOCTOR_SUMMARY_RECLAIM_NEEDED`, `DOCTOR_SUMMARY_OK_FORMAT`, and helper `doctor_summary_ok` (§13.22).
  - `DEFAULT_STALE_THRESHOLD`: Default stale heartbeat threshold in seconds (300.0; §4, §13.8, §13.14).
- **Wait choices, outcomes, and defaults:**
  - `WAIT_CHOICES`: Allowed `--state` target choices (`"done"`, `"blocked"`, `"failed"`, `"terminal"`; §6, §13.23).
  - `WAIT_WANT_NEEDS_RECLAIM`: Canonical reclaim want token (`"needs_reclaim"`; §6, §13.3.3, §13.23).
  - `want_matches(want, state)` and `wait_condition_met(status, *, want, needs_reclaim)`: Matching predicates (§6, §13.23).
  - `WAIT_JSON_KEYS`: Required keys in `wait --json` payload (§13.3.3).
  - `WAIT_OUTCOMES`: Frozen wait outcome enums (`"met"`, `"mismatch"`, `"timeout"`; §13.11).
  - Individual wait outcomes: `WAIT_OUTCOME_MET`, `WAIT_OUTCOME_MISMATCH`, `WAIT_OUTCOME_TIMEOUT` (§13.11).
  - Timing defaults: `WAIT_DEFAULT_TIMEOUT` (3600.0), `WAIT_DEFAULT_POLL` (5.0) (§6, §13.11, §13.14).
- **Human mirror headings:**
  - `STATUS_MD_TITLE`: Document title heading (`# stage-signal STATUS`; §13.18).
  - `STATUS_MD_REQUIRED_HEADINGS`: 8 required section headings (§13.18).
  - `STATUS_MD_OPTIONAL_HEADINGS`: 3 conditional headings (`heartbeat_note:`, `result:`, `error:`; §13.18).
  - `STATUS_MD_HEADINGS`: Union of required and optional headings (§13.18).
- **Supervision:**
  - `SUPERVISE_DEFAULT_EVERY`: Child supervision heartbeat interval (60.0; §4, §6, §13.14).
  - `SUPERVISE_ADOPT_MESSAGE_FORMAT` (`"adopted child pid {pid}"`) and helper `supervise_adopt_message(pid)`; `SUPERVISE_ADOPT_DETAIL_KEYS` (`previous_pid`, `pid`, `pid_token`; §13.24).
  - Default terminal templates: `SUPERVISE_DONE_SUMMARY_FORMAT` (`"command succeeded (exit 0): {cmd}"`), `SUPERVISE_FAIL_REASON_FORMAT` (`"command failed with exit code {code}: {cmd}"`), `SUPERVISE_SIGNAL_REASON_FORMAT` (`"command terminated by {signame}: {cmd}"`; §13.24).
  - Exit mapping: `SUPERVISE_SIGNAL_EXIT_BASE` (128) and helper `supervise_signal_exit(signum)`; spawn failures `SUPERVISE_EXIT_NOT_FOUND` (127) and `SUPERVISE_EXIT_PERMISSION_DENIED` (126; §7, §13.24).
- **Reclaim fail-and-clear:**
  - `RECLAIM_ALLOWED_SOURCES`: Legal source state (`"running"`; §4 rule 7, §13.25).
  - `RECLAIM_FAILED_DETAIL_KEYS`: Detail keys on reclaim-emitted `failed` event (`"reclaim"`, `"keep_failed"`; §4 rule 7, §5, §13.25).
  - `RECLAIM_CLEAR_TERMINAL_DETAIL_KEYS`: Detail keys on reclaim-emitted `clear_terminal` event (`"keep_stage"`, `"reclaim"`; §4 rule 7, §5, §13.25).
- **Heartbeat liveness:**
  - `HEARTBEAT_ALLOWED_SOURCES`: Legal source states (`"running"` only; §4, §13.27).
  - `HEARTBEAT_DETAIL_KEYS`: Audit detail keys (empty — heartbeat carries no detail extras; §5, §13.27).
- **Clear-terminal reset and audit:**
  - `CLEAR_TERMINAL_ALLOWED_SOURCES`: Legal source states (`"done"`, `"blocked"`, `"failed"`, `"queued"`; §4, §13.26).
  - `CLEAR_TERMINAL_IDLE_RESET_FIELDS`: Ten identity/claim fields reset to idle by default (§4, §13.26).
  - `CLEAR_TERMINAL_KEEP_STAGE_PRESERVED_FIELDS`: The same ten fields preserved with `--keep-stage` (§4, §13.26).
  - `CLEAR_TERMINAL_ALWAYS_CLEARED_FIELDS`: Terminal payloads always cleared (`"result"`, `"error"`, `"proof"`; §4, §13.26).
  - `CLEAR_TERMINAL_DETAIL_KEYS`: Audit detail keys (`"keep_stage"`; §5, §13.26).
  - `CLEAR_TERMINAL_MESSAGE_IDLE` (`"cleared to idle queued"`) and `CLEAR_TERMINAL_MESSAGE_KEEP_STAGE` (`"cleared to queued"`; §5, §13.26).

#### 13.21.2 Frozen structure export (`PUBLIC_EXPORTS`)

The single source of truth for the canonical top-level public export inventory is defined in `stage_signal.constants` as a sorted tuple and re-exported from `stage_signal` and `__all__`:

```python
PUBLIC_EXPORTS: tuple[str, ...] = (
    "ALLOWED_TRANSITIONS",
    "ARTIFACT_ENTRY_KEYS",
    "BadArgsError",
    "CLEAR_TERMINAL_ALLOWED_SOURCES",
    "CLEAR_TERMINAL_ALWAYS_CLEARED_FIELDS",
    "CLEAR_TERMINAL_DETAIL_KEYS",
    "CLEAR_TERMINAL_IDLE_RESET_FIELDS",
    "CLEAR_TERMINAL_KEEP_STAGE_PRESERVED_FIELDS",
    "CLEAR_TERMINAL_MESSAGE_IDLE",
    "CLEAR_TERMINAL_MESSAGE_KEEP_STAGE",
    "CLI_SUBCOMMANDS",
    "CorruptStatusError",
    "DEFAULT_DIR_NAME",
    "DEFAULT_MIRROR_DIRNAME",
    "DEFAULT_STALE_THRESHOLD",
    "DOCTOR_JSON_KEYS",
    "DOCTOR_SUMMARY_OK_FORMAT",
    "DOCTOR_SUMMARY_RECLAIM_NEEDED",
    "DOCTOR_WARNING_KEYS",
    "ENV_DIR",
    "ENV_PROJECT",
    "ENV_PROOF_REF",
    "ENV_STATUS_MIRROR",
    "ENV_VARS",
    "ERROR_KEYS",
    "ERROR_KINDS",
    "EVENTS_DEFAULT_TAIL",
    "EVENTS_FILENAME",
    "EVENT_RECORD_KEYS",
    "EVENT_TYPES",
    "EXIT_BAD_ARGS",
    "EXIT_BLOCKED",
    "EXIT_CODES",
    "EXIT_ERROR",
    "EXIT_FAILED",
    "EXIT_ILLEGAL_TRANSITION",
    "EXIT_NOT_INITIALIZED",
    "EXIT_OK",
    "EXIT_QUEUED",
    "EXIT_RUNNING",
    "EXIT_WAIT_TIMEOUT",
    "HEARTBEAT_ALLOWED_SOURCES",
    "HEARTBEAT_DETAIL_KEYS",
    "IllegalTransition",
    "LOCKS_DIRNAME",
    "LOCK_FILENAME",
    "MAX_NOTES",
    "NOTE_ENTRY_KEYS",
    "NotInitialized",
    "PROOF_KEYS",
    "PROOF_REQUIRED_KEYS",
    "PROOF_VERIFIED_VALUES",
    "PUBLIC_EXPORTS",
    "RECLAIM_ALLOWED_SOURCES",
    "RECLAIM_CLEAR_TERMINAL_DETAIL_KEYS",
    "RECLAIM_FAILED_DETAIL_KEYS",
    "RESULT_KEYS",
    "SCHEMA_VERSION",
    "STAGE_PUBLIC_METHODS",
    "STATES",
    "STATE_BLOCKED",
    "STATE_DONE",
    "STATE_EXIT_CODES",
    "STATE_FAILED",
    "STATE_QUEUED",
    "STATE_RUNNING",
    "STATUS_FILENAME",
    "STATUS_JSON_KEYS",
    "STATUS_MD_FILENAME",
    "STATUS_MD_HEADINGS",
    "STATUS_MD_OPTIONAL_HEADINGS",
    "STATUS_MD_REQUIRED_HEADINGS",
    "STATUS_MD_TITLE",
    "STATUS_REQUIRED_KEYS",
    "SUPERVISE_ADOPT_DETAIL_KEYS",
    "SUPERVISE_ADOPT_MESSAGE_FORMAT",
    "SUPERVISE_DEFAULT_EVERY",
    "SUPERVISE_DONE_SUMMARY_FORMAT",
    "SUPERVISE_EXIT_NOT_FOUND",
    "SUPERVISE_EXIT_PERMISSION_DENIED",
    "SUPERVISE_FAIL_REASON_FORMAT",
    "SUPERVISE_SIGNAL_EXIT_BASE",
    "SUPERVISE_SIGNAL_REASON_FORMAT",
    "Stage",
    "StageError",
    "StageStore",
    "TERMINAL_STATES",
    "WAIT_CHOICES",
    "WAIT_DEFAULT_POLL",
    "WAIT_DEFAULT_TIMEOUT",
    "WAIT_JSON_KEYS",
    "WAIT_OUTCOMES",
    "WAIT_OUTCOME_MET",
    "WAIT_OUTCOME_MISMATCH",
    "WAIT_OUTCOME_TIMEOUT",
    "WAIT_WANT_NEEDS_RECLAIM",
    "WARNING_CODES",
    "WARNING_CODE_DEAD_PID",
    "WARNING_CODE_STALE_HEARTBEAT",
    "WARNING_CODE_UNPARSEABLE_HEARTBEAT",
    "WARNING_KEYS",
    "WARNING_REQUIRED_KEYS",
    "WaitTimeout",
    "__version__",
    "allowed_source_states",
    "doctor_summary_ok",
    "is_transition_allowed",
    "render_status_md",
    "resolve_dir",
    "state_exit_code",
    "supervise_adopt_message",
    "supervise_signal_exit",
    "transition_target",
    "verify_proof",
    "wait_condition_met",
    "want_matches",
    "write_status_mirror",
)
```

#### 13.21.3 `__all__` set-equality and importability contract

Every symbol enumerated in `PUBLIC_EXPORTS`:
1. **`__all__` equivalence:** `set(PUBLIC_EXPORTS) == set(stage_signal.__all__)` MUST hold exactly. No public export may exist on `stage_signal` without membership in `PUBLIC_EXPORTS`, and no symbol in `PUBLIC_EXPORTS` may be omitted from `__all__`.
2. **Direct importability:** Every name in `PUBLIC_EXPORTS` MUST be directly accessible via attribute lookup (`getattr(stage_signal, name)`) and standard Python import mechanisms (`from stage_signal import <name>`).
3. **No private symbol leakage:** Names prefixed with `_` are strictly prohibited from `PUBLIC_EXPORTS`, with the sole normative exception of `__version__`.

#### 13.21.4 Cross-links

- **§11 (Library API):** Documents library usage, context managers, and top-level helper functions.
- **§13.17 (Exception hierarchy):** Formally defines the exception class tree and exit code mapping.
- **§13.20 (Stage public method surface):** Formally defines and freezes the 15 instance methods of `Stage` (`STAGE_PUBLIC_METHODS`).

#### 13.21.5 Additive-only evolution policy

Under `schema_version: 1`, the top-level public export inventory is strictly **additive-only** (§13.1):
- Existing symbols in `PUBLIC_EXPORTS` MUST NOT be removed, renamed, or relocated.
- Existing symbol types, semantics, and contracts MUST NOT undergo breaking changes.
- Future minor or patch releases under schema version 1 MAY add new classes, helper functions, or frozen constants to `stage_signal`, expanding `PUBLIC_EXPORTS` and `__all__`.
- External orchestrators, embedders, and typing definitions can safely rely on the uninterrupted presence of all 117 public exports throughout the entire lifecycle of `schema_version: 1`.

### 13.22 Doctor human summary strings freeze (`DOCTOR_SUMMARY_RECLAIM_NEEDED`, `DOCTOR_SUMMARY_OK_FORMAT`)

The `summary` field of `doctor --json` / `Stage.diagnose()` (§6, §13.3.2, `DOCTOR_JSON_KEYS`) is a **human display string** for operators and log compatibility. Orchestrators MUST branch on the machine-readable `needs_reclaim` boolean (§6, §13.3.2) rather than string-matching `summary` or scraping human warning text (§13.8). Reclaim detection rules themselves are unchanged by this section.

#### 13.22.1 Frozen values and exact format

The single sources of truth are defined in `stage_signal.constants` and exported from `stage_signal` and `__all__`:

```python
DOCTOR_SUMMARY_RECLAIM_NEEDED = "ATTENTION: running needs reclaim"
DOCTOR_SUMMARY_OK_FORMAT = "OK: {state}"
```

- When `needs_reclaim` is true (state is `running` and a `DEAD_PID` or `STALE_HEARTBEAT` warning applies; §6, §13.8), `summary` is exactly `DOCTOR_SUMMARY_RECLAIM_NEEDED` (`"ATTENTION: running needs reclaim"`), byte-for-byte, with no state suffix, prefix, or trailing punctuation.
- Otherwise, when no problems exist, `summary` is exactly `"OK: {state}"` with the readable state substituted for `{state}` (for example `"OK: running"`, `"OK: queued"`, `"OK: done"`, `"OK: blocked"`, `"OK: failed"`). The single space after the colon and the `OK:` prefix casing are normative. The helper `doctor_summary_ok(state) -> str` renders this template (`DOCTOR_SUMMARY_OK_FORMAT.format(state=state)`) and is exported alongside the constants.

#### 13.22.2 When `summary` is `null` vs a string

| Condition | `summary` |
|-----------|-----------|
| `problems` is non-empty (missing dir, missing/corrupt `STATUS.json` or `events.jsonl`, unwritable lock; §6) | `null` — regardless of `needs_reclaim`, which remains independently computed and may still be `true` when reclaim warnings coexist with problems |
| `problems` is empty and `needs_reclaim` is `true` | `DOCTOR_SUMMARY_RECLAIM_NEEDED` |
| `problems` is empty and `needs_reclaim` is `false` | `"OK: {state}"` via `doctor_summary_ok(state)` |

The same rule applies to the human `doctor` summary line printed to stdout: it prints the `summary` value when it is a string, and prints `PROBLEM:` lines instead when `summary` is `null`.

#### 13.22.3 Additive-only evolution policy

Under `schema_version: 1`, doctor summary strings are strictly **additive-only** (§13.1):
- The frozen reclaim string and the `"OK: {state}"` template MUST NOT be removed, renamed, reworded, or change semantic meaning.
- The null-vs-string rule in §13.22.2 MUST NOT change: `summary` stays `null` exactly when `problems` is non-empty.
- New summary variants for future states or conditions MAY be added in minor or patch releases only as additional `"OK: {state}"` renderings for new states, or as new distinct constants; existing frozen strings MUST keep their exact values.
- Readers MUST treat `summary` as display-only and tolerate unknown future summary strings without failing.

### 13.23 Wait want vocabulary and predicate freeze (`WAIT_CHOICES`, `WAIT_WANT_NEEDS_RECLAIM`, `want_matches`, `wait_condition_met`)

The target condition vocabulary and predicate helpers for `wait` operations (§6, §11, `Stage.wait`) are frozen under `schema_version: 1` so orchestrators and automation can rely on exact want strings and predicate semantics.

#### 13.23.1 Frozen vocabulary constants (`WAIT_CHOICES`, `WAIT_WANT_NEEDS_RECLAIM`)

The single sources of truth for the wait target vocabulary are defined in `stage_signal.constants` and exported from `stage_signal` and `__all__`:

```python
WAIT_CHOICES: tuple[str, ...] = ("done", "blocked", "failed", "terminal")
WAIT_WANT_NEEDS_RECLAIM: str = "needs_reclaim"
```

| Want Token | Constant / Origin | Target State(s) / Condition | Meaning |
|------------|-------------------|-----------------------------|---------|
| `"terminal"` | `WAIT_CHOICES[3]` (CLI default) | Any state in `TERMINAL_STATES` (`"done"`, `"blocked"`, `"failed"`; §13.12) | Stage execution reached any terminal lifecycle state (§4, §6). |
| `"done"` | `WAIT_CHOICES[0]` / `STATE_DONE` | `state == "done"` | Stage completed successfully (§4, §6). |
| `"blocked"` | `WAIT_CHOICES[1]` / `STATE_BLOCKED` | `state == "blocked"` | Stage entered blocked state awaiting external resolution (§4, §6). |
| `"failed"` | `WAIT_CHOICES[2]` / `STATE_FAILED` | `state == "failed"` | Stage aborted or exited with unrecoverable failure (§4, §6). |
| `"needs_reclaim"` | `WAIT_WANT_NEEDS_RECLAIM` | `needs_reclaim == true` | Stage is in `running` state with a dead PID or stale heartbeat requiring reclaim (§6, §13.8). |

- **`WAIT_CHOICES`**: Closed tuple of the 4 permitted target values for the CLI `--state` option (`stage-signal wait --state <choice>`) and the library `Stage.wait(want=...)` argument.
- **`WAIT_WANT_NEEDS_RECLAIM`**: The canonical string token (`"needs_reclaim"`) reported in the machine-readable `wanted` field of `wait --json` (§13.3.3) when polling for the reclaim condition via `--needs-reclaim`.
- **Mapping of `"terminal"` to `TERMINAL_STATES`**: The want token `"terminal"` matches if and only if `state in TERMINAL_STATES` (`("done", "blocked", "failed")` per §13.12). Non-terminal states (`"queued"`, `"running"`) never match `"terminal"`.

#### 13.23.2 Matching predicate helper semantics (`want_matches`, `wait_condition_met`)

Two public predicate functions implement canonical wait target evaluation and are exported from `stage_signal` and `__all__`:

```python
def want_matches(want: str, state: str) -> bool:
    """True when *state* satisfies a `wait --state` want value."""
    if want == "terminal":
        return state in TERMINAL_STATES
    return state == want


def wait_condition_met(
    status: dict[str, Any],
    *,
    want: str,
    needs_reclaim: bool = False,
) -> bool:
    """True when a wait snapshot satisfies the requested condition."""
    if needs_reclaim:
        return bool(status.get("needs_reclaim"))
    return want_matches(want, str(status.get("state")))
```

##### Predicate truth table across lifecycle states

| Observed State | `want="terminal"` | `want="done"` | `want="blocked"` | `want="failed"` | `needs_reclaim=True` (`needs_reclaim=False` in snapshot) | `needs_reclaim=True` (`needs_reclaim=True` in snapshot) |
|----------------|-------------------|---------------|------------------|-----------------|----------------------------------------------------------|---------------------------------------------------------|
| `queued` | `False` | `False` | `False` | `False` | `False` | `False` (reclaim requires `running`) |
| `running` | `False` | `False` | `False` | `False` | `False` | `True` |
| `done` | `True` | `True` | `False` | `False` | `False` | `False` |
| `blocked` | `True` | `False` | `True` | `False` | `False` | `False` |
| `failed` | `True` | `False` | `False` | `True` | `False` | `False` |
| unknown / other | `False` | `False` | `False` | `False` | `False` | `True` if `bool(status.get("needs_reclaim"))` else `False` |

##### Mutual exclusivity of `--needs-reclaim` vs `--state`

Waiting for a specific state target and waiting for `needs_reclaim` are mutually exclusive wait modes:
- **CLI (`stage-signal wait`)**: Specifying `--needs-reclaim` alongside any `--state` argument other than the default (`"terminal"`) is rejected with `BadArgsError` (exit code 2, `EXIT_BAD_ARGS`; §6, §7, §13.4).
- **Library (`Stage.wait`)**: Calling `Stage.wait(want, needs_reclaim=True)` with any `want != "terminal"` raises `BadArgsError` (`exit_code = EXIT_BAD_ARGS = 2`; §11, §13.17).
- When `needs_reclaim=True`, `wait_condition_met` inspects only `status["needs_reclaim"]`, ignoring the `want` argument.

#### 13.23.3 Cross-links

- **§6 (CLI contract):** Documents `stage-signal wait`, options (`--state`, `--needs-reclaim`, `--timeout`, `--poll`, `--json`), and observer exit code contracts (met: 0, mismatch: state exit code / 1 for done without reclaim, timeout: 14, not initialized: 15).
- **§13.11 (Wait outcomes enum freeze):** Defines `WAIT_OUTCOMES` (`"met"`, `"mismatch"`, `"timeout"`), outcome resolution, and boolean `timeout` field consistency in `wait --json`.
- **§13.12 (Stage states and terminal states freeze):** Defines `STATES` and `TERMINAL_STATES` (`"done"`, `"blocked"`, `"failed"`).
- **§13.16 (State-to-exit-code mapping freeze):** Defines `STATE_EXIT_CODES` used by wait observer mismatch resolutions (`queued` → 13, `running` → 10, `done` → 0 / mismatch 1, `blocked` → 11, `failed` → 12).
- **§13.21 (Top-level public export inventory):** Freezes the inclusion of `WAIT_CHOICES`, `WAIT_WANT_NEEDS_RECLAIM`, `want_matches`, and `wait_condition_met` in `PUBLIC_EXPORTS`.

#### 13.23.4 Additive-only evolution policy

Under `schema_version: 1`, wait want vocabulary and matching semantics are strictly **additive-only** (§13.1):
- Existing want tokens in `WAIT_CHOICES` (`"done"`, `"blocked"`, `"failed"`, `"terminal"`) and `WAIT_WANT_NEEDS_RECLAIM` (`"needs_reclaim"`) MUST NOT be removed, renamed, or relocated.
- The semantics of `want_matches` (including the mapping of `"terminal"` to `TERMINAL_STATES`) and `wait_condition_met` MUST NOT change.
- The mutual exclusivity of `needs_reclaim` with non-default state wants MUST remain enforced.
- Future versions under schema version 1 MAY add new target choices to `WAIT_CHOICES` or expand wait conditions in a strictly additive manner; existing callers relying on frozen want strings and predicate semantics will remain unaffected.

### 13.24 Supervise child-PID adoption and supervisor exit contract freeze (`SUPERVISE_ADOPT_MESSAGE_FORMAT`, `SUPERVISE_ADOPT_DETAIL_KEYS`, `SUPERVISE_SIGNAL_EXIT_BASE`, `SUPERVISE_EXIT_NOT_FOUND`, `SUPERVISE_EXIT_PERMISSION_DENIED`)

`Stage.supervise` / `stage-signal supervise` (§4 rule 7, §6, §13.20) runs a child command while auto-heartbeating, then records a terminal transition and returns the supervisor exit code. Under `schema_version: 1`, the adoption heartbeat shape and the supervisor exit-code mapping are frozen so orchestrators can branch on the adoption event and on the returned exit code without scraping human text. `doctor` liveness checks and `reclaim --kill` target the adopted child PID rather than the supervisor wrapper process (§13.8).

#### 13.24.1 Frozen constants and exact formats

The single sources of truth are defined in `stage_signal.constants` and exported from `stage_signal` and `__all__`:

```python
SUPERVISE_ADOPT_MESSAGE_FORMAT = "adopted child pid {pid}"
SUPERVISE_ADOPT_DETAIL_KEYS = ("previous_pid", "pid", "pid_token")

SUPERVISE_DONE_SUMMARY_FORMAT = "command succeeded (exit 0): {cmd}"
SUPERVISE_FAIL_REASON_FORMAT = "command failed with exit code {code}: {cmd}"
SUPERVISE_SIGNAL_REASON_FORMAT = "command terminated by {signame}: {cmd}"

SUPERVISE_SIGNAL_EXIT_BASE = 128
SUPERVISE_EXIT_NOT_FOUND = 127
SUPERVISE_EXIT_PERMISSION_DENIED = 126
```

- The helper `supervise_adopt_message(pid) -> str` renders `SUPERVISE_ADOPT_MESSAGE_FORMAT.format(pid=pid)` and is exported alongside the constants.
- The helper `supervise_signal_exit(signum: int) -> int` returns `SUPERVISE_SIGNAL_EXIT_BASE + signum` and is exported alongside the constants.

#### 13.24.2 Precondition

The stage MUST already be in state `running` before spawning the child (§4, §6, §13.19):

| Precondition failure | Library | CLI exit |
|----------------------|---------|----------|
| Stage not initialized (missing dir/STATUS) | `NotInitialized` | 15 (`EXIT_NOT_INITIALIZED`; §7, §13.4, §13.17) |
| Current state is not `running` | `IllegalTransition` | 3 (`EXIT_ILLEGAL_TRANSITION`; §7, §13.4, §13.17) |
| Empty/invalid command or `every` out of range | `BadArgsError` | 2 (`EXIT_BAD_ARGS`; §7, §13.4, §13.17) |

No child process is spawned and no STATUS, event, or mirror mutation occurs on precondition failure.

#### 13.24.3 Adoption under exclusive lock

After `Popen` successfully spawns the child, `supervise` updates STATUS under a single exclusive lock (§8): `pid` becomes the child's `proc.pid`, `pid_token` is refreshed via the existing start-identity capture (or `null` when capture is unavailable, same as `start`; §4), and `updated_at` / `heartbeat_at` are bumped. `stage_id`, `stage_name`, `attempt`, and `session_id` are preserved unchanged.

In that same locked section, adoption is recorded as a `heartbeat` event (no new event type; §5, §13.5):

- `message` is exactly `supervise_adopt_message(child_pid)` (`"adopted child pid <N>"`, byte-for-byte, no affixes).
- `detail` carries exactly the `SUPERVISE_ADOPT_DETAIL_KEYS` (`previous_pid` is the supervisor-recorded PID before adoption, `pid` is the adopted child PID, `pid_token` is the refreshed token or `null`).

Readers MUST tolerate additive unknown keys on the adoption `detail` object without failing (§13.1).

#### 13.24.4 Terminal mapping and supervisor exit codes

When the child exits, `supervise` records a terminal transition (§4) and returns the supervisor exit code:

| Child outcome | Terminal state | Default `result.summary` / `error.reason` (overridable via `summary=` / `reason=`) | Supervisor return |
|---------------|----------------|--------------------------------------------------------------------------------------|-------------------|
| Exit 0 | `done` | `SUPERVISE_DONE_SUMMARY_FORMAT.format(cmd=CMD)` | 0 |
| Exit N (non-zero) | `failed` | `SUPERVISE_FAIL_REASON_FORMAT.format(code=N, cmd=CMD)` | N (the child exit code) |
| Terminated by signal SIGNUM | `failed` | `SUPERVISE_SIGNAL_REASON_FORMAT.format(signame=NAME, cmd=CMD)` | `supervise_signal_exit(SIGNUM)` (`128 + SIGNUM`) |
| Spawn fails: command not found | `failed` (`"command not found: ..."`) | — | `SUPERVISE_EXIT_NOT_FOUND` (127) |
| Spawn fails: permission denied | `failed` (`"permission denied: ..."`) | — | `SUPERVISE_EXIT_PERMISSION_DENIED` (126) |

`CMD` is the shell-quoted command display string. Signals (`SIGINT`, `SIGTERM`) received by the supervisor are forwarded to the child; the supervisor waits for child exit and records the terminal transition before returning.

#### 13.24.5 Additive-only evolution policy

Under `schema_version: 1`, the supervise adoption and exit contract is strictly **additive-only** (§13.1):

- The frozen adoption message format, detail keys, default summary/reason templates, and exit-code mapping MUST NOT be removed, renamed, reworded, or change semantic meaning.
- No new event type is introduced for adoption: the adoption record stays a `heartbeat` event (§13.5).
- New adoption detail keys or terminal templates MAY be added in minor or patch releases only as additional constants; existing frozen values MUST keep their exact values.
- Readers MUST tolerate unknown future adoption detail keys and unknown future summary/reason strings without failing.

### 13.25 Reclaim fail-and-clear contract freeze (`RECLAIM_ALLOWED_SOURCES`, `RECLAIM_FAILED_DETAIL_KEYS`, `RECLAIM_CLEAR_TERMINAL_DETAIL_KEYS`)

`Stage.reclaim` / `stage-signal reclaim --reason TEXT [--keep-failed] [--kill]` (§4 rule 7, §6, §13.20) performs a one-shot recovery of a broken or stale `running` stage when `needs_reclaim` is true. Under `schema_version: 1`, the allowed source state, the precondition guard, the atomic fail-and-clear sequence under exclusive lock, the `--keep-failed` identity preservation, the `--kill` best-effort process termination and token re-verification, and the exact event shapes (`failed` and `clear_terminal`) are frozen so orchestrators can reliably reclaim stuck stages without scraping human text or risking partial state mutations. The transition edges are frozen in §13.19 and method signature in §13.20.

#### 13.25.1 Frozen constants and exact values

The single sources of truth are defined in `stage_signal.constants` and exported from `stage_signal` and `__all__`:

```python
RECLAIM_ALLOWED_SOURCES = (
    "running",
)

RECLAIM_FAILED_DETAIL_KEYS = (
    "reclaim",
    "keep_failed",
)

RECLAIM_CLEAR_TERMINAL_DETAIL_KEYS = (
    "keep_stage",
    "reclaim",
)
```

- `RECLAIM_ALLOWED_SOURCES`: exactly `("running",)`. Reclaim is legal only from the `running` state (§13.12). It equals `set(allowed_source_states("reclaim"))` and `set(allowed_source_states("reclaim --keep-failed"))` from `ALLOWED_TRANSITIONS` (§13.19).
- `RECLAIM_FAILED_DETAIL_KEYS`: exactly `("reclaim", "keep_failed")`. Detail keys on the `failed` event record appended by reclaim.
- `RECLAIM_CLEAR_TERMINAL_DETAIL_KEYS`: exactly `("keep_stage", "reclaim")`. Detail keys on the `clear_terminal` event record appended as the second step of default reclaim.

#### 13.25.2 Preconditions and the `needs_reclaim` guard

Reclaim is protected by a strict prerequisite guard evaluated under the exclusive filesystem lock (`locks/stage.lock`, §8):

1. The stage must be initialized (`STATUS.json` present and readable; §2). If not initialized, raise `NotInitialized` (CLI exit 15).
2. The reason must be non-empty (`reason.strip()` must not be empty). If missing or whitespace-only, raise `BadArgsError` (CLI exit 2).
3. The stage must satisfy `needs_reclaim == True` under identical detection as `doctor` (§6, §13.8), `status --json` (§13.3.1), `Stage.diagnose()`, and `wait --needs-reclaim` (§13.23):
   - Current state must be `running` (`STATE_RUNNING`, §13.12). Reclaim from non-running states (`queued`, `done`, `blocked`, `failed`) is strictly illegal.
   - At least one of `DEAD_PID` or `STALE_HEARTBEAT` warnings (§13.8) must apply:
     - `DEAD_PID`: the claiming PID is a valid positive integer and `_is_pid_alive(pid)` is `False`.
     - `STALE_HEARTBEAT`: elapsed time since `heartbeat_at` exceeds the threshold (default `DEFAULT_STALE_THRESHOLD` = 300s, §13.14) or no heartbeat is recorded.

| Precondition failure | Library exception | CLI exit code |
|---|---|---|
| Stage not initialized (missing dir or `STATUS.json`) | `NotInitialized` | 15 (`EXIT_NOT_INITIALIZED`; §7, §13.4, §13.17) |
| Missing or empty `--reason` | `BadArgsError` | 2 (`EXIT_BAD_ARGS`; §7, §13.4, §13.17) |
| `needs_reclaim` is false (healthy `running`, or non-running: `queued`, `done`, `blocked`, `failed`) | `IllegalTransition` | 3 (`EXIT_ILLEGAL_TRANSITION`; §7, §13.4, §13.17, §13.19) |

When `needs_reclaim` is false, `Stage.reclaim()` MUST raise `IllegalTransition` and CLI MUST exit 3. Crucially, **no mutation** occurs to `STATUS.json`, `STATUS.md`, `events.jsonl`, or mirrors, and **no termination signals** are sent (even if `--kill` was passed).

#### 13.25.3 Execution sequence and atomic exclusive lock

The entire reclaim operation executes under a single exclusive filesystem lock (`StageStore.locked(exclusive=True)`, §8):

1. Exclusive lock acquired.
2. Read current status; evaluate `needs_reclaim`. If false, raise `IllegalTransition` without mutation.
3. If `--kill` is enabled (`kill=True`), best-effort terminate the recorded PID (§13.25.5).
4. **Step 1 (fail transition):**
   - Mutate status in-memory: `state` becomes `"failed"`, `error` becomes `{"reason": reason, "kind": "failed", "finished_at": <iso>}` (§13.9), `result` becomes `null`, `updated_at` bumped.
   - Write `STATUS.json`.
   - Append `failed` event to `events.jsonl` with `detail: {"reclaim": True, "keep_failed": keep_failed}` (§13.25.6).
   - Write `STATUS.md` mirror and status mirror (`.orch/STATUS.md`, §10) if enabled.
5. **Step 2 (clear to idle queued, unless `--keep-failed`):**
   - If `keep_failed=True`: sequence terminates here; return `failed` status payload with `heartbeat_age_seconds` (§13.25.4).
   - If `keep_failed=False` (default): immediately reset to idle queued under the same lock:
     - `state` becomes `"queued"`.
     - Identity and claim fields in `CLEAR_TERMINAL_IDLE_RESET_FIELDS` (§13.26) are reset to `null` (`stage_id`, `stage_name`, `session_id`, `pid`, `pid_token`, `started_at`, `heartbeat_at`, `heartbeat_note`), `artifacts` to `[]`, `meta` to `{}`.
     - Payload fields in `CLEAR_TERMINAL_ALWAYS_CLEARED_FIELDS` are set to `null` (`result`, `error`, `proof`).
     - `updated_at` bumped.
     - Write `STATUS.json`.
     - Append `clear_terminal` event to `events.jsonl` with `message: "cleared to idle queued"` and `detail: {"keep_stage": False, "reclaim": True}` (§13.25.6).
     - Write `STATUS.md` mirror.
     - Return idle `queued` status payload with `heartbeat_age_seconds`.
6. Exclusive lock released.

Orchestrators observing the events log see the uninterrupted audit trail: `failed` followed immediately by `clear_terminal`.

#### 13.25.4 `--keep-failed` stage identity preservation

When `--keep-failed` is passed (`Stage.reclaim(..., keep_failed=True)`):

- The sequence halts after Step 1 (`failed`).
- Stage state remains `"failed"`.
- Stage identity is preserved: `stage_id`, `stage_name`, `session_id`, `pid`, `pid_token`, `started_at`, `heartbeat_at`, `heartbeat_note`, `artifacts`, and `meta` all retain their pre-reclaim values (§4 rule 7, rule 8).
- Exactly ONE event (`failed`) is appended to `events.jsonl`.
- This enables watchdog/triage inspection of the dead/stale attempt before explicit reset via `clear-terminal` (§13.26).

#### 13.25.5 `--kill` process termination semantics

`--kill` (`kill=True`) defaults to `False`. When enabled:

- Signals are dispatched **after** the `needs_reclaim` guard passes and **before** the state transitions to `failed`. If the guard fails, no signals are ever sent.
- Targets only the recorded positive integer `pid` (not booleans, strings, or <= 0).
- If the PID is dead, missing, or unknown liveness, signal dispatch is skipped and reclaim proceeds.
- **Process identity verification (`pid_token`, §4 rule 7):** When a non-null `pid_token` is recorded in status, the process-start identity is re-read and verified against `pid_token` before **each** signal (`SIGTERM` and subsequent `SIGKILL`). If identity differs or cannot be read (indicating PID recycling), the signal is skipped and a warning is written to stderr.
- **Signal progression:** Send `SIGTERM`, wait up to 1.0s polling liveness every 50ms, then send `SIGKILL` only if still alive. On Windows, `SIGTERM` terminates; escalation falls back to `SIGTERM` with identity verification.
- **Resilience:** Any signal or OS error (e.g. `PermissionError`) emits a warning to stderr and MUST NOT abort reclaim. The fail-and-clear transition proceeds unconditionally.
- Concurrency guarantee: Guard, liveness probe, token verification, signaling, wait, and state transitions all execute under the single exclusive lock.

#### 13.25.6 Audit event shapes

A default `reclaim` emits two audit events in atomic sequence; `--keep-failed` emits only the first:

1. `failed` event:
   - `type`: `"failed"` (`EVENT_TYPES`, §13.5).
   - `state`: `"failed"`.
   - `message`: caller-provided `reason` string.
   - `detail`: carries exactly `RECLAIM_FAILED_DETAIL_KEYS`: `{"reclaim": True, "keep_failed": bool}`.
2. `clear_terminal` event (absent when `--keep-failed`):
   - `type`: `"clear_terminal"` (`EVENT_TYPES`, §13.5).
   - `state`: `"queued"`.
   - `stage_id`: `null`, `stage_name`: `null`.
   - `message`: exactly `CLEAR_TERMINAL_MESSAGE_IDLE` (`"cleared to idle queued"`, §13.26).
   - `detail`: carries exactly `RECLAIM_CLEAR_TERMINAL_DETAIL_KEYS`: `{"keep_stage": False, "reclaim": True}`.

Readers MUST tolerate unknown future additive keys on `detail` objects without failing (§13.1).

#### 13.25.7 Cross-links

- **§4 (States & transitions, rule 7 & rule 8, Idle vs Queued):** normative transition rules, single-lock execution, `--kill` process termination and token verification.
- **§5 (events.jsonl) + §13.5/§13.6:** audit events sequence (`failed` then `clear_terminal`).
- **§6 (CLI contract):** `stage-signal reclaim --reason TEXT [--keep-failed] [--kill] [--write-status-mirror]`.
- **§13.8 (Doctor warnings):** `DEAD_PID` and `STALE_HEARTBEAT` triggers for `needs_reclaim`.
- **§13.12 (States freeze):** `running` source state vs `failed` and `queued` target states.
- **§13.17 (Exceptions freeze):** `IllegalTransition` (exit 3), `BadArgsError` (exit 2), `NotInitialized` (exit 15).
- **§13.19 (Transition matrix freeze):** `(running, "reclaim") -> queued`, `(running, "reclaim --keep-failed") -> failed`.
- **§13.20 (Stage method surface):** `Stage.reclaim(reason, *, keep_failed=False, kill=False, write_status_mirror=None) -> dict[str, Any]`.
- **§13.26 (Clear-terminal freeze):** `CLEAR_TERMINAL_MESSAGE_IDLE`, `CLEAR_TERMINAL_IDLE_RESET_FIELDS`.

#### 13.25.8 Additive-only evolution policy

Under `schema_version: 1`, the reclaim fail-and-clear contract is strictly **additive-only** (§13.1):

- The frozen allowed source, detail key tuples, transition sequence, and error exit codes MUST NOT be removed, renamed, or change semantic meaning.
- No new event type is introduced: reclaim emits existing `failed` and `clear_terminal` event types (§13.5).
- New detail keys or flags MAY be added in minor or patch releases only as additional constants; existing frozen values MUST keep their exact values.
- Readers MUST tolerate unknown future detail keys on both events without failing.

### 13.26 Clear-terminal reset and audit contract freeze (`CLEAR_TERMINAL_ALLOWED_SOURCES`, `CLEAR_TERMINAL_IDLE_RESET_FIELDS`, `CLEAR_TERMINAL_KEEP_STAGE_PRESERVED_FIELDS`, `CLEAR_TERMINAL_ALWAYS_CLEARED_FIELDS`, `CLEAR_TERMINAL_DETAIL_KEYS`, `CLEAR_TERMINAL_MESSAGE_IDLE`, `CLEAR_TERMINAL_MESSAGE_KEEP_STAGE`)

`Stage.clear_terminal` / `stage-signal clear-terminal [--keep-stage]` (§4 rule 8, §6, §13.20) resets a terminal or queued stage back to `queued`. Under `schema_version: 1`, the allowed sources, the default idle reset field set, the `--keep-stage` preserved-vs-cleared field set, and the `clear_terminal` audit event shape are frozen so orchestrators can abandon a parked queued stage or reset a finished attempt to idle without scraping human text. The `clear_terminal` event type itself is frozen in §13.5 and the record keys in §13.6; the allowed edges are frozen in §13.19.

#### 13.26.1 Frozen constants and exact values

The single sources of truth are defined in `stage_signal.constants` and exported from `stage_signal` and `__all__`:

```python
CLEAR_TERMINAL_ALLOWED_SOURCES = ("done", "blocked", "failed", "queued")

CLEAR_TERMINAL_IDLE_RESET_FIELDS = (
    "stage_id",
    "stage_name",
    "session_id",
    "pid",
    "pid_token",
    "started_at",
    "heartbeat_at",
    "heartbeat_note",
    "artifacts",
    "meta",
)

CLEAR_TERMINAL_KEEP_STAGE_PRESERVED_FIELDS = (
    "stage_id",
    "stage_name",
    "session_id",
    "pid",
    "pid_token",
    "started_at",
    "heartbeat_at",
    "heartbeat_note",
    "artifacts",
    "meta",
)

CLEAR_TERMINAL_ALWAYS_CLEARED_FIELDS = ("result", "error", "proof")

CLEAR_TERMINAL_DETAIL_KEYS = ("keep_stage",)

CLEAR_TERMINAL_MESSAGE_IDLE = "cleared to idle queued"
CLEAR_TERMINAL_MESSAGE_KEEP_STAGE = "cleared to queued"
```

`CLEAR_TERMINAL_ALLOWED_SOURCES` lists the legal source states in lifecycle order (`done`, `blocked`, `failed`, then the `queued` abandon path); it MUST equal `set(allowed_source_states("clear-terminal"))` (§13.19). `CLEAR_TERMINAL_KEEP_STAGE_PRESERVED_FIELDS` intentionally enumerates the same ten fields as `CLEAR_TERMINAL_IDLE_RESET_FIELDS`: the default path resets them to idle, while `--keep-stage` preserves them (§13.26.4).

#### 13.26.2 Allowed sources and the `running` guard

`clear-terminal` is permitted from each terminal state (`done`, `blocked`, `failed`; §13.12) and from `queued` — both named queued (abandon a parked stage) and idle queued (no-op reset that still appends an audit event). The target state is always `queued` (§13.19):

| Precondition failure | Library | CLI exit |
|----------------------|---------|----------|
| Stage not initialized (missing dir/STATUS) | `NotInitialized` | 15 (`EXIT_NOT_INITIALIZED`; §7, §13.4, §13.17) |
| Current state is `running` | `IllegalTransition` | 3 (`EXIT_ILLEGAL_TRANSITION`; §7, §13.4, §13.17) |

From `running`, `clear-terminal` is strictly illegal and MUST raise `IllegalTransition` (exit 3) with no mutation of STATUS, events, or mirrors. A stuck running stage MUST first move via `reclaim --reason TEXT` (or `fail --reason TEXT --if-needs-reclaim` / `--if-dead-pid`) per §4 rules 6–7. No child process, signal, or mirror side effect occurs on precondition failure.

#### 13.26.3 Default idle reset field set

By default (without `--keep-stage`), `clear-terminal` resets to a true idle `queued` stage (§4 "Idle vs. Queued"):

- `state` becomes `"queued"`.
- Every field in `CLEAR_TERMINAL_IDLE_RESET_FIELDS` is reset: `stage_id`, `stage_name`, `session_id`, `pid`, `pid_token`, `started_at`, `heartbeat_at`, and `heartbeat_note` become `null`; `artifacts` becomes `[]`; `meta` becomes `{}`.
- Every field in `CLEAR_TERMINAL_ALWAYS_CLEARED_FIELDS` is cleared: `result`, `error`, and `proof` become `null`.
- `updated_at` is bumped by the standard mutation path (§4 rule 9).
- Preserved unchanged in both modes: `attempt`, `notes`, `model`, `variant`, `repo_path`, `git_branch`, and `git_head`.

An idle `queued` stage therefore reads `state: queued` with `stage_id`/`stage_name` both `null`, which orchestrators polling `status` observe as `queued - (attempt N)` with no pending work (§4).

#### 13.26.4 `--keep-stage` preserved vs cleared field set

With `--keep-stage` (`Stage.clear_terminal(keep_stage=True)`), the stage re-queues under the same identity instead of returning to idle:

- `state` still becomes `"queued"`.
- Every field in `CLEAR_TERMINAL_KEEP_STAGE_PRESERVED_FIELDS` keeps its pre-clear value: `stage_id`, `stage_name`, `session_id`, `pid`, `pid_token`, `started_at`, `heartbeat_at`, `heartbeat_note`, `artifacts`, and `meta` are all preserved (so `pid`/`pid_token` claim identity survives, matching §4 rule 8).
- Every field in `CLEAR_TERMINAL_ALWAYS_CLEARED_FIELDS` is still cleared: `result`, `error`, and `proof` become `null` even with `--keep-stage`.
- The §13.26.3 preserved-in-both-modes set (`attempt`, `notes`, `model`, `variant`, `repo_path`, `git_branch`, `git_head`) is likewise preserved.
- `updated_at` is bumped by the standard mutation path.

`reclaim --keep-failed` (owned by §13.25) likewise preserves stage identity; only the direct `clear-terminal` path is frozen here.

#### 13.26.5 Audit event shape

Each `clear-terminal` call appends exactly one `clear_terminal` event (§5; no new event type is introduced):

- `type` is exactly `"clear_terminal"` (a member of `EVENT_TYPES`; §13.5) with the standard record keys (`EVENT_RECORD_KEYS`; §13.6).
- `message` is exactly `CLEAR_TERMINAL_MESSAGE_IDLE` (`"cleared to idle queued"`) by default, or exactly `CLEAR_TERMINAL_MESSAGE_KEEP_STAGE` (`"cleared to queued"`) with `--keep-stage` — byte-for-byte, no affixes.
- `detail` carries exactly the `CLEAR_TERMINAL_DETAIL_KEYS`: `{"keep_stage": bool}` reflecting the flag value (`false` by default, `true` with `--keep-stage`).
- The `clear_terminal` event emitted as the second half of a default `reclaim` (owned by §13.25) instead carries `detail: {"keep_stage": false, "reclaim": true}`; readers MUST tolerate that additive `reclaim` key without failing (§13.1).

Readers MUST tolerate additive unknown keys on the `clear_terminal` `detail` object without failing (§13.1).

#### 13.26.6 Cross-links

- **§4 (States & transitions, rule 8, Idle vs. Queued):** normative transition rules, the queued abandon path, and the idle-vs-named queued orchestrator contract.
- **§5 (events.jsonl) + §13.5/§13.6:** the `clear_terminal` event type and required record keys; audit-trail reads via `events`.
- **§6 (CLI contract):** `stage-signal clear-terminal [--keep-stage]` usage line and the `--keep-stage` flag.
- **§13.12 (states freeze):** `done`/`blocked`/`failed` terminal partition vs `queued`/`running`.
- **§13.19 (transition matrix freeze):** the eight frozen `clear-terminal`/`clear_terminal` edges and the `running` guard.
- **§13.20 (Stage method surface freeze):** `clear_terminal(*, keep_stage=False) -> dict[str, Any]` signature and CLI equivalence.

#### 13.26.7 Additive-only evolution policy

Under `schema_version: 1`, the clear-terminal reset and audit contract is strictly **additive-only** (§13.1):

- The frozen allowed sources, idle reset fields, `--keep-stage` preserved fields, always-cleared fields, detail keys, and message strings MUST NOT be removed, renamed, reworded, or change semantic meaning.
- No new event type is introduced for clearing: the audit record stays a `clear_terminal` event (§13.5).
- New detail keys or modes MAY be added in minor or patch releases only as additional constants; existing frozen values MUST keep their exact values.
- Readers MUST tolerate unknown future `clear_terminal` detail keys and unknown future message strings without failing.

### 13.27 Heartbeat liveness contract freeze (`HEARTBEAT_ALLOWED_SOURCES`, `HEARTBEAT_DETAIL_KEYS`)

`Stage.heartbeat` / `stage-signal heartbeat [--note TEXT]` (§4 rule 3, §6, §13.20) bumps the running liveness timestamp without changing lifecycle state. Under `schema_version: 1`, the allowed source, the `heartbeat_at` / `heartbeat_note` omit-vs-set semantics, the `heartbeat` audit event shape, and the running-only age rule are frozen so orchestrators can poll `status` for freshness and branch on `heartbeat_age_seconds` / `needs_reclaim` without scraping human text. The `heartbeat` event type itself is frozen in §13.5 and the record keys in §13.6; the allowed edge is frozen in §13.19.

#### 13.27.1 Frozen constants and exact values

The single sources of truth are defined in `stage_signal.constants` and exported from `stage_signal` and `__all__`:

```python
HEARTBEAT_ALLOWED_SOURCES = ("running",)

HEARTBEAT_DETAIL_KEYS: tuple[str, ...] = ()
```

`HEARTBEAT_ALLOWED_SOURCES` lists the sole legal source state; it MUST equal `allowed_source_states("heartbeat")` (§13.19). `HEARTBEAT_DETAIL_KEYS` is intentionally empty: a direct heartbeat audit record carries no detail extras (`detail == {}`, §13.27.4).

#### 13.27.2 Allowed source and the non-running guard

`heartbeat` is permitted only when `state == "running"` (§4 rule 3, §13.12, §13.19). The target state is always `running` (no lifecycle transition):

| Precondition failure | Library | CLI exit |
|----------------------|---------|----------|
| Stage not initialized (missing dir/STATUS) | `NotInitialized` | 15 (`EXIT_NOT_INITIALIZED`; §7, §13.4, §13.17) |
| Current state is `queued`, `done`, `blocked`, or `failed` | `IllegalTransition` | 3 (`EXIT_ILLEGAL_TRANSITION`; §7, §13.4, §13.17) |

From any non-running state, `heartbeat` is strictly illegal and MUST raise `IllegalTransition` (exit 3) with no mutation of STATUS, events, or mirrors. No child process, signal, or mirror side effect occurs on precondition failure. A stuck running stage keeps heartbeating normally; staleness never auto-mutates (§4 Staleness policy).

#### 13.27.3 `heartbeat_at` / `heartbeat_note` omit-vs-set semantics

On success, from the exact implementation in `Stage.heartbeat` (`src/stage_signal/stage.py`):

- `heartbeat_at` is always bumped to the current ISO-8601 timestamp (`now_iso()`).
- `updated_at` is bumped by the standard mutation path (§4 rule 9).
- `state`, `stage_id`, `stage_name`, `attempt`, `session_id`, `pid`, `pid_token`, and all other STATUS fields are preserved unchanged.
- `heartbeat_note` follows strict omit-vs-set: `if note is not None: current["heartbeat_note"] = note`.
  - Omitted (`Stage.heartbeat()` / `Stage.heartbeat(note=None)` / CLI `stage-signal heartbeat` without `--note`, whose argparse default is `None`): the previous `heartbeat_note` value is preserved byte-for-byte (including a previous `null` or a previous string).
  - Set (`note=<str>`, including the empty string `""`): `heartbeat_note` is overwritten with exactly that string, even when empty. There is no empty-means-clear vs empty-means-keep distinction; only `None` preserves.
- `start` resets `heartbeat_note` to `null` and bumps `heartbeat_at` (§4 rule 2); `clear-terminal` default idle reset clears both to `null` while `--keep-stage` preserves both (§13.26). Those paths are owned by their respective sections, not changed here.

#### 13.27.4 Audit event shape

Each successful `heartbeat` call appends exactly one `heartbeat` event (§5; no new event type is introduced):

- `type` is exactly `"heartbeat"` (a member of `EVENT_TYPES`; §13.5) with the standard record keys (`EVENT_RECORD_KEYS`; §13.6). `state` is `"running"` and `stage_id` / `stage_name` / `attempt` reflect the post-mutation STATUS.
- `message` is the note passthrough: `None` when the note was omitted, otherwise exactly the supplied note string (including `""` when set explicitly) — byte-for-byte, no affixes.
- `detail` is exactly `{}`: `set(detail.keys()) == set(HEARTBEAT_DETAIL_KEYS)` (empty). The supervise child-PID adoption record (owned by §13.24) is also a `heartbeat` event but carries the frozen adoption message (`"adopted child pid <N>"`) and `SUPERVISE_ADOPT_DETAIL_KEYS`; readers distinguish direct heartbeats (empty detail) from adoption heartbeats (adoption detail keys) by the detail shape.

Readers MUST tolerate additive unknown keys on the `heartbeat` `detail` object without failing (§13.1).

#### 13.27.5 Age only while running

Freshness is observed, never mutated, via `heartbeat_age_seconds` and the human `status` line (§3, §6, §13.3.1):

- `Stage.status()` / `status --json` reports `heartbeat_age_seconds` as a float `>= 0` (elapsed seconds since `heartbeat_at`) only when `state == "running"` and `heartbeat_at` parses as ISO-8601; otherwise it is `null` — including `done`, `blocked`, `failed`, and `queued` even when `heartbeat_at` remains recorded, and including unparseable or missing `heartbeat_at`.
- Human `status` prints `heartbeat: <ISO> (age Ns)` only when `state == "running"` with a recorded timestamp and a non-null age; otherwise it prints `heartbeat: <ISO>` with no age suffix.
- `doctor` / `Stage.diagnose()` staleness evaluation (`STALE_HEARTBEAT` vs `DEFAULT_STALE_THRESHOLD`, §13.8, §13.14) and `supervise --every` auto-heartbeating (§6, §13.14, §13.24) consume the same `heartbeat_at` clock but are owned by their respective sections; this section freezes only that age is exposed exclusively while running.

#### 13.27.6 Cross-links

- **§4 rule 3 (States & transitions):** normative `heartbeat [--note]` allowed-only-from-`running` rule, the `updated_at` bump rule (§4 rule 9), and the never-auto-mutate staleness policy.
- **§5 (events.jsonl) + §13.5/§13.6:** the `heartbeat` event type and required record keys; audit-trail reads via `events`.
- **§6 (CLI contract):** `stage-signal heartbeat [--note TEXT]` usage line; `status` human/JSON age display; `supervise` auto-heartbeat (`--every`, default `SUPERVISE_DEFAULT_EVERY`) which reuses this same heartbeat mutation while the child is alive.
- **§13.12 (states freeze):** `running` as the sole non-terminal live state vs `queued` and terminal `done`/`blocked`/`failed`.
- **§13.14 (env/timing defaults):** `DEFAULT_STALE_THRESHOLD` (300.0) consumed by `doctor` staleness, `SUPERVISE_DEFAULT_EVERY` (60.0) consumed by supervise auto-heartbeat; neither default is changed here.
- **§13.19 (transition matrix freeze):** the single frozen `(running, "heartbeat") -> running` edge and the non-running guard.
- **§13.20 (Stage method surface freeze):** `heartbeat(note=None) -> dict[str, Any]` signature and CLI equivalence.

#### 13.27.7 Additive-only evolution policy

Under `schema_version: 1`, the heartbeat liveness contract is strictly **additive-only** (§13.1):

- The frozen allowed source, the always-bump-`heartbeat_at` rule, the `None`-means-preserve omit-vs-set rule, the `message`-passthrough / empty-`detail` audit shape, and the age-only-while-running rule MUST NOT be removed, renamed, reworded, or change semantic meaning.
- No new event type is introduced for heartbeating: the audit record stays a `heartbeat` event (§13.5).
- New heartbeat detail keys or note modes MAY be added in minor or patch releases only as additional constants; existing frozen values MUST keep their exact values.
- Readers MUST tolerate unknown future `heartbeat` detail keys and unknown future note strings without failing.

