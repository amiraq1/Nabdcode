# core/dag/nodes/terminal.py
import subprocess
import shlex
from typing import Optional
from core.dag.base import BaseNode, Edge
from core.dag.context import NabdExecutionContext

class TerminalNode(BaseNode):
    """
    عقدة الطرفية الحية (The Shell Executor).
    تسمح للوكيل بتنفيذ أوامر داخل Termux/PRoot مع جدار حماية (Sandbox)
    لمنع الأوامر الكارثية.
    """
    def __init__(self, node_id: str = "terminal_node"):
        super().__init__(node_id)
        # 🛡️ القائمة السوداء للأوامر المحرمة (Sandbox Denylist)
        self.forbidden_cmds = {"rm", "mkfs", "reboot", "shutdown", "mv", "dd", "chmod", "chown"}

    def _is_command_safe(self, command: str) -> bool:
        """فحص أمني سريع لمنع تدمير بيئة Termux"""
        try:
            # تقسيم الأمر لتفحص الكلمة الأولى (مثل rm في rm -rf)
            parsed = shlex.split(command)
            if not parsed:
                return False
            base_cmd = parsed[0]
            if base_cmd in self.forbidden_cmds:
                return False
            return True
        except ValueError:
            return False

    def execute(self, context: NabdExecutionContext) -> Edge:
        # نفترض أن الوكيل (Reasoner) وضع الأمر الذي يريد تشغيله في الذاكرة المشتركة
        command = context.shared_memory.pop('pending_command', None)
        
        if not command:
            print("📭 [Terminal] No pending commands requested by the Agent. Skipping.")
            return Edge(target_node_id="end", reason="No command to execute")

        print(f"\n🖥️  [Terminal Node] Agent requested execution: `{command}`")
        
        # 1. تفعيل جدار الحماية (Sandbox Check)
        if not self._is_command_safe(command):
            print(f"🚫 [Terminal] CRITICAL SECURITY BLOCK: Command '{command}' is forbidden in NabdOS sandbox!")
            context.shared_memory['human_feedback'] = f"System Sandbox blocked your command: {command}. Do NOT use forbidden commands."
            return Edge(target_node_id="reasoner_node", reason="Sandbox violation")

        # 2. التنفيذ الفعلي (Subprocess Execution)
        print(" ⚙️ [Terminal] Executing command in isolated shell...")
        try:
            result = subprocess.run(
                command, 
                shell=True, 
                cwd=context.workspace_dir, 
                capture_output=True, 
                text=True, 
                timeout=30 # مهلة زمنية لمنع الأوامر المعلقة (Infinite Loops)
            )

            # 3. توجيه المسار بناءً على النتيجة (التعافي الذاتي)
            if result.returncode == 0:
                print(f" ✅ [Terminal] Success! Output:\n{result.stdout.strip()[:200]}...")
                context.shared_memory['terminal_output'] = result.stdout
                # إذا نجح الاختبار، ننهي المسار بسلام
                return Edge(target_node_id="end", reason="Tests/Command passed successfully")
            else:
                print(f" ❌ [Terminal] Command Failed. Output:\n{result.stderr.strip()[:200]}...")
                # تغذية العقل بالخطأ ليصلحه
                context.shared_memory['execution_error'] = f"Command `{command}` failed with output:\n{result.stderr}"
                print(" ⏪ [Terminal] Routing back to Reasoner to fix the code...")
                return Edge(target_node_id="reasoner_node", reason="Command failed, requesting self-healing")

        except subprocess.TimeoutExpired:
            print(" ⏰ [Terminal] Command execution timed out (30s).")
            context.shared_memory['execution_error'] = f"Command `{command}` timed out."
            return Edge(target_node_id="reasoner_node", reason="Timeout, requesting self-healing")
        except Exception as e:
            print(f" ⚠️ [Terminal] Unknown Shell Error: {e}")
            context.error_flags = True
            return Edge(target_node_id="end", reason="Fatal shell error")
