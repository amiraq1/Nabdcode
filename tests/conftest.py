"""Global test fixtures — tool registry isolation.

The ``engine.tool_registry.registry`` is a module-level singleton.
Tests that call ``registry.register(...)`` without cleanup leak tools
into later tests.  The ``_get_todo_manager()`` fallback in
``_ConvergenceMixin`` scans the registry for ``todo_write``, so a
leaked TodoWriteTool activates the convergence gate unexpectedly and
causes StopIteration in mocks that provide a fixed number of LLM
responses.

This conftest guarantees that every test session starts with the exact
same set of tools that were present at import-time (before any test
registered extra ones), and that any test-registered tools are removed
after each test function.
"""
import os

# Set this during collection, not only inside a fixture: some modules build
# runtime objects while pytest imports them, before autouse fixtures run.
os.environ.setdefault("NABD_NONINTERACTIVE", "1")

import pytest
from engine.tool_registry import registry


@pytest.fixture(autouse=True)
def _isolate_tool_registry():
    """Clear the global tool registry and pinned workspace root before every test.

    NBD-07: ``NABD_AUTO_APPROVE=1`` is set for the whole session so consent-gated
    tool paths run non-interactively. Tests that exercise the DENY path must
    inject a ``ConsentManager(prompt_func=...)`` (or unset the env var) — the
    product code no longer auto-approves based on a pytest-specific flag.
    """
    saved_tools = dict(registry._tools)
    registry._tools.clear()
    
    import core.kernel.security
    saved_root = core.kernel.security._WORKSPACE_ROOT
    core.kernel.security._WORKSPACE_ROOT = None
    
    saved_term = os.environ.get("TERM")
    os.environ["TERM"] = "xterm-256color"
    saved_approve = os.environ.get("NABD_AUTO_APPROVE")
    os.environ["NABD_AUTO_APPROVE"] = "1"
    saved_noninteractive = os.environ.get("NABD_NONINTERACTIVE")
    os.environ["NABD_NONINTERACTIVE"] = "1"
    
    yield
    
    if saved_term is None:
        del os.environ["TERM"]
    else:
        os.environ["TERM"] = saved_term
    if saved_approve is None:
        os.environ.pop("NABD_AUTO_APPROVE", None)
    else:
        os.environ["NABD_AUTO_APPROVE"] = saved_approve
    if saved_noninteractive is None:
        os.environ.pop("NABD_NONINTERACTIVE", None)
    else:
        os.environ["NABD_NONINTERACTIVE"] = saved_noninteractive
    
    registry._tools = saved_tools
    core.kernel.security._WORKSPACE_ROOT = saved_root
