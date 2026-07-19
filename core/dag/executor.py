# core/dag/executor.py
from typing import Dict, Optional
from core.dag.base import BaseNode, Edge
from core.dag.context import NabdExecutionContext
from core.dag.checkpoint import CheckpointManager

class NabdDAGExecutor:
    """
    محرك التنفيذ الحتمي (The Deterministic Engine).
    يسجل العقد، ويدير تدفق سياق التنفيذ عبر مسار العمل بناءً على الحواف المرجعة،
    مع حماية كاملة ضد الحلقات المفرغة (Infinite Loops) والأعطال.
    """
    def __init__(self):
        self._nodes: Dict[str, BaseNode] = {}

    def register_node(self, node: BaseNode) -> None:
        """تسجيل عقدة في سجل المحرك"""
        if node.node_id in self._nodes:
            raise ValueError(f"⚠️ [DAG Engine] Node '{node.node_id}' is already registered.")
        self._nodes[node.node_id] = node

    def execute(self, start_node_id: str, context: NabdExecutionContext, resume: bool = False) -> NabdExecutionContext:
        """
        دورة الحياة الرئيسية: تدوير السياق عبر العقد حتى الوصول لنهاية المسار أو الاستيقاف.
        """
        current_node_id = start_node_id
        
        # 1. الاستيقاظ من نقطة سابقة إذا طُلب ذلك
        if resume:
            saved_node, saved_context = CheckpointManager.load()
            if saved_node and saved_context:
                current_node_id = saved_node
                context = saved_context
                print(f"\n🚀 [DAG Engine] Resuming pipeline from checkpoint at [{current_node_id}]...")
            else:
                print("⚠️ [DAG Engine] No valid checkpoint found. Starting fresh.")
                print(f"\n🚀 [DAG Engine] Starting deterministic pipeline at [{start_node_id}]...")
        else:
            print(f"\n🚀 [DAG Engine] Starting deterministic pipeline at [{start_node_id}]...")

        while current_node_id:
            # 🛡️ الحفظ التلقائي (Auto-Save) قبل كل حركة لحماية الذاكرة من OOM Killer
            CheckpointManager.save(current_node_id, context)
            
            # 1. فحص إشارات التوقف الاضطراري (Interrupts)
            if context.halt_execution or context.error_flags:
                print("🛑 [DAG Engine] Pipeline halted due to context flags (Error or User Abort).")
                break

            # 2. التحقق من وجود العقدة أو الوصول لنهاية المسار
            if current_node_id not in self._nodes:
                if current_node_id.lower() in ("end", "done", "exit", "terminal"):
                    print(f"🏁 [DAG Engine] Pipeline reached terminal destination [{current_node_id}].")
                    break
                print(f"❌ [DAG Engine] Fatal Error: Node '{current_node_id}' not found in registry!")
                context.error_flags = True
                break

            node = self._nodes[current_node_id]
            print(f"🔄 [DAG Engine] Executing Node: [{node.node_id}]")
            
            try:
                # 3. القلب النابض: التنفيذ واستلام الوجهة القادمة
                next_edge: Optional[Edge] = node.execute(context)
                
                # 4. التوجيه (Routing)
                if next_edge is None:
                    print(f"🏁 [DAG Engine] Pipeline finished gracefully at [{node.node_id}].")
                    break
                    
                print(f" ↪️ [DAG Engine] Transitioning: [{node.node_id}] -> [{next_edge.target_node_id}] (Reason: {next_edge.reason})")
                current_node_id = next_edge.target_node_id

            except Exception as e:
                # 🛡️ شبكة الأمان الجراحية (Graceful Degradation)
                print(f"❌ [DAG Engine] Exception occurred inside [{node.node_id}]: {e}")
                context.error_flags = True
                break
                
        # 3. التنظيف بعد النجاح
        if not context.error_flags and not context.halt_execution:
            CheckpointManager.clear()
            
        print("🎯 [DAG Engine] Execution Cycle Completed.\n")
        return context
