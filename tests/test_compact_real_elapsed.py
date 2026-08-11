"""UI-CC-9: elapsed حقيقي في السطر المضغوط — أحمر حتى يُنفَّذ §3."""
import time
import re
import inspect
import pytest
from unittest.mock import MagicMock

@pytest.fixture(autouse=True)
def _patch_console(monkeypatch):
    fake = MagicMock()
    import ui.repl_termux as r
    monkeypatch.setattr(r, "console", fake)
    yield fake

def _viz_class():
    import ui.repl_termux as r
    for _, obj in vars(r).items():
        if (inspect.isclass(obj) and obj.__module__ == r.__name__
                and hasattr(obj, "on_tool_started")):
            return obj
    raise AssertionError("لا فئة تحوي on_tool_started")

def _make_ui():
    cls = _viz_class()
    ui = cls.__new__(cls)
    ui._last_compact = None
    # تحييد دورة الحياة: الهدف منطق elapsed لا stop()/start()
    ui.stop = lambda *a, **k: None
    ui.start = lambda *a, **k: None
    return ui

def _llm_start(ui):
    cands = ["on_llm_started", "on_llm_request_started", "on_llm_start",
             "on_thinking", "on_step_started", "on_thought_started"]
    for c in cands:
        if hasattr(ui, c):
            return getattr(ui, c)
    ons = [m for m in dir(ui) if m.startswith("on_")]
    raise AssertionError(f"لا مرشح llm-start مطابق؛ المتاح: {ons}")

def test_elapsed_increases_with_time(_patch_console):
    ui = _make_ui()
    _llm_start(ui)({"step": 1})
    time.sleep(0.15)
    ui.on_tool_started({"step": 1, "tool": "read"})
    combined = " ".join(str(c) for c in _patch_console.print.call_args_list)
    nums = re.findall(r"\[([\d.]+)s\]", combined)
    assert nums, f"لم يُعثر على رقم elapsed في: {combined[:300]}"
    assert float(nums[-1]) >= 0.1, f"توقعت ≥0.1s، حصلت على {nums[-1]}s"

def test_elapsed_resets_per_step(_patch_console):
    ui = _make_ui()
    start = _llm_start(ui)
    start({"step": 1})
    time.sleep(0.05)
    ui.on_tool_started({"step": 1, "tool": "read"})
    start({"step": 2})
    time.sleep(0.12)
    ui.on_tool_started({"step": 2, "tool": "write"})
    combined = " ".join(str(c) for c in _patch_console.print.call_args_list)
    assert "Step 1" in combined or "step=1" in combined
    assert "Step 2" in combined or "step=2" in combined

def test_elapsed_appears_in_output(_patch_console):
    ui = _make_ui()
    _llm_start(ui)({"step": 1})
    time.sleep(0.05)
    ui.on_tool_started({"step": 1, "tool": "echo"})
    combined = " ".join(str(c) for c in _patch_console.print.call_args_list)
    nums = re.findall(r"\[([\d.]+)s\]", combined)
    assert nums, f"لا رقم عشري قبل s] في: {combined[:300]}"
