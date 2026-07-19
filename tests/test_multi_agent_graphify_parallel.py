"""tests/test_multi_agent_graphify_parallel.py — Unit verification suite for Step B2 Parallel Dispatcher & Serial Fallback."""

import os
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from core.multi_agent_orchestrator import MultiAgentOrchestrator, OrchestratorAgent


class TestMultiAgentGraphifyParallel(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.orchestrator = MultiAgentOrchestrator()
        self.orchestrator.workspace_dir = self.test_dir

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_parallel_dispatch_and_aggregation_success(self):
        file_chunks = [
            {"chunk_num": 1, "content": "core/taste_engine.py"},
            {"chunk_num": 2, "content": "tools/graphify_tool.py"},
        ]
        prompt_template = "Chunk CHUNK_NUM/TOTAL_CHUNKS: FILE_LIST DEEP_MODE"

        results = self.orchestrator.process_graphify_chunks_parallel(
            file_chunks=file_chunks,
            prompt_template=prompt_template,
            max_workers=2,
        )

        self.assertEqual(len(results), 2)
        # Verify aggregation file was created
        out_path = os.path.join(self.test_dir, "graphify-out", ".graphify_semantic_new.json")
        self.assertTrue(os.path.exists(out_path))
        with open(out_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("nodes", data)
        self.assertIn("edges", data)

    @patch("concurrent.futures.ThreadPoolExecutor")
    def test_graceful_serial_fallback_on_oom_or_exception(self, mock_executor):
        # Simulate ThreadPoolExecutor throwing MemoryError or Resource Exhaustion
        mock_executor.side_effect = MemoryError("Simulated OOM inside Termux")

        file_chunks = [
            {"chunk_num": 1, "content": "file1.py"},
            {"chunk_num": 2, "content": "file2.py"},
        ]
        prompt_template = "Prompt CHUNK_NUM"

        results = self.orchestrator.process_graphify_chunks_parallel(
            file_chunks=file_chunks,
            prompt_template=prompt_template,
            max_workers=3,
        )

        self.assertEqual(len(results), 2)
        # Verify individual chunk files saved during serial path
        chunk1_path = os.path.join(self.test_dir, "graphify-out", ".graphify_chunk_1.json")
        chunk2_path = os.path.join(self.test_dir, "graphify-out", ".graphify_chunk_2.json")
        self.assertTrue(os.path.exists(chunk1_path))
        self.assertTrue(os.path.exists(chunk2_path))

        # Verify final aggregation also occurred after serial path
        agg_path = os.path.join(self.test_dir, "graphify-out", ".graphify_semantic_new.json")
        self.assertTrue(os.path.exists(agg_path))

    def test_extract_json_from_llm(self):
        # Clean JSON
        res = self.orchestrator._extract_json_from_llm('{"nodes": [{"id": "A"}], "edges": []}')
        self.assertEqual(res["nodes"][0]["id"], "A")

        # JSON inside Markdown code block with extra conversational text
        noisy = 'Here is the graph extraction:\n```json\n{"nodes": [{"id": "B"}], "edges": []}\n```\nHope that helps!'
        res2 = self.orchestrator._extract_json_from_llm(noisy)
        self.assertEqual(res2["nodes"][0]["id"], "B")

        # Invalid JSON fallback
        bad = "Sorry I cannot format JSON right now."
        res3 = self.orchestrator._extract_json_from_llm(bad)
        self.assertIn("error", res3)

    def test_pure_code_bypass(self):
        file_chunks = [
            {"chunk_num": 1, "content": "def foo(): pass", "type": "code"},
            {"chunk_num": 2, "content": "# Architecture Doc", "type": "doc"},
        ]
        # Mocking _model or llm_engine to return valid JSON for doc chunk
        self.orchestrator._model = lambda msgs: '{"nodes": [{"id": "DocNode"}], "edges": []}'

        results = self.orchestrator.process_graphify_chunks_parallel(file_chunks=file_chunks, prompt_template="Prompt CHUNK_NUM")
        self.assertEqual(len(results), 2)
        # First chunk (pure code) skipped deep LLM extraction
        self.assertTrue(results[0].get("skipped"))
        self.assertEqual(results[0]["nodes"], [])
        # Second chunk (doc) ran through LLM
        self.assertEqual(results[1]["nodes"][0]["id"], "DocNode")

    def test_extraction_spec_loading(self):
        # Create temporary references/extraction-spec.md inside workspace_dir
        ref_dir = os.path.join(self.test_dir, "references")
        os.makedirs(ref_dir, exist_ok=True)
        spec_path = os.path.join(ref_dir, "extraction-spec.md")
        with open(spec_path, "w", encoding="utf-8") as f:
            f.write("Spec CHUNK_NUM of TOTAL_CHUNKS: FILE_LIST (DEEP_MODE)")

        captured_prompts = []
        def mock_llm(msgs):
            captured_prompts.append(msgs[0]["content"])
            return '{"nodes": [{"id": "SPEC_NODE"}], "edges": []}'

        self.orchestrator._model = mock_llm
        chunks = [{"chunk_num": 5, "content": "Sample doc content", "type": "doc"}]
        results = self.orchestrator.process_graphify_chunks_parallel(file_chunks=chunks, prompt_template="")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["nodes"][0]["id"], "SPEC_NODE")
        self.assertIn("Spec 5 of 1: Sample doc content (true)", captured_prompts[0])


if __name__ == "__main__":
    unittest.main()
