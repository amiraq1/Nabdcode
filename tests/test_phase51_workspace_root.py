"""Phase 5.1 — Pin WORKSPACE_ROOT at build time.

Verifies:
  1. AgentConfig.workspace_root is pinned at construction.
  2. pin_workspace_root() sets the global for parser._validate_path.
  3. _validate_path uses the pinned root, not a later cwd.
  4. Path validation survives os.chdir to a different directory.
  5. ProviderRouter state key can be set after construction.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tempfile
from pathlib import Path


# ── Workspace root pinning ───────────────────────────────────────────────

def test_config_workspace_root_pinned():
    """AgentConfig.workspace_root must be a resolved Path set at construction."""
    from core.config import AgentConfig
    cfg = AgentConfig()
    assert cfg.workspace_root is not None
    assert isinstance(cfg.workspace_root, Path)
    assert cfg.workspace_root.is_absolute()
    assert cfg.workspace_root == Path.cwd().resolve()


def test_pin_workspace_root_sets_global():
    """pin_workspace_root() must update the parser's _WORKSPACE_ROOT."""
    from core.parser import pin_workspace_root, get_workspace_root

    # Pin to a known path
    test_root = Path("/tmp/test_workspace")
    pin_workspace_root(test_root)
    assert get_workspace_root() == test_root.resolve()


def test_validate_path_uses_pinned_root():
    """_validate_path must use the pinned root, not cwd."""
    from core.parser import pin_workspace_root, _validate_path
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp).resolve()
        pin_workspace_root(tmp_path)

        # Path inside workspace should validate
        assert _validate_path("test.txt"), "Path inside workspace should validate"

        # Path outside workspace should fail
        assert not _validate_path("/etc/passwd"), "Path outside workspace should fail"


def test_pinned_root_survives_chdir():
    """After os.chdir to a different directory, path validation still uses
    the original pinned root, not the new cwd."""
    from core.parser import pin_workspace_root, _validate_path

    with tempfile.TemporaryDirectory() as tmp1:
        tmp1_path = Path(tmp1).resolve()
        pin_workspace_root(tmp1_path)

        with tempfile.TemporaryDirectory() as tmp2:
            # cd to a completely different directory
            old_cwd = os.getcwd()
            try:
                os.chdir(tmp2)
                # Path relative to original workspace should validate
                # even though cwd is now tmp2
                assert _validate_path("test.txt"), (
                    "Path relative to pinned root should validate after chdir"
                )
                # Path outside pinned root should fail
                assert not _validate_path("/etc"), (
                    "Path outside pinned workspace should fail after chdir"
                )
            finally:
                os.chdir(old_cwd)


def test_config_workspace_root_survives_chdir():
    """Changing directory after AgentConfig construction must not change
    workspace_root."""
    from core.config import AgentConfig

    cfg = AgentConfig()
    original = cfg.workspace_root

    old_cwd = os.getcwd()
    try:
        os.chdir(tempfile.mkdtemp())
        assert cfg.workspace_root == original, (
            f"workspace_root changed from {original} to {cfg.workspace_root} after chdir"
        )
    finally:
        os.chdir(old_cwd)


def test_pin_workspace_root_fallback_no_pin():
    """Without a call to pin_workspace_root, get_workspace_root() returns cwd."""
    from core.parser import get_workspace_root

    # Reset by re-importing in a clean way isn't trivial; at minimum verify
    # the function returns a Path and doesn't crash
    root = get_workspace_root()
    assert isinstance(root, Path)
    assert root.is_absolute()


# ── ProviderRouter state key ─────────────────────────────────────────────

def test_provider_router_set_state_key():
    """set_state_key() must update the _state_key and trigger _restore_state."""
    from llm_router import ProviderRouter, ProviderState

    p = ProviderState(name="test", client=object(), priority=0)
    router = ProviderRouter([p])

    # Default: no key
    path_no_key = router._state_path()

    router.set_state_key("test_session")
    path_with_key = router._state_path()

    assert path_no_key != path_with_key
    assert "test_session" in path_with_key


def test_provider_router_state_key_restores():
    """set_state_key() must call _restore_state (load existing or start fresh)."""
    from llm_router import ProviderRouter, ProviderState
    p = ProviderState(name="test", client=object(), priority=0)
    router = ProviderRouter([p])

    # Should not crash — _restore_state catches file-not-found
    router.set_state_key("nonexistent_test_session")


if __name__ == "__main__":
    test_config_workspace_root_pinned()
    test_pin_workspace_root_sets_global()
    test_validate_path_uses_pinned_root()
    test_pinned_root_survives_chdir()
    test_config_workspace_root_survives_chdir()
    test_pin_workspace_root_fallback_no_pin()
    test_provider_router_set_state_key()
    test_provider_router_state_key_restores()
    print("All Phase 5.1 tests passed.")
