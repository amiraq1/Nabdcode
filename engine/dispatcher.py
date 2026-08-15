import concurrent.futures
import threading
from typing import Any, Optional, Dict
from core.kernel.events import bus
from engine.tool_registry import registry
from engine.state import RuntimeState
from core.kernel.protocols import ToolCallable

from tools.models import ToolResult

# Shared thread pool — avoids per-call allocation overhead
_MAX_WORKERS: int = 4
_SHARED_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=_MAX_WORKERS)
# Admission control: only allow _MAX_WORKERS pending tasks at a time.
# This prevents unbounded queue growth when all workers are busy.
_POOL_SEMAPHORE = threading.BoundedSemaphore(_MAX_WORKERS)
_dispatch_ctx = threading.local()

_active_worker_lock = threading.Lock()
_active_worker_count: int = 0


class _WorkerSlot:
    """Manages exact single-release ownership of a pooled worker semaphore slot.

    EXE-02 Decoupled Slot Lifetime:
    When a tool is dispatched, a slot is acquired. The slot is held for the full
    lifetime of the executing worker thread inside _SHARED_POOL, and released
    EXACTLY ONCE when the worker thread exits — even if the caller timed out.
    """

    def __init__(self, sem: threading.BoundedSemaphore):
        self._sem = sem
        self._released = False
        self._lock = threading.Lock()
        with _active_worker_lock:
            global _active_worker_count
            _active_worker_count += 1

    def release(self) -> None:
        """Release the underlying semaphore exactly once."""
        with self._lock:
            if not self._released:
                self._released = True
                with _active_worker_lock:
                    global _active_worker_count
                    _active_worker_count = max(0, _active_worker_count - 1)
                try:
                    self._sem.release()
                except ValueError:
                    pass  # BoundedSemaphore upper bound safety


def get_active_worker_count() -> int:
    """Return the number of worker tasks currently running inside _SHARED_POOL."""
    with _active_worker_lock:
        return _active_worker_count


def is_dispatching() -> bool:
    """Return True if the current thread is executing a tool inside Dispatcher.dispatch."""
    return getattr(_dispatch_ctx, "active", False)



class Dispatcher:
    """
    Dispatcher: orchestrates tool execution with timeout protection.
    Receives tool requests, manages timeouts, handles errors, and emits events.
    Returns ToolResult consistently for all outcomes.
    """
    def __init__(self, state: RuntimeState, tool_registry: Any = None, event_bus: Any = None):
        self.state = state
        self.registry = tool_registry if tool_registry is not None else registry
        self.bus = event_bus if event_bus is not None else bus

    def dispatch(self, tool_name: str, kwargs: dict, timeout: int = 30) -> ToolResult:
        """
        Dispatch to the appropriate tool with timeout monitoring to prevent hangs.
        """
        session_id = getattr(self.state, "session_id", None)

        # Resolve dotted tool names (e.g. file_system.write -> file_system)
        if tool_name not in self.registry and "." in tool_name:
            real_tool = tool_name.split(".")[0]
            if real_tool in self.registry:
                tool_name = real_tool

        # 1. Emit execution start event
        self.bus.emit("tool_started", {"tool": tool_name, "args": kwargs, "step": self.state.step_count}, session_id=session_id)

        try:
            tool = self.registry.get_tool(tool_name)
        except KeyError as e:
            error_msg = str(e)
            self.bus.emit("tool_failed", {"tool": tool_name, "error": error_msg}, session_id=session_id)
            return ToolResult(success=False, stderr=error_msg, returncode=-1, status="error")

        # ── Subagent delegation short-circuit ────────────────────────────
        # The "task" tool spawns its OWN daemon thread (SubagentRunner) with a
        # timeout, so it must NOT consume a slot in the dispatcher's bounded
        # worker pool. Handle it directly and bypass admission control entirely.
        if tool_name == "task":
            try:
                # Runtime state is an internal capability, never an LLM-facing
                # tool argument. TaskTool uses it only to bind a delegated run
                # to the current revision-bound Task Graph.
                task_kwargs = dict(kwargs)
                task_kwargs["_parent_state"] = self.state
                result = tool.execute(**task_kwargs)
            except Exception as exc:
                result = ToolResult(
                    success=False,
                    stderr=f"task sub-agent failed: {exc}",
                    returncode=-1,
                    status="error",
                )
            if not isinstance(result, ToolResult):
                result = ToolResult(
                    success=True, stdout=str(result), returncode=0, status="success"
                )
            self.bus.emit(
                "tool_completed",
                {
                    "tool": tool_name,
                    "result": result,
                    "success": result.success,
                    "returncode": result.returncode,
                    "diff": result.diff,
                    "step": self.state.step_count,
                },
                session_id=session_id,
            )
            return result

        # 2. Admission control: acquire semaphore before submitting.
        # If all workers are busy, we block here rather than letting the
        # executor's internal queue grow unbounded.
        acquired = _POOL_SEMAPHORE.acquire(blocking=True, timeout=timeout)
        if not acquired:
            error_msg = f"Execution timeout ({timeout}s): all {_MAX_WORKERS} workers are busy for tool {tool_name}"
            self.bus.emit("tool_timeout", {"tool": tool_name, "timeout": timeout}, session_id=session_id)
            return ToolResult(success=False, stderr=error_msg, returncode=-1, status="timeout")

        slot = _WorkerSlot(_POOL_SEMAPHORE)
        submitted = False

        try:
            # 3. Execute tool with timeout protection
            def _run_tool():
                _dispatch_ctx.active = True
                try:
                    return tool(**kwargs)
                finally:
                    _dispatch_ctx.active = False
                    # EXE-02: Slot is released ONLY when the worker thread genuinely completes!
                    slot.release()

            try:
                future = _SHARED_POOL.submit(_run_tool)
                submitted = True
            except Exception:
                slot.release()
                raise

            try:
                result: ToolResult = future.result(timeout=timeout)
                # Ensure result is always ToolResult
                if not isinstance(result, ToolResult):
                    result = ToolResult(
                        success=not str(result).startswith(("Error:", "Security Violation:")),
                        stdout=str(result),
                        returncode=0,
                        status="success",
                    )
                self.bus.emit(
                    "tool_completed",
                    {
                        "tool": tool_name,
                        "result": result,
                        "success": result.success,
                        "returncode": result.returncode,
                        "diff": result.diff,
                        "step": self.state.step_count,
                    },
                    session_id=session_id,
                )
                return result

            except concurrent.futures.TimeoutError:
                error_msg = f"Execution timeout ({timeout}s) for tool {tool_name}"
                self.bus.emit("tool_timeout", {"tool": tool_name, "timeout": timeout}, session_id=session_id)
                result = ToolResult(success=False, stderr=error_msg, returncode=-1, status="timeout")
                self.bus.emit(
                    "tool_completed",
                    {
                        "tool": tool_name,
                        "result": result,
                        "success": False,
                        "returncode": -1,
                        "step": self.state.step_count,
                    },
                    session_id=session_id,
                )
                # EXE-02: Cancel task if not yet started. If already executing, slot
                # remains held by the worker thread until _run_tool finishes.
                future.cancel()
                return result

            except Exception as e:
                error_msg = f"Internal tool error: {str(e)}"
                self.bus.emit("tool_failed", {"tool": tool_name, "error": error_msg}, session_id=session_id)
                result = ToolResult(success=False, stderr=error_msg, returncode=-1, status="error")
                self.bus.emit(
                    "tool_completed",
                    {
                        "tool": tool_name,
                        "result": result,
                        "success": False,
                        "returncode": -1,
                        "step": self.state.step_count,
                    },
                    session_id=session_id,
                )
                return result
        finally:
            if not submitted:
                slot.release()

