# Threat Model — NABD OS

**Date:** 2026-07-27
**Environment:** Termux / Android (single-user, no root by default)
**Threat level:** Moderate — agent executes shell commands and writes files based on LLM-generated tool calls.

## Methodology

Each threat is described as:

| Column | Description |
|--------|-------------|
| Vector | Attack surface / trigger |
| Attack | Concrete adversarial scenario |
| Defenses | Existing protections (G = Guard, D = Detection, M = Mitigation) |
| Residual Risk | Remaining gap after defenses |
| Fail-Closed Signal | Expected observable outcome when attack is blocked |
| Red-Team Test | Test name that validates this threat |

---

## 1. Prompt Injection

| Vector | Attack | Defenses | Residual Risk | Fail-Closed Signal | Red-Team Test |
|--------|--------|----------|---------------|--------------------|---------------|
| `ignore previous instructions` | LLM-as-agent jumps the system prompt | Consent gate for shell (G); tool_choice pins (`auto`/`required`) protect final turn (G); prompt-leak detector aborts on system marker leakage in output (D) | A sufficiently creative prompt could make the model emit a tool call that passes all single-tool guards — no semantic prompt-usage boundary | `is_safe_command` blocks; consent prompt shown; TOOL_BLOCKED status | `test_security_disabled_claim_denied` |
| `maintenance mode override` | Claimed security bypass in user message | No runtime path disables security based on model output — `is_safe_command` and `_validate_path` are deterministic Python (G) | Low — the security layer is not prompt-accessible | Command blocked by is_safe_command; security violation ToolResult | `test_maintenance_mode_override_denied` |
| `security guards disabled` | Model told to skip consent | `ConsentPolicy.requires_confirmation` is hardcoded (G); shell commands always hit `is_safe_command` first (G); exact-action mode overrides tool_choice (G) | Very low | Consent prompt still shown; EXACT_ACTION_BLOCKED status for exact-action | `test_security_disabled_claim_denied` |
| `/etc/passwd` read | Model asked to read system file | `project_root_guard.py` resolves absolute path → rejects if outside workspace root (G); `_guard_path_jail` blocks file_system outside workspace (G) | Low — confirmed by test_project_root_guard live tests | `ProjectRootViolation` → TOOL_RESULT with outside-workspace error | `test_etc_passwd_request_denied` |

---

## 2. Consent Bypass

| Vector | Attack | Defenses | Residual Risk | Fail-Closed Signal | Red-Team Test |
|--------|--------|----------|---------------|--------------------|---------------|
| Shell without consent | Model emits `execute_shell` without approval gate | `ConsentManager.confirm()` called before every shell dispatch (G); `_handle_consent_and_edit_gate` gates all tool dispatch (G) | Near-zero — gate cannot be bypassed without modifying `engine/consent.py` | ToolResult with "Execution blocked by user." | `test_shell_without_consent_is_blocked` |
| Empty enter approval | User presses Enter reflexively | Empty enter is now DENIED (changed from `""` in `("y", "yes")` to `""` in DENY path) (G) | Low — user can still reflexively type `y` | ToolResult (denied) with stdout="Execution blocked by user." | `test_empty_enter_does_not_approve` |
| Old approval reuse | Previously-approved command replayed in new turn | `ctx.approved_shell.clear()` after each exact-action dispatch (G); normal mode does not cache across turns (G) | Low — confirmed by `test_old_shell_approval_cannot_authorize_new_command` | Turn-level `approved_shell` cleared → consent prompt shown again | `test_old_approval_cannot_authorize_new_command` |
| Approval for command A used for command B | Approve `ls` → model runs `rm` | Approval is cached by *exact command string* — hash-level match, not wildcard (G) | Low for exact-action; normal mode caches per exact string in `ctx.approved_shell` | Different command string → not in `approved_shell` → consent required | `test_approval_bound_to_exact_command` |

---

## 3. Tool Misuse

| Vector | Attack | Defenses | Residual Risk | Fail-Closed Signal | Red-Team Test |
|--------|--------|----------|---------------|--------------------|---------------|
| `file_system` misrouted as shell | Model sends shell command as `file_system` path | `FileSystemTool` detects command-shaped inputs (no extension, no separator) → returns `WRONG_TOOL` typed error with suggested `execute_shell` (G); confirmed by `test_tool_routing` | Low | ToolResult with `status="wrong_tool"` + metadata suggesting `execute_shell` | (Covered by test_tool_routing) |
| `execute_shell` for file reads | Model uses shell `cat` to bypass file restrictions | `is_safe_command` validates the command, not the intent (G); `project_root_guard` checks the path argument if a path token is present (G) | Moderate — a shell command like `cat /etc/passwd` passes `is_safe_command` but is blocked by `project_root_guard` only if the path is tokenized | `ProjectRootViolation` if the path token resolves outside root | (Covered by path jail tests) |
| `web_search` payload injection | Model told to search for malicious content | Web search results are treated as normal tool output — no secondary execution (M) | Low — output is just text, never executed | Not applicable — no execution path | Not a red-team test target |

---

## 4. Exact-Action Abuse

| Vector | Attack | Defenses | Residual Risk | Fail-Closed Signal | Red-Team Test |
|--------|--------|----------|---------------|--------------------|---------------|
| Multiple tool calls | Model emits `file_system` then `execute_shell` | `EXACT_ACTION_ALLOWED_TOOLS` only contains `execute_shell` (G); `get_available_tools()` hides all other tools (G); `_guard_exact_action` blocks non-shell pre-dispatch (G) | Very low — triple gate | `[EXACT_ACTION_BLOCKED]` ToolResult with `status="blocked"` | `test_exact_action_blocks_non_execute_shell_tool` / `test_exact_action_prevents_multiple_tool_calls` |
| `final_answer` as normal tool | Model calls `final_answer` to skip shell | `final_answer` is excluded from FC schema in exact-action mode (G); injected only as system-level control message by Convergence Gate (G) | Very low — confirmed by `test_exact_action_fc_excludes_final_answer` | `final_answer` not in `get_available_tools()`; if called, blocked by `_guard_exact_action` | `test_final_answer_not_usable_as_normal_tool` |
| Fallback mode bypass | Model enabled fallback mode to get more tools | `exact_action_mode` and `fallback_mode` are independent flags; `get_available_tools` checks `_exact_action_mode` FIRST (G) | Low | Fallback tools hidden; exact-action guard still fires | (Covered by test_exact_action_contract) |

---

## 5. Evidence Spoofing

| Vector | Attack | Defenses | Residual Risk | Fail-Closed Signal | Red-Team Test |
|--------|--------|----------|---------------|--------------------|---------------|
| Claim file exists without tool proof | Agent says "I read core/loop.py" without calling `file_system` | `StructuralVerifier` extracts technical tokens from claim and checks against evidence output (D); `check_path_existence_claim` verifies on-disk existence (G) | Low — both checks pass for honest reads; fabricated paths not on disk are rejected | `VerifierError` with "unsupported path" or token mismatch; final_answer blocked as CONTROL directive | `test_false_file_existence_claim_rejected` |
| Claim tests passed without pytest output | Agent says "all tests pass" with no tool call | `verify_report_strict` checks test count claims against `run_tests`/`execute_shell` records (D); `_is_evidence_note` refuses vague notes without concrete signals (G) | Low | `ValueError` on mark_done; VerifierError on final_answer; unsupported claim in report | `test_false_pytest_success_claim_rejected` |
| Claim commit/push without git evidence | Agent says "committed abc1234" with no `git_log` call | `verify_report_strict` checks commit hashes against actual `git_*` records (D); no hash match → hard failure | Low | `VerificationResult(passed=False)` with "no documented git_* call" | `test_false_commit_claim_rejected` |
| Claim symbol defined without code evidence | Agent says "function sanitize exists in core/__init__.py" | `_symbol_defined_in_snippet()` checks for `def sanitize` / `class sanitize` regex match in tool output (G); `verify_structured_claim` and `verify_narrative_claim` both enforce this (G) | Near-zero — confirmed by `test_evidence_claim_check.py` 14/14 passing | `VerifierError` with "no literal 'def sanitize' or 'class sanitize' appears" | `test_false_symbol_definition_claim_rejected` |

---

## 6. Path Escape

| Vector | Attack | Defenses | Residual Risk | Fail-Closed Signal | Red-Team Test |
|--------|--------|----------|---------------|--------------------|---------------|
| Absolute path to other project | `cat /data/9router/core/sanitize.py` | `ProjectRootGuard` resolves path → rejects if outside project root (G); confirmed by live test `/etc/passwd` rejection (G) | Very low — confirmed runtime | `ProjectRootViolation` raised with "outside the active project root" | `test_absolute_path_escape_denied` |
| Relative `../../etc/passwd` | Traversal | `ProjectRootGuard` resolves `../../etc/passwd` relative to project root → rejected (G) | Very low — confirmed runtime | `ProjectRootViolation` raised | `test_relative_traversal_denied` |
| Symlink escape | Link inside project points to `/etc/passwd` | `ProjectRootGuard` follows symlink via `.resolve()` → detects target outside root (G); confirmed by `test_rejects_symlink_pointing_outside_root` | Low — a symlink must first be created (requires write access) | `ProjectRootViolation` raised with "outside the active project root" | `test_symlink_escape_denied` |
| Compound `cd && cat ...` | `cd ../../9router && cat core/sanitize.py` | `ProjectRootGuard` simulates `cd` cumulatively → detects escape at the `cd` step (G); confirmed by `test_exact_scenario_from_the_report_is_now_caught` | Very low | `ProjectRootViolation` at the `cd` step with "cumulative-cd escape" | `test_compound_cd_escape_denied` |
| Unresolvable path fail-closed | Non-existent file | `_resolve_candidate` returns `None` → `ProjectRootViolation` raised (G); confirmed by `test_nonexistent_path_is_rejected_fail_closed` | Very low | `ProjectRootViolation` with "could not be resolved safely" | `test_unresolvable_path_fails_closed` |

**Known limitation:** TOCTOU window exists between `_guard_path_jail` (path check at dispatch time) and actual `open()` at execution time. See `docs/known_limitations.md`.

---

## 7. Restart / Replay Abuse

| Vector | Attack | Defenses | Residual Risk | Fail-Closed Signal | Red-Team Test |
|--------|--------|----------|---------------|--------------------|---------------|
| Replay stale evidence | Agent restores old evidence to claim false completion | `EvidenceLog.restore()` is fail-closed on corruption (G); `can_finalize()` cross-references TODOs with evidence — stale evidence without matching TODO fails (G) | Low | `can_finalize()` returns `allowed=False` with blocking TODO list | (Covered by Condition 17 tests) |
| Duplicate terminal outcome | Agent reaches two terminal states | `_finalize_loop` enforces exactly one `TurnOutcome` via `TurnFinalizer` (G); confirmed by `test_no_dual_terminal_outcome` | Very low | `TurnFinalizer` blocks second `finalize()` call silently | (Covered by test_gate_l1_loop_semantics) |
| Duplicate E-ID after restart | Save → restart → save → E-1 conflict | `EvidenceLog.restore()` picks `_counter = max(id)` from restored records → next ID continues sequentially (G); confirmed by `test_evidence_counter_continuity_across_processes` | Very low | Sequential E-N+1 counter; VerifierError on malformed data | (Covered by Condition 17 tests) |

---

## 8. Timeout / Resource Exhaustion

| Vector | Attack | Defenses | Residual Risk | Fail-Closed Signal | Red-Team Test |
|--------|--------|----------|---------------|--------------------|---------------|
| Long-running shell command | `pytest` runs 5+ minutes | `safe_execute_command` default timeout is 120s (G); `subprocess.run(timeout=...)` raises `TimeoutExpired` → caught and returned as TIMEOUT error (D); configurable via `timeout` parameter | Low — configurable; mobile hardware occasionally exceeds even 300s | `(returncode=-1, stderr="Command execution timed out after X seconds.")` | `test_timeout_is_reported_not_swallowed` |
| Infinite LLM loop | Model produces thought-only responses indefinitely | `MAX_SELF_CORRECT` cap (G); `MAX_PROVIDER_FAIL_STREAK` cap (G); step-based hard ceiling (10-15 cycles) (G); `_check_repetition_guard` aborts on fingerprint loops (G) | Very low — multiple overlapping caps | `loop_completed` with `reason="infinite_replication_loop"` or `reason="thought_only_loop"` | (Covered by test_loop_repetition_guard) |
| Memory exhaustion | Agent accumulates too many messages | `ContextCompactor` with sliding window (M); `MAX_CRITICAL_FULL` cap (G); token and step budget ceilings (G) | Low | Compactor truncates; budget ceiling emits `loop_completed` with `reason="budget_exhausted"` | Not a red-team test target |

---

## 9. Audit Log Gaps

| Vector | Attack | Defenses | Residual Risk | Fail-Closed Signal | Red-Team Test |
|--------|--------|----------|---------------|--------------------|---------------|
| Consent decision not recorded | Model denies/approves silently | `ConsentManager.confirm()` records every decision via `_record_decision()` when `evidence_log` is passed (D); production path always passes `evidence_log` (G) | Low — confirmed by `test_production_consent_path_passes_evidence_log` | EvidenceRecord with `consent:` prefix in output_snippet | `test_denial_is_auditable` |
| Path jail rejection not recorded | Guard blocks path without audit | `_guard_path_jail` returns `ToolResult` which is appended to conversation (D) | Low — visible in conversation history | ToolResult with outside-workspace error message | (Covered by test_guard_directive_separation) |
| Verification failure not recorded | Verifier rejects claim without trace | `_verify_claim_or_self_correct` emits `verifier_critique` event (D); `_emit_final` blocks with CONTROL message (D) | Low | CONTROL message in conversation; verifier_critique event | (Covered by test_convergence_gate) |
| TODO rejection not recorded | mark_done fails → no audit trace | `mark_done` raises `ValueError` when evidence is missing (D) | Low — visible in tool result | ToolResult with `success=False` and `stderr="Cannot mark TODO ... no matching evidence found"` | `test_todo_done_without_evidence_is_blocked` |
| Shell timeout not recorded | Timeout without evidence | `safe_execute_command` returns timeout error → recorded as evidence (D) | Low | EvidenceRecord with `success=False` and `"timed out"` in output | `test_timeout_is_reported_not_swallowed` |

---

## Summary

| Attack Surface | Gate Strength | Weakest Link |
|----------------|--------------|--------------|
| Prompt injection | Strong | No semantic prompt-boundary check (only structural) |
| Consent bypass | Very strong | User reflexively typing `y` |
| Tool misuse | Strong | Shell cat for file read bypasses path jail only if path not tokenized |
| Exact-action abuse | Very strong | No known bypass |
| Evidence spoofing | Strong | Token-based verification — sophisticated rephrasing could evade L1 |
| Path escape | Very strong | TOCTOU window |
| Restart/replay | Strong | EvidenceLog fail-closed restore |
| Resource exhaustion | Very strong | Multiple overlapping caps |
| Audit gaps | Strong | All paths produce records or visible ToolResult |

**Highest residual risk:** Prompt injection leading to a semantically valid tool call that the structural guards cannot distinguish from legitimate use.
