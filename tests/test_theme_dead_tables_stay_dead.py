"""Am+8 D-7a — the two dead color tables must stay dead, the live ones alive.

COLORS and ACTION_COLORS were deleted after measurement showed zero code
readers: their only mentions in the tree were two test docstrings, one of
which states ACTION_COLORS is superseded by the D-1 atoms.

These are attribute assertions, not text greps. A re-introduction under any
spelling, indentation, or import alias rebinds the module attribute and is
caught here; a text grep can miss it.
"""

import ui.theme


def test_colors_table_is_gone():
    """COLORS had 19 raw-color lines and zero code readers. It must not return."""
    assert not hasattr(ui.theme, "COLORS"), (
        "ui.theme.COLORS was deleted in Am+8 D-7a (19 raw colors, 0 readers). "
        "Re-introducing it re-opens the ownership debt it was removed to close."
    )


def test_action_colors_table_is_gone():
    """ACTION_COLORS had 6 raw-color lines and zero code readers. It must not return."""
    assert not hasattr(ui.theme, "ACTION_COLORS"), (
        "ui.theme.ACTION_COLORS was deleted in Am+8 D-7a (6 raw colors, 0 readers). "
        "Badge color resolves via Badge meaning -> SEMANTIC, not a hardcoded palette."
    )


def test_live_owners_survive():
    """The measured-live owners must not be collateral damage of the deletion."""
    for name in ("SELECTED_COLOR", "FOOTER_COLOR", "PALETTE", "CUSTOM_THEME",
                 "nabd_theme", "PANEL_STYLES", "PROMPT_STYLE"):
        assert hasattr(ui.theme, name), f"ui.theme.{name} is live and must survive"
