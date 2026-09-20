"""Tests for GitHub Action composite action (action.yml) outputs and wait step."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import uuid
from pathlib import Path

import pytest

from stage_signal.cli import main


ROOT = Path(__file__).resolve().parent.parent
ACTION_YML = ROOT / "action.yml"


def _action_emitter_source() -> str:
    """Extract the Python heredoc embedded in action.yml's `wait` step.

    Tests run the action's *real* output-emitting code rather than a copy, so
    the two cannot drift (the copy is how the unsanitized `stage_id` write
    survived review).
    """
    lines = ACTION_YML.read_text(encoding="utf-8").splitlines()
    start = next(
        i for i, line in enumerate(lines) if "exec(textwrap.dedent(sys.stdin.read()))" in line
    )
    body = []
    for line in lines[start + 1:]:
        if line.strip() == "EOF":
            break
        body.append(line)
    else:  # pragma: no cover - action.yml is malformed
        raise AssertionError("unterminated heredoc in action.yml")
    return textwrap.dedent("\n".join(body)) + "\n"


def _run_action_emitter(
    json_path: Path,
    exit_code: int,
    stage_dir: Path,
    needs_reclaim_input: str,
    gh_out: Path,
) -> dict[str, str]:
    """Run action.yml's emitter with the argv/env the composite step gives it."""
    env = dict(os.environ)
    env["GITHUB_OUTPUT"] = str(gh_out)
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            _action_emitter_source(),
            str(json_path),
            str(exit_code),
            str(stage_dir),
            needs_reclaim_input,
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return _parse_github_output(gh_out)


def test_action_yml_declares_outputs_and_inputs() -> None:
    content = ACTION_YML.read_text(encoding="utf-8")
    assert "outputs:" in content
    assert "state:" in content
    assert "outcome:" in content
    assert "exit-code:" in content
    assert "timed-out:" in content
    assert "stage-id:" in content
    assert "json:" in content
    assert "reason:" in content
    assert "needs-reclaim:" in content
    assert "needs_reclaim:" in content
    assert "poll:" in content
    assert "id: wait" in content
    assert "steps.wait.outputs.state" in content
    assert "steps.wait.outputs.outcome" in content
    assert "steps.wait.outputs.exit-code" in content
    assert "steps.wait.outputs.timed-out" in content
    assert "steps.wait.outputs.reason" in content
    assert "steps.wait.outputs.needs-reclaim" in content


def _parse_github_output(path: Path) -> dict[str, str]:
    """Parse GITHUB_OUTPUT format including multiline delimiters."""
    lines = path.read_text(encoding="utf-8").splitlines()
    outputs: dict[str, str] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if "<<" in line:
            key, delim = line.split("<<", 1)
            val_lines = []
            i += 1
            while i < len(lines) and lines[i] != delim:
                val_lines.append(lines[i])
                i += 1
            outputs[key] = chr(10).join(val_lines)
            i += 1
        elif "=" in line:
            k, v = line.split("=", 1)
            outputs[k] = v
            i += 1
        else:
            i += 1
    return outputs


def _run_action_wait_step(
    stage_dir: Path,
    state: str = "terminal",
    timeout: str = "1",
    poll: str = "",
    needs_reclaim: bool = False,
    force_no_json: bool = False,
) -> tuple[int, dict[str, str]]:
    """Run the wait contract without a bash subshell (Windows-safe)."""
    with tempfile.TemporaryDirectory() as td:
        gh_out = Path(td) / "gh_output"
        gh_out.touch()
        tmp_out = Path(td) / "wait.json"

        exe = shutil.which("stage-signal")
        if exe is None:
            for candidate in (
                ROOT / ".venv" / "bin" / "stage-signal",
                ROOT / ".venv" / "Scripts" / "stage-signal.exe",
                ROOT / ".venv" / "Scripts" / "stage-signal",
            ):
                if candidate.is_file():
                    exe = str(candidate)
                    break
        if exe is None:
            raise FileNotFoundError("stage-signal CLI not found on PATH or in .venv")

        cmd = [exe, "--dir", str(stage_dir), "wait", "--timeout", timeout]
        if needs_reclaim:
            cmd.append("--needs-reclaim")
            if state != "terminal":
                cmd.extend(["--state", state])
        else:
            cmd.extend(["--state", state])
        if poll:
            cmd.extend(["--poll", poll])

        # The action always passes --json now; force_no_json simulates an empty
        # payload so the STATUS.json fallback branch is exercised.
        use_json = not force_no_json
        if use_json:
            cmd.append("--json")

        env = dict(os.environ)
        env["GITHUB_OUTPUT"] = str(gh_out)

        if use_json:
            with open(tmp_out, "w", encoding="utf-8") as sink:
                proc = subprocess.run(
                    cmd, env=env, stdout=sink, stderr=subprocess.DEVNULL, text=True,
                    timeout=max(30.0, float(timeout) + 5.0),
                )
        else:
            proc = subprocess.run(
                cmd, env=env, capture_output=True, text=True,
                timeout=max(30.0, float(timeout) + 5.0),
            )
        exit_code = proc.returncode

        outputs = _run_action_emitter(
            tmp_out, exit_code, stage_dir, "true" if needs_reclaim else "false", gh_out
        )
        exit_code = int(outputs["exit-code"])

        return exit_code, outputs


def test_action_wait_met_done(tmp_path: Path) -> None:
    d = tmp_path / ".stage-signal"
    assert main(["--dir", str(d), "init", "--project", "ci-demo"]) == 0
    assert main(["--dir", str(d), "start", "--stage", "ci-build", "--stage-id", "ci-123"]) == 0
    assert main(["--dir", str(d), "done", "--summary", "tests passed"]) == 0

    code, out = _run_action_wait_step(d, state="terminal", timeout="5", poll="0.05")
    assert code == 0
    assert out["outcome"] == "met"
    assert out["state"] == "done"
    assert out["observed-state"] == "done"
    assert out["exit-code"] == "0"
    assert out["timed-out"] == "false"
    assert out["stage-id"] == "ci-123"
    assert out["reason"] == ""
    assert out["needs-reclaim"] == "false"
    assert out["needs_reclaim"] == "false"
    assert "tests passed" in out["json"]


def test_action_wait_mismatch_blocked(tmp_path: Path) -> None:
    d = tmp_path / ".stage-signal"
    assert main(["--dir", str(d), "init"]) == 0
    assert main(["--dir", str(d), "start", "--stage", "review", "--stage-id", "rev-1"]) == 0
    assert main(["--dir", str(d), "blocked", "--reason", "waiting for approval"]) == 0

    code, out = _run_action_wait_step(d, state="done", timeout="2", poll="0.05")
    assert code == 11
    assert out["outcome"] == "mismatch"
    assert out["state"] == "blocked"
    assert out["exit-code"] == "11"
    assert out["timed-out"] == "false"
    assert out["stage-id"] == "rev-1"
    assert out["reason"] == "waiting for approval"
    assert out["needs-reclaim"] == "false"


def test_action_wait_mismatch_failed(tmp_path: Path) -> None:
    d = tmp_path / ".stage-signal"
    assert main(["--dir", str(d), "init"]) == 0
    assert main(["--dir", str(d), "start", "--stage", "deploy", "--stage-id", "dep-2"]) == 0
    assert main(["--dir", str(d), "fail", "--reason", "out of memory"]) == 0

    code, out = _run_action_wait_step(d, state="done", timeout="2", poll="0.05")
    assert code == 12
    assert out["outcome"] == "mismatch"
    assert out["state"] == "failed"
    assert out["exit-code"] == "12"
    assert out["timed-out"] == "false"
    assert out["stage-id"] == "dep-2"
    assert out["reason"] == "out of memory"
    assert out["needs-reclaim"] == "false"


def test_action_wait_timeout(tmp_path: Path) -> None:
    d = tmp_path / ".stage-signal"
    assert main(["--dir", str(d), "init"]) == 0
    assert main(["--dir", str(d), "start", "--stage", "long-task", "--stage-id", "long-1"]) == 0

    code, out = _run_action_wait_step(d, state="terminal", timeout="0.2", poll="0.05")
    assert code == 14
    assert out["outcome"] == "timeout"
    assert out["state"] == "running"
    assert out["exit-code"] == "14"
    assert out["timed-out"] == "true"
    assert out["stage-id"] == "long-1"
    assert "timed out" in out["reason"]
    assert out["needs-reclaim"] == "false"


def test_action_wait_fallback_no_json(tmp_path: Path) -> None:
    d = tmp_path / ".stage-signal"
    assert main(["--dir", str(d), "init"]) == 0
    assert main(["--dir", str(d), "start", "--stage", "fb-stage", "--stage-id", "fb-1"]) == 0
    assert main(["--dir", str(d), "blocked", "--reason", "need creds"]) == 0

    code, out = _run_action_wait_step(d, state="done", timeout="1", poll="0.05", force_no_json=True)
    assert code == 11
    assert out["outcome"] == "mismatch"
    assert out["state"] == "blocked"
    assert out["exit-code"] == "11"
    assert out["timed-out"] == "false"
    assert out["stage-id"] == "fb-1"
    assert out["reason"] == "need creds"
    assert out["needs-reclaim"] == "false"


def test_action_wait_needs_reclaim_met(tmp_path: Path) -> None:
    d = tmp_path / ".stage-signal"
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=10)
    assert main(["--dir", str(d), "init", "--project", "reclaim-ci"]) == 0
    assert main(["--dir", str(d), "start", "--stage", "worker", "--stage-id", "w-1", "--pid", str(proc.pid)]) == 0

    code, out = _run_action_wait_step(d, needs_reclaim=True, timeout="5", poll="0.05")
    assert code == 0
    assert out["outcome"] == "met"
    assert out["state"] == "running"
    assert out["observed-state"] == "running"
    assert out["exit-code"] == "0"
    assert out["timed-out"] == "false"
    assert out["stage-id"] == "w-1"
    assert out["needs-reclaim"] == "true"
    assert out["needs_reclaim"] == "true"
    assert out["reason"] == ""
    assert "needs_reclaim" in out["json"]


def test_action_wait_needs_reclaim_terminal_mismatch_done(tmp_path: Path) -> None:
    d = tmp_path / ".stage-signal"
    assert main(["--dir", str(d), "init"]) == 0
    assert main(["--dir", str(d), "start", "--stage", "fast-job", "--stage-id", "fast-1"]) == 0
    assert main(["--dir", str(d), "done", "--summary", "completed cleanly"]) == 0

    code, out = _run_action_wait_step(d, needs_reclaim=True, timeout="2", poll="0.05")
    # Fail closed: done without reclaim maps to exit code 1 (SPEC §6)
    assert code == 1
    assert out["outcome"] == "mismatch"
    assert out["state"] == "done"
    assert out["exit-code"] == "1"
    assert out["timed-out"] == "false"
    assert out["stage-id"] == "fast-1"
    assert out["needs-reclaim"] == "false"
    assert out["needs_reclaim"] == "false"


def test_action_wait_needs_reclaim_terminal_mismatch_blocked(tmp_path: Path) -> None:
    d = tmp_path / ".stage-signal"
    assert main(["--dir", str(d), "init"]) == 0
    assert main(["--dir", str(d), "start", "--stage", "gate", "--stage-id", "gate-1"]) == 0
    assert main(["--dir", str(d), "blocked", "--reason", "needs human review"]) == 0

    code, out = _run_action_wait_step(d, needs_reclaim=True, timeout="2", poll="0.05")
    assert code == 11
    assert out["outcome"] == "mismatch"
    assert out["state"] == "blocked"
    assert out["exit-code"] == "11"
    assert out["timed-out"] == "false"
    assert out["stage-id"] == "gate-1"
    assert out["reason"] == "needs human review"
    assert out["needs-reclaim"] == "false"


def test_action_wait_needs_reclaim_terminal_mismatch_failed(tmp_path: Path) -> None:
    d = tmp_path / ".stage-signal"
    assert main(["--dir", str(d), "init"]) == 0
    assert main(["--dir", str(d), "start", "--stage", "run", "--stage-id", "run-1"]) == 0
    assert main(["--dir", str(d), "fail", "--reason", "disk full"]) == 0

    code, out = _run_action_wait_step(d, needs_reclaim=True, timeout="2", poll="0.05")
    assert code == 12
    assert out["outcome"] == "mismatch"
    assert out["state"] == "failed"
    assert out["exit-code"] == "12"
    assert out["timed-out"] == "false"
    assert out["stage-id"] == "run-1"
    assert out["reason"] == "disk full"
    assert out["needs-reclaim"] == "false"


def test_action_wait_needs_reclaim_timeout(tmp_path: Path) -> None:
    d = tmp_path / ".stage-signal"
    # Live process so it stays healthy running
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        assert main(["--dir", str(d), "init"]) == 0
        assert main(["--dir", str(d), "start", "--stage", "live-job", "--stage-id", "live-1", "--pid", str(proc.pid)]) == 0

        code, out = _run_action_wait_step(d, needs_reclaim=True, timeout="0.2", poll="0.05")
        assert code == 14
        assert out["outcome"] == "timeout"
        assert out["state"] == "running"
        assert out["exit-code"] == "14"
        assert out["timed-out"] == "true"
        assert out["stage-id"] == "live-1"
        assert out["needs-reclaim"] == "false"
        assert "timed out" in out["reason"]
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            pass


def test_action_wait_needs_reclaim_fallback_no_json(tmp_path: Path) -> None:
    d = tmp_path / ".stage-signal"
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=10)
    assert main(["--dir", str(d), "init"]) == 0
    assert main(["--dir", str(d), "start", "--stage", "fb-reclaim", "--stage-id", "fb-r", "--pid", str(proc.pid)]) == 0

    code, out = _run_action_wait_step(d, needs_reclaim=True, timeout="5", poll="0.05", force_no_json=True)
    assert code == 0
    assert out["outcome"] == "met"
    assert out["state"] == "running"
    assert out["needs-reclaim"] == "true"
    assert out["needs_reclaim"] == "true"
    assert out["exit-code"] == "0"


def test_example_workflow_branches_on_ci_outcomes() -> None:
    content = (ROOT / "examples" / "github-action-wait.yml").read_text(encoding="utf-8")
    assert "continue-on-error: true" in content
    assert "steps.wait.outputs.state == 'done'" in content
    assert "steps.wait.outputs.state == 'blocked'" in content
    assert "steps.wait.outputs.state == 'failed'" in content
    assert "steps.wait.outputs.timed-out == 'true'" in content
    assert "steps.wait.outputs.reason" in content
    assert "steps.wait.outputs.exit-code" in content
    assert "exit 1" in content


def test_example_workflows_branch_on_reclaim_outcomes() -> None:
    for filename in ("github-action-wait.yml", "github-action-wait-reclaim.yml"):
        content = (ROOT / "examples" / filename).read_text(encoding="utf-8")
        assert "continue-on-error: true" in content
        assert "needs-reclaim: true" in content
        assert "steps.wait.outputs.needs-reclaim == 'true'" in content
        assert "steps.wait.outputs.timed-out == 'true'" in content
        assert "steps.wait.outputs.outcome == 'mismatch'" in content
        assert "reclaim-needed" in content
        assert "terminal-without-reclaim" in content



# --- Action hygiene: inputs must not be interpolated into shell, and every
# --- GITHUB_OUTPUT value must be single-line (issue #209 / OPUS review §2.4).


def test_action_yml_never_interpolates_inputs_into_shell() -> None:
    """`${{ inputs.* }}` inside a `run:` body is arbitrary code execution.

    Inputs must reach the script through `env:` and be read as "$VAR".
    Expressions are still allowed in `with:` and `env:` mappings.
    """
    lines = ACTION_YML.read_text(encoding="utf-8").splitlines()
    in_run = False
    offenders = []
    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped in ("run: |", "run: |-"):
            in_run = True
            continue
        if in_run and stripped and not line.startswith("        "):
            in_run = False
        if in_run and "${{" in line and "inputs." in line:
            offenders.append(f"{lineno}: {stripped}")
    assert not offenders, "inputs interpolated into a run: body: " + "; ".join(offenders)


def test_action_yml_pins_a_default_version() -> None:
    """An unpinned default means `@v1.0.0` can install an arbitrary later release."""
    import stage_signal

    content = ACTION_YML.read_text(encoding="utf-8")
    block = content.split("  version:", 1)[1].split("\n  cache:", 1)[0]
    assert f"default: '{stage_signal.__version__}'" in block, (
        "action.yml `version` default must match the packaged version"
    )


def test_action_yml_supports_a_local_install() -> None:
    """A release commit's pinned version is not on PyPI yet (#211)."""
    content = ACTION_YML.read_text(encoding="utf-8")
    assert '[ "$VERSION" = "local" ] || [ "$VERSION" = "." ]' in content
    assert 'pip install "$GITHUB_WORKSPACE"' in content


def test_soak_workflow_installs_the_checked_out_source() -> None:
    """`uses: ./` must not install from PyPI, or the soak races the release."""
    content = (ROOT / ".github" / "workflows" / "action.yml").read_text(encoding="utf-8")
    uses_local = content.count("uses: ./")
    assert uses_local >= 2
    assert content.count("version: local") == uses_local, (
        "every `uses: ./` step must pass `version: local`"
    )


def _forge_payload(tmp_path: Path, stage_id: str) -> Path:
    payload = tmp_path / "wait.json"
    payload.write_text(
        json.dumps(
            {
                "outcome": "met",
                "state": "queued",
                "exit_code": 13,
                "timeout": False,
                "stage_id": stage_id,
                "reason": None,
            }
        ),
        encoding="utf-8",
    )
    return payload


def test_action_outputs_cannot_be_forged_via_stage_id(tmp_path: Path) -> None:
    """A newline in a stage name must not inject a second GITHUB_OUTPUT entry."""
    payload = _forge_payload(tmp_path, "demo\nstate=done\nneeds-reclaim=true")
    outputs = _run_action_emitter(
        payload, 13, tmp_path / ".stage-signal", "false", tmp_path / "gh_out"
    )
    assert outputs["state"] == "queued"
    assert outputs["needs-reclaim"] == "false"
    assert outputs["stage-id"] == "demo state=done needs-reclaim=true"


def test_action_outputs_cannot_be_forged_via_reason(tmp_path: Path) -> None:
    payload = tmp_path / "wait.json"
    payload.write_text(
        json.dumps(
            {
                "outcome": "mismatch",
                "state": "failed",
                "exit_code": 12,
                "timeout": False,
                "stage_id": "s1",
                "reason": "boom\nstate=done\ntimed-out=false",
            }
        ),
        encoding="utf-8",
    )
    outputs = _run_action_emitter(
        payload, 12, tmp_path / ".stage-signal", "false", tmp_path / "gh_out"
    )
    assert outputs["state"] == "failed"
    assert outputs["reason"] == "boom state=done timed-out=false"


def test_action_every_scalar_output_is_single_line(tmp_path: Path) -> None:
    """No scalar output may span lines, whatever the payload contains."""
    payload = tmp_path / "wait.json"
    payload.write_text(
        json.dumps(
            {
                "outcome": "me\nt",
                "state": "que\nued",
                "exit_code": 13,
                "timeout": False,
                "stage_id": "a\nb",
                "reason": "c\nd",
                "needs_reclaim": True,
            }
        ),
        encoding="utf-8",
    )
    gh_out = tmp_path / "gh_out"
    _run_action_emitter(payload, 13, tmp_path / ".stage-signal", "false", gh_out)
    raw = gh_out.read_text(encoding="utf-8")
    scalar_part = raw.split("json<<", 1)[0]
    keys = [line.split("=", 1)[0] for line in scalar_part.splitlines() if line]
    assert keys == [
        "state",
        "observed-state",
        "observed_state",
        "outcome",
        "exit-code",
        "exit_code",
        "timed-out",
        "timed_out",
        "stage-id",
        "stage_id",
        "reason",
        "needs-reclaim",
        "needs_reclaim",
    ]
