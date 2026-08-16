"""core/commands/auto_scan.py — auto-scan command handler (V4.4)."""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any


# Arabic scan intent keywords (EXE-04: defined in core, zero UI dependencies)
_ARABIC_SCAN_KEYWORDS: list[str] = [
    "فحر",      # colloquial Egyptian "scan"
    "افحص",     # standard Arabic "scan/inspect"
    "فحص",      # "inspection"
    "مسح",      # "scan"
    "استكشاف",  # "explore"
    "كشف",      # "discover"
    "دقق",      # "scrutinize"
    "دقّق",     # "scrutinize" (with shadda)
    "طالع",     # "review"
]


def _detect_arabic_scan_intent(text: str) -> bool:
    """Return True if *text* contains an Arabic repository scan verb."""
    if not text:
        return False
    normalized = " ".join(text.split())
    return any(kw in normalized for kw in _ARABIC_SCAN_KEYWORDS)


def maybe_auto_scan(text: str, agent: Any) -> dict:
    """Run a pinned-workspace listing when *text* carries scan intent.

    The workspace result contract is intentionally stable.  When a scan is
    attempted, the UI EventBus receives exactly one ``tool_started`` and one
    ``tool_completed`` event; the emitted path is display-safe while the
    returned ``workspace_root`` remains available to trusted callers.
    """
    if not _detect_arabic_scan_intent(text):
        return {
            "triggered": False,
            "success": False,
            "entry_count": 0,
            "error": None,
            "workspace_root": None,
        }

    from core.kernel.events import bus
    from core.kernel.security import display_path, get_workspace_root, is_workspace_pinned

    workspace_root = get_workspace_root()
    if not is_workspace_pinned():
        return {
            "triggered": True,
            "success": False,
            "entry_count": 0,
            "error": (
                "لا يوجد مستودع محدد لهذه الجلسة. "
                "اختر مجلد مشروع أو استخدم /workspace <path>."
            ),
            "workspace_root": str(workspace_root),
        }

    state = _resolve_state(agent)
    step = getattr(state, "step_count", 0) if state is not None else 0
    session_id = getattr(state, "session_id", None) if state is not None else None
    result = SimpleNamespace(stdout="", stderr="", success=False)
    success = False
    entry_count = 0
    error: str | None = None

    try:
        bus.emit(
            "tool_started",
            {
                "tool": "repo_scan",
                "args": {"action": "list", "path": display_path(str(workspace_root))},
                "step": step,
                "session_id": session_id,
            },
        )
    except Exception:
        # A dead UI listener must not disable a safe workspace scan.
        pass

    try:
        entries = sorted(os.listdir(workspace_root))
        output = "\n".join(entries)
        if not output:
            # Preserve the trusted return-contract used by workspace tests;
            # the event result remains path-free and Renderer sanitizes output.
            error = f"Auto-scan returned empty listing at {workspace_root}."
            return {
                "triggered": True,
                "success": False,
                "entry_count": 0,
                "error": error,
                "workspace_root": str(workspace_root),
            }

        evidence_log = getattr(agent, "evidence_log", None)
        if evidence_log is not None and hasattr(evidence_log, "record"):
            try:
                evidence_log.record(
                    tool="file_system",
                    command_or_path=str(workspace_root),
                    success=True,
                    output_snippet=output[:200],
                    action="list",
                )
            except Exception:
                pass

        if state is not None and hasattr(state, "append_message"):
            try:
                message = (
                    "[CONTROL] Auto-scan: workspace listing was performed because "
                    "your request contained a scan command.\n\n"
                    f"Directory listing (workspace root: {workspace_root}):\n"
                    f"{output[:2000]}\n\n"
                    "You should now read specific files from this listing to "
                    "answer the user's request. Call file_system with "
                    "action='read' on relevant files."
                )
                state.append_message({"role": "system", "content": message})
            except Exception:
                pass

        entry_count = len(output.splitlines())
        result = SimpleNamespace(stdout=output, stderr="", success=True)
        success = True
        return {
            "triggered": True,
            "success": True,
            "entry_count": entry_count,
            "error": None,
            "workspace_root": str(workspace_root),
        }
    except Exception as exc:
        error = str(exc)
        result = SimpleNamespace(stdout="", stderr=error, success=False)
        return {
            "triggered": True,
            "success": False,
            "entry_count": 0,
            "error": error,
            "workspace_root": str(workspace_root),
        }
    finally:
        try:
            bus.emit(
                "tool_completed",
                {
                    "tool": "repo_scan",
                    "result": result,
                    "success": success,
                    "returncode": 0 if success else -1,
                    "diff": "",
                    "step": step,
                    "session_id": session_id,
                },
            )
        except Exception:
            pass


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
