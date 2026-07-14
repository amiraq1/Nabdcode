"""
project_root_guard.py — طبقة اعتراض مبكرة (Pre-Verification Layer)

تُفحص كل EvidenceRecord هنا *قبل* ما توصل لـ Verifier.verify أصلاً.
الهدف: منع أي دليل يشير فعليًا لمسار خارج جذر المشروع النشط —
سواء عبر:
  - مسار مطلق لمشروع آخر (حادثة 9router الفعلية)
  - traversal نسبي (../../etc/passwd)
  - symlink داخل المشروع يشير فعليًا لخارجه
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class ProjectRootViolation(Exception):
    """يُرفع عند أي دليل يشير لمسار خارج جذر المشروع النشط."""


@dataclass
class EvidenceRecord:
    evidence_id: str
    tool_name: str
    command_or_path: str
    output_snippet: str = ""
    success: bool = True


# امتدادات/أنماط تساعد على تمييز "هذا التوكن مسار" داخل أمر shell عام
_PATH_LIKE_RE = re.compile(r"^[\w\-./~]+$")


class ProjectRootGuard:
    def __init__(self, project_root: str):
        # نحل الجذر نفسه مرة واحدة (يتعامل مع أي symlink بجذر المشروع نفسه)
        self.project_root = Path(project_root).resolve()

    # -----------------------------------------------------------------
    # استخراج مرشحات المسارات من نص حر (مسار مباشر أو أمر shell كامل)
    # -----------------------------------------------------------------
    def _extract_path_candidates(self, command_or_path: str) -> list[str]:
        text = command_or_path.strip()

        # حالة بسيطة: النص كله مسار واحد بدون أي معاملات/فواصل shell
        if _PATH_LIKE_RE.match(text):
            return [text]

        # حالة أمر shell كامل: نفكك بأمان عبر shlex ونلتقط التوكنات
        # اللي تبدو كمسارات (فيها '/' أو تبدأ بـ '~' أو فيها امتداد ملف)
        candidates: list[str] = []
        try:
            # نقسم على فواصل الأوامر الشائعة أولًا (&&, ;, |) قبل shlex
            for chunk in re.split(r"&&|;|\|", text):
                tokens = shlex.split(chunk, posix=True)
                for tok in tokens:
                    if tok.startswith("-"):
                        continue  # علم/flag مثل -v أو --recursive
                    if "/" in tok or tok.startswith("~") or re.search(r"\.\w{1,6}$", tok):
                        candidates.append(tok)
        except ValueError:
            # فشل تفكيك shlex (اقتباس غير متوازن مثلاً) — fail-closed:
            # نعتبر النص كله مرشح مشبوه بدل تجاهله
            candidates.append(text)

        return candidates or [text]

    # -----------------------------------------------------------------
    # حل المسار فعليًا (يتبع أي symlink لوجهته الحقيقية)
    # -----------------------------------------------------------------
    def _resolve_candidate(self, token: str) -> Path | None:
        p = Path(token).expanduser()
        if not p.is_absolute():
            p = self.project_root / p
        try:
            return p.resolve()
        except (OSError, RuntimeError):
            # مسار غير قابل للحل (غير موجود مثلاً) — لا نستطيع تأكيد
            # الاحتواء، لذلك fail-closed: نعامله كخارج الجذر
            return None

    def _is_within_root(self, resolved: Path) -> bool:
        try:
            resolved.relative_to(self.project_root)
            return True
        except ValueError:
            return False

    # -----------------------------------------------------------------
    # الواجهة العامة (نسخة محدّثة: محاكاة cd تراكمية عبر chunks الأمر)
    # -----------------------------------------------------------------
    def check(self, record: EvidenceRecord) -> None:
        text = record.command_or_path.strip()

        # حالة بسيطة: مسار مباشر بدون أي أمر shell — نفس السلوك القديم
        if _PATH_LIKE_RE.match(text):
            self._check_single_path(text, self.project_root, record.evidence_id)
            return

        # حالة أمر shell (مركّب أو بسيط): نحاكي cd تراكميًا chunk بـ chunk
        simulated_cwd = self.project_root
        chunks = re.split(r"&&|;|\|\|?", text)

        for chunk in chunks:
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                tokens = shlex.split(chunk, posix=True)
            except ValueError:
                # فشل تفكيك — fail-closed
                raise ProjectRootViolation(
                    f"Project-root guard rejected evidence {record.evidence_id}: "
                    f"could not safely tokenize shell fragment '{chunk}' "
                    f"(fail-closed on unparsable input)."
                )
            if not tokens:
                continue

            cmd, *args = tokens

            if cmd == "cd":
                target = args[0] if args else "~"
                new_cwd = self._resolve_relative_to(target, simulated_cwd)
                if new_cwd is None or not self._is_within_root(new_cwd):
                    raise ProjectRootViolation(
                        f"Project-root guard rejected evidence {record.evidence_id}: "
                        f"'cd {target}' (from simulated cwd '{simulated_cwd}') moves "
                        f"outside the active project root '{self.project_root}'. "
                        f"(cumulative-cd escape — e.g. 'cd ../../9router && cat "
                        f"core/sanitize.py' is caught here, at the cd step itself.)"
                    )
                simulated_cwd = new_cwd
                continue  # cd نفسه ما يحتاج فحص "مسار ملف" إضافي

            # لأي أمر آخر: نفحص كل توكن يشبه مسار، نسبةً لـ simulated_cwd الحالي
            for tok in args:
                if tok.startswith("-"):
                    continue
                if "/" in tok or tok.startswith("~") or re.search(r"\.\w{1,6}$", tok):
                    self._check_single_path(tok, simulated_cwd, record.evidence_id)

    def _check_single_path(self, token: str, base: Path, evidence_id: str) -> None:
        resolved = self._resolve_relative_to(token, base)
        if resolved is None:
            raise ProjectRootViolation(
                f"Project-root guard rejected evidence {evidence_id}: "
                f"path candidate '{token}' could not be resolved safely "
                f"(fail-closed — unresolved paths are treated as violations)."
            )
        if not self._is_within_root(resolved):
            raise ProjectRootViolation(
                f"Project-root guard rejected evidence {evidence_id}: "
                f"'{token}' resolves to '{resolved}', which is outside "
                f"the active project root '{self.project_root}'. "
                f"(This is the exact class of bug behind the 9router/"
                f"smart-agent path-confusion incident.)"
            )

    def _resolve_relative_to(self, token: str, base: Path) -> Path | None:
        p = Path(token).expanduser()
        if not p.is_absolute():
            p = base / p
        try:
            return p.resolve()
        except (OSError, RuntimeError):
            return None

    def check_all(self, records: Iterable[EvidenceRecord]) -> None:
        for rec in records:
            self.check(rec)
