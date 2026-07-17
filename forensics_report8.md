# Forensic Report 8 — Residual Test Failures

Operation: REGRESSION_TRIAGE
Date: 2026-07-16
Status: 🔴 5/5 failures (Root-caused)

## 0. Executive Summary

| # | Test | Diagnosis | Root Cause | Fix Location |
|---|------|-----------|------------|--------------|
| 1 | `test_git_push_tool_auto_records_diff` | **Real Regression** | `GitPushTool.execute()` ignores the passed `evidence_log` and instantiates a fresh `EvidenceLog()` internally, so the caller's log stays empty. | `tools/git_tool.py` |
| 2 | `test_deep_agent_records_evidence_after_successful_dispatch` | **Stale Test (missing fixture)** | `execute_node` calls `validate_tool_call`, which requires the tool to be registered. Test never initializes the tool registry → `extract_command` returns `None` → 0 dispatches. | `tests/test_phase1_deep_agent_evidence.py` |
| 3 | `test_deep_agent_records_evidence_after_failed_dispatch` | **Stale Test (missing fixture)** | Same as #2. | `tests/test_phase1_deep_agent_evidence.py` |
| 4 | `test_deep_agent_record_format_matches_loop_record` | **Stale Test (missing fixture)** | Same as #2. | `tests/test_phase1_deep_agent_evidence.py` |
| 5 | `test_deep_agent_multiple_steps_produce_multiple_records` | **Stale Test (missing fixture)** | Same as #2. | `tests/test_phase1_deep_agent_evidence.py` |

**Verdict:** 1 real regression (tool contract bug), 4 stale tests that assume a populated
tool registry that no test bootstrap ever created. Both are pre-existing since the initial
commit (`c5370d3`) — none were introduced by the args_schema / event-payload unification work.

## 1. Traceback Evidence & Analysis

### ❌ Test 1: test_git_push_tool_auto_records_diff
* **Command:** `pytest tests/test_verifier.py::TestVerifierRegression::test_git_push_tool_auto_records_diff`
* **Traceback:**
```
tests/test_verifier.py:174: in test_git_push_tool_auto_records_diff
    self.assertGreaterEqual(len(diff_recs), 1)
E   AssertionError: 0 not greater than or equal to 1
```
* **Diagnosis:** Real Regression. Test calls
  `tool.execute(evidence_log=log, remote="origin", branch="main")` and then inspects
  `log.get_records()`. But `GitPushTool.execute()` signature is `execute(self, **kwargs)`
  — it never binds `evidence_log`, and `execute_with_args` hard-codes
  `evidence_log = EvidenceLog()` (git_tool.py:152), recording into a throwaway log.
  The caller's `log` is never populated → `diff_recs` is empty.
* **Fix:** Thread the caller-supplied `evidence_log` through `execute()` → `execute_with_args()`
  → `push_and_verify_evidence()`, falling back to a fresh `EvidenceLog()` only when None.

### ❌ Tests 2-5: test_phase1_deep_agent_evidence.py (4 Failures)
* **Command:** `pytest tests/test_phase1_deep_agent_evidence.py`
* **Tracebacks:**
```
test_phase1_deep_agent_evidence.py:59: Assertion 0 >= 1  (no evidence record)
test_phase1_deep_agent_evidence.py:82: assertion 0 >= 1  (no evidence record)
test_phase1_deep_agent_evidence.py:111: assert 0 >= 1    (no dispatched call)
test_phase1_deep_agent_evidence.py:167: assert 0 == 3    (0 dispatches)
```
* **Diagnosis:** Stale Test (missing registry fixture). `NativeDeepAgent.execute_node`
  calls `extract_command(response)` → `validate_tool_call(payload, registry)` →
  `_validate_tool_name` which fails (`'execute_shell' not registered`) when the global
  tool registry is empty. The test imports only `NativeDeepAgent`/`DeepAgentState`/
  `RuntimeState`/`Dispatcher`/`EvidenceLog`/`ToolResult` — it never registers any tool,
  so `extract_command` returns `None` and the execute loop records 0 dispatches / 0 records.
* **Confirmed:** `registry._tools == []` at test import time; importing `core.app_context`
  + `AppContext.build()` registers `execute_shell` (and 5 others) and `extract_command`
  then returns a valid `ToolCall`. The production app always builds `AppContext` first,
  so this is purely a test-bootstrap gap, not a runtime defect.
* **Fix:** Add a module-level fixture in the test that registers the standard tools
  (mirror `core.app_context.AppContext.build()`'s registration, or simply call it).

## 2. Action Plan & Resolutions

| # | Action | Status |
|---|--------|--------|
| 1 | `tools/git_tool.py`: accept `evidence_log` param in `execute()` / `execute_with_args()`, pass to `push_and_verify_evidence()`, default to new `EvidenceLog()` when None. | ✅ Done |
| 2 | `tests/test_phase1_deep_agent_evidence.py`: bootstrap the tool registry (import `core.app_context`, call `AppContext.build()`) so `execute_shell` is resolvable in `execute_node`. | ✅ Done |
| 3 | Re-run full suite → confirm 505/505. | ✅ Done |

## 3. Post-Fix Verification

```
500 passed (pre-existing) + 5 fixed = 505 passed, 0 failed
```
