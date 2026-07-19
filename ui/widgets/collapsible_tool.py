"""Collapsible Tool & Thought Bento Blocks for Nabd TUI.

Renders file reads, shell commands, and agent thoughts inside modular
Collapsible Bento cards that prevent TUI scroll fatigue.
"""

from __future__ import annotations

from textual.widgets import Collapsible, Static


def create_tool_trace_block(
    tool_name: str,
    file_path: str,
    line_count: int,
    full_output: str,
    collapsed: bool = True,
) -> Collapsible:
    """Create a collapsible neon Bento box for tool execution or file reads.

    Example title: 🔴 READ [core/llm.py] 382 lines
    """
    icon = "🔴" if "read" in tool_name.lower() or "file" in tool_name.lower() else "⚡"
    if line_count > 0:
        title = f"{icon} {tool_name.upper()} [{file_path}] {line_count} lines"
    else:
        title = f"{icon} {tool_name.upper()} [{file_path}]"

    content = Static(full_output, classes="tool-output-content")
    col = Collapsible(content, title=title, collapsed=collapsed, classes="bento-tool-block")
    return col


def create_thought_block(thought_text: str, step: int = 1, collapsed: bool = True) -> Collapsible:
    """Create a collapsible Bento box for agent internal thoughts."""
    title = f"🧠 THOUGHT [Step {step}] (Click to Expand)"
    content = Static(thought_text, classes="thought-block-content")
    col = Collapsible(content, title=title, collapsed=collapsed, classes="bento-thought-block")
    return col
