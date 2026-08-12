# L0 — فهرس مخاطر الشجرة الكاملة

**المرجع:** amiraq1/Nabdcode @ am8/d-0 HEAD `63e7899b` (worktree يتضمن موجات NBD غير ملتزمة)
**طريقة التحقق:** static scan حتمي (أنماط regex × حجم × نوع) — لا تشغيل

## ملخص المخاطر

| المستوى | العدد |
|---|---|
| CRITICAL | 33 |
| HIGH | 43 |
| MEDIUM | 264 |
| LOW | 278 |
| INFO | 375 |

## الملخص بالوحدة

| الوحدة | CRITICAL | HIGH | MEDIUM | LOW | INFO |
|---|---|---|---|---|---|
| .claude | 0 | 0 | 1 | 0 | 0 |
| .commandcode | 2 | 1 | 0 | 0 | 1 |
| .github | 0 | 0 | 0 | 1 | 0 |
| .nabd | 0 | 0 | 1 | 3 | 0 |
| NabdBootloader | 0 | 0 | 0 | 1 | 239 |
| adapters | 1 | 0 | 0 | 1 | 0 |
| bin | 0 | 0 | 0 | 0 | 1 |
| core | 7 | 8 | 29 | 54 | 0 |
| docs | 1 | 1 | 4 | 0 | 24 |
| engine | 0 | 2 | 10 | 7 | 0 |
| logs | 0 | 1 | 57 | 1 | 85 |
| nabd_os.egg-info | 0 | 0 | 1 | 0 | 5 |
| references | 0 | 0 | 0 | 0 | 1 |
| root | 5 | 3 | 14 | 11 | 15 |
| scripts | 1 | 1 | 5 | 2 | 1 |
| sessions | 0 | 1 | 50 | 0 | 0 |
| skills | 0 | 0 | 2 | 3 | 3 |
| smolagents | 0 | 0 | 0 | 2 | 0 |
| tests | 13 | 20 | 61 | 149 | 0 |
| tools | 3 | 4 | 2 | 13 | 0 |
| ui | 0 | 1 | 27 | 28 | 0 |
| workspace | 0 | 0 | 0 | 2 | 0 |

## الملفات عالية الخطورة (CRITICAL + HIGH)

| المستوى | المسار | الأسطر | الإشارات | المالك |
|---|---|---|---|---|
| CRITICAL | `ammar.md` | 6863 | subprocess, Popen, shell=True, eval/exec | root |
| CRITICAL | `docs/DEBT_LEDGER.md` | 681 | subprocess, Popen, shell=True, file-write | docs |
| CRITICAL | `core/kernel/subprocess_guard.py` | 662 | subprocess, Popen, shell=True, eval/exec | core |
| CRITICAL | `scripts/dna_forensics.py` | 850 | subprocess, os.system, Popen, shell=True | scripts |
| CRITICAL | `tests/test_input_gateways.py` | 708 | os.system, eval/exec, destructive, secrets | tests |
| CRITICAL | `.commandcode/settings.json` | 253 | subprocess, eval/exec, file-write, secrets | .commandcode |
| CRITICAL | `tests/test_phase22_journal_core.py` | 1971 | subprocess, Popen, file-write, secrets | tests |
| CRITICAL | `tests/test_python_repl.py` | 95 | subprocess, os.system, Popen, destructive | tests |
| CRITICAL | `CORE_FILE_DNA_DISSECTION.md` | 215 | Popen, shell=True, network, secrets | root |
| CRITICAL | `session-ses_0335.md` | 2650 | subprocess, file-write, secrets, db | root |
| CRITICAL | `tests/test_gate11_fresh_process.py` | 210 | subprocess, Popen, file-write, destructive | tests |
| CRITICAL | `core/utils.py` | 169 | subprocess, shell=True, secrets, shlex | core |
| CRITICAL | `core/accept_edits_state.py` | 2077 | file-write, destructive, secrets, permissions | core |
| CRITICAL | `session-ses_03f11.md` | 2735 | network, file-write, secrets, db | root |
| CRITICAL | `tools/file_system.py` | 866 | network, file-write, destructive, secrets | tools |
| CRITICAL | `.commandcode/taste/taste-—-codebase-preferences/taste.md` | 118 | subprocess, file-write, secrets, git-write | .commandcode |
| CRITICAL | `adapters/lightpanda_adapter.py` | 109 | subprocess, Popen, network | adapters |
| CRITICAL | `tools/git_tool.py` | 330 | subprocess, secrets, git-write | tools |
| CRITICAL | `ARCHITECTURE_DNA.md` | 153 | subprocess, Popen, secrets | root |
| CRITICAL | `core/kernel/security.py` | 360 | eval/exec, network, secrets, shlex | core |
| CRITICAL | `tests/test_nbd_hardening.py` | 394 | subprocess, file-write, secrets | tests |
| CRITICAL | `tests/test_subprocess_guard.py` | 109 | Popen, secrets, git-write | tests |
| CRITICAL | `core/uv_isolation_manager.py` | 92 | subprocess, file-write, destructive | core |
| CRITICAL | `tests/test_provenance.py` | 151 | subprocess, file-write, secrets | tests |
| CRITICAL | `core/self_refinement.py` | 106 | Popen, file-write, permissions | core |
| CRITICAL | `tests/test_am8_d1_primitives.py` | 805 | subprocess, secrets | tests |
| CRITICAL | `tests/test_pending_edits_lifecycle.py` | 977 | file-write, secrets, permissions | tests |
| CRITICAL | `tests/test_terminal_node_consent_gate.py` | 140 | os.system, network, permissions | tests |
| CRITICAL | `tools/python_repl.py` | 195 | Popen, file-write, permissions | tools |
| CRITICAL | `tests/test_defect_repairs.py` | 321 | network, file-write, secrets | tests |
| CRITICAL | `tests/test_phase22_atomic_failure_safety.py` | 469 | file-write, destructive, permissions | tests |
| CRITICAL | `core/config.py` | 261 | file-write, secrets, permissions | core |
| CRITICAL | `tests/test_provenance_resolution.py` | 94 | subprocess, secrets | tests |
| HIGH | `scripts/finalize.py` | 165 | subprocess, file-write | scripts |
| HIGH | `test_results.txt` | 1586 | network, secrets, db | root |
| HIGH | `tests/test_verify_protocol.py` | 88 | subprocess, file-write | tests |
| HIGH | `CHANGELOG.md` | 86 | network, secrets, permissions | root |
| HIGH | `FINAL_AUDIT_STATUS.md` | 83 | file-write, secrets, permissions | root |
| HIGH | `core/llm.py` | 683 | network, secrets | core |
| HIGH | `core/multi_agent_orchestrator.py` | 542 | file-write, secrets | core |
| HIGH | `docs/threat_model.md` | 136 | subprocess, secrets | docs |
| HIGH | `tests/test_r44_strict_provenance.py` | 420 | file-write, destructive | tests |
| HIGH | `tests/test_sandbox_redteam.py` | 61 | eval/exec, network | tests |
| HIGH | `tests/test_tool_routing.py` | 330 | file-write, destructive | tests |
| HIGH | `tools/rag_search.py` | 562 | file-write, secrets | tools |
| HIGH | `.commandcode/taste/taste-—-communication-&-workflow/taste.md` | 81 | eval/exec, secrets | .commandcode |
| HIGH | `core/agent_manager.py` | 455 | secrets, db | core |
| HIGH | `core/context_manager.py` | 238 | file-write, secrets | core |
| HIGH | `core/dag/checkpoint.py` | 46 | file-write, destructive | core |
| HIGH | `core/prompts.py` | 168 | network, secrets | core |
| HIGH | `core/storage.py` | 1268 | file-write, db | core |
| HIGH | `engine/consent.py` | 235 | permissions, git-write | engine |
| HIGH | `tests/debug_react.py` | 66 | network, secrets | tests |
| HIGH | `tests/test_config_security.py` | 168 | secrets, permissions | tests |
| HIGH | `tests/test_gate10_no_blind_replay.py` | 143 | file-write, destructive | tests |
| HIGH | `tests/test_gate12_corruption.py` | 151 | file-write, destructive | tests |
| HIGH | `tests/test_gate13_compaction.py` | 281 | file-write, destructive | tests |
| HIGH | `tests/test_gate14_reconstruction.py` | 214 | file-write, destructive | tests |
| HIGH | `tests/test_multi_agent_graphify_parallel.py` | 127 | file-write, destructive | tests |
| HIGH | `tests/test_phase21_evidence_restore.py` | 627 | subprocess | tests |
| HIGH | `tests/test_phase5_permissions.py` | 139 | network, git-write | tests |
| HIGH | `tests/test_project_root_guard.py` | 208 | file-write, secrets | tests |
| HIGH | `tests/test_secure_tools.py` | 204 | file-write, destructive | tests |
| HIGH | `tests/test_skills.py` | 317 | network, file-write | tests |
| HIGH | `core/evidence.py` | 984 | secrets | core |
| HIGH | `engine/loop.py` | 1909 | secrets | engine |
| HIGH | `logs/engine.log` | 774 | network, secrets | logs |
| HIGH | `sessions/sess_9e166158_20260812100326.json` | 55 | network, secrets | sessions |
| HIGH | `tests/test_fix_path_traversal.py` | 63 | subprocess | tests |
| HIGH | `tests/test_phase22c_path_lock_registry.py` | 1048 | destructive | tests |
| HIGH | `tests/test_phase5_workspace.py` | 128 | file-write, permissions | tests |
| HIGH | `tests/test_termux_prefix_guard.py` | 61 | subprocess | tests |
| HIGH | `tools/protocols.py` | 101 | shell=True | tools |
| HIGH | `tools/secure_tools.py` | 949 | secrets | tools |
| HIGH | `tools/termux_monitor.py` | 131 | shell=True | tools |
| HIGH | `ui/repl_termux.py` | 1248 | secrets | ui |

## الفهرس الكامل (مرتب بالأولوية)

| المستوى | المسار | الأسطر | الحجم |
|---|---|---|---|
| CRITICAL | `ammar.md` | 6863 | 318170 |
| CRITICAL | `docs/DEBT_LEDGER.md` | 681 | 57132 |
| CRITICAL | `core/kernel/subprocess_guard.py` | 662 | 26706 |
| CRITICAL | `scripts/dna_forensics.py` | 850 | 35187 |
| CRITICAL | `tests/test_input_gateways.py` | 708 | 27266 |
| CRITICAL | `.commandcode/settings.json` | 253 | 131718 |
| CRITICAL | `tests/test_phase22_journal_core.py` | 1971 | 83025 |
| CRITICAL | `tests/test_python_repl.py` | 95 | 3783 |
| CRITICAL | `CORE_FILE_DNA_DISSECTION.md` | 215 | 31735 |
| CRITICAL | `session-ses_0335.md` | 2650 | 166892 |
| CRITICAL | `tests/test_gate11_fresh_process.py` | 210 | 7330 |
| CRITICAL | `core/utils.py` | 169 | 6353 |
| CRITICAL | `core/accept_edits_state.py` | 2077 | 83210 |
| CRITICAL | `session-ses_03f11.md` | 2735 | 120104 |
| CRITICAL | `tools/file_system.py` | 866 | 35250 |
| CRITICAL | `.commandcode/taste/taste-—-codebase-preferences/taste.md` | 118 | 37435 |
| CRITICAL | `adapters/lightpanda_adapter.py` | 109 | 4635 |
| CRITICAL | `tools/git_tool.py` | 330 | 12655 |
| CRITICAL | `ARCHITECTURE_DNA.md` | 153 | 20832 |
| CRITICAL | `core/kernel/security.py` | 360 | 13925 |
| CRITICAL | `tests/test_nbd_hardening.py` | 394 | 15006 |
| CRITICAL | `tests/test_subprocess_guard.py` | 109 | 4091 |
| CRITICAL | `core/uv_isolation_manager.py` | 92 | 3481 |
| CRITICAL | `tests/test_provenance.py` | 151 | 5096 |
| CRITICAL | `core/self_refinement.py` | 106 | 4368 |
| CRITICAL | `tests/test_am8_d1_primitives.py` | 805 | 32974 |
| CRITICAL | `tests/test_pending_edits_lifecycle.py` | 977 | 41567 |
| CRITICAL | `tests/test_terminal_node_consent_gate.py` | 140 | 8342 |
| CRITICAL | `tools/python_repl.py` | 195 | 7953 |
| CRITICAL | `tests/test_defect_repairs.py` | 321 | 12574 |
| CRITICAL | `tests/test_phase22_atomic_failure_safety.py` | 469 | 20033 |
| CRITICAL | `core/config.py` | 261 | 9278 |
| CRITICAL | `tests/test_provenance_resolution.py` | 94 | 2986 |
| HIGH | `scripts/finalize.py` | 165 | 6635 |
| HIGH | `test_results.txt` | 1586 | 165971 |
| HIGH | `tests/test_verify_protocol.py` | 88 | 3238 |
| HIGH | `CHANGELOG.md` | 86 | 4346 |
| HIGH | `FINAL_AUDIT_STATUS.md` | 83 | 5210 |
| HIGH | `core/llm.py` | 683 | 27718 |
| HIGH | `core/multi_agent_orchestrator.py` | 542 | 22387 |
| HIGH | `docs/threat_model.md` | 136 | 15893 |
| HIGH | `tests/test_r44_strict_provenance.py` | 420 | 17005 |
| HIGH | `tests/test_sandbox_redteam.py` | 61 | 2401 |
| HIGH | `tests/test_tool_routing.py` | 330 | 13624 |
| HIGH | `tools/rag_search.py` | 562 | 25381 |
| HIGH | `.commandcode/taste/taste-—-communication-&-workflow/taste.md` | 81 | 31915 |
| HIGH | `core/agent_manager.py` | 455 | 18648 |
| HIGH | `core/context_manager.py` | 238 | 9072 |
| HIGH | `core/dag/checkpoint.py` | 46 | 1814 |
| HIGH | `core/prompts.py` | 168 | 11062 |
| HIGH | `core/storage.py` | 1268 | 48059 |
| HIGH | `engine/consent.py` | 235 | 8411 |
| HIGH | `tests/debug_react.py` | 66 | 2391 |
| HIGH | `tests/test_config_security.py` | 168 | 6120 |
| HIGH | `tests/test_gate10_no_blind_replay.py` | 143 | 5398 |
| HIGH | `tests/test_gate12_corruption.py` | 151 | 6361 |
| HIGH | `tests/test_gate13_compaction.py` | 281 | 11573 |
| HIGH | `tests/test_gate14_reconstruction.py` | 214 | 9818 |
| HIGH | `tests/test_multi_agent_graphify_parallel.py` | 127 | 5489 |
| HIGH | `tests/test_phase21_evidence_restore.py` | 627 | 26842 |
| HIGH | `tests/test_phase5_permissions.py` | 139 | 4650 |
| HIGH | `tests/test_project_root_guard.py` | 208 | 7835 |
| HIGH | `tests/test_secure_tools.py` | 204 | 7699 |
| HIGH | `tests/test_skills.py` | 317 | 14459 |
| HIGH | `core/evidence.py` | 984 | 39774 |
| HIGH | `engine/loop.py` | 1909 | 92999 |
| HIGH | `logs/engine.log` | 774 | 156283 |
| HIGH | `sessions/sess_9e166158_20260812100326.json` | 55 | 8333 |
| HIGH | `tests/test_fix_path_traversal.py` | 63 | 2076 |
| HIGH | `tests/test_phase22c_path_lock_registry.py` | 1048 | 39763 |
| HIGH | `tests/test_phase5_workspace.py` | 128 | 5091 |
| HIGH | `tests/test_termux_prefix_guard.py` | 61 | 1742 |
| HIGH | `tools/protocols.py` | 101 | 3065 |
| HIGH | `tools/secure_tools.py` | 949 | 37405 |
| HIGH | `tools/termux_monitor.py` | 131 | 5212 |
| HIGH | `ui/repl_termux.py` | 1248 | 50656 |
| MEDIUM | `core/convergence_gate.py` | 655 | 25610 |
| MEDIUM | `core/project_root_guard.py` | 176 | 7874 |
| MEDIUM | `core/prompts.py.bak` | 163 | 10538 |
| MEDIUM | `core/repo_scanner.py` | 340 | 12588 |
| MEDIUM | `core/skills.py` | 591 | 21789 |
| MEDIUM | `core/todo.py` | 409 | 16775 |
| MEDIUM | `core/ui_bridge.py` | 413 | 19509 |
| MEDIUM | `core/verifier.py` | 513 | 21675 |
| MEDIUM | `docs/known_limitations.md` | 140 | 7882 |
| MEDIUM | `engine/_context.py` | 478 | 20285 |
| MEDIUM | `engine/_convergence.py` | 751 | 38693 |
| MEDIUM | `engine/deep_agent.py` | 941 | 46431 |
| MEDIUM | `engine/renderer.py` | 433 | 17657 |
| MEDIUM | `llm_router.py` | 482 | 22265 |
| MEDIUM | `logs/session_20260801_121621.log` | 6 | 1228 |
| MEDIUM | `logs/session_20260801_174344.log` | 6 | 1330 |
| MEDIUM | `logs/session_20260801_202911.log` | 6 | 1330 |
| MEDIUM | `logs/session_20260805_235951.log` | 6 | 1330 |
| MEDIUM | `logs/session_20260806_175319.log` | 6 | 1330 |
| MEDIUM | `logs/session_20260807_062945.log` | 15 | 3277 |
| MEDIUM | `logs/session_20260810_151313.log` | 7 | 1494 |
| MEDIUM | `logs/session_20260810_161714.log` | 6 | 1330 |
| MEDIUM | `logs/session_20260810_165231.log` | 6 | 1330 |
| MEDIUM | `logs/session_20260810_173138.log` | 17 | 4154 |
| MEDIUM | `logs/session_20260810_175650.log` | 10 | 2241 |
| MEDIUM | `logs/session_20260810_184502.log` | 14 | 3436 |
| MEDIUM | `logs/session_20260810_195021.log` | 15 | 3627 |
| MEDIUM | `logs/session_20260810_201757.log` | 6 | 1330 |
| MEDIUM | `logs/session_20260810_204516.log` | 6 | 1330 |
| MEDIUM | `logs/session_20260810_211548.log` | 15 | 3826 |
| MEDIUM | `logs/session_20260810_220425.log` | 5 | 940 |
| MEDIUM | `logs/session_20260811_064210.log` | 13 | 3243 |
| MEDIUM | `logs/session_20260811_073940.log` | 41 | 11150 |
| MEDIUM | `logs/session_20260811_075714.log` | 18 | 4573 |
| MEDIUM | `logs/session_20260811_090159.log` | 6 | 1330 |
| MEDIUM | `logs/session_20260811_093010.log` | 6 | 1330 |
| MEDIUM | `logs/session_20260811_093633.log` | 6 | 1330 |
| MEDIUM | `logs/session_20260811_121209.log` | 6 | 1330 |
| MEDIUM | `logs/session_20260811_121222.log` | 6 | 1330 |
| MEDIUM | `logs/session_20260811_121432.log` | 6 | 1330 |
| MEDIUM | `logs/session_20260811_121437.log` | 6 | 1330 |
| MEDIUM | `logs/session_20260811_121610.log` | 6 | 1330 |
| MEDIUM | `logs/session_20260811_130124.log` | 4 | 747 |
| MEDIUM | `logs/session_20260811_131953.log` | 6 | 1330 |
| MEDIUM | `logs/session_20260811_132824.log` | 6 | 1330 |
| MEDIUM | `logs/session_20260811_132846.log` | 6 | 1330 |
| MEDIUM | `logs/session_20260811_133058.log` | 6 | 1330 |
| MEDIUM | `logs/session_20260811_152218.log` | 6 | 1330 |
| MEDIUM | `logs/session_20260811_153019.log` | 6 | 1330 |
| MEDIUM | `logs/session_20260811_154155.log` | 10 | 2241 |
| MEDIUM | `logs/session_20260811_160255.log` | 8 | 1913 |
| MEDIUM | `logs/session_20260811_160816.log` | 7 | 1494 |
| MEDIUM | `logs/session_20260811_161716.log` | 10 | 2241 |
| MEDIUM | `logs/session_20260811_161930.log` | 7 | 1494 |
| MEDIUM | `logs/session_20260811_162259.log` | 4 | 747 |
| MEDIUM | `logs/session_20260811_162307.log` | 7 | 1494 |
| MEDIUM | `logs/session_20260811_162548.log` | 6 | 1330 |
| MEDIUM | `logs/session_20260811_162656.log` | 8 | 1913 |
| MEDIUM | `logs/session_20260811_162800.log` | 6 | 1330 |
| MEDIUM | `logs/session_20260811_163008.log` | 7 | 1494 |
| MEDIUM | `logs/session_20260811_163330.log` | 14 | 3083 |
| MEDIUM | `logs/session_20260811_163409.log` | 6 | 1330 |
| MEDIUM | `logs/session_20260811_163416.log` | 6 | 1330 |
| MEDIUM | `logs/session_20260811_171247.log` | 6 | 1330 |
| MEDIUM | `logs/session_20260812_100326.log` | 8 | 1913 |
| MEDIUM | `logs/session_20260812_102413.log` | 4 | 747 |
| MEDIUM | `logs/session_20260812_102420.log` | 11 | 2660 |
| MEDIUM | `logs/session_20260812_102944.log` | 9 | 2077 |
| MEDIUM | `logs/session_20260812_103253.log` | 6 | 1330 |
| MEDIUM | `logs/session_20260812_141307.log` | 12 | 2824 |
| MEDIUM | `logs/session_20260812_142050.log` | 10 | 2241 |
| MEDIUM | `main.py` | 604 | 24323 |
| MEDIUM | `scripts/install_hooks.sh` | 44 | 1326 |
| MEDIUM | `tests/test_memory_manager.py` | 264 | 11654 |
| MEDIUM | `tests/test_no_reasoning_leak.py` | 738 | 24712 |
| MEDIUM | `tests/test_phase3_verification.py` | 412 | 15854 |
| MEDIUM | `tests/test_red_team_phase22.py` | 440 | 19083 |
| MEDIUM | `tests/test_semantic_verifier_phase23.py` | 403 | 16950 |
| MEDIUM | `ui/cc_style.py` | 309 | 10125 |
| MEDIUM | `artifact_policy.md` | 105 | 7111 |
| MEDIUM | `core/artifact_manager.py` | 347 | 13411 |
| MEDIUM | `core/bootloader.py` | 107 | 4287 |
| MEDIUM | `core/cancellation.py` | 46 | 1520 |
| MEDIUM | `core/canonicalize.py` | 115 | 4231 |
| MEDIUM | `core/commands/compact.py` | 99 | 3284 |
| MEDIUM | `core/constants.py` | 118 | 7343 |
| MEDIUM | `core/dag/nodes/reasoner.py` | 124 | 6017 |
| MEDIUM | `core/kernel/events.py` | 91 | 3578 |
| MEDIUM | `core/kernel/state.py` | 294 | 10201 |
| MEDIUM | `core/sanitize.py` | 209 | 7145 |
| MEDIUM | `core/security/__init__.py` | 51 | 1360 |
| MEDIUM | `core/security/decision_ladder.py` | 325 | 15428 |
| MEDIUM | `core/semantic_index.py` | 126 | 4410 |
| MEDIUM | `core/sse_bridge.py` | 196 | 6974 |
| MEDIUM | `engine/_budget.py` | 236 | 11729 |
| MEDIUM | `engine/_loop_types.py` | 227 | 10860 |
| MEDIUM | `engine/goal_verifier.py` | 143 | 5903 |
| MEDIUM | `engine/state.py` | 34 | 850 |
| MEDIUM | `engine/ui_theme.py` | 265 | 10622 |
| MEDIUM | `scripts/probe_stage6_gate.py` | 86 | 3171 |
| MEDIUM | `session-ses_03f3.md` | 504 | 29703 |
| MEDIUM | `tests/test_api_key_normalization.py` | 47 | 1880 |
| MEDIUM | `tests/test_badge_color_owner.py` | 46 | 1809 |
| MEDIUM | `tests/test_brand3_minimal_dark.py` | 91 | 3886 |
| MEDIUM | `tests/test_cancellation.py` | 59 | 1639 |
| MEDIUM | `tests/test_cc_style_footer_expand.py` | 79 | 3148 |
| MEDIUM | `tests/test_cc_style_renderer.py` | 81 | 2972 |
| MEDIUM | `tests/test_design_infrastructure.py` | 151 | 6621 |
| MEDIUM | `tests/test_emergency_stop.py` | 85 | 3518 |
| MEDIUM | `tests/test_footer.py` | 101 | 3357 |
| MEDIUM | `tests/test_gate15_transaction.py` | 307 | 13497 |
| MEDIUM | `tests/test_gate_l2_streaming_parity.py` | 283 | 14954 |
| MEDIUM | `tests/test_gate_l4_god_method_policy.py` | 95 | 4625 |
| MEDIUM | `tests/test_graphify_tool.py` | 75 | 3146 |
| MEDIUM | `tests/test_header.py` | 79 | 2779 |
| MEDIUM | `tests/test_loop_progress.py` | 317 | 13990 |
| MEDIUM | `tests/test_path_claim_gate.py` | 83 | 2635 |
| MEDIUM | `tests/test_phase41_repl_stream.py` | 183 | 6922 |
| MEDIUM | `tests/test_phase45_antifrustration.py` | 188 | 8853 |
| MEDIUM | `tests/test_phase4_streaming.py` | 157 | 5947 |
| MEDIUM | `tests/test_phase_ui.py` | 249 | 7401 |
| MEDIUM | `tests/test_phase_ui2.py` | 129 | 3962 |
| MEDIUM | `tests/test_phase_ui_dedupe.py` | 129 | 5255 |
| MEDIUM | `tests/test_post_tool_efficiency_phase24.py` | 118 | 4685 |
| MEDIUM | `tests/test_protocol_debt_batch2.py` | 66 | 2330 |
| MEDIUM | `tests/test_protocol_debt_batch3.py` | 76 | 3244 |
| MEDIUM | `tests/test_protocol_debt_batch4.py` | 43 | 1524 |
| MEDIUM | `tests/test_protocol_debt_batch5.py` | 52 | 1647 |
| MEDIUM | `tests/test_sanitize.py` | 131 | 5277 |
| MEDIUM | `tests/test_sanitize_helpers.py` | 74 | 2853 |
| MEDIUM | `tests/test_semantic_memory.py` | 96 | 3674 |
| MEDIUM | `tests/test_semantic_token_singletons.py` | 71 | 2793 |
| MEDIUM | `tests/test_single_renderer_architecture.py` | 145 | 5904 |
| MEDIUM | `tests/test_sse_bridge.py` | 43 | 1799 |
| MEDIUM | `tests/test_state.py` | 128 | 5748 |
| MEDIUM | `tests/test_streaming.py` | 98 | 3683 |
| MEDIUM | `tests/test_streaming_leak_detector.py` | 181 | 6786 |
| MEDIUM | `tests/test_taste_engine.py` | 54 | 2083 |
| MEDIUM | `tests/test_taste_manager.py` | 81 | 3112 |
| MEDIUM | `tests/test_theme_state_colors_are_semantic.py` | 41 | 1557 |
| MEDIUM | `tests/test_thread_safety.py` | 91 | 3444 |
| MEDIUM | `tests/test_tool_factory.py` | 89 | 3297 |
| MEDIUM | `tests/test_ui_scan_display.py` | 136 | 5551 |
| MEDIUM | `tests/test_v4_compact_skill_in_core.py` | 120 | 4986 |
| MEDIUM | `tools/shell.py` | 198 | 6465 |
| MEDIUM | `ui/design/__init__.py` | 47 | 1864 |
| MEDIUM | `ui/design/animation/profiles.py` | 61 | 1776 |
| MEDIUM | `ui/design/contracts/widgets.py` | 73 | 1768 |
| MEDIUM | `ui/design/layout/constants.py` | 30 | 732 |
| MEDIUM | `ui/design/primitives/gutter.py` | 56 | 2167 |
| MEDIUM | `ui/design/primitives/key_value_row.py` | 48 | 1826 |
| MEDIUM | `ui/design/primitives/layout.py` | 53 | 1654 |
| MEDIUM | `ui/design/primitives/personality.py` | 136 | 4524 |
| MEDIUM | `ui/design/primitives/spinner.py` | 48 | 1659 |
| MEDIUM | `ui/design/primitives/status_line.py` | 66 | 2344 |
| MEDIUM | `ui/design/theme/__init__.py` | 11 | 372 |
| MEDIUM | `ui/design/theme/color.py` | 48 | 1585 |
| MEDIUM | `ui/design/theme/semantic.py` | 110 | 4001 |
| MEDIUM | `ui/design/tokens/__init__.py` | 20 | 775 |
| MEDIUM | `ui/design/tokens/separator.py` | 35 | 898 |
| MEDIUM | `ui/design/tokens/sizing.py` | 86 | 1541 |
| MEDIUM | `ui/design/tokens/spacing.py` | 83 | 1782 |
| MEDIUM | `ui/design/typography/presets.py` | 52 | 1937 |
| MEDIUM | `ui/event_wiring.py` | 226 | 9150 |
| MEDIUM | `ui/live_thought.py` | 243 | 9198 |
| MEDIUM | `ui/widgets/diff_render.py` | 148 | 5623 |
| MEDIUM | `ui/widgets/footer.py` | 39 | 1338 |
| MEDIUM | `ui/widgets/header.py` | 54 | 1833 |
| MEDIUM | `ui/widgets/scan_display.py` | 126 | 4993 |
| MEDIUM | `ui/widgets/status_bar.py` | 191 | 7004 |
| MEDIUM | `core/dag/nodes/executor.py` | 76 | 3943 |
| MEDIUM | `core/dag/nodes/terminal.py` | 119 | 7861 |
| MEDIUM | `core/memory_manager.py` | 97 | 3362 |
| MEDIUM | `core/scaffolder.py` | 118 | 4365 |
| MEDIUM | `core/state_manager.py` | 77 | 2642 |
| MEDIUM | `core/taste_engine.py` | 110 | 4120 |
| MEDIUM | `engine/_tool_runner.py` | 145 | 7716 |
| MEDIUM | `fix_tests2.py` | 13 | 445 |
| MEDIUM | `nabd_os.egg-info/SOURCES.txt` | 449 | 12999 |
| MEDIUM | `qualify_skill.py` | 26 | 1028 |
| MEDIUM | `refactor.py` | 45 | 1300 |
| MEDIUM | `scripts/export_chat.py` | 87 | 3125 |
| MEDIUM | `scripts/regen_manifest.py` | 102 | 4081 |
| MEDIUM | `sessions/sess_0198ca89_20260811162259.json` | 19 | 5407 |
| MEDIUM | `sessions/sess_0397bd39_20260811162656.json` | 35 | 8487 |
| MEDIUM | `sessions/sess_0cc9fbc0_20260812141307.json` | 19 | 6816 |
| MEDIUM | `sessions/sess_0ebdf9d6_20260811132824.json` | 19 | 5034 |
| MEDIUM | `sessions/sess_14a19689_20260811125215.json` | 11 | 4885 |
| MEDIUM | `sessions/sess_1c742717_20260811171246.json` | 19 | 5520 |
| MEDIUM | `sessions/sess_1d8d45b7_20260811135336.json` | 11 | 4885 |
| MEDIUM | `sessions/sess_26d4ad7a_20260811153050.json` | 11 | 4895 |
| MEDIUM | `sessions/sess_2aadb280_20260811133058.json` | 19 | 5034 |
| MEDIUM | `sessions/sess_2d95a33d_20260811132846.json` | 19 | 5034 |
| MEDIUM | `sessions/sess_31d4b289_20260812102420.json` | 47 | 16631 |
| MEDIUM | `sessions/sess_385455b1_20260811121610.json` | 27 | 6106 |
| MEDIUM | `sessions/sess_3a6164e4_20260811163008.json` | 23 | 6350 |
| MEDIUM | `sessions/sess_3b162997_20260811163330.json` | 15 | 5363 |
| MEDIUM | `sessions/sess_3bbd5ddc_20260811163409.json` | 27 | 7022 |
| MEDIUM | `sessions/sess_489c0aaf_20260811121437.json` | 19 | 5531 |
| MEDIUM | `sessions/sess_4ce41cd1_20260812144000.json` | 11 | 5762 |
| MEDIUM | `sessions/sess_653102c2_20260812143811.json` | 11 | 5762 |
| MEDIUM | `sessions/sess_6ac08fba_20260811140610.json` | 11 | 4885 |
| MEDIUM | `sessions/sess_6e76bc7f_20260811161930.json` | 23 | 6780 |
| MEDIUM | `sessions/sess_8443dc38_20260811153019.json` | 19 | 5862 |
| MEDIUM | `sessions/sess_861b4256_20260812142050.json` | 23 | 6962 |
| MEDIUM | `sessions/sess_89aaf8dc_20260811151902.json` | 11 | 4895 |
| MEDIUM | `sessions/sess_8a699760_20260811134910.json` | 11 | 4885 |
| MEDIUM | `sessions/sess_8e25e724_20260811163416.json` | 47 | 12032 |
| MEDIUM | `sessions/sess_91e22d27_20260812103253.json` | 47 | 9689 |
| MEDIUM | `sessions/sess_9c9a729e_20260811171128.json` | 11 | 5247 |
| MEDIUM | `sessions/sess_9cb46817_20260812083426.json` | 11 | 5247 |
| MEDIUM | `sessions/sess_9e665434_20260811162307.json` | 23 | 6469 |
| MEDIUM | `sessions/sess_a5fe5388_20260811162800.json` | 19 | 6046 |
| MEDIUM | `sessions/sess_aaea49a0_20260812102944.json` | 39 | 21800 |
| MEDIUM | `sessions/sess_abd6647f_20260811162548.json` | 19 | 5861 |
| MEDIUM | `sessions/sess_aff97c0f_20260811130124.json` | 75 | 7552 |
| MEDIUM | `sessions/sess_b3efa073_20260811141307.json` | 11 | 4885 |
| MEDIUM | `sessions/sess_b6c1497b_20260811130226.json` | 11 | 4885 |
| MEDIUM | `sessions/sess_cfa650dc_20260812143630.json` | 11 | 5762 |
| MEDIUM | `sessions/sess_d420ed69_20260811160816.json` | 23 | 6345 |
| MEDIUM | `sessions/sess_d4413e53_20260811154155.json` | 23 | 6281 |
| MEDIUM | `sessions/sess_db174d34_20260812141036.json` | 11 | 5762 |
| MEDIUM | `sessions/sess_e5b74b3c_20260812142952.json` | 11 | 5762 |
| MEDIUM | `sessions/sess_e7b540c5_20260812141937.json` | 11 | 5762 |
| MEDIUM | `sessions/sess_e9d193eb_20260811131953.json` | 19 | 5024 |
| MEDIUM | `sessions/sess_ea5ae485_20260811152218.json` | 19 | 6602 |
| MEDIUM | `sessions/sess_ec109956_20260811133313.json` | 11 | 4885 |
| MEDIUM | `sessions/sess_ec1bc7af_20260811125356.json` | 11 | 4885 |
| MEDIUM | `sessions/sess_f0c88d6a_20260811160336.json` | 11 | 5002 |
| MEDIUM | `sessions/sess_f1fe4496_20260811161716.json` | 23 | 6493 |
| MEDIUM | `sessions/sess_f2cee20b_20260812102413.json` | 39 | 8686 |
| MEDIUM | `sessions/sess_fc00b102_20260811160255.json` | 35 | 10577 |
| MEDIUM | `sessions/sess_fff3ea89_20260811125332.json` | 11 | 4885 |
| MEDIUM | `skills/web_fetcher.py` | 95 | 3449 |
| MEDIUM | `tests/snapshots/event_snapshot.json` | 50 | 1023 |
| MEDIUM | `tests/test_code_intelligence.py` | 77 | 3087 |
| MEDIUM | `tests/test_code_parser_arch2.py` | 145 | 5563 |
| MEDIUM | `tests/test_fix_command.py` | 178 | 6191 |
| MEDIUM | `tests/test_live_state_lifecycle.py` | 115 | 5172 |
| MEDIUM | `tests/test_ollama_startup.py` | 81 | 3256 |
| MEDIUM | `tests/test_phase0_live_convergence.py` | 137 | 7528 |
| MEDIUM | `tests/test_phase2_pending_edits.py` | 74 | 2992 |
| MEDIUM | `tests/test_phase2_session_persistence.py` | 273 | 9991 |
| MEDIUM | `tests/test_regen_manifest_script.py` | 68 | 2461 |
| MEDIUM | `tests/test_snapshot.py` | 44 | 1306 |
| MEDIUM | `tests/test_todo_discipline_system_prompt.py` | 90 | 4336 |
| MEDIUM | `tools/web_search.py` | 235 | 7094 |
| MEDIUM | `.claude/settings.local.json` | 20 | 751 |
| MEDIUM | `.env` | 2 | 93 |
| MEDIUM | `.env.example` | 9 | 331 |
| MEDIUM | `.nabd/sandbox/temp_execution.py` | 1 | 93 |
| MEDIUM | `.pre-commit-config.yaml` | 19 | 384 |
| MEDIUM | `AGENT.md` | 126 | 6825 |
| MEDIUM | `R5_BASELINE.md` | 68 | 3213 |
| MEDIUM | `SCHEMA_POLICY.md` | 77 | 3070 |
| MEDIUM | `core/app_context.py` | 197 | 8749 |
| MEDIUM | `docs/AM8_D0_INFRASTRUCTURE.md` | 136 | 6738 |
| MEDIUM | `docs/ci_lockdown.md` | 59 | 2565 |
| MEDIUM | `docs/stage6_probe_results.md` | 67 | 2797 |
| MEDIUM | `red.log` | 53 | 17393 |
| MEDIUM | `scripts/pre_commit_check.sh` | 65 | 2525 |
| MEDIUM | `skills/code-auditor.md` | 11 | 671 |
| MEDIUM | `tests/test_circuit_breaker_recovery.py` | 92 | 3577 |
| MEDIUM | `ui/design/README.md` | 43 | 1860 |
| LOW | `RELEASE_2.x.md` | 21 | 868 |
| LOW | `core/investigation.py` | 405 | 22029 |
| LOW | `core/parser.py` | 593 | 19884 |
| LOW | `engine/_dispatch.py` | 471 | 21262 |
| LOW | `engine/_loop_helpers.py` | 729 | 30382 |
| LOW | `smolagents/__init__.py` | 367 | 16667 |
| LOW | `tests/test_completion_tracker.py` | 401 | 15774 |
| LOW | `tests/test_convergence_gate.py` | 515 | 18132 |
| LOW | `tests/test_e2e_transcript.py` | 397 | 16713 |
| LOW | `tests/test_keybindings.py` | 374 | 11503 |
| LOW | `tests/test_phase3_runtime_state.py` | 658 | 25993 |
| LOW | `tests/test_r42_target_evidence.py` | 404 | 16718 |
| LOW | `tests/test_r43_strict_evidence.py` | 334 | 14553 |
| LOW | `tests/test_r4_enforcement.py` | 561 | 24094 |
| LOW | `tests/test_r4_intent_routing.py` | 352 | 15523 |
| LOW | `tests/test_tool_result_widget.py` | 412 | 15518 |
| LOW | `tests/test_tool_routing_gap_closure.py` | 455 | 19870 |
| LOW | `tools/base.py` | 428 | 17913 |
| LOW | `tools/code_intelligence.py` | 493 | 21696 |
| LOW | `ui/widgets/tool_result.py` | 324 | 11756 |
| LOW | `workspace_semantic_memory.json` | 1809 | 43100 |
| LOW | `.gitignore` | 106 | 1944 |
| LOW | `NabdBootloader/engine.log` | 958 | 77027 |
| LOW | `adapters/__init__.py` | 9 | 233 |
| LOW | `core/__init__.py` | 12 | 444 |
| LOW | `core/_env.py` | 32 | 1160 |
| LOW | `core/_exact_action_contract.py` | 43 | 1871 |
| LOW | `core/adapters.py` | 93 | 3468 |
| LOW | `core/agent_observer.py` | 46 | 1626 |
| LOW | `core/agents/__init__.py` | 6 | 234 |
| LOW | `core/agents/coder_agent.py` | 152 | 6545 |
| LOW | `core/agents/verifier_agent.py` | 80 | 4195 |
| LOW | `core/command_dispatcher.py` | 243 | 9426 |
| LOW | `core/commands/__init__.py` | 6 | 221 |
| LOW | `core/commands/auto_scan.py` | 100 | 3837 |
| LOW | `core/commands/goal.py` | 67 | 2171 |
| LOW | `core/commands/plan_mode.py` | 65 | 2025 |
| LOW | `core/commands/skill.py` | 103 | 3489 |
| LOW | `core/context_compactor.py` | 179 | 7123 |
| LOW | `core/dag/__init__.py` | 11 | 423 |
| LOW | `core/dag/base.py` | 32 | 1117 |
| LOW | `core/dag/context.py` | 33 | 1260 |
| LOW | `core/dag/executor.py` | 86 | 4347 |
| LOW | `core/dag/launcher.py` | 57 | 2524 |
| LOW | `core/dag/nodes/__init__.py` | 9 | 306 |
| LOW | `core/dag/nodes/reader.py` | 42 | 2534 |
| LOW | `core/dag/nodes/sentinel.py` | 61 | 3325 |
| LOW | `core/diff_matrix.py` | 109 | 3567 |
| LOW | `core/display.py` | 46 | 1470 |
| LOW | `core/errors.py` | 28 | 748 |
| LOW | `core/evidence_claim_check.py` | 168 | 7356 |
| LOW | `core/fc_schemas.py` | 84 | 3212 |
| LOW | `core/gateway.py` | 156 | 5084 |
| LOW | `core/hybrid_retriever.py` | 102 | 3591 |
| LOW | `core/kernel/__init__.py` | 12 | 498 |
| LOW | `core/kernel/errors.py` | 96 | 3673 |
| LOW | `core/kernel/permissions.py` | 127 | 3946 |
| LOW | `core/kernel/protocols.py` | 42 | 1223 |
| LOW | `core/logger.py` | 88 | 3233 |
| LOW | `core/metrics.py` | 29 | 933 |
| LOW | `core/model_registry.py` | 84 | 2652 |
| LOW | `core/permissions.py` | 26 | 714 |
| LOW | `core/refusal_detector.py` | 6 | 201 |
| LOW | `core/retry.py` | 29 | 898 |
| LOW | `core/sandbox_worker.py` | 93 | 2999 |
| LOW | `core/snapshot.py` | 42 | 1396 |
| LOW | `core/sse.py` | 52 | 1669 |
| LOW | `core/test_matrix_evaluator.py` | 130 | 4965 |
| LOW | `core/test_runner_wrapper.py` | 37 | 1147 |
| LOW | `core/text_utils.py` | 191 | 6553 |
| LOW | `core/tool_factory.py` | 193 | 7602 |
| LOW | `core/turn_finalizer.py` | 123 | 4154 |
| LOW | `core/turn_outcome.py` | 105 | 3278 |
| LOW | `core/workspace.py` | 73 | 2824 |
| LOW | `core/xml_tool_parser.py` | 174 | 6202 |
| LOW | `engine/__init__.py` | 14 | 505 |
| LOW | `engine/dispatcher.py` | 173 | 7541 |
| LOW | `engine/interfaces.py` | 66 | 2142 |
| LOW | `engine/subagent_runner.py` | 84 | 3218 |
| LOW | `engine/tool_registry.py` | 59 | 2135 |
| LOW | `hello_nabd.py` | 1 | 46 |
| LOW | `nabd_logo.py` | 98 | 2923 |
| LOW | `qualify_d10.py` | 5 | 142 |
| LOW | `run_e2e_test.py` | 46 | 1812 |
| LOW | `scratch.py` | 8 | 293 |
| LOW | `scripts/live_leak_check.py` | 67 | 2998 |
| LOW | `scripts/prove_verify_path.py` | 50 | 2026 |
| LOW | `skills/__init__.py` | 72 | 2202 |
| LOW | `skills/base_skill.py` | 53 | 2048 |
| LOW | `skills/systematic_debugging.py` | 141 | 6793 |
| LOW | `smolagents/tools.py` | 45 | 1183 |
| LOW | `test_live.py` | 11 | 290 |
| LOW | `tests/__init__.py` | 2 | 21 |
| LOW | `tests/_gen_snapshot.py` | 66 | 2665 |
| LOW | `tests/conftest.py` | 55 | 1994 |
| LOW | `tests/debug_executor.py` | 45 | 1855 |
| LOW | `tests/debug_multiroot.py` | 21 | 927 |
| LOW | `tests/helper_ansi_emitter.py` | 3 | 62 |
| LOW | `tests/snapshots/schema_snapshot.json` | 305 | 7572 |
| LOW | `tests/support/render.py` | 71 | 1818 |
| LOW | `tests/test_a_station_that_has_not_started_is_not_thinking.py` | 70 | 3234 |
| LOW | `tests/test_agent_language_instructions.py` | 39 | 1422 |
| LOW | `tests/test_agent_shell_behavior.py` | 57 | 2236 |
| LOW | `tests/test_answer_in_hand_gate.py` | 88 | 3859 |
| LOW | `tests/test_arabic_claim_verification_phase25.py` | 226 | 12214 |
| LOW | `tests/test_arch4b_runtime_contract.py` | 35 | 988 |
| LOW | `tests/test_arch5_event_wiring.py` | 30 | 817 |
| LOW | `tests/test_arch6_dispatcher.py` | 38 | 1519 |
| LOW | `tests/test_arch7_layer_isolation.py` | 26 | 792 |
| LOW | `tests/test_artifact_manager.py` | 102 | 3829 |
| LOW | `tests/test_bootloader_and_errors.py` | 52 | 1641 |
| LOW | `tests/test_brand2_typing_indicator.py` | 95 | 4424 |
| LOW | `tests/test_brand4_classic_clean.py` | 86 | 3379 |
| LOW | `tests/test_brand5_bare_prompt.py` | 58 | 2274 |
| LOW | `tests/test_cc_style_compact_panels.py` | 68 | 2448 |
| LOW | `tests/test_cc_style_wiring.py` | 57 | 2277 |
| LOW | `tests/test_code_intelligence_security.py` | 77 | 3558 |
| LOW | `tests/test_compact_dedup.py` | 35 | 1223 |
| LOW | `tests/test_compact_real_elapsed.py` | 72 | 2647 |
| LOW | `tests/test_completion_policy.py` | 250 | 11018 |
| LOW | `tests/test_consent.py` | 233 | 9674 |
| LOW | `tests/test_convergence_integration.py` | 261 | 8721 |
| LOW | `tests/test_dag_consent_wiring.py` | 49 | 1552 |
| LOW | `tests/test_dangerous_todo_scenario.py` | 38 | 1559 |
| LOW | `tests/test_dead_classes_are_removed.py` | 28 | 1035 |
| LOW | `tests/test_dead_modules_stay_dead.py` | 51 | 1995 |
| LOW | `tests/test_dead_palette_keys_are_removed.py` | 13 | 370 |
| LOW | `tests/test_dead_repl_unit_is_buried.py` | 201 | 7989 |
| LOW | `tests/test_dead_variables_are_removed.py` | 87 | 3816 |
| LOW | `tests/test_dimmed_status_colors.py` | 34 | 1511 |
| LOW | `tests/test_dispatcher_event_contract.py` | 77 | 3109 |
| LOW | `tests/test_event_contract_policy.py` | 68 | 2058 |
| LOW | `tests/test_evidence_claim_check.py` | 204 | 8542 |
| LOW | `tests/test_exact_action_contract.py` | 184 | 7482 |
| LOW | `tests/test_exact_action_schema_filtering.py` | 78 | 3458 |
| LOW | `tests/test_fallback_mode_tools.py` | 33 | 1267 |
| LOW | `tests/test_final_answer_performance.py` | 76 | 3033 |
| LOW | `tests/test_final_answer_render.py` | 60 | 2310 |
| LOW | `tests/test_forbidden_changes_policy.py` | 121 | 5117 |
| LOW | `tests/test_gate16_remediation.py` | 119 | 5381 |
| LOW | `tests/test_gate_l1_loop_semantics.py` | 105 | 5291 |
| LOW | `tests/test_gate_l3_convergence.py` | 143 | 6578 |
| LOW | `tests/test_gate_l5_import_hygiene.py` | 126 | 5680 |
| LOW | `tests/test_gateway.py` | 34 | 1274 |
| LOW | `tests/test_git_p0_fixes.py` | 104 | 3579 |
| LOW | `tests/test_git_tool_security.py` | 74 | 2042 |
| LOW | `tests/test_git_write_consent.py` | 66 | 1904 |
| LOW | `tests/test_guard_directive_separation.py` | 101 | 4118 |
| LOW | `tests/test_inline_status_panel_removed.py` | 59 | 2577 |
| LOW | `tests/test_loop_repetition_guard.py` | 164 | 7555 |
| LOW | `tests/test_loop_safety.py` | 232 | 8550 |
| LOW | `tests/test_main_live_elapsed.py` | 23 | 708 |
| LOW | `tests/test_markdown_final_answer.py` | 62 | 2115 |
| LOW | `tests/test_mechanical_tool_enforcement.py` | 73 | 2627 |
| LOW | `tests/test_mode_cycle_preservation.py` | 215 | 7688 |
| LOW | `tests/test_model_registry.py` | 43 | 1409 |
| LOW | `tests/test_native_deep_agent_convergence.py` | 257 | 10376 |
| LOW | `tests/test_no_silent_exceptions.py` | 97 | 3847 |
| LOW | `tests/test_on_loop_completed_spacing.py` | 29 | 1264 |
| LOW | `tests/test_one_owner_of_live_state.py` | 50 | 1969 |
| LOW | `tests/test_oneshot_tty_rendering.py` | 59 | 2163 |
| LOW | `tests/test_output_discipline.py` | 25 | 837 |
| LOW | `tests/test_phase0_tool_required_error.py` | 80 | 2935 |
| LOW | `tests/test_phase1_deep_agent_evidence.py` | 262 | 10347 |
| LOW | `tests/test_phase32_state_tracking.py` | 156 | 5790 |
| LOW | `tests/test_phase3_e2e_transcript.py` | 284 | 12926 |
| LOW | `tests/test_phase4_context_compaction.py` | 266 | 13817 |
| LOW | `tests/test_phase51_goalspec_lmk.py` | 164 | 6464 |
| LOW | `tests/test_phase51_workspace_root.py` | 152 | 5500 |
| LOW | `tests/test_phase5_goalspec.py` | 218 | 8613 |
| LOW | `tests/test_phase5_harden.py` | 255 | 10578 |
| LOW | `tests/test_phase_context_compaction.py` | 129 | 4481 |
| LOW | `tests/test_phase_fallback_restrictions.py` | 73 | 2987 |
| LOW | `tests/test_phase_goal_12_polish.py` | 80 | 3195 |
| LOW | `tests/test_phase_hybrid_retriever.py` | 111 | 3804 |
| LOW | `tests/test_phase_ui3.py` | 82 | 3155 |
| LOW | `tests/test_prompt_leak_redaction.py` | 60 | 2558 |
| LOW | `tests/test_protocol_debt_batch1.py` | 77 | 2941 |
| LOW | `tests/test_r41_intent_evidence.py` | 162 | 6331 |
| LOW | `tests/test_r45_batch_provenance.py` | 283 | 13882 |
| LOW | `tests/test_react_style_parser.py` | 111 | 3806 |
| LOW | `tests/test_renderer_dead_keys_stay_dead.py` | 31 | 1003 |
| LOW | `tests/test_renderer_todos.py` | 28 | 956 |
| LOW | `tests/test_renderer_uses_status_bar.py` | 42 | 1857 |
| LOW | `tests/test_repl_safety_guards.py` | 111 | 4155 |
| LOW | `tests/test_repl_spinner_is_imported.py` | 31 | 1133 |
| LOW | `tests/test_repl_termux_safety.py` | 42 | 1630 |
| LOW | `tests/test_repo_scan.py` | 55 | 1683 |
| LOW | `tests/test_rtl_honesty.py` | 36 | 1288 |
| LOW | `tests/test_safe_binaries_drift.py` | 26 | 1281 |
| LOW | `tests/test_schema_contract_snapshot.py` | 139 | 4802 |
| LOW | `tests/test_secure_test_runner_lenient_signature.py` | 63 | 3066 |
| LOW | `tests/test_semantic_index_versioning.py` | 76 | 2785 |
| LOW | `tests/test_shift_enter.py` | 127 | 4369 |
| LOW | `tests/test_shift_enter_eager.py` | 86 | 3126 |
| LOW | `tests/test_smolagents_compatibility.py` | 100 | 4712 |
| LOW | `tests/test_status_bar_duration.py` | 16 | 533 |
| LOW | `tests/test_status_bar_lifecycle.py` | 17 | 492 |
| LOW | `tests/test_status_bar_live.py` | 33 | 917 |
| LOW | `tests/test_status_bar_parity.py` | 29 | 1348 |
| LOW | `tests/test_status_bar_persistent.py` | 24 | 1274 |
| LOW | `tests/test_status_box_detached.py` | 42 | 1723 |
| LOW | `tests/test_status_line_faces_are_distinct.py` | 47 | 1419 |
| LOW | `tests/test_status_verbs_are_the_ruled_words.py` | 49 | 1420 |
| LOW | `tests/test_system_prompt_extraction.py` | 30 | 992 |
| LOW | `tests/test_task_tool.py` | 62 | 2183 |
| LOW | `tests/test_terminal_node_consent_is_wired.py` | 124 | 4960 |
| LOW | `tests/test_termux_compatibility.py` | 70 | 2772 |
| LOW | `tests/test_termux_monitor.py` | 131 | 4978 |
| LOW | `tests/test_the_bar_clock_turns.py` | 127 | 4053 |
| LOW | `tests/test_the_bar_hears_the_bus.py` | 147 | 4856 |
| LOW | `tests/test_the_clock_is_alive.py` | 152 | 5150 |
| LOW | `tests/test_the_live_bar_speaks_the_ruled_verb.py` | 121 | 5262 |
| LOW | `tests/test_theme_dead_tables_stay_dead.py` | 36 | 1534 |
| LOW | `tests/test_think_line_decommissioned.py` | 23 | 1192 |
| LOW | `tests/test_todo.py` | 53 | 1985 |
| LOW | `tests/test_todo_tool.py` | 52 | 1967 |
| LOW | `tests/test_tool_result_list.py` | 264 | 8889 |
| LOW | `tests/test_toolfirst_imperative.py` | 20 | 777 |
| LOW | `tests/test_tools_kernel_isolation.py` | 41 | 1358 |
| LOW | `tests/test_ui_concurrency_slash.py` | 74 | 3141 |
| LOW | `tests/test_ui_contracts.py` | 81 | 3384 |
| LOW | `tests/test_ui_diff_readability.py` | 62 | 2252 |
| LOW | `tests/test_ui_shell_display.py` | 67 | 3008 |
| LOW | `tests/test_ui_status_formatter.py` | 94 | 3664 |
| LOW | `tests/test_unified_exploration_contract.py` | 132 | 7287 |
| LOW | `tests/test_v4_auto_scan_plan_mode_in_core.py` | 89 | 3918 |
| LOW | `tests/test_v4_goal_in_core.py` | 52 | 1979 |
| LOW | `tests/test_verifier.py` | 180 | 8379 |
| LOW | `tests/test_visualizer_emissions.py` | 160 | 6125 |
| LOW | `tools/__init__.py` | 89 | 3182 |
| LOW | `tools/action_contract.py` | 29 | 921 |
| LOW | `tools/browser_tool.py` | 31 | 1106 |
| LOW | `tools/graph_intel.py` | 186 | 7509 |
| LOW | `tools/graphify_tool.py` | 116 | 4617 |
| LOW | `tools/memory.py` | 38 | 1105 |
| LOW | `tools/models.py` | 41 | 1098 |
| LOW | `tools/search_memory.py` | 125 | 4784 |
| LOW | `tools/task_tool.py` | 133 | 5093 |
| LOW | `tools/taste_manager.py` | 108 | 4343 |
| LOW | `tools/todo.py` | 119 | 4445 |
| LOW | `ui/controllers/__init__.py` | 8 | 166 |
| LOW | `ui/controllers/agent_controller.py` | 227 | 10274 |
| LOW | `ui/design/animation/__init__.py` | 5 | 220 |
| LOW | `ui/design/contracts/__init__.py` | 11 | 418 |
| LOW | `ui/design/icons/__init__.py` | 5 | 121 |
| LOW | `ui/design/icons/registry.py` | 57 | 2125 |
| LOW | `ui/design/layout/__init__.py` | 5 | 133 |
| LOW | `ui/design/primitives/__init__.py` | 24 | 1083 |
| LOW | `ui/design/primitives/badge.py` | 38 | 1084 |
| LOW | `ui/design/primitives/collapse_indicator.py` | 38 | 1255 |
| LOW | `ui/design/primitives/divider.py` | 19 | 541 |
| LOW | `ui/design/primitives/section_panel.py` | 33 | 1087 |
| LOW | `ui/design/primitives/selection_indicator.py` | 38 | 1262 |
| LOW | `ui/design/primitives/widget.py` | 39 | 1249 |
| LOW | `ui/design/state/__init__.py` | 5 | 201 |
| LOW | `ui/design/state/ui_state.py` | 72 | 3410 |
| LOW | `ui/design/typography/__init__.py` | 13 | 453 |
| LOW | `ui/keybindings.py` | 138 | 4598 |
| LOW | `ui/theme.py` | 157 | 6244 |
| LOW | `ui/widgets/__init__.py` | 24 | 630 |
| LOW | `ui/widgets/badges.py` | 47 | 1710 |
| LOW | `ui/widgets/checklist.py` | 30 | 1059 |
| LOW | `ui/widgets/collapsible_tool.py` | 40 | 1420 |
| LOW | `ui/widgets/diff_viewer.py` | 32 | 943 |
| LOW | `ui/widgets/prompt.py` | 23 | 722 |
| LOW | `ui/widgets/spinner.py` | 21 | 680 |
| LOW | `ui/widgets/tool_result_list.py` | 122 | 4731 |
| LOW | `workspace/mock_db.py` | 14 | 511 |
| LOW | `.github/workflows/ci.yml` | 83 | 2690 |
| LOW | `.nabd/artifacts/manifest.json` | 4 | 37 |
| LOW | `.nabd/journal/workspace.json` | 1 | 144 |
| LOW | `.nabd/taste_profile.json` | 15 | 412 |
| LOW | `.nabd_agent_state.json` | 33 | 775 |
| LOW | `core/state/shared_state.json` | 6 | 69 |
| LOW | `logs/agent_execution.jsonl` | 14 | 5659 |
| LOW | `pyproject.toml` | 55 | 1505 |
| LOW | `workspace/config.json` | 2 | 96 |
| INFO | `.commandcode/taste/taste.md` | 5 | 242 |
| INFO | `AUDIT_REPORT.md` | 237 | 9414 |
| INFO | `CONDITION_REGISTRY.md` | 29 | 1492 |
| INFO | `DEBT_LEDGER.md` | 12 | 550 |
| INFO | `FINAL_REPORT.md` | 19 | 1736 |
| INFO | `MEMORY.md` | 17 | 614 |
| INFO | `NabdBootloader/session_20260801_121939.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260801_185716.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260801_194020.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260801_200628.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260801_202020.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260802_045333.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260802_054225.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260802_120222.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260802_130146.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260802_132534.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260802_132841.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260802_134457.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260802_144925.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260802_161310.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260802_164853.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260802_170958.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260802_180450.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260802_181003.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260802_192039.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260802_192908.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260802_200017.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260802_201943.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260802_202330.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260802_202625.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260802_202730.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260802_205107.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260802_205459.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260802_210728.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260802_211632.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260802_224128.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260802_225017.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260802_231357.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_081224.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_081708.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_084045.log` | 6 | 391 |
| INFO | `NabdBootloader/session_20260803_084614.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_090050.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_092303.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_093007.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_094137.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_094209.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_101304.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_102105.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_114117.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_115633.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_130528.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_135353.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_140401.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_141935.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_144832.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_144908.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_160730.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_162656.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_165314.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_171004.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_173622.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_173911.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_174914.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_180055.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_184328.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_185009.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_191323.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_192314.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_200221.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_201214.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_201910.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_202752.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_203635.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_210620.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_212521.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_223225.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260803_225049.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260804_093854.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260804_095200.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260804_102122.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260804_113246.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260804_115721.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260804_122310.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260804_124430.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260804_125535.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260804_131022.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260804_131955.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260804_140753.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260804_152210.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260804_153128.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260804_155027.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260804_165350.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260805_122555.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260805_144122.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260805_190519.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260805_195519.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260805_200707.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260805_205329.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260805_224403.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260805_232717.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260806_055537.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260806_082034.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260806_084109.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260806_090318.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260806_092423.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260806_095626.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260806_121020.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260806_124736.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260806_134712.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260806_135617.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260806_140312.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260806_140610.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260806_163401.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260806_164351.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260806_165345.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260806_170249.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260806_185648.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260806_193417.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260806_204111.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260806_204238.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260806_204803.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260806_204855.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260806_221533.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_051834.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_053747.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_055034.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_114208.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_121458.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_125232.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_132034.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_134429.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_134551.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_140543.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_141957.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_152954.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_155010.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_161249.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_162057.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_162752.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_162818.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_163722.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_165303.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_165925.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_181847.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_185025.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_194419.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_194647.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_200738.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_200911.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_201532.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_204609.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_205218.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_212933.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_213106.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260807_213618.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260808_045725.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260808_045803.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260808_045903.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260808_075058.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260808_091554.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260808_091731.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260808_100905.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260808_101037.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260808_101330.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260808_120934.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260808_122229.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260808_122644.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260808_123710.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260808_131633.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260808_150157.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260808_150332.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260808_150808.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260809_023241.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260809_035435.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260809_040833.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260809_054519.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260809_060250.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260809_122814.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260809_123148.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260809_124112.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260809_141851.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260809_142819.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260809_190445.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260809_190729.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260810_083621.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260810_084117.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260810_140424.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260810_140549.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260810_141722.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260810_145220.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260810_153016.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260810_153308.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260810_153806.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260810_155241.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260810_163113.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260810_163456.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260810_174213.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260810_174616.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260810_190911.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260810_193914.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260810_194352.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260810_200245.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260810_200938.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260810_203035.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260810_203144.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260810_203816.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260810_210448.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260810_210946.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260810_215618.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260810_220021.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260810_222637.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260810_225105.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260810_230600.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260811_051245.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260811_054557.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260811_055407.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260811_062618.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260811_063130.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260811_063654.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260811_090108.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260811_092920.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260811_125213.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260811_125227.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260811_125314.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260811_130140.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260811_133216.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260811_134930.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260811_135326.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260811_140622.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260811_141125.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260811_152014.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260811_153257.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260811_160351.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260811_171116.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260811_171120.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260812_141149.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260812_141915.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260812_142835.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260812_143715.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260812_144216.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260812_165246.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260812_170724.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260812_192009.log` | 5 | 322 |
| INFO | `NabdBootloader/session_20260812_193202.log` | 5 | 322 |
| INFO | `README.md` | 78 | 3203 |
| INFO | `SECURITY.md` | 91 | 3530 |
| INFO | `STATE.md` | 6 | 68 |
| INFO | `bin/nabdcode` | 6 | 233 |
| INFO | `docs/AM8_D2_WIDGET_MIGRATION.md` | 151 | 7903 |
| INFO | `docs/CORE_FILE_DNA_DISSECTION.md` | 143 | 8869 |
| INFO | `docs/after_error_long.ansi` | 6 | 1351 |
| INFO | `docs/after_error_short.ansi` | 7 | 1539 |
| INFO | `docs/after_gutter.ansi` | 25 | 6136 |
| INFO | `docs/after_header_footer.ansi` | 8 | 1050 |
| INFO | `docs/after_list_selection.ansi` | 18 | 4520 |
| INFO | `docs/after_nav.ansi` | 6 | 1370 |
| INFO | `docs/after_status_bar.ansi` | 4 | 955 |
| INFO | `docs/after_success_long.ansi` | 6 | 1365 |
| INFO | `docs/after_success_short.ansi` | 6 | 1340 |
| INFO | `docs/after_t1_badges.ansi` | 9 | 325 |
| INFO | `docs/am8_d1_screenshot.ansi` | 19 | 3796 |
| INFO | `docs/attribution_corrections.txt` | 8 | 546 |
| INFO | `docs/before_error_long.ansi` | 5 | 727 |
| INFO | `docs/before_error_short.ansi` | 5 | 942 |
| INFO | `docs/before_header_footer.ansi` | 7 | 570 |
| INFO | `docs/before_list_selection.ansi` | 18 | 4484 |
| INFO | `docs/before_nav.ansi` | 6 | 1370 |
| INFO | `docs/before_status_bar.ansi` | 4 | 680 |
| INFO | `docs/before_success_long.ansi` | 5 | 727 |
| INFO | `docs/before_success_short.ansi` | 5 | 942 |
| INFO | `docs/before_t1_badges.ansi` | 9 | 327 |
| INFO | `docs/provenance_quarantine.txt` | 37 | 2753 |
| INFO | `install.sh` | 33 | 1501 |
| INFO | `logs/parser_debug.log` | 0 | 8349608 |
| INFO | `logs/session_20260801_104407.log` | 5 | 322 |
| INFO | `logs/session_20260802_102812.log` | 11 | 1016 |
| INFO | `logs/session_20260802_135047.log` | 5 | 322 |
| INFO | `logs/session_20260802_172833.log` | 5 | 322 |
| INFO | `logs/session_20260802_191104.log` | 5 | 322 |
| INFO | `logs/session_20260802_191936.log` | 5 | 322 |
| INFO | `logs/session_20260802_231222.log` | 5 | 322 |
| INFO | `logs/session_20260803_082457.log` | 5 | 322 |
| INFO | `logs/session_20260803_141836.log` | 5 | 322 |
| INFO | `logs/session_20260803_181745.log` | 5 | 322 |
| INFO | `logs/session_20260804_154431.log` | 5 | 322 |
| INFO | `logs/session_20260804_165011.log` | 5 | 322 |
| INFO | `logs/session_20260804_193150.log` | 5 | 322 |
| INFO | `logs/session_20260805_232326.log` | 5 | 322 |
| INFO | `logs/session_20260806_112611.log` | 5 | 322 |
| INFO | `logs/session_20260806_164210.log` | 5 | 322 |
| INFO | `logs/session_20260807_100522.log` | 12 | 1938 |
| INFO | `logs/session_20260807_123519.log` | 5 | 322 |
| INFO | `logs/session_20260807_130945.log` | 20 | 3336 |
| INFO | `logs/session_20260807_135814.log` | 5 | 322 |
| INFO | `logs/session_20260807_142716.log` | 5 | 322 |
| INFO | `logs/session_20260807_143733.log` | 5 | 322 |
| INFO | `logs/session_20260807_150237.log` | 5 | 322 |
| INFO | `logs/session_20260807_155538.log` | 5 | 322 |
| INFO | `logs/session_20260807_163447.log` | 5 | 322 |
| INFO | `logs/session_20260807_165924.log` | 11 | 1766 |
| INFO | `logs/session_20260807_172606.log` | 6 | 883 |
| INFO | `logs/session_20260807_192027.log` | 20 | 3068 |
| INFO | `logs/session_20260808_092136.log` | 5 | 322 |
| INFO | `logs/session_20260808_121204.log` | 7 | 1032 |
| INFO | `logs/session_20260808_121240.log` | 5 | 322 |
| INFO | `logs/session_20260808_121356.log` | 6 | 883 |
| INFO | `logs/session_20260808_122212.log` | 6 | 883 |
| INFO | `logs/session_20260808_122243.log` | 6 | 883 |
| INFO | `logs/session_20260808_122635.log` | 6 | 883 |
| INFO | `logs/session_20260808_122657.log` | 6 | 883 |
| INFO | `logs/session_20260808_123622.log` | 6 | 883 |
| INFO | `logs/session_20260808_123836.log` | 6 | 883 |
| INFO | `logs/session_20260808_124247.log` | 6 | 883 |
| INFO | `logs/session_20260808_124436.log` | 6 | 883 |
| INFO | `logs/session_20260808_125458.log` | 6 | 883 |
| INFO | `logs/session_20260808_131002.log` | 6 | 883 |
| INFO | `logs/session_20260808_131546.log` | 2 | 75 |
| INFO | `logs/session_20260808_131549.log` | 2 | 75 |
| INFO | `logs/session_20260808_131655.log` | 2 | 75 |
| INFO | `logs/session_20260808_132812.log` | 2 | 75 |
| INFO | `logs/session_20260808_132814.log` | 2 | 75 |
| INFO | `logs/session_20260808_133118.log` | 2 | 75 |
| INFO | `logs/session_20260809_042135.log` | 5 | 322 |
| INFO | `logs/session_20260809_050323.log` | 5 | 322 |
| INFO | `logs/session_20260809_055712.log` | 5 | 322 |
| INFO | `logs/session_20260809_143747.log` | 18 | 2991 |
| INFO | `logs/session_20260809_185803.log` | 5 | 322 |
| INFO | `logs/session_20260810_091026.log` | 14 | 2282 |
| INFO | `logs/session_20260810_134212.log` | 14 | 2036 |
| INFO | `logs/session_20260810_142020.log` | 5 | 322 |
| INFO | `logs/session_20260810_172004.log` | 5 | 322 |
| INFO | `logs/session_20260810_175035.log` | 5 | 322 |
| INFO | `logs/session_20260810_205325.log` | 5 | 322 |
| INFO | `logs/session_20260811_050908.log` | 5 | 322 |
| INFO | `logs/session_20260811_052254.log` | 5 | 322 |
| INFO | `logs/session_20260811_090113.log` | 2 | 125 |
| INFO | `logs/session_20260811_092853.log` | 2 | 125 |
| INFO | `logs/session_20260811_115721.log` | 2 | 125 |
| INFO | `logs/session_20260811_125215.log` | 2 | 125 |
| INFO | `logs/session_20260811_125332.log` | 2 | 125 |
| INFO | `logs/session_20260811_125356.log` | 2 | 125 |
| INFO | `logs/session_20260811_130226.log` | 2 | 125 |
| INFO | `logs/session_20260811_133313.log` | 2 | 125 |
| INFO | `logs/session_20260811_134910.log` | 2 | 125 |
| INFO | `logs/session_20260811_135336.log` | 2 | 125 |
| INFO | `logs/session_20260811_140610.log` | 2 | 125 |
| INFO | `logs/session_20260811_141307.log` | 2 | 125 |
| INFO | `logs/session_20260811_151902.log` | 2 | 125 |
| INFO | `logs/session_20260811_153050.log` | 2 | 125 |
| INFO | `logs/session_20260811_160336.log` | 2 | 125 |
| INFO | `logs/session_20260811_171128.log` | 2 | 125 |
| INFO | `logs/session_20260812_141036.log` | 2 | 125 |
| INFO | `logs/session_20260812_141937.log` | 2 | 125 |
| INFO | `logs/session_20260812_142952.log` | 2 | 125 |
| INFO | `logs/session_20260812_143510.log` | 5 | 322 |
| INFO | `logs/session_20260812_143630.log` | 2 | 125 |
| INFO | `logs/session_20260812_143811.log` | 2 | 125 |
| INFO | `logs/session_20260812_144000.log` | 2 | 125 |
| INFO | `nabd_os.egg-info/PKG-INFO` | 88 | 3486 |
| INFO | `nabd_os.egg-info/dependency_links.txt` | 2 | 1 |
| INFO | `nabd_os.egg-info/entry_points.txt` | 3 | 39 |
| INFO | `nabd_os.egg-info/requires.txt` | 4 | 49 |
| INFO | `nabd_os.egg-info/top_level.txt` | 11 | 74 |
| INFO | `references/extraction-spec.md` | 52 | 1824 |
| INFO | `requirements-test.txt` | 5 | 209 |
| INFO | `requirements.txt` | 14 | 475 |
| INFO | `scripts/verify_protocol.sh` | 212 | 7305 |
| INFO | `session-ses_039b.md` | 0 | 759371 |
| INFO | `session-ses_03db.md` | 0 | 1155763 |
| INFO | `skills/auditor.md` | 12 | 759 |
| INFO | `skills/resource-monitor.md` | 15 | 899 |
| INFO | `skills/system-dissector.md` | 87 | 1926 |
| INFO | `start_agent_server.sh` | 123 | 2687 |
| INFO | `workspace_memory.db` | 55 | 45056 |
