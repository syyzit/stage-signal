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

## Tests

Run the test suite and both orchestrator smoke tests before submitting a pull
request:

```bash
python -m pytest
sh examples/orchestrator-smoke.sh
sh examples/queue-orchestrator-smoke.sh
```

Do not bump the package version, publish to PyPI, or push release tags as part
of a contribution. Maintainers follow the release procedure in
[`docs/RELEASE.md`](docs/RELEASE.md).
