# Changelog — stage-signal

All notable changes to this project are documented here.
Format follows Keep a Changelog (loosely); versioning is SemVer.
See `docs/RELEASE.md` for the release procedure.

## [Unreleased]

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

[Unreleased]: https://github.com/syyzit/stage-signal/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/syyzit/stage-signal/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/syyzit/stage-signal/releases/tag/v0.1.0
