"""tests/test_repl_safety_guards.py — V1+V2 safety contracts (ui/repl_termux.py).

V1: the re-entrancy guard ``_agent_busy`` must actually be ARMED around the
    agent.run execution and RELEASED in the finally of the same try that
    offloads it — success, failure, or cancellation alike.
V2: ``_process_pending_edits`` (which blocks on ``input()``) must be handed to
    ``asyncio.to_thread`` as a CALLABLE — never called eagerly on the loop
    thread, and never invoked synchronously — so the REPL keeps streaming
    while the user reviews pending edits.
"""

import ast
from pathlib import Path

_REPL_PATH = Path("ui/repl_termux.py")


def _repl_tree() -> ast.Module:
    assert _REPL_PATH.exists(), f"missing {_REPL_PATH}"
    return ast.parse(_REPL_PATH.read_text(encoding="utf-8"))


def _parent_map(tree: ast.Module):
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _agent_exec_try(tree: ast.Module):
    """The INNERMOST Try enclosing the asyncio.to_thread(agent.run/...) call
    (the outer REPL loop try also contains it deep in its body — the parent
    walk up to the first Try is what disambiguates)."""
    parents = _parent_map(tree)
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "to_thread"
        ):
            continue
        if not any(
            (isinstance(a, ast.Attribute) and a.attr == "run")
            or (isinstance(a, ast.Name) and a.id == "agent_runner_func")
            for a in node.args
        ):
            continue
        cur = node
        while cur in parents:
            cur = parents[cur]
            if isinstance(cur, ast.Try):
                return cur
    return None


def _is_busy_assign(node: ast.stmt, value: bool) -> bool:
    return (
        isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "_agent_busy" for t in node.targets
        )
        and isinstance(node.value, ast.Constant)
        and node.value.value is value
    )


def test_agent_busy_guard_is_armed_during_execution():
    """V1: _agent_busy must be assigned True before agent.run executes."""
    tree = _repl_tree()
    armed = any(_is_busy_assign(n, True) for n in ast.walk(tree))
    assert armed, "V1 dead guard: _agent_busy is never assigned True"


def test_agent_busy_guard_is_released_in_agent_exec_finally():
    """V1: _agent_busy must be reset False in the finally of the very try
    that offloads agent.run."""
    tree = _repl_tree()
    exec_try = _agent_exec_try(tree)
    assert exec_try is not None, "agent.run execution try block not found"
    released = any(_is_busy_assign(n, False) for n in exec_try.finalbody)
    assert released, (
        "V1 dead guard: no _agent_busy = False in the agent execution finally"
    )


def test_pending_edits_are_prompted_off_the_event_loop():
    """V2: _process_pending_edits must be handed to asyncio.to_thread as a
    callable (Name), never called eagerly (which would block the loop) and
    never invoked synchronously."""
    tree = _repl_tree()
    handed_off = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "to_thread"
        and any(
            isinstance(a, ast.Name) and a.id == "_process_pending_edits"
            for a in n.args
        )
    ]
    assert handed_off, (
        "V2 blocking: _process_pending_edits is not handed to asyncio.to_thread"
    )
    eager_calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "_process_pending_edits"
    ]
    assert not eager_calls, (
        "V2 blocking: _process_pending_edits is called eagerly/synchronously"
    )
