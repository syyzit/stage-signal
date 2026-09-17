# Contributing

Keep contributions focused on stage lifecycle signals rather than expanding
`stage-signal` into an orchestration platform. When behavior or documentation
is ambiguous, [`docs/SPEC.md`](docs/SPEC.md) is the normative contract.

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Agent receipts

Write OpenCode completion receipts to `.agloop/OC-DONE.md` in the active
worktree. The `.agloop/` directory is gitignored; receipts are local orchestrator
state and must never be committed. Do not write receipts at the repository root
(such as `.agloop-oc-DONE.md`).

## Tests

Run the test suite and both orchestrator smoke tests before submitting a pull
request:

```bash
python -m pytest
sh examples/orchestrator-smoke.sh
sh examples/queue-orchestrator-smoke.sh
```

On Windows, `pytest-timeout` enforces a 60s per-test timeout (configured in CI and defaulted in `tests/conftest.py`) so hangs fail promptly with stack traces.

Do not bump the package version, publish to PyPI, or push release tags as part
of a contribution. Maintainers follow the release procedure in
[`docs/RELEASE.md`](docs/RELEASE.md).
