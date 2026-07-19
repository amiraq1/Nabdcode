# tests/test_code_intelligence.py
"""Unit tests for AST-based zero-dependency CodeIntelligenceTool."""

from pathlib import Path
import tempfile
import unittest

from tools.code_intelligence import CodeIntelligenceTool


class TestCodeIntelligenceTool(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp_dir.name)
        self.tool = CodeIntelligenceTool(workspace=self.workspace)

        # Create sample python files
        sample_code = (
            '"""Sample module docstring."""\n\n'
            'class Animal:\n'
            '    """Base class for animals."""\n'
            '    def __init__(self, name: str) -> None:\n'
            '        self.name = name\n\n'
            '    def speak(self) -> str:\n'
            '        """Make a noise."""\n'
            '        return "..."\n\n'
            'async def fetch_data(url: str, timeout: int = 10) -> dict:\n'
            '    """Fetch data asynchronously."""\n'
            '    return {}\n'
        )
        (self.workspace / "sample.py").write_text(sample_code, encoding="utf-8")

        nested_dir = self.workspace / "pkg"
        nested_dir.mkdir()
        (nested_dir / "utils.py").write_text(
            'def calculate(x: int, y: int) -> int:\n'
            '    """Return sum."""\n'
            '    return x + y\n',
            encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_list_symbols(self) -> None:
        res = self.tool.execute(action="list_symbols", path="sample.py")
        self.assertTrue(res.success, res.stderr)
        self.assertIn("class Animal (L3-L10) -- Base class for animals.", res.output)
        self.assertIn("def speak(self) (L8-L10) -- Make a noise.", res.output)
        self.assertIn("async def fetch_data(url: str, timeout: int) (L12-L14) -- Fetch data asynchronously.", res.output)

    def test_get_definition_class_method(self) -> None:
        res = self.tool.execute(action="get_definition", path=".", symbol="speak")
        self.assertTrue(res.success, res.stderr)
        self.assertIn("• [def] speak in sample.py (L8-L10)", res.output)
        self.assertIn("Docstring: Make a noise.", res.output)

    def test_get_definition_across_nested_dir(self) -> None:
        res = self.tool.execute(action="get_definition", path=".", symbol="calculate")
        self.assertTrue(res.success, res.stderr)
        self.assertIn("pkg/utils.py", res.output)
        self.assertIn("• [def] calculate", res.output)

    def test_get_definition_missing_symbol(self) -> None:
        res = self.tool.execute(action="get_definition", path=".", symbol="non_existent_func")
        self.assertTrue(res.success)
        self.assertIn("No definition found for symbol 'non_existent_func'", res.output)

    def test_invalid_action(self) -> None:
        res = self.tool.execute(action="invalid_action")
        self.assertFalse(res.success)
        self.assertIn("Invalid action", res.stderr)


if __name__ == "__main__":
    unittest.main()
