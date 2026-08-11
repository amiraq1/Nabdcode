"""R-4.6 — one owner of live state.

engine/renderer.py keeps a live-status API (status_start / status_tick /
status_end) whose output lands in _live_buffer, which flush() never reads.
AgentStatusBar is the measured owner of what reaches the screen
(R-4.6.0: 'Step' is printed only by ui/widgets/status_bar.py:180).

These guards are deliberately structural: the law is a source-level law
("wire_events must not drive the renderer's live state"), not a pixel law.
A behavioural guard is recorded as debt, not faked here.
"""

import ast
import pathlib

FORBIDDEN = ("status_start", "status_tick", "status_end")


def _wire_events_node() -> ast.AST:
    src = pathlib.Path("ui/event_wiring.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "wire_events":
                return node
    raise AssertionError("wire_events not found in ui/event_wiring.py")


def test_the_guarded_names_still_exist_on_the_renderer() -> None:
    """A guard that watches names nobody has cannot fail. Prove they exist."""
    from engine.renderer import Renderer

    missing = sorted(n for n in FORBIDDEN if not hasattr(Renderer, n))
    assert not missing, f"guard drifted, Renderer lost: {missing}"


def test_wire_events_never_drives_renderer_live_state() -> None:
    offenders = []
    for node in ast.walk(_wire_events_node()):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in FORBIDDEN:
            base = func.value
            owner = base.id if isinstance(base, ast.Name) else getattr(base, "attr", "?")
            offenders.append(f"main.py:{node.lineno} {owner}.{func.attr}()")
    assert not offenders, (
        "wire_events must not drive the renderer's dead live state; "
        "AgentStatusBar owns it. Offenders: " + "; ".join(offenders)
    )
