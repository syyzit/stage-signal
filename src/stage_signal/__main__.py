"""Support `python -m stage_signal` (equivalent to the `stage-signal` entry point)."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
