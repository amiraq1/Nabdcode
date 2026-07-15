# tests/test_phase_hybrid_retriever.py
from pathlib import Path


def test_memory_store_append_and_load(tmp_path):
    """MemoryStore persists chunks to JSONL"""
    from core.memory_store import MemoryStore
    store = MemoryStore(tmp_path / "mem.jsonl")
    chunk = store.add("test memory", {"type": "note"})
    assert chunk.id.startswith("mem_")
    assert len(store.get_all()) == 1

    # Reload
    store2 = MemoryStore(tmp_path / "mem.jsonl")
    assert len(store2.get_all()) == 1
    assert store2.get_all()[0].text == "test memory"


def test_tfidf_index_basic_search():
    """TfIdfIndex returns relevant results"""
    from core.semantic_index import TfIdfIndex
    from core.memory_store import MemoryChunk

    index = TfIdfIndex()
    chunks = [
        MemoryChunk("1", "python programming language"),
        MemoryChunk("2", "javascript web development"),
        MemoryChunk("3", "python data science"),
    ]
    index.index_chunks(chunks)

    results = index.search("python code", chunks, top_k=2)
    assert len(results) == 2
    assert results[0][0].id == "1"  # python programming should rank highest


def test_hybrid_retriever_semantic_boost(tmp_path):
    """Hybrid search combines semantic + keyword"""
    from core.hybrid_retriever import HybridRetriever
    from core.memory_store import MemoryStore

    store = MemoryStore(tmp_path / "mem.jsonl")
    store.add("python async programming tutorial")
    store.add("java spring boot guide")
    store.add("python data analysis with pandas")

    retriever = HybridRetriever(store)
    results = retriever.search("python async", top_k=2)

    assert len(results) >= 1
    assert results[0]["score"] > 0.1


def test_hybrid_time_decay(tmp_path):
    """Recent memories rank higher than old ones"""
    from core.hybrid_retriever import HybridRetriever
    from core.memory_store import MemoryStore
    from unittest.mock import patch
    from datetime import datetime

    store = MemoryStore(tmp_path / "mem.jsonl")
    old_chunk = store.add("old python note")
    new_chunk = store.add("new python note")

    # Mock timestamps
    with patch("core.hybrid_retriever.datetime") as mock_dt:
        mock_dt.utcnow.return_value = datetime(2025, 1, 2)
        mock_dt.fromisoformat.side_effect = lambda x: datetime.fromisoformat(x)
        retriever = HybridRetriever(store)
        results = retriever.search("python", top_k=2)

    # Newer should score higher
    assert results[0]["id"] == new_chunk.id


def test_search_memory_tool_interface(tmp_path):
    """SearchMemoryTool returns correct schema"""
    from tools.search_memory import SearchMemoryTool

    tool = SearchMemoryTool(tmp_path / "test_mem")
    result = tool("python", top_k=3)
    assert "tool" in result
    assert result["tool"] == "search_memory"
    assert "results" in result
    assert isinstance(result["results"], list)


def test_search_memory_empty_store(tmp_path):
    """Empty store returns empty results"""
    from tools.search_memory import SearchMemoryTool

    tool = SearchMemoryTool(tmp_path / "empty_mem")
    result = tool("anything")
    assert result["results"] == []
    assert result["total_chunks"] == 0


def test_hybrid_add_memory_updates_index(tmp_path):
    """Adding new memory updates retriever index"""
    from core.hybrid_retriever import HybridRetriever
    from core.memory_store import MemoryStore

    store = MemoryStore(tmp_path / "mem2.jsonl")
    retriever = HybridRetriever(store)

    retriever.add_memory("new test memory", {"source": "test"})
    results = retriever.search("test memory", top_k=1)
    assert len(results) == 1
    assert results[0]["text"] == "new test memory"
