"""Regression suite for the NBD hardening plan (waves A-E).

Each test is named after its defect id so failures map 1:1 to the ledger:

- NBD-01  packaging: wheel must contain runtime packages + data; clean install imports the boot path.
- NBD-02  python_repl: disabled by default (capability_unavailable) and not registered without opt-in.
- NBD-03  atomic writes: full replacement for write/edit, exception safety, symlink containment.
- NBD-04  command quoting: original text reaches the guard (no ``" ".join`` reconstruction).
- NBD-05  consent semantics: denial is ``consent_denied``/``success=False``, never a success.
- NBD-06  background lifecycle: managed + reaped; internal errors return tuples (no NameError).
- NBD-07  non-interactive tests: product code has no pytest-specific env dependency.

Every test here is expected to PASS on the fixed tree and to FAIL on the
pre-fix tree (red/green regression contract).
"""

from __future__ import annotations

import inspect
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

from tools.models import ToolResult

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# NBD-02 — python_repl containment (wave A)
# ---------------------------------------------------------------------------

def test_nbd02_repl_capability_unavailable_when_disabled(monkeypatch):
    from tools.python_repl import PythonREPLTool, _repl_enabled

    monkeypatch.delenv("NABD_ENABLE_PYTHON_REPL", raising=False)
    assert _repl_enabled() is False
    tool = PythonREPLTool(workspace=tempfile.mkdtemp())
    res = tool.execute(code="print(1)")
    assert isinstance(res, ToolResult)
    assert res.success is False
    assert res.status == "capability_unavailable"
    assert "NABD_ENABLE_PYTHON_REPL=1" in res.stderr


def test_nbd02_repl_not_registered_by_default():
    """AppContext must NOT register python_repl unless NABD_ENABLE_PYTHON_REPL=1.

    Runs in a subprocess so the AppContext build (workspace pinning, storage)
    cannot pollute the parent test process.
    """
    code = textwrap.dedent(
        """
        from core.app_context import AppContext
        AppContext.build(auto_discover=False)
        from engine.tool_registry import registry
        print("python_repl" in registry._tools)
        """
    )
    with tempfile.TemporaryDirectory() as td:
        env = dict(os.environ)
        env.update({
            "NABD_ROOT_DIR": td,
            "NABD_WORKSPACE_ROOT": td,
            "NABD_SESSION_DIR": os.path.join(td, "sessions"),
            "NABD_LOG_DIR": os.path.join(td, "logs"),
            "NABD_ENABLE_PYTHON_REPL": "0",
        })
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=120,
            env=env,
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip().endswith("False"), proc.stdout


# ---------------------------------------------------------------------------
# NBD-03 — atomic file replacement (wave C1)
# ---------------------------------------------------------------------------

def _fs_tool(tmp_path):
    from tools.file_system import FileSystemTool
    return FileSystemTool(workspace=str(tmp_path))


def test_nbd03_write_shorter_content_replaces_entire_file(tmp_path):
    target = tmp_path / "w.txt"
    target.write_text("ABCDE", encoding="utf-8")
    res = _fs_tool(tmp_path).execute(action="write", path="w.txt", content="X")
    assert res.success, res.stderr
    # Pre-fix (no O_TRUNC): "XBCDE". Post-fix: exactly "X".
    assert target.read_text(encoding="utf-8") == "X"


def test_nbd03_edit_shorter_content_replaces_entire_file(tmp_path):
    target = tmp_path / "e.txt"
    target.write_text("ABCDE", encoding="utf-8")
    res = _fs_tool(tmp_path).execute(action="edit", path="e.txt", content="X")
    assert res.success, res.stderr
    assert target.read_text(encoding="utf-8") == "X"


def test_nbd03_exception_before_replace_leaves_target_intact(tmp_path, monkeypatch):
    import tools.file_system as fsm

    target = tmp_path / "keep.txt"
    target.write_text("KEEP", encoding="utf-8")

    def _boom(self, target_path, data):
        raise OSError("simulated IO failure before replace")

    monkeypatch.setattr(fsm.FileSystemTool, "_atomic_replace_contents", _boom)
    res = _fs_tool(tmp_path).execute(action="write", path="keep.txt", content="LOST")
    assert res.success is False
    assert target.read_text(encoding="utf-8") == "KEEP"


def test_nbd03_symlink_outside_denied_and_untouched(tmp_path):
    outside = tmp_path.parent / "outside_target.txt"
    outside.write_text("OUTSIDE", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(outside)
    res = _fs_tool(tmp_path).execute(action="write", path="link.txt", content="NEW")
    assert res.success is False, "write through an outside symlink must be denied"
    assert outside.read_text(encoding="utf-8") == "OUTSIDE"


def test_nbd03_no_temp_leftovers_after_replace(tmp_path):
    target = tmp_path / "clean.txt"
    target.write_text("old", encoding="utf-8")
    res = _fs_tool(tmp_path).execute(action="write", path="clean.txt", content="new")
    assert res.success, res.stderr
    leftovers = [p.name for p in tmp_path.rglob("*.nbd-tmp-*")]
    assert leftovers == []


# ---------------------------------------------------------------------------
# NBD-04 — command quoting (wave C2)
# ---------------------------------------------------------------------------

def test_nbd04_shell_preserves_quoted_argument_boundaries(tmp_path, monkeypatch):
    from core.kernel.security import get_workspace_root
    from core.utils import safe_execute_command

    ws = Path(get_workspace_root())
    probe = ws / ".nbd_quote_probe"
    probe.mkdir(exist_ok=True)
    try:
        f = probe / "input file.txt"
        f.write_text("quoted-ok", encoding="utf-8")
        rc, out, err = safe_execute_command('cat ".nbd_quote_probe/input file.txt"')
        assert rc == 0, err
        assert "quoted-ok" in out
    finally:
        for p in probe.iterdir():
            p.unlink()
        probe.rmdir()


def test_nbd04_quoted_semicolon_and_pipe_stay_single_args():
    from core.utils import safe_execute_command

    rc, out, err = safe_execute_command('echo "a; b"')
    assert rc == 0, err
    assert out.strip() == "a; b", out

    rc, out, err = safe_execute_command('echo "x | y"')
    assert rc == 0, err
    assert out.strip() == "x | y", out


def test_nbd04_no_join_reconstruction_of_tokens():
    """The guard must receive the ORIGINAL text, not a token-join rebuild."""
    import core.utils as utils_mod

    src = inspect.getsource(utils_mod._handle_simple)
    assert 'run_agent_command(" ".join(' not in src, "token join reconstruction must be gone"
    assert "run_agent_command(cmd_str" in src, "guard must receive the original text"


# ---------------------------------------------------------------------------
# NBD-05 — consent denial semantics (wave C3)
# ---------------------------------------------------------------------------

def _dummy_dispatch(consent_manager):
    from engine._dispatch import _ToolDispatchMixin
    from core.evidence import EvidenceLog
    from core.kernel.state import RuntimeState

    class _Dummy(_ToolDispatchMixin):
        POLL_DELAY = 0

        def __init__(self):
            self.evidence_log = EvidenceLog()
            self.state = RuntimeState(session_id="t")
            self.max_output_len = 2000
            self._ctx = None
            self.consent_manager = consent_manager

        def _build_tool_feedback(self, result, tool_name, tool_args, output):
            return output

    return _Dummy()


def test_nbd05_consent_denial_never_records_execution_success():
    from engine.consent import ConsentManager

    executed: list = []

    class _FakeRun:
        def __call__(self, *a, **k):
            executed.append(a)
            return subprocess.CompletedProcess(a[0], 0, stdout="hi", stderr="")

    dummy = _dummy_dispatch(ConsentManager(prompt_func=lambda _: "n"))
    orig_run = subprocess.run
    subprocess.run = _FakeRun()  # type: ignore[assignment]
    try:
        handled = dummy._handle_consent_and_edit_gate("execute_shell", {"command": "echo hi"})
        assert handled is True
        assert executed == [], "denied command must not execute"
        denied = [r for r in dummy.evidence_log.get_records() if r.tool == "execute_shell"]
        assert denied and denied[0].success is False
        consent = [r for r in dummy.evidence_log.get_records() if r.tool.startswith("consent.")]
        assert consent and consent[0].success is False
    finally:
        subprocess.run = orig_run


def test_nbd05_consent_manager_is_injected_single_instance():
    from engine.consent import ConsentManager
    from engine.loop import ExecutionLoop
    from engine.state import RuntimeState

    cm = ConsentManager(prompt_func=lambda _: "y")
    loop = ExecutionLoop(
        state=RuntimeState(session_id="t"),
        llm_provider=lambda *a, **k: "x",
        consent_manager=cm,
    )
    assert loop.consent_manager is cm, "injected instance must be used, not recreated"


def test_nbd05_file_edit_rejection_is_consent_denied():
    from engine.consent import ConsentManager
    from unittest.mock import patch

    import engine._dispatch as dispatch_mod

    class _RejectingBridge:
        def emit(self, name, **kwargs):
            if name == "edit_proposed":
                kwargs["decision_box"]["approved"] = False
                kwargs["event"].set()

    dummy = _dummy_dispatch(ConsentManager(prompt_func=lambda _: "n"))
    with patch.object(dispatch_mod, "get_bridge", return_value=_RejectingBridge()):
        handled = dummy._handle_consent_and_edit_gate(
            "file_system", {"action": "edit", "path": "a.py", "content": "x"}
        )
    assert handled is True
    recs = dummy.evidence_log.get_records()
    assert recs and recs[-1].success is False, "edit rejection must not be evidence success"


# ---------------------------------------------------------------------------
# NBD-06 — error tuples and background lifecycle (wave C2)
# ---------------------------------------------------------------------------

def test_nbd06_safe_execute_returns_tuple_on_internal_error(monkeypatch):
    """A TimeoutExpired reaching the orchestrator must NOT raise NameError
    (pre-fix: `except subprocess.TimeoutExpired` without `import subprocess`)."""
    import core.utils as utils_mod
    from core.utils import safe_execute_command

    def _boom(command, timeout=30, tool_name="execute_shell", args=None):
        raise subprocess.TimeoutExpired(command, timeout)

    # Patch the EXACT object safe_execute_command calls (instance-level) so
    # no cross-test class/mock state can change the outcome.
    monkeypatch.setattr(utils_mod.default_guard, "run_agent_command", _boom)
    rc, out, err = safe_execute_command("echo hi")
    assert rc == -1
    assert "timed out" in err


def test_nbd06_background_process_is_managed_and_reaped():
    from core.kernel.subprocess_guard import SubprocessGuard

    guard = SubprocessGuard()
    rc, out, err = guard.spawn_agent_background("sleep 30 &")
    assert rc == 0, err
    m = re.search(r"PID: (\d+)", out)
    assert m, out
    pid = int(m.group(1))
    try:
        assert pid in guard.background_pids()
        rc, out, err = guard.stop_background(pid)
        assert rc == 0, err
        assert pid not in guard.background_pids()
    finally:
        guard.stop_background(pid)  # idempotent cleanup


# ---------------------------------------------------------------------------
# NBD-07 — non-interactive product code (wave E)
# ---------------------------------------------------------------------------

def test_nbd07_product_code_has_no_pytest_env_dependency():
    src = (REPO_ROOT / "engine" / "consent.py").read_text(encoding="utf-8")
    assert "PYTEST_CURRENT_TEST" not in src, "product code must not key off a pytest env flag"


# ---------------------------------------------------------------------------
# NBD-01 — packaging (wave B) — slow: builds a wheel + clean venv install
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_nbd01_wheel_clean_install_imports_runtime_packages(tmp_path):
    """Build the wheel, verify its METADATA declares the runtime deps, then
    attempt a TRULY clean install (venv WITHOUT --system-site-packages, deps
    resolved from the index) and import the boot path from OUTSIDE the tree.

    PR10-02: the pre-fix version used ``venv --system-site-packages`` +
    ``pip install --no-deps``, which could silently borrow ``rich``/
    ``cryptography`` from the host and pass even if the metadata were wrong.
    The venv is now isolated. On platforms without prebuilt wheels for the
    compiled deps (e.g. cryptography/pydantic-core on Termux/Android), pip
    cannot resolve them from the index; that is a platform limitation, not a
    wheel defect — the test SKIPS honestly in that case, and the CI
    ``package-build-and-smoke`` job (ubuntu, network) performs the definitive
    clean install from the index.
    """
    if shutil.which("pip") is None and not shutil.which(f"{sys.executable} -m pip"):
        pytest.skip("pip unavailable")
    wheels = tmp_path / "wheels"
    wheels.mkdir()

    # 1) Build the wheel (offline: no build isolation).
    build = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", str(REPO_ROOT),
         "--no-deps", "--no-build-isolation", "-w", str(wheels)],
        capture_output=True, text=True, timeout=600,
    )
    assert build.returncode == 0, build.stderr[-2000:]
    wheel = next(wheels.glob("*.whl"))

    # 2) Wheel must contain the nested runtime packages + skills data.
    import zipfile
    names = zipfile.ZipFile(wheel).namelist()
    for required in (
        "core/kernel/security.py",
        "core/security/decision_ladder.py",
        "core/dag/__init__.py",
        "ui/design/theme/semantic.py",
        "adapters/lightpanda_adapter.py",
        "skills/auditor.md",
        "smolagents/__init__.py",
    ):
        assert required in names, f"wheel is missing {required}"

    # 2b) PR10-02: METADATA must declare every runtime dependency. This is the
    #     offline, network-independent gate — it runs on EVERY platform and
    #     fails if the metadata/declared deps are wrong.
    meta_name = next(n for n in names if n.endswith(".dist-info/METADATA"))
    metadata = zipfile.ZipFile(wheel).read(meta_name).decode("utf-8", "replace")
    declared: set[str] = set()
    for line in metadata.splitlines():
        if line.startswith("Requires-Dist:"):
            spec = line.split(":", 1)[1].strip()
            name = re.split(r"[<>=!~;\s]+", spec, maxsplit=1)[0].strip()
            # Normalise: PEP 503 canonicalises '_' and '-' identically.
            declared.add(name.lower().replace("_", "-"))
    for dep in ("cryptography", "prompt-toolkit", "pydantic", "rich"):
        assert dep in declared, f"wheel METADATA missing Requires-Dist: {dep}"

    # 3) TRULY clean venv: NO --system-site-packages (host packages must not
    #    leak in), install the wheel WITH deps resolved from the index.
    venv_dir = tmp_path / "venv"
    subprocess.run(
        [sys.executable, "-m", "venv", str(venv_dir)],
        check=True, timeout=180, capture_output=True,
    )
    venv_py = venv_dir / "bin" / "python"
    inst = subprocess.run(
        [str(venv_py), "-m", "pip", "install", "--quiet", str(wheel)],
        capture_output=True, text=True, timeout=600,
    )
    if inst.returncode != 0:
        err = inst.stderr[-2000:].lower()
        # Honest skip ONLY for platform/offline dependency-resolution limits;
        # anything else (bad metadata, broken wheel) must FAIL loudly.
        # PR10-02 (review): the skip list is deliberately NARROW — only
        # platform-build markers that a correctly-declared dependency set hits
        # on Termux/Android (compiled wheels absent). Generic resolution
        # failures ("no matching distribution", "could not find a version")
        # MUST NOT skip: they are exactly how a misspelled/undeclared
        # dependency surfaces, and PR10-02 exists to catch that class of bug.
        if any(k in err for k in (
            "failed to determine android api level",
            "maturin",
            "can't find rust compiler",
            "cargo",
            "building wheel for cryptography",
            "building wheel for pydantic-core",
            "[errno 2] no such file or directory: 'gcc'",
            "error: command 'gcc' failed",
            "network is unreachable",
            "temporary failure in name resolution",
            "connection timed out",
        )):
            pytest.skip(
                "Platform cannot resolve compiled deps (cryptography/pydantic-core) "
                "from the index (e.g. Termux/Android). CI package-build-and-smoke "
                "performs the definitive clean install on ubuntu."
            )
        assert False, f"clean install failed (non-platform reason): {inst.stderr[-1500:]}"

    # 4) Boot-path imports from OUTSIDE the repo (tmp_path is outside), and
    #    confirm the imports resolve from the venv, never the host/system.
    smoke = textwrap.dedent(
        """
        import core
        assert str(core.__file__).startswith(sys_v := __import__("sys").prefix), core.__file__
        import main
        import core.kernel.security
        import core.security.decision_ladder
        import ui.design.theme.semantic
        import adapters.lightpanda_adapter
        import skills, smolagents
        import rich, pydantic, cryptography, prompt_toolkit
        print("SMOKE_OK")
        """
    )
    run = subprocess.run(
        [str(venv_py), "-c", smoke],
        capture_output=True, text=True, timeout=300, cwd=str(tmp_path),
    )
    assert run.returncode == 0, run.stderr[-2000:]
    assert "SMOKE_OK" in run.stdout
