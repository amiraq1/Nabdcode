# L2 — تشريح جنائي: الطبقات 1-3

**المنهج:** CORE_FILE_DNA_DISSECTION v2 (docs/CORE_FILE_DNA_DISSECTION.md)
**المرجع:** amiraq1/Nabdcode @ am8/d-0 — HEAD `63e7899b954f2dc2487a17191385c741c7bc66a0` (worktree يتضمن موجات NBD A–E غير ملتزمة)
**التاريخ:** 2026-08-12
**البيئة:** Termux Linux (Python 3.14.6 — `python` Termux، pytest 9.1.1)، تبعيات مثبتة: prompt_toolkit/rich/pydantic/cryptography
**طريقة التحقق:** static reading + unit tests المنفذة في الجلسة (حزمة كاملة: 2051 passed) + تحقق تجريبي مباشر لسلوكيات مختارة
**سياسة الأسرار:** لم تُطبع أي مفاتيح أو قيم env حساسة
**قيود التشغيل:** لا أوامر مدمرة/شبكة حقيقية/دفع Git — كل التحقق عبر اختبارات وهمية أو أوامر read-only

> ملاحظة نطاق: الطبقات 4-5 (consent/_dispatch + الاختبارات/CI) مشمولة في L1 من تقرير تنفيذ NBD؛ يُستكمل L2 لها في دورة لاحقة.

> **تحديث (ملحق التحقق، 2026-08-12):** خضعت هذه الوثيقة لمراجعة خارجية قرأت `main` (لقطة `f7dd0c0`) لا تحوي إصلاحاتنا غير الملتزمة. صُحّح قسم الخلاصة ليعكس الحالة على `main` (1 P0، 5 P1، 5 P2 مؤكدة، وCFD-guard-1 غير مثبت)، مع جدول الإغلاق المحلي (شفرة + اختبارات على am8/d-0) وBacklog الـ 6 PRs. النتائج المؤكدة (pyproject-1، fs-2، registry-1، appctx-1) أُغلقت محلياً باختبارات `tests/test_cfd_fixes.py` (8/8 أخضر).

---

# الطبقة 1 — التغليف ونقاط الدخول

## 1.1 pyproject.toml (54 سطراً)

### الهوية والواجهة

| الحقل | القيمة | الدليل |
|---|---|---|
| الحزمة | nabd-os 1.0.0 | pyproject@:4-6 |
| نقطة الدخول | `nabdcode = "main:main"` | pyproject@:17-18 |
| Python | >=3.11 | pyproject@:10 |
| الاعتماديات المعلنة | prompt_toolkit, rich, pydantic | pyproject@:11-15 |
| الحزم (NBD-01) | `packages.find` include adapters/core/engine/skills/smolagents/tools/ui | pyproject@:30-32 |
| بيانات الحزمة | `skills = ["*.md"]` + include-package-data | pyproject@:23,33-34 |

### Coverage Map

| المسار | الحالة |
|---|---|
| سعيد: بناء wheel ← تثبيت نظيف ← استيراد مسار الإقلاع | ✅ موثق ومختبر (`test_nbd01_wheel_clean_install_imports_runtime_packages`) |
| رفض: حزمة مغفلة | ✅ pre-fix كان `ModuleNotFoundError` — مغلق باختبار |
| بيانات غير Python (skills/*.md) | ✅ في wheel + اختبار محتويات |
| تثبيت وسط وجود نسخة نظامية قديمة | ⚠️ shadowing حقيقي — الاختبار يتعامل عبر `--force-reinstall` في venv |

### النتائج

**CFD-pyproject-1 — اعتماد `cryptography` غير معلن (P1, DERIVED, High)**
- Location: pyproject@:11-15 + core/config.py@:37-38,100-105
- Claim: `ConfigManager` يستورد `cryptography.hazmat` كاستيراد كسول لتشفير AES-GCM، لكن الحزمة غير مذكورة في pyproject ولا requirements.txt — تثبيت نظيف بلا `cryptography` ينهار عند أول حفظ مفتاح.
- Impact: فقدان قدرة BYOK في بيئة نظيفة (مسار الإقلاع يستورد main لكن استخدام المفاتيح يرفع ImportError).
- Verification: `python -c "import cryptography"` نجح محلياً (46.0.7) لأنه مثبت في البيئة فقط؛ بيئة جديدة `pip install .` لن تجلبه.
- Recommendation: إضافة `cryptography>=42` إلى `[project].dependencies`.
- Regression test: `test_nbd01` يجب أن يشمل `import core.config; ConfigManager().set_api_key(...)` في الـ smoke.
- Decision: **Create issue** (P1) — إصلاح سطر واحد.

**CFD-pyproject-2 — إصدار ثابت 1.0.0 رغم تغييرات hardening (P2, DERIVED, Medium)**
- Location: pyproject@:5
- Claim: بعد موجات NBD لا يوجد bump إصدار، وخطر إعادة استخدام رقم منشور عند النشر.
- Recommendation: bump عند الإصدار التالي عبر بوابة الـ publish اليدوية.
- Decision: **Create issue** (عملية إصدار).

**CFD-pyproject-3 — غياب metadata نشر (license/urls) (P3, DIRECT, Low)**
- Decision: **No action**.

## 1.2 core/app_context.py (196 سطراً) — سجل الأدوات ومسار الإقلاع

### Coverage Map

| المسار | الحالة |
|---|---|
| سعيد: build() يسجّل كل الأدوات | ✅ probe: REGISTERED 24+ tool |
| بوابة NBD-02 (python_repl) | ✅ OFF → غير مسجلة، ON → مسجلة (اختبار) |
| اكتشاف تلقائي للأدوات الجديدة | ⚠️ معطوب جزئياً (انظر CFD-appctx-1) |
| مسار TaskTool | ✅ fail-open بلا كسر للإقلاع |

### النتائج

**CFD-appctx-1 — `discover_tools(cls)` يمرر الكلاس بدل السياق (P2, DIRECT, High)**
- Location: app_context.py@:155 + core/tool_factory.py@:59-60
- Claim: الاستدعاء يمرر `cls` (الكلاس) بينما `_build_tool_with_deps` يقرأ `app_context.config/…` — كل الاعتمادات تظهر None فيُسقَط أي أداة تحتاج معاملات، بصمت (fail-open).
- Impact: اكتشاف الأدوات الجديدة «أعمى عن الحقن» — يعمل فقط للأدوات ذات الافتراضيات.
- Verification: قراءة الأكواد (DIRECT)؛ تشغيل build() يُظهر عدم وجود أدوات مكتشفة بالاعتمادات.
- Recommendation: بناء `_discovery_ctx` مؤقت بسياق حقيقي (config/security_engine/…) قبل الاستدعاء، أو تمرير `self`.
- Regression test: تسجيل أداة جديدة تتطلب `workspace` ويجب أن تظهر.
- Decision: **Create issue** (P2).

**CFD-appctx-2 — build() له آثار جانبية على نظام الملفات (P2, DIRECT, Medium)**
- Location: app_context.py@:63-78
- Claim: يعيد ضبط STATE.md (RepositoryContextManager.reset_session_state) ويُنشئ `.nabd/journal` وworkspace_memory.db في مساحة العمل — استيراد `main`/build ليس نقيّاً.
- Impact: اختبارات/حاويات تشارك مساحة العمل قد تتداخل؛ موثق جزئياً.
- Decision: **No action** (سلوك مقصود؛ نُفِّذت عزلته في اختباراتنا عبر NABD_ROOT_DIR).

**CFD-appctx-3 — البلع الصامت لتعارضات التسجيل (P3, DERIVED, Low)**
- Location: app_context.py@:145-147
- Claim: `except ValueError: pass` عند الازدواج يخفي تعارض أسماء حقيقي بلا سجل.
- Decision: **No action** (مقبول fail-open؛ يُفضَّل سطر log مستقبلاً).

## 1.3 engine/tool_registry.py (58 سطراً)

**CFD-registry-1 — اسم افتراضي `unnamed_tool` يتسرب للسجل (P2, DIRECT, Medium)**
- Location: tools/base.py@:174 (`name: str = "unnamed_tool"`) + سجل الـ registry في probe build()
- Claim: `BaseTool.name` له افتراضي `"unnamed_tool"`، وظهرت أداة بهذا الاسم في السجل الفعلي بعد build() — أداة مسجلة بلا اسم ذي معنى يستطيع الوكيل استدعاءها.
- Impact: تشويش على النموذج وcall صامت محتمل لأداة «غير مسماة».
- Verification: probe `AppContext.build(auto_discover=False)` → `'unnamed_tool' in registry._tools` (DIRECT).
- Recommendation: رفض التسجيل عندما يكون الاسم هو الافتراضي، أو إلزام كل صنف بتعريف `name`.
- Regression test: `test_registry_rejects_default_name`.
- Decision: **Create issue** (P2).

# الطبقة 2 — تنفيذ الأوامر وحدود الثقة

## 2.1 core/kernel/subprocess_guard.py (661 سطراً)

### الواجهة والاعتماديات

| الواجهة | الأسطر | الغرض |
|---|---|---|
| `run_agent_command(command, timeout, tool_name, args)` | 206-243 | أمر وكيل مع validate + consent |
| `run_agent_pipeline(command, timeout)` | 245-339 | أنابيب shell=False |
| `spawn_agent_background(command)` | 341-416 | خلفية مُدارة (NBD-06) |
| `stop_background(pid)` / `background_pids()` | 418-471 | إيقاف/حصاد |
| `run_git(args, cwd, timeout)` | 473-493 | git مع containment |
| `run_infra` / `spawn_infra` | 495-611 | عمليات داخلية |
| `_run_simple` / `_run_tokens` | 613-661 | تنفيذ نهائي shell=False |

الاعتماديات: `core.kernel.security` فقط (جزيرة kernel بلا ربط بـ core/engine).

### Coverage Map

| المسار | الحالة |
|---|---|
| سعيد: أمر بسيط | ✅ `cat file` (اختبارات NBD-04) |
| رفض أمني: validate / consent / arg-scan | ✅ كل مسارات الرفض تعيد `(-1,"",reason)` |
| استثناءات: TimeoutExpired / FileNotFound / OSError | ✅ containment موحد |
| timeout/cancellation: pipeline + background | ✅ kill للمجموعة + wait |
| غير متحقق: سلوك consent callback عند التركيب المباشر بالحلقة | ⚠️ يلزم اختبار قطبية (CFD-guard-1) |

### النتائج

**CFD-guard-1 — عقد قطبية consent callback غير مُختبر (P2, DERIVED, High → **غير مثبت كعيب** وفق ملحق التحقق)**
- Location: subprocess_guard.py@:227-231 + core/command_dispatcher.py@:78-82
- Claim: `run_agent_command` يحجب عندما تكون قيمة callback falsy، بينما `ConsentManager.confirm` تُرجع `None` عند الموافقة — الترابط الصحيح يتطلب تحويلاً (`is None`)، وأي تركيب مباشر للحلقة يعكس القطبية (الموافقة → حجب والعكس).
- Impact: خطر انعكاس دلالي في أي مسار جديد يربط المدير مباشرة.
- Verification: قراءة الكودين (DERIVED من مصدرين DIRECT).
- **حكم ملحق التحقق (2026-08-12):** المسار الحي `/refactor` يحوّل عبر `confirm(...) is None` (قطبية صحيحة — موافقة→True، رفض→False)، ولم يظهر caller معاكس. **لا تُسجَّل كعيب** حتى يظهر caller معكوس أو اختبار فاشل. الإجراء: اختبار عقد فقط (نُفّذ: `test_cfd_guard1_consent_callback_polarity` + `test_cfd_guard1_guard_runs_on_approve_blocks_on_deny`) — لا issue إصلاح.
- Recommendation: اختبار قطبية + توثيق العقد على الواجهة.
- Regression test: `test_cfd_guard1_consent_callback_polarity` (مُضاف، 2/2 أخضر).
- Decision: **No action** (اختبار عقد فقط — وفق الملحق).

**CFD-guard-2 — `_args_safe_for_execution` قد يرفض بيانات مشروعة (P2, DIRECT, Medium)**
- Location: subprocess_guard.py@:64-67 (قاعدة base64 ≥60)
- Claim: كتلة base64 طويلة داخل وسيط بيانات مشروع (مفتاح/رمز) في مسار INFRA تُرفض — إنذار كاذب محتمل.
- Decision: **Create issue** (مراجعة عتبات الماسح).

**CFD-guard-3 — إعادة ترميز مزدوجة (validate ثم shlex في `_run_simple`) (P3, DERIVED, Low)**
- Location: subprocess_guard.py@:613-635
- Claim: حتمية لكنها تكرار عمل؛ لا ثغرة لأن `shlex.split` حتمي.
- Decision: **No action** (NBD-04 وثّق أن النص الأصلي يُمرر).

## 2.2 core/kernel/security.py (359 سطراً)

### Coverage Map

| المسار | الحالة |
|---|---|
| سعيد: أمر whitelisted | ✅ echo/cat/ls |
| رفض: عاملات خطرة غير مقتبسة | ✅ `_dangerous_operators_unquoted`@149 |
| رفض: binary غير مدرج | ✅ «Binary 'printf' is not whitelisted.» |
| رفض: install commands / pipe إلى interpreter | ✅ validate@311 |
| غير متحقق: أداء الماسح على أوامر ضخمة | ⚠️ لا benchmark (N/A للاستخدام الفردي) |

### النتائج

**CFD-sec-1 — سلسلة التحقق متعددة الطبقات سليمة (P2, DIRECT, High)**
- Location: security.py@:311-359
- Claim: validate() = اعتراض install + عاملات غير مقتبسة + tokenize quote-aware + whitelist + مسح متجه الوسائط — دفاع متعمق متسق.
- Decision: **No action**.

**CFD-sec-2 — جذر مساحة العمل عمومي على مستوى الوحدة (P2, DERIVED, Medium)**
- Location: security.py@:29-45
- Claim: `_WORKSPACE_ROOT` يُثبَّت عند الإقلاع؛ أي مسار تنفيذ يعيد ضبطه أثناء التشغيل (من build() آخر) يحرّك حد الاحتواء لكل الحرس — اعتماد على ترتيب الإقلاع الأحادي.
- Decision: **No action** (مقيد بالتصميم؛ موثق في conftest).

**CFD-sec-3 — القائمة البيضاء تحتاج سياسة نمو (P3, INFERRED, Low)**
- Location: security.py@:274-308
- Claim: كل binary جديد يتطلب تحديث القائمة يدوياً؛ لا يوجد إجراء موثق للتوسعة.
- Decision: **No action** (ملاحظة للصيانة).

## 2.3 core/utils.py (168 سطراً)

### النتائج

**CFD-utils-1 — NBD-04/06 مغلقان بالاختبار (P1, DIRECT, High)**
- Location: utils.py@:4 (import subprocess), :78-84 (_handle_simple يمرر النص الأصلي)
- Claim: لا `" ".join(args)` بعد tokenization؛ `except subprocess.TimeoutExpired` يعمل الآن — مغلق بـ `test_nbd04_*` و`test_nbd06_safe_execute_returns_tuple_on_internal_error`.
- Decision: **No action**.

**CFD-utils-2 — `tokens` أصبحت شبه ميتة في المسار البسيط (P3, DERIVED, Low)**
- Location: utils.py@:17-31 مقابل :148-152
- Claim: تُستخدم للتحقق فقط بعد نقل النص الأصلي؛ بقايا نظيفة.
- Decision: **No action** (توثيق في الكود موجود).

**CFD-utils-3 — كشف الخلفية بـ `&` النهائي (P3, DIRECT, Low)**
- Location: utils.py@:46-48,141-145
- Claim: `cmd_str.rstrip().endswith("&")` — اقتباس `&` في آخر سطر لا يمكن تمثيله كوسيط بلا endswith خطأ (ينتهي بعلامة الاقتباس) — سلوك سليم عملياً.
- Decision: **No action**.

# الطبقة 3 — عزل التنفيذ ونزاهة الملفات

## 3.1 tools/python_repl.py (194 سطراً)

### Coverage Map

| المسار | الحالة |
|---|---|
| سعيد (مفعّل): تنفيذ + print | ✅ test_python_repl 9/9 (بـ env ON) |
| رفض: بوابة NBD-02 معطلة | ✅ `capability_unavailable` (افتراضي) |
| رفض: AST filter (system/subprocess/rmtree) | ✅ اختبارات AST |
| timeout: حلقة لانهائية | ✅ circuit breaker 15s |
| غير متحقق: أمان حقيقي عند التفعيل | ⚠️ **لا sandbox بنظام التشغيل** — قدرة خطرة |

### النتائج

**CFD-repl-1 — عزل غير موجود عند التفعيل (P1, DIRECT, High)**
- Location: python_repl.py@:150-180 (تنفيذ عبر `run_infra(["python3", script])` بـ cwd=sandbox فقط)
- Claim: `open`/`pathlib`/شبكة/موارد غير مقيدة عند `NABD_ENABLE_PYTHON_REPL=1`؛ AST filter ليس حداً أمنياً.
- Impact: تنفيذ تعسفي في مساحة العمل إذا فُعِّلت القدرة.
- Recommendation: **إبقاء المعطل افتراضياً** (نافذ الآن) + الموجة D (PRoot/namespace) كشرط للتفعيل.
- Decision: **Security escalation** (P1 — مؤجل للموجة D، لا إعادة تفعيل بفلاتر AST).

**CFD-repl-2 — ملف سكربت ثابت مشترك `temp_execution.py` (P2, DIRECT, Medium)**
- Location: python_repl.py@:146-148
- Claim: ملف واحد يُكتب ويُنفذ لكل طلب — تنازع في الاستخدام المتزامن وسباق قراءة/كتابة.
- Recommendation: ملف فريد لكل طلب (نمط NBD-03 المؤقت).
- Decision: **Create issue** (P2).

**CFD-repl-3 — مرشح AST يعتمد على أسماء attributes (P3, DERIVED, Low)**
- Location: python_repl.py@:60-88
- Claim: `node.attr in FORBIDDEN_CALLS` يرفض حتى استدعاءات متغيرات تحمل الاسم، ولا يرى `getattr` الديناميكي — طبقة رسائل لا أمان.
- Decision: **No action** (موثّق أنها ليست حداً أمنياً في NBD-02).

## 3.2 tools/file_system.py (865 سطراً)

### الواجهة والاعتماديات

| الواجهة | الأسطر |
|---|---|
| `_resolve_workspace_path` (احتواء TOCTOU عبر dir_fd) | 247-300 |
| `_handle_edit` / `_write` / `_append` / `_replace` | 472 / 664 / 704 / 753 |
| `_atomic_replace_contents` (NBD-03) | 565-648 |
| بوابة Decision Ladder في execute() | ~60-78 |

### Coverage Map

| المسار | الحالة |
|---|---|
| سعيد: write/edit/replace/append/read/list | ✅ 145+ اختبار في الجلسة |
| رفض: traversal/absolute/symlink خارجي | ✅ اختبار NBD-03 |
| ذرية: كتابة أقصر، استثناء قبل replace | ✅ «X» بدل «XBCDE» + target سليم |
| timeout/cancellation | N/A (عمليات ملف محلية متزامنة) |
| غير متحقق: سلوك Decision Ladder بجذر مختلف عن cwd | ⚠️ CFD-fs-4 |

### النتائج

**CFD-fs-1 — كتابة ذرية موحدة مغلقة (P1, DERIVED, High)**
- Location: file_system.py@:547,565-648,683,815
- Claim: المسارات الثلاثة تستخدم primitive واحدة (O_EXCL temp + حلقة كتابة + fsync + os.replace + fsync مجلد)؛ لا لاحقة قديمة ولا partial write.
- Decision: **No action** (مغلق بالاختبارات).

**CFD-fs-2 — Decision Ladder يستخدم `os.getcwd()` لا الجذر المثبَّت (P2, DIRECT, High)**
- Location: file_system.py@:60-78 (`DecisionLadder(workspace_root=os.getcwd())`)
- Claim: إذا اختلف cwd العملية عن `NABD_WORKSPACE_ROOT` المثبَّت، يقيم السلم الاحتواء على جذر خاطئ — طبقة دفاع ثانية تعتمد على حالة غير مضمونة.
- Impact: في التشغيل عبر الموزع/النظام، قد يرفض السلم مسارات مشروعة (أو يسمح بجذر أوسع إذا كان cwd في مكان آخر).
- Verification: قراءة الكود (DIRECT)؛ اختبار فرض NABD_WORKSPACE_ROOT ≠ cwd يثبت الانحراف.
- Recommendation: `DecisionLadder(workspace_root=get_workspace_root())` (نفس ما تفعله الطبقات الأخرى).
- Regression test: `test_decision_ladder_uses_pinned_workspace_not_cwd`.
- Decision: **Refactor proposal** (P2 — سطر واحد).

**CFD-fs-3 — `mkdir(parents=True)` في write/edit ميت للمسارات المتداخلة الجديدة (P3, DERIVED, Low)**
- Location: file_system.py@:547,670-672 مقابل 247-300
- Claim: الاحتواء يرفض أبواباً غير موجودة قبل الوصول للكتابة، فتبقى الاستدعاءات بلا أثر في الحالة المتداخلة؛ سلوك ما قبل NBD-03 غير متغير.
- Decision: **Create issue** (توثيق أو مواءمة).

**CFD-fs-4 — `_append` يقرأ ثم يكتب (TOCTOU خفيف) (P3, DIRECT, Low)**
- Location: file_system.py@:704-750
- Claim: O_APPEND يجعل الكتابة ذرية لكل syscall، لكن قراءة old_content للـ diff تحدث قبلها — diff قد يسبق الكتابة في تزامن نادر؛ لا أثر على النزاهة.
- Decision: **No action**.

---

# الخلاصة والبوابات — مُصحَّح وفق ملحق التحقق (2026-08-12)

> **تصحيح جوهري:** المراجع قرأ `main` (لقطة `f7dd0c0`) التي لا تحوي إصلاحات الموجات A–E غير الملتزمة، ورفض إغلاق النتائج بالتوثيق وحده. الحكم الصحيح على `main` — قبل الالتزام — هو: **1 P0 مفتوحة، 5 P1 مفتوحة، 5 P2 مؤكدة مفتوحة، ونتيجة callback واحدة غير مثبتة.** الدليل الوحيد المقبول للإغلاق هو تغيير شفرة + اختبار انحدار + التزام.

## الحالة على `main` (كما راجعها الملحق)

| التصنيف | الحالة | المعرفات |
|---|---|---|
| P0 مفتوحة | **1** | NBD-01 (تغليف wheel يستثني الحزم المتداخلة) |
| P1 مفتوحة | **5** | NBD-02، NBD-03، NBD-04، NBD-05، CFD-pyproject-1 (cryptography غير معلنة) |
| P2 مؤكدة مفتوحة | **5** | NBD-06، NBD-07، CFD-fs-2، CFD-registry-1، CFD-appctx-1 |
| P2 غير مثبتة | **1** | CFD-guard-1 — لا تُسجل عيباً؛ مسار `/refactor` الحي يحوّل `None` عبر `is None` |

## نتائج التحقق التفصيلية

| المعرّف | الحكم | الدليل | الإجراء |
|---|---|---|---|
| CFD-pyproject-1 | **مؤكد P1** | `encrypt_api_key`/`decrypt_api_key` يستوردان `AESGCM`؛ لا `cryptography` في dependencies/requirements | أضِف التبعية + اختبر roundtrip في venv نظيفة |
| CFD-fs-2 | **مؤكد P2** | `DecisionLadder(workspace_root=os.getcwd())` في `FileSystemTool.execute` بدل `self.workspace` | مرّر الجذر المثبَّت + اختبر cwd≠workspace |
| CFD-registry-1 | **مؤكد P2** | `BaseTool.name == "unnamed_tool"`؛ `SecureTool` (أساس 13 أداة) لا يجاوز الافتراضي فيُكتشف باسم نائب | اجعل الاسم `None`/abstract وارفض التسجيل + استبعد الأساسيات من الاكتشاف |
| CFD-appctx-1 | **مؤكد P2** | `discover_tools(cls)` قبل إنشاء `ctx`؛ لا injector لحقول instance؛ لا `workspace_dir` في خريطة الحقن | أنشئ `ctx` أولاً + مرّر dependency bag + سجّل كل skip |
| CFD-guard-1 | **غير مثبت كعيب** | `confirm()` يعيد `None` للموافقة؛ `/refactor` يحوّل عبر `is None` (قطبية صحيحة) | اختبار عقد فقط؛ لا issue حتى يظهر caller معاكس |

## الإغلاق المحلي (الفرع `am8/d-0` — شفرة + اختبارات، قبل التوقيع البشري)

| المعرّف | الإصلاح المحلي | دليل الاختبار |
|---|---|---|
| NBD-01 | `pyproject.toml`: `packages.find` شامل + package-data | wheel 532KB + تثبيت نظيف + SMOKE_OK (test_nbd_hardening) |
| NBD-02 | REPL معطّل افتراضياً (feature flag + `capability_unavailable`) | 9/9 + بوابة تسجيل ثنائية الاتجاه |
| NBD-03 | `_atomic_replace_contents` (O_EXCL + fsync + os.replace) | `ABCDE → X` في write/edit/replace |
| NBD-04 | `_handle_simple` يمرر النص الأصلي (لا `" ".join`) | `cat "input file.txt"` وسيط واحد |
| NBD-05 | رفض = `consent_denied`/`success=False`/`blocked_by=user` | صفر تنفيذ عند الرفض، أدلة سلبية |
| NBD-06 | `import subprocess` + tuple منظَّم على TimeoutExpired | test_nbd06 مستقر 3/3 |
| NBD-07 | لا `PYTEST_CURRENT_TEST` في المنتج + CI + requirements-test | 0 ResourceWarning في الحزمة |
| CFD-pyproject-1 | `cryptography` في `[project].dependencies` | test_cfd_pyproject_byok_roundtrip (enc: مشفَّر) |
| CFD-fs-2 | `DecisionLadder(workspace_root=self.workspace)` في file_system + `get_workspace_root()` في shell (كان `os.getcwd()` في كليهما) | test_cfd_fs_decision_ladder_uses_pinned_workspace_not_cwd + test_cfd_fs2_shell_uses_pinned_workspace_root_not_cwd |
| CFD-registry-1 | رفض `unnamed_tool` عند التسجيل + استبعاد الأساسيات من الاكتشاف | test_cfd_registry_rejects_placeholder_name + discovery_skips |
| CFD-appctx-1 | اكتشاف بسياق حقيقي + `workspace_dir` في الحقن + skips مرئية | test_cfd_discovery_injects_workspace_dir |
| CFD-guard-1 | لا تغيير كود | test_cfd_guard1_consent_callback_polarity + guard_runs_on_approve |

> **تذكير:** هذه الإغلاقات محلية وغير ملتزمة. تُصبح نهائية فقط بعد التزام يدمج الشفرة + الاختبارات وتوقيع بشري (Ammar).

## Backlog المقترح — 6 PRs (من ملحق التحقق)

| PR | النطاق | النتائج | بوابة القبول |
|---|---|---|---|
| `fix(packaging): complete runtime and crypto dependencies` | اكتشاف الحزم + package data + `cryptography` | NBD-01، CFD-pyproject-1 | wheel نظيفة + imports مسار الإقلاع + roundtrip BYOK |
| `fix(repl): disable unsafe runtime pending isolation` | feature flag / إزالة التسجيل الافتراضي | NBD-02 | لا استدعاء REPL غير معزول من الـ registry |
| `fix(files): align workspace guard and atomic replace` | `self.workspace` في السلم + primitive ذري | NBD-03، CFD-fs-2 | cwd مختلف لا يغير الحكم؛ لا بقايا عند الكتابة الأقصر |
| `fix(shell-consent): preserve argv and truthful denial state` | argv/نص أصلي + import + `consent_denied` | NBD-04، NBD-05، NBD-06 | quote boundary + exception tuple + لا نجاح عند الرفض |
| `fix(tool-discovery): build with explicit dependencies` | ترتيب إنشاء `ctx` + dependency bag + رفض الاسم النائب + logging للـ skip | CFD-registry-1، CFD-appctx-1 | كل أداة باسم صالح؛ BrowserTool يُبنى أو يُسجَّل سبب skip |
| `test(process): callback contract and process cleanup` | اختبارات callback والعمليات + CI | CFD-guard-1، NBD-07 | قبول→True ورفض→False في اختبار DAG؛ صفر ResourceWarning |

## قرار go/no-go (حسب الملحق)

النشر **موقوف** حتى: إغلاق NBD-01 + `cryptography` باختبار artifact نظيف (PR الأول)، ثم المصادقة البشرية على بقية الإغلاقات المحلية. الوثائق وحدها لا تغيّر حالة العيب.

**التوقيع:** أُعدّ بواسطة الوكيل وفق CORE_FILE_DNA_DISSECTION v2 — التحقق بشري قبل التحويل إلى backlog.
