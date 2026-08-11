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
import pytest
from engine.tool_registry import registry


@pytest.fixture(autouse=True)
def _isolate_tool_registry():
    """Clear the global tool registry and pinned workspace root before every test."""
    saved_tools = dict(registry._tools)
    registry._tools.clear()
    
    import core.kernel.security
    saved_root = core.kernel.security._WORKSPACE_ROOT
    core.kernel.security._WORKSPACE_ROOT = None
    
    import os
    saved_term = os.environ.get("TERM")
    os.environ["TERM"] = "xterm-256color"
    
    yield
    
    if saved_term is None:
        del os.environ["TERM"]
    else:
        os.environ["TERM"] = saved_term
    
    registry._tools = saved_tools
    core.kernel.security._WORKSPACE_ROOT = saved_root
