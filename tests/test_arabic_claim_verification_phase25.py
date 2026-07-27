"""
test_arabic_claim_verification_phase25.py — Arabic pattern coverage for claim gate + L2 verifier.

Every Arabic pattern has a reject-test AND an accept-test.
English gates remain active alongside Arabic additions.
"""

from core.evidence import EvidenceLog, SemanticVerifier, EvidenceRecord
from core.verifier import check_final_answer_claim_gate, _normalize_arabic_for_matching


# ═══════════════════════════════════════════════════════════════════════
# Normalization unit tests
# ═══════════════════════════════════════════════════════════════════════

def test_indic_digits_normalized():
    assert _normalize_arabic_for_matching("٩٩٩") == "999"
    assert _normalize_arabic_for_matching("عدد الاختبارات: ٤٢") == "عدد الاختبارات: 42"
    assert _normalize_arabic_for_matching("٠١٢٣٤٥٦٧٨٩") == "0123456789"


def test_hamza_unified():
    assert _normalize_arabic_for_matching("إختبارات") == "اختبارات"
    assert _normalize_arabic_for_matching("أخطاء") == "اخطاء"
    assert _normalize_arabic_for_matching("إيداع") == "ايداع"


def test_tatweel_removed():
    assert _normalize_arabic_for_matching("اختبارـ") == "اختبار"


# ═══════════════════════════════════════════════════════════════════════
# Pattern A1 — Arabic "all tests passed"
# ═══════════════════════════════════════════════════════════════════════

def test_arabic_all_passed_without_evidence_rejected():
    """جميع الاختبارات نجحت without evidence → rejected."""
    log = EvidenceLog()
    log.record(tool="file_system", command_or_path="README.md", success=True,
               output_snippet="readme")
    result = check_final_answer_claim_gate("جميع الاختبارات نجحت", log)
    assert not result.passed, (
        f"Arabic 'all tests passed' without pytest evidence: {result.unsupported_claims}"
    )


def test_arabic_all_passed_with_evidence_accepted():
    """جميع الاختبارات نجحت with matching execute_shell evidence → accepted."""
    log = EvidenceLog()
    log.record(tool="execute_shell", command_or_path="pytest", success=True,
               output_snippet="نجحت جميع الاختبارات: 50 passed")
    result = check_final_answer_claim_gate("جميع الاختبارات نجحت", log)
    assert result.passed, (
        f"Arabic 'all tests passed' with matching evidence: {result.unsupported_claims}"
    )


def test_arabic_hamza_variant_not_bypass():
    """إختبارات with hamza must still be caught (normalized to اختبارات)."""
    log = EvidenceLog()
    log.record(tool="file_system", command_or_path="README.md", success=True,
               output_snippet="readme")
    result = check_final_answer_claim_gate("جميع الإختبارات نجحت", log)
    assert not result.passed, (
        "Hamza variant must not bypass the gate"
    )


# ═══════════════════════════════════════════════════════════════════════
# Pattern A2 — Arabic count claims
# ═══════════════════════════════════════════════════════════════════════

def test_arabic_count_without_pytest_evidence_rejected():
    """تم تشغيل 99 اختبار ونجحت without execute_shell evidence → rejected."""
    log = EvidenceLog()
    log.record(tool="file_system", command_or_path="README.md", success=True,
               output_snippet="readme")
    result = check_final_answer_claim_gate("تم تشغيل 99 اختبار ونجحت", log)
    assert not result.passed, (
        f"Arabic count claim without evidence: {result.unsupported_claims}"
    )


def test_arabic_count_mismatch_rejected():
    """تم تشغيل 99 اختبار but evidence shows 500 → rejected."""
    log = EvidenceLog()
    log.record(tool="execute_shell", command_or_path="pytest", success=True,
               output_snippet="تم تشغيل 500 اختبار")
    result = check_final_answer_claim_gate("تم تشغيل 99 اختبار", log)
    assert not result.passed, (
        f"Arabic count mismatch must be rejected: {result.unsupported_claims}"
    )


def test_arabic_indic_digits_normalized_and_checked():
    """Arabic-Indic ٩٩٩ normalized to 999, then checked against evidence."""
    log = EvidenceLog()
    # Evidence contains 999 in Arabic-Indic
    log.record(tool="execute_shell", command_or_path="pytest", success=True,
               output_snippet="عدد الاختبارات: ٩٩٩")
    # Claim uses "عدد الاختبارات: ٩٩٩" with Indic digits → normalized to 999
    result = check_final_answer_claim_gate("عدد الاختبارات: ٩٩٩", log)
    assert result.passed, (
        f"Arabic-Indic digits should match when evidence has same count: "
        f"{result.unsupported_claims}"
    )


def test_arabic_indic_digits_mismatch_rejected():
    """Claim ٩٩٩ but evidence shows 500 → rejected."""
    log = EvidenceLog()
    log.record(tool="execute_shell", command_or_path="pytest", success=True,
               output_snippet="تم تشغيل 500 اختبار")
    result = check_final_answer_claim_gate("عدد الاختبارات: ٩٩٩", log)
    assert not result.passed, (
        f"Arabic-Indic 999 with evidence showing 500: {result.unsupported_claims}"
    )


# ═══════════════════════════════════════════════════════════════════════
# Pattern A3 — Arabic "no errors" requires exec evidence
# ═══════════════════════════════════════════════════════════════════════

def test_arabic_no_errors_without_exec_evidence_rejected():
    """لا توجد أخطاء requires execute_shell/run_tests evidence, not file_system."""
    log = EvidenceLog()
    log.record(tool="file_system", command_or_path="README.md", success=True,
               output_snippet="readme")
    result = check_final_answer_claim_gate("لا توجد أخطاء", log)
    assert not result.passed, (
        f"'لا توجد أخطاء' with only file_system evidence: {result.unsupported_claims}"
    )


def test_arabic_no_errors_with_exec_evidence_accepted():
    """لا توجد أخطاء with execute_shell evidence → accepted."""
    log = EvidenceLog()
    log.record(tool="execute_shell", command_or_path="pytest", success=True,
               output_snippet="نجحت جميع الاختبارات")
    result = check_final_answer_claim_gate("لا توجد أخطاء", log)
    assert result.passed, (
        f"'لا توجد أخطاء' with exec evidence: {result.unsupported_claims}"
    )


# ═══════════════════════════════════════════════════════════════════════
# Pattern A4 — Arabic commit/push
# ═══════════════════════════════════════════════════════════════════════

def test_arabic_commit_claim_without_git_evidence_rejected():
    """تم commit abc1234 without git evidence → rejected."""
    log = EvidenceLog()
    log.record(tool="file_system", command_or_path="README.md", success=True,
               output_snippet="readme")
    result = check_final_answer_claim_gate("تم commit abc1234 وتم push", log)
    assert not result.passed, (
        f"Arabic commit claim without git evidence: {result.unsupported_claims}"
    )


# ═══════════════════════════════════════════════════════════════════════
# Over-block guard — benign Arabic phrases must pass
# ═══════════════════════════════════════════════════════════════════════

def test_benign_arabic_phrase_not_blocked():
    """Normal Arabic analysis phrases must NOT be blocked."""
    log = EvidenceLog()
    log.record(tool="execute_shell", command_or_path="pytest", success=True,
               output_snippet="تم التحليل")
    for phrase in [
        "تم تحليل الكود بنجاح",
        "تمت قراءة الملف",
        "تم البحث في المشروع",
    ]:
        result = check_final_answer_claim_gate(phrase, log)
        assert result.passed, (
            f"Benign Arabic phrase should not be blocked: {phrase!r}"
        )


# ═══════════════════════════════════════════════════════════════════════
# English gates remain active
# ═══════════════════════════════════════════════════════════════════════

def test_english_gates_still_active_after_arabic_addition():
    """English patterns must still reject unsupported claims."""
    log = EvidenceLog()
    log.record(tool="file_system", command_or_path="README.md", success=True,
               output_snippet="readme")
    result = check_final_answer_claim_gate("Ran 999 tests successfully.", log)
    assert not result.passed, (
        f"English 'Ran N tests' must still be rejected: {result.unsupported_claims}"
    )
    result2 = check_final_answer_claim_gate("all tests passed", log)
    assert not result2.passed, (
        f"English 'all tests passed' must still be rejected: {result2.unsupported_claims}"
    )


# ═══════════════════════════════════════════════════════════════════════
# L2 SemanticVerifier Arabic extraction
# ═══════════════════════════════════════════════════════════════════════

def test_l2_arabic_count_extracted_and_checked():
    """L2 must extract Arabic count from 'عدد الاختبارات ٩٩٩' and check evidence."""
    records = {}
    result = SemanticVerifier.verify("عدد الاختبارات ٩٩٩", records)
    assert not result.ok, (
        f"L2 must reject Arabic-Indic ٩٩٩ without matching evidence: {result.findings}"
    )


def test_l2_arabic_count_matches_evidence():
    """L2 must accept Arabic count when evidence contains the normalized number."""
    records = {
        "E-1": EvidenceRecord(
            evidence_id="E-1", tool="execute_shell",
            command_or_path="pytest", success=True,
            output_snippet="عدد الاختبارات: 999",
        ),
    }
    result = SemanticVerifier.verify("عدد الاختبارات ٩٩٩", records)
    assert result.ok, (
        f"L2 must accept Arabic-Indic ٩٩٩ with matching evidence: {result.findings}"
    )
