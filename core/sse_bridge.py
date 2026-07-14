# core/sse_bridge.py
"""
High-Fidelity SSE & NDJSON Stream Consumer (Streaming Bridge).

Inspired by professional terminal agent streaming architectures:
  1. TCP Reassembly Buffer: Safely handles fragmented SSE/NDJSON lines across packet boundaries.
  2. Reasoning State Machine: Deterministically isolates reasoning (<think> / reasoning_content)
     from final user output text and tool calls.
  3. UI Bridge Integration: Directly feeds incremental reasoning & text deltas into Nabd's UIBridge.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Coroutine, Dict, List, Optional

from core.ui_bridge import get_bridge
from core.sanitize import sanitize


class StreamState(Enum):
    IDLE = auto()
    REASONING = auto()
    TEXT = auto()
    TOOL_CALL = auto()
    COMPLETED = auto()


@dataclass
class TokenUsageEconomics:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class SSEStreamReassembler:
    """
    TCP Segmentation Reassembly Buffer.
    Prevents JSONDecodeError when network packets split a 'data: {...}' line in half.
    """

    def __init__(self):
        self._buffer = ""

    def feed(self, chunk: str) -> List[str]:
        """Feed raw string chunk and yield complete lines separated by newline."""
        self._buffer += chunk
        lines = self._buffer.split("\n")
        # Keep the trailing incomplete segment in buffer
        self._buffer = lines.pop()
        return [l.strip() for l in lines if l.strip()]

    def flush(self) -> Optional[str]:
        """Flush remaining contents in buffer at end of stream."""
        rem = self._buffer.strip()
        self._buffer = ""
        return rem if rem else None


class SSEStreamConsumer:
    """
    High-fidelity SSE Consumer engine that manages streaming events, reasoning transitions,
    token usage extraction, and UI Bridge updates.
    """

    def __init__(
        self,
        interleaved_thinking: bool = True,
        on_reasoning_delta: Optional[Callable[[str], None]] = None,
        on_text_delta: Optional[Callable[[str], None]] = None,
    ):
        self.interleaved_thinking = interleaved_thinking
        self._custom_on_reasoning = on_reasoning_delta
        self._custom_on_text = on_text_delta

        self.state = StreamState.IDLE
        self.reassembler = SSEStreamReassembler()
        self.usage = TokenUsageEconomics()

        # Accumulators
        self.reasoning_buffer = ""
        self.text_buffer = ""

    def _finalize_reasoning(self):
        """State Lock Guard: Flushes and seals reasoning before transitioning state."""
        if self.state == StreamState.REASONING:
            if self.reasoning_buffer.strip():
                clean_thought = sanitize(self.reasoning_buffer.strip())
                get_bridge().on_agent_thought(clean_thought)
            self.state = StreamState.IDLE

    def process_line(self, line: str) -> bool:
        """
        Process a single reassembled SSE/NDJSON line.
        Returns True if '[DONE]' or stream completion event reached.
        """
        if not line:
            return False

        payload_str = line
        if line.startswith("data: "):
            payload_str = line[len("data: "):].strip()

        if payload_str == "[DONE]":
            self._finalize_reasoning()
            self.state = StreamState.COMPLETED
            return True

        try:
            event_data = json.loads(payload_str)
        except json.JSONDecodeError:
            # Ignore non-JSON heartbeat or comment lines
            return False

        return self.process_event(event_data)

    def process_event(self, event_data: Dict[str, Any]) -> bool:
        """Process structured JSON payload from SSE event."""
        # Check usage economics (Anthropic / OpenAI / OpenRouter formatting)
        usage_data = event_data.get("usage")
        if usage_data and isinstance(usage_data, dict):
            self.usage.prompt_tokens = usage_data.get("prompt_tokens", self.usage.prompt_tokens)
            self.usage.completion_tokens = usage_data.get("completion_tokens", self.usage.completion_tokens)
            self.usage.cache_read_tokens = usage_data.get("cache_read_input_tokens", usage_data.get("cache_read_tokens", self.usage.cache_read_tokens))
            self.usage.cache_write_tokens = usage_data.get("cache_creation_input_tokens", usage_data.get("cache_write_tokens", self.usage.cache_write_tokens))

        choices = event_data.get("choices", [])
        if not choices:
            return False

        choice = choices[0]
        delta = choice.get("delta", {})

        # Extract reasoning content (DeepSeek / Llama-3.3 / Claude thinking)
        reasoning_delta = delta.get("reasoning_content") or delta.get("thinking")
        if reasoning_delta:
            if self.state != StreamState.REASONING:
                self.state = StreamState.REASONING
            self.reasoning_buffer += reasoning_delta

            if self.interleaved_thinking:
                if self._custom_on_reasoning:
                    self._custom_on_reasoning(reasoning_delta)
                else:
                    get_bridge().on_status_changed(f"✽ Thinking: {reasoning_delta[:50]}...")

        # Extract normal text delta
        text_delta = delta.get("content")
        if text_delta:
            # Transition out of reasoning if needed
            self._finalize_reasoning()
            self.state = StreamState.TEXT
            self.text_buffer += text_delta

            if self._custom_on_text:
                self._custom_on_text(text_delta)
            else:
                get_bridge().on_status_changed("🟢 Streaming Response...")

        # Check finish reason
        finish_reason = choice.get("finish_reason")
        if finish_reason:
            self._finalize_reasoning()
            self.state = StreamState.COMPLETED
            return True

        return False

    def feed_chunk(self, chunk: str) -> bool:
        """Feed raw network chunk into reassembler and process all complete lines."""
        lines = self.reassembler.feed(chunk)
        for line in lines:
            if self.process_line(line):
                return True
        return False

    def finish_stream(self):
        """Flush remaining reassembly buffer at end of connection."""
        remaining_line = self.reassembler.flush()
        if remaining_line:
            self.process_line(remaining_line)
        self._finalize_reasoning()
        self.state = StreamState.COMPLETED
