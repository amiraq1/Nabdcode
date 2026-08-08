"""Am+8 — token naming, ruling of 2026-08-06 10:08.

Human ruling (Am, 2026-08-06 10:08 - "وافقت"):
  error stays.  danger is deleted.  info and accent BOTH stay.
Reasoning (assistant, accepted by that ruling):
  - danger and error are one meaning with two names. They must never
    diverge; a guard forbids the dead spelling returning.
  - info and accent are TWO meanings that happen to share #6fd3d6
    today. They are allowed to diverge tomorrow. Nothing may pin
    them equal.

This guard asserts: danger is absent from the semantic theme and from
production; error / info / accent all exist; and info.hex == accent.hex
is deliberately NOT asserted — pinning two independent meanings to one
value is the defect this ruling exists to prevent.
"""

import pathlib

from ui.design.theme.semantic import SEMANTIC

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_PRODUCTION_DIRS = ("ui", "engine", "core", "tools")


def test_danger_token_is_absent():
    """danger is deleted; error is the single error-state name."""
    assert not hasattr(SEMANTIC, "danger"), (
        "SEMANTIC.danger was deleted by the 10:08 ruling; read SEMANTIC.error instead"
    )


def test_danger_spelling_absent_from_production():
    """No production module may reference the dead danger spelling."""
    offenders = []
    for base_name in _PRODUCTION_DIRS:
        for path in (REPO_ROOT / base_name).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if "SEMANTIC.danger" in line:
                    offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert not offenders, (
        "dead SEMANTIC.danger spelling referenced in production:\n"
        + "\n".join(offenders)
    )


def test_error_info_accent_all_exist():
    """The three surviving tokens are all present."""
    assert hasattr(SEMANTIC, "error"), "SEMANTIC.error must exist"
    assert hasattr(SEMANTIC, "info"), "SEMANTIC.info must exist"
    assert hasattr(SEMANTIC, "accent"), "SEMANTIC.accent must exist"


def test_info_and_accent_are_distinct_tokens():
    """info and accent are two distinct token objects, never aliased.

    Narrower than the ruling's intent on purpose: it asserts only what it
    can measure. The ban on pinning their values equal lives in the header
    above, unmeasured and labelled as such.
    """
    # Deliberately no assertion that info.hex == accent.hex. If a future
    # palette change gives them different values, that is allowed.
    assert SEMANTIC.info is not SEMANTIC.accent, (
        "info and accent must remain independent tokens"
    )
