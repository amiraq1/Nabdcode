import main
import core.prompts as prompts
from pathlib import Path

def test_a1_identity():
    assert main.base_inst is prompts.BASE_INSTRUCTIONS

def test_a2_anchors():
    assert "SAME LANGUAGE" in prompts.BASE_INSTRUCTIONS

def test_a3_behavior():
    assert "BEHAVIOR:" in prompts.BASE_INSTRUCTIONS

def test_a4_fabrication():
    assert "لا أعرف" in prompts.BASE_INSTRUCTIONS

def test_a5_spelling():
    assert "Python" in prompts.BASE_INSTRUCTIONS

def test_a6_classification():
    assert "CLASSIFY" in prompts.BASE_INSTRUCTIONS or "CLASSIFICATION" in prompts.BASE_INSTRUCTIONS

def test_a7_language_section():
    assert "D) LANGUAGE & ACCURACY" in prompts.BASE_INSTRUCTIONS

def test_a8_source_relocated():
    assert "D) LANGUAGE & ACCURACY" not in Path("main.py").read_text(encoding="utf-8")

def test_a9_global_alias():
    assert main.base_inst is prompts.BASE_INSTRUCTIONS

def test_a10_import_identity():
    import core.prompts
    assert core.prompts is prompts
