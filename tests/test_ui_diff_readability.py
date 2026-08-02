"""V-02 readability tests for ui/widgets/diff_render.py (no monkeypatch).

Calls the REAL Rich word-diff renderer. Lifecycle/perf/engine logic is NOT
touched — scope is display-only word-diff readability.
"""
import unittest

from ui.widgets.diff_render import render_edit_diff


class TestDiffReadability(unittest.TestCase):

    def test_empty_input(self):
        self.assertEqual(render_edit_diff(""), "")

    def test_simple_diff_word_diff_intact(self):
        # Simple edit -> word-diff highlighting must be preserved.
        d = render_edit_diff(
            "-def foo(self, x):\n"
            "+def foo(self, y):"
        )
        self.assertIn("[bold", d)  # changed word painted
        self.assertNotIn("[bold red][/bold red]", d)
        self.assertNotIn("[bold green][/bold green]", d)

    def test_min_match_drops_single_char_run(self):
        # A 1-char run (below min_match_len=3) stays plain, not highlighted.
        d = render_edit_diff("-x\n+y")
        self.assertNotIn("[bold", d)
        self.assertIn("[red]-x[/red]", d)
        self.assertIn("[green]+y[/green]", d)

    def test_high_churn_diff_falls_back_to_line_diff(self):
        # Multi-island, high-churn line -> scatter fallback to whole-line diff,
        # so the output is NOT a pile of fragmented word marks.
        d = render_edit_diff(
            "-old_val = compute(a, b, c)\n"
            "+new_val = compute(c, b, a)"
        )
        self.assertNotIn("[bold", d)            # no fragmented word markup
        self.assertIn("[red]-old_val", d)       # whole-line diff kept
        self.assertIn("[green]+new_val", d)

    def test_no_empty_markup_anywhere(self):
        for d in (
            "-def foo(self, x):\n+def foo(self, y):",
            "-old_val = compute(a, b, c)\n+new_val = compute(c, b, a)",
            "-x\n+y",
            "-only deleted\n+only added",
        ):
            out = render_edit_diff(d)
            self.assertNotIn("[bold red][/bold red]", out)
            self.assertNotIn("[bold green][/bold green]", out)

    def test_unchanged_lines_dimmed(self):
        d = render_edit_diff("@@ -1 +1 @@\n context line")
        self.assertIn("[dim] context line[/dim]", d)


if __name__ == "__main__":
    unittest.main()
