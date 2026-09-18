# Changelog — stage-signal

All notable changes to this project are documented here.
Format follows Keep a Changelog (loosely); versioning is SemVer.
See `docs/RELEASE.md` for the release procedure.

## [Unreleased]

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

[Unreleased]: https://github.com/syyzit/stage-signal/compare/v0.1.6...HEAD
[0.1.6]: https://github.com/syyzit/stage-signal/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/syyzit/stage-signal/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/syyzit/stage-signal/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/syyzit/stage-signal/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/syyzit/stage-signal/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/syyzit/stage-signal/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/syyzit/stage-signal/releases/tag/v0.1.0
