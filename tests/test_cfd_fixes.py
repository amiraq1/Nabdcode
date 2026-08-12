"""Closure tests for the CFD findings confirmed by the verification annex.

Each test is named after its finding id and fails on the pre-fix code:

- CFD-pyproject-1: ``cryptography`` declared + BYOK save/load roundtrip.
- CFD-fs-2:       FileSystemTool's DecisionLadder uses the pinned workspace,
                  not ``os.getcwd()``.
- CFD-registry-1: placeholder name ``unnamed_tool`` is rejected at registration
                  and skipped by auto-discovery.
- CFD-appctx-1:   auto-discovery receives a real dependency context and can
                  build tools whose constructors require ``workspace_dir``.
- CFD-guard-1:    consent callback contract — approval maps to True, denial to
                  False (contract test only; no code change per annex ruling).
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# CFD-pyproject-1 — cryptography is a declared runtime dependency
# ---------------------------------------------------------------------------

def test_cfd_pyproject_cryptography_declared():
    with open(REPO_ROOT / "pyproject.toml", "rb") as fh:
        pyproject = tomllib.load(fh)
    deps = pyproject["project"]["dependencies"]
    # Tolerate any version specifier form: ``cryptography``, ``>=42.0``, ``==42``.
    assert any(
        d.strip().lower().startswith("cryptography")
        and not d.strip().lower().startswith("cryptographyx")
        for d in deps
    ), (
        "cryptography must be a declared runtime dependency (AES-GCM BYOK)"
    )


def test_cfd_pyproject_byok_roundtrip(tmp_path):
    """ConfigManager.set_api_key/get_api_key roundtrip exercises AES-GCM."""
    from core.config import ConfigManager

    cm = ConfigManager(config_dir=tmp_path / "cfg")
    cm.set_api_key("openrouter", "sk-test-123")
    assert cm.get_api_key("openrouter") == "sk-test-123"
    # At-rest file must be ciphertext (enc: prefix), never plaintext.
    raw = (tmp_path / "cfg" / "config.json").read_text(encoding="utf-8")
    assert "sk-test-123" not in raw
    assert "enc:" in raw


# ---------------------------------------------------------------------------
# CFD-fs-2 — DecisionLadder evaluates against the pinned workspace
# ---------------------------------------------------------------------------

def test_cfd_fs_decision_ladder_uses_pinned_workspace_not_cwd(tmp_path, monkeypatch):
    import tools.file_system as fsm
    from tools.file_system import FileSystemTool

    workspace = tmp_path / "ws"
    workspace.mkdir()
    # Prove the ladder root is NOT the process cwd: run from a different dir.
    (tmp_path / "elsewhere").mkdir(exist_ok=True)  # must exist BEFORE chdir
    monkeypatch.chdir(tmp_path / "elsewhere")

    captured: dict = {}
    real_init = fsm.DecisionLadder.__init__

    def spy(self, *a, **kw):
        captured["root"] = kw.get("workspace_root")
        return real_init(self, *a, **kw)

    monkeypatch.setattr(fsm.DecisionLadder, "__init__", spy)

    tool = FileSystemTool(workspace=str(workspace))
    tool.execute(action="read", path="missing.txt")  # triggers the ladder gate

    assert captured.get("root") == str(workspace.resolve()), (
        "DecisionLadder must use self.workspace, got %r" % captured.get("root")
    )


def test_cfd_fs2_shell_uses_pinned_workspace_root_not_cwd(tmp_path, monkeypatch):
    """ShellTool's DecisionLadder must evaluate against the pinned workspace
    root (get_workspace_root), not os.getcwd() — same CFD-fs-2 class of bug."""
    import tools.shell as shell_mod
    from tools.shell import ShellTool

    pinned = tmp_path / "pinned_root"
    pinned.mkdir()
    monkeypatch.setattr(
        "core.kernel.security.get_workspace_root", lambda: pinned
    )
    (tmp_path / "elsewhere").mkdir(exist_ok=True)  # must exist BEFORE chdir
    monkeypatch.chdir(tmp_path / "elsewhere")  # must differ from pinned root

    captured: dict = {}
    real_init = shell_mod.DecisionLadder.__init__

    def spy(self, *a, **kw):
        captured["root"] = kw.get("workspace_root")
        return real_init(self, *a, **kw)

    monkeypatch.setattr(shell_mod.DecisionLadder, "__init__", spy)

    tool = ShellTool()
    tool.execute(command="echo hi")

    assert captured.get("root") == str(pinned), (
        "ShellTool DecisionLadder must use the pinned workspace root, "
        "got %r (expected %r)" % (captured.get("root"), str(pinned))
    )


# ---------------------------------------------------------------------------
# CFD-registry-1 — placeholder names are rejected / skipped
# ---------------------------------------------------------------------------

def test_cfd_registry_rejects_placeholder_name():
    from engine.tool_registry import ToolRegistry
    from tools.base import BaseTool

    class _Nameless(BaseTool):
        """Deliberately does NOT override ``name`` (inherits placeholder)."""

        def execute(self, **kwargs):
            return None  # minimal concrete impl so the class is instantiable

    with pytest.raises(ValueError, match="has no name"):
        ToolRegistry().register(_Nameless())


def _fake_discovery_ctx(tmp_path):
    class _Cfg:
        workspace_root = tmp_path

    return SimpleNamespace(
        config=_Cfg(),
        memory_manager=None,
        todo_manager=None,
        _security_engine=None,
        workspace=tmp_path,
        workspace_root=tmp_path,
        workspace_dir=tmp_path,
        memory=None,
    )


def test_cfd_discovery_skips_unnamed_base_class(tmp_path):
    from core.tool_factory import discover_tools

    discovered = discover_tools(_fake_discovery_ctx(tmp_path))
    assert "unnamed_tool" not in discovered, "base SecureTool must not be discovered"


def test_cfd_discovery_injects_workspace_dir(tmp_path):
    from core.tool_factory import _build_tool_with_deps
    from tools.browser_tool import BrowserTool

    tool = _build_tool_with_deps(BrowserTool, _fake_discovery_ctx(tmp_path))
    assert tool is not None, "BrowserTool must build once workspace_dir is injectable"
    assert isinstance(tool, BrowserTool)


# ---------------------------------------------------------------------------
# CFD-guard-1 — consent callback contract (approve → True, deny → False)
# ---------------------------------------------------------------------------

def test_cfd_guard1_consent_callback_polarity():
    """The command_dispatcher conversion ``confirm(...) is None`` must yield
    True on approval and False on denial (contract test — no code change)."""
    from core.command_dispatcher import _cmd_refactor  # noqa: F401  (import parity)
    from engine.consent import ConsentManager

    approving = ConsentManager(prompt_func=lambda _: "y")
    denying = ConsentManager(prompt_func=lambda _: "n")

    cb_approve = lambda t, a: approving.confirm(t, a) is None
    cb_deny = lambda t, a: denying.confirm(t, a) is None

    assert cb_approve("execute_shell", {"command": "echo hi"}) is True
    assert cb_deny("execute_shell", {"command": "echo hi"}) is False


def test_cfd_guard1_guard_runs_on_approve_blocks_on_deny():
    from core.kernel.subprocess_guard import SubprocessGuard
    from engine.consent import ConsentManager

    approving = ConsentManager(prompt_func=lambda _: "y")
    denying = ConsentManager(prompt_func=lambda _: "n")

    run_guard = SubprocessGuard(consent_callback=lambda t, a: approving.confirm(t, a) is None)
    rc, out, err = run_guard.run_agent_command("echo hi")
    assert rc == 0, err

    block_guard = SubprocessGuard(consent_callback=lambda t, a: denying.confirm(t, a) is None)
    rc, out, err = block_guard.run_agent_command("echo hi")
    assert rc == -1
    assert "blocked" in err
