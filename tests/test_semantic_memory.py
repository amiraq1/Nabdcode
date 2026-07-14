"""Automated verification suite for Zero-Trust Semantic Memory Pipeline.

Verifies:
  1. Deterministic pure-Python vector embedding and cosine similarity.
  2. Persistent JSON vector storage and retrieval.
  3. Context stuffing prevention (surgical max_context_chars cap).
  4. Automatic input/output sanitization through core.sanitize.
"""

import math
import pathlib
import shutil
import tempfile
import unittest

from core.memory import PurePythonEmbedder, SemanticMemoryPipeline


class TestPurePythonEmbedder(unittest.TestCase):
    def setUp(self):
        self.embedder = PurePythonEmbedder(dim=128)

    def test_embed_deterministic_and_normalized(self):
        text = "Security hardening zero trust Termux agent"
        vec1 = self.embedder.embed(text)
        vec2 = self.embedder.embed(text)
        self.assertEqual(len(vec1), 128)
        self.assertEqual(vec1, vec2)
        norm = math.sqrt(sum(v * v for v in vec1))
        self.assertAlmostEqual(norm, 1.0, places=5)

    def test_semantic_similarity_ranking(self):
        vec_sec = self.embedder.embed("zero trust security firewalls")
        vec_sim = self.embedder.embed("security zero trust protection")
        vec_diff = self.embedder.embed("cooking pasta kitchen recipe")

        sim_high = PurePythonEmbedder.cosine_similarity(vec_sec, vec_sim)
        sim_low = PurePythonEmbedder.cosine_similarity(vec_sec, vec_diff)
        self.assertGreater(sim_high, sim_low)


class TestSemanticMemoryPipeline(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.store_path = pathlib.Path(self.temp_dir) / "test_memory.json"
        self.pipeline = SemanticMemoryPipeline(
            store_path=str(self.store_path),
            max_records=100,
            max_context_chars=100,
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_add_and_search_memory(self):
        self.pipeline.add_memory(
            "Hardened Python subprocess call with explicit allowlist",
            project="nabd",
            importance=1.5,
        )
        self.pipeline.add_memory(
            "Baking chocolate chip cookies in the oven",
            project="personal",
            importance=1.0,
        )

        results = self.pipeline.search_memory("Python subprocess allowlist", top_k=2)
        self.assertGreaterEqual(len(results), 1)
        self.assertIn("Python subprocess", results[0]["content"])

    def test_context_stuffing_prevention(self):
        # max_context_chars is set to 100
        # Add three memories each ~60 chars long
        self.pipeline.add_memory("Zero trust agent architecture verification step one alpha")
        self.pipeline.add_memory("Zero trust agent architecture verification step two beta")
        self.pipeline.add_memory("Zero trust agent architecture verification step three gamma")

        results = self.pipeline.search_memory("Zero trust agent", top_k=5, min_similarity=0.0)
        total_chars = sum(len(r["content"]) for r in results)
        self.assertLessEqual(total_chars, 100 + 70)  # Should cap before adding more records
        self.assertLess(len(results), 3)

    def test_sanitization_integration(self):
        self.pipeline.add_memory("Secret \x1b[31mRed Alert\x1b[0m \x00Payload")
        results = self.pipeline.search_memory("Secret Red Alert")
        self.assertTrue(results)
        clean_content = results[0]["content"]
        self.assertNotIn("\x1b", clean_content)
        self.assertNotIn("\x00", clean_content)
        self.assertEqual(clean_content, "Secret Red Alert Payload")


if __name__ == "__main__":
    unittest.main()
