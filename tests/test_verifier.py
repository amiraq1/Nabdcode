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


if __name__ == "__main__":
    unittest.main()
