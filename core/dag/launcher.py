# core/dag/launcher.py
from core.dag.context import NabdExecutionContext
from core.dag.executor import NabdDAGExecutor
from core.dag.nodes.reader import ReaderNode
from core.dag.nodes.reasoner import ReasonerNode
from core.dag.nodes.sentinel import SentinelNode
from core.dag.nodes.executor import ExecutorNode
from core.dag.nodes.terminal import TerminalNode
from core.dag.base import BaseNode

class EndNode(BaseNode):
    """المحطة النهائية لإيقاف القطار بأمان"""
    def __init__(self):
        super().__init__("end")
    def execute(self, context: NabdExecutionContext):
        print("\n🎉 [End Node] Mission Accomplished. NabdOS Pipeline completed flawlessly.")
        return None

def launch_nabdos_core(llm_engine, graphify_tool, workspace_dir: str, target_files: list, taste_rules: list, resume: bool = False) -> NabdExecutionContext:
    """
    زر الإطلاق الرئيسي (The Ignition Switch).
    يجمع أدواتك (LLM, Graphify, Taste) ويطلقها في مسار حتمي صارم.
    """
    print("\n" + "═" * 65)
    print(" 🚀 ACTIVATING NABD-OS DETERMINISTIC KERNEL (EDGE AI) 🚀")
    print("═" * 65)

    # 1. تهيئة الكائن الإله (الذاكرة المركزية)
    context = NabdExecutionContext(
        workspace_dir=workspace_dir,
        target_files=target_files,
        taste_rules=taste_rules
    )

    # 2. تهيئة القلب المضخ (المحرك الحتمي)
    engine = NabdDAGExecutor()

    # 3. تسجيل العقد (تسليح القطار)
    # الملاحظة: العقدة الأولى الآن هي الرادار المكاني (Reader) وليس التفكير!
    engine.register_node(ReaderNode(graphify_tool=graphify_tool))
    engine.register_node(ReasonerNode(llm_engine=llm_engine))
    engine.register_node(SentinelNode())
    engine.register_node(ExecutorNode())
    engine.register_node(TerminalNode())
    engine.register_node(EndNode())

    # 4. الإطلاق (Ignition!)
    final_context = engine.execute(start_node_id="reader_node", context=context, resume=resume)
    
    print("═" * 65)
    print(f" 🏁 Kernel Execution Halted. Target(s): {target_files}")
    print("═" * 65)
    
    return final_context
