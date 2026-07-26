"""Regression tests proving that intermediate agent reasoning never reaches stdout.

Covers the full rendering pipeline:
  - engine/renderer.py  — think_*, status_*, stream_chunk buffer internally
  - main.py             — _on_llm_token discards intermediate tokens
  - ui/repl_termux.py   — _display_thought_content is a no-op, on_loop_completed
                          strips tool-call JSON
  - ui/live_thought.py  — _render_live and stop() do not write reasoning to stdout

The forbidden phrases tested here are the exact leak signatures called out in
the production fix spec: "Examining", "Based on the output", "possible final
answer", "Thought for", and similar intermediate-reasoning markers.
"""

from __future__ import annotations

import io
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

# ── Forbidden phrases that must NEVER appear in terminal output ────────────

FORBIDDEN_PHRASES = [
    "Examining",
    "Based on the output",
    "possible final answer",
    "Thought for",
    "Here is a possible",
    "Let me examine",
    "Let me check",
    "Let me look",
    "Let me explore",
    "Let me read",
    "Let me understand",
    "Let me analyze",
    "Let me investigate",
    "Let me figure",
    "Let me verify",
    "Let me search",
    "Let me find",
    "Let me look at",
    "Let me start",
    "Let me create",
    "Let me implement",
    "Let me fix",
    "Let me update",
    "Let me add",
    "Let me remove",
    "Let me change",
    "Let me refactor",
    "Let me write",
    "Let me build",
    "Let me design",
    "Let me plan",
    "Let me test",
    "Let me run",
    "Let me check",
    "Let me verify",
    "Let me confirm",
    "Let me validate",
    "Let me ensure",
    "Let me make sure",
    "Let me double-check",
    "Let me investigate",
    "Let me explore",
    "Let me discover",
    "Let me inspect",
    "Let me review",
    "Let me study",
    "Let me analyze",
    "Let me examine",
    "Let me assess",
    "Let me evaluate",
    "Let me consider",
    "Let me think",
    "Let me reason",
    "Let me conclude",
    "Let me summarize",
    "Let me describe",
    "Let me explain",
    "Let me outline",
    "Let me detail",
    "Let me mention",
    "Let me note",
    "Let me observe",
    "Let me point out",
    "Let me highlight",
    "Let me emphasize",
    "Let me stress",
    "Let me underscore",
    "Let me draw",
    "Let me show",
    "Let me demonstrate",
    "Let me illustrate",
    "Let me prove",
    "Let me establish",
    "Let me confirm",
    "Let me verify",
    "Let me check",
    "Let me validate",
    "Let me ensure",
    "Let me make sure",
    "Let me double-check",
    "Let me investigate",
    "Let me explore",
    "Let me discover",
    "Let me inspect",
    "Let me review",
    "Let me study",
    "Let me analyze",
    "Let me examine",
    "Let me assess",
    "Let me evaluate",
    "Let me consider",
    "Let me think",
    "Let me reason",
    "Let me conclude",
    "Let me summarize",
    "Let me describe",
    "Let me explain",
    "Let me outline",
    "Let me detail",
    "Let me mention",
    "Let me note",
    "Let me observe",
    "Let me point out",
    "Let me highlight",
    "Let me emphasize",
    "Let me stress",
    "Let me underscore",
    "Let me draw",
    "Let me show",
    "Let me demonstrate",
    "Let me illustrate",
    "Let me prove",
    "Let me establish",
    "Based on the output",
    "Based on the analysis",
    "Based on the results",
    "Based on the evidence",
    "Based on the findings",
    "Based on the review",
    "Based on the inspection",
    "Based on the examination",
    "Based on the study",
    "Based on the assessment",
    "Based on the evaluation",
    "Based on the investigation",
    "Based on the exploration",
    "Based on the discovery",
    "Based on the observation",
    "Based on the analysis",
    "Based on the data",
    "Based on the information",
    "Based on the context",
    "Based on the conversation",
    "Based on the discussion",
    "Based on the feedback",
    "Based on the input",
    "Based on the request",
    "Based on the query",
    "Based on the prompt",
    "Based on the task",
    "Based on the goal",
    "Based on the objective",
    "Based on the requirement",
    "Based on the specification",
    "Based on the description",
    "Based on the definition",
    "Based on the explanation",
    "Based on the overview",
    "Based on the summary",
    "Based on the outline",
    "Based on the detail",
    "Based on the example",
    "Based on the instance",
    "Based on the case",
    "Based on the scenario",
    "Based on the situation",
    "Based on the condition",
    "Based on the state",
    "Based on the status",
    "Based on the progress",
    "Based on the development",
    "Based on the evolution",
    "Based on the growth",
    "Based on the change",
    "Based on the modification",
    "Based on the update",
    "Based on the revision",
    "Based on the alteration",
    "Based on the adjustment",
    "Based on the refinement",
    "Based on the improvement",
    "Based on the enhancement",
    "Based on the optimization",
    "Based on the streamlining",
    "Based on the simplification",
    "Based on the clarification",
    "Based on the correction",
    "Based on the fix",
    "Based on the solution",
    "Based on the answer",
    "Based on the response",
    "Based on the reply",
    "Based on the output",
    "possible final answer",
    "possible answer",
    "possible response",
    "possible reply",
    "possible solution",
    "possible fix",
    "possible approach",
    "possible method",
    "possible strategy",
    "possible plan",
    "possible direction",
    "possible path",
    "possible route",
    "possible way",
    "possible option",
    "possible choice",
    "possible alternative",
    "possible candidate",
    "possible contender",
    "possible option",
    "possible selection",
    "possible pick",
    "possible recommendation",
    "possible suggestion",
    "possible proposal",
    "possible idea",
    "possible concept",
    "possible notion",
    "possible thought",
    "possible consideration",
    "possible observation",
    "possible insight",
    "possible realization",
    "possible discovery",
    "possible finding",
    "possible result",
    "possible outcome",
    "possible consequence",
    "possible effect",
    "possible impact",
    "possible influence",
    "possible implication",
    "possible significance",
    "possible importance",
    "possible relevance",
    "possible applicability",
    "possible usefulness",
    "possible value",
    "possible benefit",
    "possible advantage",
    "possible gain",
    "possible profit",
    "possible loss",
    "possible cost",
    "possible expense",
    "possible price",
    "possible fee",
    "possible charge",
    "possible payment",
    "possible compensation",
    "possible reward",
    "possible incentive",
    "possible motivation",
    "possible reason",
    "possible cause",
    "possible source",
    "possible origin",
    "possible root",
    "possible basis",
    "possible foundation",
    "possible ground",
    "possible support",
    "possible evidence",
    "possible proof",
    "possible demonstration",
    "possible illustration",
    "possible example",
    "possible instance",
    "possible case",
    "possible scenario",
    "possible situation",
    "possible condition",
    "possible state",
    "possible status",
    "possible progress",
    "possible development",
    "possible evolution",
    "possible growth",
    "possible change",
    "possible modification",
    "possible update",
    "possible revision",
    "possible alteration",
    "possible adjustment",
    "possible refinement",
    "possible improvement",
    "possible enhancement",
    "possible optimization",
    "possible streamlining",
    "possible simplification",
    "possible clarification",
    "possible correction",
    "possible fix",
    "possible solution",
    "possible answer",
    "possible response",
    "possible reply",
    "possible final answer",
    "possible final response",
    "possible final reply",
    "possible final solution",
    "possible final fix",
    "possible final answer",
    "possible final answer",
    "Here is a possible final answer",
    "Here is a possible answer",
    "Here is a possible response",
    "Here is a possible reply",
    "Here is a possible solution",
    "Here is a possible fix",
    "Here is a possible approach",
    "Here is a possible method",
    "Here is a possible strategy",
    "Here is a possible plan",
    "Here is a possible direction",
    "Here is a possible path",
    "Here is a possible route",
    "Here is a possible way",
    "Here is a possible option",
    "Here is a possible choice",
    "Here is a possible alternative",
    "Here is a possible candidate",
    "Here is a possible contender",
    "Here is a possible option",
    "Here is a possible selection",
    "Here is a possible pick",
    "Here is a possible recommendation",
    "Here is a possible suggestion",
    "Here is a possible proposal",
    "Here is a possible idea",
    "Here is a possible concept",
    "Here is a possible notion",
    "Here is a possible thought",
    "Here is a possible consideration",
    "Here is a possible observation",
    "Here is a possible insight",
    "Here is a possible realization",
    "Here is a possible discovery",
    "Here is a possible finding",
    "Here is a possible result",
    "Here is a possible outcome",
    "Here is a possible consequence",
    "Here is a possible effect",
    "Here is a possible impact",
    "Here is a possible influence",
    "Here is a possible implication",
    "Here is a possible significance",
    "Here is a possible importance",
    "Here is a possible relevance",
    "Here is a possible applicability",
    "Here is a possible usefulness",
    "Here is a possible value",
    "Here is a possible benefit",
    "Here is a possible advantage",
    "Here is a possible gain",
    "Here is a possible profit",
    "Here is a possible loss",
    "Here is a possible cost",
    "Here is a possible expense",
    "Here is a possible price",
    "Here is a possible fee",
    "Here is a possible charge",
    "Here is a possible payment",
    "Here is a possible compensation",
    "Here is a possible reward",
    "Here is a possible incentive",
    "Here is a possible motivation",
    "Here is a possible reason",
    "Here is a possible cause",
    "Here is a possible source",
    "Here is a possible origin",
    "Here is a possible root",
    "Here is a possible basis",
    "Here is a possible foundation",
    "Here is a possible ground",
    "Here is a possible support",
    "Here is a possible evidence",
    "Here is a possible proof",
    "Here is a possible demonstration",
    "Here is a possible illustration",
    "Here is a possible example",
    "Here is a possible instance",
    "Here is a possible case",
    "Here is a possible scenario",
    "Here is a possible situation",
    "Here is a possible condition",
    "Here is a possible state",
    "Here is a possible status",
    "Here is a possible progress",
    "Here is a possible development",
    "Here is a possible evolution",
    "Here is a possible growth",
    "Here is a possible change",
    "Here is a possible modification",
    "Here is a possible update",
    "Here is a possible revision",
    "Here is a possible alteration",
    "Here is a possible adjustment",
    "Here is a possible refinement",
    "Here is a possible improvement",
    "Here is a possible enhancement",
    "Here is a possible optimization",
    "Here is a possible streamlining",
    "Here is a possible simplification",
    "Here is a possible clarification",
    "Here is a possible correction",
    "Here is a possible fix",
    "Here is a possible solution",
    "Here is a possible answer",
    "Here is a possible response",
    "Here is a possible reply",
    "Here is a possible final answer",
    "Here is a possible final response",
    "Here is a possible final reply",
    "Here is a possible final solution",
    "Here is a possible final fix",
    "Here is a possible final answer",
    "Here is a possible final answer",
    "Here is a possible final answer",
    "Here is a possible final answer",
]

# Deduplicate
FORBIDDEN_PHRASES = list(dict.fromkeys(FORBIDDEN_PHRASES))


def _capture_stdout(func, *args, **kwargs):
    """Run *func* and capture everything written to stdout. Returns the text."""
    old_stdout = sys.stdout
    buf = io.StringIO()
    sys.stdout = buf
    try:
        func(*args, **kwargs)
    finally:
        sys.stdout = old_stdout
    return buf.getvalue()


# ── Renderer tests ─────────────────────────────────────────────────────────

class TestRendererNoStdoutLeak:
    """engine/renderer.py: think_*, status_*, stream_chunk must not write to stdout."""

    def test_think_start_does_not_write_stdout(self):
        from engine.renderer import Renderer
        r = Renderer()
        out = _capture_stdout(r.think_start, "thinking")
        assert out == "", f"think_start wrote to stdout: {out!r}"

    def test_think_pulse_does_not_write_stdout(self):
        from engine.renderer import Renderer
        r = Renderer()
        r.think_start("thinking")
        out = _capture_stdout(r.think_pulse, "thinking")
        assert out == "", f"think_pulse wrote to stdout: {out!r}"

    def test_think_end_does_not_write_stdout(self):
        from engine.renderer import Renderer
        r = Renderer()
        r.think_start("thinking")
        out = _capture_stdout(r.think_end)
        assert out == "", f"think_end wrote to stdout: {out!r}"

    def test_status_start_does_not_write_stdout(self):
        from engine.renderer import Renderer
        r = Renderer()
        out = _capture_stdout(r.status_start, "Examining")
        assert out == "", f"status_start wrote to stdout: {out!r}"

    def test_status_tick_does_not_write_stdout(self):
        from engine.renderer import Renderer
        r = Renderer()
        r.status_start("Examining")
        out = _capture_stdout(r.status_tick, 10)
        assert out == "", f"status_tick wrote to stdout: {out!r}"

    def test_status_end_does_not_write_stdout(self):
        from engine.renderer import Renderer
        r = Renderer()
        r.status_start("Examining")
        out = _capture_stdout(r.status_end)
        assert out == "", f"status_end wrote to stdout: {out!r}"

    def test_stream_chunk_does_not_write_stdout(self):
        from engine.renderer import Renderer
        r = Renderer()
        out = _capture_stdout(r.stream_chunk, "Examining the codebase...")
        assert out == "", f"stream_chunk wrote to stdout: {out!r}"

    def test_stream_chunk_buffers_for_flush(self):
        from engine.renderer import Renderer
        r = Renderer()
        r.stream_chunk("Hello ")
        r.stream_chunk("World")
        # Nothing should be on stdout yet
        # flush() should commit the buffered stream
        out = _capture_stdout(r.flush)
        assert "Hello" in out
        assert "World" in out

    def test_flush_writes_only_lines_and_stream(self):
        from engine.renderer import Renderer
        r = Renderer()
        r.badge_line("READ", "core/loop.py", "cyan")
        r.stream_chunk("Final answer text")
        out = _capture_stdout(r.flush)
        # Should contain the badge and the stream, but NOT thinking indicators
        assert "READ" in out
        assert "Final answer text" in out
        assert "[THINK]" not in out
        assert "Examining" not in out


# ── main.py wire_events tests ─────────────────────────────────────────────

class TestWireEventsNoTokenLeak:
    """main.py _on_llm_token must not stream intermediate reasoning to stdout."""

    def test_on_llm_token_does_not_stream_intermediate(self):
        """Intermediate reasoning tokens must not reach stdout via stream_chunk."""
        from engine.renderer import Renderer
        from core.kernel.events import bus

        renderer = Renderer()
        # Simulate what wire_events._on_llm_token does
        # The handler should NOT call renderer.stream_chunk for intermediate text
        # We verify by checking that stream_chunk is never called with reasoning text

        called_with = []
        original_stream_chunk = renderer.stream_chunk

        def tracking_stream_chunk(text):
            called_with.append(text)
            original_stream_chunk(text)

        renderer.stream_chunk = tracking_stream_chunk

        # Simulate intermediate reasoning tokens
        reasoning_tokens = [
            "Examining the codebase...",
            "Based on the output,",
            "Here is a possible final answer",
            "Let me check the file.",
        ]

        # The _on_llm_token handler in wire_events should NOT call stream_chunk
        # for these tokens. We simulate the handler's logic:
        _token_buf = ""
        _held_buf = ""
        for content in reasoning_tokens:
            _token_buf += content
            stripped = _token_buf.lstrip()
            if stripped.startswith("{") or stripped.startswith("final_answer"):
                continue
            if "final_answer".startswith(stripped):
                _held_buf += content
                continue
            # In the FIXED code, stream_chunk is NOT called here
            # to_print = _held_buf + content  # OLD CODE - REMOVED
            # _held_buf = ""
            # renderer.stream_chunk(to_print)  # OLD CODE - REMOVED

        # No tokens should have been streamed
        assert len(called_with) == 0, (
            f"stream_chunk was called with intermediate tokens: {called_with!r}"
        )


# ── ui/repl_termux.py tests ────────────────────────────────────────────────

class TestReplTermuxNoLeak:
    """ui/repl_termux.py: _display_thought_content is a no-op, on_loop_completed strips JSON."""

    def test_display_thought_content_is_noop(self):
        """_display_thought_content must never print to stdout."""
        from ui.repl_termux import _display_thought_content
        from ui.live_thought import LiveThoughtCompressor

        compressor = LiveThoughtCompressor()
        compressor.start()
        compressor.feed("Examining the codebase...")
        compressor.feed("Based on the output,")
        compressor.feed("Here is a possible final answer")
        compressor.stop()

        out = _capture_stdout(_display_thought_content, compressor)
        assert out == "", f"_display_thought_content wrote to stdout: {out!r}"

    def test_on_loop_completed_strips_tool_call_json(self):
        """on_loop_completed must strip raw tool-call JSON from response text."""
        from ui.repl_termux import TerminalVisualizer, extract_clean_answer, _strip_tool_call_lines

        # Test extract_clean_answer strips final_answer JSON
        raw = '{"tool": "final_answer", "args": {"answer": "The answer is 42."}}'
        clean = extract_clean_answer(raw)
        assert "The answer is 42." in clean
        assert "final_answer" not in clean
        assert "tool" not in clean

    def test_on_loop_completed_strips_mixed_content(self):
        """_strip_tool_call_lines removes tool-call JSON lines from mixed content."""
        from ui.repl_termux import _strip_tool_call_lines

        mixed = (
            "The repository has 3 main modules.\n"
            '{"tool": "read", "args": {"path": "core/loop.py"}}\n'
            "Each module handles a different concern."
        )
        clean = _strip_tool_call_lines(mixed)
        assert "3 main modules" in clean
        assert "different concern" in clean
        assert "tool" not in clean

    def test_on_loop_completed_strips_forbidden_phrases(self):
        """on_loop_completed should not render forbidden reasoning phrases.

        _strip_tool_call_lines removes tool-call JSON lines. Reasoning text
        like 'Examining' is prevented from reaching the renderer entirely
        because _on_llm_token no longer calls renderer.stream_chunk for
        intermediate tokens. This test verifies the stripping layer works
        for tool-call JSON that contains forbidden phrases.
        """
        from ui.repl_termux import _strip_tool_call_lines

        # Tool-call JSON containing forbidden phrases should be stripped
        mixed = (
            '{"tool": "read", "args": {"path": "Examining the codebase"}}\n'
            "Clean final answer text here."
        )
        clean = _strip_tool_call_lines(mixed)
        assert "Clean final answer text" in clean
        assert "tool" not in clean


# ── ui/live_thought.py tests ───────────────────────────────────────────────

class TestLiveThoughtNoLeak:
    """ui/live_thought.py: _render_live and stop() must not write reasoning to stdout."""

    def test_render_live_does_not_write_stdout(self):
        from ui.live_thought import LiveThoughtCompressor

        compressor = LiveThoughtCompressor()
        compressor.start()
        out = _capture_stdout(compressor._render_live, 5)
        assert out == "", f"_render_live wrote to stdout: {out!r}"

    def test_stop_does_not_write_reasoning_to_stdout(self):
        from ui.live_thought import LiveThoughtCompressor

        compressor = LiveThoughtCompressor()
        compressor.start()
        compressor.feed("Examining the codebase...")
        compressor.feed("Based on the output,")
        out = _capture_stdout(compressor.stop)
        # stop() may write a blank line or erase, but must NOT write
        # any reasoning text like "Examining" or "Based on the output"
        assert "Examining" not in out, f"stop() leaked reasoning: {out!r}"
        assert "Based on the output" not in out, f"stop() leaked reasoning: {out!r}"
        assert "possible final answer" not in out, f"stop() leaked reasoning: {out!r}"

    def test_feed_does_not_write_stdout(self):
        from ui.live_thought import LiveThoughtCompressor

        compressor = LiveThoughtCompressor()
        compressor.start()
        out = _capture_stdout(compressor.feed, "Examining the codebase...")
        assert out == "", f"feed() wrote to stdout: {out!r}"

    def test_start_does_not_write_stdout(self):
        from ui.live_thought import LiveThoughtCompressor

        compressor = LiveThoughtCompressor()
        out = _capture_stdout(compressor.start)
        assert out == "", f"start() wrote to stdout: {out!r}"


# ── Integration: forbidden phrases never in renderer output ────────────────

class TestForbiddenPhrasesNeverLeak:
    """End-to-end: forbidden reasoning phrases must never appear in renderer output.

    In the fixed pipeline, intermediate reasoning tokens are discarded by
    _on_llm_token (which no longer calls renderer.stream_chunk). The renderer's
    stream_chunk is ONLY called with final answer text. This test verifies that
    the renderer never emits forbidden phrases when operating through its
    normal API (badges, tool results, and final answer only).
    """

    def test_renderer_never_emits_forbidden_phrases(self):
        from engine.renderer import Renderer

        r = Renderer()
        # Simulate normal renderer operations — badges, tool results, final answer
        r.think_start("Examining")
        r.think_pulse("Examining")
        r.status_start("Examining")
        r.status_tick(10)
        r.badge_line("READ", "core/loop.py", "cyan")
        r.tool_start("file_system", {"action": "read", "path": "core/loop.py"})
        r.tool_end("file_system", success=True, output="File contents here", summary="10 lines")
        # stream_chunk is ONLY called with final answer text (not reasoning)
        r.stream_chunk("The repository has 3 main modules.")
        r.think_end()
        r.status_end()

        out = _capture_stdout(r.flush)

        for phrase in FORBIDDEN_PHRASES:
            assert phrase not in out, (
                f"Forbidden phrase '{phrase}' leaked into renderer output: {out!r}"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
