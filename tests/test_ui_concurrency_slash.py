# tests/test_ui_concurrency_slash.py
import unittest
from unittest.mock import MagicMock, AsyncMock
from ui.controllers.agent_controller import AgentUiController
from ui.widgets.badges import ActionTag, AgentThought
from ui.widgets.diff_viewer import DiffBlock


class TestUiConcurrencyAndSlash(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.todo_mock = MagicMock()
        self.diff_mock = MagicMock()
        self.chat_container_mock = MagicMock()
        self.chat_container_mock.mount = MagicMock()
        self.chat_container_mock.children = []
        self.status_bar_mock = MagicMock()
        self.app_mock = MagicMock()
        # Mock call_from_thread to invoke synchronously in tests
        self.app_mock.call_from_thread = lambda fn, *args, **kwargs: fn(*args, **kwargs)

        self.controller = AgentUiController(
            todo_widget=self.todo_mock,
            diff_widget=self.diff_mock,
            chat_container=self.chat_container_mock,
            status_bar=self.status_bar_mock,
            app=self.app_mock,
        )

    def test_init_concurrency_lock(self):
        self.assertFalse(self.controller.is_busy)

    def test_parse_command_input(self):
        self.assertTrue(self.controller.parse_command_input("/clear"))
        self.assertTrue(self.controller.parse_command_input("/status"))
        self.assertFalse(self.controller.parse_command_input("hello world"))

    async def test_handle_status_command(self):
        await self.controller.handle_command("/status")
        self.status_bar_mock.update.assert_called()

    async def test_handle_clear_command(self):
        self.chat_container_mock.remove_children = AsyncMock()
        await self.controller.handle_command("/clear")
        self.chat_container_mock.remove_children.assert_awaited()

    def test_bridge_overrides_use_safe_ui_update(self):
        self.controller.on_agent_thought("Thinking about the architecture...")
        self.chat_container_mock.mount.assert_called_once()
        widget = self.chat_container_mock.mount.call_args[0][0]
        self.assertIsInstance(widget, AgentThought)

        self.chat_container_mock.mount.reset_mock()
        self.controller.tool_started("read_file", path="core/dag.py")
        self.chat_container_mock.mount.assert_called_once()
        widget = self.chat_container_mock.mount.call_args[0][0]
        self.assertIsInstance(widget, ActionTag)
        self.assertEqual(widget.status, "in_progress")

        self.chat_container_mock.mount.reset_mock()
        self.controller.edit_proposed("core/dag.py", diff="+ new line", additions=1, removals=0)
        self.chat_container_mock.mount.assert_called_once()
        widget = self.chat_container_mock.mount.call_args[0][0]
        self.assertIsInstance(widget, DiffBlock)

    def test_tool_completed_updates_last_tag(self):
        tag = ActionTag("read_file", target="core/dag.py", status="in_progress")
        self.chat_container_mock.children = [tag]
        self.controller.tool_completed("read_file", ok=True)
        self.assertEqual(tag.status, "success")


if __name__ == "__main__":
    unittest.main()
