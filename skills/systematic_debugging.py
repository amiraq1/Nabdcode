"""Concrete NABD OS skill: Systematic Debugging (superpowers-inspired)."""

import re
import traceback
from typing import Any

from .base_skill import BaseSkill


class SystematicDebuggingSkill(BaseSkill):
    """Structured 4-phase root-cause analysis and defensive rewrite planner."""

    def __init__(self, mcp_context: Any = None) -> None:
        super().__init__(
            name="systematic_debugging",
            description=(
                "Performs a structured 4-phase debugging analysis on a failure: "
                "identifies the root cause and exception type, assesses blast "
                "radius across surrounding modules, aligns with previously logged "
                "failures from the MCP context, and formulates a defensive rewrite "
                "strategy using type-guards and exception handling."
            ),
            mcp_context=mcp_context,
        )

    # ── Context helpers (graceful, context-blind fallback) ──────────────
    def _read_context(self) -> dict:
        """Safely read the MCP registry; empty dict if missing/corrupt."""
        ctx = getattr(self, "mcp_context", None)
        if ctx is None:
            return {}
        try:
            return {
                "lessons_learned": list(ctx.lessons_learned),
                "failure_logs": [dict(e) for e in ctx.failure_logs],
                "short_term_context": ctx.short_term_context,
            }
        except Exception:
            return {}

    # ── Phase implementations ───────────────────────────────────────────
    def _phase1_root_cause(self, traceback_str: str) -> str:
        """Dissect the exact failing line and exception type deterministically."""
        exc_type = "Unknown"
        m = re.search(r"(\w+(?:Error|Exception|Warning))", traceback_str)
        if m:
            exc_type = m.group(1)
        # Last 'File "...", line N' is the deepest frame (where it raised).
        frames = re.findall(r'File "([^"]+)", line (\d+)', traceback_str)
        loc = frames[-1] if frames else ("unknown", "unknown")
        # The line following a '    raise' / '    <stmt>' in the last frame.
        line_snip = ""
        last_line = [ln for ln in traceback_str.splitlines() if ln.strip().startswith("raise") or "Error" in ln]
        if last_line:
            line_snip = last_line[-1].strip()
        return (
            f"Exception type: {exc_type}\n"
            f"Failing location: {loc[0]}:{loc[1]}\n"
            f"Offending statement: {line_snip or 'n/a'}"
        )

    def _phase2_blast_radius(self, broken_code: str) -> str:
        """Assess how the crash propagates to surrounding modules/imports."""
        imports = re.findall(r"^\s*(?:from|import)\s+([\w\.]+)", broken_code, re.MULTILINE)
        # A naive but deterministic signal: symbols defined vs. referenced.
        defined = set(re.findall(r"^\s*def\s+(\w+)|^\s*class\s+(\w+)", broken_code, re.MULTILINE))
        defined = {d for pair in defined for d in pair if d}
        risky = []
        for imp in imports:
            risky.append(imp)
        callees = set(re.findall(r"\b(\w+)\(", broken_code))
        external_calls = sorted(callees - defined - {"print", "len", "range", "str", "int", "float", "bool", "list", "dict", "set", "tuple", "isinstance", "enumerate", "zip", "map", "filter", "sorted", "getattr", "hasattr", "type", "open"})
        return (
            f"Imports that may propagate failure: {risky or 'none'}\n"
            f"Outbound calls (blast-radius surface): {external_calls or 'none'}\n"
            f"Locally defined symbols: {sorted(defined) or 'none'}"
        )

    def _phase3_history_alignment(self) -> str:
        """Cross-check MCP context for prior similar failures."""
        ctx = self._read_context()
        if not ctx:
            return "MCP context unavailable — skipping history alignment (context-blind)."
        failures = ctx.get("failure_logs", [])
        lessons = ctx.get("lessons_learned", [])
        if not failures and not lessons:
            return "No prior failures or lessons recorded in MCP context."
        lines = []
        for f in failures[:5]:
            action = f.get("action", "?")
            err = f.get("error", "?")
            lines.append(f"- prior failure: {action} -> {err}")
        for l in lessons[:5]:
            lines.append(f"- lesson: {l}")
        return "History alignment:\n" + "\n".join(lines)

    def _phase4_defensive_formula(self, traceback_str: str, broken_code: str) -> str:
        """Formulate a defensive rewrite strategy (type-guards + try/except)."""
        exc_type = "Exception"
        m = re.search(r"(\w+(?:Error|Exception))", traceback_str)
        if m:
            exc_type = m.group(1)
        return (
            "Defensive rewrite strategy:\n"
            f"1. Wrap the failing section in `try: ... except {exc_type} as exc:` and "
            "return a safe fallback instead of crashing.\n"
            "2. Add type-guards at the boundary (e.g. `if not isinstance(x, Expected): "
            "raise/return early`) before the crash site.\n"
            "3. Never use bare `except:`; catch the specific exception and log it.\n"
            "4. Prefer failing closed (safe default) over partial silent success."
        )

    def execute(self, traceback_str: str, broken_code: str, **kwargs: Any) -> str:
        """Run the 4-phase systematic debugging analysis and return a report."""
        try:
            ctx = kwargs.get("mcp_context") or self.mcp_context
            # Context presence is informational; all phases are deterministic
            # string analysis, so absence degrades gracefully (no crash).
            context_note = (
                "MCP context: active" if ctx is not None else "MCP context: absent (context-blind)"
            )
            report = [
                "=== SYSTEMATIC DEBUGGING REPORT ===",
                context_note,
                "",
                "[PHASE 1] ROOT CAUSE IDENTIFICATION",
                self._phase1_root_cause(traceback_str),
                "",
                "[PHASE 2] BLAST RADIUS ASSESSMENT",
                self._phase2_blast_radius(broken_code),
                "",
                "[PHASE 3] HISTORY & MCP ALIGNMENT",
                self._phase3_history_alignment(),
                "",
                "[PHASE 4] DEFENSIVE FORMULA",
                self._phase4_defensive_formula(traceback_str, broken_code),
            ]
            return "\n".join(report)
        except Exception as exc:  # noqa: BLE001 - analysis must never crash
            return f"Debugging analysis failed: {type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}"
