# Changelog — stage-signal

All notable changes to this project are documented here.
Format follows Keep a Changelog (loosely); versioning is SemVer.
See `docs/RELEASE.md` for the release procedure.

## [Unreleased]

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

[Unreleased]: https://github.com/syyzit/stage-signal/compare/v0.1.3...HEAD
[0.1.3]: https://github.com/syyzit/stage-signal/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/syyzit/stage-signal/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/syyzit/stage-signal/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/syyzit/stage-signal/releases/tag/v0.1.0
