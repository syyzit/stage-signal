# Release checklist — stage-signal

First PyPI release is **manual**. Do NOT automate upload/push in agent loops.
This doc is the whole procedure; stop after local `twine check`.

Package name (PyPI): `stage-signal`
Entry point: `stage-signal` (= `python -m stage_signal`)
Runtime deps: stdlib only — do not add runtime dependencies without a SPEC change.

## 1. Version bump

Single source of intent is `pyproject.toml`:

- `pyproject.toml` → `[project] version = "X.Y.Z"`
- `src/stage_signal/__init__.py` → `__version__ = "X.Y.Z"` (must match)

Check:

```bash
grep '^version' pyproject.toml
grep '__version__' src/stage_signal/__init__.py
.venv/bin/python -m stage_signal --version
```

## 2. Changelog note

- Add an entry at the top of `CHANGELOG.md` (`## X.Y.Z — YYYY-MM-DD` + bullets).
- Keep it short: what changed, SPEC version if bumped, migration notes (none for 0.1.0).

## 3. Tests green

```bash
.venv/bin/python -m pytest -q
sh examples/orchestrator-smoke.sh
```

Both must pass. No commit with red tests.

## 4. Build (local)

CI runs the same check on every push/PR (packaging job in
`.github/workflows/ci.yml`: `python -m build` + `twine check dist/*`, no
upload).

```bash
.venv/bin/pip install --upgrade build twine
.venv/bin/python -m build
ls -lh dist/
```

Expect exactly two artifacts:

- `dist/stage_signal-X.Y.Z.tar.gz` (sdist)
- `dist/stage_signal-X.Y.Z-py3-none-any.whl` (wheel)

## 5. Twine check + wheel smoke

```bash
.venv/bin/python -m twine check dist/*
# smoke-import the wheel without installing deps (stdlib-only):
.venv/bin/python - <<'EOF'
import zipfile, glob
whl = sorted(glob.glob("dist/*.whl"))[-1]
print("wheel:", whl)
with zipfile.ZipFile(whl) as z:
    names = z.namelist()
    assert any(n.endswith("stage_signal/__init__.py") for n in names), names[:20]
    assert any(n.endswith("stage_signal/cli.py") for n in names)
    print("wheel contents OK")
EOF
```

`twine check` must say `Passed` for both files. Fix `README.md` /
`pyproject.toml` metadata on any warning — do not work around with
`--skip-existing`.

## 6. Upload (human only, never the agent)

```bash
# maintainer runs this by hand after reviewing dist/:
python -m twine upload dist/*
# for a test run first:
# python -m twine upload --repository testpypi dist/*
```

Never run `twine upload` from an unattended agent. Never store PyPI
tokens in the repo.

## 7. Git tag (human only)

```bash
git tag -a vX.Y.Z -m "stage-signal X.Y.Z"
git log --oneline -5   # sanity check what the tag points at
# git push + git push --tags  (only when the maintainer says so)
```

Tag only a commit where steps 1–5 already passed. Push is HOLD by
default in this repo (see `.museloop/QUEUE.md`).

## Quick fail-closed rules

- `__version__` ≠ `pyproject.toml` version → stop, fix, re-test.
- New runtime dep in `pyproject.toml [project] dependencies` → stop, needs SPEC review (stdlib-only policy).
- `twine check` warning → stop, fix metadata/README.
- Any doubt about upload/push → stop, leave artifacts in `dist/` (gitignored) for a human.
