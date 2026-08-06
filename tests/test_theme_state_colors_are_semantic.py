"""D-7b: state colors in ui/theme.py are owned by the semantic layer.

Human ruling (Am, 2026-08-06 10:08 — "وافقت"), quoted verbatim:
  error stays.  danger is deleted.  info and accent BOTH stay.
Reasoning (assistant, accepted by that ruling):
  - danger and error are one meaning with two names. They must never
    diverge; a guard forbids the dead spelling returning.
  - info and accent are TWO meanings that happen to share #6fd3d6
    today. They are allowed to diverge tomorrow. Nothing may pin
    them equal.

This guard pins PALETTE's state keys to the semantic tokens the ruling
names: error -> SEMANTIC.error, info -> SEMANTIC.info, danger absent.
"""
import pathlib
import unittest

from ui.design.theme.semantic import SEMANTIC
from ui.theme import PALETTE

_THEME_SRC = pathlib.Path(__file__).resolve().parents[1] / "ui" / "theme.py"


class ThemeStateColorsAreSemantic(unittest.TestCase):
    def test_state_keys_resolve_to_semantic(self):
        self.assertEqual(PALETTE["success"], SEMANTIC.success.hex)
        self.assertEqual(PALETTE["error"], SEMANTIC.error.hex)
        self.assertEqual(PALETTE["warning"], SEMANTIC.warning.hex)
        self.assertEqual(PALETTE["info"], SEMANTIC.info.hex)

    def test_retired_error_spelling_is_absent(self):
        self.assertNotIn("#ff3333", _THEME_SRC.read_text())

    def test_brand_spellings_are_not_migrated(self):
        self.assertEqual(PALETTE["neon_green"], "#00ff9d")
        self.assertEqual(PALETTE["neon_cyan"], "#00fff7")


if __name__ == "__main__":
    unittest.main()
