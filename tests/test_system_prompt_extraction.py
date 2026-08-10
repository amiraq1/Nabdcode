import pytest
import importlib
from pathlib import Path
import main

def test_a1_identity():
    import core.prompts as prompts
    assert hasattr(prompts, "BASE_INSTRUCTIONS")
    assert main.base_inst is prompts.BASE_INSTRUCTIONS

def test_a2_anchors():
    import core.prompts as prompts
    assert hasattr(prompts, "BASE_INSTRUCTIONS")
    BASE_INSTRUCTIONS = prompts.BASE_INSTRUCTIONS
    assert "SAME LANGUAGE" in BASE_INSTRUCTIONS
    assert "BEHAVIOR:" in BASE_INSTRUCTIONS
    assert "لا أعرف" in BASE_INSTRUCTIONS
    assert "Python" in BASE_INSTRUCTIONS
    assert "CLASSIFY" in BASE_INSTRUCTIONS or "classification" in BASE_INSTRUCTIONS.lower()

def test_a3_source_relocation():
    source = Path("main.py").read_text(encoding="utf-8")
    assert "D) LANGUAGE & ACCURACY" not in source
    assert "base_inst" in source

def test_a4_import_compatibility():
    # If the import above succeeded, this is basically a no-op that passes
    importlib.reload(main)
    assert True
