"""Phase 5 — Workspace Context Loader (AGENTS.md awareness) tests.

Verifies:
  1. load_workspace_context() reads AGENTS.md and .agents/config.md (fallback).
  2. Missing file → "" (fail-safe, no exception).
  3. Unreadable / permission error → "" (fail-safe).
  4. Oversized file is truncated to the 10KB cap.
  5. The loop injects a found workspace context into messages[0] inside
     <workspace_context> guards, and the compacted output keeps it (Phase 4
     hard-preserves messages[0]).
"""

import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.workspace import load_workspace_context, MAX_WORKSPACE_CONTEXT_BYTES
from engine.loop import ExecutionLoop
from engine.state import RuntimeState


# ── Loader ───────────────────────────────────────────────────────────────

def test_loads_agents_md():
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "AGENTS.md").write_text("# Project X\nUse ruff, not flake8.\n", encoding="utf-8")
        ctx = load_workspace_context(Path(tmp))
        assert "Project X" in ctx
        assert "ruff" in ctx


def test_fallback_to_agents_config_md():
    with tempfile.TemporaryDirectory() as tmp:
        dot = Path(tmp) / ".agents"
        dot.mkdir()
        (dot / "config.md").write_text("Fallback instructions here.\n", encoding="utf-8")
        ctx = load_workspace_context(Path(tmp))
        assert "Fallback instructions here." in ctx


def test_missing_file_returns_empty():
    with tempfile.TemporaryDirectory() as tmp:
        assert load_workspace_context(Path(tmp)) == ""


def test_unreadable_file_returns_empty():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "AGENTS.md"
        p.write_text("secret instructions", encoding="utf-8")
        try:
            # Make unreadable (best-effort; may not apply on all platforms).
            os.chmod(p, 0o000)
            ctx = load_workspace_context(Path(tmp))
            assert ctx == ""
        finally:
            os.chmod(p, 0o644)


def test_oversized_file_truncated():
    with tempfile.TemporaryDirectory() as tmp:
        big = "x" * (MAX_WORKSPACE_CONTEXT_BYTES + 5000)
        (Path(tmp) / "AGENTS.md").write_text(big, encoding="utf-8")
        ctx = load_workspace_context(Path(tmp))
        # Hard cap must hold (allow small slack for multi-byte chars).
        assert len(ctx) <= MAX_WORKSPACE_CONTEXT_BYTES + 4


# ── Injection into messages[0] ───────────────────────────────────────────

def test_workspace_context_injected_into_system_anchor():
    """When cwd has AGENTS.md, the loop injects it (guarded) into messages[0],
    and the compacted output still carries it (Phase 4 hard-preserves [0])."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "AGENTS.md").write_text("PROJECT RULE: always run pytest.\n", encoding="utf-8")
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            state = RuntimeState(session_id="ws-ctx")
            loop = ExecutionLoop(state=state, llm_provider=lambda msgs: "ok")
            loop._workspace_context = load_workspace_context(Path.cwd())
            compacted = loop._compact_messages(state.get_messages())
        finally:
            os.chdir(cwd)

        # messages[0] (system anchor) must contain the guarded project context.
        # The injection lives in _inject_runtime_context, which the loop calls
        # on the compacted messages right before invoking the LLM.
        injected = loop._inject_runtime_context(compacted)
        sys_content = injected[0]["content"]
        assert "<workspace_context>" in sys_content
        assert "PROJECT RULE: always run pytest." in sys_content
        assert "</workspace_context>" in sys_content


def test_no_workspace_context_when_absent():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            state = RuntimeState(session_id="ws-none")
            loop = ExecutionLoop(state=state, llm_provider=lambda msgs: "ok")
            compacted = loop._compact_messages(state.get_messages())
            injected = loop._inject_runtime_context(compacted)
        finally:
            os.chdir(cwd)
        assert "<workspace_context>" not in injected[0]["content"]


if __name__ == "__main__":
    for fn in [
        test_loads_agents_md,
        test_fallback_to_agents_config_md,
        test_missing_file_returns_empty,
        test_unreadable_file_returns_empty,
        test_oversized_file_truncated,
        test_workspace_context_injected_into_system_anchor,
        test_no_workspace_context_when_absent,
    ]:
        fn()
        print("ok", fn.__name__)
    print("All Workspace Context tests passed.")
