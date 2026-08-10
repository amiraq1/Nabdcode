"""UI-CC-8: tests for compact-line deduplication."""
import importlib
import inspect
import sys
import types


# ---------------------------------------------------------------------------
# ع1 — identical suppressed
# ---------------------------------------------------------------------------
def test_identical_suppressed():
    from ui.cc_style import should_print_compact
    assert should_print_compact("X", "X") is False


# ---------------------------------------------------------------------------
# ع2 — different and first printed
# ---------------------------------------------------------------------------
def test_different_and_first_printed():
    from ui.cc_style import should_print_compact
    assert should_print_compact("A", "B") is True
    assert should_print_compact(None, "A") is True


# ---------------------------------------------------------------------------
# ع3 — repl uses dedup
# ---------------------------------------------------------------------------
def test_repl_uses_dedup():
    src = inspect.getsource(
        importlib.import_module("ui.repl_termux")
    )
    assert "should_print_compact" in src, (
        "ui/repl_termux.py must call should_print_compact"
    )
