# FINAL_AUDIT_STATUS.md

## Runtime Incident
**Status:** CLOSED

**Evidence:**
- 1324 tests collected, 1323 passed, 1 skipped, 0 failed
- `safe_execute_command` default timeout raised from 30s → 120s (`core/utils.py`, `tools/shell.py`)
- `TodoManager.mark_done()` now REQUIRES `evidence_log` + matching evidence record (`core/todo.py`)
- 3 legacy tests updated to wire `evidence_log` (`test_convergence_gate.py`, `test_phase2_session_persistence.py`)

## Condition 17 — Journal Durability Across Restart
**Status:** CLOSED

**Evidence:**
- 6 new tests in `tests/test_phase21_evidence_restore.py` (6/6 passing)
- Real subprocess save → subprocess restore (not in-process simulation)
- Empty restore, truncated payload, corrupt payload all fail-closed via `VerifierError`
- Counter continuity across 2 processes (A: E-1..E-3 → B: +1 = E-4)
- `SessionManager.save()` atomic: tmp + fsync + `os.replace()` + best-effort dir fsync

## Exact-Action Contract
**Status:** CLOSED

**Evidence:**
- Single source of truth: `core/_exact_action_contract.py`
- `EXACT_ACTION_ALLOWED_TOOLS = frozenset({"execute_shell"})`
- `final_answer` explicitly excluded from LLM schema; documented as Convergence-Gate-only control message
- 10 new tests in `tests/test_exact_action_contract.py` + updated existing test in `tests/test_exact_action_schema_filtering.py`
- Normal mode and fallback mode verified unaffected

## Consent Hardening
**Status:** CLOSED

**Evidence:**
- Empty enter (`""`) now DENIED (was approved)
- Prompt changed from `[Y/n]` to `[y/N]`
- Every decision (approved/denied/failed_closed) recorded as EvidenceRecord with: tool name, command, step, timestamp, decision reason
- Production dispatch path (`_handle_consent_and_edit_gate`) passes `evidence_log` + `step_count` to `confirm()`
- 15 new tests in `tests/test_consent.py` (15/15 passing)

## One-Shot Policy (Schema Contract Enforcement)
**Status:** CLOSED

**Evidence:**
- Schema snapshots for 7 core classes (`tests/snapshots/schema_snapshot.json`)
- Event name snapshot for 47 events (`tests/snapshots/event_snapshot.json`)
- Snapshot-update script: `python3 tests/_gen_snapshot.py`
- 3 new test files: `test_schema_contract_snapshot.py`, `test_event_contract_policy.py`, `test_forbidden_changes_policy.py` (7/7 passing)
- `SCHEMA_POLICY.md` documents what counts as a contract change and how to update

## Known Limitations

| Limitation | File | Severity | Resolution |
|------------|------|----------|------------|
| TOCTOU in path validation | `docs/known_limitations.md` | Low | Documented; openat+O_NOFOLLOW deferred |
| Directory fsync best-effort | `docs/known_limitations.md` | Low | File contents fsync'd before rename; dir fsync is best-effort on F2FS/Termux |
| Turn ID on EvidenceRecord | `docs/known_limitations.md` | Low | step_count + timestamp serve as temporal identifier; no separate turn_id field |
| **Skipped test:** `test_unreadable_file_returns_empty` | `tests/test_phase5_workspace.py:51` | Informational | `os.chmod 0o000` does not prevent file reads on Termux/Android — platform limitation, not a bug |
| **Warning:** `test_recovers_from_corrupt_db_file` | `tests/test_memory_manager.py` | Benign | Warning is intentional: the test deliberately corrupts the SQLite DB, triggers auto-recovery path, then asserts recovery. The warning confirms the corruption path is live. |
| **Red Team RT-1:** verify_report_strict regex gap | `docs/threat_model.md` §5, `tests/test_red_team_phase22.py` | Low | **What:** Regex `Ran \d+ tests?` does not catch "I ran pytest and all N tests passed" phrasing — a spoofed claim in different natural language passes the counter check. **Severity:** Low. The claim still requires supporting evidence via `_is_evidence_note` for TODO completion and `check_path_existence_claim` for on-disk file verification. The gap only evades the numeric count regex. **Spoofing possible?** Only for test-count claims phrased without "Ran N tests" — the underlying path and commit claim checks (`check_git_push_claim`, `check_path_existence_claim`) are unaffected. **Mitigation:** Enable L2 SemanticVerifier (currently inactive). The token-based L1 check would catch the claimed number in evidence output. |
| **Red Team RT-2:** Shell cat path escape | `docs/threat_model.md` §3 | Moderate | project_root_guard blocks when path is tokenized. TOCTOU window documented. |

## Phase 2.6 — CI / Pre-commit Lockdown
**Status:** CLOSED (2026-07-27)

**Evidence:**
- `scripts/pre_commit_check.sh` — 6-gate fail-fast runner (79 tests, ~6s)
- Hook installed: `ln -sf ../../scripts/pre_commit_check.sh .git/hooks/pre-commit`
- Pre-flight: python3/pytest missing → exit 1 fail-closed
- `[POLICY_OVERRIDE]` bypass protocol documented in `SCHEMA_POLICY.md`
- Full offline Termux compatibility (bash + pytest only)
- Full suite (1383 tests) continues to pass

**New files:** `scripts/pre_commit_check.sh`, `docs/ci_lockdown.md`
**Updated files:** `SCHEMA_POLICY.md`

## Condition 19
**Status:** UNRESOLVED_REFERENCE

**Source:** Mentioned in prior audit report
**Note:** No file in the repository defines "Condition 19". Cannot verify or close without a definition. Requires clarification from the user.
