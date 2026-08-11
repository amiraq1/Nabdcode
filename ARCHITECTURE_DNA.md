# AUTOMATED SOURCE CODE DNA FORENSICS & LIVING ARCHITECTURE REPORT

> Generated deterministically by `scripts/dna_forensics.py` (Principal Edition).

## 1. Discovery & Execution Metrics

| Metric | Computed Value |
| :--- | :--- |
| **Files Scanned** | `442` |
| **Files Successfully Parsed** | `442` |
| **Files Skipped** | `1` |
| **Parse Failures** | `0` |
| **Total Classes Detected** | `711` |
| **Total Functions/Methods Detected** | `3980` |

## 2. Deterministic Quality Scorecard

| Dimension | Score (0-100) | Assessment |
| :--- | :--- | :--- |
| **Overall Composite Score** | **35** | 🔴 Critical Attention Required |
| Architecture & Layer Discipline | `85` | Base 100 (-15 per layer violation) |
| Security & Trust Boundaries | `0` | Base 100 (-10 per security risk) |
| Complexity & Nesting Health | `0` | Base 100 (-10 per CC >= 15 hotspot) |
| Dependency & Coupling Health | `80` | Base 100 (-20 per circular cycle) |
| Documentation Coverage | `48` | Computed docstring ratio |
| Maintainability Index | `0` | Penalizes dead code & unused imports |

### Itemized Score Deductions

- [-15 Arch] core/commands/auto_scan.py: Layer Violation: Core kernel cannot import UI renderer. Found import `ui.repl_termux`.
- [-10 Security] core/kernel/subprocess_guard.py:290 (SUBPROCESS_EXECUTION)
- [-10 Security] core/kernel/subprocess_guard.py:394 (SUBPROCESS_EXECUTION)
- [-10 Security] core/kernel/subprocess_guard.py:470 (SUBPROCESS_EXECUTION)
- [-10 Security] core/kernel/subprocess_guard.py:536 (SUBPROCESS_EXECUTION)
- [-10 Security] core/kernel/subprocess_guard.py:572 (SUBPROCESS_EXECUTION)
- [-10 Security] core/kernel/subprocess_guard.py:593 (SUBPROCESS_EXECUTION)
- [-10 Security] scripts/finalize.py:74 (SUBPROCESS_EXECUTION)
- [-10 Security] tests/test_am8_d1_primitives.py:428 (SUBPROCESS_EXECUTION)
- [-10 Security] tests/test_am8_d1_primitives.py:584 (SUBPROCESS_EXECUTION)
- [-10 Security] tests/test_fix_path_traversal.py:15 (SUBPROCESS_EXECUTION)
- [-10 Security] tests/test_gate11_fresh_process.py:141 (SUBPROCESS_EXECUTION)
- [-10 Security] tests/test_gate11_fresh_process.py:166 (SUBPROCESS_EXECUTION)
- [-10 Security] tests/test_phase21_evidence_restore.py:235 (SUBPROCESS_EXECUTION)
- [-10 Security] tests/test_phase21_evidence_restore.py:269 (SUBPROCESS_EXECUTION)

## 3. Verified Security & Architectural Evidence Log

| File | Symbol | Line | Rule ID | Category | Description | Confidence | Type |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| [core/accept_edits_state.py](file://core/accept_edits_state.py#L489) | `load_and_reconcile_journal` | 489 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 15 (threshold >= 15). | HIGH | Observed |
| [core/accept_edits_state.py](file://core/accept_edits_state.py#L820) | `reconstruct_operations` | 820 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 37 (threshold >= 15). | HIGH | Observed |
| [core/accept_edits_state.py](file://core/accept_edits_state.py#L1054) | `_compact_journal` | 1054 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 20 (threshold >= 15). | HIGH | Observed |
| [core/accept_edits_state.py](file://core/accept_edits_state.py#L1560) | `accept_edit` | 1560 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 33 (threshold >= 15). | HIGH | Observed |
| [core/accept_edits_state.py](file://core/accept_edits_state.py#L1896) | `reject_edit` | 1896 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 16 (threshold >= 15). | HIGH | Observed |
| [core/app_context.py](file://core/app_context.py#L50) | `AppContext.build` | 50 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 16 (threshold >= 15). | HIGH | Observed |
| [core/artifact_manager.py](file://core/artifact_manager.py#L280) | `ArtifactManager._prune_locked` | 280 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 18 (threshold >= 15). | HIGH | Observed |
| [core/canonicalize.py](file://core/canonicalize.py#L1) | `canonicalize` | 1 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 36 (threshold >= 15). | HIGH | Observed |
| [core/convergence_gate.py](file://core/convergence_gate.py#L123) | `_todo_has_matching_evidence` | 123 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 18 (threshold >= 15). | HIGH | Observed |
| [core/convergence_gate.py](file://core/convergence_gate.py#L238) | `can_finalize` | 238 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 27 (threshold >= 15). | HIGH | Observed |
| [core/convergence_gate.py](file://core/convergence_gate.py#L478) | `classify_claim` | 478 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 28 (threshold >= 15). | HIGH | Observed |
| [core/investigation.py](file://core/investigation.py#L162) | `CoverageMetrics.update` | 162 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 16 (threshold >= 15). | HIGH | Observed |
| [core/kernel/security.py](file://core/kernel/security.py#L274) | `_validate_segment_args` | 274 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 19 (threshold >= 15). | HIGH | Observed |
| [core/kernel/subprocess_guard.py](file://core/kernel/subprocess_guard.py#L238) | `SubprocessGuard.run_agent_pipeline` | 238 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 17 (threshold >= 15). | HIGH | Observed |
| [core/kernel/subprocess_guard.py](file://core/kernel/subprocess_guard.py#L290) | `SubprocessGuard.run_agent_pipeline` | 290 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.Popen` | HIGH | Observed |
| [core/kernel/subprocess_guard.py](file://core/kernel/subprocess_guard.py#L394) | `SubprocessGuard.spawn_agent_background` | 394 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.Popen` | HIGH | Observed |
| [core/kernel/subprocess_guard.py](file://core/kernel/subprocess_guard.py#L470) | `SubprocessGuard.run_infra` | 470 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [core/kernel/subprocess_guard.py](file://core/kernel/subprocess_guard.py#L536) | `SubprocessGuard.spawn_infra` | 536 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.Popen` | HIGH | Observed |
| [core/kernel/subprocess_guard.py](file://core/kernel/subprocess_guard.py#L572) | `SubprocessGuard._run_simple` | 572 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [core/kernel/subprocess_guard.py](file://core/kernel/subprocess_guard.py#L593) | `SubprocessGuard._run_tokens` | 593 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [core/verifier.py](file://core/verifier.py#L264) | `check_final_answer_claim_gate` | 264 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 22 (threshold >= 15). | HIGH | Observed |
| [core/xml_tool_parser.py](file://core/xml_tool_parser.py#L51) | `openai_fc_to_json` | 51 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 22 (threshold >= 15). | HIGH | Observed |
| [engine/_budget.py](file://engine/_budget.py#L98) | `_BudgetMixin._maybe_force_partial_answer` | 98 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 18 (threshold >= 15). | HIGH | Observed |
| [engine/_convergence.py](file://engine/_convergence.py#L83) | `_ConvergenceMixin._extract_listing_files` | 83 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 19 (threshold >= 15). | HIGH | Observed |
| [engine/_convergence.py](file://engine/_convergence.py#L362) | `_ConvergenceMixin._emit_final` | 362 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 31 (threshold >= 15). | HIGH | Observed |
| [engine/deep_agent.py](file://engine/deep_agent.py#L462) | `NativeDeepAgent.execute_node` | 462 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 17 (threshold >= 15). | HIGH | Observed |
| [engine/deep_agent.py](file://engine/deep_agent.py#L718) | `NativeDeepAgent.run` | 718 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 16 (threshold >= 15). | HIGH | Observed |
| [engine/loop.py](file://engine/loop.py#L416) | `ExecutionLoop._invoke_llm_and_normalize` | 416 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 26 (threshold >= 15). | HIGH | Observed |
| [llm_router.py](file://llm_router.py#L90) | `ProviderRouter.generate_stream` | 90 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 20 (threshold >= 15). | HIGH | Observed |
| [main.py](file://main.py#L49) | `_summarise_tool` | 49 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 15 (threshold >= 15). | HIGH | Observed |
| [main.py](file://main.py#L491) | `_process_slash_command` | 491 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 32 (threshold >= 15). | HIGH | Observed |
| [scripts/finalize.py](file://scripts/finalize.py#L74) | `count_tests` | 74 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [smolagents/__init__.py](file://smolagents/__init__.py#L196) | `CodeAgent._try_fast_path` | 196 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 15 (threshold >= 15). | HIGH | Observed |
| [smolagents/__init__.py](file://smolagents/__init__.py#L248) | `CodeAgent._run_react_loop` | 248 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 15 (threshold >= 15). | HIGH | Observed |
| [tests/test_am8_d1_primitives.py](file://tests/test_am8_d1_primitives.py#L428) | `run` | 428 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [tests/test_am8_d1_primitives.py](file://tests/test_am8_d1_primitives.py#L584) | `test_no_test_mutates_shared_design_globals` | 584 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [tests/test_fix_path_traversal.py](file://tests/test_fix_path_traversal.py#L15) | `test_fix_rejects_traversal_one_shot` | 15 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [tests/test_forbidden_changes_policy.py](file://tests/test_forbidden_changes_policy.py#L53) | `test_no_heavy_imports_in_core_or_engine` | 53 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 15 (threshold >= 15). | HIGH | Observed |
| [tests/test_gate11_fresh_process.py](file://tests/test_gate11_fresh_process.py#L141) | `TestGate11FreshProcessRestart._run_test_for_stage` | 141 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.Popen` | HIGH | Observed |
| [tests/test_gate11_fresh_process.py](file://tests/test_gate11_fresh_process.py#L166) | `TestGate11FreshProcessRestart._run_test_for_stage` | 166 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [tests/test_phase21_evidence_restore.py](file://tests/test_phase21_evidence_restore.py#L235) | `test_evidence_survives_fresh_process` | 235 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [tests/test_phase21_evidence_restore.py](file://tests/test_phase21_evidence_restore.py#L269) | `test_evidence_survives_fresh_process` | 269 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [tests/test_phase21_evidence_restore.py](file://tests/test_phase21_evidence_restore.py#L328) | `test_evidence_truncated_tail_rejected` | 328 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [tests/test_phase21_evidence_restore.py](file://tests/test_phase21_evidence_restore.py#L371) | `test_evidence_corrupted_jsonl_rejected` | 371 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [tests/test_phase21_evidence_restore.py](file://tests/test_phase21_evidence_restore.py#L415) | `test_evidence_counter_continuity_across_processes` | 415 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [tests/test_phase21_evidence_restore.py](file://tests/test_phase21_evidence_restore.py#L448) | `test_evidence_counter_continuity_across_processes` | 448 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [tests/test_phase21_evidence_restore.py](file://tests/test_phase21_evidence_restore.py#L490) | `test_evidence_empty_restore` | 490 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [tests/test_phase21_evidence_restore.py](file://tests/test_phase21_evidence_restore.py#L538) | `test_evidence_no_duplicate_terminal_across_restart` | 538 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [tests/test_phase21_evidence_restore.py](file://tests/test_phase21_evidence_restore.py#L582) | `test_evidence_no_duplicate_terminal_across_restart` | 582 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [tests/test_phase22_journal_core.py](file://tests/test_phase22_journal_core.py#L1059) | `TestFreshProcessRestart.test_prepared_survives_subprocess_restart` | 1059 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [tests/test_phase22_journal_core.py](file://tests/test_phase22_journal_core.py#L1096) | `TestFreshProcessRestart.test_sigkill_preserves_journal` | 1096 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.Popen` | HIGH | Observed |
| [tests/test_phase22_journal_core.py](file://tests/test_phase22_journal_core.py#L1125) | `TestFreshProcessRestart.test_sigkill_preserves_journal` | 1125 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [tests/test_phase22_journal_core.py](file://tests/test_phase22_journal_core.py#L1384) | `TestCompaction.test_restart_after_compaction` | 1384 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [tests/test_phase22_journal_core.py](file://tests/test_phase22_journal_core.py#L1571) | `TestReconstructionOutcomes._write_and_verify` | 1571 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [tests/test_phase22_journal_core.py](file://tests/test_phase22_journal_core.py#L1839) | `TestCrossProcessSerialization.test_cross_process_writers_are_serialized` | 1839 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.Popen` | HIGH | Observed |
| [tests/test_phase22_journal_core.py](file://tests/test_phase22_journal_core.py#L1843) | `TestCrossProcessSerialization.test_cross_process_writers_are_serialized` | 1843 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.Popen` | HIGH | Observed |
| [tests/test_phase22_journal_core.py](file://tests/test_phase22_journal_core.py#L1935) | `TestCrossProcessSerialization.test_append_waits_for_cross_process_compaction` | 1935 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.Popen` | HIGH | Observed |
| [tests/test_phase22_journal_core.py](file://tests/test_phase22_journal_core.py#L1939) | `TestCrossProcessSerialization.test_append_waits_for_cross_process_compaction` | 1939 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.Popen` | HIGH | Observed |
| [tests/test_provenance.py](file://tests/test_provenance.py#L30) | `_git` | 30 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [tests/test_provenance_resolution.py](file://tests/test_provenance_resolution.py#L29) | `_git` | 29 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [tests/test_termux_prefix_guard.py](file://tests/test_termux_prefix_guard.py#L26) | `test_termux_prefix_guard_exits_when_not_in_termux` | 26 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [tests/test_termux_prefix_guard.py](file://tests/test_termux_prefix_guard.py#L52) | `test_termux_prefix_guard_passes_in_termux` | 52 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [tests/test_verify_protocol.py](file://tests/test_verify_protocol.py#L24) | `run_script` | 24 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [tests/test_verify_protocol.py](file://tests/test_verify_protocol.py#L41) | `TestVerifyProtocol.test_ignored_paths_are_not_scanned` | 41 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [tools/file_system.py](file://tools/file_system.py#L71) | `FileSystemTool.execute` | 71 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 20 (threshold >= 15). | HIGH | Observed |
| [tools/secure_tools.py](file://tools/secure_tools.py#L156) | `SecureWorkspaceReader.forward` | 156 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 15 (threshold >= 15). | HIGH | Observed |
| [tools/secure_tools.py](file://tools/secure_tools.py#L669) | `SecureShellTool.forward` | 669 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 16 (threshold >= 15). | HIGH | Observed |
| [ui/repl_termux.py](file://ui/repl_termux.py#L146) | `_strip_tool_call_lines` | 146 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 22 (threshold >= 15). | HIGH | Observed |
| [ui/repl_termux.py](file://ui/repl_termux.py#L900) | `extract_clean_answer` | 900 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 16 (threshold >= 15). | HIGH | Observed |
| [core/commands/auto_scan.py](file://core/commands/auto_scan.py#L1) | `<module>` | 1 | **ARCH-01** | ARCHITECTURE_LAYER_VIOLATION | Layer Violation: Core kernel cannot import UI renderer. Found import `ui.repl_termux`. | HIGH | Observed |

## 4. Module Coupling & Instability Rankings (Top 15)

| Module Path | Fan-In (Incoming) | Fan-Out (Outgoing) | Instability Index (0..1) |
| :--- | :--- | :--- | :--- |
| `engine/loop.py` | `46` | `37` | `0.45` |
| `core/evidence.py` | `57` | `1` | `0.02` |
| `engine/state.py` | `51` | `1` | `0.02` |
| `main.py` | `14` | `29` | `0.67` |
| `tools/models.py` | `39` | `0` | `0.00` |
| `ui/design/theme/semantic.py` | `33` | `1` | `0.03` |
| `core/app_context.py` | `11` | `20` | `0.65` |
| `core/parser.py` | `26` | `5` | `0.16` |
| `core/kernel/events.py` | `30` | `1` | `0.03` |
| `engine/_loop_helpers.py` | `20` | `10` | `0.33` |
| `engine/deep_agent.py` | `11` | `16` | `0.59` |
| `engine/tool_registry.py` | `25` | `1` | `0.04` |
| `ui/design/primitives/__init__.py` | `13` | `12` | `0.48` |
| `tools/base.py` | `21` | `3` | `0.12` |
| `ui/repl_termux.py` | `9` | `14` | `0.61` |

### Strongly Connected Components (Circular Dependencies)

- **Cycle:** `ui/widgets/tool_result_list.py` <---> `ui/repl_termux.py` <---> `core/commands/auto_scan.py`

## 5. Execution & Call Graph DNA

- **Detected Recursive Functions (3):** `core.agent_manager:walk`, `core.display:shorten_paths`, `core.repo_scanner:walk`
- **Detected Orphan Functions (3369):** `adapters.lightpanda_adapter:LightpandaAdapter.__init__`, `adapters.lightpanda_adapter:LightpandaAdapter._get_free_port`, `adapters.lightpanda_adapter:LightpandaAdapter._sanitize_and_compact_result`, `adapters.lightpanda_adapter:LightpandaAdapter.execute_tool`, `adapters.lightpanda_adapter:LightpandaAdapter.start`, `adapters.lightpanda_adapter:LightpandaAdapter.stop`, `core.accept_edits_state:_compact_journal`, `core.accept_edits_state:_detect_invalid_event_sequence`, `core.accept_edits_state:_get_path_lock_registry_snapshot`, `core.accept_edits_state:_highlight_word_changes`

---
*Generated by `scripts/dna_forensics.py` — Principal Automated Source Code DNA Engine.*