"""OpenAI/OpenRouter SSE streaming parser — deterministic, zero external deps."""
from __future__ import annotations

import json
from typing import Any, Generator


class SSELineReader:
    """Yields parsed JSON chunks from an SSE byte stream.

    Handles the OpenAI/OpenRouter streaming format::

        data: {"choices":[{"delta":{"content":"Hello"},"index":0}]}
        data: [DONE]

    Pure standard-library implementation. No LLM, no network, no third-party
    deps. Iterating the reader yields each ``data:`` JSON object as a dict;
    ``data: [DONE]`` terminates iteration (returning the generator).
    """

    def __init__(self, byte_stream: Any) -> None:
        self._buf = b""
        self._stream = byte_stream

    def __iter__(self) -> Generator[dict[str, Any], None, None]:
        for line in self._iter_lines():
            parsed = self._parse_line(line)
            if parsed is True:  # data: [DONE] sentinel
                return
            if parsed is not None:
                yield parsed

    def _iter_lines(self) -> Generator[bytes, None, None]:
        for chunk in self._stream:
            self._buf += chunk
            while b"\n" in self._buf:
                line, self._buf = self._buf.split(b"\n", 1)
                yield line.strip()

    @staticmethod
    def _parse_line(line: bytes) -> Any:
        if not line:
            return None
        if line == b"data: [DONE]":
            return True  # sentinel — stop iteration
        if line.startswith(b"data: "):
            try:
                return json.loads(line[6:])
            except json.JSONDecodeError:
                return None
        return None
