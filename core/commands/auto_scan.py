"""core/commands/auto_scan.py — auto-scan command handler (V4.4).

Extracted from ui/repl_termux.py._maybe_auto_scan so that:
- workspace listing logic lives in core/
- state.append_message() mutation happens in core/
- evidence_log seeding happens in core/
- UI layer only handles console feedback
"""

from __future__ import annotations

import os
from typing import Any, Optional


def maybe_auto_scan(text: str, agent: Any) -> dict:
    """If *text* contains Arabic scan intent, auto-trigger workspace listing.

    Parameters
    ----------
    text:
        The raw user input to check for scan intent.
    agent:
        The live agent (provides RuntimeState and EvidenceLog).

    Returns
    -------
    dict with keys:
        - triggered (bool): True if scan was attempted
        - success (bool): True if scan completed successfully
        - entry_count (int): number of directory entries found
        - error (str | None): error message if scan failed
    """
    from ui.repl_termux import _detect_arabic_scan_intent  # lightweight, no UI
    if not _detect_arabic_scan_intent(text):
        return {"triggered": False, "success": False, "entry_count": 0, "error": None}

    try:
        entries = sorted(os.listdir("."))
        output = "\n".join(entries)
        if not output:
            return {"triggered": True, "success": False, "entry_count": 0,
                    "error": "Auto-scan returned empty listing."}

        # ── Seed evidence log ─────────────────────────────────────────────
        evidence_log = getattr(agent, "evidence_log", None)
        if evidence_log is not None and hasattr(evidence_log, "record"):
            try:
                evidence_log.record(
                    tool="file_system",
                    command_or_path=".",
                    success=True,
                    output_snippet=output[:200],
                    action="list",
                )
            except Exception:
                pass

        # ── Append results as a system message ────────────────────────────
        state = _resolve_state(agent)
        if state is not None and hasattr(state, "append_message"):
            try:
                msg = (
                    "[CONTROL] Auto-scan: workspace listing was performed because "
                    "your request contained a scan command.\n\n"
                    f"Directory listing (workspace root):\n{output[:2000]}\n\n"
                    "You should now read specific files from this listing to "
                    "answer the user's request. Call file_system with "
                    "action='read' on relevant files."
                )
                state.append_message({"role": "system", "content": msg})
            except Exception:
                pass

        return {
            "triggered": True,
            "success": True,
            "entry_count": len(output.splitlines()),
            "error": None,
        }

    except Exception as exc:
        return {"triggered": True, "success": False, "entry_count": 0, "error": str(exc)}


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
