# core/dag/nodes/reasoner.py
import json
import re
from pathlib import Path
from core.dag.base import BaseNode, Edge
from core.dag.context import NabdExecutionContext

class ReasonerNode(BaseNode):
    """
    العقل المفكر الحي (Live Brain Node) مزود بفلتر السياق (Context Reranker).
    يتصل بمحرك الـ LLM، يفلتر قواعد الذوق لتقليل التوكنز، ويجبر النموذج على إرجاع JSON نظيف.
    """
    def __init__(self, llm_engine, node_id: str = "reasoner_node"):
        super().__init__(node_id)
        if not llm_engine:
            raise ValueError("⚠️ [Reasoner] Fatal: Real LLM Engine is required!")
        self.llm_engine = llm_engine

    def _extract_json_from_llm(self, text: str) -> dict:
        """قناص الـ JSON (JSON Sniper) لانتزاع الكود من رد النموذج"""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except Exception:
                    pass
            return {}

    def _rerank_taste_rules(self, context: NabdExecutionContext) -> list:
        """
        [الغنيمة المعمارية]: فلتر الذوق لتقليل استهلاك التوكنز (Token Optimization).
        يستبعد قواعد البايثون إذا كان الملف المستهدف Markdown، والعكس.
        """
        if not context.target_files or not context.taste_rules:
            return context.taste_rules
            
        active_rules = []
        # استخراج امتدادات الملفات المستهدفة
        target_exts = {Path(f).suffix.lower() for f in context.target_files}
        
        for rule in context.taste_rules:
            rule_lower = rule.lower()
            # فحص قواعد بايثون
            if any(k in rule_lower for k in ['type hint', 'def ', 'python', 'pep8']):
                if '.py' in target_exts:
                    active_rules.append(rule)
            # فحص قواعد واجهات المستخدم / الويب
            elif any(k in rule_lower for k in ['css', 'html', 'react', 'bento']):
                if any(ext in target_exts for ext in ['.html', '.css', '.js', '.tsx', '.ts']):
                    active_rules.append(rule)
            # قواعد عامة تطبق دائماً
            else:
                active_rules.append(rule)
                
        return active_rules

    def execute(self, context: NabdExecutionContext) -> Edge:
        print("\n🧠 [Reasoner Node] Reranking Context & Compiling Nuclear Prompt...")

        feedback = context.shared_memory.pop('human_feedback', None)
        syntax_error = context.shared_memory.pop('execution_error', None)
        
        # 1. فلترة الذوق الذكية (Reranking)
        optimized_rules = self._rerank_taste_rules(context)
        dropped_rules_count = len(context.taste_rules) - len(optimized_rules)
        if dropped_rules_count > 0:
            print(f" ♻️ [Reranker] Dropped {dropped_rules_count} irrelevant rule(s) to save tokens.")

        # 2. التوجيه النووي (Nuclear Prompt)
        prompt = "You are the NabdOS elite autonomous refactoring agent.\n\n"
        prompt += "=== TASK ===\n"
        prompt += f"Analyze and refactor the following files: {', '.join(context.target_files)}\n\n"
        
        if context.graphify_map:
            print(" 🗺️ [Reasoner] Injecting Spatial Architecture Map...")
            prompt += f"=== SPATIAL ARCHITECTURE MAP ===\nUse this repository map to understand cross-file dependencies:\n{context.graphify_map}\n\n"

        if syntax_error:
            print(f" ⚠️ [Reasoner] Injecting Previous Syntax Error Context: {syntax_error}")
            prompt += f"=== CRITICAL FIX REQUIRED ===\nYour last generated code contained a syntax error:\n{syntax_error}\nYou MUST fix this error now.\n\n"
            
        if feedback:
            print(f" 👤 [Reasoner] Injecting Sovereign Human Feedback...")
            prompt += f"=== HUMAN SOVEREIGN FEEDBACK ===\n{feedback}\nAdapt your output strictly to this feedback.\n\n"

        if optimized_rules:
            print(f" 🎨 [Reasoner] Enforcing {len(optimized_rules)} Optimized Taste Rule(s)...")
            prompt += "=== ARCHITECTURAL TASTE RULES ===\nYou MUST enforce these rules:\n"
            for rule in optimized_rules:
                prompt += f"- {rule}\n"

        # 3. الهيكلة الإجبارية (JSON Schema Constraint)
        prompt += """\n=== OUTPUT FORMAT (STRICT JSON ONLY) ===
You must reply ONLY with a valid JSON object. Do NOT wrap it in markdown. Do NOT add conversational text.
{
  "files": {
    "file_path_here.py": "FULL_UPDATED_CODE_HERE"
  }
}"""

        print(" ⚡ [Reasoner] Sending payload to Live LLM Engine. Please wait...")
        
        try:
            # 4. الاستدعاء الحقيقي للنموذج المحلي
            response_text = self.llm_engine.generate(prompt)
            parsed_data = self._extract_json_from_llm(response_text)
            
            if "files" not in parsed_data or not parsed_data["files"]:
                raise ValueError("LLM returned empty or invalid JSON structure.")
                
            context.code_diffs = parsed_data["files"]
            print(f" ✅ [Reasoner] Code generation complete for {len(context.code_diffs)} file(s).")
            
        except Exception as e:
            print(f" ❌ [Reasoner] Live LLM Execution Failed: {e}")
            context.error_flags = True
            return Edge(target_node_id="end", reason="LLM Inference Crash")

        # 5. التوجيه الإجباري للحارس البشري
        return Edge(target_node_id="sentinel_node", reason="Live modifications ready for human review")
