# SCHEMA_POLICY.md — Contract Change Policy

This document defines what counts as a "contract change" in the NABD OS
codebase, how to update snapshots, and what requires explicit review.

## What Is a Contract Change?

Any modification to the **field list, type, or name** of these classes:

| Class | Module | Reason |
|-------|--------|--------|
| `EvidenceRecord` | `core/evidence.py` | Central evidence data model; every tool call serialises through it |
| `EvidenceLog` | `core/evidence.py` | Evidence store; `restore()` + `to_serializable()` must stay compatible |
| `TodoItem` | `core/todo.py` | TODO plan data model; persisted across sessions |
| `VerificationResult` | `core/evidence.py` | Output of L1/L2 verification; consumed by agents |
| `FinalizationDecision` | `core/convergence_gate.py` | Result of `can_finalize()`; consumed by Convergence Gate |
| `TodoEvidenceLink` | `core/convergence_gate.py` | Evidence-per-TODO link in finalization decision |
| `WalRecord` | `core/accept_edits_state.py` | WAL journal record; crash recovery depends on its schema |
| `TurnOutcome` | `core/turn_outcome.py` | Terminal turn result; used by REPL + engine |

Also a contract change:

- **Adding or removing** a `bus.emit()` event name (snapshotted in `tests/snapshots/event_snapshot.json`)
- **Deleting or renaming** any file in `PROTECTED_MODULES` (`core/evidence.py`, `core/todo.py`, `core/convergence_gate.py`, `core/kernel/events.py`, `engine/consent.py`, `core/_exact_action_contract.py`)

## How to Update Snapshots

After a deliberate, reviewed schema change:

```bash
python3 tests/_gen_snapshot.py
```

This regenerates both:
- `tests/snapshots/schema_snapshot.json`
- `tests/snapshots/event_snapshot.json`

Commit the new snapshots **alongside** the schema change in the same PR/commit.

## Pre-Commit Hook

A local pre-commit hook enforces these policies before every commit.
Install via:

```bash
ln -sf ../../scripts/pre_commit_check.sh .git/hooks/pre-commit
```

The hook runs:
1. Red team validation
2. Schema snapshot contract
3. Event name snapshot contract
4. Forbidden-changes policy
5. Exact-action contract
6. Claim gate + Arabic verification

Total ~5s offline on Termux. See `docs/ci_lockdown.md` for full details.

## Bypass Markers

For intentional, reviewed changes that trigger a policy gate, add
`[POLICY_OVERRIDE]` as the first token in the commit message and update
this document with the exception. `--no-verify` is allowed only for:
- Snapshot updates (run `python3 tests/_gen_snapshot.py` first)
- Documented `[POLICY_OVERRIDE]` exceptions

Security gates (red team, claim gate, exact-action) must never be bypassed.

## What Is Forbidden Without Review

1. Deleting or renaming a schema class listed above
2. Changing the type of an existing field (e.g. `str` → `int`)
3. Removing a field that persisted data depends on (e.g. `evidence_id`)
4. Adding heavy ML/data-science dependencies (`numpy`, `torch`, `pandas`, etc.)
   to `core/` or `engine/` without explicit justification
5. Renaming `can_finalize()` or `EvidenceRecord`
