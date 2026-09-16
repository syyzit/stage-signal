"""Concurrency test: parallel heartbeats keep schema valid, no event loss (M1)."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from stage_signal import Stage


def test_concurrent_heartbeats(tmp_path: Path) -> None:
    d = tmp_path / ".stage-signal"
    Stage(d).init(project="conc")
    Stage(d).start(stage="m")

    n_threads, n_beats = 8, 25
    errors: list[Exception] = []

    def worker(i: int) -> None:
        try:
            s = Stage(d)
            for j in range(n_beats):
                s.heartbeat(note=f"t{i}-b{j}")
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    final = Stage(d).status()
    assert final["state"] == "running"
    assert final["heartbeat_at"]
    lines = (d / "events.jsonl").read_text().strip().splitlines()
    # init + start + all heartbeats, none lost
    assert len(lines) == 2 + n_threads * n_beats
    for line in lines:  # every line is valid JSON with required keys
        obj = json.loads(line)
        assert {"ts", "type", "state", "attempt"} <= set(obj)
