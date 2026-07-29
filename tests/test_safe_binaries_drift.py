from __future__ import annotations
import ast, unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

def _extract_set_literal(source_path, var_name):
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == var_name and node.value:
                return ast.unparse(node.value)
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == var_name:
                return ast.unparse(node.value)
    return ""

class TestSafeBinariesDriftAlarm(unittest.TestCase):
    def test_safe_binaries_identical_between_security_and_constants(self):
        sec_val = _extract_set_literal(_ROOT / "core" / "kernel" / "security.py", "SAFE_BINARIES")
        const_val = _extract_set_literal(_ROOT / "core" / "constants.py", "SAFE_BINARIES")
        assert sec_val, "SAFE_BINARIES not found in core/kernel/security.py"
        assert const_val, "SAFE_BINARIES not found in core/constants.py"
        assert sec_val == const_val, f"D-14 DRIFT: SAFE_BINARIES diverged! kernel={sec_val} constants={const_val}"
