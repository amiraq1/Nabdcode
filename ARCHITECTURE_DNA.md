# AUTOMATED SOURCE CODE DNA FORENSICS & LIVING ARCHITECTURE REPORT

> Generated deterministically by `scripts/dna_forensics.py` (Principal Edition).

## 1. Discovery & Execution Metrics

| Metric | Computed Value |
| :--- | :--- |
| **Files Scanned** | `228` |
| **Files Successfully Parsed** | `228` |
| **Files Skipped** | `5` |
| **Parse Failures** | `0` |
| **Total Classes Detected** | `375` |
| **Total Functions/Methods Detected** | `1950` |

## 2. Deterministic Quality Scorecard

| Dimension | Score (0-100) | Assessment |
| :--- | :--- | :--- |
| **Overall Composite Score** | **40** | 🔴 Critical Attention Required |
| Architecture & Layer Discipline | `100` | Base 100 (-15 per layer violation) |
| Security & Trust Boundaries | `0` | Base 100 (-10 per security risk) |
| Complexity & Nesting Health | `0` | Base 100 (-10 per CC >= 15 hotspot) |
| Dependency & Coupling Health | `100` | Base 100 (-20 per circular cycle) |
| Documentation Coverage | `40` | Computed docstring ratio |
| Maintainability Index | `0` | Penalizes dead code & unused imports |

### Itemized Score Deductions

- [-10 Security] core/kernel/subprocess_guard.py:160 (SUBPROCESS_EXECUTION)
- [-10 Security] core/kernel/subprocess_guard.py:200 (SUBPROCESS_EXECUTION)
- [-10 Security] core/kernel/subprocess_guard.py:225 (SUBPROCESS_EXECUTION)
- [-10 Security] core/kernel/subprocess_guard.py:235 (SUBPROCESS_EXECUTION)
- [-10 Security] core/kernel/subprocess_guard.py:252 (SUBPROCESS_EXECUTION)
- [-10 Security] core/self_refinement.py:59 (DYNAMIC_CODE_EXECUTION)
- [-10 Security] core/test_matrix_evaluator.py:93 (DYNAMIC_CODE_EXECUTION)
- [-10 Security] core/utils.py:60 (SUBPROCESS_EXECUTION)
- [-10 Security] core/utils.py:103 (SUBPROCESS_EXECUTION)
- [-10 Security] scripts/finalize.py:74 (SUBPROCESS_EXECUTION)
- [-10 Complexity] CoverageMetrics.update (CC=16)
- [-10 Complexity] UIBridge.emit (CC=17)
- [-10 Complexity] openai_fc_to_json (CC=22)
- [-10 Complexity] _BudgetMixin._maybe_force_partial_answer (CC=17)
- [-10 Complexity] _ContextMixin._inject_runtime_context (CC=20)

## 3. Verified Security & Architectural Evidence Log

| File | Symbol | Line | Rule ID | Category | Description | Confidence | Type |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| [core/investigation.py](file://core/investigation.py#L142) | `CoverageMetrics.update` | 142 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 16 (threshold >= 15). | HIGH | Observed |
| [core/kernel/subprocess_guard.py](file://core/kernel/subprocess_guard.py#L160) | `SubprocessGuard.run_infra` | 160 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [core/kernel/subprocess_guard.py](file://core/kernel/subprocess_guard.py#L200) | `SubprocessGuard.spawn_infra` | 200 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.Popen` | HIGH | Observed |
| [core/kernel/subprocess_guard.py](file://core/kernel/subprocess_guard.py#L225) | `SubprocessGuard._run_simple` | 225 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` with `shell=True` risk! | HIGH | Observed |
| [core/kernel/subprocess_guard.py](file://core/kernel/subprocess_guard.py#L235) | `SubprocessGuard._run_simple` | 235 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [core/kernel/subprocess_guard.py](file://core/kernel/subprocess_guard.py#L252) | `SubprocessGuard._run_tokens` | 252 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [core/self_refinement.py](file://core/self_refinement.py#L59) | `SafeExecutionSandbox.smoke_test_code` | 59 | **SEC-02** | DYNAMIC_CODE_EXECUTION | Dangerous dynamic execution call `exec` detected. | HIGH | Observed |
| [core/test_matrix_evaluator.py](file://core/test_matrix_evaluator.py#L93) | `TestMatrixEvaluator.evaluate_code_suite` | 93 | **SEC-02** | DYNAMIC_CODE_EXECUTION | Dangerous dynamic execution call `exec` detected. | HIGH | Observed |
| [core/ui_bridge.py](file://core/ui_bridge.py#L84) | `UIBridge.emit` | 84 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 17 (threshold >= 15). | HIGH | Observed |
| [core/utils.py](file://core/utils.py#L60) | `_handle_background` | 60 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.Popen` | HIGH | Observed |
| [core/utils.py](file://core/utils.py#L103) | `_handle_piped` | 103 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.Popen` | HIGH | Observed |
| [core/xml_tool_parser.py](file://core/xml_tool_parser.py#L51) | `openai_fc_to_json` | 51 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 22 (threshold >= 15). | HIGH | Observed |
| [engine/_budget.py](file://engine/_budget.py#L84) | `_BudgetMixin._maybe_force_partial_answer` | 84 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 17 (threshold >= 15). | HIGH | Observed |
| [engine/_context.py](file://engine/_context.py#L217) | `_ContextMixin._inject_runtime_context` | 217 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 20 (threshold >= 15). | HIGH | Observed |
| [engine/_convergence.py](file://engine/_convergence.py#L82) | `_ConvergenceMixin._extract_listing_files` | 82 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 19 (threshold >= 15). | HIGH | Observed |
| [engine/_convergence.py](file://engine/_convergence.py#L340) | `_ConvergenceMixin._emit_final` | 340 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 16 (threshold >= 15). | HIGH | Observed |
| [engine/deep_agent.py](file://engine/deep_agent.py#L462) | `NativeDeepAgent.execute_node` | 462 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 17 (threshold >= 15). | HIGH | Observed |
| [engine/deep_agent.py](file://engine/deep_agent.py#L718) | `NativeDeepAgent.run` | 718 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 15 (threshold >= 15). | HIGH | Observed |
| [engine/loop.py](file://engine/loop.py#L401) | `ExecutionLoop._invoke_llm_and_normalize` | 401 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 23 (threshold >= 15). | HIGH | Observed |
| [engine/loop.py](file://engine/loop.py#L1055) | `ExecutionLoop._pre_dispatch_guard` | 1055 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 17 (threshold >= 15). | HIGH | Observed |
| [engine/loop.py](file://engine/loop.py#L1269) | `ExecutionLoop._dispatch_and_record_evidence` | 1269 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 22 (threshold >= 15). | HIGH | Observed |
| [llm_router.py](file://llm_router.py#L90) | `ProviderRouter.generate_stream` | 90 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 20 (threshold >= 15). | HIGH | Observed |
| [main.py](file://main.py#L531) | `main` | 531 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 15 (threshold >= 15). | HIGH | Observed |
| [scripts/finalize.py](file://scripts/finalize.py#L74) | `count_tests` | 74 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [smolagents/__init__.py](file://smolagents/__init__.py#L196) | `CodeAgent._try_fast_path` | 196 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 15 (threshold >= 15). | HIGH | Observed |
| [smolagents/__init__.py](file://smolagents/__init__.py#L248) | `CodeAgent._run_react_loop` | 248 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 15 (threshold >= 15). | HIGH | Observed |
| [tools/code_intelligence.py](file://tools/code_intelligence.py#L156) | `CodeIntelligenceTool._get_definition` | 156 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 22 (threshold >= 15). | HIGH | Observed |
| [tools/secure_tools.py](file://tools/secure_tools.py#L156) | `SecureWorkspaceReader.forward` | 156 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 15 (threshold >= 15). | HIGH | Observed |
| [tools/secure_tools.py](file://tools/secure_tools.py#L644) | `SecureShellTool.forward` | 644 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 16 (threshold >= 15). | HIGH | Observed |
| [ui/repl_termux.py](file://ui/repl_termux.py#L402) | `render_agent_events` | 402 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 21 (threshold >= 15). | HIGH | Observed |
| [ui/repl_termux.py](file://ui/repl_termux.py#L536) | `run_repl` | 536 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 24 (threshold >= 15). | HIGH | Observed |
| [ui/repl_termux.py](file://ui/repl_termux.py#L768) | `extract_clean_answer` | 768 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 16 (threshold >= 15). | HIGH | Observed |

## 4. Module Coupling & Instability Rankings (Top 15)

| Module Path | Fan-In (Incoming) | Fan-Out (Outgoing) | Instability Index (0..1) |
| :--- | :--- | :--- | :--- |
| `engine/loop.py` | `25` | `30` | `0.55` |
| `engine/state.py` | `34` | `1` | `0.03` |
| `core/evidence.py` | `30` | `1` | `0.03` |
| `core/parser.py` | `24` | `5` | `0.17` |
| `tools/models.py` | `29` | `0` | `0.00` |
| `tools/base.py` | `21` | `3` | `0.12` |
| `core/kernel/events.py` | `22` | `1` | `0.04` |
| `core/multi_agent_orchestrator.py` | `2` | `20` | `0.91` |
| `main.py` | `4` | `18` | `0.82` |
| `tools/secure_tools.py` | `8` | `14` | `0.64` |
| `core/app_context.py` | `5` | `16` | `0.76` |
| `core/sanitize.py` | `21` | `0` | `0.00` |
| `engine/deep_agent.py` | `7` | `13` | `0.65` |
| `core/agent_manager.py` | `5` | `12` | `0.71` |
| `core/storage.py` | `13` | `4` | `0.24` |

## 5. Execution & Call Graph DNA

- **Detected Recursive Functions (2):** `core.agent_manager:walk`, `core.repo_scanner:walk`
- **Detected Orphan Functions (1621):** `adapters.lightpanda_adapter:LightpandaAdapter.__init__`, `adapters.lightpanda_adapter:LightpandaAdapter._get_free_port`, `adapters.lightpanda_adapter:LightpandaAdapter._sanitize_and_compact_result`, `adapters.lightpanda_adapter:LightpandaAdapter.execute_tool`, `adapters.lightpanda_adapter:LightpandaAdapter.start`, `adapters.lightpanda_adapter:LightpandaAdapter.stop`, `core.adapters:_KernelPermissionEngine.__init__`, `core.adapters:_KernelPermissionEngine.check_access`, `core.adapters:_KernelPermissionEngine.evaluate`, `core.adapters:_KernelSecurityEngine.validate`

---
*Generated by `scripts/dna_forensics.py` — Principal Automated Source Code DNA Engine.*