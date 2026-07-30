"""
_ConvergenceMixin — final answer emission, verification gate, evidence synthesis.
Extracted from engine/loop.py (refactor step5-d).
CRITICAL: _emit_final is the single choke point for ALL terminations.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import TYPE_CHECKING, Any

from core.kernel.events import bus
from core.utils import safe_strip
from core.evidence import VerifierError

from engine._loop_types import _LoopSignal, _LoopCtx
from engine._loop_helpers import _resolve_default_verifier
from engine.goal_verifier import evaluate_goal_exit, MAX_GOAL_RETRIES

if TYPE_CHECKING:
    pass

# step6: budget for independent-checker calls per run (bounded token/time cost).
MAX_VERIFIER_CALLS: int = 2


def _parse_verifier_verdict(raw: str) -> bool | None:
    """Extract the boolean verdict from the checker's JSON response.

    Returns True (pass) / False (fail) / None (unparseable). Never raises.
    """
    if not raw:
        return None
    # Find the first {...} JSON object anywhere (flash models may prefix prose).
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    blob = raw[start : end + 1]
    try:
        data = json.loads(blob)
    except Exception:
        return None
    v = str(data.get("verdict", "")).strip().lower()
    if v == "pass":
        return True
    if v == "fail":
        return False
    return None


class _ConvergenceMixin:
    """
    Mixin للـ ExecutionLoop يحتوي نقطة الاختناق النهائية.
    يفترض: self._ctx, self.state, self.evidence_log, self._goal,
    self.POLL_DELAY, self.MAX_EVIDENCE_RETRIES, self._last_response،
    وكل التوابع الأخرى للكلاس المُدمَج.
    """

    def _real_reads(self) -> int:
        """Return count of distinct file paths successfully read via file_system read/edit or code_intelligence.

        Single source of truth for all read-counting logic. Counts each unique
        path once (distinct by lowercased path). Excludes root list ("." / "/").
        """
        seen: set[str] = set()
        for r in self.evidence_log.get_records():
            if not r.success:
                continue
            tool = getattr(r, "tool", "") or ""
            action = getattr(r, "action", "") or ""
            path = str(getattr(r, "command_or_path", "") or "").strip().lower()
            if path in (".", "/", ""):
                continue
            if tool == "file_system" and action in ("read", "edit", ""):
                seen.add(path)
            elif tool in ("code_intelligence", "secure_code_intelligence") and action in ("list_symbols", "get_definition", "find_references"):
                seen.add(path)
        return len(seen)

    def _extract_listing_files(self, max_suggestions: int = 3) -> str:
        """Extract 2-3 concrete .py file paths from the most recent listing output.

        Scans evidence records for successful ``file_system list`` calls and
        extracts .py filenames from the output snippet. Returns a comma-separated
        string like 'core/__init__.py, core/constants.py, core/config.py'.
        Falls back to the directory name + '__init__.py' when no filenames found.
        Returns empty string when listing_dir is root-level ("." or "/").
        """
        # Find the most recent listing record: match action="list" OR any
        # file_system record where command_or_path looks like a directory path
        # (no file extension, not root) — some tools may not populate action.
        listing_dir = ""
        for rec in reversed(self.evidence_log.get_records()):
            if not rec.success or rec.tool != "file_system":
                continue
            action = getattr(rec, "action", "") or ""
            cmd = str(getattr(rec, "command_or_path", "") or "").strip()
            if cmd in (".", "/", ""):
                continue
            if action == "list":
                listing_dir = cmd
                break
            # Fallback: no action field set, but command_or_path is a directory
            # (no file extension).
            if not action and "." not in cmd:
                listing_dir = cmd
                break

        if not listing_dir:
            return ""

        # Phase F: build set of already-read paths (exclude from suggestions).
        already_read = set()
        for r in self.evidence_log.get_records():
            if r.success and r.tool == "file_system":
                a = getattr(r, "action", "") or ""
                if a in ("read", "edit", ""):
                    p = str(getattr(r, "command_or_path", "") or "").strip().lower()
                    if p and p not in (".", "/", ""):
                        already_read.add(p)

        # Scan output snippets of all recent file_system records for .py files
        files: list[str] = []
        seen: set[str] = set()
        for rec in reversed(self.evidence_log.get_records()):
            if not rec.success:
                continue
            snippet = str(getattr(rec, "output_snippet", "") or "")
            # Find .py filenames in the output
            for m in re.finditer(r'\b([a-zA-Z_][a-zA-Z0-9_]*\.py)\b', snippet):
                fname = m.group(1)
                if fname not in seen:
                    seen.add(fname)
                    # Build path: <listing_dir>/<filename>
                    _full = f"{listing_dir}/{fname}"
                    # Phase F: skip already-read paths.
                    if _full.lower() in already_read:
                        continue
                    files.append(_full)
                    if len(files) >= max_suggestions:
                        break
            if len(files) >= max_suggestions:
                break

        if files:
            return ", ".join(files)

        # Fallback: no unread .py files found — suggest directory itself.
        return f"{listing_dir}/__init__.py"

    def _build_evidence_summary(self) -> str:
        """Minimal, isolated evidence summary for the independent checker.

        Deliberately excludes the maker's reasoning chain / chat history — only
        the successful records' tool + output snippet (capped) are shown, so the
        checker judges on evidence, not on the maker's self-assessment (R3).
        """
        lines = []
        for rec in self.evidence_log.get_records():
            if rec.success and rec.output_snippet:
                snippet = rec.output_snippet[:300].strip()
                if snippet:
                    lines.append(f"- [{rec.tool}] {snippet}")
        return "\n".join(lines) if lines else "(no successful evidence collected)"

    def _run_independent_checker(self) -> bool:
        """Run the independent LLM checker over an ISOLATED context.

        Returns True if the checker accepts (pass), False if it rejects (fail).
        The checker receives ONLY {goal, final_answer, evidence_summary} — never
        the maker's full conversation memory. This is the semantic gate layered
        ON TOP of the mandatory rule-based gates (evaluate_goal_exit / reads
        gate). Bounded to MAX_VERIFIER_CALLS per run; any failure (missing
        verifier, network error, unparseable verdict) falls back to the existing
        deterministic behavior (R8) so termination never breaks.
        """
        verifier = getattr(self, "_verifier_provider", None)
        if verifier is None:
            return True  # no checker configured → don't block (fallback R8)
        budget = getattr(self, "_verifier_calls", 0)
        if budget >= MAX_VERIFIER_CALLS:
            return True  # budget exhausted → fall back to mandatory gates (R7/R8)
        self._verifier_calls = budget + 1
        try:
            goal = self._ctx.user_prompt if self._ctx is not None else ""
            answer = getattr(self, "_last_response", "") or ""
            summary = self._build_evidence_summary()
            raw = verifier(goal, answer, summary, logger=self._logger)
            verdict = _parse_verifier_verdict(raw)
            if verdict is None:
                # Unparseable → treat as pass-through (don't block on noise).
                return True
            return verdict
        except Exception as exc:  # network/timeout/provider down
            if self._logger is not None:
                try:
                    self._logger.warning(
                        f"[Verifier] independent checker failed, falling back to "
                        f"mandatory gates: {exc}"
                    )
                except Exception:
                    pass
            return True

    def _verify_claim_or_self_correct(self) -> _LoopSignal:
        """Run the L1 Structural Verifier against the final non-tool response.

        Phase5 (GoalSpec): the verifiable exit condition is checked FIRST. When
        a GoalSpec is active the generic verifier must NOT be allowed to declare
        a false "Success" — the goal gate is authoritative and re-enters the
        loop (or terminates with reason ``goal_not_met``) if its criteria are
        not proven against live evidence.
        """
        from engine._loop_helpers import _has_active_goal

        ctx = self._ctx
        assert ctx is not None
        bus.emit("ui_no_tool_call", {"step": self.state.step_count})

        # ── step6: independent LLM checker (semantic gate, layered ON TOP) ──
        # Runs ONLY at the termination decision, over an ISOLATED context
        # {goal, final_answer, evidence_summary}. If it rejects, re-enter the
        # loop with a concise critique instead of blindly emitting. The
        # mandatory rule-based gates below still apply regardless of this result.
        if not self._run_independent_checker():
            critique = (
                "[VERIFIER REJECT]: The independent checker found your final "
                "answer is not sufficiently grounded in the collected evidence. "
                "Do NOT claim completion. Re-enter the loop, gather stronger "
                "evidence (read actual source, not just listings), and address "
                "the gaps before answering."
            )
            self.state.append_message({"role": "user", "content": critique})
            bus.emit("verifier_critique", {
                "step": self.state.step_count,
                "attempt": getattr(self._ctx, "goal_correct_count", 0),
                "max_attempts": MAX_VERIFIER_CALLS,
                "critique": critique,
                "goal_blocked": True,
            })
            self.state.increment_step()
            return _LoopSignal.CONTINUE

        if self._goal is not None and self._goal.raw_prompt.strip():
            bus.emit("goal_verify", {
                "session_id": self.state.session_id,
                "raw_prompt": self._goal.raw_prompt,
                "step": self.state.step_count,
                "criteria_met": False,
            })
            if not getattr(self._goal, "success_criteria", None) or getattr(self._goal, "success_criteria", None) == "None":
                pass
            else:
                goal_ok = self._evaluate_goal_exit()
                goal_result = evaluate_goal_exit(
                    self._goal, self.evidence_log, require_tools=True,
                    final_claim=self._last_response,
                )
                if not goal_result.ok or not goal_ok:
                    self._auto_critical_from_claim(self._last_response)
                    if ctx.goal_correct_count < MAX_GOAL_RETRIES:
                        ctx.goal_correct_count += 1
                        ctx.fingerprints.clear()
                        self._last_tool_signature = None
                        self._fixation_count = 0
                        self._executed_sigs = set()
                        self._redundant_count = 0
                        ctx.last_command = None
                        self._recent_calls.clear()
                        critique = goal_result.to_critique() if not goal_result.ok else "Goal success criteria not proven against live evidence."
                        self.state.append_message({"role": "user", "content": critique})
                        bus.emit(
                            "verifier_critique",
                            {
                                "step": self.state.step_count,
                                "attempt": ctx.goal_correct_count,
                                "max_attempts": MAX_GOAL_RETRIES,
                                "critique": critique,
                                "goal_blocked": True,
                            },
                        )
                        self.state.increment_step()
                        backoff_delay = min(self.POLL_DELAY * (2 ** (ctx.goal_correct_count - 1)), 4.0)
                        time.sleep(backoff_delay)
                        return _LoopSignal.CONTINUE
                    self._goal.is_met = False
                    self.state.active_goal = self._goal
                    self.state.update_status("COMPLETED")
                    safe_msg = self._get_fallback_reason(
                        ctx.user_prompt,
                        "[GOAL NOT MET] " + " ".join(goal_result.findings if not goal_result.ok else ["Criteria not verified against live evidence."]),
                    )
                    bus.emit("loop_completed", {"reason": "goal_not_met", "output": safe_msg})
                    return _LoopSignal.TERMINATE

            bus.emit("goal_verify", {
                "session_id": self.state.session_id,
                "raw_prompt": self._goal.raw_prompt,
                "step": self.state.step_count,
                "criteria_met": True,
            })
            self._goal.is_met = True

        # Phase 0 convergence: verify_fresh moved to _emit_final (single choke point).
        # Check verify_fresh via _emit_final before declaring termination.
        if not self._emit_final(self._last_response, "natural_completion"):
            return _LoopSignal.CONTINUE
        return _LoopSignal.TERMINATE

    def _synthesize_from_evidence(self, reason: str) -> str:
        """Build a clean Markdown summary from the evidence gathered so far.

        Used as a safety net so the user never sees a raw tool-call JSON dumped
        as the "final answer" — every termination path funnels through
        ``_emit_final``, which falls back here when the stored response is a raw
        tool call or empty.
        """
        ctx = self._ctx
        lines = []
        for rec in reversed(self.evidence_log.get_records()):
            if rec.success and rec.output_snippet:
                snippet = rec.output_snippet[:300].strip()
                if snippet:
                    lines.append(f"- [{rec.tool}] {snippet}")
            if len(lines) >= 5:
                break
        summary = "\n".join(lines) if lines else "(no successful tool output captured yet)"
        if reason in ("answer_in_hand", "goal_satisfied", "no_tool_cap", "no_progress_cap", "consecutive_reasoning_limit") and lines:
            return f"Based on the gathered evidence:\n\n{summary}"
        task = ctx.user_prompt if ctx else ""
        return (
            f"[Synthesized answer — {reason}]\n"
            f"Task: {task}\n"
            f"What I found:\n{summary}\n"
            f"(Agent stopped before a clean final_answer; summary built from collected evidence.)"
        )

    def _get_todo_manager(self) -> Any:
        """Resolve the TodoManager from the injected attribute or the registry.

        Falls back to scanning the tool registry for the todo_write tool's
        manager reference, so the convergence gate can check TODO status
        without a hard dependency on AppContext wiring.
        """
        mgr = getattr(self, "todo_manager", None)
        if mgr is not None:
            return mgr
        try:
            from engine.tool_registry import registry
            todo_tool = registry.get_tool("todo_write")
            if todo_tool is not None:
                mgr = getattr(todo_tool, "todo_manager", None) or getattr(todo_tool, "_manager", None)
                if mgr is not None:
                    return mgr
        except Exception:
            pass
        return None

    def _emit_final(self, output: str, reason: str) -> bool:
        """Single choke point for every final answer — never emits raw tool JSON.

        Phase 0 convergence: the verify_fresh gate is called INSIDE this function
        so every emission path (natural/partial/forced/shutdown) is verified.

        - No active goal: pass immediately (no reads required).
        - Active goal: require >= 3 real file reads (read action, not list).
        On rejection: inject a concise directive and return False (caller continues).
        On hard cap exceeded: emit an explicit failure message.
        On pass: emit normally.

        Returns True if emitted, False if rejected (caller should continue loop).
        """
        from engine._loop_helpers import (
            _looks_like_tool_call,
            _has_active_goal,
            _derive_read_hint,
        )

        # Resolve context early so both the convergence gate and the verify_fresh
        # gate below can use the same ctx.user_prompt / has_active_goal signal.
        # PATCH-R4.2: _prompt_requires_investigation removed — using
        # ctx.intent_policy.needs_investigation instead (single source of truth).
        ctx = self._ctx
        has_active_goal = _has_active_goal(self)

        # ── Convergence gate: block FINAL ANSWER if TODOs are incomplete ──
        # This is the single choke point — every termination path (natural,
        # partial, forced, shutdown) flows through here. The engine cannot
        # cheat by deleting TODOs: can_finalize treats absent TODOs as unknown.
        from core.convergence_gate import (
            can_finalize,
            TodoManagerCompletionTracker,
        )

        todo_mgr = self._get_todo_manager()
        # Build a CompletionTracker adapter so can_finalize() operates on the
        # unified interface rather than a raw TodoManager. When an active goal
        # or investigation prompt is present AND a tracker is available,
        # requires_plan=True enforces fail-closed: incomplete tracker → no
        # finalization. When no tracker is available (e.g. answer-in-hand
        # gate), requires_plan=False so the gate does not block.
        # PATCH-CORE-UNIFIED-R3: Read requires_plan from ctx.intent_policy
        # instead of calling _prompt_requires_investigation dynamically.
        tracker = TodoManagerCompletionTracker(todo_mgr) if todo_mgr is not None else None
        requires_plan = False
        if ctx is not None and tracker is not None:
            requires_plan = ctx.intent_policy.requires_plan if ctx.intent_policy else False
        # PATCH-INTENT-ROUTING-R4: pass requires_root_listing from policy.
        # NOTE: requires_root_listing is enforced HERE via can_finalize BEFORE
        # verify_fresh runs below (the next gate). This satisfies the protocol
        # requirement to wire into both gates — can_finalize is the authoritative
        # check and gates the verify_fresh call that follows.
        requires_root_listing = (
            ctx.intent_policy.requires_root_listing
            if ctx is not None and ctx.intent_policy
            else False
        )
        decision = can_finalize(
            completion_tracker=tracker,
            evidence_log=self.evidence_log,
            budget_exhausted=(reason == "budget_exhausted"),
            deadline_exceeded=(reason == "deadline_exceeded"),
            requires_plan=requires_plan,
            requires_root_listing=requires_root_listing,
        )
        if not decision.allowed:
            # Inject a CONTROL message telling the model what's missing.
            # Channel-separated: never disguised as a tool result artifact.
            blocking_ids = [b.todo_id for b in decision.blocking_todos]
            control_msg = (
                f"[CONTROL] FINAL ANSWER blocked — {len(decision.blocking_todos)} "
                f"TODO(s) incomplete or unverified: {blocking_ids}. "
                f"Details: {decision.blocked_reason}. "
                f"Evidence summary:\n{decision.evidence_summary}\n"
                f"Complete all TODOs with matching evidence before emitting final_answer."
            )
            self.state.append_message({"role": "user", "content": control_msg})
            self.state.increment_step()
            bus.emit("final_answer_blocked", {
                "blocking_todos": blocking_ids,
                "reason": decision.blocked_reason,
                "step": self.state.step_count,
            })
            return False

        # ── PATCH-R4.2: Trusted Evidence Target Comparison ──────────────────
        # Before verify_fresh, check that a required target was actually read
        # via trusted tool metadata (file_system read, success=True). This is
        # a SEPARATE gate from verify_fresh — it uses trusted metadata, not
        # LLM output parsing.
        if ctx is not None and ctx.intent_policy and ctx.intent_policy.required_target:
            from engine._loop_helpers import _check_required_target_in_evidence
            # PATCH-R4.3: Pass required_evidence_actions from policy so
            # edit/write actions do NOT satisfy a read-intent target check.
            _target_actions = ctx.intent_policy.required_evidence_actions if ctx.intent_policy else frozenset()
            _target_ok, _target_reason = _check_required_target_in_evidence(
                ctx.intent_policy.required_target,
                self.evidence_log,
                required_evidence_actions=_target_actions,
            )
            if not _target_ok:
                self._evidence_rejection_count += 1
                if self._evidence_rejection_count > self.MAX_EVIDENCE_RETRIES:
                    output = (
                        f"[Convergence failed — required target file "
                        f"'{ctx.intent_policy.required_target}' not found in "
                        f"trusted evidence after {self.MAX_EVIDENCE_RETRIES + 1} "
                        f"attempts.]"
                    )
                    self._last_response = output
                else:
                    self._force_tool = True
                    _rejection_msg = (
                        "[CONTROL] FINAL ANSWER rejected — the required target "
                        f"'{ctx.intent_policy.required_target}' was not found in "
                        "trusted tool metadata. You MUST use file_system with "
                        "action='read' on this file to satisfy the requirement."
                    )
                    self.state.append_message(
                        {"role": "user", "content": _rejection_msg}
                    )
                    self.state.increment_step()
                    return False

        if _looks_like_tool_call(output) or not safe_strip(output or ""):
            output = self._synthesize_from_evidence(reason)
            self._last_response = output

        # ── EvidenceLog.verify_fresh (restored historical choke point) ────
        # Historical runtime behavior: every final answer passes through
        # EvidenceLog.verify_fresh() for L0 (structural integrity via
        # Verifier.verify + check_investigation_gates) and L1 (technical
        # token matching via StructuralVerifier.verify) verification against
        # the evidence log. This was lost during the step5-d refactor
        # (commit 46fcf50) when the inline read-count gate replaced the
        # verify_fresh call without preserving L0 + L1 structural checks.
        # Restored here as a mandatory gate before the Phase 0 gate.
        # Phase 2.4: exact-action mode is exempt from verify_fresh and
        # read-count gates since the user asked for exactly one command,
        # not multi-file analysis. The claim gate (test/commit spoofing)
        # remains active below.
        # PATCH-CORE-UNIFIED-R3: Read needs_investigation from ctx.intent_policy
        # instead of calling _prompt_requires_investigation dynamically.
        if getattr(self, "_exact_action_mode", False):
            _needs_verify_vf = False
        elif ctx is not None:
            _needs_verify_vf = ctx.intent_policy.needs_investigation if ctx.intent_policy else False
            if _needs_verify_vf and self.evidence_log is not None:
                try:
                    # PATCH-R4.1: Pass IntentPolicy params so verify_fresh and
                    # check_investigation_gates use the same policy as can_finalize.
                    _vf_min_reads = ctx.intent_policy.minimum_reads if ctx.intent_policy else 0
                    _vf_root_list = ctx.intent_policy.requires_root_listing if ctx.intent_policy else False
                    _vf_target = ctx.intent_policy.required_target if ctx.intent_policy else ""
                    # PATCH-R4.2: Pass pre-classified intent from ctx.intent
                    # instead of letting check_investigation_gates re-classify.
                    _vf_intent = ctx.intent if ctx is not None else None
                    self.evidence_log.verify_fresh(
                        claim=output,
                        require_tools=True,
                        user_prompt=ctx.user_prompt,
                        minimum_reads=_vf_min_reads,
                        requires_root_listing=_vf_root_list,
                        required_target=_vf_target,
                        intent=_vf_intent,
                    )
                except VerifierError:
                    # Route through the existing evidence rejection lifecycle.
                    self._evidence_rejection_count += 1
                    if self._evidence_rejection_count > self.MAX_EVIDENCE_RETRIES:
                        # Hard cap exceeded: emit explicit failure message.
                        self._force_tool = False
                        output = (
                            f"[Convergence failed — evidence verification rejected "
                            f"the answer after {self.MAX_EVIDENCE_RETRIES + 1} "
                            f"attempts.]"
                        )
                        self._last_response = output
                    else:
                        # Reject: force tool call, inject concise directive.
                        self._force_tool = True
                        _rejection_msg = (
                            "[CONTROL] verify_fresh structural evidence verification "
                            "failed. Your final answer must cite specific, verifiable "
                            "technical identifiers from the files you read. Do NOT emit "
                            "final_answer until the response is grounded in actual "
                            "source evidence."
                        )
                        self.state.append_message(
                            {"role": "user", "content": _rejection_msg}
                        )
                        self.state.increment_step()
                        return False

        # ── Phase 0 verify_fresh gate (single choke point) ────────────────
        # PATCH-CORE-UNIFIED-R3: Use ctx.intent_policy.minimum_reads instead of
        # hardcoded 3. Single-file exemption applied upfront via policy.
        if ctx is not None:
            # Phase 2.4: exact-action mode bypasses verify_fresh and read-count
            # gates. The user asked for exactly one command, not analysis.
            if getattr(self, "_exact_action_mode", False):
                needs_verify = False
            else:
                # Gate discriminator: casual chat ("hi") → pass immediately.
                # Investigation / active-goal prompts → require real reads.
                # PATCH-CORE-UNIFIED-R3: read from ctx.intent_policy
                needs_verify = ctx.intent_policy.needs_investigation if ctx.intent_policy else False
            if needs_verify:
                # Phase D: unified read counter from _real_reads().
                real_reads = self._real_reads()
                # PATCH-CORE-UNIFIED-R3: read minimum_reads from policy.
                minimum_reads = ctx.intent_policy.minimum_reads if ctx.intent_policy else 3
                # If reads >= minimum_reads, reset force_tool and let model answer freely.
                # Phase F: separate gates — reads gate + echo gate.
                # Gate 1: insufficient reads (real_reads < minimum_reads).
                # Gate 2: raw echo — model pasted a directory listing verbatim
                #   ("listing for '" or "directory listing") instead of
                #   synthesizing. "based on the gathered evidence:" is a
                #   legitimate synthesis lead-in, NOT an echo marker.
                # Combined: block if insufficient reads OR raw echo.
                _is_listing_only = real_reads < minimum_reads
                _is_echo = any(
                    m in (output or "").lower()
                    for m in ("listing for '", "directory listing")
                )
                _is_listing_only = _is_listing_only or _is_echo
                # PATCH-CORE-UNIFIED-R3: Single-file exemption applied upfront
                # based on policy.minimum_reads. If minimum_reads == 1 then a
                # single read is sufficient (no post-hoc hack after the gate).
                if real_reads >= minimum_reads and not _is_echo and not _looks_like_tool_call(output):
                    self._force_tool = False
                    output = self._synthesize_from_evidence("single_file_ok")
                    self._last_response = output
                elif not _is_listing_only:
                    # Sufficient reads: reset force_tool, let model emit final_answer.
                    self._force_tool = False
                else:
                    self._evidence_rejection_count += 1
                    if self._evidence_rejection_count > self.MAX_EVIDENCE_RETRIES:
                        # Hard cap exceeded: emit explicit failure, never truncated echo.
                        self._force_tool = False
                        output = (
                            f"[Convergence failed — inspected {real_reads} file(s), "
                            f"minimum required: {minimum_reads}. Please refine your query or "
                            f"request specific files to read.]"
                        )
                        self._last_response = output
                    else:
                        # Reject: force tool call + inject concrete file suggestions.
                        self._force_tool = True
                        # Derive file suggestions from latest listing evidence.
                        _file_suggestions = self._extract_listing_files()
                        _hint = _derive_read_hint(ctx.user_prompt)
                        if not _file_suggestions and _hint:
                            _file_suggestions = _hint.lstrip(" (e.g. ").rstrip(")")
                        if _file_suggestions:
                            _suggestion_line = (
                                f" Suggested files to read: {_file_suggestions}."
                            )
                        else:
                            # No listing captured yet (e.g. model jumped straight
                            # to a read, or this is a creation/docs task that never
                            # listed a directory). Without a concrete file list the
                            # rejection is un-actionable and the model stalls until
                            # MAX_EVIDENCE_RETRIES fires "Convergence failed". Force
                            # a hard first action: list the target, then read.
                            _suggestion_line = (
                                " No directory listing captured yet, so no specific "
                                "files can be suggested. Your NEXT response MUST be a "
                                "tool call: use file_system with action='list' on the "
                                "target directory to discover real files, then read "
                                f">={minimum_reads} of them before answering."
                            )
                        rejection_msg = (
                            f"[CONTROL] FINAL_ANSWER rejected — {real_reads} file(s) read, "
                            f"minimum is {minimum_reads}. You MUST call file_system with action='read' to read actual "
                            f"source files.{_suggestion_line} "
                            f"Do NOT emit final_answer until you have read >={minimum_reads} files."
                        )
                        self.state.append_message({"role": "user", "content": rejection_msg})
                        self.state.increment_step()
                        return False
            else:
                # No investigation needed (chitchat): reset force_tool.
                self._force_tool = False

        # ── Path-Claim Disk Backstop (P0 fix) ──────────────────────────────
        # Deterministic, non-LLM. Catches fabricated file/symbol claims like
        # "engine/personas.py" or "tools/handoff.py" that pass the read-count
        # gate because the agent read >=3 unrelated files. Runs for EVERY final
        # answer that reached this choke point (investigation OR chitchat).
        # Note: chitchat usually has no path claims → passes vacuously.
        from core.verifier import check_path_existence_claim

        _disk_result = check_path_existence_claim(
            output or "", None, self.evidence_log
        )
        if not _disk_result.passed:
            self._path_rejection_count = getattr(self, "_path_rejection_count", 0) + 1
            _unsupported = _disk_result.unsupported_claims
            if self._path_rejection_count <= 3:
                control_msg = (
                    "[CONTROL] Your final answer contains claims that cannot be "
                    "verified against the filesystem:\n"
                    + "\n".join(f"  • {u}" for u in _unsupported)
                    + "\nRemove these claims or read the actual files and retry."
                )
                self._force_tool = True
                self.state.append_message({"role": "user", "content": control_msg})
                self.state.increment_step()
                return False
            # Max retries — emit with visible [UNVERIFIED] markers, never silently.
            output = output or ""
            for u in _unsupported:
                _tok = u.replace("Unsupported path (not on disk): ", "")
                if _tok in output:
                    output = output.replace(_tok, f"[UNVERIFIED] {_tok}")

        # ── Final-Answer Claim Gate (Phase 2.3: catch spoofed test/commit claims) ──
        # Runs AFTER the path-claim backstop (which is a separate gate). This gate
        # handles test/pytest/commit claims only — no path overlap.
        # Never produces a dual terminal outcome: returns False for caller to
        # continue, and only emits via hard-cap fallback after MAX_EVIDENCE_RETRIES.
        from core.verifier import check_final_answer_claim_gate

        _gate_result = check_final_answer_claim_gate(
            output or "", self.evidence_log
        )
        if not _gate_result.passed:
            self._evidence_rejection_count = getattr(
                self, "_evidence_rejection_count", 0
            ) + 1
            if self._evidence_rejection_count > self.MAX_EVIDENCE_RETRIES:
                # Hard cap: emit with visible [UNVERIFIED] markers.
                for u in _gate_result.unsupported_claims:
                    _tok = u.split(":")[-1].strip()
                    if _tok and _tok in (output or ""):
                        output = output.replace(_tok, f"[UNVERIFIED] {_tok}")
            else:
                self._force_tool = True
                _blocked_reasons = "\n".join(
                    f"  • {u}" for u in _gate_result.unsupported_claims
                )
                control_msg = (
                    "[CONTROL] FINAL ANSWER rejected by claim gate — "
                    "unsupported claims detected:\n"
                    f"{_blocked_reasons}\n"
                    "Remove these claims or gather matching evidence before retrying."
                )
                self.state.append_message(
                    {"role": "user", "content": control_msg}
                )
                self.state.increment_step()
                return False

        # ── Graphify telemetry (P4, optional) ─────────────────────────────
        # AGENT.md policy: when graphify-out/graph.json exists, architecture-class
        # final answers MUST be grounded via graphify_tool first. Emit a WARNING
        # (never blocks) if an architecture answer ships with zero graphify calls
        # in evidence while the graph is present. No-op when the graph is absent.
        try:
            from pathlib import Path as _Path
            _graph = _Path.cwd() / "graphify-out" / "graph.json"
            if _graph.exists():
                _used_graphify = any(
                    getattr(r, "tool", "") in ("graphify", "graphify_tool")
                    for r in (self.evidence_log.get_records() if self.evidence_log else [])
                )
                if not _used_graphify:
                    logging.warning(
                        "ARCHITECTURE FINAL emitted with 0 graphify_tool calls "
                        "while graphify-out/graph.json exists — AGENT.md graphify "
                        "policy was bypassed for this answer."
                    )
        except Exception:
            pass

        # ── Normal emit path ──────────────────────────────────────────────
        # PATCH-CORE-UNIFIED-R3: Route through centralized terminal outcome.
        from engine._loop_helpers import _commit_terminal_outcome
        _commit_terminal_outcome(
            self,
            status="COMPLETED",
            reason=reason,
            output=output,
        )
        return True
