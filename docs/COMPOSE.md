# Compose — `proof` interop with verification tools

**Normative source:** `docs/SPEC.md` §9 (proof gate) and §4.5 (`done`).
This file is guidance: how to *reference* external proof without rebuilding
the tools that produce it. On conflict, SPEC wins.

## Posture

`stage-signal done` means **lifecycle success** ("this stage claims it is
finished"). It does **not** mean "tests provably passed". Verification
honesty belongs to verification tools — e.g.
[agent-done-or-not](https://github.com/mohamedzhioua/agent-done-or-not),
which owns capture/ledger/`verify` semantics. `stage-signal` only carries
an opaque **pointer** to their receipt in the `proof` field. See
`docs/PRIOR_ART.md` ("do not rebuild `agent-done-or-not`").

Rule: **compose, do not vendor.** No proof logic lives here beyond the
explicitly requested `--require-proof` gate (SPEC §9), which is the only
place the library ever shells out.

## The `proof` field

Set only by `done` (cleared never — a new `start` with a new `stage_id`
resets the stage; see SPEC §3). Shape:

```json
"proof": {"tool": "agent-done-or-not", "ref": "<ledger path or label>", "verified": null | "file" | "verify"}
```

| `verified` | Meaning |
|------------|---------|
| `null` | Pointer recorded, **not checked** (`--proof-ref` alone). |
| `"file"` | `--require-proof` passed because `ref` was an existing non-empty file. |
| `"verify"` | `--require-proof` passed via `agent-done-or-not verify --ref R` (exit 0). |

`proof: null` means no proof was claimed at all.

## CLI usage

```bash
# 1. Verify with the tool that owns verification, outside stage-signal:
agent-done-or-not capture -- ./pytest-or-similar
#    -> produces a receipt, e.g. /tmp/receipts/stage-42.json

# 2a. Record the pointer without checking (fast, trusts the agent):
stage-signal done --summary "tests green" --proof-ref /tmp/receipts/stage-42.json

# 2b. Record AND gate on it (fails closed, no mutation on failure):
stage-signal done --summary "tests green" \
  --proof-ref /tmp/receipts/stage-42.json --require-proof
```

`--proof-ref R` may be replaced by the env var `STAGE_SIGNAL_PROOF_REF`;
the flag wins when both are given.

### `--require-proof` gate order (SPEC §9)

1. No `R` (neither flag nor env) → fail, exit 3, no mutation.
2. `R` names an existing **non-empty** file → pass, `verified: "file"`.
   Empty/unreadable file → fail, exit 3, no mutation.
3. Else, if `agent-done-or-not` is on `PATH`, run
   `agent-done-or-not verify --ref R` (120 s timeout); exit 0 → pass
   (`verified: "verify"`), non-zero → fail, exit 3, no mutation.
4. Else (not a file, no binary) → **fail closed**, exit 3, no mutation.
   Rationale: never silently claim proof.

The gate runs **before** any mutation: a failed gate leaves `STATUS.json`
and `events.jsonl` untouched (state stays `running`/`queued`).

## What orchestrators should expect

```bash
stage-signal status --json | python3 -c "import json,sys; print(json.load(sys.stdin)['proof'])"
```

- **`proof` is `null`** — plain lifecycle `done`. The agent claims success;
  nothing was referenced. Accept this for stages where proof is overkill
  (docs, scaffolding), or route to human review when your policy needs more.
- **`proof.verified` is `null`** — a pointer was claimed but **not checked**
  by `stage-signal`. Treat the `ref` as a hint: fetch it yourself, or re-run
  the verifier (`agent-done-or-not verify --ref R`) in your own pipeline
  before promoting to the next stage. Do not treat it as verified.
- **`proof.verified` is `"file"` / `"verify"`** — the gate passed at `done`
  time. `"file"` means "a non-empty receipt existed"; `"verify"` means "the
  external verifier exited 0". Both are still **point-in-time claims**, not
  a substitute for CI: re-verify server-side if the receipt matters to you.

`STATUS.json` snippets:

```json
// done --summary "docs pass"  (no proof claimed)
{"state": "done", "proof": null, "result": {"summary": "docs pass", "...": "..."}}

// done --summary "tests green" --proof-ref /tmp/receipts/stage-42.json
{"state": "done", "proof": {"tool": "agent-done-or-not", "ref": "/tmp/receipts/stage-42.json", "verified": null}}

// done --summary "tests green" --proof-ref /tmp/receipts/stage-42.json --require-proof
{"state": "done", "proof": {"tool": "agent-done-or-not", "ref": "/tmp/receipts/stage-42.json", "verified": "file"}}
```

The `done` event in `events.jsonl` also carries the proof in its `detail`
object (`{"proof": ..., "git_head": ...}`) for audit trails.

### Suggested orchestrator policy

```bash
# minimal: require proof only for stages that need it
REF=$(stage-signal status --json | python3 -c "import json,sys; p=json.load(sys.stdin)['proof']; print((p or {}).get('ref',''))")
if [ -n "$POLICY_NEEDS_PROOF" ] && [ -z "$REF" ]; then
  echo "no proof pointer for a proof-gated stage" >&2; exit 1
fi
# strong: always re-verify with the owning tool, never trust 'verified' alone
[ -z "$REF" ] || agent-done-or-not verify --ref "$REF"
```

`stage-signal` exit codes do not change with proof: `done` exits 0 on
success; a failed `--require-proof` gate exits 3 like any illegal
transition (SPEC §7).

## Working with tools other than agent-done-or-not

The `tool` value is currently always `"agent-done-or-not"` (SPEC §9). For a
different receipt system, keep the pattern: let that tool verify, store its
receipt path/label in `ref`, and use `--proof-ref` for the pointer /
`--require-proof` for the file-exists gate (a non-empty file passes
regardless of which tool wrote it). Only the `verify` delegation step is
specific to `agent-done-or-not`.

## Non-goals (explicit)

- **No verification platform.** No test runners, no ledgers, no receipt
  signing, no CI `assert`, no Stop-hook enforcement. That is
  `agent-done-or-not`'s (or your CI's) job.
- **No receipt parsing.** `ref` is opaque — a path or label. We check
  existence/non-emptiness or delegate to the owning binary; we never read
  its meaning.
- **No new dependencies.** Core stays Python 3.11+ stdlib-only; the only
  subprocess is the explicitly requested gate above.
- **No silent claims.** Anything unverifiable fails closed (exit 3) rather
  than recording unchecked proof as verified.

## Appendix: `.orch` status mirror (SPEC §10)

Unrelated to proof, but referenced here by SPEC: `--write-status-mirror`
(or `STAGE_SIGNAL_STATUS_MIRROR=1`) on `start`/`done`/`blocked`/`fail`
best-effort writes `<repo>/.orch/STATUS.md` (`state: <state>` + stage +
updated) and touches `<repo>/.orch/DONE` when the new state is `done`.
Mirror failures warn on stderr but never fail the command.
