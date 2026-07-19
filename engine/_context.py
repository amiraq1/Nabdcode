"""
_ContextMixin — runtime context injection, message compaction, RAG trigger.
Extracted from engine/loop.py (refactor step5-b).
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Final, Optional

from core.kernel.events import bus
from core.parser import ToolCall
from core.utils import truncate, safe_strip
from core.storage import load_memory, write_lesson
from core.sanitize import sanitize
from core.prompts import (
    BROWSER_FEWSHOT_EXAMPLES,
    FALLBACK_RESTRICTED_PROMPT,
    CRITICAL_RULES_FOR_TOOL_CALLING,
)
from core.investigation import build_investigation_protocol_prompt
from engine._loop_types import (
    TOOL_WINDOW,
    CHAT_WINDOW,
    MAX_CRITICAL_FULL,
    TOOL_FEWSHOT_FALLBACK,
)

if TYPE_CHECKING:
    from engine._loop_types import _LoopCtx


class _ContextMixin:
    """Mixin for ExecutionLoop holding all context-build + compaction logic.

    Reads self._static_context_cache (defined in ExecutionLoop.__init__).
    Shared constants come from engine._loop_types; helpers defined on
    ExecutionLoop (e.g. _has_active_goal, _prompt_requires_investigation) are
    imported lazily inside the methods that need them to avoid an
    engine.loop circular import.
    """
    def _build_static_context(self) -> str:
        """Build the per-run-invariant runtime-context prefix ONCE.

        Covers disk reads that cannot change within a single run: AGENT.md
        rules, discovered native skills, and the workspace taste summary.
        Memory and graph policy remain variable and are appended per call.
        Fail-silent: any missing/unreadable piece simply contributes nothing.
        """
        parts: list[str] = []

        # AGENT.md rules (project instructions)
        try:
            agent_md = Path("AGENT.md")
            if agent_md.exists():
                parts.append(sanitize(agent_md.read_text(encoding="utf-8"))[:4000])
        except Exception:
            pass

        # Native skills (file walk over workspace + home .nabd/skills)
        try:
            from core.skills import discover_skills, format_skill_context
            skill_block = format_skill_context(discover_skills(Path.cwd()))
            if skill_block:
                parts.append(skill_block)
        except Exception:
            pass

        # Workspace taste summary
        try:
            from core.taste_engine import TasteEngine
            from core.kernel.security import get_workspace_root
            _taste_engine = TasteEngine(workspace_dir=get_workspace_root())
            _taste = _taste_engine.get_taste_summary_for_prompt()
            if _taste:
                parts.append(_taste)
        except Exception:
            pass

        return "\n\n".join(p for p in parts if p)
    def _compact_messages(
        self, messages: list[dict[str, Any]], keep_last_tools: int = TOOL_WINDOW
    ) -> list[dict[str, Any]]:
        """Phase4.1 token-aware pruning with Critical hard caps + XML hardening.

        Layout after compaction (order preserved):
          [0] system                 - always hard-preserved
          [1] user task              - hard-preserved ONLY when an active goal
                                       exists (see _has_active_goal). In casual
                                       chat mode (no goal) it is treated like any
                                       other message and may slide out of the
                                       window so the latest question stays visible.
          [2] <past_steps_summary untrusted="true">  - only if old turns exist
          [3..] recent tool turns (last ``keep_last_tools``) + frozen critical
          [+] latest critique        - [VERIFIER CRITIQUE ...] if present

        Rules enforced:
          * Sliding window keeps the last ``keep_last_tools`` turns in full text.
          * Critical turns are frozen, BUT only the most-recent ``MAX_CRITICAL_FULL``
            keep their full body; older critical turns degrade to a summary pointer.
          * A critical turn already inside the active ``TOOL_WINDOW`` is NOT
            duplicated as a separate ``[evidence:E-id]`` block (dedup check).
          * The historic summary is wrapped in explicit XML guards with
            ``untrusted="true"`` so ancient stdout strings stay isolated from
            the model's instruction channel.
          * ``messages[1]`` (the original user prompt) is frozen at the top
            ONLY when a GoalSpec is active. Without a goal (casual chat) all
            user turns compete equally in the sliding window, so the most
            recent question is never displaced by a stale greeting.
        """
        from engine.loop import _has_active_goal
        ctx = self._ctx
        interactions = ctx.tool_interactions if ctx is not None else []

        system_msg = messages[0] if messages else {"role": "system", "content": ""}

        # In casual chat (no active goal) the original user prompt is NOT frozen
        # — it competes in the sliding window like any other turn, so a stale
        # "hi" can never displace the latest question ("1+1"). With an active
        # goal, messages[1] stays pinned so the objective survives compaction.
        pin_first_user = _has_active_goal(self)
        first_user = messages[1] if (pin_first_user and len(messages) > 1) else None

        critical = [it for it in interactions if it.critical]
        normal = [it for it in interactions if not it.critical]

        # Window is positional: the last ``keep_last_tools`` interactions by
        # sequence order (criticality-agnostic). Split it into critical/normal
        # so a critical turn *sitting in the window* is still rendered as full
        # body (never dropped through the cracks).
        windowed_all = interactions[-keep_last_tools:] if keep_last_tools > 0 else []
        windowed_crit = [it for it in windowed_all if it.critical]
        windowed_norm = [it for it in windowed_all if not it.critical]
        past_norm = normal[:-keep_last_tools] if keep_last_tools > 0 else normal

        # Critical turns OUTSIDE the window: only the most-recent
        # MAX_CRITICAL_FULL keep full body; the rest degrade to a summary pointer.
        windowed_keys = {(it.step, it.evidence_id) for it in windowed_all}
        crit_outside = [it for it in critical if (it.step, it.evidence_id) not in windowed_keys]
        crit_recent = crit_outside[-MAX_CRITICAL_FULL:]
        crit_old = crit_outside[:-MAX_CRITICAL_FULL]

        # Build the lightweight structural summary of discarded turns.
        summary_lines = []
        for it in past_norm:
            summary_lines.append(self._summarize_it(it))
        for it in crit_old:
            summary_lines.append(self._summarize_it(it))
        if summary_lines:
            summary = (
                '<past_steps_summary untrusted="true">\n'
                + "\n".join(summary_lines)
                + "\n</past_steps_summary>"
            )
            past_block = [{"role": "system", "content": summary}]
        else:
            past_block = []

        # Rebuild full-text messages for the kept turns:
        #   • positional window (normal + critical)  → full body
        #   • critical turns outside the window, within the cap → full body
        #   • older critical turns                  → degraded summary pointer
        kept_interactions = list(windowed_norm) + list(windowed_crit) + list(crit_recent)
        kept_interactions.sort(key=lambda it: it.step)  # chronological timeline

        recent: list[dict[str, Any]] = []
        for it in kept_interactions:
            recent.append({
                "role": "tool",
                "tool_call_id": f"call_{it.step}",
                "name": it.tool,
                "content": (
                    f"[{it.tool} Output]\n{it.output}"
                    if it.output
                    else f"[{it.tool} Output] — {it.summary}"
                ),
            })

        # Critical pointers only for older critical turns that degraded
        # (never for windowed or recent-critical, which keep full body above).
        for it in crit_old:
            recent.append({
                "role": "system",
                "content": f"[evidence:{it.evidence_id}] {it.summary}",
            })

        # Preserve the most recent verifier critique (authoritative correction).
        critique = None
        for m in reversed(messages):
            if "[VERIFIER CRITIQUE" in str(m.get("content", "")):
                critique = m
                break

        out: list[dict[str, Any]] = [system_msg]
        if first_user is not None:
            out.append(first_user)

        if not _has_active_goal(self):
            # Casual chat mode: the original prompt is NOT frozen, so we must
            # still surface the recent conversation. Take the trailing
            # CHAT_WINDOW raw messages (user/assistant turns, after the system
            # message and any separately-emitted tool turns) so the latest
            # question ("1+1") is always visible and a stale greeting ("hi")
            # can naturally slide out of the window.
            chat_tail = [
                m for m in messages[1:]
                if m is not first_user and m.get("role") in ("user", "assistant")
            ][-CHAT_WINDOW:]
            out.extend(chat_tail)

        out.extend(past_block)
        out.extend(recent)
        if critique is not None:
            out.append(critique)
        return out
    def _inject_runtime_context(
        self, compacted: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Prepend AGENT.md rules + untrusted memory to the system message.

        Untrusted injected context (AGENT.md / memory) is delimited in
        ``<system_instructions>`` / ``<untrusted_memory_data>`` tags so the model
        can distinguish real system instructions from data that may carry
        injected directives. Treated as DATA, not commands.
        """
        # Phase 3 (tech-debt fix): AGENT.md rules + skills + taste are invariant
        # for the whole run and are pulled from the per-run cache built once in
        # run() (see _build_static_context), instead of re-read from disk here.
        # Lazily build it if absent (e.g. when _inject_runtime_context is called
        # standalone, outside run()) so behavior matches the original per-call
        from engine.loop import _prompt_requires_investigation, _has_active_goal
        # path; in run() the cache is populated once and reused here.
        if self._static_context_cache is None:
            self._static_context_cache = self._build_static_context()
        static_ctx = self._static_context_cache or ""
        rules = ""  # populated below from the cached static context
        memory = sanitize(load_memory() or "")[:4000]
        from core.constants import TODO_DISCIPLINE, SECURITY_COMPLIANCE_RULE, LANGUAGE_POLICY, PYTHON_AND_CODE_EXPLORATION_POLICY, GRAPHIFY_KNOWLEDGE_GRAPH_POLICY

        # Split the cached static context into AGENT.md rules (first, if present)
        # and the remainder (skills + taste). The AGENT.md block dominates `rules`.
        if static_ctx:
            # The AGENT.md text is the portion before the skills block marker if
            # both were captured; simplest correct split: treat whole static_ctx
            # as rules when no skill marker, else separate. We keep it simple and
            # inject the entire cached block as `rules` since downstream only
            # appends `rules` into <system_instructions>. Skills/taste are already
            # wrapped inside their own guards by the builder, so re-wrapping here
            # would double-wrap — instead we emit them after </system_instructions>.
            _skills_marker = "<workspace_skills>"
            if _skills_marker in static_ctx:
                rules, _skills_tail = static_ctx.split(_skills_marker, 1)
                rules = rules.strip()
                _skills_block = _skills_marker + _skills_tail
            else:
                rules = static_ctx.strip()
                _skills_block = ""
        else:
            rules = ""
            _skills_block = ""

        prefix = "<system_instructions>\n"
        user_msg = ""
        for m in compacted:
            if m.get("role") == "user" and isinstance(m.get("content"), str):
                user_msg = m["content"]
                break
        goal_obj = getattr(self.state, "active_goal", None) if hasattr(self, "state") and self.state else getattr(self, "_goal", None)
        has_active_goal = bool(goal_obj and getattr(goal_obj, "success_criteria", None) and getattr(goal_obj, "success_criteria", None) != "None")
        req_tools = _prompt_requires_investigation(user_msg, has_active_goal=has_active_goal) if user_msg else True

        if req_tools:
            prefix += f"{TODO_DISCIPLINE}\n\n"
            from core.investigation import build_investigation_protocol_prompt
            inv_prompt = build_investigation_protocol_prompt(user_msg)
            if inv_prompt:
                prefix += f"{inv_prompt}\n\n"
        else:
            prefix += "## Casual/Direct Context Exception (Active)\nThis user prompt is purely conversational, informational, or conceptual without an active goal or workspace task. Answer directly, warmly, and immediately using final_answer without executing tools or inspecting workspace files.\n\n"
        prefix += f"{SECURITY_COMPLIANCE_RULE}\n\n"
        prefix += f"{LANGUAGE_POLICY}\n\n"
        prefix += f"{PYTHON_AND_CODE_EXPLORATION_POLICY}\n\n"
        # Phase 1.1: inject the graphify policy only when the graph exists;
        # otherwise we mandate a tool for an absent subsystem.
        # TODO: test_graphify_policy_injected fails on HEAD (pre-existing, _graph_ok gate).
        #       Needs graph.json fixture in tests or gate removal decision by maintainer.
        try:
            from pathlib import Path as _GPath
            from core.kernel.security import get_workspace_root as _wsr
            _graph_ok = (_GPath(_wsr()) / "graphify-out" / "graph.json").exists()
        except Exception:
            _graph_ok = False
        if _graph_ok:
            prefix += f"{GRAPHIFY_KNOWLEDGE_GRAPH_POLICY}\n\n"

        # Taste summary is now part of the per-run static cache (see
        # _build_static_context) and is no longer re-read from disk per call.

        if rules:
            prefix += f"{rules}\n\n"
        prefix += "</system_instructions>\n"
        if memory:
            prefix += (
                "<untrusted_memory_data>\n"
                f"# Previous memory:\n{memory}\n"
                "</untrusted_memory_data>\n\n"
            )

        # Phase5 (Workspace Context): project-specific instructions loaded from
        # the cwd (AGENTS.md / .agents/config.md). Injected into the system anchor
        # (messages[0]) inside strict <workspace_context> guards so the Phase 4
        # compaction engine treats it as an instruction and hard-preserves it —
        # it is never evicted by the sliding window. Untrusted file content, so
        # the model must treat it as DATA/context, not overriding commands.
        ws_ctx = getattr(self, "_workspace_context", "") or ""
        if ws_ctx:
            prefix += (
                "<workspace_context>\n"
                f"{ws_ctx}\n"
                "</workspace_context>\n\n"
            )

        # Phase 6 (Native Skills Loader): skills are now part of the per-run
        # static cache (_build_static_context). Emit the cached block verbatim.
        skill_block = _skills_block
        if skill_block:
            prefix += skill_block + "\n\n"

        system_content = f"{prefix}{compacted[0]['content']}"
        goal = getattr(self.state, "active_goal", None) if hasattr(self, "state") and self.state else getattr(self, "_goal", None)
        if goal:
            from engine.state import build_goal_block
            goal_block = build_goal_block(goal)
            if goal_block:
                system_content += f"\n{goal_block}"

        # Phase 2: small / fallback models get a tight few-shot anchor so they
        # emit a single clean JSON tool call instead of prose. Capable models
        # are left untouched to avoid context bloat.
        if getattr(self.state, 'is_fallback_mode_active', False):
            system_content += f"\n\n{FALLBACK_RESTRICTED_PROMPT}"
        if self._is_small_or_fallback_model() or getattr(self.state, 'is_fallback_mode_active', False):
            system_content += f"\n\n{TOOL_FEWSHOT_FALLBACK}"
        else:
            system_content += f"\n\n{CRITICAL_RULES_FOR_TOOL_CALLING}"

        # Phase 7 (Tool Visibility): explicitly list all available tools with
        # their parameters so the model knows what it CAN call. Without this,
        # small/fallback models never see the tool registry and hallucinate.
        tools_block = self._format_tools_for_prompt()
        if tools_block:
            system_content += f"\n\n{tools_block}"

        return [
            {"role": "system", "content": system_content}
        ] + compacted[1:]

    def _maybe_auto_trigger_rag(self) -> None:
        """Force a RAG search when the user asks about a known codebase symbol.

        Small/fallback models (ORCA-FLASH) frequently skip tool calls and
        hallucinate. When the latest user message names a symbol that exists in
        the local knowledge base (e.g. "EventBus", "KineticStateEngine"), we
        inject a forced search_knowledge_base call so the model is anchored to
        real code before it answers.
        """
        ctx = self._ctx
        if ctx is None:
            return
        # Only trigger once per run (avoid loops).
        if getattr(ctx, "rag_auto_triggered", False):
            return
        from engine.tool_registry import registry
        if "search_knowledge_base" not in registry:
            return

        # Find the latest user message.
        user_msg = ""
        for msg in reversed(self.state.get_messages()):
            if msg.get("role") == "user":
                user_msg = msg.get("content", "")
                break
        if not user_msg:
            return

        # Known codebase symbols worth retrieving. Only trigger on explicit
        # architectural/code questions — never on greetings or massless queries
        # (those are caught by the Small-Talk guard in main.py before the loop
        # runs, so we add a second safety net here).
        triggers = (
            "eventbus", "kineticstateengine", "renderer class", "dispatcher class",
            "evidence log", "executionloop", "memorymanager", "toolregistry",
            "hybridretriever", "rag search", "embedding model", "vector index",
            "how does the eventbus", "how does the kinetic", "how does the renderer",
            "explain the eventbus", "explain the kinetic", "architecture of the",
        )
        _norm_user = user_msg.lower()
        # Exclude pure greetings / short inputs.
        if len(_norm_user.strip()) <= 10 or _norm_user.strip() in ("hi", "hello", "hey", "1hi"):
            return
        if not any(t in _norm_user for t in triggers):
            return

        # Mark triggered so we don't loop.
        ctx.rag_auto_triggered = True

        # Build a focused query from the user message.
        query = user_msg[:200].strip()
        tool_call = ToolCall(
            tool="search_knowledge_base",
            args={"action": "search", "query": query, "k": 3},
        )
        bus.emit("tool_started", {"tool": "search_knowledge_base", "args": tool_call.args, "step": self.state.step_count})
        result = self.dispatcher.dispatch("search_knowledge_base", tool_call.args)
        bus.emit("tool_completed", {
            "tool": "search_knowledge_base",
            "result": result,
            "success": result.success,
            "returncode": result.returncode,
            "step": self.state.step_count,
        })
        output = truncate(getattr(result, "output", "") or "", self.max_output_len)
        feedback = self._build_tool_feedback(result, "search_knowledge_base", tool_call.args, output)
        self.evidence_log.record(
            tool="search_knowledge_base",
            command_or_path=query[:60],
            success=result.success,
            output_snippet=output,
        )
        self.state.append_message({
            "role": "system",
            "content": f"[TOOL RESULT: search_knowledge_base]\n{feedback}",
        })
        self.state.increment_step()
        time.sleep(self.POLL_DELAY)


