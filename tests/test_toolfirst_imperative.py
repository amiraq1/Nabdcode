import pytest
from core.prompts import BASE_INSTRUCTIONS

def test_imperative_block():
    assert "TOOL RULE" in BASE_INSTRUCTIONS, "Missing TOOL RULE"
    assert "file_system READ" in BASE_INSTRUCTIONS, "Missing file_system READ in rule"

def test_arabic_mirror():
    assert "ممنوع «لا أستطيع»" in BASE_INSTRUCTIONS, "Missing Arabic mirror"

def test_no_bloat():
    # Previous length was roughly 5940, so we just check it hasn't exploded
    # Length of new addition is around 250 characters.
    assert len(BASE_INSTRUCTIONS) < 6400, f"Instructions too large: {len(BASE_INSTRUCTIONS)}"

def test_anchors_alive():
    assert "OUTPUT DISCIPLINE" in BASE_INSTRUCTIONS
    assert "Tool-first" in BASE_INSTRUCTIONS
    assert "SAME LANGUAGE" in BASE_INSTRUCTIONS
