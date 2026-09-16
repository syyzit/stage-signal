# Release checklist — stage-signal

First PyPI upload goes through GitHub OIDC trusted publishing via
`.github/workflows/publish.yml`, not local `twine upload`. Do NOT run
`twine upload` locally or from an agent. Local `twine check` still
required (step 5). Do NOT automate push/tag in agent loops.
This doc is the whole procedure; stop after local `twine check`
(unless this milestone explicitly asks for the publish workflow).

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

## 6. Upload (trusted publisher via GitHub, never local twine upload)

First upload for `v0.1.0` (and later tags) is handled by the
`publish` workflow in `.github/workflows/publish.yml`:

- Trigger: push a tag matching `v*` (e.g. `v0.1.0`), or manual
  `workflow_dispatch`.
- The workflow builds with `python -m build` and publishes with
  `pypa/gh-action-pypi-publish@release/v1` using OIDC — no stored
  API token, no `password`/`token` passed in the workflow.
- Required job permissions: `id-token: write`, `contents: read`, `attestations: write`.
- No `environment:` key in the workflow (pending publisher was
  registered with an empty Environment name).

### Artifact attestations & build provenance

`.github/workflows/publish.yml` generates cryptographic build provenance
attestations for built distribution packages (`dist/*`) using
`actions/attest-build-provenance@v4` (SLSA provenance backed by Sigstore
and GitHub's attestation registry).

Because `syyzit/stage-signal` is a public repository on GitHub, artifact
attestations are enabled natively without any third-party tokens or secrets.
The workflow only requires `id-token: write` (for OIDC token minting) and
`attestations: write` (to persist attestations in GitHub).

In addition, `pypa/gh-action-pypi-publish@release/v1` automatically publishes
PEP 740 digital attestations directly to PyPI.

To verify artifact provenance using the GitHub CLI:

```bash
gh attestation verify dist/stage_signal-<version>-py3-none-any.whl --repo syyzit/stage-signal
gh attestation verify dist/stage_signal-<version>.tar.gz --repo syyzit/stage-signal
```


Pending publisher fields on PyPI (must match exactly):

- PyPI project name: `stage-signal`
- Owner: `syyzit`
- Repo name: `stage-signal`
- Workflow name: `publish.yml`
- Environment name: (empty — leave blank)

Do NOT run `twine upload` locally — the pending publisher only
trusts the GitHub workflow identity. Never store PyPI tokens in
the repo.

```bash
# maintainer runs this by hand after reviewing dist/ and CI:
# git push + git push --tags  (only when the maintainer says so)
# pushing tag vX.Y.Z triggers the publish workflow, which uploads to PyPI.
# for a test run first, configure a TestPyPI pending publisher separately.
```

## 7. Git tag (human only)

```bash
git tag -a vX.Y.Z -m "stage-signal X.Y.Z"
git log --oneline -5   # sanity check what the tag points at
# git push + git push --tags  (only when the maintainer says so)
```

Tag only a commit where steps 1–5 already passed. Push is HOLD by
default in this repo until maintainer review.

## Quick fail-closed rules

- `__version__` ≠ `pyproject.toml` version → stop, fix, re-test.
- New runtime dep in `pyproject.toml [project] dependencies` → stop, needs SPEC review (stdlib-only policy).
- `twine check` warning → stop, fix metadata/README.
- Any doubt about upload/push → stop, leave artifacts in `dist/` (gitignored) for a human.
