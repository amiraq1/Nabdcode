"""
Guard: P['think'] must be removed after W-1 wiring.

Red on current state (P['think'] still in palette),
green after the atomic deletion in Phase 3.
"""


def test_think_palette_key_is_dead():
    """P['think'] must be removed after W-1 wiring."""
    from engine.ui_theme import P
    assert 'think' not in P, "P['think'] is still present — dead key not removed"
