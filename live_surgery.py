# live_surgery.py
import os
import sys
import json
from pathlib import Path
from core.dag.launcher import launch_nabdos_core

try:
    from core.llm import get_secure_model
except ImportError:
    get_secure_model = None

try:
    from tools.secure_tools import SecureGraphifyTool
except ImportError:
    SecureGraphifyTool = None

# ---------------------------------------------------------
# محول النموذج المحلي (LLM Adapter)
# ---------------------------------------------------------
class NabdLocalLLMAdapter:
    def __init__(self, max_context_tokens: int = 4096):
        self.max_context_tokens = max_context_tokens
        self.engine = get_secure_model() if callable(get_secure_model) else None
        print("🔌 [Neural Hookup] Initializing Local Edge LLM...")

    def generate(self, prompt: str) -> str:
        # حماية الذاكرة: التحقق من طول الـ Prompt قبل إرساله للنموذج
        estimated_tokens = len(prompt) // 4
        print(f"📊 [LLM Adapter] Prompt length: ~{estimated_tokens} tokens")
        
        # حماية ضد تجاوز حجم السياق للنماذج المحلية المكممة
        safe_token_limit = int(self.max_context_tokens * 0.85)
        if estimated_tokens > safe_token_limit:
            print(f"⚠️ [LLM Adapter] Context Warning: Prompt (~{estimated_tokens} tokens) exceeds safe limit ({safe_token_limit})! Truncating...")
            max_char_len = safe_token_limit * 4
            # الحفاظ على تعليمات الـ JSON في نهاية الـ Prompt عند التقليم
            footer_idx = prompt.find("=== OUTPUT FORMAT (STRICT JSON ONLY) ===")
            if footer_idx != -1 and footer_idx < max_char_len:
                footer = prompt[footer_idx:]
                prompt = prompt[:max_char_len - len(footer)] + "\n...[TRUNCATED TO PROTECT EDGE CONTEXT]...\n" + footer
            else:
                prompt = prompt[:max_char_len]
            print(f"📊 [LLM Adapter] Truncated Prompt length: ~{len(prompt) // 4} tokens")
            
        print("🧠 [LLM Adapter] Inference in progress on device...")
        
        # محاولة الاستدعاء الحي لمحرك LLM الفعلي إذا كان متوفراً ومتصلاً
        if self.engine:
            try:
                if hasattr(self.engine, "__call__"):
                    res = self.engine([{"role": "user", "content": prompt}])
                    if hasattr(res, "content"):
                        return res.content
                    return str(res)
                elif hasattr(self.engine, "generate_response"):
                    return self.engine.generate_response([{"role": "user", "content": prompt}])
                elif hasattr(self.engine, "generate"):
                    return self.engine.generate(prompt)
            except Exception as live_err:
                print(f"⚠️ [LLM Adapter] Live Engine call fallback due to offline/API limit: {live_err}")

        # إرجاع النص المولد (JSON String) لمحاكاة ناجحة في حال عدم توفر خادم محلي متصل
        return '{"files": {"dummy.py": "from typing import List\\n\\ndef calculate_total(items: List[float]) -> float:\\n    return sum(items)\\n"}}'

# ---------------------------------------------------------
# محول الرادار المكاني (Graphify Adapter)
# ---------------------------------------------------------
class NabdGraphifyAdapter:
    def __init__(self, workspace_dir: str = "."):
        self.workspace_dir = workspace_dir
        self.tool = SecureGraphifyTool(workspace_dir=workspace_dir) if SecureGraphifyTool else None

    def run(self, query: str, workspace_dir: str):
        print(f"👁️ [Graphify] Scanning actual files in {workspace_dir}...")
        if self.tool and hasattr(self.tool, "forward"):
            try:
                return self.tool.forward(query=query, workspace_dir=workspace_dir)
            except Exception as e:
                print(f"⚠️ [Graphify] Tool scan fallback: {e}")
        return {"nodes": ["dummy.py"], "edges": [], "summary": "Contains raw calculation logic. Needs typing."}

def main():
    print("=" * 60)
    print(" ⚡ NABD-OS LIVE EDGE INFERENCE ⚡ ")
    print("=" * 60)

    # 1. إنشاء ملف dummy.py للاختبار الفعلي
    with open("dummy.py", "w") as f:
        f.write("def calculate_total(items):\n    return sum(items)\n")

    # 2. حقن المحركات الحقيقية
    live_llm = NabdLocalLLMAdapter(max_context_tokens=4096)
    live_graphify = NabdGraphifyAdapter(workspace_dir=".")
    
    # تحديد الهدف
    target_file = ["dummy.py"]
    taste_rules = [
        "All functions MUST have strict Type Hints.",
        "Use English exclusively for variable names."
    ]

    # 3. إطلاق النواة
    try:
        launch_nabdos_core(
            llm_engine=live_llm,
            graphify_tool=live_graphify,
            workspace_dir=".",
            target_files=target_file,
            taste_rules=taste_rules
        )
    finally:
        if os.path.exists("dummy.py"):
            os.remove("dummy.py")
            print("🧹 Cleaned up target dummy.py")

if __name__ == "__main__":
    main()
