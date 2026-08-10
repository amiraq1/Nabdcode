"""tests/test_prompt_leak_redaction.py — SEC-4: redact leaked prompt previews.

Red-guard tests verifying that prompt-leak previews never reach the
user-facing error surface — only a redacted signal with a char count does.
"""

from __future__ import annotations

from pathlib import Path

from engine._loop_helpers import redact_leak_preview

LOOP = Path(__file__).resolve().parent.parent / "engine" / "loop.py"


# ── ع1: redaction_strips_system_markers ─────────────────────────────────────

def test_redaction_strips_system_markers() -> None:
    preview = "<system_instructions> TODO Discipline </system_instructions> secret stuff"
    out = redact_leak_preview(preview)
    assert "<system_instructions>" not in out
    assert "TODO Discipline" not in out
    assert "secret stuff" not in out


# ── ع2: redaction_keeps_operator_signal ─────────────────────────────────────

def test_redaction_keeps_operator_signal() -> None:
    out = redact_leak_preview("<system> leak </system>")
    assert "Prompt Leak detected" in out
    assert "[content redacted" in out
    # The char count is included so the operator knows the magnitude.
    import re
    assert re.search(r"\d+ chars", out)


# ── ع3: leak_sites_use_redaction ────────────────────────────────────────────

def test_leak_sites_use_redaction() -> None:
    """Both leak sites must call redact_leak_preview, not raw f-strings."""
    source = LOOP.read_text(encoding="utf-8")
    assert "redact_leak_preview(leak_preview)" in source
    # No raw f-string interpolation of leak_preview remains.
    assert 'f"Prompt Leak detected: {leak_preview}"' not in source
    # Both sites use the redaction call.
    assert source.count("redact_leak_preview(leak_preview)") == 2


# ── ع4: terminate_behavior_unchanged ────────────────────────────────────────

def test_terminate_behavior_unchanged() -> None:
    """The leak path still routes through _note_provider_failure inside a
    TERMINATE check — the control flow is unchanged."""
    source = LOOP.read_text(encoding="utf-8")
    expected = (
        'if self._note_provider_failure(redact_leak_preview(leak_preview)) '
        'is _LoopSignal.TERMINATE:'
    )
    assert source.count(expected) == 2
