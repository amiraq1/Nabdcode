"""Regression test suite for non-LLM independent verifier and fake success denial."""

import unittest
from core.verifier import check_file_count_claim, check_commit_count_claim, verify_report_strict, gate_report
from core.evidence import EvidenceLog, EvidenceRecord


def make_log(records):
    log = EvidenceLog()
    for r in records:
        log.add(r)
    return log


class TestVerifierRegression(unittest.TestCase):

    # --- الحالة اللي جربناها فعلياً: العدّ المُختلق ---
    def test_fake_file_count_rejected(self):
        """يمثل سيناريو 'عدد ملفات .py = 15' بدون دليل حقيقي كافٍ."""
        log = make_log([
            EvidenceRecord(tool_name="read_file", input="core/sanitize.py",
                           raw_output="...", exit_code=0, timestamp=0, call_id="1"),
        ])
        report = "عدد ملفات .py في المستودع هو 15"
        result = check_file_count_claim(report, log)
        self.assertFalse(result.passed)

    def test_real_file_count_accepted(self):
        log = make_log([
            EvidenceRecord(tool_name="find_files", input="*.py",
                           raw_output="a.py\nb.py\nc.py", exit_code=0, timestamp=0, call_id="1"),
        ])
        report = "عدد ملفات .py في المستودع هو 3"
        result = check_file_count_claim(report, log)
        self.assertTrue(result.passed)

    def test_mismatched_file_count_rejected(self):
        log = make_log([
            EvidenceRecord(tool_name="find_files", input="*.py",
                           raw_output="a.py\nb.py", exit_code=0, timestamp=0, call_id="1"),
        ])
        report = "عدد ملفات .py في المستودع هو 5"  # لا يطابق العدّ الفعلي
        result = check_file_count_claim(report, log)
        self.assertFalse(result.passed)

    # --- سيناريو الـ commits المُختلقة ---
    def test_fake_commits_rejected(self):
        log = make_log([])  # لا يوجد استدعاء git_log إطلاقاً
        report = 'commit 1: "Fixed bug in core/sanitize.py"'
        result = check_commit_count_claim(report, log)
        self.assertFalse(result.passed)

    def test_real_commits_accepted(self):
        log = make_log([
            EvidenceRecord(tool_name="git_log", input="-3",
                           raw_output='"Fixed bug in core/sanitize.py"\n"Added feature"',
                           exit_code=0, timestamp=0, call_id="1"),
        ])
        report = 'commit 1: "Fixed bug in core/sanitize.py"'
        result = check_commit_count_claim(report, log)
        self.assertTrue(result.passed)

    def test_gate_report_denial(self):
        log = make_log([])
        report = 'commit 1: "Fabricated commit"'
        gated = gate_report(report, log)
        self.assertIn("فشل التحقق", gated)

    def test_gate_report_passes_valid_report(self):
        """يتأكد إن gate_report ما يرفض تقرير صحيح فعلاً."""
        log = make_log([
            EvidenceRecord(tool_name="find_files", input="*.py",
                           raw_output="a.py\nb.py\nc.py",
                           exit_code=0, timestamp=0, call_id="1"),
        ])
        report = "عدد ملفات .py في المستودع هو 3"
        result = gate_report(report, log)
        self.assertNotIn("⚠️", result)

    def test_verify_report_strict_empty_log(self):
        """تقرير بدون أي evidence_log إطلاقاً يجب أن يُرفض بالكامل."""
        log = make_log([])
        report = "عدد ملفات .py هو 10 و commit 1: \"fix bug\""
        result = verify_report_strict(report, log)
        self.assertFalse(result.passed)

    def test_partial_commit_match_rejected(self):
        """لو ادّعى 3 commits لكن evidence فيها 2 بس فعلياً."""
        log = make_log([
            EvidenceRecord(tool_name="git_log", input="-3",
                           raw_output='"fix bug"\n"add feature"',
                           exit_code=0, timestamp=0, call_id="1"),
        ])
        report = 'commit 1: "fix bug"\ncommit 2: "add feature"\ncommit 3: "update docs"'
        result = check_commit_count_claim(report, log)
        self.assertFalse(result.passed)  # "update docs" مش موجود فعلياً

    def test_zero_file_count_edge_case(self):
        """حالة حدّية: عدد الملفات صفر."""
        log = make_log([
            EvidenceRecord(tool_name="find_files", input="*.py",
                           raw_output="", exit_code=0, timestamp=0, call_id="1"),
        ])
        report = "عدد ملفات .py في المستودع هو 0"
        result = check_file_count_claim(report, log)
        self.assertTrue(result.passed)

    def test_run_tests_as_evidence(self):
        """يتأكد إن run_tests_as_evidence يشغل الاختبارات ويسجل الناتج في evidence_log."""
        from core.test_runner_wrapper import run_tests_as_evidence
        log = EvidenceLog()
        out = run_tests_as_evidence("tests/test_sanitize.py", log)
        self.assertIn("Ran", out)
        recs = log.get_records()
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0].tool_name, "run_tests")
        self.assertTrue(recs[0].success)

    def test_fake_test_count_claim_rejected(self):
        """يرفض ادعاء تشغيل عدد اختبارات مزيف أو بدون استدعاء run_tests."""
        from core.verifier import check_test_count_claim
        log = make_log([])
        report = "Ran 50 tests in 0.1s OK"
        res = check_test_count_claim(report, log)
        self.assertFalse(res.passed)

    def test_real_test_count_claim_accepted(self):
        """يقبل ادعاء تشغيل عدد اختبارات مطابق لنتائج run_tests الموثقة."""
        from core.verifier import check_test_count_claim
        log = make_log([
            EvidenceRecord(tool_name="run_tests", input="tests/test_verifier.py",
                           raw_output="Ran 12 tests in 0.05s\n\nOK",
                           exit_code=0, timestamp=0, call_id="1"),
        ])
        report = "Ran 12 tests successfully."
        res = check_test_count_claim(report, log)
        self.assertTrue(res.passed)

    def test_fake_git_push_claim_rejected(self):
        """يرفض ادعاء الرفع إلى origin/main بدون وجود git_diff فارغ يثبت التزامن."""
        from core.verifier import check_git_push_claim
        log = make_log([
            EvidenceRecord(tool_name="git_log", input="-1",
                           raw_output="79a8c9b feat(verifier)",
                           exit_code=0, timestamp=0, call_id="1"),
        ])
        report = "تم الرفع بنجاح إلى origin/main"
        res = check_git_push_claim(report, log)
        self.assertFalse(res.passed)

    def test_real_git_push_claim_accepted(self):
        """يقبل ادعاء الرفع عندما يوجد استدعاء git_diff فارغ يؤكد التزامن."""
        from core.verifier import check_git_push_claim
        log = make_log([
            EvidenceRecord(tool_name="git_log", input="-1",
                           raw_output="79a8c9b feat(verifier)",
                           exit_code=0, timestamp=0, call_id="1"),
            EvidenceRecord(tool_name="git_diff", input="HEAD origin/main",
                           raw_output="",
                           exit_code=0, timestamp=0, call_id="2"),
        ])
        report = "تم الرفع بنجاح إلى origin/main والرمز 79a8c9b متزامن"
        res = check_git_push_claim(report, log)
        self.assertTrue(res.passed)

    def test_git_push_tool_auto_records_diff(self):
        """يتأكد إن أداة git_push تسجل تلقائياً سجل git_diff في evidence_log."""
        from tools.git_tool import GitPushTool
        log = EvidenceLog()
        tool = GitPushTool()
        tool.execute(evidence_log=log, remote="origin", branch="main")
        recs = log.get_records()
        diff_recs = [r for r in recs if r.tool_name == "git_diff"]
        self.assertGreaterEqual(len(diff_recs), 1)
        self.assertEqual(diff_recs[0].input, "HEAD origin/main")


if __name__ == "__main__":
    unittest.main()
