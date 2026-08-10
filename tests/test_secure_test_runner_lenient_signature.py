"""Guard: SecureTestRunner lenient signature (P-1).

حكم P-1: secure_test_runner يجب ألا يرمي TypeError عند غياب test_target —
النمط المتسامح المعتمد في بقية أدوات Secure* (قيمة افتراضية + احتياطي
kwargs + رسالة خطأ لطيفة) بدل المعامل الإلزامي بلا افتراضي.

القرار (المصدر: المشغّل البشري):
- إصلاح كمّي خالص: الأداة تبقى مسحوبة في core/agent_manager.py:136
  (Tool Fixation guard) — لا إعادة تفعيل في هذا العقد.
- النطاق: SecureTestRunner فقط — SecureGitInspector خارج النطاق (له
  مستدعٍ إنتاجي حي عبر tools/git_tool.py:122 في فحص ما قبل الـ push).

الفجوة المقيسة من الاستطلاع: tools/secure_tools.py:378 —
`def forward(self, test_target: str, **kwargs)` بلا افتراضي؛ أي استدعاء
بلا test_target (ReAct `forward(*[])` في smolagents/__init__.py:343، أو
shim الـ Dispatcher `execute() -> forward(**kwargs)` في secure_tools.py:98)
يرمي TypeError مولّدًا تشغيليًا. العقد يثبت أن الإصلاح يزيل العائلة
بجذرها: لا انهيار، ولا تغيير في المسار الصحيح.
"""

import unittest
from unittest.mock import patch

from tools.secure_tools import SecureTestRunner


class TestSecureTestRunnerLenientSignature(unittest.TestCase):
    def setUp(self):
        self.runner = SecureTestRunner(repo_path=".")

    # ع1 — استدعاء forward() بلا test_target → رسالة خطأ لطيفة، لا TypeError
    def test_missing_target_returns_graceful_error(self):
        result = self.runner.forward()
        self.assertIsInstance(result, str)
        self.assertTrue(result.startswith("Error:"))
        self.assertIn("test_target", result)

    # ع2 — shim الـ Dispatcher (execute -> forward(**kwargs)) بلا وسائط → لا انهيار
    def test_execute_shim_without_target_no_crash(self):
        result = self.runner.execute()
        self.assertIsNotNone(result)
        self.assertFalse(result.success)

    # ع3 — المسار الصحيح (fast path: forward(test_target=...)) ما زال يعمل
    @patch("core.kernel.subprocess_guard.default_guard.run_infra")
    def test_keyword_call_still_works(self, mock_run):
        mock_run.return_value = (0, "Ran 1 test OK", "")
        result = self.runner.forward(test_target="unit")
        self.assertIn("Ran 1 test OK", result)
        mock_run.assert_called_once()

    # ع4 — احتياطي kwargs (target=...) يُحل كـ test_target
    @patch("core.kernel.subprocess_guard.default_guard.run_infra")
    def test_kwargs_fallback_works(self, mock_run):
        mock_run.return_value = (0, "Ran 1 test OK", "")
        result = self.runner.forward(target="tests")
        self.assertIn("Ran 1 test OK", result)
        mock_run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
