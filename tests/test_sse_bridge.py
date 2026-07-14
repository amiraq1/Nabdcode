# tests/test_sse_bridge.py
import unittest
from unittest.mock import MagicMock, patch
from core.sse_bridge import SSEStreamConsumer, StreamState


class TestSSEStreamConsumer(unittest.TestCase):
    @patch("core.sse_bridge.get_bridge")
    def test_fragmented_packet_reassembly_and_reasoning_lock(self, mock_get_bridge):
        bridge_mock = MagicMock()
        mock_get_bridge.return_value = bridge_mock

        consumer = SSEStreamConsumer(interleaved_thinking=True)

        # Chunk 1: Fragmented line
        chunk1 = 'data: {"choices": [{"delta": {"reasoning_content": "Deep'
        consumer.feed_chunk(chunk1)
        self.assertEqual(consumer.reassembler._buffer, chunk1)
        self.assertEqual(consumer.reasoning_buffer, "")

        # Chunk 2: Completion of line + newline (with correct matching braces)
        chunk2 = ' analysis..."}}]}\n'
        consumer.feed_chunk(chunk2)
        self.assertEqual(consumer.reasoning_buffer, "Deep analysis...")
        self.assertEqual(consumer.state, StreamState.REASONING)

        # Chunk 3: Transition to normal text content -> should flush reasoning to UI bridge
        chunk3 = 'data: {"choices": [{"delta": {"content": "Final answer"}}], "usage": {"prompt_tokens": 100, "completion_tokens": 5, "cache_read_input_tokens": 80}}\n'
        consumer.feed_chunk(chunk3)

        bridge_mock.on_agent_thought.assert_called_with("Deep analysis...")
        self.assertEqual(consumer.state, StreamState.TEXT)
        self.assertEqual(consumer.text_buffer, "Final answer")

        # Check Token Usage Economics
        self.assertEqual(consumer.usage.prompt_tokens, 100)
        self.assertEqual(consumer.usage.completion_tokens, 5)
        self.assertEqual(consumer.usage.cache_read_tokens, 80)


if __name__ == "__main__":
    unittest.main()
