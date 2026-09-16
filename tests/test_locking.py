"""Tests for StageStore.locked(): POSIX flock, Windows msvcrt, and fallbacks."""

from __future__ import annotations

import threading
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import stage_signal.store as store_mod
from stage_signal.store import StageStore


def test_locked_live_posix_or_platform(tmp_path: Path) -> None:
    """On POSIX, verify real flock exclusion. On non-POSIX, verify no crash."""
    store = StageStore(tmp_path / ".stage-signal")

    # 1. Exclusive lock
    with store.locked(exclusive=True):
        assert store.lock_path.is_file()
        if store_mod.fcntl is not None:
            # On POSIX: holding exclusive lock must block another non-blocking acquire
            with open(store.lock_path, "a+b") as other_fh:
                with pytest.raises((BlockingIOError, OSError)):
                    store_mod.fcntl.flock(
                        other_fh.fileno(),
                        store_mod.fcntl.LOCK_EX | store_mod.fcntl.LOCK_NB,
                    )

    # After exit, other acquire must succeed on POSIX
    if store_mod.fcntl is not None:
        with open(store.lock_path, "a+b") as other_fh:
            store_mod.fcntl.flock(
                other_fh.fileno(),
                store_mod.fcntl.LOCK_EX | store_mod.fcntl.LOCK_NB,
            )
            store_mod.fcntl.flock(other_fh.fileno(), store_mod.fcntl.LOCK_UN)

    # 2. Shared lock
    with store.locked(exclusive=False):
        assert store.lock_path.is_file()
        if store_mod.fcntl is not None:
            # Holding shared lock allows another shared lock
            with open(store.lock_path, "a+b") as other_fh:
                store_mod.fcntl.flock(
                    other_fh.fileno(),
                    store_mod.fcntl.LOCK_SH | store_mod.fcntl.LOCK_NB,
                )
                store_mod.fcntl.flock(other_fh.fileno(), store_mod.fcntl.LOCK_UN)


def test_locked_posix_calls_flock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify fcntl.flock is called with LOCK_EX/LOCK_SH and unlocked in finally."""
    store = StageStore(tmp_path / ".stage-signal")
    mock_fcntl = MagicMock()
    mock_fcntl.LOCK_EX = 2
    mock_fcntl.LOCK_SH = 1
    mock_fcntl.LOCK_UN = 8

    monkeypatch.setattr(store_mod, "fcntl", mock_fcntl)

    # Exclusive
    with store.locked(exclusive=True):
        pass
    assert mock_fcntl.flock.call_count == 2
    assert mock_fcntl.flock.call_args_list[0][0][1] == mock_fcntl.LOCK_EX
    assert mock_fcntl.flock.call_args_list[1][0][1] == mock_fcntl.LOCK_UN

    mock_fcntl.reset_mock()

    # Shared
    with store.locked(exclusive=False):
        pass
    assert mock_fcntl.flock.call_count == 2
    assert mock_fcntl.flock.call_args_list[0][0][1] == mock_fcntl.LOCK_SH
    assert mock_fcntl.flock.call_args_list[1][0][1] == mock_fcntl.LOCK_UN

    mock_fcntl.reset_mock()

    # Exception in block still unlocks
    with pytest.raises(RuntimeError, match="fail"):
        with store.locked(exclusive=True):
            raise RuntimeError("fail")
    assert mock_fcntl.flock.call_count == 2
    assert mock_fcntl.flock.call_args_list[1][0][1] == mock_fcntl.LOCK_UN


def test_locked_windows_msvcrt_mock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify Windows path uses msvcrt.locking with LK_NBLCK and unlocks with LK_UNLCK."""
    store = StageStore(tmp_path / ".stage-signal")

    mock_msvcrt = types.SimpleNamespace(
        LK_NBLCK=1,
        LK_UNLCK=2,
        locking=MagicMock(),
    )

    monkeypatch.setattr(store_mod, "fcntl", None)
    monkeypatch.setattr(store_mod, "msvcrt", mock_msvcrt)

    # Exclusive lock
    with store.locked(exclusive=True):
        pass

    assert mock_msvcrt.locking.call_count == 2
    fd1, mode1, nbytes1 = mock_msvcrt.locking.call_args_list[0][0]
    assert mode1 == mock_msvcrt.LK_NBLCK
    assert nbytes1 == 1

    fd2, mode2, nbytes2 = mock_msvcrt.locking.call_args_list[1][0]
    assert fd2 == fd1
    assert mode2 == mock_msvcrt.LK_UNLCK
    assert nbytes2 == 1

    mock_msvcrt.locking.reset_mock()

    # Shared lock falls back to exclusive on Windows
    with store.locked(exclusive=False):
        pass

    assert mock_msvcrt.locking.call_count == 2
    assert mock_msvcrt.locking.call_args_list[0][0][1] == mock_msvcrt.LK_NBLCK
    assert mock_msvcrt.locking.call_args_list[1][0][1] == mock_msvcrt.LK_UNLCK

    mock_msvcrt.locking.reset_mock()

    # Exception in block still releases the lock
    with pytest.raises(ValueError, match="boom"):
        with store.locked(exclusive=True):
            raise ValueError("boom")

    assert mock_msvcrt.locking.call_count == 2
    assert mock_msvcrt.locking.call_args_list[1][0][1] == mock_msvcrt.LK_UNLCK


def test_locked_windows_retry_and_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify Windows polling loop retries on contention and raises on deadline."""
    store = StageStore(tmp_path / ".stage-signal")

    attempts = 0

    def fake_locking_contended(fd: int, mode: int, nbytes: int) -> None:
        nonlocal attempts
        if mode == 1:  # LK_NBLCK
            attempts += 1
            if attempts < 3:
                raise OSError(13, "Permission denied")
        # mode 2: LK_UNLCK or successful LK_NBLCK

    mock_msvcrt = types.SimpleNamespace(
        LK_NBLCK=1,
        LK_UNLCK=2,
        locking=fake_locking_contended,
    )

    monkeypatch.setattr(store_mod, "fcntl", None)
    monkeypatch.setattr(store_mod, "msvcrt", mock_msvcrt)
    monkeypatch.setattr("time.sleep", lambda s: None)

    # Slower retry succeeds
    with store.locked(exclusive=True):
        assert attempts == 3

    # Deadline timeout raises OSError
    def fake_locking_always_fails(fd: int, mode: int, nbytes: int) -> None:
        if mode == 1:
            raise OSError(13, "Permission denied")

    mock_msvcrt.locking = fake_locking_always_fails

    # Make monotonic clock jump past deadline
    fake_time = 0.0

    def fake_monotonic() -> float:
        nonlocal fake_time
        fake_time += 5.0
        return fake_time

    monkeypatch.setattr("time.monotonic", fake_monotonic)

    with pytest.raises(OSError, match="Permission denied"):
        with store.locked(exclusive=True):
            pass


def test_locked_fallback_when_neither(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When neither fcntl nor msvcrt is present, locked() yields without crashing."""
    store = StageStore(tmp_path / ".stage-signal")

    monkeypatch.setattr(store_mod, "fcntl", None)
    monkeypatch.setattr(store_mod, "msvcrt", None)

    executed = False
    with store.locked(exclusive=True):
        executed = True
    assert executed

    executed_sh = False
    with store.locked(exclusive=False):
        executed_sh = True
    assert executed_sh


@pytest.mark.parametrize("exclusive", [True, False])
def test_locked_serializes_threads_by_resolved_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exclusive: bool
) -> None:
    store = StageStore(tmp_path / ".stage-signal")
    other = StageStore(tmp_path / "alias" / ".." / ".stage-signal")
    (tmp_path / "alias").mkdir()
    mock_fcntl = MagicMock()
    monkeypatch.setattr(store_mod, "fcntl", mock_fcntl)
    attempted = threading.Event()
    entered = threading.Event()

    def acquire_other() -> None:
        attempted.set()
        with other.locked(exclusive=exclusive):
            entered.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with store.locked(exclusive=exclusive):
            future = pool.submit(acquire_other)
            assert attempted.wait(timeout=5)
            assert not entered.wait(timeout=0.1)
            assert mock_fcntl.flock.call_count == 1
        future.result(timeout=5)
    assert entered.is_set()
    assert mock_fcntl.flock.call_count == 4


def test_locked_seeds_empty_lockfile(tmp_path: Path) -> None:
    store = StageStore(tmp_path / ".stage-signal")
    store.locks_dir.mkdir(parents=True)
    store.lock_path.touch()
    with store.locked():
        assert store.lock_path.read_bytes() == b"\0"
