# Roadmap to 1.0 — Contract Freeze Map, Cut-List, and Done Bar

## 1. Product Thesis & Scope

`stage-signal` is a **thin, boring stage lifecycle contract**:
- **On-disk layout:** `.stage-signal/` (`STATUS.json`, `STATUS.md`, `events.jsonl`, `locks/stage.lock`).
- **Atomic state machine:** `queued` → `running` → `done` | `blocked` | `failed`, with clean abandon/reset (`clear-terminal`) and one-shot watchdog recovery (`reclaim`).
- **Deterministic observer contract:** normalized exit codes (0, 1, 2, 3, 10, 11, 12, 13, 14, 15) and machine-readable JSON snapshots (`status --json`, `doctor --json`, `wait --json`).
- **Python client library:** stdlib-first `Stage` class and primitives for embedding.

### What is the product?
The product is **strictly** the `.stage-signal/` filesystem contract, CLI, and Python library.

### What is NOT the product?
`stage-signal` is **not** an agent orchestrator, not a multi-agent cockpit, not a task queue runner, and not a terminal UI watcher. Outer harnesses like AGLoop, Museloop, worktree managers, or queue consumers are external callers, not part of the published package.

---

## 2. Contract Freeze Map (§13.x vs Public CLI / API)

All normative requirements for `schema_version: 1` are locked across §13.1 through §13.42 in `docs/SPEC.md`. Every public CLI command in `CLI_SUBCOMMANDS` (15 total) and every public instance method on `Stage` in `STAGE_PUBLIC_METHODS` (15 total) maps directly to one or more frozen sections.

### Architecture Layer 1: Core Schema, Storage & Layout

| §13.x Section | Frozen Constants / Enums | Public CLI Surface | Public API / Exports | Freeze Status |
|---|---|---|---|---|
| **§13.1** Additive-only policy | `SCHEMA_VERSION = 1` | `--version` | `SCHEMA_VERSION` | Frozen |
| **§13.2** STATUS.json required keys | `STATUS_REQUIRED_KEYS` (23 keys) | `init`, `status` | `STATUS_REQUIRED_KEYS` | Frozen |
| **§13.3** JSON contract keys | `STATUS_JSON_KEYS` (23 disk + dynamic) | `status --json` | `STATUS_JSON_KEYS` | Frozen |
| **§13.7** Artifact & note entry keys | `ARTIFACT_ENTRY_KEYS`, `NOTE_ENTRY_KEYS` | `artifact`, `note` | `ARTIFACT_ENTRY_KEYS`, `NOTE_ENTRY_KEYS` | Frozen |
| **§13.9** result / error object keys | `RESULT_KEYS`, `ERROR_KEYS`, `ERROR_KINDS` | `done`, `blocked`, `fail` | `RESULT_KEYS`, `ERROR_KEYS`, `ERROR_KINDS` | Frozen |
| **§13.10** Proof object keys & enum | `PROOF_KEYS`, `PROOF_VERIFIED_VALUES` | `done --proof-ref` | `PROOF_KEYS`, `PROOF_VERIFIED_VALUES` | Frozen |
| **§13.13** On-disk layout paths | `DEFAULT_DIR_NAME`, `STATUS_FILENAME`, etc. | `--dir PATH` | `DEFAULT_DIR_NAME`, `StageStore`, etc. | Frozen |
| **§13.14** Environment vars & defaults | `ENV_DIR`, `DEFAULT_STALE_THRESHOLD`, etc. | `$STAGE_SIGNAL_*` | `ENV_VARS`, `ENV_DIR`, timing constants | Frozen |
| **§13.18** STATUS.md human mirror | `STATUS_MD_REQUIRED_HEADINGS` | Automatic mirror | `render_status_md`, headings constants | Frozen |
| **§13.40** Concurrency & locking | `StageStore.locked` / file locks | All mutating commands | `StageStore.locked`, `LOCKS_DIRNAME` | Frozen |

### Architecture Layer 2: Lifecycle State Machine & Typing

| §13.x Section | Frozen Constants / Enums | Public CLI Surface | Public API / Exports | Freeze Status |
|---|---|---|---|---|
| **§13.4** Exit-code table freeze | `EXIT_CODES` (0, 1, 2, 3, 10-15) | All subcommands | `EXIT_CODES`, `EXIT_*` constants | Frozen |
| **§13.12** Stage & terminal states | `STATES`, `TERMINAL_STATES` | State machine | `STATES`, `STATE_*`, `TERMINAL_STATES` | Frozen |
| **§13.15** CLI subcommand inventory | `CLI_SUBCOMMANDS` (15 subcommands) | CLI root dispatcher | `CLI_SUBCOMMANDS` | Frozen |
| **§13.16** State-to-exit-code map | `STATE_EXIT_CODES` | `status`, `wait` | `STATE_EXIT_CODES`, `state_exit_code()` | Frozen |
| **§13.17** Public exception hierarchy | `StageError` base + 5 subclasses | All exceptions | `StageError`, `IllegalTransition`, etc. | Frozen |
| **§13.19** Allowed transitions matrix | `ALLOWED_TRANSITIONS` | State transitions | `ALLOWED_TRANSITIONS`, predicate helpers | Frozen |
| **§13.20** Stage public method surface | `STAGE_PUBLIC_METHODS` (15 methods) | `Stage` class methods | `STAGE_PUBLIC_METHODS`, `Stage` | Frozen |
| **§13.21** Public export inventory | `PUBLIC_EXPORTS` (134 symbols) | `import stage_signal` | `__all__ = list(PUBLIC_EXPORTS)` | Frozen |

### Architecture Layer 3: Mutator Commands (Agent / Writer Surface)

| §13.x Section | Frozen Constants / Enums | Public CLI Surface | Public API / Exports | Freeze Status |
|---|---|---|---|---|
| **§13.24** Supervise child PID adoption | `SUPERVISE_ADOPT_*`, exits 126/127/128+N | `stage-signal supervise` | `Stage.supervise()`, helper functions | Frozen |
| **§13.25** Reclaim fail-and-clear | `RECLAIM_ALLOWED_SOURCES`, detail keys | `stage-signal reclaim` | `Stage.reclaim()` | Frozen |
| **§13.26** Clear-terminal reset | `CLEAR_TERMINAL_ALLOWED_SOURCES`, fields | `stage-signal clear-terminal` | `Stage.clear_terminal()` | Frozen |
| **§13.27** Heartbeat liveness contract | `HEARTBEAT_ALLOWED_SOURCES`, detail keys | `stage-signal heartbeat` | `Stage.heartbeat()` | Frozen |
| **§13.28** Note progress appending | `NOTE_ALLOWED_SOURCES`, `MAX_NOTES` (200) | `stage-signal note` | `Stage.note()`, `MAX_NOTES` | Frozen |
| **§13.29** Artifact add contract | `ARTIFACT_ALLOWED_SOURCES`, detail keys | `stage-signal artifact` | `Stage.artifact()` | Frozen |
| **§13.30** Done terminal contract | `DONE_ALLOWED_SOURCES`, detail keys | `stage-signal done` | `Stage.done()` | Frozen |
| **§13.31** Fail terminal contract | `FAIL_ALLOWED_SOURCES`, guard flags | `stage-signal fail` | `Stage.fail()` | Frozen |
| **§13.32** Blocked terminal contract | `BLOCKED_ALLOWED_SOURCES`, detail keys | `stage-signal blocked` | `Stage.blocked()` | Frozen |
| **§13.33** Start claim-running contract | `START_ALLOWED_SOURCES`, detail keys | `stage-signal start` | `Stage.start()` | Frozen |
| **§13.34** Init bootstrap setup | `INIT_DETAIL_KEYS`, `INIT_IDLE_STATUS_FIELDS`| `stage-signal init` | `Stage.init()` | Frozen |
| **§13.39** Optional `.orch` mirror write | `DEFAULT_MIRROR_DIRNAME`, `ENV_STATUS_MIRROR` | `--write-status-mirror` | `write_status_mirror()` | Frozen |
| **§13.41** Proof composition gate | Proof verification before mutate | `--proof-ref`, `--require-proof` | `verify_proof()` | Frozen |

### Architecture Layer 4: Observer & Watchdog Commands (Reader Surface)

| §13.x Section | Frozen Constants / Enums | Public CLI Surface | Public API / Exports | Freeze Status |
|---|---|---|---|---|
| **§13.5** Event types freeze | `EVENT_TYPES` (9 types) | `events --type` | `EVENT_TYPES` | Frozen |
| **§13.6** Event record keys & format | `EVENT_RECORD_KEYS`, `EVENTS_JSON_KEYS` | `events --json` | `EVENT_RECORD_KEYS`, `EVENTS_JSON_KEYS` | Frozen |
| **§13.8** Doctor warning object & codes | `WARNING_CODES`, `WARNING_KEYS` | `doctor --json` | `WARNING_CODES`, `WARNING_KEYS` | Frozen |
| **§13.11** Wait outcomes enum | `WAIT_OUTCOMES` (`met`, `mismatch`, `timeout`) | `wait --json` | `WAIT_OUTCOMES`, `WAIT_OUTCOME_*` | Frozen |
| **§13.22** Doctor human summary strings | `DOCTOR_SUMMARY_RECLAIM_NEEDED`, `_OK_FORMAT` | `doctor` summary line | `DOCTOR_SUMMARY_*`, `doctor_summary_ok` | Frozen |
| **§13.23** Wait want vocabulary & predicates| `WAIT_CHOICES`, `WAIT_WANT_NEEDS_RECLAIM` | `wait --state`, `--needs-reclaim` | `WAIT_CHOICES`, predicates | Frozen |
| **§13.35** Status read snapshot contract | Status read snapshot, dynamic fields | `stage-signal status` | `Stage.status()` | Frozen |
| **§13.36** Events read & tail contract | Chronological tail, filter before tail | `stage-signal events` | `Stage.events()`, `EVENTS_DEFAULT_TAIL` | Frozen |
| **§13.37** Doctor / diagnose read contract | Diagnostic snapshot, `--exit-reclaim` | `stage-signal doctor` | `Stage.diagnose()` | Frozen |
| **§13.38** Wait observer & poll loop | Non-mutating poll loop, outcome exits | `stage-signal wait` | `Stage.wait()`, `WaitTimeout` | Frozen |
| **§13.42** PID liveness & `needs_reclaim` | `is_pid_alive`, `derive_needs_reclaim` | Liveness checks across CLI | Shared liveness probe, warning folds | Frozen |

---

## 3. Gaps & Redundant Prose Audit

### 3.1 Gaps Analysis
- **Normative Coverage:** 100% complete across all 15 CLI subcommands and 15 `Stage` methods.
- **Constant Inventory:** `PUBLIC_EXPORTS` contains exactly 134 symbols matching `stage_signal.__all__`.
- **Holes Found:** Zero. There are no unfrozen normative gaps remaining in the core lifecycle contract.

### 3.2 Redundant Prose Analysis
1. **Dual Specification Duplication (SPEC §§1–12 vs §13):**
   - In pre-1.0 development, individual features landed as discrete frozen subsections in §13 while sections 1–12 retained the narrative description.
   - Today, §13 is an exhaustive, 3,300+ line normative specification that fully re-specifies every rule introduced in §§1–12 (status schema, transition edges, event records, exit codes, and locking).
   - *1.0 Recommendation:* Streamline `SPEC.md` §§1–12 into a concise architecture overview that delegates all normative assertions to §13, eliminating duplicative prose and preventing semantic drift.
   - *Status:* **Done** — §§1–12 are now a non-normative architecture overview that indexes §13; the exit-code and CLI tables are explicitly labeled non-normative summaries citing §13.4/§13.16 and §13.15 (#201, #207).
2. **Obsolete Background References:**
   - Early planning artifacts (e.g. `docs/IMPLEMENTATION_PLAN.md` or obsolete prototype notes) have been completely superseded by `SPEC.md` and should be formally retired.

---

## 4. Short Cut-List: Demoting Dogfood Harnesses & Bloated Examples

During early development and dogfooding (releases 0.1.0 through 0.1.7), several scripts and multi-agent orchestrator patterns were checked into `examples/` and `docs/examples/` to exercise the lifecycle contract. While valuable for validation, they read as if `stage-signal` were an orchestrator product rather than a thin stage contract.

For 1.0, the following items must be cut or demoted:

| Candidate | Current Role | 1.0 Action | Rationale | Status |
|---|---|---|---|---|
| `examples/queue-orchestrator.sh` | Sequential task queue manager reading `sample-queue.md` | **Demote / Cut** to external dogfood repo or `examples/dogfood/` | Queue scheduling is an application concern, not part of `stage-signal`. | **Done** (demoted to `examples/dogfood/`) |
| `examples/queue-orchestrator-smoke.sh` | Smoke test for `queue-orchestrator.sh` | **Demote / Cut** alongside queue script | Unnecessary test overhead for non-product scripts. | **Done** (demoted to `examples/dogfood/`) |
| `examples/sample-queue.md` | Sample task list for queue orchestrator | **Demote / Cut** alongside queue script | Non-core asset. | **Done** (demoted to `examples/dogfood/`) |
| `examples/multi-cli-loop.sh` | Multi-agent CLI dispatcher (`agy` vs `opencode` vs `mock`) | **Demote / Cut** from root examples | Blurs product boundary; users confuse it with core tooling. | **Done** (demoted to `examples/dogfood/`) |
| `examples/cli-orchestrator-loop.md` | Comprehensive guide on driving dual-CLI queues | **Demote / Replace** with a 10-line integration example | Explains private orchestrator internals (`.agloop/`, `.museloop/`) rather than the contract. | **Done** (demoted to `examples/dogfood/`) |
| `docs/examples/orchestrator.md` | 557-line dual-CLI orchestrator architecture manual | **Demote / Move** out of primary `docs/` | Reads like a multi-agent product manual instead of a lifecycle specification. | **Done** (demoted to `examples/dogfood/`) |
| Harness Terminology (`.agloop/`, `.museloop/`) | Private dogfood loop directories mentioned in docs | **Purge** from general documentation | Confuses external adopters; replace with generic "caller state" or "CI runner". | **Done** (purged from CONTRIBUTING/docs) |

### Retained Core Examples for 1.0:
- `examples/orchestrator-smoke.sh`: Keep as the canonical CLI product-acceptance test.
- Minimal CI workflow example (e.g. `examples/github-action-wait.yml`): Keep as a reference for external watchers.
- A concise 1-page "Caller Guide" demonstrating the three standard watchdog loops:
  1. Synchronous wait: `stage-signal wait --state terminal`
  2. Health watchdog: `stage-signal wait --needs-reclaim` → `stage-signal reclaim --reason ... --kill`
  3. Agent wrapper: `init` → `start --pid $$` → work → `done --summary ...`

---

## 5. The 1.0 "Done" Bar

The release of **1.0.0** is achieved when the following criteria are satisfied:

1. **Contract Purity:**
   - The product boundary is strictly defined as `.stage-signal/` filesystem state, normalized CLI subcommands, exit codes, and the `Stage` Python library API.
   - Zero product features for task scheduling, queueing, or multi-agent cockpits.
2. **SPEC Consolidation:**
   - Duplicate normative text between `SPEC.md` §§1–12 and §13 is unified, establishing §13 as the single source of truth under `schema_version: 1`.
   - *Status:* **Done** (#201, #207).
3. **Examples Streamlined:**
   - Bloated dogfood harness scripts and documents listed in the cut-list are demoted or archived; only lean, caller-focused integration examples remain.
4. **0.1.7 Soak Validation:**
   - The 0.1.7 release (shipping freezes through §13.42) completes its soak period across all target platforms (Linux, macOS, Windows) and coding agents (Antigravity, OpenCode, Claude Code, Cursor, human shell) with zero breaking issues or freeze churn.
5. **Zero Open Normative Issues:**
   - All 616 unit/concurrency tests remain clean and green with 100% coverage of frozen constants and public exports.
