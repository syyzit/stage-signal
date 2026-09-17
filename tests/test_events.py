"""Library + CLI tests for the events.jsonl read path (issue #79)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stage_signal import (
    BadArgsError,
    CorruptStatusError,
    EVENT_RECORD_KEYS,
    NotInitialized,
    Stage,
)
from stage_signal.cli import build_parser, main
from stage_signal.constants import EVENT_TYPES, EVENTS_DEFAULT_TAIL


@pytest.fixture()
def stage(tmp_path: Path) -> Stage:
    s = Stage(tmp_path / ".stage-signal")
    s.init(project="testproj")
    return s


def _subparser(name: str):
    parser = build_parser()
    for action in parser._actions:
        if hasattr(action, "_name_parser_map") and name in action._name_parser_map:
            return action._name_parser_map[name]
    raise AssertionError(f"missing subparser {name!r}")


def _assert_frozen_keys(events: list[dict]) -> None:
    assert events
    for event in events:
        for key in EVENT_RECORD_KEYS:
            assert key in event, f"key {key!r} missing from event {event!r}"


def _seed_mixed(stage: Stage) -> list[str]:
    """init + start + heartbeat + note + artifact + fail + clear-terminal."""
    stage.start(stage="m1")
    stage.heartbeat(note="tick")
    stage.note("checkpoint")
    stage.artifact("out.bin", label="bin")
    stage.fail("boom")
    stage.clear_terminal()
    return [e["type"] for e in stage.events()]


def test_events_help_in_cli() -> None:
    top = build_parser().format_help()
    assert "events" in top
    assert "newest last" in " ".join(top.lower().split())
    help_text = _subparser("events").format_help()
    help_flat = " ".join(help_text.split())
    help_compact = "".join(help_text.split())
    assert "newest last" in help_flat.lower()
    assert "--tail" in help_text
    assert "--type" in help_text
    assert "--json" in help_text
    assert "JSON array" in help_text
    assert "not NDJSON" in help_text
    for event_type in EVENT_TYPES:
        assert event_type in help_compact
    assert str(EVENTS_DEFAULT_TAIL) in help_text
    assert "0 = all" in help_text


def test_events_every_record_has_frozen_keys(stage: Stage) -> None:
    """Library lifecycle events always carry all EVENT_RECORD_KEYS (#105)."""
    assert stage.events(type="init")[0].keys() >= set(EVENT_RECORD_KEYS)
    stage.start(stage="m1")
    stage.heartbeat(note="tick")
    stage.note("checkpoint")
    stage.artifact("out.bin", label="bin")
    stage.done(summary="ok")
    disk_events = [
        json.loads(line)
        for line in (stage.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    _assert_frozen_keys(disk_events)
    assert stage.events() == disk_events
    _assert_frozen_keys(stage.events(tail=2))
    _assert_frozen_keys(stage.events(type="heartbeat"))


def test_events_reclaim_trail_has_frozen_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """reclaim's failed + clear_terminal events carry all frozen keys (#105)."""
    stage = Stage(tmp_path / ".stage-signal")
    stage.init(project="p")
    stage.start(stage="m")
    monkeypatch.setattr("stage_signal.stage._is_pid_alive", lambda pid: False)
    stage.reclaim("dead pid")
    disk_events = [
        json.loads(line)
        for line in (stage.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [e["type"] for e in disk_events] == [
        "init", "start", "failed", "clear_terminal",
    ]
    _assert_frozen_keys(disk_events)
    assert stage.events() == disk_events


def test_cli_events_json_is_array_with_frozen_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """events --json is one JSON array, newest last, honoring --type/--tail (#105)."""
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    stage = Stage(d)
    stage.init(project="p")
    stage.start(stage="m1")
    stage.heartbeat(note="first tick")
    stage.note("checkpoint")
    stage.heartbeat(note="tick")
    stage.done(summary="ok")
    capsys.readouterr()

    assert main(["events", "--json", "--tail", "0"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list)
    assert all(isinstance(e, dict) for e in payload)
    _assert_frozen_keys(payload)
    assert [e["type"] for e in payload] == [
        "init", "start", "heartbeat", "note", "heartbeat", "done",
    ]
    assert payload == stage.events()

    assert main(["events", "--json", "--tail", "2"]) == 0
    assert json.loads(capsys.readouterr().out) == payload[-2:]

    assert main(["events", "--json", "--type", "heartbeat", "--tail", "1"]) == 0
    beats = json.loads(capsys.readouterr().out)
    assert isinstance(beats, list)
    assert [e["type"] for e in beats] == ["heartbeat"]
    assert beats[-1]["message"] == "tick"
    _assert_frozen_keys(beats)

    assert beats == stage.events(type="heartbeat", tail=1)

    assert main(["events", "--json", "--type", "failed"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_events_tolerate_unknown_keys(
    stage: Stage, capsys: pytest.CaptureFixture[str]
) -> None:
    event = stage.events()[0]
    event["future_field"] = {"extra": True}
    with stage._store.locked():
        stage._store.append_event(event)
    assert stage.events(tail=1) == [event]
    assert main(["--dir", str(stage.dir), "events", "--json", "--tail", "1"]) == 0
    assert json.loads(capsys.readouterr().out) == [event]


def test_library_events_not_initialized(tmp_path: Path) -> None:
    s = Stage(tmp_path / ".stage-signal")
    with pytest.raises(NotInitialized) as exc:
        s.events()
    assert exc.value.exit_code == 15


def test_library_events_empty_log(tmp_path: Path) -> None:
    s = Stage(tmp_path / ".stage-signal")
    s.init(project="p")
    (s.dir / "events.jsonl").write_text("", encoding="utf-8")
    assert s.events() == []
    assert s.events(tail=20) == []
    assert s.events(tail=0) == []
    assert s.events(type="init") == []


def test_library_events_mixed_types_tail_and_type(stage: Stage) -> None:
    types = _seed_mixed(stage)
    assert types == [
        "init", "start", "heartbeat", "note", "artifact", "failed", "clear_terminal",
    ]
    all_events = stage.events()
    assert [e["type"] for e in all_events] == types
    # newest last: last element is the most recent
    assert all_events[-1]["type"] == "clear_terminal"
    assert [e["type"] for e in stage.events(tail=2)] == ["failed", "clear_terminal"]
    assert [e["type"] for e in stage.events(tail=0)] == types
    assert [e["type"] for e in stage.events(tail=None)] == types
    notes = stage.events(type="note")
    assert len(notes) == 1
    assert notes[0]["message"] == "checkpoint"
    failed = stage.events(type="failed", tail=1)
    assert [e["type"] for e in failed] == ["failed"]
    assert failed[0]["message"] == "boom"


def test_library_events_type_filter_before_tail(stage: Stage) -> None:
    """--type then --tail: an early failed event is still returned."""
    stage.fail("early")
    stage.start(stage="m")
    for i in range(5):
        stage.heartbeat(note=f"h{i}")
    stage.done(summary="ok")
    # last 2 overall are heartbeats/done — failed is early
    last_two = [e["type"] for e in stage.events(tail=2)]
    assert "failed" not in last_two
    found = stage.events(type="failed", tail=1)
    assert len(found) == 1
    assert found[0]["message"] == "early"


def test_library_events_invalid_args(stage: Stage) -> None:
    with pytest.raises(BadArgsError) as exc:
        stage.events(type="not-a-type")
    assert exc.value.exit_code == 2
    with pytest.raises(BadArgsError):
        stage.events(tail=-1)
    with pytest.raises(BadArgsError):
        stage.events(tail=True)  # type: ignore[arg-type]


def test_library_events_corrupt_line_fail_closed(stage: Stage) -> None:
    path = stage.dir / "events.jsonl"
    path.write_text(
        path.read_text(encoding="utf-8") + "{not json\n",
        encoding="utf-8",
    )
    with pytest.raises(CorruptStatusError) as exc:
        stage.events()
    assert exc.value.exit_code == 1
    assert "line" in str(exc.value)


def test_library_events_deepcopy_isolation(stage: Stage) -> None:
    events = stage.events()
    assert events
    events[0]["message"] = "mutated"
    reread = stage.events()
    assert reread[0]["message"] != "mutated"


def test_cli_events_not_initialized(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["--dir", str(tmp_path / "missing" / ".stage-signal"), "events"])
    assert rc == 15
    err = capsys.readouterr().err
    assert "not initialized" in err.lower() or "missing" in err.lower()


def test_cli_events_empty_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    assert main(["init", "--project", "p"]) == 0
    (d / "events.jsonl").write_text("", encoding="utf-8")
    capsys.readouterr()
    assert main(["events"]) == 0
    out = capsys.readouterr().out
    assert out == ""
    assert main(["events", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == []


def test_cli_events_mixed_tail_type_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    stage = Stage(d)
    stage.init(project="p")
    types = _seed_mixed(stage)
    capsys.readouterr()

    assert main(["events", "--tail", "0"]) == 0
    human = capsys.readouterr().out.strip().splitlines()
    assert len(human) == len(types)
    assert human[-1].split()[1] == "clear_terminal"  # newest last
    assert "init" in human[0]

    assert main(["events", "--tail", "2"]) == 0
    last_two = capsys.readouterr().out.strip().splitlines()
    assert len(last_two) == 2
    assert "failed" in last_two[0]
    assert "clear_terminal" in last_two[1]

    assert main(["events", "--type", "note"]) == 0
    note_lines = capsys.readouterr().out.strip().splitlines()
    assert len(note_lines) == 1
    assert "checkpoint" in note_lines[0]

    assert main(["events", "--json", "--tail", "0"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list)
    assert [e["type"] for e in payload] == types
    # JSON array, not NDJSON (pretty-printed object-per-line would fail json.loads
    # of the whole stdout if more than one top-level value).
    assert all(isinstance(e, dict) for e in payload)

    assert main(["events", "--json", "--type", "failed", "--tail", "1"]) == 0
    failed = json.loads(capsys.readouterr().out)
    assert len(failed) == 1
    assert failed[0]["type"] == "failed"
    assert failed[0]["message"] == "boom"


def test_cli_events_default_tail_is_20(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    stage = Stage(d)
    stage.init(project="p")
    stage.start(stage="m")
    for i in range(EVENTS_DEFAULT_TAIL + 3):
        stage.note(f"n{i}")
    total = len(stage.events())
    assert total > EVENTS_DEFAULT_TAIL
    capsys.readouterr()
    assert main(["events"]) == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(lines) == EVENTS_DEFAULT_TAIL
    assert main(["events", "--tail", "0"]) == 0
    all_lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(all_lines) == total


def test_cli_events_corrupt_line_exit_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    assert main(["init"]) == 0
    (d / "events.jsonl").write_text("{not json\n", encoding="utf-8")
    capsys.readouterr()
    assert main(["events"]) == 1
    assert "corrupt" in capsys.readouterr().err.lower()


def test_cli_events_invalid_type_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    assert main(["init"]) == 0
    with pytest.raises(SystemExit) as exc:
        main(["events", "--type", "not-a-type"])
    assert exc.value.code == 2


def test_cli_events_negative_tail_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    assert main(["init"]) == 0
    with pytest.raises(SystemExit) as exc:
        main(["events", "--tail", "-1"])
    assert exc.value.code == 2
