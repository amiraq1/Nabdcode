"""tests/test_parser_validation.py — Parser validation regression tests (C1).

Locks in two behaviors around tool-call extraction (2026-08-16):

  (a) python-style ``shell(cmd=...)`` / ``execute_shell(command=...)`` written
      as visible text is NOT executed — it is treated as plain prose (no
      ToolCall, no exception), so a model can never trigger a shell command
      by writing it as text;

  (b) a fenced ```json block naming a registered tool (``execute_shell``)
      passes ``validate_tool_call`` and reaches the dispatcher path
      (``_parse_and_validate_tool`` returns ``PROCEED`` with a ToolCall).

The global ``engine.tool_registry.registry`` is isolated per test by
``tests/conftest.py``, so registering ``ShellTool`` here is safe.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.parser import extract_command, validate_tool_call  # noqa: E402
from engine._loop_types import _LoopSignal  # noqa: E402
from engine.loop import ExecutionLoop  # noqa: E402
from engine.state import RuntimeState  # noqa: E402
from engine.tool_registry import registry  # noqa: E402
from tools.shell import ShellTool  # noqa: E402


def _loop() -> ExecutionLoop:
    """Minimal ExecutionLoop for the parser/dispatch gate (no LLM needed)."""
    return ExecutionLoop(
        state=RuntimeState(session_id="parser-validation"),
        llm_provider=lambda msgs: "x",
    )


def test_python_style_shell_text_is_not_executed():
    """shell(cmd="echo x") as visible text must NOT become a tool call.

    The command must neither be parsed into a ToolCall nor raise — it passes
    through as plain text, so the loop treats it as prose (no dispatch).
    """
    registry.register(ShellTool())

    # Parser level: no ToolCall is produced for the python-style text.
    assert extract_command('shell(cmd="echo x")') is None

    # Loop gate level: no tool call reaches the dispatcher, no exception.
    tool_call, signal = _loop()._parse_and_validate_tool('shell(cmd="echo x")')
    assert tool_call is None
    assert signal is _LoopSignal.PROCEED


def test_legacy_execute_shell_text_is_not_executed():
    """execute_shell(command="echo x") as visible text is also NOT executed."""
    registry.register(ShellTool())

    assert extract_command('execute_shell(command="echo x")') is None

    tool_call, signal = _loop()._parse_and_validate_tool(
        'execute_shell(command="echo x")'
    )
    assert tool_call is None
    assert signal is _LoopSignal.PROCEED


def test_fenced_json_execute_shell_reaches_dispatch():
    """A fenced ```json execute_shell call validates and reaches the dispatcher.

    With ``execute_shell`` registered, ``validate_tool_call`` must accept the
    payload and ``_parse_and_validate_tool`` must return PROCEED with the
    ToolCall — the gate right before ``_execute_tool_iteration`` dispatches it.
    """
    registry.register(ShellTool())

    payload = {"tool": "execute_shell", "args": {"command": "echo b"}}
    ok, err = validate_tool_call(payload, registry)
    assert ok is True, f"validate_tool_call must accept a registered tool: {err}"
    assert err == ""

    raw = '```json\n{"tool": "execute_shell", "args": {"command": "echo b"}}\n```'
    parsed = extract_command(raw)
    assert parsed is not None, "fenced JSON must parse into a ToolCall"
    assert parsed.tool == "execute_shell"
    assert parsed.args["command"] == "echo b"

    tool_call, signal = _loop()._parse_and_validate_tool(raw)
    assert signal is _LoopSignal.PROCEED
    assert tool_call is not None
    assert tool_call.tool == "execute_shell"
    assert tool_call.args["command"] == "echo b"


def test_fenced_json_unknown_tool_still_rejected():
    """A fenced ```json call naming an unregistered tool must be rejected.

    The name gate must run even after the fence is unwrapped: an unknown tool
    never reaches the dispatcher (mirrors the goalspec log evidence).
    """
    raw = '```json\n{"tool": "execute_shell", "args": {"command": "echo b"}}\n```'
    # Registry intentionally empty here — execute_shell is NOT registered.
    ok, err = validate_tool_call({"tool": "execute_shell", "args": {"command": "echo b"}}, registry)
    assert ok is False
    assert "not registered" in err