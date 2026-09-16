"""Tests for GitHub Action composite action (action.yml) outputs and wait step."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
import pytest

from stage_signal.cli import main


ROOT = Path(__file__).resolve().parent.parent
ACTION_YML = ROOT / "action.yml"


def test_action_yml_declares_outputs_and_inputs() -> None:
    content = ACTION_YML.read_text(encoding="utf-8")
    assert "outputs:" in content
    assert "state:" in content
    assert "outcome:" in content
    assert "exit-code:" in content
    assert "timed-out:" in content
    assert "stage-id:" in content
    assert "json:" in content
    assert "poll:" in content
    assert "id: wait" in content
    assert "steps.wait.outputs.state" in content
    assert "steps.wait.outputs.outcome" in content
    assert "steps.wait.outputs.exit-code" in content
    assert "steps.wait.outputs.timed-out" in content


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
            outputs[key] = "\n".join(val_lines)
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
    force_no_json: bool = False,
) -> tuple[int, dict[str, str]]:
    """Run the wait contract the composite action uses, without a bash subshell.

    GitHub Actions runs the action step under `shell: bash`, but reproducing that
    via `bash -c` on Windows CI lost exit codes (always 1). Drive `wait` through
    the same installed CLI with subprocess and synthesize GITHUB_OUTPUT locally.
    """
    import json
    import shutil
    import tempfile
    import uuid

    with tempfile.TemporaryDirectory() as td:
        gh_out = Path(td) / "gh_output"
        gh_out.touch()
        tmp_out = Path(td) / "wait.json"

        exe = shutil.which("stage-signal")
        if exe is None:
            # Fallbacks used in local/dev checkouts
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

        cmd = [exe, "--dir", str(stage_dir), "wait", "--state", state, "--timeout", timeout]
        if poll:
            cmd.extend(["--poll", poll])

        use_json = not force_no_json
        if use_json:
            help_proc = subprocess.run([exe, "wait", "--help"], capture_output=True, text=True)
            use_json = "--json" in (help_proc.stdout + help_proc.stderr)
        if use_json:
            cmd.append("--json")

        env = dict(os.environ)
        env["GITHUB_OUTPUT"] = str(gh_out)

        with open(tmp_out, "w", encoding="utf-8") as sink:
            proc = subprocess.run(cmd, env=env, stdout=sink if use_json else subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        exit_code = proc.returncode

        raw_json = tmp_out.read_text(encoding="utf-8") if use_json and tmp_out.exists() else ""
        observed = ""
        outcome = ""
        timed_out = "false"
        stage_id = ""

        if raw_json.strip():
            try:
                data = json.loads(raw_json)
                observed = str(data.get("state") or data.get("observed_state") or "")
                outcome = str(data.get("outcome") or "")
                exit_code = int(data.get("exit_code", exit_code))
                timed_out = "true" if data.get("timeout") else "false"
                stage_id = str(data.get("stage_id") or "")
            except Exception:
                pass

        if not observed:
            status_file = stage_dir / "STATUS.json"
            if status_file.exists():
                try:
                    st = json.loads(status_file.read_text(encoding="utf-8"))
                    observed = str(st.get("state") or "")
                    stage_id = str(st.get("stage_id") or "")
                except Exception:
                    pass

        if not outcome:
            if exit_code == 0:
                outcome = "met"
            elif exit_code == 14:
                outcome = "timeout"
                timed_out = "true"
            elif exit_code in (11, 12):
                outcome = "mismatch"
            else:
                outcome = "error"

        if exit_code == 14:
            timed_out = "true"

        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"state={observed}
")
            f.write(f"observed-state={observed}
")
            f.write(f"observed_state={observed}
")
            f.write(f"outcome={outcome}
")
            f.write(f"exit-code={exit_code}
")
            f.write(f"exit_code={exit_code}
")
            f.write(f"timed-out={timed_out}
")
            f.write(f"timed_out={timed_out}
")
            f.write(f"stage-id={stage_id}
")
            f.write(f"stage_id={stage_id}
")
            if raw_json.strip():
                delim = f"ghdel_{uuid.uuid4().hex}"
                f.write(f"json<<{delim}
{raw_json.strip()}
{delim}
")

        return exit_code, _parse_github_output(gh_out)



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
