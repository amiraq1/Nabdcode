"""
الحكم البشري النافذ: "2A" بتاريخ 2026-08-06، الساعة 13:14.
النص الحرفي: "2A = أظهروا الفعل. 3B = الأفعال بالعربية."
الموضع المقيس: ui/widgets/status_bar.py:167
"""
import pathlib

from ui.design.primitives.personality import style_of
from ui.design.state import UIState


def test_live_bar_speaks_ruled_verb_thinking():
    """ع1: الشريط في حالة التفكير يحتوي على الفعل 'يفكّر'."""
    style = style_of(UIState.THINKING)
    assert style.verb == "يفكّر", f"الفعل المتوقع 'يفكّر'، الموجود: {style.verb}"


def test_live_bar_speaks_ruled_verb_running():
    """ع2: الشريط في حالة التنفيذ يحتوي على الفعل 'يُنفّذ'."""
    style = style_of(UIState.RUNNING)
    assert style.verb == "يُنفّذ", f"الفعل المتوقع 'يُنفّذ'، الموجود: {style.verb}"


def test_no_hide_verb_in_status_bar():
    """ع3: لا يبقى في ui/widgets/status_bar.py أي hide_verb=True."""
    source = pathlib.Path('ui/widgets/status_bar.py').read_text()
    assert "hide_verb=True" not in source, "hide_verb=True لا يزال موجوداً في status_bar.py"


def test_verb_does_not_break_width():
    """ع4: الأفعال لا تُكسر: cell_len للسطر المصيَّر لا يتجاوز 80."""
    from rich.cells import cell_len
    from ui.design.primitives.status_line import StatusLine

    # قياس السطر الحقيقي الذي يرسمه StatusLine (لا سلسلة مصطنعة)
    line = StatusLine(UIState.THINKING, context="Thinking", hide_verb=False)._line()
    width = cell_len(str(line))
    assert width <= 80, f"عرض السطر {width} يتجاوز 80"
