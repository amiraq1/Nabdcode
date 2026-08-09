# ⚖️ NABD OS — S-2 · عقد الموافقة الصريحة لـ secure_shell

**العملية:** `S-2 · الموافقة عقد لا زخرفة — لا تنفيذَ بلا موافقةٍ صريحةٍ مسجّلة`
**التاريخ:** 2026-08-09 · **الفرع:** `am8/d-0` · **الرأس:** `28d1aee` (بعد التزام S-1)
**الحالة:** ✅ مكتملة — READY FOR HUMAN SIGNATURE (لا توقيع من الوكيل)

---

## §0 · البوابة — GATE_OK

| الفحص | النتيجة | الدليل |
|---|---|---|
| Termux (PREFIX) | ✅ | `PREFIX=/data/data/com.termux/files/usr` |
| الفرع `am8/d-0` | ✅ | `git rev-parse --abbrev-ref HEAD` |
| الشجرة نظيفة عدا `.kimchi/` | ✅ بعد حكم بشري | كان `HALT_DIRTY` (S-1 غير ملتزم) → التُزم `28d1aee` بموافقتك |
| البصمات المحمية R-4.5.1 | ✅ ثابتة | `42b5c014b36d6c18` · `bf47735d30e0e1c6` · `8bbc623c388d4f02` |

**🔍 إعلان من الخام (لا تصحيح من عندي):** الثابت في نص العقد لـ `status_bar.py` كان `42b5c014b36d2c18` والفعلي `42b5c014b36d6c18` — البرهان: بوابات المشروع الذاتية `.kimchi/r45f.sh:12` و `.kimchi/r451.sh:15` تؤكدان `…6c18` (بالـ 6)، و `git diff` منذ R-4.5.1 فارغ (الملف لم يُمَسّ) ⇒ **خطأ مطبعي في العقد، لا انتهاك بصمة**. لا `HALT_FINGERPRINT`.

**أساس المقارنة:** `SBG_PRE=76efe8a3a72fa443`

---

## §1 · الاستطلاع — الفجوة المقيسة

- **س1:** التوقيع `ConsentCallback = Callable[[str, dict], bool]` (سطر 69: True=يقرّب، False=يحظر). عند غياب الـ callback، السطر 222 `if self._consent is not None and not self._consent(...)` **يتخطّى الموافقة كليًا وينفّذ** ⇒ **fail-OPEN** — جوهر الفجوة.
- **س2:** مساران إنتاجيان يبلغان `run_agent_command`/`default_guard` بلا موافقة:
  - `core/utils.py:79` (`safe_execute_command` ← منفّذ `ShellTool` — مسار الوكيل الفعلي)
  - `core/dag/nodes/terminal.py:52` (عقدة DAG الطرفية — مسار /refactor /dag)
- **س3:** رمز الـ spawn في `_run_simple` هو **`subprocess.run`** (shell=False) — لا Popen.
- **س4:** `SecureShellTool.forward` لا يمر عبر موافقة إطلاقًا (لا ذِكر لـ consent في `tools/secure_tools.py`)؛ يستخدم `run_infra` فقط.

---

## §2 · الحارس الأحمر — وُلد أحمر كما تنبّأ العقد

`tests/test_secure_shell_consent_contract.py` — 3 عقود، callbacks محقونة صراحةً (لا اعتماد على `_default_prompt` الذي يوافق تلقائيًا تحت `PYTEST_CURRENT_TEST`)، والـ spawn مُرقَّع على `subprocess.run`.

```
test_deny_blocks_spawn                PASSED  (ع1)
test_no_consent_is_fail_closed        FAILED  (ع2)  ← assert 0 == -1
test_default_guard_no_consent_is_fail_closed FAILED (ع2) ← assert 0 == -1
test_approve_sanity_spawns            PASSED  (ع3)
2 failed, 2 passed · seed=1431141563 · RED_EXIT=1
```

الفجوة **حية ومقيسة**: الأمر نُفِّذ بلا موافقة. التوقّع طابق الواقع.

---

## §3 · الذرّة الخضراء — مرساة واحدة

`core/kernel/subprocess_guard.py` — أعلى `run_agent_command` (سطر 219)، قبل `validate`:

```python
        S-2 fail-closed consent contract: AGENT_SHELL without a wired consent
        callback NEVER executes — no explicit consent, no spawn, not even a
        validation attempt. Callers must inject a ``ConsentCallback``
        explicitly.
        """
        if self._consent is None:
            return -1, "", "consent required: no consent callback wired for AGENT_SHELL policy"
        ok, reason = validate(command)
```

المرساة: `grep -c` للعبارة = **1** (فريدة). لم يُمَسّ `run_infra`/`run_git`/`_run_simple`/`run_agent_pipeline`/`spawn_agent_background`.

---

## §4 · التحقق

| المرحلة | البذرة | النتيجة |
|---|---|---|
| g1 (مثبّتة) | `20260809` | **4 passed** |
| g2 (مثبّتة) | `20260810` | **4 passed** |
| الحزمة الكاملة (حرة) | `93829852` | **1782 passed, 1 skipped, 0 failed** |
| verify_protocol.sh | — | 12 violation(s) (ديون سابقة — مطابقة للمتوقع) |
| SBG | `76efe8a3a72fa443` → `2da2db81fb14dfb7` | التغيّر المقصود في الحارس فقط |
| البصمات المحمية الثلاث | — | **ثابتة** |

---

## جدول الفرق عن النبوءة

| البند | النبوءة | الفعلي | الحكم |
|---|---|---|---|
| Baseline بعد S-1 | 1778 passed, 1 skipped | 1778 passed, 1 skipped | ✅ مطابق |
| الحزمة بعد الإصلاح | 1781 passed | **1782 passed, 1 skipped** | ⚠️ +1: ع2 يغطي `default_guard` صراحةً (4 دوال لا 3) |
| كسر الاختبارات القديمة | صفر | 7 اختبارات في 5 ملفات | ⚠️ قُيس قبليًا → حكم بشري: حُدّثت بحقن موافقة صريحة |
| `test_run_tests_as_evidence` | — | فشل بيئي لا عقدي | ✅ الناتج الخام: `ModuleNotFoundError: No module named 'rich'` (PATH: `python3` → `/usr/bin/python3`) — نجا بمجرد تصحيح PATH |

---

## §5 · نقاط التوقّف — لا توقّف (كلها نظيفة)

`HALT_NOT_TERMUX` · `HALT_HEAD` · `HALT_DIRTY` (زال بالتزام S-1) · `HALT_INVALID_RED` · `HALT_NO_GAP` · `HALT_WROTE` · `HALT_GUARD_MUTATED` · `HALT_FINGERPRINT` — **لا شيء أُطلق**.

---

## §6 · الملفات المعنية (6 معدَّلة + 1 جديد)

```
 M core/kernel/subprocess_guard.py        ← الذرّة الخضراء (7 أسطر)
 M tests/test_subprocess_guard.py         ← حقن موافقة صريحة (اختباران)
 M tests/test_sanitize.py                 ← حقن موافقة صريحة (اختبار واحد)
 M tests/test_red_team_phase22.py         ← حقن موافقة صريحة (اختبار واحد)
 M tests/test_defect_repairs.py           ← حقن موافقة صريحة (عقدة DAG)
 M tests/test_skills.py                   ← حقن موافقة صريحة (اختباران)
 ?? tests/test_secure_shell_consent_contract.py  ← الحارس الجديد (4 دوال / 3 عقود)
```

---

## 📦 رسالة الالتزام — جاهزة، **غير منفّذة** (التوقيع البشري)

```
Am+9 S-2: الموافقة عقد لا زخرفة — fail-closed عند غياب consent

المشكلة: مسار AGENT_SHELL كان يبلغ الـ spawn بلا موافقة
حين يغيب الـ callback (default_guard) — قياس §1
(core/utils.py:79 ← منفّذ ShellTool، و core/dag/nodes/terminal.py:52).
الحل: فحص fail-closed أعلى run_agent_command؛ لا تنفيذ
بلا موافقة صريحة. ع3 يثبت سلامة مسار الموافقة.
العقود: 3 في test_secure_shell_consent_contract.py
(وُلدت حمراء ثم اخضرّت؛ ع2 يغطي default_guard أيضًا).
اختبارات قديمة حُدّثت (بحكم بشري) لحقن موافقة صريحة:
test_subprocess_guard · test_sanitize · test_red_team_phase22 ·
test_defect_repairs · test_skills.
القياس: الحارس 4 passed ×بذرتين (20260809/20260810)+حزمة؛
suite 1782 passed, 1 skipped؛ verify_protocol 12؛
البصمات المحمية ثابتة.
```

---

## 🗂️ السجل الخام الحرفي

`/data/data/com.termux/files/usr/tmp/nabd-s2/` — `gate · recon · red · g1 · g2 · legacy · suite · suite2 · fixed · verify` (من `GATE_OK` إلى `SENTINEL_ACCEPT`)

**READY FOR HUMAN SIGNATURE** — ولا توقيع من الوكيل، ولا Co-authored-by في أي سطر.
