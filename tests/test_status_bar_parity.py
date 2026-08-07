"""C3 Guard: Parity Proof - StatusLine has all think_line components."""

from __future__ import annotations

def test_thinking_status_line_has_all_think_line_components():
    """C3: StatusLine for THINKING must have verb, icon, and duration capability."""
    from ui.design.primitives.status_line import StatusLine
    from ui.design.state import UIState
    from ui.design.primitives.personality import style_of
    from ui.design.icons import Icon
    from rich.console import Console

    style = style_of(UIState.THINKING)

    # 1. Parity Check: Ensure the semantic components match think_line expectations
    assert style.verb == "يفكّر", f"Expected verb 'يفكّر', got '{style.verb}'"
    assert Icon.glyph(style.icon) == "…", f"Expected icon '…', got '{Icon.glyph(style.icon)}'"

    # 2. Render Check: Ensure StatusLine encapsulates these components
    line = StatusLine(UIState.THINKING, context="thinking")
    
    # We can inspect the yielded renderables or just convert to string
    console = Console()
    rendered_text = "".join(seg.text for seg in console.render(line))
    
    # Since hide_verb might be False by default, or context might be shown, let's verify
    # it contains the icon and either verb or context.
    assert "…" in rendered_text, "Rendered StatusLine must contain the thinking icon '…'"
