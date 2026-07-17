from typing import Any, Optional, Type

from tools.base import BaseTool, BaseModel
from tools.models import ToolResult
from adapters.lightpanda_adapter import LightpandaAdapter


class BrowserToolArgs(BaseModel):
    action: str
    url: Optional[str] = None
    selector: Optional[str] = None
    text: Optional[str] = None


class BrowserTool(BaseTool):
    name = "browser_action"
    description = "تصفح الويب، استخراج النصوص، وأخذ لقطات بصمت وخفة عبر Lightpanda MCP."

    def __init__(self, workspace_dir: str):
        self.adapter = LightpandaAdapter(workspace_dir=workspace_dir)

    @property
    def args_schema(self) -> Optional[Type[BaseModel]]:
        return BrowserToolArgs

    def execute(self, action: str, **kwargs) -> ToolResult:
        result = self.adapter.execute_tool(tool_name=action, arguments=kwargs)
        if result.get("status") == "FAILED":
            return ToolResult(success=False, stdout="", stderr=result.get("error", ""), returncode=1)
        return ToolResult(success=True, stdout=str(result), stderr="", returncode=0)
