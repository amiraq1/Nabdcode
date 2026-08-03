import subprocess

import pytest


FORBIDDEN = ("commandcode", "noreply@commandcode.ai", "CommandCodeBot")


def _find_forbidden(message: str) -> list[str]:
    return [token for token in FORBIDDEN if token in message]


def test_detector_catches_known_bad_trailer():
    message = "feat: x\n\nCo-authored-by: CommandCodeBot<noreply@commandcode.ai>"
    assert _find_forbidden(message)


def test_branch_history_has_no_foreign_provenance():
    try:
        result = subprocess.run(
            ["git", "log", "--format=%B", "origin/main..HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"origin/main history unavailable: {exc}")

    assert not _find_forbidden(result.stdout)
