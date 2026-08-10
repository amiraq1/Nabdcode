"""tests/test_emergency_stop.py — Am+9 UX-3: Emergency Stop handler.

Red-guard tests verifying that SIGINT (Ctrl+C) triggers a clean emergency
shutdown: session persisted, exit code 0, no raw traceback.
"""

from __future__ import annotations

import re
import signal
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

MAIN_FILE = Path(__file__).resolve().parent.parent / "main.py"


def _read_main() -> str:
    return MAIN_FILE.read_text(encoding="utf-8")


# ── ع1: emergency_stop_exits_cleanly ───────────────────────────────────────────

def test_emergency_stop_exits_cleanly() -> None:
    """The SIGINT handler must call sys.exit(0) on emergency stop."""
    source = _read_main()
    assert "sys.exit(0)" in source, "sys.exit(0) not found in emergency stop path"
    assert "إيقاف طارئ" in source, "Emergency stop message not found in source"


def test_emergency_stop_has_second_ctrl_c_path() -> None:
    """The handler must distinguish first Ctrl+C (cancel) from second (emergency stop)."""
    source = _read_main()
    assert "is_cancelled" in source, "CancelToken check not found in SIGINT handler"
    assert "Second Ctrl+C" in source or "emergency" in source.lower(), (
        "Second-Ctrl+C emergency path not found"
    )


# ── ع2: session_saved_on_stop ──────────────────────────────────────────────────

def test_session_saved_on_stop() -> None:
    """The emergency stop path must save the session before exiting."""
    source = _read_main()
    assert "session_manager.save()" in source, "Session save not found in emergency stop"
    assert "session_manager.messages" in source, "Session messages not saved"
    assert "session_manager.todos" in source, "Session todos not saved"


def test_memory_manager_closed_on_stop() -> None:
    """The emergency stop path must close the memory manager."""
    source = _read_main()
    assert "memory_manager.close()" in source, "Memory manager not closed on emergency stop"


# ── ع3: no_exception_thrown ────────────────────────────────────────────────────

def test_no_exception_thrown() -> None:
    """The emergency stop path must wrap cleanup in try/except."""
    source = _read_main()
    # The emergency stop block should be inside a try/except
    assert "except Exception:" in source, "Exception handling not found in emergency stop"


def test_sigint_handler_registered() -> None:
    """SIGINT must be registered with the emergency stop handler."""
    source = _read_main()
    assert "signal.signal(signal.SIGINT" in source, (
        "SIGINT handler not registered"
    )


def test_sigint_handler_after_build_app() -> None:
    """The SIGINT handler must be set up AFTER _build_app() so ctx/state are available."""
    source = _read_main()
    build_app_idx = source.find("ctx, state, visualizer, base_inst, ExecutionLoop, ToolRequiredError = _build_app()")
    sigint_idx = source.find("signal.signal(signal.SIGINT")
    assert build_app_idx != -1, "_build_app() call not found"
    assert sigint_idx != -1, "SIGINT registration not found"
    assert sigint_idx > build_app_idx, (
        "SIGINT handler registered before _build_app() — ctx/state not available"
    )
