"""CLI contract tests for `start --meta` (K=V + raw JSON object)."""

from __future__ import annotations

import json

import pytest

from stage_signal.cli import _parse_meta, build_parser, main
from stage_signal.errors import BadArgsError
from stage_signal import Stage


def test_parse_meta_kv_basic() -> None:
    assert _parse_meta(["a=1", "b=2"]) == {"a": "1", "b": "2"}


def test_parse_meta_kv_value_may_contain_equals() -> None:
    assert _parse_meta(["url=a=b=c"]) == {"url": "a=b=c"}


def test_parse_meta_kv_empty_value_ok() -> None:
    assert _parse_meta(["k="]) == {"k": ""}


def test_parse_meta_json_object() -> None:
    assert _parse_meta(['{"ticket": 42, "flag": true}']) == {
        "ticket": 42,
        "flag": True,
    }


def test_parse_meta_json_types_preserved() -> None:
    meta = _parse_meta(['{"n": 1, "f": 1.5, "b": false, "z": null, "o": {"x": [1, 2]}}'])
    assert meta == {"n": 1, "f": 1.5, "b": False, "z": None, "o": {"x": [1, 2]}}


def test_parse_meta_mixed_and_later_wins() -> None:
    meta = _parse_meta(['{"a": 1, "b": 2}', "b=override", '{"a": 99}'])
    assert meta == {"a": 99, "b": "override"}


def test_parse_meta_empty_json_object_is_noop() -> None:
    assert _parse_meta(["{}"]) == {}


def test_parse_meta_rejects_bare_word() -> None:
    with pytest.raises(BadArgsError):
        _parse_meta(["justakey"])


def test_parse_meta_rejects_empty_key() -> None:
    with pytest.raises(BadArgsError):
        _parse_meta(["=v"])


def test_parse_meta_rejects_malformed_json() -> None:
    with pytest.raises(BadArgsError):
        _parse_meta(['{"a": 1'])


def test_parse_meta_rejects_non_object_json() -> None:
    for bad in ('[1, 2]', '"str"', "123", "true", "null"):
        with pytest.raises(BadArgsError):
            _parse_meta([bad])
    # JSON-looking array with leading whitespace still rejected as non-K=V.
    with pytest.raises(BadArgsError):
        _parse_meta(['  [1]'])


def test_start_help_documents_json() -> None:
    parser = build_parser()
    # --meta lives on the `start` subcommand, not top-level: inspect that parser.
    start_parser = None
    for action in parser._actions:
        if hasattr(action, "_name_parser_map") and "start" in action._name_parser_map:
            start_parser = action._name_parser_map["start"]
            break
    assert start_parser is not None
    help_text = start_parser.format_help()
    assert "--meta" in help_text
    assert "JSON" in help_text
    assert "K=V" in help_text


def test_cli_start_meta_end_to_end(tmp_path, monkeypatch) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    assert main(["init", "--project", "p"]) == 0
    assert main(["start", "--stage", "m", "--meta", "a=1",
                 "--meta", '{"b": 2, "flag": true}']) == 0
    st = Stage(str(d)).status()
    assert st["meta"] == {"a": "1", "b": 2, "flag": True}
    # meta merges across starts (existing library behavior still holds)
    assert main(["start", "--stage", "m", "--meta", "c=3"]) == 0
    st2 = Stage(str(d)).status()
    assert st2["meta"] == {"a": "1", "b": 2, "flag": True, "c": "3"}


def test_cli_start_meta_bad_exits_2(tmp_path, monkeypatch, capsys) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    assert main(["init"]) == 0
    capsys.readouterr()
    assert main(["start", "--stage", "m", "--meta", "no-equals"]) == 2
    assert main(["start", "--stage", "m", "--meta", '{"a":']) == 2
    assert main(["start", "--stage", "m", "--meta", "[1,2]"]) == 2
    # failed starts must not clobber meta
    assert Stage(str(d)).status()["meta"] == {}


def test_cli_status_json_roundtrips_meta_types(tmp_path, monkeypatch, capsys) -> None:
    d = tmp_path / ".stage-signal"
    monkeypatch.setenv("STAGE_SIGNAL_DIR", str(d))
    assert main(["init"]) == 0
    assert main(["start", "--stage", "m", "--meta", '{"n": 1}']) == 0
    capsys.readouterr()
    assert main(["status", "--json"]) == 10  # running
    out = capsys.readouterr().out
    assert json.loads(out)["meta"] == {"n": 1}
