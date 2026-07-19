# core/dag/base.py
from abc import ABC, abstractmethod
from typing import Optional
from core.dag.context import NabdExecutionContext

class Edge:
    """
    يمثل مسار الانتقال الحتمي من عقدة إلى أخرى.
    """
    def __init__(self, target_node_id: str, reason: Optional[str] = None):
        self.target_node_id = target_node_id
        self.reason = reason # للتسجيل والشفافية (Observability)

    def __repr__(self):
        return f"Edge(target='{self.target_node_id}', reason='{self.reason}')"

class BaseNode(ABC):
    """
    القالب الأساسي لأي عقدة في مسار NabdOS.
    كل عقدة يجب أن تنفذ عملها ثم تُرجع (Edge) يحدد الوجهة القادمة.
    """
    def __init__(self, node_id: str):
        self.node_id = node_id

    @abstractmethod
    def execute(self, context: NabdExecutionContext) -> Edge:
        """
        القلب النابض للعقدة. 
        يجب أن يعالج السياق (context) ويُرجع كائن (Edge) للخطوة التالية.
        """
        pass
