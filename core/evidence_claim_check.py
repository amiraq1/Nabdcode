"""
evidence_claim_check.py — إضافة مقترحة لـ core/evidence.py

يعالج ثغرة "الهلوسة الدلالية" (semantic confabulation) اللي اكتشفناها:
وكيل يفشل بالعثور على رمز (function/class) في ملف، فيقفز لادعاء
موقع/وظيفة من الذاكرة الدلالية بدل الاعتراف بالفشل.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional


class VerifierError(Exception):
    """يُرفع عند رفض ادعاء غير مدعوم بدليل حرفي."""


# ---------------------------------------------------------------------------
# الدفاع الأول (المفضّل): بنية صريحة بدل نص حر
# ---------------------------------------------------------------------------

@dataclass
class StructuredClaim:
    """
    ادعاء صريح يجب على الوكيل ملأه عند التصريح بوجود رمز في ملف،
    بدل صياغة جملة سردية حرة. أي ادعاء بهذا الشكل يُتحقق منه
    آليًا وبدقة 100% (لا اعتماد على تحليل نص).
    """
    evidence_id: str
    claimed_file: str          # المسار كما يدّعيه الوكيل
    claimed_symbol: str        # اسم الدالة/الكلاس المدّعى
    claimed_role: Optional[str] = None  # وصف اختياري لوظيفة الرمز (لا يُتحقق آليًا)


@dataclass
class EvidenceRecord:
    evidence_id: str
    tool_name: str              # مثال: "SECURE_WORKSPACE_READER" أو "SECURE_SHELL"
    command_or_path: str        # المسار أو أمر الـ shell الكامل كما نُفّذ فعليًا
    output_snippet: str         # المخرج الخام الفعلي من الأداة
    success: bool = True


def _normalize_path(p: str) -> str:
    """يطبّع المسار: يشيل المسافات، يوحّد الفواصل، يرجع basename+parents نسبيًا."""
    p = p.strip().strip("`'\"")
    p = p.replace("\\", "/")
    return os.path.normpath(p)


def _path_matches(claimed_file: str, command_or_path: str) -> bool:
    """
    يتحقق إن الملف المدّعى فعليًا هو نفسه اللي فحصته الأداة —
    حتى لو كان command_or_path أمر shell كامل (مثل 'cat /full/path/x.py').
    """
    claimed_norm = _normalize_path(claimed_file)
    # نبحث عن claimed_norm كنهاية مسار داخل command_or_path (يغطي absolute/relative)
    haystack_norm = command_or_path.replace("\\", "/")
    return claimed_norm in haystack_norm or os.path.basename(claimed_norm) in haystack_norm


def _symbol_defined_in_snippet(symbol: str, snippet: str) -> bool:
    """
    يتحقق من وجود *تعريف حقيقي* للرمز (def/class) داخل المخرج الخام —
    مو مجرد ظهور الكلمة في أي سياق (تعليق، docstring، اسم متغير مشابه).
    """
    pattern = rf"\b(?:def|class)\s+{re.escape(symbol)}\b"
    return re.search(pattern, snippet) is not None


def verify_structured_claim(claim: StructuredClaim, records: dict[str, EvidenceRecord]) -> None:
    """
    التحقق الصارم (الدفاع الأول). يرفع VerifierError عند أي تناقض.
    """
    rec = records.get(claim.evidence_id)
    if rec is None:
        raise VerifierError(
            f"Verification Failed: claim references evidence_id "
            f"'{claim.evidence_id}' which does not exist in the records."
        )

    if not rec.success:
        raise VerifierError(
            f"Verification Failed: evidence {rec.evidence_id} is marked "
            f"as a failed tool call and cannot support a positive claim."
        )

    if not _path_matches(claim.claimed_file, rec.command_or_path):
        raise VerifierError(
            f"Verification Failed: claim states file '{claim.claimed_file}' "
            f"but evidence {rec.evidence_id} actually inspected "
            f"'{rec.command_or_path}'."
        )

    if not _symbol_defined_in_snippet(claim.claimed_symbol, rec.output_snippet):
        raise VerifierError(
            f"Verification Failed: claim asserts '{claim.claimed_symbol}' is "
            f"defined in '{claim.claimed_file}', but no literal "
            f"'def {claim.claimed_symbol}' or 'class {claim.claimed_symbol}' "
            f"was found in the actual tool output of {rec.evidence_id}. "
            f"This is the exact failure mode observed in the sanitize.py "
            f"incident — reject rather than trust the narrative."
        )


# ---------------------------------------------------------------------------
# الدفاع الثاني (احتياطي): استخراج من نص حر عربي/إنجليزي
# ---------------------------------------------------------------------------

# يدعم صيغ متعددة: found in / defined in / located in / موجودة في / موجود في / يوجد في
CLAIM_FOUND_IN_RE = re.compile(
    r"(?:found in|defined in|located in|in file|"
    r"موجود(?:ة)? في|يوجد(?:ة)? في)\s*"
    r"[`'\"]?([\w\-./]+\.[A-Za-z0-9]+)[`'\"]?",
    re.IGNORECASE,
)

# يدعم: function/class/def/method X أو الدالة/الكلاس X
SYMBOL_CLAIM_RE = re.compile(
    r"(?:function|class|def|method|"
    r"(?:ال)?دالة|(?:ال)?كلاس)\s+"
    r"[`'\"]?(\w+)[`'\"]?",
    re.IGNORECASE,
)


def verify_narrative_claim(claim_text: str, evidence_id: str,
                            records: dict[str, EvidenceRecord]) -> None:
    """
    الدفاع الثاني (احتياطي فقط) — يُستخدم لو ما زال النظام عندك يمرر
    ادعاءات كنص حر بدل StructuredClaim. أضعف من الدفاع الأول بطبيعته
    (يعتمد على صياغة الوكيل)، لذلك لا يُعتمد عليه وحده في نظام جديد.
    """
    rec = records.get(evidence_id)
    if rec is None:
        raise VerifierError(f"Unknown evidence_id: {evidence_id}")

    file_match = CLAIM_FOUND_IN_RE.search(claim_text)
    symbol_match = SYMBOL_CLAIM_RE.search(claim_text)

    if file_match:
        claimed_file = file_match.group(1)
        if not _path_matches(claimed_file, rec.command_or_path):
            raise VerifierError(
                f"Verification Failed: claim states '{claimed_file}' but "
                f"evidence {rec.evidence_id} inspected '{rec.command_or_path}'."
            )

    if symbol_match:
        claimed_symbol = symbol_match.group(1)
        if not _symbol_defined_in_snippet(claimed_symbol, rec.output_snippet):
            raise VerifierError(
                f"Verification Failed: claim asserts symbol '{claimed_symbol}' "
                f"is defined, but no literal 'def {claimed_symbol}' or "
                f"'class {claimed_symbol}' appears in the verified output "
                f"of {rec.evidence_id}."
            )

    if not file_match and not symbol_match:
        raise VerifierError(
            f"Unverifiable claim: narrative text did not match any known "
            f"file/symbol pattern. Rejecting by default (fail-closed) "
            f"rather than assuming it is safe. Evidence: {rec.evidence_id}."
        )
