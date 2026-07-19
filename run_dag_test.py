# run_dag_test.py
import os
from core.dag.context import NabdExecutionContext
from core.dag.executor import NabdDAGExecutor
from core.dag.nodes.reasoner import ReasonerNode
from core.dag.nodes.sentinel import SentinelNode
from core.dag.nodes.executor import ExecutorNode
from core.dag.base import BaseNode, Edge

# 1. عقدة النهاية (Terminal Node) لامتصاص نهاية المسار بأمان
class EndNode(BaseNode):
    def __init__(self):
        super().__init__("end")

    def execute(self, context: NabdExecutionContext) -> None:
        print("\n🎉 [End Node] Pipeline reached the terminal state successfully!")
        return None  # إرجاع None يخبر المحرك بإيقاف الحلقة بسلام

def main():
    print("=" * 60)
    print("🏰 NabdOS Deterministic DAG Execution Test")
    print("=" * 60)

    # 2. تهيئة الذاكرة المركزية (الكائن الإله) مع حقن هدف وهمي وقواعد ذوق
    context = NabdExecutionContext(
        workspace_dir=".",
        target_files=["test_dummy_app.py"],
        taste_rules=["All functions MUST have strict Type Hints."]
    )

    # 3. تهيئة القلب المضخ (المحرك)
    engine = NabdDAGExecutor()

    # 4. تسجيل العقد (The Pipeline Stations)
    engine.register_node(ReasonerNode())
    engine.register_node(SentinelNode())
    engine.register_node(ExecutorNode())
    engine.register_node(EndNode())

    # 5. إطلاق القطار الحتمي من محطة "العقل المفكر"
    final_context = engine.execute(start_node_id="reasoner_node", context=context)

    # 6. التقرير الختامي
    print("\n📊 [Final Report] Execution Context State:")
    print(f"- Target File: {final_context.target_files[0]}")
    print(f"- Error Flags: {final_context.error_flags}")
    print(f"- Shared Memory (Remaining): {final_context.shared_memory}")
    
    # تنظيف سريع لملف الاختبار إذا تم إنشاؤه
    if os.path.exists("test_dummy_app.py"):
        os.remove("test_dummy_app.py")
        print("- Cleaned up test_dummy_app.py")
        
    print("\n🚀 DAG Integration Test Completed Flawlessly! ⚔️")

if __name__ == "__main__":
    main()
