"""tests/test_secure_shell_consent_contract.py — حكم S-2: الموافقة عقد لا زخرفة.

S-2 RULING (Am+9 S-2): مسار AGENT_SHELL لا يُنفَّذ أبدًا بلا موافقة صريحة مسجّلة.
«لا تنفيذَ بلا موافقة»: guard بلا consent callback = حظر fail-closed.

MEASURED GAP (§1 RECON):
  - core/kernel/subprocess_guard.py:222 —
        if self._consent is not None and not self._consent(tool_name, ...)
    يتخطّى بوابة الموافقة كليًا عندما يكون الـ callback غائبًا (fail-open):
    `default_guard = SubprocessGuard()` (سطر 610) بلا موافقة، ومع ذلك يبلغه
    مساران إنتاجيان: core/utils.py:79 (`safe_execute_command` ← منفّذ ShellTool)
    و core/dag/nodes/terminal.py:52 (عقد DAG) — تنفيذٌ بلا موافقة.
  - التوقيع المقيس: ConsentCallback = Callable[[str, dict], bool]
    (True = يُقرّب، False = يحظر) — سطر 69.
  - spawn المقيس في _run_simple: subprocess.run (shell=False) — لا Popen.

CONSENT INTEGRITY: engine/consent.py:_default_prompt يوافق تلقائيًا تحت
PYTEST_CURRENT_TEST / NABD_AUTO_APPROVE=1 — لذلك هذا الحارس لا يعتمد عليه
أبدًا؛ الـ callbacks تُحقَن صراحةً في كل عقد.

العقود الثلاثة:
  ع1 deny-blocks:              موافقة رافضة ⇒ حظر + الـ spawn لم يُستدعَ.
  ع2 no-consent fail-closed:   غياب الـ callback (أو default_guard) ⇒ حظر
                               بسبب يذكر الموافقة + الـ spawn لم يُستدعَ.
  ع3 approve-sanity:           موافقة صريحة + أمر مأمون ⇒ الـ spawn استُدعي
                               (برهان أننا لم نُفشل-الإغلاق كلَّ شيء).
"""

from __future__ import annotations

import subprocess
from unittest import mock

from core.kernel.subprocess_guard import SubprocessGuard, default_guard


def _fake_completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    """سلسلة result وهمية للـ spawn المُرقَّع — لا يُنفَّذ أي أمر حقيقي."""
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# ── ع1: deny-blocks ──────────────────────────────────────────────────────
def test_deny_blocks_spawn():
    """موافقة رافضة (False) تمنع التنفيذ ولا يبلغ الـ spawn."""
    guard = SubprocessGuard(consent_callback=lambda name, args: False)
    with mock.patch("subprocess.run", return_value=_fake_completed(0, "SHOULD-NOT-RUN")) as m_run, \
         mock.patch("subprocess.Popen") as m_popen:
        code, out, err = guard.run_agent_command("echo hi", args={"command": "echo hi"})
    assert code == -1
    assert "blocked" in (out + err).lower()
    assert not m_run.called
    assert not m_popen.called


# ── ع2: no-consent fail-closed (عقد الفجوة) ──────────────────────────────
def test_no_consent_is_fail_closed():
    """غياب consent callback = حظر fail-closed قبل أي spawn."""
    guard = SubprocessGuard()  # بلا موافقة — الفجوة المقيسة
    with mock.patch("subprocess.run", return_value=_fake_completed(0, "SHOULD-NOT-RUN")) as m_run, \
         mock.patch("subprocess.Popen") as m_popen:
        code, out, err = guard.run_agent_command("echo hi", args={"command": "echo hi"})
    assert code == -1
    assert "consent" in err.lower()
    assert not m_run.called
    assert not m_popen.called


def test_default_guard_no_consent_is_fail_closed():
    """default_guard نفسه (بلا موافقة) يحظر — لا تنفيذ بلا موافقة صريحة."""
    with mock.patch("subprocess.run", return_value=_fake_completed(0, "SHOULD-NOT-RUN")) as m_run, \
         mock.patch("subprocess.Popen") as m_popen:
        code, out, err = default_guard.run_agent_command("echo hi", args={"command": "echo hi"})
    assert code == -1
    assert "consent" in err.lower()
    assert not m_run.called
    assert not m_popen.called


# ── ع3: approve-sanity ───────────────────────────────────────────────────
def test_approve_sanity_spawns():
    """موافقة صريحة (True) + أمر مأمون ⇒ الـ spawn استُدعي (لم نُفشل-الإغلاق كل شيء)."""
    guard = SubprocessGuard(consent_callback=lambda name, args: True)
    with mock.patch("subprocess.run", return_value=_fake_completed(0, "hello")) as m_run, \
         mock.patch("subprocess.Popen") as m_popen:
        code, out, err = guard.run_agent_command("echo hi", args={"command": "echo hi"})
    assert code == 0
    assert m_run.called
