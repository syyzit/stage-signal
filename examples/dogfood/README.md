# Dogfood Harnesses & Historical Examples

> **External dogfood harnesses — not part of the `stage-signal` product.**

The scripts and documents in this directory are outer orchestration harnesses developed to dogfood and validate `stage-signal` during early development (0.1.0 through 0.1.7). They illustrate how multi-agent loops, task queues, and parallel worktrees can be constructed on top of the stage contract.

**The published `stage-signal` product is strictly the thin `.stage-signal/` lifecycle contract** (the on-disk format, CLI subcommands, exit code table, and Python library). Outer orchestrator harnesses, task queues, and multi-agent dispatchers are external caller concerns.

For supported, canonical caller integration patterns, see:
- [`docs/CALLER.md`](../../docs/CALLER.md) — Caller Guide (synchronous wait, health watchdog, and agent wrapper loops)
- [`examples/orchestrator-smoke.sh`](../orchestrator-smoke.sh) — Canonical product-acceptance test
- [`examples/orchestrator-watchdog.sh`](../orchestrator-watchdog.sh) — Minimal polling/watchdog loop
- [`examples/github-action-wait.yml`](../github-action-wait.yml) — CI wait workflow reference

---

## Contents

- **`queue-orchestrator.sh`**: Minimal sequential task queue consumer reading markdown queue files.
- **`queue-orchestrator-smoke.sh`**: Acceptance smoke test exercising `queue-orchestrator.sh`.
- **`sample-queue.md`**: Sample markdown task queue file.
- **`multi-cli-loop.sh`**: Multi-agent CLI dispatcher loop driving `agy`, `opencode`, or `mock` agents against a queue.
- **`cli-orchestrator-loop.md`**: Architecture note on driving external CLI loops and queue state.
- **`orchestrator.md`**: Dual-CLI peer orchestrator architecture guide with parallel worktrees and watchdog health checks.
