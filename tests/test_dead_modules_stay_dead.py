"""Am+8 D-7c — two proven-dead modules must stay deleted.

core/output_renderer.py (77 lines, 4 raw-color violations, six render
functions) and ui/nabd_textual.py (12 raw-color violations, NabdTerminal +
launch_stream_tui) were removed after the D-7a census (89 -> 64) showed zero inbound
references: no import, no getattr, no string lookup, no dynamic access, no
reflection from any production module or test.

Each contract asserts BOTH that the file is absent and that importing the
module raises. The file check catches a re-added source file; the import
check catches a re-introduction under a different path that still resolves
to the same module name.
"""

import importlib
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_output_renderer_is_gone():
    """core/output_renderer.py had zero inbound references. It must not return."""
    path = REPO_ROOT / "core" / "output_renderer.py"
    assert not path.exists(), (
        "core/output_renderer.py was deleted in Am+8 D-7c (77 lines, 0 readers). "
        "Its ICE_BLUE constants duplicated SEMANTIC.action_badge."
    )
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("core.output_renderer")


def test_nabd_textual_is_gone():
    """ui/nabd_textual.py had zero inbound references. It must not return."""
    path = REPO_ROOT / "ui" / "nabd_textual.py"
    assert not path.exists(), (
        "ui/nabd_textual.py was deleted in Am+8 D-7c (12 raw colors, 0 readers). "
        "The live REPL surface is ui/repl_termux.py."
    )
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("ui.nabd_textual")


def test_live_owners_survive():
    """The live rendering surfaces must not be collateral damage of the excision."""
    for name in ("engine.renderer", "ui.repl_termux", "ui.theme"):
        assert importlib.import_module(name) is not None, (
            f"{name} is a live module and must survive the D-7c excision"
        )
