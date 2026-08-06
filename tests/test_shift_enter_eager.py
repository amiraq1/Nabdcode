"""
Guards: CSI Shift+Enter binding must use eager=True to win over the
prompt_toolkit internal ControlM submit binding.

These guards were failing because the ControlM binding in
create_shift_enter_keybindings lacked eager=True, allowing PTK's internal
binding to intercept before the custom handler could check key data.
"""
import ast
import pathlib

from prompt_toolkit import PromptSession
from prompt_toolkit.filters import Condition
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys

from ui.keybindings import create_shift_enter_keybindings

_KITTY = chr(27) + "[13;2u"
_CSI = chr(27) + "[27;2;13~"


def _shift_enter_only(nav_enabled: bool):
    return create_shift_enter_keybindings(navigation_enabled=lambda: nav_enabled)


def _prompt(feed: str, bindings) -> str:
    with create_pipe_input() as inp:
        inp.send_text(feed)
        session = PromptSession(input=inp, history=None, key_bindings=bindings)
        return session.prompt()


def test_csi_shift_enter_inserts_newline_not_submit():
    """The XTerm CSI form must insert a newline; only a real Enter submits.

    Requires eager=True on the ControlM binding so the custom handler wins
    over PTK's internal submit binding.
    """
    result = _prompt(f"hello{_CSI}world\r", _shift_enter_only(False))
    assert result == "hello\nworld", (
        f"CSI Shift+Enter did not insert newline; got {result!r}. "
        "Likely missing eager=True on ControlM binding."
    )


def test_both_encodings_mix_into_one_multiline_input():
    """Both kitty and CSI encodings must accumulate into a single multi-line input."""
    result = _prompt(f"a{_KITTY}b{_CSI}c\r", _shift_enter_only(False))
    assert result == "a\nb\nc", (
        f"Mixed encodings did not accumulate; got {result!r}. "
        "Likely missing eager=True on ControlM binding."
    )


def test_csi_binding_has_eager_flag():
    """AST guard: the ControlM binding must declare eager=True.

    This is the structural guarantee that prevents regression without
    running a full prompt_toolkit session.
    """
    src = pathlib.Path("ui/keybindings.py").read_text()
    tree = ast.parse(src)

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name != "create_shift_enter_keybindings":
            continue
        # Look for bindings.add(Keys.ControlM, ..., eager=True)
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            func = child.func
            if not (isinstance(func, ast.Attribute) and func.attr == "add"):
                continue
            # Check if eager=True keyword is present
            for kw in child.keywords:
                if kw.arg == "eager" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    return  # Found it — pass
        # Fell through without finding eager=True
        raise AssertionError(
            "create_shift_enter_keybindings ControlM binding lacks eager=True"
        )
