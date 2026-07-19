# core/dag/checkpoint.py
import json
import os
from dataclasses import asdict
from core.dag.context import NabdExecutionContext

CHECKPOINT_FILE = ".nabdos_state.json"

class CheckpointManager:
    """
    درع الحماية ضد الـ OOM Killer.
    يقوم بتجميد حالة النظام بالكامل (الذاكرة + موقع القطار) على القرص الصلب.
    """
    
    @staticmethod
    def save(node_id: str, context: NabdExecutionContext):
        print(f" 💾 [Checkpoint] Saving state at node: [{node_id}]...")
        # تحويل الكائن الإله إلى قاموس (Dict) ليُحفظ كـ JSON
        state_data = {
            "current_node_id": node_id,
            "context": asdict(context)
        }
        with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
            json.dump(state_data, f, indent=2, ensure_ascii=False)

    @staticmethod
    def load():
        """يسترجع الحالة المجمدة إذا كانت موجودة، أو يُرجع None"""
        if not os.path.exists(CHECKPOINT_FILE):
            return None, None
            
        print(" ⏪ [Checkpoint] Found suspended pipeline state! Restoring...")
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            state_data = json.load(f)
            
        # إعادة بناء الكائن الإله من البيانات المحفوظة
        context = NabdExecutionContext(**state_data["context"])
        return state_data["current_node_id"], context

    @staticmethod
    def clear():
        """تنظيف نقطة الحفظ بعد انتهاء المهمة بنجاح"""
        if os.path.exists(CHECKPOINT_FILE):
            os.remove(CHECKPOINT_FILE)
            print(" 🧹 [Checkpoint] Pipeline finished. State memory cleared.")
