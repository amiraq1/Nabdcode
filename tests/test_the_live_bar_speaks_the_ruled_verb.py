"""
الحكم البشري النافذ: "2A" بتاريخ 2026-08-06، الساعة 13:14.
النص الحرفي: "2A = أظهروا الفعل. 3B = الأفعال بالعربية."
الموضع المقيس: ui/widgets/status_bar.py:167

R-2B: العقد يشهد على مقطعه. الحارس السابق كان يقرأ الصندوق كله، فيقبل
شهادة مرحلة عن مرحلة أخرى ('يفكّر' من Generating تشهد لـ Thinking).

القياس في §2 (هذه الجلسة):
- عند w=80 كل المراحل في سطر واحد، الفاصل الحرفي بينها هو ' → '
  (من Text(" → ", style=...) في status_bar.py:170).
- عند active="Running Tools": '✓ تمّ Thinking → ▶ يُنفّذ Running Tools → … يفكّر Generating'
- الحالة: Thinking=done, Running Tools=active, Generating=pending.

العقد المقطعيّ: يستخرج مقطع كل مرحلة بالتقطيع على الفاصل ' → '
ويتحقق أن فعل المرحلة يظهر في مقطعها لا في مقطع غيرها.
"""
import pathlib

from ui.widgets.status_bar import AgentStatusBar
from tests.support.render import render_to_text, strip_ansi

SEP = " → "


def _render(b: AgentStatusBar, width: int = 80) -> str:
    """Render the actual status bar and return the ANSI-stripped text.

    Goes through tests/support/render.py (make_console path) which pins BOTH
    width and height — required by test_no_unpinned_console_in_tests.
    """
    return strip_ansi(render_to_text(b._build_renderable(), width=width, height=25))


def _segments(text: str) -> dict[str, str]:
    """Split the rendered bar into per-phase segments.

    At w=80 all phases sit on one line, separated by the literal ' → '
    separator. Each segment runs from after the previous separator (or line
    start) up to the next separator (or line end), so it includes the icon
    and verb that precede the phase label — and stops BEFORE the next
    separator, so it never borrows the neighbor's icon/verb.
    """
    line = next((ln for ln in text.split("\n") if "Thinking" in ln), "")
    # Separator positions (index of ' → ').
    seps: list[int] = []
    idx = line.find(SEP)
    while idx != -1:
        seps.append(idx)
        idx = line.find(SEP, idx + len(SEP))
    # Phase label positions.
    phases = ("Thinking", "Running Tools", "Generating")
    phase_pos = {ph: line.find(ph) for ph in phases if line.find(ph) != -1}
    # Segment boundaries: line start, each separator, line end.
    bounds = [0] + seps + [len(line)]
    segs: dict[str, str] = {}
    for ph, pos in phase_pos.items():
        # The segment containing this phase runs from the last boundary before
        # it to the next boundary.
        start = max(b for b in bounds if b <= pos)
        end = min(b for b in bounds if b > pos)
        segs[ph] = line[start:end].strip().strip(SEP).strip()
    return segs


def test_rendered_bar_contains_thinking_verb_in_own_segment():
    """ع1: عند active=Thinking، مقطع Thinking يحتوي 'يفكّر'."""
    b = AgentStatusBar()
    b.set_active("Thinking")
    segs = _segments(_render(b, 80))
    assert "يفكّر" in segs["Thinking"], (
        f"مقطع Thinking لا يحتوي 'يفكّر': {segs['Thinking']!r}\nall={segs}"
    )


def test_rendered_bar_contains_running_verb_in_own_segment():
    """ع2: عند active=Running Tools، مقطع Running Tools يحتوي 'يُنفّذ'."""
    b = AgentStatusBar()
    b.set_active("Running Tools")
    segs = _segments(_render(b, 80))
    assert "يُنفّذ" in segs["Running Tools"], (
        f"مقطع Running Tools لا يحتوي 'يُنفّذ': {segs['Running Tools']!r}\nall={segs}"
    )


def test_segments_do_not_borrow_verbs():
    """ع3 (تمييز): مقطع كل مرحلة لا يستعير فعل مرحلة أخرى.

    عند active=Running Tools:
    - مقطع Thinking لا يحتوي 'يُنفّذ' (لأنها done → تمّ)
    - مقطع Running Tools لا يحتوي 'تمّ' (لأنها active → يُنفّذ)
    """
    b = AgentStatusBar()
    b.set_active("Running Tools")
    segs = _segments(_render(b, 80))
    assert "يُنفّذ" not in segs["Thinking"], (
        f"مقطع Thinking يستعير 'يُنفّذ': {segs['Thinking']!r}"
    )
    assert "تمّ" not in segs["Running Tools"], (
        f"مقطع Running Tools يستعير 'تمّ': {segs['Running Tools']!r}"
    )


def test_no_hide_verb_in_status_bar():
    """ع3 (أصيل): لا يبقى في ui/widgets/status_bar.py أي hide_verb=True."""
    source = pathlib.Path('ui/widgets/status_bar.py').read_text()
    assert "hide_verb=True" not in source, "hide_verb=True لا يزال موجوداً في status_bar.py"


def test_rendered_bar_fits_width():
    """ع4: كل سطر في الشريط المصيَّر لا يتجاوز العرض المحدد."""
    from rich.cells import cell_len
    for width in (40, 60, 80):
        b = AgentStatusBar()
        b.set_active("Thinking")
        text = _render(b, width)
        for ln in text.split("\n"):
            assert cell_len(ln) <= width, (
                f"عند w={width} سطر عرضه {cell_len(ln)}: {ln!r}"
            )
