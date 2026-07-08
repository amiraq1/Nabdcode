import concurrent.futures
from engine.events import bus
from engine.tool_registry import registry
from engine.state import RuntimeState

from typing import Any

# Shared thread pool — avoids per-call allocation overhead
_SHARED_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=4)

class DispatchResult:
    """Result wrapper supporting both dict-key and attribute access."""
    def __init__(self, status: str, output: str, error: str = "", returncode: int = -1):
        self.status = status
        self.output = output
        self.stderr = error or output
        self.stdout = output if status == "success" else ""
        self.success = (status == "success")
        self.returncode = returncode

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

class Dispatcher:
    """
    Dispatcher: orchestrates tool execution with timeout protection.
    Receives tool requests, manages timeouts, handles errors, and emits events.
    """
    def __init__(self, state: RuntimeState):
        self.state = state

    def dispatch(self, tool_name: str, kwargs: dict, timeout: int = 30) -> Any:
        """
        Dispatch to the appropriate tool with timeout monitoring to prevent hangs.
        """
        # 1. Emit execution start event
        bus.emit("tool_started", {"tool": tool_name, "args": kwargs, "step": self.state.step_count})
        
        try:
            tool = registry.get_tool(tool_name)
        except KeyError as e:
            error_msg = str(e)
            bus.emit("tool_failed", {"tool": tool_name, "error": error_msg})
            return DispatchResult(status="error", output=error_msg, returncode=-1)

        result = None
        # 2. Execute tool with timeout protection
        # Use the shared pool to prevent blocking the main engine
        future = _SHARED_POOL.submit(tool.execute, **kwargs)
        try:
            # Wait for result with timeout
            result = future.result(timeout=timeout)
            bus.emit(
                "tool_completed",
                {
                    "tool": tool_name,
                    "result": result,
                    "success": getattr(result, "success", False),
                    "returncode": getattr(result, "returncode", -1),
                    "diff": getattr(result, "diff", ""),
                    "step": self.state.step_count,
                },
            )
        except concurrent.futures.TimeoutError:
            error_msg = f"Execution timeout ({timeout}s) for tool {tool_name}"
            bus.emit("tool_timeout", {"tool": tool_name, "timeout": timeout})
            result = DispatchResult(status="error", output=error_msg, returncode=-1)
            bus.emit(
                "tool_completed",
                {
                    "tool": tool_name,
                    "result": result,
                    "success": False,
                    "returncode": -1,
                    "step": self.state.step_count,
                },
            )
            # Cancel future so hung thread doesn't continue needlessly
            future.cancel()
        except Exception as e:
            error_msg = f"Internal tool error: {str(e)}"
            bus.emit("tool_failed", {"tool": tool_name, "error": error_msg})
            result = DispatchResult(status="error", output=error_msg, returncode=-1)
            bus.emit(
                "tool_completed",
                {
                    "tool": tool_name,
                    "result": result,
                    "success": False,
                    "returncode": -1,
                    "step": self.state.step_count,
                },
            )

        return result
