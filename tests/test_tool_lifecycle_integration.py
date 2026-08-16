"""Integration coverage for terminal tool lifecycle and scan headers.

These tests protect the user-turn event boundary, EventBus payload contract,
thread-local Dispatcher ownership, and display-path privacy fallbacks.
"""
from __future__ import annotations

import io
import sys
import threading
import types
from pathlib import Path

import pytest

from core.kernel.events import EventBus, bus


class _FakeRenderer:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def tool_start(self, tool, args) -> None:
        self.calls.append(("tool_start", tool, args))

    def tool_end(self, tool, *, success, output="", summary="", diff="") -> None:
        self.calls.append(("tool_end", tool, success, summary))

    def status_snapshot(self, verb, tokens=None) -> None:
        self.calls.append(("status", verb))

    def flush(self) -> None:
        pass

    def think_end(self) -> None:
        pass

    def dim_line(self, message) -> None:
        pass

    def badge_line(self, badge_txt, message, color="cyan") -> None:
        pass

    def todos(self, items) -> None:
        pass

    def error_badge(self, title, body="") -> None:
        pass

    def shutdown(self) -> None:
        pass


@pytest.fixture
def wired(monkeypatch):
    """Wire the real singleton EventBus to an isolated fake renderer."""
    import main
    import ui.event_wiring as ew

    saved_subscribers = {name: dict(subs) for name, subs in bus._subscribers.items()}
    saved_tokens = list(ew._wire_tokens)
    original_status_bar = main.status_bar
    bus._subscribers = {}
    ew._wire_tokens = []
    monkeypatch.setattr(main, "status_bar", types.SimpleNamespace(wire=lambda: None))
    renderer = _FakeRenderer()
    context = types.SimpleNamespace(
        renderer=renderer,
        metrics=types.SimpleNamespace(record_api_call=lambda **_: None),
        todo_manager=None,
    )
    output = io.StringIO()
    monkeypatch.setattr(sys, "stdout", output)
    try:
        ew.wire_events(context)
        yield output, renderer
    finally:
        for unsubscribe in list(ew._wire_tokens):
            try:
                unsubscribe()
            except Exception:
                pass
        ew._wire_tokens = saved_tokens
        bus._subscribers = saved_subscribers
        monkeypatch.setattr(main, "status_bar", original_status_bar)


def test_multi_step_turn_keeps_tools_done(wired, capsys):
    _, renderer = wired
    bus.emit("user_turn_started", {})
    bus.emit("llm_request_started", {"step": 1})
    bus.emit("tool_started", {"tool": "repo_scan", "args": {"path": "project"}, "step": 1})
    bus.emit(
        "tool_completed",
        {
            "tool": "repo_scan",
            "success": True,
            "result": types.SimpleNamespace(stdout="src\ntests\n", stderr="", success=True),
            "returncode": 0,
            "diff": "",
            "step": 1,
            "session_id": None,
        },
    )
    bus.emit("llm_request_started", {"step": 2})
    bus.emit("llm_request_completed", {"duration": 0.1})

    rendered = capsys.readouterr().out
    assert "✓ Thinking ✓ Tools ✓ Generating" in rendered
    assert ("tool_start", "repo_scan", {"path": "project"}) in renderer.calls


def test_direct_answer_never_marks_tools_done(wired, capsys):
    _, _ = wired
    bus.emit("user_turn_started", {})
    bus.emit("llm_request_started", {"step": 1})
    bus.emit("llm_request_completed", {"duration": 0.1})
    assert "✓ Tools" not in capsys.readouterr().out


def test_wire_events_reentry_replaces_old_renderer(monkeypatch):
    import main
    import ui.event_wiring as ew

    saved_subscribers = {name: dict(subs) for name, subs in bus._subscribers.items()}
    saved_tokens = list(ew._wire_tokens)
    original_status_bar = main.status_bar
    bus._subscribers = {}
    ew._wire_tokens = []
    monkeypatch.setattr(main, "status_bar", types.SimpleNamespace(wire=lambda: None))
    output = io.StringIO()
    monkeypatch.setattr(sys, "stdout", output)

    def make_context(renderer):
        return types.SimpleNamespace(
            renderer=renderer,
            metrics=types.SimpleNamespace(record_api_call=lambda **_: None),
            todo_manager=None,
        )

    first = _FakeRenderer()
    second = _FakeRenderer()
    try:
        ew.wire_events(make_context(first))
        ew.wire_events(make_context(second))
        assert len(bus._subscribers.get("llm_request_started", {})) == 1
        assert len(bus._subscribers.get("tool_started", {})) == 1
        assert len(bus._subscribers.get("user_turn_started", {})) == 1

        bus.emit("llm_request_started", {"step": 1})
        bus.emit("tool_started", {"tool": "repo_scan", "args": {}, "step": 1})
        assert output.getvalue().count("Thinking") == 1
        assert first.calls == []
        assert any(call[0] == "tool_start" for call in second.calls)
    finally:
        for unsubscribe in list(ew._wire_tokens):
            try:
                unsubscribe()
            except Exception:
                pass
        ew._wire_tokens = saved_tokens
        bus._subscribers = saved_subscribers
        monkeypatch.setattr(main, "status_bar", original_status_bar)


def test_auto_scan_emits_one_complete_event_pair(monkeypatch, tmp_path):
    import core.commands.auto_scan as auto_scan
    import core.kernel.events as events_mod
    import core.kernel.security as security_mod

    test_bus = EventBus()
    monkeypatch.setattr(events_mod, "bus", test_bus)
    monkeypatch.setattr(security_mod, "is_workspace_pinned", lambda: True)
    monkeypatch.setattr(security_mod, "get_workspace_root", lambda: tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "README.md").write_text("# test", encoding="utf-8")

    started: list[dict] = []
    completed: list[dict] = []
    test_bus.subscribe("tool_started", started.append)
    test_bus.subscribe("tool_completed", completed.append)

    outcome = auto_scan.maybe_auto_scan("افحص المستودع", None)
    assert outcome["success"] is True
    assert len(started) == 1
    assert len(completed) == 1
    assert started[0]["tool"] == "repo_scan"
    assert str(tmp_path) not in str(started[0])
    payload = completed[0]
    assert set(payload) == {"tool", "result", "success", "returncode", "diff", "step", "session_id"}
    assert payload["success"] is True
    assert payload["returncode"] == 0
    assert payload["result"].success is True
    assert str(tmp_path) not in str(payload)


def test_auto_scan_empty_listing_emits_failed_completion(monkeypatch, tmp_path):
    import core.commands.auto_scan as auto_scan
    import core.kernel.events as events_mod
    import core.kernel.security as security_mod

    test_bus = EventBus()
    monkeypatch.setattr(events_mod, "bus", test_bus)
    monkeypatch.setattr(security_mod, "is_workspace_pinned", lambda: True)
    monkeypatch.setattr(security_mod, "get_workspace_root", lambda: tmp_path)
    completed: list[dict] = []
    test_bus.subscribe("tool_completed", completed.append)

    outcome = auto_scan.maybe_auto_scan("افحص المستودع", None)
    assert outcome["success"] is False
    assert len(completed) == 1
    assert completed[0]["success"] is False
    assert completed[0]["result"].success is False


def test_cmd_scan_emits_one_complete_event_pair(monkeypatch):
    import core.command_dispatcher as commands
    import core.kernel.events as events_mod
    import core.kernel.security as security_mod
    import core.ui_bridge as bridge_mod
    from core.repo_scanner import SECURE_REPO_SCANNER

    test_bus = EventBus()
    monkeypatch.setattr(events_mod, "bus", test_bus)
    monkeypatch.setattr(commands, "sys", types.SimpleNamespace(stdout=io.StringIO(), flush=lambda: None))
    monkeypatch.setattr(security_mod, "get_workspace_root", lambda: Path("/workspace"))
    monkeypatch.setattr(bridge_mod, "get_bridge", lambda: None)
    monkeypatch.setattr(
        SECURE_REPO_SCANNER,
        "_deep_scan",
        lambda self, root: {"total_files": 3, "files": ["a", "b", "c"]},
    )
    started: list[dict] = []
    completed: list[dict] = []
    test_bus.subscribe("tool_started", started.append)
    test_bus.subscribe("tool_completed", completed.append)

    state = types.SimpleNamespace(step_count=4, session_id="scan-session")
    assert commands._cmd_scan("/scan", state, types.SimpleNamespace(), "") is True
    assert len(started) == 1
    assert len(completed) == 1
    assert completed[0]["success"] is True
    assert completed[0]["step"] == 4
    assert completed[0]["session_id"] == "scan-session"


def test_cmd_scan_failure_emits_failed_completion(monkeypatch):
    import core.command_dispatcher as commands
    import core.kernel.events as events_mod
    import core.kernel.security as security_mod
    import core.ui_bridge as bridge_mod
    from core.repo_scanner import SECURE_REPO_SCANNER

    test_bus = EventBus()
    monkeypatch.setattr(events_mod, "bus", test_bus)
    monkeypatch.setattr(commands, "sys", types.SimpleNamespace(stdout=io.StringIO(), flush=lambda: None))
    monkeypatch.setattr(security_mod, "get_workspace_root", lambda: Path("/workspace"))
    monkeypatch.setattr(bridge_mod, "get_bridge", lambda: None)

    def fail_scan(self, root):
        raise RuntimeError("scan exploded")

    monkeypatch.setattr(SECURE_REPO_SCANNER, "_deep_scan", fail_scan)
    completed: list[dict] = []
    test_bus.subscribe("tool_completed", completed.append)

    assert commands._cmd_scan("/scan", types.SimpleNamespace(step_count=0, session_id=None), types.SimpleNamespace(), "") is True
    assert len(completed) == 1
    assert completed[0]["success"] is False
    assert "scan exploded" in completed[0]["result"].stderr


def _fake_tool_type(observed_dispatching, errors):
    from engine.dispatcher import is_dispatching
    from tools.base import BaseTool
    from tools.models import ToolResult

    class FakeTool(BaseTool):
        name = "fake_tool"

        def execute(self, **kwargs):
            try:
                observed_dispatching.append(is_dispatching())
                return ToolResult(success=True, stdout="ok", returncode=0, status="success")
            except Exception as exc:  # pragma: no cover - preserves thread failure
                errors.append(exc)
                raise

    return FakeTool


def test_direct_tool_use_in_worker_thread_emits_one_pair(monkeypatch):
    import core.kernel.events as events_mod
    import engine.dispatcher as dispatcher_mod

    test_bus = EventBus()
    monkeypatch.setattr(events_mod, "bus", test_bus)
    monkeypatch.setattr(dispatcher_mod, "bus", test_bus)
    observed: list[bool] = []
    errors: list[Exception] = []
    tool = _fake_tool_type(observed, errors)()
    started: list[dict] = []
    completed: list[dict] = []
    test_bus.subscribe("tool_started", started.append)
    test_bus.subscribe("tool_completed", completed.append)

    worker = threading.Thread(target=tool, args=({"q": "x"},))
    worker.start()
    worker.join(timeout=3)
    assert not worker.is_alive()
    assert not errors, errors
    assert observed == [False]
    assert len(started) == 1
    assert len(completed) == 1
    assert completed[0]["step"] is None
    assert completed[0]["session_id"] is None


def test_dispatcher_worker_emits_one_pair_without_base_tool_duplicate(monkeypatch):
    import core.kernel.events as events_mod
    from engine.dispatcher import Dispatcher
    from engine.state import RuntimeState
    from engine.tool_registry import ToolRegistry

    test_bus = EventBus()
    monkeypatch.setattr(events_mod, "bus", test_bus)
    monkeypatch.setattr("engine.dispatcher.bus", test_bus)
    observed: list[bool] = []
    errors: list[Exception] = []
    registry = ToolRegistry()
    registry.register("fake_tool", _fake_tool_type(observed, errors)())
    started: list[dict] = []
    completed: list[dict] = []
    test_bus.subscribe("tool_started", started.append)
    test_bus.subscribe("tool_completed", completed.append)

    state = RuntimeState(session_id="threaded", max_steps=5)
    result = Dispatcher(state, tool_registry=registry, event_bus=test_bus).dispatch("fake_tool", {"q": "x"})
    assert result.success is True
    assert not errors, errors
    assert observed == [True]
    assert len(started) == 1
    assert len(completed) == 1


def test_display_path_safe_fallback_contract(tmp_path):
    from core.kernel.security import display_path, get_workspace_root, is_workspace_pinned, pin_workspace_root

    previous = get_workspace_root() if is_workspace_pinned() else None
    root = tmp_path / "project"
    (root / "core").mkdir(parents=True)
    (root / "core" / "task_graph.py").write_text("x", encoding="utf-8")
    pin_workspace_root(root)
    try:
        assert display_path("core/task_graph.py") == "core/task_graph.py"
        assert display_path(str(root / "core" / "task_graph.py")) == "core/task_graph.py"
        assert display_path(str(tmp_path / "secret.txt")) == "<outside-workspace>"
        assert display_path("") == "<path>"
        assert display_path(None) == "<path>"
        assert display_path("x.py") == "x.py"
    finally:
        pin_workspace_root(previous)


def test_one_shot_emits_user_turn_started_once(monkeypatch):
    import main
    import core.kernel.events as events_mod

    test_bus = EventBus()
    monkeypatch.setattr(events_mod, "bus", test_bus)
    emitted: list[str] = []
    test_bus.subscribe("user_turn_started", lambda _: emitted.append("turn"))

    class FakeLoop:
        def __init__(self, **kwargs):
            pass

        def run(self, query):
            # Simulate internal LLM retry steps: no new outer user turn.
            test_bus.emit("llm_request_started", {"step": 1})
            test_bus.emit("llm_request_started", {"step": 2})
            return types.SimpleNamespace(safe_message="ok", final_answer="")

    state = types.SimpleNamespace(
        reset_step_count=lambda: None,
        append_message=lambda _: None,
        get_messages=lambda: [],
    )
    ctx = types.SimpleNamespace(
        config=types.SimpleNamespace(max_output=1000),
        evidence_log=types.SimpleNamespace(to_serializable=lambda: {"records": []}),
        todo_manager=types.SimpleNamespace(to_serializable=lambda: []),
        logger=types.SimpleNamespace(error=lambda *_: None),
        renderer=types.SimpleNamespace(stream_chunk=lambda *_: None, flush=lambda: None, think_end=lambda: None),
        session_manager=types.SimpleNamespace(messages=[], todos=[], evidence=[], save=lambda: None),
    )
    visualizer = types.SimpleNamespace(stop=lambda: None)
    monkeypatch.setattr(main.sys, "exit", lambda *_: None)
    monkeypatch.setattr(main.sys.stdout, "isatty", lambda: False)

    main._handle_one_shot_query(["hello"], state, ctx, visualizer, FakeLoop, RuntimeError)
    assert emitted == ["turn"]
