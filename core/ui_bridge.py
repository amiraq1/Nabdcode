# core/ui_bridge.py
"""UI Bridge Interface (Dependency Inversion).

The core/ backend must NEVER import from ui/. Instead it depends only on
this abstract interface. A concrete implementation (e.g. the Textual
AgentUiController) is injected at wiring time, keeping the backend runnable
in any environment: TUI, plain CLI, or a future API server.

Adapter role (P0 refactor):
    UIBridge now acts as an Adapter between the agent core and a set
    of AgentObserver subscribers. Every observer hook is invoked through
    ``_notify_observers`` which isolates each subscriber in a try/except,
    so a crashing observer can NEVER halt the main OS (fail-safe layer).
"""

from __future__ import annotations

import asyncio
import select
import sys
from typing import Any, Dict, List, Optional

# Phase2.1: sentinel returned by request_user_input when the non-blocking
# stdin select() times out. It is not "y"/"yes", so every caller that
# interprets the reply lowercases-and-compares still fails closed (deny);
# the caller can also detect it explicitly to emit a timeout-specific warning.
_TIMEOUT_REPLY = "__TIMEOUT__"

from core.agent_observer import AgentObserver


class UIBridge:
    """Abstract & Async UI bridge (Event Bus + Observer Adapter).

    Two responsibilities, cleanly separated:
      1. Async Event Bus (token / tool / thinking / done) for the
         async REPL consumer (render_agent_events).
      2. Sync Observer Adapter (on_*) that fans out to registered
         AgentObserver subscribers behind a fail-safe wrapper.
    """

    def __init__(self) -> None:
        # Queue and observer list are typed lazily to avoid nested
        # PEP 604 generic-annotation parse issues at attribute level.
        self._queue = None  # type: Optional[asyncio.Queue]
        self._observers: List[AgentObserver] = []

    def _get_queue(self) -> asyncio.Queue[Optional[Dict[str, Any]]]:
        if self._queue is None:
            self._queue = asyncio.Queue()
        return self._queue

    # --- Observer registry (Adapter injection point) ---
    def add_observer(self, observer: AgentObserver) -> None:
        """Subscribe an AgentObserver. Safe to call multiple times."""
        if observer not in self._observers:
            self._observers.append(observer)

    def remove_observer(self, observer: AgentObserver) -> None:
        """Unsubscribe an AgentObserver if present."""
        if observer in self._observers:
            self._observers.remove(observer)

    def _relay_from_bus(self, event_name: str, payload: Any) -> None:
        """Receive event from EventBus without relaying back to bus."""
        if isinstance(payload, dict):
            payload = dict(payload)
            payload["_from_bus"] = True
        else:
            payload = {"_from_bus": True, "content": payload}
        if event_name in ("tool_started", "tool_start"):
            self.emit("tool_started", **payload)
        elif event_name in ("tool_completed", "tool_end"):
            self.emit("tool_completed", **payload)
        elif event_name in ("llm_token", "token"):
            self.emit("token", **payload)
        elif event_name in ("on_agent_thought", "thought"):
            self.emit("thought", **payload)
        elif event_name in ("status_update", "status_changed"):
            self.emit("status_update", **payload)
        elif event_name in ("edit_proposed", "file_modified"):
            self.emit("edit_proposed", **payload)

    def emit(self, event_name: str, **kwargs: Any) -> None:
        """Universal event emitter routing events to observers and async queues.

        Single-direction flow (plan 1.1): the engine emits to EventBus; the
        UIBridge is a *reader* only. It MUST NOT re-emit back into EventBus —
        that bidirectional relay created an infinite echo (event -> bus ->
        bridge -> bus -> ...) suppressed only by fragile runtime flags. The
        bridge consumes events pushed to it (via _relay_from_bus) and fans out
        to its observers/queue; it never writes back to the bus.
        """
        if kwargs.pop("_from_bus", False):
            # Events arriving from the bus are consumed here, never relayed back.
            pass

        if event_name in ("on_agent_thought", "thought"):
            content = kwargs.get("content", kwargs.get("text", ""))
            if type(self).on_agent_thought is not UIBridge.on_agent_thought:
                self.on_agent_thought(content)
            else:
                self._notify_observers("on_agent_thought", content)
                try:
                    q = self._get_queue()
                    try:
                        loop = asyncio.get_running_loop()
                        loop.call_soon_threadsafe(q.put_nowait, {"type": "thought", "content": content})
                    except RuntimeError:
                        q.put_nowait({"type": "thought", "content": content})
                except Exception:
                    pass
        elif event_name in ("tool_started", "tool_start"):
            tool_name = kwargs.get("tool_name", kwargs.get("tool", kwargs.get("name", "")))
            args = kwargs.get("args", {})
            if type(self).tool_started is not UIBridge.tool_started:
                self.tool_started(tool_name, args=args)
            else:
                self.emit_tool_start_sync(tool_name, args)
        elif event_name in ("tool_completed", "tool_end"):
            tool_name = kwargs.get("tool_name", kwargs.get("tool", kwargs.get("name", "")))
            ok = kwargs.get("ok", kwargs.get("success", True))
            result = kwargs.get("result", kwargs.get("summary", ""))
            if type(self).tool_completed is not UIBridge.tool_completed:
                self.tool_completed(tool_name, ok=ok, summary=result)
            else:
                self.emit_tool_end_sync(tool_name, str(result)[:500])
        elif event_name in ("edit_proposed", "file_modified"):
            file_path = kwargs.get("file", kwargs.get("file_path", ""))
            diff = kwargs.get("diff", kwargs.get("diff_content", ""))
            additions = kwargs.get("additions", 0)
            removals = kwargs.get("removals", 0)
            # Phase 2.4 Edit Gateway: pass threading.Event + decision_box
            # through to the concrete handler so blocking approval works.
            event = kwargs.get("event", None)
            decision_box = kwargs.get("decision_box", None)
            if type(self).edit_proposed is not UIBridge.edit_proposed:
                self.edit_proposed(file=file_path, diff=diff, additions=additions, removals=removals, event=event, decision_box=decision_box)
            else:
                self.on_file_modified(f"[{file_path}]\n{diff}")
        elif event_name in ("status_update", "status_changed"):
            if type(self).status_update is not UIBridge.status_update:
                self.status_update(**kwargs)
            else:
                msg = kwargs.get("message", kwargs.get("status_text", ""))
                self.on_status_changed(msg)
        elif event_name in ("token", "llm_token"):
            content = kwargs.get("content", kwargs.get("token", ""))
            try:
                q = self._get_queue()
                try:
                    loop = asyncio.get_running_loop()
                    loop.call_soon_threadsafe(q.put_nowait, {"type": "token", "content": content})
                except RuntimeError:
                    q.put_nowait({"type": "token", "content": content})
            except Exception:
                pass
        else:
            self.on_action_triggered(event_name, kwargs.get("target", ""), str(kwargs))

    def _notify_observers(self, method: str, *args: Any) -> None:
        """Fail-safe fan-out to all observers.

        Each subscriber is isolated: if one raises, we log and continue
        so a broken UI can never crash the agent core / OS.
        """
        for obs in self._observers:
            try:
                getattr(obs, method)(*args)
            except Exception:
                # Fail-safe: swallow observer errors; the OS must stay up.
                continue

    # --- Async Event Bus API ---
    async def emit_token(self, token: str) -> None:
        """بث جزء من النص (Streaming)."""
        await self._get_queue().put({"type": "token", "content": token})

    async def emit_tool_start(self, tool_name: str, args: Dict[str, Any]) -> None:
        """بث إشعار ببدء استخدام أداة (مثل: كشط، قراءة ملف)."""
        await self._get_queue().put({"type": "tool_start", "name": tool_name, "args": args})

    async def emit_tool_end(self, tool_name: str, result_summary: str) -> None:
        """بث إشعار بانتهاء الأداة."""
        await self._get_queue().put({"type": "tool_end", "name": tool_name, "summary": result_summary})

    def emit_tool_start_sync(self, tool_name: str, args: Dict[str, Any]) -> None:
        """بث متزامن لبدء الأداة للعمل من أي سياق متزامن أو خيط."""
        self._notify_observers("on_action_triggered", "TOOL_START", tool_name, str(args))
        q = self._get_queue()
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(q.put_nowait, {"type": "tool_start", "name": tool_name, "args": args})
        except RuntimeError:
            q.put_nowait({"type": "tool_start", "name": tool_name, "args": args})

    def emit_tool_end_sync(self, tool_name: str, result_summary: str) -> None:
        """بث متزامن لانتهاء الأداة."""
        self._notify_observers("on_action_triggered", "TOOL_END", tool_name, result_summary)
        q = self._get_queue()
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(q.put_nowait, {"type": "tool_end", "name": tool_name, "summary": result_summary})
        except RuntimeError:
            q.put_nowait({"type": "tool_end", "name": tool_name, "summary": result_summary})

    async def emit_thought(self, text: str) -> None:
        """بث جزء من التفكير (Reasoning) إلى قائمة الأحداث للعارض."""
        await self._get_queue().put({"type": "thought", "content": text})

    async def emit_done(self) -> None:
        """إرسال إشارة للواجهة بأن الوكيل أنهى المهمة بالكامل."""
        await self._get_queue().put({"type": "done"})

    async def emit_thinking_start(self) -> None:
        """بث بداية حالة التفكير (منفصلة عن تيار النص)."""
        await self._get_queue().put({"type": "thinking_start"})

    async def emit_thinking_stop(self) -> None:
        """بث نهاية حالة التفكير (للمستقبل / إيقاف صريح)."""
        await self._get_queue().put({"type": "thinking_stop"})

    async def get_event(self) -> Optional[Dict[str, Any]]:
        """تسحب الواجهة الأحداث من هذا التابع لعرضها."""
        return await self._get_queue().get()

    # --- Sync Observer API (now routed through the fail-safe adapter) ---
    def on_plan_updated(self, todos: List[Dict[str, Any]]) -> None:
        """Called when the task plan / TodoManager changes."""
        self._notify_observers("on_plan_updated", todos)

    def on_file_modified(self, diff_content: str) -> None:
        """Called when a file is written/edited via FileSystemTool."""
        self._notify_observers("on_file_modified", diff_content)

    def on_action_triggered(
        self, action_type: str, target: str, meta: str = ""
    ) -> None:
        """Called when a tool/step fires (READ, SHELL, AGENT, USER, ...)."""
        self._notify_observers("on_action_triggered", action_type, target, meta)

    def on_status_changed(self, status_text: str) -> None:
        """Called to update the status bar / progress text."""
        self._notify_observers("on_status_changed", status_text)

    def on_agent_thought(self, text: str, **kw: Any) -> None:
        """Called to surface agent reasoning text."""
        self.emit("on_agent_thought", text=text, **kw)

    def tool_started(self, tool_name: str, **kw: Any) -> None:
        self.emit("tool_started", tool_name=tool_name, **kw)

    def edit_proposed(self, file: str, diff: str = "", additions: int = 0, removals: int = 0, **kw: Any) -> None:
        self.emit("edit_proposed", file=file, diff=diff, additions=additions, removals=removals, **kw)

    def tool_completed(self, tool_name: str, ok: bool = True, **kw: Any) -> None:
        self.emit("tool_completed", tool_name=tool_name, ok=ok, **kw)

    def status_update(self, **kw: Any) -> None:
        self.emit("status_update", **kw)


    def request_user_input(self, prompt: str, timeout: float | None = None) -> str:
        """Synchronous, fail-closed interactive prompt (human-in-the-loop gate).

        Used by the shell permission hook to ask the operator to allow/deny a
        command. The agent core runs inside ``asyncio.to_thread`` (see
        ``ui/repl_termux.py``), so a blocking read here only parks the
        *worker* thread — the REPL's event loop keeps streaming. It therefore
        cannot freeze the async Termux REPL.

        Phase2.1: ``timeout`` (seconds, default ``None`` = block forever)
        is enforced with ``select.select`` over ``sys.stdin`` (Unix/Termux).
        This is NON-BLOCKING at the event-loop level and leaves NO zombie
        threads — it is a single synchronous ``select`` + ``readline`` on the
        worker thread, which is already off the async loop. If the timeout is
        reached with no input, it returns ``"n"`` (DENY) — never silently
        authorizes, and never kills the REPL.

        Safety contract:
          • On any I/O error, non-interactive environment, or unreadable input,
            returns ``"n"`` (DENY) so the OS never silently authorizes.
          • The prompt is printed to stdout; the raw reply is stripped and
            lowercased by the caller before interpretation.
        """
        try:
            # Flush the prompt so it is visible before we wait on stdin.
            sys.stdout.write(prompt)
            sys.stdout.flush()
            if timeout is not None:
                # Wait up to `timeout` seconds for the operator to type.
                # select() parks ONLY this worker thread; the async REPL keeps
                # streaming. No background thread is spawned, so nothing to join.
                rlist, _, _ = select.select([sys.stdin], [], [], float(timeout))
                if not rlist:
                    # Timed out → fail closed (deny). No input consumed.
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    return _TIMEOUT_REPLY
            return sys.stdin.readline().rstrip("\n")
        except (EOFError, OSError, ValueError):
            # Headless / piped / closed stdin → fail closed.
            return "n"
        except Exception:
            return "n"

    def request_user_confirmation(self, prompt: str, timeout: float | None = None) -> bool:
        """Convenience wrapper: returns True only on an explicit ``y``/``yes``.

        Forwards ``timeout`` to ``request_user_input`` so an unanswered gate
        auto-denies instead of hanging a Termux session indefinitely.
        """
        try:
            reply = self.request_user_input(prompt, timeout=timeout).strip().lower()
        except Exception:
            return False
        return reply in ("y", "yes")


_TIMEOUT_REPLY = "__TIMEOUT__"

# Process-wide default bridge (no-op). Replaced by the wiring layer.
_DEFAULT_BRIDGE: UIBridge = UIBridge()


def get_bridge() -> UIBridge:
    return _DEFAULT_BRIDGE


def set_bridge(bridge: Optional[UIBridge]) -> None:
    """Inject the concrete UI bridge. Pass None to reset to the no-op default."""
    global _DEFAULT_BRIDGE
    _DEFAULT_BRIDGE = bridge if bridge is not None else UIBridge()
