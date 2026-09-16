# Changelog — stage-signal

All notable changes to this project are documented here.
Format follows Keep a Changelog (loosely); versioning is SemVer.
See `docs/RELEASE.md` for the release procedure.

## [Unreleased]

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

[0.1.0]: https://github.com/syyzit/stage-signal/releases/tag/v0.1.0
