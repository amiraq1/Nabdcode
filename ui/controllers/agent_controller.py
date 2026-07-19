"""Agent UI Controller bridge connecting agent worker threads to Textual UI app safely."""

from __future__ import annotations

from typing import Any
from core.ui_bridge import UIBridge
from ui.widgets.badges import ActionTag, AgentThought
from ui.widgets.diff_viewer import DiffBlock


class AgentUiController(UIBridge):
    """Textual UI Controller implementing thread-safe UI stream bridging."""

    def __init__(
        self,
        todo_widget: Any = None,
        diff_widget: Any = None,
        chat_container: Any = None,
        status_bar: Any = None,
        app: Any = None,
    ) -> None:
        super().__init__()
        self.todo_widget = todo_widget
        self.diff_widget = diff_widget
        self.chat_container = chat_container
        self.status_bar = status_bar
        self.app = app
        self.is_busy = False
        self.max_stream_widgets = 200
        # Phase 2.4 Edit Gateway: pending approval state for human-in-the-loop.
        self._pending_edit_event: Any = None  # threading.Event, typed Any to avoid import
        self._pending_edit_decision: dict[str, bool] | None = None

    def safe_ui_update(self, fn: Any, *args: Any, **kwargs: Any) -> None:
        """Thread-safe UI update dispatcher using app.call_from_thread.

        Worker threads MUST NEVER touch Textual widgets directly or call
        asyncio.create_task/await across threads. Only call_from_thread is safe.
        """
        app = getattr(self, "app", None)
        if app is None:
            return  # fail-safe: no live app (sim/headless)
        app.call_from_thread(fn, *args, **kwargs)

    # --- UIBridge Method Overrides (Single funnel to safe_ui_update) ---
    def on_agent_thought(self, text: str, **_: Any) -> None:
        self.safe_ui_update(self._mount_stream_widget, AgentThought(text))

    def tool_started(self, tool_name: str, **_: Any) -> None:
        self.safe_ui_update(self._mount_stream_widget, ActionTag(tool_name, status="in_progress"))

    def edit_proposed(self, file: str, diff: str = "", additions: int = 0, removals: int = 0, **kw: Any) -> None:
        # Phase 2.4 Edit Gateway: extract threading.Event + decision_box if present.
        self._pending_edit_event = kw.get("event", None)
        self._pending_edit_decision = kw.get("decision_box", None)

        self.safe_ui_update(self._mount_stream_widget, DiffBlock(diff_data=diff, file=file, additions=additions, removals=removals))

        if self._pending_edit_event is not None and self._pending_edit_decision is not None:
            self.safe_ui_update(self._update_status_bar, {
                "message": f"✋ Edit proposed for {file}: approve? (y/N)"
            })

    def tool_completed(self, tool_name: str, ok: bool = True, **_: Any) -> None:
        self.safe_ui_update(self._update_last_tag, tool_name, ok)

    def status_update(self, **kw: Any) -> None:
        self.safe_ui_update(self._update_status_bar, kw)

    # --- Legacy / Sync Hooks routing to safe update ---
    def on_action_triggered(self, action_type: str, target: str, meta: str = "") -> None:
        if action_type == "TOOL_START":
            self.tool_started(target, args=meta)
        elif action_type == "TOOL_END":
            self.tool_completed(target, ok=True, summary=meta)
        elif action_type == "USER":
            self.safe_ui_update(self._mount_stream_widget, ActionTag("USER", target=target, status="info"))
        elif action_type == "ERROR":
            self.safe_ui_update(self._mount_stream_widget, ActionTag("ERROR", target=target, status="error"))
        else:
            self.safe_ui_update(self._mount_stream_widget, ActionTag(action_type, target=target, status="info"))

    def on_status_changed(self, status_text: str) -> None:
        self.status_update(message=status_text)

    def on_file_modified(self, diff_content: str) -> None:
        lines = diff_content.splitlines()
        file_path = lines[0].strip("[]") if lines and lines[0].startswith("[") else "file"
        diff_body = "\n".join(lines[1:]) if len(lines) > 1 else diff_content
        self.edit_proposed(file=file_path, diff=diff_body)

    # --- Internal UI Composition Helpers (Executed on Textual Main Thread) ---
    def _mount_stream_widget(self, widget: Any) -> None:
        if self.chat_container is None:
            return
        try:
            self.chat_container.mount(widget)
            if hasattr(self.chat_container, "children") and len(self.chat_container.children) > self.max_stream_widgets:
                try:
                    self.chat_container.children[0].remove()
                except Exception:
                    pass
            if hasattr(self.chat_container, "scroll_end"):
                self.chat_container.scroll_end(animate=False)
        except Exception:
            pass

    def _update_last_tag(self, tool_name: str, ok: bool = True) -> None:
        if self.chat_container is None or not hasattr(self.chat_container, "children"):
            return
        new_status = "success" if ok else "error"
        for child in reversed(self.chat_container.children):
            if isinstance(child, ActionTag) and (child.action == tool_name or child.action == "TOOL_START"):
                if hasattr(child, "status") and child.status == "in_progress":
                    child.update_status(new_status)
                    break
            elif hasattr(child, "tool_name") and getattr(child, "tool_name") == tool_name:
                if hasattr(child, "status"):
                    child.status = new_status
                    if hasattr(child, "refresh"):
                        child.refresh()
                    break

    def has_pending_edit(self) -> bool:
        """Return True when the Edit Gateway is waiting for human approval."""
        ev = getattr(self, "_pending_edit_event", None)
        return ev is not None

    def resolve_pending_edit(self, approved: bool) -> None:
        """Resolve a pending edit approval, unblocking the engine thread."""
        dec = getattr(self, "_pending_edit_decision", None)
        ev = getattr(self, "_pending_edit_event", None)
        if dec is not None:
            dec["approved"] = approved
        if ev is not None:
            ev.set()
        # Clear pending state.
        self._pending_edit_event = None
        self._pending_edit_decision = None
        msg = "✅ Edit approved by user." if approved else "✋ Edit rejected by user."
        self.safe_ui_update(self._update_status_bar, {"message": msg})

    def _update_status_bar(self, kw: dict) -> None:
        if self.status_bar is None:
            return
        msg = kw.get("message", kw.get("status_text", ""))
        if msg and hasattr(self.status_bar, "update"):
           try:
               self.status_bar.update(msg)
           except Exception:
               pass

    # --- Slash Command & Concurrency Interface ---
    def parse_command_input(self, text: str) -> bool:
        """Check if input text is a slash command."""
        return text.strip().startswith("/")

    async def handle_command(self, command: str) -> None:
        """Handle slash commands inside the controller."""
        cmd = command.strip().lower()
        if cmd == "/clear":
            if self.chat_container and hasattr(self.chat_container, "remove_children"):
                await self.chat_container.remove_children()
        elif cmd == "/status":
            self.on_status_changed("🔵 Local Edge Status: Concurrency Lock OK")
