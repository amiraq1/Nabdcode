"""BRAND-4: tests for classic-default + clean prompt (no label, no toolbar).

ع1 header_classic_default   — draw() يحتوي █ و Repo:
ع2 no_user_label            — مصدر main.py + ui/theme.py لا يحتوي Ammar@NabdOS
ع3 no_bottom_toolbar        — main.py لا يمرر bottom_toolbar ولا خيط نبض/invalidate
ع4 protected_untouched      — البصمة ثابتة
"""
import importlib
import inspect
import io


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _capture_draw():
    """Run nabd_logo.draw() and return captured output (no Rich markup)."""
    from io import StringIO
    from rich.console import Console

    mod = importlib.import_module("nabd_logo")
    buf = StringIO()
    fake_console = Console(file=buf, force_terminal=False, color_system=None)
    orig = mod.console
    mod.console = fake_console
    try:
        mod.draw()
    finally:
        mod.console = orig
    return buf.getvalue()


# ---------------------------------------------------------------------------
# ع1 — draw() default is classic: contains █ and Repo:
# ---------------------------------------------------------------------------
def test_header_classic_default():
    out = _capture_draw()
    assert "█" in out, "draw() default must output ASCII blocks (█)"
    assert "Repo:" in out, "draw() default must output 'Repo:' metadata"


# ---------------------------------------------------------------------------
# ع2 — no Ammar@NabdOS label anywhere in prompt-building source
# ---------------------------------------------------------------------------
def test_no_user_label():
    main_src = inspect.getsource(importlib.import_module("main"))
    theme_src = inspect.getsource(importlib.import_module("ui.theme"))
    combined = main_src + theme_src
    assert "Ammar@NabdOS" not in combined, (
        "Prompt label 'Ammar@NabdOS' must be removed from main.py and ui/theme.py"
    )


# ---------------------------------------------------------------------------
# ع3 — no bottom_toolbar and no pulse thread / invalidate in main.py
# ---------------------------------------------------------------------------
def test_no_bottom_toolbar():
    src = inspect.getsource(importlib.import_module("main"))
    assert "bottom_toolbar" not in src, (
        "main.py must NOT pass bottom_toolbar to prompt()"
    )
    assert "_pulse_indicator" not in src, (
        "main.py must NOT contain the pulse indicator thread"
    )
    assert "invalidate" not in src, (
        "main.py must NOT call app.invalidate() (toolbar pulse removed)"
    )


# ---------------------------------------------------------------------------
# ع4 — protected files untouched (live checksum)
# ---------------------------------------------------------------------------
def test_protected_untouched():
    import hashlib, pathlib
    FINGERPRINTS = {
        "ui/widgets/status_bar.py": "42b5c014b36d6c18",
    }
    root = pathlib.Path(__file__).parent.parent
    for rel, expected in FINGERPRINTS.items():
        data = (root / rel).read_bytes()
        actual = hashlib.sha256(data).hexdigest()[:16]
        assert actual == expected, (
            f"HALT_FINGERPRINT: {rel} changed! expected {expected}, got {actual}"
        )
