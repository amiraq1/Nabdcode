"""Nabd OS Textual UI Terminal application."""

from __future__ import annotations

import asyncio
import os
import platform
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer
from textual.widgets import Input, Static, Markdown
from textual.binding import Binding

from core.sanitize import sanitize, fix_arabic_reversal

# Stateless components now live in their own modular packages,
# sharing the central Design System (ui/theme.py).
from ui.widgets.badges import ActionTag
from ui.widgets.diff_viewer import DiffBlock
from ui.widgets.checklist import TodoBlock
from ui.widgets.prompt import ActivePromptInput
from ui.widgets.collapsible_tool import create_tool_trace_block, create_thought_block
from ui.controllers.agent_controller import AgentUiController


class NabdTerminal(App):
    """الواجهة الرئيسية التفاعلية لوكيل Nabd."""

    CSS = """
    Screen { background: #000000; layout: vertical; }
    #header-box { height: 5; background: #000000; border-bottom: solid #222222; content-align: center middle; text-style: bold; }
    #chat-container { height: 1fr; padding: 1 2; color: #a3a3a3; scrollbar-background: #000000; scrollbar-color: #444444; }
    #chat-container Markdown, #chat-container Static { color: #a3a3a3; }
    #status-bar { height: 1; background: #0a0a0c; color: #737373; padding-left: 2; }
    #input-bar { dock: bottom; height: 3; background: #000000; border-top: solid #222222; }
    Input { width: 100%; border: none; background: transparent; color: #a3a3a3; }
    Input:focus { border: solid #666666; }
    .user-msg-block { background: #111113; border-left: solid #a3a3a3; padding: 1 2; margin-bottom: 1; }
    .user-msg-block Static { color: #ffffff; }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
    ]

    def __init__(self, agent_runner_func=None):
        super().__init__()
        self.agent_runner = agent_runner_func
        self.ui_controller = None  # يُحقن في on_mount

    def compose(self) -> ComposeResult:
        banner_text = (
            r"█▄ █ ▄▀█ █▄▀ █▀▄   █▀▀ █▀█ █▀▄ █▀▀" "\n"
            r"█ ▀█ █▀█ █▄█ █▄▀   █▄▄ █▄█ █▄▀ ██▄"
        )
        active_model = os.getenv("OPENROUTER_MODEL", "gemma-3-27b:free").split("/")[-1]
        current_repo = os.path.basename(os.getcwd())
        arch = platform.machine()

        header_styled = Text()
        header_styled.append(f"{banner_text}\n", style="bold #ffffff")
        header_styled.append(
            f" ⬢ Model: {active_model}  |  Workspace: {current_repo}  |  Env: Termux ({arch})",
            style="dim #737373"
        )

        yield Static(header_styled, id="header-box")

        with ScrollableContainer(id="chat-container"):
            yield TodoBlock(id="main-todo-block")
            yield DiffBlock(diff_data="", id="main-diff-block")

        yield Static("🟢 System Idle | Local Edge", id="status-bar")
        yield ActivePromptInput(placeholder="> Enter command or task...", id="input-bar")

    def on_mount(self) -> None:
        """يُستدعى فوراً بعد تركيب المكونات في الشاشة."""
        self.ui_controller = AgentUiController(
            todo_widget=self.query_one("#main-todo-block", TodoBlock),
            diff_widget=self.query_one("#main-diff-block", DiffBlock),
            chat_container=self.query_one("#chat-container", ScrollableContainer),
            status_bar=self.query_one("#status-bar", Static),
            app=self,
        )
        from core.ui_bridge import set_bridge
        set_bridge(self.ui_controller)

    def mount_tool_trace_block(
        self,
        tool_name: str,
        file_path: str,
        line_count: int,
        full_output: str,
    ) -> None:
        """إنشاء وحقن بطاقة أداة أو قراءة ملف قابلة للطي (Bento Box)."""
        block = create_tool_trace_block(tool_name, file_path, line_count, full_output)
        if self.ui_controller:
            self.ui_controller._mount_stream_widget(block)
        else:
            container = self.query_one("#chat-container", ScrollableContainer)
            container.mount(block)
            block.scroll_visible()

    def mount_thought_block(self, thought_text: str, step: int = 1) -> None:
        """إنشاء وحقن بطاقة تفكير قابلة للطي (Collapsible Thought Bento Block)."""
        block = create_thought_block(thought_text, step=step)
        if self.ui_controller:
            self.ui_controller._mount_stream_widget(block)
        else:
            container = self.query_one("#chat-container", ScrollableContainer)
            container.mount(block)
            block.scroll_visible()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        input_bar = event.input
        user_input = input_bar.value.strip()
        if not user_input:
            return

        controller = self.ui_controller

        # 0. 🔑 Edit Gateway: resolve pending edit approval BEFORE the busy lock.
        # The engine thread is frozen on a threading.Event.wait(); the user's
        # y/n answer decides whether the write proceeds or is rejected.
        if controller and controller.has_pending_edit():
            input_bar.value = ""
            approved = user_input.lower() in ("y", "yes")
            controller.resolve_pending_edit(approved)
            return

        # 1. 🔒 فحص قفل الحظر (Prevent Race Conditions)
        if controller and controller.is_busy:
            input_bar.value = ""
            return

        input_bar.value = ""

        # فحص الأوامر المائلة أولاً (Slash Commands)
        if controller and controller.parse_command_input(user_input):
            await controller.handle_command(user_input)
            return

        chat_container = self.query_one("#chat-container", ScrollableContainer)
        user_card = Static(f"[USER] {user_input}", classes="user-msg-block")
        await chat_container.mount(user_card)
        chat_container.scroll_end(animate=True)

        if controller:
            controller.is_busy = True
            controller.on_status_changed("⏳ Agent is Thinking | Spinning...")

        try:
            # 2. إطلاق المحرك في خيط منفصل عبر asyncio.to_thread مع تمرير الجسر
            if self.agent_runner:
                try:
                    result = await asyncio.to_thread(self.agent_runner, user_input, bridge=controller)
                except TypeError:
                    result = await asyncio.to_thread(self.agent_runner, user_input)
            else:
                await asyncio.sleep(0.5)
                result = "Mock: Backend not connected."

            # 4. بعد انتهاء المحرك يعيد الجواب النهائي ليركب في Markdown منفصل في الأسفل
            await chat_container.mount(Markdown(sanitize(str(result))))
            chat_container.scroll_end(animate=True)

            if controller:
                controller.on_action_triggered("SYSTEM", "Execution Completed")

        except Exception as exc:
            if controller:
                controller.on_action_triggered("ERROR", f"Execution Failed: {str(exc)}")
        finally:
            if controller:
                controller.is_busy = False
                controller.on_status_changed("🟢 System Idle | Local Edge")


def launch_stream_tui(agent_runner_func=None):
    """تشغيل واجهة Nabd التفاعلية المعتمدة على Textual.

    تطابق دالة core.tui.launch_stream_tui في التوقيع بحيث يستدعيها main.py
    دون تعديل. تحجب التنفيذ حتى يخرج المستخدم.
    """
    NabdTerminal(agent_runner_func).run()


if __name__ == "__main__":
    launch_stream_tui()
