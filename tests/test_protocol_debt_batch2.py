"""Guard: Batch 2 protocol debt — _BADGE_STYLES must use semantic tokens.

verify_protocol.sh flags raw hex in tracked *.py files. Batch 2 replaced the
7 raw hex badge colors in _BADGE_STYLES (repl_termux.py) with SEMANTIC tokens
from ui/design/theme/semantic.py (shell/search/git/kill added there), and
removed the raw-hex color mapping comments above it.

This guard pins the fix by walking the AST: the _BADGE_STYLES dict values and
the surrounding comment block must contain no raw hex literals.
"""

import ast
import pathlib
import re

HEX_RE = re.compile(r"#[0-9a-fA-F]{6}")

TARGET = "ui/repl_termux.py"


def _find_badge_styles(source: str) -> ast.Dict:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "_BADGE_STYLES":
                if isinstance(node.value, ast.Dict):
                    return node.value
    raise AssertionError("_BADGE_STYLES dict not found in ui/repl_termux.py")


def test_badge_styles_use_semantic_tokens():
    source = pathlib.Path(TARGET).read_text()
    badge = _find_badge_styles(source)

    for value in badge.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            assert not HEX_RE.search(value.value), (
                f"_BADGE_STYLES value still has raw hex: {value.value!r}"
            )

    # Values should reference SEMANTIC.* tokens.
    for value in badge.values:
        text = ast.get_source_segment(source, value) or ""
        assert "SEMANTIC." in text, (
            f"_BADGE_STYLES value does not use a semantic token: {text!r}"
        )


def test_badge_comment_block_has_no_raw_hex():
    """The color-mapping comment above _BADGE_STYLES must stay hex-free."""
    source = pathlib.Path(TARGET).read_text()
    # Lines immediately preceding the dict assignment.
    idx = source.index("_BADGE_STYLES:")
    prefix = source[:idx]
    block = prefix.split("\n")[-8:]
    for line in block:
        assert not HEX_RE.search(line), (
            f"comment block near _BADGE_STYLES still has raw hex: {line.strip()!r}"
        )
