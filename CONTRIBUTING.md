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

Always install with `.[dev]` into `.venv` so test dependencies (such as `pytest` and `pytest-timeout`) are available.

## Dogfooding from isolated worktrees

A shared `.venv` has only one editable-install target. Running `pip install -e .`
from another worktree can redirect every lane's `stage-signal` command to that
worktree's source. Changing directories or passing `--dir` selects neither the
Python source nor the editable target; `--dir` only selects lifecycle state.

Prefer a per-worktree venv (using the local setup above), or explicitly select
`PYTHONPATH=<worktree>/src` for every agent and watchdog invocation. From the
intended worktree, with `python` and `stage-signal` from the chosen venv:

```bash
WORKTREE="$(pwd -P)"
export PYTHONPATH="$WORKTREE/src"
python -m stage_signal --dir "$WORKTREE/.stage-signal" doctor --json
stage-signal fail -h
python -c 'import stage_signal; print(stage_signal.__file__)'
```

On a tree containing #43, `stage-signal fail -h` must list `--if-dead-pid`.
On a tree containing #75, the same help must also list `--if-needs-reclaim`.
The printed module path must belong to the intended worktree. Check with the
same interpreter and environment used by the launcher/watchdog, not just an
unrelated shell. An unrecognized flag during `DEAD_PID` recovery can mean stale
imports rather than a failed PID proof.

After merging CLI-flag changes, if sharing one `.venv`, reinstall the editable
package **from the main checkout** using that venv's Python:

```bash
python -m pip install -e ".[dev]"
```

Run that command with main as the working directory, not an isolated lane.
Recheck `stage-signal fail -h` with `PYTHONPATH` unset to verify the shared
editable target. Avoid lane-local reinstalls into the shared venv: they redirect
all unpinned callers again. Keep lane-specific `PYTHONPATH` overrides even after
repairing the shared install.

### Worktree test runs

When running tests in an isolated worktree, ensure the worktree has access to a
virtual environment with dev dependencies installed via `pip install -e ".[dev]"`
(either a dedicated per-worktree `.venv` or a symlink to the main checkout's `.venv`).
Always run `.venv/bin/pytest` (or activate that venv). Do not run bare system
`python3 -m pytest tests/`: without the dev environment, tests that require
installed plugins (such as `test_spec_gaps.py::test_pytest_timeout_plugin_installed_and_aborts_hanging_test`)
will fail with `ModuleNotFoundError: No module named 'pytest_timeout'`.

### Orchestrator helpers

Private orchestrator helpers and receipts are gitignored local state and must
not be committed. Public integration patterns are documented in
[`docs/CALLER.md`](docs/CALLER.md); historical harnesses are archived in
[`examples/dogfood/`](examples/dogfood/).

## Tests

Run the test suite and the orchestrator smoke test before submitting a pull
request:

```bash
# Using .venv directly or inside active venv:
.venv/bin/pytest
sh examples/orchestrator-smoke.sh
```

Optionally, dogfood runs may also execute the archived queue smoke test:

```bash
sh examples/dogfood/queue-orchestrator-smoke.sh
```

Local and dogfood test runs should use `pip install -e ".[dev]"` into `.venv` and
`.venv/bin/pytest` (not bare system `python3 -m pytest`). `pytest-timeout` is
defined in `[project.optional-dependencies] dev`; running bare system pytest
without the dev environment fails
`test_spec_gaps.py::test_pytest_timeout_plugin_installed_and_aborts_hanging_test`
with `ModuleNotFoundError: No module named 'pytest_timeout'`.

On Windows, `pytest-timeout` enforces a 60s per-test timeout (configured in CI and defaulted in `tests/conftest.py`) so hangs fail promptly with stack traces.

Do not bump the package version, publish to PyPI, or push release tags as part
of a contribution. Maintainers follow the release procedure in
[`docs/RELEASE.md`](docs/RELEASE.md).
