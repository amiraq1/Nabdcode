# core/dag/nodes/reader.py
from core.dag.base import BaseNode, Edge
from core.dag.context import NabdExecutionContext

class ReaderNode(BaseNode):
    """
    عقدة الرؤية المكانية (The Spatial Eye).
    تستدعي GraphifyTool لمسح المستودع وبناء خريطة العلاقات (AST) 
    وتغذيتها في الكائن الإله (Context) قبل بدء التفكير.
    """
    def __init__(self, graphify_tool=None, node_id: str = "reader_node"):
        super().__init__(node_id)
        # حقن الأداة التي قمنا بإصلاح عدم تطابق وسائطها جراحياً
        self.graphify_tool = graphify_tool 

    def execute(self, context: NabdExecutionContext) -> Edge:
        print("\n👁️  [Reader Node] Initiating Spatial Scan (Graphify)...")
        
        try:
            # تنفيذ المسح المكاني على مساحة العمل
            if self.graphify_tool:
                if hasattr(self.graphify_tool, "run"):
                    spatial_map = self.graphify_tool.run(query="Extract project structure and main endpoints", workspace_dir=context.workspace_dir)
                elif hasattr(self.graphify_tool, "execute"):
                    spatial_map = self.graphify_tool.execute(query="Extract project structure and main endpoints", workspace_dir=context.workspace_dir)
                elif hasattr(self.graphify_tool, "forward"):
                    spatial_map = self.graphify_tool.forward(query="Extract project structure and main endpoints", workspace_dir=context.workspace_dir)
                elif callable(self.graphify_tool):
                    spatial_map = self.graphify_tool(query="Extract project structure and main endpoints", workspace_dir=context.workspace_dir)
                else:
                    spatial_map = {}
                context.graphify_map = spatial_map
                print(" ✅ [Reader Node] Spatial mapping acquired successfully.")
            else:
                print(" ⚠️ [Reader Node] No GraphifyTool injected. Skipping spatial scan.")
        except Exception as e:
            print(f" ⚠️ [Reader Node] Non-fatal Warning: Spatial mapping failed - {e}")
            # لا نوقف القطار هنا، بل نمرر سياقاً فارغاً إذا فشل المسح
            
        # التوجيه الحتمي: من القراءة إلى التفكير
        return Edge(target_node_id="reasoner_node", reason="Spatial awareness acquired, proceeding to Reasoner")
