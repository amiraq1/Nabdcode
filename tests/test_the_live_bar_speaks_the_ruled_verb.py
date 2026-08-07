"""
الحكم البشري النافذ: "2A" بتاريخ 2026-08-06، الساعة 13:14.
النص الحرفي: "2A = أظهروا الفعل. 3B = الأفعال بالعربية."
الموضع المقيس: ui/widgets/status_bar.py:167

تصحيح الحارس الكاذب (a93a462): العقود القديمة (ع1/ع2/ع4) كانت تفحص
personality.py وStatusLine المُنشأة يدوياً — لا الشريط الحقيقي. العقد
الحقيقي الوحيد كان grep على نص الملف (ع3).

البديل الجديد: يُصيّر _build_renderable فعلياً عبر Console(record=True)
ويبحث عن الأفعال العربية في النص المصيَّر. هذا هو المصباح نفسه — إن لم
يظهر الفعل هنا، فلم يظهر على شاشتك.
"""
import pathlib

from ui.widgets.status_bar import AgentStatusBar
from tests.support.render import render_to_text, strip_ansi


def _render(b: AgentStatusBar, width: int = 80) -> str:
    """Render the actual status bar and return the exported text.

    Goes through tests/support/render.py (make_console path) which pins BOTH
    width and height — required by test_no_unpinned_console_in_tests.
    """
    return render_to_text(b._build_renderable(), width=width, height=25)


def test_rendered_bar_contains_thinking_verb():
    """المصباح: الشريط المصيَّر في حالة التفكير يحتوي على 'يفكّر'."""
    b = AgentStatusBar()
    b.set_active("Thinking")
    text = _render(b)
    assert "يفكّر" in text, f"الشريط المصيَّر لا يحتوي على 'يفكّر':\n{text}"


def test_rendered_bar_contains_running_verb():
    """المصباح: الشريط المصيَّر في حالة التنفيذ يحتوي على 'يُنفّذ'."""
    b = AgentStatusBar()
    b.set_active("Running Tools")
    text = _render(b)
    assert "يُنفّذ" in text, f"الشريط المصيَّر لا يحتوي على 'يُنفّذ':\n{text}"


def test_no_hide_verb_in_status_bar():
    """ع3 (أصيل): لا يبقى في ui/widgets/status_bar.py أي hide_verb=True."""
    source = pathlib.Path('ui/widgets/status_bar.py').read_text()
    assert "hide_verb=True" not in source, "hide_verb=True لا يزال موجوداً في status_bar.py"


def test_rendered_bar_fits_width():
    """المصباح: كل سطر في الشريط المصيَّر لا يتجاوز العرض المحدد."""
    from rich.cells import cell_len
    for width in (40, 60, 80):
        b = AgentStatusBar()
        b.set_active("Thinking")
        text = _render(b, width)
        for ln in strip_ansi(text).split("\n"):
            assert cell_len(ln) <= width, (
                f"عند w={width} سطر عرضه {cell_len(ln)}: {ln!r}"
            )
