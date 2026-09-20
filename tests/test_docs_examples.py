"""Execute the documentation.

`docs/CALLER.md` shipped a `stage-signal artifact --kind patch --path ...`
invocation that exits 2 (issue #209): the guide the README points external
callers at contained a command that cannot run. Nothing caught it, because
nothing ever ran the docs. These tests do two things:

1. Parse **every** `stage-signal ...` invocation that appears in a fenced block
   in README.md / docs/CALLER.md against the real argparse parser, so a
   non-existent flag fails the build the hour it lands.
2. Actually execute curated versions of the three Caller Guide patterns and the
   README quick start against a real `.stage-signal/` dir, asserting the exit
   codes the docs promise.
"""

from __future__ import annotations

import contextlib
import io
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from stage_signal.cli import build_parser


ROOT = Path(__file__).resolve().parent.parent
DOC_FILES = ["README.md", "docs/CALLER.md"]

# Docs fences are POSIX sh/bash. On Windows GitHub runners `bash` is often the
# WSL install stub (UTF-16 "install me" message, exit 1) — not a real shell.
# Product behavior on Windows is covered by the wheel smoke job + core suite.
needs_posix_bash = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="POSIX bash required (Windows covered by smoke-from-wheel)",
)

_FENCE = re.compile(r"^```(\w*)\s*$")
# Shell expansions we cannot evaluate statically. "0" keeps the surrounding
# argv shape intact and satisfies both string and numeric argparse types
# (--pid, --timeout, --poll), so only genuine flag/arity errors surface.
_EXPANSION = re.compile(r"\$\([^)]*\)|\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*|\$\$|\$\?")
_EXPANSION_PLACEHOLDER = "0"
_SEPARATORS = re.compile(r"&&|\|\||[;|&]")


def _fenced_blocks(path: Path, languages: tuple[str, ...]) -> list[str]:
    blocks: list[str] = []
    current: list[str] | None = None
    inside_fence = False
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _FENCE.match(line)
        if match:
            if inside_fence:
                if current is not None:
                    blocks.append("\n".join(current))
                current = None
                inside_fence = False
            else:
                inside_fence = True
                current = [] if match.group(1) in languages else None
            continue
        if current is not None:
            current.append(line)
    return blocks


def _doc_blocks(languages: tuple[str, ...]) -> list[tuple[str, str]]:
    out = []
    for rel in DOC_FILES:
        for block in _fenced_blocks(ROOT / rel, languages):
            out.append((rel, block))
    return out


def _stage_signal_invocations(block: str) -> list[str]:
    """Pull every `stage-signal ...` command out of a block, comments included.

    Commented-out lines (`# stage-signal blocked --reason "..."`) are documented
    commands too — a reader copies them just as readily.
    """
    text = block.replace("\\\n", " ")
    found: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        line = re.sub(r"^#+\s*", "", line)
        if "stage-signal" not in line:
            continue
        for part in _SEPARATORS.split(line):
            part = part.strip()
            if not part.startswith("stage-signal"):
                continue
            # Drop a trailing inline comment, then redirections.
            part = part.split(" # ", 1)[0]
            part = re.sub(r"\s*[12]?>{1,2}\s*\S+", "", part)
            found.append(part.strip())
    return found


def _argv_for_parser(command: str) -> list[str] | None:
    """Tokenize a documented command into argv, or None if it is not parseable text."""
    neutralized = _EXPANSION.sub(_EXPANSION_PLACEHOLDER, command)
    try:
        tokens = shlex.split(neutralized)
    except ValueError:
        return None
    assert tokens[0] == "stage-signal"
    argv = tokens[1:]
    if not argv or argv[0] == "--help":
        return None
    return argv


def _documented_commands() -> list[tuple[str, str]]:
    seen: dict[str, str] = {}
    for rel, block in _doc_blocks(("bash", "sh", "shell", "console")):
        for command in _stage_signal_invocations(block):
            seen.setdefault(command, rel)
    return sorted((cmd, rel) for cmd, rel in seen.items())


DOCUMENTED_COMMANDS = _documented_commands()


def test_docs_contain_commands_to_check() -> None:
    """Guard against the extractor silently matching nothing."""
    assert len(DOCUMENTED_COMMANDS) >= 20


@pytest.mark.parametrize("command,source", DOCUMENTED_COMMANDS, ids=lambda v: v[:60])
def test_documented_command_parses(command: str, source: str) -> None:
    """Every documented invocation must survive argparse (i.e. never exit 2)."""
    argv = _argv_for_parser(command)
    if argv is None:
        pytest.skip("not a parseable invocation")
    parser = build_parser()
    with contextlib.redirect_stderr(io.StringIO()) as err:
        try:
            parser.parse_args(argv)
        except SystemExit as exc:  # pragma: no cover - only on a doc bug
            pytest.fail(
                f"{source}: `{command}` exits {exc.code} instead of running.\n"
                f"{err.getvalue()}"
            )


@needs_posix_bash
@pytest.mark.parametrize(
    "source,block",
    _doc_blocks(("bash", "sh", "shell")),
    ids=lambda v: v[:40].replace("\n", " "),
)
def test_doc_bash_block_is_valid_shell(source: str, block: str) -> None:
    proc = subprocess.run(
        ["bash", "-n"], input=block, capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, f"{source}: shell syntax error\n{proc.stderr}"


# --- Curated end-to-end runs of the documented patterns -------------------


@pytest.fixture()
def shell_env(tmp_path: Path) -> dict[str, str]:
    """A PATH with a `stage-signal` shim pointing at the code under test."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shim = bin_dir / "stage-signal"
    shim.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" -m stage_signal "$@"\n', encoding="utf-8"
    )
    shim.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["PYTHONPATH"] = str(ROOT / "src")
    return env


def _run_script(script: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", script], cwd=cwd, env=env, capture_output=True, text=True, timeout=120
    )


@needs_posix_bash
def test_caller_agent_wrapper_runs_to_done(tmp_path: Path, shell_env: dict[str, str]) -> None:
    """docs/CALLER.md §3: init -> start -> note -> artifact -> done, exit 0 throughout."""
    work = tmp_path / "work"
    work.mkdir()
    (work / "changes.diff").write_text("diff --git a/x b/x\n", encoding="utf-8")
    script = """
set -eu
stage-signal init
stage-signal start --stage "issue-42" --session "agent-run-1" --pid $$
stage-signal note "Running test suite"
stage-signal artifact changes.diff --label patch
stage-signal done --summary "Fixed issue #42 and passed regression tests"
stage-signal status --json
"""
    proc = _run_script(script, work, shell_env)
    assert proc.returncode == 0, proc.stderr
    assert '"state": "done"' in proc.stdout


@needs_posix_bash
def test_caller_supervise_is_terminal(tmp_path: Path, shell_env: dict[str, str]) -> None:
    """docs/CALLER.md §3 alternative path: supervise concludes the stage itself.

    This is why the guide no longer shows `supervise` mid-script: afterwards the
    stage is terminal, so a following `note` is an illegal transition (exit 3).
    """
    work = tmp_path / "work"
    work.mkdir()
    script = """
set -eu
stage-signal init
stage-signal start --stage "issue-42" --session "agent-run-1" --pid $$
stage-signal supervise --every 30 -- true
"""
    proc = _run_script(script, work, shell_env)
    assert proc.returncode == 0, proc.stderr

    after = subprocess.run(
        ["bash", "-c", 'stage-signal note "after supervise"'],
        cwd=work, env=shell_env, capture_output=True, text=True, timeout=60,
    )
    assert after.returncode == 3, (after.returncode, after.stdout, after.stderr)


@needs_posix_bash
def test_caller_wait_exit_codes(tmp_path: Path, shell_env: dict[str, str]) -> None:
    """docs/CALLER.md §1 summary table.

    `--state terminal` exits 0 for done/blocked/failed alike (outcome `met`);
    only `--state done` turns blocked/failed into distinguishable 11/12. The
    guide claimed the former behaved like the latter until issue #209.
    """
    work = tmp_path / "work"
    work.mkdir()
    cases = [
        ('stage-signal blocked --reason "external dep"', 11),
        ('stage-signal fail --reason "compile error"', 12),
    ]
    _run_script("set -eu; stage-signal init", work, shell_env)

    done = _run_script(
        'set -eu\nstage-signal start --stage s0 --pid $$\nstage-signal done --summary ok\n'
        "stage-signal wait --state terminal --timeout 1",
        work, shell_env,
    )
    assert done.returncode == 0, done.stderr

    for terminal_cmd, expected in cases:
        _run_script("set -eu; stage-signal clear-terminal", work, shell_env)
        setup = f"set -eu\nstage-signal start --stage s --pid $$\n{terminal_cmd}\n"
        # --state terminal is satisfied by any terminal state: exit 0, not 11/12.
        any_terminal = _run_script(
            setup + "stage-signal wait --state terminal --timeout 1", work, shell_env
        )
        assert any_terminal.returncode == 0, (terminal_cmd, any_terminal.returncode)
        # --state done is what makes the outcome readable from the exit code.
        specific = _run_script(
            "stage-signal wait --state done --timeout 1", work, shell_env
        )
        assert specific.returncode == expected, (terminal_cmd, specific.returncode, specific.stderr)

    _run_script("set -eu; stage-signal clear-terminal", work, shell_env)
    timeout = _run_script(
        "stage-signal wait --state terminal --timeout 1 --poll 0.1", work, shell_env
    )
    assert timeout.returncode == 14, (timeout.returncode, timeout.stderr)


@needs_posix_bash
def test_stale_terminal_race_and_documented_workaround(
    tmp_path: Path, shell_env: dict[str, str]
) -> None:
    """The race README/CALLER now warn about, and the fix they prescribe.

    A leftover terminal state from stage-A satisfies `wait --state terminal`
    immediately while stage-B has not started; `clear-terminal` is what makes
    the wait honest.
    """
    work = tmp_path / "work"
    work.mkdir()
    _run_script(
        'set -eu\nstage-signal init\nstage-signal start --stage stage-A --pid $$\n'
        'stage-signal done --summary "A finished"',
        work, shell_env,
    )

    stale = _run_script(
        "stage-signal wait --json --state terminal --timeout 2 --poll 0.1", work, shell_env
    )
    assert stale.returncode == 0
    assert '"stage_id": "stage-A"' in stale.stdout, stale.stdout

    _run_script("set -eu; stage-signal clear-terminal", work, shell_env)
    cleared = _run_script(
        "stage-signal wait --state terminal --timeout 1 --poll 0.1", work, shell_env
    )
    assert cleared.returncode == 14, (cleared.returncode, cleared.stderr)


@needs_posix_bash
def test_done_is_legal_from_idle_queued(tmp_path: Path, shell_env: dict[str, str]) -> None:
    """The second route to an unearned `done` the docs now name (SPEC §13.30)."""
    work = tmp_path / "work"
    work.mkdir()
    proc = _run_script(
        'set -eu\nstage-signal init\nstage-signal done --summary "never started"\n'
        "stage-signal status --json",
        work, shell_env,
    )
    assert proc.returncode == 0, proc.stderr
    assert '"state": "done"' in proc.stdout
    assert '"stage_id": null' in proc.stdout, proc.stdout
