import pytest
import main

def test_module_exposes_wire_events():
    from ui.event_wiring import wire_events
    assert callable(wire_events)

def test_alias_identity():
    import ui.event_wiring
    assert main.wire_events is ui.event_wiring.wire_events

def test_def_left_main():
    with open("main.py", "r") as f:
        content = f.read()
    assert "def wire_events" not in content

def test_timing_aliases_alive():
    assert callable(main._mark_step)
    assert callable(main._elapsed_for)
    main._mark_step("dummy_step")
    import time
    time.sleep(0.01)
    assert main._elapsed_for("dummy_step") > 0

def test_c1_behavior_preserved():
    with open("ui/event_wiring.py", "r") as f:
        content = f.read()
    assert "status_bar.wire()" in content
    assert "status_bar.start()" not in content
