# CONDITION REGISTRY

## Condition 17 — Journal Durability Across Restart
**Status:** CLOSED (2026-07-27)
**Evidence:** 6 subprocess tests in `tests/test_phase21_evidence_restore.py`
**Guard:** `EvidenceLog.restore()` fail-closed via `VerifierError`; `SessionManager.save()` atomic with fsync+rename

## Condition 19
**Status:** UNRESOLVED_REFERENCE
**Source:** Mentioned in prior audit report — no definition found in any source file or test
**Required Action:** Clarify from original auditor/report author

## Runtime Incident — Timeout / Guessing / Todo Evidence
**Status:** CLOSED (2026-07-27)
**Evidence:** Full suite (1383 tests) completed in 122s with no timeout
**Fixes:**
- `safe_execute_command` timeout raised 30s → 300s (`core/utils.py:150`)
- `_LazyCommandExecutor` default raised 30s → 300s (`tools/shell.py:89`)
- `TodoManager.mark_done()` requires `evidence_log` and matching evidence record
- Guard against test-related TODO without `passed`/`failed` in verification_note

## Phase 2.6 — Pre-commit Lockdown
**Status:** CLOSED (2026-07-27)
**New files:** `scripts/pre_commit_check.sh`, `docs/ci_lockdown.md`
**Updated files:** `SCHEMA_POLICY.md`, `FINAL_AUDIT_STATUS.md`
**Gates:** Red team, schema snapshot, event snapshot, forbidden changes, exact-action contract, claim gate + Arabic (79 tests, ~6s)
**Hook:** `ln -sf ../../scripts/pre_commit_check.sh .git/hooks/pre-commit`
**Bypass:** `[POLICY_OVERRIDE]` marker in commit message + `SCHEMA_POLICY.md` update
