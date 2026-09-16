# Prior art — why `stage-signal` exists

**Ship name:** `stage-signal` (concept name in early docs: "agent-done").
**Rule:** compose with existing tools; do not rebuild them.

## Closest projects (reviewed 2026-09-16)

| Project | What it solves | Overlap | Gap vs our need |
|--------|----------------|---------|-----------------|
| [agent-done-or-not](https://github.com/mohamedzhioua/agent-done-or-not) | Proof-of-done: agent cannot claim success without fresh passing test receipts (Stop hooks, ledger, CI `assert`/`verify`) | "done" semantics, ledger idea | No generic stage lifecycle (`queued`/`running`/`blocked`) for an **external** watchdog; focused on verification honesty, not orchestrator polling |
| [julsemaan/agent-status](https://github.com/julsemaan/agent-status) | Local agent **presence** snapshots (`running`/`stopped`), heartbeat, prune; A2A-inspired JSON | Filesystem status + CLI, heartbeat | Process/agent oriented, not **milestone/stage** oriented; no `blocked` free-tier contract; not designed as cross-harness stage handoff for overnight queues |
| [paulvandermeijs/agent-status](https://github.com/paulvandermeijs/agent-status) | tmux indicator: which session waits on the human | "done/working" labels | Human tmux UX, not machine-readable stage completion for cron |
| StackAI `.agent/status.json` (in-tree) | Persist phase/exit after containerized agent runs | `status.json` idea | Tied to that stack; not standalone/installable |
| [claude-lane-stack](https://github.com/VKirill/claude-lane-stack), [klasp](https://github.com/klasp-dev/klasp), [agent-wave-orchestrator](https://github.com/chllming/agent-wave-orchestrator) | Rich acceptance receipts, waves, merge gates | "done ≠ exit 0" philosophy | Full orchestrator platforms — too heavy for a 1-day tiny OSS; contracts are internal |
| OpenCode / Claude Code hooks (`session.idle`, `Stop`) | Event-driven continuation inside one harness | Can advance phases | Harness-specific; a Mac cron orchestrator cannot subscribe without embedding that runtime |

## Verdict

1. **Do not rebuild `agent-done-or-not`.** It owns *verification honesty*
   (proof-of-tests). `stage-signal done` means *lifecycle success*; when proof
   matters, run `agent-done-or-not capture` first and reference its receipt in
   our `proof` field (see `docs/COMPOSE.md`).
2. **Do not rebuild a full orchestrator** (lane-stack / wave / klasp).
3. **The remaining niche is real:** a tiny, harness-agnostic **stage lifecycle
   contract** for *external* watchdogs that poll without watching a TUI:
   - States: `queued | running | done | blocked | failed`
   - CLI: `init / start / heartbeat / note / artifact / done / blocked / fail / status / wait / clear-terminal / doctor`
   - Stable exit codes for shell (`0,1,2,3,10,11,12,13,14,15`)
   - Filesystem is the API: `STATUS.json` + append-only `events.jsonl`

## Name decision (frozen in M0)

- Ship as **`stage-signal`** on PyPI / CLI (`stage-signal` command).
- `agent-done` remains the *concept* title in early planning docs only.
- Rationale: avoids collision with `agent-done-or-not` on npm/PyPI and
  signals the narrower scope (one stage's signal, not proof of correctness).

## Interop posture

- **Primary:** greenfield narrow scope, Python 3.11+ stdlib-only core.
- **Compose:** optional `--require-proof` / `proof` field pointing at an
  `agent-done-or-not` receipt; optional `--write-status-mirror` mirror for
  `.orch/STATUS.md` + `DONE`.
- **No vendoring** of proof logic in v1 (defer always).
