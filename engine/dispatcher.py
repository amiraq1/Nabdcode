import concurrent.futures
import threading
from engine.events import bus
from engine.tool_registry import registry
from engine.state import RuntimeState

from tools.models import ToolResult

# Shared thread pool — avoids per-call allocation overhead
_MAX_WORKERS: int = 4
_SHARED_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=_MAX_WORKERS)
# Admission control: only allow _MAX_WORKERS pending tasks at a time.
# This prevents unbounded queue growth when all workers are busy.
_POOL_SEMAPHORE = threading.BoundedSemaphore(_MAX_WORKERS)


class Dispatcher:
    """
    Dispatcher: orchestrates tool execution with timeout protection.
    Receives tool requests, manages timeouts, handles errors, and emits events.
    Returns ToolResult consistently for all outcomes.
    """
    def __init__(self, state: RuntimeState):
        self.state = state

    def dispatch(self, tool_name: str, kwargs: dict, timeout: int = 30) -> ToolResult:
        """
        Dispatch to the appropriate tool with timeout monitoring to prevent hangs.
        """
        # Resolve dotted tool names (e.g. file_system.write -> file_system)
        if tool_name not in registry and "." in tool_name:
            real_tool = tool_name.split(".")[0]
            if real_tool in registry:
                tool_name = real_tool

        # 1. Emit execution start event
        bus.emit("tool_started", {"tool": tool_name, "args": kwargs, "step": self.state.step_count})

        try:
            tool = registry.get_tool(tool_name)
        except KeyError as e:
            error_msg = str(e)
            bus.emit("tool_failed", {"tool": tool_name, "error": error_msg})
            return ToolResult(success=False, stderr=error_msg, returncode=-1, status="error")

        # 2. Admission control: acquire semaphore before submitting.
        # If all workers are busy, we block here rather than letting the
        # executor's internal queue grow unbounded.
        acquired = _POOL_SEMAPHORE.acquire(blocking=True, timeout=timeout)
        if not acquired:
            error_msg = f"Execution timeout ({timeout}s): all {_MAX_WORKERS} workers are busy for tool {tool_name}"
            bus.emit("tool_timeout", {"tool": tool_name, "timeout": timeout})
            return ToolResult(success=False, stderr=error_msg, returncode=-1, status="timeout")

        try:
            # 3. Execute tool with timeout protection
            future = _SHARED_POOL.submit(tool.execute, **kwargs)
            try:
                result: ToolResult = future.result(timeout=timeout)
                bus.emit(
                    "tool_completed",
                    {
                        "tool": tool_name,
                        "result": result,
                        "success": result.success,
                        "returncode": result.returncode,
                        "diff": result.diff,
                        "step": self.state.step_count,
                    },
                )
                return result

            except concurrent.futures.TimeoutError:
                error_msg = f"Execution timeout ({timeout}s) for tool {tool_name}"
                bus.emit("tool_timeout", {"tool": tool_name, "timeout": timeout})
                result = ToolResult(success=False, stderr=error_msg, returncode=-1, status="timeout")
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
                return result

            except Exception as e:
                error_msg = f"Internal tool error: {str(e)}"
                bus.emit("tool_failed", {"tool": tool_name, "error": error_msg})
                result = ToolResult(success=False, stderr=error_msg, returncode=-1, status="error")
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
        finally:
            _POOL_SEMAPHORE.release()
