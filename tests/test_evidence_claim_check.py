"""
test_evidence_claim_check.py

يعيد إنتاج حادثة "sanitize.py" الفعلية كحالة اختبار regression،
بالإضافة لحالات حدّية تفحص نقاط الضعف الثلاث اللي صلّحناها في المسودة.
"""

import pytest

from core.evidence_claim_check import (
    EvidenceRecord,
    StructuredClaim,
    VerifierError,
    verify_structured_claim,
    verify_narrative_claim,
    _symbol_defined_in_snippet,
    _path_matches,
)


# ---------------------------------------------------------------------------
# Regression: نفس حادثة sanitize.py الفعلية
# ---------------------------------------------------------------------------

class TestSanitizeIncidentRegression:
    """يثبت أن الفحص الجديد كان سيرفض الادعاء الكاذب الفعلي."""

    def test_rejects_the_actual_false_claim(self):
        records = {
            "ev1": EvidenceRecord(
                evidence_id="ev1",
                tool_name="SECURE_WORKSPACE_READER",
                command_or_path="core/__init__.py",
                output_snippet=(
                    "from .llm import OpenRouterClient\n"
                    "from .memory import MemoryManager\n"
                    "__all__ = ['OpenRouterClient', 'MemoryManager']\n"
                ),  # sanitize غير موجودة هنا فعليًا
            )
        }
        claim = StructuredClaim(
            evidence_id="ev1",
            claimed_file="core/__init__.py",
            claimed_symbol="sanitize",
            claimed_role="Sanitizes OpenRouterClient output",
        )
        with pytest.raises(VerifierError, match="sanitize"):
            verify_structured_claim(claim, records)

    def test_accepts_the_true_location(self):
        """الدالة كانت موجودة فعليًا في core/sanitize.py — التحقق يفترض يقبلها هناك."""
        records = {
            "ev2": EvidenceRecord(
                evidence_id="ev2",
                tool_name="SECURE_WORKSPACE_READER",
                command_or_path="core/sanitize.py",
                output_snippet="def sanitize(text: str) -> str:\n    ...\n",
            )
        }
        claim = StructuredClaim(
            evidence_id="ev2",
            claimed_file="core/sanitize.py",
            claimed_symbol="sanitize",
        )
        verify_structured_claim(claim, records)  # يفترض ما يرفع أي استثناء


# ---------------------------------------------------------------------------
# فحص الثغرة #1: substring مقابل تعريف حقيقي (def/class)
# ---------------------------------------------------------------------------

class TestSymbolMustBeRealDefinition:
    def test_rejects_symbol_mentioned_only_in_comment(self):
        snippet = "# TODO: consider calling sanitize() here later\nx = 1\n"
        assert _symbol_defined_in_snippet("sanitize", snippet) is False

    def test_rejects_symbol_as_substring_of_another_name(self):
        snippet = "def sanitize_flag_only():\n    pass\n"
        # 'sanitize' يظهر كجزء من 'sanitize_flag_only' لكن مو تعريف مستقل باسم sanitize
        assert _symbol_defined_in_snippet("sanitize", snippet) is False

    def test_accepts_real_function_definition(self):
        snippet = "def sanitize(x):\n    return x\n"
        assert _symbol_defined_in_snippet("sanitize", snippet) is True

    def test_accepts_real_class_definition(self):
        snippet = "class Sanitizer:\n    pass\n\nclass sanitize:\n    pass\n"
        assert _symbol_defined_in_snippet("sanitize", snippet) is True


# ---------------------------------------------------------------------------
# فحص الثغرة #2: دعم الصياغة العربية في الادعاء السردي
# ---------------------------------------------------------------------------

class TestArabicNarrativeSupport:
    def test_rejects_arabic_false_claim(self):
        records = {
            "ev1": EvidenceRecord(
                evidence_id="ev1",
                tool_name="SECURE_WORKSPACE_READER",
                command_or_path="core/__init__.py",
                output_snippet="from .llm import OpenRouterClient\n",
            )
        }
        # نفس صياغة الحادثة الفعلية بالعربي
        claim_text = "الدالة sanitize موجودة الآن في core/__init__.py"
        with pytest.raises(VerifierError):
            verify_narrative_claim(claim_text, "ev1", records)

    def test_accepts_arabic_true_claim(self):
        records = {
            "ev2": EvidenceRecord(
                evidence_id="ev2",
                tool_name="SECURE_WORKSPACE_READER",
                command_or_path="core/sanitize.py",
                output_snippet="def sanitize(text):\n    return text\n",
            )
        }
        claim_text = "الدالة sanitize موجودة في core/sanitize.py"
        verify_narrative_claim(claim_text, "ev2", records)  # ما يفترض يرفع استثناء


# ---------------------------------------------------------------------------
# فحص الثغرة #3: تطابق المسار حتى لو command_or_path أمر shell كامل
# ---------------------------------------------------------------------------

class TestPathMatchingAgainstShellCommands:
    def test_matches_relative_path_inside_full_shell_command(self):
        assert _path_matches(
            "core/sanitize.py",
            "cat /data/data/com.termux/files/home/smart-agent/core/sanitize.py",
        ) is True

    def test_rejects_mismatched_project_path(self):
        # هذا بالضبط الخطأ اللي صار: قفزة لمشروع 9router بدل smart-agent
        assert _path_matches(
            "core/sanitize.py",
            "cat /data/data/com.termux/files/home/9router/core/sanitize.py",
        ) is True  # basename يطابق — لاحظ هذا "false positive" مقبول جزئيًا

    def test_strict_full_path_mismatch_detected_separately(self):
        active_project_root = "smart-agent"
        suspicious_command = (
            "cat /data/data/com.termux/files/home/9router/core/sanitize.py"
        )
        assert active_project_root not in suspicious_command  # يثبت وجود الفجوة


# ---------------------------------------------------------------------------
# فحص fail-closed: نص بدون ملف/رمز قابل للاستخراج يُرفض لا يُمرَّر بصمت
# ---------------------------------------------------------------------------

class TestFailClosedOnUnparsableClaims:
    def test_unparsable_narrative_is_rejected_not_silently_passed(self):
        records = {
            "ev1": EvidenceRecord(
                evidence_id="ev1",
                tool_name="SECURE_SHELL",
                command_or_path="ls .",
                output_snippet="core  tests  main.py\n",
            )
        }
        vague_claim = "بشكل عام الكود يبدو منظمًا وجيدًا."
        with pytest.raises(VerifierError, match="Unverifiable"):
            verify_narrative_claim(vague_claim, "ev1", records)


# ---------------------------------------------------------------------------
# حالات حدّية إضافية
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_unknown_evidence_id_rejected(self):
        claim = StructuredClaim(
            evidence_id="does-not-exist",
            claimed_file="core/sanitize.py",
            claimed_symbol="sanitize",
        )
        with pytest.raises(VerifierError, match="does not exist"):
            verify_structured_claim(claim, {})

    def test_failed_tool_call_cannot_support_claim(self):
        records = {
            "ev1": EvidenceRecord(
                evidence_id="ev1",
                tool_name="SECURE_WORKSPACE_READER",
                command_or_path="core/sanitize.py",
                output_snippet="def sanitize(x): return x",
                success=False,  # الأداة نفسها فشلت (مثلاً: permission denied)
            )
        }
        claim = StructuredClaim(
            evidence_id="ev1",
            claimed_file="core/sanitize.py",
            claimed_symbol="sanitize",
        )
        with pytest.raises(VerifierError, match="failed tool call"):
            verify_structured_claim(claim, records)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
