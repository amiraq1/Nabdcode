"""
S-2-FINAL — حارس توصيل الموافقة الفعلي (يولد أحمر قبل التعديل).

الحكم: S-2-FINAL يُغلق الدين المفتوح من S-2-REDESIGN (a2faaa7) —
توصيل consent_callback فعليًا من main.py عبر launch_nabdos_core،
وتحويل TerminalNode من fail-open موثّق إلى fail-closed.

الفجوة المقيسة (حالة ما قبل التعديل):
- ع1: TerminalNode.__init__ يقبل consent_callback (تماس جاهز من S-2-REDESIGN).
- ع2: launch_nabdos_core لا يقبل ولا يمرر consent_callback (الدين المفتوح) —
      يتكسر بـ AST (لا regex، لا grep).
- ع3: TerminalNode بلا callback ينفّذ الأمر (fail-open) — يجب أن يُحجب
      بعد S-2-FINAL (fail-closed محلي في هذه العقدة فقط، لا يمس default_guard العام).
- ع4: TerminalNode بتماس موافِق ينفّذ الأمر — برهان أن الحجب لم يُفشل كل شيء.

الاستدعاء فعلي كما في الإنتاج: TerminalNode.execute() عبر
NabdExecutionContext حقيقي، مع حقن التماس عبر __init__ صراحةً
(لا نعتمد على PYTEST_CURRENT_TEST في _default_prompt).
"""
import ast
import inspect
from pathlib import Path

import core.dag.nodes.terminal as terminal_module
from core.dag.context import NabdExecutionContext
from core.dag.nodes.terminal import TerminalNode


def _make_context(command: str) -> NabdExecutionContext:
    ctx = NabdExecutionContext(workspace_dir=str(Path.cwd()))
    ctx.shared_memory["pending_command"] = command
    return ctx


# ── ع1 — التماس موجود في البنية (passes red & green) ──────────────
def test_terminal_node_receives_consent_callback():
    sig = inspect.signature(TerminalNode.__init__)
    assert "consent_callback" in sig.parameters, (
        "TerminalNode.__init__ must accept consent_callback (seam from S-2-REDESIGN)"
    )


# ── ع2 — التوصيل الفعلي مفقود اليوم (AST, fails red) ──────────────
def test_consent_callback_is_actually_passed():
    # (أ) التوصيل في launcher.py: معامل + تمرير إلى TerminalNode.
    src = Path("core/dag/launcher.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    fn = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "launch_nabdos_core"
    )
    param_names = [a.arg for a in fn.args.args] + [a.arg for a in fn.args.kwonlyargs]
    assert "consent_callback" in param_names, (
        "launch_nabdos_core must accept consent_callback parameter"
    )

    terminal_call = None
    for n in ast.walk(fn):
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "TerminalNode"
        ):
            terminal_call = n
            break
    assert terminal_call is not None, "TerminalNode(...) call not found in launch_nabdos_core"
    kw = {k.arg for k in terminal_call.keywords}
    assert "consent_callback" in kw, (
        "TerminalNode call must pass consent_callback=consent_callback"
    )

    # (ب) The caller check has been moved to test_dag_consent_wiring.py 
    # to test core/command_dispatcher.py instead of main.py.


# ── ع3 — fail-closed: بلا تماس، لا تنفيذ (fails red: fail-open today) ──
def test_terminal_node_blocks_without_consent(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return (0, "ran", "")

    monkeypatch.setattr(
        terminal_module.default_guard, "run_agent_command", fake_run
    )

    node = TerminalNode()  # بلا callback → يجب أن يُحجب (fail-closed)
    ctx = _make_context("echo hello")
    edge = node.execute(ctx)

    assert edge is not None
    assert "Consent" in edge.reason, (
        f"expected a Consent-denied edge, got reason={edge.reason!r}"
    )
    assert calls == [], (
        f"command executed despite missing consent callback: {calls}"
    )
    feedback = ctx.shared_memory.get("human_feedback", "")
    assert "blocked" in feedback, (
        f"human_feedback must record the block, got {feedback!r}"
    )


# ── ع4 — بتماس موافِق، يُنفَّذ (passes red & green) ────────────────
def test_terminal_node_executes_with_consent(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return (0, "ok", "")

    monkeypatch.setattr(
        terminal_module.default_guard, "run_agent_command", fake_run
    )

    node = TerminalNode(consent_callback=lambda tool_name, args: True)
    edge = node.execute(_make_context("echo hello"))

    assert calls == ["echo hello"], f"expected execution, got calls={calls}"
    assert edge.target_node_id == "end"
