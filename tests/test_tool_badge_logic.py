"""Unit tests for tool-badge classification and terminal header formatting."""

from engine.renderer import _format_args
from engine.ui_theme import map_tool_to_badge, tool_header
from ui.cc_style import _primary_arg, badge_for_tool, tool_header_line


class TestToolBadgeClassification:
    def test_file_system_read_actions_are_read(self):
        for action in ("read", "list", "scan", "open"):
            assert map_tool_to_badge("file_system", {"action": action}) == "READ"
            assert badge_for_tool("file_system", {"action": action})[0] == "READ"

    def test_file_system_mutating_actions_are_edit(self):
        for action in ("edit", "write", "append", "replace", "patch"):
            assert map_tool_to_badge("file_system", {"action": action}) == "EDIT"
            assert badge_for_tool("file_system", {"action": action})[0] == "EDIT"

    def test_shell_aliases_are_shell(self):
        for tool in ("shell", "shell_exec"):
            assert map_tool_to_badge(tool, {}) == "SHELL"
            assert badge_for_tool(tool, {})[0] == "SHELL"

    def test_engine_classifier_recognizes_exec_and_bash(self):
        assert map_tool_to_badge("exec", {}) == "SHELL"
        assert map_tool_to_badge("bash", {}) == "SHELL"

    def test_task_aliases_are_task(self):
        for tool in ("task", "subagent_runner", "delegate"):
            assert map_tool_to_badge(tool, {}) == "TASK"
            assert badge_for_tool(tool, {})[0] == "TASK"

    def test_specialized_tools_keep_their_visual_category(self):
        assert map_tool_to_badge("todo_write", {}) == "TODOS"
        assert map_tool_to_badge("web_search", {}) == "SEARCH"
        assert map_tool_to_badge("memory_lookup", {}) == "MEMORY"
        assert map_tool_to_badge("rag_query", {}) == "RAG"

    def test_unknown_tool_falls_back_to_bounded_uppercase_label(self):
        assert map_tool_to_badge("custom_tool_name", {}) == "CUSTOM_TOOL_"
        assert map_tool_to_badge("", {}) == "TOOL"


class TestToolHeaderArguments:
    def test_primary_arg_uses_context_priority(self):
        args = {
            "query": "search context",
            "command": "pytest -q",
            "path": "core/plan_apply.py",
        }

        assert _primary_arg(args) == "core/plan_apply.py"

    def test_primary_arg_falls_back_to_first_non_empty_string(self):
        assert _primary_arg({"count": 3, "payload": "inspect this"}) == "inspect this"
        assert _primary_arg(None) == ""
        assert _primary_arg({"path": "   ", "count": 3}) == ""

    def test_primary_arg_is_bounded_to_sixty_characters(self):
        value = "x" * 100

        assert _primary_arg({"path": value}) == "x" * 60

    def test_task_format_includes_role_prompt_and_graph_node(self):
        detail, extra = _format_args(
            "TASK",
            "task",
            {
                "role": "review",
                "task_id": "review-config",
                "prompt": "Review configuration and provide evidence-backed findings.",
            },
        )

        assert detail.startswith("[review]")
        assert "Review configuration" in detail
        # `_format_args` bounds the prompt portion; brackets add one character
        # on each side to the rendered detail.
        assert len(detail) <= 61
        assert extra == "node=review-config"

    def test_shell_format_flattens_and_bounds_command(self):
        command = "pytest -q\n tests/test_task_graph.py " + ("x" * 100)
        detail, extra = _format_args("SHELL", "shell", {"command": command})

        assert detail.startswith("[pytest -q  tests/test_task_graph.py")
        assert detail.endswith("...]")
        assert extra == ""
        assert len(detail) <= 63

    def test_read_and_edit_format_use_file_path(self):
        assert _format_args("READ", "file", {"path": "core/task_graph.py"}) == (
            "[core/task_graph.py]",
            "",
        )
        assert _format_args("EDIT", "file", {"file": "engine/renderer.py"}) == (
            "[engine/renderer.py]",
            "",
        )


class TestToolHeaderRendering:
    def test_tool_header_contains_badge_detail_and_extra(self):
        rendered = tool_header("READ", "[core/task_graph.py]", "382 lines")

        assert "READ" in rendered
        assert "core/task_graph.py" in rendered
        assert "382 lines" in rendered

    def test_tool_header_line_uses_action_aware_badge(self):
        assert tool_header_line(
            "file_system", {"action": "write", "path": "engine/renderer.py"}
        ) == "EDIT  engine/renderer.py"
        assert tool_header_line(
            "file_system", {"action": "read", "path": "engine/renderer.py"}
        ) == "READ  engine/renderer.py"

    def test_tool_header_line_exposes_task_role_without_raw_arguments(self):
        header = tool_header_line(
            "task",
            {
                "role": "review",
                "prompt": "Inspect the diff",
                "secret": "do-not-render",
            },
        )

        assert header == "TASK  review"
        assert "do-not-render" not in header

    def test_tool_header_line_is_bounded_for_long_context(self):
        header = tool_header_line("shell", {"command": "x" * 200})

        assert header.startswith("SHELL  ")
        # `_primary_arg` keeps 60 characters; the `SHELL  ` prefix adds 7.
        assert len(header) <= 67
