"""tests/test_repl_safety_guards.py — V1+V2 safety contracts (ui/repl_termux.py).

V1: the re-entrancy guard ``_agent_busy`` must be ARMED around the
    agent.run execution and RELEASED in the finally of the same try that
    offloads it — success, failure, or cancellation alike.
V2: ``_process_pending_edits`` (which blocks on ``input()``) must be handed to
    ``asyncio.to_thread`` as a CALLABLE — never called eagerly on the loop
    thread, and never invoked synchronously — so the REPL keeps streaming
    while the user reviews pending edits.

V-BURY-1 (Am, 2026-08-09): the async REPL machinery that these contracts
guarded — ``run_repl`` (owner of the to_thread offloads, the _agent_busy
arming/release, and the _process_pending_edits hand-off) — was buried as a
dead cluster. The safety property these contracts enforced is therefore now
satisfied trivially and PROVABLY: the event-loop-blocking machinery no
longer exists in ui/repl_termux.py at all. These guards pin that absence so
a resurrected blocking REPL cannot return silently.

The live REPL (main.py ``_run_repl``) is synchronous and prompt-driven; it
never offloads agent.run to asyncio.to_thread inside this UI module.
"""

import ast
from pathlib import Path

_REPL_PATH = Path("ui/repl_termux.py")


def _repl_tree() -> ast.Module:
    assert _REPL_PATH.exists(), f"missing {_REPL_PATH}"
    return ast.parse(_REPL_PATH.read_text(encoding="utf-8"))


def _all_names(tree: ast.Module) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names


def test_run_repl_machinery_is_buried():
    """V-BURY-1: run_repl must NOT be defined in ui/repl_termux.py.

    The async REPL loop — the only place V1's _agent_busy arming and the
    to_thread(agent.run) offload lived — is gone.
    """
    assert "run_repl" not in _all_names(_repl_tree()), (
        "run_repl was buried with its helpers (V-BURY-1). A resurrected "
        "async REPL would reintroduce the V1/V2 event-loop hazards."
    )


def test_no_blocking_input_prompt_remains():
    """V2 intent: nothing in ui/repl_termux.py may block on input().

    The only input() call lived inside the buried _process_pending_edits.
    """
    tree = _repl_tree()
    blocking = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "input"
    ]
    assert not blocking, (
        f"blocking input() calls remain in ui/repl_termux.py at L{blocking} — "
        "the V2 hazard (blocking the loop while prompting) must stay buried."
    )


def test_no_asyncio_to_thread_offload_in_ui():
    """V1/V2 intent: the UI module must not offload agent work to threads.

    The to_thread offloads (agent.run, _maybe_auto_scan, _process_pending_edits)
    all lived inside the buried run_repl. With the cluster gone, the UI layer
    is a pure renderer (TerminalVisualizer) plus event handlers.
    """
    tree = _repl_tree()
    offloads = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "to_thread"
    ]
    assert not offloads, (
        f"asyncio.to_thread offloads remain in ui/repl_termux.py at L{offloads} — "
        "the V1/V2 thread-offload machinery must stay buried."
    )


def test_agent_busy_guard_machinery_is_buried():
    """V1 intent: the _agent_busy arming/release pair lived inside run_repl.

    With run_repl buried, no assignment to _agent_busy may remain (the guard
    was only meaningful around the to_thread(agent.run) execution).
    """
    tree = _repl_tree()
    assigns = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "_agent_busy" for t in n.targets)
    ]
    assert not assigns, (
        f"_agent_busy assignments remain at L{assigns} — the V1 re-entrancy "
        "guard was armed/released inside the buried run_repl only."
    )
