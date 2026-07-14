# AUTOMATED SOURCE CODE DNA FORENSICS & LIVING ARCHITECTURE REPORT

> Generated deterministically by `scripts/dna_forensics.py` (Principal Edition).

## 1. Discovery & Execution Metrics

| Metric | Computed Value |
| :--- | :--- |
| **Files Scanned** | `125` |
| **Files Successfully Parsed** | `125` |
| **Files Skipped** | `0` |
| **Parse Failures** | `0` |
| **Total Classes Detected** | `195` |
| **Total Functions/Methods Detected** | `1003` |

## 2. Deterministic Quality Scorecard

| Dimension | Score (0-100) | Assessment |
| :--- | :--- | :--- |
| **Overall Composite Score** | **37** | 🔴 Critical Attention Required |
| Architecture & Layer Discipline | `85` | Base 100 (-15 per layer violation) |
| Security & Trust Boundaries | `0` | Base 100 (-10 per security risk) |
| Complexity & Nesting Health | `40` | Base 100 (-10 per CC >= 15 hotspot) |
| Dependency & Coupling Health | `60` | Base 100 (-20 per circular cycle) |
| Documentation Coverage | `38` | Computed docstring ratio |
| Maintainability Index | `0` | Penalizes dead code & unused imports |

### Itemized Score Deductions

- [-15 Arch] core/tui.py: Layer Violation: Core kernel cannot import UI renderer. Found import `ui.repl_termux`.
- [-10 Security] core/self_refinement.py:59 (DYNAMIC_CODE_EXECUTION)
- [-10 Security] core/test_matrix_evaluator.py:93 (DYNAMIC_CODE_EXECUTION)
- [-10 Security] core/test_runner_wrapper.py:20 (SUBPROCESS_EXECUTION)
- [-10 Security] core/utils.py:40 (SUBPROCESS_EXECUTION)
- [-10 Security] core/utils.py:74 (SUBPROCESS_EXECUTION)
- [-10 Security] core/utils.py:111 (SUBPROCESS_EXECUTION)
- [-10 Security] core/uv_isolation_manager.py:61 (SUBPROCESS_EXECUTION)
- [-10 Security] nabd_logo.py:12 (SUBPROCESS_EXECUTION)
- [-10 Security] scripts/finalize.py:74 (SUBPROCESS_EXECUTION)
- [-10 Security] tools/git_tool.py:24 (SUBPROCESS_EXECUTION)
- [-10 Security] tools/git_tool.py:42 (SUBPROCESS_EXECUTION)
- [-10 Security] tools/secure_tools.py:220 (SUBPROCESS_EXECUTION)
- [-10 Security] tools/secure_tools.py:301 (SUBPROCESS_EXECUTION)
- [-10 Complexity] StructuralVerifier.verify (CC=18)

## 3. Verified Security & Architectural Evidence Log

| File | Symbol | Line | Rule ID | Category | Description | Confidence | Type |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| [core/evidence.py](file://core/evidence.py#L241) | `StructuralVerifier.verify` | 241 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 18 (threshold >= 15). | HIGH | Observed |
| [core/parser.py](file://core/parser.py#L161) | `validate_tool_call` | 161 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 28 (threshold >= 15). | HIGH | Observed |
| [core/sanitize.py](file://core/sanitize.py#L86) | `sanitize` | 86 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 18 (threshold >= 15). | HIGH | Observed |
| [core/self_refinement.py](file://core/self_refinement.py#L59) | `SafeExecutionSandbox.smoke_test_code` | 59 | **SEC-02** | DYNAMIC_CODE_EXECUTION | Dangerous dynamic execution call `exec` detected. | HIGH | Observed |
| [core/test_matrix_evaluator.py](file://core/test_matrix_evaluator.py#L93) | `TestMatrixEvaluator.evaluate_code_suite` | 93 | **SEC-02** | DYNAMIC_CODE_EXECUTION | Dangerous dynamic execution call `exec` detected. | HIGH | Observed |
| [core/test_runner_wrapper.py](file://core/test_runner_wrapper.py#L20) | `run_tests_as_evidence` | 20 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [core/utils.py](file://core/utils.py#L10) | `safe_execute_command` | 10 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 18 (threshold >= 15). | HIGH | Observed |
| [core/utils.py](file://core/utils.py#L40) | `safe_execute_command` | 40 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.Popen` | HIGH | Observed |
| [core/utils.py](file://core/utils.py#L74) | `safe_execute_command` | 74 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.Popen` | HIGH | Observed |
| [core/utils.py](file://core/utils.py#L111) | `safe_execute_command` | 111 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [core/uv_isolation_manager.py](file://core/uv_isolation_manager.py#L61) | `UvIsolationManager.run_in_isolated_env` | 61 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [engine/loop.py](file://engine/loop.py#L161) | `ExecutionLoop.run` | 161 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 31 (threshold >= 15). | HIGH | Observed |
| [nabd_logo.py](file://nabd_logo.py#L12) | `get_git_repository_name` | 12 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [scripts/finalize.py](file://scripts/finalize.py#L74) | `count_tests` | 74 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [smolagents/__init__.py](file://smolagents/__init__.py#L238) | `CodeAgent.run` | 238 | **COMPLEX-01** | HIGH_CYCLOMATIC_COMPLEXITY | Function cyclomatic complexity is 31 (threshold >= 15). | HIGH | Observed |
| [tools/git_tool.py](file://tools/git_tool.py#L24) | `push_and_verify_evidence` | 24 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [tools/git_tool.py](file://tools/git_tool.py#L42) | `push_and_verify_evidence` | 42 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [tools/secure_tools.py](file://tools/secure_tools.py#L220) | `SecureGitInspector.forward` | 220 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [tools/secure_tools.py](file://tools/secure_tools.py#L301) | `SecureTestRunner.forward` | 301 | **SEC-01** | SUBPROCESS_EXECUTION | Process execution via `subprocess.run` | HIGH | Observed |
| [core/tui.py](file://core/tui.py#L1) | `<module>` | 1 | **ARCH-01** | ARCHITECTURE_LAYER_VIOLATION | Layer Violation: Core kernel cannot import UI renderer. Found import `ui.repl_termux`. | HIGH | Observed |

## 4. Module Coupling & Instability Rankings (Top 15)

| Module Path | Fan-In (Incoming) | Fan-Out (Outgoing) | Instability Index (0..1) |
| :--- | :--- | :--- | :--- |
| `core/__init__.py` | `69` | `19` | `0.22` |
| `tools/__init__.py` | `24` | `8` | `0.25` |
| `engine/__init__.py` | `23` | `3` | `0.12` |
| `engine/loop.py` | `7` | `13` | `0.65` |
| `tools/secure_tools.py` | `10` | `9` | `0.47` |
| `engine/deep_agent.py` | `4` | `13` | `0.76` |
| `core/agent_manager.py` | `6` | `11` | `0.65` |
| `smolagents/__init__.py` | `11` | `6` | `0.35` |
| `core/sanitize.py` | `17` | `0` | `0.00` |
| `core/parser.py` | `14` | `2` | `0.12` |
| `core/app_context.py` | `0` | `14` | `1.00` |
| `core/memory.py` | `10` | `4` | `0.29` |
| `core/evidence.py` | `14` | `0` | `0.00` |
| `core/llm.py` | `7` | `6` | `0.46` |
| `core/multi_agent_orchestrator.py` | `0` | `12` | `1.00` |

### Strongly Connected Components (Circular Dependencies)

- **Cycle:** `core/skills.py` <---> `core/bootloader.py` <---> `engine/deep_agent.py` <---> `engine/tool_registry.py` <---> `engine/dispatcher.py` <---> `core/utils.py` <---> `core/parser.py` <---> `core/security.py` <---> `tools/shell.py` <---> `tools/web_search.py` <---> `tools/memory.py` <---> `tools/__init__.py` <---> `tools/file_system.py` <---> `tools/secure_tools.py` <---> `core/memory.py` <---> `smolagents/tools.py` <---> `core/ui_bridge.py` <---> `smolagents/__init__.py` <---> `core/llm.py` <---> `llm_router.py` <---> `engine/loop.py` <---> `engine/__init__.py` <---> `core/metrics.py` <---> `core/diff_matrix.py` <---> `core/__init__.py`
- **Cycle:** `multi_agent/orchestrator.py` <---> `multi_agent/__init__.py`

## 5. Execution & Call Graph DNA

- **Detected Recursive Functions (2):** `core.agent_manager:walk`, `core.repo_scanner:walk`
- **Detected Orphan Functions (748):** `core.agent_manager:execute_with_verification`, `core.agent_observer:AgentObserver.on_action_triggered`, `core.agent_observer:AgentObserver.on_agent_thought`, `core.agent_observer:AgentObserver.on_file_modified`, `core.agent_observer:AgentObserver.on_plan_updated`, `core.agent_observer:AgentObserver.on_status_changed`, `core.app_context:AppContext.build`, `core.bootloader:NabdBootloader.__init__`, `core.bootloader:NabdBootloader._excepthook`, `core.bootloader:NabdBootloader.boot`

---
*Generated by `scripts/dna_forensics.py` — Principal Automated Source Code DNA Engine.*