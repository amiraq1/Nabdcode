import pytest
import core.prompts
import main

def test_section_e_exists():
    assert "OUTPUT DISCIPLINE" in core.prompts.BASE_INSTRUCTIONS

def test_no_worklog_rule():
    assert "WORK LOG" in core.prompts.BASE_INSTRUCTIONS
    assert "FINAL ANSWER" in core.prompts.BASE_INSTRUCTIONS

def test_bidi_rule():
    assert "backticks" in core.prompts.BASE_INSTRUCTIONS
    assert "own line" in core.prompts.BASE_INSTRUCTIONS

def test_length_rule():
    assert "12" in core.prompts.BASE_INSTRUCTIONS

def test_old_anchors_alive():
    assert "SAME LANGUAGE" in core.prompts.BASE_INSTRUCTIONS
    assert "BEHAVIOR:" in core.prompts.BASE_INSTRUCTIONS
    assert "لا أعرف" in core.prompts.BASE_INSTRUCTIONS
    assert "D) LANGUAGE & ACCURACY" in core.prompts.BASE_INSTRUCTIONS
    assert main.base_inst is core.prompts.BASE_INSTRUCTIONS
