# core/dag/nodes/executor.py
import os
import ast
from core.dag.base import BaseNode, Edge
from core.dag.context import NabdExecutionContext

class ExecutorNode(BaseNode):
    """
    عقدة التنفيذ والكتابة (The Surgeon's Scalpel).
    تستلم التعديلات المُصادق عليها، تجري فحصاً نحوياً (Syntax Check) صارماً،
    ثم تقوم بكتابة التعديلات بأمان على القرص.
    """
    def __init__(self, node_id: str = "executor_node"):
        super().__init__(node_id)

    def execute(self, context: NabdExecutionContext) -> Edge:
        print("\n⚙️  [Executor Node] Applying approved modifications to disk...")
        
        # ملاحظة معمارية: نفترض هنا أن context.code_diffs يحتوي على 
        # { "مسار_الملف": "الكود_الجديد_بالكامل" } لضمان سلامة التنفيذ.
        
        for file_path, new_content in context.code_diffs.items():
            full_path = os.path.join(context.workspace_dir, file_path)
            
            # 1. الدرع الأخير: الفحص النحوي (Syntax Validation) قبل المساس بالقرص
            try:
                ast.parse(new_content)
            except SyntaxError as e:
                print(f"❌ [Executor] CRITICAL: Syntax Error detected in the proposed code for {file_path}!")
                print(f"   Details: {e}")
                
                # حفظ الخطأ للوكيل لكي يتعلم منه
                context.shared_memory['execution_error'] = f"Syntax Error in {file_path}: {e}"
                print("⏪ [Executor] Rolling back! Returning to Reasoner Node to fix the syntax...")
                
                # توجيه عكسي لعقدة التفكير (الوكيل) لإصلاح خطئه النحوي
                return Edge(target_node_id="reasoner_node", reason="Syntax verification failed")

            # 2. الجراحة: الكتابة الفعلية على القرص
            try:
                # التأكد من وجود المجلدات (في حال كان ملفاً جديداً)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                
                with open(full_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                print(f"✅ [Executor] Successfully deployed updates to: {file_path}")
                
            except Exception as e:
                print(f"❌ [Executor] FileSystem Error - Disk write failed for {file_path}: {e}")
                context.error_flags = True
                return Edge(target_node_id="end", reason="Fatal I/O Error")

        # 3. إفراغ ذاكرة التعديلات بعد التنفيذ الناجح
        context.code_diffs.clear()
        
        print("🏁 [Executor] All modifications applied safely. Surgery complete.")
        # التوجيه لمحطة الطرفية لفحص أو تشغيل الأوامر إن وجدت
        return Edge(target_node_id="terminal_node", reason="Code deployed, checking for execution validation")
