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

The canonical stage lifecycle states and terminal partition are frozen in §13.12 (`STATES`, `TERMINAL_STATES`).

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

