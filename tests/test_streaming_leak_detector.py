"""Tests for Streaming Leak Detector — _invoke_with_token_stream leak detection.

The non-streaming path in _invoke_llm_and_normalize has had leak detection
since day one. The streaming path (_invoke_with_token_stream) was missing it
until Fix 2. These tests verify the streaming leak detector catches the same
_LEAK_MARKERS and routes them through _note_provider_failure.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch

from engine.loop import ExecutionLoop
from engine.state import RuntimeState

# ── Shared leak markers (mirrors engine._loop_types._LEAK_MARKERS) ──────

_LEAK_SAMPLES = [
    "## TODO Discipline",
    "<hard_rules>",
    "<system_instructions>",
    "<system_identity>",
    "CRITICAL RULE:",
    "TASK CLASSIFICATION",
    "SMALL-TALK & CHIT-CHAT PROTOCOL",
]

_SAFE_SAMPLES = [
    "Hello, how can I help?",
    "Based on the file analysis, here are the results:",
    "The answer is 42.",
    "I found 3 files matching the pattern.",
    "This is a normal response without any system markers.",
]


@pytest.fixture
def loop():
    """Create a minimal ExecutionLoop for testing.

    IMPORTANT: llm_provider is NOT set, so it defaults to
    _resolve_default_provider(). This ensures the ``is`` identity
    check inside _invoke_llm_and_normalize passes when we patch
    _resolve_default_provider below.
    """
    state = RuntimeState(session_id="leak-test")
    loop = ExecutionLoop(state=state)  # no explicit llm_provider
    # Disable the streaming-fallback so we always test streaming
    loop._no_stream = False

    # Install tracking wrapper on _note_provider_failure
    loop._leak_called = False
    loop._leak_reason = ""
    original = loop._note_provider_failure

    def tracking(err: str):
        loop._leak_called = True
        loop._leak_reason = err
        return original(err)

    loop._note_provider_failure = tracking
    return loop


class TestStreamingLeakDetector:
    """Verify _invoke_with_token_stream catches leaked system markers."""

    def _assert_leak_detected(self, loop, tokens: list[str]):
        """Helper: generate *tokens* and assert leak detection fires."""
        from llm_router import router as real_router

        # Patch generate_token_stream at the SOURCE (llm_router.router)
        # so the local ``from llm_router import router as _router``
        # inside _invoke_with_token_stream picks it up.
        fake_gen = MagicMock(return_value=iter(
            {"content": t} for t in tokens
        ))

        with patch.object(real_router, "generate_token_stream", fake_gen):
            # Patch _resolve_default_provider to return the SAME object
            # that was stored in loop.llm_provider during __init__.
            with patch("engine.loop._resolve_default_provider",
                       return_value=loop.llm_provider):
                result = loop._invoke_llm_and_normalize()

        assert loop._leak_called, (
            f"_note_provider_failure should be called on leak; "
            f"tokens={tokens!r}"
        )
        # LLM invocation returns a structured result, not a raw tuple
        from core.turn_outcome import LLMInvocationResult, LLMInvocationStatus
        assert isinstance(result, LLMInvocationResult), (
            f"Expected LLMInvocationResult on leak, got {type(result).__name__}"
        )
        assert result.content == "", f"Expected empty content on leak, got {result.content!r}"
        assert result.error_type == "PromptLeak", (
            f"Expected PromptLeak error_type, got {result.error_type!r}"
        )
        assert result.status in (
            LLMInvocationStatus.FATAL_ERROR,
            LLMInvocationStatus.RETRYABLE_ERROR,
        ), f"Expected error status on leak, got {result.status}"

    def _assert_safe_not_flagged(self, loop, tokens: list[str]):
        """Helper: generate *tokens* and assert leak detector does NOT fire."""
        from llm_router import router as real_router

        loop._leak_called = False

        fake_gen = MagicMock(return_value=iter(
            {"content": t} for t in tokens
        ))

        with patch.object(real_router, "generate_token_stream", fake_gen):
            with patch("engine.loop._resolve_default_provider",
                       return_value=loop.llm_provider):
                loop._invoke_llm_and_normalize()

        assert not loop._leak_called, (
            f"Leak detector falsely flagged safe content; tokens={tokens!r}"
        )

    def test_catches_system_instructions(self, loop):
        """Streaming path detects <system_instructions>."""
        self._assert_leak_detected(loop, ["<system_instructions>"])

    def test_catches_todo_discipline(self, loop):
        """Streaming path detects '## TODO Discipline'."""
        self._assert_leak_detected(loop, ["## TODO Discipline"])

    def test_catches_task_classification(self, loop):
        """Streaming path detects 'TASK CLASSIFICATION'."""
        self._assert_leak_detected(loop, ["TASK CLASSIFICATION"])

    def test_all_leak_markers_caught(self, loop):
        """Every marker in _LEAK_MARKERS is caught."""
        for marker in _LEAK_SAMPLES:
            loop._leak_called = False
            from llm_router import router as real_router
            fake_gen = MagicMock(return_value=iter(
                [{"content": marker}]
            ))
            with patch.object(real_router, "generate_token_stream", fake_gen):
                with patch("engine.loop._resolve_default_provider",
                           return_value=loop.llm_provider):
                    loop._invoke_llm_and_normalize()
            assert loop._leak_called, (
                f"Streaming leak detector missed marker: {marker}"
            )

    def test_safe_content_not_flagged(self, loop):
        """Normal conversational content does NOT trigger the leak detector."""
        for safe in _SAFE_SAMPLES:
            self._assert_safe_not_flagged(loop, [safe])

    def test_leak_in_multi_token_stream(self, loop):
        """Leak marker among safe tokens is still detected."""
        self._assert_leak_detected(loop, [
            "Before the leak ",
            "<system_instructions>",
            " after the leak",
        ])

    def test_leak_across_token_boundaries(self, loop):
        """Marker split across tokens is detected after assembly.

        ''## TODO '' + ''Discipline continues'' → ''## TODO Discipline continues''
        which contains ''## TODO Discipline'' as a substring.
        """
        self._assert_leak_detected(loop, [
            "Before ",
            "## TODO ",
            "Discipline continues",
        ])
