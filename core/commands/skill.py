"""core/commands/skill.py — /skill command handler (V4.3).

Extracted from ui/repl_termux.py._handle_skill_command so that skill
execution (execute_skill, state.active_goal) lives in core/, not UI layer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional


def handle_skill_command(text: str, agent: Any = None) -> Optional[dict]:
    """Parse and execute a /skill command.

    Parameters
    ----------
    text:
        The raw user input (e.g. ``/skill reviewer core/state.py``).
    agent:
        The live agent (provides RuntimeState and EvidenceLog).

    Returns
    -------
    dict | None
        None if *text* is not a /skill command.
        Otherwise a dict with:
            - consumed (bool): always True for /skill commands
            - success (bool)
            - skill_name (str)
            - output (str)
            - error (str | None)
    """
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    if cmd != "/skill":
        return None  # not a skill command

    name_arg = parts[1].strip() if len(parts) > 1 else ""
    if not name_arg:
        return {"consumed": True, "success": False, "skill_name": "",
                "output": "", "error": "Usage: /skill <name> [args...]"}

    name_parts = name_arg.split(maxsplit=1)
    name = name_parts[0]
    skill_args = name_parts[1].strip() if len(name_parts) > 1 else ""

    from core.skills import discover_skills, find_skill, execute_skill

    state = _resolve_state(agent)
    skills = discover_skills(Path.cwd())
    skill = find_skill(skills, name)

    if skill is None:
        return {"consumed": True, "success": False, "skill_name": name,
                "output": "", "error": f"Skill not found: {name}"}

    # Apply goal spec from skill metadata (if any)
    if state and (getattr(skill, "goal", "") or getattr(skill, "success_criteria", "")):
        from core.kernel.state import GoalSpec
        g_prompt = getattr(skill, "goal", "") or getattr(skill, "description", "") or skill.name
        g_crit = getattr(skill, "success_criteria", "") or g_prompt
        state.active_goal = GoalSpec(raw_prompt=g_prompt, success_criteria=g_crit, is_met=False)

    evidence_log = _resolve_evidence_log(agent)
    result = execute_skill(skill, state=state, evidence_log=evidence_log)

    ok = bool(getattr(result, "success", False))
    out = getattr(result, "stdout", "") or getattr(result, "stderr", "") or ""
    if isinstance(out, str) and len(out) > 4000:
        out = out[-4000:]

    return {
        "consumed": True,
        "success": ok,
        "skill_name": skill.name,
        "output": out,
        "error": None,
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _resolve_state(agent: Any):
    """Best-effort resolve RuntimeState from agent (no UI dependency)."""
    if agent is None:
        return None
    try:
        from core.kernel.state import RuntimeState
        state = getattr(agent, "state", None) or getattr(agent, "runtime_state", None)
        if isinstance(state, RuntimeState):
            return state
    except Exception:
        pass
    return None


def _resolve_evidence_log(agent: Any):
    """Best-effort resolve EvidenceLog from agent."""
    if agent is None:
        return None
    return getattr(agent, "evidence_log", None)
