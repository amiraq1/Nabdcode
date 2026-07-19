# core/dag/nodes/sentinel.py
from core.dag.base import BaseNode, Edge
from core.dag.context import NabdExecutionContext

class SentinelNode(BaseNode):
    """
    عقدة الحارس البشري (Human-in-the-Loop).
    تقوم بتجميد مسار العمل، عرض التعديلات المقترحة (Diffs) بألوان الطرفية، 
    وانتظار القرار السيادي للمستخدم (موافقة، رفض، أو تعديل).
    """
    def __init__(self, node_id: str = "sentinel_node"):
        super().__init__(node_id)

    def execute(self, context: NabdExecutionContext) -> Edge:
        # 1. التحقق من وجود تعديلات
        if not context.code_diffs:
            print("⚠️ [Sentinel] No code modifications proposed by the Reasoner. Passing through.")
            # توجيه تلقائي لنهاية المسار أو العقدة التالية إذا لم تكن هناك تعديلات
            return Edge(target_node_id="end", reason="No diffs to review")

        print("\n🛡️  [Sentinel Node] The Agent proposes the following modifications:")
        print("=" * 60)
        
        # 2. طباعة التعديلات بألوان Termux (ANSI Escape Codes)
        for file_path, diff_content in context.code_diffs.items():
            print(f"\n📄 Target File: {file_path}")
            print("-" * 60)
            for line in diff_content.split('\n'):
                if line.startswith('+'):
                    print(f"\033[92m{line}\033[0m")  # أخضر للإضافة
                elif line.startswith('-'):
                    print(f"\033[91m{line}\033[0m")  # أحمر للحذف
                else:
                    print(line)  # لون افتراضي للسياق
        print("=" * 60)

        # 3. حلقة التحكم السيادي
        while True:
            user_choice = input("\n🚀 Approve execution? [y(Approve) / n(Abort) / edit(Feedback)]: ").strip().lower()
            
            if user_choice == 'y':
                print("✅ [Sentinel] Execution Approved by Human. Proceeding to Coder/Executor...")
                # تفويض بالانتقال إلى عقدة الكتابة والتنفيذ
                return Edge(target_node_id="executor_node", reason="Human approved changes")
            
            elif user_choice == 'n':
                print("🛑 [Sentinel] Execution Aborted by Human. Halting Pipeline.")
                context.halt_execution = True
                return None  # إرجاع None يُنهي عمل الـ DAG Engine بأمان
            
            elif user_choice == 'edit':
                feedback = input("📝 Enter your feedback/adjustments to guide the Agent: ")
                # حفظ الملاحظات في الذاكرة المرنة ليعيد الوكيل التفكير
                context.shared_memory['human_feedback'] = feedback
                print("⏪ [Sentinel] Routing back to Reasoner Node with new feedback...")
                # توجيه عكسي لعقدة التفكير لإعادة المحاولة
                return Edge(target_node_id="reasoner_node", reason="Human requested code adjustments")
            
            else:
                print("⚠️ Invalid choice. Please enter 'y', 'n', or 'edit'.")
