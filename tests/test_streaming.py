"""Tests for SSE streaming pipeline: parser -> client -> router -> loop."""

from __future__ import annotations

import pytest

from core.sse import SSELineReader
from core.llm import OpenRouterClient


class TestSSELineReader:
    def test_chunked_assembly(self):
        data = b'data: {"content":"Hel"}\n\ndata: {"content":"lo"}\n\ndata: [DONE]\n'
        full = ""
        for c in SSELineReader(iter([data])):
            full += c.get("content", "")
        assert full == "Hello"

    def test_empty_lines_skipped(self):
        data = b"\n\ndata: {\"x\":1}\n\n\ndata: [DONE]\n"
        assert len(list(SSELineReader(iter([data])))) == 1

    def test_malformed_json_skipped(self):
        data = b"data: {bad}\n\ndata: {\"ok\":1}\n\ndata: [DONE]\n"
        assert len(list(SSELineReader(iter([data])))) == 1

    def test_no_content_returns_empty(self):
        data = b"data: {}\n\ndata: [DONE]\n"
        chunks = list(SSELineReader(iter([data])))
        # The empty JSON object is a valid SSE frame but carries no content.
        assert all(c.get("content", "") == "" for c in chunks)


class TestExtractContentDelta:
    def test_normal_content(self):
        from core.llm import OpenRouterClient

        client = OpenRouterClient()
        event = {"choices": [{"delta": {"content": "Hello"}}]}
        result = client._extract_content_delta(event)
        assert result == {"content": "Hello"}

    def test_missing_choices(self):
        client = OpenRouterClient()
        assert client._extract_content_delta({}) is None

    def test_empty_content(self):
        client = OpenRouterClient()
        event = {"choices": [{"delta": {"content": ""}}]}
        assert client._extract_content_delta(event) is None


class TestGenerateTokenStream:
    def test_fallback_to_generate_response(self):
        """Router calls generate_token_stream; when client has no stream(),
        falls back to generate_response and yields full content."""
        from llm_router import ProviderRouter, ProviderState

        class FakeNoStream:
            def generate_response(self, messages, **kwargs):
                return "full text answer"

        p = ProviderState(name="FAKE", client=FakeNoStream(), priority=0)
        router = ProviderRouter([p])
        deltas = list(router.generate_token_stream([{"role": "user", "content": "hi"}]))
        assert len(deltas) == 1
        assert deltas[0]["content"] == "full text answer"

    def test_unavailable_raises(self):
        """When all providers are on cooldown, raises RuntimeError."""
        import time
        from llm_router import ProviderRouter, ProviderState

        class FakeNoStream:
            def generate_response(self, messages, **kwargs):
                return "x"

        p = ProviderState(name="FAKE", client=FakeNoStream(), priority=0)
        p.cooldown_until = time.time() + 3600  # cooled down
        router = ProviderRouter([p])
        with pytest.raises(RuntimeError):
            list(router.generate_token_stream([{"role": "user", "content": "hi"}]))

    def test_streaming_yields_deltas(self):
        """When client.stream exists, deltas are yielded token-by-token."""
        from llm_router import ProviderRouter, ProviderState

        class FakeStream:
            def stream(self, messages, **kwargs):
                for t in ("Hel", "lo"):
                    yield {"content": t}
                return "Hello"

        p = ProviderState(name="FAKE", client=FakeStream(), priority=0)
        router = ProviderRouter([p])
        deltas = list(router.generate_token_stream([{"role": "user", "content": "hi"}]))
        assert [d["content"] for d in deltas] == ["Hel", "lo"]
