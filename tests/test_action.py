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
    """Execute the wait step script from action.yml in a subshell."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        gh_out = Path(td) / "gh_output"
        gh_out.touch()

        script = f"""
set -e
DIR="{stage_dir}"
STATE="{state}"
TIMEOUT="{timeout}"
POLL="{poll}"

ARGS=("--state" "$STATE" "--timeout" "$TIMEOUT")
if [ -n "$POLL" ]; then
  ARGS+=("--poll" "$POLL")
fi

TMP_OUT=$(mktemp)
HAS_JSON=false
if stage-signal wait --help 2>&1 | grep -q -- '--json'; then
  HAS_JSON=true
fi
if [ "{str(force_no_json).lower()}" = "true" ]; then
  HAS_JSON=false
fi

set +e
if [ "$HAS_JSON" = "true" ]; then
  stage-signal --dir "$DIR" wait --json "${{ARGS[@]}}" > "$TMP_OUT"
  EXIT_CODE=$?
else
  stage-signal --dir "$DIR" wait "${{ARGS[@]}}"
  EXIT_CODE=$?
fi
set -e

if [ -s "$TMP_OUT" ]; then
  cat "$TMP_OUT"
fi

python -c "import sys, textwrap; exec(textwrap.dedent(sys.stdin.read()))" << 'EOF' "$TMP_OUT" "$EXIT_CODE" "$DIR"
import json, os, sys, uuid

json_path, exit_code_str, dir_path = sys.argv[1], sys.argv[2], sys.argv[3]
exit_code = int(exit_code_str)
gh_output = os.environ.get("GITHUB_OUTPUT")

state = ""
outcome = ""
timed_out = "false"
stage_id = ""
raw_json = ""

if os.path.exists(json_path):
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            raw_json = f.read()
        if raw_json.strip():
            data = json.loads(raw_json)
            state = str(data.get("state") or data.get("observed_state") or "")
            outcome = str(data.get("outcome") or "")
            exit_code = int(data.get("exit_code", exit_code))
            timed_out = "true" if data.get("timeout") else "false"
            stage_id = str(data.get("stage_id") or "")
    except Exception:
        pass

if not state:
    status_file = os.path.join(dir_path, "STATUS.json")
    if os.path.exists(status_file):
        try:
            with open(status_file, "r", encoding="utf-8") as f:
                st = json.load(f)
            state = str(st.get("state") or "")
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

if gh_output:
    with open(gh_output, "a", encoding="utf-8") as f:
        f.write(f"state={{state}}\\n")
        f.write(f"observed-state={{state}}\\n")
        f.write(f"observed_state={{state}}\\n")
        f.write(f"outcome={{outcome}}\\n")
        f.write(f"exit-code={{exit_code}}\\n")
        f.write(f"exit_code={{exit_code}}\\n")
        f.write(f"timed-out={{timed_out}}\\n")
        f.write(f"timed_out={{timed_out}}\\n")
        f.write(f"stage-id={{stage_id}}\\n")
        f.write(f"stage_id={{stage_id}}\\n")
        if raw_json.strip():
            delim = f"ghdel_{{uuid.uuid4().hex}}"
            f.write(f"json<<{{delim}}\\n{{raw_json.strip()}}\\n{{delim}}\\n")
EOF
rm -f "$TMP_OUT"

exit $EXIT_CODE
"""
        env = dict(os.environ)
        env["GITHUB_OUTPUT"] = str(gh_out)
        # Windows CI: use os.pathsep and Scripts; a hard-coded ":" corrupts PATH
        # so `stage-signal` is not found and bash exits 1 for every wait code.
        path_prefix = []
        for candidate in (ROOT / ".venv" / "bin", ROOT / ".venv" / "Scripts"):
            if candidate.is_dir():
                path_prefix.append(str(candidate))
        env["PATH"] = os.pathsep.join([*path_prefix, env.get("PATH", "")])

        proc = subprocess.run(
            ["bash", "-c", script],
            env=env,
            capture_output=True,
            text=True,
        )
        outputs = _parse_github_output(gh_out)
        return proc.returncode, outputs


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
