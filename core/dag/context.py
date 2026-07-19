# core/dag/context.py
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from pathlib import Path

@dataclass
class NabdExecutionContext:
    """
    The God Object: الحامل المركزي للبيانات عبر مسار العمل (DAG Pipeline).
    يحمل سياق المستودع، التعديلات المقترحة، والخريطة المكانية.
    """
    workspace_dir: str
    target_files: List[str] = field(default_factory=list)
    
    # الذاكرة المكانية (من Graphify)
    graphify_map: Dict[str, Any] = field(default_factory=dict)
    
    # الذوق البرمجي (من TasteEngine)
    taste_rules: List[str] = field(default_factory=list)
    
    # التعديلات البرمجية المقترحة قبل الاعتماد (الـ Diffs)
    code_diffs: Dict[str, str] = field(default_factory=dict)
    
    # أعلام التحكم والأخطاء
    error_flags: bool = False
    halt_execution: bool = False
    
    # ذاكرة مرنة لتبادل البيانات غير المهيكلة بين العقد
    shared_memory: Dict[str, Any] = field(default_factory=dict)

    def resolve_path(self) -> Path:
        return Path(self.workspace_dir).resolve()
