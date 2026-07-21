"""Test the deep repository scanner."""

from __future__ import annotations

from pathlib import Path

from core.repo_scanner import SECURE_REPO_SCANNER, deep_scan_repo


def test_deep_scan_returns_dict() -> None:
    """_deep_scan returns a dict with expected keys."""
    result = SECURE_REPO_SCANNER()._deep_scan(Path("."))
    assert isinstance(result, dict)
    assert "build_system" in result
    assert "layers" in result
    assert "entry_points" in result
    assert "metrics" in result
    assert "security" in result


def test_detects_build_system() -> None:
    """pyproject.toml has setuptools."""
    result = SECURE_REPO_SCANNER()._deep_scan(Path("."))
    bs = result["build_system"]
    assert bs["type"] == "setuptools" or bs["type"] == "python"


def test_detects_layers() -> None:
    """At least 3 layer directories."""
    result = SECURE_REPO_SCANNER()._deep_scan(Path("."))
    assert len(result["layers"]) >= 3


def test_metrics_positive() -> None:
    """Metrics have positive values."""
    result = SECURE_REPO_SCANNER()._deep_scan(Path("."))
    assert result["metrics"]["py_files"] > 10
    assert result["metrics"]["total_lines"] > 1000


def test_deep_action_roundtrip() -> None:
    """forward(action='deep') returns JSON-parseable output with the keys."""
    import json

    out = SECURE_REPO_SCANNER().forward(action="deep")
    data = json.loads(out)
    assert "metrics" in data and data["metrics"]["py_files"] > 0


def test_module_helper_matches_method() -> None:
    """deep_scan_repo free function mirrors the bound method output."""
    a = deep_scan_repo(Path("."))
    b = SECURE_REPO_SCANNER()._deep_scan(Path("."))
    assert a == b
