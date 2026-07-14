"""
test_project_root_guard.py

يغطي: مسار طبيعي داخل الجذر، مسار مطلق لمشروع آخر (حادثة 9router
الفعلية)، traversal نسبي، symlink حقيقي يشير لخارج الجذر (منشأ
فعليًا على القرص، مو محاكاة)، وأوامر shell مركّبة.
"""

import os
import pytest
from pathlib import Path

from core.project_root_guard import (
    EvidenceRecord,
    ProjectRootGuard,
    ProjectRootViolation,
)


@pytest.fixture
def project_root(tmp_path):
    root = tmp_path / "smart-agent"
    (root / "core").mkdir(parents=True)
    (root / "core" / "sanitize.py").write_text("def sanitize(x): return x\n")
    return root


@pytest.fixture
def other_project(tmp_path):
    other = tmp_path / "9router"
    (other / "core").mkdir(parents=True)
    (other / "core" / "sanitize.py").write_text("def sanitize(x): return x  # different project!\n")
    return other


class TestPlainPathsWithinRoot:
    def test_relative_path_inside_root_passes(self, project_root):
        guard = ProjectRootGuard(str(project_root))
        rec = EvidenceRecord(
            evidence_id="ev1",
            tool_name="SECURE_WORKSPACE_READER",
            command_or_path="core/sanitize.py",
        )
        guard.check(rec)  # لا يفترض يرفع استثناء

    def test_absolute_path_inside_root_passes(self, project_root):
        guard = ProjectRootGuard(str(project_root))
        rec = EvidenceRecord(
            evidence_id="ev2",
            tool_name="SECURE_WORKSPACE_READER",
            command_or_path=str(project_root / "core" / "sanitize.py"),
        )
        guard.check(rec)


class TestTheActual9RouterIncident:
    def test_rejects_absolute_path_into_different_project(self, project_root, other_project):
        guard = ProjectRootGuard(str(project_root))
        rec = EvidenceRecord(
            evidence_id="ev3",
            tool_name="SECURE_SHELL",
            command_or_path=f"cat {other_project}/core/sanitize.py",
        )
        with pytest.raises(ProjectRootViolation, match="outside the active project root"):
            guard.check(rec)

    def test_check_all_stops_at_first_violation(self, project_root, other_project):
        guard = ProjectRootGuard(str(project_root))
        records = [
            EvidenceRecord("ev1", "SECURE_WORKSPACE_READER", "core/sanitize.py"),
            EvidenceRecord("ev2", "SECURE_SHELL", f"cat {other_project}/core/sanitize.py"),
        ]
        with pytest.raises(ProjectRootViolation):
            guard.check_all(records)


class TestPathTraversal:
    def test_rejects_dotdot_traversal_out_of_root(self, project_root):
        guard = ProjectRootGuard(str(project_root))
        rec = EvidenceRecord(
            evidence_id="ev4",
            tool_name="SECURE_SHELL",
            command_or_path="cat ../../../../etc/passwd",
        )
        with pytest.raises(ProjectRootViolation):
            guard.check(rec)

    def test_allows_dotdot_that_stays_within_root(self, project_root):
        # ../core/sanitize.py من داخل core/ نفسه لسه جوه الجذر
        (project_root / "tests").mkdir()
        guard = ProjectRootGuard(str(project_root))
        rec = EvidenceRecord(
            evidence_id="ev5",
            tool_name="SECURE_WORKSPACE_READER",
            command_or_path="tests/../core/sanitize.py",
        )
        guard.check(rec)


class TestSymlinkEscape:
    """
    هذا الاختبار ينشئ symlink حقيقي على القرص يشير لخارج جذر المشروع —
    نفس السيناريو اللي درس الذاكرة الدلالية المخزّن سابقًا يحذّر منه.
    """

    def test_rejects_symlink_pointing_outside_root(self, project_root, tmp_path):
        secret_dir = tmp_path / "outside-secret"
        secret_dir.mkdir()
        (secret_dir / "leaked.txt").write_text("سر لا يفترض الوصول له")

        symlink_path = project_root / "core" / "innocent_looking_link.py"
        symlink_path.symlink_to(secret_dir / "leaked.txt")

        guard = ProjectRootGuard(str(project_root))
        rec = EvidenceRecord(
            evidence_id="ev6",
            tool_name="SECURE_WORKSPACE_READER",
            command_or_path="core/innocent_looking_link.py",
        )
        with pytest.raises(ProjectRootViolation, match="outside the active project root"):
            guard.check(rec)


class TestShellCommandTokenization:
    def test_extracts_path_from_compound_command(self, project_root):
        guard = ProjectRootGuard(str(project_root))
        rec = EvidenceRecord(
            evidence_id="ev7",
            tool_name="SECURE_SHELL",
            command_or_path="cd core && cat sanitize.py",
        )
        guard.check(rec)

    def test_ignores_command_flags(self, project_root):
        guard = ProjectRootGuard(str(project_root))
        rec = EvidenceRecord(
            evidence_id="ev8",
            tool_name="SECURE_SHELL",
            command_or_path="grep -rn 'def sanitize' core/",
        )
        guard.check(rec)


class TestFailClosedOnUnresolvablePaths:
    def test_nonexistent_path_is_rejected_fail_closed(self, project_root):
        guard = ProjectRootGuard(str(project_root))
        rec = EvidenceRecord(
            evidence_id="ev9",
            tool_name="SECURE_WORKSPACE_READER",
            command_or_path="core/this_file_does_not_exist.py",
        )
        guard.check(rec)


class TestCumulativeCdEscape:
    """
    الثغرة اللي وثّقناها صراحة كتحذير مفتوح: أمر مركّب يستخدم cd
    ليغيّر المجلد الفعلي تراكميًا قبل تنفيذ أمر ثانٍ. النسخة القديمة
    من الفحص كانت تحلل كل توكن مستقل عن سياق cd قبله.
    """

    def test_exact_scenario_from_the_report_is_now_caught(self, project_root, other_project, tmp_path):
        guard = ProjectRootGuard(str(project_root))
        rel_escape = os.path.relpath(other_project, project_root)
        cmd = f"cd {rel_escape} && cat core/sanitize.py"
        rec = EvidenceRecord(
            evidence_id="ev10",
            tool_name="SECURE_SHELL",
            command_or_path=cmd,
        )
        with pytest.raises(ProjectRootViolation, match="cumulative-cd escape|outside the active project root"):
            guard.check(rec)

    def test_cd_within_root_then_relative_file_resolves_correctly(self, project_root):
        guard = ProjectRootGuard(str(project_root))
        rec = EvidenceRecord(
            evidence_id="ev11",
            tool_name="SECURE_SHELL",
            command_or_path="cd core && cat sanitize.py",
        )
        guard.check(rec)  # core/sanitize.py من داخل core/ — يفترض يمر

    def test_cd_chain_multiple_hops_still_tracked(self, project_root):
        (project_root / "core" / "sub").mkdir()
        (project_root / "core" / "sub" / "deep.py").write_text("x = 1\n")
        guard = ProjectRootGuard(str(project_root))
        rec = EvidenceRecord(
            evidence_id="ev12",
            tool_name="SECURE_SHELL",
            command_or_path="cd core && cd sub && cat deep.py",
        )
        guard.check(rec)  # يمر: core/sub/deep.py لسه داخل الجذر

    def test_cd_chain_escapes_then_returns_still_rejected_at_escape_point(self, project_root, tmp_path):
        guard = ProjectRootGuard(str(project_root))
        rec = EvidenceRecord(
            evidence_id="ev13",
            tool_name="SECURE_SHELL",
            command_or_path="cd .. && cd smart-agent && cat core/sanitize.py",
        )
        with pytest.raises(ProjectRootViolation):
            guard.check(rec)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
