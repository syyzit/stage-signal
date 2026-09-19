# Changelog — stage-signal

All notable changes to this project are documented here.
Format follows Keep a Changelog (loosely); versioning is SemVer.
See `docs/RELEASE.md` for the release procedure.

## [Unreleased]

- Docs: streamline SPEC §§1–12 into a concise architecture overview delegating all normative assertions to §13 freezes under `schema_version: 1` (#201).

- Docs: demote dogfood harness scripts and dual-CLI guides to `examples/dogfood/` with an explanatory README clarifying they are external harnesses rather than published product, add lean Caller Guide (`docs/CALLER.md`) covering synchronous wait, health watchdog, and agent wrapper loops, and purge internal harness references from general docs (#199).

- Docs: add 1.0 readiness roadmap (`docs/ROADMAP-1.0.md`) mapping all frozen §13.1–§13.42 sections vs public CLI/API surface, confirming zero normative gaps, detailing redundant prose between SPEC §§1–12 and §13, establishing a cut-list for dogfood harness scripts/docs, and defining the 1.0 "done" bar (#193).

- README: mention Claude Code as another pluggable agent CLI in the driving-agents table (#196).

- README: reformat the contract scan (exit codes, wait/status/doctor, reclaim) into short sections and a table for humans; SPEC remains normative (#194).

- Docs: demote orchestrator-watchdog into dogfood (`examples/dogfood/orchestrator-watchdog.sh`), updating docs, dogfood guides, and regression tests to leave only canonical acceptance smokes and CI workflows in root `examples/` (#202).

## [0.1.7] — 2026-09-19

Releases the soak of SPEC freezes §13.25–§13.42 plus docs/tests landed since 0.1.6 (PID liveness/`needs_reclaim`, locking, proof gate, observers, dual-CLI harness labeling, and `done --git-head` inherit regressions). Packaging-only; no new runtime features.


- Froze PID liveness probe and `needs_reclaim` derivation in SPEC §13.42 with no new exported constants (private `_is_pid_alive` / `_reclaim_diagnostics` reusing the already-frozen `WARNING_CODES`/`WARNING_CODE_*`/`WARNING_KEYS`, `DEFAULT_STALE_THRESHOLD`, and `STATE_RUNNING`), documenting the tri-state probe (`True` alive / `False` dead / `None` unknown) with invalid-input mapping and POSIX `os.kill(pid, 0)` / Windows `OpenProcess`/`GetExitCodeProcess` backends, the exact `DEAD_PID` / `STALE_HEARTBEAT` / `UNPARSEABLE_HEARTBEAT` emission conditions (running-only; `UNPARSEABLE_HEARTBEAT` advisory-only), the `needs_reclaim == (state == running and (DEAD_PID or STALE_HEARTBEAT))` fold excluding unparseable, the `stale_after=None`-disables-heartbeat rule, the probe-never-signals guarantee (signal `0` / read-only queries; `SIGTERM`/`SIGKILL` only via `reclaim --kill`), the frozen message prefixes and `detail` shapes, cross-linking §13.8/§13.12/§13.14/§13.22/§13.23/§13.25/§13.31/§13.35/§13.37/§13.38, leaving `PUBLIC_EXPORTS` at 134 symbols, and guaranteeing additive-only evolution under `schema_version: 1` (#178).

- Labeled the dual-CLI orchestrator guides (`docs/examples/orchestrator.md`, `examples/cli-orchestrator-loop.md`, plus a one-line README pointer) as a dogfood harness example, clarifying the published product is only the thin `.stage-signal/` lifecycle contract (#188).
- Added CLI regression tests in `tests/test_cli.py` locking that `done` without `--git-head` inherits the `git_head` recorded at `start` (SPEC §13.30.3), plus the explicit-`--git-head` override path (#186).

- Refreshed README Status to name the SPEC freeze coverage through §13.41 (status/events/doctor/wait observers in §13.35–§13.38, `.orch` mirror in §13.39, concurrency/locking in §13.40, proof gate in §13.41) and to confirm the `0.1.6` soak with aligned action (`@v0.1.6`) and PyPI (`"0.1.6"`) pins, with no version bump (#184).

- Fixed sample agent prompts in `examples/cli-orchestrator-loop.md` so `done` passes `--git-head $(git rev-parse HEAD)` after commits (omitting it inherits the start SHA per SPEC §13.30.3), and annotated non-committing smoke paths in `examples/orchestrator-smoke.sh`, `examples/queue-orchestrator-smoke.sh`, and `examples/multi-cli-loop.sh` (mock) that the inherit applies (#182).

- Documented in README that `done` without `--git-head` inherits the `git_head` recorded at `start` (SPEC §13.30.3), that agents/orchestrators committing mid-stage SHOULD pass `--git-head $(git rev-parse HEAD)`, and that `main` carries SPEC contract freezes through §13.41 while the published package remains soaking at `0.1.6` with no version bump (#180).
- Froze concurrency, atomicity, and `StageStore.locked` contract in SPEC §13.40 with no new exported constants (reusing the already-frozen `LOCKS_DIRNAME`, `LOCK_FILENAME`, `STATUS_FILENAME`, `EVENTS_FILENAME`, and `StageStore`), documenting same-process thread serialization via `_THREAD_LOCKS`, POSIX exclusive `fcntl.flock(LOCK_EX)` for mutations and shared `fcntl.flock(LOCK_SH)` for reads with fallback to exclusive, Windows stdlib `msvcrt.locking` on byte 0 of `locks/stage.lock` with non-blocking retry loop (≤10s deadline) and shared-to-exclusive fallback, best-effort no-op locking on platforms lacking both primitives, atomic `STATUS.json` publication via same-directory tempfile and `os.replace`, durability for `events.jsonl` append under lock with `flush` and `os.fsync`, torn-read retry-once before reporting `CorruptStatusError` (exit 1), and fail-closed corrupt status/event handling, cross-linking §2/§5/§8/§13.13/§13.17/§13.21, leaving `PUBLIC_EXPORTS` at 134 symbols, and guaranteeing additive-only evolution under `schema_version: 1` (#175).
- Froze proof composition gate in SPEC §13.41 with no new exported constants (record-only `--proof-ref` vs `--require-proof` verify-before-mutate reusing the already-frozen `PROOF_KEYS`, `PROOF_VERIFIED_VALUES`, `ENV_PROOF_REF`/`ENV_VARS`, `EXIT_ILLEGAL_TRANSITION`, `IllegalTransition`, and `verify_proof`), documenting the explicit-flag-beats-environment resolution with falsy-falls-back semantics, the file gate (`verified="file"`, non-empty file wins without consulting the verifier) tried before the external `agent-done-or-not verify --ref R` gate (`verified="verify"`), the fail-closed refusals (missing ref, empty/unreadable file, verifier non-zero or launch error, neither file nor binary) all raising `IllegalTransition` (exit 3), the verify-before-any-mutation atomicity with zero writes to `STATUS.json`/`events.jsonl`/mirrors on refusal, reserving §13.40 for the parallel locking lane (#175), cross-linking §4/§7/§9/§13.4/§13.9/§13.10/§13.14/§13.17/§13.21/§13.30, leaving `PUBLIC_EXPORTS` at 134 symbols, and guaranteeing additive-only evolution under `schema_version: 1` (#176).
- Froze wait observer and poll loop contract in SPEC §13.38 with no new exported constants (pure polling observer reusing the already-frozen `WAIT_CHOICES`, `WAIT_DEFAULT_POLL`, `WAIT_DEFAULT_TIMEOUT`, `WAIT_JSON_KEYS`, `WAIT_OUTCOMES`/`WAIT_OUTCOME_*`, `WAIT_WANT_NEEDS_RECLAIM`, `WaitTimeout`, `EXIT_WAIT_TIMEOUT`, `STATE_EXIT_CODES`/`state_exit_code`, `want_matches`, and `wait_condition_met`), documenting the shared-lock non-mutating poll loop, positive timeout/poll and target choice argument validation, mutual exclusivity of `--needs-reclaim` vs non-default `--state` (exit 2), library `WaitTimeout` (with `last_status`) vs CLI exit 14, guaranteed 11-key `WAIT_JSON_KEYS` payload across all outcomes (`met`, `mismatch`, `timeout`), human stdout/stderr message shapes, observer exit code table via `STATE_EXIT_CODES` with fail-closed reclaim mismatch exit 1, cross-linking §6/§7/§13.3.3/§13.4/§13.11/§13.14/§13.16/§13.17/§13.20/§13.21/§13.23/§13.35, leaving `PUBLIC_EXPORTS` at 134 symbols, and guaranteeing additive-only evolution under `schema_version: 1` (#171).
- Froze optional `.orch` mirror write contract in SPEC §13.39 with no new exported constants (best-effort `write_status_mirror` reusing the already-frozen `DEFAULT_MIRROR_DIRNAME`, `ENV_STATUS_MIRROR`/`ENV_VARS`), documenting the six honoring commands (`start`/`done`/`blocked`/`fail`/`reclaim`/`supervise`), the tri-state `None`/`True`/`False` opt-in with the exact `"1"`/`"true"`/`"yes"`/`"on"` env set, repo-root resolution (explicit `repo_root` > `.stage-signal`-parent > `cwd`), the 7-line minimal `.orch/STATUS.md` content with `source:` provenance, DONE-on-`done`-only, the reclaim-mirrors-`failed`-only point and supervise passthrough, and the never-raises warn-on-`stderr` guarantee, cross-linking §10/§13.13/§13.14/§13.18/§13.20/§13.21, leaving `PUBLIC_EXPORTS` at 134 symbols, and guaranteeing additive-only evolution under `schema_version: 1` (#172).

- Froze events read and tail contract in SPEC §13.36 with no new exported constants (pure audit log observer reusing the already-frozen `EVENT_RECORD_KEYS`, `EVENT_TYPES`, `EVENTS_DEFAULT_TAIL`, and `EVENTS_FILENAME`), documenting the shared-lock non-mutating read with detached deep-copy records, chronological oldest→newest ordering of the selected tail, filter-before-tail semantics, default tail count of 20 (CLI) vs all (library) with 0-means-all, guaranteed `EVENT_RECORD_KEYS` return shape, `NotInitialized` (exit 15) / corrupt (exit 1) / bad arguments (exit 2) preconditions with no stdout payload, human one-line output shape vs `--json` array shape with exit 0 on success, cross-linking §5/§6/§13.5/§13.6/§13.14/§13.17/§13.20/§13.21, leaving `PUBLIC_EXPORTS` at 134 symbols, and guaranteeing additive-only evolution under `schema_version: 1` (#166).

- Froze doctor/diagnose read contract in SPEC §13.37 with no new exported constants (pure observer reusing the already-frozen `DOCTOR_JSON_KEYS`, `WARNING_KEYS`/`WARNING_CODES`/`WARNING_CODE_*`, `DOCTOR_SUMMARY_RECLAIM_NEEDED`/`DOCTOR_SUMMARY_OK_FORMAT`/`doctor_summary_ok`, and `DEFAULT_STALE_THRESHOLD`), documenting the shared-lock non-mutating read with detached deep-copy snapshots, `needs_reclaim` agreement with `status`/`wait --needs-reclaim` at defaults plus `stale_after`/`--stale-after` overrides, problems-vs-warnings-vs-summary rules, human `PROBLEM:`/`WARNING:`/summary rendering vs single-JSON-object output with `--format` equivalence, and the 0/1/2/10 exit table (`--exit-reclaim` wins over problems), cross-linking §6/§13.3/§13.8/§13.12/§13.14/§13.20/§13.21/§13.22/§13.35, leaving `PUBLIC_EXPORTS` at 134 symbols, and guaranteeing additive-only evolution under `schema_version: 1` (#168).

- Froze status read snapshot contract in SPEC §13.35 with no new exported constants (pure observer reusing the already-frozen `STATUS_JSON_KEYS`, `STATE_EXIT_CODES`/`state_exit_code`, `NotInitialized`/`EXIT_NOT_INITIALIZED`, and `DEFAULT_STALE_THRESHOLD`), documenting the shared-lock non-mutating read with detached deep-copy snapshots, derived `needs_reclaim` (same `DEAD_PID`/`STALE_HEARTBEAT` detection as doctor at the default threshold) and running-only `heartbeat_age_seconds` fields, `NotInitialized` (exit 15) / corrupt (exit 1) preconditions with no stdout payload, human one-line plus `updated`/`heartbeat`/`result`/`error` output shape vs `--json` object shape with state-reflecting exit codes, cross-linking §3/§6/§13.2/§13.8/§13.12/§13.14/§13.16/§13.17/§13.20/§13.21/§13.27, leaving `PUBLIC_EXPORTS` at 134 symbols, and guaranteeing additive-only evolution under `schema_version: 1` (#165).

- Froze init bootstrap contract in SPEC §13.34 via exported `INIT_DETAIL_KEYS` (empty — direct init audit carries `detail: {}` with `message` as the resolved project name) and `INIT_IDLE_STATUS_FIELDS` (twenty-four canonical initial STATUS fields including all 23 `STATUS_REQUIRED_KEYS` plus `pid_token: null`), documenting idempotent create-vs-preserve semantics across all states, loud `CorruptStatusError` on corrupt STATUS (exit 1), 3-tier project inference precedence (`--project` > `$STAGE_SIGNAL_PROJECT` > directory fallback), initial `state: "queued"`, `attempt: 1`, null identity/vcs/claim/terminal fields, empty `artifacts`/`notes`/`meta` collections, cross-linking §3/§4/§5/§6/§13.3/§13.12/§13.17/§13.19/§13.20/§13.26, updating `PUBLIC_EXPORTS` to 134 symbols, and guaranteeing additive-only evolution under `schema_version: 1` (#162).
- Froze blocked terminal contract in SPEC §13.32 via exported `BLOCKED_ALLOWED_SOURCES` (`"queued"`, `"running"`, `"blocked"`; `done`/`failed` stay exit 3) and `BLOCKED_DETAIL_KEYS` (empty — direct blocked audit carries `detail: {}` with `message` as verbatim reason passthrough), documenting non-empty reason validation (`BadArgsError` / exit 2, stored verbatim), `ERROR_KEYS`-matching `error` object with `kind: blocked` (cross-linked to §13.9, not redefined) and `result: null`, cross-linking §4/§5/§6/§13.9/§13.12/§13.17/§13.19/§13.20, updating `PUBLIC_EXPORTS` to 132 symbols, and guaranteeing additive-only evolution under `schema_version: 1` (#159).
- Froze done terminal contract in SPEC §13.30 via exported `DONE_ALLOWED_SOURCES` (`"queued"`, `"running"`, `"done"`; blocked/failed plain done stay exit 3), `DONE_ACCEPT_FAILURE_ALLOWED_SOURCES` (`"failed"` only; non-failed stay exit 3), and `DONE_DETAIL_KEYS` (`"proof"`, `"git_head"`, `"accepted_failure"`), documenting exact result payload shape matching `RESULT_KEYS` (`"summary"`, `"git_head"`, `"finished_at"`), additive `"accepted_failure": true` key on `--accept-failure`, proof verification gating via `verify_proof` before mutation under lock cross-linked to §13.10, clearing `error` to `null` on success, audit done event message passthrough and detail keys, cross-linking §4/§5/§6/§13.9/§13.10/§13.12/§13.19/§13.20, updating `PUBLIC_EXPORTS` to 124 symbols, and guaranteeing additive-only evolution under `schema_version: 1` (#155).
- Froze fail terminal contract in SPEC §13.31 via exported `FAIL_ALLOWED_SOURCES` (plain fail from `queued`/`running`/`failed`; `done`/`blocked` stay exit 3), `FAIL_IF_DEAD_PID_ALLOWED_SOURCES` (same sources; liveness gate only from `running` requiring a valid positive pid confirmed dead, else exit 3), `FAIL_IF_NEEDS_RECLAIM_ALLOWED_SOURCES` (`running` only; refuses with `IllegalTransition` / exit 3 when `needs_reclaim` is false), and `FAIL_DETAIL_KEYS` (empty — direct fail audit carries `detail: {}` with `message` as verbatim reason passthrough), documenting non-empty reason validation (`BadArgsError` / exit 2, stored verbatim), `--if-dead-pid` / `--if-needs-reclaim` mutual exclusion (exit 2), `ERROR_KEYS`-matching `error` object with `kind: failed` (cross-linked to §13.9, not redefined) and `result: null`, cross-linking §4/§5/§6/§13.12/§13.17/§13.19/§13.20, updating `PUBLIC_EXPORTS` to 128 symbols, and guaranteeing additive-only evolution under `schema_version: 1` (#156).
- Froze start claim-running contract in SPEC §13.33 via exported `START_ALLOWED_SOURCES` (all five states — `start` never refuses on state grounds, target always `running`) and `START_DETAIL_KEYS` (`"stage_id"`, `"session_id"`, `"pid"`, `"model"`, `"variant"` — raw call args, so `detail["pid"]` is `null` when `--pid` is omitted even though STATUS records the resolved claimant), documenting non-empty stage validation (`BadArgsError` / exit 2, stored stripped), `stage_id`-defaults-to-stripped-name vs verbatim-explicit-id series rule, `pid`-as-int-or-`None`-means-self with `os.getpid()` resolution, best-effort per-platform `pid_token` capture replaced on every claim (consumed by `doctor`/`fail --if-dead-pid`/`reclaim --kill`, owned by §13.8/§13.25/§13.31, not re-frozen), attempt bump-vs-reset, conditional `artifacts` clear vs `notes` preservation vs `meta` replacement, `result`/`error`/`proof` clearing to `null`, stripped-name message passthrough, cross-linking §3/§4/§5/§6/§13.12/§13.14/§13.19/§13.20/§13.25, updating `PUBLIC_EXPORTS` to 130 symbols, and guaranteeing additive-only evolution under `schema_version: 1` (#160).

- Froze note progress appending and MAX_NOTES cap contract in SPEC §13.28 via exported `NOTE_ALLOWED_SOURCES` (`"running"` only; queued/terminal stay exit 3) and `NOTE_DETAIL_KEYS` (empty — direct note audit carries `detail: {}` with `message` as verbatim note text), documenting exact empty-text / whitespace validation semantics (`BadArgsError` / exit 2 on empty or whitespace-only strings, whitespace preserved on valid text), entry dictionary creation matching `NOTE_ENTRY_KEYS` (`"text"`, `"added_at"`), FIFO truncation capped at `MAX_NOTES` (200), lifecycle preservation across retries and `clear-terminal` resets, cross-linking §3/§4/§5/§6/§13.7/§13.12/§13.14/§13.20, updating `PUBLIC_EXPORTS` to 121 symbols, and guaranteeing additive-only evolution under `schema_version: 1` (#151).

- Froze artifact add contract in SPEC §13.29 via exported `ARTIFACT_ALLOWED_SOURCES` (`running` only; queued/terminal stay exit 3) and `ARTIFACT_DETAIL_KEYS` (`path`, `label`), documenting non-empty path validation (`BadArgsError` / exit 2), omit-vs-set label (`None` records `null`, explicit string including `""` stored exactly), `ARTIFACT_ENTRY_KEYS`-matching appends, path-passthrough audit events, heartbeat preservation with start/clear-terminal rules cross-linked only, cross-linking §3/§4/§5/§6/§13.7/§13.12/§13.20/§13.26, updating `PUBLIC_EXPORTS` to 119 symbols, and guaranteeing additive-only evolution under `schema_version: 1` (#152).

- Froze reclaim fail-and-clear contract in SPEC §13.25 via exported `RECLAIM_ALLOWED_SOURCES` (`"running"`), `RECLAIM_FAILED_DETAIL_KEYS` (`"reclaim"`, `"keep_failed"`), and `RECLAIM_CLEAR_TERMINAL_DETAIL_KEYS` (`"keep_stage"`, `"reclaim"`), defining the `needs_reclaim` guard (`IllegalTransition` / exit 3 when false), the atomic fail-and-clear sequence under exclusive lock, `--keep-failed` identity preservation, and `--kill` best-effort process signaling with process-start identity verification, cross-linking §4 rule 7/rule 8, §5, §6, §13.8, §13.12, §13.17, §13.19, §13.20, and §13.26, updating `PUBLIC_EXPORTS` to 117 symbols, and guaranteeing additive-only evolution under `schema_version: 1` (#145).

- Froze heartbeat liveness contract in SPEC §13.27 via exported `HEARTBEAT_ALLOWED_SOURCES` (`running` only; queued/terminal stay exit 3) and `HEARTBEAT_DETAIL_KEYS` (empty — direct heartbeat audit carries `detail: {}` with `message` as the note passthrough), documenting exact omit-vs-set behavior (`note=None` preserves `heartbeat_note`, explicit string including `""` overwrites), always-bump `heartbeat_at`, running-only `heartbeat_age_seconds`, cross-linking §4/§5/§6/§13.5/§13.12/§13.14/§13.20, updating `PUBLIC_EXPORTS` to 114 symbols, and guaranteeing additive-only evolution under `schema_version: 1` (#148).

- Froze clear-terminal reset and audit contract in SPEC §13.26 via exported `CLEAR_TERMINAL_ALLOWED_SOURCES` (`done`, `blocked`, `failed`, `queued`; `running` stays exit 3), `CLEAR_TERMINAL_IDLE_RESET_FIELDS` (ten identity/claim fields reset to idle), `CLEAR_TERMINAL_KEEP_STAGE_PRESERVED_FIELDS` (same ten preserved with `--keep-stage`), `CLEAR_TERMINAL_ALWAYS_CLEARED_FIELDS` (`result`, `error`, `proof`), `CLEAR_TERMINAL_DETAIL_KEYS` (`keep_stage`), and exact audit messages (`CLEAR_TERMINAL_MESSAGE_IDLE`, `CLEAR_TERMINAL_MESSAGE_KEEP_STAGE`), cross-linking §4/§5/§6/§13.12/§13.19/§13.20, updating `PUBLIC_EXPORTS` to 112 symbols, and guaranteeing additive-only evolution under `schema_version: 1` (#146).

- Froze supervise child-PID adoption and supervisor exit contract in SPEC §13.24 via exported `SUPERVISE_ADOPT_MESSAGE_FORMAT` (`"adopted child pid {pid}"`), `SUPERVISE_ADOPT_DETAIL_KEYS` (`previous_pid`, `pid`, `pid_token`), default terminal templates (`SUPERVISE_DONE_SUMMARY_FORMAT`, `SUPERVISE_FAIL_REASON_FORMAT`, `SUPERVISE_SIGNAL_REASON_FORMAT`), exit mapping (`SUPERVISE_SIGNAL_EXIT_BASE` 128 with `supervise_signal_exit(signum)`, `SUPERVISE_EXIT_NOT_FOUND` 127, `SUPERVISE_EXIT_PERMISSION_DENIED` 126), and `supervise_adopt_message(pid)` helper, cross-linking §4/§6 supervise, §13.8 reclaim targeting the adopted child, and §13.20 `Stage.supervise`, asserting precondition exits (2/3/15), exact adoption heartbeat shape, and additive-only evolution under `schema_version: 1` (#142).

- Froze wait want vocabulary and matching semantics in SPEC §13.23 via exported `WAIT_CHOICES` (`"done"`, `"blocked"`, `"failed"`, `"terminal"`) and `WAIT_WANT_NEEDS_RECLAIM` (`"needs_reclaim"`), documented `want_matches` and `wait_condition_met` predicate semantics, mutual exclusivity of `--needs-reclaim` vs non-default `--state`, cross-linked §6, §13.11, §13.12, and §13.16, updated `PUBLIC_EXPORTS` to 105 symbols, and guaranteed additive-only evolution under `schema_version: 1` (#141).
- Froze top-level public export inventory in SPEC §13.21 via exported `PUBLIC_EXPORTS` (93 canonical symbols matching `stage_signal.__all__`), cross-linking §11, §13.17, and §13.20, asserting constant freeze, set-equality to `__all__`, and direct importability, and guaranteeing additive-only evolution under `schema_version: 1` (#137).
- Froze doctor human summary strings in SPEC §13.22 via exported `DOCTOR_SUMMARY_RECLAIM_NEEDED` (`"ATTENTION: running needs reclaim"`), `DOCTOR_SUMMARY_OK_FORMAT` (`"OK: {state}"`), and the `doctor_summary_ok(state)` helper, cross-linking §6, §13.3.2, and §13.8, freezing the null-vs-string rule (`null` exactly when `problems` is non-empty), and guaranteeing additive-only display strings under `schema_version: 1` (#138).
- Froze public Stage instance method surface in SPEC §13.20 via exported `STAGE_PUBLIC_METHODS` (15 methods including `init`, `start`, `heartbeat`, `note`, `done`, `blocked`, `fail`, `reclaim`, `clear_terminal`, `supervise`, `status`, `wait`), cross-linking §11, §13.15, and §13.17, and guaranteeing additive-only evolution under `schema_version: 1` (#134).
- Froze lifecycle allowed transition matrix in SPEC §13.19 via exported `ALLOWED_TRANSITIONS`, `allowed_source_states`, `is_transition_allowed`, and `transition_target`, cross-linking §4, §6, §13.12, and §13.17, aligning `Stage` gate enforcement directly with the frozen matrix, asserting illegal transition rejection (`IllegalTransition` / exit 3), and guaranteeing additive-only transitions under `schema_version: 1` (#133).
- Froze best-effort STATUS.md human mirror required sections in SPEC §13.18 via exported `STATUS_MD_REQUIRED_HEADINGS` and `STATUS_MD_TITLE`, documenting non-normative status vs `STATUS.json`, cross-linking §2, §10, and §13.13, and asserting reader tolerance of additive sections and non-raising write failures (#130).
- Froze public exception hierarchy and exit mapping in SPEC §13.17 (`StageError`→1, `BadArgsError`→2, `IllegalTransition`→3, `NotInitialized`→15, `CorruptStatusError`→1, `WaitTimeout`→14), cross-linking §7 and §13.4, asserting top-level package exports, and guaranteeing additive-only evolution under `schema_version: 1` (#129).
- Froze state-to-exit-code mapping in SPEC §13.16 via exported `STATE_EXIT_CODES` (`queued`→13, `running`→10, `done`→0, `blocked`→11, `failed`→12), cross-linking §13.4 and §6, documenting distinction from mutation command exits and guaranteeing additive-only observer mapping under `schema_version: 1` (#126).
- Froze CLI subcommand inventory in SPEC §13.15 via exported `CLI_SUBCOMMANDS`, cross-linking §6, documenting `stage-signal == python -m stage_signal` entry point equivalence, and guaranteeing additive-only command surface under `schema_version: 1` (#125).
- Froze environment variable names (`ENV_DIR`, `ENV_PROJECT`, `ENV_PROOF_REF`, `ENV_STATUS_MIRROR`, `ENV_VARS`) and timing/capacity defaults (`WAIT_DEFAULT_TIMEOUT`, `WAIT_DEFAULT_POLL`, `EVENTS_DEFAULT_TAIL`, `DEFAULT_STALE_THRESHOLD`, `SUPERVISE_DEFAULT_EVERY`, `MAX_NOTES`) in SPEC §13.14, documenting precedence (`--dir` wins over `STAGE_SIGNAL_DIR`) and exporting missing constants from `stage_signal` (#122).
- Froze on-disk layout path constants in SPEC §13.13 via exported `DEFAULT_DIR_NAME`,
  `STATUS_FILENAME`, `STATUS_MD_FILENAME`, `EVENTS_FILENAME`, `LOCKS_DIRNAME`,
  `LOCK_FILENAME`, and `DEFAULT_MIRROR_DIRNAME`, cross-linking §2 and guaranteeing
  additive-only layout evolution under `schema_version: 1` (#121).
- Froze `wait --json` outcome enum in SPEC §13.11 via exported `WAIT_OUTCOMES`
  (`"met"`, `"mismatch"`, `"timeout"`), cross-linking §13.3.3 and guaranteeing
  additive-only outcomes and `timeout` boolean consistency under `schema_version: 1` (#117).
- Froze stage state machine enums in SPEC §13.12 via exported `STATES` and
  `TERMINAL_STATES`, cross-linking §4 and §13.2, with regression tests covering
  constant freeze, non-terminal/terminal partitions, and lifecycle state assertions
  across on-disk `STATUS.json` and `status --json` (#118).
- Froze `STATUS.json` `result`/`error` object required keys in SPEC §13.9 via
  exported `RESULT_KEYS` / `ERROR_KEYS` / `ERROR_KINDS`, with regression coverage
  for `done` / `blocked` / `fail` / `done --accept-failure` on disk and
  `status --json`, null validity, and additive tolerance (#113).
- Froze STATUS proof object required keys (`PROOF_KEYS`) and canonical `verified`
  enum values (`PROOF_VERIFIED_VALUES`) in SPEC §13.10, guaranteeing additive-only
  proof contracts across proof-ref-only and `--require-proof` paths (#114).

- Froze STATUS artifact/note entry keys in SPEC §13.7 via exported
  `ARTIFACT_ENTRY_KEYS` / `NOTE_ENTRY_KEYS`, with on-disk and `status --json`
  regression coverage for required keys, null labels, and additive fields (#109).
- Froze doctor warning object required keys (`WARNING_KEYS`) and canonical warning
  code set (`WARNING_CODES`) in SPEC §13.8, guaranteeing additive-only warning
  contracts for orchestrators branching on `warnings[].code` (#110).
- Froze required event record keys via exported `EVENT_RECORD_KEYS` and the
  `events --json` / `Stage.events()` array contract in SPEC §13.6, with
  lifecycle, reclaim-trail, and filtering regression coverage (#105).
- Proved `reclaim --kill` (Python API and CLI) signals the adopted child PID rather than the supervisor wrapper after `supervise`, asserting signal delivery target and adopt heartbeat event (#106).
- Locked `schema_version 1` read contract in SPEC Appendix §13 and added
  comprehensive regression tests ensuring `status --json`, `doctor --json`, and
  `wait --json` (including timeout path) preserve frozen key sets, exit codes,
  and `EVENT_TYPES` (#102).
- Updated `stage-signal supervise` to adopt the child process PID and capture its
  `pid_token` in STATUS under exclusive lock after `Popen`, ensuring `doctor`
  liveness probes and `reclaim --kill` target the active child worker (#98, #100).
- Pinned `ps` command execution environment to `LC_ALL=C` and `TZ=UTC` on macOS
  when capturing and verifying `pid_token` to guarantee consistent timestamp
  parsing across system locales (#97, #99).
- Added process start identity verification via opaque `pid_token` in STATUS
  (captured at `start` across Linux, macOS, and Windows), re-verified before
  `reclaim --kill` signals to protect against PID reuse (#94, #96).
- Added `stage-signal supervise [--every SEC] -- CMD` and `Stage.supervise()`
  to run and supervise a child command with automatic periodic heartbeats until exit,
  mapping exit 0 to done and non-zero to failed, with signal forwarding (#92, #95).
- Added `--kill` flag to `stage-signal reclaim` and `kill=True` to `Stage.reclaim()`
  to terminate the recorded alive PID via SIGTERM (with bounded 1s wait) and SIGKILL
  escalation after the `needs_reclaim` guard passes (#90, #93).

- Aligned watchdog example `examples/orchestrator-watchdog.sh --once --doctor-reclaim`
  (and `--once --needs-reclaim`) with full `needs_reclaim` (DEAD_PID or STALE_HEARTBEAT),
  calling `reclaim --reason ... --keep-failed` instead of DEAD_PID-only fail (#89).
- Added `stage-signal reclaim --reason TEXT [--keep-failed]` and `Stage.reclaim()`
  for one-shot fail+clear when `needs_reclaim` is true, resetting to idle queued
  under a single exclusive lock; exits 3 with no mutation when reclaim is not needed (#84).
- Updated orchestrator examples to branch on `needs_reclaim` rather than
  string-matching `summary` or treating `ok` as a liveness signal (#66, #69).
- Added `doctor --exit-reclaim` to exit 10 when `needs_reclaim` is true,
  preserving existing exit codes when reclaim is not needed (#70, #72).
- Added `needs_reclaim` boolean to `status --json` output and `Stage.status()`,
  using the same running-stage `DEAD_PID` or `STALE_HEARTBEAT` detection as
  `doctor --json` and `Stage.diagnose()` (#71, #73).
- Added a top-level `reason` to `wait --json` (`status.error.reason` when
  blocked/failed, or the short timeout message; otherwise `null`) (#74).
- Added a composite action `reason` step output so CI can branch on
  done / blocked / failed / timeout without scraping logs (#74).
- Updated example workflow `examples/github-action-wait.yml` with copy-paste
  `if:` branches for those four outcomes (#74).
- Added `fail --if-needs-reclaim` to fail a running stage only when `DEAD_PID`
  or `STALE_HEARTBEAT` requires reclamation; healthy running and non-running
  states exit 3 without mutation (#75, #78).
- Allowed `clear-terminal` from named or idle `queued` states to abandon
  queued work and reset to idle; calling it from `running` remains illegal
  (#76, #78).
- Added `stage-signal events [--tail N] [--type TYPE] [--json]` and
  `Stage.events(tail=, type=)` to read `events.jsonl` for orchestrator audit,
  with event-type filtering and tail selection (#80).
- Added `needs-reclaim` input and step outputs (`needs-reclaim`, `needs_reclaim`)
  to the composite GitHub Action, enabling CI watchdogs to gate on reclaim condition
  (`wait --needs-reclaim --json`) without custom shell loops (#85).
- Updated example workflows `examples/github-action-wait.yml` and added sibling
  `examples/github-action-wait-reclaim.yml` with copy-paste `if:` branches for
  reclaim-needed vs timeout vs terminal-without-reclaim (#85).

## [0.1.6] — 2026-09-17

- Added `needs_reclaim` boolean to `stage-signal doctor --json` output and `Stage.diagnose()`,
  allowing orchestrators to branch directly on whether a running stage requires reclamation
  (due to `DEAD_PID` or `STALE_HEARTBEAT` warnings) without string matching or scraping (#61, #65).
- Documented requirements and best practices for virtual environments (`.venv` with `.[dev]`)
  and running `.venv/bin/pytest` in isolated worktrees to ensure test dependencies like `pytest-timeout`
  are available (#60, #64).

## [0.1.5] — 2026-09-17

- Updated `stage-signal doctor` to report `ATTENTION: running needs reclaim` instead of
  `OK: running` when `DEAD_PID` or `STALE_HEARTBEAT` warnings apply to a running stage,
  and added a machine-readable `summary` field to `doctor --json` output and `Stage.diagnose()` (#57, #58).
- Omitted heartbeat elapsed age (`(age <Ns>)` in human `stage-signal status`, and
  `heartbeat_age_seconds` in `status --json`) when the stage is not in `running` state (#54, #59).

## [0.1.4] — 2026-09-17

- Added explicit `DEAD_PID` recovery hint (`reclaim with 'fail --reason TEXT --if-dead-pid'`)
  to `stage-signal doctor` message and detail in both human and JSON outputs, guiding
  operators on process reclamation without manual state editing (#44, #50).
- Added dynamic `heartbeat_age_seconds` (number of elapsed seconds, or `null` if no
  heartbeat recorded) to `stage-signal status --json` output and dictionary payloads (#44, #50).
- Added human-readable heartbeat age (`heartbeat: <iso> (age <Ns>)`) to `stage-signal status`
  output when a heartbeat is present (#51, #52).
- Dropped committed `.agloop-oc-DONE.md` receipt and added `.agloop-*-DONE.md` patterns
  to `.gitignore` to prevent agent completion receipts from polluting git worktrees (#47, #49).
- Documented isolated worktree dogfooding guidelines, shared `.venv` editable import
  pitfalls, and `PYTHONPATH` pinning in `CONTRIBUTING.md` and `docs/examples/orchestrator.md` (#48, #53).

## [0.1.3] — 2026-09-17

- Reset `clear-terminal` to true idle `queued` state by clearing stage identity
  (`stage_name` and `stage_id` set to `null`), preventing cleared failed stages
  from appearing as unfinished pending work in orchestrators and `doctor` (#26, #27).
- Added optional `--keep-stage` flag to `clear-terminal` for workflows needing to
  re-queue the previous stage identity without starting it immediately (#26, #27).
- Added `--accept-failure` flag to `done`, permitting orchestrators to transition
  a `failed` stage to `done` while recording `"accepted_failure": true` in `result`
  without inventing fake success (#26, #27).
- Documented orchestrator idle vs queued semantics and failure handling paths
  in `docs/SPEC.md`, `README.md`, and `examples/cli-orchestrator-loop.md` (#26, #27).
- Added `pytest-timeout>=2.3.0` to dev dependencies and configured a per-test
  timeout on Windows CI (`PYTEST_TIMEOUT="60"`) in `.github/workflows/ci.yml` and
  `tests/conftest.py` so test hangs trigger an informative stack dump naming the
  offending test instead of an undifferentiated CI hang (#28, #29).
- Fixed Windows CI `KeyboardInterrupt` during test runs by stopping `os.kill(pid, 0)`
  self-probe on Windows, where CPython maps signal 0 to `GenerateConsoleCtrlEvent`
  which queued an asynchronous interrupt that surfaced in subsequent threading locks (#25, #30).
- Fixed Windows test harness `PermissionError` when reading lockfile byte 0 under an
  active `msvcrt` exclusive byte lock (#31, #34).
- Added cross-platform `.cmd` stubbing for proof verification tests and explicit
  `cmd.exe /c` execution in `src/stage_signal/stage.py` when `agent-done-or-not` is
  resolved to a `.cmd` or `.bat` file on Windows `PATH` (#32, #33).
- Serialized same-process threads in `StageStore.locked()`, moved git repository detection
  outside file lock acquisition to avoid Windows lock contention, and rewritten
  Windows-safe composite action wait test harness (#20).
- Defaulted `doctor` stale-heartbeat threshold to 300s (5m) for agent workflows (#18, #21).

## [0.1.2] — 2026-09-16

- Clear stale `meta` keys on `start` (replacing entirely with newly supplied
  `--meta` flags, or clearing to `{}` when omitted) and refresh `git_head` and
  `git_branch` from current repository HEAD (#15).
- Composite action (`action.yml`) outputs exposed (`state`, `outcome`,
  `exit-code`, `timed-out`, `stage-id`, `json`) and optional `poll` input added,
  enabling CI steps to branch on wait outcomes without log scraping (#7).
- Added `wait --json` emitting a machine-readable JSON result object (`outcome`,
  `wanted`, `observed_state`, `exit_code`, `timeout`, `stage_id`, `dir`,
  `status`) to stdout for CI dashboards and orchestrators across met, mismatch,
  and timeout outcomes while preserving SPEC exit codes (#8).
- Added `doctor --json` and process liveness diagnostics checking for dead claiming
  PIDs on running stages (#5).
- Added CI workflow job to run pytest on `windows-latest` across Python 3.11, 3.12, 3.13, and 3.14 (#11, #16).
- Added copyable GitHub Actions wait workflow example in `examples/github-action-wait.yml` (#6).
- Added Windows usage notes for venv activation, `--pid` / `$$`, and POSIX
  shell examples in `README.md` (#9). (File locking semantics remain in
  `docs/SPEC.md` §8 and the README platform locking note from #1.)
- Added `CONTRIBUTING.md` guide covering development workflow, testing, style, and PR process (#10).

## [0.1.1] — 2026-09-16

- Windows stdlib locking fallback (`msvcrt.locking` on byte 0 of `stage.lock`)
  and honest concurrency documentation in `docs/SPEC.md` and `README.md` (#1).
- Composite action (`action.yml`) and workflows (`ci.yml`, `publish.yml`) bumped
  to Node 24 runtime (`actions/setup-python@v7`, `actions/checkout@v7`) avoiding
  Node 20 runner deprecation warnings (#2).
- Artifact attestations and build provenance enabled in `.github/workflows/publish.yml`
  via `actions/attest-build-provenance@v4` with `attestations: write` (#2).
- Added optional backward-compatible action inputs to `action.yml`: `version`,
  `cache`, `cache-dependency-path`, and `pip-cache` (#2).
- Multi-CLI orchestrator loop guide (`examples/cli-orchestrator-loop.md`) and
  companion thin runner (`examples/multi-cli-loop.sh`) demonstrating stage-signal
  orchestration across both Google Antigravity CLI (`agy`) and OpenCode (#3).

## [0.1.0] — 2026-09-16

Package available on PyPI (`pip install stage-signal`).
GitHub release and tag: [`v0.1.0`](https://github.com/syyzit/stage-signal/releases/tag/v0.1.0).

- Stage lifecycle CLI: `init`, `start`, `heartbeat`, `note`, `artifact`,
  `done`, `blocked`, `fail`, `status`, `wait`, `clear-terminal`, `doctor`.
- On-disk contract: `.stage-signal/STATUS.json` (normative),
  `STATUS.md` mirror, `events.jsonl`, `locks/stage.lock` (SPEC v1).
- Exit-code contract for orchestrators (`0/1/2/3/10/11/12/13/14/15`).
- Proof composition: `done --proof-ref/--require-proof` (see `docs/COMPOSE.md`).
- Optional `.orch/STATUS.md` mirror via `--write-status-mirror`.
- Composite GitHub Action for waiting without a preinstalled venv (`uses: syyzit/stage-signal@v0.1.0`).
- Stdlib only, Python `>=3.11`. Entry point `stage-signal`
  (`python -m stage_signal` alias).

[Unreleased]: https://github.com/syyzit/stage-signal/compare/v0.1.7...HEAD
[0.1.7]: https://github.com/syyzit/stage-signal/compare/v0.1.6...v0.1.7
[0.1.6]: https://github.com/syyzit/stage-signal/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/syyzit/stage-signal/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/syyzit/stage-signal/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/syyzit/stage-signal/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/syyzit/stage-signal/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/syyzit/stage-signal/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/syyzit/stage-signal/releases/tag/v0.1.0
